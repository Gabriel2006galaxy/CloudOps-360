"""Auto-assignment, technician availability and skills, and customer satisfaction ratings."""
from datetime import timedelta

from app.extensions import db
from app.models import (
    AuditLog, Notification, Ticket, TicketCategory, TicketPriority, TicketStatus, TicketStatusHistory, User,
    utcnow,
)
from app.services import metrics
from app.services.assignment import (
    _apply_assignment, choose_technician, release_returned_technicians, run_auto_assign, set_availability,
)
from app.services.settings import DEFAULT_WAIT_MINUTES, get_auto_assign_config, save_auto_assign_config
from conftest import login, logout, make_ticket

S = TicketStatus
P = TicketPriority


def _configure(enabled=True, max_open=10, waits=None):
    save_auto_assign_config(enabled, max_open, waits or dict(DEFAULT_WAIT_MINUTES))
    db.session.commit()


def _create(client, title='Laptop VPN disconnects every hour', priority=P.HIGH, category=None):
    category = category or TicketCategory.query.first()
    resp = client.post('/tickets/create', data={
        'title': title, 'description': 'The VPN client drops the tunnel roughly every hour.',
        'category_id': category.id, 'priority': priority,
    })
    assert resp.status_code == 302
    return Ticket.query.filter_by(title=title).one()


def _reload(obj):
    return db.session.get(type(obj), obj.id)


# ---------------- new tickets ---------------- #

def test_new_ticket_goes_to_least_busy_technician(client, emp_user, tech_user, other_tech):
    _configure()
    make_ticket(emp_user, technician=tech_user, status=S.ASSIGNED, priority=P.HIGH)

    login(client, 'test_emp')
    ticket = _create(client)
    assert ticket.technician_id == other_tech.id and ticket.status == S.ASSIGNED

    history = TicketStatusHistory.query.filter_by(ticket_id=ticket.id, new_status=S.ASSIGNED).one()
    assert history.changed_by_id is None and history.actor_name == 'System (auto-assign)'
    assert 'Auto-assigned to Other Technician' in history.notes and 'lightest workload' in history.notes
    audit = AuditLog.query.filter_by(action='TICKET_AUTO_ASSIGN', entity_id=ticket.reference_id).one()
    assert audit.user_id is None
    assigned_notice = Notification.query.filter_by(user_id=other_tech.id, title=f'Auto-assigned: {ticket.reference_id}').one()
    assert 'You now have 1 open ticket.' in assigned_notice.message
    # The chosen technician gets the assignment notice instead of the generic "new incident" one
    assert Notification.query.filter_by(user_id=other_tech.id, title=f'New incident {ticket.reference_id}').count() == 0
    team_notice = Notification.query.filter_by(user_id=tech_user.id, title=f'New incident {ticket.reference_id}').one()
    assert 'Auto-assigned to Other Technician' in team_notice.message


def test_when_every_technician_is_free_the_ticket_waits_to_be_claimed(client, admin_user, emp_user, tech_user, other_tech):
    _configure()
    make_ticket(emp_user, title='Already waiting')
    login(client, 'test_emp')
    ticket = _create(client)
    assert ticket.technician_id is None and ticket.status == S.OPEN

    # Every technician (and the admin, for information) hears how many tickets are waiting
    for user in (tech_user, other_tech, admin_user):
        notice = Notification.query.filter_by(user_id=user.id,
                                              title=f'New ticket in the queue: {ticket.reference_id}').one()
        assert '2 tickets are waiting to be claimed' in notice.message
    assert Notification.query.filter(Notification.title.like('Needs assignment%')).count() == 0
    logout(client)

    login(client, 'test_tech')
    assert client.post(f'/technician/claim/{ticket.reference_id}').status_code == 302
    assert _reload(ticket).technician_id == tech_user.id


def test_switched_off_leaves_new_tickets_in_the_queue(client, emp_user, tech_user, other_tech):
    _configure(enabled=False)
    make_ticket(emp_user, technician=tech_user, status=S.ASSIGNED)
    login(client, 'test_emp')
    ticket = _create(client)
    assert ticket.technician_id is None and ticket.status == S.OPEN


# ---------------- choosing a technician ---------------- #

