"""Observer residuals: real table actions, permitted facts and cold replay."""
import pytest
from combat import ext, senses
from combat.gate2_runtime_models import Position
from combat.ext import observer_information as I
from combat.ext import grave_sense as G, tremor_court as E
from combat.ext.riders14_eye import RIVAL, COURT
from combat.ext.eye_awareness import NO_FOOTSTEP
from combat.ext.radiance import CROWN
from tests import worker2_support as S
from tests.cw2_service_support import add_action
from tests.mgr_t16_support import automatic

SWEEP = 'TAL_THE_HIDDEN_EYE_THOUSAND_LANTERN_SWEEP'
EYE_COURT = 'TAL_THE_HIDDEN_EYE_COURT_OF_THE_HIDDEN_EYE'
FOUNDATION = 'EARTH_BASE_SET_FOUNDATION'


@pytest.fixture(autouse=True)
def scene_effect(monkeypatch):
    def scene(ctx, row):
        target = ctx.engine.state.actors[S.FOE]
        if row.get('death'):
            ctx.engine._apply_condition(target, 'condition:test.death_sign', ctx.source, ctx.actor.entity_id,
                expires_on='UNTIL_REMOVED', data={'death_sign': {'kind': 'undead', 'age': 'old', 'undead_state': 'bound'}})
        if row.get('rival'):
            ctx.engine._apply_condition(ctx.actor, RIVAL, ctx.source, ctx.actor.entity_id,
                expires_on='UNTIL_REMOVED', data={'target_id': S.FOE})
        if row.get('diagnostics'):
            target = ctx.engine.state.actors[S.ALLY]
            ctx.engine._apply_condition(target, 'condition:test.diagnostics', ctx.source, ctx.actor.entity_id,
                expires_on='UNTIL_REMOVED', data={'contact_diagnostics': ['carrying a heavy load', 'burrowing', 'concentrating on a vibrating technique']})
        if row.get('no_contact'):
            ctx.engine._apply_condition(ctx.engine.state.actors[S.ALLY], 'condition:typed.test_no_contact', ctx.source, ctx.actor.entity_id,
                expires_on='UNTIL_REMOVED', data={'rule': {'no_physical_contact': 1}})
        if row.get('phenomena'):
            for category in row['phenomena']:
                ctx.engine._apply_condition(target, 'condition:test.' + category, ctx.source, ctx.actor.entity_id,
                    expires_on='UNTIL_REMOVED', data={'detection': {'category': category, 'dc': -100,
                        'description': category.replace('_', ' ')}})
        if row.get('move'):
            from combat.ext.needle import step_to
            step_to(ctx.engine, target, Position(x=18, y=6), ctx.source)
    monkeypatch.setitem(ext._EFFECTS, 'test_mgr_t16_scene', scene)


def fixture(tmp_path, talents, **scene):
    def transform(bundles):
        add_action(bundles[0], 'Prepare scene', [{'type': 'test_mgr_t16_scene', **scene}], target='SELF')
        add_action(bundles[0], 'Move contact', [{'type': 'test_mgr_t16_scene', 'move': True}], target='SELF')
    c, t, mid = S.fixture(tmp_path, talents, cl=17, bundle_transform=transform)
    use(c, t, mid, 'Prepare scene')
    return c, t, mid


def use(c, t, mid, name, target=None, **kw):
    return S.settle(t, mid, S.candidate(c, mid, name, target=target).candidate_id, **kw)


def information(tmp_path, mid, viewer=S.OWNER):
    e = S.reload(tmp_path, mid)
    return senses.perception(e, e.state.actors[viewer]).get('information', [])


def test_grave_presence_only_direction_not_identity(tmp_path):
    c, t, mid = fixture(tmp_path, [G.GRAVE], death=True)
    rows = [r for r in information(tmp_path, mid) if r.get('ability') == 'Grave Sense']
    assert rows and rows[0]['direction'] == 'east'
    assert all(S.FOE not in str(r) and 'undead' not in str(r) for r in rows)
    assert not any(r.get('ability') == 'Grave Sense' for r in information(tmp_path, mid, S.ALLY))


