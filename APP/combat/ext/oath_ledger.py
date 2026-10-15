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


class Sanction(StrictModel):
    kind: Literal['damage', 'points', 'suppression', 'boundary', 'return', 'charmed', 'frightened']
    description: StrictStr = Field(min_length=1)
    source_ids: tuple[StrictStr, ...] = ()
    boundary_cells: tuple[tuple[StrictInt, StrictInt], ...] = ()
    beneficiary_id: StrictStr = ''


class OngoingStatus(StrictModel):
    """Source-scoped GM assessment of presently honoring/breaching a term.

    Only genuinely external meaning is authored. Native exact action completion
    uses conduct(), independently; this record cannot fabricate a roll/payment.
    """
    obligation_id: StrictStr
    party_id: StrictStr
    status: Literal['honoring', 'breaching']
    external_basis: StrictStr = Field(min_length=1)


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
    duration_seconds: StrictInt = Field(ge=0)
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
    covenant_law: Literal['', 'Sanctuary Covenant', 'Guarded Passage', 'Honorable Contest',
                          'Protect the Weak', 'Formation Duty', 'Forbidden Art Accord'] = ''
    benefit: StrictStr = ''
    route_cells: tuple[tuple[StrictInt, StrictInt], ...] = ()
    protected_ids: tuple[StrictStr, ...] = ()
    assigned_regions: dict[StrictStr, tuple[tuple[StrictInt, StrictInt], ...]] = {}
    formation_benefit: Literal['ac', 'speed'] = 'ac'
    category_source_ids: tuple[StrictStr, ...] = ()
    category_save_tags: tuple[StrictStr, ...] = ()
    declared_opponents: dict[StrictStr, StrictStr] = {}
    sanction: Sanction | None = None
    compulsion_basis: Literal['', 'surrendered', 'lawful_authority', 'conquered_authority', 'accepted_release_or_aid', 'subdued'] = ''
    authority_reference: StrictStr = ''
    consequence_clue: StrictStr = ''

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
    if not set(ROWS).intersection(info['owned_ids']):
        return rows
    from ..feature_access import effective_cl
    numbers = {**info['numbers'], 'cl': effective_cl(info['owner_sheet'], 'tianxia.path.qi_cultivation')}
    return [*rows, *({'block': 'oath_ledger', 'feature_id': fid, 'numbers': numbers}
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
    status = fact.answers.get('oath_ledger_status')
    if status is not None:
        value = OngoingStatus.model_validate_json(status.fact)
        if status.category != 'external_obligation_status' or value.party_id != fact.subject_id:
            raise ValueError('An ongoing status must bind the actual party and source-scoped external meaning.')
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
                                  ('record_the_promise', 'spend', 'Spend an Oath Mark (once per turn)'),
                                  ('oathkeeper_s_record', 'compelled', 'Compelled Record: impose stated terms (Action, 7 Qi)')]:
        if PREFIX + leaf not in info['owned_ids']:
            continue
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.oath_ledger.{operation}",
            owner_id=info['actor_id'], display_name=label, economy=EconomyKind.ACTION if operation == 'compelled' else EconomyKind.NONE,
            resolution_kind='TYPED', target_kind='SELF', parameters={'setting_only': True, 'expected_damage': 0,
                'typed': {'source': PREFIX + leaf, 'numbers': info['numbers'],
                          'effects': [{'type': 'oath_ledger_command', 'operation': operation}],
                          'duration': {'kind': 'instant'}, 'riders': []}}))
    return out


@hook('compile_action')
def replace_unconditional_riders(action, info):
    typed = action.parameters.get('typed') or {}
    feature = typed.get('source')
    operations = {PREFIX + 'battlefield_covenant': 'covenant', PREFIX + 'heaven_as_witness': 'heaven'}
    if feature not in operations:
        return None
    # The original cost, action economy, concentration, field geometry and all
    # six law buttons remain native. Benefits are now acceptance-qualified.
    return action.model_copy(update={'parameters': {**action.parameters, 'typed': {**typed,
        'effects': [{'type': 'oath_ledger_command', 'operation': operations[feature],
                     'law': typed.get('option_label', '')}], 'riders': []}}})


@hook('candidate_allowed')
def candidates(engine, actor, candidate, action):
    if action is None:
        return None
    typed = action.parameters.get('typed') or {}
    command = next((r for r in typed.get('effects', ()) if r.get('type') == 'oath_ledger_command'), None)
    if command is None:
        return None
    if command['operation'] == 'compelled':
        return (owned(engine, actor, 'oathkeeper_s_record') is not None and actor.resources.get(QI, 0) >= 7
                and len([d for _, d in ledger(engine, actor) if d.get('recorded_oath')]) < 3
                and any(d.compulsion_basis and d.authority_reference and len(d.parties) == 1
                        and 0 < d.duration_seconds <= 30 * 86400 for _, d in source_documents(engine, actor).values()))
    if command['operation'] in ('covenant', 'heaven'):
        feature = 'battlefield_covenant' if command['operation'] == 'covenant' else 'heaven_as_witness'
        if not owned(engine, actor, feature):
            return False
        if feature == 'heaven_as_witness':
            return not any(c.condition_id == 'condition:typed.oath_ledger_heaven_used' for c in actor.conditions.values())
        return any(d.covenant_law and d.benefit.strip() for _, d in source_documents(engine, actor).values())
    if not owned(engine, actor, 'record_the_promise'):
        return False
    if command['operation'] == 'record':
        recorded = {d['obligation_id'] for _, d in ledger(engine, actor)}
        return actor.reaction_available and actor.resources.get(QI, 0) >= 1 and any(
            d.obligation_id not in recorded for _, d in source_documents(engine, actor).values())
    return any(marks(a, actor) for a in engine.state.actors.values()) and not spent_this_turn(engine, actor)


