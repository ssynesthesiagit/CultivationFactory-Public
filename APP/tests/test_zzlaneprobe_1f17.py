"""Temporary lane diagnostic (deleted before commit): why the turn's Road was not offered later."""
import json
from combat.tabletop_service import TabletopService
from combat.ext import mgr_reserve_lantern_keeper_light_the_way as m
from combat.ext import needle
from tests.test_mgr_lantern_native import journey, POS, OWNER, ALLY, FOE, lamps, reload
from tests.worker2_support import settle


def snap(e, aid):
    a = e.state.actors[aid]
    owners = [o.entity_id for o in e.state.actors.values()]
    return {'round': e.state.round_number, 'slot': e.state.current_slot_index, 'cur': e.state.current_actor_id,
            'stamp': m.stamp(e), 'active': a.active, 'action': a.action_available,
            'lamps': [(o.object_id, o.position.x, o.position.y, o.destroyed) for o in lamps(e)],
            'conds': sorted(c.condition_id for c in a.conditions.values()),
            'road_used': m.used(e, a, 'road_used'),
            'pairs': [[o.entity_id, f.object_id, s2.object_id] for o, f, s2 in m.road_pairs(e, a)],
            'owned': {o: [r.get('feature_id') for r in getattr(e, 'typed_passive_rows', {}).get(o, [])][:3] for o in owners},
            'live': {o: [x.object_id for x in m.live(e, o)] for o in owners},
            'near10': {o: [x.object_id for x in m.near(e, a, o, 10)] for o in owners},
            'ally': {o: bool(m.ally(e, o, a)) for o in owners},
            'names': sorted({c.display_name for c in e.legal_candidates()}),
            'action_ids': sorted(getattr(a, 'action_ids', []) or [])}


def test_probe(tmp_path):
    seen = []
    real = needle.ask
    def spy(engine, intent, checkpoint, chooser, choice_id, options, **kw):
        seen.append([str(choice_id), [str(o) for o in options]])
        return real(engine, intent, checkpoint, chooser, choice_id, options, **kw)
    needle.ask = spy
    try:
        combat, s = journey(tmp_path, cl=6)
        jid = s['journey_id']
        s = combat.journey_acquire_source(jid, s['revision'], OWNER, m.PARENT, {})
        for point in (POS[OWNER], {'x': 9, 'y': 6}):
            s = combat.journey_act(jid, s['revision'], OWNER, 'lantern_create', {'position': point})
        mid = combat.journey_start_combat(jid, s['revision'], {OWNER: 'team:a', ALLY: 'team:a', FOE: 'team:b'},
            positions={**POS, FOE: {'x': 5, 'y': 6}})['match_id']
        table = TabletopService(combat, tmp_path)
        steps = []
        for _ in range(6):
            menu = table.state(mid)['menu']
            steps.append([menu['actor_id'], menu.get('display_name')])
            if menu['actor_id'] == ALLY: break
            settle(table, mid, menu['end_turn'], picks={'choice:needle.lantern_road_destination_lantern': None,
                'choice:needle.lantern_moving_lantern': None})
        e = reload(tmp_path, mid)
        rows = {'atally': snap(e, ALLY)}
        attacks = [c for c in e.legal_candidates() if c.target_ids == (FOE,) and c.display_name.startswith('Unarmed Strike')]
        rows['attacks'] = len(attacks)
        settle(table, mid, attacks[0].candidate_id)
        e2 = reload(tmp_path, mid)
        rows['after'] = snap(e2, ALLY)
        rows['after_menus'] = [[x['actor_id']] for x in [table.state(mid)['menu']]]
    finally:
        needle.ask = real
    assert False, json.dumps({'steps': steps, 'asks': seen, 'rows': rows}, indent=1, default=str)
