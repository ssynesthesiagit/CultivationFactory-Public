"""Mud-Lotus roll scopes: Witness paid bonus, skill and category matching, Medicine checks inside the native scope.

Covers the printed Witness triggers this branch exercises: Medicine and Survival checks (skill-tagged) and poisoned/disease
typed saves. Disease-treatment and Poison-treatment are a named gap: no authority save carries those tags yet.
"""
from pathlib import Path
from types import SimpleNamespace

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent, Position
from combat.gate4_engine import Gate4ControllerEngine
from combat.ext import d20_rewrite
from combat.ext import foundation_conversion_bonus as fcb
from combat.ext import foundations4_rolls as rolls
from tests.test_auto_tabik import _engine, ME
from tests.equipment_readiness import ready_weapon

ROOT = Path(__file__).resolve().parents[1]
ALLY = 'actor:mud_lotus_scope_ally'
FOE = 'actor:mud_lotus_scope_foe'
RESTRAINED = 'condition:typed.restrained'
MEDICINE = 'TAL_IRON_FIST_MEDICINE_OF_THE_CLOSED_GATE'
CYCLONE = 'TAL_AIR_CYCLONE_PRISON'


def _sheet(ids, sphere=None):
    return {
        'identity': {'proficiency_bonus': 4, 'cultivation_level': 10, 'path': 'Qi Cultivation', 'key_ability': 'WIS'},
        'ability_scores_and_statistics': {
            'abilities': [{'ability': a, 'score': 14, 'modifier': 2} for a in ('STR', 'DEX', 'CON', 'INT', 'WIS', 'CHA')],
            'primary_resource': {'name': 'Qi', 'maximum': 30}, 'armor_class': {'base_value': 14},
            'hit_points': {'maximum': 60}, 'speed': {'walking_ft': 30}, 'technique_save_dc': 15,
            'technique_attack_bonus': 8},
        'spheres_and_talents': {'sphere_record_ids': [sphere] if sphere else [], 'learned_talent_record_ids': list(ids)},
        'equipment': [{'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.jian', 'quantity': 1}]}}],
    }


def _treatment_engine(dc):
    bundles = (compile_character(_sheet([MEDICINE], 'tianxia.sphere.iron_fist'), actor_id=ME),
               compile_character(_sheet([CYCLONE], 'tianxia.sphere.air'), actor_id=FOE),
               compile_character(_sheet([]), actor_id=ALLY))
    teams = {ME: 'team:a', ALLY: 'team:a', FOE: 'team:b'}
    engine = Gate4ControllerEngine(ROOT, match_seed='MUD-LOTUS-SCOPE', typed_bundles=bundles,
                                   roster_setup={'primary_actor_ids': list(teams), 'team_by_actor': teams,
                                                 'starting_positions': {ME: {'x': 3, 'y': 6}, ALLY: {'x': 3, 'y': 9}, FOE: {'x': 12, 'y': 6}}})
    engine.state.current_slot_index = engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    ally = engine.state.actors[ALLY]
    ally.position = Position(x=4, y=6)
    source = next(k for k, action in engine.action_catalog.items() if action.owner_id == FOE and 'CYCLONE_PRISON' in k)
    engine._apply_condition(ally, RESTRAINED, source, FOE, expires_on='UNTIL_REMOVED',
                            data={'origin_save': {'ability': 'STR', 'dc': dc}})
    return engine, ally


def _use(engine, name, target):
    actor_id = engine.state.current_actor_id
    actor = engine.state.actors[actor_id]
    actor.action_available = actor.bonus_action_available = True
    ready_weapon(engine, name, actor_id)
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name and target in c.target_ids)
    engine.execute_intent(ActionIntent(intent_id='mud-lotus-medicine', decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=actor_id, target_ids=candidate.target_ids,
                                       destination=candidate.destination))

WITNESS = 'foundation.mud_lotus_dantian_v0_2A.humble_medicine_witness'
LOTUS = 'foundation.mud_lotus_dantian_v0_2A.refined_lotus_recovery'


def _stub_pool(monkeypatch):
    monkeypatch.setattr(rolls, 'pool_id', lambda actor, name: 'resource:test.pool')
    monkeypatch.setattr(rolls, '_holds', lambda engine, actor, resource, amount: True)


