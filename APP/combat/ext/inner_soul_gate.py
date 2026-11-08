"""Inner Soul-Gate Ascetic (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md "07. Inner Soul-Gate Ascetic": Soul-Gate Discipline, CL3 Root, CL6 Sacral, CL10
Solar, CL14 Heart, CL18 Crown Soul Gate, Normalized Gate Procedures). No Spheres 5e or D&D 5.5e counterpart. Ownership: the
``spirit_tradition`` rows of combat/rules/feature_blocks.d/riders_c8.json (one per gate); every hook returns early without them.

Soul-Gate Discipline: each unlocked gate's passive always works; one Gate Opening at a time (a new one ends the last) unless Crown
Opening -- which counts as Root, Sacral, Solar and Heart Openings at once. An Opening is a condition on you ("Gate Opening: ...")
lasting the fight; "<Gate> Opening" buttons (Bonus Action) open them.

What runs:
  * Root: Advantage on saves against possession. Root Reclamation (Reaction, 1 Resonance, asked): knocked Prone -> stand at once; a
    forced move -> cut by 10 + 5 x floor(PB / 2) feet; a save against Prone, Grappled, Restrained, forced movement or possession ->
    Advantage on it. Root Opening (1 Resonance): standing costs 5 feet; end your turn where you began -> Wisdom + half PB Temporary HP.
  * Sacral: Sacral Reorientation (Reaction, 2 Resonance, once per round; a d20 rewrite): you fail a Dexterity, Wisdom or Charisma save
    -> add your Wisdom modifier; turned into a success -> you are Resonance Marked by yourself until the end of your next turn, and
    against Charmed, Frightened or possession its source (within 60 feet) gets your chosen Spiritual Pressure. Sacral Opening (2
    Resonance): Advantage on saves against Charmed and Frightened; once per turn after succeeding on one, move 10 feet without
    provoking (asked).
  * Solar: Resistance to Psychic damage; Advantage on saves against Charmed and Frightened. Solar Opening (4 Resonance): a Frightened
    whose source's CL is below yours does not take hold; succeeding on a save against Charmed, Frightened or possession deals 2d8 +
    Wisdom Psychic or Radiant to its source within 60 feet; once on each of your turns your Spirit Awakening feature's Psychic or
    Radiant damage may add Repelled Heart or Stilled Intent (asked).
  * Heart: Heart Attunement (Reaction, 2 Resonance; a d20 rewrite): you or a creature on your side within 30 feet fails a save
    against Charmed, Frightened or possession -> it adds your Wisdom modifier; if that makes it succeed you take 2 x PB Psychic. Heart
    Restoration (Action, touch, 5 Resonance): one Charmed or Frightened on a willing creature ends if its source's CL is below yours,
    else it repeats the original save with Advantage; success ends it, failure suppresses its symptom until your next turn starts. Heart Opening (4 Resonance):
    allies within 10 feet of you have Advantage on saves against Charmed and Frightened; once per round when one succeeds on an Int,
    Wis or Cha save it gains Wisdom + PB Temporary HP.
  * Crown Opening (9 Resonance): all four Openings at once; Spiritual Truesight 30 feet (an Invisible creature within 30 feet gets no
    Advantage or Disadvantage from it between you); Advantage on Int, Wis and Cha saves; once per round a failed Int, Wis or Cha save
    becomes a success for 2 Resonance (asked; a d20 rewrite).

Plug-in surface: effects soul_gate_open, soul_gate_restore (the "Heart Restoration" button); hooks compile_actions, candidate_allowed, save, after_save,
condition_attempt, condition_applied, forced_distance, incoming_damage, damage_dealt, turn_start, turn_end, masked_conditions; d20
rules sacral_reorientation, heart_attunement, crown_opening_succeed. Shared helpers used: spirit_traditions (row/context/numbers/
feature_action/can_react/routes/choose_route/remove/save), end_effect (source_cl), needle.ask, typed_executor.
"""

