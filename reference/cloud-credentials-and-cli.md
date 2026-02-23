# Cloud Services - Credentials & CLI Reference

**Last Updated**: 2026-02-23
**Project**: LineCite Medical Records Extraction Platform
**Frontend Folder**: C:\Eventis\Website

---

## 🎯 Recent Critical Fixes (2026-02-23)

### ✅ Fixed: Supabase Storage Integration
- **Commit**: 2dafecf
- **Issue**: `USE_SUPABASE_STORAGE` was False even with env vars set
- **Root Cause**: `load_dotenv()` never called in `storage.py`
- **Fix**: Added `load_dotenv()` before reading env vars
- **Impact**: Worker now uploads artifacts to Supabase, API can download them

### ✅ Fixed: Artifact Database Persistence
- **Commit**: 8225de5
- **Issue**: Artifacts generated but not saved to database
- **Root Cause**: Indentation bug - writes outside session context
- **Fix**: Indented all database writes inside session
- **Impact**: Artifact records now properly persist, API can serve them

### ✅ Fixed: Missing Render Environment Variables
- **Issue**: Render API crashing with SQLite errors, 500 responses
- **Root Cause**: Missing DATABASE_URL, SUPABASE_REST_URL, SUPABASE_SERVICE_KEY, API_INTERNAL_JWT_SECRET
- **Fix**: Set all 4 critical env vars via Render API
- **Impact**: API now connects to PostgreSQL and Supabase Storage

### ✅ System Status: FULLY OPERATIONAL
- Oracle Worker: Processing runs, uploading to Supabase ✅
- Render API: Deployed, database connected, storage configured ✅
- Supabase: Database + Storage buckets (documents, artifacts) ✅
- Frontend: Ready to test at www.linecite.com ✅

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

### Render API - Required Environment Variables

**CRITICAL**: These must ALL be set on Render for the API to work properly.

Set via Render Dashboard or API:

```bash
# Database Connection (REQUIRED)
DATABASE_URL=postgresql://postgres.oqvemwshlhikhodlrjjk:WhatsAButtfor1!@aws-0-us-west-2.pooler.supabase.com:5432/postgres

# Supabase Storage for Artifacts/Documents (REQUIRED)
SUPABASE_REST_URL=https://oqvemwshlhikhodlrjjk.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9xdmVtd3NobGhpa2hvZGxyamprIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTc0NDU3NiwiZXhwIjoyMDg3MzIwNTc2fQ.NDhEx6xVP2XNttUDvrESiDgpz7VB-BBYccSxyEaLkkY

# Internal API Authentication (REQUIRED)
API_INTERNAL_JWT_SECRET=2gjpNSViS55WhpyXfjrAwiN2zLmYXG360oRBHNHlABc=

# Worker Configuration (REQUIRED)
ENABLE_API_WORKER=false
```

**Optional Render Variables**:
```bash
# CORS (comma-separated)
CORS_ALLOW_ORIGINS=https://www.linecite.com,http://localhost:3000

# Security
HIPAA_ENFORCEMENT=false
RATE_LIMIT_ENABLED=true
RATE_LIMIT_RPM=180

# Storage
DATA_DIR=/tmp/citeline_data
```

#### Update Render Env Vars via API

**Set ALL required vars at once** (recommended to prevent missing vars):

```bash
curl -X PUT \
  -H "Authorization: Bearer rnd_U3qfZLxdrsa5yioqaLaoKGd4nImJ" \
  -H "Content-Type: application/json" \
  -d '[
    {
      "key": "DATABASE_URL",
      "value": "postgresql://postgres.oqvemwshlhikhodlrjjk:WhatsAButtfor1!@aws-0-us-west-2.pooler.supabase.com:5432/postgres"
    },
    {
      "key": "SUPABASE_REST_URL",
      "value": "https://oqvemwshlhikhodlrjjk.supabase.co"
    },
    {
      "key": "SUPABASE_SERVICE_KEY",
      "value": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9xdmVtd3NobGhpa2hvZGxyamprIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTc0NDU3NiwiZXhwIjoyMDg3MzIwNTc2fQ.NDhEx6xVP2XNttUDvrESiDgpz7VB-BBYccSxyEaLkkY"
    },
    {
      "key": "API_INTERNAL_JWT_SECRET",
      "value": "2gjpNSViS55WhpyXfjrAwiN2zLmYXG360oRBHNHlABc="
    },
    {
      "key": "ENABLE_API_WORKER",
      "value": "false"
    }
  ]' \
  https://api.render.com/v1/services/srv-d6cv6dngi27c73893aog/env-vars
```

---

### Oracle Worker - Required Environment Variables (`~/citeline/.env`)

**CRITICAL**: All Supabase Storage variables must be set for artifacts to upload/download.

