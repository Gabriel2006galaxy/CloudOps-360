"""flask reset-demo: the demo data goes back to its starting state, with fresh ticket times."""
import contextlib
import io
import os
from datetime import timedelta

from app.extensions import db
from app.models import (
    Attachment, AuditLog, Notification, SLAPolicy, SystemSetting, Ticket, TicketPriority, TicketStatus, User,
    UserRole,
)
from app.services.assignment import set_availability
from app.services.settings import DEFAULT_WAIT_MINUTES, save_auto_assign_config
from app.services.storage import get_storage
from scripts.seed_data import DEMO_TICKETS, seed_database


def test_reset_demo_restores_fresh_demo_data(app, runner):
    with contextlib.redirect_stdout(io.StringIO()):
        seed_database()

    # Simulate days of practice: the tickets age, extra data is added and settings change
    for ticket in Ticket.query.all():
        for field in ('created_at', 'response_due_at', 'resolution_due_at'):
            setattr(ticket, field, getattr(ticket, field) - timedelta(days=4))
    extra = User(username='ravi.tech', email='ravi.tech@cloudops360.local', full_name='Ravi Kumar',
                 role=UserRole.TECHNICIAN)
    extra.set_password('Support2026A')
    db.session.add(extra)
    SLAPolicy.query.filter_by(priority=TicketPriority.HIGH).one().resolution_time_hours = 10
    set_availability(User.query.filter_by(username='tech_marcus').one(), False, note='Sick leave')
    save_auto_assign_config(False, 3, dict(DEFAULT_WAIT_MINUTES))
    storage = get_storage()
    os.makedirs(storage.root, exist_ok=True)
    stored = os.path.join(storage.root, 'reset-demo-test.log')
    with open(stored, 'w') as fh:
        fh.write('x')
    first = Ticket.query.order_by(Ticket.id).first()
    db.session.add(Attachment(ticket_id=first.id, user_id=first.creator_id, filename='reset-demo-test.log',
                              original_filename='mail.log', file_size=1, storage_path='reset-demo-test.log'))
    db.session.commit()
    assert sum(t.is_overdue for t in Ticket.query.all()) > 1
    db.session.commit()  # end the test's transaction so MySQL does not read from an old snapshot

    result = runner.invoke(args=['reset-demo', '--yes'])
    assert result.exit_code == 0, result.output
    db.session.commit()
    db.session.expire_all()

    tickets = Ticket.query.order_by(Ticket.id).all()
    assert len(tickets) == len(DEMO_TICKETS)
    assert [t.title for t in tickets if t.is_overdue] == ['Legacy S3 bucket missing public access block']
    assert not any(t.response_overdue for t in tickets)
    # Numbers start again at 00001: the demo script uses INC-YYYY-00002 (Elena's ticket)
    assert tickets[1].reference_id.endswith('-00002') and tickets[1].creator.username == 'emp_elena'
    assert sum(t.status == TicketStatus.OPEN and t.technician_id is None for t in tickets) == 2
    assert User.query.filter_by(username='ravi.tech').count() == 0
    assert SLAPolicy.query.filter_by(priority=TicketPriority.HIGH).one().resolution_time_hours == 12
    marcus = User.query.filter_by(username='tech_marcus').one()
    assert not marcus.is_away and len(marcus.skills) == 3
    assert SystemSetting.query.count() == 0 and Notification.query.count() == 0
    assert Attachment.query.count() == 0 and not os.path.exists(stored)
    assert [a.action for a in AuditLog.query.order_by(AuditLog.id)] == ['SYSTEM_SEED_INITIALIZED', 'SYSTEM_DEMO_RESET']
    assert 'Pass123' not in result.output
