"""Illusion lines that were left to the GM (rider lane 9, 2026-09-29; owner: "i want everything we can automated").  Built on
combat/ext/figment.py (figments, False Premises as the illusionist's marks, Misdirection Responses).  Owner's text first
(authority/typed_mechanics/rules_text.json); nothing is invented.

  Obscuring Glamer   "The effect ends early if the target attacks, casts a spell, uses a sphere talent, or deals damage": the glamer's
                     Disadvantage (and the Invisible option) come off the target when it attacks, uses a technique or deals damage --
                     unless the "keeps going" augment was chosen.  Options: blurred; Invisible (1 CP); unending (1 CP); muffled (1 CP:
                     Disadvantage on Perception to find it hidden, and its armor's Stealth Disadvantage is not rolled).
  False Obstruction  options: Lightly Obscured; Heavily Obscured (1 CP); muffled (1 CP: creatures inside cannot hear).
  Premise Chain      once per round, 1 CP keeps the False Premise a Misdirection Response would end (it still ends on time).
  Court of False     once per round a Response does not end the premise; figment sight and sound cost nothing while the Court lasts.
  Premises
  Premise Transfer   Reaction and 1 CP when a False Premise from you ends without a Response: another creature within 30 feet of it makes
                     a Wisdom save or gains the same False Premise until the start of your next turn.
  Impossible Premise a Response against its False Premise applies two different Responses.
  The One False      "choose up to two Misdirection Responses and apply them" on the failed save.
  Premise
  Sovereign Illusion two Misdirection Responses a round; Create Figment and Plant False Premise as Bonus Actions while it lasts.
  Incarnation
  World of False     the first time each round a hostile creature inside misses an attack while it carries your False Premise (or your
  Premises           Wrong Angle), you regain 1 CP, at most PB CP per use.
Substantial Phantasm uses the reviewed linked hold/Study rows through owned Create Figment variants. Other illusions' Study
outcomes remain with the GM; this does not add a general-purpose Study action.


Shared response_limit and senses_free API used by figment: query active Court/Incarnation effects for response count and figment senses cost; absent owned effects leave the normal limits and cost unchanged.
"""

from __future__ import annotations

from ..paid_relocation import activation

from typing import Any

from . import effect, hook, note
from .needle import CHOICE, ask, checkpoint_id

T = "tianxia.talent.illusion."
OBSCURING = "TAL_ILLUSION_OBSCURING_GLAMER"
UNENDING = "condition:typed.glamer_unending"
MUFFLED = "condition:typed.glamer_muffled"
CHAIN = "TAL_ILLUSION_PREMISE_CHAIN"
COURT = "TAL_ILLUSION_COURT_FALSE_PREMISES"
TRANSFER = "TAL_ILLUSION_PREMISE_TRANSFER"
IMPOSSIBLE = T + "impossible_premise"
SOVEREIGN = T + "sovereign_illusion_incarnation"
WORLD = T + "world_of_false_premises"
PREMISE = "False Premise"
RESPONSES = {"opening": "False Opening", "angle": "Wrong Angle", "timing": "Lost Timing", "step": "Stolen Step"}
SUBSTANTIAL = T + "substantial_phantasm"


@hook("compile_actions")
def substantial_figment_actions(info: dict[str, Any]) -> list[Any] | None:
    """Create Figment's owned linked modifier uses its reviewed save and Study rows.

    Explicit variants keep the unmodified action available. The augmented variant
    replaces Grappled with Restrained, including the escape record's exact guard.
    """
    import copy
    from ..factory_compiler import RESOURCE_IDS
    from .figment import figment_actions

    if SUBSTANTIAL not in (info.get("owned_ids") or []):
        return None
    base = next((a for a in figment_actions(info) or [] if a.parameters.get("figment_create")), None)
    if base is None:
        return None
    rows = info["mechanics"][SUBSTANTIAL]["modifier"]["effects"]
    pool = RESOURCE_IDS.get(str(info.get("primary") or "qi"), "resource:core.qi")
    out = []
    for hold, cost in (("grappled", 3), ("restrained", 5)):
        effects = copy.deepcopy(rows)
        for save in effects:
            for row in save.get("on_fail") or []:
                if row.get("type") == "condition":
                    row["condition"] = hold
                elif row.get("type") == "escape_option":
                    row["guards"] = [hold]
        typed = {**base.parameters["typed"], "effects": [*base.parameters["typed"]["effects"],
                 {"type": "illusion_substantial_phantasm", "effects": effects}]}
        out.append(base.model_copy(update={
            "source_definition_id": base.source_definition_id + ".substantial." + hold,
            "display_name": f"Create Figment + Substantial Phantasm ({cost} CP; {hold.title()})",
            "costs": ((pool, cost),),
            "parameters": {**base.parameters, "player_only": False, "figment_kit": False, "typed": typed,
                "description": f"Action: create a figment within 60 feet (Concentration, up to 10 minutes). "
                    f"Choose creatures inside it. For {cost} cultivation points plus your chosen figment options, "
                    f"each makes an Intelligence save against DC {info['numbers'].get('save_dc', 10)}; "
                    f"on failure it is {hold.title()} until your next turn starts or it successfully Studies the illusion "
                    "with an Intelligence (Investigation) check. Study takes an Action, or a free try at the end of its turn."}}))
    return out


