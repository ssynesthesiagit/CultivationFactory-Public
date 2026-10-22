"""Impact Collision recipients through portable sheets, map save, table commit and cold replay.

No synthetic actions, ownership markers or collision facts: the table's actual
Hammer/Brutal Shove acquisition and map objects supply the tested behavior.
"""
import json
import zipfile

import pytest

from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.worker2_support import settle, turn, candidate
from tests.r1i_service_support import force_ai_candidate

OWNER = "actor:factory.impact-owner"
FOE = "actor:factory.impact-foe"
BLOCKER = "actor:factory.impact-blocker"
BASE = "BRUTE_BASE_IMPACT_COLLISION"
HAMMER = "TAL_BRUTE_HAMMER"
ONI_FORM = "tianxia.subpath.body.oni_blood.feature.oni_form"


def start(tmp_path, *, objects=(), hammer=True, creature=False, wrong_owner=False, moving_large=False,
          walls=(), edge=False):
    documents = {
        OWNER: sheet([HAMMER] if hammer else [BASE]),
        FOE: sheet([]),
    }
    if moving_large:
        documents[FOE] = sheet([ONI_FORM], cl=17, primary="Stamina")
        documents[FOE]["identity"]["path"] = "Body Refining"
    if creature:
        documents[BLOCKER] = sheet([ONI_FORM, *([HAMMER] if wrong_owner else [])], cl=17, primary="Stamina")
        documents[BLOCKER]["identity"]["path"] = "Body Refining"
    for aid, doc in documents.items():
        stats = doc["ability_scores_and_statistics"]
        stats["hit_points"]["maximum"] = 500
        stats["skills"] = [{"skill": skill, "bonus": 10 if aid == OWNER else -10}
                           for skill in ("Athletics", "Acrobatics")]
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    saved = combat.tabletop_maps.save({
        "display_name": "Impact Collision yard", "width_squares": 20, "height_squares": 18,
        "starts": {"team1": [[3, 6], [5, 5]] if creature else [[17, 6]] if edge else [[3, 6]],
                   "team2": [[18, 6]] if edge else [[4, 6]]},
        "objects": list(objects), "walls": list(walls),
    })
    projects = ["impact-owner", "impact-blocker"] if creature else ["impact-owner"]
    mid = combat.create_factory_match(project_ids=projects, opponent_actor_ids=[FOE],
        control_modes={aid: "MANUAL" for aid in documents},
        arena_id=f"battlefield:map.{saved['map_id']}", match_seed="MGR-IMPACT")["match_id"]
    table = TabletopService(combat, tmp_path)
    if moving_large:
        turn(table, mid, FOE)
        settle(table, mid, candidate(combat, mid, "Oni Form").candidate_id)
    if creature:
        # A size label alone does not change the sealed footprint. Grow through
        # an acquired native transformation, commit it and then take our turn.
        turn(table, mid, BLOCKER)
        settle(table, mid, candidate(combat, mid, "Oni Form").candidate_id)
    turn(table, mid, OWNER)
    return combat, table, mid


def shove(tmp_path, combat, table, mid, *, auto=False):
    engine = combat._load_session(mid).engine
    before = engine.state.model_dump(mode="json")
    cid = candidate(combat, mid, "Brutal Shove", target=FOE).candidate_id
    if auto:
        force_ai_candidate(combat, mid, OWNER, cid)
    prompts = settle(table, mid, cid, {
        "choice:needle.brutal_shove_result": "push",
        "choice:needle.brute_contest_skill": "Athletics",
    }, auto=auto)
    live = combat._load_session(mid).engine
    cold = CombatService(ROOT, tmp_path)._load_session(mid)
    assert cold.mechanical.replay()["status"] == "PASS"
    assert cold.engine.state.model_dump(mode="json") == live.state.model_dump(mode="json")
    rolls = [r for r in cold.engine.rolls if r.reason == "HAMMER_IMPACT_COLLISION"]
    return before, cold.engine, rolls, prompts


