"""Magma's patches of Molten and Obsidian Terrain, Heat Pressure, and Shape the Crust (rider lane C13, 2026-09-30; owner: "i want
everything we can automated, keep going until its only the non-combat ones left"). Printed: Sphere Compendium, Magma (Molten Terrain,
Obsidian Terrain, Heat Pressure), Magma Glob, Shape the Crust.

  magma_patch        Magma Glob: "create one 5-foot patch of Molten Terrain adjacent to the target until the start of your next turn" /
                     "... Obsidian Terrain adjacent to the target for 1 minute". One square next to the target, asked (the AI takes the
                     free square nearest you); a placed zone (combat/ext/placed.py, tag ``magma_patch``) carrying the terrain rule of
                     combat/rules/terrain.json. Molten: difficult terrain; a creature entering it or starting a turn in it makes
                     the Dexterity save that rule prints -- the creating talent's own damage on a failure, half on a success -- so
                     the patch carries the Glob's 2d10 + key. A paid on-hit rider (Eruption Strike: 2 CP, once per turn, "You hit
                     a creature") is the rider's own rule with its own trigger and is never repeated by the ground (see
                     combat/ext/terrain_damage.py). Obsidian: difficult for hostile creatures; its
                     moving-through save (Proficiency Bonus Slashing).
  magma_heat_pressure  "apply Heat Pressure until the start of your next turn": the caster picks one of the printed effects -- Speed -10,
                     no Reactions, Disadvantage on its next Strength or Dexterity check; "a creature may suffer only one Heat Pressure
                     effect from you at a time" (a new one replaces it). The fourth ("must choose between moving willingly or taking an
                     Action on its next turn") is still the GM's: the affected creature owns that choice at its own turn
                     boundary, and the turn_start_choice hook did not deliver it in a table-level fight (AUTO102).
  magma_furnace_step  Furnace Step's own printed exemptions: an evented receipt makes your own Molten Terrain and
                     ordinary rubble, ash, volcanic stone and obsidian on the battlefield cost your movement nothing
                     extra until the end of this turn (difficult_exempt, source-scoped, so ground some other caster
                     conjured on the same square keeps its own cost), your own Molten Terrain also stops dealing you
                     its hazards (zone_recipient_allowed), and one chosen creature is denied an opportunity attack
                     against you, while every other creature keeps its own. Its typed Speed increase and the patch
                     clause are unchanged.
  magma_shape        Shape the Crust, aimed at one of your patches within range: "cool one 5-foot patch of your Molten Terrain into
                     Obsidian Terrain for 1 minute"; "crack one 5-foot patch of your Obsidian Terrain, ending it and dealing Slashing
                     damage equal to your Proficiency Bonus to one creature standing in it, Dexterity save negates"; "move one 5-foot
                     patch of your Molten Terrain up to 5 feet across a continuous surface" (asked: the direction; not into a creature's
                     space or a wall). A safe stepping line binds one actual ally to this patch until the next owner start. Low directional ridge cover and selecting a subarea of a larger terrain remain unfinished.
Hooks: candidate_allowed (Shape the Crust is aimed at a patch of the right kind). Inert without these effects.
"""

from __future__ import annotations

from .map_positions import map_position

import copy
from typing import Any

from . import effect, hook, note

TAG = "magma_patch"
HEAT = "condition:typed.heat_pressure"
SHAPE = "TAL_MAGMA_SHAPE_THE_CRUST"
_DIRS = {"north": (0, -1), "north-east": (1, -1), "east": (1, 0), "south-east": (1, 1), "south": (0, 1), "south-west": (-1, 1),
         "west": (-1, 0), "north-west": (-1, -1)}


def _terrain(name: str) -> dict[str, Any]:
    from .. import zones

    return (zones.terrain_rules().get("terrains") or {}).get(f"{name} terrain") or {}


def patches(engine: Any, owner: Any, kind: str | None = None) -> list[Any]:
    from . import placed

    return [z for z in placed.of(engine, TAG, owner_id=owner.entity_id) if kind is None or placed.data(z).get("kind") == kind]