@hook("button_description")
def substantial_description(action: dict[str, Any]) -> str | None:
    parameters = (action or {}).get("parameters") or {}
    rows = (parameters.get("typed") or {}).get("effects") or []
    return parameters.get("description") if any(r.get("type") == "illusion_substantial_phantasm" for r in rows) else None


@effect("illusion_substantial_phantasm")
def substantial_phantasm(ctx: Any, row: dict[str, Any]) -> None:
    """Choose recipients of the newly created figment; recognized creatures cannot be held."""
    from . import placed
    from ..typed_executor import run_effects
    from ..target_knowledge import can_see

    if not _owns(ctx.engine, ctx.actor, SUBSTANTIAL):
        return
    zones = [z for z in placed.of(ctx.engine, "figment") if z.owner_id == ctx.actor.entity_id]
    if not zones:
        return
    zone = zones[-1]
    recognized = [*(placed.data(zone).get("recognized") or []), *(placed.data(zone).get("immune") or [])]
    subjects = [a for a in ctx.engine.state.actors.values() if a.active and a.entity_id not in recognized
                and ctx.engine._footprint_intersects(a, zone.affected_cells)]
    if not subjects:
        return
    labels = {a.entity_id: f"Substantial Phantasm: hold {a.display_name} if its Intelligence save fails" for a in subjects}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "SUBSTANTIAL", ctx.actor.entity_id), ctx.actor,
                 CHOICE + "substantial_phantasm", list(labels), labels=labels, minimum=0, maximum=len(labels),
                 allow_decline=True, preferred=[a.entity_id for a in subjects if a.team_id != ctx.actor.team_id],
                 automatic_options=[a.entity_id for a in subjects if a.team_id != ctx.actor.team_id
                                    and can_see(ctx.engine, ctx.actor, a)],
                 prompt=f"{ctx.actor.display_name} uses Create Figment + Substantial Phantasm: choose creatures inside to hold.")
    for subject in subjects:
        if subject.entity_id in picked:
            action = ctx.action.model_copy(update={"source_definition_id": SUBSTANTIAL})
            inner = placed.context(ctx.engine, ctx.actor, SUBSTANTIAL, ctx.numbers, [subject], action=action)
            run_effects(inner, row.get("effects") or [])


def _owns(engine: Any, actor: Any, key: str) -> bool:
    for action in engine.action_catalog.values():
        params = action.parameters or {}
        if action.owner_id == actor.entity_id and params.get("figment_kit"):
            return key in set(params.get("figment_owned") or ())
    return False


def _active(engine: Any, actor: Any, key: str) -> bool:
    """A duration talent of the actor's is up (its zone, or a condition or modifier it put on the actor)."""
    if any(zone.active and zone.owner_id == actor.entity_id and str(zone.source_definition_id).endswith(key) for zone in engine.state.zones.values()):
        return True
    return any(str(row.source_definition_id).endswith(key) for row in actor.conditions.values()) or \
        any(str(row.source_definition_id).endswith(key) for row in actor.modifiers.values())


def _pool(actor: Any) -> str | None:
    return next((pool for pool in ("resource:core.qi", "resource:core.stamina", "resource:core.resonance") if actor.resources.get(pool, 0) > 0), None)


