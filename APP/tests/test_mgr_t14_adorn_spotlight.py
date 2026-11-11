"""Shared Spotlight integration through native commits, consent and cold reload."""
import pytest

from combat.ext.beauty_adorn_base import TONES, is_adorn
from tests.test_mgr_t14_adorn_moment import aura, use
from tests.worker2_support import fixture, reload, settle, turn, OWNER, ALLY, FOE

SHARED = 'tianxia.talent.beauty.shared_spotlight'
CHECK = 'Adorn the Moment + Shared Spotlight: Advantage on Check'
STATUS = 'Test fixture: unrelated Poisoned condition'


def arena(tmp_path, with_status_probe=False, **kwargs):
    def status_probe(bundles):
        # A native generic condition isolates preservation from another sphere's
        # optional prepared-item provider. This is test setup, not an Adorn fact.
        from combat.canonical import canonical_sha256
        owner = bundles[0]
        source = 'action:test.adorn.unrelated_status'
        owner['action_catalog'].append({
            'source_definition_id': source, 'display_name': STATUS,
            'owner_id': OWNER, 'economy': 'NONE', 'resolution_kind': 'TYPED',
            'target_kind': 'ANY_CREATURE', 'range_ft': 5, 'costs': [],
            'parameters': {'free_primary': True, 'expected_damage': 0,
                           'typed': {'source': source, 'range_ft': 5, 'riders': [],
                                     'duration': {'kind': 'minutes', 'amount': 1},
                                     'effects': [{'type': 'condition', 'condition': 'Poisoned',
                                                  'applies_to': 'target', 'harmful': False}]}}})
        owner['actor_template']['action_ids'].append(source)
        owner.pop('bundle_sha256', None)
        owner['bundle_sha256'] = canonical_sha256(owner)
    return fixture(tmp_path, [SHARED], named=True,
                   bundle_transform=status_probe if with_status_probe else None, **kwargs)


def next_turn(table, mid):
    settle(table, mid, table.state(mid)['menu']['end_turn'])
    turn(table, mid, OWNER)


def check(engine, target):
    return any(c.condition_id.endswith('check_mode') and is_adorn(c.source_definition_id)
               for c in engine.state.actors[target].conditions.values())


def unrelated(engine, target):
    return {(c.condition_id, c.source_definition_id) for c in engine.state.actors[target].conditions.values()
            if not is_adorn(c.source_definition_id)}


@pytest.mark.parametrize('aura_first', [True, False])
def test_spotlight_check_replaces_each_recipients_aura_in_both_orders(tmp_path, aura_first):
    combat, table, mid = arena(tmp_path, with_status_probe=True)
    for aid in (OWNER, ALLY):
        use(combat, table, mid, STATUS, aid)
    before = {aid: unrelated(reload(tmp_path, mid), aid) for aid in (OWNER, ALLY)}
    assert all(before.values()), before
    if not aura_first:
        use(combat, table, mid, CHECK, ALLY)
        next_turn(table, mid)
    for aid in (OWNER, ALLY):
        use(combat, table, mid, 'Adorn the Moment: Elegant aura', aid)
        engine = reload(tmp_path, mid)
        assert aura(engine, aid) and not check(engine, aid)
        next_turn(table, mid)
    if aura_first:
        use(combat, table, mid, CHECK, ALLY)
    engine = reload(tmp_path, mid)
    for aid in (OWNER, ALLY):
        assert check(engine, aid) is aura_first
        assert bool(aura(engine, aid)) is not aura_first
        assert unrelated(engine, aid) == before[aid]


@pytest.mark.parametrize('tone', TONES)
def test_every_shared_aura_is_reachable_paid_once_and_reloads(tmp_path, tone):
    combat, table, mid = arena(tmp_path)
    initial = reload(tmp_path, mid)
    qi = initial.state.actors[OWNER].resources['resource:core.qi']
    prompts = use(combat, table, mid, f'Adorn the Moment + Shared Spotlight: {tone.title()} aura', ALLY)
    assert any(p['context']['reactor_id'] == ALLY and 'Shared Spotlight' in str(p) for p in prompts)
    engine = reload(tmp_path, mid)
    for aid in (OWNER, ALLY):
        assert aura(engine, aid).data['tone'] == tone
        assert unrelated(engine, aid) == unrelated(initial, aid)
        assert not check(engine, aid)
    assert aura(engine, FOE) is None
    owner = engine.state.actors[OWNER]
    assert owner.resources['resource:core.qi'] == qi
    assert owner.action_available and not owner.bonus_action_available


@pytest.mark.parametrize('accept', [True, False])
def test_shared_aura_consent_preserves_refusers_previous_use(tmp_path, accept):
    combat, table, mid = arena(tmp_path)
    use(combat, table, mid, CHECK, ALLY)
    next_turn(table, mid)
    use(combat, table, mid, 'Adorn the Moment + Shared Spotlight: Radiant aura', ALLY,
        {'choice:willing.consent': 'accept' if accept else 'refuse'})
    engine = reload(tmp_path, mid)
    assert aura(engine, OWNER).data['tone'] == 'radiant' and not check(engine, OWNER)
    assert bool(aura(engine, ALLY)) is accept
    assert check(engine, ALLY) is not accept


def test_shared_aura_ai_recipient_accepts_without_player_prompt(tmp_path):
    combat, table, mid = arena(tmp_path)
    combat.set_controller_mode(mid, actor_id=ALLY, controller_mode='LOCAL_AUTO')
    prompts = use(combat, table, mid, 'Adorn the Moment + Shared Spotlight: Soft aura', ALLY)
    assert not prompts
    assert all(aura(reload(tmp_path, mid), aid) for aid in (OWNER, ALLY))


@pytest.mark.parametrize('distance,offered', [(30, True), (35, False)])
def test_shared_aura_ally_range_boundary_and_ownership(tmp_path, distance, offered):
    combat, table, mid = arena(tmp_path, ally_position={'x': 3 + distance // 5, 'y': 6},
                             battlefield_transform=lambda field: field.update(terrain_regions=[]))
    engine = combat._load_session(mid).engine
    choices = [c for c in engine.legal_candidates()
               if c.display_name == 'Adorn the Moment + Shared Spotlight: Soft aura']
    assert bool(choices) is offered
    assert all(c.target_ids == (ALLY,) for c in choices)
    assert not any(a.parameters.get('shared_spotlight') for a in engine.action_catalog.values()
                   if a.owner_id in (ALLY, FOE))
    if offered:
        use(combat, table, mid, 'Adorn the Moment + Shared Spotlight: Soft aura', ALLY)
        assert all(aura(reload(tmp_path, mid), aid) for aid in (OWNER, ALLY))
