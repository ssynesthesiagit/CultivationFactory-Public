"""Multiple Sand burials use the table's bounded manual/AI choice transport."""
import pytest

from combat.canonical import canonical_sha256
from combat.ext.sand_burial import BURIED, DIG
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE, SECOND
from tests.test_r1i_round3 import reload
from tests.test_c4_protection_review import inherited_prompt_loader

CHOICE = "choice:needle.sand_dig_free"
SCOUR = "SAND_BASE_SCOURING_HAND"


def burial_packets(second_dc):
    """Deliver two source-distinct burials through committed compiled actions.

    Test-only packets avoid zone placement/save randomness while using ordinary
    Sand condition creation, linked restraints, choice handling and persistence.
    """
    def prepare(bundles):
        for bundle, dc in zip(bundles[1:], (1, second_dc)):
            changed = False
            for action in bundle["action_catalog"]:
                if not action["display_name"].startswith("Scouring Hand"):
                    continue
                changed = True
                typed = action["parameters"]["typed"]
                typed["numbers"]["save_dc"] = dc
                typed["effects"] = [{"type": "sand_bury", "applies_to": "target",
                    "expires_on": "UNTIL_REMOVED", "restrain": "always", "with": ["blinded"]}]
                typed["riders"] = []
            assert changed
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
    return prepare


def setup_burials(tmp_path, second_dc, *, ai_casters=False, count=2):
    combat, table, mid, send, commit = fixture(tmp_path, [], foe_talents=[SCOUR],
        second_talents=[SCOUR], seed="C4-BURIAL-CHOICE",
        bundle_transform=burial_packets(second_dc))
    for caster in (FOE, SECOND)[:count]:
        while table.state(mid)["menu"]["actor_id"] != caster:
            commit(table.state(mid)["menu"]["end_turn"])
        cid = candidate(table, mid, "Scouring Hand", OWNER)
        if ai_casters:
            force_ai_candidate(combat, mid, caster, cid)
            assert send(cid, auto=True)["status"] == "COMMITTED"
            # Keep following turns bounded; AI escape is tested separately.
            combat.set_controller_mode(mid, actor_id=caster, controller_mode="MANUAL")
        else:
            commit(cid)
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    held = {c.source_actor_id: iid for iid, c in engine.state.actors[OWNER].conditions.items()
            if c.condition_id == BURIED}
    assert len(held) == count
    return combat, table, mid, send, commit, held


@pytest.mark.parametrize("ai_casters", [False, True])
@pytest.mark.parametrize("pick,second_dc", [(FOE, 2), (SECOND, 2), (SECOND, 100)])
def test_multiple_burials_manual_choose_pause_answer_commit_reload(tmp_path, ai_casters, pick, second_dc):
    combat, table, mid, send, commit, held = setup_burials(tmp_path, second_dc, ai_casters=ai_casters)
    cid = candidate(table, mid, "Dig free of the sand")
    before = reload(tmp_path, mid).state.model_dump(mode="json")
    result = send(cid)
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt.get("choice"), "manual burial selection requires a registered dynamic choice specification"
    assert prompt["context"]["reaction_source_id"] == CHOICE
    assert prompt["context"]["reactor_id"] == OWNER
    assert send(cid)["reaction"] == prompt
    assert reload(tmp_path, mid).state.model_dump(mode="json") == before
    options = prompt["choice"]["options"]
    assert {o["id"] for o in options} == set(held.values())
    assert prompt["choice"]["preferred"] == [held[FOE]]
    assert "Scouring Hand" in str(options) and "Foe" in str(options) and "Second" in str(options)
    assert "Athletics or Acrobatics" in str(prompt) and "No CP or Stamina cost" in str(prompt)
    answer = {**prompt["context"], "selection": "USE", "option_ids": [held[pick]]}
    assert send(cid, [answer])["status"] == "COMMITTED"
    check_escape(tmp_path, mid, before, held, pick, second_dc)