# ------------------------------------------------------------------------------------------------ called by combat/ext/figment.py
def response_limit(engine: Any, owner: Any) -> int:
    return 2 if _active(engine, owner, SOVEREIGN) else 1


def keeps_premise(ctx: Any, owner: Any, target: Any) -> bool:
    """A Response that would end the False Premise does not: the Court of False Premises (once a round, free) or Premise Chain (once a round,
    1 CP, asked)."""
    engine = ctx.engine
    if _active(engine, owner, COURT) and owner.turn_flags.get("illusion_round_court_keep") != engine.state.round_number:
        owner.turn_flags["illusion_round_court_keep"] = engine.state.round_number
        note(engine, COURT, owner, f"Court of False Premises: {target.display_name}'s False Premise holds after the Response.", targets=(target,))
        return True
    pool = _pool(owner)
    if not _owns(engine, owner, CHAIN) or owner.turn_flags.get("illusion_round_chain") == engine.state.round_number or pool is None:
        return False
    picked = ask(engine, ctx.intent, checkpoint_id(engine, "PREMISE_CHAIN", owner.entity_id, target.entity_id), owner, CHOICE + "premise_chain", ["keep"],
                 labels={"keep": "Premise Chain: spend 1 CP to keep the False Premise"}, allow_decline=True, target_id=target.entity_id,
                 prompt="Premise Chain: keep the False Premise after this Response?")
    if not picked:
        return False
    owner.turn_flags["illusion_round_chain"] = engine.state.round_number
    engine._spend_resource(owner, pool, 1, CHAIN)
    return True


def senses_free(engine: Any, owner: Any) -> bool:
    """Court of False Premises: "your figments and glamers inside the Domain may include sight and sound without paying the 1 CP augment"."""
    return _active(engine, owner, COURT)


def apply_response(engine: Any, owner: Any, target: Any, kind: str, source: str, numbers: dict[str, Any], action: Any = None) -> None:
    """One Misdirection Response's effect (the same as combat/ext/figment.py response's)."""
    from . import placed
    from ..typed_executor import run_effects

    inner = placed.context(engine, owner, source, numbers, [target], action=action)
    rows = {"opening": [{"type": "advantage", "applies_to": "target", "on": "the next attack roll against it", "duration": "until_start_of_next_turn"}],
            "angle": [{"type": "disadvantage", "applies_to": "target", "on": "its next attack roll", "duration": "until_start_of_next_turn"}],
            "timing": [{"type": "condition", "applies_to": "target", "condition": "reaction_denied", "expires_on": "END_OF_HOLDER_NEXT_TURN"}],
            "step": [{"type": "speed", "applies_to": "target", "flat": -10, "duration": "until_start_of_next_turn"}]}[kind]
    run_effects(inner, rows)


def second_response(ctx: Any, owner: Any, target: Any, first: str, premise_source: str) -> None:
    """Impossible Premise: "choose two different responses instead of one" for a False Premise it planted."""
    if not str(premise_source).endswith(IMPOSSIBLE):
        return
    choices = {key: f"Impossible Premise: also {label}" for key, label in RESPONSES.items() if key != first}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "IMPOSSIBLE_SECOND", owner.entity_id, target.entity_id), owner, CHOICE + "impossible_premise",
                 list(choices), labels=choices, preferred=["timing" if first != "timing" else "angle"], target_id=target.entity_id,
                 prompt="Impossible Premise: the second Misdirection Response")
    kind = picked[0] if picked else next(iter(choices))
    apply_response(ctx.engine, owner, target, kind, IMPOSSIBLE, ctx.numbers, ctx.action)
    note(ctx.engine, IMPOSSIBLE, owner, f"Impossible Premise: {owner.display_name} also triggers {RESPONSES[kind]} on {target.display_name}.", targets=(target,))


@effect("illusion_two_responses")
def two_responses(ctx: Any, eff: dict[str, Any]) -> None:
    """The One False Premise Beneath Heaven: "choose up to two Misdirection Responses and apply them"."""
    target = ctx.target or (ctx.targets[0] if ctx.targets else None)
    if target is None:
        return
    choices = {key: label for key, label in RESPONSES.items()}
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, "ONE_FALSE_PREMISE", ctx.actor.entity_id, target.entity_id), ctx.actor,
                 CHOICE + "one_false_premise", list(choices), labels=choices, preferred=["timing", "angle"], minimum=0, maximum=2,
                 target_id=target.entity_id, prompt="The One False Premise Beneath Heaven: up to two Misdirection Responses")
    for kind in (picked or ["timing", "angle"])[:2]:
        apply_response(ctx.engine, ctx.actor, target, kind, ctx.source, ctx.numbers, ctx.action)
    ctx.rider(f"{target.display_name} acts on the impossible premise: " + ", ".join(RESPONSES[k] for k in (picked or ["timing", "angle"])[:2]) + ".")