def test_workload_points_weight_critical_work(app, emp_user, tech_user, other_tech):
    make_ticket(emp_user, technician=tech_user, status=S.IN_PROGRESS, priority=P.CRITICAL)  # 4 points
    make_ticket(emp_user, technician=other_tech, status=S.ASSIGNED, priority=P.LOW)         # 1 point
    make_ticket(emp_user, technician=other_tech, status=S.ASSIGNED, priority=P.LOW)         # 1 point
    ticket = make_ticket(emp_user)
    chosen, reason = choose_technician(ticket, get_auto_assign_config())
    assert chosen.id == other_tech.id
    assert 'Other Technician 2 pts' in reason and 'Technician User 4 pts' in reason


def test_specialists_come_first(app, emp_user, tech_user, other_tech):
    database = TicketCategory.query.filter_by(name='Database & Storage').one()
    other_tech.skills = [database]
    db.session.commit()
    make_ticket(emp_user, technician=other_tech, status=S.ASSIGNED, priority=P.LOW)
    ticket = make_ticket(emp_user, category=database)
    chosen, reason = choose_technician(ticket, get_auto_assign_config())
    assert chosen.id == other_tech.id and 'specialist in Database & Storage' in reason

    general = make_ticket(emp_user)  # other category: the least busy technician wins
    chosen, _ = choose_technician(general, get_auto_assign_config())
    assert chosen.id == tech_user.id


def test_away_technicians_never_get_tickets(app, emp_user, tech_user, other_tech):
    set_availability(other_tech, False, note='Sick leave')
    db.session.commit()
    make_ticket(emp_user, technician=tech_user, status=S.ASSIGNED, priority=P.CRITICAL)
    ticket = make_ticket(emp_user)
    chosen, _ = choose_technician(ticket, get_auto_assign_config())
    assert chosen.id == tech_user.id

    set_availability(tech_user, False)
    db.session.commit()
    chosen, reason = choose_technician(ticket, get_auto_assign_config())
    assert chosen is None and 'away' in reason


def test_away_technicians_are_not_notified_about_new_tickets(client, emp_user, tech_user, other_tech):
    _configure()
    set_availability(other_tech, False, note='On leave')
    db.session.commit()
    login(client, 'test_emp')
    ticket = _create(client)
    title = f'New ticket in the queue: {ticket.reference_id}'
    assert Notification.query.filter_by(user_id=tech_user.id, title=title).count() == 1
    assert Notification.query.filter_by(user_id=other_tech.id, title=title).count() == 0


def test_maximum_open_tickets_per_technician(client, admin_user, emp_user, tech_user, other_tech):
    _configure(max_open=1)
    make_ticket(emp_user, technician=tech_user, status=S.ASSIGNED)
    make_ticket(emp_user, technician=other_tech, status=S.ASSIGNED)
    login(client, 'test_emp')
    ticket = _create(client)
    assert ticket.technician_id is None
    chosen, reason = choose_technician(ticket, get_auto_assign_config())
    assert chosen is None and 'maximum of 1' in reason
    # Nobody can take it, so (only now) the administrator is asked to step in
    alert = Notification.query.filter_by(user_id=admin_user.id, title=f'Needs assignment: {ticket.reference_id}').one()
    assert alert.type == 'warning' and 'assign it manually' in alert.message


def test_away_period_ends_automatically(app, tech_user):
    tech_user.is_available = False
    tech_user.away_until = utcnow() - timedelta(minutes=1)
    db.session.commit()
    assert not tech_user.is_away
    returned = release_returned_technicians()
    db.session.commit()
    assert returned == [tech_user]
    assert _reload(tech_user).is_available and _reload(tech_user).away_until is None
    assert AuditLog.query.filter_by(action='TECH_AVAILABILITY_AUTO_RETURN').count() == 1


# ---------------- queue sweep ---------------- #

def test_unclaimed_tickets_are_assigned_after_the_wait_time(app, emp_user, tech_user):
    _configure()  # Medium waits 240 minutes
    old = make_ticket(emp_user, created_at=utcnow() - timedelta(hours=5), title='Old queued ticket')
    young = make_ticket(emp_user, created_at=utcnow() - timedelta(hours=1), title='Young queued ticket')
    assigned, waiting = run_auto_assign()
    db.session.commit()
    assert [t.id for t, _, _ in assigned] == [old.id]
    assert [t.id for t, _ in waiting] == [young.id]
    assert _reload(old).technician_id == tech_user.id and _reload(old).status == S.ASSIGNED
    assert 'unclaimed for' in TicketStatusHistory.query.filter_by(ticket_id=old.id, new_status=S.ASSIGNED).one().notes
    assert Notification.query.filter_by(user_id=emp_user.id, title=f'Technician update: {old.reference_id}').count() == 1


