"""Compact ability-card digests of the owner's printed rules (owner 2026-10-08, SOL192).

Owner: "most abilities on here are very wordy, we could probably do a rewrite of the tooltips that are more easy to
digest and keep all the important info". A digest is a deterministic re-arrangement of the owner's own words:

  - ``facts``: the printed header fields (action, range, area, target, duration, cost, save, trigger, limit);
  - ``summary``: the first printed sentence (every sentence is kept; only provably cosmetic lines fold);
  - ``outcomes``: "Failed save / Successful save / On a hit / On a miss" lines;
  - ``groups``: a printed list ("While a creature is Challenged by you:" + its items) kept together;
  - ``rules``: every other printed sentence, verbatim;
  - ``conditions``: standard conditions the effect names, explained in a few words (combat/condition_text.py);
  Every printed sentence is on the card, in the owner's words (lead decision 2026-10-08: correctness over
  compactness). Compactness comes only from structure: "Label: value" header lines become the facts row, headings
  become section titles, and printed lists stay grouped. The only lines left out are internal authoring fields.

No word is invented and none is rewritten, so a summary cannot change a mechanic; the complete printed text always
stays one click away ("Full rules"). Nothing runs a model.

Digests are hash-keyed to the owner text. ``tools/build_tooltip_digests.py`` writes
``authority/typed_mechanics/tooltip_digests.json`` with each record's sha256; at runtime :func:`digest_for` serves a
digest only while ``rules_text.json`` still hashes the same, and otherwise answers ``{"status": "pending"}`` so the
card shows "Summary pending" and the full text, never a stale summary. Presentation only: no fight state is read or
written.
"""
from __future__ import annotations

import functools
import hashlib
import json
import re
from pathlib import Path
from typing import Any

APP = Path(__file__).resolve().parents[1]
DIGESTS_PATH = APP / "authority/typed_mechanics/tooltip_digests.json"
SCHEMA = "TianxiaTooltipDigest.v1"

# Printed header labels -> the card's fact name. Prerequisite/Tags are build data, not use data: Full rules only.
FACT_LABELS = {
    "action type": "Action", "activation": "Action", "action": "Action", "casting time": "Action", "type": "Action",
    "range": "Range", "area": "Area", "origin": "Origin", "target": "Target", "targets": "Target",
    "duration": "Duration", "cost": "Cost", "save": "Save", "saving throw": "Save", "attack": "Attack",
    "trigger": "Trigger", "use limit": "Limit", "limit": "Limit", "frequency": "Limit",
    "requirement": "Needs", "requirements": "Needs", "time": "Time",
}
# Build/metadata header labels: shown as facts too (every printed line is on the card), after the use facts.
META_LABELS = {"prerequisite": "Prerequisite", "prerequisites": "Prerequisite", "tags": "Tags", "tag": "Tags",
               "talent type": "Type"}
ECONOMY_LINES = {"action": "Action", "bonus action": "Bonus Action", "reaction": "Reaction", "no action": "No action",
                 "free action": "Free action"}
OUTCOMES = [
    (re.compile(r"^(?:on an? )?failed (?:saving throw|save)\s*[:,]\s*(.*)$", re.I), "Failed save"),
    (re.compile(r"^(?:on an? )?(?:successful|success(?:ful)? on the) (?:saving throw|save)\s*[:,]\s*(.*)$", re.I), "Successful save"),
    (re.compile(r"^on a success\s*[:,]\s*(.*)$", re.I), "On a success"),
    (re.compile(r"^on a (?:failure|fail)\s*[:,]\s*(.*)$", re.I), "On a failure"),
    (re.compile(r"^(?:on an? )?hit\s*[:,]\s*(.*)$", re.I), "On a hit"),
    (re.compile(r"^(?:on an? )?miss\s*[:,]\s*(.*)$", re.I), "On a miss"),
]
TRIGGER = re.compile(r"^you can use this when\s+(.*?)\.?$", re.I)
SAVE_LINE = re.compile(r"^(?:the target|the creature|the triggering creature|each creature|each target|creatures inside|"
                       r"creatures in the area|it)\s+makes?\s+(?:a|an)?\s*(strength|dexterity|constitution|intelligence|"
                       r"wisdom|charisma)\s+saving throws?\.?$", re.I)
