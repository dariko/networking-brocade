from networking_brocade.vdx.non_ampp.ml2driver.nos.nosdriver import NOSdriver
from threading import Thread

try:
    from oslo_log import log as logging
except ImportError:
    from neutron.openstack.common import log as logging
LOG = logging.getLogger(__name__)

class VirtualCluster(object):
    def __init__(self):
        self.name = ''
        self.evpn_instance = ''
        self.ports = []
        self.address = ''
        self.is_border = False
        self.evpn_instance = ''
        self.driver = None
    

class NOSFabricDriver(object):
    def __init__(self, leaves_configs, username, password,
                 external_vrf_name, external_vrf_vni, external_vrf_collector,
                 internal_vrf_name, internal_vrf_vni, internal_vrf_collector, 
                 additional_vni):
        self.additional_vni = additional_vni
        self.external_vrf_vni = external_vrf_vni
        self.internal_vrf_vni = internal_vrf_vni
        self.external_vrf_name = external_vrf_name
        self.internal_vrf_name = internal_vrf_name
        self.external_vrf_collector = external_vrf_collector
        self.internal_vrf_collector = internal_vrf_collector
        self.clusters = {}
        for ln in sorted(leaves_configs.keys()):
            lc = leaves_configs[ln]
            vcs = VirtualCluster()
            vcs.name = ln
            vcs.ports = lc.port
            vcs.evpn_instance = lc['evpn_instance']
            vcs.address = lc['address']
            vcs.is_border = lc.get('is_border',False)
            LOG.debug('Opening connection to cluster %s (%s)' %
                      (ln, vcs.address))
            vcs.driver = NOSdriver(lc['address'],
                                   username,
                                   password,
                                   vcs.evpn_instance)
            #raise Exception(vcs.driver.configure_svi('1415'))
            self.clusters[ln] = vcs
        #raise Exception(self.clusters['leaf1'].driver.remove_rbridge_router_evpn_instance_vnis(1,'1414-1417'))
        
    def init_global_vrfs(self):
        for n in ['external', 'internal']:
            vrf_vni = getattr(self,'%s_vrf_vni' % n)
            vrf_name = getattr(self,'%s_vrf_name' % n)
            cl_names = self.clusters.keys()
            le_names = { cn: v for (cn, v) in self.clusters.items() if not v.is_border }.keys()

            LOG.debug('Initializing vrf %s, vni: %s' % (vrf_name, vrf_vni))
            ret = self.exec_on_clusters(le_names, 'create_vrf', vrf_name=vrf_name)
            ret = self.exec_on_clusters(le_names, 'configure_rd_for_vrf', vrf_name=vrf_name, ident=vrf_vni)
            ret = self.exec_on_clusters(le_names, 'configure_vni_for_vrf', vrf_name=vrf_name, vni=vrf_vni)
            ret = self.exec_on_clusters(le_names, 'add_address_family_import_targets_for_vrf',
                                        vrf_name=vrf_name, vni=vrf_vni)
            ret = self.exec_on_clusters(le_names, 'add_address_family_export_targets_for_vrf',
                                        vrf_name=vrf_name, vni=vrf_vni)
            
            if self.additional_vni:
                self.exec_on_clusters(le_names, 'add_address_family_import_targets_for_vrf',
                                      vrf_name=vrf_name,vni=self.additional_vni)
                self.exec_on_clusters(le_names, 'add_address_family_export_targets_for_vrf',
                                      vrf_name=vrf_name,vni=self.additional_vni)
            self.exec_on_clusters(le_names, 'add_vrf_to_bgp', vrf_name=vrf_name)
            self.exec_on_clusters(le_names, 'set_rbridge_router_bgp_address_family_multipath_ebgp',
                                  vrf_name=vrf_name)
            self.exec_on_clusters(le_names, 'set_rbridge_router_bgp_address_family_maximum_paths_ebgp',
                                  vrf_name=vrf_name,
                                  maximum_paths=8)
            self.exec_on_clusters(le_names, 'set_rbridge_router_bgp_address_family_redistribute_connected',
                                  vrf_name=vrf_name)

    def create_subnet(self, vlan_id, gateway):
        LOG.debug('force disconnect')
        self.force_disconnect()
        cl_names = self.clusters.keys()
        le_names = { cn: v for (cn, v) in self.clusters.items() if not v.is_border }.keys()

        LOG.debug('add anycast-address %s to ve %s', (gateway, vlan_id))
        
        ret = self.exec_on_clusters(le_names, 'configure_svi_with_ip_address_anycast',
                                    vlan_id=vlan_id, ip_address=gateway)

    def delete_subnet(self, vlan_id, gateway, skip_errors=True):
        LOG.debug('force disconnect')
        self.force_disconnect()
        cl_names = self.clusters.keys()
        le_names = { cn: v for (cn, v) in self.clusters.items() if not v.is_border }.keys()

        LOG.debug('add anycast-address %s to ve %s', (gateway, vlan_id))
        try:
            ret = self.exec_on_clusters(le_names, 'deconfigure_svi_with_ip_address_anycast',
                            vlan_id=vlan_id, ip_address=gateway)
        except Exception as e:
            if not skip_errors:
                raise e
            else:
                LOG.warn('Ignoring error: %s ' % e)
    
    def force_disconnect(self):
        for name, cluster in self.clusters.iteritems():
            cluster.driver.mgr = None
    
    def delete_network(self, vlan_id, collector_vrf_name, skip_errors=True):
        LOG.debug('deconfigure network for vlan %s' % vlan_id)
        LOG.debug('force disconnect')
        self.force_disconnect()
        cl_names = self.clusters.keys()
        le_names = { cn: v for (cn, v) in self.clusters.items() if not v.is_border }.keys()
        
        for name, cluster in self.clusters.iteritems():
            LOG.debug('delete vlan interface %s on cluster %s' % (vlan_id, cluster.name))
            try:
                ret = cluster.driver.delete_vlan_interface(vlan_id)
            except Exception as e:
                if not skip_errors:
                    raise e
                else:
                    LOG.warn('Ignoring error: %s ' % e)
        #return
        try:
            ret = self.exec_on_clusters(le_names, 'remove_rbridge_router_evpn_instance_vnis', vni=vlan_id)
            LOG.debug('remove_rbridge_router_evpn_instance_vnis, ret: %s' % ret)
        except Exception as e:
            if not skip_errors:
                raise e
            else:
                LOG.warn('Ignoring error: %s ' % e)
            
        
        try:
            ret = self.exec_on_clusters(le_names, 'remove_address_family_import_targets_for_vrf',
                                        vrf_name=collector_vrf_name, vni=vlan_id)
            LOG.debug('remove_address_family_import_targets_for_vrf %s, ret: %s' %
                      (vrf_name, ret))
        except Exception as e:
            if not skip_errors:
                raise e
            else:
                LOG.warn('Ignoring error: %s ' % e)
        

        LOG.debug('done deleting network')
        

    def create_network(self, vlan_id, vrf_name, collector_vrf_name):
        LOG.debug('configuring network for vlan %s' % vlan_id)
        
        self.force_disconnect()
        
        cl_names = self.clusters.keys()
        le_names = { cn: v for (cn, v) in self.clusters.items() if not v.is_border }.keys()
        
        #raise Exception("AA: %s - %s" % (cl_names, le_names))
        
        for name, cluster in self.clusters.iteritems():
            LOG.debug('creating vlan interface %s on cluster %s' % (vlan_id, cluster.name))
            ret = cluster.driver.create_vlan_interface_rest(vlan_id)
            ret = cluster.driver.add_suppress_arp_to_vlan_interface(vlan_id)
            LOG.debug('created vlan interface %s on cluster %s.'
                      'Response: %s' % (vlan_id, cluster.name, ret))
        ret = self.add_remove_vlan_id_to_ports('add', vlan_id)
        LOG.debug('added vlan tag %s to ports' % vlan_id)
        
        ret = self.exec_on_clusters(le_names, 'create_svi_interface_rest', vlan_id=vlan_id)
        LOG.debug('interface ve, ret: %s' % ret)
        ret = self.exec_on_clusters(le_names, 'no_shut_svi_rest', vlan_id=vlan_id)
        LOG.debug('no shut ve, ret: %s' % ret)
        ret = self.exec_on_clusters(le_names, 'set_vrf_forwarding_for_svi', vlan_id=vlan_id, vrf=vrf_name)
        LOG.debug('vrf forwarding, ret: %s' % ret)
        ret = self.exec_on_clusters(le_names, 'add_ip_arp_learn_any_to_svi', vlan_id=vlan_id)
        LOG.debug('ip arp learn-any, ret: %s' % ret)
        ret = self.exec_on_clusters(le_names, 'set_ip_arp_agint_timeout_for_svi', vlan_id=vlan_id, arp_aging_timeout=8)
        LOG.debug('ip arp-aging-timeout, ret: %s' % ret)
        ret = self.exec_on_clusters(le_names, 'set_ip_policy_route_map_for_svi', vlan_id=vlan_id, route_map='PBR')
        LOG.debug('ip policy route-map, ret: %s' % ret)
        ret = self.exec_on_clusters(cl_names, 'add_rbridge_router_evpn_instance_vnis', vni=vlan_id)
        LOG.debug('add_rbridge_router_evpn_instance_vnis, ret: %s' % ret)
        ret = self.exec_on_clusters(cl_names, 'add_address_family_import_targets_for_vrf',
                                        vrf_name=collector_vrf_name, vni=vlan_id)
        LOG.debug('add_address_family_import_targets_for_vrf %s, ret: %s' %
                  (vrf_name, ret))
        
        
        LOG.debug('done creating network for vlan %s', vlan_id)
    
    
    def add_remove_vlan_id_to_ports(self, verb, vlan_id):
        self.force_disconnect()
        results = dict((k,{'status': False, 'details': ''}) for k in self.clusters.keys())
        threads = []
        for cluster_name in self.clusters.keys():
            thread = Thread(target=self.add_remove_vlan_id_to_ports_on_cluster, args=(verb, cluster_name, vlan_id, results))
            thread.start()
            threads.append(thread)
        for t in threads:
            t.join()
        if False in [results[k]['status'] for k in results.keys()]:
            raise Exception('Error adding vlan %s on clusters with. Errors: %s' %
                            (vlan_id, results))
        return results
    
    def add_remove_vlan_id_to_ports_on_cluster(self, verb, cluster_name, vlan_id, results):
        errors = []
        for port_data in self.clusters[cluster_name].ports:
            try:
                port_speed = port_data.split(':')[1]
                port_name = port_data.split(':')[2]
                #LOG.debug('add vlan %s to port %s '
                              #'on cluster %s error: %s' % (vlan_id,
                              #port_data, cluster_name, ex))
                self.clusters[cluster_name].driver.add_or_remove_vlan_from_interface(
                    "add", port_speed, port_name, vlan_id)
            except Exception as ex:
                errors.append('Failed to add vlan %s to port %s '
                              'on cluster %s error: %s' % (vlan_id,
                              port_data, cluster_name, ex))
        results[cluster_name]['details'] = errors
        if len(errors) > 0:
            results[cluster_name]['status'] = False
        else:
            results[cluster_name]['status'] = True
        
    def call_nosdriver_method_on_switch(self, switch_name, method, results, **kwargs):
        try:
            getattr(self.clusters[switch_name], method)(**kwargs)
        except Exception as ex:
            results[switch_name] = { 'status': False, 'details': str(ex) }

    def call_nosdriver_method_on_cluster(self, cluster_name, method, results, kwargs):
        local_results = [ False, False ]
        errors = []
        for rbridge_id in range(1,3):
            try:
                kwargs['rbridge_id'] = rbridge_id
                getattr(self.clusters[cluster_name].driver, method)(**kwargs)
                errors.append('ran or rbridge %s' % rbridge_id)
                local_results[rbridge_id-1] = True
            except Exception as ex:
                errors.append('Error while running method %s '
                              'on cluster %s with arguments %s, error: %s' %
                              (method, cluster_name, kwargs, ex))

        results[cluster_name]['details'] = "\n".join(errors)
        if not True in local_results:
            raise Exception('Error while running method %s '
                            'on cluster %s with arguments %s, ersror: %s' %
                            (method, cluster_name, kwargs, errors))
        results[cluster_name]['status'] = True

    def exec_on_clusters(self, cluster_names, method, **kwargs):
        results = dict((k,{'status': False, 'details': ''}) for k in cluster_names)
        threads = []
        for cluster_name in cluster_names:
            thread = Thread(target=self.call_nosdriver_method_on_cluster, args=(cluster_name, method, results, kwargs))
            thread.start()
            threads.append(thread)
        #LOG.debug('THTH waiting on %s threads' % len(threads))
        for t in threads:
            t.join()
        if False in [results[k]['status'] for k in results.keys()]:
            raise Exception('Error running method %s on clusters %s with'
                            ' args %s. Errors: %s' %
                            (cluster_names, method, kwargs, results))
        return results
    def exec_on_switches(self, method, **kwargs):
        results = dict((k,{'status': False, 'details': ''}) for k in self.clusters.keys())
        threads = []
        for i in range(len(self.clusters)):
            thread = Thread(target=self.call_nosdriver_method_on_switch, args=kwargs)
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()
        errors = {name: details for (name, details) in results if not result['status']}
        if len(errors.keys()) > 0:
            raise Exception('Error running %s with arguments %s, got errors: %s' %
                            method, kwargs, errors)
        return results

