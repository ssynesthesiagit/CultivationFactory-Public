"""Separate deterministic streams for two journey check owners, across cold commits."""
import json

from combat.gate2_rolls import DeterministicRollAuthority
from combat.gate2_runtime_models import DiceSpec
from tests.test_journey_rolls import A, B, HEART, events, game


def test_two_owners_have_independent_persisted_check_and_bonus_streams(tmp_path, monkeypatch):
    cold, jid, act, admit = game(tmp_path, monkeypatch, talents=[HEART], both_owners=True)
    for n in range(3):
        for aid in (A, B):
            name = f'plea{n}'
            admit('check_task', {'id': name, 'description': 'Plea for mercy',
                  'ability': 'CHA', 'dc': 100, 'dc_known': True,
                  'tags': ['mercy'], 'proficient': False}, aid=aid)
            act('roll_check', {'task': name}, aid=aid)
            act('roll_decide', {'offer': 'softened_heart'}, aid=aid)

    for kind, stream, sides in [('CHECK_ROLLED', 'scenecheck', 20),
                                ('ROLL_BONUS_ADDED', 'afterroll', 4)]:
        actual = {}
        for aid in (A, B):
            rows = [e for e in events(cold, jid, kind) if e['actor_id'] == aid]
            actual[aid] = [e['roll']['natural_result'] if sides == 20 else e['value'] for e in rows]
            roller = DeterministicRollAuthority(json.dumps([jid, aid, stream]))
            expected = []
            for n in range(3):
                if sides == 20:
                    roll = roller.d20(modifier=0, actor_id=aid, reason='check')
                    expected.append(roll.natural_result)
                else:
                    roll = roller.roll(DiceSpec(count=1, sides=4, modifier=0), actor_id=aid, reason='bonus')
                    expected.append(roll.total)
            assert actual[aid] == expected
        assert actual[A] != actual[B]  # compare whole streams, not individual dice
    assert cold().journeys.replay(jid)['status'] == 'PASS'
