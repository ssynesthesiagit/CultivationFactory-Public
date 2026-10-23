"""Cultivated Response's printed restrictions (F17R review, finding 1).

Printed clauses (tianxia.path.qi_cultivation.feature.cultivated_response): "Is not saving throw proficiency",
"Cannot modify a breakthrough check", "Cannot modify a training check". Breakthrough and training checks are
out-of-combat checks (character building and downtime). The only route into the save-rescue consumer is a
combat save, so these checks must never call typed_reactions.on_save.
"""
import json
import re
from pathlib import Path

from tests.h1_support import ROOT

AUTO3 = ROOT / "authority/typed_mechanics/reviewed_final.d/auto3_foundations.json"
GENERATED = ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json"
CULTIVATED = "tianxia.path.qi_cultivation.feature.cultivated_response"
ON_SAVE_CALL = re.compile(r"(?<![\w.])on_save\(")


def test_printed_restrictions_are_riders_in_the_reviewed_record_and_the_generated_authority():
    reviewed = " ".join(json.loads(AUTO3.read_text())["mechanics"][CULTIVATED]["riders"])
    generated = " ".join(json.loads(GENERATED.read_text())["mechanics"][CULTIVATED]["riders"])
    for riders in (reviewed, generated):
        assert "Cultivated Response is not saving-throw proficiency." in riders
        assert "cannot modify a breakthrough check or a training check" in riders


def test_only_combat_saves_call_the_save_rescue_consumer():
    # Breakthrough and training checks (stage2, factory_authoring) never reach on_save, so they can't be rescued.
    callers = set()
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if rel.parts[0] in {"tests", "__pycache__"} or path.name == "typed_reactions.py":
            continue
        if ON_SAVE_CALL.search(path.read_text(encoding="utf-8", errors="replace")):
            callers.add(rel.as_posix())
    assert callers == {"combat/gate2_engine.py"}
