"""Brute/Wrestling replacement choices through committed native tables.

No remaining-slot receipt, feature, condition or budget is installed by a test.
Extra Attack comes from the actual Body Refining feature; Pin's hold is a real
Grapple on the preceding turn. Portable sheets are imported through compilation
and CombatService, and every continuation crosses a fresh-service reload.
"""
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from combat import menu_rank
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext.special_attacks import FLAG, REST
from combat.ext.hand_occupancy import weapon_allowed, weapon_requirement
from tests.equipment_readiness import ready_table_weapon
from tests.h1_support import sheet
from tests.worker2_support import settle
from tests.test_agent_seats import runner_for

ROOT = Path(__file__).resolve().parents[1]
ME, FOE = 'actor:factory.slot-owner', 'actor:factory.slot-foe'
EXTRA = 'tianxia.path.body_refining.feature.extra_attack'
PIN = 'TAL_WRESTLING_PIN_2'
SHOVE = 'BRUTE_BASE_BRUTAL_SHOVE'
WRESTLE = 'WRESTLING_BASE_SPECIAL_ATTACKS'
BRUTE = 'BRUTE_BASE_SPECIAL_ATTACKS'
WEAPON = 'Fu (Short Axe) attack'
CONT = ' (replace remaining attacks)'
START = ' (one attack; choose the rest)'
ORDINARY = ' (rest of the Attack action)'
KIT = {'starting_kit': {'items': [{'item_id': 'tianxia.mortal.weapon.fu', 'name': 'Fu (Short Axe)', 'quantity': 1}]}}

# Literal dynamic registry resources for public-test export (not owner data).
REGISTRY_DEPENDENCIES = (
    'combat_gate1/generated/Battlefield.json',
    'combat_gate1/generated/Encounter.json',
    'combat_gate2/generated/Gate2_Executable_Mechanics_Lock.json',
    'combat_gate2/generated/Gate2_Universal_Combat_Defaults_Lock.json',
    'tests/test_review_sw-athletics.py',
)


@pytest.fixture(autouse=True)
def offline_embedding(monkeypatch):
    monkeypatch.setattr(menu_rank, '_CLIENT', SimpleNamespace(
        embed=lambda texts: [[1.0, 0.0] for _ in texts], prefetch=lambda *a, **k: None))


