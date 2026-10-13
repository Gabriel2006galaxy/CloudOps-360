import pytest
from app.extensions import db
from app.models import Ticket, TicketStatus, TicketPriority, TicketCategory, Comment


def test_internal_technician_note_privacy(client, app, emp_user, tech_user, admin_user):
    """
    CRITICAL SECURITY TEST:
    Verify that private internal technician notes are visible to technicians and admins,
    but NEVER leaked or rendered to employee clients.
    """
    with app.app_context():
        cat = TicketCategory.query.first()
        ticket = Ticket(
            reference_id='INC-2026-77701',
            title='Production S3 Bucket Policy Audit',
            description='Compliance review for S3 buckets',
            category_id=cat.id,
            priority=TicketPriority.MEDIUM,
            status=TicketStatus.IN_PROGRESS,
            creator_id=emp_user.id,
            technician_id=tech_user.id
        )
        db.session.add(ticket)
        db.session.flush()

        # Public comment
        c_public = Comment(
            ticket_id=ticket.id,
            user_id=emp_user.id,
            content='Public inquiry from employee regarding bucket status.',
            is_internal=False
        )
        # Private internal note
        c_internal = Comment(
            ticket_id=ticket.id,
            user_id=tech_user.id,
            content='CONFIDENTIAL ROOT CAUSE: Unpatched AWS IAM boundary allows unauthorized KMS decryption. DO NOT SHARE WITH CLIENT.',
            is_internal=True
        )
        db.session.add_all([c_public, c_internal])
        db.session.commit()

    # 1. Employee view check
    client.post('/auth/login', data={'username_or_email': 'test_emp', 'password': 'EmpSecure123!'})
    emp_resp = client.get('/tickets/INC-2026-77701')
    assert emp_resp.status_code == 200
    assert b'Public inquiry from employee' in emp_resp.data
    # The confidential note text MUST NOT exist in employee HTML!
    assert b'CONFIDENTIAL ROOT CAUSE' not in emp_resp.data
    assert b'Internal Tech Note (Restricted)' not in emp_resp.data

    # Logout
    client.get('/auth/logout')

    # 2. Technician view check
    client.post('/auth/login', data={'username_or_email': 'test_tech', 'password': 'TechSecure123!'})
    tech_resp = client.get('/tickets/INC-2026-77701')
    assert tech_resp.status_code == 200
    assert b'Public inquiry from employee' in tech_resp.data
    # Technician CAN see confidential note
    assert b'CONFIDENTIAL ROOT CAUSE' in tech_resp.data
    assert b'Internal Tech Note (Restricted)' in tech_resp.data


def test_employee_cannot_create_internal_note(client, app, emp_user):
    """Verify that employee comment submissions cannot set is_internal=True."""
    with app.app_context():
        cat = TicketCategory.query.first()
        ticket = Ticket(
            reference_id='INC-2026-77702',
            title='VPN Gateway Issue',
            description='VPN failing connection',
            category_id=cat.id,
            priority=TicketPriority.LOW,
            status=TicketStatus.OPEN,
            creator_id=emp_user.id
        )
        db.session.add(ticket)
        db.session.commit()

    client.post('/auth/login', data={'username_or_email': 'test_emp', 'password': 'EmpSecure123!'})
    
    # Attempt to post a comment with is_internal=True
    client.post('/tickets/INC-2026-77702/comment', data={
        'content': 'Attempting unauthorized internal note submission',
        'is_internal': 'y'
    }, follow_redirects=True)

    with app.app_context():
        comment = Comment.query.filter_by(content='Attempting unauthorized internal note submission').first()
        assert comment is not None
        # Must be coerced to False by server-side authorization
        assert comment.is_internal is False
