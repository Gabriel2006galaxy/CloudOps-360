"""Attachment storage abstraction.

Development: a local directory (UPLOAD_FOLDER, default ./uploads).
Production:  an Amazon EFS file system mounted on every EC2 instance
             (UPLOAD_FOLDER=/mnt/efs/cloudops360-attachments, STORAGE_BACKEND=efs).

Both are POSIX filesystems, so one FileSystemStorage class serves both; the
'efs' backend additionally verifies the mount point really is mounted, so an
instance whose EFS mount failed refuses uploads instead of silently writing to
its local disk (where other instances could never see the file).

File bytes live in storage; metadata (owner, ticket, size, checksum, key) lives
in the database. Keys are generated server-side and never derived from user input.
"""
import hashlib
import os
import socket
import uuid

from flask import current_app, send_file
from werkzeug.utils import secure_filename

from app.models import utcnow

CHUNK_SIZE = 64 * 1024

MIME_TYPES = {
    'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'gif': 'image/gif',
    'pdf': 'application/pdf', 'txt': 'text/plain', 'log': 'text/plain', 'csv': 'text/csv',
    'zip': 'application/zip',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}

# Leading "magic" bytes each binary type must start with
MAGIC_SIGNATURES = {
    'png': [b'\x89PNG\r\n\x1a\n'],
    'jpg': [b'\xff\xd8\xff'],
    'jpeg': [b'\xff\xd8\xff'],
    'gif': [b'GIF87a', b'GIF89a'],
    'pdf': [b'%PDF-'],
    'zip': [b'PK\x03\x04', b'PK\x05\x06'],
    'docx': [b'PK\x03\x04'],
}
TEXT_EXTENSIONS = {'txt', 'log', 'csv'}


class StorageError(Exception):
    """Base storage failure (message is safe to show to users)."""


class UploadValidationError(StorageError):
    """The uploaded file was rejected by validation."""


class StorageUnavailableError(StorageError):
    """The storage backend (e.g. EFS mount) is not available."""


def get_extension(filename):
    return filename.rsplit('.', 1)[1].lower() if filename and '.' in filename else ''


def is_allowed_file(filename):
    """Extension whitelist check."""
    allowed = current_app.config.get('ALLOWED_EXTENSIONS', set(MIME_TYPES))
    return get_extension(filename) in allowed


def _validate_content(ext, head):
    """Rejects files whose content does not match their extension."""
    if ext in MAGIC_SIGNATURES:
        if not any(head.startswith(sig) for sig in MAGIC_SIGNATURES[ext]):
            raise UploadValidationError(f"File content does not match the .{ext} file type.")
    elif ext in TEXT_EXTENSIONS:
        if b'\x00' in head:
            raise UploadValidationError(f"A .{ext} file must contain plain text, not binary data.")
        try:
            head.decode('utf-8')
        except UnicodeDecodeError as exc:
            # A multi-byte character may be split at the end of the sniffed chunk
            if exc.start < len(head) - 4:
                raise UploadValidationError(f"A .{ext} file must be UTF-8 text.") from exc


