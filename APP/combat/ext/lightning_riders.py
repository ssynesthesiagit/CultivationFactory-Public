"""Lightning riders, automated (rider lane 1, 2026-09-29): what the Charge-shaping Realm Evolutions and domains change about
the sphere's own Charge rules.

Shared API: meridian_hit_choice is consumed by charge_marks after a real melee
Conductive Strike; Charged Needle calls it after its selected hit outcome.

combat/ext/charge_marks.py holds the base rule ("You can maintain a number of Charges at one time equal to your Proficiency
Bonus", a ``mark_caps`` row on First Circuit Method) and typed_executor.block_mark places the Charged mark; this module is
what raises or lengthens it, through the two hooks block_mark now runs (``mark_cap`` and ``mark_duration``, documented in
combat/ext/__init__.py), driven by feature blocks in combat/rules/feature_blocks.d/riders_lane1.json:

  {"block": "charge_realm", "arc_range_ft": 15, "charge_cap_add": 1, "charge_lasts": "until_end_of_your_next_turn"}
        Current Beyond the Skin: "Your Arc range increases to 15 feet" (an ``arc_upgrade`` row, combat/ext/arcs.py); "Your Charge
        limit increases by 1"; "A target you Charge remains Charged until the end of your next turn instead of the start of your
        next turn, unless the Charge is consumed" (consuming already removes the mark).

The Courts and Incarnations that reshape the Charge (named states, combat/ext/states.py: a ``state`` effect on the talent):

  Court of Charged Paths      "Your Charge limit increases by your Proficiency Bonus" (mark_cap); "The first time each round a hostile
                              creature inside the court takes lightning damage from one of your talents, it cannot take Reactions until
                              the start of its next turn"; "When a hostile creature starts its turn Charged inside the court, you may
                              move the Charge to another visible creature ... within 10 feet of it" (taken when a hostile creature
                              near it is not Charged already)
  Lightning Sovereign         "Your Charge limit doubles"; "The first time each round you deal lightning damage to a creature, that
  Incarnation                 creature cannot take Reactions until the start of its next turn"
  Lightning-God Body          a creature that misses the user with an Opportunity Attack is Charged
"""

from __future__ import annotations

import copy
from typing import Any

from . import effect, hook

CHARGED = "charged"
COURT, SOVEREIGN = "court_of_charged_paths", "lightning_sovereign_incarnation"
THUNDER_ARROW = "TAL_LIGHTNING_THUNDER_ARROW"
SPARK_INSTRUMENT = "TAL_LIGHTNING_SPARK_INSTRUMENT_METHOD"
PRISON_BARS = "TAL_LIGHTNING_LIGHTNING_PRISON_BARS"
PRISON_THUNDER = "condition:typed.prison_thunder"
FIST = 'TAL_LIGHTNING_ELECTRIC_FIST_METHOD'
WINGS = 'TAL_LIGHTNING_LIGHTNING_WINGS_OF_THE_HEAVENLY_BODY'
FIST_USES = 'condition:typed.electric_fist_uses'
BURST = 'condition:typed.lightning_wings_burst'
MERIDIAN = 'TAL_LIGHTNING_MERIDIAN_STOPPING_SPARK'
NET = 'TAL_LIGHTNING_SKY_FIRE_NERVE_NET'
#: "This talent can affect only one additional creature each turn." The shared all-creature clock
#: (combat/turn_uses.py sweeps this namespace at every creature's turn start), so a qualifying hit on
#: somebody else's turn is not blocked by a use on the owner's turn.
NET_USES = 'once_per_turn:lightning_sky_fire'


@hook('compile_block')
def compile_lightning_combat(block, spec, row, numbers):
    """``block: "lightning_combat"`` rows own one printed Lightning rule each.

    ``kind`` names the rule; ``effects`` (optional) is that rule's typed outcome, run by this
    module against a creature the rule chooses at fight time rather than the action's own target,
    so the data stays in combat/rules/feature_blocks.d and the choice stays with the owner.
    """
    if block == 'lightning_combat':
        compiled = {**row, 'kind': spec['kind'], 'numbers': dict(numbers),
                    'keeps_compiling': bool(spec.get('keeps_compiling'))}
        if spec.get('player_outcome'):
            compiled['player_outcome'] = str(spec['player_outcome'])
        if spec.get('effects'):
            compiled['effects'] = copy.deepcopy(spec['effects'])
        if spec.get('radius_ft'):
            compiled['radius_ft'] = int(spec['radius_ft'])
        return [compiled]


def _combat_row(engine, actor, kind):
    return next((r for r in engine.typed_passive_rows.get(actor.entity_id, [])
                 if r.get('block') == 'lightning_combat' and r.get('kind') == kind), None)


