-- ==============================================================================
-- CloudOps 360 - Amazon RDS for MySQL: application database and least-privilege user
-- Run ONCE from the EC2 instance (the only host allowed through the DB security group):
--   mysql -h <rds-endpoint> -u admin -p --ssl-ca=/etc/pki/rds/global-bundle.pem < rds_mysql_setup.sql
-- Replace CHANGE_ME with a generated password and store it in Secrets Manager
-- (secret cloudops360/prod/db) - never commit it.
-- ==============================================================================

CREATE DATABASE IF NOT EXISTS cloudops360
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

-- '%' is acceptable because the RDS security group only admits the web tier's security group.
-- REQUIRE SSL makes the server refuse unencrypted connections from this account.
CREATE USER IF NOT EXISTS 'cloudops_user'@'%' IDENTIFIED BY 'CHANGE_ME' REQUIRE SSL;

-- DML + the DDL that Alembic migrations need; no global/admin privileges.
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, INDEX, ALTER, REFERENCES
  ON cloudops360.*
  TO 'cloudops_user'@'%';

SHOW GRANTS FOR 'cloudops_user'@'%';
