"""Afterimage map lifecycle through native table movement and journal reload."""
import pytest

from combat import motion, senses
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from tests.auto8f1_table_support import OWNER, FOE, SECOND, fixture, candidate_id, reload_identical
from tests.test_a2_athletics import explicit_move

FEATURE = "TAL_ATHLETICS_AFTERIMAGE"
SOURCE = "passive:" + FEATURE


def actions(bundles):
    for bundle in bundles:
        for label, effects in (
            ("Hide source", [{"type": "condition", "condition": "invisible", "applies_to": "self"}]),
            ("Close eyes", [{"type": "condition", "condition": "blinded", "applies_to": "self"}]),
            ("End image condition", [{"type": "remove_condition", "condition": "afterimage", "applies_to": "self"}]),
            ("Unrelated image condition", [{"type": "condition", "condition": "afterimage", "applies_to": "self"}]),
        ):
            action = ActionDefinition(source_definition_id="action:test.image." + bundle["actor_id"] + "." + label.replace(" ", "_"),
                display_name=label, owner_id=bundle["actor_id"], economy=EconomyKind.NONE,
                resolution_kind="TYPED", target_kind="SELF", parameters={"free_primary": True, "typed": {
                    "effects": effects, "numbers": {}, "riders": [], "duration": {"kind": "instant"}}})
            bundle["action_catalog"].append(action.model_dump(mode="json"))
            bundle["actor_template"]["action_ids"].append(action.source_definition_id)


def game(tmp_path, talents=(FEATURE,)):
    return fixture(tmp_path, list(talents), seed="mgr-t14-map", ask=False, bundle_transform=actions,
        places={OWNER: {"x": 2, "y": 6}, FOE: {"x": 8, "y": 7}, SECOND: {"x": 5, "y": 9}})


def move(g):
    return explicit_move(g, [{"x": x, "y": 6} for x in range(2, 8)])


def image(engine):
    owner = engine.state.actors[OWNER]
    held = next(c for c in owner.conditions.values() if c.condition_id == motion.AFTERIMAGE)
    object_id = held.data.get("image_object_id")
    assert object_id in engine.state.map_images, "native Afterimage must create its map image"
    return held, engine.state.map_images[object_id]


@pytest.mark.parametrize("ending", ["expiry", "condition"])
def test_native_map_identity_stationary_lifecycle_and_reload(tmp_path, ending):
    g = game(tmp_path)
    before = g["reload_owner"]().resources.copy()
    move(g)
    engine = g["stored_engine"]()
    held, obj = image(engine)
    assert obj.position == engine.state.actors[OWNER].position
    assert (obj.position.x, obj.position.y, obj.position.z) == (7, 6, 0)
    assert obj.owner_id == OWNER and obj.component["condition_instance_id"] == held.instance_id
    assert obj.component["source_definition_id"] == SOURCE
    assert obj.component["intent_id"]
    assert obj.current_hp is None and obj.ac is None and not obj.component["blocks"]
    assert len([o for o in engine.state.map_images.values() if not o.destroyed]) == 1
    assert obj.object_id not in engine.state.objects, "image cannot occupy physical object capacity or menus"
    assert g["reload_owner"]().resources == before
    assert g["reload_owner"]().movement_remaining_ft == 5
    rows = g["table"].state(g["match_id"])["objects"]
    projected = next(r for r in rows if r["id"] == obj.object_id)
    assert projected["name"] == "Afterimage" and OWNER not in str(projected)
    assert projected["map_marker"] == 1 and projected["hp"] is None
    assert obj.object_id in senses.perception(engine, engine.state.actors[FOE])["objects"]
    reload_identical(g["combat"], g["match_id"], g["userdata"])
    explicit_move(g, [{"x": 7, "y": 6}, {"x": 8, "y": 6}])
    later = g["stored_engine"]()
    assert image(later)[1].object_id == obj.object_id
    assert image(later)[1].position == obj.position
    if ending == "condition":
        g["commit"](candidate_id(g["menu"](), "End image condition"))
    else:
        g["commit"](g["menu"]()["end_turn"])
        g["to_owner"]()
    ended = g["stored_engine"]()
    assert not motion.has_afterimage(ended.state.actors[OWNER])
    assert ended.state.map_images[obj.object_id].destroyed
    assert not any(r["id"] == obj.object_id for r in g["table"].state(g["match_id"])["objects"])
    reload_identical(g["combat"], g["match_id"], g["userdata"])


