import os
from datetime import timedelta
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Load local environment variables from .env (never committed) if present.
# The test-suite sets CLOUDOPS_SKIP_DOTENV=1 so a developer's .env cannot change test results.
if os.environ.get('CLOUDOPS_SKIP_DOTENV') != '1':
    load_dotenv(os.path.join(BASE_DIR, '.env'))


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None or value.strip() == '':
        return default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')


def env_int(name, default):
    value = os.environ.get(name)
    try:
        return int(value) if value not in (None, '') else default
    except ValueError:
        return default


class Config:
    """Base configuration shared across all environments.

    Secrets (SECRET_KEY, database credentials) are resolved at application
    start-up by app.services.secrets.resolve_runtime_secrets(), never at import
    time, so importing this module never calls AWS.
    """
    ENV_NAME = 'base'
    SECRET_KEY = os.environ.get('SECRET_KEY')

    # SQLAlchemy configuration (URI resolved in create_app)
    SQLALCHEMY_DATABASE_URI = None
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_recycle': 280,
        'pool_pre_ping': True,
    }
    ALLOW_SQLITE_FALLBACK = False
    # Optional path to the Amazon RDS CA bundle. When set, MySQL connections use TLS
    # and verify the server certificate (e.g. /etc/pki/rds/global-bundle.pem).
    DB_SSL_CA = os.environ.get('DB_SSL_CA')

    # Storage abstraction: local directory in development, Amazon EFS mount in production
    STORAGE_BACKEND = os.environ.get('STORAGE_BACKEND', 'local')  # 'local' or 'efs'
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(BASE_DIR, 'uploads'))
    EFS_MOUNT_POINT = os.environ.get('EFS_MOUNT_POINT', '/mnt/efs')
    MAX_UPLOAD_BYTES = env_int('MAX_UPLOAD_BYTES', 10 * 1024 * 1024)  # per file
    # Whole-request ceiling (form fields + file); Werkzeug rejects larger bodies with 413
    MAX_CONTENT_LENGTH = env_int('MAX_CONTENT_LENGTH', 12 * 1024 * 1024)
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'txt', 'log', 'docx', 'csv', 'zip'}

    # Session & cookie security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', False)
    SESSION_COOKIE_NAME = 'cloudops360_session'
    # Sessions expire after this much inactivity (sliding) ...
    SESSION_IDLE_TIMEOUT_MINUTES = env_int('SESSION_IDLE_TIMEOUT_MINUTES', 30)
    # ... and unconditionally this long after sign-in (absolute)
    SESSION_ABSOLUTE_TIMEOUT_HOURS = env_int('SESSION_ABSOLUTE_TIMEOUT_HOURS', 8)
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=SESSION_IDLE_TIMEOUT_MINUTES)
    REMEMBER_COOKIE_DURATION = timedelta(seconds=0)
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

    # Login brute-force protection (database backed so it works across EC2 instances)
    LOGIN_MAX_FAILED_PER_ACCOUNT = env_int('LOGIN_MAX_FAILED_PER_ACCOUNT', 5)
    LOGIN_MAX_FAILED_PER_IP = env_int('LOGIN_MAX_FAILED_PER_IP', 20)
    LOGIN_LOCKOUT_WINDOW_MINUTES = env_int('LOGIN_LOCKOUT_WINDOW_MINUTES', 15)

    # Number of reverse proxies in front of Gunicorn (Nginx = 1). 0 disables ProxyFix.
    TRUSTED_PROXY_COUNT = env_int('TRUSTED_PROXY_COUNT', 0)

    # Feature flags
    ALLOW_SELF_REGISTRATION = env_bool('ALLOW_SELF_REGISTRATION', True)
    SHOW_DEMO_ACCOUNTS = env_bool('SHOW_DEMO_ACCOUNTS', False)

    # AWS configuration (credentials come from the EC2 IAM instance role, never from code)
    AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
    # Secrets Manager secret holding {"username","password","host","port","dbname"}
    DB_SECRET_NAME = os.environ.get('DB_SECRET_NAME') or os.environ.get('AWS_SECRETS_NAME')
    # Secrets Manager secret holding {"SECRET_KEY": "..."} for the Flask session key
    APP_SECRET_NAME = os.environ.get('APP_SECRET_NAME')

    TICKETS_PER_PAGE = 10


class DevelopmentConfig(Config):
    """Local development: MySQL via DATABASE_URL, debug on."""
    ENV_NAME = 'development'
    DEBUG = True
    ALLOW_SQLITE_FALLBACK = env_bool('ALLOW_SQLITE_FALLBACK', True)
    SHOW_DEMO_ACCOUNTS = env_bool('SHOW_DEMO_ACCOUNTS', True)
    DEV_FALLBACK_SECRET_KEY = 'cloudops360-dev-only-insecure-key'


class TestingConfig(Config):
    """Automated tests. Uses in-memory SQLite unless TEST_DATABASE_URL points at MySQL."""
    ENV_NAME = 'testing'
    TESTING = True
    DEBUG = False
    SECRET_KEY = 'cloudops360-test-secret-key'
    SQLALCHEMY_DATABASE_URI = os.environ.get('TEST_DATABASE_URL', 'sqlite:///:memory:')
    WTF_CSRF_ENABLED = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'tests', '.test_uploads')
    SESSION_COOKIE_SECURE = False
    MAX_UPLOAD_BYTES = 64 * 1024
    MAX_CONTENT_LENGTH = 256 * 1024
    ALLOW_SELF_REGISTRATION = True
    SHOW_DEMO_ACCOUNTS = False


class ProductionConfig(Config):
    """EC2 + Gunicorn + Nginx, Amazon RDS for MySQL, Amazon EFS for attachments.

    Fails closed: start-up aborts if no SECRET_KEY or database credentials are
    available rather than silently falling back to insecure defaults.
    """
    ENV_NAME = 'production'
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = env_bool('SESSION_COOKIE_SECURE', True)
    REMEMBER_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = 'https'
    STORAGE_BACKEND = os.environ.get('STORAGE_BACKEND', 'efs')
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', '/mnt/efs/cloudops360-attachments')
    TRUSTED_PROXY_COUNT = env_int('TRUSTED_PROXY_COUNT', 1)
    ALLOW_SELF_REGISTRATION = env_bool('ALLOW_SELF_REGISTRATION', False)
    # Off by default. Set SHOW_DEMO_ACCOUNTS=true only for a short-lived lab
    # demonstration: it shows the seeded demo passwords to anyone who opens the site.
    SHOW_DEMO_ACCOUNTS = env_bool('SHOW_DEMO_ACCOUNTS', False)
    # HSTS is only sent when the request arrived over HTTPS
    ENABLE_HSTS = env_bool('ENABLE_HSTS', True)


config_by_name = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
