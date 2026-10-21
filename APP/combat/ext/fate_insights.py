"""Fate Insight map consumers; preparation inputs do not perform cultivation.

The sealed pre-fight form imports an UNEXPENDED result from the last completed
Full Cultivation Session. Recipient setup records that session's already chosen,
willing beneficiary. Neither setup nor reload rolls a preparation die. There is
no session/scene transition or cross-fight ledger in this app: these consumers
are partial lifecycle automation, and no in-combat action can renew a grant.
Mandate requires an explicit scene receipt; it never treats fight/round as scene.
"""
from copy import deepcopy

from . import hook
from .d20_rewrite import Holder, Rule, register
from .d20_rewrite_rules import gain
from .fate_riders import fate_die
from .passive_rows import row_of

COMPANION = 'insight.auspicious-companion'
DESTINY = 'insight.loaded-destiny'
GAMBLER = 'insight.gambler-s-instinct'
VOICE = 'insight.mandate-bearing-voice'
NAME = 'insight.name-sheltering-talisman'
OWNERS = {COMPANION, DESTINY, GAMBLER, VOICE, NAME}
BLOCK = 'fate_insights'
PREPARED = 'condition:typed.fate_insight_preparation'
WORDS = frozenset('TAL_FATE_' + name + '_WORD' for name in
                 ('BINDING', 'BLESSING', 'CURSE', 'EXECRATION', 'FREEDOM',
                  'HARM', 'OPEN_CLOSE', 'SOOTHE', 'VIOLENCE'))
RECOGNITION = frozenset('recognize:' + cause for cause in
                       ('cheating', 'manipulated_wagers', 'altered_lots', 'loaded_dice',
                        'cursed_games', 'supernatural_probability_influence'))
NAME_CAUSES = {'category:fate', 'category:curse', 'category:possession',
               'category:domination', 'category:name_targeting'}


@hook('compile_passives')
def ownership(rows, info):
    return [*rows, *({'block': BLOCK, 'feature_id': fid, 'kind': fid,
                     'cl': int(info['numbers']['cl']), 'choice_owner': 1}
                    for fid in sorted(OWNERS.intersection(info['owned_ids'])))]


def owns(engine, actor, feature):
    return actor is not None and row_of(engine, actor.entity_id, BLOCK, feature) is not None


@hook('compile_resources')
def notice_pool(info):
    if VOICE not in info['owned_ids']:
        return None
    from ..gate2_runtime_models import ResourceDefinition
    # The native named-pool adapter uses 99 for an unbounded printed maximum.
    # This plugin's reward is absent from executable effect evidence, so the
    # automatic textual pool discovery cannot see it. Seal the same native pool.
    return [ResourceDefinition(resource_id='resource:named.heaven_s_notice', initial=0, maximum=99)]


def settings(bundle):
    return (bundle.get('prefight') or {}).get('setup_choices') or {}


def input_value(bundle, key):
    values = settings(bundle).get(key) or [0]
    return values[0] if len(values) == 1 and type(values[0]) is int else 0


def declaration(key, label, help_text, maximum):
    return {'id': key, 'label': label, 'help': help_text, 'kind': 'integer_range_list',
            'count': 1, 'item_label': label, 'minimum': 0, 'maximum': maximum, 'default': [0]}


@hook('prefight_setup_choices')
def preparation_inputs(bundle):
    owned = {r.get('feature_id') for r in bundle.get('typed_passives') or [] if r.get('block') == BLOCK}
    out = []
    if DESTINY in owned:
        out.append(declaration('fate_destiny_recorded', 'Loaded Destiny: previously recorded d20',
            'Preparation input: enter the unspent d20 actually rolled at the end of your last Full Cultivation Session '
            '(1–20), or 0 for no unspent result. This does not perform a session or grant a new die. '
            'You may use it once on your own attack, check or save; no action or resource cost.', 20))
    for fid, key, title in ((COMPANION, 'fate_companion_prepared', 'Auspicious Companion'),
                            (NAME, 'fate_name_prepared', 'Name-Sheltering Talisman')):
        if fid in owned:
            out.append(declaration(key, title + ': earlier session preparation',
                'Preparation input: 1 confirms a still-valid preparation from your last completed Full Cultivation Session; '
                '0 means none. Setup records the willing beneficiary already chosen then. '
                'Do not import an expended or expired grant. This does not perform the rite or renew its benefit.', 1))
            out.append(declaration(key + '_beneficiary', title + ': previously chosen beneficiary',
                'Enter 1 for yourself, or 2 onward for the other combatants in alphabetical order by name '
                '(ties follow the fight roster order). '
                'This records the willing creature chosen during that same earlier session, not a new choice. '
                '0 leaves the declaration to manual fight setup; automatic owners must supply this fact before fighting.',
                2147483647))
    if VOICE in owned:
        out.append(declaration('fate_voice_scene', 'Mandate-Bearing Voice: current scene receipt',
            'Enter a positive scene number only if this Insight is unused in that actual scene; 0 leaves the optional '
            'save penalty unavailable. A fight does not start a new scene. Once in that scene, subtract your Fate Die '
            'from a successful save against your Word; no action or resource cost. Affecting natural 20 gains 1 Heaven’s Notice.', 2147483647))
    return out or None


