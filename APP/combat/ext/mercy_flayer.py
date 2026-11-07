"""Mercy Flayer (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Mercy Flayer: Mercy Scars, CL3 Gentle Knife, CL6 Peel the Wound, CL10 Give the
Pain a Name, CL14 Painless Martyr, CL18 White Room Mercy). No Spheres 5e or D&D 5.5e counterpart. Painless Martyr's Divide the Blow is
combat/ext/damage_sharing.py and Carry the Failure a d20 rewrite in combat/ext/d20_rewrite_rules.py. Ownership: the actions need none;
the Scar rupture is a d20 rule on the Gentle Knife row (feature_blocks.d/riders_c8.json).

Mercy Scars (tradition text): a pool (resource:named.mercy_scar), maximum PB. Gaining one at the maximum ruptures one first (asked;
declining makes the extraction fail). Rupture on a failed Int/Wis/Cha save (asked; a d20 rewrite): the Scar fades, you take 2 x PB
Psychic that nothing reduces, and add your Proficiency Bonus to the save.

What runs:
  * Gentle Knife (Action, touch, 1 Resonance, a willing creature; one button per result): Ease Pain -- one Frightened is suppressed
    for the fight; Take the Edge -- PB + Wisdom Temporary HP and Advantage on its next save against Frightened or direct Spiritual Pressure; Lift the Tremor -- one
    Spiritual Pressure effect ends, or it repeats a save against a Charmed or Frightened (a success ends it). Then you take PB Psychic
    that nothing reduces -- or, when what you eased came from a hostile creature, gain 1 Mercy Scar instead (asked).
  * Peel the Wound (Action, touch, 3 Resonance): one Charmed, Frightened, Poisoned or Spiritual Pressure effect a hostile creature put
    on a willing creature -- a Cultivation Check against its DC. Success (asked): Suppress it for the fight, or Extract it (source CL
    below yours: it ends and you gain a Mercy Scar -- carried, or placed in a Flayed Burden Anchor object: AC your DC, 4 x PB HP, up to
    your Wisdom modifier of them). Failure: Advantage on its next save against the effect, and 2 x PB Psychic to you.
  * Give the Pain a Name (Action, 60 feet, 4 Resonance, a Mercy Scar of yours; a creature bearing your Resonance Mark or a willing
    one): an unwilling target's Wisdom save -- failed, the Scar passes to it until the end of its next turn with one expression you
    choose (asked): your chosen Spiritual Pressure, Frightened until the end of its next turn, Speed -10 and no Reactions, or
    Disadvantage on its next Int/Wis/Cha save; then it comes back. Success: your chosen Spiritual Pressure; the Scar stays. A willing
    creature takes the Scar and you both gain PB Temporary HP (Named Relief, once per fight each).
  * Painless Martyr: Carry the Failure now Resonance Marks the hostile source when the reroll succeeds; used at your Mercy Scar
    maximum, a Scar ruptures first (Martyr's Limit).
  * White Room Mercy (Action, 10 Resonance, the fight, a 30-foot aura on you): allies in it have Advantage on death saves and saves
    against Charmed, Frightened and possession (the zone's inside rule); once on each of your turns a "White Room" button heals an ally
    in it 3d8 + Wisdom or lets it repeat a save against a Charmed or Frightened. Impossible Triage (once, Reaction, asked; a
    life_state death handler): a creature in the aura would die -> Defer (it returns at 1 Hit Point; the GM returns the death at the
    scene's end unless it is changed), Take the Burden (it is Stable and you gain a White Mercy Scar: two Mercy Scars that cannot
    rupture), or House the Burden (it is Stable and a White Room Anchor object holds the death: AC your DC, 10 x PB HP).

Plug-in surface: effects mercy_knife, mercy_peel, mercy_name, mercy_room, mercy_room_tend; hooks compile_actions, candidate_allowed,
turn_end; a d20 rule (mercy_scar_rupture); a life_state death handler (Impossible Triage). Public helpers: ``gain_scar``,
``ordinary_scars``. Shared helpers used: spirit_traditions (context/numbers/feature_of/can_react/save/remove), end_effect (found/
source_action/source_cl/remove_instance/suppress/cultivation_dc), life_state (handler/heal_to/stabilize), needle.ask,
zones.typed_zones, typed_executor.
"""

