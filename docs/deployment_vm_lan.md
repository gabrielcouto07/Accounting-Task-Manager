# VM + LAN Deployment Guide

This guide runs the FastAPI app on a local VM so other PCs on the same company network can use it.

## Recommended Layout

Keep code and data separate. This makes updates much safer because you can replace the application folder without moving the production database.

- Windows code: `C:\apps\gerenciado-contabil`
- Windows data: `C:\data\gerenciado-contabil\controle_contabil.db`
- Linux code: `/opt/gerenciado-contabil`
- Linux data: `/var/lib/gerenciado-contabil/controle_contabil.db`

## Prerequisites

- Windows or Linux VM reachable from the LAN.
- Python 3.11+ installed.
- Project copied to the VM.
- A strong session secret defined for the VM.

## Install

Windows:

```powershell
cd "C:\apps\gerenciado-contabil"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Linux:

```bash
cd /opt/gerenciado-contabil
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Pre-Deploy Check

Run this before shipping changes to the VM:

```powershell
python scripts\check_project.py
```

`verify_counts.py` is only for validating the original legacy migration. Do not use it as a normal update check after the team starts changing live data.

## First Data Load

If you already have a current app database, copy it to the VM data folder.

If you need to rebuild from the legacy export:

```powershell
python scripts\import_legacy_data.py --reset
```

If you want to validate that initial migration once:

```powershell
python scripts\verify_counts.py
```

## Run On The LAN

Use `0.0.0.0` so other PCs can connect, and point `DATABASE_URL` to the data path outside the code folder.

Windows:

```powershell
$env:DATABASE_URL = "sqlite:///C:/data/gerenciado-contabil/controle_contabil.db"
$env:SESSION_SECRET_KEY = "replace-with-a-long-random-secret"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Linux:

```bash
export DATABASE_URL="sqlite:////var/lib/gerenciado-contabil/controle_contabil.db"
export SESSION_SECRET_KEY="replace-with-a-long-random-secret"
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Other users open:

```text
http://VM_IP_ADDRESS:8000/login
```

Health check:

```text
http://VM_IP_ADDRESS:8000/health
```

Find the VM IP on Windows:

```powershell
ipconfig
```

## Firewall

Open inbound TCP port `8000` on the VM firewall.

Windows PowerShell as administrator:

```powershell
New-NetFirewallRule -DisplayName "Gerenciado Contabil FastAPI 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
```

## Keep Running After Reboot

### Windows Task Scheduler

Create a task that starts at boot and runs:

```powershell
C:\apps\gerenciado-contabil\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Add environment variables in the task or wrapper script:

```text
DATABASE_URL=sqlite:///C:/data/gerenciado-contabil/controle_contabil.db
SESSION_SECRET_KEY=replace-with-a-long-random-secret
```

Set "Start in" to:

```text
C:\apps\gerenciado-contabil
```

### Linux systemd

Create `/etc/systemd/system/gerenciado-contabil.service`:

```ini
[Unit]
Description=Gerenciado Contabil FastAPI
After=network.target

[Service]
WorkingDirectory=/opt/gerenciado-contabil
Environment=DATABASE_URL=sqlite:////var/lib/gerenciado-contabil/controle_contabil.db
Environment=SESSION_SECRET_KEY=replace-with-a-long-random-secret
ExecStart=/opt/gerenciado-contabil/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable gerenciado-contabil
sudo systemctl start gerenciado-contabil
sudo systemctl status gerenciado-contabil
```

## Backups

Before updates, back up the active app database:

```powershell
$env:DATABASE_URL = "sqlite:///C:/data/gerenciado-contabil/controle_contabil.db"
python scripts\backup_app_db.py
```

Back up legacy SQLite files only if you still need the original source:

```powershell
python scripts\backup_legacy_sqlite.py
```

## Safe Update Flow

1. Run `python scripts\check_project.py` on the development copy.
2. Stop the VM service.
3. Back up the live database with `python scripts\backup_app_db.py`.
4. Apply code changes on the VM or deploy a fresh copy of the code folder.
5. Run `pip install -r requirements.txt`.
6. Start the service again.
7. Test `http://VM_IP_ADDRESS:8000/health`.
8. Test `http://VM_IP_ADDRESS:8000/login`.

## When SQLite Stops Being Enough

SQLite is fine for a small internal team on a LAN, especially with the current WAL mode and timeout settings. If usage grows, reports get heavier, or many people start editing at the same time, move to PostgreSQL by setting `DATABASE_URL` to the new server instead of changing app code first.