def _molten_triggers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The DEX save combat/rules/terrain.json gives Molten Terrain: the creating talent's own
    damage on a failure, half on a success, once per turn, for anyone entering or starting a turn there."""
    fail = [{**copy.deepcopy(row), "applies_to": "target"} for row in rows]
    return [{"name": "Molten Terrain", "on": ["enter", "start"], "who": "any",
             "effects": [{"type": "save", "ability": "DEX", "on_fail": fail, "on_success": [{"type": "half_damage"}]}]}]


def _place(ctx: Any, cell: Any, kind: str, damage: list[dict[str, Any]] | None) -> Any:
    from . import placed

    rule = _terrain(kind)
    rounds = 1 if kind == "molten" else 10
    clock = bool(kind == 'molten' and ctx.damage_cache.get('_auto46_glob'))
    damage = copy.deepcopy(damage)
    if clock and sovereign_active(ctx.engine, ctx.actor):
        for row in damage or []:
            row['dice'] = {'count': 6, 'sides': 10}
            row.pop('dice_by_cl', None)
    zone = placed.place(ctx.engine, ctx.actor, source=ctx.source, tag=TAG, cells=[cell], name=f"{kind.title()} Terrain (Magma)",
                        placed={"kind": kind, "damage": damage if damage else None,
                                **({'owner_start': int(ctx.actor.turns_started) + 1} if clock else {})}, duration_rounds=rounds,
                        color=rule.get("color"), material=rule.get("material") or "lava", terrain=[f"{kind} terrain"],
                        difficult=rule.get("difficult"), numbers=dict(ctx.numbers),
                        triggers=_molten_triggers(damage) if kind == "molten" and damage else None,
                        extra={"move_through": copy.deepcopy(rule.get("move_through"))} if kind == "obsidian" else None)
    return zone


def _free(engine: Any, cell: Any) -> bool:
    from .rider_support import occupant

    grid = engine.grid
    return 0 <= cell.x < grid.width and 0 <= cell.y < grid.height and (cell.x, cell.y) not in grid.blocked and occupant(engine, cell) is None


@effect("magma_patch")
def magma_patch(ctx: Any, eff: dict[str, Any]) -> None:
    from ..gate2_runtime_models import Position
    from .needle import cell_id, position_of
    from .rider_choices import pick

    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None:
        return
    kind = str(eff.get("terrain") or "molten")
    cells = sorted((cell for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy
                    if (cell := map_position(engine, target.position.x + dx, target.position.y + dy)) is not None),
                   key=lambda c: (engine.grid.distance_ft(owner.position, c), c.y, c.x))
    cells = [c for c in cells if _free(engine, c)]
    if not cells:
        ctx.rider(f"Magma Glob: no free square next to {target.display_name} for the patch.")
        return
    options = [cell_id(c) for c in cells]
    chosen = pick(engine, owner, "magma_patch", "Magma Glob", options, subject=target, preferred=[options[0]], optional=False,
                  labels={cell_id(c): f"{kind.title()} Terrain at {c.x},{c.y}" for c in cells}, trigger=f"Magma Glob hits {target.display_name}")
    cell = position_of((chosen or options)[0])
    # combat/rules/terrain.json gives Molten Terrain a save "against the creating ability's own
    # damage", so the patch keeps the damage the Glob itself lists (2d10 + key, half on a success).
    # A paid on-hit rider is not the Glob's damage: Eruption Strike has its own trigger, 2 CP and
    # once-per-turn limit, so it is skipped with its whole subtree (combat/ext/terrain_damage).
    # Obsidian carries its own fixed moving-through damage in the same rules file, not the talent's.
    from .terrain_damage import own_damage_rows

    _place(ctx, cell, kind, own_damage_rows(ctx.typed.get("effects") or []) if kind == "molten" else None)
    note(engine, ctx.source, owner, f"{owner.display_name} leaves a patch of {kind.title()} Terrain at ({cell.x}, {cell.y}).")


@effect("magma_heat_pressure")
def heat_pressure(ctx: Any, eff: dict[str, Any]) -> None:
    from ..typed_executor import run_effects
    from .condition_ownership import remove_instance
    from .rider_choices import pick

    engine, owner, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active:
        return
    labels = {"slow": "Heat Pressure: its Speed is 10 feet lower until the start of your next turn",
              "reactions": "Heat Pressure: it cannot take Reactions until the start of your next turn",
              "check": "Heat Pressure: Disadvantage on its next Strength or Dexterity check before the start of your next turn",
              }
    way = (pick(engine, owner, "magma_heat_pressure", "Heat Pressure", list(labels), subject=target, labels=labels, preferred=["slow"],
                optional=False, intent=ctx.intent,
                trigger=f"Magma Glob hits {target.display_name}") or ["slow"])[0]
    for iid, row in list(target.conditions.items()):  # "only one Heat Pressure effect from you at a time"
        if row.condition_id == HEAT and row.source_actor_id == owner.entity_id:
            for mid in list((row.data or {}).get("modifiers") or []):
                if mid in target.modifiers:
                    del target.modifiers[mid]
                    engine._append_event("MODIFIER_REMOVED", ctx.source, actor_id=owner.entity_id, target_ids=(target.entity_id,),
                                         payload={"modifier_id": mid, "reason": "REPLACED"})
            for cid in list((row.data or {}).get("conditions") or []):
                if cid in target.conditions:
                    remove_instance(engine, target, cid, ctx.source)
            remove_instance(engine, target, iid, ctx.source)
    rows = {"slow": [{"type": "speed", "applies_to": "target", "flat": -10, "duration": "until_start_of_next_turn"}],
            "reactions": [{"type": "reaction_denied", "applies_to": "target", "duration": "until_start_of_next_turn"}],
            "check": [{"type": "disadvantage", "applies_to": "target", "on": "next Strength or Dexterity check", "duration": "until_start_of_next_turn"}]}[way]
    before_c, before_m = set(target.conditions), set(target.modifiers)
    run_effects(ctx, rows)
    engine._apply_condition(target, HEAT, ctx.source, owner.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"label": labels[way], "conditions": sorted(set(target.conditions) - before_c),
                                  "modifiers": sorted(set(target.modifiers) - before_m)})


STEP = "condition:typed.magma_heat_step"
# Furnace Step waives "ordinary rubble, ash, volcanic stone, and obsidian difficult terrain", and the
# word doing the work is "ordinary". These are the names combat/rules/terrain.json and the map's paint
# tool give natural ground. Only ground painted on the battlefield (_ordinary_ground) counts: an Ash or
# Obsidian patch some ability conjured is that caster's magic, not rubble lying on the battlefield, so
# it keeps its cost. Fire Terrain is left out of the list outright -- it is a burning hazard, never
# ordinary ground -- and no terrain's hazards are waived at all: the clause waives movement cost, and
# only your own Molten Terrain is named as terrain you ignore.
_STEP_ORDINARY = {"loose rubble", "rubble terrain", "ash terrain", "obsidian terrain",
                  "volcanic stone", "volcanic stone terrain"}


@effect("magma_furnace_step")
def furnace_step(ctx: Any, eff: dict[str, Any]) -> None:
    """Furnace Step's two printed exemptions, on top of its typed Speed increase.

    "ignore your own Molten Terrain" and "ignore ordinary rubble, ash, volcanic stone, and obsidian
    difficult terrain" become an evented receipt on you that the two ground hooks read. The ordinary
    list waives movement cost on the battlefield's own ground only (see ``_ordinary_ground``); it never
    waives a save, damage or condition, and only your own Molten Terrain stops dealing you its hazards.
    "do not provoke opportunity attacks from one creature of your choice" picks exactly one creature and
    denies it an opportunity attack against you; every other creature keeps its own.
    """
    from dataclasses import replace

    from ..typed_executor import run_effects
    from .rider_choices import pick

    engine, owner = ctx.engine, ctx.actor
    engine._apply_condition(owner, STEP, ctx.source, owner.entity_id, expires_on="END_OF_CURRENT_TURN",
                            data={"label": "Furnace Step: your own Molten Terrain, and ordinary rubble, ash, volcanic "
                                           "stone and obsidian on the ground, cost your movement nothing extra until "
                                           "the end of this turn"})
    foes = [a for a in engine.state.actors.values() if a.active and a.team_id != owner.team_id]
    if not foes:
        note(engine, ctx.source, owner, "Furnace Step: "
                                        f"{owner.display_name} moves through their own Molten Terrain and ordinary rubble, ash, "
                                        "volcanic stone and obsidian as if they were level ground, until the end of this turn.")
        return
    options = [a.entity_id for a in foes]
    chosen = pick(engine, owner, "magma_furnace_step", "Furnace Step", options, subject=owner, maximum=1, minimum=1,
                  optional=False, labels={a.entity_id: f"{a.display_name} gets no opportunity attack against you this turn"
                                          for a in foes},
                  preferred=[options[0]], intent=ctx.intent,
                  trigger=f"{owner.display_name} moves through heat and rubble")
    foe = engine.state.actors.get((chosen or options)[0])
    if foe is None:
        return
    run_effects(replace(ctx, target=foe, targets=[foe]),
                [{"type": "reaction_denied", "applies_to": "target", "flat": 0, "formula": "none", "damage_types": [],
                  "ability": "none", "condition": "none", "distance_ft": 0,
                  "on": "opportunity attacks against you",
                  "evidence": "do not provoke opportunity attacks from one creature of your choice",
                  "duration": "until_end_of_turn", "expires_on": "END_OF_CURRENT_TURN"}])
    note(engine, ctx.source, owner, "Furnace Step: "
                                    f"{owner.display_name} moves through heat and rubble without provoking "
                                    f"{foe.display_name}'s opportunity attack this turn.")


def _terrain_names(zone: Any) -> set[str]:
    return {str(name).lower() for name in (zone.trigger_profile.get("terrain") or [])}


def _own_molten(actor: Any, zone: Any) -> bool:
    """"your own Molten Terrain": lava you created, judged by the patch's own terrain name and its creator."""
    return "molten terrain" in _terrain_names(zone) and zone.owner_id == actor.entity_id


