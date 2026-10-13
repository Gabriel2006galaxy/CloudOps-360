"""SLA target calculation, overdue detection, compliance metrics and admin configuration."""
from datetime import timedelta

from app.extensions import db
from app.models import SLAPolicy, Ticket, TicketPriority, TicketStatus, format_duration, utcnow
from app.services.sla import calculate_sla_due_dates, compute_sla_metrics
from conftest import login, make_ticket


def test_due_dates_follow_policy_per_priority(app):
    start = utcnow().replace(microsecond=0)
    expected = {'Critical': (1, 4), 'High': (4, 12), 'Medium': (8, 24), 'Low': (24, 72)}
    for priority, (resp, resol) in expected.items():
        response_due, resolution_due = calculate_sla_due_dates(priority, start)
        assert response_due == start + timedelta(hours=resp)
        assert resolution_due == start + timedelta(hours=resol)


def test_policy_changes_are_used_for_new_calculations(app):
    policy = SLAPolicy.query.filter_by(priority='Low').one()
    policy.resolution_time_hours = 100
    db.session.commit()
    start = utcnow()
    assert calculate_sla_due_dates('Low', start)[1] == start + timedelta(hours=100)


def test_overdue_and_time_remaining(app, emp_user):
    late = make_ticket(emp_user, priority='Critical', created_at=utcnow() - timedelta(hours=5))
    fresh = make_ticket(emp_user, priority='Critical')
    assert late.is_overdue and late.time_remaining_display.startswith('Overdue by 1h')
    assert not fresh.is_overdue and fresh.time_remaining_display.endswith('remaining')
    assert late.sla_progress_percent == 100 and fresh.sla_progress_percent < 5
    assert late.response_overdue  # no first response after > 1h


def test_resolved_ticket_is_never_overdue_and_duration_is_recorded(app, emp_user, tech_user):
    t = make_ticket(emp_user, technician=tech_user, status=TicketStatus.RESOLVED, priority='High',
                    created_at=utcnow() - timedelta(hours=30))
    t.resolved_at = t.created_at + timedelta(hours=10)
    db.session.commit()
    assert not t.is_overdue
    assert t.resolution_met_sla is True
    assert t.resolution_duration == '10h 0m'
    t.resolved_at = t.created_at + timedelta(hours=13)
    assert t.resolution_met_sla is False and t.time_remaining_display == 'Resolved late'


def test_format_duration():
    assert format_duration(59) == '0h 0m'
    assert format_duration(3 * 3600 + 120) == '3h 2m'
    assert format_duration(2 * 86400 + 5 * 3600) == '2d 5h'


def test_compliance_metrics(app, emp_user, tech_user):
    now = utcnow()
    on_time = make_ticket(emp_user, technician=tech_user, status=TicketStatus.RESOLVED, priority='High', created_at=now - timedelta(hours=20))
    on_time.resolved_at = on_time.created_at + timedelta(hours=2)
    on_time.first_responded_at = on_time.created_at + timedelta(minutes=30)
    late = make_ticket(emp_user, technician=tech_user, status=TicketStatus.CLOSED, priority='High', created_at=now - timedelta(hours=40))
    late.resolved_at = late.created_at + timedelta(hours=20)
    late.first_responded_at = late.created_at + timedelta(hours=6)
    make_ticket(emp_user, priority='Critical', created_at=now - timedelta(hours=8))  # active + overdue
    make_ticket(emp_user, priority='Low')  # active, within SLA, not evaluated
    db.session.commit()

    m = compute_sla_metrics(Ticket.query.all())
    assert m['resolved_within_sla'] == 1 and m['resolved_breached'] == 1 and m['overdue_count'] == 1
    assert m['evaluated_count'] == 3 and m['compliance_rate'] == 33.3
    assert m['breached_count'] == 2
    # response: on_time responded in time, late responded late, overdue critical never responded
    assert m['response_compliance_rate'] == 33.3
    assert m['avg_resolution_seconds'] == (2 + 20) / 2 * 3600


def test_metrics_empty_state(app):
    m = compute_sla_metrics([])
    assert m['compliance_rate'] is None and m['evaluated_count'] == 0


def test_admin_updates_sla_policy_and_recalculates_active(client, admin_user, emp_user):
    ticket = make_ticket(emp_user, priority='Medium')
    login(client, 'test_admin')
    resp = client.post('/admin/sla', data={'priority': 'Medium', 'response_time_hours': 2,
                                           'resolution_time_hours': 6, 'description': 'Tighter', 'apply_to_active': 'y'})
    assert resp.status_code == 302
    policy = SLAPolicy.query.filter_by(priority='Medium').one()
    assert (policy.response_time_hours, policy.resolution_time_hours) == (2, 6)
    t = db.session.get(Ticket, ticket.id)
    assert abs((t.resolution_due_at - t.created_at) - timedelta(hours=6)) < timedelta(seconds=2)


def test_sla_form_rejects_resolution_shorter_than_response(client, admin_user):
    login(client, 'test_admin')
    resp = client.post('/admin/sla', data={'priority': 'High', 'response_time_hours': 10, 'resolution_time_hours': 5})
    assert resp.status_code == 200 and b'cannot be shorter' in resp.data
    assert SLAPolicy.query.filter_by(priority='High').one().resolution_time_hours == 12
    resp = client.post('/admin/sla', data={'priority': 'High', 'response_time_hours': 0, 'resolution_time_hours': 5})
    assert SLAPolicy.query.filter_by(priority='High').one().response_time_hours == 4
