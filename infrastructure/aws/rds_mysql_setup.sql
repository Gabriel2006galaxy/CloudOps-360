-- ==============================================================================
-- CloudOps 360: Amazon RDS MySQL Database Provisioning Script
-- Run as RDS Master User (e.g. admin) upon initial RDS instance creation
-- ==============================================================================

-- 1. Create CloudOps 360 Database with utf8mb4 character set for international text & emojis
CREATE DATABASE IF NOT EXISTS cloudops360
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

-- 2. Create dedicated least-privilege application user
-- Replace 'YourStrongPassword123!' with a cryptographically generated password stored in AWS Secrets Manager
CREATE USER IF NOT EXISTS 'cloudops_user'@'%' IDENTIFIED BY 'YourStrongPassword123!';

-- 3. Grant required application privileges (DML + Schema Migrations DDL)
-- Avoid granting administrative SUPER, RELOAD, or SHUTDOWN privileges
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, INDEX, ALTER, REFERENCES, LOCK TABLES 
  ON cloudops360.* 
  TO 'cloudops_user'@'%';

-- 4. Flush privileges
FLUSH PRIVILEGES;

-- 5. Verification query
SELECT user, host FROM mysql.user WHERE user = 'cloudops_user';
SHOW GRANTS FOR 'cloudops_user'@'%';
