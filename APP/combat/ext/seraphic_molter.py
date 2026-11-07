"""Seraphic Molter (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Seraphic Molter: Seraphic Signs and Molt Debt, CL3 First Molt, CL6 Wingless Ascent,
CL10 Burn Away the Lesser Self, CL14 Eyes in the Wings, CL18 Molt the Mortal Name). No Spheres 5e or D&D 5.5e counterpart. Ownership row:
combat/rules/feature_blocks.d/riders_c8.json (First Molt: it has no action of its own).

Molt Debt (tradition text): a pool (resource:named.molt_debt), maximum PB, 0 at the start of the fight; a feature that would add Debt
at the maximum is not offered (a Permanent Seraphic Sign is the GM's).

What runs:
  * First Molt: the Minor Seraphic Sign is a standing free choice (combat/ext/menus.py; the AI and a player who never chose keep the
    Feather-Scar Sign). Glass-Eye Sign -- Spiritual Sense +5 feet; Feather-Scar Sign -- Advantage on saves against Frightened, and after
    such a save succeeds a 5-foot move without provoking (asked). The other Signs are the GM's.
  * Wingless Ascent (typed, Bonus Action, 3 Resonance, the fight): "Wingless Ascent: Shielding Pinions" (free, once on each of your
    later turns while the wings are out): you or an ally within 10 feet takes Wisdom + PB less from the first Psychic, Radiant or
    Necrotic damage before the start of your next turn.
  * Burn Away the Lesser Self (typed options, Bonus Action, 5 Resonance): one Charmed, Frightened, Poisoned or Spiritual Pressure effect
    on you -- a lower source's ends; otherwise a Cultivation Check against its DC suppresses it for the fight (failed: until the end of
    your next turn). Optional Molt Debt (asked) doubles the Cast-Off Self's Hit Points. The Cast-Off Self object (AC your DC, 5 x PB
    HP) stands next to you: while it lasts the same effect from the same source cannot take hold of you again, a hostile source
    within 60 feet becomes Resonance Marked, and its destruction by anyone else gives you 1 Molt Debt. "Reintegrate the Cast-Off
    Self" (Action) removes it and restores half your PB (rounded down) Resonance.
  * Eyes in the Wings (typed, Bonus Action, 6 Resonance, the fight): Spiritual Sense +30 feet (Spiritual Sense sees hidden and
    invisible creatures in range); once per round a hostile creature in your Spiritual Sense that misses you with an attack or whose
    technique you save against suffers a Spiritual Pressure effect. Pinion Witness (Reaction, 2 Resonance, asked): a creature within
    your Spiritual Sense teleports or becomes invisible -- your Resonance Mark. Sensory Overgrowth: starting your turn sensing more
    hostile creatures than your Wisdom modifier (minimum 1) -- PB Psychic, eyes closed until your next turn, or 1 Molt Debt (asked).
  * Molt the Mortal Name (typed, Action, 10 Resonance + 1 Molt Debt, the fight): two Ascension Anatomies (asked) and a third when you
    are at half your Hit Points or lower (asked). Throne Wings -- no Opportunity Attacks from creatures known to be of lower CL (the
    flight is 60 feet with hovering); Thousand Eyes -- Spiritual Sense +60 feet; Burning Name -- Resistance to Psychic and Radiant, and a creature
    that deals you either becomes Resonance Marked; Crown of Unselfing -- Advantage on Int/Wis/Cha saves, and a success puts a
    Spiritual Pressure effect on a source within 60 feet; Mercyless Purity -- at the start of your turns one Charmed, Frightened or
    Poisoned on you ends (a lower source's) or is checked against; Swordless Judgment -- once a turn your Spirit Awakening feature's
    Psychic, Radiant or Necrotic damage adds 2d8 and a Spiritual Pressure effect. Death and the Shed Name (once, asked): the first
    time you would drop to 0 Hit Points you stay at 1 and a Mortal Name Husk object (AC your DC, 10 x PB HP) appears next to you.

Plug-in surface: effects seraphic_wings, seraphic_pinions, seraphic_burn, seraphic_reintegrate, seraphic_eyes, seraphic_form; hooks
compile_actions, candidate_allowed, save, after_save_resolved, incoming_damage, sense_range, condition_attempt, event, turn_start,
would_drop, damage_dealt, opportunity_allowed, flight. Shared helpers used: spirit_traditions (context/numbers/feature_action/feature_of/
is_spirit_feature/pick_creature/routes/choose_route/can_react/remove/suppress/data_of/set_data), menus, end_effect (source_cl/
cultivation_dc/suppress), senses.of, needle, typed_executor.
"""