def test_native_hammer_acquisition_retains_collision_without_optional_feature_shard(tmp_path, monkeypatch):
    from combat import typed_reactions
    rules = json.loads(json.dumps(typed_reactions.rules()))
    rules['features'].pop(HAMMER, None)
    path = tmp_path / 'portable-feature-blocks.json'
    path.write_text(json.dumps(rules))
    monkeypatch.setattr(typed_reactions, 'RULES_PATH', path)
    monkeypatch.setattr(typed_reactions, '_CACHE', {})
    combat, table, mid = start(tmp_path, objects=[{'kind': 'custom', 'material': 'iron',
        'size': 'medium', 'blocks': True, 'hp': 1000, 'x': 5, 'y': 6}])
    engine = combat._load_session(mid).engine
    assert len([r for r in engine.typed_passive_rows[OWNER]
                if r.get('block') == 'brute_hammer_owned' and r.get('feature_id') == HAMMER]) == 1
    assert not any(r.get('block') == 'brute_hammer_owned' for r in engine.typed_passive_rows.get(FOE, []))
    _, engine, rolls, _ = shove(tmp_path, combat, table, mid)
    assert len(rolls) == 1
    obj = engine.state.objects['object:map.1']
    assert obj.maximum_hp - obj.current_hp == rolls[0].total


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("profile", ["ordinary", "resistant", "threshold", "attended", "artifact"])
def test_placed_object_receives_same_bludgeoning_packet_with_native_defenses(tmp_path, auto, profile):
    obj = {"kind": "custom", "name": "Collision block", "size": "medium", "material": "iron",
           "hp": 1000, "blocks": True, "x": 5, "y": 6}
    if profile in ("resistant", "artifact"):
        obj["resist"] = ["BLUDGEONING"]
    if profile == "artifact":
        obj["artifact"] = True
    if profile == "threshold":
        obj["threshold"] = 1000
    if profile == "attended":
        obj["unattended"] = False
    combat, table, mid = start(tmp_path, objects=[obj])
    before, engine, rolls, prompts = shove(tmp_path, combat, table, mid, auto=auto)
    assert len(rolls) == 1  # one collision per shove sequence
    assert engine.state.actors[FOE].position.model_dump(mode="json") == before["actors"][FOE]["position"]
    updates = [e for e in engine.events if e.event_type == "OBJECT_UPDATED" and e.source_definition_id.endswith("BRUTE_BASE_BRUTAL_SHOVE")
               and e.payload.get("damage")]
    expected = (0 if profile in ("threshold", "attended") else
                rolls[0].total // 2 if profile in ("resistant", "artifact") else rolls[0].total)
    obj = engine.state.objects["object:map.1"]
    assert obj.maximum_hp - obj.current_hp == expected
    assert len(updates) == int(profile != "attended")
    if updates:
        assert updates[0].payload["damage"]["taken"] == expected
    damage = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]
    assert any(e.payload.get("damage_type") == "BLUDGEONING" for e in damage)


@pytest.mark.parametrize("block_first", [False, True])
def test_shared_square_hits_only_the_actual_blocker(tmp_path, block_first):
    block = {"kind": "blacksmith_anvil", "x": 5, "y": 6, "hp": 1000}
    cushion = {"kind": "meditation_cushion", "x": 5, "y": 6, "hp": 1000}
    rows = [block, cushion] if block_first else [cushion, block]
    combat, table, mid = start(tmp_path, objects=rows)
    _, engine, rolls, _ = shove(tmp_path, combat, table, mid)
    assert len(rolls) == 1
    block_id, cushion_id = ("object:map.1", "object:map.2") if block_first else ("object:map.2", "object:map.1")
    obj = engine.state.objects[block_id]
    cushion = engine.state.objects[cushion_id]
    assert obj.current_hp == obj.maximum_hp - rolls[0].total
    assert cushion.current_hp == cushion.maximum_hp


