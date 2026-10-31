"""Miko (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, "05. Miko": Offerings, CL3 Purification Dance, CL6 Minor Kami Favor, CL10 Sacred
Ground, CL14 Kami's Messenger, CL18 Kami Descent). No Spheres 5e or D&D 5.5e counterpart. Ownership row: combat/rules/
feature_blocks.d/riders_c8.json (Minor Kami Favor: it has no action of its own; the Favor of the Hearth rule reads it).

Offerings (tradition text): a pool (resource:named.offering), maximum PB, prepared before the fight (it starts full). Brief
Purification costs 1 Offering or 2 Resonance (two buttons); Sacred Ground 5 Resonance and 1 Offering; Kami Descent 10 Resonance and 1
Offering.

What runs:
  * Brief Purification (typed): "Brief Purification: End Poisoned" (end_effect), "...: Advantage against Frightened" (its next save
    before the end of the fight) and "...: Remove a Resonance Mark" (mode ``miko_unmark``: one Resonance Mark a hostile creature of
    lower CL put on the target ends).
  * Minor Kami Favor: "Choose two Minor Kami Favors" is a standing free choice (combat/ext/menus.py; the sheet does not record them;
    the AI and a player who never chose keep Clear Water and Hearth). Favor of Clear Water (Action, 30 feet, 1 Resonance: 1d8 +
    Wisdom Hit Points, once per fight for each creature); Favor of the Guiding Wind (Bonus Action, 30 feet, 1 Resonance: a willing
    creature moves 10 feet, where you choose, without provoking); Favor of the Hearth (Reaction, 1 Resonance, asked; a d20 rewrite):
    you or an ally within 30 feet fails a save against Charmed or Frightened -- add your Proficiency Bonus.
  * Sacred Ground (typed options, CELL within 30 feet, a 20-foot sphere for the fight): "Sacred Ground: Purifying Ground" (allies in it
    have Advantage on saves against Poisoned and Frightened; once per fight each, an ally that starts its turn there may repeat a
    save against a hostile Frightened or Poisoned -- asked) or Welcoming Ground (hostile spirit entry save and a ban on hostile actions until its next turn starts or it is attacked). A Shrine Anchor object stands at
    the center (AC your DC, 5 x PB HP, Poison/Psychic immune); destroying it ends the Ground (``miko_ground``).
  * Kami Descent (Bonus Action, 10 Resonance + 1 Offering, the fight; one button per Descent Aspect): +2 AC and Advantage on saves
    against Charmed and Frightened (typed rows); the Descent Movement is a standing free choice (menus; Processional Step by default:
    walking Speed 60 and nonmagical difficult terrain ignored; Heavenly Flight grants native Fly 60 and Hover. Climb, swim and liquid walking remain open). ``miko_descent`` records the Aspect:
      Purity     -- once per turn, after a Spirit Awakening/Miko action of yours that spent Resonance, one willing creature it affected
                    regains Wisdom-modifier HP or repeats a save against a hostile Frightened/Poisoned (asked); "Kami Purification"
                    (once, Action): up to PB willing creatures within 60 feet each end one Charmed or Frightened (asked who).
      Protection -- a 20-foot aura on you: you and allies in it resist Psychic and Necrotic; once per round (Reaction, 1 Resonance,
                    asked) an ally in it takes 2d10 + Wisdom less damage; "Descent of Protection: Sacred Ground" (once, Action): a
                    Purifying Ground on you that moves with you, no Anchor.
      Revelation -- Spiritual Sense 120 feet; thin-wall perception and the three questions remain open.
      Renewal    -- at the start of each of your turns one willing creature within 30 feet with at least 1 HP regains Wisdom-modifier
                    HP (asked which); "Descent of Renewal: restore" (once, Action, touch): 8d8 + Wisdom HP and one hostile Poisoned
                    ends.

Plug-in surface: effects miko_unmark, miko_favor, miko_ground, miko_descent, miko_descent_once; hooks compile_actions,
candidate_allowed, row_allowed (a Welcoming Ground ban also closes hostile generic triggered reactions, whose own
admission does not pass through candidate_allowed), event (Shrine Anchor), turn_start, technique_used,
incoming_damage, speed; a d20 rule (favor_of_the_hearth).
Shared helpers used: spirit_traditions (row/context/numbers/feature_of/is_spirit_feature/affected_by/pick_creature/routes/
choose_route/can_react/remove), menus (toggle_actions/picks), end_effect.source_cl, needle (ask/step_to), zones (create/remove/
typed_zones), typed_executor.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st
from ..effect_harm import classify_effect

TRADITION = "tianxia.tradition.spirit.miko.feature."
DANCE = TRADITION + "purification_dance"
FAVOR = TRADITION + "minor_kami_favor"
GROUND = TRADITION + "sacred_ground"
DESCENT = TRADITION + "kami_descent"
OFFERING = "resource:named.offering"
RESONANCE = "resource:core.resonance"
FAVOR_MENU = "miko.minor_kami_favors"
FAVORS = ("Clear Water", "Guiding Wind", "Hearth", "Harvest", "Lantern", "Shrine Hound")
MOVE_MENU = "miko.descent_movement"
MOVES = ("Heavenly Flight", "Sacred Ascent", "River Passage", "Processional Step")
CLEAR_WATER = "condition:typed.favor_of_clear_water"
DESCENDED = "condition:typed.kami_descent"
ANCHOR = "object:typed.shrine_anchor:"
GROUND_USED = "condition:typed.purifying_ground_used"
CALM = ("charmed", "frightened")
PURIFICATION = ("frightened", "poisoned", "possession", "possessed", "curse", "cursed", "disease", "diseased", "spiritual_contamination")


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def _name(condition: Any) -> str:
    return str(condition.condition_id or "").rsplit(".", 1)[-1].lower()


def _hostile_made(engine: Any, creature: Any, condition: Any) -> bool:
    source = engine.state.actors.get(condition.source_actor_id or "")
    return source is not None and source.team_id != creature.team_id


def _afflictions(engine: Any, creature: Any, names: tuple[str, ...]) -> list[Any]:
    return [c for _, c in sorted(creature.conditions.items()) if _name(c) in names]


def _hostile_afflictions(engine: Any, creature: Any, names: tuple[str, ...]) -> list[Any]:
    """Conditions a repeat save may end: only those a hostile creature made, so an ally's or the Miko's own condition is never offered."""
    return [c for c in _afflictions(engine, creature, names) if _hostile_made(engine, creature, c)]


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


def _heal(engine: Any, miko: Any, feature: str, creature: Any, rows: list[dict[str, Any]]) -> None:
    _te().run_effects(st.context(engine, miko, st.feature_action(engine, miko, feature), [creature], st.numbers(engine, miko)), rows)


# ---------------------------------------------------------------------------------------------------------- Brief Purification
@effect("miko_unmark")
def unmark(ctx: Any, row: dict[str, Any]) -> None:
    """"Remove one ordinary Resonance Mark ... with Source CL lower than yours"."""
    target = next(iter(_te()._default_subject(ctx, row, harmful=False)), None)
    marks = _marks(ctx, target) if target is not None else []
    if marks:
        st.remove(ctx.engine, target, marks[0], "PURIFIED")


def _marks(ctx: Any, target: Any) -> list[Any]:
    from .end_effect import source_cl

    te = _te()
    mine = int((ctx.numbers or {}).get("cl") or 1)
    return [c for _, c in sorted(target.conditions.items())
            if c.condition_id in te.mark_requirement_ids("Resonance", c.source_actor_id) and _hostile_made(ctx.engine, target, c)
            and source_cl(ctx, c) < mine]


# ---------------------------------------------------------------------------------------------------------- buttons
def _favor_menu() -> dict[str, Any]:
    return {"type": "menu", "id": FAVOR_MENU, "name": "Minor Kami Favors", "count": 2, "label": "Choose your two Minor Kami Favors",
            "options": list(FAVORS), "default": ["Clear Water", "Hearth"]}


def _move_menu() -> dict[str, Any]:
    return {"type": "menu", "id": MOVE_MENU, "name": "Descent Movement", "count": 1, "label": "Choose your recorded Descent Movement",
            "options": list(MOVES), "default": ["Processional Step"]}


@hook("compile_actions")
def miko_buttons(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    from . import menus

    owned = info["owned_ids"]
    out: list[Any] = []
    numbers = info["numbers"]

    def button(key: str, name: str, economy: Any, target: str, range_ft: int, effects: list[dict[str, Any]], text: str, source: str,
               costs: tuple = ()) -> Any:
        return ActionDefinition(
            source_definition_id=f"action:typed.{info['short']}.miko.{key}", display_name=name, owner_id=info["actor_id"], economy=economy,
            resolution_kind="TYPED", target_kind=target, range_ft=range_ft, costs=costs,
            parameters={"typed": {"numbers": numbers, "duration": {"kind": "instant"}, "riders": [], "source": source, "effects": effects},
                        "expected_damage": 0, "miko": key, "description": text})

    if FAVOR in owned:
        for toggle in menus.toggle_actions(info, _favor_menu(), carry=True):
            out.append(toggle.model_copy(update={"parameters": {**toggle.parameters, "description":
                       f"Minor Kami Favor: make {toggle.parameters.get('menu_option')} one of your two Favors (free; it stays until you change it; "
                       "choosing another replaces the one chosen longest ago)."}}))
        resonance = ((RESONANCE, 1),)
        out.append(button("clear_water", "Favor of Clear Water", EconomyKind.ACTION, "ALLY_OR_SELF", 30,
                          [{"type": "miko_favor", "applies_to": "target", "favor": "Clear Water"}],
                          "Minor Kami Favor (1 Resonance): one willing creature within 30 feet regains 1d8 + your Wisdom modifier Hit Points "
                          "(once per fight for each creature).", FAVOR, resonance))
        out.append(button("guiding_wind", "Favor of the Guiding Wind", EconomyKind.BONUS_ACTION, "ALLY_OR_SELF", 30,
                          [{"type": "miko_favor", "applies_to": "target", "favor": "Guiding Wind"}],
                          "Minor Kami Favor (1 Resonance): move one willing creature within 30 feet up to 10 feet; this does not provoke "
                          "Opportunity Attacks.", FAVOR, resonance))
    if DESCENT in owned:
        for toggle in menus.toggle_actions(info, _move_menu(), carry=True):
            out.append(toggle.model_copy(update={"parameters": {**toggle.parameters, "description":
                       f"Kami Descent: record {toggle.parameters.get('menu_option')} as your Descent Movement (free; it stays until you "
                       "change it). Heavenly Flight grants Fly 60 feet with Hover; Processional Step grants walking Speed 60 feet."}}))
        out.append(button("purification", "Kami Purification", EconomyKind.ACTION, "SELF", 0,
                          [{"type": "miko_descent_once", "applies_to": "self", "mode": "purity"}],
                          "Descent of Purity (once during the Descent, free): up to your Proficiency Bonus willing creatures within 60 feet "
                          "each end one Charmed or Frightened condition.", DESCENT))
        out.append(button("protection_ground", "Descent of Protection: Sacred Ground", EconomyKind.ACTION, "SELF", 0,
                          [{"type": "miko_descent_once", "applies_to": "self", "mode": "protection"}],
                          "Descent of Protection (once during the Descent, free): a Purifying Ground centered on you that moves with you "
                          "until the Descent ends.", DESCENT))
        out.append(button("renewal_restore", "Descent of Renewal: restore", EconomyKind.ACTION, "ALLY_OR_SELF", 5,
                          [{"type": "miko_descent_once", "applies_to": "target", "mode": "renewal"}],
                          "Descent of Renewal (once during the Descent): touch one creature; it regains 8d8 + your Wisdom modifier Hit Points "
                          "and one Poisoned condition a hostile creature caused ends.", DESCENT))
    return out or None


def _descent(miko: Any) -> Any:
    return next((c for c in miko.conditions.values() if c.condition_id == DESCENDED and c.source_actor_id == miko.entity_id), None)


@hook("candidate_allowed")
def miko_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    from . import menus

    if action is None:
        return None
    params = action.parameters or {}
    key = params.get("miko")
    target = engine.state.actors.get(next(iter(getattr(candidate, "target_ids", None) or ()), ""))
    if st.feature_of(action) == DANCE and any(isinstance(r, dict) and r.get("type") == "miko_unmark" for r in ((params.get("typed") or {}).get("effects") or [])):
        return None if target is not None and _marks(st.context(engine, actor, action, [target]), target) else False
    if key in ("clear_water", "guiding_wind"):
        favor = "Clear Water" if key == "clear_water" else "Guiding Wind"
        if favor not in menus.picks(engine, actor, FAVOR_MENU):
            return False
        if key == "clear_water" and target is not None and (target.current_hp >= target.maximum_hp or any(c.condition_id == CLEAR_WATER for c in target.conditions.values())):
            return False  # "A creature can benefit from this Favor only once per scene."
        return None
    if key in ("purification", "protection_ground", "renewal_restore"):
        held = _descent(actor)
        aspect = {"purification": "purity", "protection_ground": "protection", "renewal_restore": "renewal"}[key]
        if held is None or (held.data or {}).get("aspect") != aspect or st.data_of(actor, held).get(f"{aspect}_used"):
            return False
        if key == "purification":
            return None if _purifiable(engine, actor) else False
        return None
    return None


# ---------------------------------------------------------------------------------------------------------- Minor Kami Favor
@effect("miko_favor")
def favor(ctx: Any, row: dict[str, Any]) -> None:
    engine, miko = ctx.engine, ctx.actor
    target = next(iter(_te()._default_subject(ctx, row, harmful=False)), None)
    if target is None or not target.active:
        return
    if row.get("favor") == "Clear Water":
        engine._apply_condition(target, CLEAR_WATER, ctx.source, miko.entity_id, expires_on="UNTIL_REMOVED",
                                data={"label": "Favor of Clear Water used on it this fight"})
        _te().run_effects(ctx, [{"type": "healing", "applies_to": "target", "dice": {"count": 1, "sides": 8}, "formula": "key_ability_modifier",
                                 "evidence": "One willing creature regains Hit Points equal to 1d8 + Wisdom modifier"}])
        return
    spots = {c: v for c, v in st.routes(engine, target, 10).items() if c != target.position}
    path = st.choose_route(engine, miko, spots, ctx.intent, checkpoint="GUIDING_WIND", prompt=f"Favor of the Guiding Wind: move {target.display_name} where?",
                           name="Favor of the Guiding Wind", feature=FAVOR) if spots else None
    if path is not None:
        from . import needle

        needle.step_to(engine, target, path[-1], FAVOR)  # "This movement does not provoke opportunity attacks."


def _hearth_guard(engine: Any, holder: Any, rc: Any) -> bool:
    from . import menus

    return "Hearth" in menus.picks(engine, holder.actor, FAVOR_MENU) and bool(set(rc.named) & set(CALM))


def _hearth_ai(engine: Any, holder: Any, rc: Any) -> bool:
    return 0 < int(rc.dc) - int(rc.roll.total) <= int(st.numbers(engine, holder.actor).get("pb") or 2)


def _register_rules() -> None:
    from .d20_rewrite import Rule, register

    register(Rule("favor_of_the_hearth", "Favor of the Hearth", feature=FAVOR, rolls=("save",), who="team", range_ft=30, when="failed", op="choose",
                  choose=lambda engine, holder, rc: rc.natural, bonus=lambda engine, holder, rc: int(st.numbers(engine, holder.actor).get("pb") or 2),
                  costs=((("resonance", 1),),), reaction=True, checkpoint="D20_REROLL_ALLY", guard=_hearth_guard, ai=_hearth_ai))


_register_rules()


# ---------------------------------------------------------------------------------------------------------- Sacred Ground
PURIFYING = [{"id": "sacred_ground:purifying", "who": "ally", "name": "Purifying Ground",
              "rule": {"save_against": {"mode": "ADVANTAGE", "against": list(PURIFICATION)}},
              "reading": "Allies in the Purifying Ground have Advantage on saving throws against possession, curses, disease, poison, Frightened and spiritual contamination."}]


def _grounds(engine: Any) -> list[Any]:
    from .. import zones

    return [z for z in zones.typed_zones(engine) if (z.trigger_profile or {}).get("miko_ground")]


@effect("miko_ground")
def ground(ctx: Any, row: dict[str, Any]) -> None:
    """The Ground the zone row just made: its aspect, and (unless it is the Descent's) a Shrine Anchor at its center."""
    from ..gate2_runtime_models import RuntimeObjectState
    from .. import zones

    engine, miko = ctx.engine, ctx.actor
    zone = next((z for z in reversed(zones.typed_zones(engine)) if z.owner_id == miko.entity_id and z.source_definition_id == ctx.source), None)
    if zone is None:
        return
    profile = {**zone.trigger_profile, "miko_ground": str(row.get("aspect") or "purifying")}
    if not row.get("no_anchor"):
        pb = int((ctx.numbers or {}).get("pb") or 2)
        anchor = RuntimeObjectState(object_id=f"{ANCHOR}{miko.entity_id}:{engine.state.event_sequence}", object_kind="SHRINE_ANCHOR", position=zone.center,
                                    unattended=True, flammable=False, owner_id=miko.entity_id, ac=int((ctx.numbers or {}).get("save_dc") or 10),
                                    current_hp=5 * pb, maximum_hp=5 * pb, damage_immunities=("POISON", "PSYCHIC"),
                                    component={"label": "Shrine Anchor (Sacred Ground)", "zone_id": zone.zone_id})
        engine._update_object(anchor, ctx.source, miko.entity_id)
        profile["anchor"] = anchor.object_id
    zone.trigger_profile = profile
    engine._append_event("ZONE_CREATED", ctx.source, actor_id=miko.entity_id, payload={"zone": zone.model_dump(mode="json")})


@hook("event")
def shrine_anchor_breaks(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """"Sacred Ground ends if the Anchor is destroyed"."""
    if event_type != "OBJECT_UPDATED":
        return
    obj = (kwargs.get("payload") or {}).get("object") or {}
    if not str(obj.get("object_id") or "").startswith(ANCHOR) or not (obj.get("destroyed") or int(obj.get("current_hp") or 0) <= 0):
        return
    from .. import zones

    for zone in _grounds(engine):
        if zone.trigger_profile.get("anchor") == obj.get("object_id"):
            zones.remove(engine, zone, "ANCHOR_DESTROYED")


@hook("turn_start")
def ground_and_renewal(engine: Any, actor: Any) -> None:
    from . import needle

    # Purifying Ground: "A willing ally that starts its turn there can repeat one save against an ongoing qualifying effect once per scene."
    if actor.active and not any(c.condition_id == GROUND_USED for c in actor.conditions.values()):
        for zone in _grounds(engine):
            owner = engine.state.actors.get(zone.owner_id)
            if (zone.trigger_profile.get("miko_ground") != "purifying" or owner is None or owner.team_id != actor.team_id
                    or not engine._footprint_intersects(actor, zone.affected_cells)):
                continue
            held = next(iter(_hostile_afflictions(engine, actor, PURIFICATION)), None)
            if held is None:
                break
            label = _name(held).title()
            if needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "PURIFYING_GROUND", actor.entity_id), actor,
                          "choice:needle.miko.purifying_ground", ["repeat"], labels={"repeat": f"Repeat your save against {label} (once per fight)"},
                          prompt="Purifying Ground: repeat a save now?", preferred=["repeat"], allow_decline=True, name="Purifying Ground", feature_id=GROUND):
                engine._apply_condition(actor, GROUND_USED, GROUND, zone.owner_id, expires_on="UNTIL_REMOVED", data={"label": "Purifying Ground's repeated save used"})
                _repeat_save(engine, actor, held, GROUND)
            break
    # Descent of Renewal: "At the start of each of your turns, one willing creature you can perceive within 30 feet regains Hit Points equal
    # to your Wisdom modifier if it has at least 1 Hit Point."
    held = _descent(actor)
    if held is not None and (held.data or {}).get("aspect") == "renewal":
        near = [c for c in engine.state.actors.values() if c.active and c.team_id == actor.team_id and c.current_hp >= 1
                and engine._distance_actor_to_actor(actor, c) <= 30
                and _perceives(engine, actor, c)]
        hurt = sorted(near, key=lambda c: (c.current_hp - c.maximum_hp, c.entity_id))
        chosen = st.pick_creature(engine, engine._active_intent, actor, hurt, checkpoint="DESCENT_RENEWAL", choice_id="choice:needle.miko.renewal",
                                  prompt="Descent of Renewal: who regains Hit Points?", name="Descent of Renewal", feature_id=DESCENT,
                                  preferred=hurt[0] if hurt else None)
        if chosen is not None:
            _heal(engine, actor, DESCENT, chosen, [{"type": "healing", "applies_to": "target", "formula": "key_ability_modifier",
                                                    "evidence": "regains Hit Points equal to your Wisdom modifier"}])


