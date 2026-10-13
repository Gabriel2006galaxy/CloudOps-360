"""Shared pytest fixtures.

Tests run against in-memory SQLite by default. To run the same suite against
MySQL (e.g. the local cloudops360_test database) set TEST_DATABASE_URL, or use
scripts\\run_tests_mysql.ps1.
"""
import io
import os
import uuid

# Tests must not depend on a developer's local .env (set before the app is imported)
os.environ['CLOUDOPS_SKIP_DOTENV'] = '1'

import pytest
from flask.testing import FlaskClient

from app import create_app
from app.extensions import db
from app.models import (
    SLAPolicy, Ticket, TicketCategory, TicketPriority, TicketStatus, User, UserRole, utcnow,
)
from app.services.sla import apply_sla_to_ticket

PASSWORDS = {
    'test_admin': 'AdminSecure123!',
    'test_tech': 'TechSecure123!',
    'other_tech': 'TechSecure456!',
    'test_emp': 'EmpSecure123!',
    'other_emp': 'OtherSecure123!',
}

PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64


class FreshContextClient(FlaskClient):
    """Runs every request in its own app context, exactly like production.

    Without this, requests would reuse the fixture's long-lived app context (and
    its cached flask.g user), which hides real per-request behaviour. After each
    request the test's own session is expired so assertions read fresh rows.
    """

    def open(self, *args, **kwargs):
        # End the test's own transaction so (on MySQL REPEATABLE READ) neither side
        # works from a stale snapshot, then run the request in a fresh context.
        db.session.commit()
        with self.application.app_context():
            response = super().open(*args, **kwargs)
        db.session.commit()
        db.session.expire_all()
        return response


@pytest.fixture
def app(tmp_path):
    app = create_app('testing', config_overrides={'UPLOAD_FOLDER': str(tmp_path / 'uploads')})
    app.test_client_class = FreshContextClient

    with app.app_context():
        db.drop_all()
        db.create_all()
        db.session.add_all([
            SLAPolicy(priority=TicketPriority.CRITICAL, response_time_hours=1, resolution_time_hours=4),
            SLAPolicy(priority=TicketPriority.HIGH, response_time_hours=4, resolution_time_hours=12),
            SLAPolicy(priority=TicketPriority.MEDIUM, response_time_hours=8, resolution_time_hours=24),
            SLAPolicy(priority=TicketPriority.LOW, response_time_hours=24, resolution_time_hours=72),
            TicketCategory(name='Cloud Infrastructure', description='EC2 and VPC issues', is_active=True),
            TicketCategory(name='Database & Storage', description='RDS and EFS issues', is_active=True),
        ])
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def runner(app):
    return app.test_cli_runner()


def _make_user(username, role, full_name, active=True):
    user = User(username=username, email=f'{username}@test.local', full_name=full_name,
                role=role, is_active=active, department='QA')
    user.set_password(PASSWORDS[username])
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def admin_user(app):
    return _make_user('test_admin', UserRole.ADMIN, 'Admin User')


@pytest.fixture
def tech_user(app):
    return _make_user('test_tech', UserRole.TECHNICIAN, 'Technician User')


@pytest.fixture
def other_tech(app):
    return _make_user('other_tech', UserRole.TECHNICIAN, 'Other Technician')


@pytest.fixture
def emp_user(app):
    return _make_user('test_emp', UserRole.EMPLOYEE, 'Employee User')


@pytest.fixture
def other_emp_user(app):
    return _make_user('other_emp', UserRole.EMPLOYEE, 'Other Employee')


def login(client, username, password=None):
    return client.post('/auth/login', data={
        'username_or_email': username,
        'password': password if password is not None else PASSWORDS[username],
    })


def logout(client):
    return client.post('/auth/logout')


def make_ticket(creator, technician=None, status=TicketStatus.OPEN, priority=TicketPriority.MEDIUM,
                created_at=None, title='Test incident', category=None):
    """Inserts a ticket directly (bypassing HTTP) for permission tests."""
    category = category or TicketCategory.query.first()
    now = created_at or utcnow()
    ticket = Ticket(reference_id=f'TMP-{uuid.uuid4().hex[:20]}', title=title,
                    description='Detailed description of the problem.', category_id=category.id,
                    priority=priority, status=status, creator_id=creator.id,
                    technician_id=technician.id if technician else None, created_at=now, updated_at=now)
    apply_sla_to_ticket(ticket, start_time=now)
    db.session.add(ticket)
    db.session.flush()
    ticket.reference_id = f'INC-{now.year}-{ticket.id:05d}'
    db.session.commit()
    return ticket


def file_upload(data=PNG_BYTES, name='screenshot.png'):
    return (io.BytesIO(data), name)
