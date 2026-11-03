"""RW164 public-safety guard: branch combat code must not copy printed book text.

The public export withholds any file that quotes a redacted source passage, and
`combat/ext` sits in the import closure of most tests. So a comment, docstring or
string in the combat code this branch wires may describe a feature, but must not
repeat a run of words from its printed rules text. The printed text is read from
the in-repo rules text file at run time; the test itself carries no book text.
"""

import json
import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
RULES_TEXT = APP / "authority" / "typed_mechanics" / "rules_text.json"
# Modules this branch adds hooks to; their comments, docstrings and strings are checked.
BRANCH_MODULES = (
    APP / "combat" / "ext" / "drunken_fist.py",
    APP / "combat" / "ext" / "serpent_coils.py",
)

# Records whose features this branch wires (Heavenly Drunk, Seventh Coil).
RECORDS = (
    "tianxia.subpath.body.drunken_fist.feature.heavenly_drunk",
    "tianxia.subpath.body.seven_coiled_serpent_spine.feature.seventh_coil_heaven_swallowing_serpent",
)
RUN = 8


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _runs(text: str) -> set[tuple[str, ...]]:
    words = _words(text)
    return {tuple(words[i:i + RUN]) for i in range(len(words) - RUN + 1)}


def _printed_runs() -> set[tuple[str, ...]]:
    if not RULES_TEXT.exists():
        pytest.skip("printed rules text is not in this export")
    data = json.loads(RULES_TEXT.read_text(encoding="utf-8"))
    runs: set[tuple[str, ...]] = set()
    for record in RECORDS:
        text = data.get(record)
        assert isinstance(text, str) and text, f"no printed rules text for {record}"
        runs |= _runs(text)
    return runs


def test_combat_code_does_not_copy_printed_text_for_the_branch_records():
    printed = _printed_runs()
    offenders = []
    for path in BRANCH_MODULES:
        shared = printed & _runs(path.read_text(encoding="utf-8"))
        if shared:
            offenders.append(f"{path.relative_to(APP)}: {' '.join(sorted(shared)[0])}")
    assert not offenders, "printed rules text copied into combat code (cite the record id instead):\n" + "\n".join(offenders)
