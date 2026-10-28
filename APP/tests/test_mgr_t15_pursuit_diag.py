"""TEMPORARY diagnostics for the Pursuit teleport trigger (not for commit)."""
import json

from combat import ext
from combat.ext.sky_treading import PURSUIT
from tests.worker2_support import turn, OWNER, ALLY, FOE
from tests.test_mgr_t15_pursuit_horizon import fight, cold, action, move, chase_events

RECEIPTS = []


@ext.hook("committed_teleport_receipt")
def _capture(engine, receipt):
    RECEIPTS.append(dict(receipt))
    return None


def test_diag_flash_step(tmp_path):
    combat, table, mid = fight(tmp_path, foe_talents=['TAL_ATHLETICS_FLASH_STEP'])
    turn(table, mid, FOE)
    engine, prompts = action(tmp_path, mid, 'Flash Step', pending=True)
    report = {}
    report['receipts'] = RECEIPTS
    rows = [r for r in (getattr(engine, 'typed_reaction_rows', {}) or {}).get(OWNER, [])
            if r.get('feature_id') == PURSUIT]
    report['pursuit_rows'] = [{k: v for k, v in r.items() if k not in ('effects', 'numbers')} for r in rows]
    from combat.typed_reactions import _generic_rows
    report['generic_moved'] = [r.get('kind') for r in _generic_rows(engine, OWNER, 'moved')]
    report['generic_teleport'] = [r.get('kind') for r in _generic_rows(engine, OWNER, 'sky_pursuit_teleport')]
    report['typed_actor_ids'] = sorted(getattr(engine, 'typed_actor_ids', set()))
    report['ask_reactors'] = sorted(getattr(engine, 'typed_ask_reactors', set()) or [])
    foe = engine.state.actors[FOE]
    report['foe_action_ids'] = list(foe.action_ids)
    report['foe_reaction_ids'] = list(foe.reaction_ids)
    report['foe_position'] = (foe.position.x, foe.position.y)
    if RECEIPTS:
        source = RECEIPTS[-1]['source_definition_id']
        action_obj = engine.action_catalog.get(source)
        report['source'] = source
        report['action'] = None if action_obj is None else (action_obj.owner_id, action_obj.display_name)
        from combat.ext.ability_source import mechanic_of
        report['mechanic_of'] = None if action_obj is None else mechanic_of(action_obj)
        report['receipt_feature'] = RECEIPTS[-1]['source_feature_id']
    report['chase_events'] = len(chase_events(engine))
    report['events'] = [(e.event_type, e.source_definition_id) for e in engine.events][-16:]
    report['prompts'] = [p.get('context') for p in prompts]
    assert False, 'DIAG ' + json.dumps(report, default=str)


def test_diag_blinded(tmp_path):
    from tests.cw2_service_support import add_action

    def prepare(bundles):
        add_action(bundles[0], 'Prepare control',
                   [{'type': 'condition', 'condition': 'blinded', 'applies_to': 'self'}], target='SELF')

    combat, table, mid = fight(tmp_path, prepare=prepare)
    action(tmp_path, mid, 'Prepare control')
    turn(table, mid, FOE)
    engine, _ = move(tmp_path, mid, 8)
    owner = engine.state.actors[OWNER]
    report = {}
    report['conditions'] = [(c.condition_id, c.source_definition_id) for c in owner.conditions.values()]
    from combat.target_knowledge import can_see
    report['can_see'] = can_see(engine, owner, engine.state.actors[FOE])
    report['chase'] = len(chase_events(engine))
    report['owner_pos'] = (owner.position.x, owner.position.y)
    report['events'] = [(e.event_type, e.source_definition_id) for e in engine.events][-16:]
    assert False, 'DIAG ' + json.dumps(report, default=str)


def test_diag_immobile(tmp_path):
    combat, table, mid = fight(tmp_path, owner_speed=0)
    engine, _ = move(tmp_path, mid, 8)
    owner = engine.state.actors[OWNER]
    report = {}
    report['effective_speed'] = engine._effective_speed(owner)
    report['movement_remaining'] = owner.movement_remaining_ft
    report['chase'] = len(chase_events(engine))
    report['owner_pos'] = (owner.position.x, owner.position.y)
    report['events'] = [(e.event_type, e.source_definition_id) for e in engine.events][-16:]
    assert False, 'DIAG ' + json.dumps(report, default=str)
