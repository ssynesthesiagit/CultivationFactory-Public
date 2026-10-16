"""White Heron Crescent Body riders (rider lane C7, 2026-09-30: "i want everything we can automated").

Rules: Body Refining Subpath Compendium R8, White Heron Crescent Body (the five features and their Normalized Procedures). Owned rows:
``{"type": "path_passive", "kind": "heron", "role": "integration" | "guard" | "white_wing" | "moon"}``; Crescent-Body Integration also
carries the integrated-weapon row (group "polearm") and a reach_bonus row (combat/ext/reach_bonus.py). One-Legged Guard's Reaction
runs ``one_legged_guard``; Crescent Reaping Circle is an Attack-action variant (combat/ext/attack_lines.py, ``reaping_circle``); Moon
over the Reed Sea's action runs ``moon_over_the_reed_sea``; its stance is the named state "moon_reed_stance".

Heron's Passing Cut  once per turn, a Polearm hit after 10+ feet of willing movement this turn (asked, 1 Stamina): move 10 feet
                    without provoking, push it 10 feet, pull it 5 feet (to a square still within reach), or + 1d8/2d8/3d8
                    Slashing or Force.
One-Legged Guard    the Reaction (1 Stamina, once per round) before a melee attack from a creature within your Polearm's reach at
                    you or at a creature next to you: one Polearm attack (a Granted Attack); on a hit, asked: - PB on that attack
                    roll, move the protected creature 5 feet (the attack then misses if it no longer reaches), push the attacker
                    5 feet (likewise), or no Reactions for the attacker until its next turn.
Crescent Reaping Circle  "Crescent Reaping Circle (<Polearm>)": the Attack action with one attack spent on the sweep (2 Stamina, once
                    per turn): the hostile creatures you choose within the Polearm's reach make a Dexterity save (one weapon die
                    + CON + 3d8; on a failure you choose, for each, a 5-foot push or no Reactions; half on a success), then an
                    asked 10-foot move without provoking, then the remaining attacks.
White Wing Crosses the Reed Field  once during each of your turns after a Polearm hit (asked): move up to half your Speed through
                    that creature's space (at least 5 feet through it), then choose: a Polearm attack against a different creature
                    in reach (Granted), push it 10 feet, knock it Prone on a failed Strength save, or + 2 AC until your next turn.
Moon over the Reed Sea  a route of up to twice your Speed to the aimed square, through hostile creatures, without provoking: each
                    hostile creature you choose that comes within the Polearm's reach makes a Dexterity save (10d8, a push of up
                    to 15 feet you choose, no Reactions until the end of its next turn; or half, 5 feet, until the start of its
                    next turn); then the guarded stance until your next turn: + 2 AC, + 5 feet reach, and the first hostile creature
                    to come within your reach takes one attack that spends no Reaction.
Every hook returns early for a creature without these rows, flags or state.
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook, note, query

PREFIX = "tianxia.subpath.body.white_heron_crescent_body.feature."
REAPING = PREFIX + "crescent_reaping_circle"
STANCE = "moon_reed_stance"
STAMINA = "resource:core.stamina"
SOURCE = PREFIX.removesuffix('.feature.')
FEATURE_LEVELS = {PREFIX + name: level for name, level in (
    ('crescent_body_integration', 3), ('one_legged_guard', 6), ('crescent_reaping_circle', 10),
    ('white_wing_crosses_the_reed_field', 14), ('moon_over_the_reed_sea', 18))}
ROLE_FEATURE = dict(zip(('integration', 'guard', 'white_wing', 'moon'),
    (PREFIX+n for n in ('crescent_body_integration', 'one_legged_guard',
                       'white_wing_crosses_the_reed_field', 'moon_over_the_reed_sea'))))


def _available(engine, actor, feature):
    from .body_modes_scene_resources import available
    return available(engine, actor, feature, FEATURE_LEVELS[feature], requires_conscious=False)


def _ready(engine, actor):
    from ..weapon_delivery import ready_weapons
    return {key: a for key, a in ready_weapons(engine, actor).items()
            if _polearm((a.parameters or {}).get('typed') or {})}


def _owns(engine, actor, feature):
    from .body_modes_scene_resources import bundle_of
    bundle = bundle_of(engine, actor)
    return (any(r.get('feature_id') == feature for r in bundle.get('typed_passives', []))
            or any(((a.get('parameters') or {}).get('typed') or {}).get('source') == feature
                   or (a.get('parameters') or {}).get('attack_line') == feature
                   for a in bundle.get('action_catalog', [])))



def _roles(engine: Any, actor: Any) -> set[str]:
    return {str(row.get("role")) for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(getattr(actor, "entity_id", ""), [])
            if row.get("block") == "path_rider" and row.get("kind") == "heron"
            and row.get('role') in ROLE_FEATURE and _available(engine, actor, ROLE_FEATURE[row['role']])}


def _stamp(engine: Any) -> str:
    from .body_modes_scene_resources import turn_key
    return turn_key(engine)


def _intent(engine: Any) -> Any:

    return getattr(engine, "_active_intent", None)


def _polearm(typed: dict[str, Any]) -> bool:
    from .integrated_weapons import in_group

    return in_group(typed or {}, "polearm") and not (typed or {}).get("range_ft")


def _moved(engine: Any, actor: Any) -> int:
    total = 0
    for event in reversed(engine.events):
        if event.event_type == "TURN_STARTED":
            break
        payload = event.payload or {}
        if event.event_type == "MOVEMENT_COMMITTED" and event.actor_id == actor.entity_id and not payload.get("forced") and not payload.get("teleport") and payload.get("movement_mode") != "teleport":
            total += int(payload.get('willing_distance_ft',
                max(0, len(payload.get("path") or []) - 1) * engine.grid.square_size_ft))
    return total


def _polearm_attacks(engine: Any, actor: Any, target: Any | None, *, opportunity: bool = False) -> dict[str, Any]:
    """The owner's Polearm attack actions (and their integrated variants) that reach ``target``, the longest reach first."""
    from .reach_bonus import MARK, applies, current_reach

    from ..weapon_delivery import physical_weapon_id
    ready = _ready(engine, actor)
    out = {}
    for action in sorted(engine.action_catalog.values(), key=lambda a: (-int(a.range_ft or 5), a.source_definition_id)):
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id != actor.entity_id or not _polearm(typed) or (action.parameters or {}).get("player_only") \
                or str(getattr(action.economy, "value", action.economy)) != "ACTION" or ("#" in action.source_definition_id and "#integrated" not in action.source_definition_id):
            continue
        if physical_weapon_id(action.source_definition_id, action.parameters) not in ready:
            continue
        if not any(isinstance(e, dict) and e.get("type") == "attack" for e in typed.get("effects") or []):
            continue
        rule = (action.parameters or {}).get(MARK)
        if rule and not applies(engine, actor, rule, opportunity=opportunity):
            continue
        reach = current_reach(engine, actor, action, opportunity=opportunity)
        if target is None or engine._distance_actor_to_actor(actor, target) <= reach:
            out[action.source_definition_id] = action.model_copy(update={"range_ft": reach})
    return out


