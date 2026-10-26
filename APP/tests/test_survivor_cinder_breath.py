"""Breath's native compiled action, table consent, scoped saves and cold replay.

Scenario save packets exercise the existing sealed per-save categories contract;
they do not claim production of campaign facts or Remnant Cinder generation.
The initial Cinder is legitimate source-backed starting data, not a success receipt.
"""
import hashlib
import json
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.ext.survivor_cinder import SOURCE, STATUS, CONSENT
from tests.h1_support import sheet
from tests.test_a2_foundations3 import add_action
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn, sealed_native_attack

POOL = 'resource:foundation.remnant_cinder'
FAMILIES = ('fear', 'despair', 'remnant_possession', 'battlefield_horror',
            'grief_based_control', 'ash_contamination', 'death_pressure', 'fire_aftermath_backlash')


def setup(tmp_path, *, score=14, initial=1, stage='Awakened', target_position=None, modes=None, threats=True):
    document = sheet([SOURCE], score=score, cl=15, foundation={
        'foundation_id': 'ash_born_remnant_core_v0_2B', 'stage': stage,
        'resource': {'name': 'Remnant Cinder', 'resource_id': 'tianxia.resource.remnant_cinder',
                     'maximum': 1, 'current': initial}})
    bundle = compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})

    def delivery(bundles):
        sealed_native_attack(bundles[2], 'Ordinary strike', damage_type='FORCE',
                             sides=2, modifier=2, attack_bonus=100)
        for family in ((*FAMILIES, 'unrelated', 'fire', 'possession') if threats else ()):
            add_action(bundles[2], 'Threat ' + family, [
                # Breath covers every save ability. Use Dexterity here so the
                # Foundation's separate Wisdom-only Reserve cannot mask use
                # or consumption of Breath's one-save grant.
                {'type': 'save', 'ability': 'DEX', 'save_categories': [family],
                 'on_fail': [], 'on_success': []}], economy='NONE', dc=15)
        add_action(bundles[0], 'Ordinary temporary HP', [
            {'type': 'temp_hp', 'flat': 12, 'applies_to': 'target'}], target_kind='ALLY_OR_SELF')

    return fixture(tmp_path, [], owner_bundle=bundle, named=True,
                   foe_sheet=sheet(['TAL_DAEMONIC_CULTIVATION_DREAD_APPETITE'], name='Mara'),
                   ally_position=target_position, modes=modes, bundle_transform=delivery,
                   seed='SURVIVOR-CINDER')


def display(engine, row):
    # System rows (movement, end turn) have no catalogued action; never index them directly.
    action = engine.action_catalog.get(row.source_definition_id)
    return getattr(action, 'display_name', '') or ''


def use(combat, table, mid, name='Survivor Cinder Breath', target=OWNER, choices=None):
    # A menu label may carry an option suffix ("Dread Appetite: Frighten"); match the printed name.
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates()
            if display(engine, c) in (name,) or display(engine, c).startswith(name + ':')]
    rows = [c for c in rows if target is None or c.target_ids == (target,)]
    assert rows, name
    return settle(table, mid, rows[0].candidate_id, picks=choices)


def grants(engine, actor):
    return [c for c in engine.state.actors[actor].conditions.values()
            if c.condition_id.startswith(STATUS + '.')]


def last_save(engine):
    return [e for e in engine.events if e.event_type == 'SAVE_ROLLED'][-1]


def test_source_and_dynamic_native_rule_inputs():
    root = Path(__file__).resolve().parents[1]
    texts = json.loads((root / 'authority/typed_mechanics/rules_text.json').read_text())
    assert hashlib.sha256(texts[SOURCE].encode()).hexdigest() == 'c0edd1dc719af801bdd008ba185d83a6158e7a244b4f69991c8abaf0100e195b'
    # Literal dependencies keep native compiler inputs in safe CI exports.
    from combat.typed_reactions import rules
    for relative in ('combat/rules/feature_blocks.d/tabik.json',
                     'combat/rules/feature_blocks.d/auto8-athletics.json',
                     'combat/rules/feature_blocks.d/insights7.json',
                     'combat/rules/feature_blocks.d/a2_group_insights_1_residual.json'):
        rows = json.loads((root / relative).read_text())['features']
        assert all(key in rules()['features'] for key in rows)


@pytest.mark.parametrize('score,expected', [(14, 6), (8, 3), (4, 1), (2, 0)])
def test_signed_key_payment_and_native_reload(tmp_path, score, expected):
    combat, table, mid = setup(tmp_path, score=score)
    use(combat, table, mid)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    assert actor.temporary_hp == expected
    assert len([e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED'
                and e.actor_id == OWNER and OWNER in e.target_ids]) == 1
    assert actor.resources[POOL] == 0
    assert grants(engine, OWNER)
    assert all(isinstance(v, (str, int)) for c in grants(engine, OWNER) for v in c.data.values())
    assert not [c for c in engine.legal_candidates() if display(engine, c) == 'Survivor Cinder Breath']


