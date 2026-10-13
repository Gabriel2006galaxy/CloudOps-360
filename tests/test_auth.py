"""Authentication, sessions, account status and login rate limiting."""
import time

from app.extensions import db
from app.models import AuditLog, LoginAttempt, User, UserRole
from conftest import PASSWORDS, login, logout


def test_login_success_redirects_to_role_dashboard(client, admin_user, tech_user, emp_user):
    for username, expected in (('test_admin', '/dashboard/admin'), ('test_tech', '/dashboard/technician'),
                               ('test_emp', '/dashboard/employee')):
        c = client.application.test_client()
        resp = login(c, username)
        assert resp.status_code == 302
        resp = c.get('/dashboard')
        assert resp.headers['Location'].endswith(expected)


def test_login_with_email_is_case_insensitive(client, emp_user):
    resp = login(client, 'TEST_EMP@Test.Local', PASSWORDS['test_emp'])
    assert resp.status_code == 302


def test_login_failure_is_rejected_and_audited(client, emp_user):
    resp = login(client, 'test_emp', 'WrongPassword1')
    assert resp.status_code == 401
    assert b'Invalid username/email or password' in resp.data
    assert AuditLog.query.filter_by(action='AUTH_LOGIN_FAILED').count() == 1
    # Never store the submitted password
    assert b'WrongPassword1' not in str([(a.details) for a in AuditLog.query.all()]).encode()


def test_unknown_user_gets_same_generic_message(client):
    resp = login(client, 'nobody', 'Whatever123')
    assert resp.status_code == 401
    assert b'Invalid username/email or password' in resp.data


def test_protected_pages_require_login(client):
    for path in ('/dashboard', '/tickets', '/tickets/create', '/admin/users', '/notifications'):
        resp = client.get(path)
        assert resp.status_code == 302
        assert '/auth/login' in resp.headers['Location']


def test_passwords_are_hashed(app, emp_user):
    user = db.session.get(User, emp_user.id)
    assert user.password_hash != PASSWORDS['test_emp']
    assert user.password_hash.startswith(('scrypt:', 'pbkdf2:'))
    assert user.check_password(PASSWORDS['test_emp'])


def test_deactivated_account_cannot_log_in(client, app, emp_user):
    user = db.session.get(User, emp_user.id)
    user.is_active = False
    db.session.commit()
    resp = login(client, 'test_emp')
    assert resp.status_code == 403
    assert b'deactivated' in resp.data
    assert client.get('/dashboard').status_code == 302


def test_deactivation_ends_existing_session(client, app, emp_user):
    login(client, 'test_emp')
    assert client.get('/dashboard/employee').status_code == 200
    user = db.session.get(User, emp_user.id)
    user.is_active = False
    db.session.commit()
    resp = client.get('/dashboard/employee')
    assert resp.status_code == 302 and '/auth/login' in resp.headers['Location']
    assert AuditLog.query.filter_by(action='AUTH_SESSION_REVOKED_DEACTIVATED').count() == 1


def test_logout_requires_post_and_clears_session(client, emp_user):
    login(client, 'test_emp')
    assert client.get('/auth/logout').status_code == 405
    resp = logout(client)
    assert resp.status_code == 302
    assert client.get('/dashboard').status_code == 302


def test_session_idle_timeout(client, app, emp_user):
    login(client, 'test_emp')
    with client.session_transaction() as sess:
        sess['last_seen'] = time.time() - (app.config['SESSION_IDLE_TIMEOUT_MINUTES'] * 60 + 5)
    resp = client.get('/dashboard/employee')
    assert resp.status_code == 302 and '/auth/login' in resp.headers['Location']
    assert AuditLog.query.filter_by(action='AUTH_SESSION_EXPIRED').count() == 1


def test_session_absolute_timeout(client, app, emp_user):
    login(client, 'test_emp')
    with client.session_transaction() as sess:
        sess['login_at'] = time.time() - (app.config['SESSION_ABSOLUTE_TIMEOUT_HOURS'] * 3600 + 5)
    resp = client.get('/dashboard/employee')
    assert resp.status_code == 302 and '/auth/login' in resp.headers['Location']


