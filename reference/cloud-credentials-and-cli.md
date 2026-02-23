# Cloud Services - Credentials & CLI Reference

**Last Updated**: 2026-02-22
**Project**: LineCite Medical Records Extraction Platform
**Frontend Folder**: C:\Eventis\Website
---

## 🔑 API Keys & Credentials

### Render (Backend API)
- **API Key**: `rnd_U3qfZLxdrsa5yioqaLaoKGd4nImJ`
- **Service ID**: `srv-d6cv6dngi27c73893aog`
- **Service Name**: linecite-api
- **URL**: https://linecite-api.onrender.com
- **Dashboard**: https://dashboard.render.com/web/srv-d6cv6dngi27c73893aog


### Vercel (Frontend)
- **Project Name**: eventis-website
- **URL**: https://www.linecite.com
- **Repo**: https://github.com/Deputy1389/EventisWebsite
- **Branch**: master
- **Dashboard**: https://vercel.com/deputy1389s-projects/eventis-website

### Oracle Cloud (Worker)
- **Instance Name**: linecite-worker-micro
- **Public IP**: 192.9.156.165
- **Region**: San Jose (us-sanjose-1)
- **SSH Key**: `C:\Users\paddy\.ssh\oracle-worker`
- **SSH User**: ubuntu
- **Compute**: 2 OCPU + 12GB RAM (ARM Ampere A1)
- **Plan**: Always Free (permanent)

### Supabase (Database & Storage)
- **Project ID**: oqvemwshlhikhodlrjjk
- **Region**: US West 2
- **Host**: aws-0-us-west-2.pooler.supabase.com
- **Port**: 5432 (Session Pooler)
- **Database**: postgres
- **Username**: postgres.oqvemwshlhikhodlrjjk
- **Password**: WhatsAButtfor1!
- **Connection String**:
  ```
  postgresql://postgres.oqvemwshlhikhodlrjjk:WhatsAButtfor1!@aws-0-us-west-2.pooler.supabase.com:5432/postgres
  ```
- **REST URL (`SUPABASE_REST_URL`)**: `https://oqvemwshlhikhodlrjjk.supabase.co`
- **Service Role Key (`SUPABASE_SERVICE_KEY`)**: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9xdmVtd3NobGhpa2hvZGxyamprIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTc0NDU3NiwiZXhwIjoyMDg3MzIwNTc2fQ.NDhEx6xVP2XNttUDvrESiDgpz7VB-BBYccSxyEaLkkY`
- **Anon Key**: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9xdmVtd3NobGhpa2hvZGxyamprIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzE3NDQ1NzYsImV4cCI6MjA4NzMyMDU3Nn0.0RA3J2iEAGbQxuxtGvfaDLReGVygIRQaHVVvu4ljL1o`
- **Dashboard**: https://supabase.com/dashboard/project/oqvemwshlhikhodlrjjk

---

## 🖥️ CLI Commands

### Render CLI (via API)

#### List Services
```bash
curl -H "Authorization: Bearer rnd_U3qfZLxdrsa5yioqaLaoKGd4nImJ" \
  https://api.render.com/v1/services | python -m json.tool
```

#### Get Service Details
```bash
curl -H "Authorization: Bearer rnd_U3qfZLxdrsa5yioqaLaoKGd4nImJ" \
  https://api.render.com/v1/services/srv-d6cv6dngi27c73893aog | python -m json.tool
```

#### List Deployments
```bash
curl -H "Authorization: Bearer rnd_U3qfZLxdrsa5yioqaLaoKGd4nImJ" \
  https://api.render.com/v1/services/srv-d6cv6dngi27c73893aog/deploys?limit=5 | python -m json.tool
```

#### Get Environment Variables
```bash
curl -H "Authorization: Bearer rnd_U3qfZLxdrsa5yioqaLaoKGd4nImJ" \
  https://api.render.com/v1/services/srv-d6cv6dngi27c73893aog/env-vars | python -m json.tool
```

#### Update Environment Variable
```bash
curl -X PUT \
  -H "Authorization: Bearer rnd_U3qfZLxdrsa5yioqaLaoKGd4nImJ" \
  -H "Content-Type: application/json" \
  -d '{
    "envVars": [
      {
        "key": "VARIABLE_NAME",
        "value": "new_value"
      }
    ]
  }' \
  https://api.render.com/v1/services/srv-d6cv6dngi27c73893aog/env-vars
```

