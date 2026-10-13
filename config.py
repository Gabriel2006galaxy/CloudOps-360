import os
from datetime import timedelta
from dotenv import load_dotenv

# Load local environment variables from .env file if present
load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    """Base configuration shared across all environments."""
    SECRET_KEY = os.environ.get('SECRET_KEY', 'cloudops360-dev-insecure-secret-key-replace-in-prod')
    
    # SQLAlchemy configuration
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_recycle': 280,
        'pool_pre_ping': True,
    }
    
    # Storage abstraction (Amazon EFS mount path or local directory fallback)
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', os.path.join(BASE_DIR, 'uploads'))
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 10 * 1024 * 1024))  # 10 MB limit
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'txt', 'log', 'docx', 'csv', 'zip'}
    
    # Security & Session Settings
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(minutes=int(os.environ.get('PERMANENT_SESSION_LIFETIME_MINUTES', 60)))
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

    # AWS Configuration
    AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')
    AWS_SECRETS_NAME = os.environ.get('AWS_SECRETS_NAME', None)

    @classmethod
    def get_database_uri(cls):
        """
        Resolves the database URI.
        1. Checks for AWS Secrets Manager secret if configured
        2. Checks DATABASE_URL environment variable (MySQL / RDS)
        3. Falls back to local SQLite file for immediate out-of-the-box local operation
        """
        if cls.AWS_SECRETS_NAME:
            try:
                from app.services.secrets import fetch_secret_database_uri
                aws_uri = fetch_secret_database_uri(cls.AWS_SECRETS_NAME, cls.AWS_REGION)
                if aws_uri:
                    return aws_uri
            except Exception as e:
                print(f"[Config] Warning: Could not retrieve DB URI from AWS Secrets Manager: {e}")

        env_db = os.environ.get('DATABASE_URL')
        if env_db:
            return env_db
            
        # SQLite fallback for developer quickstart or when MySQL is unconfigured
        return f"sqlite:///{os.path.join(BASE_DIR, 'cloudops360.db')}"


class DevelopmentConfig(Config):
    """Development configuration with debugging enabled."""
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    REMEMBER_COOKIE_SECURE = False
    SQLALCHEMY_DATABASE_URI = Config.get_database_uri()


class TestingConfig(Config):
    """Testing configuration with in-memory SQLite and isolated settings."""
    TESTING = True
    DEBUG = False
    WTF_CSRF_ENABLED = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'tests', 'test_uploads')
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    """Production configuration designed for EC2, RDS, and EFS."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    SQLALCHEMY_DATABASE_URI = Config.get_database_uri()
    # In production, default EFS mount is /mnt/efs/cloudops360-attachments
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', '/mnt/efs/cloudops360-attachments')


config_by_name = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
