"""Oath-Ledger's source-scoped records on the public fact/consent contracts.

The table owner describes external meaning; controllers accept their own terms.
Mechanical performance is matched against committed native intents, never names,
team membership or an effects-array assertion. Records, marks and deduplication
are evented conditions so reconstruction uses the ordinary journal reducer.
"""
from __future__ import annotations

import json
from dataclasses import replace
from typing import Literal

from pydantic import Field, StrictInt, StrictStr, model_validator
from . import effect, hook, note
from .needle import ask, checkpoint_id, timed_condition
from .condition_ownership import remove_instance
from ..models import StrictModel
from ..table_facts import PredictedAction, action_matches, observable, records
from ..fact_consent_admission import admit_choice, canonical
from ..typed_reactions import spend_reaction

PREFIX = 'tianxia.subpath.qi.oath_ledger_cultivator.feature.'
LEVELS = {'record_the_promise': 3, 'invoke_the_clause': 6, 'battlefield_covenant': 10,
          'oathkeeper_s_record': 14, 'heaven_as_witness': 18}
ROWS = {PREFIX + name: level for name, level in LEVELS.items()}
RECORD = 'condition:typed.oath_ledger_record'
MARK = 'condition:typed.oath_ledger_mark'
QI = 'resource:core.qi'
FACT_KEY = 'oath_ledger'


class Obligation(StrictModel):
    """The seven printed fields, plus concrete known performance definitions.

    External meaning is supplied through a GM-owned table fact. Merely authoring
    this document neither binds a participant nor creates a mark or reward.
    """
    obligation_id: StrictStr = Field(min_length=1)
    parties: tuple[StrictStr, ...]
    beneficiaries: tuple[StrictStr, ...]
    term: StrictStr = Field(min_length=1)
    duration: StrictStr = Field(min_length=1)
    acceptance: StrictStr = Field(min_length=1)
    fulfillment: StrictStr = Field(min_length=1)
    breach: StrictStr = Field(min_length=1)
    release: StrictStr = Field(min_length=1)
    duration_seconds: StrictInt = Field(ge=1)
    comprehensible: Literal[1]
    possible: Literal[1]
    meaningful: Literal[1]
    self_manufactured: Literal[0]
    fulfilled_by: tuple[PredictedAction, ...] = ()
    breached_by: tuple[PredictedAction, ...] = ()
    release_by: tuple[PredictedAction, ...] = ()
    fulfillment_releases: tuple[StrictStr, ...] = ()
    governed_source_ids: tuple[StrictStr, ...] = ()
    governed_item_ids: tuple[StrictStr, ...] = ()
    required_position: dict[str, StrictInt] | None = None

    @model_validator(mode='after')
    def concrete_parties(self):
        if not self.parties or not self.beneficiaries or len(set(self.parties)) != len(self.parties):
            raise ValueError('Name distinct bound parties and at least one beneficiary.')
        for prediction in (*self.fulfilled_by, *self.breached_by, *self.release_by):
            if prediction.actor_id not in self.parties or prediction.actor_id not in prediction.aware_actor_ids:
                raise ValueError('Performance must name a bound party who knows the exact term.')
        for value in (self.term, self.duration, self.acceptance, self.fulfillment, self.breach, self.release):
            if not value.strip():
                raise ValueError('Every obligation field needs a clear, discoverable term.')
        if self.required_position is not None:
            from ..gate2_runtime_models import Position
            Position.model_validate(self.required_position)
        return self


@hook('feature_access_policy')
def access(feature_id):
    if feature_id in ROWS:
        return {'path': 'tianxia.path.qi_cultivation', 'minimum_cl': ROWS[feature_id],
                'classification': 'Restricted Scripture',
                'source_kinds': ['scripture', 'teacher', 'campaign_permission']}


@hook('compile_passives')
def ownership(rows, info):
    return [*rows, *({'block': 'oath_ledger', 'feature_id': fid, 'numbers': info['numbers']}
                    for fid in ROWS if fid in info['owned_ids'])]


def owned(engine, actor, leaf):
    return next((r for r in getattr(engine, 'typed_passive_rows', {}).get(actor.entity_id, ())
                 if r.get('block') == 'oath_ledger' and r['feature_id'] == PREFIX + leaf), None)