#### Trigger Manual Deploy
```bash
curl -X POST \
  -H "Authorization: Bearer rnd_U3qfZLxdrsa5yioqaLaoKGd4nImJ" \
  -H "Content-Type: application/json" \
  -d '{"clearCache": "do_not_clear"}' \
  https://api.render.com/v1/services/srv-d6cv6dngi27c73893aog/deploys
```

#### Check API Health
```bash
curl https://linecite-api.onrender.com/health | python -m json.tool
```

---

### Vercel CLI

#### Installation
```bash
npm install -g vercel
```

#### Login
```bash
vercel login
```

#### List Deployments
```bash
vercel ls
```

#### Deploy to Production
```bash
cd C:\Eventis\Website
vercel --prod
```

#### Check Deployment Status
```bash
vercel inspect [deployment-url]
```

#### View Logs
```bash
vercel logs [deployment-url]
```

#### List Environment Variables
```bash
vercel env ls
```

#### Pull Environment Variables
```bash
vercel env pull
```

---

### Oracle Cloud Worker (SSH)

#### SSH Connection
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165
```

#### Check Worker Service Status
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 \
  "sudo systemctl status linecite-worker --no-pager"
```

#### View Worker Logs (Live)
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 \
  "sudo journalctl -u linecite-worker -f"
```

#### View Last 50 Log Lines
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 \
  "sudo journalctl -u linecite-worker -n 50 --no-pager"
```

#### Restart Worker
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 \
  "sudo systemctl restart linecite-worker"
```

#### Stop Worker
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 \
  "sudo systemctl stop linecite-worker"
```

#### Start Worker
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 \
  "sudo systemctl start linecite-worker"
```

#### Update Code and Restart
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 \
  "cd ~/citeline && git pull origin main && sudo systemctl restart linecite-worker"
```

#### Check Disk Space
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 "df -h"
```

#### Check Memory Usage
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 "free -h"
```

#### List Artifacts for a Run
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 \
  "ls -lh /tmp/citeline_data/artifacts/[RUN_ID]/"
```

#### View Environment Variables
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 \
  "cat ~/citeline/.env"
```

---

### Supabase (Database)

#### Connect via psql (from Oracle worker)
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 \
  "psql 'postgresql://postgres.oqvemwshlhikhodlrjjk:WhatsAButtfor1!@aws-0-us-west-2.pooler.supabase.com:5432/postgres'"
```

#### Run SQL Query via Python (from Oracle worker)
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 "cd ~/citeline && python3 -c \"
from packages.db.database import get_session

with get_session() as session:
    result = session.execute('SELECT COUNT(*) FROM runs')
    print(f'Total runs: {result.scalar()}')
\""
```

#### List All Matters
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 "cd ~/citeline && python3 -c \"
from packages.db.database import get_session
from packages.db.models import Matter

with get_session() as session:
    matters = session.query(Matter).all()
    for m in matters:
        print(f'{m.id} | firm={m.firm_id[:8]}...')
\""
```

#### List Recent Runs
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 "cd ~/citeline && python3 -c \"
from packages.db.database import get_session
from packages.db.models import Run
from sqlalchemy import desc

with get_session() as session:
    runs = session.query(Run).order_by(desc(Run.created_at)).limit(10).all()
    for r in runs:
        print(f'{r.id[:8]}... | status={r.status} | created={r.created_at}')
\""
```

#### Create New Run (for testing)
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 "cd ~/citeline && python3 -c \"
from packages.db.database import get_session
from packages.db.models import Run
from datetime import datetime, timezone
import uuid
import json

matter_id = 'REPLACE_WITH_MATTER_ID'

config = {
    'max_pages': 500,
    'event_confidence_min_export': 40,
    'low_confidence_event_behavior': 'exclude_from_export',
}

with get_session() as session:
    new_run = Run(
        id=uuid.uuid4().hex,
        matter_id=matter_id,
        status='pending',
        config_json=json.dumps(config),
        created_at=datetime.now(timezone.utc)
    )
    session.add(new_run)
    session.commit()
    print(f'Created run: {new_run.id}')
