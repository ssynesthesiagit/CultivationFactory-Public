"""Shelter's printed two-choice and one Dexterity-save cover behavior at a table."""
from copy import deepcopy

from tests.r1i_service_support import OWNER, FOE, SECOND, candidate, fixture
from tests.test_r1i_round3 import reload
from tests.test_riders_c16 import SEED, SOWN, VG

GROVE = VG + "SHELTER_GROVE_POSTURE"
CHOICE = "choice:needle.verdant_shelter"


def add_dex_save(bundles):
    for bundle in bundles:
        if bundle["actor_id"] == OWNER:
            base = next(a for a in bundle["action_catalog"] if a["display_name"] == "Seed-Thorn Strike")
            action = deepcopy(base)
            action.update(source_definition_id="test:c16.mark_probe", display_name="Mark probe", target_kind="ALLY_OR_SELF", economy="NONE")
            action["parameters"]["typed"].update(effects=[{"type": "mark", "mark": "Growth Mark", "applies_to": "target"}],
                                                   source="test:c16.mark_probe")
            bundle["action_catalog"].append(action)
            bundle["actor_template"]["action_ids"].append(action["source_definition_id"])
        if bundle["actor_id"] != FOE:
            continue
        base = next(a for a in bundle["action_catalog"] if a["display_name"] == "Seed-Thorn Strike")
        action = deepcopy(base)
        action.update(source_definition_id="test:c16.dex_save", display_name="Dexterity Save Probe", target_kind="HOSTILE_ENTITY",
                      range_ft=60, economy="NONE")
        action["parameters"]["typed"].update(effects=[{"type": "save", "ability": "DEX", "dc": 1,
                                                        "on_fail": [], "on_success": [],
                                                        "evidence": "The target makes a Dexterity saving throw."}],
                                               range_ft=60, source="test:c16.dex_save")
        bundle["action_catalog"].append(action)
        bundle["actor_template"]["action_ids"].append(action["source_definition_id"])
    for bundle in bundles:
        bundle.pop("bundle_sha256", None)
    from combat.canonical import canonical_sha256
    for bundle in bundles:
        bundle["bundle_sha256"] = canonical_sha256(bundle)


def test_shelter_grove_requires_two_options_and_cover_protects_one_dex_save(tmp_path):
    combat, table, mid, send, commit = fixture(
        tmp_path, [SOWN, GROVE], foe_talents=[SEED], allies=("actor:factory.r1i-third",), extra_foe=True,
        bundle_transform=add_dex_save,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 8}, SECOND: {"x": 5, "y": 8},
                   "actor:factory.r1i-third": {"x": 3, "y": 8}})
    from tests.test_c16_root_feed_choices import sow
    sow(table, mid, commit, 3, 8)
    commit(candidate(table, mid, "Mark probe", "actor:factory.r1i-third"))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    third = "actor:factory.r1i-third"
    cid = candidate(table, mid, "Verdant Response: Shelter", third)
    answers, prompts = [], []
    for _ in range(8):
        result = send(cid, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        if prompt["context"]["reaction_source_id"] == CHOICE:
            selection = ["cover", "temp_hp"]
        else:
            selection = ["marks"]
        answers.append({**prompt["context"], "selection": "USE", "option_ids": selection})
    else:
        raise AssertionError("Shelter did not finish after its two choices")
    assert any(p["context"]["reaction_source_id"] == CHOICE for p in prompts), (prompts, table.state(mid)["menu"])
    shelter_prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == CHOICE)
    assert "choose two" in shelter_prompt["moment"]
    assert {o["id"] for o in shelter_prompt["choice"]["options"]} >= {"cover", "temp_hp", "obscure"}
    engine = reload(tmp_path, mid)
    cover, = [c for c in engine.state.actors[third].conditions.values()
              if c.condition_id == "condition:typed.verdant_shelter_cover"]
    assert cover.data["grove_dex_save"] == 1
    assert engine.state.actors[third].temporary_hp == 4

    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == "condition:typed.verdant_shelter_cover"
               for c in engine.state.actors[third].conditions.values())
    cid = candidate(table, mid, "Dexterity Save Probe", third)
    commit(cid)
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[FOE]
    action = next(engine.action_catalog[action_id] for action_id in foe.action_ids
                  if engine.action_catalog[action_id].display_name == "Dexterity Save Probe")
    typed = action.parameters["typed"]
    rolls = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == third]
    assert rolls and rolls[-1].payload.get("dc") == int(typed["numbers"]["save_dc"]) - 2
    assert not any(c.condition_id == "condition:typed.verdant_shelter_cover"
                   for c in engine.state.actors[third].conditions.values())

    # The one-save cover is spent. A later Dexterity save must use its full DC.
    cid = candidate(table, mid, "Dexterity Save Probe", third)
    commit(cid)
    engine = reload(tmp_path, mid)
    rolls = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.actor_id == third]
    assert len(rolls) >= 2 and rolls[-1].payload.get("dc") == int(typed["numbers"]["save_dc"])
    assert not any(c.condition_id == "condition:typed.verdant_shelter_cover"
                   for c in engine.state.actors[third].conditions.values())
