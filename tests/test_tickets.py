"""Ticket creation, listing, filtering, sorting, pagination and persistence."""
import re
from datetime import timedelta

from app.extensions import db
from app.models import (
    Attachment, AuditLog, Notification, Ticket, TicketCategory, TicketStatus, TicketStatusHistory, utcnow,
)
from conftest import file_upload, login, make_ticket


def _create(client, **overrides):
    data = {'title': 'VPN keeps disconnecting', 'category_id': TicketCategory.query.first().id,
            'priority': 'High', 'affected_system': 'vpn-gw', 'department': 'Finance',
            'description': 'Disconnects every ten minutes since this morning.'}
    data.update(overrides)
    return client.post('/tickets/create', data=data, content_type='multipart/form-data')


def test_create_ticket_persists_with_reference_sla_history_and_notifications(client, emp_user, tech_user, admin_user):
    login(client, 'test_emp')
    resp = _create(client)
    assert resp.status_code == 302
    ticket = Ticket.query.one()
    assert re.fullmatch(r'INC-\d{4}-\d{5}', ticket.reference_id)
    assert resp.headers['Location'].endswith(f'/tickets/{ticket.reference_id}')
    assert ticket.status == TicketStatus.OPEN and ticket.creator_id == emp_user.id
    # High priority SLA: 4h response, 12h resolution
    assert abs((ticket.response_due_at - ticket.created_at) - timedelta(hours=4)) < timedelta(seconds=2)
    assert abs((ticket.resolution_due_at - ticket.created_at) - timedelta(hours=12)) < timedelta(seconds=2)
    assert TicketStatusHistory.query.filter_by(ticket_id=ticket.id).count() == 1
    assert {n.user_id for n in Notification.query.all()} == {tech_user.id, admin_user.id}
    assert AuditLog.query.filter_by(action='TICKET_CREATE', entity_id=ticket.reference_id).count() == 1


def test_reference_numbers_are_sequential_and_unique(client, emp_user):
    login(client, 'test_emp')
    for i in range(3):
        _create(client, title=f'Incident number {i}')
    refs = [t.reference_id for t in Ticket.query.order_by(Ticket.id).all()]
    assert len(set(refs)) == 3
    assert [int(r[-5:]) for r in refs] == sorted(int(r[-5:]) for r in refs)


def test_create_ticket_validation_errors(client, emp_user):
    login(client, 'test_emp')
    resp = _create(client, title='abc', description='short')
    assert resp.status_code == 400
    assert Ticket.query.count() == 0
    resp = _create(client, priority='Urgent!!')
    assert resp.status_code == 400 and Ticket.query.count() == 0


def test_inactive_category_cannot_be_used(client, emp_user):
    cat = TicketCategory.query.first()
    cat.is_active = False
    db.session.commit()
    login(client, 'test_emp')
    assert _create(client, category_id=cat.id).status_code == 400


def test_create_ticket_with_attachment(client, app, emp_user):
    login(client, 'test_emp')
    resp = _create(client, attachment=file_upload())
    assert resp.status_code == 302
    att = Attachment.query.one()
    assert att.original_filename == 'screenshot.png' and att.mime_type == 'image/png'
    assert len(att.checksum_sha256) == 64


def test_create_ticket_with_invalid_attachment_creates_nothing(client, emp_user):
    login(client, 'test_emp')
    resp = _create(client, attachment=file_upload(b'MZ\x90\x00 fake exe', 'virus.exe'))
    assert resp.status_code == 400
    assert b'File type not allowed' in resp.data
    assert Ticket.query.count() == 0 and Attachment.query.count() == 0


def test_list_filters_search_and_sort(client, admin_user, emp_user, tech_user):
    make_ticket(emp_user, title='Database slow', priority='Low')
    make_ticket(emp_user, title='Email outage', priority='Critical', technician=tech_user, status=TicketStatus.ASSIGNED)
    make_ticket(emp_user, title='Old printer jam', priority='Medium', created_at=utcnow() - timedelta(days=40))
    login(client, 'test_admin')

    body = client.get('/tickets?priority=Critical').data
    assert b'Email outage' in body and b'Database slow' not in body
    body = client.get('/tickets?status=Assigned').data
    assert b'Email outage' in body and b'Database slow' not in body
    body = client.get('/tickets?q=printer').data
    assert b'Old printer jam' in body and b'Email outage' not in body
    body = client.get(f'/tickets?technician={tech_user.id}').data
    assert b'Email outage' in body and b'Database slow' not in body
    body = client.get('/tickets?technician=unassigned').data
    assert b'Email outage' not in body and b'Database slow' in body

    since = (utcnow() - timedelta(days=7)).strftime('%Y-%m-%d')
    body = client.get(f'/tickets?date_from={since}').data
    assert b'Old printer jam' not in body and b'Database slow' in body

    body = client.get('/tickets?sort_by=priority&order=desc').data.decode()
    assert body.index('Email outage') < body.index('Old printer jam') < body.index('Database slow')
    body = client.get('/tickets?sort_by=priority&order=asc').data.decode()
    assert body.index('Database slow') < body.index('Email outage')


def test_list_ignores_invalid_filter_values(client, admin_user, emp_user):
    make_ticket(emp_user, title='Still listed')
    login(client, 'test_admin')
    resp = client.get('/tickets?status=DROP TABLE&priority=x&sort_by=password_hash&order=sideways&per_page=9999&date_from=notadate')
    assert resp.status_code == 200 and b'Still listed' in resp.data


def test_pagination(client, admin_user, emp_user):
    for i in range(23):
        make_ticket(emp_user, title=f'Paged ticket {i:02d}')
    login(client, 'test_admin')
    assert b'of 23 tickets' in client.get('/tickets').data
    page3 = client.get('/tickets?page=3').data
    assert page3.count(b'title="Paged ticket') == 3
    assert client.get('/tickets?per_page=25').data.count(b'title="Paged ticket') == 23


def test_overdue_filter(client, admin_user, emp_user):
    make_ticket(emp_user, title='Way overdue', priority='Critical', created_at=utcnow() - timedelta(hours=10))
    make_ticket(emp_user, title='Fresh ticket', priority='Critical')
    login(client, 'test_admin')
    body = client.get('/tickets?overdue=1').data
    assert b'Way overdue' in body and b'Fresh ticket' not in body


def test_ticket_data_persists_across_app_restart(tmp_path):
    """Records written by one application instance are read back by a new one (file-backed DB)."""
    from app import create_app
    from app.models import User, UserRole

    db_url = f"sqlite:///{(tmp_path / 'persist.db').as_posix()}"

    def build():
        return create_app('testing', config_overrides={'SQLALCHEMY_DATABASE_URI': db_url})

    first = build()
    with first.app_context():
        db.create_all()
        user = User(username='persist', email='p@test.local', full_name='Persist', role=UserRole.EMPLOYEE)
        user.set_password('Persist12345')
        db.session.add(user)
        db.session.add(TicketCategory(name='General'))
        db.session.commit()
        make_ticket(user, title='Survives restart')
        db.session.remove()
        db.engine.dispose()

    second = build()
    with second.app_context():
        ticket = Ticket.query.filter_by(title='Survives restart').one()
        assert ticket.creator.username == 'persist'
        db.session.remove()
        db.drop_all()
        db.engine.dispose()