def _pick(engine: Any, intent: Any, actor: Any, target: Any, name: str, *, optional: bool = False, opportunity: bool = False) -> Any:
    from .needle import ask, checkpoint_id

    attacks = _polearm_attacks(engine, actor, target, opportunity=opportunity)
    if len(attacks) == 0:
        return None
    if not optional and len(attacks) <= 1:
        return next(iter(attacks.values()), None)
    preferred = [k for k in attacks if k.endswith("#integrated_con")] or list(attacks)
    picked = ask(engine, intent, checkpoint_id(engine, "heron_attack", target.entity_id), actor, "choice:needle.heron_polearm_attack", list(attacks),
                 labels={k: a.display_name for k, a in attacks.items()}, preferred=preferred[:1], target_id=target.entity_id, name=name,
                 allow_decline=optional,
                 prompt=(f"{name}: {target.display_name} entered your reach. Take one Polearm Opportunity Attack without spending your Reaction?"
                         if optional else f"{name}: which Polearm attack against {target.display_name}?"))
    return attacks.get(picked[0]) if picked else None


def _granted(engine: Any, actor: Any, action: Any, target: Any, intent: Any) -> bool:
    """One Granted Attack with ``action``; True on a hit."""
    from .. import typed_executor as te

    typed = (action.parameters or {}).get("typed") or {}
    attack = next((dict(e) for e in typed.get("effects") or [] if isinstance(e, dict) and e.get("type") == "attack"), None)
    if attack is None:
        return False
    attack.update(count=1, granted_attack_root=True)
    start = len(engine.events)
    te.run_effects(te.Context(engine, actor, action, intent, {**typed, "effects": [attack], "granted_attack": True}, [target], target, {}), [attack])
    return any(e.event_type == "ATTACK_ROLLED" and e.actor_id == actor.entity_id and (e.payload or {}).get("provisional_hit") for e in engine.events[start:])


def _free_move(engine: Any, intent: Any, actor: Any, feet: int, choice_id: str, name: str) -> None:
    from .needle import ask, checkpoint_id
    from ..granted_movement import routes, Route, resolve_path
    from .needle import cell_id

    paths = {cell_id(c): Route(tuple(path), mode) for c, (path, cost, mode) in routes(engine, actor, feet).items()}
    if not paths:
        return
    picked = ask(engine, intent, checkpoint_id(engine, "heron_move", actor.entity_id), actor, choice_id, sorted(paths), allow_decline=True, default="decline",
                 labels={k: "Move to " + k.removeprefix("cell:") for k in paths}, target_id=actor.entity_id, name=name,
                 prompt=f"{name}: move up to {feet} feet without provoking Opportunity Attacks?")
    if picked and picked[0] in paths:
        resolve_path(engine, actor, paths[picked[0]], PREFIX + 'crescent_body_integration',
                     feet=feet, intent=intent, provokes=False)


# ----------------------------------------------------------------------------------- Heron's Passing Cut and White Wing
@hook("after_hit")
def heron_hits(ctx: Any, target: Any, kind: str) -> None:
    engine, actor = ctx.engine, ctx.actor
    roles = _roles(engine, actor)
    if not roles or target is None or not target.active or target.team_id == actor.team_id or kind not in ("weapon", "weapon_melee") or not _polearm(ctx.typed):
        return
    stamp = _stamp(engine)
    mine = engine.state.current_actor_id == actor.entity_id
    if "integration" in roles and mine and actor.turn_flags.get("_round_passing_cut") != stamp and _moved(engine, actor) >= 10 \
            and int(actor.resources.get(STAMINA, 0) or 0) >= 1:
        _passing_cut(ctx, target)
    if not ctx.typed.get("granted_attack") and "white_wing" in roles and mine and target.active and actor.turn_flags.get("_round_white_wing") != stamp:
        _white_wing(ctx, target)


def _passing_cut(ctx: Any, target: Any) -> None:
    from .. import typed_executor as te
    from .needle import ask, cell_id, checkpoint_id
    from .rider_movement import forced_route

    engine, actor = ctx.engine, ctx.actor
    from .body_modes_scene_resources import effective_body_cl
    cl = effective_body_cl(engine, actor)
    count = 3 if cl >= 17 else 2 if cl >= 11 else 1
    labels = {"move": "Move 10 feet without provoking", "push": "Push it 10 feet", "pull": "Pull it 5 feet toward you (still within reach)",
              "damage": f"+ {count}d8 Slashing or Force"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "passing_cut", target.entity_id), actor, "choice:needle.herons_passing_cut", list(labels), labels=labels,
                 allow_decline=True, default="decline", target_id=target.entity_id, name="Heron's Passing Cut",
                 prompt=f"Heron's Passing Cut: your Polearm hit {target.display_name} on the move. 1 Stamina: choose one.")
    if not picked or picked[0] not in labels:
        return
    actor.turn_flags["_round_passing_cut"] = _stamp(engine)
    engine._spend_resource(actor, STAMINA, 1, PREFIX + "crescent_body_integration")
    from dataclasses import replace
    sub = replace(ctx,targets=[target],target=target,critical_hit=False)
    choice = picked[0]
    if choice == "move":
        _free_move(engine, ctx.intent, actor, 10, "choice:needle.passing_cut_move", "Heron's Passing Cut")
    elif choice == "push":
        te.run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away"}])
    elif choice == "pull":
        reach = int(ctx.action.range_ft or 5)
        found = engine.grid.reachable(target.position, movement_ft=5, occupied_cells=engine._occupied_cells_except(target.entity_id), difficult_cells=set(),
                                      footprint=engine._footprint(target))
        here = engine.grid.distance_ft(actor.position, target.position)
        paths = {cell_id(c): p for c, (p, cost) in found.items() if c != target.position and engine.grid.distance_ft(actor.position, c) < here
                 and engine.grid.distance_ft(actor.position, c) <= reach}
        if paths:
            pick = ask(engine, ctx.intent, checkpoint_id(engine, "passing_pull", target.entity_id), actor, "choice:needle.passing_cut_pull", sorted(paths),
                       labels={k: "Pull it to " + k.removeprefix("cell:") for k in paths}, target_id=target.entity_id,
                       prompt="Heron's Passing Cut: where do you pull it?")
            if pick and pick[0] in paths:
                forced_route(engine, target, paths[pick[0]], PREFIX + "crescent_body_integration", actor)
    else:
        te.run_effects(sub, [{"type": "extra_damage", "applies_to": "target", "dice": {"count": count, "sides": 8}, "damage_types": ["slashing", "force"],
                              "evidence": "Heron's Passing Cut"}])


