# CloudOps 360 — context for Claude

Student AWS Cloud Computing Lab project (Flask + MySQL + Bootstrap/Chart.js, three roles, ticket workflow, SLA, audit log). The owner (Gabriel) is a student who prefers short, step-by-step instructions in simple English, one step at a time, waiting for a screenshot before the next step.

## Where things are
- `README.md` — overview and exact local commands.
- `docs/REQUIREMENTS_CHECKLIST.md` — requirement-by-requirement status (what is done, verified, or pending AWS).
- `docs/CHEAT_SHEET.md` — demo-day steps, accounts, update workflow (keep in sync if workflows change).
- `docs/CloudOps360_Demo_Script.docx`, `docs/CloudOps360_User_and_Demo_Guide.docx` — the class demo script (DO/SAY steps) and full guide.
- `docs/aws_deployment.md` — Lab 1/2/3 AWS guide; `infrastructure/aws/` — all deployment scripts.
- `demo_files/` — screenshot + log (accepted uploads) and `fake.png` (rejected on purpose).

## State of the project (as of 2026-10-24)
- App complete; 144 pytest tests pass locally on SQLite and MySQL 8.0 (`.venv\Scripts\python -m pytest -q`).
- Added 2026-10-24: auto-assignment (ON by default; least busy available technician, specialists first, weighted points, max open per technician default 10 / admin 1–50, queue + claim when every technician is free, per-priority wait then auto-assign on its own — no admin button, by request; technicians notified of every new ticket with queue count; admins alerted only when nobody can take a ticket), technician Available/Away status, technician skills, CSAT star ratings. Migration `c3f1a9d27e64`; 12 tables.
- Local dev: Windows, MySQL80 service, `.env` created by `scripts/setup_local_mysql.ps1` (gitignored), run with `.venv\Scripts\python run.py`.
- GitHub: https://github.com/Gabriel2006galaxy/CloudOps-360 (branch `main`). This machine has no credential helper: pushes go through `git push origin main` in a terminal where Gabriel types his username and a GitHub access token himself — never handle the token.
- **Lab 1 is done on AWS** and verified live: EC2 Amazon Linux 2023, t3.micro, Nginx + Gunicorn, MariaDB on the instance.
- **All 3 labs live since 2026-10-24 on Gabriel's OWN AWS account** (Free plan, $100 credits until 2027-04-24, Zero-spend budget alert; root sign-in with MFA; region **ap-south-1 Mumbai**). Instance `cloudops360-web` (i-0e4ad16a9a36176cb, https://13.201.137.27, self-signed cert) with IAM role `CloudOps360-EC2-Role`; RDS `cloudops360-db` (MySQL 8.4, private, encrypted, app user `cloudops_user` REQUIRE SSL); EFS `fs-0719497a0c861f620` (encrypted, TLS + role-only policy); secrets `cloudops360/prod/db`, `cloudops360/prod/app`, `cloudops360/admin/rds-master` (master password rotated after being shown on screen). Built with `cloudshell_lab2_lab3.sh` + `server_lab2_lab3.sh`; `verify_deployment.sh` all PASS. Don't stop the instance (public IP would change). Delete RDS/EFS/instance after the final demo.

## AWS facts learned the hard way
- The account is an **AWS Academy "Sandbox environment"** (course: AWS Academy Cloud Architecting). Each session gives a **brand-new, empty AWS account**; everything (instances, IPs) is deleted when the session ends. Session timer ~3 hours, $20 budget. Key pair `vockey` exists; **no LabInstanceProfile** (IAM roles can't be created/attached) — Lab 3 IAM/Secrets Manager may be blocked; check before planning.
- The Sandbox is now only a backup (Lab 1). Gabriel later created an own Free-plan account (no auto-pay; never upgrade to a paid plan).
- Deployment method: paste the 2-line **User data** at launch → `infrastructure/aws/user_data_demo.sh` installs everything from the latest GitHub `main` in ~2–10 minutes (bootstrap, MariaDB, schema, `seed-db` demo data in development mode, `SHOW_DEMO_ACCOUNTS=true`). Tested end-to-end on 2026-10-20.
- Update a running server: `sudo bash /opt/cloudops360/infrastructure/aws/deploy_update.sh main` (git runs as the `cloudops` user — root hits "dubious ownership").
- EC2 Instance Connect quirks: Ctrl+Shift+V pastes twice (use right-click → Paste); connections drop occasionally (reconnect); expired session → "voc-cancel-cred" errors / "You must first log out" page.
- The grey terminal on the Sandbox page is AWS Academy's helper machine, not the EC2 server.

## Conventions
- Production config fails closed; demo data and demo login buttons only via explicit opt-in (`seed-db` in development mode, `SHOW_DEMO_ACCOUNTS=true`).
- Keep `.env`, `*.db`, `uploads/`, `instance/` out of Git. Shell scripts must stay LF (`.gitattributes`).
- Commit messages end with the Co-Authored-By line; run tests before committing.

## Possible next work
- After the final demo: clean-up of the own account (RDS, EFS, instance, secrets, security groups, IAM role).
- Optional: two-instance EFS sharing demo (`docs/aws_deployment.md` §2.3), still 🟡 in the checklist.
- Feature ideas Gabriel liked and not built yet: SLA escalation, email alerts, two-step login (OTP).
