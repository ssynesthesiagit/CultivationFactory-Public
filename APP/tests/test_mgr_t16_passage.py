"""Mapped Obscure Passage: committed geometry, observer policy and expiry."""
import pytest
from combat import ext, senses
from combat.gate2_runtime_models import Position
from combat.terrain_apertures import light_transmits
from combat.ext.obscure_passage import PASSAGE
from tests import worker2_support as S
from tests.cw2_service_support import add_action


@pytest.fixture(autouse=True)
def setup_effect(monkeypatch):
    def setup(ctx, row):
        if row.get('sense'):
            ctx.engine._apply_condition(ctx.actor, senses.SENSE, ctx.source, ctx.actor.entity_id,
                expires_on='UNTIL_REMOVED', data={'sense': row['sense'], 'range_ft': 120})
        if row.get('end'):
            ctx.engine._end_concentration(ctx.actor, 'PLAYER_ENDS_CONCENTRATION')
    monkeypatch.setitem(ext._EFFECTS, 'test_mgr_passage_setup', setup)


def fixture(tmp_path, *, sense=None, hard=False, wall=True, dc=100):
    def arena(doc):
        doc['terrain_regions'] = ([{'region_id': 'test:wall', 'terrain_type': 'BLOCKED',
            'movement_cost': 0, 'description': 'Stone wall',
            'cells': [{'x': 5, 'y': 6}], 'height_ft': 20, 'exceptional_hardness': int(hard)}] if wall else [])
    def transform(bundles):
        add_action(bundles[0], 'Prepare senses', [{'type': 'test_mgr_passage_setup', 'sense': sense}], target='SELF')
        add_action(bundles[0], 'End passage', [{'type': 'test_mgr_passage_setup', 'end': True}], target='SELF')
    c, t, mid = S.fixture(tmp_path, [PASSAGE], cl=17, owner_pb=6, dc=dc,
        battlefield_transform=arena, bundle_transform=transform)
    S.settle(t, mid, S.candidate(c, mid, 'Prepare senses').candidate_id)
    return c, t, mid


def cast(c, t, mid, at=(5, 6), **kw):
    return S.settle(t, mid, S.candidate(c, mid, 'Obscure Passage', at=at).candidate_id,
                    picks={'choice:needle.passage_direction': 'east', **kw})


def test_temporary_passage_geometry_restores_unmarred_on_end(tmp_path):
    c, t, mid = fixture(tmp_path)
    cast(c, t, mid)
    e = S.reload(tmp_path, mid)
    assert not e.grid.terrain_at((5, 6, 0), 'BLOCKED')
    assert e.grid.terrain_at((5, 6, 2), 'BLOCKED')  # outside the 6-foot opening
    aperture = next(z.trigger_profile['aperture'] for z in e.state.zones.values() if z.active)
    assert aperture['diameter_ft'] == 6 and aperture['maximum_depth_ft'] == 20
    S.settle(t, mid, S.candidate(c, mid, 'End passage').candidate_id)
    assert S.reload(tmp_path, mid).grid.terrain_at((5, 6, 0), 'BLOCKED')


@pytest.mark.parametrize('sense,visible', [(None, False), ('darkvision', False), ('truesight', True)])
def test_passage_blocks_light_and_ordinary_darkvision(tmp_path, sense, visible):
    c, t, mid = fixture(tmp_path, sense=sense)
    cast(c, t, mid)
    e = S.reload(tmp_path, mid)
    owner, foe = e.state.actors[S.OWNER], e.state.actors[S.FOE]
    assert not light_transmits(e, owner.position, foe.position)
    assert senses.perceives(e, owner, foe) is visible


def test_exceptionally_hard_surface_fails_after_payment(tmp_path):
    c, t, mid = fixture(tmp_path, hard=True)
    before = S.reload(tmp_path, mid).state.actors[S.OWNER].resources['resource:core.qi']
    cast(c, t, mid)
    e = S.reload(tmp_path, mid)
    assert e.state.actors[S.OWNER].resources['resource:core.qi'] == before - 1
    assert e.grid.terrain_at((5, 6, 0), 'BLOCKED')
    assert not any(z.active and z.trigger_profile.get('aperture') for z in e.state.zones.values())


def test_standing_creature_save_chooses_nearest_safe_relocation(tmp_path):
    c, t, mid = fixture(tmp_path, wall=False, dc=-100)
    prompts = cast(c, t, mid, at=(6, 6), **{'choice:needle.passage_save': 'save'})
    e = S.reload(tmp_path, mid)
    assert any(p['context']['reaction_source_id'] == 'choice:needle.passage_safe' for p in prompts)
    assert e.grid.distance_ft(Position(x=6, y=6), e.state.actors[S.FOE].position) == 5


def test_automatic_standing_creature_saves_and_relocates_without_player_prompt(tmp_path):
    c, t, mid = fixture(tmp_path, wall=False, dc=-100)
    c.set_controller_mode(mid, actor_id=S.FOE, controller_mode='LOCAL_AUTO')
    prompts = cast(c, t, mid, at=(6, 6))
    e = S.reload(tmp_path, mid)
    assert not any(p['context']['reaction_source_id'] in ('choice:needle.passage_save', 'choice:needle.passage_safe') for p in prompts)
    assert e.grid.distance_ft(Position(x=6, y=6), e.state.actors[S.FOE].position) == 5