def test_sweep_runs_during_normal_page_loads(client, emp_user, tech_user):
    _configure()
    old = make_ticket(emp_user, created_at=utcnow() - timedelta(hours=5))
    login(client, 'test_emp')
    client.get('/dashboard')
    assert _reload(old).technician_id == tech_user.id


def test_assignment_is_applied_only_once(app, emp_user, tech_user, other_tech):
    ticket = make_ticket(emp_user)
    assert _apply_assignment(ticket, tech_user, 'first worker')
    assert not _apply_assignment(ticket, other_tech, 'second worker')
    db.session.commit()
    assert _reload(ticket).technician_id == tech_user.id
    assert TicketStatusHistory.query.filter_by(ticket_id=ticket.id).count() == 1


# ---------------- administrator pages ---------------- #

def test_no_admin_action_is_needed_to_assign_the_queue(client, runner, admin_user, emp_user, tech_user):
    _configure()
    ticket = make_ticket(emp_user)
    login(client, 'test_admin')
    # There is no manual "run" button: assignment happens on its own
    assert client.post('/admin/auto-assign/run').status_code == 404
    assert b'Run auto-assign now' not in client.get('/admin/auto-assign').data
    logout(client)

    # Operators can still force it from cron/SSH
    result = runner.invoke(args=['auto-assign', '--now'])
    assert 'ASSIGNED' in result.output and _reload(ticket).technician_id == tech_user.id
    history = TicketStatusHistory.query.filter_by(ticket_id=ticket.id, new_status=S.ASSIGNED).one()
    assert history.changed_by_id is None and 'flask auto-assign --now' in history.notes


def test_settings_page_limits_max_open_between_1_and_50(client, admin_user, emp_user):
    waits = {'wait_critical': 30, 'wait_high': 120, 'wait_medium': 240, 'wait_low': 720}
    login(client, 'test_admin')
    assert client.get('/admin/auto-assign').status_code == 200

    for bad in (0, 51):
        assert client.post('/admin/auto-assign', data={'enabled': 'y', 'max_open': bad, **waits}).status_code == 400
        assert get_auto_assign_config().max_open == 10

    resp = client.post('/admin/auto-assign', data={'max_open': 25, **waits, 'wait_low': 60})
    assert resp.status_code == 302
    config = get_auto_assign_config()
    assert config.max_open == 25 and config.enabled is False and config.wait_minutes[P.LOW] == 60
    assert AuditLog.query.filter_by(action='ADMIN_AUTO_ASSIGN_SETTINGS').count() == 1
    logout(client)

    login(client, 'test_emp')
    assert client.get('/admin/auto-assign').status_code == 403


def test_admin_sets_technician_skills_and_availability(client, admin_user, tech_user, emp_user):
    category = TicketCategory.query.first()
    back_on = (utcnow() + timedelta(days=3)).date()
    login(client, 'test_admin')
    resp = client.post(f'/admin/users/{tech_user.id}/technician-settings', data={
        'skills': [category.id], 'status': 'away', 'away_note': 'Annual leave', 'back_on': back_on.isoformat(),
    })
    assert resp.status_code == 302
    tech = _reload(tech_user)
    assert [c.id for c in tech.skills] == [category.id]
    assert tech.is_away and tech.away_note == 'Annual leave' and tech.away_until.date() == back_on
    assert AuditLog.query.filter_by(action='ADMIN_TECH_SKILLS_CHANGE').count() == 1
    assert AuditLog.query.filter_by(action='TECH_AVAILABILITY_CHANGE').count() == 1
    assert b'Annual leave' in client.get(f'/admin/users/{tech_user.id}/edit').data

    client.post(f'/admin/users/{emp_user.id}/technician-settings', data={'status': 'away'})
    assert not _reload(emp_user).skills and _reload(emp_user).is_available


# ---------------- technician status ---------------- #

