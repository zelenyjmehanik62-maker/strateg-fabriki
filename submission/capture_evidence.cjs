// Authoring-only screenshot of local HTML containing unchanged CLI outputs.
const { chromium } = require(process.env.CODEX_NODE_MODULES + '/playwright');
const path = require('path');
const { pathToFileURL } = require('url');
(async () => {
  const browser = await chromium.launch({ executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1100, height: 100 }, deviceScaleFactor: 1 });
    for (const name of ['verification', 'traceability']) {
      await page.goto(pathToFileURL(path.join(__dirname, 'evidence', name + '.html')).href);
      await page.screenshot({ path: path.join(__dirname, 'evidence', name + '.png'), fullPage: true });
    }
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