@pytest.mark.parametrize('key', ['kind', 'age', 'undead_state'])
def test_grave_focus_one_fact_asked_and_retained(tmp_path, key):
    c, t, mid = fixture(tmp_path, [G.GRAVE], death=True)
    prompts = use(c, t, mid, 'Grave Sense: Focus', picks={'choice:needle.grave_fact': key})
    assert len([p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.grave_fact']) == 1
    rows = [r for r in information(tmp_path, mid) if r.get('fact')]
    assert len(rows) == 1 and rows[0]['fact'] == key


def test_grave_focus_automatic_choice_retains_one_fact_without_prompt(tmp_path):
    c, t, mid = fixture(tmp_path, [G.GRAVE], death=True)
    prompts = automatic(c, t, mid, S.OWNER, 'Grave Sense: Focus')
    assert not any(p['context']['reaction_source_id'].startswith('choice:needle.grave_') for p in prompts)
    rows = [r for r in information(tmp_path, mid) if r.get('fact')]
    assert len(rows) == 1


def test_no_footstep_rival_coarse_direction_and_distance(tmp_path):
    c, t, mid = fixture(tmp_path, [NO_FOOTSTEP], rival=True)
    rows = [r for r in information(tmp_path, mid) if r.get('ability') == 'No Footstep Escapes the World']
    assert rows and rows[0]['direction'] == 'east' and rows[0]['approximate_distance_ft'] == 15
    assert 'subject' not in rows[0] and 'position' not in rows[0]


def test_court_perceived_departure_only_owner(tmp_path):
    c, t, mid = fixture(tmp_path, [EYE_COURT])
    use(c, t, mid, 'Court of the Hidden Eye')
    use(c, t, mid, 'Move contact')
    rows = [r for r in information(tmp_path, mid) if r.get('transition')]
    assert rows and rows[0]['transition'] == 'left' and rows[0]['subject'] == S.FOE
    assert not any(r.get('transition') for r in information(tmp_path, mid, S.ALLY))


@pytest.mark.parametrize('category', ['hidden_object', 'magical_sensor', 'ongoing_effect'])
def test_sweep_three_extra_candidate_classes_use_same_search(tmp_path, category):
    c, t, mid = fixture(tmp_path, [SWEEP], phenomena=[category])
    use(c, t, mid, 'Thousand-Lantern Sweep')
    assert any(r.get('category') == category for r in information(tmp_path, mid))
    e = S.reload(tmp_path, mid)
    assert len([ev for ev in e.events if ev.event_type == 'CHECK_ROLLED' and ev.payload.get('lantern_search')]) == 1


def test_radiance_five_categories_excludes_other_secrets(tmp_path):
    wanted = ['illusion', 'disguise', 'possession', 'magical_darkness', 'spiritual_corruption']
    c, t, mid = fixture(tmp_path, [CROWN], phenomena=[*wanted, 'secret_door', 'ethereal', 'planar_boundary'])
    use(c, t, mid, 'Crown of the Unblinking Sun')
    rows = [r for r in information(tmp_path, mid) if r.get('ability') == 'Crown of the Unblinking Sun']
    assert {r['category'] for r in rows} == set(wanted)


def test_tremor_court_contact_location_and_represented_diagnostics(tmp_path):
    c, t, mid = fixture(tmp_path, [E.COURT, FOUNDATION], diagnostics=True)
    use(c, t, mid, 'Set Foundation', target=S.ALLY)
    S.settle(t, mid, t.state(mid)['menu']['end_turn'])
    S.turn(t, mid, S.OWNER)
    use(c, t, mid, 'Tremor Court Hearing')
    e = S.reload(tmp_path, mid)
    assert senses.pinpoints(e, e.state.actors[S.OWNER], e.state.actors[S.ALLY])
    rows = [r for r in information(tmp_path, mid) if r.get('ability') == 'Tremor Court Hearing' and r.get('subject') == S.ALLY]
    assert rows and all(word in rows[0]['facts'] for word in ['heavy load', 'burrowing', 'vibrating'])


def test_tremor_court_ignores_creatures_without_physical_contact(tmp_path):
    c, t, mid = fixture(tmp_path, [E.COURT, FOUNDATION], no_contact=True)
    use(c, t, mid, 'Set Foundation', target=S.ALLY)
    S.settle(t, mid, t.state(mid)['menu']['end_turn'])
    S.turn(t, mid, S.OWNER)
    use(c, t, mid, 'Tremor Court Hearing')
    e = S.reload(tmp_path, mid)
    assert not E.contact(e, e.state.actors[S.OWNER], e.state.actors[S.ALLY])
    assert not any(r.get('ability') == 'Tremor Court Hearing' and r.get('subject') == S.ALLY
                   for r in information(tmp_path, mid))