@hook('after_save_resolved')
def _sky_fire_nerve_net(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Sky-Fire Nerve Net: "When a creature fails a saving throw against Meridian-Stopping Spark, you may choose one
    additional Charged creature within 20 feet of it. The additional creature makes a Constitution saving throw.
    Failed Save: It cannot take Reactions until the start of its next turn and has Disadvantage on the next Constitution
    saving throw it makes to maintain Concentration before the end of its next turn. Successful Save: It loses its Charge.
    This talent can affect only one additional creature each turn."

    The printed trigger names Meridian-Stopping Spark's own save, so this is gated on that technique being the
    attribution of the save that failed (``Context.effect_source``, set by _meridian_intensify). Nothing else may
    open it: Infection of the Cultivation Breath and Meridian Ruin Shock apply the same "cannot regain CP" condition
    to their own failures, so a failed-save *condition* is shared authority text, not this talent's trigger.

    "each turn" is the shared all-creature clock (combat/turn_uses.py sweeps the ``once_per_turn:`` namespace at every
    creature's turn start), so a qualifying hit on somebody else's turn is not blocked by a use on the owner's turn.
    The use is spent only once the owner accepts, so declining leaves the talent available for a later qualifying hit
    in the same turn.
    """
    if not failed or subject is None or ctx.actor.team_id == subject.team_id:
        return
    if ctx.effect_source != MERIDIAN:
        return
    row = _combat_row(ctx.engine, ctx.actor, 'sky_fire')
    if row is None or ctx.actor.turn_flags.get(NET_USES):
        return
    from . import needle
    from .. import typed_executor as te, stealth

    radius = int(row.get('radius_ft') or 20)
    nearby = [other for other in ctx.engine.state.actors.values()
              if other.active and other.entity_id != subject.entity_id
              and te.bears_mark(other, ctx.actor.entity_id, CHARGED)
              and ctx.engine._distance_actor_to_actor(subject, other) <= radius]
    if not nearby:
        return
    order = sorted(nearby, key=lambda other: ctx.engine._distance_actor_to_actor(subject, other))
    # The printed human pool needs Charge and distance, not sight or hostility.
    # Automatic recipients are restricted to what this creature sees.
    automatic = [other.entity_id for other in order
                 if other.team_id != ctx.actor.team_id and stealth.sees(ctx.engine, ctx.actor, other)]
    chosen = needle.ask(
        ctx.engine, ctx.intent, needle.checkpoint_id(ctx.engine, 'sky_fire', subject.entity_id), ctx.actor,
        needle.CHOICE + 'sky_fire', [other.entity_id for other in order],
        labels={other.entity_id: other.display_name for other in order},
        preferred=automatic, automatic_options=automatic, allow_decline=True,
        prompt=f'Sky-Fire Nerve Net: {subject.display_name} failed Meridian-Stopping Spark\'s Constitution saving throw '
               f'from {ctx.action.display_name}. Choose one other Charged creature within {radius} feet of '
               f'{subject.display_name} to also make a Constitution save: on a failure it loses its Reactions until '
               'its next turn starts and has Disadvantage on its next Constitution save to hold Concentration before '
               'the end of its next turn; on a success it loses its Charge. This talent can affect only one '
               'additional creature each turn.',
        target_id=subject.entity_id, name='Sky-Fire Nerve Net', feature_id=NET,
        prompt_context={'source_definition_id': ctx.action.source_definition_id,
                        'action_name': ctx.action.display_name,
                        'action_actor_id': ctx.actor.entity_id, 'affected_id': subject.entity_id})
    if not chosen:
        return  # declining spends nothing: no additional creature was affected, so the turn's use is still available
    ctx.actor.turn_flags[NET_USES] = True
    additional = ctx.engine.state.actors[chosen[0]]
    from . import states

    # The additional creature's save stays against the technique that carried Meridian's rider (Electric Fist,
    # Charged Needle or Conductive Strike), so its printed technique save DC resolves exactly as the first save did.
    # states.context names that action and no rider, so this second save cannot open Sky-Fire again.
    sub = states.context(ctx.engine, ctx.actor, ctx.action.source_definition_id, [additional],
                         dict((ctx.typed or {}).get('numbers') or {}))
    te.run_effects(sub, row.get('effects') or [])


@hook('compile_actions')
def seal_fist_numbers(info):
    # Compilation-only annotation: block compilation has PB/CL/key but not the
    # sheet's Cultivation DC. Never borrow a weapon maneuver's different DC.
    for row in info['passives']:
        if row.get('block') == 'lightning_combat' and row.get('kind') in {'fist', 'meridian', 'fist_adept'}:
            row['numbers'] = {key: int(info['numbers'][key]) for key in ('pb', 'cl', 'key_mod', 'save_dc')}
    return []


@hook('flight')
def lightning_flight(engine, actor):
    from . import states
    sovereign = states.active(engine, actor, SOVEREIGN)
    body = states.active(engine, actor, 'lightning_god_body', 'true_lightning_god_mantle', SOVEREIGN)
    from ..movement_speeds import land_speed_grant, all_bonus
    speed = 60 if sovereign is not None else 0
    # Two independent grants: Sovereign's printed 60 ft (resolve adds the all-Speeds bonus once) and Wings' Fly equal
    # to walking Speed. Without Sovereign, Wings alone is the grant. With Sovereign, the walking grant only wins when
    # live walking Speed beats the printed grant after its own bonus; otherwise the printed grant is the faster one.
    if (body is not None and _combat_row(engine, actor, 'wings')
            and (not speed or engine._effective_speed(actor) > speed + all_bonus(engine, actor))):
        # Walking-derived: live walking Speed already holds the all-Speeds bonus. The grant declares that
        # provenance so movement_speeds.resolve does not add the bonus a second time.
        return {**land_speed_grant(engine, actor, 'fly'), 'flight_hover': 1}
    if speed:
        return {'fly_speed_ft': int(speed), 'flight_hover': 1}


@effect('lightning_wings_burst')
def wings_burst(ctx, effect_row):
    from .rider_choices import pick
    from ..typed_executor import run_effects
    from dataclasses import replace
    expires = 'END_OF_CURRENT_TURN'
    if int(ctx.numbers.get('cl') or 1) >= 11:
        chosen = pick(ctx.engine, ctx.actor, 'wings_burst_duration', 'Lightning Wings Burst', ['SUSTAIN'],
            subject=ctx.actor, preferred=[], automatic=False,
            labels={'SUSTAIN': 'Concentrate to keep flying until your next turn starts'},
            trigger='Unfold your wings: 1 CP was paid; otherwise flight ends this turn and you must land or fall')
        if chosen:
            ctx.engine._start_concentration(ctx.actor, ctx.source)
            expires = 'CONCENTRATION_END'
            timer = replace(ctx, typed={**ctx.typed, 'duration': {'kind': 'until_start_of_your_next_turn'}})
            run_effects(timer, [{'type': 'limit_concentration_duration'}])
    from ..movement_speeds import land_speed_grant
    ctx.engine._apply_condition(ctx.actor, BURST, ctx.source, ctx.actor.entity_id, expires_on=expires,
        data={**land_speed_grant(ctx.engine, ctx.actor),
              'label': 'Lightning Wings Burst: fly at your walking Speed; land before flight ends or fall'})


@hook('after_hit_choice')
def electric_fist_choice(ctx, target, kind):
    from ..attack_notifications import is_melee_hit
    from .rider_choices import pick
    from .condition_ownership import refresh_owned
    from ..typed_executor import run_effects
    from dataclasses import replace
    row = _combat_row(ctx.engine, ctx.actor, 'fist')
    if row is None or target is None or not target.active or not is_melee_hit(ctx):
        return
    if target.team_id == ctx.actor.team_id:
        return
    counter = next((c for c in ctx.actor.conditions.values() if c.condition_id == FIST_USES), None)
    used = int(counter.data.get('uses', 0)) if counter is not None else 0
    maximum = int(row['numbers'].get('pb') or ctx.actor.proficiency_bonus)
    if used >= maximum:
        return
    options, labels = ['SHOCK'], {'SHOCK': 'Force a Constitution save; no extra Action or CP'}
    intensify = _meridian_option(ctx, target, row)
    if intensify is not None:
        options, labels = ['SHOCK', 'INTENSIFY'], {
            'SHOCK': 'Force a Constitution save; no extra Action or CP',
            'INTENSIFY': intensify[1]}
    # The two abilities' penalties end on different clocks, so name both rather than a single "your next turn":
    # Electric Fist's penalties end at the start of the user's next turn; Meridian's last to the end of the target's next turn.
    deadlines = ("the Electric Fist shock's speed and Reaction penalties end at the start of "
                 "your next turn")
    if intensify is not None:
        deadlines += ("; Meridian-Stopping Spark's penalties last until the end of "
                      f"{target.display_name}'s next turn")
    chosen = pick(ctx.engine, ctx.actor, 'electric_fist', 'Electric Fist Method', options, subject=target,
        preferred=[options[0]], labels=labels,
        trigger=f'{ctx.action.display_name} hits {target.display_name} in melee; {maximum-used} uses left until a '
                f'short or long rest; {deadlines}')
    if not chosen:
        return
    refresh_owned(ctx.engine, ctx.actor, FIST_USES, ctx.actor.entity_id, FIST)
    ctx.engine._apply_condition(ctx.actor, FIST_USES, FIST, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
        data={'uses': used + 1, 'label': f'Electric Fist Method: {maximum-used-1} uses left until a short or long rest'})
    expiry = {'expires_on': 'START_OF_SOURCE_NEXT_TURN', 'applies_to': 'target'}
    sub = replace(ctx, typed={**ctx.typed, 'source': FIST, 'numbers': row['numbers']}, effect_source=FIST)
    run_effects(sub, [{'type': 'save', 'ability': 'con', 'on_fail': [
        {'type': 'speed', 'flat': -10, **expiry}, {'type': 'reaction_denied', **expiry}],
        'on_success': [{'type': 'reaction_denied', 'on': 'against you', **expiry}]}])
    if intensify is not None and 'INTENSIFY' in chosen:
        _meridian_intensify(ctx, target, row, intensify[0])


def _meridian_hit_key(ctx: Any, target: Any) -> str:
    """Identify a confirmed hit across its Fist, Conductive and Needle riders."""
    hit = ctx.attack_damage_context
    roll_id = hit.roll_id if hit is not None else str((ctx.attack_result or {}).get('roll_id') or '')
    return 'meridian_intensified:' + target.entity_id + ':' + roll_id


def _meridian_option(ctx: Any, target: Any, fist_row: dict[str, Any]) -> tuple[str, str] | None:
    """Meridian-Stopping Spark's "spend 1 CP to intensify" as a second option on the Fist's own ask.

    The two decisions are one menu because the choice transport carries a single pending request per
    transaction, and both are decided on the same melee hit. Returns ``(resource_id, label)`` when the
    owner may intensify, else None so a character without Meridian-Stopping Spark sees the printed Fist
    menu unchanged. Charged Needle and a melee Conductive Strike are the talent's other two printed
    triggers; their actual selected hit resolution calls meridian_hit_choice.
    """
    row = _combat_row(ctx.engine, ctx.actor, 'meridian')
    if ctx.damage_cache.get(_meridian_hit_key(ctx, target)):
        return None
    if row is None or not row.get('effects'):
        return None
    from ..factory_compiler import RESOURCE_IDS

    resource = RESOURCE_IDS['qi']  # CP is the Cultivation Points pool; Qi/CP share one resource id.
    cost = int(row.get('cp_cost') or 1)
    if ctx.actor.resources.get(resource, 0) < cost:
        return None
    return resource, (f'Meridian-Stopping Spark: spend {cost} CP for an extra Constitution saving throw. If the '
                      f'target fails it, until the end of its next turn it cannot regain CP, has Disadvantage on '
                      f'Constitution saves to hold Concentration, and cannot take Reactions. If the target saves, '
                      f'until the start of its next turn it cannot regain CP and has Disadvantage on its next '
                      f'Constitution save to hold Concentration.')


def _meridian_intensify(ctx: Any, target: Any, fist_row: dict[str, Any], resource: str) -> None:
    """Run Meridian-Stopping Spark's own save after the Fist save it intensifies."""
    row = _combat_row(ctx.engine, ctx.actor, 'meridian')
    from ..typed_executor import run_effects
    from dataclasses import replace

    ctx.damage_cache[_meridian_hit_key(ctx, target)] = True
    ctx.engine._spend_resource(ctx.actor, resource, int(row.get('cp_cost') or 1), MERIDIAN)
    numbers = {**dict((ctx.typed or {}).get('numbers') or {}), **dict(fist_row.get('numbers') or {})}
    sub = replace(ctx, typed={**ctx.typed, 'numbers': numbers}, effect_source=MERIDIAN)
    run_effects(sub, row['effects'])


@hook("decision_text")
def decision_text(engine: Any, context: dict[str, Any], printed_rules: dict[str, str]) -> dict[str, Any] | None:
    """The active court's transfer is free; its activation cost was already paid."""
    if context.get("reaction_source_id") != "choice:needle.court_charge":
        return None
    trigger = context.get("choice_trigger") or {}
    owner = engine.state.actors.get(context.get("reactor_id"))
    if owner is None or not any(c.source_definition_id == trigger.get("feature_id") for c in owner.conditions.values()):
        return None
    affected = engine.state.actors.get(trigger.get("target_id"))
    return {"feature_id": trigger.get("feature_id"), "cost": "No action or resource cost to transfer; the court was paid for when activated",
            "summary": "Move the existing lightning Charge to a visible creature within 10 feet. Charge is a lightning mark that your Lightning abilities can use; moving it does not refresh its duration.",
            "option_descriptions": {option: f"Move {affected.display_name if affected else 'the creature'}'s Charge to {engine.state.actors[option].display_name}; keep its current expiry."
                                    for option in (context.get("extension_choice") or {}).get("option_ids") or [] if option in engine.state.actors},
            "table_note": "This table offers creature destinations for the transfer."}


@hook("event")
def _thunder_presses_prison_repeat(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Only thunder damage while Restrained arms the bars' next repeat-save Disadvantage."""
    if event_type != "DAMAGE_COMMITTED" or str((kwargs.get("payload") or {}).get("damage_type") or "").upper() != "THUNDER":
        return
    if int((kwargs.get("payload") or {}).get("reduced_to") or 0) <= 0:
        return
    from .effect_durations import token

    for target_id in kwargs.get("target_ids") or ():
        target = engine.state.actors.get(target_id)
        if target is None:
            continue
        for bars in list(target.conditions.values()):
            repeat = (bars.data or {}).get("repeat_save") or {}
            if bars.condition_id != "condition:typed.restrained" or not repeat.get("thunder_disadvantage"):
                continue
            marker = PRISON_THUNDER + "." + bars.source_definition_id
            engine._remove_condition(target, marker, bars.source_definition_id)
            engine._apply_condition(target, marker, bars.source_definition_id, bars.source_actor_id,
                                    expires_on=token("end", target.entity_id, target.turns_started + 1),
                                    data={"bars_source": bars.source_definition_id, "label": "Thunder: next bars repeat save has Disadvantage"})


@hook("before_dex_save")
def _prison_repeat_mode(engine: Any, defender: Any, intent: Any, context: dict[str, Any]) -> dict[str, str] | None:
    # Typed initial saves carry their effect in context; the engine's repeat save does not.
    if context.get("effect") is not None:
        return None
    source = context.get("source_id")
    restrained = any(c.condition_id == "condition:typed.restrained" and c.source_definition_id == source
                     and (c.data or {}).get("repeat_save", {}).get("thunder_disadvantage") for c in defender.conditions.values())
    marker = next((c for c in defender.conditions.values() if c.condition_id.startswith(PRISON_THUNDER + ".")
                   and (c.data or {}).get("bars_source") == source), None)
    if not restrained or marker is None:
        return None
    engine._remove_condition(defender, marker.condition_id, source)
    return {"mode": "DISADVANTAGE"}


@hook("compile_actions")
def _thunder_arrow_weapons(info: dict[str, Any]) -> list[Any] | None:
    """Thunder Arrow is an ammunition/thrown weapon imbuement; Lightning Lash is not a weapon.

    Its typed ``thunder_arrow_report`` row runs on a hit, choosing and spending 1 CP then.
    The existing weapon action supplies its own range, attack roll and weapon damage.
    """
    if THUNDER_ARROW not in info["owned_ids"]:
        return None
    import copy
    from ..factory_compiler import RESOURCE_IDS

    spec = (info["mechanics"].get(THUNDER_ARROW) or {}).get("modifier") or {}
    report = next((row for row in spec.get("effects") or [] if row.get("type") == "thunder_arrow_report"), None)
    if report is None:
        return None
    made = []
    for action in info["actions"]:
        typed = copy.deepcopy((action.parameters or {}).get("typed") or {})
        if not typed.get("weapon") or not typed.get("range_ft"):
            continue
        attacks = [row for row in typed.get("effects") or [] if row.get("type") == "attack" and row.get("attack_kind") == "weapon"]
        if not attacks:
            continue
        for attack in attacks:
            attack.setdefault("on_hit", []).append({**copy.deepcopy(report), "resource_id": RESOURCE_IDS[info["primary"]]})
        typed["numbers"] = {**typed.get("numbers", {}), "save_dc": info["numbers"]["save_dc"]}
        made.append(action.model_copy(update={"source_definition_id": action.source_definition_id + "+thunder_arrow",
                                             "display_name": action.display_name + " + Thunder Arrow",
                                             "parameters": {**action.parameters, "typed": typed,
                                                            "variant_of": action.source_definition_id}}))
    return made or None


@effect("thunder_arrow_report")
def _thunder_arrow_report(ctx: Any, eff: dict[str, Any]) -> None:
    from .. import typed_executor as te, typed_reactions

    resource = str(eff.get("resource_id") or "")
    if ctx.actor.resources.get(resource, 0) < 1 or not typed_reactions._consent(
            ctx.engine, {"feature_id": THUNDER_ARROW, "ask": True}, ctx.actor, "THUNDER_ARROW_HIT"):
        return
    ctx.engine._spend_resource(ctx.actor, resource, 1, THUNDER_ARROW)
    te.run_effects(ctx, eff.get("effects") or [])


@effect("spark_instrument_choice")
def _spark_instrument_choice(ctx: Any, eff: dict[str, Any]) -> None:
    """Spark-Instrument: ask its owner for exactly one creature near a Charged target."""
    from .. import typed_executor as te
    from . import needle

    target = ctx.target
    if target is None or not any(c.condition_id.startswith(te.mark_condition_id("Charged", ""))
                                 for c in target.conditions.values()):
        return
    radius = int(eff.get("range_ft") or 5)
    options = [a.entity_id for a in ctx.engine.state.actors.values()
               if a.active and a.entity_id != target.entity_id
               and ctx.engine.grid.distance_ft(target.position, a.position) <= radius]
    if not options:
        return
    labels = {aid: f"Have {ctx.engine.state.actors[aid].display_name} hear the report"
              for aid in options}
    selected = needle.ask(
        ctx.engine, ctx.intent,
        needle.checkpoint_id(ctx.engine, "spark_instrument", ctx.actor.entity_id, target.entity_id),
        ctx.actor, needle.CHOICE + "spark_instrument", options, labels=labels,
        prompt=f"Spark-Instrument Method: {target.display_name} is Charged. Choose one creature within {radius} feet of {target.display_name} to hear the sharp report and have Disadvantage on its next Wisdom (Perception) check before your next turn.",
        target_id=target.entity_id, name="Spark-Instrument Method", feature_id=SPARK_INSTRUMENT,
        prompt_context={"source_definition_id": ctx.source, "action_name": ctx.action.display_name,
                        "action_actor_id": ctx.actor.entity_id, "affected_id": target.entity_id})
    if not selected:
        return
    subject = ctx.engine.state.actors[selected[0]]
    ctx.engine._apply_condition(
        subject, te.CONDITION_PREFIX + "check_mode", ctx.source, ctx.actor.entity_id,
        expires_on="START_OF_SOURCE_NEXT_TURN",
        data={"rule": {"check_mode": {"Perception": "DISADVANTAGE"}}, "spark_instrument": True, "next_check": True,
              "label": f"Spark-Instrument Method: Disadvantage on the next Wisdom (Perception) check until {ctx.actor.display_name}'s next turn starts"})


@hook("event")
def _consume_spark_instrument_check(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Spend the oldest Spark instance after its holder rolls Perception.

    Each application buys one penalized check. Persisted application sequences,
    rather than dictionary order (which can change on reload), determine FIFO.
    """
    payload = kwargs.get("payload") or {}
    if event_type != "CHECK_ROLLED" or str(payload.get("skill") or payload.get("check") or "").casefold() != "perception":
        return
    # CHECK_ROLLED may name creatures being searched as targets. Only the roller
    # spent this one-check penalty; by-sense discovery does not roll at all.
    if payload.get("by_sense"):
        return
    actor = engine.state.actors.get(kwargs.get("actor_id") or "")
    if actor is None:
        return
    for condition in sorted(actor.conditions.values(), key=lambda c: (c.applied_sequence, c.instance_id)):
        data = condition.data or {}
        if (condition.condition_id != "condition:typed.check_mode"
                or not data.get("next_check")
                or not data.get("spark_instrument")):
            continue
        del actor.conditions[condition.instance_id]
        engine._append_event("CONDITION_REMOVED", condition.source_definition_id,
                             actor_id=condition.source_actor_id, target_ids=(actor.entity_id,),
                             payload={"condition_id": condition.condition_id,
                                      "instance_id": condition.instance_id})
        break


@hook("compile_block")
def _compile_charge_realm(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]) -> list[dict[str, Any]] | None:
    if block != "charge_realm":
        return None
    out: list[dict[str, Any]] = []
    if spec.get("arc_range_ft"):
        out.append({**row, "block": "arc_upgrade", "for": ["*"], "range_ft": int(spec["arc_range_ft"]), "conductive_becomes_charged": False})
    if spec.get("charge_cap_add"):
        out.append({**row, "block": "charge_cap", "add": int(spec["charge_cap_add"])})
    if spec.get("charge_lasts"):
        out.append({**row, "block": "charge_lasts", "kind": str(spec["charge_lasts"])})
    return out


@hook("mark_cap")
def _charge_cap(ctx: Any, name: str) -> dict[str, int] | None:
    if name.strip().lower() != CHARGED:
        return None
    from .. import typed_reactions

    from . import states

    add = sum(int(row.get("add") or 0) for row in typed_reactions._rows(ctx.engine, ctx.actor.entity_id, "charge_cap"))
    court = states.active(ctx.engine, ctx.actor, COURT)
    if court is not None:
        add += int(((court.data or {}).get("numbers") or {}).get("pb") or 0)  # "increases by your Proficiency Bonus"
    out: dict[str, int] = {"add": add} if add else {}
    if states.active(ctx.engine, ctx.actor, SOVEREIGN):
        out["mul"] = 2  # "Your Charge limit doubles"
    return out or None


@hook("mark_duration")
def _charge_lasts(ctx: Any, name: str, kind: str) -> str | None:
    if name.strip().lower() != CHARGED or kind != "until_start_of_your_next_turn":
        return None
    from .. import typed_reactions

    return next((str(row["kind"]) for row in typed_reactions._rows(ctx.engine, ctx.actor.entity_id, "charge_lasts")), None)


def _opportunity_attack(engine: Any, attacker: Any, reason: str) -> bool:
    return "opportunity" in str(reason or "").lower() or getattr(engine, "_typed_oa_attacker", None) == attacker.entity_id


@hook("event")
def _god_body_marks_a_missed_opportunity_attack(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Lightning-God Body: "When a creature misses you with an Opportunity Attack, you may place a Charge on that creature."
    (The attack roll's own event names the target; a foe of a Body that is on and misses it is Charged: it costs nothing.)"""
    payload = kwargs.get("payload") or {}
    if event_type != "ATTACK_ROLLED" or payload.get("provisional_hit") is not False:
        return
    attacker = engine.state.actors.get(kwargs.get("actor_id") or "")
    if attacker is None or not attacker.active or not _opportunity_attack(engine, attacker, payload.get("reason")):
        return
    from . import states
    from .. import typed_executor as te

    for target_id in kwargs.get("target_ids") or ():
        holder = engine.state.actors.get(target_id)
        state = states.active(engine, holder, "lightning_god_body") if holder is not None and holder.team_id != attacker.team_id else None
        if state is None:
            continue
        ctx = states.context(engine, holder, state.source_definition_id, [attacker], (state.data or {}).get("numbers"))
        from dataclasses import replace
        from . import needle
        ctx = replace(ctx, intent=getattr(engine, "_active_intent", None))
        chosen = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "god_body_charge", attacker.entity_id), holder,
                            needle.CHOICE + "god_body_charge", [attacker.entity_id], allow_decline=True,
                            labels={attacker.entity_id: f"Place a Charge on {attacker.display_name}"},
                            prompt=f"Lightning-God Body: {attacker.display_name}'s Opportunity Attack misses {holder.display_name}; "
                                   "place a Charge on the attacker?",
                            target_id=attacker.entity_id, name="Lightning-God Body", feature_id=state.source_definition_id)
        if not chosen:
            continue
        cap = te.mark_capacity(ctx, "Charged")
        charged = sorted((c.applied_sequence, a.entity_id) for a in engine.state.actors.values() for c in a.conditions.values()
                         if c.condition_id == te.mark_condition_id("Charged", holder.entity_id))
        if cap and len(charged) >= cap and not te.bears_mark(attacker, holder.entity_id, "Charged"):
            replacement = needle.ask(engine, ctx.intent, needle.checkpoint_id(engine, "god_body_replace", attacker.entity_id), holder,
                                     needle.CHOICE + "god_body_replace", [aid for _, aid in charged], allow_decline=True,
                                     labels={aid: f"Replace the Charge on {engine.state.actors[aid].display_name}" for _, aid in charged},
                                     prompt=f"Lightning-God Body: after {attacker.display_name}'s missed Opportunity Attack against "
                                            f"{holder.display_name}, Charge limit reached; which existing Charge should be replaced?",
                                     target_id=attacker.entity_id, name="Lightning-God Body", feature_id=state.source_definition_id)
            if not replacement:
                continue
            engine._remove_condition(engine.state.actors[replacement[0]], te.mark_condition_id("Charged", holder.entity_id), ctx.source)
        te.run_effects(ctx, [{"type": "mark", "mark": "Charged", "applies_to": "target", "duration": {"kind": "until_start_of_your_next_turn"}}])


@hook("event")
def _first_lightning_each_round(engine: Any, event_type: str, kwargs: dict[str, Any]) -> None:
    """Court of Charged Paths / Lightning Sovereign Incarnation: the first lightning damage a hostile creature takes each round from
    the user (inside the court, for the Court) takes its Reactions away until the start of its next turn."""
    payload = kwargs.get("payload") or {}
    if event_type != "DAMAGE_COMMITTED" or str(payload.get("damage_type") or "").upper() != "LIGHTNING":
        return
    if int(payload.get("reduced_to") or 0) <= 0:
        return
    owner = engine.state.actors.get(kwargs.get("actor_id") or "")
    if owner is None:
        return
    from . import states
    from .. import typed_executor as te

    event = next((e for e in reversed(engine.events) if e.event_type == "DAMAGE_COMMITTED"
                  and e.actor_id == owner.entity_id and e.payload == payload), None)
    source = event.source_definition_id if event is not None else ""
    action = engine.action_catalog.get(source)
    typed = (action.parameters or {}).get("typed") or {} if action is not None else {}
    # Court says "from one of your talents"; Incarnation covers all lightning damage.
    talent_damage = bool(typed.get("sphere")) or "TAL_" in source or "tianxia.talent." in source
    if not talent_damage:
        talent_damage = any(row.get("feature_id") or row.get("source_modifier") or row.get("type") == "thunder_arrow_report"
                            for row in te._walk_rows(typed.get("effects") or []))

    for victim_id in kwargs.get("target_ids") or ():
        victim = engine.state.actors.get(victim_id)
        if victim is None or not victim.active:
            continue
        for name, needs_court in ((SOVEREIGN, False), (COURT, True)):
            state = states.active(engine, owner, name)
            key = f"lightning_reactions_denied_round_{engine.state.round_number}_{name}_{victim.entity_id}"
            if state is None or owner.turn_flags.get(key) or (needs_court and
                    (not talent_damage or victim.team_id == owner.team_id or engine._distance_actor_to_actor(owner, victim) > 60)):
                continue
            owner.turn_flags[key] = True
            te.run_effects(states.context(engine, owner, state.source_definition_id, [victim], (state.data or {}).get("numbers")),
                           [{"type": "reaction_denied", "applies_to": "target", "expires_on": te.TARGET_NEXT_START}])


@hook("turn_start")
def _court_moves_the_charge(engine: Any, actor: Any) -> None:
    """Court of Charged Paths: "When a hostile creature starts its turn Charged inside the court, you may move the Charge to another
    visible creature, object, or space within 10 feet of it."  Moved to the nearest creature near it that is not Charged already."""
    from . import states, arcs, needle
    from .. import stealth
    from .. import typed_executor as te

    for owner in list(engine.state.actors.values()):
        state = states.active(engine, owner, COURT) if owner.active and owner.team_id != actor.team_id else None
        if state is None or not te.bears_mark(actor, owner.entity_id, arcs.CHARGED) or engine._distance_actor_to_actor(owner, actor) > 60:
            continue
        near = sorted((engine._distance_actor_to_actor(actor, row), row.entity_id, row) for row in engine.state.actors.values()
                      if row.active and row.entity_id != actor.entity_id and stealth.sees(engine, owner, row)
                      and engine._distance_actor_to_actor(actor, row) <= 10 and not te.bears_mark(row, owner.entity_id, arcs.CHARGED))
        # Hostile recipients first for the unattended default; a player can choose any visible creature, or decline.
        foes = [item for item in near if item[2].team_id != owner.team_id]
        if not near:
            continue
        ids = [item[2].entity_id for item in near]
        chosen = needle.ask(engine, getattr(engine, "_active_intent", None),
                            needle.checkpoint_id(engine, "court_charge", actor.entity_id), owner,
                            needle.CHOICE + "court_charge", ids, labels={item[2].entity_id: item[2].display_name for item in near},
                            preferred=[(foes or near)[0][2].entity_id], allow_decline=True,
                            prompt=f"Court of Charged Paths: {actor.display_name} starts its turn Charged; move its Charge to which creature?",
                            target_id=actor.entity_id, name="Court of Charged Paths", feature_id=state.source_definition_id)
        if not chosen:
            continue
        mark_id = te.mark_condition_id("Charged", owner.entity_id)
        charge = next(c for c in actor.conditions.values() if c.condition_id == mark_id)
        # Moving a Charge neither consumes it to empower a talent nor refreshes its duration.
        engine._remove_condition(actor, mark_id, state.source_definition_id)
        moved = engine.state.actors[chosen[0]]
        engine._apply_condition(moved, mark_id, charge.source_definition_id, owner.entity_id,
                                expires_on=charge.expires_on, data=dict(charge.data or {}))
        engine._append_event("PASSIVE_TRIGGERED", state.source_definition_id, actor_id=owner.entity_id, target_ids=(actor.entity_id, moved.entity_id),
                             payload={"log": f"{owner.display_name} moves the Charge from {actor.display_name} to {moved.display_name}."})


@hook("candidate_allowed")
def _prison_bars_target(engine: Any, actor: Any, candidate: Any, action: Any) -> bool | None:
    """Lightning Prison Bars: "Target: One Charged creature or one creature standing inside a Conductive Field"."""
    if action is None or not str(action.source_definition_id).split("+")[0].endswith("TAL_LIGHTNING_LIGHTNING_PRISON_BARS"):
        return None
    from . import arcs
    from .. import typed_executor as te

    for target_id in candidate.target_ids or ():
        target = engine.state.actors.get(target_id)
        if target is not None and not (te.bears_mark(target, actor.entity_id, arcs.CHARGED) or arcs.in_conductive_field(engine, actor, target)):
            return False
    return None


@effect("meridian_hit_choice")
def meridian_hit_choice(ctx: Any, effect_row: dict[str, Any]) -> None:
    """Optional Meridian save after a real Charged Needle or melee Conductive hit.

    Called by the selected Needle modifier or by Conductive Strike's actual
    post-hit resolution, never merely by owning either talent. A hit can carry
    Electric Fist too; one intensification on that hit is sufficient.
    """
    target = ctx.target
    if target is None or not target.active or target.team_id == ctx.actor.team_id:
        return
    if ctx.damage_cache.get(_meridian_hit_key(ctx, target)):
        return
    row = _combat_row(ctx.engine, ctx.actor, 'meridian')
    if row is None:
        return
    offer = _meridian_option(ctx, target, row)
    if offer is None:
        return
    from . import needle
    if not needle.ask(ctx.engine, ctx.intent,
                       needle.checkpoint_id(ctx.engine, "meridian_hit", target.entity_id),
                       ctx.actor, needle.CHOICE + "meridian_hit", ["INTENSIFY"],
                       labels={"INTENSIFY": offer[1]}, allow_decline=True,
                       prompt=f"Meridian-Stopping Spark: {ctx.action.display_name} hits {target.display_name}. " + offer[1],
                       name="Meridian-Stopping Spark", feature_id=MERIDIAN, target_id=target.entity_id):
        return
    _meridian_intensify(ctx, target, row, offer[0])


@effect("charged_needle_choice")
def charged_needle_choice(ctx: Any, effect_row: dict[str, Any]) -> None:
    """Sample the old Charge before this hit places one; choose one printed outcome."""
    from .. import typed_executor as te
    from . import needle
    target = ctx.target
    if target is None:
        return
    from dataclasses import replace
    ctx = replace(ctx, typed={**ctx.typed, "numbers": {**ctx.numbers, **effect_row.get("numbers", {})}})
    existing = te.bears_mark(target, ctx.actor.entity_id, "Charged")
    options = ["CHARGE", "CONSUME"] if existing else ["CHARGE"]
    picks = needle.ask(ctx.engine, ctx.intent,
                       needle.checkpoint_id(ctx.engine, "charged_needle", target.entity_id),
                       ctx.actor, needle.CHOICE + "charged_needle", options,
                       labels={"CHARGE": "Place a Charge until your next turn starts",
                               "CONSUME": "Consume the existing Charge; force a Constitution save against CP recovery"},
                       allow_decline=True, prompt=f"Charged Needle hits {target.display_name}: place a Charge" +
                       (" or consume its existing Charge?" if existing else "? This new Charge cannot be consumed on the same hit."),
                       name="Charged Needle", feature_id="TAL_LIGHTNING_CHARGED_NEEDLE", target_id=target.entity_id)
    if not picks:
        return
    if picks[0] == "CHARGE":
        te.run_effects(ctx, effect_row["place"])
    else:
        te.run_effects(ctx, effect_row["consume"])
    meridian_hit_choice(ctx, {})


@hook("movement_step")
def wings_burst_pass_damage(engine: Any, mover: Any, previous: Any, nxt: Any, intent: Any) -> None:
    """Shock nearby Charged creatures on actual voluntary flight steps, once per turn."""
    from ..movement_steps import context as movement_context
    scope = engine.movement_scope(mover.entity_id) or {}
    if movement_context(engine, mover).get("forced") or scope.get("mode") != "fly":
        return
    grant = next((c for c in mover.conditions.values() if c.condition_id == BURST), None)
    if grant is None:
        return
    from .. import typed_executor as te, stealth
    from . import needle, states
    nearby = [other for other in engine.state.actors.values()
              if other.active and other.entity_id != mover.entity_id
              and te.bears_mark(other, mover.entity_id, "Charged")
              and engine._distance_actor_to_actor(mover, other) <= 5
              and not mover.turn_flags.get("once_per_turn:wings_burst:" + other.entity_id)]
    options = sorted(other.entity_id for other in nearby)
    if not options:
        return
    # Sight/hostility constrain the automatic subset, never the printed human menu.
    enemies = sorted(other.entity_id for other in nearby
                     if other.team_id != mover.team_id and stealth.sees(engine, mover, other))
    picks = needle.ask(engine, intent,
                       needle.checkpoint_id(engine, "wings_burst_pass", str(nxt)), mover,
                       needle.CHOICE + "wings_burst_pass", options,
                       automatic_options=enemies, preferred=enemies, minimum=0,
                       maximum=len(options), default_count=len(enemies), allow_decline=True,
                       labels={other.entity_id: f"Deal {mover.proficiency_bonus} lightning damage to {other.display_name}" for other in nearby},
                       prompt="Lightning Wings Burst: choose Charged creatures passed within 5 feet to take lightning damage. "
                       "Each creature can take this damage once per turn.", name="Lightning Wings Burst",
                       feature_id=grant.source_definition_id)
    for aid in picks:
        mover.turn_flags["once_per_turn:wings_burst:" + aid] = True
        ctx = states.context(engine, mover, grant.source_definition_id, [engine.state.actors[aid]],
                             {"pb": int(mover.proficiency_bonus)})
        te.run_effects(ctx, [{"type": "damage", "applies_to": "target", "formula": "pb", "damage_types": ["lightning"]}])


@hook("after_save_resolved")
def electric_fist_adept(ctx: Any, subject: Any, ability: str, named: Any, failed: bool) -> None:
    """Adept's optional PB shock and once-per-scene immediate 5-foot step."""
    if not failed or subject is None or ctx.effect_source != FIST:
        return
    row = _combat_row(ctx.engine, ctx.actor, "fist_adept")
    if row is None:
        return
    from . import needle, granted_movement
    from .. import typed_executor as te
    source = "insight.electric-fist-adept"
    if needle.ask(ctx.engine, ctx.intent,
                   needle.checkpoint_id(ctx.engine, "fist_adept_damage", subject.entity_id),
                   ctx.actor, needle.CHOICE + "fist_adept_damage", ["SHOCK"],
                   labels={"SHOCK": f"Deal {ctx.actor.proficiency_bonus} lightning damage"},
                   allow_decline=True, name="Electric Fist Adept", feature_id=source,
                   prompt=f"Electric Fist Adept: {subject.display_name} failed Electric Fist Method's save. "
                   f"Deal {ctx.actor.proficiency_bonus} lightning damage?", target_id=subject.entity_id):
        from dataclasses import replace
        te.run_effects(replace(ctx, target=subject, targets=[subject], effect_source=source),
                       [{"type":"damage", "formula":"pb", "damage_types":["lightning"], "applies_to":"target"}])
    used = "electric_fist_adept_round_scene_step"
    if ctx.actor.turn_flags.get(used):
        return
    routes = {needle.cell_id(c.destination): c for c in granted_movement.choices(ctx.engine, ctx.actor, 5)}
    if not routes:
        return
    chosen = needle.ask(ctx.engine, ctx.intent,
                        needle.checkpoint_id(ctx.engine, "fist_adept_step", subject.entity_id),
                        ctx.actor, needle.CHOICE + "fist_adept_step", list(routes),
                        labels={key:f"Move to ({c.destination.x}, {c.destination.y})" for key,c in routes.items()},
                        minimum=0, allow_decline=True, name="Electric Fist Adept", feature_id=source,
                        prompt="Electric Fist Adept: move 5 feet without provoking Opportunity Attacks? Once per scene.",
                        target_id=subject.entity_id)
    if chosen:
        ctx.actor.turn_flags[used] = True
        foes = [a.entity_id for a in ctx.engine.state.actors.values() if a.team_id != ctx.actor.team_id]
        granted_movement.move(ctx.engine, ctx.actor, routes[chosen[0]], ctx.intent, 5, foes,
                              name="Electric Fist Adept")