def choose(ctx, chooser, key, options, labels, prompt, *, optional=False, automatic=None):
    if not options:
        return None
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'OATH_LEDGER', ctx.source, key, chooser.entity_id),
        chooser, 'choice:needle.oath_ledger.' + key, list(options), labels=labels,
        minimum=0 if optional else 1, maximum=1, allow_decline=optional,
        automatic_options=None if automatic is None else list(automatic), preferred=list(automatic or ()),
        feature_id=ctx.typed.get('source'), name='Oath-Ledger', prompt=prompt)
    return picked[0] if picked else None


def consent(ctx, subject, document):
    return admit_choice(ctx, subject, ctx.typed.get('source') or PREFIX + 'record_the_promise', 'obligation_acceptance',
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
    save_record(ctx, document, seconds=min(28800, document.duration_seconds or 28800), origin=fact.record_id)


def save_record(ctx, document, *, seconds, origin):
    data = document.model_dump(mode='json')
    data.update({'created_round': ctx.engine.state.round_number, 'deadline_round': -1 if seconds == 0 else ctx.engine.state.round_number + (seconds + 5) // 6,
                 'origin': origin, 'seen': [], 'resolved': 0})
    ctx.engine._apply_condition(ctx.actor, RECORD, ctx.source, ctx.actor.entity_id, expires_on='UNTIL_REMOVED', data=
        {'document': canonical(data), 'categories': ['oath'], 'source_cl': int(ctx.numbers.get('cl') or 1),
         'label': 'Recorded obligation: ' + document.term})


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
            if doc.get('recorded_oath'):
                doc['seen'].append(receipt)
                update_record(engine, owner, condition, doc)
                if match == 'breach':
                    add_mark(ctx, actor, doc, match, count=int(ctx.numbers.get('pb') or 2))
                    sanction(ctx, actor, doc)
                    engine._apply_condition(actor, 'condition:typed.oath_ledger_recorded_direction', ctx.source,
                        owner.entity_id, expires_on='UNTIL_REMOVED', data={'obligation': doc['obligation_id'],
                            'source_cl': int(ctx.numbers.get('cl') or 1), 'label': 'Recorded breach: direction witnessed on the same plane'})
                else:
                    recorded_reward(ctx, doc)
                    engine._apply_condition(owner, 'condition:typed.oath_ledger_completed', ctx.source, owner.entity_id,
                        expires_on='UNTIL_REMOVED', data={'obligation': doc['obligation_id'], 'label': 'This oath has already granted its fulfillment reward'})
                    end_record(engine, owner, condition, doc)
                continue
            from ..target_knowledge import can_see
            immediate = next(((c, law) for caster, c, law in covenants(engine, actor)
                              if caster.entity_id == owner.entity_id and law['obligation_id'] == doc['obligation_id']), None)
            witnessed_field = heaven_contains(engine, owner, actor)
            if immediate is not None and not any(c.condition_id == 'condition:typed.oath_ledger_immediate_round'
                    and c.data['round'] == engine.state.round_number for c in owner.conditions.values()):
                add_mark(ctx, actor, doc, match)
                timed_condition(engine, owner, 'condition:typed.oath_ledger_immediate_round', ctx.source, owner.entity_id,
                    'UNTIL_REMOVED', {'round': engine.state.round_number, 'label': 'Immediate Witness used this round'})
                invoke(ctx, actor, doc, match)
                doc['seen'].append(receipt)
                update_record(engine, owner, condition, doc)
                continue
            if witnessed_field:
                last = next((c for c in actor.conditions.values() if c.condition_id == 'condition:typed.oath_ledger_heaven_round'
                             and c.source_actor_id == owner.entity_id), None)
                if last is not None and last.data['round'] == engine.state.round_number:
                    continue
                add_mark(ctx, actor, doc, match)
                timed_condition(engine, actor, 'condition:typed.oath_ledger_heaven_round', ctx.source, owner.entity_id,
                    'UNTIL_REMOVED', {'round': engine.state.round_number, 'label': 'Heavenly Mark witnessed this round'})
                doc['seen'].append(receipt)
                update_record(engine, owner, condition, doc)
                continue
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
            if 0 <= doc['deadline_round'] <= engine.state.round_number:
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
              'relief': 'End an eligible charm or fear expressly released by fulfillment',
              'direction': 'Learn the direction of the beneficiary or next required destination within 1 mile'}


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
    elif option == 'direction':
        destinations = {aid: ctx.engine.state.actors[aid].position for aid in doc['beneficiaries']
                        if ctx.engine.grid.distance_ft(subject.position, ctx.engine.state.actors[aid].position) <= 5280}
        if doc.get('required_position'):
            from ..gate2_runtime_models import Position
            point = Position.model_validate(doc['required_position'])
            if ctx.engine.grid.distance_ft(subject.position, point) <= 5280:
                destinations['required_destination'] = point
        destination = choose(ctx, ctx.actor, 'fulfillment_direction', destinations,
            {key: 'The next required destination' if key == 'required_destination' else ctx.engine.state.actors[key].display_name
             for key in destinations}, 'Record the Promise: choose the beneficiary or next required destination within 1 mile.')
        if destination:
            from ..observer_information import publish, direction
            publish(ctx.engine, subject, ctx.source, ctx.actor, 'direction',
                    {'direction': direction(subject.position, destinations[destination])}, 'END_OF_CURRENT_TURN')
    invoke(ctx, subject, doc, 'fulfillment')