from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Iterator

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.inner_soul_gate_ascetic.feature."
ROOT = TRADITION + "root_soul_gate"
SACRAL = TRADITION + "sacral_soul_gate"
SOLAR = TRADITION + "solar_soul_gate"
HEART = TRADITION + "heart_soul_gate"
CROWN = TRADITION + "crown_soul_gate"
GATES = {"root": (ROOT, 1), "sacral": (SACRAL, 2), "solar": (SOLAR, 4), "heart": (HEART, 4), "crown": (CROWN, 9)}
OPENING = "condition:typed.gate_opening"
RESONANCE = "resource:core.resonance"
EMOTION = ("charmed", "frightened")
POSSESSION = ("possessed", "possession")
MENTAL = ("INT", "WIS", "CHA")


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def has_gate(engine: Any, actor: Any, gate: str) -> bool:
    return actor is not None and st.row(engine, actor, GATES[gate][0].rsplit(".", 1)[-1]) is not None


def _opening(actor: Any) -> Any:
    return next((c for c in actor.conditions.values() if c.condition_id == OPENING and c.source_actor_id == actor.entity_id), None)


def opened(actor: Any, gate: str) -> bool:
    """That Gate Opening is active (Crown Opening counts as Root, Sacral, Solar and Heart Openings at once)."""
    held = _opening(actor)
    which = str((held.data or {}).get("gate") or "") if held is not None else ""
    return which == gate or (which == "crown" and gate in ("root", "sacral", "solar", "heart"))


def _named(named: Any) -> set[str]:
    return {str(n).lower() for n in (named or ())}


def _cl(engine: Any, actor: Any) -> int:
    return int(st.numbers(engine, actor).get("cl") or 1)


# ---------------------------------------------------------------------------------------------------------- the Openings
@hook("compile_actions")
def opening_buttons(info: dict[str, Any]) -> list[Any] | None:
    owned = info["owned_ids"]
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    words = {"root": "your turn's end in the space you began it gives Wisdom + half PB Temporary HP",
             "sacral": "Advantage on saves against Charmed and Frightened; once per turn after one succeeds, a free 10-foot move",
             "solar": "lower-CL fear cannot take hold; saves you win against Charmed, Frightened or possession burn their source; your Spirit Awakening Psychic or Radiant damage may add Repelled Heart or Stilled Intent",
             "heart": "allies within 10 feet have Advantage on saves against Charmed and Frightened and gain Temporary HP when they win Int/Wis/Cha saves",
             "crown": "all four Openings at once, Spiritual Truesight 30 feet, Advantage on Int/Wis/Cha saves, and once per round a failed one succeeds for 2 Resonance"}
    out = []
    for gate, (feature, cost) in GATES.items():
        if feature not in owned:
            continue
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.gate_opening.{gate}", display_name=f"{gate.title()} Opening", owner_id=info["actor_id"],
            economy=EconomyKind.BONUS_ACTION, resolution_kind="TYPED", target_kind="SELF", costs=((RESONANCE, cost),),
            parameters={"typed": {"effects": [{"type": "soul_gate_open", "applies_to": "self", "gate": gate}], "numbers": info["numbers"],
                                  "duration": {"kind": "scene"}, "riders": [], "source": feature},
                        "expected_damage": 0, "soul_gate_opening": gate,
                        "description": f"{gate.title()} Soul Gate (Bonus Action, {cost} Resonance, the scene): {words[gate]}. One Gate Opening at a time: "
                                       "opening another ends this one."}))
    if HEART in owned:
        out.append(ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.heart_restoration", display_name="Heart Restoration", owner_id=info["actor_id"],
            economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="ALLY_OR_SELF", range_ft=5, costs=((RESONANCE, 5),),
            parameters={"typed": {"effects": [{"type": "soul_gate_restore", "applies_to": "target"}], "numbers": info["numbers"],
                                  "duration": {"kind": "instant"}, "riders": [], "source": HEART},
                        "expected_damage": 0, "heart_restoration": True,
                        "description": "Heart Soul Gate (Action, touch, 5 Resonance): one Charmed or Frightened on a willing creature ends if its source's CL is "
                                       "below yours; otherwise the creature repeats the save with Advantage, and a success ends it."}))
    return out or None


