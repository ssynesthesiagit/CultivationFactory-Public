"""Staggering Blow's three Speeds follow its creator's current Body CL."""
from tests.auto_worker1_support import LEFT, RIGHT, act, fight, reload, resolve

STOMP = 'tianxia.path.body_refining.feature.stomping_step'
BODY = 'tianxia.path.body_refining'
SLOW = 'condition:typed.drunken_slow'


def test_speed_reduction_dormant_and_restored_after_table_commits(tmp_path):
    def sheet_edit(doc, aid):
        if aid == LEFT:
            doc['path_and_subpath']['path_feature_record_ids'] = [STOMP]

    def bundle_edit(bundle):
        if bundle['actor_id'] == RIGHT:
            bundle['actor_template']['fly_speed_ft'] = 30
            bundle['actor_template']['climb_speed_ft'] = 30

    combat, table, mid = fight(tmp_path, [], cl=10, sheet_edit=sheet_edit, bundle_edit=bundle_edit,
        prepare=[{'type': 'drunken_speed', 'feet': 10}],
        extra_actions=[
            ('Suppress', {'effects': [{'type': 'path_effective_cl', 'path_id': BODY,
                 'effective_cl': 9, 'applies_to': 'self', 'duration': {'kind': 'until_removed'}}]}),
            ('Restore', {'effects': [{'type': 'remove_condition', 'condition': 'path_effective_cl',
                                      'applies_to': 'self'}]}),
        ])

    from combat.flight import profile as flight
    from combat.roof_movement import profile as climb

    def check(expected):
        engine = reload(combat, mid)
        victim = engine.state.actors[RIGHT]
        condition = next(c for c in victim.conditions.values() if c.condition_id == SLOW)
        assert condition.expires_on == 'START_OF_SOURCE_NEXT_TURN'
        assert (engine._effective_speed(victim), flight(engine, victim).speed_ft,
                climb(engine, victim).speed_ft) == (expected, expected, expected)

    resolve(lambda answers: act(table, mid, 'Prepare', answers))
    check(20)
    resolve(lambda answers: act(table, mid, 'Suppress', answers))
    check(30)
    resolve(lambda answers: act(table, mid, 'Restore', answers))
    check(20)
