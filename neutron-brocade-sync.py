#!/usr/bin/env python

from networking_brocade.vdx.ml2driver.nos.nosdriver import NOSdriver
from networking_brocade.vdx.ml2driver.nos import nctemplates as template
from ncclient.operations.rpc import RPCError

from os_client_config import OpenStackConfig
from os import environ as os_environ
from keystoneauth1 import session as keystoneauth1_session
from keystoneclient import v3 as keystoneclient_v3
from neutronclient.v2_0 import client as neutronclient_v2_0
#from oslo_log import log as logging
import logging
import re

LOG = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

leaves = [
        #{'vip': '10.70.144.72', 'rbridges': [{'address': '10.70.144.70', 'rid': 1},{'address': '10.70.144.71', 'rid': 2}]},
        {'vip': '10.70.144.72', 'rbridges': [{'address': '10.70.144.70', 'rid': 1}]},
        {'vip': '10.70.144.75', 'rbridges': [{'address': '10.70.144.73', 'rid': 1},{'address': '10.70.144.74', 'rid': 2}]},
        {'vip': '10.70.144.78', 'rbridges': [{'address': '10.70.144.76', 'rid': 1},{'address': '10.70.144.77', 'rid': 2}]},
        {'vip': '10.70.144.81', 'rbridges': [{'address': '10.70.144.79', 'rid': 1},{'address': '10.70.144.80', 'rid': 2}]},
        #{'vip': '10.70.144.84', 'rbridges': [{'address': '10.70.144.82', 'rid': 1},{'address': '10.70.144.83', 'rid': 2}]},
        {'vip': '10.70.144.84', 'rbridges': [{'address': '10.70.144.82', 'rid': 1}]},
    ]

leaves_username='admin'
leaves_password='!$c0rf@n0ne!'

esx_lldp_regexp='p2esx'

serviceout_vni = 7301
vni_vlan_id_delta = 1000000
arp_aging_timeout = 4


def get_openstack_info():    
    cloud_config = OpenStackConfig().get_one_cloud(cloud=os_environ.get('OS_CLOUD'))

    keystone_session = keystoneauth1_session.Session(auth=cloud_config.get_auth(),
                                       verify=cloud_config.verify)

    keystone = keystoneclient_v3.client.Client(session=keystone_session,debug=True,
                                               interface=cloud_config.get_interface())
    keystone_projects = keystone.projects.list()
    
    neutron = neutronclient_v2_0.Client(session=keystone_session)
    networks = neutron.list_networks()['networks']
    subnets = neutron.list_subnets()['subnets']
    
    networks = [n for n in networks if n['tenant_id'] in [ p.id for p in keystone_projects]]
    subnets= [s for s in subnets if s['network_id'] in [ n['id'] for n in networks ]]
    return(networks, subnets)

