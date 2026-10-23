"""Lotus-Root native admission, actual Dew payment, cold reload and replay.

Initial Foundation data is built by the authentic installation resolver. Scenario
pressure actions are deterministic authored inputs; no successful receipt,
resource gain, condition or recovery result is injected into runtime state.
"""
import hashlib
import json
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from non_sphere_authority.foundation_mechanics import (
    installed_foundation_state, resolve_initial_foundation_mechanics, verified_foundation_records,
)
from tests.h1_support import sheet
from tests.test_a2_foundations3 import add_action, use, pool, BOON
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, turn, reload

APP = Path(__file__).resolve().parents[1]
# Literal dynamic compiler/source dependencies for safe-export discovery.
INPUTS = ('APP/non_sphere_authority/authority/qi_cultivation.path_index.p2a.json',
          'APP/non_sphere_authority/authority/body_refining.path_index.p2a.json',
          'APP/non_sphere_authority/authority/Tianxia_Foundations_Unified_Transparent_GM_Screen_Catalog_v0_4C.md',
          'APP/non_sphere_authority/authority/Foundation_Runtime_Authority_v0_4C.json',
          'APP/authority/typed_mechanics/rules_text.json',
          'APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json',
          'APP/combat/rules/feature_blocks.d/foundations3.json',
          'APP/authority/typed_mechanics/reviewed_final.d/foundations3.json')
FOUNDATION = 'mud_lotus_dantian_v0_2A'
LOTUS_ROOT = 'foundation.mud_lotus_dantian_v0_2A.lotus_root_recovery'
LOTUS_SUPPORT = 'choice:needle.lotus_root_support'
LOTUS_CONSENT = 'choice:needle.lotus_root_consent'
NAME = 'Lotus-Root Recovery'
CATEGORIES = ('poison', 'disease', 'rot', 'polluted_water', 'sickness_exhaustion',
              'failed_medicine_backlash', 'terrain_contamination')


