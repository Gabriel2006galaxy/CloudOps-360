"""auto-assignment, technician availability and skills, customer satisfaction

- users.is_available / away_note / away_until: away technicians get no auto-assigned tickets
- technician_skills: categories a technician specialises in
- system_settings: administrator-editable settings (auto-assignment configuration)
- tickets.satisfaction_rating / satisfaction_comment / rated_at: CSAT (1-5 stars)
- ticket_status_history.changed_by_id nullable: NULL = done by the system (auto-assignment)

Revision ID: c3f1a9d27e64
Revises: 824a33157b1b
Create Date: 2026-10-24 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3f1a9d27e64'
down_revision = '824a33157b1b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('system_settings',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', sa.String(length=255), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('technician_skills',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['category_id'], ['ticket_categories.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'category_id')
    )

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_available', sa.Boolean(), server_default=sa.true(), nullable=False))
        batch_op.add_column(sa.Column('away_note', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('away_until', sa.DateTime(), nullable=True))

    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('satisfaction_rating', sa.SmallInteger(), nullable=True))
        batch_op.add_column(sa.Column('satisfaction_comment', sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column('rated_at', sa.DateTime(), nullable=True))
        batch_op.create_check_constraint(
            'ck_tickets_satisfaction_rating',
            'satisfaction_rating IS NULL OR (satisfaction_rating >= 1 AND satisfaction_rating <= 5)')

    with op.batch_alter_table('ticket_status_history', schema=None) as batch_op:
        batch_op.alter_column('changed_by_id', existing_type=sa.Integer(), nullable=True)


def downgrade():
    # Rows written by the system have no actor; they cannot satisfy NOT NULL again
    op.execute('DELETE FROM ticket_status_history WHERE changed_by_id IS NULL')
    with op.batch_alter_table('ticket_status_history', schema=None) as batch_op:
        batch_op.alter_column('changed_by_id', existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table('tickets', schema=None) as batch_op:
        batch_op.drop_constraint('ck_tickets_satisfaction_rating', type_='check')
        batch_op.drop_column('rated_at')
        batch_op.drop_column('satisfaction_comment')
        batch_op.drop_column('satisfaction_rating')

    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('away_until')
        batch_op.drop_column('away_note')
        batch_op.drop_column('is_available')

    op.drop_table('technician_skills')
    op.drop_table('system_settings')
