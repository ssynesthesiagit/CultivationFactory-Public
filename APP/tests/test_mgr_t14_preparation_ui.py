"""Actual Items module, with browser verification explicitly opt in."""
import base64
import os
from pathlib import Path
import subprocess

import pytest

APP = Path(__file__).resolve().parents[1]


def test_items_preparation_renderer_and_submission_without_browser():
    result = subprocess.run(["node", str(APP / "tests/items_preparation.mjs")],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.environ.get("CF_PREPARATION_BROWSER") != "1",
                    reason="Lead must run Chromium outside the sandbox with CF_PREPARATION_BROWSER=1")
def test_items_preparation_browser_buttons():
    from playwright.sync_api import sync_playwright
    source = (APP / "static/tabletop/items.js").read_bytes()
    module = "data:text/javascript;base64," + base64.b64encode(source).decode()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        page = browser.new_page()
        page.set_content('<div id="items-root"></div>')
        page.evaluate("""async module => {
          const {initItems, renderItems} = await import(module);
          function h(tag, props, ...children) {
            const node = document.createElement(tag);
            for (const [key, value] of Object.entries(props || {})) {
              if (key === 'class') node.className = value;
              else if (key === 'dataset') Object.assign(node.dataset, value);
              else node[key] = value;
            }
            for (const child of children.flat()) if (child != null) node.append(child);
            return node;
          }
          window.requests = [];
          initItems({h, $: id => document.getElementById(id), projectId: () => 'hero',
            sheet: () => ({equipment: {items: []}}), toast: () => {},
            fetchJson: async (url, options) => {
              if (url === '/api/session') return {token: 'fixture'};
              if (options) window.requests.push(JSON.parse(options.body));
              return {state: {revision: 3, armor: {}}, commands: [{operation: 'armor.fit.start',
                parameters: {item_key: 'given.0'}, label: 'Fit Lamellar: begin 10 minutes of fitting'}]};
            }});
          renderItems();
        }""", module)
        page.get_by_role("button", name="Fit Lamellar: begin 10 minutes of fitting").click()
        page.wait_for_function("window.requests.length === 1")
        assert page.evaluate("window.requests[0]") == {"operation": "armor.fit.start",
            "parameters": {"item_key": "given.0"}, "expected_revision": 3}
        browser.close()
