"""SLA escalation, the System Status page, IST times and clickable ticket rows."""
from datetime import datetime, timedelta

from app.extensions import db
from app.models import AuditLog, Notification, Ticket, TicketPriority, TicketStatus, utcnow
from app.services.escalation import run_sla_escalation
from app.services.sla import apply_sla_to_ticket
from conftest import login, logout, make_ticket

S = TicketStatus
P = TicketPriority


def _reload(obj):
    return db.session.get(type(obj), obj.id)


def _count(user, title):
    return Notification.query.filter_by(user_id=user.id, title=title).count()


# ---------------- SLA escalation ---------------- #

def test_warning_at_75_percent_then_one_escalation(app, admin_user, emp_user, tech_user):
    # High = 12 h to resolve: 8 h old is 66 %, no warning yet
    ticket = make_ticket(emp_user, technician=tech_user, status=S.IN_PROGRESS, priority=P.HIGH,
                         created_at=utcnow() - timedelta(hours=8))
    assert run_sla_escalation() == ([], [])

    # 10 h old = 83 %: the technician is warned, once
    ticket.created_at = utcnow() - timedelta(hours=10)
    apply_sla_to_ticket(ticket, start_time=ticket.created_at)
    db.session.commit()
    warned, escalated = run_sla_escalation()
    db.session.commit()
    assert warned == [ticket] and escalated == []
    assert _count(tech_user, f'SLA warning: {ticket.reference_id}') == 1
    assert _count(admin_user, f'SLA warning: {ticket.reference_id}') == 0
    assert run_sla_escalation() == ([], [])

    # Deadline passed: admins and the technician are alerted, once; the ticket shows Escalated
    ticket.resolution_due_at = utcnow() - timedelta(minutes=1)
    db.session.commit()
    warned, escalated = run_sla_escalation()
    db.session.commit()
    assert escalated == [ticket] and warned == []
    assert _count(admin_user, f'SLA breached: {ticket.reference_id}') == 1
    assert _count(tech_user, f'SLA breached: {ticket.reference_id}') == 1
    assert AuditLog.query.filter_by(action='TICKET_SLA_ESCALATED', entity_id=ticket.reference_id).count() == 1
    assert AuditLog.query.filter_by(action='TICKET_SLA_ESCALATED').one().user_id is None  # done by the system
    assert _reload(ticket).is_escalated
    assert run_sla_escalation() == ([], [])

    # A new deadline (e.g. new priority) starts the cycle again
    ticket = _reload(ticket)
    apply_sla_to_ticket(ticket, start_time=utcnow())
    db.session.commit()
    assert ticket.escalated_at is None and ticket.sla_warning_sent_at is None and not ticket.is_escalated


def test_escalation_rules(app, admin_user, emp_user, tech_user):
    old = utcnow() - timedelta(days=5)
    queued = make_ticket(emp_user, priority=P.CRITICAL, created_at=utcnow() - timedelta(hours=3, minutes=30))
    breached_unassigned = make_ticket(emp_user, priority=P.LOW, created_at=old, title='Nobody took it')
    resolved = make_ticket(emp_user, technician=tech_user, status=S.RESOLVED, created_at=old, title='Fixed late')
    warned, escalated = run_sla_escalation()
    db.session.commit()
    # Unassigned tickets: the warning goes to the admins; resolved tickets are never escalated
    assert warned == [queued] and escalated == [breached_unassigned]
    assert _count(admin_user, f'SLA warning: {queued.reference_id}') == 1
    assert _count(admin_user, f'SLA breached: {breached_unassigned.reference_id}') == 1
    assert _reload(resolved).escalated_at is None
    # A breached ticket is not warned afterwards
    assert _reload(breached_unassigned).sla_warning_sent_at is not None


def test_page_loads_run_escalation_even_with_auto_assign_off(app, client, admin_user, emp_user, tech_user):
    app.config['SLA_ESCALATION_ENABLED'] = True
    ticket = make_ticket(emp_user, technician=tech_user, status=S.IN_PROGRESS, priority=P.CRITICAL,
                         created_at=utcnow() - timedelta(hours=6))
    login(client, 'test_admin')
    assert _reload(ticket).is_escalated
    page = client.get(f'/tickets/{ticket.reference_id}').get_data(as_text=True)
    assert 'Escalated to admin' in page
    assert 'Escalated' in client.get('/tickets').get_data(as_text=True)


def test_sla_check_command(app, runner, admin_user, emp_user):
    make_ticket(emp_user, priority=P.CRITICAL, created_at=utcnow() - timedelta(hours=5))
    db.session.commit()
    result = runner.invoke(args=['sla-check'])
    assert result.exit_code == 0 and '1 escalated' in result.output


# ---------------- System Status page ---------------- #

def test_system_status_page_for_admins_only(app, client, admin_user, emp_user, tech_user):
    login(client, 'test_admin')
    page = client.get('/admin/system-status')
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    for text in ('System Status', 'Web server', 'Identity &amp; secrets', 'Database', 'File storage',
                 'Application security', 'Secret values shown', 'not running on AWS'):
        assert text in html, text
    assert app.config['SECRET_KEY'] not in html
    logout(client)
    for username in ('test_tech', 'test_emp'):
        login(client, username)
        assert client.get('/admin/system-status').status_code == 403
        logout(client)


# ---------------- times in IST, clickable rows ---------------- #

def test_times_are_shown_in_ist(app, client, emp_user):
    ticket = make_ticket(emp_user, created_at=datetime(2026, 1, 1, 0, 0))
    login(client, 'test_emp')
    page = client.get(f'/tickets/{ticket.reference_id}').get_data(as_text=True)
    assert 'Jan 01, 2026 05:30 IST' in page
    assert 'All times IST (UTC+5:30)' in page


def test_ticket_rows_open_the_ticket(app, client, emp_user, tech_user):
    ticket = make_ticket(emp_user, technician=tech_user, status=S.ASSIGNED)
    login(client, 'test_tech')
    for path in ('/tickets', '/technician/workload', '/dashboard/technician'):
        html = client.get(path).get_data(as_text=True)
        assert f'data-href="/tickets/{ticket.reference_id}"' in html, path
