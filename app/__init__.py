import os
from datetime import datetime, timezone
from flask import Flask, render_template
from config import config_by_name
from app.extensions import db, migrate, login_manager, csrf


def create_app(config_name=None):
    """
    Application factory for CloudOps 360.
    Initializes Flask application, extensions, blueprints, and security filters.
    """
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config_by_name.get(config_name, config_by_name['default']))

    # Initialize Flask Extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    # Register Blueprints
    from app.main.routes import main_bp
    from app.auth.routes import auth_bp
    from app.tickets.routes import tickets_bp
    from app.dashboard.routes import dashboard_bp
    from app.technician.routes import technician_bp
    from app.admin.routes import admin_bp
    from app.attachments.routes import attachments_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(technician_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(attachments_bp)

    # Custom Jinja Template Filters
    @app.template_filter('datetimeformat')
    def datetimeformat(value, format='%b %d, %Y %H:%M UTC'):
        if value is None:
            return "—"
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return value
        return value.strftime(format)

    @app.template_filter('dateformat')
    def dateformat(value, format='%b %d, %Y'):
        if value is None:
            return "—"
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return value
        return value.strftime(format)

    # Context Processors for Global Template Variables
    @app.context_processor
    def inject_global_data():
        from flask_login import current_user
        from app.services.notifications import get_unread_count, get_user_notifications
        
        unread_count = 0
        user_notifications = []
        if current_user.is_authenticated:
            unread_count = get_unread_count(current_user.id)
            user_notifications = get_user_notifications(current_user.id, limit=5)

        return {
            'app_name': 'CloudOps 360',
            'app_tagline': 'Intelligent IT Operations. Secure by Design.',
            'unread_notifications_count': unread_count,
            'recent_notifications': user_notifications,
            'current_year': datetime.now(timezone.utc).year
        }

    # Error Handlers with Professional IT Operation Views
    @app.errorhandler(400)
    def bad_request(e):
        return render_template('errors/400.html', error=e), 400

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html', error=e), 403

    @app.errorhandler(404)
    def page_not_found(e):
        return render_template('errors/404.html', error=e), 404

    @app.errorhandler(500)
    def internal_server_error(e):
        return render_template('errors/500.html', error=e), 500

    # Register custom CLI commands
    register_commands(app)

    return app


def register_commands(app):
    """Registers custom flask CLI commands."""
    import click

    @app.cli.command('seed-db')
    @click.option('--no-input', is_flag=True, help='Skip confirmation prompt')
    def seed_db_command(no_input):
        """Seed initial categories, SLA policies, and development demonstration users."""
        from scripts.seed_data import seed_database
        seed_database()
        click.echo("[CloudOps 360] Database successfully seeded with baseline datasets.")

    @app.cli.command('init-db')
    def init_db_command():
        """Creates all database tables directly."""
        with app.app_context():
            db.create_all()
            click.echo("[CloudOps 360] Database tables successfully created.")
