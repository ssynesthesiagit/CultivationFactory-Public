from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.authorities import GM_SCREEN_SHA256
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
        system_chromium = Path("/usr/bin/chromium")
        return str(system_chromium) if system_chromium.is_file() else None
    return next((str(path) for path in _windows_browser_candidates() if path.is_file()), None)


def _linux_browser_candidates() -> list[Path]:
    candidates = [
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/opt/google/chrome/chrome"),
        Path("/usr/bin/brave-browser"),
        Path("/opt/brave.com/brave/brave-browser"),
    ]
    home = Path.home()
    candidates.extend(
        (
            home / ".local/bin/chromium",
            home / ".local/bin/google-chrome",
            home / ".local/bin/brave-browser",
        )
    )
    return candidates


def _playwright_headless_shell_executable() -> str | None:
    """Locate the Playwright revision-matched headless shell for evidence.

    Playwright selects this binary itself when Chromium is launched headless
    without an explicit executable path.  The path is reported so an audit can
    distinguish that default from an owner-supplied full Chrome binary.
    """
    roots: list[Path] = []
    configured_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured_root and configured_root != "0":
        roots.append(Path(configured_root).expanduser())
    roots.extend((Path.home() / ".cache" / "ms-playwright", Path("/tmp/rec1-p1c-browsers")))
    for root in roots:
        if not root.is_dir():
            continue
        candidates = sorted(root.glob("chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"))
        if candidates:
            return str(candidates[-1].resolve())
    return None


def _playwright_full_browser_executable() -> str | None:
    roots: list[Path] = []
    configured_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if configured_root and configured_root != "0":
        roots.append(Path(configured_root).expanduser())
    roots.extend((Path.home() / ".cache" / "ms-playwright", Path("/tmp/rec1-p1c-browsers")))
    for root in roots:
        if not root.is_dir():
            continue
        candidates = sorted(root.glob("chromium-*/chrome-linux*/chrome"))
        if candidates:
            return str(candidates[-1].resolve())
    return None


def _discover_browser_executable() -> str | None:
    """Resolve a real Chromium-compatible executable without weakening the gate."""
    configured = os.environ.get("TIANXIA_BROWSER_EXECUTABLE")
    if configured:
        return configured
    if _is_windows():
        return _default_browser_executable()
    playwright_browser = _playwright_full_browser_executable()
    if playwright_browser:
        return playwright_browser
    for candidate in _linux_browser_candidates():
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    return _playwright_headless_shell_executable()


def _browser_runtime_descriptor(browser_executable: str | None) -> dict[str, Any]:
    requested = os.environ.get("TIANXIA_BROWSER_EXECUTABLE")
    if requested:
        candidate = Path(browser_executable).expanduser() if browser_executable else None
        resolved = str(candidate.resolve()) if candidate and candidate.is_file() and os.access(candidate, os.X_OK) else None
        return {
            "kind": "explicit_executable",
            "runtime_kind": "explicit_executable",
            "requested_executable": requested,
            "resolved_executable": resolved,
        }
    if browser_executable:
        return {
            "kind": "discovered_executable",
            "runtime_kind": "discovered_executable",
            "requested_executable": None,
            "resolved_executable": str(Path(browser_executable).expanduser().resolve()),
        }
    return {
        "kind": "playwright_default_headless_shell",
        "runtime_kind": "playwright_default_headless_shell",
        "requested_executable": None,
        "resolved_executable": _playwright_headless_shell_executable(),
    }


def _browser_failure_report(
    package: Path,
    consumer_root: Path,
    *,
    browser_runtime: dict[str, Any],
    error: BaseException,
    playwright_default_executable: str | None = None,
) -> dict[str, Any]:
    runtime = {
        **browser_runtime,
        "playwright_default_executable": playwright_default_executable,
        "launch_error_type": type(error).__name__,
        "launch_error": str(error),
        # Playwright puts the browser's complete stderr/stdout in its launch
        # exception text.  Keep it verbatim for an independent diagnosis.
        "launch_stderr": str(error),
    }
    return {
        "schema_version": "TianxiaFoundry.ExactBundledGMSourceConsumerReport.v1",
        "status": "GM_SCREEN_SOURCE_CONSUMER_FAILED",
        "package_path": str(package),
        "package_sha256": sha256_file(package) if package.is_file() else None,
        "consumer_root": str(consumer_root),
        "consumer_package_sha256": GM_SCREEN_SHA256,
        "browser_harness": {"engine": "Chromium/Playwright", "native_or_interactive_acceptance": "NOT_RUN"},
        "browser_runtime": runtime,
        "failure_reasons": ["BROWSER_LAUNCH_FAILED"],
        "console_or_page_errors": [],
        "legacy_full_execution_acceptance": "NOT_CLAIMED_DIAGNOSTIC_REQUIRES_COMBAT_SIDECARS",
    }


