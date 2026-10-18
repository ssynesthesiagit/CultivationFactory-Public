"""Printed provenance for shared choice prompts naming an exact ability.

Used by Needle's shared transport and its Body/Qi/Spirit consumers. Only a
leading, complete printed ability name qualifies. Explicit feature metadata
always wins; unknown or ambiguous names retain the existing diagnostic text.
"""
import re
from functools import lru_cache

from . import hook


@lru_cache(maxsize=2)
def _titles(items):
    names = []
    for record, text in items:
        heading = str(text).splitlines()[0] if text else ""
        heading = re.sub(r"^#+\s*", "", heading).replace("**", "")
        heading = re.sub(r"^CL\s*\d+\s*[-—–]\s*", "", heading)
        name = re.split(r"\s+[-—–]\s+", heading)[0].strip()
        if len(name) >= 5:
            names.append((name.casefold(), record))
    return tuple(names)


def named_record(prompt, rules):
    prompt = str(prompt).casefold()
    matches = [(len(name), record) for name, record in _titles(tuple(rules.items()))
               if prompt.startswith(name) and (len(prompt) == len(name) or
               not (prompt[len(name)].isalnum() or prompt[len(name)] == "_"))]
    if not matches:
        return None
    longest = max(n for n, _ in matches)
    records = {record for n, record in matches if n == longest}
    return next(iter(records)) if len(records) == 1 else None


@hook("decision_text")
def describe(engine, context, printed_rules):
    trigger = context.get("choice_trigger") or {}
    if trigger.get("feature_id") or not str(context.get("reaction_source_id") or "").startswith("choice:"):
        return None
    record = named_record(trigger.get("prompt") or "", printed_rules)
    return {"feature_id": record} if record else None
