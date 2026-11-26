"""Shield-Breaking Eye through service commands, cold verification and replay."""
import pytest

from combat.ext import shield_breaking_eye as plug
from tests.auto_worker1_support import LEFT, RIGHT, act, action_sender, fight, reload, resolve, turn


def fresh(c, mid):
    session = c._load_session(mid)
    assert session.verify()['status'] == 'PASS'
    assert session.mechanical.replay()['status'] == 'PASS'
    return reload(c, mid)


def fixture(tmp_path, *, owns=True, shield=True, scores=None, prepare=()):
    def sheet(doc, aid):
        if aid == LEFT:
            doc['spheres_and_talents']['cultivation_insight_record_ids'] = [plug.FEATURE] if owns else []
        else:
            doc['proficiencies'] = {'armor': ['Shield']}
    def bundle(b):
        if b['actor_id'] == RIGHT and scores:
            b['actor_template']['saving_throws'].update(scores)
    kit = {'items': [{'item_id': 'tianxia.mortal.armor.shield', 'name': 'Shield', 'quantity': 1}]} if shield else {'items': []}
    return fight(tmp_path, sheet_edit=sheet, bundle_edit=bundle, right_kit=kit,
                 prepare=prepare, prepare_target='ANY_CREATURE', reaction_ask=True)


@pytest.mark.parametrize('ai', [False, True])
@pytest.mark.parametrize('scores,expected', [({'STR': 9, 'DEX': 2, 'WIS': 1}, 'Strength'),
    ({'STR': 2, 'DEX': 9, 'WIS': 1}, 'Dexterity'),
    ({'STR': 2, 'DEX': 1, 'WIS': 9}, 'Wisdom'),
    ({'STR': 9, 'DEX': 9, 'WIS': 9}, 'Strength,Dexterity,Wisdom')])
def test_study_defense_optional_information_and_cold_reload(tmp_path, ai, scores, expected):
    c, t, mid = fixture(tmp_path, scores=scores)
    before = fresh(c, mid).state.actors[LEFT]
    _, prompts = resolve(action_sender(c, t, mid, plug.LABEL, target_id=RIGHT, ai=ai))
    e = fresh(c, mid)
    notes = [ev for ev in e.events if ev.source_definition_id == plug.FEATURE
             and 'strongest_defenses' in ev.payload]
    assert len(notes) == 1 and notes[0].payload['strongest_defenses'] == expected
    assert e.state.actors[LEFT].resources == before.resources
    assert e.state.actors[LEFT].reaction_available == before.reaction_available
    assert not e.state.actors[LEFT].action_available
    assert bool(prompts) != ai
    assert all(key not in notes[0].payload for key in scores)
    if prompts:
        assert 'Shield-Breaking Eye' in str(prompts) and 'Visitor' in str(prompts)


def test_decline_spends_study_but_discloses_nothing(tmp_path):
    c, t, mid = fixture(tmp_path)
    resolve(lambda a: act(t, mid, plug.LABEL, a, target_id=RIGHT), {plug.CHOICE: []})
    e = fresh(c, mid)
    assert not any('strongest_defenses' in ev.payload for ev in e.events)
    assert not e.state.actors[LEFT].action_available


@pytest.mark.parametrize('owns,shield', [(False, True), (True, False)])
def test_no_ownership_or_visible_posture_no_reading_option(tmp_path, owns, shield):
    c, t, mid = fixture(tmp_path, owns=owns, shield=shield)
    e = fresh(c, mid)
    assert not any(candidate.source_definition_id.endswith('.shield_breaking_eye')
                   and RIGHT in candidate.target_ids for candidate in e.legal_candidates())


@pytest.mark.parametrize('posture', ['dodge', 'guard', 'guarded_stance', 'river_second_guard'])
def test_native_dodge_and_source_authored_guard_without_shield(tmp_path, posture):
    # A harmless service setup effect records an observable posture; no engine
    # state is mutated after admission. Native Dodge uses its actual core ID.
    effect = {'type': 'condition', 'condition': 'guard_posture', 'applies_to': 'target',
              'duration': {'kind': 'until_removed'}}
    if posture == 'guard':
        effect['condition_data'] = {'visible_defensive_posture': 1}
    else:
        effect['condition'] = posture
    c, t, mid = fixture(tmp_path, shield=False, prepare=[] if posture == 'dodge' else [effect])
    if posture == 'dodge':
        turn(t, mid, RIGHT)
        resolve(lambda a: act(t, mid, 'system:combat.dodge', a))
        turn(t, mid, LEFT)
    else:
        resolve(lambda a: act(t, mid, 'Prepare', a, target_id=RIGHT))
    resolve(lambda a: act(t, mid, plug.LABEL, a, target_id=RIGHT))
    assert any('strongest_defenses' in ev.payload for ev in fresh(c, mid).events)


def test_hidden_target_is_not_offered(tmp_path):
    c, t, mid = fixture(tmp_path, prepare=[{'type': 'condition', 'condition': 'invisible',
        'applies_to': 'target', 'duration': {'kind': 'until_removed'}}])
    resolve(lambda a: act(t, mid, 'Prepare', a, target_id=RIGHT))
    e = fresh(c, mid)
    assert not any(candidate.source_definition_id.endswith('.shield_breaking_eye')
                   and RIGHT in candidate.target_ids for candidate in e.legal_candidates())
