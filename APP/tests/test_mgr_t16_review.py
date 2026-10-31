"""F1–F5: actual table commits, cold replay and observer information."""
import os
from pathlib import Path

import pytest
from combat import ext, senses
from combat.gate2_runtime_models import Position, RuntimeObjectState
from combat.ext.obscure_passage import PASSAGE
from combat.ext.air_delivery import DELIVERY
from combat.ext.grave_sense import GRAVE
from combat.ext.sound_echoes import CONFUSED
from tests import worker2_support as S
from tests.cw2_service_support import add_action

SWEEP = 'TAL_THE_HIDDEN_EYE_THOUSAND_LANTERN_SWEEP'


@pytest.fixture(autouse=True)
def scene(monkeypatch):
    def setup(ctx, row):
        if row.get('death'):
            ctx.engine._apply_condition(ctx.engine.state.actors[S.FOE], 'condition:test.death', ctx.source,
                ctx.actor.entity_id, expires_on='UNTIL_REMOVED', data={'death_sign': {'kind': 'undead'}})
        if row.get('end'):
            ctx.engine._end_concentration(ctx.actor, 'PLAYER_ENDS_CONCENTRATION')
        if row.get('phenomena'):
            ctx.engine._apply_condition(ctx.actor, senses.SENSE, ctx.source, ctx.actor.entity_id,
                expires_on='UNTIL_REMOVED', data={'sense': 'blindsight', 'range_ft': 120})
            ctx.engine._apply_condition(ctx.actor, CONFUSED, ctx.source, ctx.actor.entity_id,
                expires_on='UNTIL_REMOVED')
            for category, sense in row['phenomena']:
                obj = RuntimeObjectState(object_id='object:test.' + category + sense,
                    object_kind='test', position=Position(x=11, y=6), unattended=True, flammable=False,
                    component={'detection': {'category': category, 'sense': sense, 'dc': 15}})
                ctx.engine._update_object(obj, ctx.source, ctx.actor.entity_id)
        if row.get('delivery'):
            ctx.engine._update_object(RuntimeObjectState(object_id='object:test.script', object_kind='talisman',
                position=Position(x=5, y=6), unattended=True, flammable=False,
                component={'size': 'Tiny', 'prepared_by': S.OWNER, 'activated': 0}), ctx.source, ctx.actor.entity_id)
    monkeypatch.setitem(ext._EFFECTS, 'test_t16_review_setup', setup)


def fixture(tmp_path, talents, *, positions=None, arena=None, **setup):
    def transform(bundles):
        add_action(bundles[0], 'Prepare review scene', [{'type': 'test_t16_review_setup', **setup}], target='SELF')
        add_action(bundles[0], 'End review passage', [{'type': 'test_t16_review_setup', 'end': True}], target='SELF')
    c, t, mid = S.fixture(tmp_path, talents, cl=17, owner_pb=6, dc=-100,
        positions=positions, battlefield_transform=arena, bundle_transform=transform)
    S.settle(t, mid, S.candidate(c, mid, 'Prepare review scene').candidate_id)
    return c, t, mid


def test_f1_facts_reach_table_with_fog_disabled(tmp_path):
    c, t, mid = fixture(tmp_path, [GRAVE], death=True)
    S.reload(tmp_path, mid)
    state = t.state(mid, fog=False, fog_view='own', fog_actor_ids=(S.OWNER,))
    assert state.get('fog_perception', {}) == {}
    facts = state['observer_information']
    assert set(facts) == {S.OWNER}
    assert any(row.get('ability') == 'Grave Sense' for row in facts[S.OWNER]['information'])
    lines = facts[S.OWNER]['information_text']
    assert any('Grave Sense: a death-sign' in line for line in lines)
    assert all('Grave Sense: Grave Sense:' not in line for line in lines)
    other = t.state(mid, fog=False, fog_view='own', fog_actor_ids=(S.ALLY,))
    assert not any(row.get('ability') == 'Grave Sense'
                   for row in other['observer_information'].get(S.ALLY, {}).get('information', []))


def elevated_arena(doc):
    doc['terrain_regions'] = []
    doc['roof_surfaces'] = [{'id': 'test:floor', 'height_ft': 10,
        'cells': [{'x': 6, 'y': 6}, {'x': 6, 'y': 7}, {'x': 6, 'y': 8}]}]


