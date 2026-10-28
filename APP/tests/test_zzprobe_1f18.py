"""TEMPORARY lane probe (delete before commit): why is the fight-time Lantern Road never offered?"""
import json
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.worker2_support import settle, reload as native_reload
from tests.test_mgr_lantern_native import journey, POS, OWNER, ALLY, FOE, PARENT


def diag(e, actor_id, owner_id):
    from combat.ext import mgr_reserve_lantern_keeper_light_the_way as L
    from combat import ext
    actor = e.state.actors[actor_id]
    owner = e.state.actors[owner_id]
    out = {}
    out['owned'] = L.owned(e, owner, L.ROAD)
    out['ROAD'] = L.ROAD
    out['rows'] = sorted({r.get('feature_id') for r in getattr(e, 'typed_passive_rows', {}).get(owner_id, [])})
    out['actor_active'] = actor.active
    out['ally'] = L.ally(e, owner, actor)
    out['live'] = [(o.object_id, o.owner_id, o.position.x, o.position.y, (o.component or {}).get('expires_round'),
                    (o.component or {}).get('expires_slot'), (o.component or {}).get('empowerment_ended'))
                   for o in L.live(e, owner)]
    out['near'] = [o.object_id for o in L.near(e, actor, owner, 10)]
    out['used'] = L.used(e, actor, 'road_used')
    out['stamp'] = L.stamp(e)
    out['conditions'] = [(c.condition_id, c.data) for c in actor.conditions.values()]
    out['pending'] = e.state.pending_resolution is not None
    out['hook_count'] = len(ext._HOOKS.get('additional_actions', []))
    try:
        out['pairs'] = [[owner_id, f.object_id, s.object_id] for _o, f, s in L.road_pairs(e, actor)]
    except Exception as exc:
        out['pairs'] = 'ERR ' + repr(exc)
    try:
        out['hook_out'] = L.unused_road_option(e, actor)
    except Exception as exc:
        out['hook_out'] = 'ERR ' + repr(exc)
    out['catalog_road'] = sorted(a for a in e.action_catalog if 'road' in a)
    out['action_ids'] = sorted(actor.action_ids)
    out['catalog'] = sorted(e.action_catalog)
    out['candidates'] = [(c.display_name, c.source_definition_id) for c in e.legal_candidates()]
    return out


def test_zzprobe_road_after_move(tmp_path):
    combat, s = journey(tmp_path, cl=6)
    jid = s['journey_id']
    s = combat.journey_acquire_source(jid, s['revision'], OWNER, PARENT, {})
    for point in (POS[OWNER], {'x': 9, 'y': 6}):
        s = combat.journey_act(jid, s['revision'], OWNER, 'lantern_create', {'position': point})
    mid = combat.journey_start_combat(jid, s['revision'], {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b'},
        positions={OWNER: POS[OWNER], ALLY: {'x': 6, 'y': 6}, FOE: {'x': 8, 'y': 10}})['match_id']
    table = TabletopService(combat, tmp_path)
    for _ in range(6):
        if table.state(mid)['menu']['actor_id'] == ALLY:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'],
               picks={'choice:needle.lantern_road_destination_lantern': None,
                      'choice:needle.lantern_moving_lantern': None})
    e = native_reload(tmp_path, mid)
    before = diag(e, ALLY, OWNER)
    step = next(c for c in e.legal_candidates() if c.kind == 'MOVE' and c.destination.x == 7 and c.destination.y == 6)
    settle(table, mid, step.candidate_id)
    e = native_reload(tmp_path, mid)
    after = diag(e, ALLY, OWNER)
    after['position'] = (e.state.actors[ALLY].position.x, e.state.actors[ALLY].position.y)
    before['position'] = (6, 6)
    assert False, json.dumps({'before': before, 'after': after}, indent=1, default=str)
