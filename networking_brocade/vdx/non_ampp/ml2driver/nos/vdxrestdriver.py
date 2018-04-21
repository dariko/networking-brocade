from oslo_log import log as logging
from concurrent.futures import ThreadPoolExecutor
import lxml.etree as ET
import requests

from oslo_log import log as logging
LOG = logging.getLogger(__name__)

class VdxRESTException(Exception):
    def __init__(self, response):
        self.request = response.request
        self.response = response
        super(VdxRESTException, self).__init__(self, str(self))

    def __str__(self):
        return ("Got response %s [%s] while requesting "
                "url [%s]. Request body: %s" %
                (self.response.status_code, self.response.content,
                self.request.url, self.request.body))

class VdxRESTDriver(object):
    def __init__(self, address, username, password):
        self.address = address
        self.username = username
        self.password = password
        self.base_url = 'http://%s/rest/config/running' % self.address

    def get_session(self):
        session = requests.Session()
        session.auth = (self.username, self.password)
        return session
    

    def ve_no_shut(self, rbridge_id, vlan_id, session=None):
        if not session:
            session = self.get_session()
        url = "%s/rbridge-id/%s/interface/ve/%s/shutdown" % \
              (self.base_url, rbridge_id, vlan_id)
        response = session.delete(url, auth=(self.username, self.password))
        if response.ok or response.status_code==404:
            return response
        else:
            raise VdxRESTException(response)
    
    def vlan_interface_create(self, vlan_id, session=None):
        if not session:
            session = self.get_session()
        url = "%s/interface/" % (self.base_url)
        data="""
            <Vlan>
                <name>%s</name>
            </Vlan>
        """ % vlan_id
        response = session.post(url, auth=(self.username, self.password),
                                 data=data)
        if response.ok or 'object already exists' in response.content:
            return response
        else:
            raise VdxRESTException(response)
    
    def vlan_interface_delete(self, vlan_id, session=None):
        if not session:
            session = self.get_session()
        url = "%s/interface/vlan/%s" % (self.base_url, vlan_id)
        #raise Exception(url)
        response = session.delete(url)
        if not response.ok and not response.status_code==404:
            raise VdxRESTException(response)
        return response

    def ve_interface_create(self, rbridge_id, vlan_id, session=None):
        if not session:
            session = self.get_session()
        url = "%s/rbridge-id/%s/interface/" % (self.base_url, rbridge_id)
        data="""
            <Ve>
                <name>%s</name>
            </Ve>
        """ % vlan_id
        response = session.post(url, data=data)
        if response.ok or 'object already exists' in response.content:
            return response
        else:
            raise VdxRESTException(response)

    def ve_interface_delete(self, rbridge_id, vlan_id, session=None):
        if not session:
            session = self.get_session()
        url = "%s/rbridge-id/%s/interface/ve/%s" % (self.base_url, rbridge_id, vlan_id)
        response = session.delete(url)
        if not response.ok and not response.status_code==404:
            raise VdxRESTException(response)
        return response  

    def trunk_add_remove_vlan(self, ar, i_speed, i_name, vlan_id, session=None):
        if not session:
            session = self.get_session()
        url = ('%s/interface/%s/"%s"/switchport/trunk/allowed/'
              'vlan/%s' % (self.base_url, i_speed, i_name, ar))
        data = "<%s>%s</%s>" % (ar, vlan_id, ar)
        response = session.put(url, data=data)
        if not response.ok:
            raise VdxRESTException(response)
        return response

    def ve_remove_address_anycast(self, rbridge_id, vlan_id, address, session=None):
        if not session:
            session = self.get_session()
        url = '%s/rbridge-id/%s/interface/ve/%s/ip/anycast-address/"%s"' % \
              (self.base_url, rbridge_id, vlan_id, address)
        response = session.delete(url)
        if not response.ok and not response.status_code==404:
            raise VdxRESTException(response)
        return response 

    def ve_add_address_anycast(self, rbridge_id, vlan_id, address, session=None):
        if not session:
            session = self.get_session()
        url = "%s/rbridge-id/%s/interface/ve/%s/ip" % \
              (self.base_url, rbridge_id, vlan_id)
        data="""
            <anycast-address>
                <ip-address>%s</ip-address>
            </anycast-address>
        """ % address
        response = session.post(url, data=data)
        if response.ok or 'object already exists' in response.content:
            return response
        else:
            raise VdxRESTException(response)

    def evpn_instance_add_vni(self, rbridge_id, evpn_instance, vni, session=None):
        if not session:
            session = self.get_session()
        url = "%s/rbridge-id/%s/evpn-instance/%s/vni" % \
              (self.base_url, rbridge_id, evpn_instance)
        data="""
            <vni>
                <add>%s</add>
            </vni>
        """ % vni
        response = session.patch(url, data=data)
        if response.ok:
            return response
        else:
            raise VdxRESTException(response)
    
    def evpn_instance_remove_vni(self, rbridge_id, evpn_instance, vni, session=None):
        if not session:
            session = self.get_session()
        url = "%s/rbridge-id/%s/evpn-instance/%s/vni" % \
              (self.base_url, rbridge_id, evpn_instance)
        data="""
            <vni>
                <remove>%s</remove>
            </vni>
        """ % vni
        response = session.patch(url, data=data)
        if response.ok:
            return response
        else:
            raise VdxRESTException(response)

    def vlan_interface_suppress_arp(self, vlan_id, session=None):
        if not session:
            session = self.get_session()
        url = "%s/interface/vlan/%s/suppress-arp" % (self.base_url, vlan_id)
        data = '<enable>false</enable>'
        response = session.post(url, data=data)
        if response.ok or response.status_code==409:
            return response
        else:
            raise VdxRESTException(response)

    def ve_set_vrf_forwarding(self, rbridge_id, vlan_id, vrf, session=None):
        if not session:
            session = self.get_session()
        url = "%s/rbridge-id/%s/interface/ve/%s/vrf" % \
              (self.base_url, rbridge_id, vlan_id)
        data = """
            <vrf>
                <forwarding>%s</forwarding><
            /vrf>
        """ % vrf
        response = session.put(url, data=data)
        if response.ok or response.status_code==409:
            return response
        else:
            raise VdxRESTException(response)
    
    def ve_set_ip_arp_learn_any(self, rbridge_id, vlan_id, session=None):
        if not session:
            session = self.get_session()
        url = "%s/rbridge-id/%s/interface/ve/%s/ip/arp" % \
              (self.base_url, rbridge_id, vlan_id)
        data = """
            <arp>
                <learn-any>true</learn-any>
            </arp>
        """
        response = session.put(url, auth=(self.username, self.password),
                                 data=data)
        if response.ok or response.status_code==409:
            return response
        else:
            raise VdxRESTException(response)
    
    def ve_set_arp_aging_timeout(self, rbridge_id, vlan_id,
                                 arp_aging_timeout, session=None):
        if not session:
            session = self.get_session()
        url = "%s/rbridge-id/%s/interface/ve/%s/ip/arp-aging-timeout" % \
              (self.base_url, rbridge_id, vlan_id)
        data = """
            <arp-aging-timeout>%s</arp-aging-timeout>
        """ % arp_aging_timeout
        response = session.put(url, auth=(self.username, self.password),
                                 data=data)
        if response.ok:
            return response
        else:
            raise VdxRESTException(response)

    def ve_set_ip_policy_route_map(self, rbridge_id, vlan_id, route_map, session=None):
        LOG.info('untested')
        if not session:
            session = self.get_session()
        url = "%s/rbridge-id/%s/interface/ve/%s/ip/policy/route-map" % \
              (self.base_url, rbridge_id, vlan_id)
        data = """
            <route-map>
                <route-map-name>%s</route-map-name>
            </route-map>
        """ % route_map
        response = session.patch(url, data=data)
        if response.ok:
            return response
        else:
            raise VdxRESTException(response)

