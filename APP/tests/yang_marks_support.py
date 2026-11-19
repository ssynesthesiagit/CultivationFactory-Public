"""Synthetic prose inputs for Yang tests; production compilation and mechanics stay intact.

Public exports omit some source prose used by trigger classification and light
presentation. These inputs exercise those same readers on public and private
runners without replacing reaction rows, effects, limits or zone geometry.
"""
import json
from hashlib import sha256
from contextlib import contextmanager

from combat import factory_compiler, reaction_triggers
from combat.ext.yang_sun_marks import LIFE, DAWN, MANTLE


@contextmanager
def synthetic_yang_inputs(tmp_path, monkeypatch):
    authority = json.loads(factory_compiler.TYPED_AUTHORITY.read_text())
    mechanics = authority["mechanics"]
    readings = []
    for source in (LIFE, DAWN):
        trigger = "Synthetic survival trigger."
        mechanics[source]["activation"]["trigger"] = trigger
        readings.append({
            "mechanic_id": source, "text_sha256": sha256(trigger.encode()).hexdigest(),
            "reading": "Synthetic incoming lethal packet.",
            "events": [{"kind": "ally_drop_to_zero", "range_ft": 60,
                        "includes_self": source == DAWN}],
        })
    readings_path = tmp_path / "synthetic-yang-trigger-readings.jsonl"
    readings_path.write_text("".join(json.dumps(row) + "\n" for row in readings))
    light = next(effect for effect in mechanics[MANTLE]["effects"]
                 if effect.get("type") == "zone" and not effect.get("triggers"))
    light["evidence"] = "Synthetic aura: bright light in a 10-foot radius."
    path = tmp_path / "synthetic-yang-authority.json"
    path.write_text(json.dumps(authority))
    with monkeypatch.context() as patch:
        patch.setattr(factory_compiler, "TYPED_AUTHORITY", path)
        patch.setattr(reaction_triggers, "READINGS_PATH", readings_path)
        patch.setattr(reaction_triggers, "_READINGS", {})
        yield
