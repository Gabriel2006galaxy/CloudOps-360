from flask import Blueprint, abort, flash, redirect, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Attachment
from app.services import permissions as perm
from app.services.audit import log_audit_event
from app.services.storage import get_storage

attachments_bp = Blueprint('attachments', __name__, url_prefix='/attachments')


def _get_attachment(attachment_id):
    attachment = db.session.get(Attachment, attachment_id)
    if attachment is None:
        abort(404)
    return attachment


@attachments_bp.route('/<int:attachment_id>/download', methods=['GET'])
@login_required
def download(attachment_id):
    """Authorized download from EFS/local storage.

    Access follows ticket visibility (creator, assigned technician, admin), the
    file is always sent as an attachment with nosniff and a sandbox CSP, and
    every download or denial is audited.
    """
    attachment = _get_attachment(attachment_id)
    if not perm.can_download_attachment(current_user, attachment):
        log_audit_event('ATTACHMENT_UNAUTHORIZED_DOWNLOAD', 'Attachment', attachment.id,
                        f"'{current_user.username}' denied download of attachment #{attachment.id} "
                        f"on {attachment.ticket.reference_id}")
        abort(403)

    try:
        response = get_storage().send(attachment.storage_path, attachment.original_filename, attachment.mime_type)
    except FileNotFoundError:
        log_audit_event('ATTACHMENT_FILE_MISSING', 'Attachment', attachment.id,
                        f"Stored file for attachment #{attachment.id} is missing from storage")
        abort(404)

    log_audit_event('ATTACHMENT_DOWNLOAD', 'Attachment', attachment.id,
                    f"'{attachment.original_filename}' downloaded by {current_user.username}")
    return response


@attachments_bp.route('/<int:attachment_id>/delete', methods=['POST'])
@login_required
def delete(attachment_id):
    """Deletes an attachment's file and database row (admin or uploader only)."""
    attachment = _get_attachment(attachment_id)
    ticket = attachment.ticket
    if not perm.can_delete_attachment(current_user, attachment):
        log_audit_event('ATTACHMENT_UNAUTHORIZED_DELETE', 'Attachment', attachment.id,
                        f"'{current_user.username}' denied deletion of attachment #{attachment.id}")
        abort(403)

    key, name, ref = attachment.storage_path, attachment.original_filename, ticket.reference_id
    db.session.delete(attachment)
    log_audit_event('ATTACHMENT_DELETE', 'Attachment', attachment_id,
                    f"'{name}' deleted from {ref} by {current_user.username}", commit=False)
    db.session.commit()
    get_storage().delete(key)  # remove the bytes only after the metadata delete committed

    flash(f"Attachment '{name}' deleted.", 'info')
    return redirect(url_for('tickets.detail', reference_id=ref) + '#attachments')