# ---------------------------------------------------------------------------------------------------------- Kami Descent
@effect("miko_descent")
def descend(ctx: Any, row: dict[str, Any]) -> None:
    from . import menus
    from .. import zones

    engine, miko = ctx.engine, ctx.actor
    held = _descent(miko)
    if held is not None:
        st.remove(engine, miko, held, "REPLACED")
    aspect = str(row.get("aspect") or "purity")
    movement = next(iter(menus.picks(engine, miko, MOVE_MENU)), "Processional Step")
    processional = movement == "Processional Step"
    engine._apply_condition(miko, DESCENDED, ctx.source, miko.entity_id, expires_on="UNTIL_REMOVED",
                            data={"aspect": aspect, "movement": movement, "processional": processional,
                                  **({"fly_speed_ft": 60, "flight_hover": 1} if movement == "Heavenly Flight" else {}),
                                  "rule": {"save_against": {"mode": "ADVANTAGE", "against": ["possession", "possessed", "curse", "cursed", "frightened", "charmed", "spiritual_contamination"]},
                                           **({"ignore_difficult": True} if processional else {})},
                                  "label": f"Kami Descent: Descent of {aspect.title()}; Advantage against possession, curses, Frightened, Charmed and spiritual contamination"})
    if aspect == "revelation":
        _te().run_effects(ctx, [{"type": "gain_sense", "sense": "spiritual_sense", "range_ft": 120,
                                 "requires_condition": DESCENDED,
                                 "requires_condition_data": {"aspect": "revelation"}}])
    if aspect == "protection":
        zones.create(ctx, {"shape": "emanation", "size_ft": 20, "centered_on_self": True, "follows_owner": True, "duration": {"kind": "scene"},
                           "name": "Descent of Protection",
                           "inside": [{"id": "kami_descent:protection", "who": "ally", "name": "Descent of Protection",
                                       "modifiers": [{"field": "damage_resistance", "value": "PSYCHIC"}, {"field": "damage_resistance", "value": "NECROTIC"}],
                                       "reading": "You and allies within 20 feet have Resistance to Psychic and Necrotic damage."}]})