from __future__ import annotations

from ..paid_relocation import activation

from .map_positions import offset_positions

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.mercy_flayer.feature."
KNIFE = TRADITION + "gentle_knife"
PEEL = TRADITION + "peel_the_wound"
NAME = TRADITION + "give_the_pain_a_name"
MARTYR = TRADITION + "painless_martyr"
ROOM = TRADITION + "white_room_mercy"
SCAR = "resource:named.mercy_scar"
RESONANCE = "resource:core.resonance"
LENT = "condition:typed.lent_mercy_scar"
ROOM_STATE = "condition:typed.white_room"
WHITE_SCAR = "condition:typed.white_mercy_scar"
RELIEF = "condition:typed.named_relief"
BURDEN = "object:typed.flayed_burden:"
WHITE_ANCHOR = "object:typed.white_room_anchor:"
PRESSURE = "condition:typed.spirit_awakening_pressure"
CALM = ("charmed", "frightened")


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _name(condition: Any) -> str:
    return str(condition.condition_id or "").rsplit(".", 1)[-1].lower()


def _unreduced(engine: Any, victim: Any, amount: int, source: str) -> None:
    if amount <= 0 or not victim.active:
        return
    engine.__dict__["_damage_unreduced"] = victim.entity_id
    try:
        engine._commit_damage(victim, amount, "PSYCHIC", source, victim.entity_id, engine._active_intent, reaction_depth=1)
    finally:
        if engine.__dict__.get("_damage_unreduced") == victim.entity_id:
            engine.__dict__.pop("_damage_unreduced", None)


def _subject(ctx: Any, row: dict[str, Any]) -> Any:
    """The creature a touch ability was used on (itself, for a "willing creature" ability aimed at its user)."""
    return next(iter(_te()._default_subject(ctx, row, harmful=False)), None)


def _pb(engine: Any, actor: Any) -> int:
    return int(st.numbers(engine, actor).get("pb") or 2)


def ordinary_scars(flayer: Any) -> int:
    """Mercy Scars that can rupture: a White Mercy Scar counts as two and "cannot rupture for a save bonus"."""
    white = sum(int((c.data or {}).get("count") or 0) for c in flayer.conditions.values() if c.condition_id == WHITE_SCAR)
    return max(0, int(flayer.resources.get(SCAR, 0)) - 2 * white)


def _rupture(engine: Any, flayer: Any, source: str) -> None:
    engine._spend_resource(flayer, SCAR, 1, source)
    _unreduced(engine, flayer, 2 * _pb(engine, flayer), source)


def gain_scar(engine: Any, flayer: Any, source: str, count: int = 1, *, forced: bool = False) -> bool:
    """Gain Mercy Scars. At the maximum one ruptures first -- asked ("choose one existing Scar to rupture immediately, or the
    attempted extraction fails"); ``forced`` when the player already chose a use that requires it (Martyr's Limit). False: nothing
    was gained."""
    from . import needle

    maximum = int(flayer.resource_maximums.get(SCAR, 0) or 0)
    if maximum <= 0:
        return False
    for _ in range(count):
        if flayer.resources.get(SCAR, 0) >= maximum:
            if ordinary_scars(flayer) < 1:
                return False
            if not forced and not needle.ask(
                    engine, engine._active_intent, needle.checkpoint_id(engine, "SCAR_RUPTURE", flayer.entity_id), flayer,
                    "choice:needle.mercy_flayer.rupture_to_gain", ["rupture"], prompt="Your Mercy Scars are full.", preferred=["rupture"],
                    labels={"rupture": f"Rupture a Mercy Scar ({2 * _pb(engine, flayer)} Psychic damage to you that nothing reduces) to take this one"},
                    allow_decline=True, name="Mercy Scars", feature_id=KNIFE):
                return False
            _rupture(engine, flayer, source)
        engine._gain_resource(flayer, SCAR, 1, source)
    return True


