# CloudOps 360 — Security Verification Checklist

Status legend:
* ✅ **Verified locally** — proven by an automated test (named) that passes on SQLite *and* MySQL 8.0, or by a recorded local check.
* 🟡 **Scripted, AWS verification pending** — implemented in `infrastructure/aws/` or documented; must be confirmed on your AWS resources with `verify_deployment.sh` / CloudShell before claiming it.
* ⛔ **Not implemented**.

Last local run: `pytest` → **123 passed** (SQLite) and **123 passed** (MySQL 8.0.43 via `scripts\run_tests_mysql.ps1`).

## 1. Application security

| # | Control | Implementation | Evidence | Status |
| :-: | :--- | :--- | :--- | :-: |
| A1 | Password hashing | Werkzeug `generate_password_hash` (scrypt) | `test_auth::test_passwords_are_hashed` | ✅ |
| A2 | Password strength | ≥10 chars, upper/lower/digit (`StrongPassword`); admin CLI ≥12 | `test_auth::test_registration_rejects_weak_password_and_duplicates`, `test_security::test_create_admin_command_requires_strong_password` | ✅ |
| A3 | Login rate limiting | DB-backed per-account (5/15 min) and per-IP (20/15 min) lockout → 429 | `test_auth::test_account_lockout_after_repeated_failures`, `test_ip_rate_limit_blocks_password_spraying` | ✅ |
| A4 | No user enumeration | identical message for unknown user/wrong password; dummy hash equalises timing | `test_auth::test_unknown_user_gets_same_generic_message` | ✅ |
| A5 | Account status checks | inactive users cannot sign in; active sessions revoked on next request | `test_auth::test_deactivated_account_cannot_log_in`, `test_deactivation_ends_existing_session` | ✅ |
| A6 | Session expiration | 30 min idle + 8 h absolute; background polling does not extend sessions | `test_auth::test_session_idle_timeout`, `test_session_absolute_timeout`, `test_background_poll_does_not_extend_session` | ✅ |
| A7 | Session fixation | session cleared before `login_user` | code review `auth/routes.py` | ✅ |
| A8 | Secure cookies | HttpOnly, SameSite=Lax, `Secure` in production (env override only for HTTP labs) | `test_security::test_session_cookie_flags`, `test_production_config_is_hardened` | ✅ |
| A9 | CSRF protection | Flask-WTF on every form; JSON POSTs send `X-CSRFToken`; logout is POST-only | `test_security::test_csrf_is_enforced_when_enabled`, `test_auth::test_logout_requires_post_and_clears_session` | ✅ |
| A10 | Server-side RBAC | `role_required` decorators + `services/permissions.py` on every ticket route | `test_rbac.py` (16 tests) | ✅ |
| A11 | Employees isolated to own tickets (list, detail, search, attachments, notifications) | `visible_tickets_query`, `can_view_ticket` | `test_rbac::test_employee_cannot_view_other_employees_ticket`, `test_employee_ticket_list_is_scoped_to_own_tickets`, `test_workflow::test_cannot_read_other_users_notifications` | ✅ |
| A12 | Privilege escalation blocked | role never read from registration/profile requests; admin-only endpoints; admins cannot demote themselves; last admin protected | `test_rbac::test_profile_form_cannot_escalate_role`, `test_employee_cannot_use_admin_user_edit_endpoint`, `test_admin_cannot_demote_or_deactivate_self`, `test_auth::test_registration_creates_employee_only` | ✅ |
| A13 | Internal notes private | SQL filter `is_internal = false` for employees; employees cannot create internal notes | `test_internal_notes.py` (5 tests) | ✅ |
| A14 | Workflow integrity | transitions validated server-side per role; resolution summary required | `test_workflow.py` (16 tests) | ✅ |
| A15 | Upload validation | extension whitelist, magic-byte check, UTF-8 check for text, empty-file and size limits (streamed), 413 on oversized requests | `test_attachments::test_upload_validation` (6 cases), `test_oversized_upload_rejected` | ✅ |
| A16 | Path traversal prevented | generated keys `YYYY/MM/<uuid>.<ext>`; `secure_filename`; `commonpath` containment | `test_attachments::test_path_traversal_filename_is_neutralised`, `test_storage_rejects_keys_outside_root` | ✅ |
| A17 | Authorized downloads only | `can_download_attachment` = ticket visibility; denials audited | `test_attachments::test_authorized_downloads` | ✅ |
| A18 | Safe download headers | `Content-Disposition: attachment`, `nosniff`, `CSP: sandbox`, `no-store` | `test_attachments::test_authorized_downloads` | ✅ |
| A19 | Safe HTML output | Jinja2 autoescaping; no `|safe` on user data; toasts built with `textContent` | code review; `test_pages.py` crawl | ✅ |
| A20 | SQL injection | SQLAlchemy ORM / bound parameters only; sort columns whitelisted | `test_security::test_sql_injection_attempts_are_inert`, `test_tickets::test_list_ignores_invalid_filter_values` | ✅ |
| A21 | Security headers | CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, HSTS on HTTPS | `test_security::test_security_headers` | ✅ |
| A22 | Open redirects | `next` must be a relative path; notification links internal-only | `test_auth::test_open_redirect_is_blocked`, `test_security::test_notification_links_cannot_open_redirect` | ✅ |
| A23 | Secrets never exposed | no SECRET_KEY/hashes/passwords in any page; `/health` shows engine type only | `test_security::test_secrets_and_hashes_never_rendered`, `test_health_reveals_no_connection_details` | ✅ |
| A24 | Audit logging | auth events, denials, assignments, status, priority, role/status/password-reset changes, SLA/category edits, uploads/downloads, CSRF rejections; credentials scrubbed | assertions throughout `test_auth`, `test_rbac`, `test_workflow`, `test_attachments`; `test_security::test_audit_scrubs_credentials` | ✅ |
| A25 | Production fails closed | no SECRET_KEY / short key / no database → start-up error; demo seed refused | `test_security::test_production_fails_closed_*`, `test_seed_command_refused_in_production` | ✅ |
| A26 | Secrets not in Git | `.env`, `*.db`, `uploads/`, `instance/` ignored; `.env.example` placeholders only; Docker Compose reads passwords from `.env` | `git ls-files` review before each commit | ✅ |
| A27 | DB constraints | CHECK constraints for role/status/priority/SLA | MySQL 8.0 rejected invalid updates with error 3819 (manual check, 2026-10-14) | ✅ |