def test_technician_asks_for_leave_and_an_admin_approves_it(client, admin_user, emp_user, tech_user):
    make_ticket(emp_user, technician=tech_user, status=S.IN_PROGRESS)
    login(client, 'test_tech')
    # Going away directly is not possible any more
    client.post('/technician/availability', data={'status': 'away', 'away_note': 'Sick'})
    assert not _reload(tech_user).is_away

    back_on = (utcnow() + timedelta(days=3)).date()
    resp = client.post('/technician/leave-request', data={'away_note': 'Sick leave', 'back_on': back_on.isoformat()})
    assert resp.status_code == 302
    tech = _reload(tech_user)
    assert tech.has_leave_request and not tech.is_away  # still available until an admin approves
    assert Notification.query.filter_by(user_id=admin_user.id, title='Leave request: Technician User').count() == 1
    assert 'waiting for an administrator' in client.get('/technician/workload').get_data(as_text=True)
    logout(client)

    login(client, 'test_admin')
    page = client.get('/dashboard/admin').get_data(as_text=True)
    assert 'value="approve"' in page and 'Sick leave' in page
    assert 'Leave requested' in client.get('/admin/users').get_data(as_text=True)
    resp = client.post(f'/admin/users/{tech_user.id}/leave-request', data={'decision': 'approve'})
    assert resp.status_code == 302
    tech = _reload(tech_user)
    assert tech.is_away and tech.away_note == 'Sick leave' and tech.away_until.date() == back_on
    assert not tech.has_leave_request
    assert Notification.query.filter_by(user_id=tech_user.id, title='Leave approved').count() == 1
    page = client.get('/dashboard/admin').get_data(as_text=True)
    assert 'value="approve"' not in page and 'still has <strong>1</strong> open ticket' in page
    assert AuditLog.query.filter_by(action='TECH_LEAVE_APPROVED').count() == 1
    logout(client)

    login(client, 'test_tech')
    assert 'Your leave was approved' in client.get('/technician/workload').get_data(as_text=True)
    client.post('/technician/availability')
    assert not _reload(tech_user).is_away


def test_leave_request_rules(client, admin_user, emp_user, tech_user):
    login(client, 'test_tech')
    client.post('/technician/leave-request', data={'away_note': ''})
    assert not _reload(tech_user).has_leave_request  # a reason is required
    yesterday = (utcnow() - timedelta(days=1)).date().isoformat()
    client.post('/technician/leave-request', data={'away_note': 'Holiday', 'back_on': yesterday})
    assert not _reload(tech_user).has_leave_request  # past return dates are rejected

    client.post('/technician/leave-request', data={'away_note': 'Holiday'})
    assert _reload(tech_user).has_leave_request
    client.post('/technician/leave-request/cancel')
    assert not _reload(tech_user).has_leave_request
    client.post('/technician/leave-request', data={'away_note': 'Training'})
    # a technician cannot approve a leave request, not even their own
    assert client.post(f'/admin/users/{tech_user.id}/leave-request', data={'decision': 'approve'}).status_code == 403
    logout(client)

    login(client, 'test_emp')
    assert client.post('/technician/leave-request', data={'away_note': 'x'}).status_code == 403
    assert client.post(f'/admin/users/{tech_user.id}/leave-request', data={'decision': 'approve'}).status_code == 403
    logout(client)

    login(client, 'test_admin')
    assert client.post('/technician/leave-request', data={'away_note': 'x'}).status_code == 403
    assert client.post(f'/admin/users/{tech_user.id}/leave-request', data={'decision': 'maybe'}).status_code == 400
    client.post(f'/admin/users/{tech_user.id}/leave-request', data={'decision': 'reject'})
    tech = _reload(tech_user)
    assert not tech.has_leave_request and not tech.is_away
    assert Notification.query.filter_by(user_id=tech_user.id, title='Leave request rejected').count() == 1
    client.post(f'/admin/users/{tech_user.id}/leave-request', data={'decision': 'approve'})
    assert not _reload(tech_user).is_away  # nothing left to approve
    assert [a.action for a in AuditLog.query.filter(AuditLog.action.like('TECH_LEAVE_%'))
            .order_by(AuditLog.id)] == ['TECH_LEAVE_REQUESTED', 'TECH_LEAVE_CANCELLED', 'TECH_LEAVE_REQUESTED',
                                        'TECH_LEAVE_REJECTED']