# Internal authoring fields, never player text (the same lines rules.js cleanRules() strips).
AUTHORING = re.compile(r"^\W*(?:Factory [\w -]+|Recommended Factory Realization|Split Review Decision|"
                       r"Split Candidate Buckets|Typing Status|Structure Source)\W*:", re.I)
CONDITION_NAMES = ["Blinded", "Charmed", "Deafened", "Frightened", "Grappled", "Incapacitated", "Invisible", "Paralyzed",
                   "Petrified", "Poisoned", "Prone", "Restrained", "Stunned", "Unconscious"]


def text_sha(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def _clean(line: str) -> str:
    line = re.sub(r"\*\*|__|`", "", str(line)).replace(" ", " ")
    return " ".join(line.split()).strip()


def _heading_name(text: str) -> str:
    name = re.sub(r"^\s*(?:core ability|base ability|ability)\s*:\s*", "", text, flags=re.I)
    name = re.sub(r"^\s*CL\s*\d+\s*[-\u2013\u2014:]\s*", "", name)
    name = re.sub(r"\s*[-–—]\s*(?:unique\s+)?[\w' -]*?\b(?:talent|meld|augment|ability)\s*$", "", name, flags=re.I)
    return name.strip()


def norm_name(text: str) -> str:
    text = re.sub(r"\s*\([^)]*\)\s*$", "", str(text or ""))
    text = re.sub(r"\s*\((?:Concentration|Persistent)\)$", "", text)
    return " ".join(re.sub(r"[^\w' ]+", " ", text).split()).casefold()


def _sections(text: str) -> list[tuple[str, int, list[str]]]:
    """(name, heading level, body lines) for each printed section; a record without headings is one section."""
    out: list[tuple[str, int, list[str]]] = []
    name, level, body = "", 0, []
    for raw in str(text or "").split("\n"):
        heading = re.match(r"^\s*(#{1,6})\s+(.*)$", raw)
        if heading:
            if name or any(line.strip() for line in body):
                out.append((name, level, body))
            name, level, body = _heading_name(_clean(heading[2])), len(heading[1]), []
        elif raw.strip() and not re.match(r"^\s*-{3,}\s*$", raw):
            body.append(raw)
    if name or any(line.strip() for line in body):
        out.append((name, level, body))
    return out


def _table(rows: list[str]) -> str:
    cells = [[cell.strip() for cell in row.strip().strip("|").split("|")] for row in rows]
    cells = [row for row in cells if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in row if cell)]
    if len(cells) < 2:
        return "; ".join(" ".join(row) for row in cells)
    head, body = cells[0], cells[1:]
    if len(head) == 2:
        return f"{head[1]} by {head[0]}: " + "; ".join(f"{row[0]}: {row[1]}" for row in body if len(row) >= 2)
    return "; ".join(", ".join(f"{h}: {v}" for h, v in zip(head, row)) for row in body)


