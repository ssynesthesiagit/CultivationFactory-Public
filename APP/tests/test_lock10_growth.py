"""Recorded growth: native geometry, public effective-size contract and saved Table actions."""
import pytest

from combat import dynamic_size
from combat.ext.effective_size import cells
from combat.gate2_grid import SquareGrid
from combat.gate2_runtime_models import Position
from combat.gate5_service import CombatService
from tests.h1_support import duel, ME, FOE, ready, use, ROOT
from tests.test_tabletop_hunt6 import table_fight, LEFT
from tests.test_lock2_persistence import act

TITAN = "tianxia.subpath.body.flesh_crucible.feature.titan_s_frame"
ONI = "tianxia.subpath.body.oni_blood.feature.oni_form"


def grow(e, who=ME, size="Large", source="test:growth", **kw):
    dynamic_size.apply_growth(e, e.state.actors[who], size, source,
        source_actor_id=who, expires_on="UNTIL_REMOVED", **kw)


def remove(e, source):
    actor = e.state.actors[ME]
    for key, row in list(actor.conditions.items()):
        if row.source_definition_id == source:
            del actor.conditions[key]
            e._append_event("CONDITION_REMOVED", source, actor_id=ME, target_ids=(ME,),
                payload={"instance_id":key, "condition_id":row.condition_id})


def test_growth_relocates_to_nearest_legal_space_and_uses_occupied_edges():
    e = duel([])
    a, foe = e.state.actors[ME], e.state.actors[FOE]
    # Right-adjacent foe blocks the old anchor's expansion. The nearest legal
    # anchor is left, with a stable coordinate tie-break.
    grow(e)
    assert a.position == Position(x=2, y=5)
    assert e._footprint(a).width_cells == 2
    assert e._distance_actor_to_actor(a, foe) == 5
    assert not set(e._footprint(a).occupied_cells(a.position)) & set(e._footprint(foe).occupied_cells(foe.position))
    receipt = next(ev for ev in e.events if ev.event_type == "FOOTPRINT_CHANGED")
    assert receipt.payload["size_category"] == "Large"
    remove(e, "test:growth")
    assert a.transformed_size_category is None and e._footprint(a).width_cells == 1


@pytest.mark.parametrize("side, expected", [(1,"Medium"),(2,"Large"),(3,"Huge")])
def test_growth_clamps_to_largest_fitting_size(side, expected):
    e = duel([])
    e.state.actors[FOE].active = False
    e.state.actors[ME].position = Position(x=0,y=0)
    e.grid = SquareGrid({"width_squares":side,"height_squares":side,"square_size_ft":5,"terrain_regions":[],"starting_positions":{}})
    grow(e, size="Gargantuan")
    assert dynamic_size.current_category(e, e.state.actors[ME]) == expected
    c = next(c for c in e.state.actors[ME].conditions.values() if c.condition_id == dynamic_size.CONDITION)
    assert c.data["growth_category"] == expected


def test_multiple_sources_refresh_without_stacking_and_restore_remaining_size():
    e=duel([])
    e.state.actors[FOE].position=Position(x=10,y=10)
    grow(e, source="test:large")
    grow(e, size="Huge", source="test:huge")
    grow(e, size="Huge", source="test:huge")
    a=e.state.actors[ME]
    assert len([c for c in a.conditions.values() if c.condition_id == dynamic_size.CONDITION]) == 2
    assert e._footprint(a).width_cells == 3
    remove(e,"test:huge")
    assert e._footprint(a).width_cells == 2
    remove(e,"test:large")
    assert e._footprint(a).width_cells == 1


def test_effective_size_adds_functional_step_without_extra_reach_or_space():
    e=duel([])
    grow(e,functional_steps=1)
    a=e.state.actors[ME]
    assert cells(e,a,"act",{"grapple"}) == 3
    assert cells(e,a,"resist",{"shove"}) == 3
    assert cells(e,a,"act",set()) == 2
    assert e._footprint(a).width_cells == 2


def test_native_grapple_size_gate_reads_transformation_and_functional_steps():
    from combat import typed_executor as te
    e=duel([])
    grow(e,who=FOE,size="Huge")
    actor,target=e.state.actors[ME],e.state.actors[FOE]
    action=next(iter(e.action_catalog.values())).model_copy(update={"range_ft":500})
    ctx=te.Context(e,actor,action,None,{"numbers":{"save_dc":16}},[target],target,{})
    row={"type":"save","ability":"str","max_size_larger":0,
         "on_fail":[{"type":"condition","condition":"grappled","applies_to":"target"}]}
    before=len(e.rolls)
    te.block_save(ctx,row)
    assert len(e.rolls)==before  # Huge is too big for the normal creature.
    grow(e,functional_steps=1)
    te.block_save(ctx,row)
    assert len(e.rolls)>before  # Large plus its one functional step can try.


@pytest.mark.parametrize("mid,name",[(TITAN,"Titan's Frame"),(ONI,"Oni Form")])
def test_compiled_owned_ability_changes_size_and_refreshes(mid,name):
    e=duel([mid],primary="Stamina")
    use(e,name)
    a=e.state.actors[ME]
    assert a.transformed_size_category == "Large"
    c=next(c for c in a.conditions.values() if c.condition_id == dynamic_size.CONDITION)
    assert c.expires_on.startswith("START_OF_SLOT_AT:")
    if mid == TITAN:
        ready(e)
        use(e,name)
        assert a.transformed_size_category == "Large"
        assert len([c for c in a.conditions.values() if c.condition_id == dynamic_size.CONDITION]) == 1


@pytest.mark.parametrize("mid",[TITAN,ONI])
def test_table_owned_growth_reloads_replays_and_expires(tmp_path,monkeypatch,mid):
    combat,table,match=table_fight(tmp_path,[mid],primary="Stamina")
    source=next(g["source_definition_id"] for g in table.state(match)["menu"]["actions"] if mid in g["source_definition_id"])
    assert act(table,match,source)["status"] == "COMMITTED"
    loaded=CombatService(ROOT,tmp_path)._load_session(match)
    a=loaded.engine.state.actors[LEFT]
    assert a.transformed_size_category == "Large"
    assert loaded.mechanical.replay()["status"] == "PASS"
    view = next(a for a in table.state(match)["presentation"]["actors"] if a["entity_id"] == LEFT)
    assert view["footprint"]["width_cells"] == 2
    assert len(view["footprint"]["occupied_cells"]) == 4
    for _ in range(31):
        assert act(table,match,"end")["status"] == "COMMITTED"
    loaded=CombatService(ROOT,tmp_path)._load_session(match)
    a=loaded.engine.state.actors[LEFT]
    assert a.transformed_size_category is None
    assert loaded.engine._footprint(a).width_cells == 1
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("before,after",[("Tiny","Small"),("Small","Medium")])
def test_one_category_growth_preserves_small_creature_categories(before,after):
    e=duel([TITAN],primary="Stamina")
    e.state.actors[ME].size_category=before
    use(e,"Titan's Frame")
    assert e.state.actors[ME].transformed_size_category == after
    assert e._footprint(e.state.actors[ME]).width_cells == 1


def test_unowned_default_serialization_stays_small():
    e=duel([])
    a=e.state.actors[ME]
    assert "size_category" not in a.model_dump(mode="json")
    assert "transformed_size_category" not in a.model_dump(mode="json")
    assert not any(ev.event_type == "FOOTPRINT_CHANGED" for ev in e.events)
