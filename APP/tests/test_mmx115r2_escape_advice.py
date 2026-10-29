"""Table regressions for individual escape selection and independent stored-DC conditions."""

import pytest

from combat.canonical import canonical_sha256
from combat.ext.abyssal_depths import DEEP, ESCAPE, LIQUID
from combat.ext.sand_burial import BURIED, DIG
from combat.ext.thread_lines import BOUND
from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.hunt51_grapple_support import on_turn, verify_reloaded
from tests.r1i_service_support import OWNER, FOE, SECOND, candidate, fixture
from tests.test_c4_burial_choice_review import burial_packets
from tests.test_mmx115_grapple_escape_dc import (
    GRAPPLED, condition_details, fail_every_save, held_conditions, script_check,
)


def test_liquid_body_individual_escape_advice_and_selected_dc_table(tmp_path, monkeypatch):
    """Real ordinary holds, Liquid Body, manual choice, commit and reload at DC 12 vs 16."""
    fail_every_save(monkeypatch)

    def stronger_second(bundles):
        bundles[2] = compile_character(sheet([], cl=17, score=18), actor_id=SECOND)

    combat, table, mid, send, commit = fixture(tmp_path, [DEEP], foe_score=10,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 3, "y": 7}},
        bundle_transform=stronger_second, seed="MMX115R2-INDIVIDUAL")
    for actor in (FOE, SECOND):
        on_turn(table, mid, actor)
        commit(candidate(table, mid, "Grapple", OWNER))
    on_turn(table, mid, OWNER)
    commit(candidate(table, mid, "Deep’s Embrace"))
    actor = combat._load_session(mid).engine.state.actors[OWNER]
    assert any(c.condition_id == LIQUID and c.data.get("individual_escape") == 1
               for c in actor.conditions.values())
    grips = held_conditions(combat, mid, OWNER)
    assert sorted(c.data["escape_dc"] for c in grips) == [12, 16]
    chosen = next(c.instance_id for c in grips if c.data["escape_dc"] == 12)
    remaining = next(c.instance_id for c in grips if c.data["escape_dc"] == 16)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    event_count = len(combat._load_session(mid).engine.events)
    details = condition_details(table, mid, OWNER)
    group = next(g for g in table.state(mid)["menu"]["actions"] if g["label"] == "Escape grapple")
    for text in details + [group["description"]]:
        assert "by default" in text.lower()
        assert "choose an individual hold" in text
        assert "chosen hold's DC" in text
        assert "success ends only that hold" in text
    # Rendering must not ask the player a choice or mutate observational state.
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert len(combat._load_session(mid).engine.events) == event_count
    script_check(monkeypatch, 12)
    cid = candidate(table, mid, "Escape grapple")
    result = send(cid)
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == ESCAPE
    assert {o["id"] for o in prompt["choice"]["options"]} == {chosen, remaining}
    answer = {**prompt["context"], "selection": "USE", "option_ids": [chosen]}
    assert send(cid, [answer])["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    roll = next(e.payload for e in reversed(engine.events)
                if e.event_type == "CHECK_ROLLED" and e.actor_id == OWNER)
    assert roll["dc"] == 12 and roll["success"]
    assert 12 <= roll["actor"]["total"] < 16
    assert {c.instance_id for c in held_conditions(combat, mid, OWNER)} == {remaining}
    verify_reloaded(tmp_path, combat, mid)


@pytest.mark.parametrize("save_style", [False, True])
def test_buried_advice_and_dig_free_stay_independent_of_grapples_table(tmp_path, monkeypatch, save_style):
    """Committed test packets create burials, bindings and check/save-style grapples.

    Save-style metadata matches a Serpent hold; this fixture tests condition scope,
    not summoning the Serpent. Dig free uses its burial DC and removes only that burial.
    """
    def mixed_packets(bundles):
        burial_packets(2)(bundles)
        for bundle, dc in zip(bundles[1:], (12, 16)):
            for action in bundle["action_catalog"]:
                if not action["display_name"].startswith("Scouring Hand"):
                    continue
                data = {"escape_dc": dc}
                if save_style and dc == 16:
                    data["escape_save"] = "STR"
                action["parameters"]["typed"]["effects"].append({"type": "condition",
                    "condition": "grappled", "applies_to": "target", "duration": "until_removed",
                    "condition_data": data})
                action["parameters"]["typed"]["effects"].append({"type": "condition",
                    "condition": "bound_limb", "applies_to": "target", "duration": "until_removed",
                    "condition_data": {"escape_dc": 30, "mode": "hand"}})
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, mid, send, commit = fixture(tmp_path, [],
        foe_talents=["SAND_BASE_SCOURING_HAND"], second_talents=["SAND_BASE_SCOURING_HAND"],
        bundle_transform=mixed_packets, seed=f"MMX115R2-BURIED-{save_style}")
    for actor in (FOE, SECOND):
        on_turn(table, mid, actor)
        commit(candidate(table, mid, "Scouring Hand", OWNER))
    on_turn(table, mid, OWNER)
    grips = {c.instance_id: c.model_dump(mode="json") for c in held_conditions(combat, mid, OWNER)}
    assert len(grips) == 2
    bindings = {c.instance_id: c.model_dump(mode="json")
                for c in combat._load_session(mid).engine.state.actors[OWNER].conditions.values()
                if c.condition_id == BOUND}
    assert len(bindings) == 2
    group = next(g for g in table.state(mid)["menu"]["actions"] if g["label"] == "Escape grapple")
    help_text = group["description"]
    assert "escape a grapple or pin" in help_text
    assert "every pin" in help_text and "every grapple" in help_text
    assert "Grappled and Pinned statuses" in help_text
    assert "highest DC among your pins, or among your grapples if you are not pinned" in help_text
    assert "Independent bindings and burials stay in place" in help_text
    assert "Escape the binding" in help_text and "Dig free" in help_text
    assert "any other grip" not in help_text
    details = condition_details(table, mid, OWNER, BURIED)
    assert len(details) == 2
    for text in details:
        assert "Athletics" in text and "Acrobatics" in text
        assert "highest of those DCs" not in text
        assert "all of them at once" not in text
        assert "repeat the Strength saving throw" not in text
        assert "choose an individual hold" not in text
    # The relevant grapple rows still show their default set advice.
    assert all("highest of those DCs" in text for text in condition_details(table, mid, OWNER, GRAPPLED))
    script_check(monkeypatch, 12)
    cid = candidate(table, mid, "Dig free of the sand")
    result = send(cid)
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    actor = combat._load_session(mid).engine.state.actors[OWNER]
    burial = next(c.instance_id for c in actor.conditions.values()
                  if c.condition_id == BURIED and c.data["escape_dc"] == 1)
    answer = {**prompt["context"], "selection": "USE", "option_ids": [burial]}
    assert send(cid, [answer])["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    roll = next(e.payload for e in reversed(engine.events)
                if e.event_type == "CHECK_ROLLED" and e.source_definition_id == DIG)
    assert roll["dc"] == 1 and roll["success"]
    assert {c.instance_id: c.model_dump(mode="json") for c in held_conditions(combat, mid, OWNER)} == grips
    burials = [c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == BURIED]
    assert len(burials) == 1 and burials[0].data["escape_dc"] == 2
    assert {c.instance_id: c.model_dump(mode="json") for c in engine.state.actors[OWNER].conditions.values()
            if c.condition_id == BOUND} == bindings
    verify_reloaded(tmp_path, combat, mid)