@effect("soul_gate_open")
def open_gate(ctx: Any, row: dict[str, Any]) -> None:
    held = _opening(ctx.actor)
    if held is not None:
        st.remove(ctx.engine, ctx.actor, held, "REPLACED")  # "Activating a new Gate Opening ends the previous one"
    gate = str(row.get("gate") or "")
    ctx.engine._apply_condition(ctx.actor, OPENING, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"gate": gate, "label": f"Gate Opening: {gate.title()}"})


@hook("candidate_allowed")
def gate_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    params = (action.parameters or {}) if action is not None else {}
    gate = params.get("soul_gate_opening")
    if gate:
        held = _opening(actor)
        return False if held is not None and (held.data or {}).get("gate") == gate else None
    if params.get("heart_restoration"):
        target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
        return None if target is not None and _calm(target) else False
    return None


# ---------------------------------------------------------------------------------------------------------- saves
@hook("save")
def gate_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    engine = ctx.engine
    if subject is None:
        return None
    names = _named(named)
    modes = []
    if has_gate(engine, subject, "root") and names & set(POSSESSION):
        modes.append("ADVANTAGE")  # Rooted Identity
    if names & set(EMOTION) and (has_gate(engine, subject, "solar") or (has_gate(engine, subject, "sacral") and opened(subject, "sacral"))):
        modes.append("ADVANTAGE")  # Solar Core; Sacral Opening
    if str(ability or "").upper()[:3] in MENTAL and has_gate(engine, subject, "crown") and opened(subject, "crown") and _opening(subject).data.get("gate") == "crown":
        modes.append("ADVANTAGE")  # Crown Opening
    if names & set(EMOTION) and any(owner is not subject and owner.team_id == subject.team_id and has_gate(engine, owner, "heart") and opened(owner, "heart")
                                    and engine._distance_actor_to_actor(owner, subject) <= 10 for owner in engine.state.actors.values() if owner.active):
        modes.append("ADVANTAGE")  # Heart Opening: "allies of your choice within 10 feet"
    if not modes and has_gate(engine, subject, "root") and names & {"prone", "grappled", "restrained", "forced_movement", *POSSESSION}:
        with _reclaim(engine, subject, ctx.intent, "the saving throw is made with Advantage", "save") as accepted:
            if accepted:
                modes.append("ADVANTAGE")  # Root Reclamation: "Gain Advantage on the triggering saving throw"
    return {"bonus": 0, "modes": modes[:1]} if modes else None