def build(tmp_path, sphere, *, cl=10, extra=True, far=False, talents=(), ready=True):
    mids = [BRUTE] if sphere == 'brute' else [WRESTLE, PIN] if sphere == 'wrestling' else []
    pb = 2 + (cl - 1) // 4
    owner = sheet([*mids, *talents], cl=cl, dc=8 + 5 + pb, score=20, primary='Stamina', kit=KIT, name='Slot Keeper')
    if sphere in ('brute', 'wrestling'):
        # Learning the sphere grants all its base definitions automatically.
        # The passive Special Attacks rule is never a purchased talent.
        owner['spheres_and_talents']['learned_talent_record_ids'] = ([PIN] if sphere == 'wrestling' else []) + list(talents)
    owner['identity']['proficiency_bonus'] = pb
    owner['identity']['path'] = 'Body Refining'
    owner['ability_scores_and_statistics']['initiative'] = {'bonus': 100}
    if extra:
        owner['path_and_subpath'] = {'path_record_ids': ['tianxia.path.body_refining'], 'path_feature_record_ids': [EXTRA]}
    foe = sheet([], cl=cl, score=1, primary='Stamina', name='Hold Target')
    foe['identity']['proficiency_bonus'] = pb
    for doc in (owner, foe):
        doc['ability_scores_and_statistics']['hit_points']['maximum'] = 1000
    docs = [(ME, owner), (FOE, foe)]
    for aid, doc in docs:
        folder = tmp_path / 'portable_characters' / aid.removeprefix('actor:factory.')
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / 'current.zip', 'w') as archive:
            archive.writestr('Tianxia_Owner_Character_Sheet_v1.json', json.dumps(doc))
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={'ask': True}) for aid, doc in docs]
    for bundle in bundles:
        ids = [a['source_definition_id'] for a in bundle['action_catalog']]
        assert len(ids) == len(set(ids)), 'composition must emit each canonical action exactly once'
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [ME, FOE], {ME: 'team:a', FOE: 'team:b'},
        {ME: {'x': 3, 'y': 6}, FOE: {'x': 8 if far else 4, 'y': 6}},
        combat.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [ME], [FOE],
        control_modes={ME: 'MANUAL', FOE: 'MANUAL'}, match_seed='SPECIAL-SLOTS',
        display_name='Special Attack replacement', maximum_rounds=12)['match_id']
    table = TabletopService(combat, tmp_path)
    while table.state(mid)['menu']['actor_id'] != ME:
        end(table, mid)
    engine = combat._load_session(mid).engine
    weapon = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == WEAPON)
    if ready:
        ready_table_weapon(table, mid, weapon.source_definition_id)
    elif weapon_allowed(engine, engine.state.actors[ME], weapon) is not False:
        identity, _ = weapon_requirement(engine, weapon)
        stow = next(c for c in engine.legal_candidates()
                    if (a := engine.action_catalog.get(c.source_definition_id)) is not None
                    and (grip := a.parameters.get('equipment_grip'))
                    and grip['weapon'] == identity and not grip['held'])
        settle(table, mid, stow.candidate_id)
    if sphere == 'wrestling' and not far:
        use(combat, table, mid, 'Grapple')
        assert not combat._load_session(mid).engine.state.actors[ME].action_available
        end(table, mid)
        end(table, mid)
        assert any(c.condition_id == 'condition:typed.grappled' for c in combat._load_session(mid).engine.state.actors[FOE].conditions.values())
    return combat, table, mid


def end(table, mid):
    settle(table, mid, table.state(mid)['menu']['end_turn'])


def options(combat, mid):
    engine = combat._load_session(mid).engine
    return {engine.action_catalog[c.source_definition_id].display_name: c
            for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog and c.actor_id == ME}


def use(combat, table, mid, label):
    before = len(combat._load_session(mid).engine.events)
    candidate = options(combat, mid).get(label)
    assert candidate is not None, (label, sorted(options(combat, mid)))
    settle(table, mid, candidate.candidate_id)
    return combat._load_session(mid).engine.events[before:]


def cold(tmp_path, combat, mid):
    previous = combat._load_session(mid).engine.state.model_dump(mode='json')
    fresh = CombatService(ROOT, tmp_path)
    session = fresh._load_session(mid)
    assert session.engine.state.model_dump(mode='json') == previous
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return fresh, TabletopService(fresh, tmp_path), session.engine


@pytest.mark.parametrize('sphere,special,event', [('brute', 'Shove Aside', 'CHECK_ROLLED'), ('wrestling', 'Pin', 'SAVE_ROLLED')])
@pytest.mark.parametrize('cl,count', [(5, 2), (11, 3), (17, 4)])
@pytest.mark.parametrize('order', ['special-special', 'special-ordinary', 'ordinary-special'])
def test_native_mixed_slots_survive_each_commit_and_cold_continuation(tmp_path, sphere, special, event, cl, count, order):
    combat, table, mid = build(tmp_path, sphere, cl=cl)
    engine = combat._load_session(mid).engine
    initial = dict(engine.state.actors[ME].resources)
    assert engine.state.actors[ME].action_available
    assert not any(n.endswith((CONT, ORDINARY)) for n in options(combat, mid))
    sequence = ([WEAPON + START] + [WEAPON + ORDINARY] * (count - 2) + [special + CONT]
                if order == 'ordinary-special' else
                [special] + [WEAPON + ORDINARY] * (count - 1) if order == 'special-ordinary' else
                [special] + [special + CONT] * (count - 1))
    for index, label in enumerate(sequence):
        events = use(combat, table, mid, label)
        expected = 'ATTACK_ROLLED' if label.startswith(WEAPON) else event
        roller = FOE if expected == 'SAVE_ROLLED' else ME
        assert sum(e.event_type == expected and e.actor_id == roller for e in events) == 1, [(e.event_type, e.actor_id) for e in events]
        combat, table, engine = cold(tmp_path, combat, mid)
        actor = engine.state.actors[ME]
        assert actor.action_available is False and actor.bonus_action_available is True
        assert int(actor.turn_flags.get(FLAG) or 0) == count - index - 1
        assert actor.resources == initial
        names = options(combat, mid)
        assert WEAPON not in names and WEAPON + START not in names
        if index < count - 1:
            assert special + CONT in names and WEAPON + ORDINARY in names
        else:
            assert not any(n.endswith((CONT, ORDINARY)) for n in names)
    end(table, mid)
    end(table, mid)
    combat, table, engine = cold(tmp_path, combat, mid)
    assert FLAG not in engine.state.actors[ME].turn_flags
    assert engine.state.actors[ME].action_available
    assert not any(n.endswith((CONT, ORDINARY)) for n in options(combat, mid))