@effect('oath_ledger_command')
def command(ctx, row):
    if row['operation'] == 'compelled' and owned(ctx.engine, ctx.actor, 'oathkeeper_s_record'):
        compelled(ctx)
    elif row['operation'] == 'covenant' and owned(ctx.engine, ctx.actor, 'battlefield_covenant'):
        covenant(ctx, row.get('law', ''))
    elif row['operation'] == 'heaven' and owned(ctx.engine, ctx.actor, 'heaven_as_witness'):
        heaven(ctx)
    elif not owned(ctx.engine, ctx.actor, 'record_the_promise'):
        return
    elif row['operation'] == 'record':
        record_promise(ctx)
    elif row['operation'] == 'spend':
        spend(ctx)


@hook('state_event')
def scene_ends(engine, event):
    if event.event_type != 'MATCH_ENDED':
        return
    for actor in engine.state.actors.values():
        for held in list(actor.conditions.values()):
            if held.condition_id == MARK or (held.source_definition_id.startswith(PREFIX) and held.condition_id in {
                    'condition:typed.fact_consent_admission', 'condition:typed.oath_ledger_witness_round',
                    'condition:typed.oath_ledger_compelled_immunity', 'condition:typed.oath_ledger_heaven_used'}):
                remove_instance(engine, actor, held.instance_id, held.source_definition_id)


@hook('state_event')
def obligation_severed(engine, event):
    if event.event_type != 'CONDITION_REMOVED' or event.payload.get('condition_id') != RECORD:
        return
    for owner in engine.state.actors.values():
        current = {doc['obligation_id'] for _, doc in ledger(engine, owner)}
        for subject in engine.state.actors.values():
            for mark in marks(subject, owner):
                if mark.data['obligation'] not in current:
                    remove_instance(engine, subject, mark.instance_id, event.source_definition_id)


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
        functions = [key for key in doc['governed_source_ids'] if key in actual_breach_sources(ctx.engine, subject, doc)]
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
        from ..movement_paths import resolve
        candidate = paths[selected]
        resolve(ctx.engine, subject, tuple(candidate.canonical_path), ctx.source, kind='forced', feet=feet,
                intent=ctx.intent, source_actor_id=ctx.actor.entity_id, ctx=ctx)


@hook('candidate_allowed')
def function_lock(engine, actor, candidate, action):
    if any(c.condition_id == 'condition:typed.oath_ledger_function_lock'
           and c.data['function'] == candidate.source_definition_id for c in actor.conditions.values()):
        return False


@hook('presentation_hidden_conditions')
def hide_private_consent(engine, actor):
    return [c.instance_id for c in actor.conditions.values() if c.condition_id == 'condition:typed.fact_consent_admission'
            and c.source_definition_id.startswith(PREFIX)]


@hook('observer_information_rows')
def mark_directions(engine, viewer):
    from ..observer_information import direction
    out = []
    for subject in engine.state.actors.values():
        held = marks(subject, viewer)
        if held and engine._on_battlefield(subject) and engine.grid.distance_ft(viewer.position, subject.position) <= 5280:
            out.append({'viewer_id': viewer.entity_id, 'authority_actor_id': viewer.entity_id,
                'source_id': held[0].source_definition_id, 'kind': 'direction',
                'details': {'direction': direction(viewer.position, subject.position)}})
    return out


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


COVENANT = 'condition:typed.oath_ledger_covenant'
HEAVEN = 'condition:typed.oath_ledger_heaven'


def covenant(ctx, law):
    proposals = {key: (fact, doc) for key, (fact, doc) in source_documents(ctx.engine, ctx.actor).items()
                 if doc.covenant_law and doc.benefit.strip() and (not law or law == doc.covenant_law)}
    selected = choose(ctx, ctx.actor, 'covenant_terms', proposals,
        {key: doc.covenant_law + ': ' + doc.term + '; benefit: ' + doc.benefit for key, (_, doc) in proposals.items()},
        'Battlefield Covenant: declare one comprehensible rule and its reciprocal benefit. '
        '30-foot aura, Concentration, 1 minute; your Action costs 5 Qi.')
    if selected is None:
        return
    fact, doc = proposals[selected]
    # Accepting and rejecting are controller decisions; no ally/hostile shortcut.
    accepted = []
    for party in doc.parties:
        subject = ctx.engine.state.actors[party]
        if ctx.engine._distance_actor_to_actor(ctx.actor, subject) <= 30 and consent(ctx, subject, doc):
            accepted.append(party)
    from .effect_durations import round_token
    ctx.engine._apply_condition(ctx.actor, COVENANT, ctx.source, ctx.actor.entity_id,
        expires_on=round_token(ctx.engine, 10), data={'document': canonical(doc.model_dump(mode='json')),
            'accepted': canonical(accepted), 'center': ctx.actor.entity_id, 'deadline_round': ctx.engine.state.round_number + 10,
            'label': 'Battlefield Covenant: ' + doc.covenant_law})
    if accepted:
        save_record(ctx, doc.model_copy(update={'parties': tuple(accepted)}), seconds=60, origin=fact.record_id)