def passage(c, t, mid, direction, target):
    engine = c._load_session(mid).engine
    candidates = [row for row in engine.legal_candidates()
        if getattr(engine.action_catalog.get(row.source_definition_id), 'display_name', None) == 'Obscure Passage'
        and row.destination == target]
    if not candidates:
        from combat.targeting import cell_line_of_effect
        from combat.area_knowledge import origin_allowed
        action = next(a for a in engine.action_catalog.values() if a.display_name == 'Obscure Passage')
        actor = engine.state.actors[S.OWNER]
        raw = engine._action_candidates(actor, action)
        detail = (f'target={target}; owner={actor.position}; action={actor.action_available}; '
            f'surface_effect={cell_line_of_effect(engine, actor, action, target)}; '
            f'origin_allowed={origin_allowed(engine, actor, action, target)}; '
            f'raw_count={len(raw)}; raw_has_target={any(c.destination == target for c in raw)}; '
            f'raw_levels={sorted({c.destination.z for c in raw if c.destination})}')
        import sys
        print(detail, file=sys.__stdout__, flush=True)
        assert candidates, detail
    return S.settle(t, mid, candidates[0].candidate_id,
        picks={'choice:needle.passage_direction': direction, 'choice:needle.passage_save': 'save'})


@pytest.mark.parametrize('direction,z,foe_z', [('down', 2, 2), ('up', 2, 2), ('up', 2, 0)])
def test_f2_real_floor_roof_aperture_restores_after_reload(tmp_path, direction, z, foe_z):
    places = {S.OWNER: {'x': 5, 'y': 6, 'z': 2}, S.ALLY: {'x': 4, 'y': 6},
              S.FOE: {'x': 6, 'y': 6, 'z': foe_z}}
    # Owner stands on a separate support cell beside the affected floor.
    def arena(doc):
        elevated_arena(doc)
        doc['roof_surfaces'][0]['cells'].append({'x': 5, 'y': 6})
        if direction == 'up':
            places[S.OWNER]['z'] = 0
    c, t, mid = fixture(tmp_path, [PASSAGE], positions=places, arena=arena)
    before = S.reload(tmp_path, mid)
    assert before.grid.roof_supported(Position(x=6, y=6, z=2))
    prompts = passage(c, t, mid, direction, Position(x=6, y=6, z=z))
    e = S.reload(tmp_path, mid)
    assert not e.grid.roof_supported(Position(x=6, y=6, z=2))
    assert not e.grid.roof_step_blocked((6, 6, 1), (6, 6, 2))
    assert e.grid.roof_supported(Position(x=6, y=7, z=2))
    assert not e.grid.roof_ray_blocked((6, 6, 0), (6, 6, 3))
    from combat.terrain_apertures import light_transmits
    assert not light_transmits(e, Position(x=6, y=6), Position(x=6, y=6, z=3))
    assert any(p['context']['reaction_source_id'] == 'choice:needle.passage_save' for p in prompts) is (foe_z == 2)
    S.settle(t, mid, S.candidate(c, mid, 'End review passage').candidate_id)
    e = S.reload(tmp_path, mid)
    assert e.grid.roof_supported(Position(x=6, y=6, z=2))
    assert e.grid.roof_step_blocked((6, 6, 1), (6, 6, 2))


def test_f2_ground_floor_opens_under_creature_and_restores(tmp_path):
    c, t, mid = fixture(tmp_path, [PASSAGE], arena=lambda doc: doc.update(terrain_regions=[]))
    prompts = passage(c, t, mid, 'down', Position(x=6, y=6))
    e = S.reload(tmp_path, mid)
    from combat.falling import supported
    foe = e.state.actors[S.FOE]
    assert not supported(e, foe, Position(x=6, y=6))
    assert supported(e, foe)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.passage_safe' for p in prompts)
    S.settle(t, mid, S.candidate(c, mid, 'End review passage').candidate_id)
    assert supported(S.reload(tmp_path, mid), foe, Position(x=6, y=6))


def test_f2_ai_reaches_unoccupied_visible_ceiling(tmp_path, monkeypatch):
    c, t, mid = fixture(tmp_path, [PASSAGE], arena=elevated_arena)
    from combat.ext import obscure_passage
    native = obscure_passage.ask
    def choose(engine, intent, checkpoint, chooser, choice_id, options, **kwargs):
        if choice_id == 'choice:needle.passage_direction':
            kwargs['preferred'] = ['up']
        return native(engine, intent, checkpoint, chooser, choice_id, options, **kwargs)
    monkeypatch.setattr(obscure_passage, 'ask', choose)
    from tests.mgr_t16_support import automatic
    automatic(c, t, mid, S.OWNER, 'Obscure Passage', at=(6, 6, 2))
    e = S.reload(tmp_path, mid)
    assert not e.grid.roof_supported(Position(x=6, y=6, z=2))
    assert e.state.actors[S.FOE].position.z == 0
    c.set_controller_mode(mid, actor_id=S.OWNER, controller_mode='MANUAL')
    S.settle(t, mid, S.candidate(c, mid, 'End review passage').candidate_id)
    assert S.reload(tmp_path, mid).grid.roof_supported(Position(x=6, y=6, z=2))


