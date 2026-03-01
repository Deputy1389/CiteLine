import { test, expect, chromium } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

/**
 * LineCite "Lawyer Loop" - Automated UI verification script.
 * 
 * This script:
 * 1. Logs into the production site.
 * 2. Uploads the target packet.
 * 3. Waits for full extraction (Step 1-19).
 * 4. Verifies Audit Mode UI and Strategic Moat.
 * 5. Captures artifacts for agent review.
 */

async function runLawyerLoop() {
  const browser = await chromium.launch({ headless: false }); // Set to true for headless
  const context = await browser.newContext();
  const page = await context.newPage();

  console.log('🚀 STARTING LAWYER LOOP VERIFICATION');

  try {
    // 1. Sign In
    console.log('🔑 Logging in...');
    await page.goto('https://www.linecite.com/auth/signin');
    await page.fill('input[type="email"]', 'demo@ontarus.ai');
    await page.fill('input[type="password"]', 'eventis123');
    await page.click('button:has-text("Sign In")');
    await expect(page).toHaveURL(/\/app/, { timeout: 30000 });

    // 2. Create Matter
    console.log('📁 Creating new matter...');
    await page.click('text=Start New Matter');
    const caseName = `Loop Test - ${new Date().toISOString()}`;
    await page.fill('#caseName', caseName);

    // 3. Upload Packet
    const packetPath = 'C:\\CiteLine\\PacketIntake\\batch_029_complex_prior\\packet.pdf';
    console.log(`📤 Uploading packet: ${packetPath}`);
    await page.setInputFiles('input[type="file"]', packetPath);

    // 4. Wait for Analysis
    console.log('⏳ Waiting for analysis (3-5 minutes)...');
    await expect(page).toHaveURL(/\/app\/cases\/.*\/review/, { timeout: 600000 });
    console.log('✅ Audit Mode Loaded.');

    // 5. Verify Strategic Moat
    console.log('🧠 Verifying AI Strategic Moat...');
    await page.click('button[role="tab"]:has-text("Strategic Moat")');
    // Ensure AI results are populated
    await expect(page.locator('text=Contradiction, text=Strategic Recommendations').first()).toBeVisible({ timeout: 60000 });
    console.log('✨ Strategic Moat verified.');

    // 6. Inspect Timeline Density
    await page.click('button[role="tab"]:has-text("Timeline")');
    const eventCount = await page.locator('button.w-full.text-left.border').count();
    console.log(`📊 Timeline Density: ${eventCount} events extracted.`);

    // 7. Download Final PDF
    console.log('📥 Downloading chronology report...');
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.click('button:has-text("Export DOCX")'), // Or finding the PDF export
    ]);
    const downloadPath = path.join(process.cwd(), 'tmp', 'loop_result.docx');
    await download.saveAs(downloadPath);
    console.log(`💾 Report saved to: ${downloadPath}`);

    await page.screenshot({ path: 'tmp/lawyer-loop-success.png', fullPage: true });
    console.log('🏁 LAWYER LOOP COMPLETE - SUCCESS');

  } catch (err) {
    console.error('❌ LAWYER LOOP FAILED:', err);
    await page.screenshot({ path: 'tmp/lawyer-loop-error.png' });
  } finally {
    await browser.close();
  }
}

runLawyerLoop();