@hook('movement_landed')
def later_covenant_acceptance(engine, subject, previous, destination, intent, forced):
    from ..concentration import concentrating_on
    if intent is None:
        return
    for owner in engine.state.actors.values():
        for condition in list(owner.conditions.values()):
            if condition.condition_id != COVENANT or not concentrating_on(owner, condition.source_definition_id):
                continue
            accepted = json.loads(condition.data['accepted'])
            document = Obligation.model_validate_json(condition.data['document'])
            if (subject.entity_id in accepted or subject.entity_id not in document.parties
                    or engine._distance_actor_to_actor(owner, subject) > 30):
                continue
            ctx = context_for(engine, owner, intent)
            if ctx is None or consent(ctx, subject, document) is None:
                continue
            accepted.append(subject.entity_id)
            engine._update_condition_data(owner, condition, {**condition.data, 'accepted': canonical(accepted)}, ctx.source)
            existing = next(((held, doc) for held, doc in ledger(engine, owner)
                             if doc['obligation_id'] == document.obligation_id), None)
            if existing:
                held, doc = existing
                doc['parties'] = accepted
                update_record(engine, owner, held, doc)
            else:
                save_record(ctx, document.model_copy(update={'parties': tuple(accepted)}),
                            seconds=max(1, (condition.data['deadline_round'] - engine.state.round_number) * 6),
                            origin='covenant:' + str(condition.applied_sequence))


def covenants(engine, subject):
    from ..concentration import concentrating_on
    for owner in engine.state.actors.values():
        if not owned(engine, owner, 'battlefield_covenant'):
            continue
        for condition in owner.conditions.values():
            if condition.condition_id != COVENANT or not concentrating_on(owner, condition.source_definition_id):
                continue
            if (subject.entity_id not in json.loads(condition.data['accepted'])
                    or engine._distance_actor_to_actor(owner, subject) > 30):
                continue
            yield owner, condition, json.loads(condition.data['document'])


@hook('ac_against')
def sanctuary_ac(engine, attacker, target, spec, source):
    for owner, condition, doc in covenants(engine, target):
        if doc['covenant_law'] == 'Sanctuary Covenant' and any(
                other.instance_id == condition.instance_id for _, other, _ in covenants(engine, attacker)):
            return 1


@hook('ac')
def formation_ac(engine, subject):
    for _, _, doc in covenants(engine, subject):
        if (doc['covenant_law'] == 'Formation Duty' and doc['formation_benefit'] == 'ac'
                and [subject.position.x, subject.position.y] in doc['assigned_regions'].get(subject.entity_id, [])):
            return 1


@hook('speed')
def formation_speed(engine, subject):
    for _, _, doc in covenants(engine, subject):
        if (doc['covenant_law'] == 'Formation Duty' and doc['formation_benefit'] == 'speed'
                and [subject.position.x, subject.position.y] in doc['assigned_regions'].get(subject.entity_id, [])):
            return 5


@hook('opportunity_allowed')
def guarded_passage(engine, reactor, mover):
    for _, condition, doc in covenants(engine, mover):
        if (doc['covenant_law'] == 'Guarded Passage' and [mover.position.x, mover.position.y] in doc['route_cells']
                and any(c.instance_id == condition.instance_id for _, c, _ in covenants(engine, reactor))):
            return False


@hook('turn_start')
def protector_start(engine, subject):
    for owner, condition, doc in covenants(engine, subject):
        if doc['covenant_law'] == 'Protect the Weak' and any(
                aid in engine.state.actors and engine._distance_actor_to_actor(subject, engine.state.actors[aid]) <= 10
                for aid in doc['protected_ids']):
            row = owned(engine, owner, 'battlefield_covenant')
            engine._grant_temp_hp(subject, int(row['numbers'].get('pb') or 2), condition.source_definition_id, owner.entity_id)


@hook('save_mode')
def covenant_saves(engine, subject, ability, dc, source, roll_context):
    tags = set((roll_context or {}).get('named') or [])
    for owner, condition, doc in covenants(engine, subject):
        law = doc['covenant_law']
        if law == 'Sanctuary Covenant' and tags.intersection({'charmed', 'forced_hostility'}):
            return 'ADVANTAGE'
        if law == 'Forbidden Art Accord' and (source in doc['category_source_ids'] or tags.intersection(doc['category_save_tags'])):
            return 'ADVANTAGE'
        if law == 'Honorable Contest':
            action = engine.action_catalog.get(source)
            if action is not None and action.owner_id not in json.loads(condition.data['accepted']):
                return 'ADVANTAGE'


