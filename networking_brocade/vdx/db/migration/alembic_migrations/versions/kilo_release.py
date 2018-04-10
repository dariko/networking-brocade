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

"""kilo

Revision ID: kilo
Revises: start_networking_brcd_clos
Create Date: 2015-04-16 00:00:00.000000

"""
# revision identifiers, used by Alembic.
revision = 'kilo'
down_revision = 'start_ml2_brcd'


from alembic import op
import sqlalchemy as sa

def upgrade():
    #op.drop_table('brocadenetworks')
    #op.drop_table('brocadeports')
    #op.drop_table('ml2_brocadenetworks')
    #op.drop_table('ml2_brocadeports')
    #op.create_table(
        #'brocadenetworks',
        #sa.Column('id', sa.String(length=36), nullable=False),
        #sa.Column('vlan', sa.String(length=10), nullable=True),
        #sa.PrimaryKeyConstraint('id'))

    #op.create_table(
        #'brocadeports',
        #sa.Column('port_id', sa.String(length=36), nullable=False,
                  #server_default=''),
        #sa.Column('network_id', sa.String(length=36), nullable=False),
        #sa.Column('admin_state_up', sa.Boolean(), nullable=False),
        #sa.Column('physical_interface', sa.String(length=36), nullable=True),
        #sa.Column('vlan_id', sa.String(length=36), nullable=True),
        #sa.Column('project_id', sa.String(length=36), nullable=True),
        #sa.ForeignKeyConstraint(['network_id'], ['brocadenetworks.id'], ),
        #sa.PrimaryKeyConstraint('port_id'))

    with op.batch_alter_table("ml2_brocadenetworks") as batch_op:
        try:
            batch_op.drop_index('ix_ml2_brocadenetworks_tenant_id')
        except:
            # index missing
            pass
        batch_op.drop_column('tenant_id')
        batch_op.add_column(sa.Column('project_id', sa.String(length=255), nullable=True,
                  index=True))
        #batch_op.create_index('ix_ml2_brocadenetworks_project_id', ['project_id'], unique=False)
        
    #op.create_table(
        #'ml2_brocadenetworks',
        #sa.Column('id', sa.String(length=36), nullable=False),
        #sa.Column('vlan', sa.String(length=10), nullable=True),
        #sa.Column('segment_id', sa.String(length=36), nullable=True),
        #sa.Column('network_type', sa.String(length=10), nullable=True),
        #sa.Column('project_id', sa.String(length=255), nullable=True,
                  #index=True),
        #sa.PrimaryKeyConstraint('id'))

    with op.batch_alter_table("ml2_brocadeports") as batch_op:
        try:
            batch_op.drop_index('ix_ml2_brocadeports_tenant_id')
        except:
            # index missing
            pass
        batch_op.drop_column('tenant_id')
        batch_op.add_column(sa.Column('project_id', sa.String(length=255), nullable=True,
                  index=True))
        #batch_op.create_index('ix_ml2_brocadeports_project_id', ['project_id'], unique=False)

    #op.create_table(
        #'ml2_brocadeports',
        #sa.Column('id', sa.String(length=36), nullable=False),
        #sa.Column('network_id', sa.String(length=36), nullable=False),
        #sa.Column('admin_state_up', sa.Boolean(), nullable=False),
        #sa.Column('physical_interface', sa.String(length=36), nullable=True),
        #sa.Column('vlan_id', sa.String(length=36), nullable=True),
        #sa.Column('project_id', sa.String(length=255), nullable=True,
                  #index=True),
        #sa.PrimaryKeyConstraint('id'),
        #sa.ForeignKeyConstraint(['network_id'], ['ml2_brocadenetworks.id']))
