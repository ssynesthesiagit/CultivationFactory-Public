"""Karma's source-hashed combat Insights (A2KARMASEC).

Debt Collector restores PB CP once per scene/fight on a three-Debt creature's
actual drop within 60 feet. Merciless Accountant optionally transfers an existing
Debt after a witnessed combat Cause, with its provenance and capacity preserved;
once until the owner's next turn. Narrative Causes remain table judgments, as
for Record the Deed. Borrowed Merit asks both donor and roller, preserves the
natural d20, adds one evented d4 to a failed DC/defense-aware native attack/check/save, and spends the
donor's Grace. Its round allowance belongs to the ledger, not each donor.
AI donations/transfers require perceived allies/enemies respectively.
Advancement ability increases are chosen in the character sheet.
Extension rolls without failure metadata remain an explicit reviewed rider.
Hooks: compile_block, event; shared post-rewrite bonus/consent registration.
"""
from . import hook, note
from .ability_source import compiled_feature_rows
from .karma_imprints import held, capacity, features, witnessed, spend, record_range
from .needle import CHOICE, ask, checkpoint_id, ai_controlled
from .choice_prompt import action_context
from ..targeting import line_of_effect

BLOCK = 'karma_insights'
COLLECT = 'insight.debt-collector'
TRANSFER = 'insight.merciless-accountant'
BORROW = 'insight.borrowed-merit'
COLLECT_USED = 'condition:typed.karma_debt_collector_used'
TRANSFER_USED = '_round_karma_accountant_turn'
BORROW_USED = '_round_karma_borrowed_merit'


def debt_collection_used(actor):
    """Pure scene-use query shared by Karma and the alphabetical Insight menu."""
    return any(c.condition_id == COLLECT_USED for c in actor.conditions.values())


@hook('compile_block')
def compile_rows(block, spec, row, numbers):
    if block != BLOCK:
        return None
    return [{**row, 'block': BLOCK, 'player_outcome': str(spec.get('player_outcome') or ''), 'cl': int(numbers.get('cl') or 1),
             'pb': int(numbers.get('pb') or 2), 'key_mod': int(numbers.get('key_mod') or 0)}]


def owned(engine, actor, feature):
    return tuple(r for r in compiled_feature_rows(engine, actor.entity_id, feature) if r.get('block') == BLOCK)


def sees(engine, observer, creature):
    from ..stealth import sees as visible
    return creature.entity_id == observer.entity_id or visible(engine, observer, creature)


@hook('event', nested=True, priority=-10)
def combat_insights(engine, event_type, kwargs):
    if event_type not in ('DAMAGE_COMMITTED', 'CONDITION_APPLIED'):
        return
    ids = kwargs.get('target_ids') or ()
    victim = engine.state.actors.get(ids[0]) if ids else None
    actor = engine.state.actors.get(kwargs.get('actor_id') or '')
    payload = kwargs.get('payload') or {}
    if victim is None:
        return
    if (event_type == 'DAMAGE_COMMITTED' and int(payload.get('hp_before') or 0) > 0
            and int(payload.get('hp_damage') or 0) > 0 and victim.current_hp == 0):
        from .d20_rewrite import pool_id
        for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
            rows = owned(engine, owner, COLLECT)
            if not owner.active or owner.current_hp <= 0 or not rows:
                continue
            if len(held(victim, owner.entity_id, 'debt')) < 3 or engine._distance_actor_to_actor(owner, victim) > 60:
                continue
            if debt_collection_used(owner):
                continue
            pool = pool_id(owner, 'cp')
            if pool is None:
                continue
            engine._apply_condition(owner, COLLECT_USED, COLLECT, owner.entity_id, expires_on='UNTIL_REMOVED',
                                    data={'label': 'Debt Collector used this scene'})
            engine._gain_resource(owner, pool, int(rows[0]['pb']), COLLECT)
            note(engine, COLLECT, owner, f'{owner.display_name} collects the fallen debtor: regains {rows[0]["pb"]} Cultivation Points.', (victim,))
    if actor is None or actor.entity_id == victim.entity_id:
        return
    if event_type == 'DAMAGE_COMMITTED':
        if int(payload.get('reduced_to') or 0) <= 0:
            return
        from .karma_riders import CHAIN_ID, TEN_ID, TRIAL_ID, WRIT_ID, BONE_ID, DEFERRED_ID
        from .karma_consumers import HARM
        origin = kwargs.get('originating_event')
        if str(getattr(origin, 'source_definition_id', '')) in (CHAIN_ID, TEN_ID, TRIAL_ID, WRIT_ID, BONE_ID, DEFERRED_ID, HARM, 'tianxia.talent.karma.return_the_sting'):
            return  # Consequence payments cannot manufacture a new Cause.
    else:
        from .karma_causes import inflicted_harm
        if not inflicted_harm(engine, payload, victim.entity_id):
            return
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if not owner.active or not owned(engine, owner, TRANSFER):
            continue
        automatic = ai_controlled(engine, owner)
        if automatic and owner.team_id == actor.team_id:
            continue
        if not held(actor, owner.entity_id, 'debt') or not witnessed(engine, owner, actor, victim, record_range(owner)) or not line_of_effect(engine, owner, target=actor):
            continue
        if owner.turn_flags.get(TRANSFER_USED) == owner.turns_started or len(held(actor, owner.entity_id)) >= capacity(owner, features(engine, owner)):
            continue
        eligible_donors = [a for a in engine.state.actors.values() if a.active and a.entity_id != actor.entity_id
                  and engine._distance_actor_to_actor(owner, a) <= 60
                  and held(a, owner.entity_id, 'debt') and sees(engine, owner, a) and line_of_effect(engine, owner, target=a)]
        # Automatic owners retain their enemy-only policy; manual owners see every rule-legal
        # debtor and may choose whom to help.
        donors = [a for a in eligible_donors if not automatic or a.team_id != owner.team_id]
        preferred = [a.entity_id for a in donors] if automatic else []
        origin = kwargs.get('originating_event')
        source_id = str(getattr(origin, 'source_definition_id', '') or
                        getattr(origin, 'source_id', '') or
                        getattr(engine, '_active_action_source_id', '') or '')
        source_actor = engine.state.actors.get(getattr(origin, 'actor_id', '') or '') or actor
        trigger_context = action_context(engine, source_actor, source_id, victim) if source_id else {}
        picked = ask(engine, None, checkpoint_id(engine, 'karma_accountant', owner.entity_id, actor.entity_id),
                     owner, CHOICE + 'karma_accountant', sorted(a.entity_id for a in donors),
                     labels={a.entity_id: a.display_name for a in donors}, allow_decline=True, target_id=actor.entity_id,
                     name='Merciless Accountant', feature_id=TRANSFER,
                     preferred=preferred, prompt_context=trigger_context,
                     prompt=f'Merciless Accountant: {actor.display_name} caused harm with {trigger_context.get("action_name") or "an action"}. Move one of your Debt Imprints from which creature to it? No action or point cost; once until your next turn.')
        if not picked:
            continue
        donor = engine.state.actors[picked[0]]
        key, imprint = held(donor, owner.entity_id, 'debt')[0]
        del donor.conditions[key]
        engine._append_event('CONDITION_REMOVED', TRANSFER, actor_id=owner.entity_id, target_ids=(donor.entity_id,),
                             payload={'condition_id': imprint.condition_id, 'instance_id': key, 'reason': 'IMPRINT_TRANSFERRED'})
        engine._apply_condition(actor, imprint.condition_id, imprint.source_definition_id, imprint.source_actor_id,
                                expires_on=imprint.expires_on, data=dict(imprint.data or {}))
        owner.turn_flags[TRANSFER_USED] = int(owner.turns_started)
        note(engine, TRANSFER, owner, f'{owner.display_name} moves a Debt Imprint from {donor.display_name} to {actor.display_name}.', (donor, actor))