def digest_section(name: str, lines: list[str]) -> dict[str, Any]:
    facts: list[list[str]] = []
    outcomes: list[list[str]] = []
    groups: list[dict[str, Any]] = []
    rules: list[str] = []
    summary = ""
    i = 0
    cleaned = [line for line in lines]

    lossy: list[str] = []
    ordered: list[list[str]] = []  # the body in PRINTED order: ["text", "", line] / ["outcome", label, value]
    header_body = [0]  # body size when the last header fact was printed
    events: list[tuple[str, str]] = []  # ("proc" | "outcome" | "prose", line), in printed order
    use_facts: list[str] = []  # use facts (not Prerequisite/Tags/Type) printed so far
    prose: list[str] = []  # body sentences; a printed "Label: value" line (Timing Detail: ...) is header, not body

    def add_fact(label: str, value: str, *, sentence_kept: bool = False) -> None:
        """One header fact. The facts row can only show ONE value per label for the whole ability: a label printed
        twice with different values (six response Triggers, a 150 gp and a 3 CP Cost) or a fact printed after the
        body started (it belongs to one option or step) cannot be shown losslessly there, so the section is marked
        lossy and served as the complete rules, open (lead decision, SOL192r3)."""
        value = value.strip().rstrip(".") if label != "Trigger" else value.strip()
        if not value:
            return
        if any(existing == label and other != value for existing, other in facts):
            lossy.append(f"repeated {label}")
        # The header is ONE block of facts (an intro line or quote before it is fine). A fact printed after the
        # header block was followed by body text belongs to one option or step: scoped.
        body = len(prose) + len(outcomes) + len(groups)
        if not sentence_kept and label not in META_LABELS.values():
            if use_facts and body > header_body[0]:
                lossy.append(f"scoped {label}")
            header_body[0] = body
            use_facts.append(label)
        if [label, value] not in facts:
            facts.append([label, value])

    def take_list(start: int) -> tuple[list[str], int]:
        """Items under a printed "...:" line: bullets, or lines while the previous item ended with ';'."""
        items: list[str] = []
        j = start
        while j < len(cleaned):
            raw = cleaned[j]
            line = _clean(raw)
            bullet = re.match(r"^\s*(?:[-*•]|\d+\.)\s+(.*)$", raw)
            if bullet:
                items.append(_clean(bullet[1]))
            elif not items or items[-1].endswith(";") or (line[:1].islower()):
                if re.match(r"^[A-Z][\w ]{0,24}:\s", line) and items:
                    break
                if any(rx.match(line) for rx, _ in OUTCOMES) or TRIGGER.match(line):
                    break
                items.append(line)
            else:
                break
            j += 1
        return items, j

    while i < len(cleaned):
        raw = cleaned[i]
        line = _clean(raw)
        i += 1
        if not line or AUTHORING.match(line):
            continue
        if line.startswith("|"):
            rows = [raw]
            while i < len(cleaned) and _clean(cleaned[i]).startswith("|"):
                rows.append(cleaned[i]); i += 1
            rules.append(_table(rows))
            continue
        is_outcome = any(rx.match(line) for rx, _ in OUTCOMES)
        if is_outcome:
            events.append(("outcome", line))
        elif PROC_SAVE.search(line) or PROC_ATTACK.search(line):
            events.append(("proc", line))
        elif not re.match(r"^[A-Z][A-Za-z ]{0,30}:\s*\S", line) and not (len(line.split()) <= 3 and not line.endswith(".")):
            events.append(("prose", line))
        low = line.rstrip(".").casefold()
        if low in ECONOMY_LINES:
            add_fact("Action", ECONOMY_LINES[low]); continue
        field = re.match(r"^([A-Za-z][A-Za-z ]{0,22}?)\s*:\s*(.*)$", line)
        if field and field[1].strip().casefold() in META_LABELS and field[2].strip():
            add_fact(META_LABELS[field[1].strip().casefold()], field[2].strip()); continue
        if field and field[1].strip().casefold() in FACT_LABELS and field[2].strip():
            label = FACT_LABELS[field[1].strip().casefold()]
            value = field[2].strip()
            add_fact(label, value); continue
        trigger = TRIGGER.match(line)
        if trigger:
            add_fact("Trigger", trigger[1][:1].upper() + trigger[1][1:]); continue
        save = SAVE_LINE.match(line)
        if save:
            add_fact("Save", save[1].capitalize(), sentence_kept=True)  # the sentence itself stays too
        outcome = next(((label, m) for rx, label in OUTCOMES if (m := rx.match(line))), None)
        if outcome:
            label, match = outcome
            value = match[1].strip()
            if not value:
                items, i = take_list(i)
                value = "; ".join(item.rstrip(";.") for item in items) + ("." if items else "")
            # The compact card shows the result's trigger exactly as printed ("On a failed save,", "Hit:").
            outcomes.append([label, value]); ordered.append(["outcome", line[:match.start(1)].strip(), value]); continue
        if line.endswith(":") and i < len(cleaned):
            items, j = take_list(i)
            if items:
                i = j
                group = {"lead": line, "items": items}
                if not summary and not outcomes and not line.casefold().startswith("while "):
                    summary = line
                    group["lead"] = ""
                groups.append(group)
                continue
        # Every other printed sentence is kept, whatever its wording: no sentence is ever classified away.
        # The summary is the first printed line BEFORE any outcome; a line after the outcomes is a rule.
        # A "Label: value" line or a bare word or two ("Ritual") is header material, not body prose.
        if not re.match(r"^[A-Z][A-Za-z ]{0,30}:\s*\S", line) and not (len(line.split()) <= 3 and not line.endswith(".")):
            prose.append(line)
        ordered.append(["text", "", line])
        if not summary and not outcomes:
            summary = line; continue
        rules.append(line)

    outcomes = [[label, value[:1].upper() + value[1:]] for label, value in outcomes]
    # Conditions the ability APPLIES: named in an outcome, or after "becomes / knocked / falls / is" elsewhere.
    # A condition it only protects against ("Advantage on saves against Prone") is not explained.
    applied = " ".join(v for _, v in outcomes)
    other = " ".join([summary, *rules, *[" ".join([g["lead"], *g["items"]]) for g in groups]])
    conditions = [c for c in CONDITION_NAMES if re.search(rf"^\s*{c}\b|\b(?:becomes?|knock(?:ed|s)?|falls?|is|are|be)\s+(?:\w+\s+){{0,2}}{c}\b", applied)
                  or re.search(rf"\b(?:becomes?|knock(?:ed|s)?|falls?|is|are|be)\s+(?:\w+\s+){{0,2}}{c}\b", other)]
    lossy.extend(procedure_problems(events, header_procedure=any(label in ("Save", "Attack") for label, _ in facts
                                                                    if label in use_facts)))
    lossy.extend(allowlist_problems(lines))
    content = bool(summary or outcomes or rules or groups)
    status = "full" if content and facts else "partial" if content else "empty"
    if lossy:
        status = "open"
    # A compact card renders `ordered` (printed order, SOL192r7): no result can move ahead of the sentence that
    # names who rolls and when. Kept only for allowlisted (non-open) sections.
    out = {"name": name, "summary": summary, "facts": facts, "outcomes": outcomes, "groups": groups,
           "ordered": ordered if not lossy else [],
           "rules": rules, "conditions": conditions, "status": status, "lossy": sorted(set(lossy))}
    # Compact on disk: empty fields are omitted (readers default them).
    return {key: value for key, value in out.items() if value or key in {"name", "status"}}


