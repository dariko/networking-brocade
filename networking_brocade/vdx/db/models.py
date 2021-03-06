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
# Authors:
# Shiv Haris (sharis@brocade.com)
# Varma Bhupatiraju (vbhupati@#brocade.com)
# Ritesh Madapurath (rmadapur@brocade.com)
# Raghuprem Muthigi (rmuthigi@brocade.com)

"""Brocade specific database schema/model."""
import sqlalchemy as sa

from neutron_lib.db import model_base
from neutron.db import models_v2

class ML2_BrocadeNetwork(model_base.BASEV2, model_base.HasId,
                         model_base.HasProject):

    """Schema for brocade network."""

    vlan = sa.Column(sa.String(10))
    segment_id = sa.Column(sa.String(36))
    network_type = sa.Column(sa.String(10))


class ML2_BrocadePort(model_base.BASEV2, model_base.HasId,
                      model_base.HasProject):

    """Schema for brocade port."""

    network_id = sa.Column(sa.String(36),
                           sa.ForeignKey("ml2_brocadenetworks.id"),
                           nullable=False)
    admin_state_up = sa.Column(sa.Boolean, nullable=False)
    physical_interface = sa.Column(sa.String(36))
    vlan_id = sa.Column(sa.String(36))
    host = sa.Column(sa.String(255))


class ML2_BrocadeSvi(model_base.BASEV2, model_base.HasId,
                     model_base.HasProject):

    """schema for brocade svi """
    svi_id = sa.Column(sa.String(36), primary_key=True)
    admin_state_up = sa.Column(sa.Boolean, nullable=False)
    ip_address = sa.Column(sa.String(36))
    subnet_mask = sa.Column(sa.String(36))


def create_svi(context, router_id, project_id, svi,
               admin_state_up, ip_address, net_mask):
    """create svi port """
    session = context.session
    with session.begin(subtransactions=True):
        ve = get_svi(context, router_id, project_id, svi, ip_address, net_mask)
        if not ve:
            svi = ML2_BrocadeSvi(id=router_id, project_id=project_id,
                                 svi_id=svi, admin_state_up=admin_state_up,
                                 ip_address=ip_address,
                                 subnet_mask=net_mask)
            session.add(svi)
    return svi


def delete_svi(context, router_id, project_id, svi, ip_address, net_mask):
    """Delete a brocade specific network/port-profiles."""

    session = context.session
    with session.begin(subtransactions=True):
        svi = get_svi(context, router_id, project_id, svi, ip_address, net_mask)
        if svi:
            session.delete(svi)


def get_svi(context, router_id, project_id, svi, ip_address, net_mask):
    session = context.session
    return session.query(ML2_BrocadeSvi).filter_by(id=router_id,
                                                   project_id=project_id,
                                                   svi_id=svi,
                                                   ip_address=ip_address,
                                                   subnet_mask=net_mask).\
        first()


def get_svis(context, router_id, project_id):
    session = context.session
    return session.query(ML2_BrocadeSvi).filter_by(id=router_id,
                                                   project_id=project_id).all()


def get_list_svi_ids(context, router_id, project_id):
    ves = []
    svis = get_svis(context, router_id, project_id)
    for svi in svis:
        if svi['svi_id']:
            ves.append(svi['svi_id'])
    return ves


def create_network(context, net_id, vlan, segment_id, network_type, project_id):
    """Create a brocade specific network/port-profiles."""

    # only network_type of vlan is supported
    session = context.session
    with session.begin(subtransactions=True):
        net = get_network(context, net_id, None)
        if not net:
            net = ML2_BrocadeNetwork(id=net_id, vlan=vlan,
                                     segment_id=segment_id,
                                     network_type=network_type,
                                     project_id=project_id)
            session.add(net)
    return net


def delete_network(context, net_id):
    """Delete a brocade specific network"""

    session = context.session
    with session.begin(subtransactions=True):
        net = get_network(context, net_id, None)
        if net:
            session.delete(net)


def get_network(context, net_id, fields=None):
    """Get brocade specific network, with vlan extension."""

    session = context.session
    return session.query(ML2_BrocadeNetwork).filter_by(id=net_id).first()


def get_networks(context, filters=None, fields=None):
    """Get all brocade specific networks."""

    session = context.session
    return session.query(ML2_BrocadeNetwork).all()


def create_port(context, port_id, network_id, physical_interface,
                vlan_id, project_id, admin_state_up, host):
    """Create a brocade specific port, has policy like vlan."""

    session = context.session
    with session.begin(subtransactions=True):
        port = get_port(context, port_id)
        if not port:
            port = ML2_BrocadePort(id=port_id,
                                   network_id=network_id,
                                   physical_interface=physical_interface,
                                   vlan_id=vlan_id,
                                   admin_state_up=admin_state_up,
                                   project_id=project_id,
                                   host=host)
            session.add(port)

    return port


def get_port(context, port_id):
    """get a brocade specific port."""

    session = context.session
    return session.query(ML2_BrocadePort).filter_by(id=port_id).first()


def is_vm_exists_on_host(context, host, physnet, vlan_id):
    """check if port is tagged on host"""
    session = context.session
    qc = session.query(ML2_BrocadePort).filter_by(
        physical_interface=physnet, host=host, vlan_id=vlan_id).count()
    return qc > 1


def is_last_vm_on_host(context, host, physnet, vlan_id):
    """check if port is tagged on host"""
    session = context.session
    qc = session.query(ML2_BrocadePort).filter_by(
        physical_interface=physnet, host=host, vlan_id=vlan_id).count()
    return qc <= 0


def get_ports(context, network_id=None):
    """get a brocade specific port."""

    session = context.session
    return session.query(ML2_BrocadePort).filter_by(
        network_id=network_id).all()


def delete_port(context, port_id):
    """delete brocade specific port."""

    session = context.session
    with session.begin(subtransactions=True):
        port = get_port(context, port_id)
        if port:
            session.delete(port)


def update_port_state(context, port_id, admin_state_up):
    """Update port attributes."""

    session = context.session
    with session.begin(subtransactions=True):
        session.query(ML2_BrocadePort).filter_by(
            id=port_id).update({'admin_state_up': admin_state_up})