# ---------------------------------------------------------------------------------------------------------- buttons and gates
@hook("compile_actions")
def flayer_buttons(info: dict[str, Any]) -> list[Any] | None:
    if ROOM not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    base = {"numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": ROOM}
    return [ActionDefinition(
        source_definition_id=f"action:typed.{info['short']}.white_room.{key}", display_name=label, owner_id=info["actor_id"], economy=EconomyKind.NONE,
        resolution_kind="TYPED", target_kind="ALLY_OR_SELF", range_ft=30,
        parameters={"typed": {**base, "effects": [{"type": "mercy_room_tend", "applies_to": "target", "mode": key}]}, "expected_damage": 0, "white_room": key,
                    "description": f"White Room Mercy (once on each of your turns): {text}"})
        for key, label, text in (("heal", "White Room: heal an ally", "an ally in the aura regains 3d8 + your Wisdom modifier Hit Points."),
                                 ("repeat", "White Room: an ally repeats a save", "an ally in the aura repeats one save against its Charmed or Frightened."))]


def _hostile_calm(engine: Any, creature: Any, names: tuple[str, ...] = CALM) -> list[Any]:
    return [c for _, c in sorted(creature.conditions.items()) if _name(c) in names
            and (lambda s: s is not None and s.team_id != creature.team_id)(engine.state.actors.get(c.source_actor_id or ""))]


def _pressures(creature: Any) -> list[Any]:
    return [c for _, c in sorted(creature.conditions.items()) if str(c.condition_id).startswith(PRESSURE) and c.source_actor_id != creature.entity_id]


def _repeat_save(engine: Any, creature: Any, held: Any, source: str) -> bool:
    """The creature repeats its save against ``held`` (the DC and ability it was put there with); True when that ended it."""
    origin = (held.data or {}).get("origin_save") or {}
    made_by = engine.action_catalog.get(str(held.source_definition_id or ""))
    dc = int(origin.get("dc") or (((getattr(made_by, "parameters", None) or {}).get("typed") or {}).get("numbers") or {}).get("save_dc") or 10)
    roll = engine._roll_save(creature, str(origin.get("ability") or "WIS").upper()[:3], dc, source)
    if roll is not None and roll.total >= dc:
        st.remove(engine, creature, held, "SAVED")
        return True
    return False


def _may_receive(engine: Any, flayer: Any, target: Any) -> bool:
    """Give the Pain a Name's Requirement: "The receiving target is Resonance Marked by you, bears your Mercy Scar through a prior link,
    or is touching a Flayed Burden Anchor"."""
    if _te().bears_mark(target, flayer.entity_id, "Resonance"):
        return True
    if any(c.condition_id == LENT and c.source_actor_id == flayer.entity_id for c in target.conditions.values()):
        return True
    cells = engine._actor_cells(target)
    return any(max(abs(o.position.x - x), abs(o.position.y - y)) <= 1 for o in _anchors(engine, flayer, BURDEN) for x, y in cells)


@hook("candidate_allowed")
def flayer_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None:
        return None
    params = action.parameters or {}
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    room = params.get("white_room")
    if room:
        if (_room(actor) is None or actor.turn_flags.get("white_room_tended") or target is None or target is actor
                or not _in_room(engine, actor, target)):
            return False
        if room == "heal":
            return None if target.current_hp < target.maximum_hp else False
        return None if _hostile_calm(engine, target) else False
    feature = st.feature_of(action)
    kinds = {r.get("type"): r for r in ((params.get("typed") or {}).get("effects") or []) if isinstance(r, dict)}
    if feature == KNIFE and "mercy_knife" in kinds and target is not None:
        mode = kinds["mercy_knife"].get("mode")
        if mode == "ease":
            return None if any(_name(c) == "frightened" for c in target.conditions.values()) else False
        if mode == "tremor":
            return None if _pressures(target) or _hostile_calm(engine, target) else False
        return None
    if feature == PEEL and target is not None:
        return None if _peelable(engine, target) else False
    if feature == NAME:
        return None if actor.resources.get(SCAR, 0) >= 1 and target is not None and target is not actor and _may_receive(engine, actor, target) else False
    return None