def check_escape(tmp_path, mid, before, held, pick, second_dc):
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    checks = [e for e in engine.events if e.event_type == "CHECK_ROLLED" and e.source_definition_id == DIG]
    assert len(checks) == 1
    dc = 1 if pick == FOE else second_dc
    assert checks[0].payload["dc"] == dc
    success = dc < 100
    assert checks[0].payload["success"] == success
    removed = {held[pick]} if success else set()
    assert {iid for iid, c in actor.conditions.items() if c.condition_id == BURIED} == set(held.values()) - removed
    prior = before["actors"][OWNER]["conditions"]
    # Only the chosen burial and its own Restrained/Blinded children end.
    removed.update(iid for iid, c in prior.items() if c["data"].get("parent_hold") in removed)
    assert set(actor.conditions) == set(prior) - removed
    for iid, condition in actor.conditions.items():
        assert condition.model_dump(mode="json") == prior[iid]
    assert actor.resources == before["actors"][OWNER]["resources"]
    assert actor.current_hp == before["actors"][OWNER]["current_hp"]
    assert before["actors"][OWNER]["action_available"] and not actor.action_available
    assert actor.reaction_available == before["actors"][OWNER]["reaction_available"]
    assert not any(e.event_type == "RESOURCE_SPENT" and e.source_definition_id == DIG for e in engine.events)
    return engine


@pytest.mark.parametrize("second_dc", [2, 100])
def test_multiple_burials_ai_escaper_selects_easiest_without_prompt(tmp_path, second_dc):
    combat, table, mid, send, commit, held = setup_burials(tmp_path, second_dc, ai_casters=True)
    cid = candidate(table, mid, "Dig free of the sand")
    force_ai_candidate(combat, mid, OWNER, cid)
    before = reload(tmp_path, mid).state.model_dump(mode="json")
    assert send(cid, auto=True)["status"] == "COMMITTED"
    check_escape(tmp_path, mid, before, held, FOE, second_dc)


@pytest.mark.parametrize("ai_escaper", [False, True])
def test_single_burial_needs_no_selection_and_removes_only_linked_conditions(tmp_path, ai_escaper):
    combat, table, mid, send, commit, held = setup_burials(tmp_path, 2, count=1)
    cid = candidate(table, mid, "Dig free of the sand")
    if ai_escaper:
        force_ai_candidate(combat, mid, OWNER, cid)
    before = reload(tmp_path, mid).state.model_dump(mode="json")
    assert send(cid, auto=ai_escaper)["status"] == "COMMITTED"
    engine = check_escape(tmp_path, mid, before, held, FOE, 2)
    assert not engine.state.actors[OWNER].conditions


@pytest.mark.parametrize("pick", [FOE, SECOND])
def test_second_escape_after_reload_clears_remaining_burial_without_another_choice(tmp_path, pick):
    combat, table, mid, send, commit, held = setup_burials(tmp_path, 2)
    cid = candidate(table, mid, "Dig free of the sand")
    result = send(cid)
    assert result["status"] == "REACTION_REQUIRED", result
    answer = {**result["reaction"]["context"], "selection": "USE", "option_ids": [held[pick]]}
    assert send(cid, [answer])["status"] == "COMMITTED"
    assert len([c for c in reload(tmp_path, mid).state.actors[OWNER].conditions.values()
                if c.condition_id == BURIED]) == 1
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    assert send(candidate(table, mid, "Dig free of the sand"))["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert not engine.state.actors[OWNER].conditions
    checks = [e for e in engine.events if e.event_type == "CHECK_ROLLED" and e.source_definition_id == DIG]
    assert [e.payload["dc"] for e in checks] == ([1, 2] if pick == FOE else [2, 1])
    assert all(e.payload["success"] for e in checks)
    assert all(g["label"] != "Dig free of the sand" for g in table.state(mid)["menu"]["actions"])
