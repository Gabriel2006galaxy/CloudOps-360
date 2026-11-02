"""SLA escalation flags on tickets

- tickets.sla_warning_sent_at: technician warned at 75 % of the resolution window
- tickets.escalated_at: resolution SLA breached, administrators alerted

Revision ID: e7a4c1d92b38
Revises: d4b2e8f13a57
Create Date: 2026-11-02 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e7a4c1d92b38'
down_revision = 'd4b2e8f13a57'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sla_warning_sent_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('escalated_at', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.drop_column('escalated_at')
        batch_op.drop_column('sla_warning_sent_at')