def native_fixture(tmp_path, *, score=14, pb=4, stage='Awakened', subject=ALLY,
                   thp=0, distance=5, modes=None, corruption=None, blocked=False, path='qi_cultivation', key=None, reflect=False):
    record = verified_foundation_records()[FOUNDATION]
    mechanics = resolve_initial_foundation_mechanics(record, ['tianxia.path.' + path], stage=stage)
    installed = installed_foundation_state(mechanics, FOUNDATION, 'event:scenario.initial-foundation')
    # Published initial acquisition is CL5; use source-consistent CL/PB pairs.
    cl = {3: 5, 4: 9}[pb]
    key = key or ('CON' if path == 'body_refining' else 'INT')
    index_name = {'body_refining': 'body_refining.path_index.p2a.json',
                  'qi_cultivation': 'qi_cultivation.path_index.p2a.json'}[path]
    path_index = json.loads((APP / 'non_sphere_authority/authority' / index_name).read_text())
    source_options = path_index['path_profile']['key_ability']['options']
    full_key = {'CON': 'Constitution', 'INT': 'Intelligence', 'CHA': 'Charisma'}[key]
    assert full_key in source_options
    doc = sheet([], cl=cl, key=key, score=18, name='Lotus supporter')
    for ability in doc['ability_scores_and_statistics']['abilities']:
        if ability['ability'] == key:
            ability.update(score=score, modifier=(score - 10) // 2)
    doc['ability_scores_and_statistics']['technique_save_dc'] = 8 + pb + (score - 10) // 2
    doc['ability_scores_and_statistics']['technique_attack_bonus'] = pb + (score - 10) // 2
    label, primary = {'qi_cultivation': ('Qi Cultivation', 'Qi'),
                      'body_refining': ('Body Refining', 'Stamina'),
                      'spirit_awakening': ('Spirit Awakening', 'Resonance')}[path]
    doc['identity']['path'] = label
    doc['ability_scores_and_statistics']['primary_resource']['name'] = primary
    doc['identity']['proficiency_bonus'] = pb
    doc['foundation'] = installed
    assert installed['resource']['current'] == 0
    bundle = compile_character(doc, actor_id=OWNER, reaction_plan={'ask': True})

    def delivery(bundles):
        if reflect:
            reflector = sheet(['tianxia.talent.formations.reflecting_gate'], cl=9, key='INT', score=18)
            bundles[2] = compile_character(reflector, actor_id=FOE, reaction_plan={'ask': True})
        # Real earlier, dangerous poison saving throw; no seeded success/Dew.
        add_action(bundles[2], 'Poison exposure', [{'type': 'save', 'ability': 'CON',
            'save_categories': ['poison'], 'on_fail': [{'type': 'damage', 'flat': 1,
            'damage_types': ['poison'], 'applies_to': 'target'}], 'on_success': []}], economy='NONE', dc=6)
        if corruption is not None:
            data = {'recovery_support_exclusion': 'preserves_corruption'} if corruption else {}
            add_action(bundles[2], 'Authored source exposure', [{'type': 'condition',
                'condition': 'poisoned', 'condition_data': data,
                'duration': {'kind': 'minutes', 'amount': 1}, 'applies_to': 'target'}], economy='NONE')
        add_action(bundles[2], 'Dispel treatment support', [{'type': 'remove_condition',
            'condition': 'foundations3_boon.lotus', 'applies_to': 'target'}], economy='NONE')
        add_action(bundles[2], 'Direct damage', [{'type': 'damage', 'flat': 8,
            'damage_types': ['force'], 'applies_to': 'target'}], economy='NONE')
        for tag in (*CATEGORIES, 'force'):
            for index in (1, 2):
                add_action(bundles[index], 'Scope ' + tag, [{'type': 'save', 'ability': 'WIS',
                    'save_categories': [tag], 'on_fail': [{'type': 'damage', 'flat': 1,
                    'damage_types': ['force'], 'applies_to': 'target'}], 'on_success': []}],
                    target_kind='ANY_CREATURE', economy='NONE', dc=15)
        if thp:
            add_action(bundles[0], 'Earlier support', [{'type': 'temp_hp', 'flat': thp,
                       'applies_to': 'target'}], target_kind='ANY_CREATURE', economy='NONE')
    places = {OWNER: {'x': 3, 'y': 6}, ALLY: {'x': 3, 'y': 5}, FOE: {'x': 6, 'y': 6}}
    if subject == FOE:
        places[subject] = {'x': 3 + distance // 5, 'y': 6}
    from combat.tabletop import normalize_map, to_battlefield
    walls = [{'id': 'support-screen', 'shape': 'rect', 'points': [[6, 0], [7, 12]],
              'filled': True, 'blocks': 'sight_and_movement', 'height_ft': 30}] if blocked else []
    battlefield = to_battlefield(normalize_map({'display_name': 'Lotus recovery scene',
        'width_squares': 16, 'height_squares': 12, 'walls': walls}))
    if blocked:
        places.update({ALLY: {'x': 9, 'y': 5}, FOE: {'x': 9, 'y': 6}})
    if reflect:
        places.update({ALLY: {'x': 8, 'y': 6}, FOE: {'x': 9, 'y': 6}})
    combat, table, mid = fixture(tmp_path, [], cl=9, owner_bundle=bundle, seed='LOTUS-ROOT-NATIVE',
                                 positions=places, bundle_transform=delivery, modes=modes, battlefield=battlefield)
    if thp:
        use(combat, table, mid, 'Earlier support', subject)
    turn(table, mid, FOE)
    before_poison = reload(tmp_path, mid)
    # A qualifying danger must be able to fail; DC1 would be a guaranteed
    # success for this creature and cannot prove genuine recovery generation.
    minimum = 1 + before_poison.state.actors[ALLY].saving_throws.get('CON', 0)
    assert minimum < 6
    use(combat, table, mid, 'Poison exposure', ALLY)
    engine = reload(tmp_path, mid)
    save = [e for e in engine.events if e.event_type == 'SAVE_ROLLED'][-1]
    assert save.actor_id == ALLY and save.payload['success'] is True
    assert engine.state.actors[OWNER].resources[pool('lotus')] == 1
    if corruption is not None:
        use(combat, table, mid, 'Authored source exposure', ALLY)
    if reflect:
        from tests.worker2_support import settle
        settle(table, mid, candidate(combat, mid, 'Combat Array: Nourishing Cycle', at=(9, 6)).candidate_id)
    turn(table, mid, OWNER)
    return combat, table, mid


def support(combat, table, mid, subject, method='humble_recovery', accept=True):
    return use(combat, table, mid, NAME, subject,
               picks={LOTUS_SUPPORT: method, LOTUS_CONSENT: 'accept' if accept else None})


def test_exact_source_hash_and_installation_stage():
    texts = json.loads((APP / 'authority/typed_mechanics/rules_text.json').read_text())
    assert hashlib.sha256(texts[LOTUS_ROOT].encode()).hexdigest() == '565d8241caeebb75ea91408566a044482560b5a0b92d2239f47e59bb9d4918a4'
    from non_sphere_authority.foundation_features import features_for_stage
    for stage in ('Awakened', 'Refined', 'Perfected'):
        assert LOTUS_ROOT in {r['id'] for r in features_for_stage(FOUNDATION, stage)}
    assert LOTUS_ROOT not in {r['id'] for r in features_for_stage(FOUNDATION, 'Latent')}


@pytest.mark.parametrize('subject', [OWNER, ALLY, FOE])
@pytest.mark.parametrize('method', ['living_water', 'medicine', 'humble_recovery'])
def test_native_earned_payment_all_recovery_methods_and_willing_sides(tmp_path, subject, method):
    combat, table, mid = native_fixture(tmp_path, subject=subject)
    before = reload(tmp_path, mid)
    hp = before.state.actors[subject].current_hp
    prompts = support(combat, table, mid, subject, method)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('lotus')] == 0
    assert engine.state.actors[OWNER].bonus_action_available is False
    assert engine.state.actors[OWNER].action_available is True
    assert engine.state.actors[subject].temporary_hp == 6
    assert engine.state.actors[subject].current_hp == hp
    assert any(c.condition_id == BOON + 'lotus' for c in engine.state.actors[subject].conditions.values())
    receipts = [e for e in engine.events if e.source_definition_id == LOTUS_ROOT and e.payload.get('support_method')]
    assert len(receipts) == 1 and receipts[0].payload['support_method'] == method
    assert receipts[0].payload['consent_actor_id'] == subject
    if subject != OWNER:
        assert any(p['context']['reaction_source_id'] == LOTUS_CONSENT for p in prompts)
    gains = [e for e in engine.events if e.event_type == 'RESOURCE_GAINED' and e.payload.get('resource_id') == pool('lotus')]
    spends = [e for e in engine.events if e.event_type == 'RESOURCE_SPENT' and e.payload.get('resource_id') == pool('lotus')]
    grants = [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED' and e.source_definition_id.endswith('lotus_root_recovery')]
    assert len(gains) == len(spends) == len(grants) == 1
    assert gains[0].sequence < receipts[0].sequence < spends[0].sequence < grants[0].sequence
    assert not any(c.source_definition_id.endswith('lotus_root_recovery') for c in engine.legal_candidates())


@pytest.mark.parametrize('subject', [ALLY, FOE])
def test_unwilling_creature_keeps_earlier_dew_and_bonus_action(tmp_path, subject):
    combat, table, mid = native_fixture(tmp_path, subject=subject)
    support(combat, table, mid, subject, accept=False)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('lotus')] == 1
    assert engine.state.actors[OWNER].bonus_action_available
    assert engine.state.actors[subject].temporary_hp == 0
    assert not any(c.condition_id == BOON + 'lotus' for c in engine.state.actors[subject].conditions.values())


@pytest.mark.parametrize('missing', ['support', 'consent'])
def test_unanswered_native_persistent_intent_does_not_infer_permission(tmp_path, missing):
    from combat.gate2_runtime_models import ActionIntent, ReactionDecision
    from tests.worker2_support import act
    combat, table, mid = native_fixture(tmp_path)
    c = candidate(combat, mid, NAME, target=ALLY)
    preview = act(table, mid, c.candidate_id)
    assert preview['status'] == 'REACTION_REQUIRED'
    context = preview['reaction']['context']
    assert context['reaction_source_id'] == LOTUS_SUPPORT
    decisions = () if missing == 'support' else (ReactionDecision(
        checkpoint=context['checkpoint'], reactor_id=OWNER,
        reaction_source_id=LOTUS_SUPPORT, selection='USE', option_ids=('medicine',)),)
    intent = ActionIntent(intent_id='intent:lotus-root-missing-' + missing,
        decision_id=c.decision_id, candidate_id=c.candidate_id,
        state_version=c.state_version, actor_id=c.actor_id, target_ids=c.target_ids,
        destination=c.destination, reaction_decisions=decisions)
    # This is the real durable public persistent-session boundary. It accepts
    # an absent reaction provider; no controller, receipt or permission is faked.
    combat._load_session(mid).submit_intent(intent, primary_decision_record=None,
                                          reaction_provider=None)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('lotus')] == 1
    assert engine.state.actors[OWNER].bonus_action_available
    assert engine.state.actors[ALLY].temporary_hp == 0
    assert not any(c.condition_id == BOON + 'lotus' for c in engine.state.actors[ALLY].conditions.values())


