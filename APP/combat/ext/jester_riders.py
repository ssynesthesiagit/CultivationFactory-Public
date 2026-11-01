"""Jester lines that were left to the GM (rider lane 9, 2026-09-29; owner: "i want everything we can automated").  Built on
combat/ext/jester.py (Set the Scene, the Foil marks, Deliver the Punchline, Flustered).  Owner's text first
(authority/typed_mechanics/rules_text.json, Sphere Compendium, Jester); nothing is invented.  Rows: feature block "lane9_jester"
(combat/rules/feature_blocks.d/riders_lane9.json).

  Strike the Fool       A Fine Display and Banquet Escape are the Punchlines of Strike the Fool ("fulfilled when the Foil makes an attack
  Punchlines            roll against you"; "Resolve after the attack roll"): the Jester's Reaction, only against its Foil (Strike the
                        Fool), decided once the roll is known -- ``hit_response`` for a hit, ``after_miss`` for a miss.
                        A Fine Display: a miss -> move up to 10 feet without Opportunity Attacks from the Foil, the Foil Flustered; a
                        hit -> the damage is reduced by PB.  Banquet Escape: move up to half your Speed without Opportunity Attacks from
                        the Foil; out of the attack's reach or range -> it misses; still hit -> the damage is reduced by 2d6 + CHA.
                        Either ends Set the Scene.  The reduction waits for the damage (``damage_pending``).
  False Opening         "At the start of your turn, choose to take -2 AC until the start of your next turn. The first time a creature
                        misses you with an attack roll before the penalty ends: regain Martial Focus if absent; move 5 feet without
                        provoking opportunity attacks from that creature."  A no-action choice offered before the turn's first action.
  Pratfall Exit         "When you fall Prone or deliberately drop Prone, move 5 feet without provoking opportunity attacks. Use Pratfall
                        Exit once per round."
  Focused Applause      "When your Punchline causes an attack to miss ... or makes a creature fall Prone, regain Martial Focus if absent":
                        Banquet Escape's miss, Applaud the Master / The Audience Chooses the Hero's miss (combat/ext/jester.py _settle),
                        a Punchline's Prone.
  Free Set the Scene    Grand Entrance ("When Initiative is rolled, use Set the Scene without spending a Bonus Action": once, on your first
                        turn -- the table has no moment between initiative and the first turn), Court of Words Without Offense and
                        Recluse-at-Court Incarnation ("use Set the Scene at the start of each of your turns without spending a Bonus
                        Action": once a turn while they last).  Mock-Praise Scripture: Set the Scene with two Propositions.
  Recluse-at-Court      up to three Foils (combat/ext/jester.py run_foil asks ``keeps_foils``); when a Foil becomes Flustered, Martial
                        Focus returns if absent.
  Court-Hermit Step     Dongfang Shuo's Court-Hermit Step: after its move, Hide if the Hide action's rules allow it there.
  Ultimatums            Reductio ad Absurdum and Mocking Heaven's Decree: the technique's user chooses -- abandon it (its costs come back
                        and it does nothing) or resolve it and become Flustered (Reductio: and take 4d8 Psychic; Mocking Heaven: or let
                        an ally of the Jester take the Dodge action).
  Thrown Slipper        an improvised-weapon ranged attack at the Foil, then the menu's choice (Flustered, -10 Speed, an ally steps 5 feet).


Shared helpers used by jester: keeps_foils supplies the permitted scene count and focused_applause restores Martial Focus after the printed trigger. The owning row gates both helpers; no core behavior is patched.
"""

from __future__ import annotations

from ..paid_relocation import activation

import dataclasses
from typing import Any

from . import effect, hook, note
from .needle import CHOICE, ask, checkpoint_id

BLOCK = "lane9_jester"
T = "tianxia.talent.jester."
FOCUS = "resource:core.martial_focus"
PARKED = "_jester_parked"            # {(attacker, jester): damage reduction waiting for the hit's damage}
FALSE_OPENING = "condition:typed.false_opening"
PROPOSITIONS = ("Come Closer", "Strike the Fool", "Ignore the Fool", "Show Your Hand")


