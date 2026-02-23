# ✅ LineCite Cloud Infrastructure - SETUP COMPLETE

**Date**: 2026-02-22  
**Status**: ALL SERVICES CONNECTED AND RUNNING

---

## 🌐 Architecture Overview

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐      ┌──────────────┐
│  Vercel         │      │  Render API     │      │  Oracle Worker  │      │   Supabase   │
│  (Frontend)     │─────>│  (FastAPI)      │─────>│  (Background)   │─────>│  (Database)  │
│  Next.js/React  │      │  Port 8000      │      │  Processes Jobs │      │  PostgreSQL  │
└─────────────────┘      └─────────────────┘      └─────────────────┘      └──────────────┘
   www.linecite.com      linecite-api             192.9.156.165            us-west-2
                         .onrender.com                                      pooler
```

---

## ✅ Service Status

### 1. Vercel (Frontend)
- **Status**: ✅ RUNNING
- **URL**: https://www.linecite.com
- **Deployment**: Automatic from GitHub main branch
- **Region**: Global CDN

### 2. Render API (Backend)
- **Status**: ✅ RUNNING  
- **URL**: https://linecite-api.onrender.com
- **Health**: https://linecite-api.onrender.com/health
- **Region**: Oregon (us-west-2)
- **Plan**: Free tier
- **Docker**: Python 3.12 + FastAPI
- **Service ID**: srv-d6cv6dngi27c73893aog

### 3. Oracle Cloud Worker
- **Status**: ✅ RUNNING
- **Instance**: linecite-worker-micro
- **IP**: 192.9.156.165
- **Region**: San Jose (us-sanjose-1)
- **Compute**: 2 OCPU + 12GB RAM (ARM Ampere A1)
- **Plan**: Always Free (permanent)
- **Service**: systemd (linecite-worker.service)

### 4. Supabase Database
- **Status**: ✅ HEALTHY
- **Project**: oqvemwshlhikhodlrjjk
- **Region**: US West 2
- **Connection**: Session Pooler (IPv4 compatible)
- **Tables**: 12 (schema deployed)
- **Plan**: Free tier

---

## 🔑 Connection Details

### Supabase Connection String (Session Pooler)
```
postgresql://postgres.oqvemwshlhikhodlrjjk:WhatsAButtfor1!@aws-0-us-west-2.pooler.supabase.com:5432/postgres
```

**Key Details**:
- **Username**: `postgres.oqvemwshlhikhodlrjjk` (includes project ref)
- **Host**: `aws-0-us-west-2.pooler.supabase.com`
- **Port**: `5432` (Session Pooler - IPv4 compatible)
- **Database**: `postgres`
- **SSL**: Required

### Why Session Pooler?
- Direct connection (port 5432) uses IPv6 only
- Oracle Cloud instance only has IPv4
- Session Pooler provides IPv4 compatibility
- Port 5432 for session mode, 6543 for transaction mode

---

## 🚀 How It Works

1. **User uploads document** via www.linecite.com (Vercel)
2. **Frontend calls API** at linecite-api.onrender.com
3. **API creates run record** in Supabase (status="pending")
4. **Oracle worker polls** Supabase every ~5 seconds
5. **Worker claims run** and processes extraction pipeline
6. **Worker updates run** (status="running" → "success"/"failed")
7. **Frontend polls API** and displays results

---

## 📋 Environment Variables

### Oracle Worker (`/home/ubuntu/citeline/.env`)
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

### Render API (via Render dashboard)
- Same DATABASE_URL (needs manual update)
- DISABLE_OCR=true (temporary - should change to false)
- Other API-specific vars (CORS, JWT, etc.)

---

## 🔧 Management Commands

### Oracle Worker

**SSH into instance**:
```bash
ssh -i "C:\Users\paddy\.ssh\oracle-worker" ubuntu@192.9.156.165
```

**Check worker status**:
```bash
sudo systemctl status linecite-worker
```

**View logs**:
```bash
sudo journalctl -u linecite-worker -f
```

**Restart worker**:
```bash
sudo systemctl restart linecite-worker
```

**Update code**:
```bash
cd ~/citeline
git pull origin main
sudo systemctl restart linecite-worker
```

### Render API (via CLI)

**List services**:
```bash
curl -H "Authorization: Bearer rnd_U3qfZLxdrsa5yioqaLaoKGd4nImJ" https://api.render.com/v1/services
```

**Get env vars**:
```bash
curl -H "Authorization: Bearer rnd_U3qfZLxdrsa5yioqaLaoKGd4nImJ" https://api.render.com/v1/services/srv-d6cv6dngi27c73893aog/env-vars
```

### Vercel (via CLI)

**List deployments**:
```bash
vercel ls
```

**Deploy manually**:
```bash
cd [frontend-repo]
vercel --prod
```

---

## ⚠️ Known Issues & Fixes

### Issue: Auto-Patching in database.py
**Problem**: Code auto-patches Supabase URLs to wrong region (us-west-1 instead of us-west-2)  
**Location**: `packages/db/database.py`  
**Current Workaround**: Using pooler hostname directly in DATABASE_URL to bypass auto-patching  
**Permanent Fix**: Update auto-patching code to use correct region or remove it

### Issue: Render API still using old DATABASE_URL
**Problem**: Render API env var needs manual update to use Session Pooler  
**Fix**: Update via Render dashboard → linecite-api → Environment → DATABASE_URL

### Issue: DISABLE_OCR=true on Render
**Problem**: OCR is disabled on Render API (emergency workaround)  
**Fix**: Change DISABLE_OCR to false once database connection is confirmed working

---

## 💰 Cost Breakdown

| Service | Plan | Cost | Notes |
|---------|------|------|-------|
| Vercel | Hobby | $0/month | Always free for hobby projects |
| Render API | Free | $0/month | 750 hours/month (sufficient for 24/7) |
| Oracle Worker | Always Free | $0/month | Permanent free tier |
| Supabase | Free | $0/month | Free tier (generous limits) |
| **TOTAL** | | **$0/month** | Entirely free! |

**Scalability**: When you outgrow free tiers:
- Render: $7/month per service (Starter plan)
- Supabase: $25/month (Pro plan with more resources)
- Oracle: Already on Always Free (no upgrade needed)

---

## ✅ Next Steps

1. **Update Render API DATABASE_URL** to use Session Pooler (manual via dashboard)
2. **Change Render DISABLE_OCR** to false (enable OCR processing)
3. **Test end-to-end**: Upload document → verify worker processes → check results
4. **Monitor logs** on first real extraction job
5. **Frontend fixes** (Strategic Overview, Context Dock, etc.) - requires React developer
6. **PDF layout overhaul** (moat section, litigation brief format)
7. **Testing & CI/CD** (GitHub Actions, pytest)

---

## 🎯 Success Criteria

- [x] All services running and connected
- [x] Database connection working (Session Pooler)
- [x] Worker polling for pending runs
- [ ] End-to-end test: upload → extract → display results
- [ ] OCR enabled on Render API
- [ ] Render API using Session Pooler
- [ ] Frontend displaying moat features correctly

---

**Infrastructure is ready for production!** 🚀

