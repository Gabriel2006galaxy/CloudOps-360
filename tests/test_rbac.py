"""Role-based access control and privilege-escalation attempts."""
import pytest

from app.extensions import db
from app.models import AuditLog, Ticket, TicketStatus, User, UserRole
from conftest import login, make_ticket

ADMIN_PAGES = ['/admin/users', '/admin/categories', '/admin/sla', '/admin/audit-logs',
               '/admin/audit-logs/export.csv', '/admin/analytics', '/dashboard/admin']


@pytest.mark.parametrize('username,fixture', [('test_emp', 'emp_user'), ('test_tech', 'tech_user')])
def test_non_admins_denied_admin_pages(request, client, username, fixture):
    request.getfixturevalue(fixture)
    login(client, username)
    for path in ADMIN_PAGES:
        assert client.get(path).status_code == 403, path
    assert AuditLog.query.filter_by(action='ACCESS_DENIED_RBAC').count() >= len(ADMIN_PAGES) - 1


def test_employee_denied_technician_pages(client, emp_user):
    login(client, 'test_emp')
    assert client.get('/technician/workload').status_code == 403
    assert client.get('/dashboard/technician').status_code == 403


def test_employee_cannot_view_other_employees_ticket(client, emp_user, other_emp_user):
    ticket = make_ticket(other_emp_user, title='Confidential payroll outage')
    login(client, 'test_emp')
    resp = client.get(f'/tickets/{ticket.reference_id}')
    assert resp.status_code == 403
    assert b'Confidential payroll outage' not in resp.data
    assert AuditLog.query.filter_by(action='TICKET_UNAUTHORIZED_ACCESS').count() == 1


def test_employee_ticket_list_is_scoped_to_own_tickets(client, emp_user, other_emp_user):
    make_ticket(emp_user, title='Mine visible')
    make_ticket(other_emp_user, title='Someone else hidden')
    login(client, 'test_emp')
    body = client.get('/tickets').data
    assert b'Mine visible' in body and b'Someone else hidden' not in body
    # Search cannot be used to discover other tickets either
    assert b'Someone else hidden' not in client.get('/tickets?q=hidden').data


def test_technician_sees_assigned_and_queue_only(client, emp_user, tech_user, other_tech):
    mine = make_ticket(emp_user, technician=tech_user, status=TicketStatus.ASSIGNED, title='Assigned to me')
    queue = make_ticket(emp_user, title='Unassigned queue item')
    theirs = make_ticket(emp_user, technician=other_tech, status=TicketStatus.IN_PROGRESS, title='Other tech work')
    login(client, 'test_tech')
    body = client.get('/tickets').data
    assert b'Assigned to me' in body and b'Unassigned queue item' in body and b'Other tech work' not in body
    assert client.get(f'/tickets/{mine.reference_id}').status_code == 200
    assert client.get(f'/tickets/{queue.reference_id}').status_code == 200
    assert client.get(f'/tickets/{theirs.reference_id}').status_code == 403


def test_admin_sees_everything(client, admin_user, emp_user, other_emp_user, tech_user):
    a = make_ticket(emp_user, title='Ticket A')
    b = make_ticket(other_emp_user, technician=tech_user, status=TicketStatus.ASSIGNED, title='Ticket B')
    login(client, 'test_admin')
    body = client.get('/tickets').data
    assert b'Ticket A' in body and b'Ticket B' in body
    assert client.get(f'/tickets/{b.reference_id}').status_code == 200


def test_employee_cannot_change_status_priority_or_assignment(client, emp_user, tech_user):
    ticket = make_ticket(emp_user, technician=tech_user, status=TicketStatus.IN_PROGRESS)
    login(client, 'test_emp')
    ref = ticket.reference_id
    client.post(f'/tickets/{ref}/status', data={'status': 'Resolved', 'resolution_summary': 'I fixed it myself!!'})
    client.post(f'/tickets/{ref}/priority', data={'priority': 'Critical'})
    assert client.post(f'/tickets/{ref}/assign', data={'technician_id': 0}).status_code == 403
    assert client.post(f'/tickets/{ref}/details', data={'affected_system': 'x'}).status_code == 403
    db.session.expire_all()
    t = db.session.get(Ticket, ticket.id)
    assert t.status == TicketStatus.IN_PROGRESS and t.priority == 'Medium' and t.technician_id == tech_user.id