@hook("after_save")
def gate_after_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    engine = ctx.engine
    if subject is None or failed or not subject.active:
        return
    names = _named(named)
    source = ctx.actor
    if has_gate(engine, subject, "solar") and opened(subject, "solar") and names & {*EMOTION, *POSSESSION} and source is not None \
            and source.team_id != subject.team_id and source.active and engine._distance_actor_to_actor(subject, source) <= 60:
        run = st.context(engine, subject, st.feature_action(engine, subject, SOLAR), [source], st.numbers(engine, subject))
        _te().run_effects(run, [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "formula": "key_ability_modifier",
                                 "damage_types": ["psychic", "radiant"], "evidence": "the effect's source takes Psychic or Radiant damage equal to 2d8 + Wisdom modifier"}])
    if has_gate(engine, subject, "sacral") and opened(subject, "sacral") and names & set(EMOTION) and not subject.turn_flags.get("sacral_opening_move"):
        routes = {cell: v for cell, v in st.routes(engine, subject, 10).items() if cell != subject.position}
        path = st.choose_route(engine, subject, routes, ctx.intent or engine._active_intent, checkpoint="SACRAL_OPENING_MOVE",
                               prompt=f"Sacral Opening: {subject.display_name} may move 10 feet without provoking.", name="Sacral Opening", feature=SACRAL) if routes else None
        if path is not None:
            subject.turn_flags["sacral_opening_move"] = True  # "Once per turn"
            from .rider_movement import step

            step(engine, subject, list(path), SACRAL)
    if str(ability or "").upper()[:3] in MENTAL:
        for owner in engine.state.actors.values():
            if (owner.active and owner is not subject and owner.team_id == subject.team_id and has_gate(engine, owner, "heart") and opened(owner, "heart")
                    and engine._distance_actor_to_actor(owner, subject) <= 10 and owner.turn_flags.get("heart_opening_round_") != engine.state.round_number):
                owner.turn_flags["heart_opening_round_"] = engine.state.round_number  # "Once per round"
                numbers = st.numbers(engine, owner)
                engine._grant_temp_hp(subject, int(numbers.get("key_mod") or 0) + int(numbers.get("pb") or 2), HEART, owner.entity_id)


# ---------------------------------------------------------------------------------------------------------- Root Reclamation
@contextmanager
def _reclaim(engine: Any, actor: Any, intent: Any, what: str, key: str) -> Iterator[bool]:
    if not st.can_react(actor) or actor.resources.get(RESONANCE, 0) < 1:
        yield False
        return
    from . import needle

    chosen = needle.ask(engine, intent or engine._active_intent, needle.checkpoint_id(engine, f"ROOT_RECLAMATION_{key.upper()}", actor.entity_id), actor,
                        f"choice:needle.soul_gate.root_reclamation_{key}", ["reclaim"], labels={"reclaim": f"Root Reclamation (Reaction, 1 Resonance): {what}"},
                        prompt="Root Reclamation?", preferred=["reclaim"], allow_decline=True, name="Root Reclamation", feature_id=ROOT)
    if not chosen:
        yield False
        return
    with activation(engine, actor, ROOT):
        engine._spend_resource(actor, RESONANCE, 1, ROOT)
        actor.reaction_available = False
        engine._append_event("REACTION_RESOLVED", ROOT, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                             payload={"checkpoint": key.upper(), "reaction_name": "Root Reclamation"})
        yield True


