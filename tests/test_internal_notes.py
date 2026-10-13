"""Internal technician notes must never reach employees."""
from app.models import Comment, TicketStatus
from conftest import login, logout, make_ticket

SECRET_NOTE = 'INTERNAL-ONLY root cause: unindexed query in release 2.4.1'


def _ticket_with_notes(client, emp_user, tech_user):
    ticket = make_ticket(emp_user, technician=tech_user, status=TicketStatus.IN_PROGRESS)
    login(client, 'test_tech')
    client.post(f'/tickets/{ticket.reference_id}/comment', data={'content': 'Public: investigating now.'})
    client.post(f'/tickets/{ticket.reference_id}/comment', data={'content': SECRET_NOTE, 'is_internal': 'y'})
    logout(client)
    return ticket


def test_internal_note_is_stored_as_internal(client, emp_user, tech_user):
    _ticket_with_notes(client, emp_user, tech_user)
    note = Comment.query.filter_by(content=SECRET_NOTE).one()
    assert note.is_internal is True


def test_employee_never_sees_internal_notes(client, emp_user, tech_user):
    ticket = _ticket_with_notes(client, emp_user, tech_user)
    login(client, 'test_emp')
    body = client.get(f'/tickets/{ticket.reference_id}').data
    assert b'Public: investigating now.' in body
    assert SECRET_NOTE.encode() not in body
    assert b'Internal note' not in body  # not even the timeline marker
    # Not leaked through notifications either
    assert SECRET_NOTE.encode() not in client.get('/notifications').data
    assert SECRET_NOTE.encode() not in client.get('/dashboard/employee').data


def test_staff_see_internal_notes(client, admin_user, emp_user, tech_user):
    ticket = _ticket_with_notes(client, emp_user, tech_user)
    for user in ('test_tech', 'test_admin'):
        login(client, user)
        assert SECRET_NOTE.encode() in client.get(f'/tickets/{ticket.reference_id}').data
        logout(client)


def test_employee_cannot_create_internal_note_by_tampering(client, emp_user, tech_user):
    ticket = make_ticket(emp_user, technician=tech_user, status=TicketStatus.IN_PROGRESS)
    login(client, 'test_emp')
    client.post(f'/tickets/{ticket.reference_id}/comment', data={'content': 'Sneaky hidden note', 'is_internal': 'y'})
    comment = Comment.query.filter_by(content='Sneaky hidden note').one()
    assert comment.is_internal is False


def test_unclaimed_queue_ticket_cannot_receive_technician_notes(client, emp_user, tech_user):
    ticket = make_ticket(emp_user)
    login(client, 'test_tech')
    client.post(f'/tickets/{ticket.reference_id}/comment', data={'content': 'Note before claiming', 'is_internal': 'y'})
    assert Comment.query.count() == 0
