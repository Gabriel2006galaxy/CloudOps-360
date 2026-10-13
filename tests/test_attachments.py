import io
import pytest
from app.extensions import db
from app.models import Ticket, TicketCategory, TicketPriority, TicketStatus, Attachment
from app.services.storage import is_allowed_file


def test_file_extension_whitelist(app):
    """Verify file extension security whitelist."""
    with app.app_context():
        assert is_allowed_file('screenshot.png') is True
        assert is_allowed_file('error.log') is True
        assert is_allowed_file('dump.txt') is True
        assert is_allowed_file('architecture.pdf') is True
        assert is_allowed_file('malicious.exe') is False
        assert is_allowed_file('script.sh') is False
        assert is_allowed_file('hack.php') is False
        assert is_allowed_file('noextension') is False


def test_authorized_and_unauthorized_download(client, app, emp_user, other_emp_user, tech_user, admin_user):
    """
    CRITICAL ATTACHMENT SECURITY TEST:
    Verify that creator, assigned technician, and admin can download diagnostic files,
    while unauthorized third-party employees receive 403 Forbidden.
    """
    with app.app_context():
        cat = TicketCategory.query.first()
        ticket = Ticket(
            reference_id='INC-2026-66601',
            title='EC2 Memory Dump Analysis',
            description='Kernel panic memory dump',
            category_id=cat.id,
            priority=TicketPriority.HIGH,
            status=TicketStatus.IN_PROGRESS,
            creator_id=emp_user.id,
            technician_id=tech_user.id
        )
        db.session.add(ticket)
        db.session.flush()

        # Create physical test file in upload dir
        from app.services.storage import get_upload_dir
        import os
        upload_dir = get_upload_dir()
        file_path = os.path.join(upload_dir, 'test_memory_dump.log')
        with open(file_path, 'w') as f:
            f.write("PANIC: kernel NULL pointer dereference at 0000000000000008")

        attachment = Attachment(
            ticket_id=ticket.id,
            user_id=emp_user.id,
            filename='test_memory_dump.log',
            original_filename='memory_dump.log',
            file_size=60,
            mime_type='text/plain',
            storage_path=file_path
        )
        db.session.add(attachment)
        db.session.commit()
        att_id = attachment.id

    # 1. Creator (emp_user) can download
    client.post('/auth/login', data={'username_or_email': 'test_emp', 'password': 'EmpSecure123!'})
    resp1 = client.get(f'/attachments/{att_id}/download')
    assert resp1.status_code == 200
    assert b'PANIC: kernel NULL pointer' in resp1.data
    client.get('/auth/logout')

    # 2. Assigned Technician (tech_user) can download
    client.post('/auth/login', data={'username_or_email': 'test_tech', 'password': 'TechSecure123!'})
    resp2 = client.get(f'/attachments/{att_id}/download')
    assert resp2.status_code == 200
    assert b'PANIC: kernel NULL pointer' in resp2.data
    client.get('/auth/logout')

    # 3. Third-party Employee (other_emp_user) MUST BE REJECTED with 403 Forbidden!
    client.post('/auth/login', data={'username_or_email': 'other_emp', 'password': 'OtherSecure123!'})
    resp3 = client.get(f'/attachments/{att_id}/download')
    assert resp3.status_code == 403