def ledger(engine, owner):
    return [(c, json.loads(c.data['document'])) for c in owner.conditions.values() if c.condition_id == RECORD]


def marks(subject, owner, *, kind=None, obligation=None):
    return [c for c in subject.conditions.values() if c.condition_id == MARK
            and c.source_actor_id == owner.entity_id and (kind is None or c.data['kind'] == kind)
            and (obligation is None or c.data['obligation'] == obligation)]


def source_documents(engine, owner):
    """Current, observed and source-validated proposals; no acceptance inferred."""
    out = {}
    for key, fact in records(engine, owner).items():
        answer = fact.answers.get(FACT_KEY)
        if answer is None or answer.category != 'witnessed_obligation' or not observable(engine, owner, fact, 60):
            continue
        document = Obligation.model_validate_json(answer.fact)
        if not set((*document.parties, *document.beneficiaries)) <= engine.state.actors.keys():
            continue
        out[key] = (fact, document)
    return out


@hook('table_fact_validate')
def validate_fact(engine, fact):
    answer = fact.answers.get(FACT_KEY)
    if answer is None:
        return
    if answer.category != 'witnessed_obligation':
        raise ValueError('Oath-Ledger facts must describe a witnessed obligation.')
    doc = Obligation.model_validate_json(answer.fact)
    if not set((*doc.parties, *doc.beneficiaries)) <= engine.state.actors.keys():
        raise ValueError('Name actual parties and beneficiaries in this scene.')
    # Every mechanical branch passes the same native action validation as the
    # shared prediction contract; embedding it as text cannot evade validation.
    from ..table_facts import validate
    predictions = (*doc.fulfilled_by, *doc.breached_by, *doc.release_by)
    shadow = fact.model_copy(update={'answers': {'mechanical_branches': answer.model_copy(
        update={'predictions': predictions})}})
    validate(engine, shadow)


@hook('compile_actions')
def actions(info):
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    out = []
    for leaf, operation, label in [('record_the_promise', 'record', 'Witness Acceptance: record a promise (Reaction, 1 Qi)'),
                                  ('record_the_promise', 'spend', 'Spend an Oath Mark (once per turn)')]:
        if PREFIX + leaf not in info['owned_ids']:
            continue
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.oath_ledger.{operation}",
            owner_id=info['actor_id'], display_name=label, economy=EconomyKind.NONE,
            resolution_kind='TYPED', target_kind='SELF', parameters={'setting_only': True, 'expected_damage': 0,
                'typed': {'source': PREFIX + leaf, 'numbers': info['numbers'],
                          'effects': [{'type': 'oath_ledger_command', 'operation': operation}],
                          'duration': {'kind': 'instant'}, 'riders': []}}))
    return out


@hook('candidate_allowed')
def candidates(engine, actor, candidate, action):
    if action is None:
        return None
    typed = action.parameters.get('typed') or {}
    command = next((r for r in typed.get('effects', ()) if r.get('type') == 'oath_ledger_command'), None)
    if command is None:
        return None
    if not owned(engine, actor, 'record_the_promise'):
        return False
    if command['operation'] == 'record':
        recorded = {d['obligation_id'] for _, d in ledger(engine, actor)}
        return actor.reaction_available and actor.resources.get(QI, 0) >= 1 and any(
            d.obligation_id not in recorded for _, d in source_documents(engine, actor).values())
    return any(marks(a, actor) for a in engine.state.actors.values()) and not spent_this_turn(engine, actor)


def choose(ctx, chooser, key, options, labels, prompt, *, optional=False, automatic=()):
    if not options:
        return None
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'OATH_LEDGER', ctx.source, key, chooser.entity_id),
        chooser, 'choice:needle.oath_ledger.' + key, list(options), labels=labels,
        minimum=0 if optional else 1, maximum=1, allow_decline=optional,
        automatic_options=list(automatic), preferred=list(automatic),
        feature_id=ctx.typed.get('source'), name='Oath-Ledger', prompt=prompt)
    return picked[0] if picked else None


