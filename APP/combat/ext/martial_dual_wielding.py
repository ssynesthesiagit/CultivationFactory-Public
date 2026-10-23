"""Dual Wielding sphere: the two talents keyed on "your Paired Strike hits a creature" (worker martial,
2026-09-28). Hua Muruo and Lianhui of the Flowing Grave own these.

combat/factory_compiler.py's own weapon-pairing code (HANDLED_IN_CODE: Greater Blades, Ambidexterity, Paired
Rhythm, Synchronous Accuracy, Following Strike, Tandem Offensive, Twin-Weapon Training) already tracks a Lead
and an Answering Weapon attack (typed["pair_role"] "lead"/"answer") and fires a "paired_strike" own_action event
when the Answering Weapon's attack hits (combat/typed_executor.py line ~590) -- that is the game's own "Paired
Strike" (the two attacks made together from a Qualifying Pair, as opposed to a single weapon's own attack).
"Paired Strike" is not a separately named ability anywhere in the authority (nothing to attach a reviewed_final
modifier to -- confirmed empty search), so Dancing Display and Dizzying Combination hook the same event point
their own engine code already uses: the ``attack_resolved`` plug-in hook, filtered to the Answering Weapon's
hit.

New auto94 packets use the current physical-grip query for Focusing Defense and
critical_hits' native Critical Follow-Up eligibility. Focusing Defense records, through the
strict state_event lifecycle seam and per live Dodging instance, whether the pair was readied at
that Dodge's trigger (so drawing a weapon after Dodging without it grants nothing, and ending one
Dodge never cancels another) and re-reads the pair live (so stowing it ends the increase and
drawing it again restores it). A save written before the record keeps the live-pair rule it was
played under. On-hit Pair choices use
transactional Needle transport. Dancing Display suppresses only Opportunity
Attacks against its owner; Dizzying Combination ties the one-minute walking
penalty to a repeat-save anchor. Old sealed markers keep their original path.
Dual Opportunity and replacement-Pair budget coordination remain partial.
Shared helper qualifying_pair serves critical_hits and this module's defenses.
"""

from __future__ import annotations

from typing import Any

from . import hook
from .qualifying_pairs import qualifying_pair

DANCING_DISPLAY = "TAL_DUAL_WIELDING_DANCING_DISPLAY"
DIZZYING_COMBINATION = "TAL_DUAL_WIELDING_DIZZYING_COMBINATION"
DEFENSIVE_WHIRL = "TAL_DUAL_WIELDING_DEFENSIVE_WHIRL"
FOCUS = "resource:core.martial_focus"

#: The on-hit Pair talents that share one "choose only one Pair talent" budget per Paired Strike.
PAIR_BLOCKS = ('dw_dancing_display', 'dw_dizzying_combination', 'dw_defensive_whirl')

#: The engine's own Dodging state, which Focusing Defense reads and records at its trigger.
DODGE_CONDITION = 'condition:core.dodge'

#: Focusing Defense's eligibility, recorded per live Dodging instance when that instance begins: one
#: '<instance_id>=<0 or 1>' entry per live Dodge, ';'-separated, in turn_flags. A string of integers,
#: so it survives a table commit and a cold reload, and one instance's ending never erases another's.
DODGE_PAIR_FLAG = 'dw_focusing_defense:pair_at_dodge'


@hook('recipient_allowed')
def following_recipient(engine, actor, target, action):
    """One Pair target rule for menus and recipient queries; compilation owns the flag."""
    if not action.parameters.get('following_strike') or action.owner_id != actor.entity_id:
        return None
    paired = actor.turn_flags.get('pair:paired_target')
    return target.entity_id != paired and bool(set(actor.turn_flags.get('pair:lead_targets') or [])
                                               - {paired, target.entity_id})


def _is_paired_strike_hit(ctx: Any, hit: bool) -> bool:
    return bool(hit) and ctx.typed.get("pair_role") == "answer"