\""
```

---

## 🚀 Common Operations

### Deploy Code Changes

#### 1. Frontend (Vercel - Auto-deploys on git push)
```bash
cd C:\Eventis\Website
git add .
git commit -m "Your commit message"
git push origin master
# Vercel auto-deploys from GitHub
```

#### 2. Backend API (Render - Auto-deploys on git push)
```bash
cd C:\Citeline
git add .
git commit -m "Your commit message"
git push origin main
# Render auto-deploys from GitHub
```

#### 3. Worker (Oracle - Manual deploy)
```bash
# Push to GitHub first
cd C:\Citeline
git add .
git commit -m "Your commit message"
git push origin main

# Then update Oracle worker
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 \
  "cd ~/citeline && git pull origin main && sudo systemctl restart linecite-worker"
```

---

### Check System Health

#### All Services Health Check
```bash
# Render API
curl -s https://linecite-api.onrender.com/health | python -m json.tool

# Vercel Frontend
curl -s -o /dev/null -w "%{http_code}" https://www.linecite.com

# Oracle Worker
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 \
  "sudo systemctl is-active linecite-worker"

# Supabase
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 "cd ~/citeline && python3 -c \"
from packages.db.database import get_session
try:
    with get_session() as session:
        session.execute('SELECT 1')
    print('✅ Database connected')
except Exception as e:
    print(f'❌ Database error: {e}')
\""
```

---

### Monitor Active Runs

#### Check for Pending/Running Runs
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 "cd ~/citeline && python3 -c \"
from packages.db.database import get_session
from packages.db.models import Run

with get_session() as session:
    pending = session.query(Run).filter_by(status='pending').count()
    running = session.query(Run).filter_by(status='running').count()
    print(f'Pending: {pending}, Running: {running}')
\""
```

#### Watch Worker Process Run
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 \
  "sudo journalctl -u linecite-worker -f | grep -E '(Claimed run|Pipeline completed|ERROR)'"
```

---

## 📝 Environment Variables

### Render API (via Dashboard)
- `DATABASE_URL`: Supabase connection string
- `ENABLE_API_WORKER`: `false` (worker disabled on Render)
- Add more as needed via dashboard or CLI

### Oracle Worker (`~/citeline/.env`)
```bash
DATABASE_URL=postgresql://postgres.oqvemwshlhikhodlrjjk:WhatsAButtfor1!@aws-0-us-west-2.pooler.supabase.com:5432/postgres
DATA_DIR=/tmp/citeline_data
PYTHONPATH=/home/ubuntu/citeline
DISABLE_OCR=false
OCR_MODE=full
OCR_DPI=200
OCR_WORKERS=2
OCR_TIMEOUT_SECONDS=30
OCR_TOTAL_TIMEOUT_SECONDS=600
MAX_RUN_RETRIES=3
RUN_TIMEOUT_SECONDS=1800
```

---

## 🔒 Security Notes

- ⚠️ **Keep this file private** - contains sensitive credentials
- SSH key location: `C:\Users\paddy\.ssh\oracle-worker`
- Never commit `.env` files or credentials to git
- Rotate API keys periodically
- Use environment variables for all secrets

---

## 📚 API Documentation

- **Render API Docs**: https://api-docs.render.com/
- **Vercel CLI Docs**: https://vercel.com/docs/cli
- **Supabase Docs**: https://supabase.com/docs
- **Oracle Cloud Docs**: https://docs.oracle.com/en-us/iaas/Content/home.htm

---

## 🆘 Troubleshooting Quick Reference

### Render API not responding
1. Check deployment status: `curl` deploy endpoint
2. Check logs in Render dashboard
3. Trigger manual redeploy if needed

### Oracle Worker not processing
1. Check service status: `systemctl status linecite-worker`
2. Check logs: `journalctl -u linecite-worker -n 50`
3. Restart service: `systemctl restart linecite-worker`
4. Verify database connection with Python script

### Frontend errors
1. Check Vercel deployment status
2. Check browser console for errors
3. Verify API is responding
4. Clear cache and hard refresh (Ctrl+Shift+R)

### Database connection issues
1. Verify Session Pooler connection string
2. Check Supabase dashboard for status
3. Test connection from Oracle worker
4. Ensure port 5432 (not 6543) is used

---

**Generated**: 2026-02-22
**Maintained by**: Claude Code
**Project**: LineCite
