import pytest
from app.extensions import db
from app.models import Ticket, TicketStatus, TicketPriority, TicketCategory


def test_ticket_creation(client, app, emp_user):
    """Test incident ticket creation and reference generation."""
    client.post('/auth/login', data={'username_or_email': 'test_emp', 'password': 'EmpSecure123!'})
    
    with app.app_context():
        cat = TicketCategory.query.first()
        cat_id = cat.id

    response = client.post('/tickets/create', data={
        'title': 'Automated Latency Alarm on EC2 Fleet',
        'category_id': cat_id,
        'priority': TicketPriority.HIGH,
        'affected_system': 'i-0918237faec2',
        'department': 'DevOps',
        'description': 'Target response time exceeded 2000ms threshold for 5 consecutive minutes.'
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        ticket = Ticket.query.filter_by(title='Automated Latency Alarm on EC2 Fleet').first()
        assert ticket is not None
        assert ticket.reference_id.startswith('INC-')
        assert ticket.status == TicketStatus.OPEN
        assert ticket.priority == TicketPriority.HIGH
        assert ticket.response_due_at is not None
        assert ticket.resolution_due_at is not None


def test_status_transitions(client, app, tech_user, emp_user):
    """Test valid lifecycle status transitions and audit history logging."""
    with app.app_context():
        cat = TicketCategory.query.first()
        ticket = Ticket(
            reference_id='INC-2026-88801',
            title='RDS Storage Alert',
            description='FreeStorageSpace metric is under 10%',
            category_id=cat.id,
            priority=TicketPriority.MEDIUM,
            status=TicketStatus.OPEN,
            creator_id=emp_user.id
        )
        db.session.add(ticket)
        db.session.commit()

    # Login as technician
    client.post('/auth/login', data={'username_or_email': 'test_tech', 'password': 'TechSecure123!'})

    # Step 1: Claim/Assign Ticket
    client.post('/technician/claim/INC-2026-88801', follow_redirects=True)
    with app.app_context():
        t = Ticket.query.filter_by(reference_id='INC-2026-88801').first()
        assert t.status == TicketStatus.ASSIGNED
        assert t.technician_id == tech_user.id

    # Step 2: Transition to In Progress
    client.post('/tickets/INC-2026-88801/update', data={
        'status': TicketStatus.IN_PROGRESS,
        'priority': TicketPriority.MEDIUM,
        'technician_id': tech_user.id,
        'affected_system': 'rds-primary-prod',
        'resolution_summary': ''
    }, follow_redirects=True)
    with app.app_context():
        t = Ticket.query.filter_by(reference_id='INC-2026-88801').first()
        assert t.status == TicketStatus.IN_PROGRESS

    # Step 3: Transition to Resolved
    client.post('/tickets/INC-2026-88801/update', data={
        'status': TicketStatus.RESOLVED,
        'priority': TicketPriority.MEDIUM,
        'technician_id': tech_user.id,
        'affected_system': 'rds-primary-prod',
        'resolution_summary': 'Allocated storage modified from 100GB to 250GB. CloudWatch alarm cleared.'
    }, follow_redirects=True)
    with app.app_context():
        t = Ticket.query.filter_by(reference_id='INC-2026-88801').first()
        assert t.status == TicketStatus.RESOLVED
        assert t.resolved_at is not None
        assert 'Allocated storage modified' in t.resolution_summary


def test_reopen_resolved_ticket(client, app, emp_user, tech_user):
    """Test authorized reopening of a resolved ticket."""
    with app.app_context():
        cat = TicketCategory.query.first()
        ticket = Ticket(
            reference_id='INC-2026-88802',
            title='VPN Gateway Packet Loss',
            description='Tunnel 1 experiencing 40% packet drops',
            category_id=cat.id,
            priority=TicketPriority.MEDIUM,
            status=TicketStatus.RESOLVED,
            creator_id=emp_user.id,
            technician_id=tech_user.id
        )
        db.session.add(ticket)
        db.session.commit()

    client.post('/auth/login', data={'username_or_email': 'test_emp', 'password': 'EmpSecure123!'})
    response = client.post('/tickets/INC-2026-88802/reopen', follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        t = Ticket.query.filter_by(reference_id='INC-2026-88802').first()
        assert t.status == TicketStatus.IN_PROGRESS
        assert t.resolved_at is None