def consent(ctx, subject, document):
    return admit_choice(ctx, subject, PREFIX + 'record_the_promise', 'obligation_acceptance',
        document.obligation_id, ['accept'], labels={'accept': 'Accept: ' + document.term},
        prompt=f'Oath-Ledger: {subject.display_name}, accept this obligation? {document.term} '
               f'It lasts {document.duration}. Release: {document.release}. Acceptance costs no action or Qi.',
        expires_on='UNTIL_REMOVED', readers=[ctx.actor.entity_id], automatic_options=['accept'])


def record_promise(ctx):
    proposals = source_documents(ctx.engine, ctx.actor)
    existing = {d['obligation_id'] for _, d in ledger(ctx.engine, ctx.actor)}
    proposals = {k: v for k, v in proposals.items() if v[1].obligation_id not in existing}
    key = choose(ctx, ctx.actor, 'proposal', proposals, {k: d.term for k, (_, d) in proposals.items()},
        'Witness Acceptance: choose the perceived obligation to record for up to 8 hours. Costs your Reaction and 1 Qi.')
    if key is None:
        return
    fact, document = proposals[key]
    if not ctx.actor.reaction_available or ctx.actor.resources.get(QI, 0) < 1:
        raise ValueError('Witness Acceptance needs your Reaction and 1 Qi.')
    for party in document.parties:
        if consent(ctx, ctx.engine.state.actors[party], document) is None:
            return
    ctx.engine._spend_resource(ctx.actor, QI, 1, ctx.source)
    spend_reaction(ctx.engine, ctx.actor, {'feature_id': ctx.typed['source']})
    save_record(ctx, document, seconds=min(28800, document.duration_seconds), origin=fact.record_id)


def save_record(ctx, document, *, seconds, origin):
    data = document.model_dump(mode='json')
    data.update({'created_round': ctx.engine.state.round_number, 'deadline_round': ctx.engine.state.round_number + (seconds + 5) // 6,
                 'origin': origin, 'seen': [], 'resolved': 0})
    ctx.engine._apply_condition(ctx.actor, RECORD, ctx.source, ctx.actor.entity_id, expires_on='UNTIL_REMOVED', data=
        {'document': canonical(data), 'label': 'Recorded obligation: ' + document.term})


def update_record(engine, owner, condition, doc):
    engine._update_condition_data(owner, condition, {**condition.data, 'document': canonical(doc)}, condition.source_definition_id)


def end_record(engine, owner, condition, doc):
    for subject in engine.state.actors.values():
        for mark in marks(subject, owner, obligation=doc['obligation_id']):
            remove_instance(engine, subject, mark.instance_id, condition.source_definition_id)
    remove_instance(engine, owner, condition.instance_id, condition.source_definition_id)


def add_mark(ctx, subject, doc, kind, *, count=1):
    maximum = int(ctx.numbers.get('pb') or 2)
    count = min(count, maximum - len(marks(subject, ctx.actor)))
    for _ in range(max(0, count)):
        ctx.engine._apply_condition(subject, MARK, ctx.source, ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
            data={'obligation': doc['obligation_id'], 'kind': kind, 'label': kind.title() + ' Mark: ' + doc['term']})


def context_for(engine, owner, intent):
    from ..typed_executor import Context
    action = next((a for a in engine.action_catalog.values() if a.owner_id == owner.entity_id
                   and any(r.get('type') == 'oath_ledger_command' for r in (a.parameters.get('typed') or {}).get('effects', ()))), None)
    if action is None:
        return None
    return Context(engine, owner, action, intent, action.parameters['typed'], [])