## 2. AWS security (Lab 3)

| # | Control | Implementation | How to verify | Status |
| :-: | :--- | :--- | :--- | :-: |
| W1 | EC2 IAM instance role, no access keys | `iam_ec2_trust_policy.json`; boto3 uses instance credentials | `verify_deployment.sh` (role attached, no `~/.aws/credentials`, no `AKIA` keys) | 🟡 |
| W2 | Least-privilege policy | `iam_instance_profile_policy.json`: GetSecretValue on 2 secrets; ClientMount/Write on 1 file system | `aws iam get-role-policy ...` | 🟡 |
| W3 | Secrets Manager for DB credentials and SECRET_KEY | `DB_SECRET_NAME`, `APP_SECRET_NAME` (`services/secrets.py`) | `verify_deployment.sh` (no `DATABASE_URL` in env file) | 🟡 |
| W4 | HTTPS/TLS | `nginx_https.conf`, `tls_self_signed.sh` / certbot; HTTP → HTTPS redirect | `verify_deployment.sh` (HSTS, redirect), browser padlock | 🟡 |
| W5 | RDS encrypted at rest | chosen at creation | `aws rds describe-db-instances` → `StorageEncrypted: true` | 🟡 |
| W6 | EFS encrypted at rest | chosen at creation | `aws efs describe-file-systems` → `Encrypted: true` | 🟡 |
| W7 | TLS to RDS | `DB_SSL_CA` + `REQUIRE SSL` user | `verify_deployment.sh` → `Ssl_version` | 🟡 |
| W8 | TLS to EFS | efs-utils `tls`; file-system policy denies insecure transport | `verify_deployment.sh` (fstab `tls`, stunnel/efs-proxy) | 🟡 |
| W9 | RDS private | Public access = No; 3306 only from web SG | `describe-db-instances` → `PubliclyAccessible: false`; SG rules | 🟡 |
| W10 | EFS private | mount targets in private subnets; 2049 only from web SG | `describe-mount-targets`; SG rules | 🟡 |
| W11 | Restricted SSH | 22 from one /32 or removed | SG rules | 🟡 |
| W12 | Minimal exposure on host | Gunicorn 127.0.0.1:8000; MariaDB 127.0.0.1 (Lab 1) | `verify_deployment.sh` (listening sockets) | 🟡 |
| W13 | Service hardening | dedicated `cloudops` user, systemd `NoNewPrivileges`, `ProtectSystem`, env file 0640 | `verify_deployment.sh` (env file permissions) | 🟡 |

**Fallback if Secrets Manager is unavailable:** credentials stay in `/etc/cloudops360/cloudops360.env`
(root:cloudops 0640, outside the repository). This is weaker (readable by root and the service
user, no rotation) and must be stated as a limitation in the lab report.

## 3. How to re-run the evidence locally
```powershell
.venv\Scripts\python -m pytest -q                                   # SQLite
powershell -ExecutionPolicy Bypass -File scripts\run_tests_mysql.ps1 -q   # MySQL
```