```bash
# Database Connection (REQUIRED)
DATABASE_URL=postgresql://postgres.oqvemwshlhikhodlrjjk:WhatsAButtfor1!@aws-0-us-west-2.pooler.supabase.com:5432/postgres

# Supabase Storage for Artifacts/Documents (REQUIRED)
SUPABASE_REST_URL=https://oqvemwshlhikhodlrjjk.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9xdmVtd3NobGhpa2hvZGxyamprIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTc0NDU3NiwiZXhwIjoyMDg3MzIwNTc2fQ.NDhEx6xVP2XNttUDvrESiDgpz7VB-BBYccSxyEaLkkY

# File Storage Configuration
DATA_DIR=/tmp/citeline_data
PYTHONPATH=/home/ubuntu/citeline

# OCR Settings
DISABLE_OCR=false
OCR_MODE=full
OCR_DPI=200
OCR_WORKERS=2
OCR_TIMEOUT_SECONDS=30
OCR_TOTAL_TIMEOUT_SECONDS=600

# Worker Configuration
MAX_RUN_RETRIES=3
RUN_TIMEOUT_SECONDS=1800
```

**Verify Oracle Worker has correct env vars**:
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 "cd ~/citeline && python3 -c 'from packages.shared.storage import USE_SUPABASE_STORAGE, SUPABASE_REST_URL; print(f\"USE_SUPABASE_STORAGE={USE_SUPABASE_STORAGE}\"); print(f\"SUPABASE_REST_URL={SUPABASE_REST_URL}\")'"
```
Expected output:
```
USE_SUPABASE_STORAGE=True
SUPABASE_REST_URL=https://oqvemwshlhikhodlrjjk.supabase.co
```

---

### Frontend (Vercel) - Environment Variables

Set via Vercel Dashboard:

```bash
# Next-Auth
NEXTAUTH_URL=https://www.linecite.com
NEXTAUTH_SECRET=[your-nextauth-secret]

# API Connection
NEXT_PUBLIC_API_URL=https://linecite-api.onrender.com

# Internal API Auth
API_INTERNAL_JWT_SECRET=2gjpNSViS55WhpyXfjrAwiN2zLmYXG360oRBHNHlABc=
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

### ⚠️ CRITICAL: Supabase Storage Not Working (USE_SUPABASE_STORAGE=False)

**Symptom**: Artifacts not uploading to Supabase, API returns 404 for artifacts

**Root Cause**: `load_dotenv()` not called before reading env vars in `storage.py`

**Fix Applied** (commit 2dafecf - 2026-02-23):
- Added `from dotenv import load_dotenv` to `packages/shared/storage.py`
- Called `load_dotenv()` before reading `SUPABASE_REST_URL` and `SUPABASE_SERVICE_KEY`

**Verify Fix**:
```bash
# On Oracle Worker
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 "cd ~/citeline && python3 -c 'from packages.shared.storage import USE_SUPABASE_STORAGE; print(USE_SUPABASE_STORAGE)'"

# Expected: True
# If False, check ~/citeline/.env has SUPABASE_REST_URL and SUPABASE_SERVICE_KEY set
```

**Prevention**: Always call `load_dotenv()` at the top of any module that reads environment variables at import time.

---

### ⚠️ CRITICAL: Artifacts Not Persisting to Database

**Symptom**: Run completes but no artifact records in database, API returns 404

**Root Cause**: Indentation bug in `apps/worker/pipeline_persistence.py` - database writes outside session context

**Fix Applied** (commit 8225de5):
- Indented all `for` loops inside `with get_session()` context manager
- All `session.add()` calls now properly inside session

**Verify Fix**:
```bash
# Check if artifacts exist in DB for a run
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 "cd ~/citeline && python3 -c \"
from packages.db.database import get_session
from packages.db.models import Artifact

run_id = '90af8d5f716b490fa60781dbc49aaba8'  # Replace with your run ID

with get_session() as session:
    count = session.query(Artifact).filter_by(run_id=run_id).count()
    print(f'Artifacts in DB: {count}')
\""
```

---

### ⚠️ Missing Render Environment Variables

**Symptom**: Render deployment succeeds but API crashes with SQLite errors or 500 errors

**Root Cause**: Missing required environment variables on Render

**Fix**: Ensure ALL 4 critical env vars are set:
1. `DATABASE_URL` - PostgreSQL connection string
2. `SUPABASE_REST_URL` - Supabase REST API URL
3. `SUPABASE_SERVICE_KEY` - Supabase service role key
4. `API_INTERNAL_JWT_SECRET` - JWT signing secret