def _owned(engine: Any, actor: Any, mechanic_id: str) -> bool:
    return any(row.get("mechanic_id") == mechanic_id or row.get("id") == mechanic_id
               for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


@hook("compile_block")
def compile_dw_markers(block: str, spec: dict[str, Any], row: dict[str, Any], numbers: dict[str, Any]):
    if block in ("dw_dancing_display", "dw_dizzying_combination", "dw_focusing_defense", "dw_defensive_whirl"):
        return [{**row, **({'auto94': 1, 'numbers': numbers} if spec.get('auto94') else {})}]
    return None


def _has_block(engine: Any, actor: Any, block: str) -> bool:
    return any(row.get("block") == block for row in (getattr(engine, "typed_passive_rows", {}) or {}).get(actor.entity_id, []))


@hook("attack_resolved")
def paired_strike_talents(ctx: Any, target: Any, hit: bool, effect: dict[str, Any]) -> None:
    if not _is_paired_strike_hit(ctx, hit) or not target.active:
        return
    handled = _new_pair(ctx, target)
    if 'dw_dancing_display' not in handled and _has_block(ctx.engine, ctx.actor, "dw_dancing_display"):
        from ..typed_executor import Context, run_effects

        inner = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, ctx.damage_cache)
        run_effects(inner, [{"type": "reaction_denied", "applies_to": "target", "duration": "until_end_of_turn",
                             "evidence": "Dancing Display: your movement does not provoke Opportunity Attacks from that creature "
                                         "for the rest of the current turn."}])
    if 'dw_dizzying_combination' not in handled and _has_block(ctx.engine, ctx.actor, "dw_dizzying_combination") and not ctx.actor.turn_flags.get("dizzying_combination_used"):
        ctx.actor.turn_flags["dizzying_combination_used"] = True
        from ..typed_executor import Context, run_effects

        # The printed 1-minute, repeat-save-to-end-early duration has no runtime hook for a numeric "speed_halved"
        # modifier (gate2_engine's repeat-save rerolling only reads a named condition's own data, not a plain
        # speed modifier -- see typed_executor.block_condition's "repeat_save" handling); approximated as a single
        # round (until the start of the wielder's next turn) instead, with a rider noting the simplification, so
        # the effect is never stronger than the printed 1-minute version.
        inner = Context(ctx.engine, ctx.actor, ctx.action, ctx.intent, ctx.typed, [target], target, ctx.damage_cache)
        run_effects(inner, [{"type": "save", "ability": "dex", "dc": "technique_save_dc", "applies_to": "target",
                             "on_fail": [{"type": "speed", "applies_to": "target", "halved": True, "duration": "until_start_of_next_turn",
                                         "evidence": "Each of the target's Speeds is halved (approximated as 1 round, not the printed "
                                                      "1 minute with a repeat save each turn -- no runtime hook re-rolls a plain speed "
                                                      "modifier's save each turn)."}],
                             "on_success": [], "evidence": "The target must make a Dexterity saving throw against your Cultivation Save DC."}])
    if 'dw_defensive_whirl' not in handled and _has_block(ctx.engine, ctx.actor, "dw_defensive_whirl"):
        _defensive_whirl(ctx.engine, ctx.actor, target, DEFENSIVE_WHIRL)


@hook('ac')
def focusing_defense(engine: Any, target: Any) -> int:
    """Focusing Defense's +2 AC, only for a Dodge that was taken while wielding the pair.

    "When you take the Dodge action while wielding a Qualifying Pair" (owner rules_text.json).
    "If you cease wielding a Qualifying Pair, you lose this increased bonus until you again
    satisfy the requirement." Both halves are state, not intent: the
    +2 needs the Dodge taken WITH the pair (recorded by :func:`focusing_defense_dodge_lifecycle`)
    and the pair still readied now, so stowing the weapon ends the increase and drawing it again
    during the same Dodge restores it. Reading the live pair alone let a character Dodge with a
    weapon stowed, then draw it and receive a bonus for a trigger they never met.

    A saved fight that predates the record has no answer to read. It keeps the rule it was played
    under -- the live pair alone -- rather than silently losing an increase it already had; the
    first Dodge taken afterwards is judged normally.
    """
    if not _owns_focusing_defense(engine, target.entity_id):
        return 0
    if not _dodge_instances(target):
        return 0
    judged = _recorded_dodge_judgement(target)
    if judged is False:
        return 0
    return 2 if qualifying_pair(engine, target) else 0


def _owns_focusing_defense(engine: Any, entity_id: str) -> bool:
    """Whether this creature's own compiled bundle carries the reviewed auto94 Focusing Defense row."""
    return any(row.get('block') == 'dw_focusing_defense' and row.get('auto94')
               for row in (getattr(engine, 'typed_passive_rows', {}) or {}).get(entity_id, []))


def _dodge_instances(actor: Any) -> list[str]:
    """The live Dodging instance ids, oldest first; each is a separate printed Dodging state."""
    live = [(c.applied_sequence, iid) for iid, c in actor.conditions.items()
            if c.condition_id == DODGE_CONDITION]
    return [iid for _, iid in sorted(live)]