@hook("compile_block")
def compile_rows(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != BLOCK:
        return None
    return [{**row, "block": BLOCK, "kind": spec.get("kind"), "pb": int(numbers.get("pb") or 2), "key_mod": int(numbers.get("key_mod") or 0),
             "keeps_compiling": bool(spec.get("keeps_compiling")),
             **({"auto65": True} if spec.get("auto65") else {})}]


def rows(engine: Any, actor: Any, kind: str) -> list[dict[str, Any]]:
    return [row for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, [])
            if row.get("block") == BLOCK and row.get("kind") == kind]


def _cha(engine: Any, actor: Any) -> int:
    for bundle in getattr(engine, "typed_bundle_documents", ()) or ():
        if bundle.get("actor_id") == actor.entity_id:
            for row in bundle.get("typed_reactions") or []:
                if isinstance(row.get("ability_mods"), dict):
                    return int(row["ability_mods"].get("CHA") or 0)
    return 0


def regain_focus(engine: Any, jester: Any, why: str) -> None:
    if FOCUS in jester.resources and jester.resources.get(FOCUS, 0) < 1 and jester.resource_maximums.get(FOCUS, 0) >= 1:
        engine._gain_resource(jester, FOCUS, 1, why)


def focused_applause(engine: Any, jester: Any) -> None:
    """Focused Applause: a Punchline made an attack miss, or a creature fall Prone."""
    if jester is not None and rows(engine, jester, "focused_applause"):
        regain_focus(engine, jester, T + "focused_applause")


def _react_ctx(engine: Any, jester: Any, other: Any, feature: str, name: str) -> Any:
    from .. import typed_reactions

    return typed_reactions._generic_context(engine, jester, other, {"feature_id": feature, "name": name, "effects": [], "numbers": {}})


def _step_away(engine: Any, jester: Any, foil: Any, feet: Any, feature: str, name: str) -> None:
    from ..typed_executor import run_effects

    run_effects(_react_ctx(engine, jester, foil, feature, name),
                [{"type": "reaction_move", "direction": "away", "distance_ft": feet, "no_opportunity_attacks": True,
                  "evidence": f"{name}: move without provoking opportunity attacks from the Foil"}])


def _end_scene(engine: Any, jester: Any, foil: Any, feature: str, name: str) -> None:
    from ..typed_executor import run_effects

    run_effects(_react_ctx(engine, jester, foil, feature, name), [{"type": "jester_end_scene"}])
    # Native Strike-the-Fool delivery must publish the same completed reaction
    # as ordinary typed Punchlines, after its effects and scene cleanup.
    engine._append_event('REACTION_RESOLVED', feature, actor_id=jester.entity_id,
        target_ids=(foil.entity_id,), payload={'checkpoint': 'JESTER_PUNCHLINE'})


def _flustered(engine: Any, jester: Any, foil: Any, feature: str, name: str) -> None:
    from ..typed_executor import run_effects

    run_effects(_react_ctx(engine, jester, foil, feature, name), [{"type": "flustered", "applies_to": "target"}])


# ------------------------------------------------------------------------------------------------ Strike the Fool Punchlines
def _strike_punchlines(engine: Any, jester: Any, foil: Any) -> list[str]:
    from .. import typed_reactions
    from ..typed_executor import bears_mark
    from .jester import foil_mark

    if foil is None or not bears_mark(foil, jester.entity_id, foil_mark("Strike the Fool")):
        return []
    if not typed_reactions._can_react(engine, jester, _punchline_row(rows(engine, jester, "fine_display") or rows(engine, jester, "banquet_escape"))):
        return []
    return [kind for kind in ("fine_display", "banquet_escape") if rows(engine, jester, kind)]


def _punchline_row(found: Any, feature: str | None = None) -> dict[str, Any] | None:
    """The reaction row a Strike the Fool Punchline is delivered as (its Foil mark makes it a Punchline for the shared
    reaction economy, combat/ext/reaction_economy.py: "deliver one Punchline per round without spending your Reaction").
    Keep its source ID/mark contract stable; name is the printed player-facing talent name, not an ID suffix."""
    from .jester import foil_mark

    feature = feature or (str((found or [{}])[0].get("feature_id") or "") if found else "")
    if not feature:
        return None
    # Keep existing delivery source IDs stable; fine_display is the historical
    # delivery alias for the printed A Fine Display talent (a_fine_display).
    name = {T + "fine_display": "A Fine Display", T + "a_fine_display": "A Fine Display",
            T + "banquet_escape": "Banquet Escape"}.get(feature) or str((found or [{}])[0].get("name") or "Punchline")
    return {"feature_id": feature, "name": name, "requires_mark": foil_mark("Strike the Fool")}


