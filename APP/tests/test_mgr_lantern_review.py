"""Public, synthetic/native regressions for the Lantern review findings."""
import json
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT
from tests.test_mgr_lantern_native import (
    journey, declare_allies, declare_source, reload, cast,
    OWNER, ALLY, FOE, PARENT, POS, ALL,
)
from tests.worker2_support import turn, settle


def act(combat, state, kind, payload, actor=OWNER):
    return combat.journey_act(state['journey_id'], state['revision'], actor, kind, payload)


def test_field_menu_is_linear_and_every_ally_subset_remains_reachable(tmp_path):
    combat, s = journey(tmp_path, extra_allies=8)
    jid = s['journey_id']
    s = combat.journey_acquire_source(jid, s['revision'], OWNER, PARENT, {})
    companions = [a for a in s['actors'] if 'companion-' in a]
    s = declare_allies(combat, s, [ALLY, *companions])
    initial = combat.journey_menu(jid, OWNER)
    fields = [o for o in initial['options'] if o['kind'].startswith('lantern_field')]
    # One option per center, not 2**allies per center.
    assert fields and all(o['kind'] == 'lantern_field_prepare' for o in fields)
    assert len(fields) == len({json.dumps(o['payload']['position'], sort_keys=True) for o in fields})
    assert len(fields) <= 20 * 14 * 25  # map cells times legal height steps
    before_state = combat.journey_state(jid)
    with pytest.raises(ValueError):
        act(combat, s, fields[0]['kind'], fields[0]['payload'], ALLY)
    assert combat.journey_state(jid) == before_state
    s = act(combat, s, fields[0]['kind'], fields[0]['payload'])
    cancel = next(o for o in combat.journey_menu(jid, OWNER)['options'] if o['kind'] == 'lantern_field_cancel')
    s = act(combat, s, cancel['kind'], cancel['payload'])
    again = [o for o in combat.journey_menu(jid, OWNER)['options'] if o['kind'] == 'lantern_field_prepare']
    assert len(again) == len(fields)
    assert s['seconds'] == before_state['seconds']
    assert s['actors'][OWNER]['resources'] == before_state['actors'][OWNER]['resources']
    picked = again[-1]
    before = s['seconds'], s['actors'][OWNER]['resources']
    s = act(combat, s, picked['kind'], picked['payload'])
    center = picked['payload']['position']
    # Independent toggle for every ally makes all 2**N subsets reachable.
    for aid in [OWNER, ALLY, *companions, companions[0]]:
        options = CombatService(ROOT, tmp_path).journey_menu(jid, OWNER)['options']
        choices = [o for o in options if o['kind'].startswith('lantern_field')]
        assert len(choices) == len(companions) + 4  # self, ally, cast, cancel
        chosen = json.loads(s['actors'][OWNER]['source_states'][PARENT]['field_selection'])['chosen']
        expected = sorted(set(chosen) ^ {aid})
        toggle = next(o for o in choices if o['kind'] == 'lantern_field_prepare'
                      and o['payload']['chosen'] == expected)
        s = act(combat, s, toggle['kind'], toggle['payload'])
    assert (s['seconds'], s['actors'][OWNER]['resources']) == before
    assert CombatService(ROOT, tmp_path).journey_state(jid) == s
    final = next(o for o in combat.journey_menu(jid, OWNER)['options'] if o['kind'] == 'lantern_field')
    assert final['payload']['position'] == center
    assert set(final['payload']['chosen']) == {OWNER, ALLY, *companions[1:]}
    s = act(combat, s, final['kind'], final['payload'])
    field = json.loads(s['actors'][OWNER]['source_states'][PARENT]['field'])
    assert set(field['chosen']) == set(final['payload']['chosen'])
    assert s['actors'][OWNER]['resources']['resource:core.qi'] == 92
    assert CombatService(ROOT, tmp_path).journey_replay(jid)['status'] == 'PASS'


@pytest.mark.parametrize('traveler', [OWNER, ALLY])
def test_keeper_and_other_allies_can_take_the_menu_road(tmp_path, traveler):
    combat, s = journey(tmp_path, cl=6)
    jid = s['journey_id']
    s = combat.journey_acquire_source(jid, s['revision'], OWNER, PARENT, {})
    s = declare_allies(combat, s, [ALLY])
    for point in (POS[OWNER], {'x': 9, 'y': 6}):
        s = act(combat, s, 'lantern_create', {'position': point})
    menu = combat.journey_menu(jid, traveler)
    option = next(o for o in menu['options'] if o['kind'] == 'lantern_road_step'
                  and o['payload']['position'] != s['actors'][traveler]['position'])
    before = s['actors'][traveler]['resources'].copy()
    s = act(combat, s, option['kind'], option['payload'], traveler)
    assert s['actors'][traveler]['position'] == option['payload']['position']
    assert s['actors'][traveler]['resources'] == before
    assert CombatService(ROOT, tmp_path).journey_state(jid) == s
    assert not any(o['kind'] == 'lantern_road_step' for o in combat.journey_menu(jid, FOE)['options'])
    assert CombatService(ROOT, tmp_path).journey_replay(jid)['status'] == 'PASS'