@hook('intent_resolved')
def conduct(engine, actor, candidate, intent, start_sequence):
    """Exact accepted native completion is the mechanical performance producer."""
    for owner in engine.state.actors.values():
        if not owned(engine, owner, 'record_the_promise'):
            continue
        ctx = context_for(engine, owner, intent)
        if ctx is None:
            continue
        for condition, doc in list(ledger(engine, owner)):
            if actor.entity_id not in doc['parties']:
                continue
            receipt = intent.intent_id
            if receipt in doc['seen']:
                continue
            match = None
            for field, kind in [('release_by', 'release'), ('breached_by', 'breach'), ('fulfilled_by', 'fulfillment')]:
                if any(action_matches(engine, PredictedAction.model_validate(p), actor, candidate, intent, start_sequence)
                       for p in doc[field]):
                    match = kind
                    break
            if match is None:
                continue
            if match == 'release':
                end_record(engine, owner, condition, doc)
                continue
            from ..target_knowledge import can_see
            if (engine._distance_actor_to_actor(owner, actor) > 60 or not can_see(engine, owner, actor)
                    or not owner.reaction_available or observed_round(engine, owner)):
                continue
            pick = choose(ctx, owner, 'witness_' + doc['obligation_id'], ['record'],
                {'record': 'Record ' + match + ' by ' + actor.display_name},
                f'Record the Promise: {actor.display_name} has completed {candidate.display_name}, '
                f'which matches “{doc[match]}”. Spend your Reaction to place one {match.title()} Mark (once per round)?',
                optional=True, automatic=['record'])
            if pick is None:
                continue
            spend_reaction(engine, owner, {'feature_id': PREFIX + 'record_the_promise'})
            timed_condition(engine, owner, 'condition:typed.oath_ledger_witness_round', ctx.source,
                owner.entity_id, 'UNTIL_REMOVED', {'round': engine.state.round_number})
            add_mark(ctx, actor, doc, match)
            doc['seen'].append(receipt)
            update_record(engine, owner, condition, doc)


def observed_round(engine, owner):
    return any(c.condition_id == 'condition:typed.oath_ledger_witness_round' and c.data['round'] == engine.state.round_number
               for c in owner.conditions.values())


def spent_this_turn(engine, owner):
    return any(c.condition_id == 'condition:typed.oath_ledger_spent' for c in owner.conditions.values())


@hook('turn_start')
def expire_records(engine, actor):
    for owner in engine.state.actors.values():
        for condition, doc in list(ledger(engine, owner)):
            if doc['deadline_round'] <= engine.state.round_number:
                end_record(engine, owner, condition, doc)


def move_grant(ctx, subject, feet):
    from .granted_movement import choices, move
    choices_by_id = {c.candidate_id: c for c in choices(ctx.engine, subject, feet)}
    selected = choose(ctx, subject, 'passage', choices_by_id,
        {key: c.display_name for key, c in choices_by_id.items()},
        f'Oath-Ledger: {subject.display_name} may move up to {feet} feet without provoking Opportunity Attacks. No action or Qi cost.',
        optional=True)
    if selected:
        move(ctx.engine, subject, choices_by_id[selected], ctx.intent, feet, list(ctx.engine.state.actors), name='Oath-Ledger passage')


def relief(ctx, subject, doc, names):
    from .qi_subpaths_1 import relief_options
    from .end_effect import remove_instance as end_instance
    options = relief_options(ctx, subject, {'conditions': names})
    options = [(key, c) for key, c in options if c.source_definition_id in doc['fulfillment_releases']]
    chosen = choose(ctx, ctx.actor, 'relief', [k for k, _ in options],
        {k: c.data.get('label', 'Condition expressly released by this obligation') for k, c in options},
        f'Oath-Ledger: end one permitted effect on {subject.display_name} that this fulfillment expressly releases.')
    for key, c in options:
        if chosen == key:
            end_instance(ctx, subject, 'condition', key, c)


FULFILLMENT = {'move': 'Move 10 feet without provoking', 'temp_hp': 'Gain temporary Hit Points equal to twice Proficiency Bonus',
              'relief': 'End an eligible charm or fear expressly released by fulfillment'}