def _deliver(engine: Any, jester: Any, foil: Any, feature: str) -> None:
    from .. import typed_reactions

    row = _punchline_row(None, feature)
    typed_reactions._open(engine, row, jester, (foil.entity_id,), "JESTER_PUNCHLINE")
    typed_reactions.spend_reaction(engine, jester, row)


@hook("hit_response")
def strike_the_fool_hit(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> Any:
    kinds = _strike_punchlines(engine, target, attacker)
    if not kinds:
        return None
    labels = {"fine_display": f"A Fine Display: reduce the damage by {rows(engine, target, 'fine_display')[0]['pb']}" if "fine_display" in kinds else "",
              "banquet_escape": "Banquet Escape: move up to half your Speed; out of its reach the attack misses, else 2d6 + Charisma less damage"}
    labels = {kind: labels[kind] for kind in kinds}
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "STRIKE_THE_FOOL_HIT", target.entity_id, attacker.entity_id),
                 target, CHOICE + "strike_the_fool", list(labels), labels=labels, preferred=["banquet_escape"] if "banquet_escape" in kinds else kinds[:1],
                 allow_decline=True, target_id=target.entity_id,
                 prompt=f"Strike the Fool: {attacker.display_name}'s attack ({total}) hits you. Deliver a Punchline?")
    if not picked:
        return None
    kind = picked[0]
    feature = T + kind
    with activation(engine, target, feature):
        _deliver(engine, target, attacker, feature)
        parked = engine.__dict__.setdefault(PARKED, {})
        if kind == "fine_display":
            parked[(attacker.entity_id, target.entity_id)] = int(rows(engine, target, "fine_display")[0]["pb"])
            note(engine, feature, target, f"A Fine Display: {target.display_name} takes {parked[(attacker.entity_id, target.entity_id)]} less damage from the hit.")
        else:
            _step_away(engine, target, attacker, "half_speed", feature, "Banquet Escape")
            reach = int(spec.get("range_ft") or spec.get("reach_ft") or 5)
            if engine._distance_actor_to_actor(attacker, target) > reach:
                note(engine, feature, target, f"Banquet Escape: {target.display_name} is out of the attack's reach; it misses.")
                _end_scene(engine, target, attacker, feature, "Banquet Escape")
                focused_applause(engine, target)
                from ..attack_outcomes import unconditional_miss

                return unconditional_miss()
            from ..gate2_runtime_models import DiceSpec

            rolled = engine.roller.roll(DiceSpec(count=2, sides=6, modifier=_cha(engine, target)), actor_id=target.entity_id, reason=f"DAMAGE_REDUCTION:{feature}")
            engine._record_roll(rolled)
            parked[(attacker.entity_id, target.entity_id)] = max(0, int(rolled.total))
            note(engine, feature, target, f"Banquet Escape: the attack still hits; its damage is reduced by {max(0, int(rolled.total))}.")
        _end_scene(engine, target, attacker, feature, kind)
        return None


@hook("damage_pending")
def punchline_reduction(engine: Any, target: Any, pending: int, source_definition_id: Any, source_actor_id: Any) -> int | None:
    parked = engine.__dict__.get(PARKED) or {}
    amount = parked.pop((source_actor_id, target.entity_id), None)
    if amount is None:
        return None
    from .attack_reduction import remember
    return remember(engine, target, pending, max(0, int(pending) - int(amount)), [(int(amount), ())])


@hook("after_hit")
def clear_parked(ctx: Any, target: Any, kind: str) -> None:
    (ctx.engine.__dict__.get(PARKED) or {}).pop((ctx.actor.entity_id, target.entity_id), None)


