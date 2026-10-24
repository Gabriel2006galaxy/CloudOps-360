# CloudOps 360 — Requirement-by-Requirement Checklist

Status key:
* ✅ **Done & tested** — implemented and covered by passing automated tests (SQLite **and** MySQL 8.0) and/or a recorded local verification.
* ☑️ **Done, manually verified** — implemented and checked by hand in the browser / CLI (no automated test).
* 🟡 **Scripted / documented — AWS verification pending** — needs your AWS account; never claimed as enabled until `verify_deployment.sh` / CloudShell output proves it.
* ⚠️ **Partial** — see note.
* ⛔ **Not done** — see note.

AWS verification (2026-10-24, own AWS account, ap-south-1): Labs 1–3 live; `verify_deployment.sh` every line PASS;
CloudShell evidence: RDS encrypted and not public, EFS encrypted, 3306/2049 only from the web security group,
SSH only from EC2 Instance Connect, IAM policy limited to 2 secrets and 1 file system.

Latest local verification (2026-10-25): `pytest` 145 passed on SQLite and 145 passed on MySQL 8.0.43;
migration `c3f1a9d27e64` upgraded/downgraded/re-upgraded on MySQL and `flask db check` clean; new
auto-assignment, availability and rating pages checked in the browser.

Earlier baseline (2026-10-14): `pytest` 123 passed on SQLite and 123 passed on MySQL 8.0.43;
migrations upgraded/downgraded/re-upgraded on MySQL; live server end-to-end check (CSRF, upload,
EFS-style storage, authorized/denied downloads, `storage-check`) passed; browser checks at desktop
and 375 px in dark and light themes.

## 1. Technology stack
| Requirement | Status | Evidence / note |
| :--- | :-: | :--- |
| HTML5, CSS3, ES6+, Bootstrap 5, Bootstrap Icons, Chart.js | ✅ | `app/templates`, `app/static`; `test_pages.py` crawl |
| Flask + Blueprints + Jinja2, app factory, config classes | ✅ | `app/__init__.py`, `config.py` |
| MySQL + Flask-SQLAlchemy + Flask-Migrate | ✅ | migrations verified on MySQL 8.0.43 |
| Flask-Login, Flask-WTF/WTForms, Werkzeug hashing | ✅ | `test_auth.py` |
| EC2 Linux, Nginx + Gunicorn | ☑️ | Lab 1 verified live in the AWS Academy Sandbox (Oct 2026): `http://<public-ip>` served by Nginx → Gunicorn, `/health` OK, MariaDB on the instance; installed by `user_data_demo.sh` → `ec2_bootstrap.sh`, `lab1_mariadb_on_ec2.sh` |
| Amazon RDS for MySQL | ☑️ | live since 2026-10-24 (own AWS account, Mumbai): MySQL 8.4, not public, encrypted, app user `REQUIRE SSL`; `verify_deployment.sh` all PASS |
| Amazon EFS | ☑️ | live: encrypted, TLS mount with the instance role, `/health` reports storage `efs` |
| IAM instance role, least privilege, Secrets Manager | ☑️ | live: role attached, no keys, DB credentials and session key from Secrets Manager (`security_checklist.md` W1–W3) |
| Git/GitHub, pytest | ✅ | GitHub `main`; 145 tests |
| Docker Compose for local dev | ⚠️ | file updated (no hard-coded passwords) but **not run** — Docker is not installed on the dev machine; local MySQL 8.0 service used instead |