@pytest.mark.parametrize('sphere', ['brute', 'wrestling'])
def test_single_attack_and_wrong_owner_do_not_gain_free_continuations(tmp_path, sphere):
    combat, table, mid = build(tmp_path, sphere, extra=False)
    use(combat, table, mid, 'Shove Aside' if sphere == 'brute' else 'Pin')
    combat, table, engine = cold(tmp_path, combat, mid)
    assert not engine.state.actors[ME].action_available
    assert not engine.state.actors[ME].turn_flags.get(FLAG)
    assert not any(a.parameters.get(REST) for a in engine.action_catalog.values() if a.owner_id == ME)
    other, _, other_mid = build(tmp_path / 'wrong-owner', 'none', cl=17)
    assert not any(n.endswith((CONT, START, ORDINARY)) for n in options(other, other_mid))


def test_weapon_backed_special_keeps_one_canonical_continuation_and_unique_catalog_ids(tmp_path):
    combat, _, mid = build(tmp_path, 'brute', talents=['TAL_BERSERKER_BATTER'])
    session = combat._load_session(mid)
    # The imported catalog and actor's sealed IDs must agree; a shared weapon
    # Special Attack must not be emitted by both loops in replacement_actions.
    actor = session.engine.state.actors[ME]
    assert len(actor.action_ids) == len(set(actor.action_ids))
    rows = [a for a in session.engine.action_catalog.values() if a.owner_id == ME
            and ((a.parameters or {}).get('typed') or {}).get('maneuver') == 'batter'
            and (a.parameters or {}).get(REST)]
    assert rows
    assert all(sum(int(e.get('count') or 1) for e in a.parameters['typed']['effects'] if e.get('type') == 'attack') == 1 for a in rows)


def test_withering_hand_ranged_action_is_not_a_free_attack_replacement(tmp_path):
    combat, table, mid = build(tmp_path, 'none', talents=['TAL_DEATH_WITHERING_HAND'])
    engine = combat._load_session(mid).engine
    catalog = [a for a in engine.action_catalog.values() if a.owner_id == ME]
    melee = next(a for a in catalog if a.display_name == 'Withering Hand')
    ranged = next(a for a in catalog if a.display_name == 'Withering Hand (ranged)')
    assert not melee.parameters.get('replaces_attack', 0)
    assert melee.parameters['typed']['source'] == 'TAL_DEATH_WITHERING_HAND'
    assert ranged.parameters['replaces_attack'] == 0
    assert 'Withering Hand (ranged)' in options(combat, mid), 'the ordinary ranged Action must remain available'

    use(combat, table, mid, 'Withering Hand')
    combat, table, engine = cold(tmp_path, combat, mid)
    names = options(combat, mid)
    assert 'Withering Hand (replace remaining attacks)' in names
    assert 'Withering Hand (ranged) (replace remaining attacks)' not in names
    ranged_continuations = [a for a in engine.action_catalog.values()
                            if a.owner_id == ME and a.source_definition_id.startswith(ranged.source_definition_id)
                            and (a.parameters or {}).get(REST)]
    assert not ranged_continuations