@hook('target_eligibility')
def contest_target(engine, actor, target, action):
    if target is None or action is None:
        return
    for owner, condition, doc in covenants(engine, target):
        if doc['covenant_law'] != 'Honorable Contest' or actor.entity_id in json.loads(condition.data['accepted']):
            continue
        numbers = (action.parameters.get('typed') or {}).get('numbers') or {}
        if numbers and int(numbers.get('cl') or 0) < int(owned(engine, owner, 'battlefield_covenant')['numbers']['cl']):
            return False


def heaven(ctx):
    if any(c.condition_id == 'condition:typed.oath_ledger_heaven_used' for c in ctx.actor.conditions.values()):
        raise ValueError('Heaven as Witness can be activated only once per scene.')
    from .effect_durations import round_token
    timed_condition(ctx.engine, ctx.actor, 'condition:typed.oath_ledger_heaven_used', ctx.source,
        ctx.actor.entity_id, 'UNTIL_REMOVED', {'label': 'Heaven as Witness used this scene'})
    timed_condition(ctx.engine, ctx.actor, HEAVEN, ctx.source, ctx.actor.entity_id, round_token(ctx.engine, 10),
        {'final_used': 0, 'label': 'Heaven as Witness: accepted obligations are perceptible in this 40-foot field'})


def heaven_contains(engine, owner, subject):
    from ..concentration import concentrating_on
    return any(c.condition_id == HEAVEN and concentrating_on(owner, c.source_definition_id)
               and engine.grid.distance_ft(owner.position, subject.position) <= 40
               and abs(owner.position.z - subject.position.z) * 5 <= 40 for c in owner.conditions.values())


def compelled(ctx):
    proposals = {key: (f, d) for key, (f, d) in source_documents(ctx.engine, ctx.actor).items()
                 if d.compulsion_basis and d.authority_reference and len(d.parties) == 1
                 and 0 < d.duration_seconds <= 30 * 86400 and d.sanction is not None}
    proposals = {key: (f, d) for key, (f, d) in proposals.items()
                 if ctx.engine._distance_actor_to_actor(ctx.actor, ctx.engine.state.actors[d.parties[0]]) <= 5}
    selected = choose(ctx, ctx.actor, 'compelled_terms', proposals,
        {key: d.term + '; sanction: ' + d.sanction.description for key, (_, d) in proposals.items()},
        'Compelled Record: choose lawful or coercive terms for the touched creature. '
        'Action, 7 Qi, Charisma save; duration at most 30 days. This imposes authority and is not consent.')
    if selected is None:
        return
    fact, doc = proposals[selected]
    subject = ctx.engine.state.actors[doc.parties[0]]
    if any(c.condition_id == 'condition:typed.oath_ledger_compelled_immunity' and c.source_actor_id == ctx.actor.entity_id
           for c in subject.conditions.values()):
        raise ValueError('That creature already resisted your Compelled Record this scene.')
    from ..typed_executor import resolve_opposed_check
    own_cl = int(ctx.numbers.get('cl') or 1)
    subject_numbers = actor_numbers(ctx.engine, subject)
    if not subject_numbers or 'cl' not in subject_numbers or 'save_dc' not in subject_numbers:
        raise ValueError('Compelled Record requires this creature’s actual Source CL and Cultivation Save DC.')
    subject_cl = int(subject_numbers['cl'])
    subdued = any(c.condition_id in {'condition:typed.completely_subdued', 'completely_subdued'} for c in subject.conditions.values())
    if doc.compulsion_basis == 'subdued' and not subdued:
        raise ValueError('This creature is not Completely Subdued in the native state.')
    ctx.engine._spend_resource(ctx.actor, QI, 7, ctx.source)
    auto_fail = own_cl - subject_cl >= 6 and subdued
    protected = any((c.data.get('rule') or {}).get('anti_oath') for c in subject.conditions.values())
    save = None if auto_fail and not protected else ctx.engine._roll_save(subject, 'CHA', int(ctx.numbers.get('save_dc') or 10), ctx.source)
    success = save is not None and save.total >= int(ctx.numbers.get('save_dc') or 10)
    if not success and subject_cl - own_cl >= 3:
        contest = resolve_opposed_check(ctx, subject, {'kind': 'cultivation'}, {'kind': 'dc', 'dc': int(subject_numbers['save_dc'])})
        success = not contest.success
    if success:
        ctx.engine._apply_condition(subject, 'condition:typed.oath_ledger_compelled_immunity', ctx.source,
            ctx.actor.entity_id, expires_on='UNTIL_REMOVED', data={'label': 'Compelled Record resisted until scene end'})
        return
    save_record(ctx, doc, seconds=doc.duration_seconds, origin=fact.record_id)
    condition, saved = ledger(ctx.engine, ctx.actor)[-1]
    saved['recorded_oath'] = 1
    saved['coerced'] = 1
    update_record(ctx.engine, ctx.actor, condition, saved)