**Verify**:
```bash
curl -H "Authorization: Bearer rnd_U3qfZLxdrsa5yioqaLaoKGd4nImJ" \
  https://api.render.com/v1/services/srv-d6cv6dngi27c73893aog/env-vars | \
  python -m json.tool | grep -E '"key"' | grep -E 'DATABASE_URL|SUPABASE_REST_URL|SUPABASE_SERVICE_KEY|API_INTERNAL_JWT_SECRET'
```

**Fix via API** (see Environment Variables section above for full command)

---

### Render API not responding
1. Check deployment status:
   ```bash
   curl -H "Authorization: Bearer rnd_U3qfZLxdrsa5yioqaLaoKGd4nImJ" \
     https://api.render.com/v1/services/srv-d6cv6dngi27c73893aog/deploys?limit=1 | \
     python -m json.tool | grep '"status"'
   ```
2. Check health endpoint: `curl https://linecite-api.onrender.com/health`
3. Verify env vars are set (see above)
4. Check logs in Render dashboard
5. Trigger manual redeploy if needed

### Oracle Worker not processing
1. Check service status:
   ```bash
   ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 \
     "sudo systemctl status linecite-worker --no-pager"
   ```
2. Check logs:
   ```bash
   ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 \
     "sudo journalctl -u linecite-worker -n 50 --no-pager"
   ```
3. Verify Supabase Storage enabled:
   ```bash
   ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 \
     "cd ~/citeline && python3 -c 'from packages.shared.storage import USE_SUPABASE_STORAGE; print(USE_SUPABASE_STORAGE)'"
   ```
4. Check .env file has all required vars:
   ```bash
   ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 \
     "cat ~/citeline/.env | grep -E 'DATABASE_URL|SUPABASE_REST_URL|SUPABASE_SERVICE_KEY'"
   ```
5. Restart service: `sudo systemctl restart linecite-worker`
6. Verify database connection with Python script

### Frontend errors
1. Check Vercel deployment status
2. Check browser console for errors (F12)
3. Verify API is responding: `curl https://linecite-api.onrender.com/health`
4. Clear cache and hard refresh (Ctrl+Shift+R)
5. Log out and log back in to refresh session

### Database connection issues
1. Verify Session Pooler connection string (port 5432, not 6543)
2. Check Supabase dashboard for status
3. Test connection from Oracle worker:
   ```bash
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
4. Ensure DATABASE_URL uses Session Pooler: `aws-0-us-west-2.pooler.supabase.com:5432`

### Artifacts not downloading (404 errors)
1. Verify artifacts uploaded to Supabase Storage:
   - Check worker logs for "Successfully uploaded" messages
   - Check Supabase dashboard → Storage → artifacts bucket
2. Verify artifact records in database:
   ```bash
   ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 "cd ~/citeline && python3 -c \"
   from packages.db.database import get_session
   from packages.db.models import Artifact

   run_id = 'YOUR_RUN_ID'

   with get_session() as session:
       artifacts = session.query(Artifact).filter_by(run_id=run_id).all()
       print(f'Artifacts: {len(artifacts)}')
       for a in artifacts:
           print(f'  - {a.artifact_type}: {a.storage_uri}')
   \""
   ```
3. Verify Render API has Supabase env vars (see above)
4. Test direct download from Supabase:
   ```bash
   curl -H "apikey: [SUPABASE_SERVICE_KEY]" \
     -H "Authorization: Bearer [SUPABASE_SERVICE_KEY]" \
     "https://oqvemwshlhikhodlrjjk.supabase.co/storage/v1/object/artifacts/[RUN_ID]/evidence_graph.json" \
     -o test_download.json
   ```

### Low extraction quality (too few events exported)
1. Check confidence threshold in run config (default: 40)
2. Lower threshold if needed when creating run:
   ```python
   # In API request
   {"event_confidence_min_export": 30}  # Lower from 40 to 30
   ```
3. Check worker logs for warnings about low confidence
4. Review evidence_graph.json to see all extracted events (before filtering)

---

## 🔍 Debugging Commands

### Verify Supabase Storage Integration

#### Check if worker can access Supabase Storage
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 "cd ~/citeline && python3 -c '
from packages.shared.storage import USE_SUPABASE_STORAGE, SUPABASE_REST_URL, SUPABASE_SERVICE_KEY
print(f\"USE_SUPABASE_STORAGE: {USE_SUPABASE_STORAGE}\")
print(f\"SUPABASE_REST_URL: {SUPABASE_REST_URL}\")
print(f\"Has Service Key: {bool(SUPABASE_SERVICE_KEY)}\")
'"
```
**Expected Output**:
```
USE_SUPABASE_STORAGE: True
SUPABASE_REST_URL: https://oqvemwshlhikhodlrjjk.supabase.co
Has Service Key: True
```

#### Test artifact upload to Supabase
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 "cd ~/citeline && python3 -c '
from packages.shared.storage import _supabase_upload
import uuid

