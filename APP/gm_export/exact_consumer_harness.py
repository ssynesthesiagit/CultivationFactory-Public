from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from app.authorities import GM_SCREEN_SHA256
from typing import Any

from app.core import canonical_json, sha256_file

EXPECTED_TABS = [
    "overview-core-stats", "leveling-ledger", "background-origin", "paths-subpaths",
    "spheres-talents", "insights", "actions", "composite-playbooks", "forged-techniques",
    "martial-manuals-recorded-arts", "immortal-arts", "foundation", "method",
    "companions-spirits", "equipment", "resources-states-suppression", "dao-i-ching", "diagnostics",
]
SCRIPTS = [
    "pako.min.js", "sphere-rules.js", "chakra-sphere-rules.js", "foundation-catalog.js",
    "foundation-readable-catalog.js", "sphere-talent-catalog.js", "background-catalog.js",
    "insight-catalog.js", "app.js", "r2h-builder.js", "r2h2-builder.js",
    "r2h3-foundation-layout.js", "r2h4-semantic.js", "path-subpath-feature-catalog.js",
    "r2i-phase2e.js", "r2k3-hf2-training-recorded-arts.js",
]


def _norm(value: str) -> str:
    return " ".join((value or "").split())


def _is_windows() -> bool:
    return os.name == "nt"


def _windows_browser_candidates() -> list[Path]:
    candidates: list[Path] = []
    for variable, relative in (
        ("ProgramFiles(x86)", "Microsoft/Edge/Application/msedge.exe"),
        ("ProgramFiles", "Microsoft/Edge/Application/msedge.exe"),
        ("ProgramFiles", "Google/Chrome/Application/chrome.exe"),
        ("ProgramFiles(x86)", "Google/Chrome/Application/chrome.exe"),
        ("LOCALAPPDATA", "Microsoft/Edge/Application/msedge.exe"),
        ("LOCALAPPDATA", "Google/Chrome/Application/chrome.exe"),
    ):
        root = os.environ.get(variable)
        if root:
            candidates.append(Path(root) / relative)
    return candidates


def _default_browser_executable() -> str | None:
    configured = os.environ.get("TIANXIA_BROWSER_EXECUTABLE")
    if configured:
        return configured
    if not _is_windows():
        return "/usr/bin/chromium"
    return next((str(path) for path in _windows_browser_candidates() if path.is_file()), None)


