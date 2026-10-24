"""Mirror Speaker (Spirit Awakening Tradition; rider lane C8, 2026-09-30: "i want everything we can automated").

Source: the owner's text (authority/typed_mechanics/rules_text.json; LocalSources/03_paths/Spirit/
Tianxia_Spirit_Awakening_Tradition_Compendium_R7.md, Mirror Speaker: Valid Reflections, Reflection Traces, CL3 Reflection Listener,
CL6 Inverted Glance, CL10 Borrowed Reflection, CL14 Mirror Confession, CL18 World Behind the Glass). No Spheres 5e or D&D 5.5e
counterpart. Ownership row: combat/rules/feature_blocks.d/riders_c8.json (Inverted Glance: the plug-in answers attacks and saves).

The table has no reflective surfaces: a valid reflection is taken to be available (the GM rules otherwise). A Reflection Trace is the
mark "Reflection Trace" (for the fight); it counts as your Resonance Mark (rules/typed_conditions.json mark_counts_as).

What runs:
  * Reflection Diagnosis (typed; Bonus Action, 60 feet, 1 Resonance): a hostile creature's Charisma save or a willing creature --
    a Reflection Trace.
  * Inverted Glance (Reaction, 2 Resonance, asked; you or an ally within 30 feet): before an attack roll against it
    (``before_attack``) or a hostile Intelligence, Wisdom or Charisma save it is forced to make (``save``), the source makes a Wisdom
    save. Failed: the attack has Disadvantage, or the protected creature has Advantage on the save or (against a charm or fear) Wisdom
    + PB Temporary HP (asked); a traced source then takes 2d8 + Wisdom Psychic. Succeeded: +2 AC against that attack
    (``hit_response``) or +2 to the save. An attack that then misses or a save that then succeeds allows Reflected Consequence (asked,
    1 more Resonance: a Reflection Trace, or a Spiritual Pressure effect on a traced creature). One Inverted Glance per roll.
  * Borrowed Reflection (Bonus Action, 4 Resonance, a square within 30 feet): a Reflection Double object (AC your DC, 4 x PB HP),
    one at a time. "Direct the Reflection Double" (Bonus Action) moves it up to 30 feet, staying within 60 feet of you; "Dismiss the
    Reflection Double" (free) removes it quietly. At 0 Hit Points it bursts: every creature within 5 feet makes a Wisdom save (2d8
    Psychic and no Reactions until the start of its next turn; half on a success).
  * Mirror Confession (typed options, Action, 60 feet, 6 Resonance, a Charisma save): Confession Crack (``mirror_crack``) -- until it
    succeeds on two Charisma saves at the end of its turns, the first Charisma save it makes against you each round has
    Disadvantage; one Crack from you at a time. Emotional Confession and Reflected Exposure are the GM's after the save.
  * World Behind the Glass (Action, 10 Resonance, Concentration, the fight, a 30-foot Mirror Domain on you): once per round a traced
    hostile creature attacking you or an ally in it has Disadvantage (asked, no Reaction); a traced creature in it cannot be Hidden
    from you; when a traced creature fails an Int/Wis/Cha save against you, Reflection Cell (once, 6 Resonance, a Wis or Cha save
    against a Spirit Awakening feature, asked) or a 10-foot move of it you choose (asked). In the Cell it is Incapacitated and cannot
    be targeted; at the end of its turn it repeats the Charisma save (a success frees it; after a failure it returns at the end of its
    following turn).

Plug-in surface: effects mirror_double, mirror_direct, mirror_dismiss, mirror_crack; hooks compile_actions,
candidate_allowed, save, after_save_resolved, event, hit_response, turn_end, before_attack, masked_conditions. Shared helpers used:
spirit_traditions (row/context/numbers/feature_action/feature_of/is_spirit_feature/can_react/save/remove/routes/choose_route),
needle (ask/step_to/checkpoint_id), zones.typed_zones, typed_executor.
"""

from __future__ import annotations

from ..paid_relocation import activation, capture, causal_scope, retain, take, preserve_pending

from typing import Any

from . import effect, hook, note
from . import spirit_traditions as st