def _white_wing(ctx: Any, target: Any) -> None:
    from .. import typed_executor as te
    from .needle import ask, cell_id, checkpoint_id
    from .rider_movement import step
    from .frightened_movement import path_allowed

    engine, actor = ctx.engine, ctx.actor
    half = int(engine._effective_speed(actor)) // 2
    paths = {cell_id(cell): route for cell, (route,cost) in _heron_routes(engine,actor,half,through=target.entity_id).items()}
    if not paths:
        return
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "white_wing", target.entity_id), actor, "choice:needle.white_wing_move", sorted(paths),
                 labels={k: "Pass through to " + k.removeprefix("cell:") for k in paths}, allow_decline=True, default="decline", target_id=target.entity_id,
                 name="White Wing Crosses the Reed Field", prompt=f"White Wing Crosses the Reed Field: pass through {target.display_name}'s space?")
    if not picked or picked[0] not in paths:
        return
    actor.turn_flags["_round_white_wing"] = _stamp(engine)
    from ..granted_movement import resolve_path
    route=paths[picked[0]]
    with _route_scope(engine,actor,through=target.entity_id):
        resolve_path(engine,actor,route,PREFIX+'white_wing_crosses_the_reed_field',feet=half,
                     intent=ctx.intent,provokes=True,ignore_oa_from=(target.entity_id,))
    if actor.position != route[-1]:return
    if not actor.active:
        return
    others = {c.entity_id: c for c in engine.state.actors.values() if c.active and c.team_id != actor.team_id and c.entity_id != target.entity_id
              and _polearm_attacks(engine, actor, c)}
    labels = {**({"attack": "One Polearm attack against a different creature in reach"} if others else {}), "push": f"Push {target.display_name} 10 feet",
              "prone": f"Knock {target.display_name} Prone if it fails a Strength save", "ac": "+ 2 AC until the start of your next turn"}
    choice = ask(engine, ctx.intent, checkpoint_id(engine, "white_wing_result", target.entity_id), actor, "choice:needle.white_wing_result", list(labels),
                 labels=labels, target_id=target.entity_id, name="White Wing Crosses the Reed Field", prompt="White Wing Crosses the Reed Field: choose one.")
    choice = choice[0] if choice and choice[0] in labels else "ac"
    sub = te.Context(engine, actor, ctx.action, ctx.intent, ctx.typed, [target], target, {})
    if choice == "attack":
        pick = ask(engine, ctx.intent, checkpoint_id(engine, "white_wing_other", actor.entity_id), actor, "choice:needle.white_wing_target", list(others),
                   labels={k: c.display_name for k, c in others.items()}, target_id=actor.entity_id, prompt="White Wing: attack whom?")
        other = others.get(pick[0] if pick else next(iter(others)))
        action = _pick(engine, ctx.intent, actor, other, "White Wing Crosses the Reed Field") if other is not None else None
        if action is not None:
            _granted(engine, actor, action, other, ctx.intent)
    elif choice == "push" and target.active:
        te.run_effects(sub, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 10, "direction": "away"}])
    elif choice == "prone" and target.active:
        te.run_effects(sub, [{"type": "save", "ability": "str", "evidence": "White Wing: Strength saving throw",
                              "on_fail": [{"type": "condition", "applies_to": "target", "condition": "prone"}], "on_success": []}])
    else:
        engine._add_modifier(actor, PREFIX + "white_wing_crosses_the_reed_field", "armor_class", "ADD", 2, "SELF", expires_on="START_OF_SOURCE_NEXT_TURN")


# ------------------------------------------------------------------------------------------------------ One-Legged Guard
def _pending(engine: Any) -> dict[str, Any]:
    return getattr(engine, "_typed_pending_attack", None) or {}


@hook("row_allowed")
def guard_needs_reach(engine: Any, actor: Any, row: dict[str, Any]) -> bool | None:
    """One-Legged Guard: only against a creature within your Polearm's reach (off your turn: no turn-only reach)."""
    if row.get("feature_id") != PREFIX + "one_legged_guard":
        return None
    if not _available(engine, actor, PREFIX + 'one_legged_guard'):
        return False
    attacker = engine.state.actors.get(str(_pending(engine).get("attacker") or ""))
    return None if attacker is not None and _polearm_attacks(engine, actor, attacker, opportunity=True) else False


@hook("ally_row_allowed")
def guard_needs_reach_ally(engine: Any, reactor: Any, subject: Any, row: dict[str, Any]) -> bool | None:
    if row.get("feature_id") != PREFIX + "one_legged_guard":
        return None
    if not _available(engine, reactor, PREFIX + 'one_legged_guard'):
        return False
    attacker = engine.state.actors.get(str(_pending(engine).get("attacker") or ""))
    near = engine._distance_actor_to_actor(reactor, subject) <= engine.grid.square_size_ft
    return None if near and attacker is not None and _polearm_attacks(engine, reactor, attacker, opportunity=True) else False