def _parse_pair_record(record: Any) -> dict[str, bool] | None:
    """The per-instance record as {instance_id: eligible}; None for any older saved shape."""
    if not isinstance(record, str):
        return None
    rows: dict[str, bool] = {}
    for entry in record.split(';'):
        instance_id, _, flag = entry.rpartition('=')
        if instance_id:
            rows[instance_id] = flag == '1'
    return rows


def recorded_dodge_pairs(actor: Any) -> dict[str, bool]:
    """The saved record {Dodging instance id: was a Qualifying Pair readied as Dodging began}.

    Pure read of serialized fight state, for this module's own ``ac`` query and for reporting what
    a saved fight recorded. Empty when nothing is recorded, including a save written before the
    record existed; it judges nothing itself.
    """
    return _parse_pair_record(actor.turn_flags.get(DODGE_PAIR_FLAG)) or {}


def _recorded_dodge_judgement(actor: Any) -> bool | None:
    """Whether a live Dodge was judged eligible, or None when no answer was ever recorded.

    None means the save predates the record. The caller preserves its live-pair rule.
    An earlier actor-wide integer preserves its recorded answer until those Dodges end.
    """
    record = actor.turn_flags.get(DODGE_PAIR_FLAG)
    rows = _parse_pair_record(record)
    if rows is not None:
        return any(rows.get(instance_id, True) for instance_id in _dodge_instances(actor))
    return None if record is None else record == 1


def _write_pair_record(actor: Any, previous: Any, *, applied: str | None = None,
                       pair_readied: bool | None = None) -> str:
    """Rewrite the record from the live Dodging instances, keeping every other instance's answer.

    Instances that are no longer live are dropped, so ending one Dodge -- a different one from any
    still eligible -- cannot erase it. Previously unrecorded instances inherit their save's
    live-pair rule; the older actor-wide integer preserves its answer for existing instances.
    Only the newly applied instance is judged from current grips.
    """
    live = _dodge_instances(actor)
    rows = _parse_pair_record(previous)
    inherited = previous == 1 if isinstance(previous, int) else True
    rows = {instance_id: (rows or {}).get(instance_id, inherited) for instance_id in live}
    if applied is not None and applied in live and pair_readied is not None:
        rows[applied] = bool(pair_readied)
    return ';'.join(f'{instance_id}={int(rows[instance_id])}' for instance_id in live)


@hook('state_event')
def focusing_defense_dodge_lifecycle(engine: Any, event: Any) -> None:
    """Record, per live Dodging instance, whether a Qualifying Pair was readied as Dodging began.

    The printed rule is "While Dodging WITH a readied Qualifying Pair", so the trigger is judged
    once, when the engine's own Dodge condition lands, and stored in serialized fight state rather
    than re-derived from the pair's later state. A Dodge from the action and a Dodge granted by
    another feature alike put the creature in the printed Dodging state, so both are judged the
    same way; this is not keyed on the source, keeping the plug-in general. Inert for a creature
    without its own compiled row: nothing is written, and nothing already written is touched.
    Ending one instance drops only that instance's answer, so an overlapping Dodge keeps its own.
    This is the documented strict lifecycle seam, so Gate2, Gate3 and Gate4 all deliver it.
    """
    from .retained_updates import is_retained_update

    if event.event_type not in ('CONDITION_APPLIED', 'CONDITION_REMOVED'):
        return
    payload = event.payload or {}
    if payload.get('condition_id') != DODGE_CONDITION:
        return
    if is_retained_update(event.event_type, payload):
        return  # a replay-only upsert of an instance that was already judged
    for who in event.target_ids or ():
        actor = engine.state.actors.get(who)
        if actor is None or not _owns_focusing_defense(engine, who):
            continue
        if not _dodge_instances(actor):
            actor.turn_flags.pop(DODGE_PAIR_FLAG, None)
            continue
        previous = actor.turn_flags.get(DODGE_PAIR_FLAG)
        if event.event_type == 'CONDITION_APPLIED':
            actor.turn_flags[DODGE_PAIR_FLAG] = _write_pair_record(
                actor, previous, applied=payload.get('instance_id'),
                pair_readied=qualifying_pair(engine, actor))
        elif DODGE_PAIR_FLAG in actor.turn_flags:
            actor.turn_flags[DODGE_PAIR_FLAG] = _write_pair_record(actor, previous)