# ---------------- customer satisfaction ---------------- #

def _closed_ticket(creator, technician):
    ticket = make_ticket(creator, technician=technician, status=S.CLOSED)
    ticket.resolved_at = utcnow() - timedelta(hours=2)
    ticket.closed_at = utcnow() - timedelta(hours=1)
    db.session.commit()
    return ticket


def test_reporter_rates_a_closed_ticket_once(client, emp_user, tech_user):
    ticket = _closed_ticket(emp_user, tech_user)
    login(client, 'test_emp')
    assert b'How was the support' in client.get(f'/tickets/{ticket.reference_id}').data

    client.post(f'/tickets/{ticket.reference_id}/rate', data={'rating': 5, 'comment': 'Quick and friendly.'})
    rated = _reload(ticket)
    assert rated.satisfaction_rating == 5 and rated.satisfaction_comment == 'Quick and friendly.' and rated.rated_at
    assert AuditLog.query.filter_by(action='TICKET_RATED', entity_id=ticket.reference_id).count() == 1
    assert Notification.query.filter_by(user_id=tech_user.id, title=f'New rating: {ticket.reference_id}').count() == 1

    client.post(f'/tickets/{ticket.reference_id}/rate', data={'rating': 1})
    assert _reload(ticket).satisfaction_rating == 5
    assert AuditLog.query.filter_by(action='TICKET_RATING_REJECTED').count() == 1
    assert b'Customer satisfaction' in client.get(f'/tickets/{ticket.reference_id}').data


def test_rating_rules(client, emp_user, other_emp_user, tech_user):
    resolved = make_ticket(emp_user, technician=tech_user, status=S.RESOLVED)
    cancelled = make_ticket(emp_user, status=S.CLOSED)  # closed without being resolved
    closed = _closed_ticket(emp_user, tech_user)

    login(client, 'test_emp')
    client.post(f'/tickets/{resolved.reference_id}/rate', data={'rating': 4})
    client.post(f'/tickets/{cancelled.reference_id}/rate', data={'rating': 4})
    client.post(f'/tickets/{closed.reference_id}/rate', data={'rating': 6})
    assert all(_reload(t).satisfaction_rating is None for t in (resolved, cancelled, closed))
    logout(client)

    login(client, 'other_emp')
    assert client.post(f'/tickets/{closed.reference_id}/rate', data={'rating': 4}).status_code == 403
    logout(client)
    login(client, 'test_tech')
    client.post(f'/tickets/{closed.reference_id}/rate', data={'rating': 4})
    assert _reload(closed).satisfaction_rating is None


def test_satisfaction_metrics(client, admin_user, emp_user, tech_user):
    for stars in (5, 3):
        ticket = _closed_ticket(emp_user, tech_user)
        ticket.satisfaction_rating = stars
    db.session.commit()

    summary = metrics.rating_summary()
    assert summary['avg'] == 4.0 and summary['count'] == 2 and summary['distribution'][5] == 1
    row = next(w for w in metrics.technician_workload() if w['user'].id == tech_user.id)
    assert row['avg_rating'] == 4.0 and row['rating_count'] == 2

    login(client, 'test_admin')
    page = client.get('/admin/analytics').get_data(as_text=True)
    assert 'Customer satisfaction' in page and '★ 4.0 / 5' in page


def test_new_pages_render_with_seed_data_and_auto_assign_on(app):
    import contextlib
    import io
    from scripts.seed_data import seed_database
    with contextlib.redirect_stdout(io.StringIO()):
        seed_database()
    _configure()
    client = app.test_client()
    client.post('/auth/login', data={'username_or_email': 'admin', 'password': 'AdminPass123!'})
    for path in ('/dashboard/admin', '/admin/auto-assign', '/admin/analytics', '/admin/users',
                 f"/admin/users/{User.query.filter_by(username='tech_sarah').one().id}/edit"):
        assert client.get(path).status_code == 200, path
    client.post('/auth/logout')
    client.post('/auth/login', data={'username_or_email': 'tech_sarah', 'password': 'TechPass123!'})
    assert client.get('/technician/workload').status_code == 200
    rated = Ticket.query.filter(Ticket.satisfaction_rating.isnot(None)).count()
    assert rated == 4