def receipt(actor, feature):
    return next((c for c in actor.conditions.values() if c.condition_id == PREPARED
                 and c.source_definition_id == feature), None)


def record(engine, actor, feature, data):
    # Retain spent receipts, too: rerunning setup cannot reset a used input.
    if receipt(actor, feature) is None:
        engine._apply_condition(actor, PREPARED, feature, actor.entity_id,
                                expires_on='UNTIL_REMOVED', data=data)


@hook('match_start')
def import_recorded_inputs(engine):
    for bundle in getattr(engine, 'typed_bundle_documents', ()):
        actor = engine.state.actors.get(bundle['actor_id'])
        if owns(engine, actor, DESTINY):
            die = input_value(bundle, 'fate_destiny_recorded')
            if 1 <= die <= 20:
                record(engine, actor, DESTINY, {'die': die, 'spent': 0,
                    'label': f'Loaded Destiny: unspent recorded d20 {die}; from the last cultivation session'})
        if owns(engine, actor, VOICE):
            scene = input_value(bundle, 'fate_voice_scene')
            if scene > 0:
                record(engine, actor, VOICE, {'scene': scene, 'spent': 0,
                    'label': 'Mandate-Bearing Voice: unused in the admitted scene'})


@hook('fight_setup_tasks')
def recipient_inputs(engine):
    tasks = []
    for bundle in getattr(engine, 'typed_bundle_documents', ()):
        actor = engine.state.actors.get(bundle['actor_id'])
        if actor is None:
            continue
        for feature, key in ((COMPANION, 'fate_companion_prepared'), (NAME, 'fate_name_prepared')):
            if owns(engine, actor, feature) and input_value(bundle, key) == 1 and receipt(actor, feature) is None:
                tasks.append({'actor_id': actor.entity_id, 'source_id': feature})
    return tasks or None


@hook('fight_setup')
def record_recipient(engine, actor, source, intent):
    if source not in (COMPANION, NAME) or not owns(engine, actor, source):
        return None
    from .needle import ask, checkpoint_id
    title = 'Auspicious Companion' if source == COMPANION else 'Name-Sheltering Talisman'
    options = [a.entity_id for a in engine.state.actors.values() if a.active]
    key = 'fate_companion_prepared' if source == COMPANION else 'fate_name_prepared'
    bundle = next(b for b in engine.typed_bundle_documents if b['actor_id'] == actor.entity_id)
    declared = input_value(bundle, key + '_beneficiary')
    roster = [actor.entity_id, *(a.entity_id for a in sorted(
        (a for a in engine.state.actors.values() if a.entity_id != actor.entity_id),
        key=lambda a: a.display_name))]
    if declared:
        if not 1 <= declared <= len(roster) or roster[declared - 1] not in options:
            raise ValueError(title + ': the declared earlier beneficiary is not an active combatant.')
        picked = [roster[declared - 1]]
    else:
        from . import ai_controlled
        if ai_controlled(engine, actor):
            raise ValueError(title + ': declare the earlier session beneficiary in pre-fight setup before automatic play.')
        picked = ask(engine, intent, checkpoint_id(engine, 'fate_preparation', source), actor,
            'choice:needle.fate_preparation.' + source, options,
            labels={aid: engine.state.actors[aid].display_name for aid in options},
            preferred=[], automatic=False, default='decline', allow_decline=True, name=title, feature_id=source,
            prompt=title + ': record the willing beneficiary already chosen at the end of your last Full Cultivation '
                'Session. For Name-Sheltering Talisman, their name must already have been written, sealed or concealed. '
                'Pass if there is no valid unspent preparation. This input performs no session and grants no renewal.')
    recipient = engine.state.actors[picked[0]].display_name if picked else ''
    benefit = ('may add 1d8 to one failed attack roll, check or save' if source == COMPANION else
               'has Advantage on saves against Fate, curses, possession, domination and effects targeting their name')
    label = (f'{title}: {recipient} {benefit}, until the next Full Cultivation Session; no action or resource cost'
             if picked else title + ': no valid preparation recorded')
    record(engine, actor, source, {'beneficiary': picked[0] if picked else '', 'spent': int(not bool(picked)),
                                  'label': label})
    return True


def prepared_holders(engine, feature):
    for owner in engine.state.actors.values():
        held = receipt(owner, feature)
        if not owns(engine, owner, feature) or held is None or held.data.get('spent') != 0:
            continue
        bearer = engine.state.actors.get(held.data.get('beneficiary', owner.entity_id))
        if bearer is not None and bearer.active:
            yield Holder(bearer, feature, {'owner': owner.entity_id}, held.instance_id)


