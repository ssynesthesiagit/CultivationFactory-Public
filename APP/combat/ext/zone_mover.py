"""Moving an area you made, as its printed Bonus Action (rider lane C13, 2026-09-30; owner: "i want everything we can automated, keep
going until its only the non-combat ones left"). Shared by the abilities in MOVERS below:

  Smoke Veil:    "As a Bonus Action while the veil persists, move it up to 10 feet to a space within range. The veil cannot pass through
                 solid barriers unless a talent says otherwise."
  Shape Current: "You may move a Basin or Current up to 10 feet as a Bonus Action on your turn." (Range 60 feet.)

compile_actions gives the owner of the ability one "<label>" button (Bonus Action, aimed at a square); candidate_allowed offers it only
while one of its areas stands, for squares within the ability's range of you and within the move distance of that area's centre, with no
wall on the way; the shared move_zone effect (combat/ext/tabik_dark.py) moves the nearest such area there.

Hooks: compile_actions, candidate_allowed. No hooks added to the framework. Inert for characters without these abilities.
"""

from __future__ import annotations

from typing import Any

from . import hook

MOVERS = {
    "SMOKE_BASE_SMOKE_VEIL": {"zone": "Smoke Veil", "max_ft": 10, "range_ft": 60, "label": "Smoke Veil: move it 10 feet",
                              "description": "Bonus Action: move your Smoke Veil up to 10 feet to a square within 60 feet of you; it cannot pass "
                                             "through a wall.",
                              "evidence": "As a Bonus Action while the veil persists, move it up to 10 feet to a space within range."},
    "WATER_BASE_SHAPE_CURRENT": {"zone": "Shape Current", "max_ft": 10, "range_ft": 60, "label": "Shape Current: move it 10 feet",
                                 "description": "Bonus Action: move your Basin or Current up to 10 feet to a square within 60 feet of you; it "
                                                "cannot pass through a wall.",
                                 "evidence": "You may move a Basin or Current up to 10 feet as a Bonus Action on your turn."},
}
FLAG = "zone_move_technique"  # (tabik_ninpo already reads a "zone_mover" parameter of its own)


def areas(engine: Any, actor: Any, technique: str) -> list[Any]:
    from .. import zones

    name = MOVERS[technique]["zone"]
    return [z for z in zones.typed_zones(engine) if z.active and z.owner_id == actor.entity_id and technique in z.source_definition_id
            and (z.trigger_profile.get("name") or "") == name and not z.trigger_profile.get("anchor_id")]


@hook("compile_actions")
def mover_buttons(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    out = []
    for technique, spec in MOVERS.items():
        if technique not in info["owned_ids"]:
            continue
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.{technique.lower()}.move", display_name=spec["label"],
            owner_id=info["actor_id"], economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="CELL", range_ft=spec["range_ft"],
            parameters={"typed": {"effects": [{"type": "move_zone", "zone_name": spec["zone"], "max_ft": spec["max_ft"], "range_ft": spec["range_ft"],
                                               "evidence": spec["evidence"]}],
                                  "numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": technique},
                        "expected_damage": 0, "player_only": True, "any_cell": True, FLAG: technique, "description": spec["description"]}))
    return out or None


@hook("candidate_allowed")
def mover_aim(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    technique = ((action.parameters or {}) if action is not None else {}).get(FLAG)
    if not technique:
        return None
    spec = MOVERS[technique]
    aim = getattr(candidate, "destination", None)
    if aim is None or engine.grid.distance_ft(actor.position, aim) > spec["range_ft"]:
        return False
    blocked = engine.grid.blocked
    return any(engine.grid.distance_ft(zone.center, aim) <= spec["max_ft"]
               and not any(tuple(cell) in blocked for cell in engine.grid.ray_cells(zone.center, aim))
               for zone in areas(engine, actor, technique))
