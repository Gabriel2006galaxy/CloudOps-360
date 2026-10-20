# CloudOps 360 — context for Claude

Student AWS Cloud Computing Lab project (Flask + MySQL + Bootstrap/Chart.js, three roles, ticket workflow, SLA, audit log). The owner (Gabriel) is a student who prefers short, step-by-step instructions in simple English, one step at a time, waiting for a screenshot before the next step.

## Where things are
- `README.md` — overview and exact local commands.
- `docs/REQUIREMENTS_CHECKLIST.md` — requirement-by-requirement status (what is done, verified, or pending AWS).
- `docs/CHEAT_SHEET.md` — demo-day steps, accounts, update workflow (keep in sync if workflows change).
- `docs/CloudOps360_Demo_Script.docx`, `docs/CloudOps360_User_and_Demo_Guide.docx` — the class demo script (DO/SAY steps) and full guide.
- `docs/aws_deployment.md` — Lab 1/2/3 AWS guide; `infrastructure/aws/` — all deployment scripts.
- `demo_files/` — screenshot + log (accepted uploads) and `fake.png` (rejected on purpose).

## State of the project (as of 2026-10-20)
- App complete; full pytest suite passes locally on SQLite and MySQL 8.0 (`.venv\Scripts\python -m pytest -q`).
- Local dev: Windows, MySQL80 service, `.env` created by `scripts/setup_local_mysql.ps1` (gitignored), run with `.venv\Scripts\python run.py`.
- GitHub: https://github.com/Gabriel2006galaxy/CloudOps-360 (branch `main`). This machine has no credential helper: pushes go through `git push origin main` in a terminal where Gabriel types his username and a GitHub access token himself — never handle the token.
- **Lab 1 is done on AWS** and verified live: EC2 Amazon Linux 2023, t3.micro, Nginx + Gunicorn, MariaDB on the instance.

## AWS facts learned the hard way
- The account is an **AWS Academy "Sandbox environment"** (course: AWS Academy Cloud Architecting). Each session gives a **brand-new, empty AWS account**; everything (instances, IPs) is deleted when the session ends. Session timer ~3 hours, $20 budget. Key pair `vockey` exists; **no LabInstanceProfile** (IAM roles can't be created/attached) — Lab 3 IAM/Secrets Manager may be blocked; check before planning.
- Gabriel decided **not** to use a personal AWS account (no card/spending).
- Deployment method: paste the 2-line **User data** at launch → `infrastructure/aws/user_data_demo.sh` installs everything from the latest GitHub `main` in ~2–10 minutes (bootstrap, MariaDB, schema, `seed-db` demo data in development mode, `SHOW_DEMO_ACCOUNTS=true`). Tested end-to-end on 2026-10-20.
- Update a running server: `sudo bash /opt/cloudops360/infrastructure/aws/deploy_update.sh main` (git runs as the `cloudops` user — root hits "dubious ownership").
- EC2 Instance Connect quirks: Ctrl+Shift+V pastes twice (use right-click → Paste); connections drop occasionally (reconnect); expired session → "voc-cancel-cred" errors / "You must first log out" page.
- The grey terminal on the Sandbox page is AWS Academy's helper machine, not the EC2 server.

## Conventions
- Production config fails closed; demo data and demo login buttons only via explicit opt-in (`seed-db` in development mode, `SHOW_DEMO_ACCOUNTS=true`).
- Keep `.env`, `*.db`, `uploads/`, `instance/` out of Git. Shell scripts must stay LF (`.gitattributes`).
- Commit messages end with the Co-Authored-By line; run tests before committing.

## Possible next work
- Lab 2: RDS + EFS (`docs/aws_deployment.md` §2) — in the Sandbox these are deleted each session too; consider a CloudFormation template if allowed.
- Lab 3: HTTPS (`tls_self_signed.sh`, `nginx_https.conf`), encryption, audit demos; IAM/Secrets Manager depend on Sandbox permissions.
- Feature ideas Gabriel liked: star rating (CSAT), auto-assignment, SLA escalation, email alerts.