def test_declared_corruption_preservation_is_refused_before_payment(tmp_path):
    combat, table, mid = native_fixture(tmp_path)
    support(combat, table, mid, ALLY, method='preserve_corruption')
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('lotus')] == 1
    assert engine.state.actors[OWNER].bonus_action_available
    assert engine.state.actors[ALLY].temporary_hp == 0


@pytest.mark.parametrize('score,pb,existing,expected', [(3, 3, 0, 0), (4, 3, 0, 0),
                         (8, 4, 0, 3), (14, 4, 8, 8), (14, 4, 3, 6)])
def test_signed_sum_and_ordinary_temp_hp_replacement(tmp_path, score, pb, existing, expected):
    combat, table, mid = native_fixture(tmp_path, score=score, pb=pb, thp=existing)
    support(combat, table, mid, ALLY)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == expected
    assert engine.state.actors[OWNER].resources[pool('lotus')] == 0
    assert any(c.condition_id == BOON + 'lotus' for c in engine.state.actors[ALLY].conditions.values())


@pytest.mark.parametrize('category', CATEGORIES)
@pytest.mark.parametrize('source', [ALLY, FOE])
def test_every_category_hostile_and_nonhostile_one_save_only(tmp_path, category, source):
    combat, table, mid = native_fixture(tmp_path)
    support(combat, table, mid, ALLY)
    turn(table, mid, source)
    use(combat, table, mid, 'Scope force', ALLY)
    engine = reload(tmp_path, mid)
    assert [e for e in engine.events if e.event_type == 'SAVE_ROLLED'][-1].payload['mode'] == 'NORMAL'
    assert any(c.condition_id == BOON + 'lotus' for c in engine.state.actors[ALLY].conditions.values())
    for expected in ('ADVANTAGE', 'NORMAL'):
        use(combat, table, mid, 'Scope ' + category, ALLY)
        engine = reload(tmp_path, mid)
        assert [e for e in engine.events if e.event_type == 'SAVE_ROLLED'][-1].payload['mode'] == expected
    assert not any(c.condition_id == BOON + 'lotus' for c in engine.state.actors[ALLY].conditions.values())