def _check(skill=None, named=(), ability='WIS'):
    return SimpleNamespace(kind='check', ability=ability, named=list(named), skill=skill)


def test_witness_roll_adds_the_shared_provider_bonus(monkeypatch):
    # Before the fix the Witness added only its base PB; the shared provider was never read for it.
    seen = []

    def quote(engine, actor, conversion, receipt_id=None):
        seen.append(conversion)
        return 3 if conversion == 'humble_medicine_witness' else 0
    monkeypatch.setattr(fcb, 'conversion_bonus', quote)
    holder = SimpleNamespace(feature_id=WITNESS, numbers={'pb': 3}, actor=SimpleNamespace())
    assert rolls.roll_bonus(None, holder, SimpleNamespace(roll=SimpleNamespace(roll_id='r'))) == 6
    assert seen == ['humble_medicine_witness']


def test_witness_settles_its_own_receipt(monkeypatch):
    settled = []
    monkeypatch.setattr(fcb, 'settle_conversion_bonus',
                        lambda engine, actor, conversion, receipt_id, source_id: settled.append((conversion, receipt_id, source_id)) or 3)
    holder = SimpleNamespace(feature_id=WITNESS, numbers={'pb': 3}, actor=SimpleNamespace())
    rolls.settle_roll_bonus(None, holder, SimpleNamespace(roll=SimpleNamespace(roll_id='r')))
    assert settled == [('humble_medicine_witness', 'r', WITNESS)]


def test_witness_matches_a_medicine_or_survival_check_by_skill(monkeypatch):
    _stub_pool(monkeypatch)
    holder = SimpleNamespace(feature_id=WITNESS, actor=SimpleNamespace())
    assert rolls.guard('humble_medicine_witness')(None, holder, _check('Medicine')) is True
    assert rolls.guard('humble_medicine_witness')(None, holder, _check('Survival')) is True
    assert rolls.guard('humble_medicine_witness')(None, holder, _check('Stealth')) is False


def test_witness_matches_a_poisoned_or_disease_save_by_category(monkeypatch):
    _stub_pool(monkeypatch)
    holder = SimpleNamespace(feature_id=WITNESS, actor=SimpleNamespace())
    guard = rolls.guard('humble_medicine_witness')
    for word in ('poisoned', 'disease'):
        save = SimpleNamespace(kind='save', ability='CON', named=['category:' + word], skill=None)
        assert guard(None, holder, save) is True, word
    prone = SimpleNamespace(kind='save', ability='DEX', named=['category:prone'], skill=None)
    assert guard(None, holder, prone) is False


def test_skill_scope_is_read_from_the_native_check_scope(monkeypatch):
    # A Medicine check inside the native d20 scope carries its skill into RollCtx; a save under the same plumbing carries none.
    engine, _ = _engine([])
    with engine.d20_scope({'kind': 'check', 'actor_id': ME, 'reason': 'CHECK:test:medicine', 'ability': 'WIS', 'skill': 'Medicine'}):
        check = d20_rewrite.context_of(engine, engine.roller.d20(modifier=0, actor_id=ME, reason='CHECK:test:medicine'))
    with engine.d20_scope({'kind': 'save', 'actor_id': ME, 'reason': 'SAVE:test:con', 'ability': 'CON'}):
        save = d20_rewrite.context_of(engine, engine.roller.d20(modifier=0, actor_id=ME, reason='SAVE:test:con'))
    assert check.kind == 'check' and check.skill == 'Medicine'
    assert save.kind == 'save' and save.skill is None


def test_medicine_of_the_closed_gate_rolls_its_medicine_check_inside_a_skill_scope(monkeypatch):
    # Before the fix the treatment's d20 was drawn outside any d20_scope, so the Medicine skill never reached RollCtx.
    engine, _ally = _treatment_engine(1)
    seen = []
    original = engine.roller.d20

    def d20(**kwargs):
        record = original(**kwargs)
        if 'Medicine' in str(kwargs.get('reason') or ''):
            seen.append(d20_rewrite.context_of(engine, record))
        return record
    monkeypatch.setattr(engine.roller, 'd20', d20)
    _use(engine, 'Medicine of the Closed Gate', target=ALLY)
    assert len(seen) == 1
    assert seen[0].kind == 'check' and seen[0].skill == 'Medicine' and seen[0].ability == 'WIS'
    assert seen[0].dc == 15