@pytest.mark.parametrize('bonus', [False, True])
def test_explicit_overrun_economy_never_spends_or_grants_attack_slots(tmp_path, bonus):
    combat, table, mid = build(tmp_path, 'brute')
    use(combat, table, mid, 'Overrun (Bonus Action)' if bonus else 'Overrun')
    combat, table, engine = cold(tmp_path, combat, mid)
    actor = engine.state.actors[ME]
    assert actor.action_available is bonus
    assert actor.bonus_action_available is not bonus
    assert not actor.turn_flags.get(FLAG)
    assert not any(n.startswith('Overrun') and n.endswith(CONT) for n in options(combat, mid))


def test_pin_continuation_requires_actual_hold_and_range(tmp_path):
    combat, table, mid = build(tmp_path, 'wrestling', far=True)
    assert 'Pin' not in options(combat, mid)
    # A real ordinary ranged target is unnecessary: without a legal initial
    # Attack action, no continuation can authorize itself or fabricate a hold.
    assert not any(n.endswith(CONT) for n in options(combat, mid))
    assert combat._load_session(mid).engine.state.actors[ME].action_available


def test_releasing_actual_hold_removes_pin_but_keeps_ordinary_remaining_attack(tmp_path):
    combat, table, mid = build(tmp_path, 'wrestling')
    use(combat, table, mid, 'Pin')
    assert 'Pin' + CONT in options(combat, mid)
    use(combat, table, mid, 'Release grapple')
    combat, table, engine = cold(tmp_path, combat, mid)
    assert 'Pin' + CONT not in options(combat, mid)
    assert WEAPON + ORDINARY in options(combat, mid)
    assert engine.state.actors[ME].turn_flags[FLAG] == 1
    use(combat, table, mid, WEAPON + ORDINARY)
    _, _, engine = cold(tmp_path, combat, mid)
    assert engine.state.actors[ME].turn_flags[FLAG] == 0


@pytest.mark.parametrize('sphere,special', [('brute', 'Shove Aside'), ('wrestling', 'Pin')])
def test_special_weapon_special_can_fill_one_three_attack_action(tmp_path, sphere, special):
    combat, table, mid = build(tmp_path, sphere, cl=11)
    for label, remaining in [(special, 2), (WEAPON + ORDINARY, 1), (special + CONT, 0)]:
        use(combat, table, mid, label)
        combat, table, engine = cold(tmp_path, combat, mid)
        assert engine.state.actors[ME].turn_flags[FLAG] == remaining
        assert not engine.state.actors[ME].action_available
        assert engine.state.actors[ME].bonus_action_available


def test_unspent_slots_expire_at_natural_turn_transition_after_table_reload(tmp_path):
    combat, table, mid = build(tmp_path, 'wrestling')
    use(combat, table, mid, 'Pin')
    combat, table, engine = cold(tmp_path, combat, mid)
    assert engine.state.actors[ME].turn_flags[FLAG] == 1
    end(table, mid)
    end(table, mid)
    combat, table, engine = cold(tmp_path, combat, mid)
    assert FLAG not in engine.state.actors[ME].turn_flags
    assert engine.state.actors[ME].action_available
    assert not any(n.endswith((CONT, ORDINARY)) for n in options(combat, mid))


def test_bonus_action_between_specials_keeps_the_same_attack_slots(tmp_path):
    combat, table, mid = build(tmp_path, 'brute')
    use(combat, table, mid, 'Shove Aside')
    assert 'Overrun' not in options(combat, mid)
    use(combat, table, mid, 'Overrun (Bonus Action)')
    combat, table, engine = cold(tmp_path, combat, mid)
    actor = engine.state.actors[ME]
    assert actor.turn_flags[FLAG] == 1
    assert not actor.action_available and not actor.bonus_action_available
    use(combat, table, mid, 'Shove Aside' + CONT)
    _, _, engine = cold(tmp_path, combat, mid)
    assert engine.state.actors[ME].turn_flags[FLAG] == 0
    assert not engine.state.actors[ME].bonus_action_available