@hook('choice_reactors')
def beneficiary_choices(engine):
    # The recipient chooses, even when they own no reaction or Insight row.
    return [holder.actor.entity_id for holder in prepared_holders(engine, COMPANION)] or None


def spend(engine, holder, ctx):
    owner = engine.state.actors[holder.data.get('owner', holder.actor.entity_id)]
    held = receipt(owner, holder.feature_id)
    title = {DESTINY: 'Loaded Destiny', COMPANION: 'Auspicious Companion', VOICE: 'Mandate-Bearing Voice'}[holder.feature_id]
    engine._update_condition_data(owner, held, {**held.data, 'spent': 1, 'label': title + ': recorded use spent'}, holder.feature_id)


def die_bonus(engine, holder, ctx, sides):
    from ..gate2_runtime_models import DiceSpec
    roll = engine.roller.roll(DiceSpec(count=1, sides=sides, modifier=0),
                              actor_id=holder.actor.entity_id, reason=holder.feature_id)
    engine._record_roll(roll)
    return int(roll.total)


register(Rule('auspicious_companion', 'Auspicious Companion', rolls=('attack', 'check', 'save'),
    op='bonus', finder=lambda engine: prepared_holders(engine, COMPANION), when='failed',
    bonus=lambda engine, holder, ctx: die_bonus(engine, holder, ctx, 8), on_use=spend,
    checkpoint='D20_ROLL_BONUS', ai=lambda *_: True))


def stored_die(engine, holder, ctx):
    return int(receipt(holder.actor, DESTINY).data['die'])


register(Rule('loaded_destiny', 'Loaded Destiny', feature=DESTINY, rolls=('attack', 'check', 'save'),
    when='any', op='choose', choose=stored_die, on_use=spend,
    guard=lambda engine, holder, ctx: receipt(holder.actor, DESTINY) is not None
        and receipt(holder.actor, DESTINY).data.get('spent') == 0,
    ai=lambda engine, holder, ctx: ctx.succeeded() is False and stored_die(engine, holder, ctx) > ctx.natural,
    checkpoint='D20_REWRITE_ROLL'))


@hook('ability_check_hazard_mode')
def recognition(engine, actor, ability, skill, against, hazards):
    if owns(engine, actor, GAMBLER) and RECOGNITION.intersection(hazards):
        return 'ADVANTAGE'
    return None


@hook('save_mode')
def name_protection(engine, target, ability, dc, source, context):
    if not any(h.actor.entity_id == target.entity_id for h in prepared_holders(engine, NAME)):
        return None
    action = engine.action_catalog.get(source)
    typed = (action.parameters.get('typed') or {}) if action else {}
    if NAME_CAUSES.intersection((context or {}).get('named') or ()) or typed.get('sphere') == 'tianxia.sphere.fate':
        return 'ADVANTAGE'
    return None


@hook('save_roll_tags')
def prepared_save_tags(ctx, target, ability, named):
    if any(h.actor.entity_id == target.entity_id for h in prepared_holders(ctx.engine, NAME)):
        return sorted(named)
    return None


@hook('compile_action')
def word_range(action, info):
    typed = action.parameters.get('typed') or {}
    source = typed.get('source')
    if VOICE not in info['owned_ids'] or source not in WORDS or source not in info['owned_ids']:
        return None
    if action.range_ft is None:
        return None
    typed = deepcopy(typed)
    typed['mandate_word_owner'] = action.owner_id
    typed['range_ft'] = int(action.range_ft) + 30
    return action.model_copy(update={'range_ft': int(action.range_ft) + 30,
                                    'parameters': {**action.parameters, 'typed': typed}})


def mandate_guard(engine, holder, ctx):
    held = receipt(holder.actor, VOICE)
    action = engine.action_catalog.get(ctx.source_id)
    typed = (action.parameters.get('typed') or {}) if action else {}
    return held is not None and held.data.get('spent') == 0 and ctx.source_actor is holder.actor \
        and action is not None and action.owner_id == holder.actor.entity_id \
        and typed.get('source') in WORDS and typed.get('mandate_word_owner') == holder.actor.entity_id


def mandate_spend(engine, holder, ctx):
    spend(engine, holder, ctx)
    if ctx.natural == 20:
        gain(engine, holder, 'heaven_s_notice', 1)


register(Rule('mandate_bearing_voice', 'Mandate-Bearing Voice', feature=VOICE, rolls=('save',),
    who='any', when='succeeded', op='bonus', guard=mandate_guard, on_use=mandate_spend,
    bonus=lambda engine, holder, ctx: -die_bonus(engine, holder, ctx, fate_die(engine, holder.actor, holder.numbers['cl'])),
    ai=lambda *_: True, checkpoint='D20_ROLL_BONUS'))
