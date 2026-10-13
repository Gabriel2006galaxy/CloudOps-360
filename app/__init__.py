import logging
import os
import time
from datetime import timedelta, timezone

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, logout_user
from flask_wtf.csrf import CSRFError
from werkzeug.middleware.proxy_fix import ProxyFix

from config import config_by_name
from app.extensions import csrf, db, login_manager, migrate


def create_app(config_name=None, config_overrides=None):
    """Application factory for CloudOps 360.

    config_overrides: optional dict applied after the config class (used by tests).
    """
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config_by_name.get(config_name, config_by_name['default']))
    if config_overrides:
        app.config.update(config_overrides)

    if not app.logger.handlers or app.config.get('ENV_NAME') == 'production':
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s [%(name)s] %(message)s')

    # Resolve SECRET_KEY and database credentials (Secrets Manager / .env / dev fallback)
    from app.services.secrets import resolve_runtime_secrets
    resolve_runtime_secrets(app)

    # Behind Nginx: trust exactly TRUSTED_PROXY_COUNT hops of X-Forwarded-* headers
    proxies = app.config.get('TRUSTED_PROXY_COUNT', 0)
    if proxies:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxies, x_proto=proxies, x_host=proxies, x_port=proxies)

    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app.main.routes import main_bp
    from app.auth.routes import auth_bp
    from app.tickets.routes import tickets_bp
    from app.dashboard.routes import dashboard_bp
    from app.technician.routes import technician_bp
    from app.admin.routes import admin_bp
    from app.attachments.routes import attachments_bp

    for bp in (main_bp, auth_bp, tickets_bp, dashboard_bp, technician_bp, admin_bp, attachments_bp):
        app.register_blueprint(bp)

    register_template_helpers(app)
    register_security_hooks(app)
    register_error_handlers(app)
    register_commands(app)
    if app.config.get('ENV_NAME') == 'development':
        warn_if_database_not_ready(app)
    return app


def warn_if_database_not_ready(app):
    """Explain a fresh checkout's missing setup instead of failing later with 'no such table'."""
    from sqlalchemy import inspect

    with app.app_context():
        try:
            ready = inspect(db.engine).has_table('users')
        except Exception as exc:  # noqa: BLE001 - e.g. MySQL not running
            app.logger.warning("[Setup] Cannot connect to the database (%s). Check DATABASE_URL in .env "
                               "and that MySQL is running.", type(exc).__name__)
            return
    if not ready:
        app.logger.warning("[Setup] The database has no tables yet. Run:  flask db upgrade  then  flask seed-db  "
                           "(demo accounts), then start the app again.")


def register_template_helpers(app):
    from app.models import as_utc

    @app.template_filter('datetimeformat')
    def datetimeformat(value, format='%b %d, %Y %H:%M UTC'):
        if value is None:
            return '—'
        return as_utc(value).strftime(format)

    @app.template_filter('dateformat')
    def dateformat(value, format='%b %d, %Y'):
        if value is None:
            return '—'
        return as_utc(value).strftime(format)

    @app.template_filter('isoformat')
    def isoformat(value):
        return as_utc(value).isoformat() if value else ''

    @app.template_filter('timeago')
    def timeago(value):
        if value is None:
            return '—'
        from datetime import datetime
        seconds = (datetime.now(timezone.utc) - as_utc(value)).total_seconds()
        future = seconds < 0
        seconds = abs(seconds)
        for unit, size in (('d', 86400), ('h', 3600), ('m', 60)):
            if seconds >= size:
                text = f"{int(seconds // size)}{unit}"
                return f"in {text}" if future else f"{text} ago"
        return 'just now'

    @app.context_processor
    def inject_global_data():
        from datetime import datetime
        from app.services.notifications import get_unread_count, get_user_notifications

        unread_count = 0
        user_notifications = []
        if current_user.is_authenticated:
            unread_count = get_unread_count(current_user.id)
            user_notifications = get_user_notifications(current_user.id, limit=6)

        return {
            'app_name': 'CloudOps 360',
            'app_tagline': 'Intelligent IT Operations. Secure by Design.',
            'unread_notifications_count': unread_count,
            'recent_notifications': user_notifications,
            'current_year': datetime.now(timezone.utc).year,
            'allow_registration': app.config.get('ALLOW_SELF_REGISTRATION', False),
            'show_demo_accounts': app.config.get('SHOW_DEMO_ACCOUNTS', False),
            'session_idle_minutes': app.config.get('SESSION_IDLE_TIMEOUT_MINUTES', 30),
        }