def test_reed_and_clarity_keep_main_matching_on_bare_tags(monkeypatch):
    # Reed Recovery and Severing Clarity match the bare printed tag, exactly as on main.
    _stub_pool(monkeypatch)
    holder = SimpleNamespace(feature_id='foundation.x.reed_recovery', actor=SimpleNamespace())
    prone = SimpleNamespace(kind='save', ability='DEX', named=['prone'], skill=None)
    assert rolls.guard('reed_recovery')(None, holder, prone) is True
    clarity = SimpleNamespace(kind='check', ability='STR', named=['restrained'], skill=None)
    holder_c = SimpleNamespace(feature_id='foundation.x.severing_clarity', actor=SimpleNamespace())
    assert rolls.guard('severing_clarity')(None, holder_c, clarity) is True


BLACKBLOOD_PRINTED = ('blood_loss', 'poisoned', 'disease', 'corruption', 'forced_body_alteration', 'internal_body_disruption')
CLARITY_PRINTED = ('disarmed', 'weapon_binding', 'restrained', 'prone')


def test_typed_category_saves_do_not_reach_blackblood_clarity_or_reed(monkeypatch):
    # Regression for finding 1: stripping 'category:' for every kind gave players new spendable options on Blackblood
    # Refusal, Severing Clarity and Reed Recovery. Those rows keep main's exact matching, so a typed 'category:<tag>'
    # save does not qualify. Before the fix these asserted True.
    _stub_pool(monkeypatch)
    blackblood = SimpleNamespace(feature_id='foundation.x.blackblood_refusal', actor=SimpleNamespace())
    clarity = SimpleNamespace(feature_id='foundation.x.severing_clarity', actor=SimpleNamespace())
    reed = SimpleNamespace(feature_id='foundation.x.reed_recovery', actor=SimpleNamespace())
    for tag in BLACKBLOOD_PRINTED:
        save = SimpleNamespace(kind='save', ability='STR', named=['category:' + tag], skill=None)
        assert rolls.guard('blackblood_refusal')(None, blackblood, save) is False, tag
    for tag in CLARITY_PRINTED:
        roll = SimpleNamespace(kind='save', ability='STR', named=['category:' + tag], skill=None)
        assert rolls.guard('severing_clarity')(None, clarity, roll) is False, tag
        assert rolls.guard('reed_recovery')(None, reed, roll) is False, tag


def test_blackblood_keeps_main_matching_on_bare_tags(monkeypatch):
    _stub_pool(monkeypatch)
    holder = SimpleNamespace(feature_id='foundation.x.blackblood_refusal', actor=SimpleNamespace())
    bare = SimpleNamespace(kind='save', ability='STR', named=['poisoned'], skill=None)
    assert rolls.guard('blackblood_refusal')(None, holder, bare) is True
    unrelated = SimpleNamespace(kind='save', ability='STR', named=['prone'], skill=None)
    assert rolls.guard('blackblood_refusal')(None, holder, unrelated) is False
    con = SimpleNamespace(kind='save', ability='CON', named=['category:prone'], skill=None)
    assert rolls.guard('blackblood_refusal')(None, holder, con) is True


UNVERIFIED_WITNESS_TAGS = ('herbalism', 'water', 'life', 'flowers', 'alchemy', 'protection', 'cultivation', 'rot',
                           'polluted_water', 'sickness_exhaustion', 'poison', 'damage:poison', 'disease_treatment',
                           'poison_treatment', 'failed_medicine_backlash', 'terrain_contamination')


def test_witness_rejects_tags_with_no_authority_save_or_test(monkeypatch):
    # Regression for finding 2: a typed save tagged water/life/protection must not offer a paid +PB.
    # Before the fix these tags were in the Witness scope and this asserted True.
    _stub_pool(monkeypatch)
    holder = SimpleNamespace(feature_id=WITNESS, actor=SimpleNamespace())
    guard = rolls.guard('humble_medicine_witness')
    for tag in UNVERIFIED_WITNESS_TAGS:
        save = SimpleNamespace(kind='save', ability='WIS', named=['category:' + tag], skill=None)
        assert guard(None, holder, save) is False, tag
        check = SimpleNamespace(kind='check', ability='WIS', named=[], skill=tag.title())
        assert guard(None, holder, check) is False, tag