TRADITION = "tianxia.tradition.spirit.mirror_speaker.feature."
LISTENER = TRADITION + "reflection_listener"
GLANCE = TRADITION + "inverted_glance"
DOUBLE = TRADITION + "borrowed_reflection"
CONFESSION = TRADITION + "mirror_confession"
WORLD = TRADITION + "world_behind_the_glass"
TRACE = "Reflection Trace"
RESONANCE = "resource:core.resonance"
DOUBLE_OBJ = "object:typed.reflection_double:"
CRACK = "condition:typed.confession_crack"
CELL = "condition:typed.reflection_cell"
MENTAL = ("INT", "WIS", "CHA")
_GLANCES = "_mirror_glance_attack"
_SAVE_GLANCES = "_mirror_glance_saves"


def _te() -> Any:
    from .. import typed_executor

    return typed_executor


def traced(creature: Any, speaker: Any) -> bool:
    return creature is not None and speaker is not None and _te().bears_mark(creature, speaker.entity_id, TRACE)


def _ctx(engine: Any, speaker: Any, feature: str, targets: list[Any], intent: Any = None) -> Any:
    return st.context(engine, speaker, st.feature_action(engine, speaker, feature), targets, st.numbers(engine, speaker), intent)


def _psychic_backlash(engine: Any, speaker: Any, foe: Any, intent: Any) -> None:
    """"The triggering creature then takes 2d8 + Wisdom modifier Psychic damage if it bears your Reflection Trace"."""
    if traced(foe, speaker) and foe.active:
        _te().run_effects(_ctx(engine, speaker, GLANCE, [foe], intent),
                          [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "formula": "key_ability_modifier",
                            "damage_types": ["psychic"], "evidence": "2d8 + Wisdom modifier Psychic damage if it bears your Reflection Trace"}])


def _consequence(engine: Any, speaker: Any, foe: Any, intent: Any) -> None:
    """Reflected Consequence: "you may spend 1 additional Resonance to place a Reflection Trace on the triggering creature. If it already
    bears your trace, choose one ordinary Spiritual Pressure effect for it until the start of its next turn"."""
    from . import needle

    if foe is None or not foe.active or speaker.resources.get(RESONANCE, 0) < 1:
        return
    label = "Choose a Spiritual Pressure effect for it" if traced(foe, speaker) else "Place a Reflection Trace on it"
    if not needle.ask(engine, intent, needle.checkpoint_id(engine, "REFLECTED_CONSEQUENCE", foe.entity_id), speaker,
                      "choice:needle.mirror.consequence", ["yes"], labels={"yes": f"{label} (1 Resonance)"}, preferred=["yes"], allow_decline=True,
                      prompt=f"Reflected Consequence: {foe.display_name}'s move failed.", name="Reflected Consequence", feature_id=GLANCE,
                      target_id=foe.entity_id):
        return
    engine._spend_resource(speaker, RESONANCE, 1, GLANCE)
    rows = ([{"type": "spiritual_pressure", "applies_to": "target", "evidence": "one ordinary Spiritual Pressure effect until the start of its next turn"}]
            if traced(foe, speaker) else
            [{"type": "mark", "mark": TRACE, "applies_to": "target", "duration": {"kind": "until_removed"}, "evidence": "place a Reflection Trace"}])
    _te().run_effects(_ctx(engine, speaker, GLANCE, [foe], intent), rows)


