import os
import pytest
from app import create_app
from app.extensions import db
from app.models import User, UserRole, TicketCategory, SLAPolicy, Ticket, TicketStatus, TicketPriority, Comment


@pytest.fixture
def app():
    """Create and configure a testing Flask application instance."""
    app = create_app('testing')
    
    with app.app_context():
        db.create_all()
        # Seed default SLA policies
        policies = [
            SLAPolicy(priority=TicketPriority.CRITICAL, response_time_hours=1, resolution_time_hours=4),
            SLAPolicy(priority=TicketPriority.HIGH, response_time_hours=4, resolution_time_hours=12),
            SLAPolicy(priority=TicketPriority.MEDIUM, response_time_hours=8, resolution_time_hours=24),
            SLAPolicy(priority=TicketPriority.LOW, response_time_hours=24, resolution_time_hours=72)
        ]
        db.session.add_all(policies)

        # Seed categories
        cat1 = TicketCategory(name='Cloud Infrastructure', description='EC2 and VPC issues', is_active=True)
        cat2 = TicketCategory(name='Database & Storage', description='RDS and EFS issues', is_active=True)
        db.session.add_all([cat1, cat2])
        db.session.commit()

        yield app

        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Test client for simulating HTTP requests."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """CLI runner for testing Flask commands."""
    return app.test_cli_runner()


@pytest.fixture
def admin_user(app):
    with app.app_context():
        user = User(
            username='test_admin',
            email='admin@test.local',
            full_name='Admin User',
            role=UserRole.ADMIN,
            is_active=True
        )
        user.set_password('AdminSecure123!')
        db.session.add(user)
        db.session.commit()
        return user


@pytest.fixture
def tech_user(app):
    with app.app_context():
        user = User(
            username='test_tech',
            email='tech@test.local',
            full_name='Technician User',
            role=UserRole.TECHNICIAN,
            is_active=True
        )
        user.set_password('TechSecure123!')
        db.session.add(user)
        db.session.commit()
        return user


@pytest.fixture
def emp_user(app):
    with app.app_context():
        user = User(
            username='test_emp',
            email='emp@test.local',
            full_name='Employee User',
            role=UserRole.EMPLOYEE,
            is_active=True
        )
        user.set_password('EmpSecure123!')
        db.session.add(user)
        db.session.commit()
        return user


@pytest.fixture
def other_emp_user(app):
    with app.app_context():
        user = User(
            username='other_emp',
            email='other@test.local',
            full_name='Other Employee',
            role=UserRole.EMPLOYEE,
            is_active=True
        )
        user.set_password('OtherSecure123!')
        db.session.add(user)
        db.session.commit()
        return user
