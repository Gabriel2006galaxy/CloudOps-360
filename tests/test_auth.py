import pytest
from flask import url_for
from app.models import User, UserRole


def test_login_success(client, admin_user):
    """Test successful login with valid credentials."""
    response = client.post('/auth/login', data={
        'username_or_email': 'test_admin',
        'password': 'AdminSecure123!'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Welcome back, Admin User!' in response.data


def test_login_invalid_password(client, admin_user):
    """Test failed login with incorrect password."""
    response = client.post('/auth/login', data={
        'username_or_email': 'test_admin',
        'password': 'WrongPassword123'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Invalid username/email or password.' in response.data


def test_deactivated_user_login(client, app, emp_user):
    """Test that deactivated accounts cannot log in."""
    with app.app_context():
        user = User.query.filter_by(username='test_emp').first()
        user.is_active = False
        from app.extensions import db
        db.session.commit()

    response = client.post('/auth/login', data={
        'username_or_email': 'test_emp',
        'password': 'EmpSecure123!'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'This account has been deactivated' in response.data


def test_logout(client, admin_user):
    """Test secure user logout."""
    # Login first
    client.post('/auth/login', data={
        'username_or_email': 'test_admin',
        'password': 'AdminSecure123!'
    })
    # Logout
    response = client.get('/auth/logout', follow_redirects=True)
    assert response.status_code == 200
    assert b'You have been securely logged out' in response.data


def test_registration(client, app):
    """Test user registration and verify password hash is never stored in plaintext."""
    response = client.post('/auth/register', data={
        'full_name': 'New Registered User',
        'username': 'newuser',
        'email': 'newuser@test.local',
        'department': 'DevOps',
        'role': 'employee',
        'password': 'ValidPassword123!',
        'confirm_password': 'ValidPassword123!'
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b'Your account has been created successfully' in response.data

    with app.app_context():
        user = User.query.filter_by(username='newuser').first()
        assert user is not None
        assert user.password_hash != 'ValidPassword123!'
        assert user.check_password('ValidPassword123!') is True
