"""technician leave requests approved by an administrator

- users.leave_requested_at / leave_note / leave_until: a technician asks to be away;
  only an administrator's approval marks them away

Revision ID: d4b2e8f13a57
Revises: c3f1a9d27e64
Create Date: 2026-10-25 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4b2e8f13a57'
down_revision = 'c3f1a9d27e64'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('leave_requested_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('leave_note', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('leave_until', sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('leave_until')
        batch_op.drop_column('leave_note')
        batch_op.drop_column('leave_requested_at')