def spend(ctx):
    if spent_this_turn(ctx.engine, ctx.actor):
        return
    available = {}
    documents = {d['obligation_id']: d for _, d in ledger(ctx.engine, ctx.actor)}
    for actor in ctx.engine.state.actors.values():
        for mark in marks(actor, ctx.actor, kind='fulfillment'):
            if mark.data['obligation'] in documents:
                available[mark.instance_id] = (actor, mark, documents[mark.data['obligation']])
    selected = choose(ctx, ctx.actor, 'mark', available,
        {key: a.display_name + ': ' + d['term'] for key, (a, _, d) in available.items()},
        'Spend a Fulfillment Mark: choose a willing creature and its recorded obligation. Once per turn; costs one Mark, no Qi.')
    if selected is None:
        return
    subject, mark, doc = available[selected]
    accepted = admit_choice(ctx, subject, PREFIX + 'record_the_promise', 'fulfillment_reward', doc['obligation_id'],
        ['accept'], labels={'accept': 'Accept this Fulfillment Mark reward'},
        prompt=f'Oath-Ledger: {subject.display_name}, accept the reward for “{doc["term"]}”? No action or Qi cost.',
        expires_on='END_OF_CURRENT_TURN', readers=[ctx.actor.entity_id], automatic_options=['accept'])
    if not accepted:
        return
    option = choose(ctx, ctx.actor, 'reward', FULFILLMENT, FULFILLMENT,
        f'Oath-Ledger: choose the benefit for {subject.display_name}. Spend one Fulfillment Mark; no Qi.')
    if option is None:
        return
    remove_instance(ctx.engine, subject, mark.instance_id, ctx.source)
    timed_condition(ctx.engine, ctx.actor, 'condition:typed.oath_ledger_spent', ctx.source, ctx.actor.entity_id,
                    'END_OF_CURRENT_TURN', {'label': 'Oath Mark already spent this turn'})
    if option == 'move':
        move_grant(ctx, subject, 10)
    elif option == 'temp_hp':
        ctx.engine._grant_temp_hp(subject, 2 * int(ctx.numbers.get('pb') or 2), ctx.source, ctx.actor.entity_id)
    elif option == 'relief':
        relief(ctx, subject, doc, ['charmed', 'frightened'])
    invoke(ctx, subject, doc, 'fulfillment')


@effect('oath_ledger_command')
def command(ctx, row):
    if not owned(ctx.engine, ctx.actor, 'record_the_promise'):
        return
    if row['operation'] == 'record':
        record_promise(ctx)
    elif row['operation'] == 'spend':
        spend(ctx)


@hook('terminal_result')
def scene_ends(engine, *args):
    for actor in engine.state.actors.values():
        for condition, doc in list(ledger(engine, actor)):
            end_record(engine, actor, condition, doc)
        for held in list(actor.conditions.values()):
            if held.source_definition_id.startswith(PREFIX) and held.condition_id in {
                    'condition:typed.fact_consent_admission', 'condition:typed.oath_ledger_witness_round'}:
                remove_instance(engine, actor, held.instance_id, held.source_definition_id)


def applied_effect(ctx, subject, row):
    from ..typed_executor import run_effects
    run_effects(replace(ctx, target=subject, targets=[subject]), [{**row, 'applies_to': 'target'}])