def sanction(ctx, subject, doc, *, maximum=False):
    """Apply only the sanction established in this obligation at creation."""
    spec = doc.get('sanction')
    if spec is None:
        return
    kind = spec['kind']
    from .effect_durations import round_token
    if kind == 'damage':
        damage_type = choose(ctx, ctx.actor, 'sanction_damage', ['psychic', 'force'],
            {'psychic': 'Psychic damage', 'force': 'Force damage'}, 'Recorded Sanction: choose Psychic or Force damage.')
        applied_effect(ctx, subject, {'type': 'damage', **({'flat': 60} if maximum else {'dice': {'count': 6, 'sides': 10}}),
                                     'damage_types': [damage_type]})
    elif kind == 'points':
        from .d20_rewrite import pool_id
        pool = pool_id(subject, 'cp')
        if pool:
            ctx.engine._spend_resource(subject, pool, min(subject.resources[pool], 2 * int(ctx.numbers.get('pb') or 2)), ctx.source)
    elif kind == 'suppression':
        if not set(spec['source_ids']) <= set(doc['governed_source_ids']):
            raise ValueError('The sanction may suppress only the exact cultivation functions governed by this oath.')
        for source in spec['source_ids']:
            ctx.engine._apply_condition(subject, 'condition:typed.oath_ledger_function_lock', ctx.source,
                ctx.actor.entity_id, expires_on=round_token(ctx.engine, 10),
                data={'function': source, 'obligation': doc['obligation_id'], 'label': 'Recorded Sanction: named function suppressed for 1 minute'})
    elif kind == 'boundary':
        ctx.engine._apply_condition(subject, 'condition:typed.oath_ledger_boundary', ctx.source, ctx.actor.entity_id,
            expires_on=round_token(ctx.engine, 4800), data={'cells': canonical(spec['boundary_cells']),
                'label': 'Recorded Sanction: cannot cross the oath’s named boundary for 8 hours'})
    elif kind == 'return':
        raise ValueError('Compelled return must use the native governed item, payment, office or authority transaction; no movement distance is supplied by this sanction.')
    elif kind in ('charmed', 'frightened'):
        if spec['beneficiary_id'] not in doc['beneficiaries']:
            raise ValueError('The sanction must name an actual beneficiary of this oath.')
        ctx.engine._apply_condition(subject, 'condition:typed.' + kind, ctx.source, ctx.actor.entity_id,
            expires_on=round_token(ctx.engine, 10), data={'beneficiary_id': spec['beneficiary_id'],
                'origin_save': {'ability': 'CHA', 'dc': int(ctx.numbers.get('save_dc') or 10)},
                'repeat_save': {'ability': 'CHA', 'dc': int(ctx.numbers.get('save_dc') or 10), 'when': 'end'},
                'label': 'Recorded Sanction: ' + kind.title() + ' of the named beneficiary for 1 minute'})


@hook('movement_attempt')
@hook('forced_movement_attempt')
def sanction_boundary(engine, actor, previous, destination, *args, **kwargs):
    for condition in actor.conditions.values():
        if condition.condition_id == 'condition:typed.oath_ledger_boundary':
            cells = json.loads(condition.data['cells'])
            if ([previous.x, previous.y] in cells) != ([destination.x, destination.y] in cells):
                return False


def actor_numbers(engine, actor):
    """Read actual sealed compilation numbers, never visual names or damage tags."""
    return next(((a.parameters.get('typed') or {}).get('numbers') for a in engine.action_catalog.values()
                 if a.owner_id == actor.entity_id and (a.parameters.get('typed') or {}).get('numbers')), None)


def actual_breach_sources(engine, subject, doc):
    allowed = {p['source_definition_id'] for p in doc['breached_by']}
    return {event.source_definition_id for event in engine.events if event.event_type == 'INTENT_ACCEPTED'
            and event.actor_id == subject.entity_id and event.trigger_or_intent_id in doc['seen']
            and event.source_definition_id in allowed}