# ---------------------------------------------------------------------------------------------------------- Gentle Knife
@effect("mercy_knife")
def knife(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle
    from .end_effect import suppress

    engine, flayer, target = ctx.engine, ctx.actor, _subject(ctx, row)
    if target is None:
        return
    mode = row.get("mode")
    hostile_source = False
    if mode == "ease":
        held = next((c for c in _hostile_calm(engine, target, ("frightened",))), None) or next((c for c in target.conditions.values() if _name(c) == "frightened"), None)
        if held is not None:
            hostile_source = any(c is held for c in _hostile_calm(engine, target, ("frightened",)))
            key = next(k for k, c in target.conditions.items() if c is held)
            suppress(target, "condition", key, held, rounds=100, by=flayer)  # "Suppress one ... fear symptom ... until the end of the scene"
    elif mode == "edge":
        numbers = ctx.numbers or st.numbers(engine, flayer)
        engine._grant_temp_hp(target, int(numbers.get("pb") or 2) + int(numbers.get("key_mod") or 0), KNIFE, flayer.entity_id)
        engine._apply_condition(target, "condition:typed.save_against", ctx.source, flayer.entity_id,
            expires_on=_te().effect_expiry(ctx, {"duration": {"kind": "until_end_of_your_next_turn"}}, target, condition=True),
            data={"mercy_edge": 1, "label": "Take the Edge: Advantage on the next save against Frightened or Spiritual Pressure",
                  "rule": {"save_against": {"mode": "ADVANTAGE", "against": ["frightened"], "abilities": [], "next": True}}})
    else:
        pressures, calm = _pressures(target), _hostile_calm(engine, target)
        if pressures:
            held = pressures[0]
            hostile_source = (lambda s: s is not None and s.team_id != target.team_id)(engine.state.actors.get(held.source_actor_id or ""))
            st.remove(engine, target, held, "LIFTED")  # "End one ordinary Spiritual Pressure effect"
        elif calm:
            hostile_source = _repeat_save(engine, target, calm[0], KNIFE)  # "suppresses or ends an effect created by a ... hostile creature"
    take_scar = False
    if hostile_source and int(flayer.resource_maximums.get(SCAR, 0) or 0):
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "KNIFE_SCAR", target.entity_id), flayer, "choice:needle.mercy_flayer.knife_scar",
                            ["scar"], labels={"scar": "Gain 1 Mercy Scar instead of taking the Psychic damage"}, prompt="Gentle Knife: carry the burden as a Scar?",
                            preferred=["scar"], allow_decline=True, name="Gentle Knife", feature_id=KNIFE)
        take_scar = bool(chosen) and gain_scar(engine, flayer, KNIFE)
    if not take_scar:
        _unreduced(engine, flayer, _pb(engine, flayer), KNIFE)  # "take Psychic damage equal to your Proficiency Bonus. This damage cannot be reduced."


# ---------------------------------------------------------------------------------------------------------- Peel the Wound
def _peelable(engine: Any, target: Any) -> list[tuple[str, str, Any]]:
    from .end_effect import found

    rows = found(engine, target, {"conditions": ["charmed", "frightened", "poisoned"], "select": "hostile"})
    rows += [("condition", key, c) for key, c in target.conditions.items() if c in _pressures(target)
             and (lambda s: s is not None and s.team_id != target.team_id)(engine.state.actors.get(c.source_actor_id or ""))]
    return rows


def _anchors(engine: Any, flayer: Any, prefix: str) -> list[Any]:
    return [o for o in engine.state.objects.values() if o.object_id.startswith(prefix) and o.owner_id == flayer.entity_id and not o.destroyed]


