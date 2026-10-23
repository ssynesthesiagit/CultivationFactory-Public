"""Read-only, repeatable portable-sheet QA using the production table library.

Input: a directory of copied packages (*.zip) or extracted character folders
containing Tianxia_Owner_Character_Sheet_v1.json and Character_Master_Ledger.json.
No live database, model, service, or browser is needed. Findings are review
candidates, not permission to repair a character. See --help for browser mode.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import zipfile

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
from character_sheet.build_provenance import ACQUISITION, component_purpose

SHEET = "Tianxia_Owner_Character_Sheet_v1.json"
LEDGER = "Character_Master_Ledger.json"
AUTHORING = re.compile(r"Factory (?:Routing|Combat Bucket|Realization)|Canonical Action Type:|Split (?:Review|Candidate)|source_record|NOT_IMPLEMENTED|\b(?:TAL_[A-Z0-9_]+|[A-Z]+_BASE_[A-Z0-9_]+|tianxia\.[a-z_]+\.[\w.]+)\b")
MARKDOWN = re.compile(r"(?m)^#{1,6}\s|\*\*|```|\[[^]]+\]\([^)]+\)")


def additional_grant_findings(sheet):
    """Source-scoped review pointers for grants beyond the standard free Talent.

    Conditional proficiency alternatives need the original pre-acquisition state;
    portable ownership alone cannot prove them missing or legally select a repair.
    """
    findings = []
    for row in (sheet.get("spheres_and_talents") or {}).get("automatic_sphere_components") or []:
        text = row.get("player_rules_text") or ""
        if ACQUISITION.search(text) and re.search(r"gain proficiency|choose one [^.\n]*(?:skill|package|pattern)|gain [^.\n]*kit|learn [^.\n]*formula", text, re.I):
            findings.append({"code": "additional_build_grant_review", "record_id": row.get("component_id"),
                "evidence": "This acquisition also grants a proficiency, package, pattern, formula or item. Standard free-Talent ownership does not verify that separate grant.",
                "proposal": "Inspect the original acquisition choice and pre-acquisition proficiencies, then compare the selected benefit/item with the ledger. Propose a legal concrete choice only if missing; rebuild through the verified builder after individual review."})
    return findings


def table_library(sheet):
    """The same compiler, automatic buttons, owner overlay and library as sheet().

    No custom button/owner-item overrides are invented. Those optional live
    settings need a separate export; this audit covers portable-owned abilities.
    """
    from character_sheet.current_rules import overlay_owner_current_rules
    from factory_authoring.owner_text_edits import apply_edit
    from combat.factory_compiler import compile_character
    from combat.tabletop import auto_buttons, sheet_library, sheet_summary
    edits = json.loads((APP / "authority/typed_mechanics/owner_text_edits.json").read_text()).get("records") or {}
    display = overlay_owner_current_rules(sheet, edits=edits, apply_owner_edit=apply_edit,
        authenticated_rules_block=lambda _s, _r: ("", ""), factory_root=lambda: None)
    bundle = compile_character(display, actor_id="sheetqa:character")
    buttons = auto_buttons(bundle, sheet_summary(display))
    automated = {r.get("feature_id") for key in ("typed_passives", "typed_reactions") for r in bundle.get(key) or []}
    automated |= {r["id"] for r in bundle.get("modifiers") or [] if r.get("status") == "applied"}
    boundaries = {r["id"]: r for r in (bundle.get("diagnostics") or {}).get("insights") or []}
    library = sheet_library(display, buttons, automated, boundaries)
    from combat.action_text import layout_action
    for _, item in library_entries(library):
        item["hover"] = layout_action({"label": item.get("name"),
            "parameters": {"description": item.get("text") or item.get("summary") or ""}})
    rendered = subprocess.run(["node", str(APP / "tools/sheet_qa_render.mjs")],
        input=json.dumps(library), text=True, capture_output=True, check=True)
    library = json.loads(rendered.stdout)
    library["qa_compile_sha256"] = hashlib.sha256(json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return display, library


def library_entries(library):
    for group in library.get("groups") or []:
        for row in group.get("entries") or []:
            yield group["key"], row
        for sphere in group.get("spheres") or []:
            yield group["key"], sphere
            for row in sphere.get("entries") or []:
                yield group["key"], row


def audit_character(sheet, ledger, library, *, display=None):
    """Audit effective presentation separately from historical causal receipts.

    Join current display cards by record ID, not automatic-component receipts:
    the owner overlay deliberately preserves those receipts. Direct library
    callers without a display snapshot use the actual visible rules instead.
    """
    findings = additional_grant_findings(sheet)
    def flag(code, record, evidence, proposal=None, lane=None):
        findings.append({"code": code, "record_id": record, "evidence": evidence,
                         **({"proposal": proposal} if proposal else {}), **({"lane": lane} if lane else {})})
    visible = {r.get("id"): r for _, r in library_entries(library)}
    current_rows = {r.get("record_id"): r
                    for rows in ((display or {}).get("selected_record_sections") or {}).values()
                    for r in rows if isinstance(r, dict)}
    owned = set((sheet.get("spheres_and_talents") or {}).get("learned_talent_record_ids") or [])
    owned.add((sheet.get("spheres_and_talents") or {}).get("background_talent_record_id"))
    components = (sheet.get("spheres_and_talents") or {}).get("automatic_sphere_components") or []
    for component in components:
        rid = component.get("component_id")
        if rid not in visible:
            continue
        row = current_rows.get(rid)
        text = row.get("full_description") if row is not None else visible[rid].get("text")
        purpose = component_purpose({"display_name": row.get("display_name") if row is not None else visible[rid].get("name"),
                                     "full_description": text})
        if purpose == "build":
            flag("build_instruction_as_ability", rid, text)
        if purpose in {"build", "reference"} and visible[rid].get("status") == "gm":
            flag("misleading_not_automated_badge", rid, visible[rid].get("name"))
        if ACQUISITION.search(text or "") and purpose == "ability":
            flag("mixed_grant_requires_review", rid, "Acquisition prose shares a row with ongoing rules; preserve the ongoing ability.")
    # Verify the exact granted choice, not merely any Talent from the Sphere.
    sphere_names = {r.get("sphere_id"): r.get("name") for r in ledger.get("spheres") or []}
    for sphere in ledger.get("spheres") or []:
        sid = sphere.get("sphere_id")
        grant_type = "background_talent" if sphere.get("acquisition_type") == "background_sphere" else "new_sphere_bonus"
        candidates = [r for r in ledger.get("talents") or [] if r.get("sphere") == sphere_names.get(sid)
                      and r.get("gained_at_cl") == sphere.get("gained_at_cl")
                      and r.get("acquisition_type") == grant_type]
        if not candidates:
            flag("unresolved_free_talent", sid, "No causal same-Sphere free Talent receipt at acquisition CL.",
                 "Review original acquisition choices and prerequisites; propose one legal free Talent, then rebuild through the verified builder. Do not append to the sheet.")
        for choice in candidates:
            if choice.get("talent_id") not in owned or choice.get("talent_id") not in visible:
                flag("granted_talent_missing", choice.get("talent_id"), "Recorded free Talent is absent from the owned IDs or displayed library.",
                     "Restore this recorded choice through the verified builder after checking the original source receipt.")
    seen = {}
    for section, row in library_entries(library):
        text = "\n".join(str(row.get(k) or "") for k in ("name", "summary", "text", "automation", "tooltip"))
        for code, pattern in (("raw_id_or_authoring_text", AUTHORING), ("raw_markdown", MARKDOWN)):
            # Full rules deliberately contain Markdown parsed by rulesText();
            # names and collapsed summaries are rendered as plain text.
            inspected = text if code != "raw_markdown" else str(row.get("name") or "") + "\n" + str(row.get("summary") or "")
            match = pattern.search(inspected)
            if match:
                flag(code, row.get("id"), match.group(0))
        normalized = re.sub(r"\s+", " ", str(row.get("text") or "")).strip().lower()
        if len(normalized) > 80 and normalized in seen and seen[normalized] != row.get("id"):
            flag("duplicate_rules_text", row.get("id"), f"Same displayed rules as {seen[normalized]}")
        seen[normalized] = row.get("id")
    for occurrence in (sheet.get("spheres_and_talents") or {}).get("cultivation_insight_occurrences") or []:
        if occurrence.get("insight_id") not in visible:
            flag("acquired_insight_missing", occurrence.get("insight_id"), "Acquired Insight omitted from library.", lane="SOL186")
    for level in (sheet.get("advancement_history") or {}).get("levels") or []:
        milestones = [f for f in level.get("earned_feature_occurrences") or []
                      if str(f.get("feature_id") or "").endswith("ability_score_improvement_or_cultivation_insight")]
        # Multi-Path sheets also list unselected Path milestone occurrences.
        # A resolved choice at this character CL satisfies the actual milestone.
        if milestones and not any(f.get("selection") for f in milestones):
            flag("unresolved_advancement_choice", milestones[0].get("feature_id"), f"CL {level.get('cl')}", lane="SOL186/SOL188")
    return findings


def screenshot_sections(page, output):
    """Opt-in only: screenshot actual rendered table sheet sections from a lead URL."""
    page.locator("#stats").wait_for()
    output.mkdir(parents=True, exist_ok=True)
    for i, section in enumerate(page.locator("main section").all()):
        if section.is_visible():
            section.screenshot(path=str(output / f"overview-{i:02}.png"))
    for tab in ("actions", "features", "items", "grow"):
        page.locator(f"#tab-{tab}").click()
        page.locator(f"#panel-{tab}").screenshot(path=str(output / f"{tab}.png"))
    page.locator("#tab-library").click()
    page.locator("#lib-list").wait_for()
    sections = page.locator("#lib-list section.lib-group")
    if sections.count() == 0:
        raise RuntimeError("No sheet sections found; inspect the live sheet DOM selector.")
    for toggle in page.locator("#lib-list .lib-toggle[aria-expanded=false]").all():
        toggle.click()
    for i in range(sections.count()):
        sections.nth(i).screenshot(path=str(output / f"section-{i:02}.png"))


def browser_capture(url_template, reports, output):
    if os.environ.get("SHEETQA_BROWSER") != "1":
        return "SKIPPED: lead must run with SHEETQA_BROWSER=1 outside sandbox"
    if not url_template or "{character_id}" not in url_template:
        raise ValueError("Browser mode requires --browser-url with {character_id}; use the actual sheet URL, not a synthetic page.")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"])
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            for report in reports:
                page.goto(url_template.format(character_id=report["character_id"]))
                screenshot_sections(page, output / report["character_id"])
        finally:
            browser.close()
    return "CAPTURED"


def write_reports(reports, output, browser):
    """Write the review artifacts; also used to consolidate targeted rechecks."""
    output.mkdir(parents=True, exist_ok=True)
    totals = Counter(f["code"] for r in reports for f in r["findings"])
    result = {"characters": len(reports), "counts": dict(sorted(totals.items())), "browser": browser,
              "cross_links": {"SOL186": "Insights acquisition/eligibility; legal ASIs are not missing Insights", "SOL188": "Ability-increase arithmetic and expected scores"}, "reports": reports}
    (output / "sheet-qa.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# Sheet QA", "", browser, "", "Portable-owned abilities use the production compiler and actual in-process table card renderer. Optional live owner items/custom button overrides are not included. Findings require review; no repairs applied.", "", "SOL186: acquired Insights and milestone resolution. SOL188: ability-increase arithmetic. This tool does not duplicate those lanes or assume every milestone must grant an Insight.", "", "| Character | ID | Findings |", "|---|---|---:|"]
    lines += [f"| {r['name']} | {r['character_id']} | {len(r['findings'])} |" for r in reports]
    for r in reports:
        lines += ["", f"## {r['name']} ({r['character_id']})"]
        lines += [f"- {f['code']}: {f.get('record_id', '')} — {str(f['evidence']).replace(chr(10), ' ')}" + (f" Proposal only: {f['proposal']}" if f.get('proposal') else "") for f in r["findings"]]
    (output / "sheet-qa.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"characters": len(reports), "counts": dict(totals), "browser": browser}))
    return result


def main(argv=None, *, render_sheet=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--browser-url", help="Lead-only actual sheet URL containing {character_id}; SHEETQA_BROWSER=1 required")
    parser.add_argument("--character-id", action="append", help="Audit only these copied character IDs (repeatable)")
    args = parser.parse_args(argv)
    paths = sorted(args.input.glob(f"*/{SHEET}")) + sorted(args.input.glob("*.zip")) + sorted(args.input.glob("*/current.zip"))
    if args.character_id:
        paths = [p for p in paths if (p.parent.name if p.name in {SHEET, 'current.zip'} else p.stem) in args.character_id]
    reports = []
    for path in paths:
        library = {}
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as archive:
                sheet = json.loads(archive.read(SHEET)); ledger = json.loads(archive.read(LEDGER))
        else:
            sheet = json.loads(path.read_text()); ledger = json.loads((path.parent / LEDGER).read_text())
        cid = path.parent.name if path.name in {SHEET, "current.zip"} else path.stem
        try:
            display, library = (render_sheet or table_library)(sheet)
            findings = audit_character(sheet, ledger, library, display=display)
        except Exception as exc:
            findings = [{"code": "render_error", "evidence": f"{type(exc).__name__}: {exc}"}]
        reports.append({"character_id": cid, "name": sheet.get("identity", {}).get("display_name"),
                        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "findings": findings,
                        "compiled_bundle_sha256": library.get("qa_compile_sha256")})
        print(f"Audited {len(reports)}/{len(paths)}: {len(findings)} findings", flush=True)
    if not reports:
        parser.error("No copied portable sheets found")
    args.output.mkdir(parents=True, exist_ok=True)
    browser = browser_capture(args.browser_url, reports, args.output / "screenshots")
    result = write_reports(reports, args.output, browser)
    return 1 if result["counts"].get("render_error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
