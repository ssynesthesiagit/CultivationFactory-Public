"""Guard for the wall enter trigger (combat/factory_compiler.py _zone_spec).

The compiler copies a wall's typed effects onto its own enter trigger with "deferred": False. That is only a
behaviour change for an enter wall whose typed rows are deferred. Today only Blackglass Rampart has one, so this
test pins the set of enter walls that carry deferred rows; a new one must be reviewed on purpose.
Reads only the public authority and terrain rules files.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _has_deferred(node):
    if isinstance(node, dict):
        return node.get("deferred") is True or any(_has_deferred(value) for value in node.values())
    if isinstance(node, list):
        return any(_has_deferred(value) for value in node)
    return False


def test_only_blackglass_rampart_is_an_enter_wall_with_deferred_rows():
    walls = json.loads((ROOT / "combat/rules/terrain.json").read_text())["walls"]
    enter_walls = {name for name, rule in walls.items() if isinstance(rule, dict) and rule.get("enter")}
    assert enter_walls == {"blackglass rampart", "wind wall", "monsoon wall"}
    mechanics = json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
    deferred = set()
    for key, record in mechanics.items():
        name = str(record.get("name") or "").strip().lower()
        if name in enter_walls and _has_deferred(record):
            deferred.add(key)
    assert deferred == {"TAL_MAGMA_BLACKGLASS_RAMPART"}, deferred
