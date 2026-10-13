from flask import Blueprint, abort, flash, redirect, url_for
from flask_login import login_required, current_user
from app.extensions import db
from app.models import Attachment
from app.services.storage import get_secure_attachment_response, delete_attachment_file
from app.services.audit import log_audit_event

attachments_bp = Blueprint('attachments', __name__, url_prefix='/attachments')


@attachments_bp.route('/<int:attachment_id>/download', methods=['GET'])
@login_required
def download(attachment_id):
    """
    Downloads an attachment file from EFS or local storage.
    
    Security & RBAC Controls:
    1. Only authenticated users can access.
    2. User must be an Administrator, Support Technician, or the original creator/uploader.
    3. Serves with sanitized filename and safe attachment headers to prevent XSS.
    4. Logs download action for compliance audit.
    """
    attachment = Attachment.query.get_or_404(attachment_id)
    ticket = attachment.ticket

    # Authorization Check
    authorized = (
        current_user.is_admin or
        current_user.is_technician or
        ticket.creator_id == current_user.id or
        attachment.user_id == current_user.id
    )

    if not authorized:
        log_audit_event(
            action='ATTACHMENT_UNAUTHORIZED_DOWNLOAD_ATTEMPT',
            entity_type='Attachment',
            entity_id=attachment.id,
            details=f"User '{current_user.username}' attempted unauthorized download of file '{attachment.original_filename}'"
        )
        abort(403)

    log_audit_event(
        action='ATTACHMENT_DOWNLOAD',
        entity_type='Attachment',
        entity_id=attachment.id,
        details=f"File '{attachment.original_filename}' downloaded by {current_user.username}"
    )

    return get_secure_attachment_response(attachment.filename, attachment.original_filename)


@attachments_bp.route('/<int:attachment_id>/delete', methods=['POST'])
@login_required
def delete(attachment_id):
    """Deletes an attachment file and its database record."""
    attachment = Attachment.query.get_or_404(attachment_id)
    ticket = attachment.ticket

    # Only admin or original uploader can delete
    if not (current_user.is_admin or attachment.user_id == current_user.id):
        abort(403)

    stored_name = attachment.filename
    orig_name = attachment.original_filename
    ref_id = ticket.reference_id

    # Remove physical file from EFS / storage
    delete_attachment_file(stored_name)

    # Delete DB record
    db.session.delete(attachment)
    db.session.commit()

    log_audit_event(
        action='ATTACHMENT_DELETE',
        entity_type='Attachment',
        entity_id=attachment_id,
        details=f"Attachment '{orig_name}' deleted by {current_user.username}"
    )

    flash(f"Attachment '{orig_name}' was deleted.", 'info')
    return redirect(url_for('tickets.detail', reference_id=ref_id))