@hook("speed")
def processional_step(engine: Any, actor: Any) -> int | None:
    """Processional Step: "walking Speed becomes 60 feet"."""
    held = _descent(actor)
    if held is None or not (held.data or {}).get("processional"):
        return None
    return max(0, 60 - int(actor.speed_ft))


def _purifiable(engine: Any, miko: Any) -> list[Any]:
    return [c for c in engine.state.actors.values() if c.active and c.team_id == miko.team_id and engine._distance_actor_to_actor(miko, c) <= 60
            and any(_name(h) in CALM for h in c.conditions.values())]


@effect("miko_descent_once")
def descent_once(ctx: Any, row: dict[str, Any]) -> None:
    from . import needle
    from .. import zones

    engine, miko = ctx.engine, ctx.actor
    held = _descent(miko)
    mode = str(row.get("mode"))
    if held is None:
        return
    st.set_data(miko, held, **{f"{mode}_used": True})  # "Once during the Descent"
    numbers = ctx.numbers or st.numbers(engine, miko)
    if mode == "purity":
        creatures = _purifiable(engine, miko)
        ids = [c.entity_id for c in creatures]
        pb = int(numbers.get("pb") or 2)
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "KAMI_PURIFICATION", miko.entity_id), miko, "choice:needle.miko.purification",
                            ids, labels={c.entity_id: c.display_name for c in creatures}, preferred=ids[:pb], minimum=1, maximum=min(pb, len(ids)), default="all",
                            prompt=f"Kami Purification: up to {pb} willing creatures end one Charmed or Frightened.", name="Kami Purification", feature_id=DESCENT)
        for creature in [c for c in creatures if c.entity_id in (chosen or ids[:pb])][:pb]:
            ending = next((c for _, c in sorted(creature.conditions.items()) if _name(c) in CALM), None)
            if ending is not None:
                st.remove(engine, creature, ending, "PURIFIED")  # "end one ordinary Charmed or Frightened condition"
    elif mode == "protection":
        zone = zones.create(ctx, {"shape": "sphere", "size_ft": 20, "centered_on_self": True, "follows_owner": True, "duration": {"kind": "scene"},
                                  "name": "Sacred Ground (Descent of Protection)", "inside": list(PURIFYING)})
        if zone is not None:
            ground(ctx, {"aspect": "purifying", "no_anchor": True})
    elif mode == "renewal":
        target = next(iter(_te()._default_subject(ctx, row, harmful=False)), None)
        if target is None:
            return
        _te().run_effects(ctx, [{"type": "healing", "applies_to": "target", "dice": {"count": 8, "sides": 8}, "formula": "key_ability_modifier",
                                 "evidence": "restore 8d8 + Wisdom modifier Hit Points"}])
        poison = next((c for c in _afflictions(engine, target, ("poisoned", "disease", "diseased"))
                       if (c.data or {}).get("ordinary") is not False
                       and not any((c.data or {}).get(k) for k in ("legendary", "secret", "artifact", "realm_defining"))), None)
        if poison is not None:
            st.remove(engine, target, poison, "PURIFIED")  # "end one ordinary poison or disease"


