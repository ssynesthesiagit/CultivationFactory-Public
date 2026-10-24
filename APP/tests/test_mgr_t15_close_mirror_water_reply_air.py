"""Mirror-Water Reply offers only squares a ground creature can stand on.

Regression for the Reply review (B1): the subject-destination menu and forced
routes offered unsupported mid-air squares. A ground attacker then fell 10 feet,
took fall damage and ended Prone on its start square instead of being moved.
"""
from combat.falling import SOURCE as FALL_SOURCE
from combat.gate2_runtime_models import Position
from tests.test_mgr_t15_close_mirror_water_reply import (
    REPLY, OWNER, ALLY, FOE, native, cold, turn, candidate, settle, dice,
)


def test_ground_attacker_menu_has_no_unsupported_air_and_moves_on_the_ground(tmp_path, monkeypatch):
    service, table, mid = native(tmp_path)
    turn(tmp_path, mid, OWNER)
    service, table, _ = cold(tmp_path, mid)
    settle(tmp_path, mid, candidate(service, table, mid, 'Shape Current: Mist Basin', at=(4, 5)))
    turn(tmp_path, mid, FOE)
    dice(monkeypatch)
    service, table, engine = cold(tmp_path, mid)
    start = engine.state.actors[FOE].position
    hp_before = engine.state.actors[FOE].current_hp
    assert start == Position(x=4, y=5, z=0)
    seen = []

    def choose(prompt):
        source = prompt['context']['reaction_source_id']
        if source == f'reaction:typed.{REPLY}:mode:0':
            return ''
        if source == 'choice:needle.subject_destination':
            options = {o['id'] for o in prompt['choice']['options']}
            # No square above ground: an ordinary creature has no support there.
            assert not {o for o in options if o.count(',') == 2 and not o.endswith(',0')}, options
            assert 'cell:4,7' in options  # 10 feet south along the ground
            seen.append(prompt)
            return 'cell:4,7'
        return None

    settle(tmp_path, mid, candidate(service, table, mid, 'Jian', ALLY), choose)
    _, _, engine = cold(tmp_path, mid)
    assert seen
    foe = engine.state.actors[FOE]
    assert foe.position == Position(x=4, y=7, z=0)
    assert foe.current_hp == hp_before  # no fall damage
    assert not any('prone' in c.condition_id for c in foe.conditions.values())
    assert not any(getattr(e, 'source_definition_id', None) == FALL_SOURCE for e in engine.events)