def register_borrowed_merit():
    from .d20_rewrite import Holder, Rule, register

    def finder(engine):
        for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
            rows = owned(engine, owner, BORROW)
            if not owner.active or not rows:
                continue
            for donor in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
                if donor.active and held(donor, owner.entity_id, 'grace'):
                    yield Holder(donor, BORROW, {'ledger_owner': owner.entity_id}, f'{BORROW}:{owner.entity_id}', rows[0])

    def guard(engine, holder, rc):
        owner = engine.state.actors[holder.data['ledger_owner']]
        return (holder.actor.entity_id != rc.roller.entity_id
                and bool(held(rc.roller, owner.entity_id, 'grace'))
                and owner.turn_flags.get(BORROW_USED) != engine.state.round_number)

    def accept(engine, holder, rc):
        from .choice_prompt import action_context
        source_actor = rc.source_actor or rc.roller
        context = action_context(engine, source_actor, str(rc.source_id or ''), rc.roller)
        action_name = context.get('action_name') or 'an action'
        kind = {'attack': 'attack', 'save': 'saving throw', 'check': 'ability check'}.get(rc.kind, 'roll')
        return bool(ask(engine, None, f'karma_borrow_accept:{rc.roll.roll_id}:{holder.actor.entity_id}', rc.roller,
                        CHOICE + 'karma_borrow_accept', ['accept'], labels={'accept': 'Accept the donated Grace'},
                        allow_decline=True, target_id=rc.roller.entity_id, feature_id=BORROW, name='Borrowed Merit',
                        prompt_context=context,
                        prompt=f'Borrowed Merit: accept {holder.actor.display_name}\'s Grace Imprint to add 1d4 to your failed {kind} from {action_name}? Your donor spends that Grace Imprint. No action or point cost.'))

    def on_use(engine, holder, rc):
        from ..gate2_runtime_models import DiceSpec
        owner = engine.state.actors[holder.data['ledger_owner']]
        spend(engine, owner, holder.actor, 'grace', 1, BORROW)
        owner.turn_flags[BORROW_USED] = engine.state.round_number
        roll = engine.roller.roll(DiceSpec(count=1, sides=4), actor_id=holder.actor.entity_id, reason='BORROWED_MERIT')
        engine._record_roll(roll)
        holder.data['donated_bonus'] = int(roll.total)

    register(Rule('karma_borrowed_merit', 'Borrowed Merit (donate one Grace Imprint)',
                  rolls=('attack', 'check', 'save'), who='any', range_ft=30, when='failed', op='bonus', checkpoint='D20_ROLL_BONUS',
                  feature=BORROW, finder=finder, guard=guard, accept=accept, on_use=on_use,
                  bonus=lambda e, h, rc: int(h.data['donated_bonus']),
                  ai=lambda e, h, rc: h.actor.team_id == rc.roller.team_id and sees(e, h.actor, rc.roller)))


register_borrowed_merit()
