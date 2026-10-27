# CloudOps 360 — Cheat Sheet (everything to copy-paste)

## 0. FINAL DEMO: the site is always on (own AWS account, all 3 labs)
- Open **https://13.201.137.27** → "not private" warning → **Advanced → Proceed** (self-signed
  certificate, still encrypted). Demo buttons work as before. Don't stop the instance (the IP would change).
- AWS console: sign in as **root user** (your email + password + Microsoft Authenticator code) →
  region **Asia Pacific (Mumbai)**.
- **About 30 minutes before presenting: reset the demo data** (fresh ticket times, practice data
  removed, ticket numbers from INC-2026-00001 again). EC2 → cloudops360-web → **Connect → EC2
  Instance Connect** → paste (right-click → Paste):
```bash
sudo bash /opt/cloudops360/infrastructure/aws/reset_demo_data.sh
```
  It ends with "[reset] Done". Only INC-2026-00005 is overdue (on purpose); the rest stay on time for
  at least 2 hours. Laptop backup: `.venv\Scripts\flask reset-demo`.
- What to show for each lab:

| Lab | Console page | Point at |
| :-- | :-- | :-- |
| 1 | **EC2 → Instances → cloudops360-web** | Running, t3.micro, Amazon Linux 2023, public IP |
| 2 | **RDS → Databases → cloudops360-db** | MySQL 8.4, **Publicly accessible: No**, **Encryption: Enabled**, security group cloudops360-db |
| 2 | **EFS → cloudops360-attachments** | **Encrypted**, mount targets; upload a file in the app → it is stored on EFS |
| 3 | **EC2 instance → Security tab** | **IAM role: CloudOps360-EC2-Role** (no access keys) |
| 3 | **Secrets Manager** | `cloudops360/prod/db`, `cloudops360/prod/app` (the app reads them via the role) |
| 3 | **Browser 🔒** | https, http → https redirect |
| 2+3 | **Proof report** (server terminal, see below) | every line **PASS** |

Proof report: EC2 → cloudops360-web → **Connect → EC2 Instance Connect** → paste:
```bash
sudo bash /opt/cloudops360/infrastructure/aws/verify_deployment.sh | grep -E "^(PASS|FAIL)"
```
Update the live server after pushing code:
```bash
sudo bash /opt/cloudops360/infrastructure/aws/deploy_update.sh main
```
Cost: about $1/day from the free credits ($100, Free plan, budget alert at $0.01). After the final
demo, delete RDS, EFS and the instance (or ask Claude for the clean-up steps).

## 1. Backup: AWS Academy Sandbox (only Lab 1; start ~20 minutes before)
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
- **Leave (Away):** Marcus (`tech_marcus` / `TechPass123!`) → **Queue & Workload** → reason "Sick leave",
  back-on date → **Send leave request** (he stays Available). Admin → dashboard shows **Leave request**
  → **Approve** → Marcus is **Away**: yellow warning with his open tickets, Away badge on **Users &
  Roles**, new tickets go to Sarah only. Undo: Marcus → **I'm back**.
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
   - **Own account (cloudops360-web is always on):** Connect → run:
```bash
sudo bash /opt/cloudops360/infrastructure/aws/deploy_update.sh main
```
   - **Sandbox (backup):** launch with the User data lines — it installs the newest code automatically.

## 5. Remember
- Own account: Free plan only, never upgrade; the budget e-mail warns you if anything costs money.
- The AWS Academy **Sandbox deletes the server when the session ends** — just relaunch with User data.
- **End Lab** = safe. **Reset** = deletes everything — never click.
- In the browser terminal, paste with **right-click → Paste** (Ctrl + Shift + V pastes twice).
- Connection fails → check the timer, wait 1 minute, reconnect.
- Production mode never loads demo data by itself; the User data script loads it on purpose for the demo.

## 6. Starting a new chat
Open the chat in the `CloudOps-360` folder and say:
> Read README.md, docs/REQUIREMENTS_CHECKLIST.md and docs/CHEAT_SHEET.md. All 3 labs run on my own AWS account (Mumbai, https://13.201.137.27). Next I want to … (add a feature / clean up AWS after the demo).

## 7. Next steps (not done yet)
- After the final demo: delete RDS, EFS, the instance and the secrets (ask Claude for the clean-up steps).
- Optional: two servers sharing the EFS files (`docs/aws_deployment.md` §2.3).
- Optional features: SLA escalation, email alerts, two-step login (OTP).