# A save or attack PROCEDURE: the sentence that asks for the roll. "repeats the saving throw" and "Advantage on
# saving throws" are not new procedures.
PROC_SAVE = re.compile(r"\bmakes?\b[^.;]*\bsaving throws?\b|\bmust succeed on\b[^.;]*\bsaving throw\b", re.I)
PROC_ATTACK = re.compile(r"\bmake (?:a|an|one)\b[^.;]*\battack(?: roll)?\b", re.I)
SCOPED_START = re.compile(r"^(?:if|when|whenever|at the (?:start|end)|once|while|after|before|each time|the first time|"
                          r"on (?:a|an|your|each|its)|until|instead|alternatively|or)\b", re.I)


def procedure_problems(events: list[tuple[str, str]], *, header_procedure: bool) -> list[str]:
    """Why a section's save/attack procedures cannot sit in one compact card (lead decision, SOL192r4).

    A compact card is allowed only for exactly ONE save/attack procedure that applies to the whole ability, with its
    results printed right after it. Anything else -- a procedure scoped to an option, condition, mode or later
    clause ("If the target is Unclean, it makes...", "At the start of each of your turns ... makes"), several
    procedures, results separated from the sentence that asks for the roll, or results with no procedure at all --
    is served as the complete rules, open, with no save chip.
    """
    problems = []
    procs = [line for kind, line in events if kind == "proc"]
    if any(SCOPED_START.match(line) for line in procs):
        problems.append("scoped procedure")
    kinds = {("save", m[0].casefold()) for line in procs for m in [re.search(
        r"strength|dexterity|constitution|intelligence|wisdom|charisma", line, re.I)] if m and PROC_SAVE.search(line)}
    kinds |= {("attack", "")} if any(PROC_ATTACK.search(line) for line in procs) else set()
    if len(procs) > 1 and len(kinds) > 1 or len(procs) > 2:
        problems.append("several procedures")
    outcomes = [i for i, (kind, _) in enumerate(events) if kind == "outcome"]
    if outcomes:
        if not procs and not header_procedure:
            problems.append("results without a procedure")
        last_proc = max((i for i, (kind, _) in enumerate(events) if kind == "proc" and i < outcomes[0]), default=None)
        if last_proc is not None and any(kind == "prose" for kind, _ in events[last_proc + 1:outcomes[0]]):
            problems.append("results separated from their procedure")
        if any(events[i][0] != "outcome" for i in range(outcomes[0], outcomes[-1] + 1)):
            problems.append("split result blocks")
        if any(kind == "proc" for kind, _ in events[outcomes[-1] + 1:]):
            problems.append("procedure after results")
    return problems


PROSE_END = re.compile(r"[.!?)\u201d\"]$")
SAVE_OR_ATTACK = re.compile(r"saving throws?|\bmakes? (?:a|an|one)\b[^.]*\battack|\bcultivation attack\b", re.I)