from __future__ import annotations

from .map_positions import offset_positions

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.seraphic_molter.feature."
FIRST = TRADITION + "first_molt"
WINGS = TRADITION + "wingless_ascent"
BURN = TRADITION + "burn_away_the_lesser_self"
EYES = TRADITION + "eyes_in_the_wings"
NAME = TRADITION + "molt_the_mortal_name"
DEBT = "resource:named.molt_debt"
RESONANCE = "resource:core.resonance"
SIGN_MENU = "seraphic.minor_sign"
SIGNS = ("Glass-Eye Sign", "Feather-Scar Sign", "Halo-Bruise Sign", "Second-Voice Sign", "Many-Shadow Sign", "Molt Recognition Sign")
FIRST_MOLT_FEATURE = "tianxia.tradition.spirit.seraphic_molter.feature.first_molt"


def _acquired_sign(sheet: Any) -> str | None:
    """The Minor Sign chosen when First Molt was gained (the saved acquisition), or None when none was recorded."""
    block = ((sheet or {}).get("path_and_subpath") or {}).get("feature_build_choices") or {}
    name = (block.get(FIRST_MOLT_FEATURE) or {}).get("minor_sign")
    return str(name) if name in SIGNS else None


WINGS_OUT = "condition:typed.wingless_ascent"
PINIONS = "condition:typed.shielding_pinions"
EYES_OPEN = "condition:typed.eyes_in_the_wings"
FORM = "condition:typed.seraphic_ascension"
CAST_OFF = "object:typed.cast_off_self:"
HUSK = "object:typed.mortal_name_husk:"
ANATOMIES = ("Throne Wings", "Thousand Eyes", "Burning Name", "Crown of Unselfing", "Mercyless Purity", "Swordless Judgment")
BURDENS = {"charmed": "Charmed", "frightened": "Frightened", "poisoned": "Poisoned", "pressure": "Spiritual Pressure"}
PRESSURE = "condition:typed.spirit_awakening_pressure"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _name(condition: Any) -> str:
    return str(condition.condition_id or "").rsplit(".", 1)[-1].lower()


def _held(creature: Any, condition_id: str) -> Any:
    return next((c for c in creature.conditions.values() if c.condition_id == condition_id and c.source_actor_id == creature.entity_id), None)


def _numbers(engine: Any, actor: Any) -> dict[str, Any]:
    return st.numbers(engine, actor)


def _debt_room(actor: Any) -> bool:
    return DEBT in actor.resources and actor.resources.get(DEBT, 0) < actor.resource_maximums.get(DEBT, 0)


def _add_debt(engine: Any, actor: Any, source: str, why: str) -> None:
    if _debt_room(actor):
        engine._gain_resource(actor, DEBT, 1, source)
        note(engine, source, actor, f"{actor.display_name} gains 1 Molt Debt ({why}).")


def _pressure(engine: Any, owner: Any, feature: str, target: Any, intent: Any = None) -> None:
    _te().run_effects(st.context(engine, owner, st.feature_action(engine, owner, feature), [target], _numbers(engine, owner), intent),
                      [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "impose one ordinary Spiritual Pressure effect"}])


def _anatomy(actor: Any, name: str) -> bool:
    held = _held(actor, FORM)
    return held is not None and name in (st.data_of(actor, held).get("anatomies") or [])


def _sense_range(engine: Any, actor: Any) -> int:
    from .. import senses

    return int((senses.of(engine, actor).get("spiritual_sense") or {}).get("range_ft") or 0)


def _cl(engine: Any, creature: Any) -> int | None:
    bundle = next((row for row in getattr(engine, "typed_bundle_documents", ()) or () if row.get("actor_id") == creature.entity_id), None)
    return int(bundle["cl"]) if bundle and bundle.get("cl") else None


# ---------------------------------------------------------------------------------------------------------- First Molt
def _sign(engine: Any, actor: Any) -> str | None:
    from . import menus

    if st.row(engine, actor, "first_molt") is None:
        return None
    picked = menus.picks(engine, actor, SIGN_MENU)
    return picked[0] if picked else None


@hook("sense_range")
def seraphic_senses(engine: Any, actor: Any, sense: str) -> int:
    if sense != "spiritual_sense":
        return 0
    extra = 5 if _sign(engine, actor) == "Glass-Eye Sign" else 0
    eyes = _held(actor, EYES_OPEN)
    if eyes is not None and not st.data_of(actor, eyes).get("closed_turn") == int(actor.turns_started):
        extra += 30  # "Your Spiritual Sense range increases by 30 feet."
    if _anatomy(actor, "Thousand Eyes"):
        extra += 60
    return extra