def _place_anchor(engine: Any, flayer: Any, prefix: str, kind: str, hp: int, label: str, immune: tuple[str, ...] = ("POISON", "PSYCHIC")) -> Any:
    from ..gate2_runtime_models import Position, RuntimeObjectState

    taken = {(o.position.x, o.position.y) for o in engine.state.objects.values() if not o.destroyed}
    occupied = set(engine._occupied_cells_except(flayer.entity_id)) | set(engine._actor_cells(flayer))
    around = list(offset_positions(engine, flayer.position, ((dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)))
    spot = next((p for p in around if engine.grid.in_bounds((p.x, p.y)) and (p.x, p.y) not in engine.grid.blocked and (p.x, p.y) not in occupied
                 and (p.x, p.y) not in taken), flayer.position)
    numbers = st.numbers(engine, flayer)
    obj = RuntimeObjectState(object_id=f"{prefix}{flayer.entity_id}:{engine.state.event_sequence}", object_kind=kind, position=spot, unattended=True,
                             flammable=False, owner_id=flayer.entity_id, ac=int(numbers.get("save_dc") or 10), current_hp=hp, maximum_hp=hp,
                             damage_immunities=immune, component={"label": label})
    engine._update_object(obj, flayer.entity_id, flayer.entity_id)
    return obj


@effect("mercy_peel")
def peel(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle
    from .end_effect import cultivation_dc, remove_instance, source_action, source_cl, suppress

    engine, flayer, target = ctx.engine, ctx.actor, _subject(ctx, row)
    rows = _peelable(engine, target) if target is not None else []
    if not rows:
        return
    ids = [f"e{i}" for i in range(len(rows))]
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "PEEL_WHICH", target.entity_id), flayer, "choice:needle.mercy_flayer.peel_which",
                        ids, labels={f"e{i}": _name(item).replace("_", " ").title() for i, (_k, _key, item) in enumerate(rows)}, preferred=ids[:1],
                        prompt=f"Peel the Wound: which affliction on {target.display_name}?", name="Peel the Wound", feature_id=PEEL, target_id=target.entity_id)
    kind, key, item = rows[ids.index(chosen[0])] if chosen and chosen[0] in ids else rows[0]
    from . import run as run_hooks

    # "Make a Cultivation Check against the effect's save DC. If it has no save DC, use 8 + source Proficiency Bonus + source key
    # ability modifier" (its technique's save DC, else its creator's Cultivation Save DC).
    source = engine.state.actors.get(item.source_actor_id or "")
    made_by = source_action(ctx, item)
    dc = int(((item.data or {}).get("origin_save") or {}).get("dc") or 0) or int(
        (((getattr(made_by, "parameters", None) or {}).get("typed") or {}).get("numbers") or {}).get("save_dc") or 0) or (
        cultivation_dc(engine, source) if source is not None else 10)
    numbers = st.numbers(engine, flayer)
    modifier = int(numbers.get("pb") or 2) + int(numbers.get("key_mod") or 0) + sum(run_hooks("check_bonus", ctx, flayer))
    roll = engine.roll_check(modifier=modifier, actor_id=flayer.entity_id, reason=f'CHECK:{PEEL}')
    engine._record_roll(roll)
    engine._append_event("CHECK_ROLLED", PEEL, actor_id=flayer.entity_id, payload={"actor": roll.model_dump(mode="json"), "dc": dc, "success": roll.total >= dc,
                                                                                 "check": "Cultivation Check (Peel the Wound)"})
    if roll.total < dc:
        _te().run_effects(st.context(engine, flayer, ctx.action, [target], numbers, ctx.intent),
                          [{"type": "advantage", "applies_to": "target", "on": f"its next saving throw against being {_name(item).title()}", "duration": {"kind": "until_removed"},
                            "evidence": "The target gains Advantage on its next saving throw against the effect"}])
        _unreduced(engine, flayer, 2 * int(numbers.get("pb") or 2), PEEL)
        return
    can_extract = source_cl(ctx, item) < int(numbers.get("cl") or 1)
    options = {**({"extract": "Extract: it ends and you gain a Mercy Scar"} if can_extract else {}), "suppress": "Suppress it for the fight"}
    pick = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "PEEL_RESULT", target.entity_id), flayer, "choice:needle.mercy_flayer.peel_result",
                      list(options), labels=options, preferred=list(options)[:1], prompt="Peel the Wound: success -- choose one.", name="Peel the Wound",
                      feature_id=PEEL, target_id=target.entity_id)
    choice = pick[0] if pick and pick[0] in options else list(options)[0]
    if choice == "suppress":
        suppress(target, kind, key, item, rounds=100, by=flayer)
        return
    limit = max(1, int(numbers.get("key_mod") or 1))
    where = ["carry", *(["anchor"] if len(_anchors(engine, flayer, BURDEN)) < limit else [])]
    placed = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "PEEL_SCAR", target.entity_id), flayer, "choice:needle.mercy_flayer.peel_scar",
                        where, labels={"carry": "Carry the Mercy Scar yourself", "anchor": "Place it in a Flayed Burden Anchor"}, preferred=where[-1:],
                        prompt="Flayed Burden: where does the Scar go?", name="Peel the Wound", feature_id=PEEL)
    if (placed[0] if placed else where[-1]) == "anchor":
        _place_anchor(engine, flayer, BURDEN, "FLAYED_BURDEN_ANCHOR", 4 * int(numbers.get("pb") or 2), f"Flayed Burden Anchor ({_name(item).title()})")
    elif not gain_scar(engine, flayer, PEEL):
        return  # "or the attempted extraction fails before affecting its source"
    remove_instance(ctx, target, kind, key, item)


