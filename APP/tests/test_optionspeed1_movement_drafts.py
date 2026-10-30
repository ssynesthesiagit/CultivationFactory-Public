"""Movement must preserve a player's uncommitted option draft on both clients."""
import json

from combat.ext import blossom
from tests.hunt12_support import ME
from tests.test_a2_flowers import scene
from tests.node_support import run_node_test


def test_same_turn_movement_rebinds_local_draft_on_desktop_and_phone(tmp_path, monkeypatch):
    monkeypatch.setenv('CF_EMBED_MENU', '0')
    # Exercise the unsupported-isolation fallback (Node 20) even on newer CI Nodes.
    monkeypatch.setattr('tests.node_support.isolation_flag', lambda node='node': None)
    combat, table, mid = scene(tmp_path, ['TAL_FLOWERS_CULTIVATE_BLOSSOM', blossom.SEED])
    before = table.state(mid)
    menu = before['menu']
    setting = next(cid for cid, spec in menu['composition'].items()
                   if spec['source'].endswith('blossom.pick.seed'))
    move = next(row for row in menu['moves'] if not row.get('deferred_route') and row['destination'] !=
                next(actor['position'] for actor in before['presentation']['actors'] if actor['entity_id'] == ME))
    reply = table.act(mid, move['candidate_id'], menu['decision_id'], menu['state_version'],
                      before['last_sequence'], [])
    assert reply['status'] == 'COMMITTED'
    after = table.state(mid)
    source = next(g['source_definition_id'] for g in after['menu']['actions']
                  if g['source_definition_id'].endswith('blossom.cultivate_bloom'))
    payload = dict(actor_id=ME, decision_id=after['menu']['decision_id'],
                   state_version=after['menu']['state_version'],
                   sources=[next(spec['source'] for spec in after['menu']['composition'].values()
                                  if spec['source'].endswith('blossom.pick.seed'))],
                   source_definition_id=source, request_id='movement-draft')
    preview = table.preview_composition(mid, payload)
    fixture = dict(case='move-draft', state=before, after=after, setting=setting,
                   move=move['candidate_id'], source=source, preview=preview)
    for case in ('move-draft', 'move-draft-phone'):
        fixture['case'] = case
        result = run_node_test('--test-reporter=tap',
                               'tests/optionspeed1_f4_controllers.test.mjs',
                               input=json.dumps(fixture), text=True, capture_output=True, timeout=120)
        expected = ('desktop retains the local choice across successful same-turn movement and rebases it'
                    if case == 'move-draft' else
                    'phone retains the local choice across successful same-turn movement and rebases it')
        assert f'# Subtest: {expected}' in result.stdout, result.stdout + result.stderr
        if result.returncode:
            lines = (result.stdout + result.stderr).splitlines()
            detail = next((line for line in lines if line.lstrip().startswith('error:')),
                          next((line for line in lines if line.lstrip().startswith('AssertionError:')
                                or line.startswith('not ok')), lines[-1]))
            raise AssertionError(detail)
