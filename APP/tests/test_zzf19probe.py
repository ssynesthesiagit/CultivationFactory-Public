"""TEMPORARY lane probe (delete before commit): why is the fight-time Lantern Road never offered?"""
import json
import pytest
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.ext import mgr_reserve_lantern_keeper_light_the_way as L
from combat import ext
from tests.worker2_support import settle, reload as native_reload
from tests.test_mgr_lantern_native import journey, POS, OWNER, ALLY, FOE, PARENT, declare_source


def diag(e, actor_id, owner_id):
    actor = e.state.actors[actor_id]
    owner = e.state.actors[owner_id]
    out = {}
    out['owned'] = L.owned(e, owner, L.ROAD)
    out['ally'] = L.ally(e, owner, actor)
    out['live'] = [(o.object_id, o.position.x, o.position.y, (o.component or {}).get('expires_round'), (o.component or {}).get('expires_slot'))
                   for o in L.live(e, owner)]
    out['near'] = [o.object_id for o in L.near(e, actor, owner, 10)]
    out['used'] = L.used(e, actor, 'road_used')
    out['stamp'] = L.stamp(e)
    out['conditions'] = [(c.condition_id, c.data) for c in actor.conditions.values()]
    out['action_avail'] = actor.action_available
    try:
        out['pairs'] = [[owner_id, f.object_id, s.object_id] for _o, f, s in L.road_pairs(e, actor)]
    except Exception as exc:
        out['pairs'] = 'ERR ' + repr(exc)
    out['hook_out'] = L.unused_road_option(e, actor)
    out['catalog_road'] = sorted(a for a in e.action_catalog if 'road' in a)
    out['candidates'] = [(c.display_name, c.source_definition_id) for c in e.legal_candidates()]
    out['legal_names'] = sorted({c.display_name for c in e.legal_candidates()})
    return out


def test_zzf19_probe_road(tmp_path):
    combat, s = journey(tmp_path, cl=6)
    jid = s['journey_id']
    s = combat.journey_acquire_source(jid, s['revision'], OWNER, PARENT, {})
    for point in (POS[OWNER], {'x': 9, 'y': 6}):
        s = combat.journey_act(jid, s['revision'], OWNER, 'lantern_create', {'position': point})
    mid = combat.journey_start_combat(jid, s['revision'], {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b'},
        positions={**POS, FOE: {'x': 5, 'y': 6}})['match_id']
    table = TabletopService(combat, tmp_path)
    log = []
    for _ in range(6):
        if table.state(mid)['menu']['actor_id'] == ALLY:
            break
        settle(table, mid, table.state(mid)['menu']['end_turn'],
               picks={'choice:needle.lantern_road_destination_lantern': None,
                      'choice:needle.lantern_moving_lantern': None})
    e = native_reload(tmp_path, mid)
    log.append(('at_turn_start', diag(e, ALLY, OWNER)))
    assert e.state.actors[ALLY].position.x == 4
    attacks = [c for c in e.legal_candidates() if c.target_ids == (FOE,) and c.display_name.startswith('Unarmed Strike')]
    log.append(('attacks', [c.display_name for c in attacks]))
    if attacks:
        settle(table, mid, attacks[0].candidate_id)
    e = native_reload(tmp_path, mid)
    log.append(('after_attack', diag(e, ALLY, OWNER)))
    raise AssertionError(json.dumps(log, default=str, indent=1))
