"""Read-only facts for the administrator's System Status page.

Shows where the application runs and how it is protected: the EC2 instance and
its IAM role, the database connection and its TLS, the EFS mount, where the
secrets came from and the main security settings. Secret VALUES are never read
here - only their source names - and the IAM role's temporary credentials are
never requested (only the role name).

Every check is a dict(label, value, state) with state 'ok', 'warn' or 'info'.
"""
import ipaddress
import os
import platform
import socket
import time
import urllib.request

from flask import current_app, request
from sqlalchemy import func

from app.extensions import db
from app.models import Attachment, Ticket, TicketStatus, User, utcnow
from app.services.settings import get_auto_assign_config
from app.services.storage import get_storage

IMDS = 'http://169.254.169.254/latest'
_instance_cache = {'at': 0.0, 'data': None}


def _check(label, value, state='info'):
    return {'label': label, 'value': value, 'state': state}


def _ok(flag):
    return 'ok' if flag else 'warn'


def instance_metadata(timeout=0.4):
    """EC2 instance facts via IMDSv2, or {} when not running on EC2 (cached)."""
    now = time.monotonic()
    cached = _instance_cache['data']
    if cached is not None and (cached or now - _instance_cache['at'] < 300):
        return cached
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # metadata never goes via a proxy
    data = {}
    try:
        token_req = urllib.request.Request(f'{IMDS}/api/token', method='PUT',
                                           headers={'X-aws-ec2-metadata-token-ttl-seconds': '60'})
        token = opener.open(token_req, timeout=timeout).read().decode()
        paths = {
            'instance_id': 'instance-id', 'instance_type': 'instance-type', 'zone': 'placement/availability-zone',
            'region': 'placement/region', 'private_ip': 'local-ipv4', 'public_ip': 'public-ipv4',
            # Lists the role NAME only; the credentials document below it is never requested
            'iam_role': 'iam/security-credentials/',
        }
        for key, path in paths.items():
            try:
                req = urllib.request.Request(f'{IMDS}/meta-data/{path}', headers={'X-aws-ec2-metadata-token': token})
                data[key] = opener.open(req, timeout=timeout).read().decode().strip() or None
            except Exception:  # noqa: BLE001 - a missing item (e.g. no public IP) is normal
                data[key] = None
    except Exception:  # noqa: BLE001 - not on EC2
        data = {}
    _instance_cache.update(at=now, data=data)
    return data


def _app_version():
    """Short git commit of the deployed code, read from .git (no subprocess)."""
    git_dir = os.path.join(os.path.dirname(current_app.root_path), '.git')
    try:
        with open(os.path.join(git_dir, 'HEAD'), encoding='utf-8') as fh:
            head = fh.read().strip()
        if not head.startswith('ref: '):
            return head[:7]
        ref = head[5:]
        ref_file = os.path.join(git_dir, *ref.split('/'))
        if os.path.exists(ref_file):
            with open(ref_file, encoding='utf-8') as fh:
                return f"{fh.read().strip()[:7]} ({ref.rsplit('/', 1)[-1]})"
        with open(os.path.join(git_dir, 'packed-refs'), encoding='utf-8') as fh:
            for line in fh:
                if line.strip().endswith(ref):
                    return f"{line.split()[0][:7]} ({ref.rsplit('/', 1)[-1]})"
    except OSError:
        pass
    return 'unknown'


def _server_section(ec2):
    cfg = current_app.config
    checks = [
        _check('Server name', socket.gethostname()),
        _check('Application server', request.environ.get('SERVER_SOFTWARE', 'unknown').split(' ')[0]),
        _check('Reverse proxy', 'Nginx in front of the app' if cfg.get('TRUSTED_PROXY_COUNT') else 'none (direct)',
               'ok' if cfg.get('TRUSTED_PROXY_COUNT') else 'info'),
        _check('Connection', 'HTTPS (encrypted)' if request.is_secure else 'HTTP (not encrypted)', _ok(request.is_secure)),
        _check('Environment', cfg.get('ENV_NAME', 'unknown'), 'ok' if cfg.get('ENV_NAME') == 'production' else 'info'),
        _check('Debug mode', 'off' if not cfg.get('DEBUG') else 'ON', _ok(not cfg.get('DEBUG'))),
        _check('App version', _app_version()),
        _check('Python', platform.python_version()),
    ]
    if ec2:
        checks[:0] = [
            _check('Amazon EC2 instance', f"{ec2.get('instance_id')} ({ec2.get('instance_type')})", 'ok'),
            _check('Region / zone', f"{ec2.get('region')} / {ec2.get('zone')}"),
            _check('Private / public IP', f"{ec2.get('private_ip') or '-'} / {ec2.get('public_ip') or '-'}"),
        ]
    else:
        checks.insert(0, _check('Amazon EC2 instance', 'not running on AWS (local computer)'))
    return checks