@hook("forced_distance")
def root_holds(engine: Any, mover: Any, source: Any, distance_ft: int) -> int | None:
    if distance_ft <= 0 or not has_gate(engine, mover, "root"):
        return None
    cut = 10 + 5 * (int(st.numbers(engine, mover).get("pb") or 2) // 2)
    with _reclaim(engine, mover, None, f"cut the forced movement by {cut} feet", "move") as accepted:
        return min(cut, distance_ft) if accepted else None


@hook("condition_applied")
def root_stands(ctx: Any, name: str, subject: Any) -> None:
    if str(name or "").lower() != "prone" or subject is None or not subject.active or not has_gate(ctx.engine, subject, "root"):
        return
    held = next((c for c in subject.conditions.values() if c.condition_id.rsplit(".", 1)[-1] == "prone"), None)
    if held is not None:
        with _reclaim(ctx.engine, subject, ctx.intent, "stand from Prone without spending movement", "prone") as accepted:
            if accepted:
                st.remove(ctx.engine, subject, held, "STOOD")


# ---------------------------------------------------------------------------------------------------------- Root Opening
@hook("turn_start")
def root_stance(engine: Any, actor: Any) -> None:
    if has_gate(engine, actor, "root"):
        actor.turn_flags["root_opening_from"] = [actor.position.x, actor.position.y]


@hook("turn_end")
def root_rest(engine: Any, actor: Any) -> None:
    start = actor.turn_flags.get("root_opening_from")
    if not start or not actor.active or not opened(actor, "root") or [actor.position.x, actor.position.y] != list(start):
        return
    numbers = st.numbers(engine, actor)
    engine._grant_temp_hp(actor, int(numbers.get("key_mod") or 0) + int(numbers.get("pb") or 2) // 2, ROOT, actor.entity_id)


# ---------------------------------------------------------------------------------------------------------- Solar
@hook("incoming_damage")
def solar_core(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str, source_actor_id: str | None) -> int | None:
    if amount <= 1 or str(damage_type).upper() != "PSYCHIC" or not has_gate(engine, target, "solar"):
        return None
    return amount - amount // 2  # Solar Core: Resistance to Psychic damage


@hook("condition_attempt")
def solar_fearless(ctx: Any, subject: Any, effect_row: dict[str, Any]) -> bool | None:
    if str(effect_row.get("condition") or "").lower() != "frightened" or subject is None or not has_gate(ctx.engine, subject, "solar") \
            or not opened(subject, "solar") or ctx.actor.team_id == subject.team_id:
        return None
    theirs = int((ctx.numbers or {}).get("cl") or 1)
    return False if theirs < _cl(ctx.engine, subject) else None  # "immune to ordinary Frightened effects with lower Source CL"


@hook("damage_dealt")
def solar_heat(ctx: Any, target: Any, amount: int) -> None:
    engine, actor = ctx.engine, ctx.actor
    if (amount <= 0 or target is None or not target.active or not has_gate(engine, actor, "solar") or not opened(actor, "solar")
            or not st.is_spirit_feature(ctx.action) or actor.turn_flags.get("solar_heat") or engine.state.current_actor_id != actor.entity_id):
        return
    last = next((e for e in reversed(engine.events) if e.event_type == "DAMAGE_COMMITTED" and target.entity_id in e.target_ids and e.actor_id == actor.entity_id), None)
    if last is None or str((last.payload or {}).get("damage_type") or "").upper() not in ("PSYCHIC", "RADIANT"):
        return
    from . import needle

    options = {"repelled_heart": "Repelled Heart (it cannot willingly move closer to you)", "stilled_intent": "Stilled Intent (no Reactions)"}
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "SOLAR_OPENING", target.entity_id), actor, "choice:needle.soul_gate.solar",
                        list(options), labels=options, preferred=["stilled_intent"], allow_decline=True, name="Solar Opening", feature_id=SOLAR,
                        target_id=target.entity_id, prompt=f"Solar Opening: impose a Spiritual Pressure effect on {target.display_name}?")
    if not chosen or chosen[0] not in options:
        return
    actor.turn_flags["solar_heat"] = True  # "Once on each of your turns"
    _te().run_effects(st.context(engine, actor, ctx.action, [target], ctx.numbers, ctx.intent),
                      [{"type": "spiritual_pressure", "applies_to": "target", "option": chosen[0], "evidence": "impose Repelled Heart or Stilled Intent"}])


# ---------------------------------------------------------------------------------------------------------- Heart Restoration
def _calm(creature: Any) -> list[Any]:
    # A suppressed condition keeps its final name component so ordinary
    # condition matching can still identify the underlying rule. It is not a
    # live symptom, however, and must not be selected for another restoration.
    return [c for _, c in sorted(creature.conditions.items())
            if c.condition_id.rsplit(".", 1)[-1] in EMOTION
            and not c.condition_id.startswith("condition:typed.suppressed.")]


