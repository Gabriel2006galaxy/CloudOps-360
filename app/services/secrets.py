import os
import json
import logging

logger = logging.getLogger(__name__)


def fetch_secret_database_uri(secret_name, region_name='us-east-1'):
    """
    Fetches database credentials from AWS Secrets Manager and constructs
    a SQLAlchemy MySQL connection string.
    
    Expected JSON structure in Secrets Manager:
    {
      "username": "cloudops_admin",
      "password": "...",
      "host": "cloudops-db.cxxxxxx.us-east-1.rds.amazonaws.com",
      "port": 3306,
      "dbname": "cloudops360"
    }
    """
    try:
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError

        client = boto3.client(
            service_name='secretsmanager',
            region_name=region_name
        )
        response = client.get_secret_value(SecretId=secret_name)
        
        if 'SecretString' in response:
            secret = json.loads(response['SecretString'])
        else:
            logger.warning("[SecretsManager] Secret format binary not supported.")
            return None

        username = secret.get('username')
        password = secret.get('password')
        host = secret.get('host')
        port = secret.get('port', 3306)
        dbname = secret.get('dbname', 'cloudops360')

        if username and password and host:
            logger.info(f"[SecretsManager] Successfully loaded credentials for RDS host: {host}")
            return f"mysql+pymysql://{username}:{password}@{host}:{port}/{dbname}"
        else:
            logger.warning("[SecretsManager] Required DB secret keys missing in secret JSON payload.")
            return None

    except NoCredentialsError:
        logger.info("[SecretsManager] No AWS credentials or IAM role found. Using local configuration fallback.")
        return None
    except Exception as e:
        logger.warning(f"[SecretsManager] Notice: Could not retrieve secret '{secret_name}': {e}. Using local configuration fallback.")
        return None


def fetch_secret_value(secret_name, key=None, region_name='us-east-1'):
    """
    Generic helper to retrieve a secret or specific key from AWS Secrets Manager.
    """
    try:
        import boto3
        client = boto3.client(service_name='secretsmanager', region_name=region_name)
        response = client.get_secret_value(SecretId=secret_name)
        if 'SecretString' in response:
            data = json.loads(response['SecretString'])
            return data.get(key) if key else data
        return None
    except Exception as e:
        logger.debug(f"[SecretsManager] Failed fetching key '{key}' from '{secret_name}': {e}")
        return None