def allowlist_problems(lines: list[str]) -> list[str]:
    """The ALLOWLIST for a compact card (lead decision, SOL192r5). Anything not provably simple is served open.

    After the header facts, the body must be plain prose sentences with at most one whole-ability save/attack, its
    results in one contiguous block directly after it, no list or group leads, no option/outcome sub-headings, no
    "Label: value" lines in the body, no tables, and no scoped clause (If / When / At the start / On a ...) anywhere
    in the body. Prefer a false "open" to any false "compact".
    """
    kinds: list[tuple[str, str]] = []
    for raw in lines:
        line = _clean(raw)
        if not line or AUTHORING.match(line):
            continue
        field = re.match(r"^([A-Za-z][A-Za-z ]{0,22}?)\s*:\s*(.*)$", line)
        key = field[1].strip().casefold() if field else ""
        if line.rstrip(".").casefold() in ECONOMY_LINES or (field and field[2].strip() and (key in FACT_LABELS or key in META_LABELS)):
            kinds.append(("header", line))
        elif TRIGGER.match(line):
            kinds.append(("header", line))
        elif any(rx.match(line) for rx, _ in OUTCOMES):
            kinds.append(("outcome", line))
        else:
            kinds.append(("body", line))
    problems = []
    body_started = False
    for kind, line in kinds:
        if kind == "header" and body_started:
            problems.append("allowlist: header fact inside the body")
        if kind != "header":
            body_started = True
    body = [(kind, line) for kind, line in kinds if kind != "header"]
    for kind, line in body:
        if kind == "outcome":
            if re.search(r":\s*$", line):
                problems.append("allowlist: result followed by a list")
            continue
        if line.startswith("|") or re.match(r"^\s*(?:[-*\u2022]|\d+\.)\s", line) or line.endswith(":"):
            problems.append("allowlist: list, group or table")
        elif re.match(r"^[A-Za-z][A-Za-z ,'()-]{0,40}:\s", line):
            problems.append("allowlist: labelled body line")
        elif not PROSE_END.search(line):
            problems.append("allowlist: not a plain sentence")
        if SCOPED_START.match(line):
            problems.append("allowlist: scoped clause")
    procs = [i for i, (kind, line) in enumerate(body) if kind == "body" and SAVE_OR_ATTACK.search(line)]
    results = [i for i, (kind, _) in enumerate(body) if kind == "outcome"]
    if len(procs) > 1:
        problems.append("allowlist: more than one save/attack")
    if results:
        if not procs or procs[0] != results[0] - 1:
            problems.append("allowlist: results not directly after their save/attack")
        if results != list(range(results[0], results[-1] + 1)):
            problems.append("allowlist: results not contiguous")
    return problems


def digest_text(text: str) -> list[dict[str, Any]]:
    out = []
    for name, level, body in _sections(text):
        digest = digest_section(name, body)
        digest["level"] = level
        # An optional augment is printed as "Augment - 2 CP: ..." (or "Augment:"): the card labels it optional.
        if any(re.match(r"^\W*augment\b", _clean(line), re.I) for line in body[:2]):
            digest["optional"] = True
        out.append(digest)
    return out


def build_all(rules_text: dict[str, str]) -> dict[str, Any]:
    records = {}
    for record, text in sorted(rules_text.items()):
        records[record] = {"sha": text_sha(text), "sections": digest_text(text)}
    return {"schema": SCHEMA,
            "note": "Generated by tools/build_tooltip_digests.py from authority/typed_mechanics/rules_text.json. "
                    "Do not edit by hand: a changed rule makes its record 'pending' until the tool is rerun.",
            "records": records}


@functools.lru_cache(maxsize=1)
def _digests(mtime: float) -> dict[str, Any]:
    try:
        return json.loads(DIGESTS_PATH.read_text(encoding="utf-8")).get("records") or {}
    except (OSError, ValueError):
        return {}


def _loaded() -> dict[str, Any]:
    try:
        return _digests(DIGESTS_PATH.stat().st_mtime)
    except OSError:
        return {}


def _rules_text() -> dict[str, str]:
    """The owner's current rules text: the same cached, change-aware read the full hover text uses."""
    from .status_text import printed_rules

    return printed_rules()


@functools.lru_cache(maxsize=8192)
def _sha_cached(text: str) -> str:
    return text_sha(text)