@hook("save")
def seraphic_saves(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    if subject is None:
        return None
    modes = []
    if _sign(ctx.engine, subject) == "Feather-Scar Sign" and "frightened" in {str(n).lower() for n in named or ()}:
        modes.append("ADVANTAGE")  # "You have Advantage on saving throws against Frightened."
    if _anatomy(subject, "Crown of Unselfing") and str(ability or "").upper()[:3] in ("INT", "WIS", "CHA"):
        modes.append("ADVANTAGE")
    return {"bonus": 0, "modes": modes[:1]} if modes else None


@hook("after_save_resolved")
def seraphic_after_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    engine = ctx.engine
    if subject is None or failed:
        return
    source = ctx.actor
    if _sign(engine, subject) == "Feather-Scar Sign" and "frightened" in {str(n).lower() for n in named or ()}:
        spots = {c: v for c, v in st.routes(engine, subject, 5).items() if c != subject.position}
        path = st.choose_route(engine, subject, spots, ctx.intent, checkpoint="FEATHER_SCAR", prompt="Feather-Scar Sign: move 5 feet without provoking?",
                               name="Feather-Scar Sign", feature=FIRST, stay=True) if spots else None
        if path is not None:
            from .rider_movement import step as walk

            walk(engine, subject, list(path), FIRST)
    if (_anatomy(subject, "Crown of Unselfing") and str(ability or "").upper()[:3] in ("INT", "WIS", "CHA") and source is not None
            and source.team_id != subject.team_id and source.active and engine._distance_actor_to_actor(subject, source) <= 60):
        _pressure(engine, subject, NAME, source, ctx.intent)  # "When you succeed on one, impose one ordinary Spiritual Pressure effect on the source"
    eyes = _held(subject, EYES_OPEN)
    if eyes is not None and source is not None and source.team_id != subject.team_id:
        _eyes_punish(engine, subject, source, ctx.intent)


# ---------------------------------------------------------------------------------------------------------- Wingless Ascent
@effect("seraphic_wings")
def wings(ctx: Any, row: dict[str, Any]) -> None:
    held = _held(ctx.actor, WINGS_OUT)
    if held is not None:
        st.remove(ctx.engine, ctx.actor, held, "REPLACED")
    ctx.engine._apply_condition(ctx.actor, WINGS_OUT, WINGS, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"turn": int(ctx.actor.turns_started), "label": "Wingless Ascent: spiritual wings unfolded"})


@effect("seraphic_pinions")
def pinions(ctx: Any, row: dict[str, Any]) -> None:
    engine, molter = ctx.engine, ctx.actor
    target = next(iter(_te()._default_subject(ctx, row, harmful=False)), None)
    molter.turn_flags["wingless_mode"] = True  # "At the start of each of your turns, choose one mode."
    if target is None:
        return
    numbers = ctx.numbers or _numbers(engine, molter)
    amount = int(numbers.get("key_mod") or 0) + int(numbers.get("pb") or 2)
    engine._apply_condition(target, PINIONS, WINGS, molter.entity_id, expires_on="START_OF_SOURCE_NEXT_TURN",
                            data={"amount": amount, "label": f"Shielding Pinions: the first Psychic, Radiant or Necrotic damage is {amount} less"})


@hook("incoming_damage")
def seraphic_shields(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str, source_actor_id: str | None) -> int | None:
    kind = str(damage_type).upper()
    off = 0
    if kind in ("PSYCHIC", "RADIANT", "NECROTIC"):
        held = next((c for c in target.conditions.values() if c.condition_id == PINIONS), None)
        if held is not None:
            st.remove(engine, target, held, "USED")  # "reduce the first instance"
            off += min(amount, int((held.data or {}).get("amount") or 0))
    if kind in ("PSYCHIC", "RADIANT") and _anatomy(target, "Burning Name") and amount - off > 1:
        rest = amount - off
        off += rest - rest // 2  # "Gain Resistance to Psychic and Radiant damage."
    return off or None


# ---------------------------------------------------------------------------------------------------------- Burn Away the Lesser Self
def _burdens(creature: Any, kind: str) -> list[Any]:
    if kind == "pressure":
        return [c for _, c in sorted(creature.conditions.items()) if str(c.condition_id).startswith(PRESSURE) and c.source_actor_id != creature.entity_id]
    return [c for _, c in sorted(creature.conditions.items()) if _name(c) == kind]


def cast_off_of(engine: Any, molter: Any) -> Any:
    return next((o for o in engine.state.objects.values() if o.object_id.startswith(CAST_OFF) and o.owner_id == molter.entity_id and not o.destroyed), None)