def register_security_hooks(app):
    @app.before_request
    def enforce_session_policy():
        if request.endpoint in ('static', 'main.health'):
            return None
        # Note: Flask-Login's is_authenticated is False for inactive users, so test
        # is_anonymous first to catch sessions of accounts deactivated mid-session.
        if current_user.is_anonymous:
            return None

        from app.services.audit import log_audit_event

        # Account status is checked on every request, so deactivation takes effect immediately
        if not current_user.is_active:
            user_id, username = current_user.id, current_user.username
            logout_user()
            session.clear()
            log_audit_event('AUTH_SESSION_REVOKED_DEACTIVATED', 'User', user_id,
                            f"Active session of deactivated account '{username}' terminated", user_id=user_id)
            flash('Your account has been deactivated. Please contact an administrator.', 'danger')
            return redirect(url_for('auth.login'))

        now = time.time()
        idle_limit = app.config.get('SESSION_IDLE_TIMEOUT_MINUTES', 30) * 60
        absolute_limit = app.config.get('SESSION_ABSOLUTE_TIMEOUT_HOURS', 8) * 3600
        last_seen = session.get('last_seen', now)
        login_at = session.get('login_at', now)
        if now - last_seen > idle_limit or now - login_at > absolute_limit:
            user_id = current_user.id
            logout_user()
            session.clear()
            log_audit_event('AUTH_SESSION_EXPIRED', 'User', user_id, 'Session expired', user_id=user_id)
            if request.accept_mimetypes.best == 'application/json' or request.path.startswith('/api/'):
                return jsonify({'error': 'session_expired'}), 401
            flash('Your session expired. Please sign in again.', 'warning')
            return redirect(url_for('auth.login', next=request.full_path if request.method == 'GET' else None))

        session.permanent = True
        # Background polling must not keep an idle session alive
        if not request.headers.get('X-Background-Poll'):
            session['last_seen'] = now
        session.setdefault('login_at', now)
        return None

    @app.after_request
    def security_headers(response):
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
        response.headers.setdefault(
            'Content-Security-Policy',
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'"
        )
        if current_user.is_authenticated and request.endpoint != 'static':
            response.headers.setdefault('Cache-Control', 'no-store')
        if app.config.get('ENABLE_HSTS') and request.is_secure:
            response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
        return response


def register_error_handlers(app):
    def render_error(code, title, message):
        if request.path.startswith('/api/') or request.accept_mimetypes.best == 'application/json':
            return jsonify({'error': title, 'message': message}), code
        return render_template('errors/error.html', code=code, title=title, message=message), code

    @app.errorhandler(400)
    def bad_request(e):
        return render_error(400, 'Bad Request', getattr(e, 'description', None) or 'The request could not be understood.')

    @app.errorhandler(CSRFError)
    def csrf_error(e):
        from app.services.audit import log_audit_event
        log_audit_event('SECURITY_CSRF_REJECTED', 'Endpoint', request.path, 'Request rejected: missing or invalid CSRF token')
        return render_error(400, 'Security Check Failed',
                            'Your form expired or was not submitted from this site. Reload the page and try again.')

    @app.errorhandler(403)
    def forbidden(e):
        return render_error(403, 'Access Denied', 'You do not have permission to access this resource.')

    @app.errorhandler(404)
    def page_not_found(e):
        return render_error(404, 'Page Not Found', 'The page or record you requested does not exist.')

    @app.errorhandler(405)
    def method_not_allowed(e):
        return render_error(405, 'Method Not Allowed', 'This action is not available with that request method.')

    @app.errorhandler(413)
    def too_large(e):
        limit = app.config.get('MAX_UPLOAD_BYTES', 0) // (1024 * 1024) or 1
        return render_error(413, 'File Too Large', f'Uploads are limited to {limit} MB per file.')

    @app.errorhandler(429)
    def too_many(e):
        return render_error(429, 'Too Many Requests', 'Too many attempts. Please wait and try again.')

    @app.errorhandler(500)
    def internal_server_error(e):
        db.session.rollback()
        return render_error(500, 'Server Error', 'An unexpected error occurred. The operations team has been notified.')