def test_technician_cannot_assign_tickets_to_others(client, emp_user, tech_user, other_tech):
    ticket = make_ticket(emp_user, technician=tech_user, status=TicketStatus.ASSIGNED)
    login(client, 'test_tech')
    resp = client.post(f'/tickets/{ticket.reference_id}/assign', data={'technician_id': other_tech.id})
    assert resp.status_code == 403
    assert db.session.get(Ticket, ticket.id).technician_id == tech_user.id


def test_technician_cannot_claim_ticket_already_assigned(client, emp_user, tech_user, other_tech):
    ticket = make_ticket(emp_user, technician=other_tech, status=TicketStatus.ASSIGNED)
    login(client, 'test_tech')
    client.post(f'/technician/claim/{ticket.reference_id}')
    db.session.expire_all()
    assert db.session.get(Ticket, ticket.id).technician_id == other_tech.id


def test_profile_form_cannot_escalate_role(client, emp_user):
    login(client, 'test_emp')
    client.post('/auth/profile', data={'full_name': 'Hacked', 'department': 'Ops', 'role': 'admin', 'is_active': 'y'})
    db.session.expire_all()
    user = db.session.get(User, emp_user.id)
    assert user.role == UserRole.EMPLOYEE and user.full_name == 'Hacked'


def test_employee_cannot_use_admin_user_edit_endpoint(client, emp_user):
    login(client, 'test_emp')
    resp = client.post(f'/admin/users/{emp_user.id}/edit', data={
        'full_name': 'Employee User', 'email': 'emp@test.local', 'role': 'admin', 'is_active': 'y'})
    assert resp.status_code == 403
    db.session.expire_all()
    assert db.session.get(User, emp_user.id).role == UserRole.EMPLOYEE


def test_admin_cannot_demote_or_deactivate_self(client, admin_user):
    login(client, 'test_admin')
    resp = client.post(f'/admin/users/{admin_user.id}/edit', data={
        'full_name': 'Admin User', 'email': 'test_admin@test.local', 'role': 'employee', 'is_active': 'y'})
    assert resp.status_code == 400
    assert client.post(f'/admin/users/{admin_user.id}/toggle-status').status_code == 302
    db.session.expire_all()
    user = db.session.get(User, admin_user.id)
    assert user.role == UserRole.ADMIN and user.is_active


def test_admin_role_change_is_audited(client, admin_user, emp_user):
    login(client, 'test_admin')
    resp = client.post(f'/admin/users/{emp_user.id}/edit', data={
        'full_name': 'Employee User', 'email': 'test_emp@test.local', 'role': 'technician', 'is_active': 'y'})
    assert resp.status_code == 302
    assert db.session.get(User, emp_user.id).role == UserRole.TECHNICIAN
    log = AuditLog.query.filter_by(action='ADMIN_ROLE_CHANGE').one()
    assert 'employee -> technician' in log.details


def test_admin_can_create_user_with_role(client, admin_user):
    login(client, 'test_admin')
    resp = client.post('/admin/users', data={
        'full_name': 'New Tech', 'username': 'newtech', 'email': 'newtech@corp.local', 'role': 'technician',
        'password': 'TechStrong123', 'is_active': 'y'})
    assert resp.status_code == 302
    user = User.query.filter_by(username='newtech').one()
    assert user.role == UserRole.TECHNICIAN and user.check_password('TechStrong123')


def test_cannot_demote_technician_with_active_assignments(client, admin_user, emp_user, tech_user):
    make_ticket(emp_user, technician=tech_user, status=TicketStatus.ASSIGNED)
    login(client, 'test_admin')
    resp = client.post(f'/admin/users/{tech_user.id}/edit', data={
        'full_name': 'Technician User', 'email': 'test_tech@test.local', 'role': 'employee', 'is_active': 'y'})
    assert resp.status_code == 400
    assert db.session.get(User, tech_user.id).role == UserRole.TECHNICIAN
