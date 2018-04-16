from networking_brocade.vdx.non_ampp.ml2driver.nos.nosdriver import NOSdriver
from threading import Thread
from concurrent.futures import ThreadPoolExecutor
from hashlib import md5 as hashlib_md5

try:
    from oslo_log import log as logging
except ImportError:
    from neutron.openstack.common import log as logging
LOG = logging.getLogger(__name__)

class RBridge(object):
    def __init__(self):
        self.rid = None
        self.rd = None

class VirtualCluster(object):
    def __init__(self):
        self.name = ''
        self.evpn_instance = ''
        self.ports = []
        self.address = ''
        self.is_border = False
        self.evpn_instance = ''
        self.driver = None
        #self.rbridges_ids = [1, 2]
        self.username = ''
        self.password = ''
        self.rbridges = []
        self.rd = ''
    def connect(self, force=False):
        if force and self.driver:
            LOG.debug('Forcing reconnection to cluster %s (%s)' %
                      (self.name, self.address))
            self.driver = None
        LOG.debug('Opening connection to cluster %s (%s)' %
                  (self.name, self.address))
        if not self.driver:
            self.driver = NOSdriver(self.address, self.username,
                                    self.password, self.evpn_instance)
        return self.driver
    
    def refresh_acl(self, access_list_name, required_seqs):
        current_seq_ids = self.driver.get_access_list_seqs_ids(access_list_name)
        if current_seq_ids is None:
            self.driver.create_access_list(access_list_name)
            current_seq_ids = []
        required_seq_ids = [ s['id'] for s in required_seqs ]
        to_add_seq_ids = [ s for s in required_seq_ids if not s in current_seq_ids]
        to_delete_seq_ids = [ s for s in current_seq_ids if not s in required_seq_ids]
        
        for seq_id in to_add_seq_ids:
            seq = [ s for s in required_seqs if s['id']==seq_id][0]
            self.driver.create_acl_seq(access_list_name, seq)
        for seq_id in to_delete_seq_ids:
            self.driver.delete_acl_seq(access_list_name, seq_id)
        return True
    
    def exec_on_rbridges(self, method, requires_both=False, customattrs=[], has_custom_rd=None, **kwargs):
        rbridge_results = { rbridge.rid: {'status':False, 'details': []} for rbridge in self.rbridges }
        errors = []
        fargs = kwargs
        if has_custom_rd:
            vni = fargs['vni']
            fargs.pop('vni')
        for rbridge in self.rbridges:
            results = rbridge_results[rbridge.rid]
            try:
                fargs['rbridge_id'] = rbridge.rid
                for c in customattrs:
                    fargs[c] = getattr(rbridge, c)
                if has_custom_rd:
                    fargs['rd'] = '%s:%s' % (rbridge.rd, vni)
                getattr(self.driver, method)(**fargs)
                results['details'].append('ran or rbridge %s' % rbridge.rid)
                results['status'] = True
            except Exception as ex:
                errors.append('Error while running method %s '
                              'on rbridge %s with arguments %s, error: %s' %
                              (method, rbridge.rid, kwargs, repr(ex)))
        rbridge_statuses = [ r['status'] for k, r in rbridge_results.iteritems() ]
        if ((False in rbridge_statuses) and requires_both) or not (True in rbridge_statuses):
               raise Exception('Error while running method %s '
                               'on cluster %s with arguments %s, errors: %s' %
                               (method, self.name, kwargs, errors))
        return rbridge_results
    def create_subnet(self, vlan_id, gateway):
        self.connect(force=True)

        self.exec_on_rbridges('configure_svi_with_ip_address_anycast',
                              vlan_id=vlan_id, ip_address=gateway)
        
        return True

    def delete_subnet(self, vlan_id, gateway, skip_errors=True):
        self.connect(force=True)
        try:
            self.exec_on_rbridges('deconfigure_svi_with_ip_address_anycast',
                                  vlan_id=vlan_id, ip_address=gateway)
        except Exception as ex:
            if not skip_errors:
                raise ex
            else:
                LOG.info('Error in delete_subnet("%s","%s"), ignoring'
                         'for skip_errors. Error: %s' %
                         (vlan_id, gateway, repr(ex)))
        return True

    def delete_network(self, vlan_id, skip_errors=True): 
        LOG.debug('deconfiguring network vlan_id: %s' % vlan_id )
        self.connect(force=True)
        for port in self.ports:
            port_speed = port.split(':')[1]
            port_name = port.split(':')[2]
            try:
                self.driver.add_or_remove_vlan_from_interface(
                        "remove", port_speed, port_name, vlan_id)
            except Exception as ex:
                if not skip_errors:
                    raise ex
                else:
                    LOG.info('Error removing vlan tag: %s from port %s. '
                             'Ignoring for skip_errors. Error: %s' %
                             (vlan_id, port, repr(ex)))
        try:
            self.exec_on_rbridges('remove_rbridge_router_evpn_instance_vnis', vni=vlan_id)
        except Exception as ex:
            if not skip_errors:
                raise ex
            else:
                LOG.info('Error removing vni %s from evpn instance. '
                         'Ignoring for skip_errors. Error: %s' %
                         (vlan_id, repr(ex)))

        try:
            self.exec_on_rbridges('remove_svi', vlan_id=vlan_id)
        except Exception as ex:
            if not skip_errors:
                raise ex
            else:
                LOG.info('Error removing vni %s from evpn instance. '
                         'Ignoring for skip_errors. Error: %s' %
                         (vlan_id, repr(ex)))
        
        LOG.debug('deconfigured network, vlan_id %s' % vlan_id)

    def create_network(self, vlan_id, target_vrf, route_map=None):
        LOG.debug('configuring network for vlan %s, forwarding to vrf %s, route_map %s' % (vlan_id, target_vrf, route_map))
        
        self.connect(force=True)
        
        self.driver.create_vlan_interface_rest(vlan_id)
        self.driver.add_suppress_arp_to_vlan_interface(vlan_id)
        
        for port in self.ports:
            port_speed = port.split(':')[1]
            port_name = port.split(':')[2]
            self.driver.add_or_remove_vlan_from_interface(
                    "add", port_speed, port_name, vlan_id)
        if not self.is_border:
            ret = self.exec_on_rbridges('create_svi_interface_rest', vlan_id=vlan_id)
            LOG.debug('interface ve, ret: %s' % ret)
            ret = self.exec_on_rbridges('no_shut_svi_rest', vlan_id=vlan_id)
            LOG.debug('no shut ve, ret: %s' % ret)
            ret = self.exec_on_rbridges('set_vrf_forwarding_for_svi', vlan_id=vlan_id, vrf=target_vrf)
            LOG.debug('vrf forwarding, ret: %s' % ret)
            ret = self.exec_on_rbridges('add_ip_arp_learn_any_to_svi', vlan_id=vlan_id)
            LOG.debug('ip arp learn-any, ret: %s' % ret)
            ret = self.exec_on_rbridges('set_ip_arp_agint_timeout_for_svi', vlan_id=vlan_id, arp_aging_timeout=8)
            LOG.debug('ip arp-aging-timeout, ret: %s' % ret)
            if route_map:
                ret = self.exec_on_rbridges('set_ip_policy_route_map_for_svi', vlan_id=vlan_id, route_map=route_map)
                LOG.debug('ip policy route-map, ret: %s' % ret)
        ret = self.exec_on_rbridges('add_rbridge_router_evpn_instance_vnis', vni=vlan_id)
        LOG.debug('add_rbridge_router_evpn_instance_vnis, ret: %s' % ret)
        
        LOG.debug('done creating network for vlan %s', vlan_id)
        return True
        
    def init_global_vrf(self, vrf_vni, vrf_name):
        if not self.is_border:
            ret = self.exec_on_rbridges('create_vrf', vrf_name=vrf_name)
            LOG.debug(ret)
            ret = self.exec_on_rbridges('configure_rd_for_vrf', has_custom_rd=True,
                                        vrf_name=vrf_name, vni=vrf_vni)
            LOG.debug(ret)
            ret = self.exec_on_rbridges('configure_vni_for_vrf',
                                        vrf_name=vrf_name, vni=vrf_vni)
            LOG.debug(ret)
            ret = self.exec_on_rbridges('add_address_family_import_targets_for_vrf',
                                        vrf_name=vrf_name, vni=vrf_vni)
            LOG.debug(ret)
            ret = self.exec_on_rbridges('add_address_family_export_targets_for_vrf',
                                        vrf_name=vrf_name, vni=vrf_vni)
            ret = self.exec_on_rbridges('add_vrf_to_bgp', vrf_name=vrf_name)
            LOG.debug(ret)
            ret = self.exec_on_rbridges('set_rbridge_router_bgp_address_family_multipath_ebgp',
                                        vrf_name=vrf_name)
            LOG.debug(ret)
            ret = self.exec_on_rbridges('set_rbridge_router_bgp_address_family_maximum_paths',
                                        vrf_name=vrf_name,
                                        maximum_paths=8)
            LOG.debug(ret)
            ret = self.exec_on_rbridges('set_rbridge_router_bgp_address_family_redistribute_connected',
                                  vrf_name=vrf_name)
            LOG.debug(ret)
        return True

    def deconfigure_network(self):
        pass

    def configure_subnet(self):
        pass

    def deconfigure_subnet(self):
        pass
    

