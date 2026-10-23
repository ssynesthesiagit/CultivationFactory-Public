"""Read-only selector rules shared by action_text and tabletop's sheet/status text.

Uses existing option record IDs and printed names; never alters sealed actions,
fight state, execution, ownership or AI decisions.
"""
import re
import json
from pathlib import Path
from functools import lru_cache
from typing import Any

CHOICE_LINE = "Choosing this option takes no action and costs nothing; it stays selected until you change it."


def _name(text: str) -> str:
    text = re.sub(r"^#+\s*", "", text).strip()
    text = re.sub(r"^CL\s*\d+\s*[-—–]\s*", "", text, flags=re.I)
    return re.split(r"\s+[-—–]\s+", text, maxsplit=1)[0].casefold()


@lru_cache(maxsize=1)
def _names() -> dict[str, list[str]]:
    from .status_text import printed_rules
    names: dict[str, list[str]] = {}
    for key, text in printed_rules().items():
        for heading in re.findall(r"(?m)^#+\s+(.+)$", text):
            names.setdefault(_name(heading), []).append(key)
    return names


@lru_cache(maxsize=1)
def _effect_sources() -> dict[str, dict]:
    return json.loads((Path(__file__).parent / "rules/option_text_sources.json").read_text())


def _inline_option(text: str, option: str) -> str:
    """Scope a uniquely named rider in a printed inline Choose-one list.

    Retain the surrounding trigger, cost and limits. Ambiguous labels keep the
    original text; this never generates mechanics from prose.
    """
    match = re.search(r"(?:Then\s+)?choose one(?: rider| effect)?:\s*([^\n]+)", text, re.I)
    if not match:
        return text
    options, dot, rest = match[1].partition(". ")
    parts = re.split(r";\s*(?:or\s+)?", options)
    if len(parts) < 2:
        return text
    def words(value: str) -> set[str]:
        value = re.sub(r"\bft\b", "feet", value.casefold())
        return set(re.findall(r"[a-z]+|\d+", value)) - {"no", "the", "a", "or", "on", "off"}
    wanted = words(option)
    scores = [len(wanted & words(part)) for part in parts]
    best = max(scores)
    if not best or scores.count(best) != 1:
        return text
    selected = parts[scores.index(best)].strip().rstrip(".") + "."
    context = text[:match.start()] + (rest if dot else "") + text[match.end():]
    return selected + "\n\n" + context.strip()