# ---------------------------------------------------------------------------------------------------------- Inverted Glance
@hook("before_attack")
def glance_on_attack(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    """"Trigger: A creature you can perceive targets you or an ally within 30 feet with an attack" -- before the roll."""
    from . import needle

    if attacker is None or defender is None or attacker.team_id == defender.team_id or engine.__dict__.get("_mirror_resolving"):
        return None
    for speaker in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if (st.row(engine, speaker, "inverted_glance") is None or speaker.team_id != defender.team_id or not st.can_react(speaker)
                or speaker.resources.get(RESONANCE, 0) < 2 or engine._distance_actor_to_actor(speaker, defender) > 30):
            continue
        if not needle.ask(engine, intent, needle.checkpoint_id(engine, "INVERTED_GLANCE_ATTACK", attacker.entity_id), speaker,
                          "choice:needle.mirror.inverted_glance", ["glance"], preferred=["glance"], allow_decline=True,
                          labels={"glance": f"Inverted Glance (Reaction, 2 Resonance): {attacker.display_name} makes a Wisdom save"},
                          prompt=f"{attacker.display_name} attacks {defender.display_name}.", name="Inverted Glance", feature_id=GLANCE,
                          target_id=attacker.entity_id):
            continue
        with activation(engine, speaker, GLANCE):
            speaker.reaction_available = False
            engine._spend_resource(speaker, RESONANCE, 2, GLANCE)
            engine._append_event("REACTION_RESOLVED", GLANCE, actor_id=speaker.entity_id, target_ids=(attacker.entity_id,),
                                 payload={"checkpoint": "ATTACK_DECLARED", "reaction_name": "Inverted Glance", "protects": defender.entity_id})
            engine.__dict__["_mirror_resolving"] = True
            try:
                failed = st.save(_ctx(engine, speaker, GLANCE, [attacker], intent), attacker, "wis")
            finally:
                engine.__dict__.pop("_mirror_resolving", None)
            preserve_pending(engine, _GLANCES)
            engine.__dict__[_GLANCES] = {"speaker": speaker.entity_id, "attacker": attacker.entity_id, "defender": defender.entity_id,
                                         "events": len(engine.events), "plus_two": not failed,
                                         "roll": f"ATTACK:{context.get('source_id')}:{context.get('attack_index', 1)}"}
            retain(engine, _GLANCES, capture(engine))
            if failed:
                _psychic_backlash(engine, speaker, attacker, intent)
                return {"mode": "DISADVANTAGE"}  # "The triggering attack is made with Disadvantage."
            return {}
    return None


def _pending_attack(engine: Any, attacker_id: Any, reason: str) -> dict[str, Any] | None:
    held = engine.__dict__.get(_GLANCES)
    if not isinstance(held, dict) or held.get("attacker") != attacker_id:
        return None
    return held if str(reason or "") == held.get("roll") else None


@hook("event")
def glance_attack_rolled(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "ATTACK_ROLLED":
        return
    payload = kwargs.get("payload") or {}
    held = _pending_attack(engine, kwargs.get("actor_id"), payload.get("reason"))
    if held is None:
        return
    if payload.get("provisional_hit") and held.get("plus_two"):
        return  # hit_response below decides whether +2 AC turns it
    with causal_scope(engine, take(engine, _GLANCES)):
        preserve_pending(engine, _GLANCES)
        engine.__dict__.pop(_GLANCES, None)
        if not payload.get("provisional_hit"):
            _missed(engine, held)


@hook("hit_response")
def glance_plus_two(engine: Any, attacker: Any, target: Any, spec: dict[str, Any], total: int, natural: int, effective_ac: int) -> tuple[int, bool] | None:
    """"Successful Save: The protected creature gains +2 to AC against the triggering attack"."""
    held = engine.__dict__.get(_GLANCES)
    if not isinstance(held, dict) or held.get("attacker") != getattr(attacker, "entity_id", None) or held.get("defender") != target.entity_id:
        return None
    with causal_scope(engine, take(engine, _GLANCES)):
        preserve_pending(engine, _GLANCES)
        engine.__dict__.pop(_GLANCES, None)
        if natural == 20 or total >= effective_ac + 2:
            return None
        _missed(engine, held)
        return effective_ac + 2, False


def _missed(engine: Any, held: dict[str, Any]) -> None:
    speaker, foe = engine.state.actors.get(held["speaker"]), engine.state.actors.get(held["attacker"])
    if speaker is not None and speaker.active:
        _consequence(engine, speaker, foe, engine._active_intent)  # "If Inverted Glance causes the triggering attack to miss"


@hook("save")
def glance_on_save(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """"Trigger: A creature you can perceive ... forces you or that ally to make an Intelligence, Wisdom, or Charisma saving throw"."""
    from . import needle

    engine, foe = ctx.engine, ctx.actor
    code = str(ability or "").upper()[:3]
    if code not in MENTAL or foe is None or subject is None or foe.team_id == subject.team_id or engine.__dict__.get("_mirror_resolving"):
        return None
    for speaker in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if (st.row(engine, speaker, "inverted_glance") is None or speaker.team_id != subject.team_id or not st.can_react(speaker)
                or speaker.resources.get(RESONANCE, 0) < 2 or engine._distance_actor_to_actor(speaker, subject) > 30):
            continue
        if not needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "INVERTED_GLANCE", subject.entity_id), speaker,
                          "choice:needle.mirror.inverted_glance", ["glance"], preferred=["glance"], allow_decline=True,
                          labels={"glance": f"Inverted Glance (Reaction, 2 Resonance): {foe.display_name} makes a Wisdom save"},
                          prompt=f"{foe.display_name} forces {subject.display_name} to make a {code} save.", name="Inverted Glance",
                          feature_id=GLANCE, target_id=foe.entity_id):
            continue
        with activation(engine, speaker, GLANCE):
            speaker.reaction_available = False
            engine._spend_resource(speaker, RESONANCE, 2, GLANCE)
            engine._append_event("REACTION_RESOLVED", GLANCE, actor_id=speaker.entity_id, target_ids=(foe.entity_id,),
                                 payload={"checkpoint": "SAVE_FORCED", "reaction_name": "Inverted Glance"})
            engine.__dict__["_mirror_resolving"] = True
            try:
                failed = st.save(_ctx(engine, speaker, GLANCE, [foe], ctx.intent), foe, "wis")
            finally:
                engine.__dict__.pop("_mirror_resolving", None)
            preserve_pending(engine, _SAVE_GLANCES)
            engine.__dict__[_SAVE_GLANCES] = {**(engine.__dict__.get(_SAVE_GLANCES) or {}), (ctx.source, subject.entity_id): speaker.entity_id}
            retain(engine, (_SAVE_GLANCES, ctx.source, subject.entity_id), capture(engine))
            if not failed:
                return {"bonus": 2}  # "The protected creature gains +2 ... to the triggering saving throw"
            charm = bool({str(n).lower() for n in named or ()} & {"charmed", "frightened"})
            choice = "advantage"
            if charm:
                numbers = st.numbers(engine, speaker)
                temp = int(numbers.get("key_mod") or 0) + int(numbers.get("pb") or 2)
                picked = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "INVERTED_GLANCE_RESULT", subject.entity_id), speaker,
                                    "choice:needle.mirror.inverted_glance_result", ["advantage", "temp_hp"], preferred=["advantage"],
                                    labels={"advantage": f"{subject.display_name} makes the save with Advantage",
                                            "temp_hp": f"{subject.display_name} gains {temp} Temporary Hit Points"},
                                    prompt="Inverted Glance: the source failed its save -- choose one result.", name="Inverted Glance", feature_id=GLANCE)
                choice = picked[0] if picked else "advantage"
                if choice == "temp_hp":
                    engine._grant_temp_hp(subject, temp, GLANCE, speaker.entity_id)
            _psychic_backlash(engine, speaker, foe, ctx.intent)
            return {"bonus": 0, "modes": ["ADVANTAGE"]} if choice == "advantage" else None
    return None