# ---------------------------------------------------------------------------------------------------------- Give the Pain a Name
def _lend(engine: Any, flayer: Any, target: Any) -> None:
    engine._spend_resource(flayer, SCAR, 1, NAME)
    engine._apply_condition(target, LENT, NAME, flayer.entity_id, expires_on="UNTIL_REMOVED",
                            data={"turn": int(target.turns_started), "label": f"Carrying {flayer.display_name}'s Mercy Scar until the end of its next turn"})


@effect("mercy_name")
def name_the_pain(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle

    engine, flayer, target = ctx.engine, ctx.actor, ctx.target
    if target is None or not target.active or ordinary_scars(flayer) < 1:
        return
    pb = _pb(engine, flayer)
    if target.team_id == flayer.team_id:  # "A willing receiving target accepts the transfer."
        _lend(engine, flayer, target)
        for creature in (flayer, target):  # Named Relief: "only once per scene for each creature"
            if not any(c.condition_id == RELIEF for c in creature.conditions.values()):
                engine._apply_condition(creature, RELIEF, NAME, flayer.entity_id, expires_on="UNTIL_REMOVED", data={"label": "Named Relief used this fight"})
                engine._grant_temp_hp(creature, pb, NAME, flayer.entity_id)
        return
    pressure = [{"type": "spiritual_pressure", "applies_to": "target", "evidence": "one ordinary Spiritual Pressure effect"}]
    if not st.save(ctx, target, "wis", on_success=pressure):
        return  # "The transfer fails. The target suffers one ordinary Spiritual Pressure effect, and the Scar remains where it was."
    expressions = {"pressure": "A Spiritual Pressure effect", "fear": "Frightened until the end of its next turn (a Scar of fear)",
                   "pain": "Speed -10 and no Reactions (a Scar of pain)", "contamination": "Disadvantage on its next Int/Wis/Cha save (a Scar of spiritual contamination)"}
    chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "NAME_THE_PAIN", target.entity_id), flayer, "choice:needle.mercy_flayer.name_the_pain",
                        list(expressions), labels=expressions, preferred=["pain"], name="Give the Pain a Name", feature_id=NAME, target_id=target.entity_id,
                        prompt="Give the Pain a Name: what did this Scar come from? It carries that burden to the target.")
    pick = chosen[0] if chosen and chosen[0] in expressions else "pain"
    until = {"kind": "until_end_of_next_turn"}
    rows = {"pressure": pressure,
            "fear": [{"type": "condition", "applies_to": "target", "condition": "frightened", "duration": until, "evidence": "Frightened until the end of its next turn"}],
            "pain": [{"type": "speed", "applies_to": "target", "flat": -10, "duration": until, "evidence": "reduce Speed by 10 feet"},
                     {"type": "reaction_denied", "applies_to": "target", "duration": until, "evidence": "and prevent Reactions"}],
            "contamination": [{"type": "disadvantage", "applies_to": "target", "on": "its next Intelligence, Wisdom, or Charisma saving throw", "duration": until,
                               "evidence": "Disadvantage on the next Intelligence, Wisdom, or Charisma save"}]}[pick]
    _lend(engine, flayer, target)
    _te().run_effects(st.context(engine, flayer, ctx.action, [target], ctx.numbers, ctx.intent), rows)