@hook("after_miss")
def strike_the_fool_miss(ctx: Any, target: Any) -> None:
    engine, foil = ctx.engine, ctx.actor
    (engine.__dict__.get(PARKED) or {}).pop((foil.entity_id, target.entity_id), None)
    kinds = _strike_punchlines(engine, target, foil)
    if not kinds:
        return
    labels = {"fine_display": "A Fine Display: move up to 10 feet (no Opportunity Attacks from the Foil); the Foil is Flustered",
              "banquet_escape": "Banquet Escape: move up to half your Speed (no Opportunity Attacks from the Foil)"}
    labels = {kind: labels[kind] for kind in kinds}
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "STRIKE_THE_FOOL_MISS", target.entity_id, foil.entity_id), target, CHOICE + "strike_the_fool",
                 list(labels), labels=labels, preferred=["fine_display"] if "fine_display" in kinds else kinds[:1], allow_decline=True,
                 target_id=target.entity_id, prompt=f"Strike the Fool: {foil.display_name}'s attack misses you. Deliver a Punchline?")
    if not picked:
        return
    kind = picked[0]
    feature = T + kind
    with activation(engine, target, feature):
        _deliver(engine, target, foil, feature)
        if kind == "fine_display":
            _step_away(engine, target, foil, 10, feature, "A Fine Display")
            _flustered(engine, target, foil, feature, "A Fine Display")
        else:
            _step_away(engine, target, foil, "half_speed", feature, "Banquet Escape")
        _end_scene(engine, target, foil, feature, kind)


# ------------------------------------------------------------------------------------------------ False Opening, Pratfall Exit
@hook("compile_action")
def ridiculous_weapon_stats(action: Any, info: dict[str, Any]) -> Any:
    """Ridiculous Weapon uses higher Charisma for improvised attack and damage.

    The general compile_action seam supplies basic actions after compilation.
    Other abilities/actions and characters without this talent stay inert.
    """
    if T + "ridiculous_weapon" not in info["owned_ids"] or not action.source_definition_id.endswith((".improvised.attack", ".improvised.thrown")):
        return None
    import copy

    params = copy.deepcopy(action.parameters)
    typed = params["typed"]
    modifier = max(int(info["mods"].get("STR", 0)), int(info["mods"].get("CHA", 0)))
    old = int(typed["weapon"]["damage"]["modifier"])
    typed["weapon"]["damage"]["modifier"] = modifier
    typed["numbers"]["attack_bonus"] += modifier - old
    count = int(typed["effects"][0].get("count") or 1)
    params["expected_damage"] += count * (modifier - old)
    return action.model_copy(update={"parameters": params})


@hook("compile_actions")
def actions(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    owned = set(info.get("owned_ids") or [])
    out: list[Any] = []

    def make(sid: str, name: str, economy: str, kind: str, effects: list[dict[str, Any]], tag: str, range_ft: int | None = None, **extra: Any) -> Any:
        typed = {"effects": effects, "numbers": dict(info["numbers"]), "duration": {"kind": "instant"}, "riders": [], "source": tag, "coverage": "FULL"}
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.jester.{sid}", display_name=name, owner_id=info["actor_id"],
                                economy=EconomyKind[economy], resolution_kind="TYPED", target_kind=kind, range_ft=range_ft,
                                parameters={"typed": typed, "expected_damage": 0, "player_only": True, "jester_extra": sid.split(".")[0], **extra})

    if T + "false_opening" in owned:
        out.append(make("false_opening", "False Opening (-2 AC)", "NONE", "SELF", [{"type": "jester_false_opening"}], T + "false_opening",
                        description="At the start of your turn: -2 AC until the start of your next turn; the first creature to miss you gives back "
                                    "Martial Focus and lets you step 5 feet away from it."))
    free = [key for key in ("grand_entrance", "court_of_words_without_offense", "recluse_at_court_incarnation") if T + key in owned]
    if free:
        for proposition in PROPOSITIONS:
            out.append(make(f"free_scene.{proposition.lower().replace(' ', '_')}", f"Set the Scene (free): {proposition}", "NONE", "HOSTILE_ENTITY",
                            [{"type": "jester_foil", "proposition": proposition}], "JESTER_BASE_SET_THE_SCENE", 60, jester_free=free))
    if T + "mock_praise_scripture" in owned and int(info["numbers"].get("cl") or 1) >= 5:
        for index, first in enumerate(PROPOSITIONS):
            for second in PROPOSITIONS[index + 1:]:
                out.append(make(f"mock_praise.{first.lower().replace(' ', '_')}.{second.lower().replace(' ', '_')}",
                                f"Set the Scene (Mock-Praise): {first} + {second}", "BONUS_ACTION", "HOSTILE_ENTITY",
                                [{"type": "jester_foil_pair", "propositions": [first, second]}], "JESTER_BASE_SET_THE_SCENE", 60))
    return out or None