def _defensive_whirl(engine: Any, actor: Any, target: Any, source: str) -> bool:
    """Defensive Whirl: spend 1 Martial Focus, that creature attacks you with Disadvantage until the end of its next turn.

    Shared by the on-hit Pair choice and the sealed old path. The printed window ("until the end of that
    creature's next turn") is the holder's own turn end, which is the sealed END_OF_HOLDER_NEXT_TURN expiry
    combat/gate2_engine.py's checkpoint sweep removes; the modifier lives on the target and names the owner,
    so no other target is affected. Returns whether it was paid for.
    """
    if actor.resources.get(FOCUS, 0) < 1:
        return False
    engine._spend_resource(actor, FOCUS, 1, source)
    engine._add_modifier(target, source, 'attack_mode_vs', 'SET', f'DISADVANTAGE:{actor.entity_id}',
                         'END_OF_HOLDER_NEXT_TURN', expires_on='END_OF_HOLDER_NEXT_TURN')
    return True


def _new_pair(ctx: Any, target: Any) -> set[str]:
    """Choose one supported on-hit Pair; old sealed rows keep their original path."""
    rows = [r for r in getattr(ctx.engine, 'typed_passive_rows', {}).get(ctx.actor.entity_id, [])
            if r.get('auto94') and r.get('block') in PAIR_BLOCKS]
    if not rows:
        return set()
    kinds = {r['block'] for r in rows}
    if (ctx.engine.state.current_actor_id != ctx.actor.entity_id or ctx.typed.get('opportunity_of')
            or ctx.typed.get('reaction_attack')):
        return kinds
    used = [v for v in str(ctx.actor.turn_flags.get('auto94_pair_used') or '').split(',') if v]
    maximum = 2 if ctx.action.source_definition_id.endswith('#offhand_synchronous') else 1
    if len(used) >= maximum or not qualifying_pair(ctx.engine, ctx.actor):
        return kinds
    options = [r['block'] for r in rows if r['block'] not in used]
    if ctx.actor.resources.get(FOCUS, 0) < 1:  # a talent whose printed cost cannot be paid is not offered
        options = [block for block in options if block != 'dw_defensive_whirl']
    if not options:
        return kinds
    from .needle import ask, checkpoint_id
    from dataclasses import replace
    from ..typed_executor import run_effects
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'DUAL_PAIR', target.entity_id, str(len(used))),
        ctx.actor, 'choice:needle.dual_pair', options,
        labels={'dw_dancing_display': 'Dancing Display: this creature cannot make Opportunity Attacks against you this turn',
                'dw_dizzying_combination': 'Dizzying Combination: Dexterity save or halve walking Speed for 1 minute; repeat each turn',
                'dw_defensive_whirl': 'Defensive Whirl: spend 1 Martial Focus; this creature has Disadvantage on its attack rolls against you until the end of its next turn'},
        allow_decline=True, target_id=target.entity_id, name='Paired Strike',
        prompt=f'{ctx.action.display_name} hits {target.display_name}: choose one Pair talent, or decline. '
               f'Choosing a talent costs no extra action, but you still pay whatever that talent itself costs '
               f'(Defensive Whirl spends 1 Martial Focus).')
    if not picked:
        return kinds
    chosen = picked[0]
    ctx.actor.turn_flags['auto94_pair_used'] = ','.join([*used, chosen])
    row = next(r for r in rows if r['block'] == chosen)
    source = row['feature_id']
    from .needle import save_dc
    inner = replace(ctx, typed={**ctx.typed, 'source': source,
                    'numbers': {**row['numbers'], 'save_dc': save_dc(ctx.engine, ctx.actor)}}, targets=[target], target=target)
    if chosen == 'dw_dancing_display':
        ctx.engine._apply_condition(target, 'condition:typed.no_opportunity_attacks', source, ctx.actor.entity_id,
            expires_on='END_OF_CURRENT_TURN', data={'against': ctx.actor.entity_id,
            'label': f'Dancing Display: no Opportunity Attacks against {ctx.actor.display_name} this turn'})
    elif chosen == 'dw_defensive_whirl':
        _defensive_whirl(ctx.engine, ctx.actor, target, source)
    else:
        run_effects(inner, [{'type': 'save', 'ability': 'dex', 'applies_to': 'target', 'dc': 'technique_save_dc',
            'on_fail': [{'type': 'rider_repeat_group', 'name': 'Dizzying Combination', 'duration': 'one_minute',
                'effects': [{'type': 'condition', 'condition': 'dizzying_combination', 'applies_to': 'target',
                    'duration': 'one_minute', 'repeat_save': {'ability': 'DEX'},
                    'condition_data': {'label': 'Dizzying Combination: walking Speed halved; repeat Dexterity save each turn'}},
                    {'type': 'speed', 'applies_to': 'target', 'halved': True, 'duration': 'one_minute'}]}],
            'on_success': []}])
    return kinds