@hook("after_save_resolved")
def after_mirror_save(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    engine = ctx.engine
    preserve_pending(engine, _SAVE_GLANCES)
    held = (engine.__dict__.get(_SAVE_GLANCES) or {}).pop((ctx.source, subject.entity_id), None)
    with causal_scope(engine, take(engine, (_SAVE_GLANCES, ctx.source, subject.entity_id))):
        if held is not None and not failed:
            speaker = engine.state.actors.get(held)
            if speaker is not None and speaker.active:
                _consequence(engine, speaker, ctx.actor, ctx.intent)  # "or the saving throw to succeed"
    if failed:
        _domain_answer(ctx, subject, str(ability or "").upper()[:3])


# ---------------------------------------------------------------------------------------------------------- Borrowed Reflection
def double_of(engine: Any, speaker: Any) -> Any:
    return next((o for o in engine.state.objects.values() if o.object_id.startswith(DOUBLE_OBJ) and o.owner_id == speaker.entity_id and not o.destroyed), None)


def _remove_double(engine: Any, speaker: Any, source: str, *, dismissed: bool) -> None:
    obj = double_of(engine, speaker)
    if obj is not None:
        engine._update_object(obj.model_copy(update={"destroyed": True, "component": {**(obj.component or {}), "dismissed": dismissed}}), source, speaker.entity_id)


@effect("mirror_double")
def make_double(ctx: Any, row: dict[str, Any]) -> None:
    from ..gate2_runtime_models import RuntimeObjectState

    engine, speaker = ctx.engine, ctx.actor
    spot = getattr(ctx, "destination", None) or getattr(ctx.intent, "destination", None)
    if spot is None:
        return
    _remove_double(engine, speaker, ctx.source, dismissed=True)  # "You can maintain only one Reflection Double at a time."
    numbers = ctx.numbers or st.numbers(engine, speaker)
    hp = 4 * int(numbers.get("pb") or 2)
    engine._update_object(RuntimeObjectState(object_id=f"{DOUBLE_OBJ}{speaker.entity_id}:{engine.state.event_sequence}", object_kind="REFLECTION_DOUBLE",
                                             position=spot, unattended=False, flammable=False, owner_id=speaker.entity_id,
                                             ac=int(numbers.get("save_dc") or 10), current_hp=hp, maximum_hp=hp, damage_immunities=("POISON",),
                                             component={"label": f"{speaker.display_name}'s Reflection Double", "resist": ["PSYCHIC"]}), ctx.source, speaker.entity_id)


@effect("mirror_direct")
def direct_double(ctx: Any, row: dict[str, Any]) -> None:
    engine, speaker = ctx.engine, ctx.actor
    obj, spot = double_of(engine, speaker), getattr(ctx, "destination", None) or getattr(ctx.intent, "destination", None)
    if obj is not None and spot is not None:
        engine._update_object(obj.model_copy(update={"position": spot}), ctx.source, speaker.entity_id)


@effect("mirror_dismiss")
def dismiss_double(ctx: Any, row: dict[str, Any]) -> None:
    _remove_double(ctx.engine, ctx.actor, ctx.source, dismissed=True)  # "You may dismiss the Double without this burst."


@hook("event")
def double_breaks(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Break the Double: "When the Double is reduced to 0 Hit Points, every creature within 5 feet of it makes a Wisdom saving throw"."""
    if event_type != "OBJECT_UPDATED":
        return
    obj = (kwargs.get("payload") or {}).get("object") or {}
    if not str(obj.get("object_id") or "").startswith(DOUBLE_OBJ) or (obj.get("component") or {}).get("dismissed"):
        return
    if not (obj.get("destroyed") or (obj.get("current_hp") is not None and int(obj.get("current_hp") or 0) <= 0)):
        return
    speaker = engine.state.actors.get(str(obj.get("owner_id") or ""))
    if speaker is None:
        return
    x, y = int((obj.get("position") or {}).get("x", 0)), int((obj.get("position") or {}).get("y", 0))
    near = [c for _, c in sorted(engine.state.actors.items()) if c.active and any(max(abs(cx - x), abs(cy - y)) <= 1 for cx, cy in engine._actor_cells(c))]
    stored = engine.state.objects.get(str(obj.get("object_id")))
    if stored is not None:
        engine._update_object(stored.model_copy(update={"component": {**(stored.component or {}), "dismissed": True}}), DOUBLE, stored.owner_id)  # it breaks once (evented: the replay sees it)
    if not near:
        return
    ctx = _ctx(engine, speaker, DOUBLE, near)
    _te().run_effects(ctx, [{"type": "save", "ability": "wis", "applies_to": "target",
                             "on_fail": [{"type": "damage", "applies_to": "target", "dice": {"count": 2, "sides": 8}, "damage_types": ["psychic"],
                                          "evidence": "The creature takes 2d8 Psychic damage"},
                                         {"type": "reaction_denied", "applies_to": "target", "duration": {"kind": "until_start_of_next_turn"},
                                          "evidence": "and cannot take Reactions until the start of its next turn"}],
                             "on_success": [{"type": "half_damage", "applies_to": "target", "evidence": "It takes half damage."}],
                             "evidence": "every creature within 5 feet of it makes a Wisdom saving throw"}])


@hook("compile_actions")
def mirror_buttons(info: dict[str, Any]) -> list[Any] | None:
    if DOUBLE not in info["owned_ids"]:
        return None
    from ..gate2_runtime_models import ActionDefinition, EconomyKind

    def button(key: str, name: str, economy: Any, rows: list[dict[str, Any]], text: str) -> Any:
        return ActionDefinition(source_definition_id=f"action:typed.{info['short']}.mirror.{key}", display_name=name, owner_id=info["actor_id"],
                                economy=economy, resolution_kind="TYPED", target_kind="SELF",
                                parameters={"typed": {"numbers": info["numbers"], "duration": {"kind": "instant"}, "riders": [], "source": DOUBLE, "effects": rows},
                                            "expected_damage": 0, "mirror": key, "description": text})

    return [button("direct", "Direct the Reflection Double", EconomyKind.BONUS_ACTION,
                   [{"type": "mirror_direct", "applies_to": "self", "picks_destination": True, "distance_ft": 60}],
                   "Borrowed Reflection: move your Reflection Double up to 30 feet (it stays within 60 feet of you)."),
            button("dismiss", "Dismiss the Reflection Double", EconomyKind.NONE, [{"type": "mirror_dismiss", "applies_to": "self"}],
                   "Borrowed Reflection: dismiss your Reflection Double without its burst (free).")]


@hook("candidate_allowed")
def mirror_gates(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    target_ids = tuple(getattr(candidate, "target_ids", None) or ())
    if any(_in_cell(engine.state.actors.get(t)) for t in target_ids if t != actor.entity_id):
        return False  # the Reflection Cell: total cover from creatures outside it
    if action is None:
        return None
    key = (action.parameters or {}).get("mirror")
    if key in ("direct", "dismiss"):
        obj = double_of(engine, actor)
        if obj is None:
            return False
        spot = getattr(candidate, "destination", None)
        if key == "direct" and spot is not None and engine.grid.distance_ft(obj.position, spot) > 30:
            return False  # "it can move up to its Speed" (30 feet)
    return None


# ---------------------------------------------------------------------------------------------------------- Mirror Confession
def _crack(creature: Any, speaker_id: str) -> Any:
    return next((c for c in creature.conditions.values() if c.condition_id == CRACK and c.source_actor_id == speaker_id), None)


@effect("mirror_crack")
def crack(ctx: Any, row: dict[str, Any]) -> None:
    target = next(iter(_te()._default_subject(ctx, row, harmful=True)), None)
    if target is None or not target.active or _crack(target, ctx.actor.entity_id) is not None:
        return  # "A creature can suffer only one active Confession Crack from you."
    ctx.engine._apply_condition(target, CRACK, ctx.source, ctx.actor.entity_id, expires_on="UNTIL_REMOVED",
                                data={"successes": 0, "round": -1, "label": f"Confession Crack ({ctx.actor.display_name}): Disadvantage on its first Charisma save "
                                                                         "against them each round"})


@hook("save")
def crack_disadvantage(ctx: Any, subject: Any, ability: str, named: Any) -> dict[str, Any] | None:
    """"it has Disadvantage on the first Charisma saving throw it makes against you each round"."""
    if str(ability or "").upper()[:3] != "CHA" or subject is None or ctx.actor is None:
        return None
    held = _crack(subject, ctx.actor.entity_id)
    if held is None or st.data_of(subject, held).get("round") == ctx.engine.state.round_number:
        return None
    st.set_data(subject, held, round=ctx.engine.state.round_number)
    return {"bonus": 0, "modes": ["DISADVANTAGE"]}


@hook("turn_end")
def crack_and_cell(engine: Any, actor: Any) -> None:
    for held in [c for c in actor.conditions.values() if c.condition_id == CRACK]:
        speaker = engine.state.actors.get(held.source_actor_id or "")
        if speaker is None:
            continue
        if st.save(_ctx(engine, speaker, CONFESSION, [actor]), actor, "cha"):
            continue  # failed
        successes = int(st.data_of(actor, held).get("successes") or 0) + 1
        st.set_data(actor, held, successes=successes)
        if successes >= 2:  # "until it succeeds on two Charisma saving throws at the end of its turns"
            st.remove(engine, actor, held, "RECOVERED")
    for held in [c for c in actor.conditions.values() if c.condition_id == CELL]:
        speaker = engine.state.actors.get(held.source_actor_id or "")
        if st.data_of(actor, held).get("leaving") or speaker is None:
            st.remove(engine, actor, held, "RETURNED")  # "it remains until the end of its following turn, then returns automatically"
            continue
        if st.save(_ctx(engine, speaker, WORLD, [actor]), actor, "cha"):  # failed
            st.set_data(actor, held, leaving=True)
        else:
            st.remove(engine, actor, held, "ESCAPED")  # "on a success, it returns to its former space"


# ---------------------------------------------------------------------------------------------------------- World Behind the Glass
def domain_of(engine: Any, speaker: Any) -> Any:
    from .. import zones

    return next((z for z in zones.typed_zones(engine) if z.owner_id == speaker.entity_id and st.feature_of(engine.action_catalog.get(z.source_definition_id)) == WORLD), None)


def _inside(engine: Any, zone: Any, creature: Any) -> bool:
    return zone is not None and creature is not None and engine._footprint_intersects(creature, zone.affected_cells)


def _in_cell(creature: Any) -> bool:
    return creature is not None and any(c.condition_id == CELL for c in creature.conditions.values())


@hook("before_attack")
def mirror_disadvantage(engine: Any, attacker: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    """"Once per round when a traced hostile creature attacks you or an ally in the Domain, you may impose Disadvantage without spending
    your Reaction. Resolve this before the roll.\""""
    from . import needle

    if attacker is None or defender is None or attacker.team_id == defender.team_id:
        return None
    for speaker in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        zone = domain_of(engine, speaker) if speaker.active and speaker.team_id == defender.team_id else None
        if zone is None or not traced(attacker, speaker) or not _inside(engine, zone, defender) or zone.trigger_profile.get("glass_round") == engine.state.round_number:
            continue
        if not needle.ask(engine, intent, needle.checkpoint_id(engine, "MIRROR_DOMAIN_ATTACK", attacker.entity_id), speaker,
                          "choice:needle.mirror.domain_disadvantage", ["impose"], labels={"impose": f"{attacker.display_name}'s attack has Disadvantage"},
                          preferred=["impose"], allow_decline=True, prompt=f"World Behind the Glass (once per round): {attacker.display_name} attacks "
                          f"{defender.display_name}.", name="World Behind the Glass", feature_id=WORLD, target_id=attacker.entity_id):
            continue
        zone.trigger_profile = {**zone.trigger_profile, "glass_round": engine.state.round_number}
        engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=speaker.entity_id, payload={"zone": zone.model_dump(mode="json")})
        return {"mode": "DISADVANTAGE"}
    return None


@hook("masked_conditions")
def no_hiding_from_the_glass(engine: Any, attacker: Any, target: Any) -> dict[str, set[str]] | None:
    """"A traced enemy cannot become Hidden from you through ordinary darkness, invisibility, smoke, disguise, or mundane cover"."""
    if attacker is None or target is None:
        return None
    for speaker, other in ((attacker, target), (target, attacker)):
        zone = domain_of(engine, speaker)
        if zone is not None and traced(other, speaker) and _inside(engine, zone, other):
            hidden = {iid for iid, c in other.conditions.items() if c.condition_id == "condition:typed.hidden"}
            if hidden:
                return {other.entity_id: hidden}
    return None


def _domain_answer(ctx: Any, subject: Any, code: str) -> None:
    """A traced creature in the Domain failed an Int/Wis/Cha save against you: Reflection Cell (once) or a 10-foot reflected move."""
    from . import needle

    engine, speaker = ctx.engine, ctx.actor
    if speaker is None or subject is None or code not in MENTAL or not subject.active or subject.team_id == speaker.team_id:
        return
    zone = domain_of(engine, speaker)
    if zone is None or not traced(subject, speaker) or not _inside(engine, zone, subject) or _in_cell(subject):
        return
    if (code in ("WIS", "CHA") and st.is_spirit_feature(ctx.action) and not zone.trigger_profile.get("cell_used")
            and speaker.resources.get(RESONANCE, 0) >= 6
            and needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "REFLECTION_CELL", subject.entity_id), speaker, "choice:needle.mirror.cell",
                           ["cell"], labels={"cell": f"Draw {subject.display_name} into a Reflection Cell (6 Resonance, once)"}, preferred=["cell"],
                           allow_decline=True, prompt=f"World Behind the Glass: {subject.display_name} failed its save.", name="Reflection Cell",
                           feature_id=WORLD, target_id=subject.entity_id)):
        zone.trigger_profile = {**zone.trigger_profile, "cell_used": True}
        engine._append_event("ZONE_CREATED", zone.source_definition_id, actor_id=speaker.entity_id, payload={"zone": zone.model_dump(mode="json")})
        engine._spend_resource(speaker, RESONANCE, 6, WORLD)
        engine._apply_condition(subject, CELL, WORLD, speaker.entity_id, expires_on="UNTIL_REMOVED",
                                data={"rule": {"counts_as_incapacitated": True, "no_actions": True, "no_reactions": True, "speed_zero": True},
                                      "label": "In a Reflection Cell: Incapacitated, and nothing outside can target it"})
        return
    spots = {c: v for c, v in st.routes(engine, subject, 10).items() if c != subject.position}
    path = st.choose_route(engine, speaker, spots, ctx.intent, checkpoint="MIRROR_DISPLACE", prompt=f"World Behind the Glass: move {subject.display_name} "
                           "up to 10 feet?", name="World Behind the Glass", feature=WORLD) if spots else None
    if path is not None:
        needle.step_to(engine, subject, path[-1], WORLD)  # "forced spiritual displacement"