def _identity_section(ec2):
    cfg = current_app.config
    static_keys = bool(os.environ.get('AWS_ACCESS_KEY_ID')) or os.path.exists(os.path.expanduser('~/.aws/credentials'))
    role = ec2.get('iam_role') if ec2 else None
    checks = [
        _check('IAM instance role', role or ('none attached' if ec2 else 'not on AWS'), _ok(role) if ec2 else 'info'),
        _check('Static AWS access keys', 'present' if static_keys
               else ('none (the role gives short-lived credentials)' if role else 'none'), _ok(not static_keys)),
        _check('Database credentials from', cfg.get('DB_CREDENTIALS_SOURCE') or 'unknown',
               'ok' if 'Secrets Manager' in (cfg.get('DB_CREDENTIALS_SOURCE') or '') else 'info'),
        _check('Session signing key from', cfg.get('SECRET_KEY_SOURCE') or 'unknown',
               'ok' if 'Secrets Manager' in (cfg.get('SECRET_KEY_SOURCE') or '')
               else ('warn' if 'fallback' in (cfg.get('SECRET_KEY_SOURCE') or '') else 'info')),
        _check('Secret values shown', 'never (only where they come from)', 'ok'),
    ]
    return checks


def _database_section():
    url = db.engine.url
    engine = url.get_backend_name()
    checks = []
    try:
        version = db.session.execute(db.text('SELECT VERSION()' if engine == 'mysql' else 'SELECT sqlite_version()')).scalar()
        checks.append(_check('Connection', 'connected', 'ok'))
    except Exception:  # noqa: BLE001 - details go to the server log only
        current_app.logger.error('[Status] Database check failed')
        return [_check('Connection', 'unavailable', 'warn')], {}
    host = url.host or 'local file'
    is_rds = bool(url.host and url.host.endswith('.rds.amazonaws.com'))
    checks.append(_check('Engine', f"{'Amazon RDS for MySQL' if is_rds else engine.upper()} {version}", 'ok' if is_rds else 'info'))
    checks.append(_check('Endpoint', host))
    if url.host:
        try:
            addr = socket.gethostbyname(url.host)
            private = ipaddress.ip_address(addr).is_private or ipaddress.ip_address(addr).is_loopback
            checks.append(_check('Network address', f"{addr} ({'private' if private else 'PUBLIC'})", _ok(private)))
        except OSError:
            pass
    if engine == 'mysql':
        ssl = db.session.execute(db.text("SHOW SESSION STATUS LIKE 'Ssl_version'")).fetchone()
        cipher = db.session.execute(db.text("SHOW SESSION STATUS LIKE 'Ssl_cipher'")).fetchone()
        tls = ssl[1] if ssl and ssl[1] else None
        checks.append(_check('Encrypted connection (TLS)', f"{tls} {cipher[1] if cipher else ''}".strip() if tls else 'no',
                             _ok(tls)))
    counts = {
        'Users': User.query.count(),
        'Tickets': Ticket.query.count(),
        'Attachments': Attachment.query.count(),
    }
    return checks, counts


def _storage_section():
    cfg = current_app.config
    storage = get_storage()
    health = storage.health()
    efs = health.get('backend') == 'efs'
    checks = [
        _check('Backend', 'Amazon EFS (shared network storage)' if efs else 'local disk', 'ok' if efs else 'info'),
        _check('Folder', storage.root),
    ]
    if efs:
        checks.append(_check('Mounted', 'yes' if health.get('mounted') else 'NO', _ok(health.get('mounted'))))
        mount_point = cfg.get('EFS_MOUNT_POINT', '/mnt/efs')
        source = None
        try:
            with open('/proc/mounts', encoding='utf-8') as fh:
                for line in fh:
                    parts = line.split()
                    if len(parts) > 1 and parts[1] == mount_point:
                        source = parts[0]
        except OSError:
            pass
        # efs-utils mounts with TLS through a local tunnel, so the source is 127.0.0.1
        tls = bool(source and source.startswith('127.0.0.1'))
        checks.append(_check('Encrypted in transit (TLS)', 'yes (efs-utils TLS tunnel)' if tls else 'not detected', _ok(tls)))
    checks.append(_check('Read / write test', health.get('status', 'unknown'), _ok(health.get('status') == 'accessible')))
    files, size = db.session.query(func.count(Attachment.id), func.coalesce(func.sum(Attachment.file_size), 0)).one()
    checks.append(_check('Stored attachments', f"{files} file(s), {int(size) / 1024:.1f} KB"))
    return checks


