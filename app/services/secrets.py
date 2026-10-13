"""Runtime secret resolution.

Order of precedence for the database connection:
  1. AWS Secrets Manager secret named by DB_SECRET_NAME (production on EC2,
     credentials supplied by the EC2 IAM instance role - no access keys in code).
  2. DATABASE_URL environment variable (local .env, never committed).
  3. Development only: local SQLite file, with a loud warning.

Secret values are never logged, printed or returned to clients.
"""
import json
import logging
import os
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)


class SecretResolutionError(RuntimeError):
    """Raised when a required secret cannot be resolved in a fail-closed environment."""


def _get_secret_json(secret_name, region_name):
    """Returns the parsed JSON SecretString of a Secrets Manager secret."""
    import boto3  # imported lazily so local development does not need AWS

    client = boto3.client(service_name='secretsmanager', region_name=region_name)
    response = client.get_secret_value(SecretId=secret_name)
    if 'SecretString' not in response:
        raise SecretResolutionError(f"Secret '{secret_name}' is binary; a JSON SecretString is required.")
    return json.loads(response['SecretString'])


def build_mysql_uri(username, password, host, port=3306, dbname='cloudops360'):
    """Builds a PyMySQL SQLAlchemy URI, URL-encoding credentials safely."""
    return (
        f"mysql+pymysql://{quote_plus(str(username))}:{quote_plus(str(password))}"
        f"@{host}:{int(port)}/{dbname}?charset=utf8mb4"
    )


def fetch_secret_database_uri(secret_name, region_name='us-east-1'):
    """Fetches RDS credentials from AWS Secrets Manager and builds a SQLAlchemy URI.

    Accepts both a custom secret ({"username","password","host","port","dbname"})
    and an RDS-managed master secret ({"username","password"}), in which case the
    host comes from the DB_HOST environment variable.
    """
    secret = _get_secret_json(secret_name, region_name)
    username = secret.get('username')
    password = secret.get('password')
    host = secret.get('host') or os.environ.get('DB_HOST')
    port = secret.get('port') or os.environ.get('DB_PORT', 3306)
    dbname = secret.get('dbname') or os.environ.get('DB_NAME', 'cloudops360')
    if not (username and password and host):
        raise SecretResolutionError(
            f"Secret '{secret_name}' is missing username/password/host (set DB_HOST for RDS-managed secrets)."
        )
    logger.info("[Secrets] Database credentials loaded from AWS Secrets Manager secret '%s'.", secret_name)
    return build_mysql_uri(username, password, host, port, dbname)


def fetch_secret_value(secret_name, key, region_name='us-east-1'):
    """Returns a single key from a JSON secret."""
    return _get_secret_json(secret_name, region_name).get(key)


def resolve_runtime_secrets(app):
    """Populates SECRET_KEY and SQLALCHEMY_DATABASE_URI on the Flask config.

    Raises SecretResolutionError in production when anything required is missing.
    """
    cfg = app.config
    env_name = cfg.get('ENV_NAME')
    production = env_name == 'production'
    region = cfg.get('AWS_REGION', 'us-east-1')

    # ---- Flask SECRET_KEY ----
    if cfg.get('APP_SECRET_NAME'):
        try:
            value = fetch_secret_value(cfg['APP_SECRET_NAME'], 'SECRET_KEY', region)
            if value:
                cfg['SECRET_KEY'] = value
                app.logger.info("[Secrets] SECRET_KEY loaded from AWS Secrets Manager.")
        except Exception as exc:  # noqa: BLE001 - boto raises many types
            if production:
                raise SecretResolutionError(f"Could not load SECRET_KEY from Secrets Manager: {type(exc).__name__}") from exc
            app.logger.warning("[Secrets] SECRET_KEY secret unavailable (%s); using local value.", type(exc).__name__)

    if not cfg.get('SECRET_KEY'):
        if production:
            raise SecretResolutionError('SECRET_KEY is not set. Provide it via APP_SECRET_NAME or the environment.')
        cfg['SECRET_KEY'] = cfg.get('DEV_FALLBACK_SECRET_KEY', os.urandom(32).hex())
        app.logger.warning("[Secrets] Using the insecure development SECRET_KEY. Never do this in production.")
    elif production and len(cfg['SECRET_KEY']) < 32:
        raise SecretResolutionError('SECRET_KEY must be at least 32 characters in production.')

    # ---- Database URI ----
    if cfg.get('SQLALCHEMY_DATABASE_URI'):
        return  # explicitly configured (tests)

    uri = None
    if cfg.get('DB_SECRET_NAME'):
        try:
            uri = fetch_secret_database_uri(cfg['DB_SECRET_NAME'], region)
        except Exception as exc:  # noqa: BLE001
            if production:
                raise SecretResolutionError(
                    f"Could not load database credentials from Secrets Manager: {type(exc).__name__}"
                ) from exc
            app.logger.warning("[Secrets] DB secret unavailable (%s); falling back to DATABASE_URL.", type(exc).__name__)

    if not uri:
        uri = os.environ.get('DATABASE_URL')

    if not uri:
        if cfg.get('ALLOW_SQLITE_FALLBACK') and not production:
            base_dir = os.path.abspath(os.path.join(app.root_path, '..'))
            uri = f"sqlite:///{os.path.join(base_dir, 'cloudops360.db')}"
            app.logger.warning(
                "[Database] DATABASE_URL is not set - using local SQLite fallback. "
                "Configure MySQL in .env to match the RDS production engine."
            )
        else:
            raise SecretResolutionError('No database configured. Set DB_SECRET_NAME or DATABASE_URL.')

    cfg['SQLALCHEMY_DATABASE_URI'] = uri

    # TLS to MySQL / RDS when a CA bundle is configured
    if uri.startswith('mysql') and cfg.get('DB_SSL_CA'):
        engine_options = dict(cfg.get('SQLALCHEMY_ENGINE_OPTIONS') or {})
        connect_args = dict(engine_options.get('connect_args') or {})
        connect_args['ssl'] = {'ca': cfg['DB_SSL_CA']}
        engine_options['connect_args'] = connect_args
        cfg['SQLALCHEMY_ENGINE_OPTIONS'] = engine_options
        app.logger.info("[Database] TLS enabled for MySQL connections (server certificate verified against DB_SSL_CA).")


def describe_database(uri):
    """Returns a password-free description of the database for health/diagnostics."""
    if not uri:
        return 'unconfigured'
    if uri.startswith('sqlite'):
        return 'sqlite'
    if uri.startswith('mysql'):
        return 'mysql'
    return uri.split(':', 1)[0]
