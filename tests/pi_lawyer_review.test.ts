import { test, expect } from '@playwright/test';
import path from 'path';

test('Upload, Review, and Verify Evidence', async ({ page }) => {
  const baseURL = 'http://localhost:5173';
  // 1. Landing Page - "The Pitch"
  await page.goto(baseURL + '/');
  await expect(page).toHaveTitle(/CiteLine/);
  console.log('Lawyer: "Okay, landing page loads. Clean design."');

    // 2. Upload - "The Intake"
    // Navigate to a new matter or existing list
    // Assuming we land on a dashboard or can click "New Matter"
    // For this test, we might need to seed a matter ID or just pick the first one
    
    // Let's assume we can navigate to a matter list
    await page.goto('/matters'); 
    
    // Simulate creating a new matter if needed, or picking "Golden Validation Case"
    // Clicking the first available matter for now
    const firstMatter = page.locator('.matter-card').first();
    if (await firstMatter.isVisible()) {
        await firstMatter.click();
    } else {
        console.log('Lawyer: "Where are my cases? Creating a dummy one..."');
        // Fallback: Create matter logic would go here
    }

    // Upload Document
    console.log('Lawyer: "Time to upload the big packet."');
    const fileInput = page.locator('input[type="file"]');
    // We'll use the sample pilot for speed, though a real lawyer would use a 500mb file
    await fileInput.setInputFiles('sample_pilot.pdf'); 
    
    // Wait for upload confirmation
    await expect(page.locator('text=Upload PDF')).toBeVisible(); 
    // Trigger analysis
    await page.click('button:has-text("Start Analysis")');
    
    // 3. The Wait - "Is it working?"
    console.log('Lawyer: "Spinning... hopeful."');
    // In a real e2e, we'd wait for the websocket/polling. 
    // Here we'll wait for the "Success" status badge
    await expect(page.locator('.status-badge.success')).toBeVisible({ timeout: 300000 }); // 5 min timeout

    // 4. The Review - "Show me the money"
    console.log('Lawyer: "Okay, it finished. Let\'s see the timeline."');
    
    // Check for the "Anchored Narrative" rows (The new feature)
    const narrativeRow = page.locator('.narrative-row').first();
    await expect(narrativeRow).toBeVisible();
    
    const headline = await narrativeRow.locator('.headline').innerText();
    console.log(`Lawyer: "Reading: ${headline}"`);
    
    // 5. The "Aha!" Moment - Clicking Evidence
    console.log('Lawyer: "But is this real? Clicking the evidence pill..."');
    const evidencePill = narrativeRow.locator('.evidence-pill');
    await evidencePill.click();
    
    // Expect the PDF viewer or Evidence Dock to open
    await expect(page.locator('.evidence-dock')).toBeVisible();
    await expect(page.locator('.pdf-viewer')).toBeVisible();
    
    console.log('Lawyer: "It actually jumped to the page. I might pay for this."');
});
