"""Dashboard metrics must be computed from real database rows."""
from datetime import timedelta

from app.extensions import db
from app.models import TicketStatus, utcnow
from app.services import metrics
from conftest import login, make_ticket


def test_employee_dashboard_counts_only_own_tickets(client, emp_user, other_emp_user, tech_user):
    make_ticket(emp_user, title='Mine open')
    make_ticket(emp_user, technician=tech_user, status=TicketStatus.IN_PROGRESS, title='Mine progress')
    make_ticket(emp_user, technician=tech_user, status=TicketStatus.RESOLVED, title='Mine resolved')
    make_ticket(other_emp_user, title='Not mine')
    m = metrics.employee_dashboard(emp_user)
    assert m['total'] == 3 and m['open_count'] == 1 and m['in_progress'] == 1 and m['resolved_count'] == 1
    assert m['awaiting_confirmation'] == 1
    login(client, 'test_emp')
    body = client.get('/dashboard/employee').data
    assert b'Mine progress' in body and b'Not mine' not in body


def test_employee_dashboard_empty_state(client, emp_user):
    login(client, 'test_emp')
    assert b'No incidents reported yet' in client.get('/dashboard/employee').data


def test_technician_dashboard_metrics(client, emp_user, tech_user, other_tech):
    make_ticket(emp_user, technician=tech_user, status=TicketStatus.IN_PROGRESS, priority='Critical',
                created_at=utcnow() - timedelta(hours=6))  # overdue critical
    make_ticket(emp_user, technician=tech_user, status=TicketStatus.ASSIGNED, priority='Low')
    done = make_ticket(emp_user, technician=tech_user, status=TicketStatus.RESOLVED, priority='Medium')
    done.resolved_at = utcnow()
    make_ticket(emp_user, technician=other_tech, status=TicketStatus.ASSIGNED)  # someone else's
    make_ticket(emp_user)  # queue
    db.session.commit()
    m = metrics.technician_dashboard(tech_user)
    assert m['active_count'] == 2 and len(m['critical_tickets']) == 1 and len(m['overdue_tickets']) == 1
    assert m['resolved_week'] == 1 and m['queue_count'] == 1
    assert m['priority_counts']['Critical'] == 1 and m['priority_counts']['Low'] == 1
    login(client, 'test_tech')
    assert client.get('/dashboard/technician').status_code == 200


def test_admin_dashboard_matches_database(client, admin_user, emp_user, tech_user):
    for i in range(3):
        make_ticket(emp_user, priority='High', title=f'h{i}')
    make_ticket(emp_user, technician=tech_user, status=TicketStatus.CLOSED, priority='Low')
    m = metrics.admin_dashboard()
    assert m['total_tickets'] == 4 and m['open_tickets'] == 3 and m['resolved_tickets'] == 1
    assert m['priority_counts'] == {'Critical': 0, 'High': 3, 'Medium': 0, 'Low': 1}
    assert m['unassigned'] == 3 and m['total_users'] == 3
    assert sum(m['trend']['created']) == 4
    workload = {w['user'].username: w for w in m['workload']}
    assert workload['test_tech']['active_count'] == 0
    login(client, 'test_admin')
    assert client.get('/dashboard/admin').status_code == 200


def test_daily_trend_buckets_by_day(app, emp_user, tech_user):
    now = utcnow()
    make_ticket(emp_user, created_at=now - timedelta(days=2))
    make_ticket(emp_user, created_at=now - timedelta(days=2))
    old = make_ticket(emp_user, technician=tech_user, status=TicketStatus.RESOLVED, created_at=now - timedelta(days=20))
    old.resolved_at = now - timedelta(days=1)
    db.session.commit()
    from app.models import Ticket
    trend = metrics.daily_trend(Ticket.query, days=7)
    assert len(trend['labels']) == 7
    assert trend['created'][-3] == 2 and sum(trend['created']) == 2  # 20-day-old ticket outside window
    assert trend['resolved'][-2] == 1


def test_analytics_and_sla_pages_render(client, admin_user, emp_user):
    make_ticket(emp_user)
    login(client, 'test_admin')
    for path in ('/admin/analytics', '/admin/analytics?days=7', '/admin/sla'):
        assert client.get(path).status_code == 200