@hook('turn_start_choice')
def heavenly_confirmation(engine, owner):
    if not owned(engine, owner, 'heaven_as_witness') or not heaven_contains(engine, owner, owner):
        return
    intent = getattr(engine, '_active_intent', None)
    if intent is None:
        return
    ctx = context_for(engine, owner, intent)
    if ctx is None:
        return
    docs = {d['obligation_id']: d for _, d in ledger(engine, owner)}
    options = {}
    for key, fact in records(engine, owner).items():
        answer = fact.answers.get('oath_ledger_status')
        if answer is None:
            continue
        status = OngoingStatus.model_validate_json(answer.fact)
        doc = docs.get(status.obligation_id)
        subject = engine.state.actors.get(status.party_id)
        if doc is not None and subject is not None and status.party_id in doc['parties'] and heaven_contains(engine, owner, subject):
            options[key] = (doc, subject, status)
    selected = choose(ctx, owner, 'heavenly_confirmation_party', options,
        {key: subject.display_name + ': ' + status.status + ' “' + doc['term'] + '”'
         for key, (doc, subject, status) in options.items()},
        'Heavenly Confirmation: choose one accepted obligation and one party presently honoring or breaching it in your field. '
        'This start-of-turn effect costs no action, Qi or Mark.', optional=True)
    if selected is None:
        return
    doc, subject, status = options[selected]
    if status.status == 'honoring':
        benefits = {'heal': 'Restore 3d8 + key modifier Hit Points', 'points': 'Restore 2 Cultivation Points',
            'ac': 'Grant +2 AC until your next turn starts', 'move': 'Move 15 feet without provoking',
            'release': 'End one eligible condition directly obstructing fulfillment'}
    else:
        benefits = {'damage': 'Deal 3d8 Psychic or Force damage', 'points': 'Remove 2 current Cultivation Points',
            'reaction': 'Prevent Reactions until the party’s next turn starts',
            'move': 'Move 15 feet toward a required or away from a forbidden position',
            'suppress': 'Suppress the exact function used for the breach until its next turn starts'}
    selected = choose(ctx, owner, 'heavenly_confirmation_effect', benefits, benefits,
        f'Heavenly Confirmation: choose the effect on {subject.display_name} for “{doc["term"]}”.')
    honoring = status.status == 'honoring'
    if selected == 'heal':
        applied_effect(ctx, subject, {'type': 'healing', 'dice': {'count': 3, 'sides': 8}, 'formula': 'key_ability_modifier'})
    elif selected == 'points':
        from .d20_rewrite import pool_id
        pool = pool_id(subject, 'cp')
        if pool:
            if honoring:
                engine._gain_resource(subject, pool, min(2, subject.resource_maximums[pool] - subject.resources[pool]), ctx.source)
            else:
                engine._spend_resource(subject, pool, min(2, subject.resources[pool]), ctx.source)
    elif selected == 'ac':
        engine._add_modifier(subject, ctx.source, 'armor_class', 'ADD', 2, 'ALL_ATTACKS', expires_on='START_OF_SOURCE_NEXT_TURN')
    elif selected == 'move':
        if honoring:
            move_grant(ctx, subject, 15)
        else:
            return_movement(ctx, subject, doc, 15)
    elif selected == 'release':
        relief(ctx, subject, doc, ['restrained', 'charmed', 'frightened', 'oath', 'curse', 'suppression'])
    elif selected == 'damage':
        damage_type = choose(ctx, owner, 'heavenly_damage_type', ['psychic', 'force'],
            {'psychic': 'Psychic damage', 'force': 'Force damage'}, 'Heavenly Confirmation: choose Psychic or Force damage.')
        applied_effect(ctx, subject, {'type': 'damage', 'dice': {'count': 3, 'sides': 8}, 'damage_types': [damage_type]})
    elif selected == 'reaction':
        from .effect_durations import holder_next_turn
        engine._apply_condition(subject, 'condition:typed.oath_ledger_no_reactions', ctx.source, owner.entity_id,
            expires_on=holder_next_turn(subject), data={'rule': {'no_reactions': 1}, 'label': 'Heavenly Confirmation: no Reactions until your next turn'})
    elif selected == 'suppress':
        sources = [key for key in doc['governed_source_ids'] if key in actual_breach_sources(engine, subject, doc)]
        source = choose(ctx, owner, 'heavenly_suppress', sources,
            {key: getattr(engine.action_catalog.get(key), 'display_name', 'The named function used in this breach') for key in sources},
            'Heavenly Confirmation: name the exact function actually used for the recorded breach.')
        if source:
            from .effect_durations import holder_next_turn
            engine._apply_condition(subject, 'condition:typed.oath_ledger_function_lock', ctx.source, owner.entity_id,
                expires_on=holder_next_turn(subject), data={'function': source, 'obligation': doc['obligation_id'],
                    'label': 'Heavenly Confirmation: the implicated function is suppressed until your next turn'})


def recorded_reward(ctx, doc):
    recipients = {aid: ctx.engine.state.actors[aid] for aid in doc['parties']}
    selected = choose(ctx, ctx.actor, 'recorded_recipient', recipients,
        {aid: a.display_name for aid, a in recipients.items()},
        'Oathkeeper’s Record: choose one participant to receive this meaningful oath’s single fulfillment reward.')
    if selected is None:
        return
    subject = recipients[selected]
    options = {'qi': 'Regain 3 Qi', 'healing': 'Regain 4d8 + key modifier Hit Points',
        'temp': 'Gain temporary Hit Points equal to four times Proficiency Bonus',
        'release': 'End an eligible oath, fear, charm, restraint or curse that fulfillment expressly releases',
        'save': 'Advantage on one saving throw before the end of the next scene',
        'clue': 'Receive one truthful symbolic clue about this oath’s direct consequences'}
    option = choose(ctx, ctx.actor, 'recorded_reward', options, options,
        f'Oathkeeper’s Record: choose {subject.display_name}’s fulfillment reward. No action, Mark or Qi cost.')
    if option == 'qi':
        ctx.engine._gain_resource(subject, QI, min(3, subject.resource_maximums.get(QI, 0) - subject.resources.get(QI, 0)), ctx.source)
    elif option == 'healing':
        applied_effect(ctx, subject, {'type': 'healing', 'dice': {'count': 4, 'sides': 8}, 'formula': 'key_ability_modifier'})
    elif option == 'temp':
        ctx.engine._grant_temp_hp(subject, 4 * int(ctx.numbers.get('pb') or 2), ctx.source, ctx.actor.entity_id)
    elif option == 'release':
        relief(ctx, subject, doc, ['oath', 'frightened', 'charmed', 'restrained', 'curse'])
    elif option == 'save':
        ctx.engine._apply_condition(subject, 'condition:typed.oath_ledger_next_save', ctx.source, ctx.actor.entity_id,
            expires_on='UNTIL_REMOVED', data={'scene_remaining': 2, 'label': 'Oath fulfillment: Advantage on one save before the next scene ends'})
    elif option == 'clue':
        if not doc['consequence_clue'].strip():
            raise ValueError('The table owner must record a truthful symbolic clue about this oath’s direct consequences.')
        note(ctx.engine, ctx.source, ctx.actor, 'Oathkeeper’s Record: ' + doc['consequence_clue'], targets=(subject,))