def test_owner_next_start_expiry_not_recipient_turn_and_temp_hp_remains(tmp_path):
    combat, table, mid = native_fixture(tmp_path)
    support(combat, table, mid, ALLY)
    turn(table, mid, ALLY)
    assert any(c.condition_id == BOON + 'lotus' for c in reload(tmp_path, mid).state.actors[ALLY].conditions.values())
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == BOON + 'lotus' for c in engine.state.actors[ALLY].conditions.values())
    assert engine.state.actors[ALLY].temporary_hp == 6


@pytest.mark.parametrize('distance,legal', [(30, True), (35, False)])
def test_native_map_range(tmp_path, distance, legal):
    combat, table, mid = native_fixture(tmp_path, subject=FOE, distance=distance)
    engine = reload(tmp_path, mid)
    rows = [c for c in engine.legal_candidates() if c.source_definition_id.endswith('lotus_root_recovery') and c.target_ids == (FOE,)]
    assert bool(rows) == legal
    if legal:
        support(combat, table, mid, FOE)
        assert reload(tmp_path, mid).state.actors[FOE].temporary_hp == 6


@pytest.mark.parametrize('corruption', [True, False])
def test_actual_authored_source_exclusion_not_condition_name(tmp_path, corruption):
    combat, table, mid = native_fixture(tmp_path, corruption=corruption)
    before = reload(tmp_path, mid)
    conditions = [c for c in before.state.actors[ALLY].conditions.values()
                  if c.condition_id == 'condition:typed.poisoned']
    assert len(conditions) == 1
    offers = [c for c in before.legal_candidates()
              if c.source_definition_id.endswith('lotus_root_recovery') and c.target_ids == (ALLY,)]
    assert bool(offers) is (not corruption)
    if not corruption:
        support(combat, table, mid, ALLY)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == (0 if corruption else 6)
    assert engine.state.actors[OWNER].resources[pool('lotus')] == (1 if corruption else 0)
    assert engine.state.actors[OWNER].bonus_action_available == corruption
    assert any(c.condition_id == 'condition:typed.poisoned'
               for c in engine.state.actors[ALLY].conditions.values())


