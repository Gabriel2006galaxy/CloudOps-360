"""Upload validation, storage safety and authorized downloads."""
import hashlib
import io
import os

import pytest

from app.extensions import db
from app.models import Attachment, AuditLog, TicketStatus
from app.services.storage import FileSystemStorage, StorageError, StorageUnavailableError, get_storage, is_allowed_file
from conftest import PNG_BYTES, file_upload, login, logout, make_ticket


def _upload(client, ref, data=PNG_BYTES, name='screenshot.png'):
    return client.post(f'/tickets/{ref}/attach', data={'attachment': (io.BytesIO(data), name)},
                       content_type='multipart/form-data')


def test_extension_whitelist(app):
    for ok in ('a.png', 'b.JPG', 'c.log', 'd.txt', 'e.pdf', 'f.csv', 'g.docx', 'h.zip', 'i.gif', 'j.jpeg'):
        assert is_allowed_file(ok), ok
    for bad in ('x.exe', 'x.sh', 'x.php', 'x.html', 'x.svg', 'x.js', 'noext', 'x.png.exe'):
        assert not is_allowed_file(bad), bad


def test_valid_upload_stores_file_and_metadata(client, app, emp_user):
    ticket = make_ticket(emp_user)
    login(client, 'test_emp')
    assert _upload(client, ticket.reference_id).status_code == 302
    att = Attachment.query.one()
    storage = get_storage()
    path = os.path.join(storage.root, att.storage_path)
    assert os.path.isfile(path)
    assert att.checksum_sha256 == hashlib.sha256(PNG_BYTES).hexdigest()
    assert att.file_size == len(PNG_BYTES)
    # Stored name is generated, never the user's filename
    assert 'screenshot' not in att.storage_path and att.storage_path.endswith('.png')
    assert AuditLog.query.filter_by(action='ATTACHMENT_UPLOAD').count() == 1


@pytest.mark.parametrize('data,name,message', [
    (b'MZ\x90\x00binary', 'tool.exe', b'File type not allowed'),
    (b'MZ\x90\x00binary pretending', 'photo.png', b'does not match'),
    (b'<?php system($_GET[c]); ?>', 'shell.php', b'File type not allowed'),
    (b'%PDF-1.7 but actually', 'report.txt', None),  # valid text
    (b'\x00\x01\x02 binary in a log', 'dump.log', b'plain text'),
    (b'', 'empty.txt', b'empty'),
])
def test_upload_validation(client, emp_user, data, name, message):
    ticket = make_ticket(emp_user)
    login(client, 'test_emp')
    resp = client.post(f'/tickets/{ticket.reference_id}/attach', data={'attachment': (io.BytesIO(data), name)},
                       content_type='multipart/form-data', follow_redirects=True)
    if message is None:
        assert Attachment.query.count() == 1
    else:
        assert message in resp.data
        assert Attachment.query.count() == 0


def test_oversized_upload_rejected(client, app, emp_user):
    ticket = make_ticket(emp_user)
    login(client, 'test_emp')
    too_big = b'a' * (app.config['MAX_UPLOAD_BYTES'] + 1)
    resp = _upload(client, ticket.reference_id, too_big, 'big.txt')
    assert resp.status_code in (302, 413)
    assert Attachment.query.count() == 0
    # Request bodies above MAX_CONTENT_LENGTH are refused before reaching the view
    huge = b'a' * (app.config['MAX_CONTENT_LENGTH'] + 10)
    assert _upload(client, ticket.reference_id, huge, 'huge.txt').status_code == 413
    # No partial files are left behind
    leftovers = [f for _, _, files in os.walk(get_storage().root) for f in files]
    assert leftovers == []


def test_path_traversal_filename_is_neutralised(client, emp_user):
    ticket = make_ticket(emp_user)
    login(client, 'test_emp')
    _upload(client, ticket.reference_id, b'log line', '../../../../etc/passwd.txt')
    att = Attachment.query.one()
    assert '..' not in att.storage_path and '/etc/' not in att.storage_path
    assert att.original_filename == 'etc_passwd.txt'


