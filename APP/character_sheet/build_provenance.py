"""Shared Factory/table sheet classification; never changes acquisition or combat state.

Pure acquisition instructions belong in build provenance. Mixed training rows
with ongoing benefits remain abilities; downtime designations remain reference
rules. Classification uses printed prose, never an ability ID.
"""
from copy import deepcopy
import re


ACQUISITION = re.compile(r"when you (?:first )?(?:gain|learn)\b|choose one .*talent.*(?:free|bonus)|gain .* for free", re.I)
RUNTIME = re.compile(r"action type:\s*(?:action|bonus action|reaction|multi-mode)|\b(?:while|whenever|on a hit|once per|until the|at the start|as an action|as a bonus action|augment|target|sense|attack rolls|damage|base AC|talent functions|measures)\b(?!:\s*Self)|\byou (?:can|know)\b", re.I)

# Positive, whole-prose contract: recognizing an acquisition trigger is not
# evidence that everything following it concerns only character creation.
# Keep unfamiliar grants/conditions visible until their complete grammar can
# be described here. In particular, do not grow a list of runtime keywords to
# try to prove the absence of ongoing rules.
PURE_ACQUISITION = re.compile(
    r"When you (?:first )?(?:gain|learn) [^,.;\n]+, (?:you )?"
    r"(?:choose one (?:[\w'’ -]+ )?talent and gain it for free|"
    r"gain proficiency in (?:one|a) (?:skill|tool|weapon)(?: of your choice)?)"
    r"\.?(?: You must meet the talent['’]s prerequisites\.)?", re.I)


def pure_acquisition(text):
    """Recognize complete simple grants; any unconsumed prose is ambiguous.

    Headings and passive self/no-cost headers describe the card, not extra
    rules. Every other field or sentence must match the acquisition contract.
    This display helper neither resolves grants nor modifies owned records.
    """
    body = re.sub(r"(?m)^[ \t]*#{1,6}[ \t]+[^\n]*(?:\n|$)", "", text)
    body = re.sub(
        r"(?im)^[ \t]*(?:Action Type:[ \t]*Passive|Range:[ \t]*Self|"
        r"Target:[ \t]*Self|Cost:[ \t]*0)[ \t]*(?:\n|$)", "", body)
    return PURE_ACQUISITION.fullmatch(" ".join(body.split())) is not None


def component_purpose(row):
    """Return build, reference, or ability. Ambiguous/mixed prose stays an ability."""
    text = str(row.get("player_rules_text") or row.get("full_description") or "")
    if re.search(r"\bdesignation\b", str(row.get("display_name") or ""), re.I) and re.search(r"long rest|spending \d+ minutes", text, re.I) and not re.search(r"action type:\s*(?:action|bonus action|reaction)", text, re.I):
        return "reference"
    if RUNTIME.search(text):
        return "ability"
    if ACQUISITION.search(text) and pure_acquisition(text):
        return "build"
    return "ability"


def effective_component_rules(row, receipt):
    """Use current display prose; receipts fill only unauthenticated empty cards.

    A short rule is still a rule. Only missing text, a known title, or card
    headers without a rules body establish incompleteness; length does not.
    Source-labelled/authenticated and owner-edited rows always take precedence.
    """
    text = str(row.get("full_description") or "").strip()
    if row.get("full_description_source") or row.get("rules_text_source_locator"):
        return row
    receipt_text = str(receipt.get("player_rules_text") or "").strip()
    titles = {str(row.get("display_name") or "").strip().lstrip("# ")}
    titles.update(line.strip().lstrip("# ") for line in receipt_text.splitlines()
                  if line.lstrip().startswith("#"))
    body = [line.strip() for line in text.splitlines() if line.strip()]
    incomplete = all(line.lstrip("# ") in titles or re.fullmatch(
        r"(?:Action Type|Range|Target|Cost|Duration):\s*[^\n]+", line, re.I)
        for line in body)
    if receipt_text and incomplete and receipt_text != text:
        display = deepcopy(row)
        display["full_description"] = receipt_text
        return display
    return row


def present_build_provenance(snapshot):
    """Copy only when needed; retain source rows and all signed identities unchanged.

    Acquisitions are already resolved by the Stage 2 causal grant pipeline. This
    display projection keeps their instructions inspectable without claiming the
    instruction itself is an owned ability. Missing choices are QA findings,
    never manufactured here. Repeated application is idempotent.
    """
    if not isinstance(snapshot, dict):
        return snapshot
    rows = (snapshot.get("selected_record_sections") or {}).get("sphere_automatic_components") or []
    components = {r.get("component_id"): r for r in (snapshot.get("spheres_and_talents") or {}).get("automatic_sphere_components") or []}
    moved, references, kept = [], [], []
    for row in rows:
        display = effective_component_rules(row, components.get(row.get("record_id")) or {})
        # Display prose has already passed through the owner/current-rules
        # overlay. Do not classify a stale player_rules_text acquisition receipt.
        purpose = component_purpose({**display, "player_rules_text": display.get("full_description")})
        if purpose == "ability":
            kept.append(display)
            continue
        (moved if purpose == "build" else references).append(deepcopy(display))
    if not moved and not references and kept == rows:
        return snapshot
    out = deepcopy(snapshot)
    out["selected_record_sections"]["sphere_automatic_components"] = deepcopy(kept)
    if moved:
        out.setdefault("build_provenance", {})["grant_instructions"] = moved
    if references:
        out["selected_record_sections"].setdefault("equipment_reference", []).extend(references)
    return out