def test_f2_finite_solid_floor_opens_and_restores(tmp_path):
    def arena(doc):
        doc['roof_surfaces'] = []
        doc['roof_cells'] = []
        doc['terrain_regions'] = [{'region_id': 'test:platform', 'terrain_type': 'BLOCKED',
            'movement_cost': 0, 'height_ft': 10, 'description': 'Stone platform',
            'cells': [{'x': 5, 'y': 6}, {'x': 6, 'y': 6}, {'x': 6, 'y': 7}]}]
    c, t, mid = fixture(tmp_path, [PASSAGE], arena=arena,
        positions={S.OWNER: {'x': 5, 'y': 6, 'z': 2}, S.ALLY: {'x': 4, 'y': 6},
                   S.FOE: {'x': 6, 'y': 6, 'z': 2}})
    passage(c, t, mid, 'down', Position(x=6, y=6, z=2))
    e = S.reload(tmp_path, mid)
    assert not e.grid.terrain_at((6, 6, 1), 'BLOCKED')
    from combat.falling import supported
    assert not supported(e, e.state.actors[S.FOE], Position(x=6, y=6, z=2))
    assert supported(e, e.state.actors[S.FOE])
    S.settle(t, mid, S.candidate(c, mid, 'End review passage').candidate_id)
    assert S.reload(tmp_path, mid).grid.terrain_at((6, 6, 1), 'BLOCKED')


@pytest.mark.skipif(os.environ.get('MGR_T16_BROWSER') != '1', reason='Lead-only browser check outside sandbox')
def test_f1_browser_information_panel():
    from playwright.sync_api import sync_playwright
    source = (Path(__file__).parents[1] / 'static/tabletop/observer-information.js').read_text()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        try:
            page = browser.new_page()
            page.set_content('<aside id="inspector"></aside>')
            page.add_script_tag(content=source.replace('export function', 'function'))
            page.evaluate('''renderObserverInformation(document.querySelector('#inspector'),
                [{entity_id:'owner',display_name:'Wren'}, {entity_id:'enemy',display_name:'Mara'}],
                {owner:[{text:'Grave Sense: a death-sign is present to the east'}],
                 enemy:[{text:'Enemy private information'}]}, ['owner'])''')
            assert page.get_by_text('Wren: Grave Sense: a death-sign is present to the east').is_visible()
            assert page.get_by_text('Enemy private information').count() == 0
        finally:
            browser.close()


@pytest.mark.parametrize('direction', ['east', 'down'])
def test_f3_save_offers_supported_ledge_landings_only(tmp_path, direction):
    places = {S.OWNER: {'x': 3, 'y': 6}, S.ALLY: {'x': 4, 'y': 6}, S.FOE: {'x': 6, 'y': 6, 'z': 2}}
    c, t, mid = fixture(tmp_path, [PASSAGE], positions=places, arena=elevated_arena)
    prompts = passage(c, t, mid, direction, Position(x=6, y=6, z=2))
    safe = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.passage_safe')
    assert {o['id'] for o in safe['choice']['options']} == {'cell:6,7,2'}
    e = S.reload(tmp_path, mid)
    assert e.state.actors[S.FOE].position == Position(x=6, y=7, z=2)
    from combat.falling import supported
    assert supported(e, e.state.actors[S.FOE])