def test_direct_damage_and_dispelled_support_remain_native_counterplay(tmp_path):
    combat, table, mid = native_fixture(tmp_path)
    support(combat, table, mid, ALLY)
    hp = reload(tmp_path, mid).state.actors[ALLY].current_hp
    turn(table, mid, FOE)
    use(combat, table, mid, 'Direct damage', ALLY)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == 0
    assert engine.state.actors[ALLY].current_hp == hp - 2
    use(combat, table, mid, 'Dispel treatment support', ALLY)
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == BOON + 'lotus' for c in engine.state.actors[ALLY].conditions.values())
    use(combat, table, mid, 'Scope disease', ALLY)
    assert [e for e in reload(tmp_path, mid).events if e.event_type == 'SAVE_ROLLED'][-1].payload['mode'] == 'NORMAL'


@pytest.mark.parametrize('accept', [True, False])
def test_manual_recipient_on_automatic_supporter_turn(tmp_path, accept):
    from combat.gate4_adapters import ManualControllerAdapter
    from tests.worker2_support import settle
    combat, table, mid = native_fixture(tmp_path)
    source = candidate(combat, mid, NAME, target=ALLY).source_definition_id
    original = combat.controller
    class OfflineController:
        def choose_primary_action(self, context):
            row = next(c for c in context.legal_candidates
                       if c.source_definition_id == source and c.target_ids == (ALLY,))
            return ManualControllerAdapter(lambda _: (row.candidate_id, ())).choose_primary_action(context)
        def choose_reaction(self, context):
            return original.choose_reaction(context)
    combat.controller = OfflineController()
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode='LOCAL_AUTO')
    prompts = settle(table, mid, None, auto=True,
                     picks={LOTUS_CONSENT: 'accept' if accept else None})
    consent = [p for p in prompts if p['context']['reaction_source_id'] == LOTUS_CONSENT]
    assert len(consent) == 1 and consent[0]['context']['reactor_id'] == ALLY
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == (6 if accept else 0)
    assert engine.state.actors[OWNER].resources[pool('lotus')] == (0 if accept else 1)


@pytest.mark.parametrize('subject,expected', [(ALLY, 6), (FOE, 0)])
def test_automatic_recipient_makes_its_own_decision(tmp_path, subject, expected):
    combat, table, mid = native_fixture(tmp_path, subject=subject)
    combat.set_controller_mode(mid, actor_id=subject, controller_mode='LOCAL_AUTO')
    prompts = support(combat, table, mid, subject)
    assert not any(p['context']['reaction_source_id'] == LOTUS_CONSENT for p in prompts)
    assert reload(tmp_path, mid).state.actors[subject].temporary_hp == expected