## 2. UI/UX
| Requirement | Status | Evidence / note |
| :--- | :-: | :--- |
| Navy / white / blue-gray / cyan palette, polished cards & tables | ☑️ | browser review |
| Responsive desktop/tablet/mobile | ☑️ | checked at 375 px: sidebar drawer, stacked filters, horizontally scrolling tables |
| Collapsible sidebar, top navbar, breadcrumbs, profile menu | ☑️ | `base.html`; breadcrumbs on every inner page |
| Landing page, login page, role-specific dashboards | ✅ | `test_pages.py`, `test_dashboards.py` |
| Light/dark mode | ☑️ | toggle persists; contrast fixes for light theme |
| Global search, notification dropdown, toasts | ✅ | search → ticket list (`test_tickets`); notifications (`test_workflow::test_notifications_mark_read`) |
| Interactive charts, filters, sorting, pagination | ✅ | `test_tickets::test_list_filters_search_and_sort`, `test_pagination` |
| Modals and confirmation dialogs | ☑️ | resolve/reopen modal, global `data-confirm` dialog (deactivate user, delete file, status moves) |
| Loading skeletons, form validation, empty states, useful errors | ☑️ | chart skeletons; server-side + HTML validation; empty states on all lists; unified error page (400/403/404/405/413/429/500) |
| Accessible controls, keyboard navigation | ⚠️ | skip link, labels, `aria-*`, visible focus, AA button contrast, Escape closes drawer. **Not** audited with a screen reader or automated a11y tool |
| Every button/menu/link works; no fake statistics; no dead links | ✅ | crawl per role (`test_pages.py`); every metric from SQL (`test_dashboards.py`); demo-credential panel and lab "Completed" badges removed from production views |

## 3. Roles & core functionality
| Requirement | Status | Evidence |
| :--- | :-: | :--- |
| Employee: dashboard, create tickets, upload files, view own tickets/status/comments, track progress | ✅ | `test_tickets`, `test_dashboards`, `test_attachments` |
| Technician: assigned tickets, status & priority updates, public comments, internal notes, troubleshooting/resolution, workload, overdue | ✅ | `test_workflow`, `test_internal_notes`, `test_dashboards::test_technician_dashboard_metrics` |
| Admin: users, roles, categories, assignments, all tickets, analytics, priorities & SLA targets, audit logs, operational metrics | ✅ | `test_rbac`, `test_sla::test_admin_updates_sla_policy_and_recalculates_active`, `test_dashboards` |
| Secure login/logout, account status, session expiration, CSRF, login rate limiting, hashing | ✅ | `test_auth.py`, `test_security.py` |
| Backend RBAC; no privilege escalation; employees never see others' tickets or internal notes | ✅ | `test_rbac.py`, `test_internal_notes.py` |

## 4. Ticket management
| Requirement | Status | Evidence |
| :--- | :-: | :--- |
| Unique reference `INC-2026-00001` | ✅ | `test_tickets::test_reference_numbers_are_sequential_and_unique` |
| Title, description, category, priority (Low–Critical), creator, technician, status, timestamps, affected system, department, attachments, resolution summary | ✅ | model + `test_tickets::test_create_ticket_persists_with_reference_sla_history_and_notifications` |
| Create, list, detail, assign, comment, filter, update, resolve | ✅ | `test_tickets`, `test_workflow` |
| Workflow Open → Assigned → In Progress → Resolved → Closed, validated on backend | ✅ | `test_workflow::test_full_lifecycle_open_to_closed`, `test_invalid_transition_is_rejected` |
| Authorized reopening | ✅ | `test_employee_can_reopen_resolved_ticket_and_sla_restarts`, `test_closed_ticket_reopen_window` |
| Search; status/priority/category/technician/date filters; sorting; pagination | ✅ | `test_list_filters_search_and_sort`, `test_pagination`, `test_overdue_filter` |
| Activity history | ✅ | status history + attachments + comments timeline on ticket page |
| Delete tickets | — | intentionally not offered (cancel = close) to preserve the audit trail |

## 5. Dashboards
| Requirement | Status | Evidence |
| :--- | :-: | :--- |
| Employee: totals, status counts, recent tickets, activity | ✅ | `test_employee_dashboard_counts_only_own_tickets` |
| Technician: assigned, critical, overdue, workload, resolution activity | ✅ | `test_technician_dashboard_metrics` |
| Admin: users, incidents, open/resolved, priority/category charts, trends, workload, overdue, audit events | ✅ | `test_admin_dashboard_matches_database`, `test_daily_trend_buckets_by_day` |
| All metrics from DB; meaningful empty states | ✅ | `test_employee_dashboard_empty_state`; compliance shows "—" when nothing is evaluated |