@hook('state_event')
def breach_activation(engine, event):
    if event.event_type != 'INTENT_ACCEPTED':
        return
    intent = getattr(engine, '_active_intent', None)
    candidate = getattr(engine, '_active_candidate', None)
    if intent is None or candidate is None or intent.table_fact is not None or candidate.kind.value not in {'MOVE', 'ACTION', 'BONUS_ACTION'}:
        return
    subject = engine.state.actors.get(event.actor_id)
    if subject is None:
        return
    for owner in sorted(engine.state.actors.values(), key=lambda a: a.entity_id):
        if not owned(engine, owner, 'record_the_promise') or spent_this_turn(engine, owner):
            continue
        ctx = context_for(engine, owner, intent)
        if ctx is None:
            continue
        docs = {d['obligation_id']: d for _, d in ledger(engine, owner)}
        applicable = {}
        for mark in marks(subject, owner, kind='breach'):
            doc = docs.get(mark.data['obligation'])
            if doc is None:
                continue
            if any(p['source_definition_id'] == candidate.source_definition_id
                   and p['kind'] == candidate.kind.value and tuple(p['target_ids']) == tuple(candidate.target_ids)
                   and tuple(p['option_ids']) == tuple(intent.option_ids)
                   and (p['destination'] is None or p['destination'] == intent.destination.model_dump(mode='json'))
                   for p in doc['breached_by']):
                applicable[mark.instance_id] = (mark, doc)
        selected = choose(ctx, owner, 'breach_mark', applicable,
            {key: doc['term'] for key, (_, doc) in applicable.items()},
            f'Record the Promise: {subject.display_name} begins {candidate.display_name}, connected to the recorded breach. '
            'Spend one Breach Mark, once per turn? No action or Qi cost.', optional=True)
        if selected is None:
            continue
        mark, doc = applicable[selected]
        options = {'speed': 'Reduce Speed by 15 feet until your next turn starts',
            'reactions': 'Prevent Reactions until the breacher’s next turn starts',
            'direction': 'Reveal direction and distance within 1 mile until the scene ends',
            'beneficiary': 'A beneficiary gains Advantage on its next attack or saving throw against this breacher before your next turn'}
        benefit = choose(ctx, owner, 'breach_effect', options, options,
            f'Record the Promise: choose the sanction for {subject.display_name}. One Breach Mark, no Qi.')
        if benefit is None:
            continue
        remove_instance(engine, subject, mark.instance_id, ctx.source)
        timed_condition(engine, owner, 'condition:typed.oath_ledger_spent', ctx.source, owner.entity_id,
            'END_OF_CURRENT_TURN', {'label': 'Oath Mark already spent this turn'})
        if benefit == 'speed':
            applied_effect(ctx, subject, {'type': 'speed', 'flat': -15, 'expires_on': 'START_OF_SOURCE_NEXT_TURN', 'source_owned': 1})
        elif benefit == 'reactions':
            from .effect_durations import holder_next_turn
            engine._apply_condition(subject, 'condition:typed.oath_ledger_no_reactions', ctx.source, owner.entity_id,
                expires_on=holder_next_turn(subject), data={'rule': {'no_reactions': 1}, 'label': 'Breach Mark: no Reactions until your next turn'})
        elif benefit == 'direction':
            engine._apply_condition(subject, 'condition:typed.oath_ledger_revealed', ctx.source, owner.entity_id,
                expires_on='UNTIL_REMOVED', data={'label': 'Breach Mark: direction and distance revealed within 1 mile until scene end'})
        elif benefit == 'beneficiary':
            recipients = {aid: engine.state.actors[aid] for aid in doc['beneficiaries']}
            target = choose(ctx, owner, 'breach_beneficiary', recipients,
                {aid: a.display_name for aid, a in recipients.items()}, 'Record the Promise: choose the beneficiary who gains Advantage against this breacher.')
            if target:
                engine._apply_condition(recipients[target], 'condition:typed.oath_ledger_against_breacher', ctx.source, owner.entity_id,
                    expires_on='START_OF_SOURCE_NEXT_TURN', data={'target': subject.entity_id,
                        'label': 'Breach Mark: Advantage on the next attack or save against the named breacher'})
        invoke(ctx, subject, doc, 'breach')


@hook('attack_roll_modes')
def beneficiary_attack(engine, actor, target):
    if any(c.condition_id == 'condition:typed.oath_ledger_against_breacher' and c.data['target'] == target.entity_id
           for c in actor.conditions.values()):
        return ['ADVANTAGE']


@hook('attack_result')
def beneficiary_attack_spent(ctx, target, hit, critical):
    for c in list(ctx.actor.conditions.values()):
        if c.condition_id == 'condition:typed.oath_ledger_against_breacher' and c.data['target'] == target.entity_id:
            remove_instance(ctx.engine, ctx.actor, c.instance_id, ctx.source)
