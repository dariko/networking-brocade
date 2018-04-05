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
from networking_brocade.vdx.non_ampp.ml2driver.nos.nosfabricdriver import NOSFabricDriver
from networking_brocade.vdx.non_ampp.ml2driver import utils
from neutron.common import constants as n_const
from neutron_lib import context as neutron_context
from neutron.extensions import portbindings
from neutron.plugins.common import constants as p_const
from neutron.plugins.ml2 import driver_api as api
from neutron.objects import subnet as subnet_obj
from neutron.objects import network as network_obj
from neutron.db import models_v2
from neutron.db.models import segment as segment_models
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
        self.switches = utils.get_switches()
        self.username, self.password = utils.get_user_pw()

        ml2_options = utils.get_brocade_ml2_conf()
        self.external_vrf_name = ml2_options.external_vrf_name
        self.external_vrf_vni = ml2_options.external_vrf_vni
        self.internal_vrf_name = ml2_options.internal_vrf_name
        self.internal_vrf_vni = ml2_options.internal_vrf_vni
        self.tenants_acl_name = ml2_options.tenants_acl_name

        
        self.fabric_driver = NOSFabricDriver(ml2_options, self.switches)
        #self.fabric_driver.init_global_vrfs()

    def initialize(self):
        pass
        #self.fabric_driver.init_global_vrfs()
        
    def is_flat_network(self, segment):
        if not segment or segment['network_type'] == p_const.TYPE_FLAT:
            LOG.info(_LI("Flat network nothing to be done"))
            return True
        return False

    def create_network_precommit(self, mech_context):
        LOG.debug("create_network_precommit: called")
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

    def create_network_postcommit(self, context):
        #return
        LOG.debug("create_network_postcommit: called")
        LOG.debug("context: %s" % context)
        network = context.current
        LOG.debug("network: %s" % context.current)
        network_id = network['id']
        provider_type = network['provider:network_type']
        segmentation_id = network['provider:segmentation_id']
        physnet = network['provider:physical_network']
        
        try:
            vrf_name = self.internal_vrf_name
            if '-pub-' in network['name']:
                vrf_name = self.external_vrf_name
            self.fabric_driver.create_network(segmentation_id, vrf_name, 'PBR')
        except Exception as ex:
            LOG.exception("Error in create_network_postcommit")
            raise ex
        return True

    #def deconfigure_network_on_switch(self, switch_name, vrf_name, vlan_id, results, result_key):
        #try:
            #result_text = []
            #rbridge_results = [ True, True ]
            #results[result_key]['status'] = False
            #results[result_key]['text'] = ""
            #for rbridge_id in [1, 2]:
                #try:
                    #self._drivers[switch_name].delete_vrf(rbridge_id, vrf_name)
                #except Exception as e:
                    #result_text.append("Error deleting vrf: %s switch %s rbridge_id: %s" %
                                       #(vrf_name, switch_name, rbridge_id))
                    #rbridge_results[rbridge_id-1] = False
                #try:
                    #self._drivers[switch_name].remove_svi(rbridge_id, vlan_id)
                #except Exception as e:
                    #result_text.append("Error deleting svi: %s switch %s rbridge_id: %s" %
                                       #(vlan_id, switch_name, rbridge_id))
                    #rbridge_results[rbridge_id-1] = False
            #results[result_key]['text'] = "; ".join(result_text)
            #results[result_key]['status'] = True in rbridge_results
        #except Exception as e:
            #results[result_key]['status'] = False
            #results[result_key]['text'] = "Error deconfiguring network switch: %s vrf: %s vlan_id: %s : %s" % (switch_name, vrf_name, vlan_id, e)
        #return True
        

    def delete_network_precommit(self, context):
        network = context.current
        provider_type = network['provider:network_type']
        brocade_network = brocade_db.get_network(context._plugin_context, network['id'])
        segmentation_id = brocade_network.vlan
        vrf_name = self.internal_vrf_name
        if '-pub-' in network['name']:
            vrf_name = self.external_vrf_name
        try:
            self.fabric_driver.delete_network(segmentation_id)
            brocade_db.delete_network(context._plugin_context, network['id'])
        except Exception as ex:
            LOG.exception("Error in create_network_postcommit.")
            raise ex
        return True

    def delete_network_postcommit(self, context):
        return

    def update_network_precommit(self, mech_context):
        """Noop now, it is left here for future."""

    def update_network_postcommit(self, mech_context):
        """Noop now, it is left here for future."""

    def create_port_precommit(self, mech_context):
        return
        
    def create_port_postcommit(self, mech_context):
        return
        
    def delete_port_precommit(self, mech_context):
        return
        
    def delete_port_postcommit(self, mech_context):
        return
        
    def update_port_precommit(self, mech_context):
        return
        
    def update_port_postcommit(self, mech_context):
        return

    def get_project_access_list_seqs(self, project_id):
        import neutron.db.api as db
        session = db.get_reader_session()
        project_subnets = []
        project_networks = []
        subnet_model = models_v2.Subnet
        network_model = models_v2.Network
        segment_model = segment_models.NetworkSegment
        with session.begin():
            project_subnets = (session.query(subnet_model)
                .filter(subnet_model.project_id == project_id)).all()
            project_networks = (session.query(network_model)
                .filter(network_model.project_id == project_id)).all()
            #project_networks = (session.query(network_model,segment_model)
                #.filter(network_model.project_id == project_id)
                #.join(segment_model)
                #.filter(network_model.id == segment_model.network_id)
                #).all()
        required_seqs = []
        for src_net in project_networks:
            for dst_net in project_networks:
                if src_net['id']==dst_net['id']:
                    continue
                
                if len(src_net.segments) == 0:
                    LOG.info('No segments found for network %s. '
                             'This is normal if the network '
                             'is being deleted' % src_net.id)
                    continue
                src_seg_id = src_net.segments[0].segmentation_id
                if len(dst_net.segments) == 0:
                    LOG.info('No segments found for network %s. '
                             'This is normal if the network '
                             'is being deleted' % dst_net.id)
                    continue
                dst_seg_id = dst_net.segments[0].segmentation_id
                
                src_subnets = [ s for s in project_subnets if str(s.network_id) == str(src_net.id)]
                if len(src_subnets) == 0:
                    LOG.warn('No subnet found for src network %s. '
                             'This is normal if the subnet '
                             'is being deleted' % src_net.id)
                    continue
                src_subnet = src_subnets[0]
                
                dst_subnets = [ s for s in project_subnets if str(s.network_id) == str(dst_net.id)]
                if len(dst_subnets) == 0:
                    LOG.warn('No subnet found for src network %s. '
                             'This is normal if the subnet '
                             'is being deleted' % dst_net.id)
                    continue
                dst_subnet = dst_subnets[0]
                
                data = {}
                data['id'] = '1%04d%04d' % (src_seg_id,
                                             dst_seg_id)
                dst_cidr = str(dst_subnet.cidr)
                data['dst_cidr'] = dst_cidr
                data['dst_address'] = dst_cidr.split('/')[0]
                data['dst_wildcard_mask'] = '.'.join([str(255 - (0xffffffff << (32 - int(dst_cidr.split('/')[1])) >> i) & 0xff)
                                               for i in [24, 16, 8, 0]])
                data['src_vlan'] = src_seg_id
                required_seqs.append(data)
        #LOG.debug('UU: %s' % required_seqs)
        return required_seqs
    
    def create_subnet_precommit(self, mech_context):
        LOG.debug("create_subnetwork_precommit: called")
        network = mech_context.network._network
        network_subnets = subnet_obj.Subnet.get_objects(mech_context._plugin_context,
                                                        network_id=network['id'])
        if len(network_subnets) > 1:
            raise Exception('Too many subnets')
    
    def create_subnet_postcommit(self, mech_context):
        """Noop now, it is left here for future."""
        LOG.debug("create_subnet_postcommit: called")
        network = mech_context.network._network
        subnet = mech_context.current
        vlan_id = brocade_db.get_network(mech_context._plugin_context,
                                         subnet['network_id'])['vlan']

        required_seqs = self.get_project_access_list_seqs(subnet['project_id'])
        LOG.debug('refreshing acl, required_seqs: %s' % required_seqs)
        ret = self.fabric_driver.refresh_acl(self.tenants_acl_name, required_seqs)
        LOG.debug('refreshed acls, returned: %s' % ret)
        
        gateway_ip = subnet['gateway_ip']
        gateway_subnet = str(subnet['cidr']).split('/')[1]
        gateway_address= "%s/%s" % (gateway_ip, gateway_subnet)
        try:
            network_name = network['name']
            vrf_name = self.internal_vrf_name
            if '-pub-' in network_name:
                vrf_name = self.external_vrf_name
            self.fabric_driver.create_subnet(vlan_id, gateway_address)
        except Exception as ex:
            LOG.exception('Error creating subnet: %s' % repr(ex))
            raise ex

    def delete_subnet_precommit(self, mech_context):
        return

    def delete_subnet_postcommit(self, mech_context):
        LOG.debug("delete_subnet_precommit: called")
        subnet = mech_context.current
        vlan_id = brocade_db.get_network(mech_context._plugin_context,
                                         subnet['network_id'])['vlan']
        
        required_seqs = self.get_project_access_list_seqs(subnet['project_id'])
        LOG.debug('refreshing acl, required_seqs: %s' % required_seqs)
        ret = self.fabric_driver.refresh_acl(self.tenants_acl_name, required_seqs)
        LOG.debug('refreshed acls, returned: %s' % ret)
        
        gateway_ip = subnet['gateway_ip']
        gateway_subnet = subnet['cidr'].split('/')[1]
        gateway_address= "%s/%s" % (gateway_ip, gateway_subnet)
        gateway_address= "%s/%s" % (gateway_ip, gateway_subnet)
        try:
            self.fabric_driver.delete_subnet(vlan_id, gateway_address)
        except Exception:
            LOG.exception('Error deleting subnet: %s' % repr(ex))
            raise ex

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
