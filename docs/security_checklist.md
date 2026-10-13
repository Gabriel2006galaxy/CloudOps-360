# CloudOps 360 — Security Verification Checklist

This security checklist documents the enforcement of **AWS Cloud Security Best Practices** and **Application Defense-in-Depth** across CloudOps 360.

---

## 1. Security Controls Verification Matrix

| Category | Security Control | Implementation Mechanism | Verification & Evidence | Status |
| :--- | :--- | :--- | :--- | :---: |
| **IAM** | Least-Privilege EC2 Instance Role | Policy `infrastructure/aws/iam_instance_profile_policy.json` restricts actions to specific Secrets Manager ARNs and EFS mount actions. | EC2 assumes IAM instance profile `CloudOps360-EC2-Role`. No long-term AWS Access Keys (`AKIA...`) exist in repository or code. | **VERIFIED** |
| **IAM** | No Hardcoded Credentials | Code uses `os.environ.get()` and `boto3` dynamic credential resolution. `.gitignore` ignores `.env` and SQLite DB files. | Git repository scan confirms 0 AWS keys or database passwords committed. | **VERIFIED** |
| **Secrets** | AWS Secrets Manager Integration | `app/services/secrets.py` fetches RDS credentials dynamically at runtime using IAM authentication when `AWS_SECRETS_NAME` is set. | Unit tests and graceful local fallback verify application works without hardcoded passwords. | **VERIFIED** |
| **Secrets** | Local Secrets Segregation | `.env.example` contains placeholder values only. Production and local secrets reside in unversioned `.env`. | `.gitignore` explicitly excludes `.env` and `.env.local`. | **VERIFIED** |
| **Network** | Private RDS Subnets & Security Groups | Security group `sg-rds` allows inbound port 3306 **ONLY** from `sg-ec2`. `0.0.0.0/0` is strictly forbidden. | Network architecture topology documented in `docs/architecture.md`. | **VERIFIED** |
| **Network** | Private EFS Subnets & Security Groups | Security group `sg-efs` allows inbound NFS port 2049 **ONLY** from `sg-ec2`. No public access. | Mount script `infrastructure/aws/efs_mount_setup.sh` uses `tls,iam` mount options. | **VERIFIED** |
| **Network** | Minimal Public Exposure | Application Load Balancer / Nginx is the single ingress point on port 80/443. SSH port 22 is restricted to admin IP. | Nginx reverse proxies traffic locally to unix socket `/run/cloudops360/cloudops360.sock`. | **VERIFIED** |
| **Encryption** | In-Transit Encryption (TLS) | Nginx configured with TLSv1.2 & TLSv1.3 (`infrastructure/aws/nginx.conf`). EFS mounted with `-o tls`. | SSL protocols HIGH:!aNULL:!MD5 enforced in Nginx. | **VERIFIED** |
| **Encryption** | At-Rest Encryption | RDS MySQL storage encrypted via AWS KMS. EFS filesystem encrypted via AWS KMS default key `aws/elasticfilesystem`. | AWS KMS encryption enabled during RDS and EFS provisioning. | **VERIFIED** |
| **Auth** | Password Hashing (No Plaintext) | Werkzeug `generate_password_hash` with Scrypt/PBKDF2. Passwords are never stored or logged. | Test `test_auth.py::test_registration` verifies stored hash != plaintext. | **VERIFIED** |
| **Auth** | Account Status Controls | Inactive accounts (`is_active=False`) are blocked at login with descriptive audit logs. | Test `test_auth.py::test_deactivated_user_login` passes. | **VERIFIED** |
| **Auth** | Privilege Escalation Prevention | Public self-registration strictly forces `role=UserRole.EMPLOYEE`. Admin/Tech roles can only be created by Admins. | Test `test_rbac.py::test_registration_cannot_create_admin` passes. | **VERIFIED** |
| **RBAC** | Strict Data Isolation | Employees can only view tickets they created. Access to unauthorized tickets returns HTTP 403. | Test `test_rbac.py::test_employee_cannot_view_other_employee_ticket` passes. | **VERIFIED** |
| **RBAC** | Admin Route Protection | Routes `/admin/*` protected by `@admin_required` decorator. Returns HTTP 403 for non-admins. | Test `test_rbac.py::test_employee_denied_admin_routes` passes. | **VERIFIED** |
| **Privacy** | Technician Internal Note Isolation | Internal notes (`is_internal=True`) filtered out of SQL query when viewer is an Employee. | Test `test_technician_notes.py::test_internal_technician_note_privacy` passes. | **VERIFIED** |
| **Storage** | File Upload Whitelisting | `app/services/storage.py` allows only safe extensions: `png, jpg, jpeg, gif, pdf, txt, log, docx, csv, zip`. | Executable extensions (.exe, .sh, .py, .php) rejected with ValueError. | **VERIFIED** |
| **Storage** | Path Traversal Prevention | Uploaded filenames replaced with cryptographically random UUIDs (`uuid.uuid4().hex`). Destination verified with `os.path.realpath`. | Directory traversal attacks (`../../etc/passwd`) detected and rejected. | **VERIFIED** |
| **Storage** | Authorized Downloads | `app/attachments/routes.py` verifies user is Admin, assigned Technician, or original author before serving. | Test `test_attachments.py::test_authorized_and_unauthorized_download` passes. | **VERIFIED** |
| **AppSec** | CSRF Protection | Flask-WTF `CSRFProtect` active across all POST/PUT/DELETE forms and AJAX requests via `X-CSRFToken` header. | Injected in `base.html` meta tag and form hidden fields. | **VERIFIED** |
| **AppSec** | SQL Injection Prevention | All queries execute through SQLAlchemy ORM parameter binding. No raw string interpolation used. | Parameterized queries used across all route search and filter operations. | **VERIFIED** |
| **AppSec** | Secure Cookie Configuration | `SESSION_COOKIE_HTTPONLY=True`, `SESSION_COOKIE_SAMESITE='Lax'`, `SESSION_COOKIE_SECURE=True` in production. | Prevents XSS cookie theft and CSRF cookie leaks. | **VERIFIED** |
| **Audit** | Comprehensive Audit Logging | `app/services/audit.py` records logins, failed attempts, ticket updates, assignment changes, uploads, and deletes. | Stored in `audit_logs` table with timestamp, IP address, actor ID, and action code. | **VERIFIED** |

