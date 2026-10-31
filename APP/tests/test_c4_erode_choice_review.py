"""Erode's save belongs to the teleporting creature, including off-turn steps."""
import pytest

from combat.canonical import canonical_sha256
from combat.ext.sand_riders import ERODE, CLINGING
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE
from tests.test_r1i_round3 import reload
from tests.test_c4_protection_review import inherited_prompt_loader

SAVE = "choice:needle.sand_erode_save"
REACT = "choice:needle.sand_erode"
STEP = "TAL_VOID_EMPTY_STEP"
PATH = "TAL_VOID_HOLLOW_PATH_STEP"


def packets(bundles):
    """Keep real owned rows/costs; bound saves and isolate one teleport.

    Empty Step has an inherited duplicate teleport row. This test-only packet
    isolates choice ownership, not that separate duplication defect.
    """
    owner, foe = bundles[:2]
    foe["reaction_plan"]["mode"] = "ask"
    foe["actor_template"]["saving_throws"].update(DEX=-100, CHA=100)
    for row in foe["typed_reactions"]:
        row["ask"] = True
    for action in foe["action_catalog"]:
        if action["display_name"] == "Empty Step":
            action["parameters"]["typed"]["effects"] = [
                {"type": "teleport", "applies_to": "self", "distance_ft": 20}]
    for action in owner["action_catalog"]:
        if action["display_name"].startswith("Scouring Hand"):
            typed = action["parameters"]["typed"]
            typed["numbers"]["attack_bonus"] = -100
            typed["effects"] = [{"type": "attack", "attack_kind": "cultivation_ranged", "on_hit": []}]
            typed["riders"] = []
    for bundle in bundles:
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)


@pytest.mark.parametrize("off_turn,mode", [(False, "manual"), (False, "ai_eroder"),
    (True, "manual"), (True, "ai_mover"), (True, "ai_eroder"), (True, "ai_both")])
@pytest.mark.parametrize("save", ["DEX", "CHA"])
def test_erode_save_choice_table_pause_answer_reload(tmp_path, off_turn, mode, save):
    combat, table, mid, send, commit = fixture(tmp_path, [ERODE],
        foe_talents=[STEP, PATH], foe_ac=500, seed="C4-ERODE-SAVE",
        bundle_transform=packets)
    actor = OWNER if off_turn else FOE
    while table.state(mid)["menu"]["actor_id"] != actor:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, "Scouring Hand" if off_turn else "Empty Step", FOE if off_turn else None)
    ai_mover = mode in ("ai_mover", "ai_both")
    ai_eroder = mode in ("ai_eroder", "ai_both")
    if ai_mover:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    if ai_eroder:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    auto = ai_eroder if off_turn else ai_mover
    if auto:
        force_ai_candidate(combat, mid, actor, cid)
    before_engine = reload(tmp_path, mid)
    before = before_engine.state.model_dump(mode="json")
    start = len(before_engine.events)
    answers, prompts = [], []
    for _ in range(8):
        result = send(cid, answers, auto=auto)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        source = prompt["context"]["reaction_source_id"]
        prompts.append(source)
        assert reload(tmp_path, mid).state.model_dump(mode="json") == before
        assert send(cid, answers, auto=auto)["reaction"] == prompt
        answer = {**prompt["context"], "selection": "USE"}
        if source == SAVE:
            assert not ai_mover
            assert prompt["context"]["reactor_id"] == FOE
            assert {o["id"] for o in prompt["choice"]["options"]} == {"DEX", "CHA"}
            assert prompt["choice"]["preferred"] == ["CHA"]
            assert not prompt["choice"]["allow_decline"]
            text = str(prompt)
            assert all(label in text for label in ("Erode the Path of Return", "Foe", "Owner",
                "Dexterity", "Charisma", "No additional", "Hollow Path Step" if off_turn else "Empty Step"))
            answer["option_ids"] = [save]
        elif source == REACT:
            assert not ai_eroder
            assert prompt["context"]["reactor_id"] == OWNER
            answer["option_ids"] = ["fail"]
        else:
            assert off_turn and source in ("reaction:typed." + PATH, "choice:needle.reaction_teleport"), prompt
            if prompt.get("choice"):
                answer["option_ids"] = prompt["choice"]["preferred"][:1]
        answers.append(answer)
    else:
        pytest.fail("Erode did not commit after bounded choices")
    assert prompts.count(SAVE) == (0 if ai_mover else 1)
    assert prompts.count(REACT) == (0 if ai_eroder else 1)
    engine = reload(tmp_path, mid)
    events = engine.events[start:]
    reactions = [e for e in events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == ERODE]
    selected = "CHA" if ai_mover else save
    assert len(reactions) == 1
    assert reactions[0].payload["save"] == selected
    assert reactions[0].payload["failed"] == (selected == "DEX")
    eroder, mover = engine.state.actors[OWNER], engine.state.actors[FOE]
    assert not eroder.reaction_available
    assert eroder.resources["resource:core.qi"] == before["actors"][OWNER]["resources"]["resource:core.qi"] - 3
    payments = [e for e in events if e.event_type == "RESOURCE_SPENT" and e.source_definition_id == ERODE]
    assert [(e.payload["resource_id"], e.payload["amount"]) for e in payments] == [("resource:core.qi", 3)]
    assert (mover.position.model_dump(mode="json") != before["actors"][FOE]["position"]) == (selected == "CHA")
    assert any(c.condition_id == CLINGING for c in mover.conditions.values()) == (selected == "CHA")
    assert mover.reaction_available == (not off_turn)
    assert mover.resources["resource:core.qi"] == before["actors"][FOE]["resources"]["resource:core.qi"] - (2 if off_turn else 1)


@pytest.mark.parametrize("owned", [False, True])
def test_erode_no_save_choice_without_owned_accepted_reaction(tmp_path, owned):
    combat, table, mid, send, commit = fixture(tmp_path, [ERODE] if owned else [],
        foe_talents=[STEP, PATH], seed="C4-ERODE-CONTROL", bundle_transform=packets)
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, "Empty Step")
    before = reload(tmp_path, mid).state.model_dump(mode="json")
    result = send(cid)
    if owned:
        assert result["status"] == "REACTION_REQUIRED"
        assert result["reaction"]["context"]["reaction_source_id"] == REACT
        result = send(cid, [{**result["reaction"]["context"], "selection": "DECLINE"}])
    assert result["status"] == "COMMITTED", result
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].reaction_available
    assert engine.state.actors[OWNER].resources == before["actors"][OWNER]["resources"]
    assert engine.state.actors[FOE].position.model_dump(mode="json") != before["actors"][FOE]["position"]
    assert not any(c.condition_id == CLINGING for c in engine.state.actors[FOE].conditions.values())
    assert not any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == ERODE for e in engine.events)