def test_storage_rejects_keys_outside_root(tmp_path):
    storage = FileSystemStorage(str(tmp_path / 'root'))
    for key in ('../outside.txt', '/etc/passwd', '2026/../../x', '..\\win.ini'):
        with pytest.raises(StorageError):
            storage._resolve(key)


def test_efs_backend_refuses_when_not_mounted(tmp_path):
    storage = FileSystemStorage(str(tmp_path / 'efs' / 'attachments'), backend='efs', mount_point=str(tmp_path / 'efs'))
    with pytest.raises(StorageUnavailableError):
        storage.ensure_available()
    assert storage.health()['status'] == 'not-mounted'


def test_authorized_downloads(client, app, admin_user, emp_user, other_emp_user, tech_user, other_tech):
    ticket = make_ticket(emp_user, technician=tech_user, status=TicketStatus.IN_PROGRESS)
    login(client, 'test_emp')
    _upload(client, ticket.reference_id, b'PANIC: kernel NULL pointer dereference', 'memory_dump.log')
    logout(client)
    att = Attachment.query.one()
    url = f'/attachments/{att.id}/download'

    for user in ('test_emp', 'test_tech', 'test_admin'):
        login(client, user)
        resp = client.get(url)
        assert resp.status_code == 200, user
        assert b'PANIC: kernel NULL pointer' in resp.data
        assert resp.headers['Content-Disposition'].startswith('attachment;')
        assert 'memory_dump.log' in resp.headers['Content-Disposition']
        assert resp.headers['X-Content-Type-Options'] == 'nosniff'
        assert 'sandbox' in resp.headers['Content-Security-Policy']
        logout(client)

    for user in ('other_emp', 'other_tech'):
        login(client, user)
        resp = client.get(url)
        assert resp.status_code == 403, user
        assert b'PANIC' not in resp.data
        logout(client)

    assert client.get(url).status_code == 302  # anonymous -> login
    assert AuditLog.query.filter_by(action='ATTACHMENT_UNAUTHORIZED_DOWNLOAD').count() == 2
    assert AuditLog.query.filter_by(action='ATTACHMENT_DOWNLOAD').count() == 3


def test_missing_file_returns_404(client, emp_user):
    ticket = make_ticket(emp_user)
    login(client, 'test_emp')
    _upload(client, ticket.reference_id)
    att = Attachment.query.one()
    os.remove(os.path.join(get_storage().root, att.storage_path))
    assert client.get(f'/attachments/{att.id}/download').status_code == 404


def test_attachment_delete_permissions(client, emp_user, other_emp_user, tech_user, admin_user):
    ticket = make_ticket(emp_user, technician=tech_user, status=TicketStatus.IN_PROGRESS)
    login(client, 'test_emp')
    _upload(client, ticket.reference_id)
    logout(client)
    att = Attachment.query.one()
    path = os.path.join(get_storage().root, att.storage_path)

    login(client, 'test_tech')  # not the uploader
    assert client.post(f'/attachments/{att.id}/delete').status_code == 403
    logout(client)
    login(client, 'test_emp')  # uploader
    assert client.post(f'/attachments/{att.id}/delete').status_code == 302
    assert Attachment.query.count() == 0 and not os.path.exists(path)


def test_upload_denied_on_foreign_ticket(client, emp_user, other_emp_user):
    ticket = make_ticket(other_emp_user)
    login(client, 'test_emp')
    assert _upload(client, ticket.reference_id).status_code == 403
    assert Attachment.query.count() == 0


def test_storage_check_command(client, runner, emp_user):
    ticket = make_ticket(emp_user)
    login(client, 'test_emp')
    _upload(client, ticket.reference_id)
    result = runner.invoke(args=['storage-check'])
    assert result.exit_code == 0, result.output
    assert '1 ok, 0 missing, 0 checksum mismatches' in result.output
    att = Attachment.query.one()
    with open(os.path.join(get_storage().root, att.storage_path), 'ab') as fh:
        fh.write(b'tampered')
    result = runner.invoke(args=['storage-check'])
    assert result.exit_code == 1 and '1 checksum mismatches' in result.output
