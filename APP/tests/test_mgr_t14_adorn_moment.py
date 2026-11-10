"""Native aura/recipient regressions; not certification of Adorn's social checks."""
import json
from hashlib import sha256

import pytest

from combat.ext.beauty_adorn_base import ADORN, AURA, TONES
from combat.factory_compiler import compile_character
from tests.h1_support import ROOT, sheet
from tests.worker2_support import fixture, candidate, settle, reload, turn, OWNER, ALLY, FOE


def arena(tmp_path, **kw):
    document = sheet([ADORN])
    # Acquired base component, not a purchased talent or injected action.
    document['spheres_and_talents']['learned_talent_record_ids'] = []
    owner = compile_character(document, actor_id=OWNER, reaction_plan={'ask': True})
    return fixture(tmp_path, [], owner_bundle=owner, named=True, **kw)


def aura(engine, target):
    return next((c for c in engine.state.actors[target].conditions.values() if c.condition_id == AURA), None)


def use(combat, table, mid, label, target=OWNER, picks=None):
    return settle(table, mid, candidate(combat, mid, label, target=target).candidate_id, picks or {})


def test_source_hash_and_automatic_acquisition_packet():
    text = json.loads((ROOT / 'authority/typed_mechanics/rules_text.json').read_text())[ADORN]
    assert sha256(text.encode()).hexdigest() == '69732090cbb9e5c4feab1406e27eecdb7599be7763f7cd944b5a05d36c46e638'
    catalog = json.loads((ROOT / 'catalog_authority/cat3/generated/catalog_authority.v1.json').read_text())
    sphere = next(s for s in catalog['spheres'] if s['canonical_sphere_id'] == 'tianxia.sphere.beauty')
    packet = next(r for r in sphere['automatic_base_abilities'] if r['candidate_record_id'] == ADORN)
    assert packet['automatic_grant'] and not packet['counts_as_talent_choice']
    # CAT3 adds these two routing annotations to the otherwise exact source.
    lines = packet['full_exact_source_text'].splitlines()
    routing = ['Factory Combat Bucket: bonus_action', 'Factory Routing: combat_action_row']
    assert all(lines.count(line) == 1 for line in routing)
    assert '\n'.join(line for line in lines if line not in routing) == text


@pytest.mark.parametrize('tone', TONES)
def test_every_printed_aura_is_native_free_bonus_action_and_persists(tmp_path, tone):
    combat, table, mid = arena(tmp_path)
    before = reload(tmp_path, mid).state.actors[OWNER]
    qi = before.resources['resource:core.qi']
    use(combat, table, mid, f'Adorn the Moment: {tone.title()} aura')
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    held = aura(engine, OWNER)
    assert held and held.data['tone'] == tone
    assert held.expires_on == f'START_OF_SLOT_AT:{engine.state.round_number + 10}:{engine.state.current_slot_index}'
    assert actor.resources['resource:core.qi'] == qi
    assert not actor.bonus_action_available and actor.action_available
    assert not any(c.condition_id.endswith('check_mode') for c in actor.conditions.values())
    assert actor.modifiers == before.modifiers


@pytest.mark.parametrize('accept', [True, False])
def test_recipient_decides_on_another_creatures_turn_and_refusal_preserves_existing_use(tmp_path, accept):
    combat, table, mid = arena(tmp_path)
    use(combat, table, mid, 'Adorn the Moment: Radiant aura', ALLY,
        {'choice:willing.consent': 'accept'})
    turn(table, mid, FOE)
    settle(table, mid, table.state(mid)['menu']['end_turn']); turn(table, mid, OWNER)
    prompts = use(combat, table, mid, 'Adorn the Moment: Terrible aura', ALLY,
        {'choice:willing.consent': 'accept' if accept else 'refuse'})
    prompt = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:willing.consent')
    assert prompt['context']['reactor_id'] == ALLY
    assert 'Adorn the Moment' in str(prompt) and '1 minute' in str(prompt)
    assert aura(reload(tmp_path, mid), ALLY).data['tone'] == ('terrible' if accept else 'radiant')


@pytest.mark.parametrize('target', [ALLY, FOE])
def test_ai_recipient_uses_its_own_relation_for_consent(tmp_path, target):
    combat, table, mid = arena(tmp_path, foe_position={'x': 3, 'y': 5})
    # The shared fixture advances to the owner using manual end-turn buttons.
    # Change seats through the native service only after that setup is complete.
    for actor in (ALLY, FOE):
        combat.set_controller_mode(mid, actor_id=actor, controller_mode='LOCAL_AUTO')
    prompts = use(combat, table, mid, 'Adorn the Moment: Soft aura', target)
    assert not prompts
    assert bool(aura(reload(tmp_path, mid), target)) is (target == ALLY)


@pytest.mark.parametrize('accept', [True, False])
def test_existing_check_option_now_reaches_only_its_consenting_touch_recipient(tmp_path, accept):
    combat, table, mid = arena(tmp_path)
    prompts = use(combat, table, mid, 'Adorn the Moment: Advantage on Check', ALLY,
        {'choice:willing.consent': 'accept' if accept else 'refuse'})
    assert any(p['context']['reactor_id'] == ALLY for p in prompts)
    engine = reload(tmp_path, mid)
    for target in (OWNER, ALLY, FOE):
        applied = any(c.condition_id.endswith('check_mode') for c in engine.state.actors[target].conditions.values())
        assert applied is (accept and target == ALLY)


def test_touch_boundary_wrong_owner_and_replacement_in_both_directions(tmp_path):
    combat, table, mid = arena(tmp_path)
    engine = combat._load_session(mid).engine
    offered = [c for c in engine.legal_candidates() if 'aura' in c.display_name and 'Adorn the Moment' in c.display_name]
    assert {c.target_ids[0] for c in offered} == {OWNER, ALLY}
    assert not any(ADORN in a.source_definition_id for a in engine.action_catalog.values() if a.owner_id == FOE)
    use(combat, table, mid, 'Adorn the Moment: Advantage on Check')
    settle(table, mid, table.state(mid)['menu']['end_turn']); turn(table, mid, OWNER)
    use(combat, table, mid, 'Adorn the Moment: Elegant aura')
    actor = reload(tmp_path, mid).state.actors[OWNER]
    assert not any(c.condition_id.endswith('check_mode') for c in actor.conditions.values())
    assert aura(reload(tmp_path, mid), OWNER)
    settle(table, mid, table.state(mid)['menu']['end_turn']); turn(table, mid, OWNER)
    use(combat, table, mid, 'Adorn the Moment: Advantage on Check')
    engine = reload(tmp_path, mid)
    assert aura(engine, OWNER) is None
    assert any(c.condition_id.endswith('check_mode') for c in engine.state.actors[OWNER].conditions.values())


def test_one_minute_expires_through_real_turn_commits(tmp_path):
    combat, table, mid = arena(tmp_path)
    use(combat, table, mid, 'Adorn the Moment: Haunting aura')
    initial_round = reload(tmp_path, mid).state.round_number
    for _ in range(9):
        settle(table, mid, table.state(mid)['menu']['end_turn']); turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.round_number == initial_round + 9 and aura(engine, OWNER)
    settle(table, mid, table.state(mid)['menu']['end_turn']); turn(table, mid, OWNER)
    assert aura(reload(tmp_path, mid), OWNER) is None
