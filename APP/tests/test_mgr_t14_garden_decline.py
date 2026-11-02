"""One native zero-drop cannot bypass Garden's optional gain by another route."""
from combat.ext.foundation_context import CONTEXT
from tests.worker2_support import OWNER, FOE, reload
from tests.test_mgr_t14_garden_sum import GARDEN_NAME
from tests.test_mgr_t14_garden_actions import native_garden, cast


def test_declined_garden_drop_cannot_generate_from_damage_or_defeat(tmp_path):
    combat, table, mid = native_garden(tmp_path, hp=1,
        extra_foes=1, seed='GARDEN-ZERO-None')
    cast(combat, table, mid, GARDEN_NAME)
    before = reload(tmp_path, mid).state.event_sequence
    prompts = cast(combat, table, mid, 'Flame Lash', choices={
        CONTEXT: 'real', CONTEXT+'.detail': 'defeat',
        'choice:needle.ash_garden.generate': None})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[FOE].current_hp == 0
    assert sum(p['context']['reaction_source_id'] == 'choice:needle.ash_garden.generate'
               for p in prompts) == 1
    assert engine.state.actors[OWNER].resources['resource:foundation.funeral_ash'] == 0
    assert not any(e.event_type == 'RESOURCE_GAINED' and e.sequence > before
        and e.actor_id == OWNER and e.payload.get('resource_id') == 'resource:foundation.funeral_ash'
        for e in engine.events)