test_data = b\"Test artifact content\"
test_path = f\"test/{uuid.uuid4().hex}/test.txt\"
_supabase_upload(\"artifacts\", test_path, test_data, \"text/plain\")
print(f\"Test upload completed for: {test_path}\")
'"
```

#### Test artifact download from Supabase
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 "cd ~/citeline && python3 -c '
from packages.shared.storage import get_artifact_path
from pathlib import Path

# Replace with a known run ID that has artifacts
run_id = \"90af8d5f716b490fa60781dbc49aaba8\"
filename = \"evidence_graph.json\"

path = get_artifact_path(run_id, filename)
if path and Path(path).exists():
    size = Path(path).stat().st_size
    print(f\"✅ Successfully downloaded: {filename} ({size} bytes)\")
else:
    print(f\"❌ Failed to download: {filename}\")
'"
```

#### List artifacts in Supabase bucket
```bash
# Using Supabase REST API
curl -H "apikey: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9xdmVtd3NobGhpa2hvZGxyamprIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTc0NDU3NiwiZXhwIjoyMDg3MzIwNTc2fQ.NDhEx6xVP2XNttUDvrESiDgpz7VB-BBYccSxyEaLkkY" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9xdmVtd3NobGhpa2hvZGxyamprIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MTc0NDU3NiwiZXhwIjoyMDg3MzIwNTc2fQ.NDhEx6xVP2XNttUDvrESiDgpz7VB-BBYccSxyEaLkkY" \
  "https://oqvemwshlhikhodlrjjk.supabase.co/storage/v1/object/list/artifacts?limit=10" | \
  python -m json.tool
```

### Verify Database Persistence

#### Check artifact records for a run
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 "cd ~/citeline && python3 -c \"
from packages.db.database import get_session
from packages.db.models import Artifact

run_id = '90af8d5f716b490fa60781dbc49aaba8'  # Replace with your run ID

with get_session() as session:
    artifacts = session.query(Artifact).filter_by(run_id=run_id).all()
    print(f'Total artifacts: {len(artifacts)}')
    for a in artifacts:
        print(f'  {a.artifact_type}: {a.storage_uri}')
\""
```

#### Check recent successful runs
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165 "cd ~/citeline && python3 -c \"
from packages.db.database import get_session
from packages.db.models import Run
from sqlalchemy import desc

with get_session() as session:
    runs = session.query(Run).filter_by(status='success').order_by(desc(Run.finished_at)).limit(5).all()
    print('Recent successful runs:')
    for r in runs:
        print(f'  {r.id[:16]}... | finished={r.finished_at} | events={r.metrics_json}')
\""
```

### Test End-to-End Artifact Flow

#### Complete test: Upload → Process → Download
```bash
# On local machine
cd C:\Citeline
python test_e2e_full_flow.py
```

This test will:
1. Create a new matter
2. Upload a document (or use existing)
3. Trigger extraction
4. Wait for completion (max 5 minutes)
5. Download evidence_graph.json
6. Download chronology.pdf
7. Verify file sizes and content

---

## 📋 Checklist: Setting Up New Environment

Use this checklist when setting up a new worker or API instance:

### Oracle Worker Setup
- [ ] Clone repo: `git clone https://github.com/Deputy1389/CiteLine.git ~/citeline`
- [ ] Create `.env` file with ALL required vars (see Environment Variables section)
- [ ] Install dependencies: `pip3 install -e .`
- [ ] Verify Supabase Storage: `python3 -c 'from packages.shared.storage import USE_SUPABASE_STORAGE; print(USE_SUPABASE_STORAGE)'` → Must be True
- [ ] Verify database connection: Test with `get_session()`
- [ ] Set up systemd service (see setup docs)
- [ ] Start service: `sudo systemctl start linecite-worker`
- [ ] Check logs: `sudo journalctl -u linecite-worker -f`

### Render API Setup
- [ ] Connect GitHub repo to Render
- [ ] Set build command: `pip install -e .`
- [ ] Set start command: `uvicorn apps.api.main:app --host 0.0.0.0 --port $PORT`
- [ ] Add ALL 4 required env vars (DATABASE_URL, SUPABASE_REST_URL, SUPABASE_SERVICE_KEY, API_INTERNAL_JWT_SECRET)
- [ ] Set ENABLE_API_WORKER=false
- [ ] Deploy and verify health endpoint responds
- [ ] Test artifact download via API

### Vercel Frontend Setup
- [ ] Connect GitHub repo to Vercel
- [ ] Set environment variables (NEXTAUTH_URL, API_INTERNAL_JWT_SECRET, etc.)
- [ ] Deploy to production
- [ ] Test login flow
- [ ] Test audit mode (view runs/documents)
- [ ] Test artifact downloads

---

**Last Updated**: 2026-02-23
**Maintained by**: Claude Code
**Project**: LineCite