def test_image_perception_does_not_disclose_invisible_source(tmp_path):
    g = game(tmp_path)
    g["commit"](candidate_id(g["menu"](), "Hide source"))
    move(g)
    engine = g["stored_engine"]()
    held, obj = image(engine)
    from combat.ext.afterimage_targeting import perceived_image
    viewer, owner = engine.state.actors[FOE], engine.state.actors[OWNER]
    assert OWNER not in senses.perception(engine, viewer)["creatures"]
    assert perceived_image(engine, viewer, owner).object_id == obj.object_id
    g["turn_of"](FOE)
    g["commit"](candidate_id(g["menu"](), "Close eyes"))
    engine = g["stored_engine"]()
    assert perceived_image(engine, engine.state.actors[FOE], engine.state.actors[OWNER]) is None
    assert obj.object_id not in senses.perception(engine, engine.state.actors[FOE])["objects"]
    reload_identical(g["combat"], g["match_id"], g["userdata"])


def test_nonowner_has_no_image(tmp_path):
    g = game(tmp_path, talents=())
    move(g)
    assert not motion.has_afterimage(g["reload_owner"]())
    assert not g["stored_engine"]().state.map_images


def test_public_destruction_receipt_and_stale_identity_are_inert(tmp_path):
    g = game(tmp_path)
    move(g)
    engine = g["stored_engine"]()
    held, obj = image(engine)
    from combat.ext.afterimage_targeting import perceived_image, destroy_image
    owner, viewer = engine.state.actors[OWNER], engine.state.actors[FOE]
    before = engine.state.model_dump(mode="json")
    assert perceived_image(engine, viewer, owner).object_id == obj.object_id
    assert perceived_image(engine, viewer, owner).object_id == obj.object_id
    assert engine.state.model_dump(mode="json") == before
    assert not destroy_image(engine, "missing", "action:test.targeting", FOE, "intent:test")
    assert destroy_image(engine, obj.object_id, "action:test.targeting", FOE, "intent:test")
    assert engine.state.map_images[obj.object_id].destroyed
    assert engine.state.map_images[obj.object_id].component["destruction_intent_id"] == "intent:test"
    assert held.instance_id not in owner.conditions
    assert perceived_image(engine, viewer, owner) is None
    assert not destroy_image(engine, obj.object_id, "action:test.targeting", FOE, "intent:test")


def test_wrong_source_condition_does_not_gain_map_image(tmp_path):
    g = game(tmp_path)
    g["commit"](candidate_id(g["menu"](), "Unrelated image condition"))
    engine = g["stored_engine"]()
    assert motion.has_afterimage(engine.state.actors[OWNER])
    assert not engine.state.map_images
    reload_identical(g["combat"], g["match_id"], g["userdata"])


def test_native_successful_image_targeting_destruction_reloads(tmp_path):
    g = game(tmp_path)
    move(g)
    held, obj = image(g["stored_engine"]())
    explicit_move(g, [{"x": 7, "y": 6}, {"x": 8, "y": 6}])
    hp = g["reload_owner"]().current_hp
    g["turn_of"](FOE)
    g["commit"](candidate_id(g["menu"](), "Unarmed Strike"))
    engine = g["stored_engine"]()
    assert any(e.event_type == "CONDITION_REMOVED" and e.payload.get("instance_id") == held.instance_id
               for e in engine.events), "fixture seed must successfully target the native image"
    assert engine.state.map_images[obj.object_id].destroyed
    assert engine.state.actors[OWNER].current_hp == hp
    reload_identical(g["combat"], g["match_id"], g["userdata"])
