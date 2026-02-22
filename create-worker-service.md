# Create Worker Service on Render

Since Render didn't auto-create the worker from render.yaml, follow these steps:

## Quick Setup (5 minutes)

### Step 1: Create Background Worker
1. Go to https://dashboard.render.com
2. Click **"New +"** button (top right corner)
3. Select **"Background Worker"**

### Step 2: Repository Settings
- **Repository**: `Deputy1389/CiteLine` (should already be authorized)
- **Branch**: `main`
- Click "Connect"

### Step 3: Basic Configuration
- **Name**: `linecite-worker`
- **Region**: Same as your API (probably Oregon or Ohio)
- **Runtime**: Docker
- **Instance Type**: Free

### Step 4: Build Settings
- **Dockerfile Path**: `./Dockerfile`
- **Docker Context**: `.` (root directory)
- **Docker Command**: `python -m apps.worker.runner`

### Step 5: Environment Variables

Click **"Advanced"** to expand environment variables section.

Add these one by one (click "+ Add Environment Variable" for each):

| Key | Value | Notes |
|-----|-------|-------|
| `DATABASE_URL` | *Use "Add from Database" dropdown* | Select `linecite-db` |
| `DATA_DIR` | `/app/data` | Where files are stored |
| `PYTHONPATH` | `/app` | Python import path |
| `DISABLE_OCR` | `false` | Enable OCR processing |
| `OCR_MODE` | `full` | Process all pages |
| `OCR_DPI` | `200` | Image resolution for OCR |
| `OCR_WORKERS` | `2` | Parallel OCR threads |
| `OCR_TIMEOUT_SECONDS` | `30` | Per-page timeout |
| `OCR_TOTAL_TIMEOUT_SECONDS` | `600` | Total OCR budget (10 min) |
| `MAX_RUN_RETRIES` | `3` | Retry limit for failed runs |
| `RUN_TIMEOUT_SECONDS` | `1800` | Pipeline timeout (30 min) |

**CRITICAL**: For `DATABASE_URL`, click the dropdown and select **"Add from database"**, then choose `linecite-db`. This ensures the worker uses the same database as your API.

### Step 6: Create Service
1. Click **"Create Background Worker"**
2. Render will start building (5-10 minutes)
3. Watch the deployment logs

### Step 7: Verify It's Working

Once deployed, check the logs:
- Click on `linecite-worker` service
- Click "Logs" tab
- You should see:
  ```
  Worker runner started. Polling for pending runs...
  ```
  repeating every ~5 seconds

If you see that message, **the worker is ready!**

---

## Testing

### Test 1: Upload a Document
1. Go to https://www.linecite.com
2. Create a new matter
3. Upload a small PDF (5-10 pages)
4. Start extraction

### Test 2: Monitor Worker
1. Go to Render dashboard → linecite-worker → Logs
2. You should see:
   ```
   Found pending run {run_id}. Starting pipeline...
   OCR progress: page 1/10...
   OCR progress: page 2/10...
   ...
   Pipeline complete. Status: success
   ```

### Test 3: Check Output
1. Go back to https://www.linecite.com
2. Run should show "success" status
3. Check chronology for real medical content
4. Check Evidence Vault loads PDF

---

## Troubleshooting

### Issue: Worker build fails
**Solution**: Check build logs for errors. Most common:
- Missing dependencies → already in Dockerfile, shouldn't happen
- Docker build timeout → retry deployment

### Issue: Worker starts but crashes immediately
**Solution**: Check runtime logs. Most common:
- `ModuleNotFoundError` → Dockerfile needs update
- Database connection error → DATABASE_URL not set correctly

### Issue: Worker runs but doesn't pick up jobs
**Solution**:
1. Check DATABASE_URL matches between API and worker
2. Verify worker logs show "Polling for pending runs..."
3. Manually queue a run via UI and watch worker logs

### Issue: Jobs start but fail with "Persist failed"
**Solution**: This is the bug we fixed! But if you still see it:
1. Check error message in run.error_message field
2. Likely a database constraint violation
3. Share the full error message for debugging

---

## Cost

**Free Tier Limits**:
- API: 750 hours/month (always running = 720 hours/month ✓)
- Worker: 750 hours/month (always running = 720 hours/month ✓)
- Database: Free for 90 days, then $7/month

Both services fit in free tier for the first 90 days!

---

## Next Steps After Worker is Running

1. ✅ Test with small document (5-10 pages)
2. ✅ Test with medium document (50-100 pages)
3. ✅ Test with large document (500 pages)
4. ✅ Verify no runs get stuck in "running"
5. ✅ Verify Evidence Vault works
6. ✅ Then move on to frontend polish

---

## Alternative: If You Don't Want to Click Through UI

You can also use Render CLI:

```bash
# Install Render CLI
npm install -g @render-deploy/cli

# Login
render login

# Deploy services from render.yaml
render blueprint launch
```

But the UI method above is simpler for first-time setup.