class VdxRBridge(object):
    def __init__(self):
        self.rid = None
        self.rd = None

class VdxCluster(object):
    def __init__(self, name, vcs_config, username, password):
        self.username = username
        self.password = password
        self.name = name
        self.ports = vcs_config.port
        self.evpn_instance = vcs_config.evpn_instance
        self.address = vcs_config.address
        self.rbridges = []
        for i, r in enumerate(vcs_config.rbridge_rd_prefixes):
            rbridge = VdxRBridge()
            rbridge.rid = i+1
            rbridge.rd = r
            self.rbridges.append(rbridge)
        
        self.is_border = vcs_config.get('is_border',False)
        self.driver = VdxRESTDriver(self.address, self.username, self.password)

    #def refresh_acl(self, access_list_name, required_seqs):
        #current_seq_ids = self.driver.get_access_list_seqs_ids(access_list_name)
        #if current_seq_ids is None:
            #self.driver.create_access_list(access_list_name)
            #current_seq_ids = []
        #required_seq_ids = [ s['id'] for s in required_seqs ]
        #to_add_seq_ids = [ s for s in required_seq_ids if not s in current_seq_ids]
        #to_delete_seq_ids = [ s for s in current_seq_ids if not s in required_seq_ids]
        
        #for seq_id in to_add_seq_ids:
            #seq = [ s for s in required_seqs if s['id']==seq_id][0]
            #self.driver.create_acl_seq(access_list_name, seq)
        #for seq_id in to_delete_seq_ids:
            #self.driver.delete_acl_seq(access_list_name, seq_id)
        #return True
    
    def create_subnet(self, vlan_id, gateway):
        if not self.is_border:
            for rbridge in self.rbridges:
                self.driver.ve_add_address_anycast(rbridge.rid, vlan_id, gateway)
        return True
    
    def delete_subnet(self, vlan_id, gateway, skip_errors=True):
        if not self.is_border:
            for rbridge in self.rbridges:
                try:
                    self.driver.ve_remove_address_anycast(rbridge.rid, vlan_id, gateway)
                except Exception as ex:
                    if not skip_errors:
                        raise ex                
                    else:
                        LOG.info("Ignoring error %s, skip_error==true" % ex)
        return True

    def create_network(self, vlan_id, target_vrf, route_map=None):
        session = self.driver.get_session()
        self.driver.vlan_interface_create(vlan_id, session=session)
        self.driver.vlan_interface_suppress_arp(vlan_id, session=session)
        #for port in self.ports:
            #port_speed = port.split(':')[1]
            #port_name = port.split(':')[2]
            #self.driver.trunk_add_remove_vlan('add', port_speed, port_name, vlan_id, session=session)
        ret = self.add_tag_to_ports(vlan_id, session=session)
        LOG.debug('Trunked vlan to ports, results: %s' % ret)
        for rbridge in self.rbridges:
            if not self.is_border:
                self.driver.ve_interface_create(rbridge.rid, vlan_id, session=session)
                self.driver.ve_no_shut(rbridge.rid, vlan_id, session=session)
                self.driver.ve_set_vrf_forwarding(rbridge.rid, vlan_id, target_vrf, session=session)
                self.driver.ve_set_ip_arp_learn_any(rbridge.rid, vlan_id, session=session)
                self.driver.ve_set_arp_aging_timeout(rbridge.rid, vlan_id, 8, session=session)
                if route_map:
                    self.driver.ve_set_ip_policy_route_map(rbridge.rid, vlan_id, route_map, session=session)
            self.driver.evpn_instance_add_vni(rbridge.rid, self.evpn_instance, vlan_id, session=session)
        return True
    
    def add_tag_to_ports(self, vlan_id, session):
        results = { port: None for port in self.ports }
        executor = ThreadPoolExecutor(max_workers=20)
        for port in self.ports:
            port_speed = port.split(':')[1]
            port_name = port.split(':')[2]
            results[port] = executor.submit(self.driver.trunk_add_remove_vlan,
                                            'add', port_speed, port_name,
                                            vlan_id, session)
        executor.shutdown()
        results = [ r.result() for k, r in results.iteritems() ]
        
    
    def delete_network(self, vlan_id, skip_errors=True):
        session = self.driver.get_session() 
        try:
            self.driver.vlan_interface_delete(vlan_id, session=session)
        except Exception as ex:
            if not skip_errors:
                raise ex
            else:
                LOG.info("Ignoring error %s, skip_error==true" % ex)
        for rbridge in self.rbridges:
            try:
                self.driver.evpn_instance_remove_vni(rbridge.rid, 
                    self.evpn_instance, vlan_id, session=session)
            except Exception as ex:
                if not skip_errors:
                    raise ex
                else:
                    LOG.info("Ignoring error %s, skip_error==true" % ex)
        return True

