# Copyright 2016 Brocade Communications System, Inc.
# All rights reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
#
# Shiv Haris (shivharis@hotmail.com)


"""Implentation of Brocade ML2 Mechanism driver for ML2 Plugin."""

from networking_brocade._i18n import _
from networking_brocade._i18n import _LE
from networking_brocade._i18n import _LI
from networking_brocade.vdx.bare_metal import util as baremetal_util
from networking_brocade.vdx.db import models as brocade_db
from networking_brocade.vdx.non_ampp.ml2driver.nos import nosdriver as driver
from networking_brocade.vdx.non_ampp.ml2driver import utils
from neutron.common import constants as n_const
from neutron_lib import context as neutron_context
from neutron.extensions import portbindings
from neutron.plugins.common import constants as p_const
from neutron.plugins.ml2 import driver_api as api
import sys
try:
    from oslo_log import log as logging
except ImportError:
    from neutron.openstack.common import log as logging

from threading import Thread

LOG = logging.getLogger(__name__)
MECHANISM_VERSION = 1.0


class BrocadeMechanismCustom(api.MechanismDriver):

    """ML2 Mechanism driver for Brocade VDX switches. This is the upper
    Layer driver class that interfaces to lower layer (NETCONF) below.
    """

    def __init__(self):
        self._drivers = {}
        self.switches = []
        self._physical_networks = None
        #self._switch = None
        self._device_dict = {}
        self._bond_mappings = {}
        self._lacp_ports = {}
        self.initialize()
        self._username = None
        self._password = None
        self.additional_export_vrf = None

    def initialize(self):
        """Initilize of variables needed by this class."""
        self.brocade_init()

    def brocade_init(self):
        """Brocade specific initialization for this class."""
        utils.register_brocade_credentials()
        self._username, self._password = utils.get_user_pw()
        self._fqdn_supported = utils.is_fqdn_supported()
        self.initialize_vcs = utils.get_vcs_initialize()
        self.initialize_vcs = False
        self._physical_networks = utils.get_physical_networks()
        self.additional_export_vrf = utils.get_additional_export_vrf()
        self.switches = utils.get_switches()
        for switch_name, switch_config in self.switches.iteritems():
            LOG.debug('Opening connection to %s' % switch_config['address'])
            self._drivers[switch_name] = driver.NOSdriver(
                                            switch_config['address'],
                                            self._username,
                                            self._password)

        if False and self.initialize_vcs:
            self.configure_vcs()
        for switch_name, _driver in self._drivers.iteritems():
            LOG.debug('CLosing connection to %s' % switch_config['address'])
            _driver.close_session()

    def configure_vcs(self):
        # configure vcs interfaces based on topology
        if not utils._is_valid_interface(self._device_dict,
                                         self._switch, self._driver):
            sys.exit(0)

        LOG.debug("device dictionary %s", self._device_dict)

        try:
            if utils._is_lacp_enabled():
                LOG.debug("LACP enabled")
                (self._device_dict, self._lacp_ports) =\
                    utils._aggregate_nics_to_support_lacp(self._device_dict,
                                                          self._bond_mappings)
            self._driver.configure_l2_and_trunk_mode_for_interface(
                self._device_dict, self._lacp_ports,
                self._mtu, self._native_vlans)
        except Exception:
            LOG.exception(
                _LE("Brocade Mechanism: failed to put"
                    " interface l2 or tr mode"))
            raise Exception(
                _("Brocade Mechanism: failed to put interface l2 or tr mode"))

    def is_flat_network(self, segment):
        if not segment or segment['network_type'] == p_const.TYPE_FLAT:
            LOG.info(_LI("Flat network nothing to be done"))
            return True
        return False

    def create_network_precommit(self, mech_context):
        LOG.debug("create_network_precommit: called")

        """Create Network in the mechanism specific database table."""
        if self.is_flat_network(mech_context.network_segments[0]):
            return

        network = mech_context.current
        context = mech_context._plugin_context
        project_id = network['project_id']
        network_id = network['id']

        segments = mech_context.network_segments
        # currently supports only one segment per network
        segment = segments[0]

        network_type = segment['network_type']
        vlan_id = segment['segmentation_id']
        segment_id = segment['id']

        if network_type not in [p_const.TYPE_VLAN]:
            raise Exception(
                _("Brocade Mechanism: failed to create network, "
                  "only network type vlan is supported"))

        try:
            brocade_db.create_network(context, network_id, vlan_id,
                                      segment_id, network_type, project_id)
        except Exception:
            LOG.exception(
                _LE("Brocade Mechanism: failed to create network in db"))
            raise Exception(
                _("Brocade Mechanism: create_network_precommit failed"))

    def _vrf_name(self, vlan_id):
        return "os-vrf-%s" % vlan_id

    def configure_network_on_switch(self, switch_name, vlan_id, vrf_name, rd, results, result_key):
        try:
            result_text = []
            rbridge_results = [ True, True ]
            results[result_key]['status'] = False
            results[result_key]['text'] = ""
            driver = self._drivers[switch_name]
            for rbridge_id in [1,2]:
                try:
                    driver.create_vrf(rbridge_id, vrf_name)
                    driver.configure_rd_for_vrf(rbridge_id, vrf_name, rd)
                    driver.configure_vni_for_vrf(rbridge_id, vrf_name, vlan_id)
                    driver.add_address_family_import_targets_for_vrf(rbridge_id, vrf_name, vlan_id)
                    driver.add_address_family_export_targets_for_vrf(rbridge_id, vrf_name, vlan_id)
                    if self.additional_export_vrf:
                        driver.add_address_family_import_targets_for_vrf(
                            rbridge_id,vrf_name,self.additional_export_vrf)
                        driver.add_address_family_export_targets_for_vrf(
                            rbridge_id,vrf_name,self.additional_export_vrf)
                except Exception as e:
                    rbridge_results[rbridge_id] = False
                    result_text.append("error configuring vrf: %s switch: %s rbridge_id: %s rd: %s vlan_id: %s error: %s" %
                                       (vrf_name, switch_name, rbridge_id, rd, vlan_id, e))
                try:
                    driver.create_vlan_interface(vlan_id)
                    driver.configure_svi(rbridge_id, vlan_id)
                    driver.bind_vrf_to_svi(rbridge_id, vlan_id, vrf_name)
                    driver.activate_svi(rbridge_id, vlan_id)
                    driver.add_vrf_to_svi(rbridge_id, vlan_id, vrf_name)
                    driver.add_arp_learn_any_to_vlan_interface(rbridge_id, vlan_id)
                    driver.set_arp_aging_timeout_for_vlan_interface(rbridge_id, vlan_id, 4)
                except Exception as e:
                    rbridge_results[rbridge_id] = False
                    result_text.append("error configuring vni: %s switch: %s rbridge_id: %s error: %s" %
                                       (vlan_id, switch_name, rbridge_id, e))
                for port in self.switches[switch_name].port:
                    try:
                        port_speed = port.split(':')[1]
                        port_name = port.split(':')[2]
                        driver.add_or_remove_vlan_from_interface(
                            "add", port_speed, port_name, vlan_id)
                    except Exception as e:
                        rbridge_results[0] = False
                        rbridge_results[1] = False
                        result_text.append("error adding tag: s switch: %s port_name: %s error: %s" %
                                           (vlan_id, switch_name, port_name, e))
                results[result_key]['text'] = "; ".join(result_text)
                results[result_key]['status'] = True in rbridge_results
        except Exception as e:
            results[result_key]['status'] = False
            results[result_key]['text'] = "Error configuring network switch: %s vrf: %s vlan_id: %s : %s" % (switch_name, vrf_name, vlan_id, e)
            


    def create_network_postcommit(self, mech_context):
        """Create Network on the switch."""

        LOG.debug("create_network_postcommit: called")
        LOG.debug("context: %s" % mech_context)
        LOG.debug("network: %s" % mech_context.current)
        if self.is_flat_network(mech_context.network_segments[0]):
            return

        network = mech_context.current
        subnets = network['subnets']
        LOG.debug("subnets: %s" % subnets)


        context = mech_context._plugin_context
        network_id = network['id']
        network = brocade_db.get_network(context, network_id)
        vlan_id = network['vlan']
        segments = mech_context.network_segments
        # currently supports only one segment per network
        segment = segments[0]
        physical_network = segment['physical_network']
        vrf_name = self._vrf_name(vlan_id)
        LOG.debug("vrf_name: %s" % vrf_name)
        try:
            threads = []
            results = dict((k,{'status': False, 'text': ''}) for k in self._drivers.keys())
            for switch_name, _driver in self._drivers.iteritems():
                rd = "%s:%s" % (self.switches[switch_name]['address'], vlan_id)
                LOG.debug("creating vrf: %s switch: %s(%s) rd: %s results: %s" %
                      (vrf_name, switch_name,
                       self.switches[switch_name]['address'],
                       rd,
                       results))
                thread = Thread(target=self.configure_network_on_switch, args=[switch_name, vlan_id, vrf_name, rd, results, switch_name])
                thread.start()
                threads.append(thread)
            for thread in threads:
                thread.join()
            result = not False in [result[1]['status'] for result in results.items()]
            result_text = "; ".join(["%s: %s" % 
                            (s, results[s]['text']) for s in results.keys()])
            if not result:
                error_switches = [ s for s in self.switches.keys() if not results[s]['status'] ]
                raise Exception("Error deleting network: %s" % result_text)
            LOG.info("created network, returned text: %s", result_text)
        except Exception:
            LOG.exception(_LE("Brocade NOS driver: failed in create network"))
            brocade_db.delete_network(context, network_id)
            raise Exception(
                _("Brocade Mechanism: create_network_postcommmit failed"))

    def deconfigure_network_on_switch(self, switch_name, vrf_name, vlan_id, results, result_key):
        try:
            result_text = []
            rbridge_results = [ True, True ]
            results[result_key]['status'] = False
            results[result_key]['text'] = ""
            for rbridge_id in [1, 2]:
                try:
                    self._drivers[switch_name].delete_vrf(rbridge_id, vrf_name)
                except Exception as e:
                    result_text.append("Error deleting vrf: %s switch %s rbridge_id: %s" %
                                       (vrf_name, switch_name, rbridge_id))
                    rbridge_results[rbridge_id-1] = False
                try:
                    self._drivers[switch_name].remove_svi(rbridge_id, vlan_id)
                except Exception as e:
                    result_text.append("Error deleting svi: %s switch %s rbridge_id: %s" %
                                       (vlan_id, switch_name, rbridge_id))
                    rbridge_results[rbridge_id-1] = False
            results[result_key]['text'] = "; ".join(result_text)
            results[result_key]['status'] = True in rbridge_results
        except Exception as e:
            results[result_key]['status'] = False
            results[result_key]['text'] = "Error deconfiguring network switch: %s vrf: %s vlan_id: %s : %s" % (switch_name, vrf_name, vlan_id, e)
        

    def delete_network_precommit(self, mech_context):
        """Delete Network from the plugin specific database table."""
        LOG.debug("delete_network_precommit: called")

        network = mech_context.current
        network_id = network['id']
        brocade_network = brocade_db.get_network(mech_context._plugin_context, network_id)
        vlan_id = brocade_network['vlan']
        vrf_name = self._vrf_name(vlan_id)
        try:
            threads = []
            results = dict((k,{}) for k in self._drivers.keys())
            
            for switch_name, driver in self._drivers.iteritems():
                thread = Thread(target=self.deconfigure_network_on_switch,
                                args=[switch_name, vrf_name, vlan_id, results, switch_name])
                thread.start()
                threads.append(thread)
            for thread in threads:
                thread.join()
            result = not False in [result[1]['status'] for result in results.items()]
            result_text = "; ".join(["%s: %s" % 
                            (s, results[s]['text']) for s in results.keys()])
            if not result:
                error_switches = [ s for s in self.switches.keys() if not results[s]['status'] ]
                raise Exception("Error deleting network: %s" % result_text)
            LOG.info("deleted network, returned text: %s", result_text)
            brocade_db.delete_network(mech_context._plugin_context, network_id)
            
        except Exception:
            LOG.exception(
                _LE("Brocade Mechanism: failed to delete network"))
            raise Exception(
                _("Brocade Mechanism: delete_network_precommit failed"))

    def delete_network_postcommit(self, mech_context):
        return
        """Delete network
        from the switch.
        """
        LOG.debug("delete_network_postcommit: called")
        network = mech_context.current
        network_id = network['id']
        vlan_id = network['provider:segmentation_id']
        vrf_name = self._vrf_name(vlan_id)
        try:
            for switch_name, _driver in self._drivers.iteritems():
                LOG.debug("deleting vrf %s on switch %s (%s)" %
                          (vrf_name, switch_name, self.switches[switch_name]['address']))
                for rbridge_id in [1,2]:
                    LOG.debug('rbridge_id: %s' % rbridge_id)
                    LOG.debug('vrf_name: %s' % vrf_name)
                    LOG.debug('vlan_id: %s' % vlan_id)
                    LOG.debug('vlan_id: %s' % vlan_id)
                    _driver.delete_vrf(rbridge_id, vrf_name)
                    _driver.remove_svi(rbridge_id, vlan_id)
                LOG.debug("deleted vrf %s on switch %s" %
                      (vrf_name, switch_name))
        except Exception:
            LOG.exception(_LE("Brocade NOS driver: failed to delete network"))
            raise Exception(
                _("Brocade switch exception, "
                  "delete_network_postcommit failed"))

    def update_network_precommit(self, mech_context):
        """Noop now, it is left here for future."""

    def update_network_postcommit(self, mech_context):
        """Noop now, it is left here for future."""

    def create_port_precommit(self, mech_context):
        return
        """Create logical port on the switch (db update)."""
        LOG.debug("create_port_precommit: called")
        if self.is_flat_network(mech_context.network.network_segments[0]):
            return

        port = mech_context.current
        if not self._is_compute_or_dhcp_port(port, mech_context):
            return
        if baremetal_util.is_baremetal_deploy(port):
            LOG.debug("create_port_precommit: baremetal deploy")
            return
        context = neutron_context.get_admin_context()
        self._create_brocade_port(
            context, port, mech_context.top_bound_segment)

    def create_port_postcommit(self, mech_context):
        return
        """Associate the port to the network."""
        LOG.debug("create_port_postcommit(self: called")
        if self.is_flat_network(mech_context.network.network_segments[0]):
            return

        port = mech_context.current
        if not self._is_compute_or_dhcp_port(port, mech_context):
            return
        context = mech_context._plugin_context
        self._create_nos_port(context, port, mech_context.top_bound_segment)

    def delete_port_precommit(self, mech_context):
        return
        """Delete logical port on the switch (db update)."""

        LOG.debug("delete_port_precommit: called")
        if self.is_flat_network(mech_context.network.network_segments[0]):
            return

        port = mech_context.current
        if not self._is_compute_or_dhcp_port(port, mech_context):
            return

        context = mech_context._plugin_context
        self._delete_brocade_port(context, port)

    def delete_port_postcommit(self, mech_context):
        return
        """Dissociate port from the network."""
        LOG.debug("delete_port_postcommit(self: called")
        if self.is_flat_network(mech_context.network.network_segments[0]):
            return

        port = mech_context.current
        if not self._is_compute_or_dhcp_port(port, mech_context):
            return

        context = mech_context._plugin_context
        self._delete_nos_port(context, port, mech_context.top_bound_segment)

    def update_port_precommit(self, mech_context):
        return
        """updates brocade db if vm is migrating"""
        if self.is_flat_network(mech_context.network.network_segments[0]):
            return

        context = mech_context._plugin_context
        port = mech_context.current
        LOG.debug("update_port_precommit(self: called")
        if not self._is_compute_or_dhcp_port(port, mech_context):
            return

        if self._is_vm_migration(mech_context):
            # PortContext.current['binding:host_id']: current (new) value
            port = mech_context.original
            LOG.debug("update_port_precommit: VM is migrating to"
                      "new host %s(case 1) port['status'] %s",
                      port[portbindings.HOST_ID], port['status'])
            self._delete_brocade_port(context, port)
        else:
            # PortContext.current['binding:host_id']: previous value
            if mech_context.top_bound_segment and\
                    port['status'] == n_const.PORT_STATUS_BUILD:
                LOG.debug("update_port_pretcommit: VM is migrating to"
                          "new host %s(case 2)", port[portbindings.HOST_ID])
                self._create_brocade_port(context, port,
                                          mech_context.top_bound_segment)

    def update_port_postcommit(self, mech_context):
        return
        """updates brocade nos if vm is migrating"""
        if self.is_flat_network(mech_context.network.network_segments[0]):
            return

        port = mech_context.current
        context = mech_context._plugin_context
        LOG.debug("update_port_postcommit: called")
        if not self._is_compute_or_dhcp_port(port, mech_context):
            return

        if self._is_vm_migration(mech_context):
            # add new entry to switch
            # PortContext.current['binding:host_id']: current (new) value
            port = mech_context.original
            LOG.debug("update_port_precommit: VM is migrating to"
                      "new host %s(case 1) port['status'] %s",
                      port[portbindings.HOST_ID], port['status'])
            self._delete_nos_port(context, port,
                                  mech_context.original_bound_segment)
        else:
            # remove previouse port binings
            # PortContext.current['binding:host_id']: previous value
            if mech_context.top_bound_segment and\
                    port['status'] == n_const.PORT_STATUS_BUILD:
                LOG.debug("update_port_postcommit: VM is migrating to"
                          "new host %s(case 2)", port[portbindings.HOST_ID])
                self._create_nos_port(context, port,
                                      mech_context.top_bound_segment)

    def create_subnet_precommit(self, mech_context):
        """Noop now, it is left here for future."""
        LOG.debug("create_subnetwork_precommit: called")

    def create_subnet_postcommit(self, mech_context):
        """Noop now, it is left here for future."""
        subnet = mech_context.current
        vlan_id = brocade_db.get_network(mech_context._plugin_context,
                                         subnet['network_id'])['vlan']
        vrf_name = self._vrf_name(vlan_id)
        gateway_ip = subnet['gateway_ip']
        gateway_subnet = subnet['cidr'].split('/')[1]
        gateway_address= "%s/%s" % (gateway_ip, gateway_subnet)
        try:
            for switch_name, _driver in self._drivers.iteritems():
                LOG.debug("deleting vrf %s on switch %s (%s)" %
                          (vrf_name, switch_name, self.switches[switch_name]['address']))
                for rbridge_id in [1,2]:
                    _driver.configure_svi_with_ip_address_anycast(rbridge_id, vlan_id, gateway_address)
        except Exception:
            LOG.exception(_LE("Brocade NOS driver: failed to create subnet"))
            raise Exception(
                _("Brocade switch exception, "
                  "delete_network_postcommit failed"))

        LOG.debug("create_subnetwork_postcommit: called")

    def delete_subnet_precommit(self, mech_context):
        """Noop now, it is left here for future."""
        LOG.debug("delete_subnetwork_precommit: called")

    def delete_subnet_postcommit(self, mech_context):
        """Noop now, it is left here for future."""
        LOG.debug("delete_subnetwork_postcommit: called")

    def update_subnet_precommit(self, mech_context):
        """Noop now, it is left here for future."""
        LOG.debug("update_subnet_precommit(self: called")

    def update_subnet_postcommit(self, mech_context):
        """Noop now, it is left here for future."""
        LOG.debug("update_subnet_postcommit: called")

    def _is_vm_migration(self, context):
        LOG.debug("_is_vm_migration called")
        return (context.current.get(portbindings.HOST_ID) !=
                context.original.get(portbindings.HOST_ID))

    def _is_compute_or_dhcp_port(self, port, context):
        if (("compute" not in port['device_owner']) and
                ("dhcp" not in port['device_owner'])):
            # Not a compute port or dhcp , return
            return False
        if not baremetal_util.is_baremetal_deploy(port):
            return True
        if not self._is_profile_bound_to_port(port, context):
            # it is baremetal port
            return False
        return True

    def _is_profile_bound_to_port(self, port, context):
        profile = context.current.get(portbindings.PROFILE, {})
        if not profile:
            LOG.debug("Missing profile in port binding")
            return False
        return True

    def _is_dhcp_port(self, port):
        if("dhcp" in port['device_owner']):
            # dhcp port, return
            return True
        return False

    def _get_vlanid(self, segment):
        if (segment and segment[api.NETWORK_TYPE] == p_const.TYPE_VLAN):
            return segment.get(api.SEGMENTATION_ID)

    def _get_physical_interface(self, segment):
        if (segment and segment[api.NETWORK_TYPE] == p_const.TYPE_VLAN):
            return segment.get(api.PHYSICAL_NETWORK)

    def _get_hostname(self, port):
        host = port[portbindings.HOST_ID]
        LOG.debug("_get_hostname host %s", host)
        return host if self._fqdn_supported else host.split('.')[0]

    def _get_port_info(self, port, segment):
        "get vlan id and physical networkkfrom bound segment"
        if port and segment:
            vlan_id = self._get_vlanid(segment)
            hostname = self._get_hostname(port)
            physical_interface = self._get_physical_interface(segment)
            LOG.debug("_get_port_info: hostname %s, vlan_id %s,"
                      " physical_interface %s", hostname, str(vlan_id),
                      physical_interface)
            return hostname, vlan_id, physical_interface
        return None, None, None

    def _create_brocade_port(self, context, port, segment):
        port_id = port['id']
        network_id = port['network_id']
        project_id = port['project_id']
        admin_state_up = port['admin_state_up']
        hostname, vlan_id, physical_network = self._get_port_info(
            port, segment)
        try:
            brocade_db.create_port(context, port_id, network_id,
                                   physical_network, vlan_id, tenant_id,
                                   admin_state_up, hostname)
        except Exception:
            LOG.exception(_LE("Brocade Mechanism: "
                              "failed to create port in db"))
            raise Exception(
                _("Brocade Mechanism: create_port_precommit failed"))

    def _create_nos_port(self, context, port, segment):
        hostname, vlan_id, physical_network = self._get_port_info(
            port, segment)
        if not hostname or not vlan_id:
            LOG.info(_LI("hostname or vlan id is empty"))
            return
        for (speed, name) in self._device_dict[(hostname, physical_network)]:
            LOG.debug("_create_nos_port:port %s %s vlan %s",
                      speed, name, str(vlan_id))
            try:
                if not brocade_db.is_vm_exists_on_host(context,
                                                       hostname,
                                                       physical_network,
                                                       vlan_id):
                    self._driver.add_or_remove_vlan_from_interface(
                        "add", speed, name, vlan_id)
                else:
                    LOG.debug("_create_nos_port:port is already trunked")
            except Exception:
                self._delete_brocade_port(context, port)
                LOG.exception(_LE("Brocade NOS driver:failed to trunk vlan"))
                raise Exception(_("Brocade switch exception:"
                                  " create_port_postcommit failed"))

    def _delete_brocade_port(self, context, port):
        try:
            port_id = port['id']
            brocade_db.delete_port(context, port_id)
        except Exception:
            LOG.exception(_LE("Brocade Mechanism:"
                              " failed to delete port in db"))
            raise Exception(
                _("Brocade Mechanism: delete_port_precommit failed"))

    def _delete_nos_port(self, context, port, segment):

        hostname, vlan_id, physical_network =\
            self._get_port_info(port, segment)
        if not hostname or not vlan_id:
            LOG.info(_LI("hostname or vlan id is empty"))
            return
        for (speed, name) in self._device_dict[(hostname, physical_network)]:
            try:
                if brocade_db.is_last_vm_on_host(context,
                                                 hostname,
                                                 physical_network, vlan_id)\
                        and not self._is_dhcp_port(port):

                    self._driver.add_or_remove_vlan_from_interface("remove",
                                                                   speed,
                                                                   name,
                                                                   vlan_id)
                else:
                    LOG.info(_LI("more vm exist for network on host hence vlan"
                               " is not removed from port"))
            except Exception:
                LOG.exception(
                    _LE("Brocade NOS driver: failed to remove vlan from port"))
                raise Exception(
                    _("Brocade switch exception: delete_port_postcommit"
                      "failed"))
