"""Security controls: CSRF, headers, secret handling, production fail-closed config, audit."""
import pytest

from app import create_app
from app.extensions import db
from app.models import AuditLog, User
from app.services.audit import scrub_secrets
from app.services.secrets import SecretResolutionError, build_mysql_uri
from conftest import PASSWORDS, login


def test_security_headers(client):
    resp = client.get('/auth/login')
    assert resp.headers['X-Frame-Options'] == 'DENY'
    assert resp.headers['X-Content-Type-Options'] == 'nosniff'
    assert "frame-ancestors 'none'" in resp.headers['Content-Security-Policy']
    assert resp.headers['Referrer-Policy'] == 'strict-origin-when-cross-origin'


def test_session_cookie_flags(client, emp_user):
    resp = login(client, 'test_emp')
    cookie = resp.headers.get('Set-Cookie', '')
    assert 'HttpOnly' in cookie and 'SameSite=Lax' in cookie


def test_authenticated_pages_are_not_cached(client, emp_user):
    login(client, 'test_emp')
    assert client.get('/dashboard/employee').headers['Cache-Control'] == 'no-store'


def test_csrf_is_enforced_when_enabled(tmp_path):
    app = create_app('testing', config_overrides={'WTF_CSRF_ENABLED': True, 'UPLOAD_FOLDER': str(tmp_path)})
    with app.app_context():
        db.create_all()
        client = app.test_client()
        resp = client.post('/auth/login', data={'username_or_email': 'x', 'password': 'y'})
        assert resp.status_code == 400
        assert b'Security Check Failed' in resp.data
        assert AuditLog.query.filter_by(action='SECURITY_CSRF_REJECTED').count() == 1
        db.session.remove()
        db.drop_all()


def test_secrets_and_hashes_never_rendered(client, app, admin_user, emp_user):
    login(client, 'test_admin')
    pages = ['/admin/users', f'/admin/users/{emp_user.id}/edit', '/admin/audit-logs', '/health', '/auth/profile']
    hashes = [u.password_hash for u in User.query.all()]
    for path in pages:
        body = client.get(path).data
        assert app.config['SECRET_KEY'].encode() not in body, path
        for h in hashes:
            assert h.encode() not in body, path
        for pw in PASSWORDS.values():
            assert pw.encode() not in body, path


def test_health_reveals_no_connection_details(client, app):
    body = client.get('/health').get_data(as_text=True)
    assert 'sqlite:' not in body and 'mysql+pymysql' not in body and app.config['SECRET_KEY'] not in body


def test_audit_scrubs_credentials():
    assert 'Hunter2' not in scrub_secrets('login password=Hunter2 failed')
    assert 's3cr3t' not in scrub_secrets('mysql+pymysql://admin:s3cr3t@db:3306/x')
    assert scrub_secrets('plain message') == 'plain message'


def test_mysql_uri_encodes_special_characters():
    uri = build_mysql_uri('app', 'p@ss:w/rd#1', 'db.local', 3306, 'cloudops360')
    assert uri == 'mysql+pymysql://app:p%40ss%3Aw%2Frd%231@db.local:3306/cloudops360?charset=utf8mb4'


def test_production_fails_closed_without_secret_key(monkeypatch):
    monkeypatch.delenv('SECRET_KEY', raising=False)
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    with pytest.raises(SecretResolutionError):
        create_app('production', config_overrides={'SECRET_KEY': None, 'APP_SECRET_NAME': None})


def test_production_fails_closed_without_database(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    with pytest.raises(SecretResolutionError):
        create_app('production', config_overrides={'SECRET_KEY': 'x' * 40, 'DB_SECRET_NAME': None})


def test_production_rejects_short_secret_key(monkeypatch):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    with pytest.raises(SecretResolutionError):
        create_app('production', config_overrides={'SECRET_KEY': 'too-short'})


def test_production_config_is_hardened(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    app = create_app('production', config_overrides={'SECRET_KEY': 'p' * 48, 'UPLOAD_FOLDER': str(tmp_path)})
    assert app.config['SESSION_COOKIE_SECURE'] is True
    assert app.config['DEBUG'] is False
    assert app.config['SHOW_DEMO_ACCOUNTS'] is False
    assert app.config['TRUSTED_PROXY_COUNT'] == 1
    assert app.config['STORAGE_BACKEND'] == 'efs'


def test_seed_command_refused_in_production(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', f"sqlite:///{(tmp_path / 'p.db').as_posix()}")
    app = create_app('production', config_overrides={'SECRET_KEY': 'p' * 48, 'UPLOAD_FOLDER': str(tmp_path)})
    result = app.test_cli_runner().invoke(args=['seed-db'])
    assert result.exit_code != 0 and 'disabled in production' in result.output
    with app.app_context():
        db.engine.dispose()


def test_production_demo_accounts_opt_in(monkeypatch, tmp_path):
    monkeypatch.setenv('DATABASE_URL', 'sqlite://')
    monkeypatch.delenv('SHOW_DEMO_ACCOUNTS', raising=False)
    import importlib, config
    importlib.reload(config)
    try:
        assert config.ProductionConfig.SHOW_DEMO_ACCOUNTS is False
        monkeypatch.setenv('SHOW_DEMO_ACCOUNTS', 'true')
        importlib.reload(config)
        assert config.ProductionConfig.SHOW_DEMO_ACCOUNTS is True
    finally:
        monkeypatch.delenv('SHOW_DEMO_ACCOUNTS', raising=False)
        importlib.reload(config)


def test_demo_accounts_hidden_unless_enabled(client, app):
    assert b'Development demo accounts' not in client.get('/auth/login').data
    app.config['SHOW_DEMO_ACCOUNTS'] = True
    assert b'Development demo accounts' in client.get('/auth/login').data


def test_create_admin_command_requires_strong_password(runner, app):
    result = runner.invoke(args=['create-admin', '--username', 'ops', '--email', 'ops@corp.local',
                                 '--full-name', 'Ops Admin', '--password', 'short'])
    assert result.exit_code != 0
    result = runner.invoke(args=['create-admin', '--username', 'ops', '--email', 'ops@corp.local',
                                 '--full-name', 'Ops Admin', '--password', 'Very-Strong-Pass-2026'])
    assert result.exit_code == 0, result.output
    assert User.query.filter_by(username='ops').one().is_admin


def test_notification_links_cannot_open_redirect(app, emp_user):
    from app.services.notifications import create_notification
    n = create_notification(emp_user.id, 'x', 'y', link='https://evil.example')
    assert n.link is None
    n = create_notification(emp_user.id, 'x', 'y', link='//evil.example')
    assert n.link is None
    assert create_notification(emp_user.id, 'x', 'y', link='/tickets').link == '/tickets'


def test_sql_injection_attempts_are_inert(client, admin_user, emp_user):
    login(client, 'test_admin')
    for q in ("' OR 1=1 --", "'; DROP TABLE tickets; --", '" UNION SELECT password_hash FROM users --'):
        assert client.get('/tickets', query_string={'q': q}).status_code == 200
        assert client.get('/admin/users', query_string={'search': q}).status_code == 200
    assert User.query.count() == 2