@hook("technique_used")
def descent_of_purity(ctx: Any) -> None:
    """"Once per turn when you spend Resonance on a Miko or Spirit Awakening feature, one willing creature affected by that feature regains
    Hit Points equal to your Wisdom modifier or repeats one save against possession, curse, poison, disease, Frightened, or spiritual
    contamination"."""
    from . import needle

    engine, miko = ctx.engine, ctx.actor
    held = _descent(miko)
    if held is None or (held.data or {}).get("aspect") != "purity" or not st.is_spirit_feature(ctx.action):
        return
    paid = int(dict(getattr(ctx.action, "costs", None) or ()).get(RESONANCE) or 0) > 0  # the printed cost is paid before the technique starts
    if not paid and not any(e.event_type == "RESOURCE_SPENT" and (e.payload or {}).get("resource_id") == RESONANCE and e.source_definition_id == ctx.source
                            for e in st.activation_events(engine, ctx)):
        return
    turn_key = f"{engine.state.round_number}:{engine.state.current_slot_index}"
    if st.data_of(miko, held).get("purity_turn") == turn_key:
        return
    affected = list({c.entity_id: c for c in [*(t for t in ctx.targets if t is miko), *st.affected_by(engine, ctx)]
                     if c.active and c.team_id == miko.team_id}.values())
    creature = st.pick_creature(engine, ctx.intent, miko, affected, checkpoint="DESCENT_PURITY", choice_id="choice:needle.miko.purity",
                                prompt=f"Descent of Purity: after {ctx.action.display_name}, which willing creature is purified?", name="Descent of Purity",
                                feature_id=DESCENT, allow_decline=True)
    if creature is None:
        return
    st.set_data(miko, held, purity_turn=turn_key)
    afflicted = next(iter(_hostile_afflictions(engine, creature, PURIFICATION)), None)
    options = {"heal": f"{creature.display_name} regains Hit Points equal to your Wisdom modifier",
               **({"save": f"{creature.display_name} repeats its save against {_name(afflicted).title()}"} if afflicted is not None else {})}
    pick = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "DESCENT_PURITY_WHAT", creature.entity_id), miko, "choice:needle.miko.purity_what",
                      list(options), labels=options, preferred=["save" if afflicted is not None else "heal"], prompt="Descent of Purity: which blessing?",
                      name="Descent of Purity", feature_id=DESCENT, target_id=creature.entity_id)
    if (pick[0] if pick else "heal") == "save" and afflicted is not None:
        _repeat_save(engine, creature, afflicted, DESCENT)
    else:
        _heal(engine, miko, DESCENT, creature, [{"type": "healing", "applies_to": "target", "formula": "key_ability_modifier",
                                                  "evidence": "regains Hit Points equal to your Wisdom modifier"}])