@effect("one_legged_guard")
def one_legged_guard(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .needle import ask, cell_id, checkpoint_id
    from .rider_movement import step
    from .frightened_movement import path_allowed

    engine, me, attacker = ctx.engine, ctx.actor, ctx.target
    protected = engine.state.actors.get(str(_pending(engine).get("target") or (ctx.typed or {}).get("protects") or me.entity_id))
    if attacker is None or protected is None:
        return
    action = _pick(engine, ctx.intent, me, attacker, "One-Legged Guard", opportunity=True)
    if action is None or not _granted(engine, me, action, attacker, ctx.intent) or not attacker.active:
        return
    labels = {"minus": f"- {int(me.proficiency_bonus or 2)} on its attack roll", "move": f"Move {protected.display_name} 5 feet",
              "push": f"Push {attacker.display_name} 5 feet", "deny": f"{attacker.display_name} cannot take Reactions until its next turn"}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "one_legged_guard", attacker.entity_id), me, "choice:needle.one_legged_guard", list(labels),
                 labels=labels, target_id=attacker.entity_id, name="One-Legged Guard", prompt="One-Legged Guard: your Polearm hit. Choose one.")
    choice = picked[0] if picked and picked[0] in labels else "minus"
    if choice == "minus":
        spec=ctx.typed.get('triggering_attack_spec')
        if spec is not None:
            spec['attack_bonus']=int(spec.get('attack_bonus') or 0)-int(me.proficiency_bonus or 2)
    elif choice == "move":
        found = engine.grid.reachable(protected.position, movement_ft=5, occupied_cells=engine._occupied_cells_except(protected.entity_id),
                                      difficult_cells=set(), footprint=engine._footprint(protected))
        # The protected creature chooses willing travel, so its fear (not the
        # guard's) must allow the route before the destination is offered.
        paths = {cell_id(c): p for c, (p, cost) in found.items()
                 if c != protected.position and path_allowed(engine, protected, p)}
        if paths:
            pick = ask(engine, ctx.intent, checkpoint_id(engine, "guard_move", protected.entity_id), protected,
                       "choice:needle.one_legged_guard_move", sorted(paths), labels={k: "Move to " + k.removeprefix("cell:") for k in paths},
                       allow_decline=True, default="decline", target_id=protected.entity_id, prompt="One-Legged Guard: step 5 feet out of the blow?")
            if pick and pick[0] in paths:
                from ..granted_movement import resolve_path
                resolve_path(engine,protected,paths[pick[0]],PREFIX+'one_legged_guard',feet=5,intent=ctx.intent,provokes=False)
            else:
                # Willingness belongs to the protected creature. Declining
                # movement returns the paid guard's choice to its owner.
                alternate=ask(engine,ctx.intent,checkpoint_id(engine,'guard_declined',attacker.entity_id),me,
                    'choice:needle.one_legged_guard_alternate',['minus','push','deny'],
                    labels={k:v for k,v in labels.items() if k!='move'},target_id=attacker.entity_id,
                    name='One-Legged Guard',prompt=f'{protected.display_name} declined movement. Choose another result for One-Legged Guard.')
                choice=(alternate or ['minus'])[0]
                if choice=='minus':
                    spec=ctx.typed.get('triggering_attack_spec')
                    if spec is not None:spec['attack_bonus']=int(spec.get('attack_bonus') or 0)-int(me.proficiency_bonus or 2)
                elif choice=='push':
                    te.run_effects(te.Context(engine,me,action,ctx.intent,action.parameters['typed'],[attacker],attacker,{}),
                        [{'type':'forced_movement','applies_to':'target','distance_ft':5,'direction':'away'}])
                else:
                    te.run_effects(te.Context(engine,me,action,ctx.intent,action.parameters['typed'],[attacker],attacker,{}),
                        [{'type':'reaction_denied','applies_to':'target','expires_on':'START_OF_TARGET_NEXT_TURN'}])
    elif choice == "push":
        te.run_effects(te.Context(engine, me, action, ctx.intent, (action.parameters or {}).get("typed") or {}, [attacker], attacker, {}),
                       [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}])
    else:
        te.run_effects(te.Context(engine, me, action, ctx.intent, (action.parameters or {}).get("typed") or {}, [attacker], attacker, {}),
                       [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}])

    if choice in ('move','push'):
        te.run_effects(ctx,[{'type':'negate_attack','if_out_of_reach':True,
                            'evidence':'One-Legged Guard moved the target outside the triggering melee attack reach.'}])


@hook("hit_response")
def guard_turns_the_blow(engine: Any, attacker: Any, target: Any, spec: Any, total: int, natural: int, effective_ac: int) -> Any:
    record = target.turn_flags.get("_one_legged_guard")
    if not record or record.get("attacker") != attacker.entity_id:
        return None
    target.turn_flags.pop("_one_legged_guard", None)
    if record.get("miss"):
        from ..attack_outcomes import unconditional_miss

        return unconditional_miss()
    minus = int(record.get("minus") or 0)
    if natural != 20 and total - minus < effective_ac:
        return effective_ac + minus, False  # equivalent threshold for this one attack; retain terminal eligibility
    return None


@hook("attack_resolved")
def guard_record_ends(ctx: Any, target: Any, hit: bool, attack_effect: Any) -> None:
    if target is not None and (target.turn_flags.get("_one_legged_guard") or {}).get("attacker") == ctx.actor.entity_id:
        target.turn_flags.pop("_one_legged_guard", None)


# ------------------------------------------------------------------------------------------------ Crescent Reaping Circle
@hook("compile_actions")
def reaping_circle_actions(info: dict[str, Any]) -> list[Any] | None:
    if REAPING not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import EconomyKind
    from .attack_lines import line_variants

    bases = [a for a in info["actions"] if a.economy == EconomyKind.ACTION and _polearm((a.parameters or {}).get("typed") or {})]
    actions=line_variants(info, REAPING, bases, replace=1, area=None, stamina=2, name="Crescent Reaping Circle", lead="reaping_circle")
    by_id={a.source_definition_id:a for a in bases}
    for action in actions:
        typed=action.parameters['typed'];base=by_id[typed['attack_line_of']]
        typed['heron_weapon_sides']=int(base.parameters['typed']['weapon']['damage']['sides'])
        typed['heron_con_mod']=int(info['mods'].get('CON',0))
    return actions or None


@effect("reaping_circle")
def reaping_circle(ctx: Any, row: dict[str, Any]) -> None:
    """The sweep: chosen hostile creatures within the Polearm's reach (with this turn's reach increases) save; you choose each failed
    creature's push or Reaction denial; then the asked 10-foot move."""
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    engine, actor = ctx.engine, ctx.actor
    from .reach_bonus import current_reach

    base_id = ctx.typed.get("attack_line_of")
    base = next((a for a in engine.action_catalog.values() if a.owner_id == actor.entity_id and a.source_definition_id == base_id), None)
    reach = current_reach(engine, actor, base) if base is not None else int(row.get("reach_ft") or 5)
    foes = {c.entity_id: c for c in sorted(engine.state.actors.values(), key=lambda a: a.entity_id) if c.active and c.team_id != actor.team_id
            and engine._distance_actor_to_actor(actor, c) <= reach and not engine.cover_from(engine._actor_volume(actor),actor.entity_id,c)['blocked']}
    if foes:
        chosen = ask(engine, ctx.intent, checkpoint_id(engine, "reaping_targets", actor.entity_id), actor, "choice:needle.reaping_circle_targets", list(foes),
                     labels={k: c.display_name for k, c in foes.items()}, minimum=1, maximum=len(foes), default_count=len(foes), allow_decline=True,
                     target_id=actor.entity_id, name="Crescent Reaping Circle", prompt="Crescent Reaping Circle: choose hostile creatures in Polearm reach. 2 Stamina, once per turn.") or []
        from ..gate2_runtime_models import DiceSpec
        sides=int(ctx.typed.get('heron_weapon_sides') or 4)
        damage_type=ask(engine,ctx.intent,checkpoint_id(engine,'reaping_type',actor.entity_id),actor,
            'choice:needle.heron_damage_type',['SLASHING','FORCE'],target_id=actor.entity_id,name='Crescent Reaping Circle',
            prompt='Crescent Reaping Circle: choose Slashing or Force for every target of this sweep.')
        damage_type=(damage_type or ['SLASHING'])[0]
        total=0
        for dice in (DiceSpec(count=1,sides=sides,modifier=int(ctx.typed.get('heron_con_mod') or 0)),DiceSpec(count=3,sides=8)):
            roll=engine.roller.roll(dice,actor_id=actor.entity_id,reason='DAMAGE:'+REAPING)
            engine._record_roll(roll);total+=roll.total
        damage={'type':'damage','applies_to':'target','flat':max(0,total),'damage_types':[damage_type]}
        for key in [k for k in foes if k in chosen]:
            foe=foes[key]
            save={'type':'save','ability':'dex','on_fail':[damage,{'type':'reaping_rider'}],
                  'on_success':[{'type':'half_damage'}]}
            te.run_effects(te.Context(engine,actor,ctx.action,ctx.intent,ctx.typed,[foe],foe,{}),[save])
    if actor.active:
        _free_move(engine, ctx.intent, actor, 10, "choice:needle.reaping_circle_move", "Crescent Reaping Circle")