class NOSFabricDriver(object):
    def __init__(self, ml2_config, leaves_configs):
        self.external_vrf_vni = ml2_config.external_vrf_vni
        self.internal_vrf_vni = ml2_config.internal_vrf_vni
        self.external_vrf_name = ml2_config.external_vrf_name
        self.internal_vrf_name = ml2_config.internal_vrf_name
        self.tenants_acl_name = ml2_config.tenants_acl_name
        self.username = ml2_config.username
        self.password = ml2_config.password
        self.clusters = {}
        for ln in sorted(leaves_configs.keys()):
            lc = leaves_configs[ln]
            vcs = VirtualCluster()
            vcs.name = ln
            vcs.ports = lc.port
            vcs.evpn_instance = lc['evpn_instance']
            vcs.username = ml2_config.username
            vcs.password = ml2_config.password
            vcs.address = lc['address']
            for i, r in enumerate(lc.rbridge_rd_prefixes):
                rbridge = RBridge()
                rbridge.rid = i+1
                rbridge.rd = r
                vcs.rbridges.append(rbridge)
            
            vcs.is_border = lc.get('is_border',False)
            #vcs.connect()
            self.clusters[ln] = vcs
        self.connect()
    def connect(self):
        LOG.debug('Connecting')
        results = { vcs: None for vcs in self.clusters.keys() }
        executor = ThreadPoolExecutor(max_workers=20)
        for k, vcs in self.clusters.iteritems():
            results[vcs.name] = executor.submit(vcs.connect)
        executor.shutdown()
        results = [ r.result() for k, r in results.iteritems() ]
        LOG.debug('Connected, results: %s' % results)

    def init_global_vrfs(self):
        LOG.debug('Initializing internal vrf on %s' % self.clusters.keys())
        results = { vcs: None for vcs in self.clusters.keys() }
        executor = ThreadPoolExecutor(max_workers=20)
        for k, vcs in self.clusters.iteritems():
            results[vcs.name] = executor.submit(vcs.init_global_vrf, 
                                                self.internal_vrf_vni,
                                                self.internal_vrf_name)
        executor.shutdown()
        results = [ r.result() for k, r in results.iteritems() ]
        LOG.debug('Initialized internal vrf, results: %s' % results)
        return
        LOG.debug('Initializing external vrf')
        results = { vcs: None for vcs in self.clusters.keys() }
        executor = ThreadPoolExecutor(max_workers=20)
        for k, vcs in self.clusters.iteritems():
            results[vcs.name] = executor.submit(vcs.init_global_vrf,
                                                self.external_vrf_vni,
                                                self.external_vrf_name)
        executor.shutdown()
        results = [ r.result() for k, r in results.iteritems() ]
        LOG.debug('Initialized external vrf, results: %s' % results)

    def create_subnet(self, vlan_id, gateway):
        results = { vcs: None for vcs in self.clusters.keys() }
        executor = ThreadPoolExecutor(max_workers=20)
        for k, vcs in self.clusters.iteritems():
            results[vcs.name] = executor.submit(vcs.create_subnet, 
                                                vlan_id,
                                                gateway)
        executor.shutdown()
        results = [ r.result() for k, r in results.iteritems() ]
        LOG.debug('Created subnet, results:' % results)
        return results

    def delete_subnet(self, vlan_id, gateway, skip_errors=True):
        results = { vcs: None for vcs in self.clusters.keys() }
        executor = ThreadPoolExecutor(max_workers=20)
        for k, vcs in self.clusters.iteritems():
            results[vcs.name] = executor.submit(vcs.delete_subnet, 
                                                vlan_id,
                                                gateway)
        executor.shutdown()
        LOG.debug('results: %s' % results)
        results = [ r.result() for k, r in results.iteritems() ]
        LOG.debug('deleted subnet, results:' % results)
        return results
    
    def force_disconnect(self):
        for name, cluster in self.clusters.iteritems():
            cluster.driver.mgr = None
    
    def delete_network(self, vlan_id):
        results = { vcs: None for vcs in self.clusters.keys() }
        executor = ThreadPoolExecutor(max_workers=20)
        for k, vcs in self.clusters.iteritems():
            results[vcs.name] = executor.submit(vcs.delete_network, 
                                                vlan_id)
        executor.shutdown()
        results = [ r.result() for k, r in results.iteritems() ]
        LOG.debug('Deleted network, results:' % results)

    def cidr_pair_hash(self, c1, c2):
        hexdigest = hashlib_md5('%s%s' % (c1,c2)).hexdigest()
        num = int(''.join([ c for c in hexdigest if c in '0123456789']))
        remainder = num % 2**32
        return str(remainder)

    def refresh_acl(self, acl_name, required_seqs):
        results = { vcs: None for vcs in self.clusters.keys() }
        executor = ThreadPoolExecutor(max_workers=20)
        for k, vcs in self.clusters.iteritems():
            results[vcs.name] = executor.submit(vcs.refresh_acl, 
                                                acl_name,
                                                required_seqs)
        executor.shutdown()
        results = [ r.result() for k, r in results.iteritems() ]
        LOG.debug('Refreshed acls, results:' % results)
        return results

    def create_network(self, vlan_id, target_vrf, route_map=None):
        results = { vcs: None for vcs in self.clusters.keys() }
        executor = ThreadPoolExecutor(max_workers=20)
        for k, vcs in self.clusters.iteritems():
            results[vcs.name] = executor.submit(vcs.create_network, 
                                                vlan_id,
                                                target_vrf,
                                                route_map)
        executor.shutdown()
        results = [ r.result() for k, r in results.iteritems() ]
        LOG.debug('Created network, results:' % results)