@hook("incoming_damage")
def descent_of_protection(engine: Any, target: Any, amount: int, damage_type: str, source_definition_id: str, source_actor_id: str | None) -> int | None:
    """"Once per round when an ally in that aura takes damage, use your Reaction and spend 1 Resonance to reduce the damage by 2d10 + Wisdom
    modifier"."""
    from . import needle
    from .. import zones

    if amount <= 0:
        return None
    for miko in engine.state.actors.values():
        held = _descent(miko)
        if (held is None or miko is target or (held.data or {}).get("aspect") != "protection" or miko.team_id != target.team_id
                or not st.can_react(miko) or miko.resources.get(RESONANCE, 0) < 1 or st.data_of(miko, held).get("protection_round") == engine.state.round_number):
            continue
        aura = next((z for z in zones.typed_zones(engine) if z.owner_id == miko.entity_id and z.source_definition_id == held.source_definition_id), None)
        if aura is None or not engine._footprint_intersects(target, aura.affected_cells):
            continue
        wis = int(st.numbers(engine, miko).get("key_mod") or 0)
        if not needle.ask(engine, engine._active_intent, needle.checkpoint_id(engine, "DESCENT_PROTECTION", target.entity_id), miko,
                          "choice:needle.miko.protection", ["reduce"], labels={"reduce": f"Reduce the {amount} damage by 2d10 + {wis} (Reaction, 1 Resonance)"},
                          prompt=f"Descent of Protection: {target.display_name} takes damage.", preferred=["reduce"], allow_decline=True,
                          name="Descent of Protection", feature_id=DESCENT, target_id=target.entity_id):
            continue
        with activation(engine, miko, DESCENT):
            st.set_data(miko, held, protection_round=engine.state.round_number)
            miko.reaction_available = False
            engine._spend_resource(miko, RESONANCE, 1, DESCENT)
            from ..gate2_runtime_models import DiceSpec

            roll = engine.roller.roll(DiceSpec(count=2, sides=10, modifier=wis), actor_id=miko.entity_id, reason=f"DAMAGE_REDUCTION:{DESCENT}")
            engine._record_roll(roll)
            reduction = max(0, int(roll.total))
            engine._append_event("REACTION_RESOLVED", DESCENT, actor_id=miko.entity_id, target_ids=(target.entity_id,),
                                 payload={"checkpoint": "DAMAGE_TAKEN", "reaction_name": "Descent of Protection", "reduction": reduction})
            return min(amount, reduction)  # incoming_damage returns the points taken off
    return None