@effect("reaping_rider")
def reaping_rider(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    foe = ctx.target
    if foe is None or not foe.active:
        return
    labels = {"push": f"Push {foe.display_name} 5 feet", "deny": f"{foe.display_name} cannot take Reactions until its next turn"}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "reaping_rider", foe.entity_id), ctx.actor, "choice:needle.reaping_circle_rider", list(labels),
                 labels=labels, target_id=foe.entity_id, name="Crescent Reaping Circle", prompt=f"Crescent Reaping Circle: {foe.display_name} failed its save. Choose one.")
    if (picked[0] if picked else "push") == "push":
        te.run_effects(ctx, [{"type": "forced_movement", "applies_to": "target", "distance_ft": 5, "direction": "away"}])
    else:
        te.run_effects(ctx, [{"type": "reaction_denied", "applies_to": "target", "expires_on": "START_OF_TARGET_NEXT_TURN"}])


# ------------------------------------------------------------------------------------------------- Moon over the Reed Sea
def _moon_paths(engine: Any, actor: Any):
    from ..paid_relocation import preserve_pending
    preserve_pending(engine,'_heron_moon_routes')
    key=(actor.entity_id,engine.state.event_sequence,actor.position.x,actor.position.y,actor.position.z,
         int(engine._effective_speed(actor)))
    cache=engine.__dict__.setdefault('_heron_moon_routes',{})
    if key not in cache:
        cache.clear()
        cache[key]={(cell.x,cell.y,cell.z): route for cell,(route,cost)
            in _heron_routes(engine,actor,2*int(engine._effective_speed(actor)),moon=True).items()}
    return cache[key]


@hook("compile_actions")
def moon_aim(info: dict[str, Any]) -> None:
    for action in info["actions"]:
        if ((action.parameters or {}).get("typed") or {}).get("source") == PREFIX + "moon_over_the_reed_sea" and action.target_kind == "CELL":
            action.parameters["any_cell"] = True  # this character's own action, being compiled
            action.parameters["moon_reed"] = True


@hook("candidate_allowed")
def moon_reachable(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if not (getattr(action, "parameters", None) or {}).get("moon_reed") or getattr(candidate, "destination", None) is None:
        return None
    return None if (candidate.destination.x, candidate.destination.y, candidate.destination.z) in _moon_paths(engine, actor) else False


@effect("moon_over_the_reed_sea")
def moon_over_the_reed_sea(ctx: Any, row: dict[str, Any]) -> None:
    from .needle import ask, checkpoint_id
    from .states import PREFIX as STATE, slug
    from ..granted_movement import resolve_path
    from ..target_knowledge import actors_for
    engine, actor = ctx.engine, ctx.actor
    aim=ctx.damage_cache.get('_checkpoint_aim') or ctx.destination
    path=_moon_paths(engine,actor).get((aim.x,aim.y,aim.z)) if aim is not None else None
    if path is None:return
    foes={a.entity_id:a for a in actors_for(engine,actor) if a.active and a.team_id!=actor.team_id}
    selected=ask(engine,ctx.intent,checkpoint_id(engine,'moon_reed',actor.entity_id),actor,
        'choice:needle.moon_over_the_reed_sea',list(foes),labels={k:a.display_name for k,a in foes.items()},
        minimum=1,maximum=len(foes),default_count=len(foes),allow_decline=True,target_id=actor.entity_id,
        name='Moon over the Reed Sea',prompt='Moon over the Reed Sea: choose hostile creatures to sweep when your route reaches them. '
            '7 Stamina, once per scene; each creature saves once.') if foes else []
    token=_MOON.set((engine,actor.entity_id,ctx,set(selected or []),set()))
    try:
        with _route_scope(engine,actor,moon=True):
            _moon_sweep(engine,actor)
            if len(path)>1:
                resolve_path(engine,actor,path,PREFIX+'moon_over_the_reed_sea',feet=2*int(engine._effective_speed(actor)),
                             intent=ctx.intent,provokes=False)
    finally:
        _MOON.reset(token)
    if actor.active:
        engine._apply_condition(actor,STATE+slug(STANCE),PREFIX+'moon_over_the_reed_sea',actor.entity_id,
            expires_on='START_OF_SOURCE_NEXT_TURN',data={'label':'Moon over the Reed Sea: +2 AC, +5 feet reach, one free Opportunity Attack until your next turn','name':STANCE})
        engine._add_modifier(actor,PREFIX+'moon_over_the_reed_sea','armor_class','ADD',2,'SELF',expires_on='START_OF_SOURCE_NEXT_TURN')
        actor.turn_flags['_round_moon_free_strike']=True


@effect("moon_push")
def moon_push(ctx: Any, row: dict[str, Any]) -> None:
    from .. import typed_executor as te
    from .needle import ask, checkpoint_id

    foe = ctx.target
    if foe is None or not foe.active:
        return
    options = ["15", "10", "5", "0"]
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "moon_push", foe.entity_id), ctx.actor, "choice:needle.moon_push_distance", options,
                 labels={o: f"Push {foe.display_name} {o} feet" if o != "0" else f"Leave {foe.display_name} in place" for o in options},
                 target_id=foe.entity_id, name="Moon over the Reed Sea", prompt=f"Moon over the Reed Sea: {foe.display_name} failed its save. Push it how far (up to 15 feet)?")
    feet = int(picked[0]) if picked and picked[0] in options else 15
    te.run_effects(ctx, [{"type": "forced_movement", "applies_to": "target", "distance_ft": feet, "direction": "away"}])