@pytest.mark.parametrize('family', FAMILIES)
def test_one_scoped_save_keeps_unrelated_saves_and_consumes_once(tmp_path, family):
    combat, table, mid = setup(tmp_path)
    use(combat, table, mid)
    turn(table, mid, FOE)
    for unscoped in ('unrelated', 'fire', 'possession'):
        use(combat, table, mid, 'Threat ' + unscoped)
        engine = reload(tmp_path, mid)
        assert last_save(engine).payload['mode'] == 'NORMAL'
        assert grants(engine, OWNER)
    use(combat, table, mid, 'Threat ' + family)
    engine = reload(tmp_path, mid)
    assert last_save(engine).payload['mode'] == 'ADVANTAGE'
    assert not grants(engine, OWNER)
    use(combat, table, mid, 'Threat ' + family)
    assert last_save(reload(tmp_path, mid)).payload['mode'] == 'NORMAL'


@pytest.mark.parametrize('recipient', [ALLY, FOE])
def test_recipient_owns_consent_and_refusal_preserves_payment(tmp_path, recipient):
    combat, table, mid = setup(tmp_path)
    prompts = use(combat, table, mid, target=recipient, choices={CONSENT: None})
    assert any(p['context']['reactor_id'] == recipient for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[POOL] == 1
    assert engine.state.actors[recipient].temporary_hp == 0
    assert not grants(engine, recipient)
    use(combat, table, mid, target=recipient, choices={CONSENT: 'accept'})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[recipient].temporary_hp == 6
    assert engine.state.actors[OWNER].resources[POOL] == 0
    assert grants(engine, recipient)


def test_recipient_turn_does_not_expire_owner_clock_and_hp_does_not_stack(tmp_path):
    combat, table, mid = setup(tmp_path)
    # Establish the existing HP with an Action, then spend the initial Cinder
    # with the Bonus Action in this same turn; do not assume Cinder persists
    # through an extra owner turn while its generation record is read-only.
    use(combat, table, mid, 'Ordinary temporary HP', ALLY)
    use(combat, table, mid, target=ALLY)
    assert reload(tmp_path, mid).state.actors[ALLY].temporary_hp == 12
    turn(table, mid, ALLY)
    assert grants(reload(tmp_path, mid), ALLY)
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert not grants(engine, ALLY)
    assert engine.state.actors[ALLY].temporary_hp == 12


@pytest.mark.parametrize('initial,position', [(0, None), (1, {'x': 12, 'y': 6})])
def test_unavailable_without_cinder_or_outside_range(tmp_path, initial, position):
    combat, table, mid = setup(tmp_path, initial=initial, target_position=position)
    engine = reload(tmp_path, mid)
    assert not [c for c in engine.legal_candidates()
                if display(engine, c) == 'Survivor Cinder Breath'
                and (initial == 0 or c.target_ids == (ALLY,))]
    assert not any(engine.action_catalog.get(s) is not None and engine.action_catalog[s].display_name == 'Survivor Cinder Breath'
                   for s in engine.state.actors[ALLY].action_ids)


def test_native_printed_fear_source_consumes_the_grant(tmp_path):
    combat, table, mid = setup(tmp_path)
    use(combat, table, mid)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Dread Appetite')  # foe's Frighten option, printed as 'Dread Appetite: Frighten'
    engine = reload(tmp_path, mid)
    assert last_save(engine).payload['mode'] == 'ADVANTAGE'
    assert not grants(engine, OWNER)


def test_common_expression_does_not_acquire_awakened_breath(tmp_path):
    combat, table, mid = setup(tmp_path, stage='Common Expression')
    engine = reload(tmp_path, mid)
    assert not any(engine.action_catalog[s].display_name == 'Survivor Cinder Breath'
                   for s in engine.state.actors[OWNER].action_ids)


def test_exact_thirty_feet_and_recipient_owned_save(tmp_path):
    combat, table, mid = setup(tmp_path, target_position={'x': 3, 'y': 12})
    use(combat, table, mid, target=ALLY)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Threat fear', OWNER)
    engine = reload(tmp_path, mid)
    assert last_save(engine).payload['mode'] == 'NORMAL'
    assert grants(engine, ALLY)
    use(combat, table, mid, 'Threat fear', ALLY)
    engine = reload(tmp_path, mid)
    assert last_save(engine).payload['mode'] == 'ADVANTAGE'
    assert not grants(engine, ALLY)


def test_ordinary_damage_strips_hp_without_consuming_the_save(tmp_path):
    combat, table, mid = setup(tmp_path)
    use(combat, table, mid)
    turn(table, mid, FOE)
    use(combat, table, mid, 'Ordinary strike')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].temporary_hp < 6
    assert grants(engine, OWNER)


@pytest.mark.parametrize('recipient_mode,recipient,accepted', [
    ('MANUAL', FOE, True), ('MANUAL', FOE, False),
    ('LOCAL_AUTO', ALLY, True), ('LOCAL_AUTO', FOE, True), ('LOCAL_AUTO', FOE, False)])