def register_commands(app):
    """Custom flask CLI commands."""
    import click

    @app.cli.command('seed-db')
    @click.option('--with-demo-tickets/--no-demo-tickets', default=True, help='Also create sample incidents.')
    def seed_db_command(with_demo_tickets):
        """Seed categories, SLA policies and DEVELOPMENT demo accounts (refused in production)."""
        if app.config.get('ENV_NAME') == 'production':
            raise click.ClickException(
                'seed-db creates demo accounts with known passwords and is disabled in production. '
                'Use `flask seed-reference-data` and `flask create-admin` instead.'
            )
        from scripts.seed_data import seed_database
        seed_database(with_demo_tickets=with_demo_tickets)
        click.echo('[CloudOps 360] Database seeded with development data.')

    @app.cli.command('seed-reference-data')
    def seed_reference_command():
        """Seed only categories and SLA policies (safe for production; creates no users)."""
        from scripts.seed_data import seed_reference_data
        seed_reference_data()
        click.echo('[CloudOps 360] Categories and SLA policies are in place.')

    @app.cli.command('create-admin')
    @click.option('--username', prompt=True)
    @click.option('--email', prompt=True)
    @click.option('--full-name', prompt=True)
    @click.password_option()
    def create_admin_command(username, email, full_name, password):
        """Create an administrator interactively (password is prompted, never a default)."""
        from app.models import User, UserRole
        from app.services.audit import log_audit_event
        if len(password) < 12:
            raise click.ClickException('Administrator passwords must be at least 12 characters.')
        if User.query.filter((User.username == username) | (User.email == email.lower())).first():
            raise click.ClickException('A user with that username or email already exists.')
        user = User(username=username.strip(), email=email.strip().lower(), full_name=full_name.strip(),
                    role=UserRole.ADMIN, is_active=True)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        log_audit_event('ADMIN_USER_CREATE_CLI', 'User', user.id, f"Administrator '{user.username}' created from CLI",
                        user_id=user.id)
        click.echo(f"[CloudOps 360] Administrator '{user.username}' created.")

    @app.cli.command('init-db')
    def init_db_command():
        """Create tables directly (prefer `flask db upgrade`)."""
        db.create_all()
        click.echo('[CloudOps 360] Database tables created.')

    @app.cli.command('storage-check')
    def storage_check_command():
        """Verify every attachment row has its file on storage (EFS) with a matching checksum."""
        from app.models import Attachment
        from app.services.storage import get_storage
        storage = get_storage()
        health = storage.health()
        click.echo(f"Storage root : {storage.root}")
        click.echo(f"Backend      : {health.get('backend')}  instance={health.get('instance')}")
        if 'mounted' in health:
            click.echo(f"EFS mounted  : {health['mounted']}")
        click.echo(f"Probe        : {health.get('status')}")
        ok = missing = mismatch = 0
        for att in Attachment.query.order_by(Attachment.id).all():
            if not storage.exists(att.storage_path):
                missing += 1
                click.echo(f"  MISSING   #{att.id} {att.storage_path} ({att.original_filename})")
            elif att.checksum_sha256 and storage.checksum(att.storage_path) != att.checksum_sha256:
                mismatch += 1
                click.echo(f"  MISMATCH  #{att.id} {att.storage_path}")
            else:
                ok += 1
                click.echo(f"  OK        #{att.id} {att.storage_path} {att.file_size}B sha256={(att.checksum_sha256 or '-')[:12]}")
        click.echo(f"Summary: {ok} ok, {missing} missing, {mismatch} checksum mismatches")
        if missing or mismatch or health.get('status') != 'accessible':
            raise SystemExit(1)

    @app.cli.command('purge-login-attempts')
    @click.option('--days', default=30, show_default=True)
    def purge_login_attempts_command(days):
        """Delete sign-in attempt records older than N days."""
        from app.services.login_security import purge_old_attempts
        click.echo(f"Deleted {purge_old_attempts(days)} old login attempt records.")
