"""The light result chooses one new effect, not a prior use's area/object."""
import copy

import pytest

from combat import lighting
from combat.canonical import canonical_sha256
from combat.typed_executor import bears_mark
from tests.h1_support import sheet
from tests.lighting_support import map_arena, map_document
from tests.test_r9i_karma_persistence import act
from tests.worker2_support import FOE, OWNER, candidate, fixture, reload, settle, turn

SMALL = "TAL_YANG_THE_ACTION_CANNOT_STAY_SMALL"


def _creations(bundle):
    source = "action:test.lighting.created_effects"
    base = {"source_definition_id": source, "display_name": "Create test ward", "owner_id": bundle["actor_id"],
        "economy": "ACTION", "resolution_kind": "TYPED", "target_kind": "ANY_CREATURE", "range_ft": 90,
        "costs": [], "parameters": {"typed": {"numbers": {"cl": 15, "pb": 4, "save_dc": 100},
        "duration": {"kind": "instant"}, "riders": [], "effects": [
        {"type": "terrain_patch", "center": {"x": 10, "y": 3}, "name": "Test ward area",
         "duration": {"kind": "minutes", "amount": 1}},
        {"type": "bound_object", "name": "Test ward object", "guards_zone": True, "ac": 1, "hp": 50}]}}}
    damage = copy.deepcopy(base)
    damage.update(source_definition_id=source + ".damage", display_name="Damage test ward", economy="BONUS_ACTION")
    damage["parameters"]["typed"]["effects"] = [{"type": "object_damage", "dice": {"count": 1, "sides": 1},
                                               "flat": 1, "damage_types": ["force"]}] * 2
    for row in (base, damage):
        bundle["action_catalog"].append(row)
        bundle["actor_template"]["action_ids"].append(row["source_definition_id"])
    bundle.pop("bundle_sha256", None)
    bundle["bundle_sha256"] = canonical_sha256(bundle)


def _answer_created(table, mid, cid, kind):
    answers, prompts = [], []
    for _ in range(20):
        response = act(table, mid, cid, answers)
        if response["status"] != "REACTION_REQUIRED":
            assert response["status"] == "COMMITTED", response
            return prompts
        prompt = response["reaction"]
        prompts.append(prompt)
        rid = prompt["context"]["reaction_source_id"]
        ids = [o["id"] for o in (prompt.get("choice") or {}).get("options") or []]
        pick = {"choice:willing.consent": "refuse", "choice:needle.overcomplete_result": "light"}.get(rid)
        if rid == "choice:needle.overcomplete_recipient":
            pick = next(key for key in ids if key.startswith(kind + ":"))
        answer = {**prompt["context"], "selection": "USE"}
        if prompt.get("choice"):
            answer["option_ids"] = [pick or ids[0]]
        answers.append(answer)
    raise AssertionError("Unsettled created-effect choice")


@pytest.mark.parametrize("kind", ["zone", "object"])
def test_only_the_selected_new_created_effect_carries_light_and_vulnerability(tmp_path, kind):
    foe_sheet = sheet([])
    foe_sheet["ability_scores_and_statistics"]["hit_points"]["maximum"] = 400
    foe_sheet["ability_scores_and_statistics"]["armor_class"]["base_value"] = 1
    combat, table, mid = fixture(tmp_path, [SMALL], owner_dc=100, foe_sheet=foe_sheet,
        foe_position={"x": 3, "y": 3}, seed="WORKER2",
        bundle_transform=lambda bundles: _creations(bundles[2]))
    # An older use of exactly the same source is not this triggering use.
    turn(table, mid, FOE)
    settle(table, mid, candidate(combat, mid, "Create test ward", target=OWNER).candidate_id)
    old = reload(tmp_path, mid)
    old_ids = set(old.state.zones) | set(old.state.objects)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Rising Thread", target=FOE).candidate_id)
    assert bears_mark(reload(tmp_path, mid).state.actors[FOE], OWNER, "Overkindled Mark")
    turn(table, mid, FOE)
    marked = reload(tmp_path, mid)
    assert bears_mark(marked.state.actors[FOE], OWNER, "Overkindled Mark"), f"mark ended before the triggering action;owner_turns={marked.state.actors[OWNER].turns_started}"
    prompts = _answer_created(table, mid, candidate(combat, mid, "Create test ward", target=OWNER).candidate_id, kind)
    engine = reload(tmp_path, mid)
    questions = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.overcomplete_recipient"]
    assert questions, ("prompts=" + ",".join(p["context"]["reaction_source_id"] for p in prompts)
                       + f";reaction={engine.state.actors[OWNER].reaction_available};mark={bears_mark(engine.state.actors[FOE], OWNER, 'Overkindled Mark')}"
                       + ";riders=" + "|".join(str(e.payload) for e in engine.events[-20:] if e.event_type == "GM_RIDER"))
    options = questions[0]["choice"]["options"]
    ids = {o["id"] for o in options}
    assert len(ids) == 2 and not ids & old_ids
    receipt, = [c for c in engine.state.actors[OWNER].conditions.values()
                if c.condition_id == "condition:typed.overcomplete_effect"]
    assert receipt.data["kind"] == kind and receipt.data["recipient"] in ids
    light, = [s for s in lighting.sources(engine) if s.name == "The Action Cannot Stay Small"]
    assert light.following is None and light.cells == frozenset({(10, 3)})
    assert (light.bright_ft, light.dim_ft) == (20, 20)
    if kind == "object":
        since = len(engine.events)
        row = next(c for c in engine.legal_candidates()
                   if c.target_ids == (receipt.data["recipient"],) and c.display_name.startswith("Damage test ward"))
        settle(table, mid, row.candidate_id)
        engine = reload(tmp_path, mid)
        taken = [e.payload["damage"]["taken"] for e in engine.events[since:]
                 if e.event_type == "OBJECT_UPDATED" and "damage" in e.payload]
        assert taken == [4, 2]
        assert any(s.name == "The Action Cannot Stay Small" for s in lighting.sources(engine))
    turn(table, mid, OWNER)
    assert not any(s.name == "The Action Cannot Stay Small" for s in lighting.sources(reload(tmp_path, mid)))