def setting_text(row: dict[str, Any], fallback: str = "", *, with_markup: bool = False) -> str:
    """Option effect first, then one free-selection line; inert for other rows.

    Metadata IDs take precedence over labels. Exact printed option names resolve
    legacy selectors lacking a source ID, with ambiguous names left untouched.
    A setting's contextual help is retained when no printed source exists.
    """
    from .ext.setting_choices import is_setting_action
    from .status_text import printed_rules, printed_excerpt, plain, markup
    from .player_text import display_text

    if not is_setting_action(row):
        return fallback
    params = row.get("parameters") or {}
    typed = params.get("typed") or {}
    label = str(row.get("display_name") or row.get("label") or "")
    feature, _, option = label.partition(":")
    option = option.split(" — ", 1)[0].strip()
    records = list(params.get("shape_talents") or [])
    records += [params.get("augment_key"), (params.get("attack_modifier_setting") or {}).get("modifier"),
                typed.get("source"), typed.get("option_of"), typed.get("forged_from")]
    records += [(_effect_sources().get(effect.get("type")) or {}).get("record")
                for effect in typed.get("effects") or []]
    rules = printed_rules()
    # Inert rules-reference buttons do not select or store an option. Keep their
    # builder's explicit handling text; never promise a choice lifetime.
    if params.get("inert") and params.get("setting_description"):
        record = next((record for record in records if record in rules), None)
        printed = printed_excerpt(record, with_markup=with_markup) if record else fallback
        return "\n\n".join(dict.fromkeys(part for part in (str(params["setting_description"]), printed) if part))
    direct = f"printed_option:{option}"
    if direct in rules:
        records = [direct]
    if not any(record in rules for record in records if record):
        for name in (option, feature.strip()):
            matches = list(dict.fromkeys(_names().get(_name(name), [])))
            if len(matches) == 1:
                records = matches
                break
    texts = []
    for record in dict.fromkeys(records):
        if record not in rules:
            continue
        selected = _inline_option(rules[record], option) if option else rules[record]
        if selected != rules[record]:
            texts.append((markup if with_markup else plain)(display_text(selected)))
        else:
            # Project the same reviewed wording before either surface flattens
            # it. Otherwise plain() can match a whole reviewed card while the
            # hover sees raw rules plus selector help and misses that match.
            excerpt = printed_excerpt(record, "" if record.startswith("printed_option:") else option,
                                      with_markup=True)
            texts.append((markup if with_markup else plain)(display_text(excerpt)))
    # Paid-hit selector labels already carry the chosen option's printed
    # evidence. Scope its ordinary Choose-one list without interpreting an
    # ability ID, losing the trigger/cost/save, or inventing an effect summary.
    evidence = label.partition(" — ")[2].strip()
    if evidence:
        scoped = []
        for record in dict.fromkeys(records):
            if record not in rules:
                continue
            lines = rules[record].splitlines()
            normalize = lambda value: plain(value).casefold().replace("’", "'").replace("‘", "'").rstrip(";. ")
            selected = next((line for line in lines if normalize(line) == normalize(evidence)), None)
            if selected:
                start = next((i for i, line in enumerate(lines) if re.search(r"Choose one:\s*$", line)), None)
                end = next((i for i in range((start or 0) + 1, len(lines))
                            if re.match(r"^(?:Successful Save|Success|Miss|Hit|Duration|Limit):", lines[i])), len(lines))
                context = lines[:start] + lines[end:] if start is not None else [line for line in lines if line != selected]
                # Moving a rider out of its list must retain the list's outcome
                # qualifier, such as Failed Save, rather than imply a free effect.
                qualifier = lines[start].rsplit("Choose one:", 1)[0].strip() if start is not None else ""
                scoped.append("\n".join([" ".join(part for part in (qualifier, selected.rstrip(";")) if part), *context]))
        if scoped:
            texts = scoped
    text = "\n\n".join(dict.fromkeys(texts)) or fallback or str(params.get("setting_description") or "")
    if texts and params.get("setting_description"):
        text += "\n\n" + str(params["setting_description"])
    # A selector's builder can explain what it selects (aim, form, next use).
    # Printed effect text complements that context rather than replacing it.
    contextual = params.get("description")
    if texts and contextual and plain(str(contextual)) not in plain(text):
        text += "\n\n" + str(contextual)
    if not texts and params.get("zone_shape") and not params.get("shape_talents"):
        text = f"Use {params.get('zone_name') or 'this area'} without any optional area talents."
    # Remove duplicated generic selector blocks from historical payloads.
    blocks = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    blocks = [part for part in blocks if not part.startswith("Free choice, kept until you change it:")
              and part != CHOICE_LINE]
    text = "\n\n".join(dict.fromkeys(blocks))
    picked = re.sub(r"\s*\(\d+ CP\)$", "", option)  # the cost is stated by the option's own text, not repeated here
    if picked and f"This button picks: {picked}." not in plain(text):
        text += f"\n\nThis button picks: {picked}."
    lifetime = params.get("setting_lifetime")
    if not lifetime:
        # Older sealed catalogs can predate lifetime metadata. Ask the owning
        # plug-in without changing the saved row or inferring rules from prose.
        from .ext import query
        lifetime = next((value for value in query("setting_lifetime", row)
                         if isinstance(value, str) and value), None)
    choice_line = ("Choosing this option takes no action and costs nothing. " + str(lifetime)) if lifetime else CHOICE_LINE
    joined = "\n\n".join(part for part in ((markup if with_markup else plain)(text), choice_line) if part)
    return _cost_explained_once(joined)


# A cost number in any form the plain or markup path leaves: "1 CP", "1 CP (...)" or "1 cultivation points (your Path resource)".
_COST = re.compile(r"(\d+) (?:CP(?: \(cultivation points, your Path resource\))?|cultivation points \(your Path resource\))")


def _cost_explained_once(text: str) -> str:
    """Say a cost as "1 CP (cultivation points, your Path resource)" once, whichever path wrote it."""
    return _COST.sub(r"\1 CP (cultivation points, your Path resource)", text)