## 6. SLA & notifications
| Requirement | Status | Evidence |
| :--- | :-: | :--- |
| Configurable response/resolution targets per priority | ✅ | `test_sla.py` |
| Overdue indicators, time remaining, resolution duration, UTC | ✅ | `test_overdue_and_time_remaining`, `test_resolved_ticket_is_never_overdue_and_duration_is_recorded` |
| DB-backed notifications (assignment, comments, status), unread count, mark read | ✅ | `test_workflow::test_admin_assignment_notifies_and_audits`, `test_notifications_mark_read` |

## 7. Database
| Requirement | Status | Evidence |
| :--- | :-: | :--- |
| Tables users, tickets, ticket_categories, comments, attachments, ticket_status_history, audit_logs, notifications, sla_policies | ✅ | `app/models.py` (+ `login_attempts`) |
| FKs, indexes, constraints, migrations | ✅ | CHECK constraints enforced by MySQL (error 3819); `flask db check` clean |
| ORM, transactions, safe queries | ✅ | single commit per action; `test_security::test_sql_injection_attempts_are_inert` |
| Data persists (no in-memory/localStorage primary store) | ✅ | `test_ticket_data_persists_across_app_restart`; localStorage only for theme/sidebar preference |
| Explicit seed command; never auto-seed admin in production | ✅ | `flask seed-db` refused in production (`test_seed_command_refused_in_production`); `flask create-admin` prompts for password |

## 8. Amazon EFS / storage
| Requirement | Status | Evidence |
| :--- | :-: | :--- |
| Storage abstraction: local dir (dev) / EFS mount (prod) | ✅ | `services/storage.py`; EFS mount guard `test_efs_backend_refuses_when_not_mounted` |
| Files on storage, metadata + associations in DB | ✅ | live check: row + file + SHA-256 match |
| Authenticated upload, authorized download | ✅ | `test_authorized_downloads`, `test_upload_denied_on_foreign_ticket` |
| Safe names, type & size validation, traversal prevention, safe headers, error handling | ✅ | `test_attachments.py` (17 tests) |
| EFS docs: creation, mount targets, SGs, POSIX permissions, persistence, encryption; never public | ☑️ | `docs/aws_deployment.md §2.2`, `efs_mount_setup.sh`, `efs_file_system_policy.json` |
| Two EC2 instances share attachments | 🟡 | procedure in §2.3; `/health` reports instance; `flask storage-check` per instance |

## 9. AWS security
| Requirement | Status | Evidence |
| :--- | :-: | :--- |
| IAM role, no keys in code, least privilege | ☑️ | live evidence: `security_checklist.md` W1–W2 |
| Secrets Manager (with documented fallback) | ☑️ live / ✅ code | `services/secrets.py`; fallback documented (`security_checklist.md`) |
| HTTPS/TLS, encrypted RDS & EFS, DB TLS | ☑️ (W4–W8) | `nginx_https.conf`, `tls_self_signed.sh`, `DB_SSL_CA`, `REQUIRE SSL` |
| Private RDS/EFS, SG-restricted MySQL/NFS, restricted SSH | ☑️ (W9–W11) | `docs/architecture.md §2` |
| App security: CSRF, validation, safe output, secure sessions, SQLi protection, rate limiting, server-side authZ | ✅ | `docs/security_checklist.md` A1–A27 |
| Audit logs without secrets | ✅ | `test_audit_scrubs_credentials` and audit assertions |