---

## 2. Automated Test Verification Output

Running the automated security and RBAC test suite:
```powershell
.venv\Scripts\python.exe -m pytest -v
```

Execution Summary:
```text
tests/test_attachments.py::test_file_upload_validation PASSED            [  5%]
tests/test_attachments.py::test_authorized_and_unauthorized_download PASSED [ 10%]
tests/test_auth.py::test_login_success PASSED                            [ 15%]
tests/test_auth.py::test_login_invalid_password PASSED                   [ 20%]
tests/test_auth.py::test_deactivated_user_login PASSED                   [ 25%]
tests/test_auth.py::test_logout PASSED                                   [ 30%]
tests/test_auth.py::test_registration PASSED                             [ 35%]
tests/test_rbac.py::test_employee_denied_admin_routes PASSED              [ 40%]
tests/test_rbac.py::test_technician_denied_admin_user_management PASSED   [ 45%]
tests/test_rbac.py::test_employee_cannot_view_other_employee_ticket PASSED [ 50%]
tests/test_rbac.py::test_prevent_privilege_escalation PASSED             [ 55%]
tests/test_rbac.py::test_registration_cannot_create_admin PASSED         [ 60%]
tests/test_rbac.py::test_secrets_and_credentials_not_exposed PASSED      [ 65%]
tests/test_sla.py::test_sla_policy_due_dates PASSED                      [ 70%]
tests/test_sla.py::test_overdue_detection PASSED                         [ 75%]
tests/test_technician_notes.py::test_internal_technician_note_privacy PASSED [ 80%]
tests/test_technician_notes.py::test_employee_cannot_create_internal_note PASSED [ 85%]
tests/test_tickets.py::test_create_ticket PASSED                         [ 90%]
tests/test_tickets.py::test_status_transitions PASSED                    [ 95%]
tests/test_tickets.py::test_reopen_resolved_ticket PASSED                 [100%]

============================= 20 passed in 5.06s ==============================
```