# A2GTRA4: current native creature kinds and flight replace obsolete GM riders.
def _perceives(engine: Any, viewer: Any, target: Any) -> bool:
    from ..senses import perceives
    return viewer is target or perceives(engine, viewer, target, locate_concealed=True)


@hook("before_attack")
def purifying_ground_attack(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    from .creature_kinds import matches
    if attacker is None or not matches(attacker, ("undead", "fiend", "demon", "intruder")):
        return None
    for zone in _grounds(engine):
        owner = engine.state.actors.get(zone.owner_id)
        if (zone.trigger_profile.get("miko_ground") != "purifying" or owner is None
                or owner.team_id == attacker.team_id or not _in_ground(engine, attacker, zone)):
            continue
        # The printed allowance belongs to the creature, shared across overlapping Grounds.
        clock = f"{engine.state.round_number}:{engine.state.current_slot_index}"
        if attacker.turn_flags.get("miko_first_attack") == clock:
            return None
        attacker.turn_flags["miko_first_attack"] = clock
        return {"mode": "DISADVANTAGE"}
    return None


def _in_ground(engine: Any, actor: Any, zone: Any) -> bool:
    from ..spatial_areas import zone_contains
    return zone_contains(engine, actor, zone)


WELCOMED = "condition:typed.welcoming_ground"


def holder_turn_start(actor: Any) -> str:
    """"until the start of its next turn" on a condition this module puts on a creature.

    Shared expiry-name helper (combat/ext/effect_durations.holder_next_turn): the holder's own turn counter,
    so an intervening turn of the Ground's owner cannot free it early.
    """
    from . import effect_durations

    return effect_durations.holder_next_turn(actor)


@hook("zone_arrival")
def welcoming_ground_entry(engine: Any, mover: Any, start: Any, end: Any, forced: bool) -> None:
    from ..spatial_areas import zone_contains
    from .creature_kinds import matches
    if not mover.active or not matches(mover, ("spirit", "ghost", "kami", "projected soul", "possession entity")):
        return
    for zone in _grounds(engine):
        owner = engine.state.actors.get(zone.owner_id)
        if (zone.trigger_profile.get("miko_ground") != "welcoming" or owner is None or owner.team_id == mover.team_id
                or zone_contains(engine, mover, zone, at=start) or not zone_contains(engine, mover, zone, at=end)):
            continue
        clock = f"{engine.state.round_number}:{engine.state.current_slot_index}"
        key = f"miko_welcoming:{zone.zone_id}"
        if mover.turn_flags.get(key) == clock:
            continue
        mover.turn_flags[key] = clock
        ctx = st.context(engine, owner, st.feature_action(engine, owner, GROUND), [mover], st.numbers(engine, owner))
        if st.save(ctx, mover, "cha"):
            # "until the start of its next turn": the ban lives on the spirit's own turn clock
            # (effect_durations.token), never START_OF_TARGET_NEXT_TURN -- that name is swept at the start of the
            # applier's next turn too, so a spirit welcomed on its own turn would be freed before its own turn came
            # round again and could act hostilely in between (bug 3, tests/test_expiry_names.py).
            engine._apply_condition(mover, WELCOMED, zone.source_definition_id, owner.entity_id,
                                    expires_on=holder_turn_start(mover),
                                    data={"label": "Welcoming Ground: cannot take hostile actions until its next turn starts; being attacked ends this"})


def _welcomed(actor: Any) -> bool:
    return any(c.condition_id == WELCOMED for c in actor.conditions.values())


# One reading of "a hostile action", shared by every seam that has to answer it.
def _takes_on_another(row: dict[str, Any], numbers: dict[str, Any] | None = None, *,
                      ability_mods: dict[str, Any] | None = None, weapon: dict[str, Any] | None = None) -> bool:
    """Whether a row affects another creature harmfully, using the shared harm contract.

    Self effects do not reach another creature. Signed modifier amounts are
    interpreted without rolling; plug-in effect declarations and native
    condition/damage semantics are handled by ``effect_harm``.
    """
    if row.get("applies_to") == "self":
        return False  # nothing done to anyone else
    # Native typed effects and plug-in declarations share one harm contract.
    # In particular, speed/ac rows honor their actual `amount` encoding and
    # unflagged conditions are harmful by their native operation semantics.
    return classify_effect(row, numbers=numbers, ability_mods=ability_mods, weapon=weapon) is True


@hook("candidate_allowed")
def welcoming_ground_actions(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not _welcomed(actor):
        return None
    if action.target_kind == "HOSTILE_ENTITY" or action.attack_bonus is not None:
        return False
    # Areas and hostile self-origin techniques also count as hostile actions.
    typed = (action.parameters or {}).get("typed") or {}
    return False if any(_takes_on_another(r, typed.get("numbers"), ability_mods=typed.get("ability_mods"),
                                         weapon=typed.get("weapon"))
                        for r in _te()._walk_rows(typed.get("effects") or [])) else None


@hook("row_allowed")
def welcoming_ground_triggered_reactions(engine: Any, actor: Any, row: Any) -> bool | None:
    """"...it cannot take hostile actions until the start of its next turn unless attacked."

    ``candidate_allowed`` only covers the spirit's own turn and ``opportunity_allowed`` only covers an
    opportunity attack. A generic *triggered* reaction -- ``ally_attacked``'s bystander counterattack or penalty,
    any free ``when a creature is hit`` row -- runs its own admission (``typed_reactions._can_trigger`` and
    ``_ally_row_ok``) and would otherwise slip the ban entirely. ``row_allowed`` is the existing documented seam
    that every one of those paths asks (``_can_trigger``, ``_open``, ``_can_react``), so one answer here gates
    them all.

    Only hostile rows are refused: a reaction that helps the spirit or a third party is not a hostile action and
    stays available, which is what the printed sentence keeps.
    """
    if actor is None or not row or not _welcomed(actor):
        return None
    return False if any(_takes_on_another(r, row.get("numbers"), ability_mods=row.get("ability_mods"),
                                         weapon=row.get("weapon"))
                        for r in _te()._walk_rows(row.get("effects") or [])) else None


@hook("opportunity_allowed")
def welcoming_ground_reactions(engine: Any, reactor: Any, mover: Any) -> bool | None:
    return False if _welcomed(reactor) else None


@hook("event")
def welcoming_ground_attacked(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "ATTACK_ROLLED":
        return
    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        if target is not None:
            for held in list(target.conditions.values()):
                if held.condition_id == WELCOMED:
                    st.remove(engine, target, held, "ATTACKED")


MESSENGER = TRADITION + 'kami_s_messenger'
ASSET_KIND = 'Kami Messenger'
MESSENGER_CONTACT = 'condition:typed.miko_messenger_contact'


@hook('compile_actions')
def messenger_buttons(info):
    if MESSENGER not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    record = ActionDefinition(source_definition_id=f"action:typed.{info['short']}.miko.record_messenger",
            display_name='Record willing messenger contact', owner_id=info['actor_id'], economy=EconomyKind.NONE,
            resolution_kind='TYPED', target_kind='SELF',
            parameters={'typed': {'numbers': info['numbers'], 'source': MESSENGER, 'duration': {'kind': 'instant'},
                        'riders': [], 'effects': [{'type': 'miko_contact', 'applies_to': 'self'}]},
                        'miko_contact': True, 'expected_damage': 0,
                        'description': 'Record a messenger kami that you have already contacted and that willingly agreed to serve. '
                        'This records the existing agreement; it does not contact or compel a spirit.'})
    return [record] + [ActionDefinition(source_definition_id=f"action:typed.{info['short']}.miko.messenger.{mode}",
            display_name=f'Manifest Messenger: {mode.title()}', owner_id=info['actor_id'], economy=EconomyKind.ACTION,
            resolution_kind='TYPED', target_kind='SELF', costs=((RESONANCE, 4),),
            parameters={'typed': {'numbers': info['numbers'], 'source': MESSENGER, 'duration': {'kind': 'instant'},
                        'riders': [], 'effects': [{'type': 'miko_messenger', 'mode': mode}]},
                        'description': 'Manifest your previously contacted willing messenger kami for this scene. Choose an empty '
                        'space within 30 feet. At the end of your turns, choose a destination within 40 feet using the planar '
                        'clear-path helper. This helper does not resolve mode-specific terrain or crossed hazards; resolve those '
                        'with the GM. It can deliver one touch or 30-foot support '
                        'feature each turn from its space. If destroyed, it needs a Full Cultivation Session or restitution.'})
            for mode in ('fly', 'climb', 'swim', 'walk')]


@effect('miko_contact')
def record_messenger_contact(ctx, row):
    from . import needle
    ctx.actor.turn_flags['miko_contact_attempt'] = True
    confirmed = needle.ask(ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'MIKO_MESSENGER_CONTACT', ctx.actor.entity_id),
        ctx.actor, 'choice:needle.miko.messenger_contact', ['record'], allow_decline=True, default='decline', automatic_options=[],
        labels={'record': 'Record the existing willing messenger agreement'}, name="Kami's Messenger", feature_id=MESSENGER,
        prompt='Have you already contacted a messenger kami that willingly agreed to serve? Record that existing agreement to enable Manifest Messenger.')
    if confirmed:
        ctx.engine._apply_condition(ctx.actor, MESSENGER_CONTACT, MESSENGER, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
                                    data={'label': 'Existing willing messenger agreement recorded'})


@effect('miko_messenger')
def manifest_messenger(ctx, row):
    from . import spirit_assets
    spirit_assets.manifest(ctx, ASSET_KIND, count=1, hp_pb=4, speed=40, resist=('PSYCHIC',))
    for obj in spirit_assets.assets(ctx.engine, ctx.actor, ASSET_KIND):
        ctx.engine._update_object(obj.model_copy(update={'component': {**obj.component, 'travel_mode': row['mode']}}),
                                  ctx.source, ctx.actor.entity_id)


@hook('effect_origins')
def messenger_origins(engine, actor, action):
    from . import spirit_assets
    typed = action.parameters.get('typed') or {}
    if (not st.is_spirit_feature(action) or st.feature_of(action) == MESSENGER
            or action.target_kind not in ('ALLY_OR_SELF', 'ALLY_ENTITY') or (action.range_ft or action.reach_ft or 0) > 30
            or actor.turn_flags.get('miko_messenger_delivered')):
        return None
    return spirit_assets.origins(engine, actor, ASSET_KIND)


@hook('candidate_allowed')
def messenger_gate(engine, actor, candidate, action):
    from . import spirit_assets
    from ..target_knowledge import located
    if action is None:
        return None
    typed = action.parameters.get('typed') or {}
    if action.parameters.get('miko_contact'):
        return False if actor.turn_flags.get('miko_contact_attempt') or any(c.condition_id == MESSENGER_CONTACT for c in actor.conditions.values()) else None
    if any(r.get('type') == 'miko_messenger' for r in typed.get('effects', []) if isinstance(r, dict)):
        if not any(c.condition_id == MESSENGER_CONTACT for c in actor.conditions.values()):
            return False
        if spirit_assets.assets(engine, actor, ASSET_KIND, live=False):
            return False
        placements = spirit_assets.legal_spaces(engine, actor.position, 30)
        from ..senses import perceives_cell
        from .needle import ai_controlled
        if ai_controlled(engine, actor):
            placements = [p for p in placements if perceives_cell(engine, actor, p)]
        return bool(placements)
    origin = candidate.metadata.get('effect_origin') or {}
    if str(origin.get('id', '')).startswith('object:spirit_asset:Kami Messenger:'):
        return all(t in engine.state.actors and engine.state.actors[t].team_id == actor.team_id
                   and located(engine, actor, engine.state.actors[t]) for t in candidate.target_ids)
    return None


@hook('technique_used')
def messenger_delivery(ctx):
    from ..action_geometry import record_for
    origin = record_for(ctx.engine, ctx.actor, ctx.source) or {}
    if str(origin.get('id', '')).startswith('object:spirit_asset:Kami Messenger:'):
        ctx.actor.turn_flags['miko_messenger_delivered'] = True