# ------------------------------------------------------------------------------------------------ Premise Transfer
@hook("event")
def premise_ends(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    from .. import typed_reactions
    from ..typed_executor import MARK_PREFIX, bears_mark, mark_condition_id

    if event_type != "CONDITION_REMOVED":
        return
    condition = str((kwargs.get("payload") or {}).get("condition_id") or "")
    if not condition.startswith(MARK_PREFIX + "false_premise."):
        return
    event = kwargs.get("originating_event")
    source = str(kwargs.get("source_definition_id") or getattr(event, "source_definition_id", ""))
    if "figment.response" in source:
        return  # ended by a Misdirection Response
    owner = engine.state.actors.get(condition.rsplit(".", 1)[-1]) or engine.state.actors.get(condition[len(MARK_PREFIX + "false_premise."):])
    target = next((engine.state.actors.get(t) for t in kwargs.get("target_ids") or () if t in engine.state.actors), None)
    if owner is None or target is None or not owner.active or not _owns(engine, owner, TRANSFER) or not typed_reactions._can_react(engine, owner):
        return
    pool = _pool(owner)
    if pool is None:
        return
    others = [row for row in engine.state.actors.values() if row.active and row is not target and row.team_id != owner.team_id
              and engine._distance_actor_to_actor(target, row) <= 30 and not bears_mark(row, owner.entity_id, PREMISE)]
    if not others:
        return
    labels = {row.entity_id: f"Premise Transfer (Reaction, 1 CP): pass the False Premise to {row.display_name}" for row in others}
    picked = ask(engine, getattr(engine, "_active_intent", None), checkpoint_id(engine, "PREMISE_TRANSFER", owner.entity_id, target.entity_id), owner,
                 CHOICE + "premise_transfer", list(labels), labels=labels, preferred=[others[0].entity_id], allow_decline=True,
                 target_id=target.entity_id, prompt=f"{target.display_name}'s False Premise ends.")
    new = next((row for row in others if picked and row.entity_id == picked[0]), None)
    if new is None:
        return
    with activation(engine, owner, TRANSFER):
        owner.reaction_available = False
        engine._spend_resource(owner, pool, 1, TRANSFER)
        dc = next((int((((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("save_dc") or 10) for a in engine.action_catalog.values()
                   if a.owner_id == owner.entity_id and (a.parameters or {}).get("figment_kit")), 10)
        roll = engine._roll_save(new, "WIS", dc, TRANSFER)
        if roll is not None and int(roll.total) < dc:
            from .effect_durations import token

            # "until the start of your next turn" -- counted from now: a transfer made as the old premise expired at the start of your turn
            # lasts to your following turn (START_OF_SOURCE_NEXT_TURN would expire it in the same pass).
            engine._apply_condition(new, mark_condition_id(PREMISE, owner.entity_id), TRANSFER, owner.entity_id,
                                    expires_on=token("start", owner.entity_id, int(owner.turns_started or 0) + 1),
                                    data={"label": f"False Premise from {owner.display_name} (Premise Transfer)"})
            note(engine, TRANSFER, owner, f"Premise Transfer: {new.display_name} gains the False Premise.", targets=(new,))


# ------------------------------------------------------------------------------------------------ Obscuring Glamer
def _obscuring_source(engine: Any, source: str) -> bool:
    action = engine.action_catalog.get(source)
    return (str(source).split("#")[0].endswith(OBSCURING) or bool(action and
        ((action.parameters or {}).get("typed") or {}).get("source") == OBSCURING))


def _end_glamer(engine: Any, actor: Any, why: str) -> None:
    if any(row.condition_id == UNENDING for row in actor.conditions.values()):
        return
    ended = False
    for mid, modifier in list(actor.modifiers.items()):
        if _obscuring_source(engine, modifier.source_definition_id):
            del actor.modifiers[mid]
            engine._append_event("MODIFIER_REMOVED", modifier.source_definition_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"modifier_id": mid, "reason": why})
            ended = True
    for iid, row in list(actor.conditions.items()):
        if _obscuring_source(engine, row.source_definition_id):
            del actor.conditions[iid]
            engine._append_event("CONDITION_REMOVED", row.source_definition_id, actor_id=actor.entity_id, target_ids=(actor.entity_id,),
                                 payload={"condition_id": row.condition_id, "instance_id": iid, "reason": why})
            ended = True
    if ended:
        note(engine, OBSCURING, actor, f"Obscuring Glamer: {actor.display_name} {why.lower().replace('_', ' ')}; the glamer ends.")


@hook("after_hit")
def glamer_attack_hit(ctx: Any, target: Any, kind: str) -> None:
    _end_glamer(ctx.engine, ctx.actor, "ATTACKS")


@hook("after_miss")
def glamer_attack_miss(ctx: Any, target: Any) -> None:
    _end_glamer(ctx.engine, ctx.actor, "ATTACKS")
    _world_regain(ctx.engine, ctx.actor)


@hook("technique_used")
def glamer_technique(ctx: Any) -> None:
    if ((ctx.action.parameters or {}).get("persist_augment")) == "TAL_ILLUSION_APPLY_GLAMER":
        return  # the glamer's own augment (combat/ext/persist_augment.py) is not another technique
    if not _obscuring_source(ctx.engine, ctx.source) and ((ctx.action.parameters or {}).get("typed") or {}).get("weapon") is None:
        _end_glamer(ctx.engine, ctx.actor, "USES_A_TECHNIQUE")


@hook("event")
def glamer_damage(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    if event_type != "DAMAGE_COMMITTED" or int((kwargs.get("payload") or {}).get("hp_damage") or 0) + int((kwargs.get("payload") or {}).get("temporary_hp_absorbed") or 0) <= 0:
        return
    source = engine.state.actors.get(kwargs.get("actor_id") or "")
    if source is not None and source.entity_id not in (kwargs.get("target_ids") or ()):
        _end_glamer(engine, source, "DEALS_DAMAGE")


@hook("stealth_search_mode")
def muffled_search(engine: Any, searcher: Any, foe: Any) -> str | None:
    """Muffle: "creatures have Disadvantage on Wisdom (Perception) checks made to hear the target"."""
    return "DISADVANTAGE" if any(row.condition_id == MUFFLED for row in foe.conditions.values()) else None


@hook("hide_check_override")
def muffled_hide(engine: Any, actor: Any) -> int | None:
    """Muffle: "The target does not suffer Disadvantage on Dexterity (Stealth) checks from heavy armor"."""
    if not any(row.condition_id == MUFFLED for row in actor.conditions.values()):
        return None
    hide = next((row for row in engine.action_catalog.values() if row.owner_id == actor.entity_id and ((row.parameters or {}).get("stealth") == "hide")), None)
    effect_row = ((((hide.parameters or {}).get("typed") or {}).get("effects") or [{}])[0]) if hide is not None else {}
    if effect_row.get("mode") != "DISADVANTAGE":
        return None
    roll = engine.roll_check(
        modifier=int(effect_row.get('bonus') or 0),
        actor_id=actor.entity_id,
        reason='CHECK:hide:muffled',
        ability='DEX',
        skill='Stealth',
    )
    engine._record_roll(roll)
    return int(roll.total)


# ------------------------------------------------------------------------------------------------ Sovereign Illusion Incarnation
@hook("compile_actions")
def sovereign_bonus_actions(info: dict[str, Any]) -> list[Any] | None:
    from ..gate2_runtime_models import EconomyKind

    if SOVEREIGN not in (info.get("owned_ids") or []):
        return None
    from .figment import figment_actions

    out = []
    for action in figment_actions(info) or []:  # (another plug-in's actions are not in info["actions"])
        params = action.parameters or {}
        if action.owner_id == info["actor_id"] and (params.get("figment_create") or params.get("figment_plant")):
            out.append(action.model_copy(update={"source_definition_id": action.source_definition_id + ".bonus", "display_name": f"{action.display_name} (Bonus Action)",
                                                 "economy": EconomyKind.BONUS_ACTION, "parameters": {**params, "illusion_sovereign": True,
                                                                                                    "figment_kit": False}}))
    return out or None


@hook("candidate_allowed")
def sovereign_allowed(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    if action is None or not (action.parameters or {}).get("illusion_sovereign"):
        return None
    return None if _active(engine, actor, SOVEREIGN) else False


# ------------------------------------------------------------------------------------------------ World of False Premises
def _world_regain(engine: Any, attacker: Any) -> None:
    """A hostile creature inside the World misses an attack while it carries your False Premise or your Wrong Angle: 1 CP back, the first time
    each round, at most PB a use."""
    from ..typed_executor import bears_mark

    for zone in engine.state.zones.values():
        if not zone.active or not str(zone.source_definition_id).endswith(WORLD) or not engine._footprint_intersects(attacker, zone.affected_cells):
            continue
        owner = engine.state.actors.get(zone.owner_id)
        if owner is None or owner.team_id == attacker.team_id or owner.turn_flags.get("illusion_round_world") == engine.state.round_number:
            continue
        misled = bears_mark(attacker, owner.entity_id, PREMISE) or any(
            row.target_field == "attack_mode" and row.source_actor_id == owner.entity_id for row in attacker.modifiers.values())
        gained = int((zone.trigger_profile or {}).get("world_gained") or 0)
        pb = next((int((((a.parameters or {}).get("typed") or {}).get("numbers") or {}).get("pb") or 2) for a in engine.action_catalog.values()
                   if a.owner_id == owner.entity_id and (a.parameters or {}).get("typed")), 2)
        pool = next((p for p in ("resource:core.qi", "resource:core.stamina", "resource:core.resonance") if p in owner.resources), None)
        if not misled or gained >= pb or pool is None:
            continue
        owner.turn_flags["illusion_round_world"] = engine.state.round_number
        zone.trigger_profile = {**zone.trigger_profile, "world_gained": gained + 1}
        engine._append_event("ZONE_CREATED", WORLD, actor_id=owner.entity_id, payload={"zone": zone.model_dump(mode="json")})
        engine._gain_resource(owner, pool, 1, WORLD)
        note(engine, WORLD, owner, f"World of False Premises: {attacker.display_name} misses on a false premise; {owner.display_name} regains 1 CP.")


@effect('illusion_sting_premise')
def sting_premise(ctx: Any, row: dict[str, Any]) -> None:
    """Phantom Sting's chosen, perceived hit follow-up; no forced saving throw on decline."""
    from ..typed_executor import run_effects
    from ..senses import perceives_cell
    target = ctx.target
    if target is None or not _owns(ctx.engine, ctx.actor, 'TAL_ILLUSION_PHANTOM_STING'):
        return
    # The false attack reaches the hit creature's space. Perceiving that
    # stimulus uses senses/conditions; seeing its caster is not a requirement.
    if not perceives_cell(ctx.engine, target, target.position):
        return
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'PHANTOM_STING', ctx.actor.entity_id, target.entity_id),
                 ctx.actor, CHOICE + 'phantom_sting', ['PREMISE'], allow_decline=True, preferred=['PREMISE'],
                 labels={'PREMISE': 'Force a Wisdom save; failure plants a False Premise'}, target_id=target.entity_id,
                 prompt=f'Phantom Sting hits {target.display_name}: {ctx.actor.display_name} may force a Wisdom save to plant a false belief until their next turn starts. No extra cost.')
    if picked:
        run_effects(ctx, [{'type': 'save', 'ability': 'wis', 'on_fail': [{'type': 'figment_premise', 'planted': True}]}])


@hook("cell_candidate_metadata")
def substantial_placement_metadata(engine: Any, actor: Any, action: Any, cell: Any) -> dict[str, Any] | None:
    """AI estimates only known enemies inside the real creation footprint."""
    effects = ((action.parameters or {}).get("typed") or {}).get("effects") or []
    if not any(row.get("type") == "illusion_substantial_phantasm" for row in effects):
        return None
    from .figment import creation_cells
    from ..candidate_knowledge import roster
    cells = creation_cells(engine, actor, cell)
    visible_roster = roster(engine)
    subjects = engine.state.actors.values() if visible_roster is None else visible_roster
    caught = sum(1 for subject in subjects if subject.active and subject.team_id != actor.team_id
                 and engine._footprint_intersects(subject, cells))
    return {"expected_damage": 0, "hostiles_in_area": caught, "empty_area": caught == 0}