class FileSystemStorage:
    """Stores files under a root directory (local disk or an EFS mount)."""

    def __init__(self, root, backend='local', mount_point=None, max_bytes=10 * 1024 * 1024):
        self.root = os.path.realpath(os.path.abspath(root))
        self.backend = backend
        self.mount_point = mount_point
        self.max_bytes = max_bytes

    # ---------- path safety ----------
    def _resolve(self, key):
        """Absolute path for a storage key; rejects anything escaping the root."""
        if not key or key.startswith(('/', '\\')) or '..' in key.replace('\\', '/').split('/'):
            raise StorageError('Invalid storage key.')
        path = os.path.realpath(os.path.join(self.root, key))
        if os.path.commonpath([path, self.root]) != self.root:
            raise StorageError('Invalid storage key.')
        return path

    def is_mounted(self):
        if self.backend != 'efs':
            return True
        mount = self.mount_point or self.root
        return os.path.ismount(mount)

    def ensure_available(self):
        if self.backend == 'efs' and not self.is_mounted():
            raise StorageUnavailableError(
                'Shared attachment storage (Amazon EFS) is not mounted on this server. Upload refused.'
            )
        try:
            os.makedirs(self.root, exist_ok=True)
        except OSError as exc:
            raise StorageUnavailableError('Attachment storage directory is not available.') from exc

    # ---------- operations ----------
    def save(self, file_storage):
        """Validates and stores an upload. Returns a metadata dict."""
        if not file_storage or not file_storage.filename:
            raise UploadValidationError('No file was selected.')

        original_filename = secure_filename(file_storage.filename)[:200] or 'attachment'
        ext = get_extension(original_filename)
        if not is_allowed_file(original_filename):
            allowed = ', '.join(sorted(current_app.config.get('ALLOWED_EXTENSIONS', MIME_TYPES)))
            raise UploadValidationError(f'File type not allowed. Supported types: {allowed}.')

        self.ensure_available()
        now = utcnow()
        key = f"{now:%Y}/{now:%m}/{uuid.uuid4().hex}.{ext}"
        final_path = self._resolve(key)
        os.makedirs(os.path.dirname(final_path), exist_ok=True)
        temp_path = final_path + '.part'

        digest = hashlib.sha256()
        size = 0
        head = b''
        stream = file_storage.stream
        try:
            with open(temp_path, 'wb') as out:
                while True:
                    chunk = stream.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    if len(head) < 8192:
                        head += chunk[:8192 - len(head)]
                    size += len(chunk)
                    if size > self.max_bytes:
                        raise UploadValidationError(
                            f'File exceeds the maximum size of {self.max_bytes // (1024 * 1024) or 1} MB.'
                            if self.max_bytes >= 1024 * 1024 else
                            f'File exceeds the maximum size of {self.max_bytes // 1024} KB.'
                        )
                    digest.update(chunk)
                    out.write(chunk)
            if size == 0:
                raise UploadValidationError('The selected file is empty.')
            _validate_content(ext, head)
            os.replace(temp_path, final_path)
            try:
                os.chmod(final_path, 0o640)
            except OSError:
                pass
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise

        return {
            'key': key,
            'original_filename': original_filename,
            'size': size,
            'mime_type': MIME_TYPES.get(ext, 'application/octet-stream'),
            'checksum_sha256': digest.hexdigest(),
        }

    def exists(self, key):
        try:
            return os.path.isfile(self._resolve(key))
        except StorageError:
            return False

    def checksum(self, key):
        digest = hashlib.sha256()
        with open(self._resolve(key), 'rb') as fh:
            for chunk in iter(lambda: fh.read(CHUNK_SIZE), b''):
                digest.update(chunk)
        return digest.hexdigest()

    def send(self, key, download_name, mime_type=None):
        """Streams a stored file as a forced download with safe headers."""
        try:
            path = self._resolve(key)
        except StorageError:
            path = None
        if not path or not os.path.isfile(path):
            raise FileNotFoundError(key)
        response = send_file(
            path,
            mimetype=mime_type or 'application/octet-stream',
            as_attachment=True,
            download_name=secure_filename(download_name) or 'attachment',
            max_age=0,
            conditional=True,
        )
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'none'; sandbox"
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    def delete(self, key):
        try:
            path = self._resolve(key)
            if os.path.isfile(path):
                os.remove(path)
                return True
        except (OSError, StorageError) as exc:
            current_app.logger.error("[Storage] Could not delete %s: %s", key, type(exc).__name__)
        return False

    def health(self):
        """Write/read/delete probe used by /health and the storage-check command."""
        info = {'backend': self.backend, 'instance': socket.gethostname()}
        if self.backend == 'efs':
            info['mounted'] = self.is_mounted()
            if not info['mounted']:
                info['status'] = 'not-mounted'
                return info
        probe = f".health-{uuid.uuid4().hex}"
        try:
            os.makedirs(self.root, exist_ok=True)
            path = os.path.join(self.root, probe)
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write('ok')
            with open(path, encoding='utf-8') as fh:
                ok = fh.read() == 'ok'
            os.remove(path)
            info['status'] = 'accessible' if ok else 'error'
        except OSError:
            info['status'] = 'error'
        return info


def get_storage():
    """Storage backend for the current app, configured from app.config."""
    app = current_app._get_current_object()
    storage = app.extensions.get('cloudops_storage')
    if storage is None:
        root = app.config.get('UPLOAD_FOLDER', 'uploads')
        if not os.path.isabs(root):
            root = os.path.join(app.root_path, '..', root)
        storage = FileSystemStorage(
            root=root,
            backend=app.config.get('STORAGE_BACKEND', 'local'),
            mount_point=app.config.get('EFS_MOUNT_POINT'),
            max_bytes=app.config.get('MAX_UPLOAD_BYTES', 10 * 1024 * 1024),
        )
        app.extensions['cloudops_storage'] = storage
    return storage


def get_upload_dir():
    """Absolute path of the storage root (kept for backwards compatibility)."""
    storage = get_storage()
    os.makedirs(storage.root, exist_ok=True)
    return storage.root