def invoke(ctx, subject, doc, kind):
    if not owned(ctx.engine, ctx.actor, 'invoke_the_clause') or any(
            c.condition_id == 'condition:typed.oath_ledger_invoked' for c in subject.conditions.values()):
        return
    if kind == 'fulfillment':
        options = {'heal': 'Honored Performance: regain 2d8 + key modifier Hit Points',
            'temp': 'Honored Performance: gain 2d8 + key modifier temporary Hit Points',
            'passage': 'Granted Passage: move 15 feet without provoking',
            'authority': 'Witnessed Authority: Advantage on the next qualifying Charisma, Wisdom or Cultivation Check',
            'release': 'Released Burden: end an eligible condition expressly released by the obligation'}
    else:
        count = 2 + int(int(ctx.numbers.get('cl') or 1) >= 11) + int(int(ctx.numbers.get('cl') or 1) >= 17)
        options = {'pain': f'Pain of Perjury: deal {count}d8 Psychic or Force damage',
            'return': 'Return to the Boundary: push or pull up to 10 feet toward the required position',
            'hand': 'Stay the Violating Hand: prevent an implicated held object or Domain Armament function from being activated or moved until your next turn',
            'forfeit': 'Forfeit the Moment: a nearby beneficiary moves 10 feet or gains twice Proficiency Bonus temporary Hit Points',
            'speak': 'Speak the Clause: reveal understanding, the recorded breach test and disguised responsibility'}
    selected = choose(ctx, ctx.actor, 'invoke', options, options,
        f'Invoke the Clause: choose an additional {kind} effect for {subject.display_name}, '
        f'appropriate to “{doc["term"]}”. No additional Mark or Qi cost. One effect per creature per turn.', optional=True)
    if selected is None:
        return
    timed_condition(ctx.engine, subject, 'condition:typed.oath_ledger_invoked', ctx.source,
        ctx.actor.entity_id, 'END_OF_CURRENT_TURN', {'label': 'Invoke the Clause received this turn'})
    if selected in ('heal', 'temp'):
        applied_effect(ctx, subject, {'type': 'healing' if selected == 'heal' else 'temp_hp',
            'dice': {'count': 2, 'sides': 8}, 'formula': 'key_ability_modifier'})
    elif selected == 'passage':
        move_grant(ctx, subject, 15)
    elif selected == 'authority':
        ctx.engine._apply_condition(subject, 'condition:typed.oath_ledger_authority', ctx.source,
            ctx.actor.entity_id, expires_on='UNTIL_REMOVED',
            data={'obligation': doc['obligation_id'], 'label': 'Witnessed Authority: next qualifying check has Advantage'})
    elif selected == 'release':
        relief(ctx, subject, doc, ['restrained', 'charmed', 'frightened', 'oath'])
    elif selected == 'pain':
        damage = choose(ctx, ctx.actor, 'pain_type', ['psychic', 'force'],
            {'psychic': 'Psychic damage', 'force': 'Force damage'}, 'Pain of Perjury: choose the damage type.')
        applied_effect(ctx, subject, {'type': 'damage', 'dice': {'count': count, 'sides': 8}, 'damage_types': [damage]})
    elif selected == 'return':
        return_movement(ctx, subject, doc, 10)
    elif selected == 'hand':
        functions = list(doc['governed_source_ids'])
        selected_function = choose(ctx, ctx.actor, 'violating_function', functions,
            {key: getattr(ctx.engine.action_catalog.get(key), 'display_name', 'Named function governed by the obligation') for key in functions},
            f'Stay the Violating Hand: choose the exact object or Domain Armament function used by {subject.display_name} for this breach.')
        if selected_function:
            ctx.engine._apply_condition(subject, 'condition:typed.oath_ledger_function_lock', ctx.source,
                ctx.actor.entity_id, expires_on='START_OF_SOURCE_NEXT_TURN',
                data={'function': selected_function, 'obligation': doc['obligation_id'],
                      'label': 'Stay the Violating Hand: implicated function cannot activate'})
    elif selected == 'forfeit':
        recipients = {aid: ctx.engine.state.actors[aid] for aid in doc['beneficiaries']
                      if ctx.engine._distance_actor_to_actor(ctx.actor, ctx.engine.state.actors[aid]) <= 30}
        target = choose(ctx, ctx.actor, 'beneficiary', recipients,
            {aid: a.display_name for aid, a in recipients.items()}, 'Forfeit the Moment: choose one beneficiary within 30 feet.')
        if target:
            benefit = choose(ctx, ctx.actor, 'forfeit_benefit', ['move', 'temp'],
                {'move': 'Move 10 feet without provoking', 'temp': 'Gain twice Proficiency Bonus temporary Hit Points'},
                'Forfeit the Moment: choose the beneficiary’s benefit.')
            if benefit == 'move':
                move_grant(ctx, recipients[target], 10)
            elif benefit == 'temp':
                ctx.engine._grant_temp_hp(recipients[target], 2 * int(ctx.numbers.get('pb') or 2), ctx.source, ctx.actor.entity_id)
    elif selected == 'speak':
        note(ctx.engine, ctx.source, ctx.actor,
            f'Speak the Clause: {subject.display_name} understood and accepted “{doc["term"]}”. '
            f'The witnessed act matched the recorded breach: {doc["breach"]}. '
            'This record establishes the obligation’s operation; it does not reveal private thoughts.', targets=(ctx.actor,))