@pytest.mark.parametrize('blocked', [False, True])
def test_spirit_trace_requires_light_to_reach_spirit_not_only_viewer(tmp_path, blocked):
    terrain = [{'type': 'BLOCKED', 'height_ft': 20, 'cells': [[5, 6]]}] if blocked else []
    combat, s = journey(tmp_path, terrain=terrain)
    jid = s['journey_id']
    s = combat.journey_acquire_source(jid, s['revision'], OWNER, PARENT, {})
    s = declare_source(combat, s, FOE, 'wall-possession', ['possession'], cl=6, position=POS[ALLY])
    s = act(combat, s, 'lantern_create', {'position': {'x': 6, 'y': 6}})
    mid = combat.journey_start_combat(jid, s['revision'],
        {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b'}, positions=POS)['match_id']
    engine = reload(tmp_path, mid)
    from combat.gate2_runtime_models import Position
    assert engine.grid.line_of_physical_transmission(engine.state.actors[OWNER].position, Position(**POS[ALLY]))
    view = TabletopService(CombatService(ROOT, tmp_path), tmp_path).state(
        mid, fog=True, fog_view='own', fog_actor_ids=(OWNER,), include_menu=False)
    rows = view['fog_perception'][OWNER].get('information', [])
    traces = [r for r in rows if r.get('source_id') == ALL[0]]
    assert bool(traces) is not blocked


def test_peal_suppression_expires_on_recipient_at_native_scene_end(tmp_path, monkeypatch):
    from combat import ext
    from combat.gate2_runtime_models import ActionDefinition
    from combat.ext import mgr_reserve_bell_tower_cultivator_watch_bell as bell
    # A synthetic ongoing Corruption source uses the real general producer,
    # rather than giving Lantern's external-source collector a new Bell tag.
    def corruption_source(info):
        if info['actor_id'] != ALLY:
            return None
        return [ActionDefinition(source_definition_id='action:test.temporary-corruption',
            display_name='Test temporary Corruption', owner_id=ALLY, economy='ACTION',
            resolution_kind='TYPED', target_kind='SELF',
            parameters={'typed': {'source': 'test:temporary-corruption',
                'numbers': dict(info['numbers']), 'duration': {'kind': 'instant'},
                'riders': [], 'effects': [{'type': 'information_source',
                    'tags': ['temporary_corruption'], 'applies_to': 'self'}]}})]
    monkeypatch.setitem(ext._HOOKS, 'compile_actions', [*ext.subscribers('compile_actions'), corruption_source])
    combat, s = journey(tmp_path, owner_ids=[bell.PURIFY])
    jid = s['journey_id']
    teams = {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b'}
    mid = combat.journey_start_combat(jid, s['revision'], teams, positions=POS, maximum_rounds=3)['match_id']
    table = TabletopService(combat, tmp_path)
    turn(table, mid, ALLY)
    cast(combat, table, mid, 'Test temporary Corruption')
    turn(table, mid, OWNER)
    cast(combat, table, mid, 'Purifying Peal', {'choice:needle.bell_allies_to_purify': [ALLY]})
    engine = reload(tmp_path, mid)
    grant = bell.held(engine.state.actors[ALLY], 'corruption_suppressed')[0]
    assert grant.data['scene'] == s.get('scene_id', jid)
    assert not bell.owned(engine, engine.state.actors[ALLY], bell.PURIFY)
    for _ in range(12):
        if combat._load_session(mid).engine.state.terminal_result is not None:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'])
    s = combat.journey_state(jid)
    s = combat.journey_resume(jid, s['revision'])
    assert grant.instance_id in s['actors'][ALLY]['encounter_snapshot']['conditions']
    s = combat.journey_end_scene(jid, s['revision'], 'The purification scene ends.')
    assert grant.instance_id not in s['actors'][ALLY]['encounter_snapshot']['conditions']
    assert CombatService(ROOT, tmp_path).journey_state(jid) == s
    second = combat.journey_start_combat(jid, s['revision'], teams, positions=POS)['match_id']
    assert not bell.held(reload(tmp_path, second).state.actors[ALLY], 'corruption_suppressed')


def test_hold_prompt_never_exposes_noncatalog_damage_ids(tmp_path, monkeypatch):
    from combat.ext import mgr_reserve_lantern_keeper_light_the_way as lantern
    from tests.test_mgr_lantern_native import play
    combat, table, mid = play(tmp_path, lantern_positions=[POS[OWNER]])
    engine = reload(tmp_path, mid)
    prompts = []
    def decline(ctx, *args, **kwargs):
        prompts.append(ctx.action.parameters['trigger_context'])
        return []
    monkeypatch.setattr(lantern, 'pick', decline)
    target = engine.state.actors[ALLY]
    engine._commit_damage(target, target.current_hp, 'FIRE',
        'condition:internal.damage-over-time', FOE, None, reaction_depth=0)
    assert prompts == ['the triggering effect reduced Tobin to 0 Hit Points.']


def test_external_stock_comparison_uses_only_supplied_files(tmp_path):
    from tools.lantern_stock_compare import main
    capture = {'steps': ['one'], 'state': {'terminal_result': 'DRAW'}}
    base, head, output = [tmp_path / n for n in ('base.json', 'head.json', 'comparison.json')]
    for path in (base, head):
        path.write_text(json.dumps(capture))
    assert main([str(base), str(head), str(output)]) == 0
    assert json.loads(output.read_text())['identical']
    head.write_text(json.dumps({**capture, 'steps': ['different']}))
    with pytest.raises(AssertionError):
        main([str(base), str(head), str(output)])


def test_fact_consent_regression_collects_without_private_support():
    import tests.test_fact_consent_admission as module
    assert callable(module.test_second_source_native_consent_privacy_expiry_and_refusal)