async def verify(package: Path, consumer_root: Path, *, browser_executable: str | None = None) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    package = package.resolve(); consumer_root = consumer_root.resolve()
    errors: list[dict[str, str]] = []
    async with async_playwright() as pw:
        launch_options: dict[str, Any] = {"headless": True, "args": ["--no-sandbox"]}
        if browser_executable:
            launch_options["executable_path"] = browser_executable
        browser = await pw.chromium.launch(**launch_options)
        page = await browser.new_page()
        page.on("console", lambda msg: errors.append({"kind": "console", "type": msg.type, "text": msg.text}) if msg.type == "error" else None)
        page.on("pageerror", lambda exc: errors.append({"kind": "pageerror", "type": "error", "text": str(exc)}))
        html = (consumer_root / "index.html").read_text(encoding="utf-8")
        html = re.sub(r'<script[^>]+src="[^"]+"[^>]*></script>', "", html)
        html = re.sub(r'<link[^>]+href="[^"]+"[^>]*>', "", html)
        await page.set_content(html, wait_until="domcontentloaded")
        await page.evaluate("""(()=>{const m=new Map();Object.defineProperty(window,'localStorage',{value:{getItem:k=>m.has(k)?m.get(k):null,setItem:(k,v)=>m.set(k,String(v)),removeItem:k=>m.delete(k),clear:()=>m.clear(),key:i=>Array.from(m.keys())[i]||null,get length(){return m.size}},configurable:true});})()""")
        for script in SCRIPTS:
            await page.add_script_tag(content=(consumer_root / script).read_text(encoding="utf-8"))
        await page.wait_for_timeout(500)
        await page.set_input_files("#packageFileInput", str(package))
        await page.wait_for_timeout(3500)
        status_text = await page.locator("#packageFileStatus").inner_text()
        option_count = await page.locator("#activeCharacterSelect option").count()
        selected_id = await page.locator("#activeCharacterSelect").input_value()
        import_state = await page.evaluate("""()=>{
          const raw=localStorage.getItem('tianxia-dao-dashboard-v1');
          return raw ? JSON.parse(raw) : null;
        }""")
        collection = await page.evaluate("""()=>{
          const root=document.getElementById('activeCharacterVisualSheet');
          const tabs=[...root.querySelectorAll('[data-sheet-tab]')].map(x=>x.dataset.sheetTab);
          const text={}; const counts={};
          for(const tab of tabs){const panel=root.querySelector(`[data-sheet-panel="${tab}"]`);text[tab]=panel?.innerText||'';counts[tab]={characters:(panel?.innerText||'').length,articles:panel?.querySelectorAll('article').length||0,rows:panel?.querySelectorAll('tr').length||0};}
          const stored=JSON.parse(localStorage.getItem('tianxia-dao-dashboard-v1')||'{}');
          const pkg=(stored.packages||[])[0]||null;
          const model=typeof window.HF05ZUI_R2I?.modelFor==='function'&&pkg?window.HF05ZUI_R2I.modelFor(pkg):null;
          const saved=pkg;
          const test=document.createElement('div');test.id='c2c1Rehydrate';test.style.position='fixed';test.style.left='-100000px';test.style.width='1600px';
          if(saved&&typeof window.renderVisualCharacterSheet==='function'){test.innerHTML=window.renderVisualCharacterSheet(saved,{});document.body.appendChild(test);attachVisualSheetTabs(test.id);}
          const reloadText={}; if(saved){for(const tab of tabs){reloadText[tab]=test.querySelector(`[data-sheet-panel="${tab}"]`)?.innerText||'';}} test.remove();
          return {tabs,text,counts,reloadText,package:{id:pkg?.id,name:pkg?.name,sourcePackageKey:pkg?.sourcePackageKey},model};
        }""")
        body_text = await page.locator("body").inner_text()
        await browser.close()
    tabs = collection.get("tabs") or []
    tab_text = collection.get("text") or {}
    reload_text = collection.get("reloadText") or {}
    retention = {tab: _norm(tab_text.get(tab, "")) == _norm(reload_text.get(tab, "")) for tab in tabs}
    no_object = "[object Object]" not in body_text
    exact_tabs = tabs == EXPECTED_TABS
    nonempty = all(_norm(tab_text.get(tab, "")) for tab in EXPECTED_TABS)
    background_text = _norm(tab_text.get("background-origin", ""))
    talent_text = _norm(tab_text.get("spheres-talents", ""))
    background_talent_separate = "Hidden Tool Cache" in background_text and "Background Talent" in background_text
    result = {
        "schema_version": "TianxiaFoundry.ExactBundledGMSourceConsumerReport.v1",
        "status": "GM_SCREEN_SOURCE_CONSUMER_VERIFIED" if exact_tabs and nonempty and all(retention.values()) and no_object and not errors and option_count >= 1 else "GM_SCREEN_SOURCE_CONSUMER_FAILED",
        "package_path": str(package), "package_sha256": sha256_file(package),
        "consumer_root": str(consumer_root), "consumer_package_sha256": GM_SCREEN_SHA256,
        "importer_identity": "HF05ZUI-R2K.3 app.js packageFileInput + pako",
        "renderer_identity": "HF05ZUI-R2K.3 r2i-phase2e.js renderVisualCharacterSheet",
        "browser_harness": {"engine": "Chromium/Playwright", "native_or_interactive_acceptance": "NOT_RUN"},
        "status_text": status_text, "option_count": option_count, "selected_id": selected_id,
        "package_identity": collection.get("package"), "tabs": tabs, "expected_tabs": EXPECTED_TABS,
        "exact_tab_order": exact_tabs, "all_tabs_nonempty": nonempty, "tab_counts": collection.get("counts"),
        "array_preservation": {"spheres_talents_chars": len(talent_text), "background_origin_chars": len(background_text)},
        "background_talent_separate": background_talent_separate,
        "no_object_object": no_object, "save_reload_semantic_equivalence": all(retention.values()), "retention": retention,
        "console_or_page_errors": errors, "local_save_package_count": len((import_state or {}).get("packages") or []),
        "semantic_hash": hashlib.sha256(canonical_json({"tabs": tabs, "text": {k:_norm(v) for k,v in tab_text.items()}, "display_name": (collection.get("package") or {}).get("name")}).encode("utf-8")).hexdigest(),
        "legacy_full_execution_acceptance": "NOT_CLAIMED_DIAGNOSTIC_REQUIRES_COMBAT_SIDECARS",
    }
    if result["status"] != "GM_SCREEN_SOURCE_CONSUMER_VERIFIED":
        result["failure_reasons"] = [
            key for key, passed in {
                "exact_tabs": exact_tabs, "nonempty_tabs": nonempty, "save_reload": all(retention.values()),
                "no_object_object": no_object, "no_errors": not errors, "package_imported": option_count >= 1,
            }.items() if not passed
        ]
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--consumer-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--browser", default=_default_browser_executable())
    args = parser.parse_args()
    report = asyncio.run(verify(args.package, args.consumer_root, browser_executable=args.browser))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "GM_SCREEN_SOURCE_CONSUMER_VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