def _security_section():
    cfg = current_app.config
    return [
        _check('Passwords', 'stored as scrypt hashes, never plain text', 'ok'),
        _check('Login lockout', f"{cfg.get('LOGIN_MAX_FAILED_PER_ACCOUNT')} failed tries per account / "
                                f"{cfg.get('LOGIN_MAX_FAILED_PER_IP')} per IP, {cfg.get('LOGIN_LOCKOUT_WINDOW_MINUTES')} min", 'ok'),
        _check('Session timeout', f"{cfg.get('SESSION_IDLE_TIMEOUT_MINUTES')} min idle, "
                                  f"{cfg.get('SESSION_ABSOLUTE_TIMEOUT_HOURS')} h maximum", 'ok'),
        _check('Session cookie', f"HttpOnly, SameSite={cfg.get('SESSION_COOKIE_SAMESITE')}, "
                                 f"Secure={'yes' if cfg.get('SESSION_COOKIE_SECURE') else 'no'}",
               _ok(cfg.get('SESSION_COOKIE_SECURE')) if request.is_secure else 'info'),
        _check('CSRF protection', 'on (every form)' if cfg.get('WTF_CSRF_ENABLED') else 'OFF', _ok(cfg.get('WTF_CSRF_ENABLED'))),
        _check('HSTS', 'on' if cfg.get('ENABLE_HSTS') and request.is_secure else 'off',
               _ok(cfg.get('ENABLE_HSTS')) if request.is_secure else 'info'),
        _check('Uploads', f"max {cfg.get('MAX_UPLOAD_BYTES', 0) // (1024 * 1024)} MB, content checked, "
                          f"{len(cfg.get('ALLOWED_EXTENSIONS', []))} allowed types", 'ok'),
    ]


def _activity_section():
    cfg = current_app.config
    now = utcnow()
    active = Ticket.query.filter(Ticket.status.in_(TicketStatus.ACTIVE))
    overdue = active.filter(Ticket.resolution_due_at.isnot(None), Ticket.resolution_due_at < now).count()
    escalated = active.filter(Ticket.escalated_at.isnot(None)).count()
    return [
        _check('Auto-assignment', 'ON' if get_auto_assign_config().enabled else 'OFF'),
        _check('SLA escalation', 'ON (warning at 75 %, admins alerted on breach)'
               if cfg.get('SLA_ESCALATION_ENABLED') else 'OFF'),
        _check('Active tickets', active.count()),
        # Overdue tickets are work to do, not a system problem, so they are not counted as warnings
        _check('Overdue / escalated tickets', f"{overdue} / {escalated}"),
    ]


def collect_status():
    """Everything the System Status page shows, grouped in sections."""
    ec2 = instance_metadata()
    db_checks, counts = _database_section()
    sections = [
        {'title': 'Web server', 'icon': 'bi-hdd-rack', 'checks': _server_section(ec2)},
        {'title': 'Identity & secrets', 'icon': 'bi-shield-lock', 'checks': _identity_section(ec2)},
        {'title': 'Database', 'icon': 'bi-database', 'checks': db_checks},
        {'title': 'File storage', 'icon': 'bi-folder2-open', 'checks': _storage_section()},
        {'title': 'Application security', 'icon': 'bi-lock', 'checks': _security_section()},
        {'title': 'Operations', 'icon': 'bi-activity', 'checks': _activity_section()},
    ]
    states = {c['label']: c['state'] for s in sections for c in s['checks']}
    cfg = current_app.config
    services = [
        ('Amazon EC2', bool(ec2)),
        ('Amazon RDS', any('Amazon RDS' in str(c['value']) for c in db_checks)),
        ('Amazon EFS', cfg.get('STORAGE_BACKEND') == 'efs' and states.get('Mounted') == 'ok'),
        ('IAM role', bool(ec2 and ec2.get('iam_role'))),
        ('Secrets Manager', 'Secrets Manager' in (cfg.get('DB_CREDENTIALS_SOURCE') or '')),
        ('HTTPS', request.is_secure),
    ]
    warnings = sum(1 for s in sections for c in s['checks'] if c['state'] == 'warn')
    return {'sections': sections, 'services': services, 'counts': counts, 'warnings': warnings,
            'on_aws': bool(ec2), 'checked_at': utcnow()}
