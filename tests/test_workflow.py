"""Status workflow, assignment, priority changes, reopening and notifications."""
from datetime import timedelta

from app.extensions import db
from app.models import AuditLog, Notification, Ticket, TicketStatus, TicketStatusHistory, utcnow
from app.services.workflow import allowed_transitions
from conftest import login, logout, make_ticket

S = TicketStatus


def _status(client, ref, status, **extra):
    return client.post(f'/tickets/{ref}/status', data={'status': status, **extra})


def _reload(ticket):
    return db.session.get(Ticket, ticket.id)


def test_full_lifecycle_open_to_closed(client, emp_user, tech_user):
    ticket = make_ticket(emp_user)
    ref = ticket.reference_id

    login(client, 'test_tech')
    assert client.post(f'/technician/claim/{ref}').status_code == 302
    t = _reload(ticket)
    assert t.status == S.ASSIGNED and t.technician_id == tech_user.id

    _status(client, ref, S.IN_PROGRESS)
    t = _reload(ticket)
    assert t.status == S.IN_PROGRESS and t.first_responded_at is not None

    _status(client, ref, S.RESOLVED, resolution_summary='Replaced faulty NIC driver and verified connectivity.')
    t = _reload(ticket)
    assert t.status == S.RESOLVED and t.resolved_at is not None
    assert t.resolution_summary.startswith('Replaced faulty NIC')
    logout(client)

    login(client, 'test_emp')
    _status(client, ref, S.CLOSED)
    t = _reload(ticket)
    assert t.status == S.CLOSED and t.closed_at is not None

    history = [(h.old_status, h.new_status) for h in
               TicketStatusHistory.query.filter_by(ticket_id=ticket.id).order_by(TicketStatusHistory.id)]
    assert history == [(S.OPEN, S.ASSIGNED), (S.ASSIGNED, S.IN_PROGRESS), (S.IN_PROGRESS, S.RESOLVED), (S.RESOLVED, S.CLOSED)]
    assert AuditLog.query.filter_by(action='TICKET_STATUS_CHANGE', entity_id=ref).count() == 3
    assert AuditLog.query.filter_by(action='TICKET_CLAIM', entity_id=ref).count() == 1


def test_invalid_transition_is_rejected(client, admin_user, emp_user):
    ticket = make_ticket(emp_user)
    login(client, 'test_admin')
    _status(client, ticket.reference_id, S.RESOLVED, resolution_summary='Skipping straight to resolved')
    assert _reload(ticket).status == S.OPEN
    assert AuditLog.query.filter_by(action='TICKET_TRANSITION_REJECTED').count() == 1
    # Assigned requires a technician
    _status(client, ticket.reference_id, S.ASSIGNED)
    assert _reload(ticket).status == S.OPEN


def test_unknown_status_value_rejected(client, admin_user, emp_user, tech_user):
    ticket = make_ticket(emp_user, technician=tech_user, status=S.IN_PROGRESS)
    login(client, 'test_admin')
    _status(client, ticket.reference_id, 'Hacked')
    assert _reload(ticket).status == S.IN_PROGRESS


def test_resolution_requires_summary(client, emp_user, tech_user):
    ticket = make_ticket(emp_user, technician=tech_user, status=S.IN_PROGRESS)
    login(client, 'test_tech')
    _status(client, ticket.reference_id, S.RESOLVED, resolution_summary='short')
    assert _reload(ticket).status == S.IN_PROGRESS
    _status(client, ticket.reference_id, S.RESOLVED)
    assert _reload(ticket).status == S.IN_PROGRESS


def test_technician_cannot_work_unclaimed_or_foreign_tickets(client, emp_user, tech_user, other_tech):
    queue = make_ticket(emp_user)
    foreign = make_ticket(emp_user, technician=other_tech, status=S.ASSIGNED)
    login(client, 'test_tech')
    _status(client, queue.reference_id, S.CLOSED)
    assert _reload(queue).status == S.OPEN
    assert _status(client, foreign.reference_id, S.IN_PROGRESS).status_code == 403
    assert _reload(foreign).status == S.ASSIGNED


def test_employee_allowed_transitions(app, emp_user, tech_user):
    ticket = make_ticket(emp_user, technician=tech_user, status=S.IN_PROGRESS)
    assert allowed_transitions(emp_user, ticket) == []
    ticket.status = S.RESOLVED
    assert set(allowed_transitions(emp_user, ticket)) == {S.CLOSED, S.IN_PROGRESS}


def test_employee_can_reopen_resolved_ticket_and_sla_restarts(client, emp_user, tech_user):
    ticket = make_ticket(emp_user, technician=tech_user, status=S.RESOLVED,
                         created_at=utcnow() - timedelta(days=3))
    t = _reload(ticket)
    t.resolved_at = utcnow() - timedelta(days=2)
    db.session.commit()
    login(client, 'test_emp')
    _status(client, ticket.reference_id, S.IN_PROGRESS, note='Still broken after reboot')
    t = _reload(ticket)
    assert t.status == S.IN_PROGRESS and t.resolved_at is None
    assert t.resolution_due_at > utcnow()  # fresh resolution window
    assert AuditLog.query.filter_by(action='TICKET_REOPEN').count() == 1
    assert Notification.query.filter_by(user_id=tech_user.id).count() == 1


def test_closed_ticket_reopen_window(client, emp_user, tech_user):
    ticket = make_ticket(emp_user, technician=tech_user, status=S.CLOSED)
    t = _reload(ticket)
    t.closed_at = utcnow() - timedelta(days=30)
    db.session.commit()
    login(client, 'test_emp')
    _status(client, ticket.reference_id, S.IN_PROGRESS)
    assert _reload(ticket).status == S.CLOSED  # window expired