def create_network(network_id, vlan_id, vni, gateways=[]):
    identifier = "".join([c for c in network_id if c in '0123456789'])[0:11]
    LOG.debug("create network %s (vni: %s, vlan_id: %s)" % (network_id,
                                                            vlan_id,
                                                            vni))
    vrf_name = 'openstack-%s' % identifier
    for switch_cluster in leaves:
        vcs_driver = NOSdriver()
        vcs_mgr = vcs_driver.connect(switch_cluster['vip'], leaves_username, leaves_password)
        switch_drivers = [ NOSdriver() for x in switch_cluster['rbridges']]
        switch_mgrs = []
        for idx, driver in enumerate(switch_drivers):
            switch_mgrs.append(driver.connect(switch_cluster['rbridges'][idx]['address'], leaves_username, leaves_password))
        #switch_mgrs = [
            #switch_drivers[0].connect(switch_cluster['rbridges'][0]['address'], leaves_username, leaves_password),
            #switch_drivers[1].connect(switch_cluster['rbridges'][1]['address'], leaves_username, leaves_password)
        #]
        for idx, rbridge in enumerate(switch_cluster['rbridges']):
            switch_mgr = switch_mgrs[idx]
            switch_driver = switch_drivers[idx]
            rbridge_id = rbridge['rid']
            rd = "%s:%s" % (rbridge['address'], vlan_id)
            LOG.info("creating Ve %s on switch %s:%s" % (vlan_id,
                                                         rbridge['address'],
                                                         rbridge_id))
    
        
            vcs_driver.create_vrf(vcs_mgr, rbridge_id, vrf_name)
            try:
                vcs_driver.configure_rd_for_vrf(vcs_mgr, rbridge_id, vrf_name, rd)
            except RPCError as error:
                if "RTM_ERR_RD_CONFIGURED" in error.message:
                    LOG.debug("ignoring RTM_ERR_RD_CONFIGURED on configure_rd_for_vrf")
                else:
                    raise(error)
            vcs_driver.configure_vni_for_vrf(vcs_mgr, rbridge_id, vrf_name, vni)
            vcs_driver.configure_address_family_for_vrf(vcs_mgr, rbridge_id, vrf_name)
            vcs_driver.add_address_family_import_targets_for_vrf(vcs_mgr, rbridge_id, vrf_name, vni)
            vcs_driver.add_address_family_export_targets_for_vrf(vcs_mgr, rbridge_id, vrf_name, vni)
            #driver.add_address_family_import_targets_for_vrf(mgr, rbridge_id, vrf_name, serviceout_vni)
        
            vcs_driver.create_vlan_interface(vcs_mgr, vlan_id)
            vcs_driver.add_vrf_to_svi(vcs_mgr, rbridge_id, vlan_id, vrf_name)
            for gateway in gateways:
                vcs_driver.add_anycast_ip_address_to_vlan_interface(vcs_mgr, rbridge_id, vlan_id, gateway)
            vcs_driver.add_arp_learn_any_to_vlan_interface(vcs_mgr, rbridge_id, vlan_id)
            vcs_driver.set_arp_aging_timeout_for_vlan_interface(vcs_mgr, rbridge_id, vlan_id, arp_aging_timeout)
            try:
                vcs_driver.activate_svi(vcs_mgr, rbridge_id, vlan_id)
            except RPCError as error:
                if "<bad-element>shutdown</bad-element>" in error.info:
                    LOG.info("Ignoring no shutdown error")
                else:
                    raise(error)
            
            # vlan tags
            lldp_neighbors = switch_driver.get_lldp_neighbor_detail(rbridge['address'], leaves_username, leaves_password)
            local_interfaces = [ n['local-interface-name'] for n in lldp_neighbors if not re.search(esx_lldp_regexp,n['remote-system-name'])==None]
            
            LOG.warn( local_interfaces)
            #LOG.warn(switch_driver.nos_version_request(switch_mgr))

def delete_network(network_id, vlan_id, vni):
    identifier = "".join([c for c in network_id if c in '0123456789'])[0:11]
    vrf_name = 'openstack-%s' % identifier
    LOG.debug('deleting network')
    for switch in leaves:
        address = switch['address']
        rbridge_id = switch['rbridge_id']
        rd = "%s:%s" % (address, vlan_id)
        print('vrf_name: %s, rd: %s, vni:1234'% (vrf_name, rd))
    
    
        driver = NOSdriver()
        mgr = driver.connect(address, leaves_username, leaves_password)
        # configure vrf
        try:
            driver.delete_vrf(mgr, rbridge_id, vrf_name)
        except:
            print('except delete_vrf')
            pass
        try:
            driver.delete_vlan_interface(mgr, vlan_id)
        except:
            print('except delete_vlan')
            pass

    
def add_tag_to_interface():
    mgr=driver.connect(leaves[9].address,leaves_username,leaves_password)

networks, subnets = get_openstack_info()
# filter
networks = [n for n in networks if n['name']=='dario']
#print networks
#exit(1)
for network in networks:
    network_subnets = [s for s in subnets if s['network_id']==network['id']]
    network_gateways = ["%s/%s" % (s['gateway_ip'], s['cidr'].split('/')[1]) for s in network_subnets]
    vlan_id = int(network['provider:segmentation_id'])
    vni = vlan_id# + vni_vlan_id_delta
    print network['name']
    print network_gateways
    create_network(network['id'], vlan_id, vni, network_gateways)
    #delete_network(network['id'], vlan_id, vni)