@hook("candidate_allowed")
def extra_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = (getattr(action, "parameters", None) or {}) if action is not None else {}
    kind = params.get("jester_extra")
    if kind is None:
        return None
    if kind == "false_opening":
        fresh = actor.action_available and actor.bonus_action_available and actor.movement_remaining_ft >= engine._effective_speed(actor)
        return None if fresh and not actor.turn_flags.get("jester_false_opening") and engine.state.current_actor_id == actor.entity_id else False
    if kind == "free_scene":
        return None if free_scene_open(engine, actor, params.get("jester_free") or []) else False
    return None


def free_scene_open(engine: Any, actor: Any, sources: list[str]) -> str | None:
    """Which talent lets the actor Set the Scene without a Bonus Action now, or None."""
    if actor.turn_flags.get("jester_free_scene"):
        return None
    if "grand_entrance" in sources and int(engine.state.round_number or 0) <= 1 and not actor.turn_flags.get("jester_round_grand_entrance"):
        return "grand_entrance"
    for key in ("court_of_words_without_offense", "recluse_at_court_incarnation"):
        if key in sources and active(engine, actor, key):
            return key
    return None


def active(engine: Any, actor: Any, key: str) -> bool:
    """Court of Words (a zone of its own) or Recluse-at-Court (its minute-long modifiers) is up for this Jester."""
    suffix = T + key
    if any(zone.active and zone.owner_id == actor.entity_id and str(zone.source_definition_id).endswith(suffix) for zone in engine.state.zones.values()):
        return True
    return any(str(modifier.source_definition_id).endswith(suffix) for modifier in actor.modifiers.values()) or \
        any(str(condition.source_definition_id).endswith(suffix) for condition in actor.conditions.values())


@hook("technique_used")
def free_scene_used(ctx: Any) -> None:
    params = ctx.action.parameters or {}
    if params.get("jester_extra") != "free_scene":
        return
    which = free_scene_open(ctx.engine, ctx.actor, params.get("jester_free") or [])
    ctx.actor.turn_flags["jester_free_scene"] = True
    if which == "grand_entrance":
        ctx.actor.turn_flags["jester_round_grand_entrance"] = True


@effect("jester_false_opening")
def jester_false_opening(ctx: Any, eff: dict[str, Any]) -> None:
    ctx.actor.turn_flags["jester_false_opening"] = True
    ctx.engine._apply_condition(ctx.actor, FALSE_OPENING, ctx.source, ctx.actor.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                                data={"label": "False Opening: -2 AC until the start of your next turn"})
    ctx.rider(f"{ctx.actor.display_name} offers a False Opening: -2 AC until the start of their next turn.")


@hook("ac")
def false_opening_ac(engine: Any, target: Any) -> int | None:
    return -2 if target.conditions and any(row.condition_id == FALSE_OPENING for row in target.conditions.values()) else None


@hook("after_miss")
def false_opening_miss(ctx: Any, target: Any) -> None:
    iid = next((iid for iid, row in target.conditions.items() if row.condition_id == FALSE_OPENING), None)
    if iid is None or target.turn_flags.get(f"jester_round_false_opening_used:{iid}"):
        return
    target.turn_flags[f"jester_round_false_opening_used:{iid}"] = True
    regain_focus(ctx.engine, target, T + "false_opening")
    _step_away(ctx.engine, target, ctx.actor, 5, T + "false_opening", "False Opening")


@effect("jester_foil_pair")
def jester_foil_pair(ctx: Any, eff: dict[str, Any]) -> None:
    """Mock-Praise Scripture: "choose two different Propositions. The first one fulfilled permits one compatible Punchline and ends Set the
    Scene normally" (combat/ext/jester.py jester_end_scene takes every Foil mark off)."""
    from ..typed_executor import block_mark
    from .jester import drop_foils, foil_mark

    first, second = (list(eff.get("propositions") or []) + ["", ""])[:2]
    if ctx.target is None or first not in PROPOSITIONS or second not in PROPOSITIONS:
        return
    drop_foils(ctx)
    for proposition in (first, second):
        block_mark(ctx, {"type": "mark", "mark": foil_mark(proposition), "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"}})
    ctx.rider(f"{ctx.target.display_name} is your Foil: {first} or {second} (Mock-Praise).")


