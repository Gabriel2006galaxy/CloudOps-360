import pytest
from app.extensions import db
from app.models import Ticket, TicketStatus, TicketPriority, TicketCategory


def test_employee_denied_admin_routes(client, emp_user):
    """Verify that employee accounts are strictly denied access to admin views."""
    client.post('/auth/login', data={'username_or_email': 'test_emp', 'password': 'EmpSecure123!'})
    
    # Attempting to access admin user management
    response = client.get('/admin/users')
    assert response.status_code == 403

    # Attempting to access SLA configuration
    response = client.get('/admin/sla')
    assert response.status_code == 403

    # Attempting to access audit logs
    response = client.get('/admin/audit-logs')
    assert response.status_code == 403


def test_technician_denied_admin_user_management(client, tech_user):
    """Verify technicians cannot manage users or change SLA policies."""
    client.post('/auth/login', data={'username_or_email': 'test_tech', 'password': 'TechSecure123!'})
    
    response = client.get('/admin/users')
    assert response.status_code == 403

    response = client.get('/admin/sla')
    assert response.status_code == 403


def test_employee_cannot_view_other_employee_ticket(client, app, emp_user, other_emp_user):
    """Verify employee cannot view an incident ticket created by another employee."""
    # Create ticket owned by other_emp
    with app.app_context():
        cat = TicketCategory.query.first()
        ticket = Ticket(
            reference_id='INC-2026-99991',
            title='Confidential Internal Finance Outage',
            description='Sensitive payroll processing disruption',
            category_id=cat.id,
            priority=TicketPriority.HIGH,
            status=TicketStatus.OPEN,
            creator_id=other_emp_user.id
        )
        db.session.add(ticket)
        db.session.commit()

    # Log in as test_emp
    client.post('/auth/login', data={'username_or_email': 'test_emp', 'password': 'EmpSecure123!'})
    
    # Try to access other_emp's ticket
    response = client.get('/tickets/INC-2026-99991')
    assert response.status_code == 403


def test_prevent_privilege_escalation(client, app, emp_user):
    """Verify employees cannot escalate role via profile form submission."""
    client.post('/auth/login', data={'username_or_email': 'test_emp', 'password': 'EmpSecure123!'})
    
    # Send manipulated post request attempting to alter role
    response = client.post('/auth/profile', data={
        'full_name': 'Hacked Name',
        'department': 'Operations',
        'role': 'admin'  # Tampered field
    }, follow_redirects=True)

    with app.app_context():
        from app.models import User
        user = User.query.filter_by(username='test_emp').first()
        # Role must still be employee
        assert user.role == 'employee'


def test_registration_cannot_create_admin(client, app):
    """Verify that public registration rejects or ignores attempts to set role to admin."""
    response = client.post('/auth/register', data={
        'full_name': 'Attacker User',
        'username': 'attacker1',
        'email': 'attacker1@cloudops.local',
        'department': 'Security',
        'role': 'admin',  # Attempted privilege escalation
        'password': 'AttackPassword123!',
        'confirm_password': 'AttackPassword123!'
    }, follow_redirects=True)

    with app.app_context():
        from app.models import User, UserRole
        user = User.query.filter_by(username='attacker1').first()
        if user:
            # Must be forced to employee, never admin
            assert user.role == UserRole.EMPLOYEE


def test_secrets_and_credentials_not_exposed(client, app, admin_user):
    """Verify that sensitive configuration secrets and password hashes are never exposed in responses."""
    # Check landing page and public routes
    response = client.get('/')
    assert b'SECRET_KEY' not in response.data
    assert b'AdminSecure123!' not in response.data

    # Log in as admin and view user list
    client.post('/auth/login', data={'username_or_email': 'test_admin', 'password': 'AdminSecure123!'})
    response = client.get('/admin/users')
    assert response.status_code == 200
    # Password hashes must never appear in raw HTML or tables
    assert b'scrypt:' not in response.data
    assert b'pbkdf2:' not in response.data