@hook("event")
def moon_free_strike(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """The stance's "first hostile creature entering your reach provokes one Opportunity Attack that does not consume your
    Reaction" (entering, not standing there as the reach grows)."""
    if event_type != "MOVEMENT_COMMITTED":
        return
    mover = engine.state.actors.get(kwargs.get("actor_id") or "")
    path = (kwargs.get("payload") or {}).get("path") or []
    if mover is None or not mover.active or len(path) < 2 or (kwargs.get("payload") or {}).get("teleport"):
        return
    from ..gate2_runtime_models import Position
    from .states import active

    for guard in engine.state.actors.values():
        if guard.team_id == mover.team_id or not guard.turn_flags.get("_round_moon_free_strike") or not active(engine, guard, STANCE):
            continue
        attacks = _polearm_attacks(engine, guard, mover, opportunity=True)
        if not attacks:
            continue
        reach = max(int(a.range_ft or 5) for a in attacks.values())
        start = Position.model_validate(path[0])
        if engine.grid.distance_between_cell_sets(engine._actor_cells(guard), engine._actor_cells(mover, start)) * engine.grid.square_size_ft <= reach:
            continue  # it was already within reach
        action = _pick(engine, _intent(engine), guard, mover, "Moon over the Reed Sea", optional=True, opportunity=True)
        guard.turn_flags.pop("_round_moon_free_strike", None)
        if action is not None:
            _granted(engine, guard, action, mover, _intent(engine))
        return

# Source-owned continuation on the public acquisition, wielding and Body seams.
@hook('body_mode_profiles')
def heron_scene_profile(bundle):
    owned = {r.get('feature_id') for r in bundle.get('typed_passives', [])}
    owned.update(((a.get('parameters') or {}).get('typed') or {}).get('source')
                 for a in bundle.get('action_catalog', []))
    if not owned.intersection(FEATURE_LEVELS):
        return None
    limits = sorted({cost[0] for action in bundle.get('action_catalog', [])
                     if ((action.get('parameters') or {}).get('typed') or {}).get('source') == PREFIX+'moon_over_the_reed_sea'
                     for cost in action.get('costs', []) if cost[0].startswith('resource:uses.')})
    return [{'source': SOURCE, 'name': 'White-Heron Crescent Body',
             'feature_levels': FEATURE_LEVELS, 'scene_limits': limits}]


@hook('cultivation_feature_available')
def heron_availability(engine, actor, feature):
    if feature not in FEATURE_LEVELS:
        return None
    # Do not call available here: it queries this same hook.
    from .body_modes_scene_resources import effective_body_cl, SUPPRESSION
    if effective_body_cl(engine, actor) < FEATURE_LEVELS[feature]:
        return False
    for condition in actor.conditions.values():
        d=condition.data
        if condition.condition_id == SUPPRESSION and (d.get('feature_id') == feature or
                (d.get('system') in ('body','all','tianxia.path.body_refining') and d.get('suppressed') == 1)):
            return False
    return None


@hook('weapon_proficiency')
def heron_proficiency(info):
    if PREFIX+'crescent_body_integration' not in info['owned_ids']:
        return None
    return True if _polearm({'source':info['weapon']['item_id'], 'weapon':info['weapon']}) else None


@hook('compile_actions', priority=-30)
def heron_profiles(info):
    if PREFIX+'crescent_body_integration' not in info['owned_ids']:
        return None
    for a in info['actions']:
        t=(a.parameters or {}).get('typed') or {}
        if not _polearm(t):continue
        t['heron_profile']={'con_attack': int(info['pb'])+int(info['mods'].get('CON',0))+int(t.get('magic_bonus') or 0),
            'cultivation_attack':int(info['numbers']['attack_bonus'])+int(t.get('magic_bonus') or 0),
            'con_damage':int(info['mods'].get('CON',0))+int(t.get('magic_bonus') or 0),
            'fist_permissions':[f for f in ('refined_iron_fist','heavenly_fist')
                if 'tianxia.path.body_refining.feature.'+f in info['owned_ids']]}


@hook('attack_spec_choice')
def heron_strike_profile(ctx, target, attack, spec, attack_index):
    if 'integration' not in _roles(ctx.engine,ctx.actor) or not _polearm(ctx.typed):return
    from ..weapon_delivery import weapon_identity
    if weapon_identity(ctx.engine,ctx.source,ctx.typed,ctx.action.parameters,owner_id=ctx.actor.entity_id) not in _ready(ctx.engine,ctx.actor):return
    profile=ctx.typed.get('heron_profile')
    if not profile:return
    from .needle import ask,checkpoint_id
    options={'Constitution':profile['con_attack'],'Cultivation':profile['cultivation_attack']}
    choice=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'heron_ability',target.entity_id,attack_index),ctx.actor,
        'choice:needle.heron_ability',list(options),labels={'Constitution':'Constitution for attack and damage',
            'Cultivation':'Cultivation Attack Modifier for attack; Constitution for damage'},
        preferred=[max(options,key=options.get)],target_id=target.entity_id,name='Crescent-Body Integration',
        prompt=f'Crescent-Body Integration: choose the attack modifier for {ctx.action.display_name} against {target.display_name}. '
               'Damage uses Constitution. No extra attack or cost.')
    if not choice:return
    typed=copy.deepcopy(spec['typed'])
    before=int(typed['numbers']['attack_bonus']);damage=int(typed['weapon']['damage'].get('modifier') or 0)
    spec['attack_bonus']+=options[choice[0]]-before
    if spec.get('damage') is not None:
        spec['damage']=spec['damage'].model_copy(update={'modifier':spec['damage'].modifier+profile['con_damage']-damage})
    typed['weapon']['damage']['modifier']=profile['con_damage']
    typed['numbers']['attack_bonus']=spec['attack_bonus'];typed['resolved_attack_ability']=choice[0]
    spec['typed']=typed


def _fist(engine,actor,typed,permission):
    if 'integration' not in _roles(engine,actor) or not _polearm(typed):return False
    if permission not in (typed.get('heron_profile') or {}).get('fist_permissions',[]):return False
    from .body_modes_scene_resources import available
    if not available(engine,actor,'tianxia.path.body_refining.feature.'+permission,
                     17 if permission=='heavenly_fist' else 5,requires_conscious=False):return False
    source=typed.get('source')
    return any(((a.parameters or {}).get('typed') or {}).get('source')==source for a in _ready(engine,actor).values())