def test_employee_cannot_close_other_employees_ticket(client, emp_user, other_emp_user, tech_user):
    ticket = make_ticket(other_emp_user, technician=tech_user, status=S.RESOLVED)
    login(client, 'test_emp')
    assert _status(client, ticket.reference_id, S.CLOSED).status_code == 403
    assert _reload(ticket).status == S.RESOLVED


def test_admin_assignment_notifies_and_audits(client, admin_user, emp_user, tech_user, other_tech):
    ticket = make_ticket(emp_user)
    login(client, 'test_admin')
    client.post(f'/tickets/{ticket.reference_id}/assign', data={'technician_id': tech_user.id})
    t = _reload(ticket)
    assert t.technician_id == tech_user.id and t.status == S.ASSIGNED
    assert Notification.query.filter_by(user_id=tech_user.id).count() == 1
    assert Notification.query.filter_by(user_id=emp_user.id).count() == 1

    client.post(f'/tickets/{ticket.reference_id}/assign', data={'technician_id': other_tech.id})
    assert _reload(ticket).technician_id == other_tech.id
    assert Notification.query.filter_by(user_id=tech_user.id).count() == 2  # told about the reassignment

    client.post(f'/tickets/{ticket.reference_id}/assign', data={'technician_id': 0})
    t = _reload(ticket)
    assert t.technician_id is None and t.status == S.OPEN
    assert AuditLog.query.filter_by(action='TICKET_ASSIGNMENT_CHANGE').count() == 3


def test_cannot_assign_to_employee_or_inactive_user(client, admin_user, emp_user, other_emp_user, tech_user):
    ticket = make_ticket(emp_user)
    login(client, 'test_admin')
    client.post(f'/tickets/{ticket.reference_id}/assign', data={'technician_id': other_emp_user.id})
    assert _reload(ticket).technician_id is None
    tech_user.is_active = False
    db.session.commit()
    client.post(f'/tickets/{ticket.reference_id}/assign', data={'technician_id': tech_user.id})
    assert _reload(ticket).technician_id is None


def test_priority_change_recalculates_sla(client, emp_user, tech_user):
    ticket = make_ticket(emp_user, technician=tech_user, status=S.IN_PROGRESS, priority='Low')
    login(client, 'test_tech')
    client.post(f'/tickets/{ticket.reference_id}/priority', data={'priority': 'Critical'})
    t = _reload(ticket)
    assert t.priority == 'Critical'
    assert abs((t.resolution_due_at - t.created_at) - timedelta(hours=4)) < timedelta(seconds=2)
    assert AuditLog.query.filter_by(action='TICKET_PRIORITY_CHANGE').count() == 1


def test_public_comment_notifies_other_party_and_records_first_response(client, emp_user, tech_user):
    ticket = make_ticket(emp_user, technician=tech_user, status=S.ASSIGNED)
    login(client, 'test_tech')
    client.post(f'/tickets/{ticket.reference_id}/comment', data={'content': 'Looking into it now.'})
    assert _reload(ticket).first_responded_at is not None
    assert Notification.query.filter_by(user_id=emp_user.id).count() == 1
    logout(client)
    login(client, 'test_emp')
    client.post(f'/tickets/{ticket.reference_id}/comment', data={'content': 'Thanks, it is urgent.'})
    assert Notification.query.filter_by(user_id=tech_user.id).count() == 1


def test_closed_ticket_rejects_comments(client, emp_user, tech_user):
    ticket = make_ticket(emp_user, technician=tech_user, status=S.CLOSED)
    login(client, 'test_emp')
    client.post(f'/tickets/{ticket.reference_id}/comment', data={'content': 'One more thing'})
    assert len(_reload(ticket).comments) == 0


def test_notifications_mark_read(client, emp_user, tech_user):
    ticket = make_ticket(emp_user, technician=tech_user, status=S.ASSIGNED)
    login(client, 'test_tech')
    client.post(f'/tickets/{ticket.reference_id}/comment', data={'content': 'Update one'})
    client.post(f'/tickets/{ticket.reference_id}/comment', data={'content': 'Update two'})
    logout(client)
    login(client, 'test_emp')
    assert client.get('/api/notifications/unread-count').get_json()['unread_count'] == 2
    first = Notification.query.filter_by(user_id=emp_user.id).first()
    resp = client.get(f'/notifications/{first.id}/open')
    assert resp.status_code == 302 and ticket.reference_id in resp.headers['Location']
    assert client.get('/api/notifications/unread-count').get_json()['unread_count'] == 1
    client.post('/notifications/read-all', headers={'X-Requested-With': 'XMLHttpRequest'})
    assert client.get('/api/notifications/unread-count').get_json()['unread_count'] == 0


def test_cannot_read_other_users_notifications(client, emp_user, other_emp_user, tech_user):
    ticket = make_ticket(other_emp_user, technician=tech_user, status=S.ASSIGNED)
    login(client, 'test_tech')
    client.post(f'/tickets/{ticket.reference_id}/comment', data={'content': 'Private update'})
    logout(client)
    theirs = Notification.query.filter_by(user_id=other_emp_user.id).one()
    login(client, 'test_emp')
    assert client.post(f'/notifications/{theirs.id}/read').status_code == 404
    assert db.session.get(Notification, theirs.id).is_read is False
    assert b'Private update' not in client.get('/notifications').data
