"""TEMPORARY diagnostics #3 for the Pursuit teleport trigger (not for commit)."""
import json

from tests.worker2_support import turn, OWNER, ALLY, FOE
from tests.cw2_service_support import add_action
from tests.test_mgr_t15_pursuit_horizon import fight, action, move, chase_events


def test_diag_flash_step(tmp_path):
    combat, table, mid = fight(tmp_path, foe_talents=['TAL_ATHLETICS_FLASH_STEP'])
    turn(table, mid, FOE)
    engine, prompts = action(tmp_path, mid, 'Flash Step', pending=True)
    report = {}
    report['receipts'] = [(e.event_type, e.actor_id, e.source_definition_id, e.payload.get('teleport'),
                           e.payload.get('destination')) for e in engine.events
                          if e.event_type == 'MOVEMENT_COMMITTED']
    report['chase'] = len(chase_events(engine))
    report['foe_pos'] = (engine.state.actors[FOE].position.x, engine.state.actors[FOE].position.y)
    report['owner_pos'] = (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y)
    report['prompts'] = [p['context']['reaction_source_id'] for p in prompts]
    assert False, 'DIAG ' + json.dumps(report, default=str)


def test_diag_blink_guard(tmp_path):
    def prepare(bundles):
        add_action(bundles[0], 'Trigger attack', [{'type': 'attack', 'attack_kind': 'ranged_cultivation',
                   'count': 1, 'on_hit': []}], typed={'numbers': {'cl': 14, 'pb': 5, 'attack_bonus': 100, 'save_dc': 16}})
    combat, table, mid = fight(tmp_path, prepare=prepare,
                               foe_talents=['tianxia.talent.space.blink_guard'])
    seen = []

    def pick(prompt, options):
        seen.append((prompt['context']['reaction_source_id'],
                     [(o.get('id'), o.get('cell'), str(o.get('label') or o.get('text'))) for o in options]))
        return ((prompt.get('choice') or {}).get('preferred') or [options[0]['id']])[0]

    engine, prompts = action(tmp_path, mid, 'Trigger attack', target=FOE, pick=pick)
    report = {}
    report['seen'] = seen
    report['chase'] = len(chase_events(engine))
    report['foe_pos'] = (engine.state.actors[FOE].position.x, engine.state.actors[FOE].position.y)
    report['owner_pos'] = (engine.state.actors[OWNER].position.x, engine.state.actors[OWNER].position.y)
    from combat.target_knowledge import can_see
    report['can_see'] = can_see(engine, engine.state.actors[OWNER], engine.state.actors[FOE])
    from combat.typed_reactions import _rows
    report['rows'] = [(r.get('kind'), r.get('feature_id')) for r in _rows(engine, OWNER, 'generic')]
    assert False, 'DIAG ' + json.dumps(report, default=str)
