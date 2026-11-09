import assert from "node:assert/strict";
import {test} from "node:test";

// Lead-only visual surface check. Supply a running table URL outside the
// sandbox; this test never starts an app or a browser unless explicitly opted in.
test("table has no visible authoring schema or raw typed IDs", {
  skip: !process.env.SOL183_BROWSER_URL,
}, async () => {
  const {chromium} = await import("playwright");
  const browser = await chromium.launch({executablePath: "/usr/bin/chromium", args: ["--no-sandbox"]});
  try {
    const page = await browser.newPage();
    await page.goto(process.env.SOL183_BROWSER_URL);
    await page.waitForLoadState("networkidle");
    const visible = await page.locator("body").innerText();
    assert.doesNotMatch(visible, /#{1,6}\s|\b(?:Talent Type|Prerequisite|Action Type|Trigger|Effect)\s*:|\b(?:action:typed\.|condition:typed\.|TAL_)/i);
  } finally {
    await browser.close();
  }
});
