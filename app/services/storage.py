import os
import uuid
from werkzeug.utils import secure_filename
from flask import current_app, send_from_directory, abort


def is_allowed_file(filename):
    """Verify file extension matches allowed security whitelist."""
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    allowed = current_app.config.get('ALLOWED_EXTENSIONS', {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'txt', 'log', 'docx', 'csv', 'zip'})
    return ext in allowed


def get_upload_dir():
    """
    Returns absolute path to upload directory.
    Supports local filesystem path or mounted Amazon EFS directory.
    Ensures directory exists.
    """
    upload_dir = current_app.config.get('UPLOAD_FOLDER', 'uploads')
    if not os.path.isabs(upload_dir):
        upload_dir = os.path.join(current_app.root_path, '..', upload_dir)
    upload_dir = os.path.abspath(upload_dir)
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def save_file(file_storage):
    """
    Saves an uploaded file securely to EFS/local storage.
    
    Security controls:
    - Verifies allowed extensions
    - Generates a cryptographically random UUID filename to prevent collisions & directory traversal
    - Verifies total file size
    - Returns (safe_stored_filename, original_filename, file_size, storage_path, mime_type)
    """
    if not file_storage or not file_storage.filename:
        raise ValueError("No file provided for upload.")

    original_filename = secure_filename(file_storage.filename)
    if not original_filename:
        original_filename = "attachment"

    if not is_allowed_file(original_filename):
        raise ValueError("File type not allowed. Supported extensions: png, jpg, jpeg, gif, pdf, txt, log, docx, csv, zip.")

    ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else 'bin'
    stored_filename = f"{uuid.uuid4().hex}.{ext}"
    
    upload_dir = get_upload_dir()
    destination_path = os.path.join(upload_dir, stored_filename)
    
    # Path traversal check
    real_destination = os.path.realpath(destination_path)
    real_upload_dir = os.path.realpath(upload_dir)
    if not real_destination.startswith(real_upload_dir):
        raise PermissionError("Directory traversal attempt detected.")

    file_storage.save(destination_path)
    file_size = os.path.getsize(destination_path)
    
    max_size = current_app.config.get('MAX_CONTENT_LENGTH', 10 * 1024 * 1024)
    if file_size > max_size:
        os.remove(destination_path)
        raise ValueError(f"File exceeds maximum allowed size of {max_size // (1024*1024)} MB.")

    mime_type = file_storage.mimetype or 'application/octet-stream'
    
    return stored_filename, original_filename, file_size, destination_path, mime_type


def get_secure_attachment_response(stored_filename, original_filename):
    """
    Serves the file from EFS/local storage with safe download headers.
    """
    upload_dir = get_upload_dir()
    file_path = os.path.join(upload_dir, stored_filename)

    # Path traversal verification
    real_file_path = os.path.realpath(file_path)
    real_upload_dir = os.path.realpath(upload_dir)
    if not real_file_path.startswith(real_upload_dir) or not os.path.exists(real_file_path):
        abort(404, description="Requested attachment file not found.")

    return send_from_directory(
        upload_dir,
        stored_filename,
        as_attachment=True,
        download_name=original_filename
    )


def delete_attachment_file(stored_filename):
    """Deletes attachment file from EFS / local storage."""
    try:
        upload_dir = get_upload_dir()
        file_path = os.path.join(upload_dir, stored_filename)
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
    except Exception as e:
        current_app.logger.error(f"Error deleting file {stored_filename}: {e}")
    return False
