"""Selected Sound residuals through real table commits and cold replay."""
import pytest
from combat.ext import sound_echoes as E
from combat.typed_executor import check_modes
from tests import worker2_support as S
from tests.cw2_service_support import add_action


def probes(bundles):
    for bundle in bundles:
        for skill, ability in [('Stealth', 'DEX'), ('Perception', 'WIS')]:
            for hazard in ['hearing', 'visual_concealment']:
                add_action(bundle, f'{skill} {hazard}', [{'type': 'contest_against',
                    'applies_to': 'target',
                    'actor_check': {'kind': 'check', 'ability': ability, 'skill': skill, 'hazards': [hazard]},
                    'target_check': {'kind': 'dc', 'dc': 15}}])


def use(combat, table, mid, name, target=None, **kwargs):
    return S.settle(table, mid, S.candidate(combat, mid, name, target=target).candidate_id, **kwargs)


def mode(tmp_path, combat, table, mid, actor, skill, hazard, target):
    S.turn(table, mid, actor)
    use(combat, table, mid, f'{skill} {hazard}', target)
    engine = S.reload(tmp_path, mid)
    rolls = [e for e in engine.events if e.event_type == 'CHECK_ROLLED' and e.actor_id == actor
             and e.payload.get('actor')]
    return rolls[-1].payload['actor']['mode']


def test_muffle_only_sound_detection(tmp_path):
    c, t, mid = S.fixture(tmp_path, [E.MUFFLE], bundle_transform=probes)
    use(c, t, mid, 'Muffle Footfall', picks={'choice:willing.targets': S.OWNER})
    assert any(q.condition_id == E.QUIET for q in S.reload(tmp_path, mid).state.actors[S.OWNER].conditions.values())
    assert mode(tmp_path, c, t, mid, S.OWNER, 'Stealth', 'hearing', S.FOE) == 'ADVANTAGE'
    assert mode(tmp_path, c, t, mid, S.OWNER, 'Stealth', 'visual_concealment', S.FOE) == 'NORMAL'


@pytest.mark.parametrize('actor,skill,expected', [(S.ALLY, 'Stealth', 'ADVANTAGE'),
                                                 (S.FOE, 'Perception', 'DISADVANTAGE')])
def test_live_field_qualified_checks(tmp_path, actor, skill, expected):
    c, t, mid = S.fixture(tmp_path, [E.FIELD], bundle_transform=probes, dc=100)
    prompts = use(c, t, mid, 'Ten-Thousand Echoes Field')
    assert any(p['context']['reaction_source_id'] == 'choice:needle.echo_step' for p in prompts)
    target = S.FOE if actor == S.ALLY else S.OWNER
    assert mode(tmp_path, c, t, mid, actor, skill, 'hearing', target) == expected
    assert mode(tmp_path, c, t, mid, actor, skill, 'visual_concealment', target) == 'NORMAL'
    engine = S.reload(tmp_path, mid)
    # Live query does not retain a casting-time condition or affect visual checks.
    assert not any(q.condition_id == 'condition:typed.check_mode'
                   for a in engine.state.actors.values() for q in a.conditions.values())


@pytest.mark.parametrize('pick', ['reaction', 'confusion'])
def test_failed_save_affected_creature_chooses_and_expires(tmp_path, pick):
    c, t, mid = S.fixture(tmp_path, [E.FIELD], dc=100, named=True)
    use(c, t, mid, 'Ten-Thousand Echoes Field')
    # Advance to the foe's actual start; its decision belongs to the foe.
    prompts = []
    for _ in range(4):
        if t.state(mid)['menu']['actor_id'] == S.FOE:
            break
        prompts += S.settle(t, mid, t.state(mid)['menu']['end_turn'],
                            picks={'choice:needle.echo_failure': pick})
    request = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.echo_failure')
    assert S.FOE in str(request['context'])
    e = S.reload(tmp_path, mid)
    cid = 'condition:typed.reaction_denied' if pick == 'reaction' else E.CONFUSED
    q = next(q for q in e.state.actors[S.FOE].conditions.values() if q.condition_id == cid)
    assert S.FOE in q.expires_on
    assert not any(q.condition_id == (E.CONFUSED if pick == 'reaction' else 'condition:typed.reaction_denied')
                   for q in e.state.actors[S.FOE].conditions.values())


def test_allied_sound_use_offers_one_step_and_commits_destination(tmp_path):
    c, t, mid = S.fixture(tmp_path, [E.FIELD], ally_talents=[E.MUFFLE], dc=100)
    use(c, t, mid, 'Ten-Thousand Echoes Field')
    S.turn(t, mid, S.ALLY)
    before = S.reload(tmp_path, mid).state.actors[S.ALLY].position
    prompts = use(c, t, mid, 'Muffle Footfall')
    assert any(p['context']['reaction_source_id'] == 'choice:needle.echo_step' for p in prompts)
    after = S.reload(tmp_path, mid).state.actors[S.ALLY]
    assert after.position != before
    assert after.turn_flags.get('sound_echo_step')