@hook("turn_end")
def scar_returns(engine: Any, actor: Any) -> None:
    """"At the end of the target's next turn, the Scar returns to its prior bearer or Anchor unless another procedure receives it"."""
    for held in [c for c in actor.conditions.values() if c.condition_id == LENT]:
        if actor.turns_started > int((held.data or {}).get("turn") or 0):
            st.remove(engine, actor, held, "RETURNED")
            flayer = engine.state.actors.get(held.source_actor_id or "")
            if flayer is not None and flayer.active:
                gain_scar(engine, flayer, NAME)


# ---------------------------------------------------------------------------------------------------------- Mercy Scar rupture
def _rupture_guard(engine: Any, holder: Any, rc: Any) -> bool:
    return ordinary_scars(holder.actor) >= 1 and rc.dc is not None


def _rupture_ai(engine: Any, holder: Any, rc: Any) -> bool:
    return 0 < int(rc.dc) - int(rc.roll.total) <= _pb(engine, holder.actor)


def _rupture_after(engine: Any, holder: Any, rc: Any, result: Any) -> None:
    _unreduced(engine, holder.actor, 2 * _pb(engine, holder.actor), KNIFE)  # "you take Psychic damage equal to 2 x Proficiency Bonus; this damage cannot be reduced"


def _register_rules() -> None:
    from .d20_rewrite import Rule, register

    register(Rule("mercy_scar_rupture", "Rupture a Mercy Scar", feature=KNIFE, rolls=("save",), who="self", when="failed", op="choose",
                  choose=lambda engine, holder, rc: rc.natural, bonus=lambda engine, holder, rc: _pb(engine, holder.actor), abilities=("INT", "WIS", "CHA"),
                  costs=((("mercy_scar", 1),),), guard=_rupture_guard, ai=_rupture_ai, after=_rupture_after))


_register_rules()


# ---------------------------------------------------------------------------------------------------------- White Room Mercy
def _room(flayer: Any) -> Any:
    return next((c for c in flayer.conditions.values() if c.condition_id == ROOM_STATE and c.source_actor_id == flayer.entity_id), None)


def _in_room(engine: Any, flayer: Any, creature: Any) -> bool:
    from .. import zones

    held = _room(flayer)
    zone = next((z for z in zones.typed_zones(engine) if held is not None and z.owner_id == flayer.entity_id and z.source_definition_id == held.source_definition_id), None)
    return zone is not None and engine._footprint_intersects(creature, zone.affected_cells)


@effect("mercy_room")
def room(ctx: Any, row: dict[str, Any]) -> None:
    held = _room(ctx.actor)
    if held is not None:
        st.remove(ctx.engine, ctx.actor, held, "REPLACED")
    ctx.engine._apply_condition(ctx.actor, ROOM_STATE, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"triage_used": 0, "label": "White Room Mercy: Advantage on death saves and saves against Charmed, Frightened and possession"})


@effect("mercy_room_tend")
def tend(ctx: Any, row: dict[str, Any]) -> None:
    engine, flayer, target = ctx.engine, ctx.actor, ctx.target
    flayer.turn_flags["white_room_tended"] = True  # "Once on each of your turns"
    if target is None or not target.active:
        return
    if row.get("mode") == "heal":
        _te().run_effects(ctx, [{"type": "healing", "applies_to": "target", "dice": {"count": 3, "sides": 8}, "formula": "key_ability_modifier",
                                 "evidence": "It regains 3d8 + Wisdom modifier Hit Points"}])
        return
    held = next(iter(_hostile_calm(engine, target)), None)
    if held is not None:
        _repeat_save(engine, target, held, ROOM)