def test_f3_origin_only_hover_does_not_make_air_safe(tmp_path, monkeypatch):
    def pocket_flight(engine, actor):
        if actor.entity_id == S.FOE and actor.position == Position(x=6, y=6, z=2):
            return {'fly_speed_ft': 30, 'flight_hover': 1}
    monkeypatch.setitem(ext._HOOKS, 'flight', [*ext._HOOKS.get('flight', []), pocket_flight])
    places = {S.OWNER: {'x': 3, 'y': 6}, S.ALLY: {'x': 4, 'y': 6}, S.FOE: {'x': 6, 'y': 6, 'z': 2}}
    c, t, mid = fixture(tmp_path, [PASSAGE], positions=places, arena=elevated_arena)
    prompts = passage(c, t, mid, 'down', Position(x=6, y=6, z=2))
    safe = next(p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.passage_safe')
    assert {o['id'] for o in safe['choice']['options']} == {'cell:6,7,2'}
    e = S.reload(tmp_path, mid)
    assert e.state.actors[S.FOE].position == Position(x=6, y=7, z=2)


@pytest.mark.parametrize('category', ['hidden_object', 'magical_sensor', 'ongoing_effect'])
def test_f5_sweep_phenomena_use_qualified_shared_dice(tmp_path, monkeypatch, category):
    c, t, mid = fixture(tmp_path, [SWEEP],
        arena=lambda doc: doc.update(terrain_regions=[], roof_surfaces=[], roof_cells=[]),
        phenomena=[(category, 'sight'), (category, 'nonvisual')])
    from combat.gate2_rolls import DeterministicRollAuthority
    original = DeterministicRollAuthority.d20
    def roll(self, **kw):
        result = original(self, **kw)
        if kw.get('reason', '').endswith(':LANTERN'):
            natural = 2 if kw.get('mode') == 'DISADVANTAGE' else 18
            result = result.model_copy(update={'dice': (18, 2) if kw.get('mode') != 'NORMAL' else (18,),
                'natural_result': natural, 'total': natural + result.modifier,
                'discarded': (18,) if kw.get('mode') == 'DISADVANTAGE' else (2,) if kw.get('mode') == 'ADVANTAGE' else ()})
        return result
    monkeypatch.setattr(DeterministicRollAuthority, 'd20', roll)
    S.settle(t, mid, S.candidate(c, mid, 'Thousand-Lantern Sweep').candidate_id)
    e = S.reload(tmp_path, mid)
    facts = senses.observer_information(e, e.state.actors[S.OWNER])
    assert not any(r.get('candidate') == 'object:test.' + category + 'sight' for r in facts)
    assert any(r.get('candidate') == 'object:test.' + category + 'nonvisual' for r in facts)
    checks = [ev.payload for ev in e.events if ev.event_type == 'CHECK_ROLLED' and ev.payload.get('candidate')]
    assert {p['actor']['mode'] for p in checks} == {'NORMAL', 'DISADVANTAGE'}
    assert len({p['actor']['counter_start'] for p in checks}) == 1
    assert all(p['actor']['dice'] == [18, 2] for p in checks)


def test_f4_ai_delivery_retains_unseen_around_corner_destination(tmp_path, monkeypatch):
    def arena(doc):
        doc['terrain_regions'] = [{'region_id': 'test:corner', 'terrain_type': 'BLOCKED',
            'movement_cost': 0, 'cells': [{'x': 6, 'y': 6}], 'description': 'Stone wall'}]
    c, t, mid = fixture(tmp_path, [DELIVERY, 'AIR_BASE_GATHER_CURRENT'], arena=arena, delivery=True,
        positions={S.OWNER: {'x': 3, 'y': 6}, S.ALLY: {'x': 4, 'y': 6}, S.FOE: {'x': 10, 'y': 9}})
    e = S.reload(tmp_path, mid)
    endpoint = Position(x=7, y=6)
    assert not senses.perceives_cell(e, e.state.actors[S.OWNER], endpoint)
    from combat.ext.air_delivery import routes
    assert 'cell:7,6,0' in routes(e, Position(x=5, y=6), 1)
    # Native AI choice transport retains every endpoint. The deterministic
    # policy chooses a blind direction without learning anything about occupants.
    from combat.ext import needle
    native = needle.ask
    def choose(engine, intent, checkpoint, chooser, choice_id, options, **kwargs):
        if choice_id == 'choice:needle.wind_script_destination':
            assert 'cell:7,6,0' in options
            assert kwargs.get('automatic_options') is None
            kwargs['preferred'] = ['cell:7,6,0']
        return native(engine, intent, checkpoint, chooser, choice_id, options, **kwargs)
    from combat.ext import air_delivery
    monkeypatch.setattr(air_delivery, 'ask', choose)
    from tests.mgr_t16_support import automatic
    automatic(c, t, mid, S.OWNER, 'Gather Current: Carry', at=(5, 6))
    e = S.reload(tmp_path, mid)
    assert e.state.objects['object:test.script'].position == endpoint
    assert e.state.objects['object:test.script'].component['activated'] == 0