def test_background_poll_does_not_extend_session(client, emp_user):
    login(client, 'test_emp')
    with client.session_transaction() as sess:
        sess['last_seen'] = 1000.0
        sess['login_at'] = time.time()
    # last_seen far in the past => this poll is rejected as expired rather than refreshing it
    resp = client.get('/api/notifications/unread-count', headers={'X-Background-Poll': '1', 'Accept': 'application/json'})
    assert resp.status_code == 401


def test_open_redirect_is_blocked(client, emp_user):
    resp = client.post('/auth/login?next=https://evil.example/phish', data={
        'username_or_email': 'test_emp', 'password': PASSWORDS['test_emp']})
    assert resp.status_code == 302
    assert 'evil.example' not in resp.headers['Location']


def test_safe_next_redirect_is_followed(client, emp_user):
    resp = client.post('/auth/login?next=/tickets', data={
        'username_or_email': 'test_emp', 'password': PASSWORDS['test_emp']})
    assert resp.headers['Location'].endswith('/tickets')


def test_account_lockout_after_repeated_failures(client, app, emp_user):
    limit = app.config['LOGIN_MAX_FAILED_PER_ACCOUNT']
    for _ in range(limit):
        assert login(client, 'test_emp', 'WrongPassword1').status_code == 401
    # Even the correct password is refused while locked
    resp = login(client, 'test_emp')
    assert resp.status_code == 429
    assert b'Too many failed sign-in attempts' in resp.data
    assert AuditLog.query.filter_by(action='AUTH_LOGIN_LOCKED').count() == 1
    assert LoginAttempt.query.filter_by(success=False).count() == limit


def test_successful_login_resets_failure_count(client, app, emp_user):
    limit = app.config['LOGIN_MAX_FAILED_PER_ACCOUNT']
    for _ in range(limit - 1):
        login(client, 'test_emp', 'WrongPassword1')
    assert login(client, 'test_emp').status_code == 302
    logout(client)
    for _ in range(limit - 1):
        login(client, 'test_emp', 'WrongPassword1')
    assert login(client, 'test_emp').status_code == 302


def test_ip_rate_limit_blocks_password_spraying(client, app, emp_user):
    app.config['LOGIN_MAX_FAILED_PER_IP'] = 4
    for i in range(4):
        login(client, f'ghost{i}', 'Nope12345')
    assert login(client, 'test_emp').status_code == 429


def test_registration_creates_employee_only(client, app):
    resp = client.post('/auth/register', data={
        'full_name': 'New Person', 'username': 'new.person', 'email': 'New.Person@corp.local',
        'department': 'Ops', 'role': 'admin', 'password': 'StrongPass123', 'confirm_password': 'StrongPass123',
    })
    assert resp.status_code == 302
    user = User.query.filter_by(username='new.person').one()
    assert user.role == UserRole.EMPLOYEE
    assert user.email == 'new.person@corp.local'


def test_registration_rejects_weak_password_and_duplicates(client, emp_user):
    resp = client.post('/auth/register', data={
        'full_name': 'Weak', 'username': 'weakling', 'email': 'weak@corp.local',
        'password': 'password', 'confirm_password': 'password'})
    assert resp.status_code == 200 and User.query.filter_by(username='weakling').first() is None
    resp = client.post('/auth/register', data={
        'full_name': 'Dup', 'username': 'test_emp', 'email': 'emp@test.local',
        'password': 'StrongPass123', 'confirm_password': 'StrongPass123'})
    assert b'already registered' in resp.data


def test_registration_can_be_disabled(client, app):
    app.config['ALLOW_SELF_REGISTRATION'] = False
    assert client.get('/auth/register').status_code == 404


def test_profile_password_change_requires_current_password(client, emp_user):
    login(client, 'test_emp')
    resp = client.post('/auth/profile', data={'full_name': 'Employee User', 'department': 'QA',
                                              'new_password': 'BrandNew12345', 'confirm_new_password': 'BrandNew12345'})
    assert resp.status_code == 400
    resp = client.post('/auth/profile', data={'full_name': 'Employee User', 'department': 'QA',
                                              'current_password': PASSWORDS['test_emp'],
                                              'new_password': 'BrandNew12345', 'confirm_new_password': 'BrandNew12345'})
    assert resp.status_code == 302
    assert db.session.get(User, emp_user.id).check_password('BrandNew12345')
    assert AuditLog.query.filter_by(action='USER_PASSWORD_CHANGE').count() == 1