@hook('attack_magical')
def integrated_polearm_magical(engine,actor_id,typed):
    actor=engine.state.actors.get(actor_id)
    if actor and any(_fist(engine,actor,typed,p) for p in ('refined_iron_fist','heavenly_fist')):return True


@hook('attack_damage_types')
def heavenly_polearm_types(ctx,attack,kinds):
    if _fist(ctx.engine,ctx.actor,ctx.typed,'heavenly_fist'):return list(dict.fromkeys([*kinds,'FORCE']))


@hook('attack_damage_type_choice')
def heavenly_polearm_choice(ctx,attack,target,kinds,attack_index):
    if not _fist(ctx.engine,ctx.actor,ctx.typed,'heavenly_fist'):return
    from .needle import ask,checkpoint_id
    chosen=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'heron_heavenly_type',target.entity_id,attack_index),ctx.actor,
        'choice:needle.heron_heavenly_type',kinds,target_id=target.entity_id,name='Heavenly Fist',
        prompt=f'Heavenly Fist: choose the damage type for your integrated Polearm hit against {target.display_name}. No extra cost.')
    return chosen[0] if chosen else None


@hook('opportunity_choices')
def heron_opportunity_profiles(engine,actor,default):
    if 'integration' not in _roles(engine,actor):return None
    return list(_polearm_attacks(engine,actor,None,opportunity=True).values()) or None


@hook('candidate_allowed')
def heron_action_guard(engine,actor,candidate,action):
    if action is None:return
    typed=(action.parameters or {}).get('typed') or {}
    source=typed.get('source')
    if source in (REAPING,PREFIX+'moon_over_the_reed_sea'):
        if not _available(engine,actor,source) or not _ready(engine,actor):return False
    if typed.get('heron_profile') and not _available(engine,actor,PREFIX+'crescent_body_integration'):
        if '#integrated_con' in action.source_definition_id:return False


@hook('damage_type_choice')
def heron_damage_choice(ctx,kinds,targets):
    if ctx.source not in FEATURE_LEVELS and not ('integration' in _roles(ctx.engine,ctx.actor) and _polearm(ctx.typed)):
        return
    if len(kinds)<2:return
    from .needle import ask,checkpoint_id
    target=targets[0] if targets else ctx.actor
    pick=ask(ctx.engine,ctx.intent,checkpoint_id(ctx.engine,'heron_damage',ctx.source,target.entity_id),ctx.actor,
        'choice:needle.heron_damage_type',kinds,target_id=target.entity_id,name='White-Heron Crescent Body',
        prompt=f'{ctx.action.display_name}: choose Slashing or Force damage for this use. No additional cost.')
    return pick[0] if pick else None


@hook('subpath_acquisition')
def acquire_heron(source, sheet):
    """Open School progression, with no Sphere or sibling grants."""
    if source != PREFIX.removesuffix('.feature.'):
        return None
    import hashlib
    from .qiweaving_common import rules_text
    paths = sheet.get('path_and_subpath') or {}
    identity = sheet.get('identity') or {}
    ids = set(identity.get('path_ids') or paths.get('path_record_ids') or [])
    if paths.get('path_record_id'):
        ids.add(paths['path_record_id'])
    profile_rows = paths.get('paths') or []
    body = next((p for p in profile_rows if isinstance(p, dict) and p.get('path_id') == 'tianxia.path.body_refining'), None)
    if body is not None:
        ids.add('tianxia.path.body_refining')
    legal = 'tianxia.path.body_refining' in ids if ids else identity.get('path') == 'Body Refining'
    level = int(identity.get('cultivation_level') or 1)
    if body is not None:
        # Existing Path profile fields: explicit effective CL is authoritative;
        # NS1R attainment otherwise caps the sheet's effective cultivation CL.
        attained = next((body[k] for k in ('effective_cl', 'attainment', 'owning_path_level') if k in body), None)
        if type(attained) is not int or attained < 0:
            legal, level = False, 0
        else:
            level = min(level, attained)
    elif profile_rows:
        legal, level = False, 0
    printed = rules_text()
    return {'name': 'White-Heron Crescent Body', 'legal': legal, 'effective_cl': level,
        'reasons': [] if legal else ['White-Heron Crescent Body requires an acquired Body Refining Path with a known effective level.'],
        'features': [{'id': PREFIX + name, 'minimum_cl': cl,
            'text_sha256': hashlib.sha256(printed[PREFIX + name].encode()).hexdigest()}
            for name, cl in [(name.removeprefix(PREFIX), level) for name, level in FEATURE_LEVELS.items()]]}



@hook('attack_resolution_scope')
def passing_cut_packet_scope(engine,attacker,target,spec,intent):
    if 'integration' not in _roles(engine,attacker) or not _polearm(spec.get('typed') or {}):return
    from ..attack_delivery import resolving
    return resolving(engine,attacker,target,spec,buffer_attached=True)


@hook('attack_packet_buffer_enabled')
def passing_cut_packet_enabled(engine,attacker,target,spec):
    if 'integration' in _roles(engine,attacker) and _polearm(spec.get('typed') or {}):return True


@hook('attack_payload_prepare')
def passing_cut_in_packet(ctx):
    if (ctx.target is not None and 'integration' in _roles(ctx.engine,ctx.actor)
            and _polearm(ctx.typed) and ctx.engine.state.current_actor_id==ctx.actor.entity_id
            and ctx.actor.turn_flags.get('_round_passing_cut')!=_stamp(ctx.engine)
            and _moved(ctx.engine,ctx.actor)>=10 and ctx.actor.resources.get(STAMINA,0)>=1):
        _passing_cut(ctx,ctx.target)


# Source-scoped permissions exist only while pricing/resolving the printed route.
# They are not anatomy, flight, persistent passage, or actor-supplied receipts.
from contextlib import contextmanager
from contextvars import ContextVar
_ROUTE = ContextVar('white_heron_route',default=None)


@contextmanager
def _route_scope(engine,actor,*,through=None,moon=False):
    token=_ROUTE.set((engine,actor.entity_id,through,moon))
    try:yield
    finally:_ROUTE.reset(token)


def _route_mode(engine,actor):
    value=_ROUTE.get()
    return value if value and value[:2]==(engine,actor.entity_id) else None


@hook('pass_through')
def heron_route_passage(engine,actor,occupant):
    mode=_route_mode(engine,actor)
    if mode and (occupant.entity_id==mode[2] or (mode[3] and occupant.team_id!=actor.team_id)):
        return 'difficult'