def test_continuation_weapon_still_requires_committed_equipment_readiness(tmp_path):
    combat, table, mid = build(tmp_path, 'wrestling', ready=False)
    use(combat, table, mid, 'Pin')
    assert WEAPON + ORDINARY not in options(combat, mid)
    assert 'Pin' + CONT in options(combat, mid)
    engine = combat._load_session(mid).engine
    weapon = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == WEAPON)
    ready_table_weapon(table, mid, weapon.source_definition_id)
    combat, table, engine = cold(tmp_path, combat, mid)
    assert WEAPON + ORDINARY in options(combat, mid)
    assert not engine.state.actors[ME].action_available
    use(combat, table, mid, WEAPON + ORDINARY)
    _, _, engine = cold(tmp_path, combat, mid)
    assert engine.state.actors[ME].turn_flags[FLAG] == 0


def test_paid_special_continuation_keeps_native_payment_and_once_rest_counter(tmp_path):
    talent = 'TAL_WRESTLING_HEAVEN_LIFTING_THROW'
    combat, table, mid = build(tmp_path, 'wrestling', cl=17, talents=[
        'TAL_WRESTLING_MOUNTAIN_CRASHING_SUPLEX', talent])
    use(combat, table, mid, 'Pin')
    engine = combat._load_session(mid).engine
    original = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == 'Heaven-Lifting Throw')
    replacement = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == 'Heaven-Lifting Throw' + CONT)
    assert original.costs == replacement.costs and original.costs
    assert original.parameters['typed'] == replacement.parameters['typed']
    before = dict(engine.state.actors[ME].resources)
    use(combat, table, mid, replacement.display_name)
    combat, table, engine = cold(tmp_path, combat, mid)
    actor = engine.state.actors[ME]
    for resource, amount in original.costs:
        assert actor.resources[resource] == before[resource] - amount
    assert any(resource.startswith('resource:uses.') for resource, _ in original.costs)
    assert actor.turn_flags[FLAG] == 2
    assert actor.action_available is False and actor.bonus_action_available is True
    assert 'Heaven-Lifting Throw' + CONT not in options(combat, mid)
    assert 'Pin' + CONT not in options(combat, mid), 'throwing ends the actual hold'


@pytest.mark.parametrize('sphere,special', [('brute', 'Shove Aside'), ('wrestling', 'Pin')])
def test_model_seat_selects_special_continuation_from_its_real_menu(tmp_path, sphere, special):
    combat, table, mid = build(tmp_path, sphere)
    use(combat, table, mid, special)
    combat, table, _ = cold(tmp_path, combat, mid)
    prompts = []
    def provider(config, prompt, png):
        prompts.append(prompt)
        legal = json.loads(prompt.split('\n', 1)[1])['legal_menu']
        if 'ability' in legal:
            opts = (legal.get('choice') or {}).get('options') or []
            return json.dumps({'selection': 'USE', 'option_ids': [opts[0]['id']] if opts else [], 'spend': 0}), None
        selected = next(k for k, v in legal.items() if v['action'] == special + CONT)
        return json.dumps({'plan': [selected]}), None
    runner, _ = runner_for(tmp_path, table, provider, render_png=lambda view: None)
    runner.set_seat(mid, ME, 'MODEL', 'fake')
    runner.set_seat(mid, FOE, 'MODEL', 'fake')
    for _ in range(12):
        if combat._load_session(mid).engine.state.actors[ME].turn_flags[FLAG] == 0:
            break
        assert runner.drive(mid, max_steps=1) == 1
    assert prompts and any(d.get('status') == 'COMMITTED' for d in runner.decisions(mid))
    _, _, engine = cold(tmp_path, combat, mid)
    assert engine.state.actors[ME].turn_flags[FLAG] == 0
    assert not engine.state.actors[ME].action_available
    assert engine.state.actors[ME].bonus_action_available