@pytest.mark.parametrize('owner_mode', ['LOCAL_AUTO', 'API_AUTO'])
def test_automatic_owner_preserves_recipient_decision(tmp_path, recipient_mode, recipient, accepted, owner_mode):
    from combat.gate4_adapters import ManualControllerAdapter
    from combat.gate2_runtime_models import ReactionDecision
    from combat.gate5_service import AI_RESPONSE_SCHEMA
    modes = {OWNER: owner_mode, ALLY: 'MANUAL', FOE: 'MANUAL'}
    modes[recipient] = recipient_mode
    # The Threat saves are free, repeatable foe actions for the save tests. An automatic foe
    # would spend its turns on them instead of ending it, so this consent test omits them.
    combat, table, mid = setup(tmp_path, modes=modes, threats=False)
    cid = candidate(combat, mid, 'Survivor Cinder Breath', target=recipient).candidate_id
    delegate = combat.controller

    class FakeProvider:
        calls = 0

        def status(self):
            return {'ready': True, 'provider_id': 'test:survivor-cinder'}

        def complete_json(self, *, prompt_text, system_message, purpose):
            assert purpose == 'combat_decision'
            self.calls += 1
            frame = json.loads(prompt_text.split('\n\n', 1)[1])
            selected = next(c for c in frame['legal_candidates'] if c['candidate_id'] == cid)
            # Copy only the creature-permitted legal frame; never synthesize
            # a hidden target, a successful consent answer or a state change.
            intent = {key: selected[key] for key in
                      ('candidate_id', 'actor_id', 'target_ids', 'destination')}
            intent.update(decision_id=frame['decision_id'], state_version=frame['state_version'],
                          option_ids=[])
            return {'value': {'schema': AI_RESPONSE_SCHEMA, 'action_intent': intent},
                    'provider_id': 'test:survivor-cinder', 'model': 'fake'}

    class FixedController:
        # Fake primary transport selects an actual legal candidate; normal
        # choice transport still decides the recipient's separate consent.
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

        def choose_reaction(self, context):
            if context.reaction_source_id == CONSENT:
                decision = ReactionDecision(checkpoint=context.checkpoint,
                    reactor_id=context.reactor_id, reaction_source_id=CONSENT,
                    selection='USE' if accepted else 'DECLINE',
                    option_ids=('accept',) if accepted else ())
                return ManualControllerAdapter(lambda _: (cid, ()),
                    reaction_chooser=lambda _: decision).choose_reaction(context)
            return delegate.choose_reaction(context)

        def __getattr__(self, name):
            return getattr(delegate, name)

    combat.controller = FixedController()
    provider = FakeProvider()
    combat.ai_provider = provider
    prompts = settle(table, mid, cid, auto=True, picks={CONSENT: 'accept' if accepted else None})
    assert bool(prompts) == (recipient_mode == 'MANUAL')
    engine = reload(tmp_path, mid)
    assert bool(grants(engine, recipient)) == accepted
    assert engine.state.actors[OWNER].resources[POOL] == (0 if accepted else 1)
    assert provider.calls == (1 if owner_mode == 'API_AUTO' else 0)


MECHANIC = 'foundation.ash_born_remnant_core_v0_2B.survivor_cinder_breath'


def test_shipped_authority_dispatches_only_the_reviewed_breath_effect():
    # Finding 1: the generated authority must not keep the old generic Temporary HP and
    # Advantage rows beside the reviewed single provider; the compiled action reads them.
    authority = json.loads((Path(__file__).resolve().parents[1] / 'authority' /
                            'Tianxia_Typed_Mechanics_Authority_R1.json').read_text())
    row = authority['mechanics'][MECHANIC]
    assert [effect['type'] for effect in row['effects']] == ['survivor_cinder_breath']
    assert row['typing_status'] == 'reviewed_final'
    assert row['coverage'] == 'FULL'
    assert 'model_v2_unchecked' not in json.dumps(row)


def test_compiled_breath_action_carries_only_the_reviewed_effect(tmp_path):
    # Finding 1 at runtime: the compiled Breath action must not carry a generic temp_hp or
    # advantage row beside the reviewed provider; that duplicate would grant HP twice.
    bundle = compile_character(sheet([SOURCE], cl=15, name='Wren'), actor_id=OWNER, reaction_plan={'ask': True})
    rows = [row for row in bundle['action_catalog'] if row.get('display_name') == 'Survivor Cinder Breath']
    assert len(rows) == 1
    blob = json.dumps(rows[0], sort_keys=True)
    assert 'survivor_cinder_breath' in blob
    assert '"temp_hp"' not in blob or blob.count('"temp_hp"') == 0
    assert 'model_v2_unchecked' not in blob


def test_no_agent_written_gm_disposition_for_the_seven_families():
    # Finding 2 (whole record): the seven non-fear families have no catalogued source and no
    # GM adjudication in this record. The shipped row must not claim one; the gap is recorded
    # as an explicit residual in the fix report, not as a reviewer note.
    authority = json.loads((Path(__file__).resolve().parents[1] / 'authority' /
                            'Tianxia_Typed_Mechanics_Authority_R1.json').read_text())
    row = authority['mechanics'][MECHANIC]
    assert 'GM-adjudicated' not in json.dumps(row)
    assert 'seven non-fear families' not in json.dumps(row)