def test_model_transport_can_offer_and_accept_enemy_recovery(tmp_path):
    from agent_seats import SeatRunner
    from agent_seats.providers import ProviderRegistry
    combat, table, mid = native_fixture(tmp_path, subject=FOE)
    registry = tmp_path / 'offline-providers.json'
    registry.write_text(json.dumps({'providers': [{'id': 'fake', 'kind': 'local',
        'model': 'offline', 'base_url': 'http://127.0.0.1:1/v1', 'timeout_s': 2}]}))
    seen = []
    def transport(provider, prompt, png):
        assert png is None
        frame = json.loads(prompt.split('\n', 1)[1])
        legal = frame['legal_menu']
        seen.append(legal)
        if 'ability' in legal:
            options = (legal.get('choice') or {}).get('options', [])
            chosen = next((o for o in options if o['id'] == 'medicine'), options[0] if options else None)
            return json.dumps({'selection': 'USE', 'option_ids': [chosen['id']] if chosen else [], 'spend': 0}), None
        end = next(k for k, v in legal.items() if v['action'] == 'End turn')
        root = next((k for k, v in legal.items() if NAME in v['action'] and FOE in v['targets']), None)
        return json.dumps({'plan': [root, end] if root else [end]}), None
    runner = SeatRunner(table, registry=ProviderRegistry(registry), provider=transport, background=False)
    runner.set_seat(mid, OWNER, 'MODEL', 'fake')
    runner.set_seat(mid, FOE, 'MODEL', 'fake')
    runner.drive(mid, max_steps=6)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].temporary_hp == 6
    assert engine.state.actors[OWNER].resources[pool('lotus')] == 0
    decisions = runner.decisions(mid)
    assert any(r['kind'] == 'TURN' for r in decisions)
    assert any(r['kind'] == 'REACTION' for r in decisions)
    assert all(r.get('fallback') is None for r in decisions)
    assert seen


@pytest.mark.parametrize('path', ['body_refining', 'qi_cultivation'])
def test_installed_supported_path_uses_own_key_and_payment(tmp_path, path):
    combat, table, mid = native_fixture(tmp_path, path=path)
    support(combat, table, mid, ALLY)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == 6
    assert engine.state.actors[OWNER].resources[pool('lotus')] == 0


def test_latent_is_not_a_published_initial_installation():
    from app.core import FoundryError
    with pytest.raises(FoundryError):
        resolve_initial_foundation_mechanics(verified_foundation_records()[FOUNDATION],
            ['tianxia.path.qi_cultivation'], stage='Latent')


def test_native_solid_screen_retains_targeting_exclusion(tmp_path):
    combat, table, mid = native_fixture(tmp_path, blocked=True)
    engine = reload(tmp_path, mid)
    assert not any(c.source_definition_id.endswith('lotus_root_recovery')
                   and c.target_ids in ((ALLY,), (FOE,)) for c in engine.legal_candidates())
    assert any(c.source_definition_id.endswith('lotus_root_recovery')
               and c.target_ids == (OWNER,) for c in engine.legal_candidates())


def test_unsupported_spirit_path_is_not_an_installation_permission():
    from app.core import FoundryError
    with pytest.raises(FoundryError):
        resolve_initial_foundation_mechanics(verified_foundation_records()[FOUNDATION],
            ['tianxia.path.spirit_awakening'], stage='Awakened')


def test_qi_charisma_key_is_distinct_from_other_ability_modifiers(tmp_path):
    combat, table, mid = native_fixture(tmp_path, key='CHA', score=8)
    support(combat, table, mid, ALLY)
    engine = reload(tmp_path, mid)
    # PB4 + chosen Charisma(-1), not the other +4 ability modifiers.
    assert engine.state.actors[ALLY].temporary_hp == 3


