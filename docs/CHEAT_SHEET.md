# CloudOps 360 — Cheat Sheet (everything to copy-paste)

## 1. Demo day: put the site on AWS (start ~20 minutes before)
1. AWS Academy → course → **Modules** → **Sandbox environment** → **Start Lab** → wait for green dot → click **AWS**.
   - If it says "You must first log out" → click **here** → click **AWS** again.
2. Region **N. Virginia** → **EC2** → **Launch instance**:
   - Name `cloudops360-web` · **Amazon Linux 2023** · **t3.micro** · key pair **vockey**
   - Tick: SSH (Anywhere), HTTPS, HTTP
   - **Advanced details → User data** (last box) — paste exactly, do not edit:

```bash
#!/bin/bash
curl -fsSL https://raw.githubusercontent.com/Gabriel2006galaxy/CloudOps-360/main/infrastructure/aws/user_data_demo.sh | bash
```

3. **Launch** → **View all instances** → copy the **Public IPv4**.
4. Wait **about 10 minutes** → open `http://<IP>` (http, not https).
5. Check the lab **timer** has enough time left for the demo.

## 2. Demo accounts (one-click buttons on the Sign In page)
| Role | Username | Password |
| --- | --- | --- |
| Admin | `admin` | `AdminPass123!` |
| Technician | `tech_sarah` | `TechPass123!` |
| Employee | `emp_jordan` | `EmpPass123!` |
| Employee 2 | `emp_elena` | `EmpPass123!` |

- Demo Step 3 (access denied) — new tab (**Ctrl + T**), paste:
  - `http://<IP>/tickets/INC-2026-00002` → 403
  - `http://<IP>/admin/users` → 403
- Demo files: `demo_files/` (screenshot, log, fake.png)
- Full demo script: `docs/CloudOps360_Demo_Script.docx`
- Full guide: `docs/CloudOps360_User_and_Demo_Guide.docx`

## 2b. New features to show (auto-assign, Away status, star rating)
- **Auto-assign (ON by default):** Jordan reports a ticket (category *End-User Computing*) → it is
  assigned straight away to **Sarah** (specialist, lightest workload). Open the ticket → **Activity
  history** shows "System (auto-assign)" and the reason. *Sarah does not need to Claim it any more.*
- **Notifications:** Sarah and Marcus get a notification for every new ticket (when it waits in the
  queue it also says how many tickets are waiting). The admin is only alerted ("Needs assignment") when
  nobody can take a ticket — no daily work for the admin.
- **Queue:** admin → **Auto-Assignment** shows the 2 sample tickets still waiting and "auto after 4 h /
  12 h" — the system assigns them on its own (technicians can claim them earlier).
- **Away:** Marcus → **Queue & Workload** → My status **Away**, note "Sick leave" → admin dashboard
  shows a warning; new tickets go to Sarah only.
- **Settings:** admin → **Auto-Assignment** → ON/OFF, max open tickets per technician (1–50, default
  10), wait times; skills are set on **Users & Roles → edit technician**.
- **Star rating:** after Jordan presses **Confirm & Close**, the ticket shows **"How was the support?"**
  → pick stars + comment → Sarah gets a notification; admin **Analytics** shows the average.
- **Claim still exists:** when every technician is free, new tickets wait in the queue and anyone can
  claim them (auto-assigned after Critical 30 min / High 2 h / Medium 4 h / Low 12 h).

## 3. Run on the laptop (practice / backup)
```bash
cd C:\Users\Gabriel\OneDrive\Desktop\CloudOps-360
.venv\Scripts\python run.py
```
Open `http://127.0.0.1:5000`. If MySQL is not running: `Start-Service MySQL80` (PowerShell as Administrator).

Tests (expect all passed):
```bash
.venv\Scripts\python -m pytest -q
```

## 4. Workflow when you change code
1. Change code on the laptop, test with `run.py`.
2. Push:
```bash
git add -A
git commit -m "describe your change"
git push origin main
```
   Username `Gabriel2006galaxy`, password = your **GitHub access token**.
3. AWS:
   - **New session / demo day:** launch with the User data lines — it installs the newest code automatically.
   - **Server already running:** Connect → run:
```bash
sudo bash /opt/cloudops360/infrastructure/aws/deploy_update.sh main
```

## 5. Remember
- The AWS Academy **Sandbox deletes the server when the session ends** — just relaunch with User data.
- **End Lab** = safe. **Reset** = deletes everything — never click.
- In the browser terminal, paste with **right-click → Paste** (Ctrl + Shift + V pastes twice).
- Connection fails → check the timer, wait 1 minute, reconnect.
- Production mode never loads demo data by itself; the User data script loads it on purpose for the demo.

## 6. Starting a new chat
Open the chat in the `CloudOps-360` folder and say:
> Read README.md, docs/REQUIREMENTS_CHECKLIST.md, docs/CHEAT_SHEET.md and infrastructure/aws/user_data_demo.sh. The site is deployed on the AWS Academy Sandbox using the User data script. Next I want to … (add a feature / do Lab 2 RDS + EFS / Lab 3 security).

## 7. Next steps (not done yet)
- Lab 2: Amazon RDS (database) + Amazon EFS (files) — guide in `docs/aws_deployment.md` section 2.
- Lab 3: IAM role, Secrets Manager, HTTPS — section 3 (the Sandbox may block some of these; check first).
- Optional features: star rating (CSAT), auto-assignment, SLA escalation, email alerts.