## 10. Code organization & deployment docs
| Requirement | Status | Evidence |
| :--- | :-: | :--- |
| Structure (factory, blueprints, services, templates, static, migrations, tests, scripts, infrastructure/aws, docs, config, requirements, .env.example, .gitignore, docker-compose, run.py, wsgi.py, README) | ✅ | repository tree |
| Exact local install/run/migrate/seed/test commands | ✅ | README §3–§7 (Windows commands executed on this machine) |
| EC2 guide, systemd, Nginx, RDS, EFS, IAM, Secrets Manager, HTTPS, SGs, backup/recovery/cleanup/cost | ☑️ followed on AWS | `docs/aws_deployment.md` |
| No secrets committed | ✅ | `.env` ignored; staged diff reviewed before every commit |

## 11. Deliverables
| Deliverable | Status | Location |
| :--- | :-: | :--- |
| Working frontend + backend | ✅ | `app/` |
| Models + migrations | ✅ | `app/models.py`, `migrations/` |
| Local dev configuration | ✅ | `.env.example`, `scripts/setup_local_mysql.ps1` |
| EFS storage integration | ✅ code / ☑️ AWS | `services/storage.py` |
| AWS deployment config/scripts | ☑️ | `infrastructure/aws/` (fast path: `cloudshell_lab2_lab3.sh` + `server_lab2_lab3.sh`) |
| Automated tests | ✅ | `tests/` (145) |
| README | ✅ | `README.md` |
| AWS architecture diagram | ✅ | `docs/architecture.md` |
| ER diagram | ✅ | `docs/database_er.md` |
| Request/data-flow diagram | ✅ | `docs/data_flow.md` |
| Security verification checklist | ✅ | `docs/security_checklist.md` |
| Lab 1/2/3 demonstration checklists | ✅ | `docs/lab_guides.md` |

## 12. Additional features (added 2026-10-24, beyond the original brief)
| Feature | Status | Evidence / note |
| :--- | :-: | :--- |
| Auto-assignment of new tickets (least busy available technician) | ✅ | `services/assignment.py`; `test_new_ticket_goes_to_least_busy_technician` |
| Every technician free → ticket waits in the queue to be claimed | ✅ | `test_when_every_technician_is_free_the_ticket_waits_to_be_claimed` |
| Unclaimed tickets auto-assigned after a per-priority wait (on page loads and `flask auto-assign`) | ✅ | `test_unclaimed_tickets_are_assigned_after_the_wait_time`, `test_sweep_runs_during_normal_page_loads` |
| Weighted workload points, specialists first (technician skills), random only on ties | ✅ | `test_workload_points_weight_critical_work`, `test_specialists_come_first` |
| Maximum open tickets per technician (default 10, admin sets 1–50) | ✅ | `test_maximum_open_tickets_per_technician`, `test_settings_page_limits_max_open_between_1_and_50` |
| Technician Available/Away with note and "back on" date; automatic return; admin warning for away technicians with open tickets | ✅ | `test_away_technicians_never_get_tickets`, `test_away_period_ends_automatically`, `test_technician_asks_for_leave_and_an_admin_approves_it` |
| Leave requests: a technician asks, only an admin's approval makes them Away; reject / cancel; admins notified; audit trail | ✅ | `test_technician_asks_for_leave_and_an_admin_approves_it`, `test_leave_request_rules` (migration `d4b2e8f13a57`, checked in the browser 2026-10-25) |
| Runs on its own: no admin action needed (settings page optional; `flask auto-assign --now` for operators) | ✅ | `test_no_admin_action_is_needed_to_assign_the_queue` |
| Every available technician notified about each new ticket, with the number waiting in the queue; admins alerted only when nobody can take a ticket | ✅ | `test_when_every_technician_is_free_the_ticket_waits_to_be_claimed`, `test_away_technicians_are_not_notified_about_new_tickets`, `test_maximum_open_tickets_per_technician` |
| Reason shown in ticket history ("System (auto-assign)") and audit trail | ✅ | asserted in the tests above |
| Safe with several workers/instances (conditional UPDATE) | ✅ | `test_assignment_is_applied_only_once` |
| Customer satisfaction rating 1–5 stars by the reporter, once, after close; analytics average | ✅ | `test_reporter_rates_a_closed_ticket_once`, `test_rating_rules`, `test_satisfaction_metrics` |