def keeps_foils(ctx: Any) -> bool:
    """Recluse-at-Court Incarnation: "maintain up to three Foils at once" -- called by combat/ext/jester.py run_foil.  True when the older
    Foils stay (fewer than three other creatures bear one); at three, the oldest Foil's marks come off."""
    from ..typed_executor import MARK_PREFIX

    engine, jester = ctx.engine, ctx.actor
    if not active(engine, jester, "recluse_at_court_incarnation"):
        return False
    suffix = f".{jester.entity_id}"
    held = [(min(row.applied_sequence for row in other.conditions.values() if row.condition_id.startswith(MARK_PREFIX + "foil_") and row.condition_id.endswith(suffix)), other)
            for other in engine.state.actors.values() if other is not ctx.target
            and any(row.condition_id.startswith(MARK_PREFIX + "foil_") and row.condition_id.endswith(suffix) for row in other.conditions.values())]
    if len(held) >= 3:
        _, oldest = min(held, key=lambda pair: pair[0])
        for iid, row in list(oldest.conditions.items()):
            if row.condition_id.startswith(MARK_PREFIX + "foil_") and row.condition_id.endswith(suffix):
                engine._remove_condition(oldest, row.condition_id, ctx.source)
    if ctx.target is not None:
        for row in list(ctx.target.conditions.values()):
            if row.condition_id.startswith(MARK_PREFIX + "foil_") and row.condition_id.endswith(suffix):
                engine._remove_condition(ctx.target, row.condition_id, ctx.source)  # its new Proposition replaces its old one
    return True