def return_movement(ctx, subject, doc, feet):
    """Legal forced paths toward the recorded required position, including stay."""
    from .granted_movement import choices
    from ..gate2_runtime_models import Position
    point = doc.get('required_position')
    if point is None:
        return
    destination = Position.model_validate(point)
    old = ctx.engine.grid.distance_ft(subject.position, destination)
    paths = {c.candidate_id: c for c in choices(ctx.engine, subject, feet)
             if ctx.engine.grid.distance_ft(c.destination, destination) < old}
    selected = choose(ctx, ctx.actor, 'return_path', paths, {key: c.display_name for key, c in paths.items()},
        f'Return to the Boundary: move {subject.display_name} up to {feet} feet toward the obligation’s required position.', optional=True)
    if selected:
        # Native forced movement preserves collision, sealed boundaries and
        # movement prevention. Each chosen route endpoint is already validated.
        from ..forced_movement import move
        move(ctx, subject, paths[selected].destination)


@hook('candidate_allowed')
def function_lock(engine, actor, candidate, action):
    if any(c.condition_id == 'condition:typed.oath_ledger_function_lock'
           and c.data['function'] == candidate.source_definition_id for c in actor.conditions.values()):
        return False


@hook('presentation_hidden_conditions')
def hide_private_consent(engine, actor):
    return [c.instance_id for c in actor.conditions.values() if c.condition_id == 'condition:typed.fact_consent_admission'
            and c.source_definition_id.startswith(PREFIX)]


@hook('d20_bonus')
def roll_mark(engine, roll, intent):
    """After rolling, before resolution: at most one Oath Mark on this roll."""
    if intent is None:
        return
    context = engine.d20_context(roll)
    subject = engine.state.actors.get(roll.actor_id)
    if subject is None or context is None or context['kind'] not in {'attack', 'save', 'check'}:
        return
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if not owned(engine, owner, 'record_the_promise') or spent_this_turn(engine, owner):
            continue
        ctx = context_for(engine, owner, intent)
        if ctx is None:
            continue
        docs = {d['obligation_id']: d for _, d in ledger(engine, owner)}
        available = {}
        for mark in marks(subject, owner):
            doc = docs.get(mark.data['obligation'])
            if doc is None:
                continue
            if mark.data['kind'] == 'breach' and (context['kind'] == 'check' or
                    context['source_id'] not in {p['source_definition_id'] for p in doc['breached_by']}):
                continue
            available[mark.instance_id] = (mark, doc)
        selected = choose(ctx, owner, 'roll_mark_' + str(roll.roll_id), available,
            {key: ('Add' if m.data['kind'] == 'fulfillment' else 'Subtract') + ' 1d6: ' + doc['term']
             for key, (m, doc) in available.items()},
            f'Record the Promise: {subject.display_name} rolled {roll.total}. Spend one Oath Mark '
            'to add 1d6 (willing fulfillment) or subtract 1d6 (connected breach), before resolution? No Qi; once per turn.', optional=True)
        if selected is None:
            continue
        mark, doc = available[selected]
        if mark.data['kind'] == 'fulfillment' and not admit_choice(ctx, subject, PREFIX + 'record_the_promise',
                'fulfillment_roll', str(roll.roll_id), ['accept'], labels={'accept': 'Accept +1d6 on this roll'},
                prompt=f'Oath-Ledger: {subject.display_name}, accept +1d6 on this roll for one Fulfillment Mark?',
                expires_on='END_OF_CURRENT_TURN', readers=[owner.entity_id], automatic_options=['accept']):
            continue
        remove_instance(engine, subject, mark.instance_id, ctx.source)
        timed_condition(engine, owner, 'condition:typed.oath_ledger_spent', ctx.source, owner.entity_id,
                        'END_OF_CURRENT_TURN', {'label': 'Oath Mark already spent this turn'})
        from ..gate2_runtime_models import DiceSpec
        die = engine.roller.roll(DiceSpec(count=1, sides=6), actor_id=owner.entity_id, reason='OATH_MARK')
        engine._record_roll(die)
        invoke(ctx, subject, doc, mark.data['kind'])
        return die.total * (1 if mark.data['kind'] == 'fulfillment' else -1)
