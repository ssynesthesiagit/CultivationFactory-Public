"""Regression tests for the 4F7R Sol seam blocking findings on Emotion Cultivator.

Each test fails on the unfixed branch: Hostile Calm's failed save omitted the printed
Speed reduction; Weather of the Heart's Concentration outlived its 1-minute aura; and a
hostile creature teleported into the aura got no entry save.
"""
from combat.ext.emotion_cultivator import WEATHER, PULSE
from combat.gate2_runtime_models import Position
from combat import ext as X
from tests import test_a2_qi_subpaths_1_service as Q
from tests import auto11_service_support as S


def test_hostile_calm_pulse_failed_save_leaves_speed_unchanged(tmp_path):
    # Finding: Emotional Pulse's printed Hostile Calm failure is only the
    # Opportunity Attack and emotional-escalation limits; Speed is not reduced.
    # (The printed Speed reduction belongs to Weather of Calm, tested separately.)
    svc, table, mid = Q.fight(tmp_path, [PULSE])
    pre = Q.cold(svc, mid)
    base_speed = pre._effective_speed(pre.state.actors[Q.FOE])
    Q.use(table, mid, 'Emotional Pulse: Hostile Calm', target=Q.FOE)
    eng = Q.cold(svc, mid)
    foe = eng.state.actors[Q.FOE]
    assert Q.conditions(foe, 'emotional_calm')
    assert eng._effective_speed(foe) == base_speed


def test_weather_of_the_heart_ends_its_concentration_after_one_minute(tmp_path):
    # Finding: the 1-minute aura must end the Concentration copy too, so no ended copy persists.
    # A long-enough match, so the aura's real one-minute (ten-round) deadline is reached.
    svc, table, mid = Q.fight(tmp_path, [WEATHER], cl=18, rounds=30)
    Q.use(table, mid, 'Weather of the Heart: Calm (centered on you)', target=Q.ME, answer=lambda p: None)
    eng = Q.cold(svc, mid)
    assert eng.state.actors[Q.ME].concentration is not None
    start = eng.state.round_number
    for _ in range(200):
        eng = Q.cold(svc, mid)
        if not Q.conditions(eng.state.actors[Q.ME], 'heart_weather'):
            break
        S.play(table, mid, table.state(mid)['menu']['end_turn'])
    eng = Q.cold(svc, mid)
    assert Q.conditions(eng.state.actors[Q.ME], 'heart_weather') == []
    assert eng.state.round_number - start <= 11
    assert eng.state.actors[Q.ME].concentration is None


def test_hostile_teleported_into_weather_aura_gets_the_entry_save(tmp_path):
    # Finding: a teleport that lands a hostile in the aura is an entry; the entry save
    # must fire through committed_teleport_receipt, not only movement_landed.
    svc, table, mid = Q.fight(tmp_path, [WEATHER], cl=18)
    Q.use(table, mid, 'Weather of the Heart: Calm (centered on you)', target=Q.ME, answer=lambda p: None)
    eng = Q.cold(svc, mid)
    me = eng.state.actors[Q.ME]
    foe = eng.state.actors[Q.FOE]
    outside = Position(x=me.position.x + 10, y=me.position.y, z=me.position.z)
    inside_at = Position(x=me.position.x + 2, y=me.position.y, z=me.position.z)
    foe.position = inside_at
    receipt = {'receipt_id': 'test:teleport:1', 'movement_sequence': 1, 'intent_id': 'test',
        'source_definition_id': 'test', 'source_feature_id': 'test',
        'actor_id': str(foe.entity_id), 'source_actor_id': str(me.entity_id),
        'previous_x': outside.x, 'previous_y': outside.y, 'previous_z': outside.z,
        'destination_x': inside_at.x, 'destination_y': inside_at.y, 'destination_z': inside_at.z,
        'distance_ft': 40, 'turn_actor_id': str(eng.state.current_actor_id),
        'own_turn': 0, 'self_teleport': 0, 'unwilling': 1, 'forced': 0}
    X.run_strict('committed_teleport_receipt', eng, receipt)
    assert Q.conditions(foe, 'emotion_weather_received')