@effect("soul_gate_restore")
def restore(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle
    from .end_effect import source_cl, suppress

    engine, actor, target = ctx.engine, ctx.actor, ctx.target
    held = _calm(target) if target is not None else []
    if not held:
        return
    ids = [f"c{i}" for i in range(len(held))]
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "HEART_RESTORATION", target.entity_id), actor, "choice:needle.soul_gate.heart_restoration",
                        ids, labels={f"c{i}": c.condition_id.rsplit(".", 1)[-1].title() for i, c in enumerate(held)}, preferred=ids[:1],
                        prompt=f"Heart Restoration: which effect on {target.display_name}?", name="Heart Restoration", feature_id=HEART, target_id=target.entity_id)
    condition = held[ids.index(chosen[0])] if chosen and chosen[0] in ids else held[0]
    if source_cl(ctx, condition) < _cl(engine, actor):
        st.remove(engine, target, condition, "RESTORED")  # "If the effect's Source CL is lower than yours, end it"
        note(engine, HEART, actor, f"Heart Restoration ends {target.display_name}'s {condition.condition_id.rsplit('.', 1)[-1].title()}.", (target,))
        return
    source = engine.state.actors.get(condition.source_actor_id or "")
    origin = (condition.data or {}).get("origin_save") or {}
    dc = int(origin.get("dc") or (condition.data or {}).get("dc") or ((condition.data or {}).get("repeat_save") or {}).get("dc") or
             (st.numbers(engine, source).get("save_dc") if source is not None else 10) or 10)
    ability = str(origin.get("ability") or ((condition.data or {}).get("repeat_save") or {}).get("ability") or "WIS").upper()[:3]
    roll = engine._roll_save(target, ability, dc, HEART, extra_mode="ADVANTAGE")  # "immediately repeats its saving throw with Advantage"
    if roll is not None and roll.total >= dc:
        st.remove(engine, target, condition, "RESTORED")
    else:
        key = next(key for key, item in target.conditions.items() if item is condition)
        suppress(target, "condition", key, condition, rounds=1, by=actor, engine=engine, boundary="start")
        relative = "the same Cultivation Level as you" if source_cl(ctx, condition) == _cl(engine, actor) else "a higher Cultivation Level than you"
        symptom = condition.condition_id.rsplit(".", 1)[-1].title()
        note(engine, HEART, actor, f"Heart Restoration: {symptom} on {target.display_name} is suppressed until the start of your next turn; the effect's source has {relative}.", (target,))


# ---------------------------------------------------------------------------------------------------------- Crown: Spiritual Truesight
@hook("masked_conditions")
def truesight(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    out: dict[str, set[str]] = {}
    for seer, other in ((attacker, target), (target, attacker)):
        if seer is None or other is None or not has_gate(engine, seer, "crown") or (_opening(seer) is None or (_opening(seer).data or {}).get("gate") != "crown"):
            continue
        if engine._distance_actor_to_actor(seer, other) > 30:
            continue
        hidden = {iid for iid, c in other.conditions.items() if c.condition_id == "condition:typed.invisible"}
        if hidden:
            out.setdefault(other.entity_id, set()).update(hidden)
    return out or None


@hook("sense_grant_allowed")
def crown_truesight_grant(engine: Any, actor: Any, grant: dict[str, Any], seen: Any) -> bool | None:
    """Crown Opening's Spiritual Truesight 30 feet is live only while the owner's Crown Opening holds.

    The grant compiles into the bundle like every other always-on row; this shared eligibility
    seam excludes it until the actor's own Crown Opening is the live Gate Opening (an Opening
    lasts the scene, and opening another gate ends it). Line of effect, cover and concealment
    stay with the shared perception queries, so ``seen`` is not consulted here."""
    if str((grant or {}).get("feature_id") or "") != CROWN:
        return None
    return has_gate(engine, actor, "crown") and opened(actor, "crown")


# ---------------------------------------------------------------------------------------------------------- d20 rules
def _wis(engine: Any, holder: Any) -> int:
    """The holder's Wisdom modifier (its compiled numbers: a d20 rule's holder row carries none)."""
    return int(st.numbers(engine, holder.actor).get("key_mod") or 0)


def _emotional(rc: Any) -> bool:
    return bool(_named(rc.named) & {*EMOTION, *POSSESSION})


def _sacral_after(engine: Any, holder: Any, rc: Any, result: Any) -> None:
    outcome = (getattr(engine, "_typed_roll_outcome", None) or {}).get(rc.roller.entity_id)
    if outcome != "success" and (outcome is not None or rc.dc is None or int(result.total) < int(rc.dc)):
        return
    actor = holder.actor
    ctx = st.context(engine, actor, st.feature_action(engine, actor, SACRAL), [actor], st.numbers(engine, actor))
    engine._apply_condition(actor, _te().mark_condition_id("Resonance", actor.entity_id), SACRAL, actor.entity_id,
                            expires_on=_te().effect_expiry(ctx, {"duration": {"kind": "until_end_of_your_next_turn"}}, actor, condition=True),
                            data={"label": "Resonance Marked by yourself (Sacral Reorientation)"})
    source = getattr(rc, "source_actor", None)
    if _emotional(rc) and source is not None and source.active and source.team_id != actor.team_id and engine._distance_actor_to_actor(actor, source) <= 60:
        _te().run_effects(st.context(engine, actor, ctx.action, [source], st.numbers(engine, actor)),
                          [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "impose one ordinary Spiritual Pressure effect on its source"}])