def impossible_triage(engine: Any, target: Any, cause: str, source_id: str) -> bool:
    """"When a creature in the aura would die ... you may use your Reaction and choose one result" (once during the White Room)."""
    from . import life_state, needle

    for flayer in engine.state.actors.values():
        held = _room(flayer)
        if held is None or flayer is target or not flayer.active or st.data_of(flayer, held).get("triage_used") or not st.can_react(flayer) or not _in_room(engine, flayer, target):
            continue
        pb = _pb(engine, flayer)
        options = {"defer": f"Defer: {target.display_name} returns at 1 Hit Point (the death comes back at the end of the fight unless it is changed)",
                   "take": f"Take the Burden: {target.display_name} is Stable and you gain a White Mercy Scar (counts as two Mercy Scars)",
                   "house": f"House the Burden: {target.display_name} is Stable and a White Room Anchor ({10 * pb} HP) holds its death"}
        if flayer.resources.get(SCAR, 0) + 2 > flayer.resource_maximums.get(SCAR, 0):
            options.pop("take")
        chosen = needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "IMPOSSIBLE_TRIAGE", target.entity_id), flayer,
                            "choice:needle.mercy_flayer.triage", list(options), labels=options, preferred=["house"], allow_decline=True,
                            prompt=f"Impossible Triage (once, your Reaction): {target.display_name} is about to die.", name="Impossible Triage",
                            feature_id=ROOM, target_id=target.entity_id)
        if not chosen or chosen[0] not in options:
            continue
        with activation(engine, flayer, ROOM):
            st.set_data(flayer, held, triage_used=1)
            flayer.reaction_available = False
            engine._append_event("REACTION_RESOLVED", ROOM, actor_id=flayer.entity_id, target_ids=(target.entity_id,),
                                 payload={"checkpoint": "WOULD_DIE", "reaction_name": "Impossible Triage", "choice": chosen[0]})
            if chosen[0] == "defer":
                life_state.heal_to(engine, target, 1, ROOM, flayer.entity_id)
                note(engine, ROOM, flayer, f"Impossible Triage: {target.display_name}'s death is deferred to the end of the scene (the GM returns it unless it is repaired, "
                                           "escaped or exorcised).")
                return True
            if chosen[0] == "take":
                engine._gain_resource(flayer, SCAR, 2, ROOM)
                engine._apply_condition(flayer, WHITE_SCAR, ROOM, flayer.entity_id, expires_on="UNTIL_REMOVED",
                                        data={"count": 1, "label": "White Mercy Scar (counts as two Mercy Scars; cannot rupture)"})
            else:
                _place_anchor(engine, flayer, WHITE_ANCHOR, "WHITE_ROOM_ANCHOR", 10 * pb, f"White Room Anchor ({target.display_name}'s death)",
                              ("POISON", "PSYCHIC", "NECROTIC", "RADIANT"))
            life_state.stabilize(engine, target, ROOM)
            return True
    return False


def _register_triage() -> None:
    from . import life_state

    life_state.handler(impossible_triage, priority=-100)


_register_triage()


@hook("save_effects")
def edge_against_pressure(ctx: Any, subject: Any, ability: str, fail_effects: Any, success_effects: Any, categories: Any) -> dict[str, Any] | None:
    """Direct Spiritual Pressure outcomes consume the same single-use Edge as fear."""
    def pressure(rows: Any) -> bool:
        return any(isinstance(r, dict) and (r.get("type") == "spiritual_pressure" or pressure(r.get("effects") or [])) for r in rows or [])
    if subject is None or not pressure(fail_effects):
        return None
    grants = [c for c in subject.conditions.values() if c.condition_id == "condition:typed.save_against" and (c.data or {}).get("mercy_edge")]
    if not grants:
        return None
    for grant in grants:
        st.remove(ctx.engine, subject, grant, "CONSUMED")
    return {"bonus": 0, "modes": ["ADVANTAGE"]}
