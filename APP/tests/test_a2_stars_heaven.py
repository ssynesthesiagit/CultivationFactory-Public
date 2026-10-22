"""The complete printed Heaven-Falling Star contract at a saved table."""
import json
from pathlib import Path

from combat.ext import placed
from tests.test_a2_stars_insights import fight, MARK, bonus_rolls
from tests.auto_worker1_support import ALLY, LEFT, RIGHT, act, reload, resolve, turn, cell_send

HEAVEN = "STARS_TAL_HEAVEN_FALLING_STAR"


def test_heaven_falling_star_complete_contract_and_no_manual_reminder(tmp_path):
    def yard(arena):
        arena['map_objects'] = [{'id': 1, 'kind': 'crate', 'x': 5, 'y': 5, 'material': 'stone',
                                 'hp': 1000, 'threshold': 0, 'blocks': False, 'unattended': True}]
    combat, table, mid = fight(tmp_path, [HEAVEN], prepare=[MARK], cl=17, arena_edit=yard,
                              positions={LEFT: {'x': 3, 'y': 6}, RIGHT: {'x': 4, 'y': 6}})
    resolve(lambda a: act(table, mid, 'Prepare', a, target_id=RIGHT))
    resolve(cell_send(table, mid, 'Heaven-Falling Star', (4, 6)))
    engine = reload(combat, mid)
    saves = [e for e in engine.events if e.event_type == 'SAVE_ROLLED' and e.actor_id == RIGHT]
    assert saves and saves[-1].payload['mode'] == 'DISADVANTAGE'
    rolls = bonus_rolls(engine)
    assert len(rolls) == 1 and rolls[0].expression.startswith('12d10')
    assert engine.state.actors[RIGHT].current_hp < 1000
    assert any(c.condition_id.endswith('prone') for c in engine.state.actors[RIGHT].conditions.values())
    updated = [e for e in engine.events if e.event_type == 'OBJECT_UPDATED' and e.payload.get('damage')]
    assert len(updated) == 1 and updated[0].payload['damage']['taken'] == 2 * rolls[0].total
    assert next(iter(engine.state.objects.values())).current_hp == 1000 - 2 * rolls[0].total
    zone, = placed.of(engine, 'stellar_impact')
    assert [(c.x, c.y) for c in zone.affected_cells] == [(4, 6)]
    assert zone.duration_rounds is None and zone.trigger_profile['difficult'] == 'all'
    assert engine.state.actors[LEFT].resources['resource:core.qi'] == 88
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    assert not any(g['label'] == 'Heaven-Falling Star' for g in table.state(mid)['menu']['actions'])
    assert placed.of(reload(combat, mid), 'stellar_impact')
    record = json.loads((Path(__file__).parents[1] / 'authority/Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics'][HEAVEN]
    assert record['riders'] == [] and record['coverage'] == 'FULL'
    assert not any(e.event_type == 'GM_RIDER' and 'While Aligned' in e.payload.get('rider', '') for e in engine.events)


def test_heaven_falling_star_leaves_an_ally_inside_the_area_unaffected(tmp_path):
    combat, table, mid = fight(tmp_path, [HEAVEN], ally=[], cl=17,
                              positions={LEFT: {'x': 3, 'y': 6}, ALLY: {'x': 2, 'y': 5}, RIGHT: {'x': 4, 'y': 6}})
    resolve(cell_send(table, mid, 'Heaven-Falling Star', (4, 6)))
    engine = reload(combat, mid)
    assert engine.state.actors[ALLY].current_hp == 1000
    assert engine.state.actors[LEFT].current_hp == 1000
    assert {e.actor_id for e in engine.events if e.event_type == 'SAVE_ROLLED'} == {RIGHT}
    assert engine.state.actors[RIGHT].current_hp < 1000