class VdxRESTFabricDriverDriver(object):
    def __init__(self, ml2_config, leaves_configs):
        self.external_vrf_vni = ml2_config.external_vrf_vni
        self.internal_vrf_vni = ml2_config.internal_vrf_vni
        self.external_vrf_name = ml2_config.external_vrf_name
        self.internal_vrf_name = ml2_config.internal_vrf_name
        self.tenants_acl_name = ml2_config.tenants_acl_name
        self.clusters = {}
        for ln in sorted(leaves_configs.keys()):
            lc = leaves_configs[ln]
            vcs = VdxCluster(ln, lc, ml2_config.username, ml2_config.password)
            self.clusters[ln]=vcs
    
    def create_network(self, vlan_id, target_vrf, route_map=None):
        results = { vcs: None for vcs in self.clusters.keys() }
        executor = ThreadPoolExecutor(max_workers=20)
        for k, vcs in self.clusters.iteritems():
            results[vcs.name] = executor.submit(vcs.create_network, 
                                                vlan_id,
                                                target_vrf,
                                                route_map)
        executor.shutdown()
        results = {k: r.result() for k, r in results.iteritems() }
        LOG.debug('created network, results: %s' % results)
        return results
    
    def delete_network(self, vlan_id):
        results = { vcs: None for vcs in self.clusters.keys() }
        executor = ThreadPoolExecutor(max_workers=20)
        for k, vcs in self.clusters.iteritems():
            results[vcs.name] = executor.submit(vcs.delete_network, 
                                                vlan_id)
        executor.shutdown()
        results = {k: r.result() for k, r in results.iteritems() }
        LOG.debug('deleted network, results: %s' % results)
        return results

    def create_subnet(self, vlan_id, gateway):
        results = { vcs: None for vcs in self.clusters.keys() }
        executor = ThreadPoolExecutor(max_workers=20)
        for k, vcs in self.clusters.iteritems():
            results[vcs.name] = executor.submit(vcs.create_subnet, 
                                                vlan_id,
                                                gateway)
        executor.shutdown()
        results = {k: r.result() for k, r in results.iteritems() }
        LOG.debug('created subnet, results: %s' % results)
        return results

    def delete_subnet(self, vlan_id, gateway, skip_errors=True):
        results = { vcs: None for vcs in self.clusters.keys() }
        executor = ThreadPoolExecutor(max_workers=20)
        for k, vcs in self.clusters.iteritems():
            results[vcs.name] = executor.submit(vcs.delete_subnet, 
                                                vlan_id,
                                                gateway)
        executor.shutdown()
        results = {k: r.result() for k, r in results.iteritems() }
        LOG.debug('deleted subnet, results: %s' % results)
        return results
