"""Review entry points use real table choices, then commit and cold-replay them."""
import json
import subprocess

import pytest

from combat import hold_position, posture
from combat.ext import blossom
from tests import test_a2_flowers as flowers
from tests.hunt12_support import ME, STAMINA, event_hook, reload


def controller(fixture):
    result = subprocess.run(
        ['node', '--test', '--test-isolation=none', '--test-reporter=tap',
         'tests/optionspeed1_f4_controllers.test.mjs'],
        input=json.dumps(fixture), text=True, capture_output=True, timeout=120,
    )
    detail = next((line.strip() for line in result.stdout.splitlines() if 'error:' in line),
                  result.stderr[:700].replace('\n', ' | '))
    assert result.returncode == 0, detail + '\n' + result.stdout + result.stderr
    return json.loads(next(line.split('REVIEW_PAYLOAD ', 1)[1] for line in result.stdout.splitlines()
                           if 'REVIEW_PAYLOAD ' in line))


def selection(state, suffix):
    return next((cid, spec) for cid, spec in state['menu']['composition'].items()
                if spec['source'].endswith(suffix))


def request(state, source, setting):
    menu = state['menu']
    return dict(actor_id=ME, decision_id=menu['decision_id'], state_version=menu['state_version'],
                source_definition_id=source, sources=[setting], request_id='review-draft')


def commit_setting(table, mid, cid):
    state = table.state(mid)
    assert table.act(mid, cid, state['menu']['decision_id'], state['menu']['state_version'],
                     state['last_sequence'], [])['status'] == 'COMMITTED'


def test_existing_sheet_turn_controller_contracts():
    result = subprocess.run(['node', '--test', '--test-isolation=none', '--test-reporter=tap',
                             'tests/optionspeed1_sheet_controller_public.test.mjs'],
                            text=True, capture_output=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr


def test_desktop_assisted_confirmation_uses_draft_and_reconfirms_square(tmp_path, monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    combat, table, mid = flowers.scene(tmp_path, ['TAL_FLOWERS_CULTIVATE_BLOSSOM', blossom.SEED],
                                      control_modes={ME: 'SUGGESTED', flowers.FOE: 'MANUAL', flowers.ALLY: 'MANUAL'})
    commit_setting(table, mid, selection(table.state(mid), 'blossom.pick.seed')[0])
    state = table.state(mid)
    cid, spec = selection(state, 'blossom.pick.medicinal')
    source = next(g['source_definition_id'] for g in state['menu']['actions']
                  if g['source_definition_id'].endswith('blossom.cultivate_bloom'))
    payload = request(state, source, spec['source'])
    before_cp = combat._load_session(mid).engine.state.actors[ME].resources[STAMINA]
    fixture = dict(case='assisted', state=state, setting=cid, source=source,
                   preview=table.preview_composition(mid, payload))
    submitted = controller(fixture)
    assert submitted['composition'] == payload
    assert table.commit_composition(mid, payload, submitted['candidate_id'], submitted['after'])['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    config = next(c.data for c in engine.state.actors[ME].conditions.values() if c.condition_id == blossom.SETUP)
    assert config['bloom'] == 'medicinal'
    assert engine.state.actors[ME].resources[STAMINA] == before_cp - 1


@pytest.mark.parametrize('client', ['desktop', 'phone'])
@pytest.mark.parametrize('native_source', [posture.SOURCE, hold_position.SOURCE])
def test_native_actions_remain_usable_with_a_local_draft(tmp_path, monkeypatch, client, native_source):
    monkeypatch.setenv('CF_EMBED_MENU', '0')

    def prone_at_start(engine, event, data):
        if event == 'TURN_STARTED' and data.get('actor_id') == ME:
            engine._apply_condition(engine.state.actors[ME], 'condition:typed.prone',
                                    'test:review-prone', ME, expires_on='UNTIL_REMOVED')

    event_hook(monkeypatch, prone_at_start)
    combat, table, mid = flowers.scene(tmp_path, ['TAL_FLOWERS_CULTIVATE_BLOSSOM', blossom.SEED])
    state = table.state(mid)
    cid, spec = selection(state, 'blossom.pick.seed')
    native = next(g for g in state['menu']['actions'] if g['source_definition_id'] == native_source)
    before = combat._load_session(mid).engine.state.actors[ME].movement_remaining_ft
    option = native['options'][0]
    result = table.act(mid, option['candidate_id'], state['menu']['decision_id'], state['menu']['state_version'],
                       state['last_sequence'], [])
    assert result['status'] == 'COMMITTED'
    after = table.state(mid)
    source = next(g['source_definition_id'] for g in after['menu']['actions']
                  if g['source_definition_id'].endswith('blossom.cultivate_bloom'))
    payload = request(after, source, spec['source'])
    fixture = dict(case='native', client=client, state=state, after=after, setting=cid,
                   source=source, native=native_source, preview=table.preview_composition(mid, payload))
    submitted = controller(fixture)
    assert submitted == dict(candidate_id=option['candidate_id'], decision_id=state['menu']['decision_id'],
                             state_version=state['menu']['state_version'], after=state['last_sequence'],
                             **({'reactions': []} if client == 'desktop' else {}))
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[ME]
    assert actor.action_available
    assert not any(c.condition_id == blossom.SETUP for c in actor.conditions.values()), 'Native action must not save the draft'
    if native_source == posture.SOURCE:
        assert not posture.prone_conditions(actor)
        assert actor.movement_remaining_ft == before - actor.speed_ft // 2
    else:
        assert hold_position.used(actor)
        assert actor.movement_remaining_ft == before


def test_named_saved_active_sheet_talent_replaces_a_conflicting_draft(tmp_path, monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    pure, numbing = 'TAL_DARK_PURE_DARKNESS', 'TAL_DARK_NUMBING_DARKNESS'
    combat, table, mid = flowers.scene(tmp_path, ['DARK_BASE_DARKNESS', pure, numbing])
    state = table.state(mid)
    family = next(f for f in state['shapes'][ME] if any(o['talents'] == [pure] for o in f['options']))
    chosen = next(o for o in family['options'] if o['talents'] == [pure])
    commit_setting(table, mid, chosen['candidate_id'])
    state = table.state(mid)
    family = next(f for f in state['shapes'][ME] if f['base'] == family['base'])
    chosen = next(o for o in family['options'] if o['talents'] == [pure])
    other = next(o for o in family['options'] if o['talents'] == [numbing])
    assert chosen['active'] and not other['active']
    payload = request(state, family['base'], state['menu']['composition'][chosen['candidate_id']]['source'])
    # Use the actual generated sheet button schema, without requiring a private library.
    from combat.tabletop import auto_buttons
    engine = combat._load_session(mid).engine
    buttons = auto_buttons({'action_catalog': [a.model_dump(mode='json') for a in engine.action_catalog.values()
                                               if a.owner_id == ME]}, {'cultivation_level': 18})
    named = next(b for b in buttons if b.get('shape', {}).get('talents') == [pure])
    fixture = dict(case='named', state=state, setting=other['candidate_id'], source=family['base'],
                   named=named, sheet={'buttons': buttons}, preview=table.preview_composition(mid, payload),
                   initialPreview=table.preview_composition(mid, request(state, family['base'],
                       state['menu']['composition'][other['candidate_id']]['source'])))
    submitted = controller(fixture)
    assert submitted['composition'] == payload
    assert table.commit_composition(mid, payload, submitted['candidate_id'], submitted['after'])['status'] == 'COMMITTED'
    engine = reload(tmp_path, mid)
    from combat import zones
    assert zones.shaping_of(engine.state.actors[ME], family['zone']) == [pure]