@hook('movement_step_capability')
def moon_surface_step(engine,actor,previous,destination,mode):
    scope=_route_mode(engine,actor)
    if not scope or not scope[3] or mode!='walk':return
    from ..roof_movement import faces
    if (destination.z==0 or engine.grid.roof_supported(destination,engine._footprint(actor))
            or faces(engine,actor,destination,include_virtual=False)):
        return True
    # Moon permits moving over liquids; ordinary height-zero ground routes
    # already carry the authoritative map's water and terrain prices.
    if previous.z==destination.z==0:return True
    return False


@hook('support_surface')
def moon_transit_support(engine,actor,position):
    scope=_route_mode(engine,actor)
    if scope and scope[3]:
        # Kept only until this activation's traversal completes; then falling
        # queries the real roof/liquid/ground and other actual support sources.
        return True


def _heron_routes(engine,actor,feet,*,through=None,moon=False):
    """Printed physical traversal with native per-edge geometry and costs.

    White Wing keeps the state 'has crossed this target' in the search so a
    cheaper route around it cannot hide a legal through route. Moon admits
    only real walls/ground for vertical travel. No query changes positions.
    """
    import heapq
    from itertools import product
    from ..gate2_runtime_models import Position
    from ..flight import step_allowed,step_cost,profile
    from ..voluntary_movement import path_allowed
    from ..granted_movement import Route
    from ..target_knowledge import actors_for
    if not actor.active or engine._effective_speed(actor)<=0:return {}
    target=engine.state.actors.get(through) if through else None
    target_cells=set(engine._actor_volume(target)) if target else set()
    occupied={p for other in actors_for(engine,actor) if other.active and other.entity_id!=actor.entity_id
              for p in engine._actor_volume(other)}
    modes=['walk']+(['fly'] if profile(engine,actor).speed_ft else [])
    out={}
    if moon:
        out[actor.position]=(Route((actor.position,),'walk'),0)
    for mode in modes:
        spatial=moon or bool(actor.position.z) or mode=='fly'
        directions=list(product((-1,0,1),repeat=3 if spatial else 2))
        directions=[d for d in directions if any(d)]
        start=(actor.position,False);costs={start:0};paths={start:(actor.position,)}
        queue=[(0,0,start)];serial=0
        with _route_scope(engine,actor,through=through,moon=moon):
            from ..creature_passage import geometry
            difficult=engine._hostile_difficult_cells(actor)|geometry(engine,actor,observed=True)[2]
            while queue:
                spent,_,key=heapq.heappop(queue);cell,passed=key
                if spent!=costs[key]:continue
                if spent and (passed or not through) and not (set(engine._actor_volume(actor,cell)) & occupied):
                    if cell not in out or spent<out[cell][1]:out[cell]=(Route(paths[key],mode),spent)
                if spent>=feet:continue
                for delta in directions:
                    dx,dy,*zs=delta;dz=zs[0] if zs else 0
                    nxt=Position(x=cell.x+dx,y=cell.y+dy,z=cell.z+dz)
                    if nxt.z<0 or nxt.z>actor.position.z+feet//engine.grid.square_size_ft or not engine.grid.in_bounds((nxt.x,nxt.y)):continue
                    if not step_allowed(engine,actor,cell,nxt,mode=mode,observed=True):continue
                    # Native voluntary restrictions include fear and bindings.
                    path=(*paths[key],nxt)
                    if not path_allowed(engine,actor,path):continue
                    amount=spent+step_cost(engine,actor,cell,nxt,mode,difficult)
                    crosses=passed or bool(set(engine._actor_volume(actor,nxt))&target_cells)
                    nextkey=(nxt,crosses)
                    if amount>feet or amount>=costs.get(nextkey,feet+1):continue
                    costs[nextkey]=amount;paths[nextkey]=path;serial+=1
                    heapq.heappush(queue,(amount,serial,nextkey))
    return out

_MOON=ContextVar('white_heron_moon_traversal',default=None)


def _moon_sweep(engine,actor):
    traversal=_MOON.get()
    if not traversal or traversal[:2]!=(engine,actor.entity_id):return
    _,_,ctx,chosen,affected=traversal
    from ..typed_executor import Context,run_effects
    from .effect_durations import token
    reach=max((a.range_ft or 5 for a in _polearm_attacks(engine,actor,None).values()),default=0)
    for key in sorted(chosen-affected):
        foe=engine.state.actors.get(key)
        if not foe or not foe.active or engine._distance_actor_to_actor(actor,foe)>reach:continue
        if engine.cover_from(engine._actor_volume(actor),actor.entity_id,foe)['blocked']:continue
        affected.add(key)
        run_effects(Context(engine,actor,ctx.action,ctx.intent,ctx.typed,[foe],foe,{}),[
            {'type':'save','ability':'dex','evidence':'Moon over the Reed Sea: Dexterity save',
             'on_fail':[{'type':'damage','applies_to':'target','dice':{'count':10,'sides':8},'damage_types':['slashing','force']},
                 {'type':'reaction_denied','applies_to':'target','expires_on':token('end',foe.entity_id,int(foe.turns_started)+1)},
                 {'type':'moon_push','up_to':15}],
             'on_success':[{'type':'half_damage','applies_to':'target'},
                 {'type':'reaction_denied','applies_to':'target','expires_on':'START_OF_TARGET_NEXT_TURN'},
                 {'type':'forced_movement','applies_to':'target','distance_ft':5,'direction':'away'}]}])


@hook('movement_step')
def moon_completed_step(engine,actor,previous,nxt,intent):
    _moon_sweep(engine,actor)
    _stance_entry(engine,actor,previous,nxt,intent)


@hook('forced_movement_step')
def moon_forced_entry(engine,actor,previous,nxt,intent):
    _stance_entry(engine,actor,previous,nxt,intent)


def _stance_entry(engine,mover,previous,nxt,intent):
    from .states import active
    for guard in engine.state.actors.values():
        if (guard.team_id==mover.team_id or not guard.turn_flags.get('_round_moon_free_strike')
                or not active(engine,guard,STANCE) or not _available(engine,guard,PREFIX+'moon_over_the_reed_sea')):continue
        attacks=_polearm_attacks(engine,guard,mover,opportunity=True)
        if not attacks:continue
        reach=max(int(a.range_ft or 5) for a in attacks.values())
        if engine.grid.distance_between_cell_sets(engine._actor_volume(guard),engine._actor_volume(mover,previous))*engine.grid.square_size_ft<=reach:continue
        # Only the first physical entry consumes this stance's one opportunity,
        # even when its owner declines the optional attack.
        guard.turn_flags.pop('_round_moon_free_strike',None)
        action=_pick(engine,intent,guard,mover,'Moon over the Reed Sea',optional=True,opportunity=True)
        if action is not None:_granted(engine,guard,action,mover,intent)