def _heart_after(engine: Any, holder: Any, rc: Any, result: Any) -> None:
    outcome = (getattr(engine, "_typed_roll_outcome", None) or {}).get(rc.roller.entity_id)
    if outcome == "success" or (outcome is None and rc.dc is not None and int(result.total) >= int(rc.dc)):
        actor = holder.actor
        _te().run_effects(st.context(engine, actor, st.feature_action(engine, actor, HEART), [actor], st.numbers(engine, actor)),
                          [{"type": "damage", "applies_to": "target", "flat": 2 * int(st.numbers(engine, actor).get("pb") or 2), "damage_types": ["psychic"],
                            "evidence": "you take Psychic damage equal to 2 x Proficiency Bonus as you absorb the spiritual recoil"}])


def _crown_guard(engine: Any, holder: Any, rc: Any) -> bool:
    held = _opening(holder.actor)
    return held is not None and (held.data or {}).get("gate") == "crown" and rc.dc is not None


def _register_rules() -> None:
    from .d20_rewrite import Rule, register

    register(Rule("sacral_reorientation", "Sacral Reorientation", feature=SACRAL, rolls=("save",), who="self", when="failed", op="choose",
                  choose=lambda engine, holder, rc: rc.natural, bonus=lambda engine, holder, rc: _wis(engine, holder), abilities=("DEX", "WIS", "CHA"),
                  costs=((("resonance", 2),),), reaction=True, limit="round", after=_sacral_after,
                  ai=lambda engine, holder, rc: rc.dc is not None and 0 < int(rc.dc) - int(rc.roll.total) <= _wis(engine, holder)))
    register(Rule("heart_attunement", "Heart Attunement", feature=HEART, rolls=("save",), who="team", range_ft=30, when="failed", op="choose",
                  choose=lambda engine, holder, rc: rc.natural, bonus=lambda engine, holder, rc: _wis(engine, holder), costs=((("resonance", 2),),),
                  reaction=True, checkpoint="D20_REROLL_ALLY", guard=lambda engine, holder, rc: _emotional(rc), after=_heart_after,
                  ai=lambda engine, holder, rc: rc.dc is not None and 0 < int(rc.dc) - int(rc.roll.total) <= _wis(engine, holder)))
    register(Rule("crown_opening_succeed", "Crown Opening (succeed instead)", feature=CROWN, rolls=("save",), who="self", when="failed", op="choose",
                  choose=lambda engine, holder, rc: rc.natural, outcome="success", abilities=MENTAL, costs=((("resonance", 2),),), limit="round",
                  guard=_crown_guard))


_register_rules()


@hook("stand_cost")
def root_opening_stand(engine: Any, actor: Any, normal_cost: int) -> int | None:
    """The native posture transition owns legality and payment."""
    return 5 if has_gate(engine, actor, "root") and opened(actor, "root") else None
