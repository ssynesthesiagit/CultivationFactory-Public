"""Printed text shared by tabletop description plug-ins; no mechanical evaluation.

Used by description plug-ins and the target_eligibility/option_payments
admission plug-ins. Resolve the module's fixed source path once, not for every
candidate. The parsed document is keyed by path and file identity/version;
each independent lookup checks for edits, including same-mtime replacements.
One pure enumeration uses a single snapshot; the next menu checks again.
No fighter/action/state is cached, and no cache enters a saved fight.
"""
import json
from pathlib import Path
from .read_queries import file_snapshot

RULES_PATH = Path(__file__).resolve().parents[1] / "authority/typed_mechanics/rules_text.json"
_CACHE = {}


def printed_rule_text(key: str) -> str:
    texts = file_snapshot(('printed_rule_text', RULES_PATH), _printed_texts)
    return str(texts.get(key) or "")


def _printed_texts():
    path = RULES_PATH
    stat = path.stat()
    stamp = (path, stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    texts = _CACHE.get("texts")
    if _CACHE.get("stamp") != stamp:
        texts = json.loads(path.read_text(encoding="utf-8"))
        _CACHE.update(stamp=stamp, texts=texts)
    return texts