@effect("seraphic_burn")
def burn(ctx: Any, row: dict[str, Any]) -> None:
    from ..gate2_runtime_models import Position, RuntimeObjectState
    from . import needle
    from .end_effect import cultivation_dc, source_cl, suppress

    engine, molter = ctx.engine, ctx.actor
    kind = str(row.get("burden"))
    found = _burdens(molter, kind)
    if not found:
        return
    held = found[0]
    source = engine.state.actors.get(held.source_actor_id or "")
    numbers = ctx.numbers or _numbers(engine, molter)
    debt = _debt_room(molter) and bool(needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "BURN_DEBT", molter.entity_id), molter,
                                                  "choice:needle.seraphic.burn_debt", ["debt"], labels={"debt": "Gain 1 Molt Debt to strengthen it (the Cast-Off has double Hit Points)"},
                                                  allow_decline=True, prompt="Burn Away the Lesser Self: strengthen the result?", name="Burn Away the Lesser Self",
                                                  feature_id=BURN))
    if debt:
        _add_debt(engine, molter, BURN, "Burn Away the Lesser Self")
    iid = next(k for k, c in molter.conditions.items() if c is held)
    if source_cl(ctx, held) < int(numbers.get("cl") or 1):
        st.remove(engine, molter, held, "BURNED_AWAY")  # "If the effect is ordinary and lower Source CL, end it."
    else:
        origin = (held.data or {}).get("origin_save") or {}
        dc = int(origin.get("dc") or (cultivation_dc(engine, source) if source is not None else 10))
        roll = engine.roll_check(
            modifier=int(numbers.get('pb') or 2) + int(numbers.get('key_mod') or 0),
            actor_id=molter.entity_id,
            reason=f'CHECK:{BURN}',
        )
        engine._record_roll(roll)
        engine._append_event("CHECK_ROLLED", BURN, actor_id=molter.entity_id, payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": roll.total >= dc,
                                                                                     "check": "Cultivation Check (Burn Away the Lesser Self)"})
        if roll.total >= dc:
            suppress(molter, "condition", iid, held, rounds=100, by=molter)  # "On success, suppress it for the scene instead."
        else:
            st.suppress(engine, molter, held, BURN, molter.entity_id, "Burn Away the Lesser Self")  # "until the end of your next turn"
    old = cast_off_of(engine, molter)
    if old is not None:
        engine._update_object(old.model_copy(update={"destroyed": True, "component": {**(old.component or {}), "reintegrated": True}}), BURN, molter.entity_id)
    taken = {(o.position.x, o.position.y) for o in engine.state.objects.values() if not o.destroyed} | set(engine._occupied_cells_except(molter.entity_id)) \
        | set(engine._actor_cells(molter))
    around = list(offset_positions(engine, molter.position, ((dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)))
    spot = next((p for p in around if engine.grid.in_bounds((p.x, p.y)) and (p.x, p.y) not in engine.grid.blocked and (p.x, p.y) not in taken), molter.position)
    hp = 5 * int(numbers.get("pb") or 2) * (2 if debt else 1)
    engine._update_object(RuntimeObjectState(object_id=f"{CAST_OFF}{molter.entity_id}:{engine.state.event_sequence}", object_kind="CAST_OFF_SELF", position=spot,
                                             unattended=False, flammable=False, owner_id=molter.entity_id, ac=int(numbers.get("save_dc") or 10), current_hp=hp,
                                             maximum_hp=hp, damage_immunities=("POISON", "PSYCHIC"),
                                             component={"label": f"Cast-Off Self ({BURDENS[kind]})", "condition_id": held.condition_id,
                                                        "source_actor_id": held.source_actor_id}), BURN, molter.entity_id)
    if source is not None and source.team_id != molter.team_id and source.active and engine._distance_actor_to_actor(molter, source) <= 60:
        _te().run_effects(st.context(engine, molter, ctx.action, [source], numbers, ctx.intent),
                          [{"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                            "evidence": "If the hostile source was within 60 feet when you shed it, that source becomes Resonance Marked by you."}])


@hook("condition_attempt")
def shed_stays_shed(ctx: Any, subject: Any, eff: dict[str, Any]) -> bool | None:
    """"While the Cast-Off exists: You cannot gain the exact same ordinary effect from the same source again.\""""
    obj = cast_off_of(ctx.engine, subject) if subject is not None else None
    if obj is None:
        return None
    wanted = f"condition:typed.{str(eff.get('condition') or '').lower()}"
    comp = obj.component or {}
    return False if comp.get("condition_id") == wanted and comp.get("source_actor_id") == ctx.actor.entity_id else None


@effect("seraphic_reintegrate")
def reintegrate(ctx: Any, row: dict[str, Any]) -> None:
    engine, molter = ctx.engine, ctx.actor
    obj = cast_off_of(engine, molter)
    if obj is None:
        return
    engine._update_object(obj.model_copy(update={"destroyed": True, "component": {**(obj.component or {}), "reintegrated": True}}), BURN, molter.entity_id)
    engine._gain_resource(molter, RESONANCE, int((ctx.numbers or _numbers(engine, molter)).get("pb") or 2) // 2, BURN)  # "regain Resonance equal to half your PB"


@hook("event")
def seraphic_objects_and_eyes(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    payload = kwargs.get("payload") or {}
    if event_type == "OBJECT_UPDATED":
        obj = payload.get("object") or {}
        if str(obj.get("object_id") or "").startswith(CAST_OFF) and not (obj.get("component") or {}).get("reintegrated") and (
                obj.get("destroyed") or (obj.get("current_hp") is not None and int(obj.get("current_hp") or 0) <= 0)):
            molter = engine.state.actors.get(str(obj.get("owner_id") or ""))
            stored = engine.state.objects.get(str(obj.get("object_id")))
            if stored is not None:
                engine._update_object(stored.model_copy(update={"component": {**(stored.component or {}), "reintegrated": True}}), BURN, stored.owner_id)
            if molter is not None:
                _add_debt(engine, molter, BURN, "the Cast-Off Self was destroyed")  # "the burden does not return, but you gain 1 Molt Debt"
        return
    if event_type == "ATTACK_ROLLED" and not payload.get("provisional_hit"):
        attacker = engine.state.actors.get(kwargs.get("actor_id") or "")
        for victim_id in kwargs.get("target_ids") or ():
            victim = engine.state.actors.get(victim_id)
            if victim is not None and attacker is not None and _held(victim, EYES_OPEN) is not None and attacker.team_id != victim.team_id:
                _eyes_punish(engine, victim, attacker, engine._active_intent)
        return
    if event_type == "DAMAGE_COMMITTED" and int(payload.get("hp_damage") or 0) + int(payload.get("temporary_hp_absorbed") or 0) > 0:
        source = engine.state.actors.get(kwargs.get("actor_id") or "")
        kind = str(payload.get("damage_type") or "").upper()
        for victim_id in kwargs.get("target_ids") or ():
            victim = engine.state.actors.get(victim_id)
            if (victim is not None and source is not None and source.team_id != victim.team_id and kind in ("PSYCHIC", "RADIANT")
                    and _anatomy(victim, "Burning Name") and source.active):
                _te().run_effects(st.context(engine, victim, st.feature_action(engine, victim, NAME), [source], _numbers(engine, victim)),
                                  [{"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                                    "evidence": "When a creature damages you with one of those types, it becomes Resonance Marked by you."}])
        return
    if event_type in ("CONDITION_APPLIED", "MOVEMENT_COMMITTED"):
        subject = engine.state.actors.get(next(iter(kwargs.get("target_ids") or ()), "") if event_type == "CONDITION_APPLIED" else kwargs.get("actor_id") or "")
        vanished = event_type == "CONDITION_APPLIED" and payload.get("condition_id") == "condition:typed.invisible"
        teleported = event_type == "MOVEMENT_COMMITTED" and payload.get("teleport")
        if subject is not None and (vanished or teleported):
            _pinion_witness(engine, subject)


def _eyes_punish(engine: Any, molter: Any, foe: Any, intent: Any) -> None:
    """"Once per round when a detected hostile creature misses you with an attack or fails a technique against you, impose one ordinary
    Spiritual Pressure effect on it.\""""
    eyes = _held(molter, EYES_OPEN)
    if eyes is None or not foe.active or engine._distance_actor_to_actor(molter, foe) > _sense_range(engine, molter):
        return
    if st.data_of(molter, eyes).get("punish_round") == engine.state.round_number:
        return
    st.set_data(molter, eyes, punish_round=engine.state.round_number)
    _pressure(engine, molter, EYES, foe, intent)


def _pinion_witness(engine: Any, subject: Any) -> None:
    from . import needle

    for molter in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if (_held(molter, EYES_OPEN) is None or molter is subject or not st.can_react(molter) or molter.resources.get(RESONANCE, 0) < 2
                or engine._distance_actor_to_actor(molter, subject) > _sense_range(engine, molter)):
            continue
        if not needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "PINION_WITNESS", subject.entity_id), molter, "choice:needle.seraphic.pinion",
                          ["mark"], labels={"mark": f"Pinion Witness (Reaction, 2 Resonance): Resonance Mark {subject.display_name}"}, preferred=["mark"],
                          allow_decline=True, prompt=f"{subject.display_name} slips from sight.", name="Pinion Witness", feature_id=EYES, target_id=subject.entity_id):
            continue
        from ..paid_relocation import activation as relocation_activation
        with relocation_activation(engine, molter, EYES, independent=True):
            molter.reaction_available = False
            engine._spend_resource(molter, RESONANCE, 2, EYES)
            engine._append_event("REACTION_RESOLVED", EYES, actor_id=molter.entity_id, target_ids=(subject.entity_id,),
                                 payload={"checkpoint": "VANISHED", "reaction_name": "Pinion Witness"})
            _te().run_effects(st.context(engine, molter, st.feature_action(engine, molter, EYES), [subject], _numbers(engine, molter)),
                              [{"type": "mark", "mark": "Resonance", "applies_to": "target", "duration": {"kind": "until_end_of_your_next_turn"},
                                "evidence": "Place a Resonance Mark on it and record a Pinion Trace until the end of the scene."}])
            return


# ---------------------------------------------------------------------------------------------------------- Eyes in the Wings
@effect("seraphic_eyes")
def eyes(ctx: Any, row: dict[str, Any]) -> None:
    held = _held(ctx.actor, EYES_OPEN)
    if held is not None:
        st.remove(ctx.engine, ctx.actor, held, "REPLACED")
    ctx.engine._apply_condition(ctx.actor, EYES_OPEN, EYES, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Eyes in the Wings: Spiritual Sense +30 feet"})


@hook("turn_start")
def seraphic_turn(engine: Any, actor: Any) -> None:
    from . import needle

    eyes_held = _held(actor, EYES_OPEN)
    if eyes_held is not None and actor.active:
        # Sensory Overgrowth: "If you begin your turn perceiving more meaningful hostile creatures ... than your Wisdom modifier, minimum one"
        reach = _sense_range(engine, actor)
        seen = [c for c in engine.state.actors.values() if c.active and c.team_id != actor.team_id and engine._distance_actor_to_actor(actor, c) <= reach]
        if len(seen) > max(1, int(_numbers(engine, actor).get("key_mod") or 0)):
            pb = int(_numbers(engine, actor).get("pb") or 2)
            options = {"psychic": f"Take {pb} Psychic damage", "close": "Close the additional eyes until the start of your next turn",
                       **({"debt": "Gain 1 Molt Debt and keep full perception"} if _debt_room(actor) else {})}
            chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "SENSORY_OVERGROWTH", actor.entity_id), actor,
                                "choice:needle.seraphic.overgrowth", list(options), labels=options, preferred=["close"], prompt="Sensory Overgrowth",
                                name="Eyes in the Wings", feature_id=EYES)
            pick = chosen[0] if chosen and chosen[0] in options else "close"
            if pick == "psychic":
                engine._commit_damage(actor, pb, "PSYCHIC", EYES, actor.entity_id, engine._active_intent, reaction_depth=1)
            elif pick == "debt":
                _add_debt(engine, actor, EYES, "Sensory Overgrowth")
            else:
                st.set_data(actor, eyes_held, closed_turn=int(actor.turns_started))
    form = _held(actor, FORM)
    if form is not None and _anatomy(actor, "Mercyless Purity") and actor.active:
        # "At the start of each of your turns, end one ordinary Charmed, Frightened, Poisoned ... effect on yourself."
        from .end_effect import source_cl

        found = next((c for _, c in sorted(actor.conditions.items()) if _name(c) in ("charmed", "frightened", "poisoned") and c.source_actor_id != actor.entity_id), None)
        if found is not None:
            sub = st.context(engine, actor, st.feature_action(engine, actor, NAME), [actor], _numbers(engine, actor))
            if source_cl(sub, found) < int(_numbers(engine, actor).get("cl") or 1):
                st.remove(engine, actor, found, "PURIFIED")
            else:
                st.suppress(engine, actor, found, NAME, actor.entity_id, "Mercyless Purity")


# ---------------------------------------------------------------------------------------------------------- Molt the Mortal Name
@effect("seraphic_form")
def form(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, molter = ctx.engine, ctx.actor
    held = _held(molter, FORM)
    if held is not None:
        st.remove(engine, molter, held, "REPLACED")
    _add_debt(engine, molter, NAME, "Molt the Mortal Name")  # "Cost: 10 Resonance and 1 Molt Debt"
    ids = [a.lower().replace(" ", "_") for a in ANATOMIES]
    labels = dict(zip(ids, ANATOMIES))
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "ASCENSION_ANATOMIES", molter.entity_id), molter, "choice:needle.seraphic.anatomies",
                        ids, labels=labels, preferred=["burning_name", "crown_of_unselfing"], minimum=2, maximum=2, default="all",
                        prompt="Molt the Mortal Name: choose two Ascension Anatomies.", name="Molt the Mortal Name", feature_id=NAME)
    picked = [labels[i] for i in (chosen or []) if i in labels][:2] or ["Burning Name", "Crown of Unselfing"]
    engine._apply_condition(molter, FORM, NAME, molter.entity_id, expires_on="UNTIL_REMOVED",
                            data={"anatomies": picked, "husk": 0, "label": f"Seraphic Ascension Form: {', '.join(picked)}"})


@hook("event")
def third_anatomy(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"... and a third when you reach half your Hit Point maximum or lower.\""""
    from . import needle

    if event_type != "DAMAGE_COMMITTED":
        return
    for target_id in kwargs.get("target_ids") or ():
        molter = engine.state.actors.get(target_id)
        held = _held(molter, FORM) if molter is not None else None
        if held is None or molter.current_hp > molter.maximum_hp // 2 or len(st.data_of(molter, held).get("anatomies") or []) >= 3 or not molter.active:
            continue
        have = st.data_of(molter, held).get("anatomies") or []
        rest = [a for a in ANATOMIES if a not in have]
        ids = [a.lower().replace(" ", "_") for a in rest]
        chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "THIRD_ANATOMY", molter.entity_id), molter, "choice:needle.seraphic.third_anatomy",
                            ids, labels=dict(zip(ids, rest)), preferred=ids[:1], prompt="Molt the Mortal Name: you are Bloodied -- choose a third Ascension Anatomy.",
                            name="Molt the Mortal Name", feature_id=NAME)
        third = dict(zip(ids, rest)).get((chosen or ids[:1])[0], rest[0])
        st.set_data(molter, held, anatomies=[*have, third])


@hook("opportunity_allowed")
def throne_wings(engine: Any, reactor: Any, mover: Any) -> bool | None:
    """Throne Wings: "Your movement does not provoke opportunity attacks from creatures with lower Source CL\""""
    if mover is None or reactor is None or not _anatomy(mover, "Throne Wings"):
        return None
    theirs, mine = _cl(engine, reactor), int(_numbers(engine, mover).get("cl") or 1)
    return False if theirs is not None and theirs < mine else None


@hook("damage_dealt")
def swordless_judgment(ctx: Any, target: Any, amount: int) -> None:
    """Swordless Judgment: "Once on each of your turns when you deal Psychic, Radiant, or Necrotic damage with a Spirit Awakening feature,
    deal an additional 2d8 damage of one of those types and impose one ordinary Spiritual Pressure effect.\""""
    engine, molter = ctx.engine, ctx.actor
    if (amount <= 0 or target is None or target.team_id == molter.team_id or not _anatomy(molter, "Swordless Judgment") or not st.is_spirit_feature(ctx.action)
            or engine.state.current_actor_id != molter.entity_id or molter.turn_flags.get("swordless_judgment")):
        return
    last = next((e for e in reversed(engine.events) if e.event_type == "DAMAGE_COMMITTED" and target.entity_id in (e.target_ids or ())), None)
    kind = str(((last.payload or {}).get("damage_type") if last is not None else "") or "").upper()
    if kind not in ("PSYCHIC", "RADIANT", "NECROTIC"):
        return
    molter.turn_flags["swordless_judgment"] = True
    _te().run_effects(st.context(engine, molter, ctx.action, [target], ctx.numbers, ctx.intent),
                      [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": [kind.lower()],
                        "evidence": "deal an additional 2d8 damage of one of those types"},
                       {"type": "spiritual_pressure", "applies_to": "target", "evidence": "and impose one ordinary Spiritual Pressure effect"}])


@hook("would_drop")
def shed_name(engine: Any, target: Any, pending: int, source_actor_id: str | None) -> int | None:
    """Death and the Shed Name: "The first time during the form that you would be reduced to 0 Hit Points ... you may shed the consequence
    into a Mortal Name Husk and remain at 1 Hit Point.\""""
    from ..gate2_runtime_models import Position, RuntimeObjectState
    from . import needle

    held = _held(target, FORM)
    if held is None or st.data_of(target, held).get("husk") or target.current_hp + target.temporary_hp <= 1:
        return None
    if not needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "SHED_NAME", target.entity_id), target, "choice:needle.seraphic.shed_name",
                      ["shed"], labels={"shed": "Shed it into a Mortal Name Husk and stay at 1 Hit Point"}, preferred=["shed"], allow_decline=True,
                      prompt="Death and the Shed Name (once in the form)", name="Molt the Mortal Name", feature_id=NAME):
        return None
    st.set_data(target, held, husk=1)
    numbers = _numbers(engine, target)
    taken = {(o.position.x, o.position.y) for o in engine.state.objects.values() if not o.destroyed} | set(engine._occupied_cells_except(target.entity_id)) \
        | set(engine._actor_cells(target))
    around = list(offset_positions(engine, target.position, ((dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)))
    spot = next((p for p in around if engine.grid.in_bounds((p.x, p.y)) and (p.x, p.y) not in engine.grid.blocked and (p.x, p.y) not in taken), target.position)
    hp = 10 * int(numbers.get("pb") or 2)
    engine._update_object(RuntimeObjectState(object_id=f"{HUSK}{target.entity_id}:{engine.state.event_sequence}", object_kind="MORTAL_NAME_HUSK", position=spot,
                                             unattended=False, flammable=False, owner_id=target.entity_id, ac=int(numbers.get("save_dc") or 10), current_hp=hp,
                                             maximum_hp=hp, damage_immunities=("POISON", "PSYCHIC", "RADIANT", "NECROTIC"),
                                             component={"label": "Mortal Name Husk"}), NAME, target.entity_id)
    return max(0, target.current_hp + target.temporary_hp - 1)


# ---------------------------------------------------------------------------------------------------------- buttons and gates
@hook("compile_actions")
def seraphic_buttons(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from . import menus

    owned, out = info["owned_ids"], []

    def button(key: str, name: str, economy: Any, target: str, range_ft: int | None, rows: list[dict[str, Any]], text: str, source: str) -> Any:
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.seraphic.{key}", display_name=name, owner_id=info["actor_id"], economy=economy,
                                resolution_kind="TYPED", target_kind=target, range_ft=range_ft,
                                parameters={"typed": {"numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": source, "effects": rows},
                                            "expected_damage": 0, "seraphic": key, "description": text})

    if FIRST in owned:
        menu = {"type": "menu", "id": SIGN_MENU, "name": "Minor Seraphic Sign", "count": 1, "label": "Choose your Minor Seraphic Sign",
                "options": list(SIGNS), "default": [_acquired_sign(info.get("owner_sheet")) or "Feather-Scar Sign"]}
        out.extend(menus.toggle_actions(info, menu, carry=True))
    if WINGS in owned:
        out.append(button("pinions", "Wingless Ascent: Shielding Pinions", EconomyKind.NONE, "ALLY_OR_SELF", 10,
                          [{"type": "seraphic_pinions", "applies_to": "target"}],
                          "Wingless Ascent (free, your mode for this turn): you or an ally within 10 feet takes Wisdom + Proficiency Bonus less from the first "
                          "Psychic, Radiant or Necrotic damage before the start of your next turn.", WINGS))
    if BURN in owned:
        out.append(button("reintegrate", "Reintegrate the Cast-Off Self", EconomyKind.ACTION, "SELF", None, [{"type": "seraphic_reintegrate", "applies_to": "self"}],
                          "Burn Away the Lesser Self (Action): take your Cast-Off Self back and regain Resonance equal to half your Proficiency Bonus.", BURN))
    return out or None


@hook("candidate_allowed")
def seraphic_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    key = (action.parameters or {}).get("seraphic")
    if key == "pinions":
        held = _held(actor, WINGS_OUT)
        return None if held is not None and int(actor.turns_started) > int((held.data or {}).get("turn") or 0) and not actor.turn_flags.get("wingless_mode") else False
    if key == "reintegrate":
        return None if cast_off_of(engine, actor) is not None else False
    feature = st.feature_of(action)
    if feature == BURN:
        kind = next((r.get("burden") for r in ((action.parameters or {}).get("typed") or {}).get("effects") or [] if isinstance(r, dict) and r.get("type") == "seraphic_burn"), None)
        return None if kind and _burdens(actor, kind) else False
    if feature == NAME:
        return None if _debt_room(actor) else False  # "At maximum Molt Debt, you cannot voluntarily use a feature that would add more"
    return None


@hook("flight")
def throne_flight(engine: Any, actor: Any) -> dict[str, Any] | None:
    if _anatomy(actor, "Throne Wings"):
        return {"fly_speed_ft": 60, "flight_hover": True}
    return None