@pytest.mark.parametrize("wrong_owner", [False, True])
def test_collision_uses_creature_footprint_and_never_borrows_hammer(tmp_path, wrong_owner):
    combat, table, mid = start(tmp_path, creature=True, hammer=not wrong_owner, wrong_owner=wrong_owner)
    before, engine, rolls, _ = shove(tmp_path, combat, table, mid)
    blocker = engine.state.actors[BLOCKER]
    assert blocker.position.x == 5 and blocker.position.y == 5
    assert engine._footprint(blocker).width_cells == 2
    assert engine.state.actors[FOE].position.model_dump(mode="json") == before["actors"][FOE]["position"]
    assert len(rolls) == int(not wrong_owner)
    previous = before["actors"][BLOCKER]
    assert (previous["current_hp"] + previous["temporary_hp"]
            - blocker.current_hp - blocker.temporary_hp) == (rolls[0].total if rolls else 0)


def test_open_path_has_no_impact_packet(tmp_path):
    combat, table, mid = start(tmp_path)
    before, engine, rolls, _ = shove(tmp_path, combat, table, mid)
    assert not rolls
    assert engine.state.actors[FOE].position.x > before["actors"][FOE]["position"]["x"]


@pytest.mark.parametrize("obstacle_size", ["tiny", "small", "medium", "large"])
def test_transformed_mover_leading_edge_hits_only_size_eligible_object(tmp_path, obstacle_size):
    obj = {"kind": "custom", "name": "Leading edge block", "size": obstacle_size,
           "material": "iron", "hp": 500, "blocks": True, "x": 6, "y": 7}
    combat, table, mid = start(tmp_path, objects=[obj], moving_large=True)
    before, engine, rolls, _ = shove(tmp_path, combat, table, mid)
    mover = engine.state.actors[FOE]
    assert engine._footprint(mover).width_cells == 2
    assert mover.position.model_dump(mode="json") == before["actors"][FOE]["position"]
    eligible = obstacle_size in ("medium", "large")
    assert len(rolls) == int(eligible)
    block = engine.state.objects["object:map.1"]
    assert block.maximum_hp - block.current_hp == (rolls[0].total if eligible else 0)


def test_native_authored_wall_stops_shove_and_commits_only_one_collision(tmp_path):
    wall = {'shape': 'line', 'points': [[5, 5], [5, 7]], 'height_ft': 10}
    combat, table, mid = start(tmp_path, walls=[wall])
    before, engine, rolls, _ = shove(tmp_path, combat, table, mid)
    assert len(rolls) == 1
    foe = engine.state.actors[FOE]
    assert foe.position.model_dump(mode='json') == before['actors'][FOE]['position']
    packets = [e.payload for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
               and FOE in e.target_ids]
    assert sum(p['rolled_or_pending_damage'] == rolls[0].total for p in packets) == 1
    # Brutal Shove also has its own ordinary damage; it is not a second
    # collision. Match the actual committed HP ledger instead of omitting it.
    assert before['actors'][FOE]['current_hp'] - foe.current_hp == sum(p['hp_damage'] for p in packets)
    assert not engine.state.objects


def test_map_boundary_is_not_an_invented_physical_collision(tmp_path):
    combat, table, mid = start(tmp_path, edge=True)
    _, engine, rolls, _ = shove(tmp_path, combat, table, mid)
    assert not rolls
    assert engine.state.actors[FOE].position.x == 19


@pytest.mark.parametrize('eligible_first', [False, True])
def test_size_eligible_contact_is_not_hidden_by_an_undersized_shared_object(tmp_path, eligible_first):
    common = {'kind': 'custom', 'x': 6, 'y': 7, 'hp': 500, 'blocks': True, 'material': 'iron'}
    # Two different leading-edge cells of the same attempted large-body step.
    # A Medium object already fills its square, so putting Tiny beside it in
    # that same square would correctly fail native map capacity admission.
    tiny = {**common, 'name': 'Tiny block', 'size': 'tiny', 'y': 6}
    medium = {**common, 'name': 'Medium block', 'size': 'medium'}
    rows = [medium, tiny] if eligible_first else [tiny, medium]
    combat, table, mid = start(tmp_path, objects=rows, moving_large=True)
    _, engine, rolls, _ = shove(tmp_path, combat, table, mid)
    assert len(rolls) == 1
    for index, row in enumerate(rows, 1):
        obj = engine.state.objects[f'object:map.{index}']
        assert obj.maximum_hp - obj.current_hp == (rolls[0].total if row['size'] == 'medium' else 0)
