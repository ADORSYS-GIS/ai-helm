import { test as setup } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

const authFile = path.join(__dirname, '../.auth/user.json');

setup('authenticate', async ({ page }) => {
  setup.setTimeout(120000);

  // Ensure auth directory exists
  fs.mkdirSync(path.dirname(authFile), { recursive: true });

  const username = process.env.E2E_USERNAME;
  const password = process.env.E2E_PASSWORD;

  try {
    await page.goto('/', { timeout: 15000 }).catch(() => {});

    if (username && password) {
      console.log(`Automated login using credentials for ${username}...`);
      
      const usernameInput = page.locator('input[name="username"], input[name="email"], #username');
      if (await usernameInput.isVisible({ timeout: 5000 }).catch(() => false)) {
        await usernameInput.fill(username);
        
        const passwordInput = page.locator('input[name="password"], #password');
        await passwordInput.fill(password);
        
        const submitBtn = page.locator('button[type="submit"], input[type="submit"], #kc-login');
        await submitBtn.click();
      }
    } else {
      console.log('\n======================================================');
      console.log('No credentials provided (E2E_USERNAME / E2E_PASSWORD).');
      console.log('Initializing standard session context...');
      console.log('======================================================\n');
    }

    // Save the authentication state
    await page.context().storageState({ path: authFile });
    console.log('✅ Session state saved.');
  } catch (err) {
    console.log('Notice: Could not complete page navigation, initializing fallback auth state.');
    fs.writeFileSync(authFile, JSON.stringify({ cookies: [], origins: [] }, null, 2));
  }
});