@hook("event")
def jester_events(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "CONDITION_APPLIED":
        return
    condition = str((kwargs.get("payload") or {}).get("condition_id") or "")
    source = str(engine.events[-1].source_definition_id if engine.events else "")
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        if target is None:
            continue
        if condition.endswith(".prone"):
            _pratfall(engine, target)
            jester = engine.state.actors.get(kwargs.get("actor_id") or "")
            if jester is not None and T in source and jester is not target:
                focused_applause(engine, jester)  # a Punchline made a creature fall Prone
        elif condition == "condition:typed.flustered":
            _recluse_focus(engine, target)


def _pratfall(engine: Any, jester: Any) -> None:
    """Pratfall Exit: falling or dropping Prone -> a 5-foot move without Opportunity Attacks, once per round."""
    if not rows(engine, jester, "pratfall_exit") or not jester.active or jester.turn_flags.get("jester_round_pratfall") == engine.state.round_number:
        return
    foes = [other for other in engine.state.actors.values() if other.active and other.team_id != jester.team_id]
    if not foes:
        return
    jester.turn_flags["jester_round_pratfall"] = engine.state.round_number
    nearest = min(foes, key=lambda other: engine._distance_actor_to_actor(jester, other))
    _step_away(engine, jester, nearest, 5, T + "pratfall_exit", "Pratfall Exit")


def _recluse_focus(engine: Any, foil: Any) -> None:
    """Recluse-at-Court Incarnation: "when a Foil becomes Flustered, regain Martial Focus if absent"."""
    from ..typed_executor import MARK_PREFIX

    for jester in engine.state.actors.values():
        suffix = f".{jester.entity_id}"
        if any(row.condition_id.startswith(MARK_PREFIX + "foil_") and row.condition_id.endswith(suffix) for row in foil.conditions.values()) \
                and active(engine, jester, "recluse_at_court_incarnation"):
            regain_focus(engine, jester, T + "recluse_at_court_incarnation")


# ------------------------------------------------------------------------------------------------ Court-Hermit Step, ultimatums
@effect("jester_hide_after")
def jester_hide_after(ctx: Any, eff: dict[str, Any]) -> None:
    """Dongfang Shuo's Court-Hermit Step: "Hide as part of this Reaction if you end Heavily Obscured or behind Total Cover and otherwise
    meet the 2024 Hide requirements" (combat/stealth.py can_hide is those requirements on this table)."""
    from .. import stealth

    actor = ctx.actor
    if not stealth.can_hide(ctx.engine, actor):
        return
    bonus = next((int(((row.parameters or {}).get("typed") or {}).get("effects", [{}])[0].get("bonus") or 0)
                  for row in ctx.engine.action_catalog.values() if row.owner_id == actor.entity_id
                  and ((row.parameters or {}).get("typed") or {}).get("effects", [{}])[0].get("type") == "hide"), 0)
    if stealth.hide(ctx.engine, actor, bonus, ctx.source):
        ctx.rider(f"{actor.display_name} hides at the end of the Court-Hermit Step.")


@effect("jester_ultimatum")
def jester_ultimatum(ctx: Any, eff: dict[str, Any]) -> None:
    """The technique's user chooses (Reductio ad Absurdum; Mocking Heaven's Decree): abandon the technique "before paying its cost or
    expending its use" (its costs come back and it does nothing), or resolve it and become Flustered -- Reductio: and take 4d8 Psychic;
    Mocking Heaven: or let one ally of the Jester take the Dodge action.  The AI resolves it (it has already committed)."""
    from ..typed_executor import run_effects

    engine, foil = ctx.engine, ctx.target
    pending = getattr(engine, "_typed_pending_technique", None) or {}
    if foil is None or pending.get("actor") != foil.entity_id:
        return
    options = {"abandon": "Abandon the technique (its cost is not paid)",
               "flustered": "Resolve it and become Flustered" + (" and take 4d8 Psychic damage" if eff.get("damage") else "")}
    allies = [row for row in engine.state.actors.values() if row.active and row.team_id == ctx.actor.team_id and row is not ctx.actor]
    if eff.get("ally_dodge") and allies:
        options["ally"] = f"Resolve it and let {allies[0].display_name} take the Dodge action"
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "JESTER_ULTIMATUM", ctx.actor.entity_id, foil.entity_id), foil, CHOICE + "jester_ultimatum",
                 list(options), labels=options, preferred=["flustered"], target_id=foil.entity_id,
                 prompt=f"{ctx.actor.display_name}'s {ctx.action.display_name}: choose.")
    choice = picked[0] if picked else "flustered"
    if choice == "abandon":
        started = engine.__dict__.get("_jester_technique") or {}
        if started.get("actor") == foil.entity_id:
            for resource, amount in started.get("costs") or ():
                if resource in foil.resources and int(amount) > 0:
                    engine._gain_resource(foil, resource, int(amount), ctx.source)  # "before paying its cost or expending its use"
        engine._typed_countered = True
        ctx.rider(f"{foil.display_name} abandons the technique.")
        return
    if choice == "ally" and allies:
        engine._apply_condition(allies[0], "condition:core.dodge", ctx.source, ctx.actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN")
        ctx.rider(f"{allies[0].display_name} takes the Dodge action.")
        return
    rows_ = [eff["flustered_row"]] if isinstance(eff.get("flustered_row"), dict) else [{"type": "flustered", "applies_to": "target"}]
    if eff.get("damage"):
        rows_.append({"type": "damage", "dice": {"count": 4, "sides": 8}, "damage_types": ["psychic"], "applies_to": "target",
                      "evidence": "Reductio ad Absurdum: 4d8 Psychic damage"})
    run_effects(ctx, rows_)


@hook("technique_start")
def remember_technique(engine: Any, actor: Any, action: Any) -> None:
    """What a technique cost as it started, for an ultimatum's "abandon ... before paying its cost" (the reaction runs after it is paid)."""
    engine.__dict__["_jester_technique"] = {"actor": actor.entity_id, "costs": [(resource, int(amount)) for resource, amount in action.costs]}
    return None


@effect("jester_dodge")
def jester_dodge(ctx: Any, eff: dict[str, Any]) -> None:
    """"Take the Dodge action as part of this Reaction": the engine's own Dodge condition, until the start of your next turn."""
    ctx.engine._apply_condition(ctx.actor, "condition:core.dodge", ctx.source, ctx.actor.entity_id, expires_on="START_OF_SELF_NEXT_TURN")
    ctx.rider(f"{ctx.actor.display_name} takes the Dodge action.")


@effect('jester_borrowed_action')
def borrowed_action(ctx: Any, eff: dict[str, Any]) -> None:
    """New Borrowed Action packets choose legal ordinary actions through transactional transport."""
    from ..typed_executor import condition_rules, run_effects
    from .. import stealth
    rules = condition_rules(ctx.actor)
    options = {'dodge': 'Dodge until the start of your next turn'}
    if not any(r.get('no_dash') for r in rules):
        options['dash'] = 'Dash: gain extra movement equal to your Speed this turn'
    if not any(r.get('no_disengage') for r in rules):
        options['disengage'] = 'Disengage: no Opportunity Attacks for your movement this turn'
    if stealth.can_hide(ctx.engine, ctx.actor):
        options['hide'] = 'Hide using the normal hiding requirements'
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'borrowed_action', ctx.actor.entity_id, ctx.target.entity_id),
        ctx.actor, CHOICE+'borrowed_action', list(options), labels=options, preferred=['dodge'],
        name='Borrowed Action, Honest Consequence',
        prompt=f'Borrowed Action, Honest Consequence: {ctx.target.display_name} fulfilled your Proposition. Choose an ordinary action as part of this Reaction; no additional Action or resource cost.')
    if not selected:
        return
    if selected[0] == 'dash':
        run_effects(ctx, [{'type':'movement', 'applies_to':'self', 'distance_ft':'speed'}])
    elif selected[0] == 'disengage':
        ctx.actor.turn_flags['disengaged'] = True
        ctx.rider(f'{ctx.actor.display_name} Disengages: movement does not provoke Opportunity Attacks this turn.')
    elif selected[0] == 'hide':
        jester_hide_after(ctx, {})
    else:
        jester_dodge(ctx, {})


