import { chromium } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  console.log('🚀 [START] PI Lawyer Review Simulation');

  try {
    // 1. Login
    console.log('🔑 Logging in to LineCite...');
    await page.goto('https://www.linecite.com/auth/signin');
    await page.fill('input[type="email"]', 'demo@ontarus.ai');
    await page.fill('input[type="password"]', 'eventis123');
    await page.click('button:has-text("Authorize Session")');
    await page.waitForURL('**/app/**');
    console.log('✅ Logged in.');

    // 2. Start New Matter
    console.log('📁 Creating New Matter...');
    await page.click('text=New Matter');
    const caseName = `PI Review Simulation - ${new Date().toISOString()}`;
    await page.fill('input[placeholder*="auto-generate"], input[aria-label*="Case Name"]', caseName);

    // 3. Upload Packet
    const packetPath = 'C:/Citeline/PacketIntake/batch_029_complex_prior/packet.pdf';
    console.log(`📤 Uploading: ${packetPath}`);
    if (!require('fs').existsSync(packetPath)) {
      throw new Error(`File not found: ${packetPath}`);
    }
    await page.setInputFiles('input[type="file"]', packetPath);

    // 4. Wait for Audit Mode
    console.log('⏳ Cloud worker is processing (wait up to 10 mins)...');
    await page.waitForURL('**/app/cases/**/review', { timeout: 600000 });
    console.log(`✅ URL reached: ${page.url()}`);
    const reviewUrl = page.url();
    const caseIdMatch = reviewUrl.match(/\/app\/cases\/([^/]+)\/review/);
    const caseId = caseIdMatch?.[1] ?? null;

    // Wait for the page to actually load its dynamic content
    await page.waitForFunction(() => document.body.innerText.length > 500, { timeout: 60000 });

    // Wait for "PROCESSING" to disappear
    console.log('⏳ Waiting for AI extraction to complete...');
    let attempts = 0;
    while (attempts < 60) {
      const bodyText = await page.innerText('body');
      const hasProcessing = /PROCESSING/i.test(bodyText) || /\? pages/i.test(bodyText) || /Analyzing Medical Records/i.test(bodyText);

      if (bodyText.length > 500 && !hasProcessing) {
        console.log('✅ Extraction complete.');
        break;
      }

      // If we've been waiting more than 2 minutes and it seems stuck on "Analyzing", try a reload
      if (attempts > 12 && attempts % 6 === 0) {
        console.log('🔄 Results taking longer than expected. Triggering UI reload...');
        await page.reload();
        await page.waitForTimeout(5000);
      }

      await page.waitForTimeout(10000);
      attempts++;
    }
    if (attempts >= 60) console.warn('⚠️ Timed out waiting for extraction finalization, proceeding anyway...');

    // Give it a moment to render final UI
    await page.waitForTimeout(5000);
    const bodyContent = await page.innerText('body');
    console.log(`📄 Page content snippet (first 500 chars): ${bodyContent.substring(0, 500).replace(/\n/g, ' ')}`);

    // Log all button texts
    const allButtons = await page.locator('button').allInnerTexts();
    console.log(`🔘 All buttons: ${allButtons.join(' | ')}`);

    // 5. Inspect Strategic Moat
    console.log('🧠 Auditing Strategic Moat...');

    const moatSelector = 'text=/Strategic (Moat|Context)/i';
    const moatElement = page.locator(moatSelector);

    if (await moatElement.count() > 0) {
      console.log('📍 Found Strategic Moat/Context element.');
      await moatElement.first().click();
    } else {
      console.warn('⚠️ Strategic Moat/Context not found by text.');
    }

    // Check for AI insights
    try {
      // Use a more flexible selector for insights
      const insightSelector = 'text=/Contradiction|Strategic Recommendations|Recommendation/i';
      await page.waitForSelector(insightSelector, { timeout: 60000 });
      console.log('✨ Strategic Moat populated with AI insights.');
    } catch (e) {
      console.warn('⚠️ Strategic Moat did not show insights within 60s. Proceeding with verification.');
    }

    // 6. Check Timeline Density
    console.log('📊 Verifying Extraction Density...');
    const timelineSelector = 'text=/Timeline/i';
    const timelineElement = page.locator(timelineSelector);

    if (await timelineElement.count() > 0) {
      await timelineElement.first().click();
      const rowCount = await page.locator('button.w-full.text-left.border, .timeline-row, [role="row"]').count();
      console.log(`📊 Total Events/Rows: ${rowCount}`);
    } else {
      console.warn('⚠️ Timeline not found by text.');
    }

    // 7. Verify High-Stakes Data
    const body = await page.innerText('body');
    const hasMRI = body.includes('MRI');
    const hasER = body.includes('ER');
    console.log(`🔍 MRI Data: ${hasMRI}, ER Data: ${hasER}`);

    await page.screenshot({ path: 'tmp/final-pi-audit.png', fullPage: true });
    console.log('🏁 Simulation Complete. Screenshot saved to tmp/final-pi-audit.png');
    fs.mkdirSync('tmp', { recursive: true });
    fs.writeFileSync(
      'tmp/last_pi_audit_run.json',
      JSON.stringify({ caseId, reviewUrl, caseName, packetPath }, null, 2),
      'utf-8',
    );
    console.log(`RUN_RESULT_JSON ${JSON.stringify({ caseId, reviewUrl, caseName })}`);

  } catch (err) {
    console.error('❌ Simulation Failed:', err);
    await page.screenshot({ path: 'tmp/pi-audit-error.png' });
  } finally {
    await browser.close();
  }
}

main();