def _ordinary_ground(zone: Any) -> bool:
    """"ordinary rubble, ash, volcanic stone, and obsidian": natural ground on the battlefield.

    Only terrain painted on the map qualifies (combat/rules/terrain.json's own map terrains, which carry
    no creator). A patch any ability conjured is excluded, so another caster's Ash or Obsidian Terrain,
    and yours, keep the movement cost the printed clause never waived.
    """
    from .. import zones

    return zone.owner_id == zones.MAP_OWNER and bool(_terrain_names(zone) & _STEP_ORDINARY)


def _stepping(engine: Any, actor: Any) -> bool:
    """Whether this creature holds Furnace Step's evented receipt for the current turn."""
    return any(c.condition_id == STEP and c.source_actor_id == actor.entity_id
               for c in actor.conditions.values())


@hook("difficult_exempt")
def heat_step_ignores_ground(engine: Any, actor: Any) -> set[tuple[int, int]] | None:
    """The squares Furnace Step says cost the mover nothing extra, while that turn's receipt is on them.

    Scoped to the sources, because the engine subtracts these squares from the whole board: a square is
    exempt only when every area on it is one the printed clause names (your own Molten Terrain, or
    ordinary battlefield ground) and no other area still charges that creature for it. Your own Molten
    patch lying inside another caster's lava, or on hostile Obsidian Terrain, therefore keeps its cost,
    which is what "_step_ground rejects that other caster" means.

    "Still charges that creature" is asked of the engine itself (combat/zones.py zone_is_difficult), the same
    per-area answer difficult_cells uses, so ground whose policy does not reach this creature -- aimed at
    other creatures, needing a mark this creature does not bear, or ignored as nonmagical -- leaves the
    printed waiver standing instead of cancelling it.
    """
    if not _stepping(engine, actor):
        return None
    from .. import zones

    waived: set[tuple[int, int]] = set()
    charged: set[tuple[int, int]] = set()
    for zone in zones.typed_zones(engine):
        if not zone.owner_id:
            continue
        cells = {(cell.x, cell.y) for cell in zone.affected_cells}
        if _own_molten(actor, zone) or _ordinary_ground(zone):
            waived |= cells
        elif zones.zone_is_difficult(engine, zone, actor):
            charged |= cells
    return (waived - charged) or None