@effect('jester_ally_advantage')
def absurd_ally_advantage(ctx: Any, eff: dict[str, Any]) -> None:
    """Absurd Agreement: the owner selects an ally that saw the technique, with target-specific consumption."""
    from ..target_knowledge import can_see
    from .effect_durations import token
    foil = ctx.target
    if foil is None:
        return
    allies = [a for a in ctx.engine.state.actors.values() if a.active and a is not ctx.actor
              and a.team_id == ctx.actor.team_id and can_see(ctx.engine, a, foil)]
    if not allies:
        return
    selected = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine,'absurd_ally',ctx.actor.entity_id,foil.entity_id),
        ctx.actor, CHOICE+'absurd_ally', [a.entity_id for a in allies], labels={a.entity_id:a.display_name for a in allies},
        name='Absurd Agreement', prompt=f'Absurd Agreement: choose an ally who saw {foil.display_name}\'s technique. Its next attack against that creature has Advantage before your next turn starts; no additional cost.')
    if not selected:
        return
    ally = ctx.engine.state.actors[selected[0]]
    expiry = token('start',ctx.actor.entity_id,int(ctx.actor.turns_started)+1)
    mid = ctx.engine._add_modifier(ally,ctx.source,'attack_mode_vs','SET',f'ADVANTAGE:{foil.entity_id}',
                                   'NEXT_ATTACK',expires_on=expiry)
    # Removal addresses condition_id, not instance_id. Bind each receipt to its
    # unique modifier so consuming one grant cannot orphan another grant.
    ctx.engine._apply_condition(ally,'condition:typed.absurd_advantage.'+ctx.actor.entity_id+'.'+mid,ctx.source,ctx.actor.entity_id,
        expires_on=expiry, data={'foil':foil.entity_id,'modifier_id':mid,
            'label':f'Absurd Agreement: Advantage on the next attack against {foil.display_name} before the Jester\'s next turn'})


@hook('event')
def absurd_attack_used(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != 'ATTACK_ROLLED':
        return
    actor = engine.state.actors.get(kwargs.get('actor_id'))
    if actor is None:
        return
    for condition in list(actor.conditions.values()):
        data = condition.data or {}
        if not condition.condition_id.startswith('condition:typed.absurd_advantage.') or data.get('foil') not in (kwargs.get('target_ids') or ()):
            continue
        mid = data.get('modifier_id')
        if mid in actor.modifiers:
            del actor.modifiers[mid]
            engine._append_event('MODIFIER_REMOVED',condition.source_definition_id,actor_id=actor.entity_id,
                payload={'modifier_id':mid,'reason':'CONSUMED'})
        engine._remove_condition(actor,condition.condition_id,condition.source_definition_id)
