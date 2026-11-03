"""A persisted rider selector must not inherit its parent build-choice lifetime."""
import pytest

from combat.ext.setting_status_text import selector_rule_section
from combat.ext.bodya_body_refining import CHOICE_CONDITION, MR_CHOICE_CONDITION
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.hunt10_support import ROOT, fight
from tests.hunt15_support import act
from tests.test_auto_bodya import BODY_REFINING_SHEET


def test_selector_section_keeps_upgrades_but_not_parent_or_siblings():
    text = "## Build\nPermanent choice.\n### Selected Style\nEffect.\n#### Perfected Style\nUpgrade.\n### Other\nSibling."
    assert selector_rule_section(text, "Selected") == "### Selected Style\nEffect.\n#### Perfected Style\nUpgrade."
    assert selector_rule_section(text, "Build") == text
    assert selector_rule_section(text, "Absent") == text
    ambiguous = text + "\n### Selected Alternative\nDifferent effect."
    assert selector_rule_section(ambiguous, "Selected") == ambiguous


@pytest.mark.parametrize("choice", ["Push", "Deny Reactions", "Knock Prone"])
def test_mountain_rider_setting_remains_changeable_after_table_reload(tmp_path, choice):
    sheet = {**BODY_REFINING_SHEET, "identity": {
        **BODY_REFINING_SHEET["identity"], "cultivation_level": 17}}
    service, session = fight(tmp_path, sheet=sheet)
    mid, actor_id = session.match_id, session.engine.state.current_actor_id
    table = TabletopService(service, tmp_path)
    assert act(table, mid, "Core Tempering Expression: Mountain-Rending Pulse")["status"] == "COMMITTED"
    assert act(table, mid, "Mountain-Rending: " + choice)["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)
    loaded = fresh._load_session(mid)
    state_before = loaded.engine.state.model_dump(mode="json")
    events_before = [e.model_dump(mode="json") for e in loaded.engine.events]
    rows = next(a for a in TabletopService(fresh, tmp_path).state(mid)["presentation"]["actors"]
                if a["entity_id"] == actor_id)["conditions"]
    build = next(c for c in rows if c["condition_id"] == CHOICE_CONDITION)
    rider = next(c for c in rows if c["condition_id"] == MR_CHOICE_CONDITION)
    assert "permanent until a later Realm breakthrough" in build["detail"]
    assert "cannot change it during this fight" in build["detail"]
    assert "until you change it" in rider["detail"]
    assert "permanent until" not in rider["detail"]
    assert "Golden Bell Circulation" not in rider["rule_text"]
    assert "Selected setting: Mountain-Rending: " + choice in rider["rule_text"]
    assert "deny_reactions" not in rider["detail"]
    for phrase in ("1d8", "2d8", "5 feet", "10 feet", "Strength saving throw",
                   "start of its next turn", "before the end of your next turn"):
        # The printed base and perfected Reaction options each state this deadline.
        expected = 2 if phrase == "start of its next turn" else 1
        assert rider["rule_text"].count(phrase) == expected
    assert "costs no action or resource" in rider["handling"]
    assert fresh._load_session(mid).engine.state.model_dump(mode="json") == state_before
    assert [e.model_dump(mode="json") for e in fresh._load_session(mid).engine.events] == events_before
    replacement = "Deny Reactions" if choice == "Push" else "Push"
    assert act(TabletopService(fresh, tmp_path), mid, "Mountain-Rending: " + replacement)["status"] == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    condition = next(c for c in reloaded.engine.state.actors[actor_id].conditions.values()
                     if c.condition_id == MR_CHOICE_CONDITION)
    assert condition.data["choice"] == ("deny_reactions" if replacement == "Deny Reactions" else "push")
    assert fresh.verify(mid)["status"] == "PASS"
    assert fresh.replay(mid)["status"] == "PASS"
