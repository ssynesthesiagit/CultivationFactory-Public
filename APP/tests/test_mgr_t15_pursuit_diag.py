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


def _dump(label, value):
    print(f"DIAG {label}: {value}")


def test_diag_flash_step(tmp_path):
    combat, table, mid = fight(tmp_path, foe_talents=['TAL_ATHLETICS_FLASH_STEP'])
    turn(table, mid, FOE)
    engine, prompts = action(tmp_path, mid, 'Flash Step', pending=True)
    _dump('receipts', json.dumps(RECEIPTS, default=str))
    rows = [r for r in (getattr(engine, 'typed_reaction_rows', {}) or {}).get(OWNER, [])
            if r.get('feature_id') == PURSUIT]
    _dump('pursuit_rows', json.dumps([{k: v for k, v in r.items() if k not in ('effects', 'numbers')}
                                      for r in rows], default=str))
    from combat.typed_reactions import _generic_rows
    _dump('generic_moved', [r.get('kind') for r in _generic_rows(engine, OWNER, 'moved')])
    _dump('generic_teleport', [r.get('kind') for r in _generic_rows(engine, OWNER, 'sky_pursuit_teleport')])
    _dump('typed_actor_ids', sorted(getattr(engine, 'typed_actor_ids', set())))
    _dump('ask_reactors', sorted(getattr(engine, 'typed_ask_reactors', set()) or []))
    foe = engine.state.actors[FOE]
    _dump('foe_action_ids', list(foe.action_ids))
    _dump('foe_position', (foe.position.x, foe.position.y))
    if RECEIPTS:
        source = RECEIPTS[-1]['source_definition_id']
        action_obj = engine.action_catalog.get(source)
        _dump('source', source)
        _dump('action', None if action_obj is None else (action_obj.owner_id, action_obj.display_name))
        from combat.ext.ability_source import mechanic_of
        _dump('mechanic_of', None if action_obj is None else mechanic_of(action_obj))
        _dump('receipt_feature', RECEIPTS[-1]['source_feature_id'])
    _dump('chase_events', len(chase_events(engine)))
    _dump('events', [(e.event_type, e.source_definition_id) for e in engine.events][-14:])


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
    _dump('blinded_conditions', [(c.condition_id, c.source_definition_id) for c in owner.conditions.values()])
    from combat.target_knowledge import can_see
    _dump('can_see', can_see(engine, owner, engine.state.actors[FOE]))
    _dump('blinded_chase', len(chase_events(engine)))
    _dump('blinded_owner_pos', (owner.position.x, owner.position.y))


def test_diag_immobile(tmp_path):
    combat, table, mid = fight(tmp_path, owner_speed=0)
    engine, _ = move(tmp_path, mid, 8)
    owner = engine.state.actors[OWNER]
    _dump('effective_speed', engine._effective_speed(owner))
    _dump('movement_remaining', owner.movement_remaining_ft)
    _dump('immobile_chase', len(chase_events(engine)))
    _dump('immobile_pos', (owner.position.x, owner.position.y))