async def verify(package: Path, consumer_root: Path, *, browser_executable: str | None = None) -> dict[str, Any]:
    from playwright.async_api import async_playwright

    package = package.resolve(); consumer_root = consumer_root.resolve()
    errors: list[dict[str, str]] = []
    browser_runtime = _browser_runtime_descriptor(browser_executable)
    if browser_executable:
        executable = Path(browser_executable).expanduser()
        if not executable.is_file() or not os.access(executable, os.X_OK):
            error = FileNotFoundError(
                f"The explicitly supplied browser executable is missing or not executable: {browser_executable}"
            )
            return _browser_failure_report(
                package,
                consumer_root,
                browser_runtime=browser_runtime,
                error=error,
            )
    playwright_default_executable: str | None = None
    runtime_parent = APP_ROOT.parents[2] / ".rec1-p1cr3-browser-runtime"
    runtime_parent.mkdir(parents=True, exist_ok=True)
    runtime_dir = Path(tempfile.mkdtemp(prefix="run-", dir=runtime_parent))
    for child in ("home", "xdg-config", "xdg-cache", "tmp", "user-data"):
        (runtime_dir / child).mkdir(parents=True, exist_ok=True)
    previous_environment = {
        key: os.environ.get(key)
        for key in ("HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "TMPDIR", "PLAYWRIGHT_BROWSERS_PATH")
    }
    original_home = Path(previous_environment["HOME"] or Path.home()).expanduser()
    playwright_root = Path(
        previous_environment["PLAYWRIGHT_BROWSERS_PATH"]
        or (original_home / ".cache" / "ms-playwright")
    ).expanduser()
    os.environ.update({
        "HOME": str(runtime_dir / "home"),
        "XDG_CONFIG_HOME": str(runtime_dir / "xdg-config"),
        "XDG_CACHE_HOME": str(runtime_dir / "xdg-cache"),
        "TMPDIR": str(runtime_dir / "tmp"),
        "PLAYWRIGHT_BROWSERS_PATH": str(playwright_root),
    })
    try:
        async with async_playwright() as pw:
            playwright_default_executable = str(pw.chromium.executable_path)
            if browser_runtime.get("resolved_executable") is None and not browser_executable:
                browser_runtime["resolved_executable"] = playwright_default_executable
            launch_options: dict[str, Any] = {
                "headless": True,
                # These are the minimum host-runtime flags needed for an
                # unprivileged bounded Linux launch: the container has no
                # usable Chromium sandbox namespace or /dev/shm budget.
                "args": [
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            }
            if browser_executable:
                launch_options["executable_path"] = browser_executable
            try:
                browser = await pw.chromium.launch(**launch_options)
            except Exception as exc:
                return _browser_failure_report(
                    package,
                    consumer_root,
                    browser_runtime=browser_runtime,
                    error=exc,
                    playwright_default_executable=playwright_default_executable,
                )
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
    except Exception as exc:
        return _browser_failure_report(
            package,
            consumer_root,
            browser_runtime=browser_runtime,
            error=exc,
            playwright_default_executable=playwright_default_executable,
        )
    finally:
        for key, previous in previous_environment.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
        import shutil
        shutil.rmtree(runtime_dir, ignore_errors=True)
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
        "browser_runtime": {
            **browser_runtime,
            "playwright_default_executable": playwright_default_executable,
        },
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
    parser.add_argument("--browser", default=_discover_browser_executable())
    args = parser.parse_args()
    report = asyncio.run(verify(args.package, args.consumer_root, browser_executable=args.browser))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "GM_SCREEN_SOURCE_CONSUMER_VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
