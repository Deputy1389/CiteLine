const { chromium } = require('@playwright/test');
const fs = require('fs');
const path = require('path');
const BASE='https://www.linecite.com';
const EMAIL='demo@ontarus.ai';
const PASSWORD='eventis123';
const PACKET='C:/CiteLine/PacketIntake/batch_029_complex_prior/packet.pdf';
const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));

async function ensureLogin(page){
  await page.goto(`${BASE}/app/new-case`, { waitUntil:'domcontentloaded' });
  if (page.url().includes('/auth/signin')) {
    await page.goto(`${BASE}/auth/signin`, { waitUntil:'domcontentloaded' });
    await page.waitForSelector('input[type="email"]', { timeout: 60000 });
    await page.fill('input[type="email"]', EMAIL);
    await page.fill('input[type="password"]', PASSWORD);
    await page.getByRole('button', { name: /authorize session|sign in/i }).click();
    await page.waitForTimeout(4000);
  }
  await page.goto(`${BASE}/app/new-case`, { waitUntil:'domcontentloaded' });
  await page.waitForSelector('#caseName, input[placeholder*="auto-generate" i]', { timeout: 60000 });
}

async function createMatterAndUpload(page){
  const caseInput = page.locator('#caseName, input[placeholder*="auto-generate" i]').first();
  await caseInput.fill(`Loop ${new Date().toISOString().replace(/[:.]/g,'-')}`);
  const fileInput = page.locator('input[type="file"]').first();
  await fileInput.setInputFiles(PACKET);
  const selectors = [
    'button:has-text("Start")',
    'button:has-text("Create")',
    'button:has-text("Analyze")',
    'button:has-text("Upload")',
    'button:has-text("Begin")',
    'button:has-text("Initialize")',
    'button:has-text("Matter")',
  ];
  for (const sel of selectors) {
    try {
      const btn = page.locator(sel).first();
      if (await btn.count() && await btn.isVisible({ timeout: 500 })) {
        await btn.click();
        break;
      }
    } catch {}
  }
  await page.waitForURL(/\/app\/cases\/.+\/review/, { timeout: 600000 });
  return page.url();
}

async function waitForRun(page,matterId){
  for (let i=0;i<240;i++){
    const payload = await page.evaluate(async (m) => {
      const r = await fetch(`/api/citeline/matters/${m}/runs`, { credentials:'include' });
      const text = await r.text();
      let body; try { body = JSON.parse(text); } catch { body = text; }
      return { status: r.status, body };
    }, matterId);
    if (payload.status===200 && Array.isArray(payload.body) && payload.body.length){
      const runs=[...payload.body].sort((a,b)=>String(b.started_at||b.created_at||'').localeCompare(String(a.started_at||a.created_at||'')));
      const run=runs[0]; const st=String(run.status||'').toLowerCase();
      console.log('poll', i, run.id, st);
      if (['success','partial','needs_review','failed'].includes(st)) return run;
    } else {
      console.log('poll', i, 'runs', payload.status);
    }
    await sleep(5000);
  }
  throw new Error('Timed out waiting for run');
}

async function fetchArtifact(page, runId, name, outPath, binary){
  const res = await page.evaluate(async ({runId,name,binary}) => {
    const r = await fetch(`/api/citeline/runs/${runId}/artifacts/by-name/${name}`, { credentials:'include' });
    if (!r.ok) return { ok:false, status:r.status, text: await r.text() };
    if (binary){ const ab = await r.arrayBuffer(); return { ok:true, bytes:Array.from(new Uint8Array(ab)) }; }
    return { ok:true, text: await r.text() };
  }, {runId,name,binary});
  if (!res.ok) throw new Error(`${name} ${res.status} ${res.text}`);
  fs.mkdirSync(path.dirname(outPath), { recursive:true });
  if (binary) fs.writeFileSync(outPath, Buffer.from(res.bytes)); else fs.writeFileSync(outPath, res.text, 'utf8');
}

(async()=>{
  const browser = await chromium.launch({ headless:false });
  const page = await browser.newPage();
  try {
    await ensureLogin(page);
    const reviewUrl = await createMatterAndUpload(page);
    const matterId = reviewUrl.split('/app/cases/')[1].split('/')[0];
    console.log('matter', matterId);
    await page.reload({ waitUntil:'domcontentloaded' });
    const run = await waitForRun(page, matterId);
    console.log('run', JSON.stringify(run));
    const runId = run.id;
    await fetchArtifact(page, runId, 'chronology.pdf', `reference/run_${runId}_pdf.pdf`, true);
    await fetchArtifact(page, runId, 'evidence_graph.json', `reference/run_${runId}_evidence_graph.json`, false);
    console.log('saved', runId, matterId);
  } catch (e) {
    console.error(e);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