def pick_section(sections: list[dict[str, Any]], label: str) -> dict[str, Any] | None:
    """The printed section a button names, WITH its subordinate sections (deeper headings that follow it).

    A button that names no section gets the record's single top-level section with everything under it. When the
    scope cannot be determined (several top-level sections, none named) the answer is None and the card shows the
    complete rules open.
    """
    def with_children(index: int) -> dict[str, Any]:
        top = sections[index]
        level = top.get("level", 0)
        children = []
        for child in sections[index + 1:]:
            if child.get("level", 0) <= level:
                break
            children.append(child)
        out = dict(top)
        if children:
            out["children"] = children
        if out.get("status") == "empty" and any(c.get("status") != "empty" for c in children):
            out["status"] = "full" if any(c.get("status") == "full" for c in children) else "partial"
        return out

    wanted = [norm_name(label), norm_name(str(label).split(": ", 1)[-1]), norm_name(str(label).split(":", 1)[0])]
    for key in wanted:
        if not key:
            continue
        names = [{norm_name(s.get("name")), norm_name(re.split(r"\s+[-\u2013\u2014]\s+", str(s.get("name")))[0])}
                 for s in sections]
        matches = [i for i, found in enumerate(names) if key in found]
        if len(matches) > 1:
            return None  # one name, several printed sections (CL11 / CL17 versions): show the complete rules open
        if matches:
            hit = with_children(matches[0])
            if hit.get("status") != "empty":
                return hit
    if not sections:
        return None
    top = min(s.get("level", 0) for s in sections)
    roots = [i for i, s in enumerate(sections) if s.get("level", 0) == top]
    if len(roots) == 1:
        hit = with_children(roots[0])
        return hit if hit.get("status") != "empty" else None
    useful = [i for i in roots if sections[i].get("status") != "empty"]
    return with_children(useful[0]) if len(useful) == 1 and len(roots) == 1 else None


def digest_for(record: str | None, label: str, texts: dict[str, str] | None = None) -> dict[str, Any] | None:
    """The card digest for a button, or {"status": "pending"} when its owner text changed since the last build.

    None means no printed record (or no single section to summarise): the card shows the full rules, rendered.
    """
    if not record:
        return None
    if texts is None:
        texts = _rules_text()
    text = texts.get(record)
    if text is None:
        return None
    entry = _loaded().get(record)
    if not entry or entry.get("sha") != _sha_cached(text):
        return {"status": "pending", "record": record}
    section = pick_section(entry.get("sections") or [], label)
    if not section:
        return {"status": "open", "record": record}  # scope cannot be determined: complete rules open
    def explain(part: dict[str, Any]) -> dict[str, Any]:
        part = dict(part)
        if part.get("conditions"):
            part["conditions"] = [[name, _condition_gist(name)] for name in part["conditions"]]
        if part.get("children"):
            part["children"] = [explain(child) for child in part["children"]]
        return part

    def parts(part: dict[str, Any]):
        yield part
        for child in part.get("children") or []:
            yield from parts(child)

    if any(part.get("status") == "open" for part in parts(section)):
        # Facts or procedures the compact card cannot show exactly: complete rules open, header only, no save chip.
        return {"status": "open", "record": record}
    children = section.get("children") or []
    sections = entry.get("sections") or []
    index = next((i for i, part in enumerate(sections) if part.get("name") == section.get("name")
                  and part.get("level") == section.get("level")), 0)
    if any(part.get("level", 0) < section.get("level", 0) for part in sections[:index]):
        # The selected section sits under a parent heading (an option, mode or augment of something larger):
        # outside the allowlist, complete rules open.
        return {"status": "open", "record": record}
    if children:
        # Option / mode / augment sub-headings are outside the allowlist (SOL192r5): complete rules open.
        return {"status": "open", "record": record}
    has_procedure = lambda part: bool(part.get("outcomes")) or any(label in ("Save", "Attack")  # noqa: E731
                                                                   for label, _ in part.get("facts") or [])
    if any(has_procedure(child) for child in children) and (len(children) > 1 or has_procedure(section)):
        # A save or attack inside one option/mode (Willing / Unwilling Creature) is scoped to that option.
        return {"status": "open", "record": record}
    return {**explain(section), "record": record}


def _condition_gist(name: str) -> str:
    from .condition_text import condition_gist

    return condition_gist(name.casefold())