@pytest.mark.parametrize('accept', [True, False])
def test_native_reflection_obtains_the_final_recipients_own_consent(tmp_path, accept):
    from tests.worker2_support import settle
    # Actual legal low-key cast DC9; actual reflector PB4/key4 check has a
    # minimum9. This makes the native counter reliable without replacing rolls.
    combat, table, mid = native_fixture(tmp_path, score=4, reflect=True)
    before = reload(tmp_path, mid)
    qi = before.state.actors[FOE].resources['resource:core.qi']
    prompts = settle(table, mid, candidate(combat, mid, NAME, target=ALLY).candidate_id,
        picks={LOTUS_SUPPORT: 'medicine', LOTUS_CONSENT: ('accept', 'accept' if accept else None),
               'choice:needle.reflecting_gate': 'redirect:' + FOE})
    consents = [p for p in prompts if p['context']['reaction_source_id'] == LOTUS_CONSENT]
    assert [p['context']['reactor_id'] for p in consents] == [ALLY, FOE]
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('lotus')] == 0
    assert engine.state.actors[OWNER].bonus_action_available is False
    assert engine.state.actors[FOE].resources['resource:core.qi'] == qi - 2
    assert engine.state.actors[ALLY].temporary_hp == 0
    assert engine.state.actors[FOE].temporary_hp == (1 if accept else 0)
    grants = [e for e in engine.events if e.event_type == 'TEMP_HP_GRANTED'
              and e.source_definition_id.endswith('lotus_root_recovery')]
    assert [e.target_ids for e in grants] == ([(FOE,)] if accept else [])


def test_human_controlled_friendly_recipient_is_always_asked(tmp_path):
    # Regression (lead review fix 1): a friendly default must not decide a human-controlled ally's
    # consent. Declining the real prompt keeps the temporary HP at zero and spends nothing.
    combat, table, mid = native_fixture(tmp_path, subject=ALLY)
    engine = reload(tmp_path, mid)
    assert (getattr(engine, 'typed_control_modes', None) or {}).get(ALLY, 'MANUAL') in ('MANUAL', 'SUGGESTED', 'MANUAL_AI_BRIDGE')
    prompts = support(combat, table, mid, ALLY, accept=False)
    consent = [p for p in prompts if p['context']['reaction_source_id'] == LOTUS_CONSENT]
    assert len(consent) == 1 and consent[0]['context']['reactor_id'] == ALLY
    engine = reload(tmp_path, mid)
    assert engine.state.actors[ALLY].temporary_hp == 0
    assert engine.state.actors[OWNER].resources[pool('lotus')] == 1


@pytest.mark.parametrize('corruption', [None, True])
def test_lotus_root_recipients_are_actual_recipients(tmp_path, corruption):
    # Regression (lead review fix 3): a creature excluded by a source contraindication is refused
    # before any prompt, so it takes no reactor slot. The Lotus-Root owner remains an enrolled
    # recipient of other supporters' casts (F7R lead1 fix: ownership must not filter consent).
    from combat.ext.foundations3 import lotus_root_recipients
    combat, table, mid = native_fixture(tmp_path, subject=ALLY, corruption=corruption)
    engine = reload(tmp_path, mid)
    ids = lotus_root_recipients(engine)
    assert ids is not None and OWNER in ids and FOE in ids
    assert (ALLY in ids) is (corruption is None)


@pytest.mark.parametrize('method', [None, 'preserve_corruption'])
def test_declined_or_corruption_preserving_support_pays_and_grants_nothing(tmp_path, method):
    # Regression (lead review fix 4): declining the support prompt, or choosing to preserve
    # corruption as health, must make no payment, grant no temporary HP or boon, fire no passive
    # and ask no consent. method None is a real DECLINE answer on the LOTUS_SUPPORT prompt.
    combat, table, mid = native_fixture(tmp_path, subject=ALLY)
    prompts = support(combat, table, mid, ALLY, method=method)
    assert not any(p['context']['reaction_source_id'] == LOTUS_CONSENT for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[pool('lotus')] == 1
    assert engine.state.actors[OWNER].bonus_action_available
    assert engine.state.actors[ALLY].temporary_hp == 0
    assert not any(c.condition_id == BOON + 'lotus' for c in engine.state.actors[ALLY].conditions.values())
    assert not [e for e in engine.events if e.source_definition_id == LOTUS_ROOT
                and e.event_type in ('PASSIVE_TRIGGERED', 'TEMP_HP_GRANTED')]
    assert not [e for e in engine.events if e.event_type == 'RESOURCE_SPENT'
                and e.payload.get('resource_id') == pool('lotus')]