@hook("zone_recipient_allowed")
def heat_step_ignores_ground_hazards(engine: Any, zone: Any, actor: Any, spec: Any) -> bool | None:
    """Furnace Step's own Molten Terrain stops dealing this creature its hazards while the receipt lasts.

    Scoped to your own lava only. Fire Terrain, Ash Terrain and another caster's molten ground keep every
    effect they print for this creature -- the ordinary-ground clause waives movement cost, not saves,
    damage or conditions.
    """
    if not _stepping(engine, actor):
        return None
    return False if _own_molten(actor, zone) else None


@hook("candidate_allowed")
def shape_needs_a_patch(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    typed = ((getattr(action, "parameters", None) or {}).get("typed") or {}) if action is not None else {}
    row = next((e for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "magma_shape"), None)
    if row is None:
        return None
    aim = getattr(candidate, "destination", None)
    kind = None if row.get('op') == 'safe' else "obsidian" if row.get("op") == "crack" else "molten"
    return aim is not None and any((c.x, c.y) == (aim.x, aim.y) for z in patches(engine, actor, kind) for c in z.affected_cells)


@effect("magma_shape")
def shape(ctx: Any, eff: dict[str, Any]) -> None:
    from ..gate2_runtime_models import Position
    from . import placed
    from .rider_choices import pick

    engine, owner, aim = ctx.engine, ctx.actor, getattr(ctx.intent, "destination", None)
    op = str(eff.get("op") or "")
    kind = None if op == 'safe' else "obsidian" if op == "crack" else "molten"
    zone = next((z for z in patches(engine, owner, kind) if aim is not None and any((c.x, c.y) == (aim.x, aim.y) for c in z.affected_cells)), None)
    if zone is None:
        ctx.rider(f"Shape the Crust: no {kind.title() if kind else 'eligible'} Terrain of yours there.")
        return
    cell = zone.center
    if op == 'safe':
        from .needle import ask, checkpoint_id, CHOICE
        from ..typed_executor import effect_expiry
        allies = [a for a in engine.state.actors.values() if a.active and a.team_id == owner.team_id
                  and engine._distance_actor_to_actor(owner, a) <= 60]
        picked = ask(engine, ctx.intent, checkpoint_id(engine, 'magma_safe_step', zone.zone_id), owner,
                     CHOICE + 'magma_safe_step', [a.entity_id for a in allies],
                     labels={a.entity_id: a.display_name for a in allies}, allow_decline=False,
                     name='Shape the Crust', prompt='Shape the Crust: choose one ally to cross this patch safely until your next turn starts. No CP cost.')
        if picked and isinstance(zone.trigger_profile.get('difficult'), str):
            # The legacy scalar terrain path has no recipient predicate.
            # Opt this actual patch into the existing policy-bearing form.
            who = zone.trigger_profile['difficult']
            placed.reshape(engine, zone, profile={'difficult': {'who': 'any' if who == 'all' else who}})
        for aid in picked:
            ally = engine.state.actors[aid]
            expires = effect_expiry(ctx, {'expires_on': 'START_OF_SOURCE_NEXT_TURN'}, ally, condition=True)
            engine._apply_condition(ally, SAFE, ctx.source, owner.entity_id, expires_on=expires,
                                    data={'label': 'Safe stepping line: Shape the Crust', 'zone_id': zone.zone_id})
    elif op == "cool":
        placed.drop(engine, zone, "COOLED")
        _place(ctx, cell, "obsidian", None)
        note(engine, ctx.source, owner, f"The Molten Terrain at ({cell.x}, {cell.y}) cools into Obsidian Terrain for 1 minute.")
    elif op == "crack":
        from .rider_support import occupant
        from ..typed_executor import run_effects

        placed.drop(engine, zone, "CRACKED")
        victim = occupant(engine, cell)
        if victim is not None and victim.active:
            sub = placed.context(engine, owner, ctx.source, dict(ctx.numbers), [victim])
            run_effects(sub, [{"type": "save", "ability": "dex", "on_fail": [{"type": "damage", "applies_to": "target", "flat": 0, "formula": "pb",
                                                                              "damage_types": ["slashing"]}], "on_success": []}])
        note(engine, ctx.source, owner, f"The Obsidian Terrain at ({cell.x}, {cell.y}) cracks apart.")
    elif op == "move":
        moves = {}
        for word, (dx, dy) in _DIRS.items():
            dest = map_position(engine, cell.x + dx, cell.y + dy)
            if dest is not None and _free(engine, dest) and engine.grid.step_legal(cell, dest, occupied_cells=set()):  # not through a wall or a corner
                moves[word] = dest
        if not moves:
            ctx.rider("Shape the Crust: nowhere to move that patch.")
            return
        words = list(moves)
        word = (pick(engine, owner, "magma_move", "Shape the Crust", words, subject=owner, preferred=[words[0]], optional=False,
                     labels={w: f"Move the Molten Terrain 5 feet {w}" for w in words}, trigger="Shape the Crust") or words)[0]
        placed.reshape(engine, zone, cells=[moves[word]], center=moves[word])
        note(engine, ctx.source, owner, f"The Molten Terrain flows 5 feet {word}.")


GLOB = 'TAL_MAGMA_MAGMA_GLOB'
SOVEREIGN = 'TAL_MAGMA_VOLCANO_SOVEREIGN_INCARNATION'
SAFE = 'condition:typed.magma_safe_step'


@hook('before_target_reactions')
def shape_edits_existing_ground(ctx):
    """Keep catalogue aim eligibility; omit inferred ground in this use only."""
    if ctx.typed.get('source') == SHAPE and any(row.get('editing_existing')
            for row in ctx.typed.get('effects') or [] if row.get('type') == 'magma_shape'):
        # resolve_typed supplies a fresh action-local dictionary. Old sealed
        # rows lack this opt-in marker and keep their original execution.
        ctx.typed.pop('zone_spec', None)


def sovereign_active(engine, actor):
    """The actual evented form, rather than merely owning its passive row."""
    from ..typed_executor import mark_condition_id
    cid = mark_condition_id('Volcano-Sovereign Incarnation', actor.entity_id)
    return any(c.condition_id == cid and c.source_actor_id == actor.entity_id
               and ((engine.action_catalog.get(c.source_definition_id).parameters or {}).get('typed') or {}).get('source') == SOVEREIGN
               for c in actor.conditions.values() if c.source_definition_id in engine.action_catalog)


@hook('attack_damage')
def sovereign_glob_dice(ctx, dice):
    from ..gate2_runtime_models import DiceSpec
    if ctx.typed.get('source') == GLOB and dice is not None and sovereign_active(ctx.engine, ctx.actor):
        return DiceSpec(count=6, sides=10, modifier=dice.modifier)
    return None


@effect('magma_glob_expression')
def glob_expression(ctx, spec):
    """Choose the printed expression on a hit, once per actual global turn."""
    from .needle import ask, checkpoint_id, CHOICE
    from ..typed_executor import run_effects, size_width
    if ctx.typed.get('source') != GLOB or ctx.target is None:
        return
    stamp = int(ctx.engine.state.round_number) * 1000 + int(ctx.engine.state.current_slot_index)
    flag = f'auto46:glob:{stamp}'
    if ctx.actor.turn_flags.get(flag):
        return
    options = [row for row in spec['options'] if row['label'] != 'Push 5 Feet'
               or size_width(ctx, ctx.target, 'subject', {}) <= 2]
    labels = [row['label'] for row in options]
    preferred = [spec.get('preferred')] if spec.get('preferred') in labels else labels[:1]
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'magma_glob_expression', ctx.target.entity_id),
                 ctx.actor, CHOICE + 'magma_glob_expression', labels, preferred=preferred, allow_decline=False,
                 target_id=ctx.target.entity_id, name='Magma Glob',
                 prompt=f'Magma Glob hit {ctx.target.display_name}: choose one effect. Once per turn; no extra CP cost.')
    if picked:
        ctx.actor.turn_flags[flag] = True
        ctx.damage_cache['_auto46_glob'] = 1
        for row in options:
            if row['label'] in picked:
                run_effects(ctx, row['effects'])


@hook('zone_recipient_allowed')
def safe_patch_policy(engine, zone, actor, spec):
    if any(c.condition_id == SAFE and c.source_actor_id == zone.owner_id
           and c.data.get('zone_id') == zone.zone_id for c in actor.conditions.values()):
        return False
    return None


@hook('turn_start')
def glob_patch_expiry(engine, actor):
    from . import placed
    for zone in patches(engine, actor):
        due = placed.data(zone).get('owner_start')
        if due is not None and actor.turns_started >= due:
            placed.drop(engine, zone, 'DURATION_ENDED')
