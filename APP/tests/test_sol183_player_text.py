"""SOL183: authored evidence is preserved; table prose never prints its schema."""
import json
import re
from pathlib import Path

import pytest

from combat.player_text import clean
from combat.history_text import rider_text
from tests.hunt15_support import LEFT, act, fight, reload, turn

ROOT = Path(__file__).resolve().parents[1]
KEY = "TAL_THREAD_STITCH_THE_FALLING_BODY"
# "Trigger:" is an approved player header (PLAYER_TEXT_STYLE.md, CLARITY4); authoring fields at line starts still fail; ordinary sentences may name an action type.
BAD = re.compile(r"(?m)#{1,6}\s|^\s*(?:Talent Type|Prerequisite|Action Type|Effect)\s*:|"
                 r"\b(?:action:typed\.|condition:typed\.|TAL_)", re.I)


def authority():
    return json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_text())


def test_stitch_reminder_at_table_commit_reload_keeps_evidence(tmp_path):
    raw = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())[KEY]
    assert "####" in raw and "Action Type:" in raw
    combat, table, mid = fight(tmp_path, ["POISON_BASE_DELIVER_THE_DOSE"],
        effects=[{"type": "rider", "evidence": raw}])
    turn(table, mid, LEFT)
    assert act(table, mid, "Test setup")["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert [e.payload["rider"] for e in engine.events if e.event_type == "GM_RIDER"] == [raw]
    lines = [e["summary"] for e in table.events(mid, 0)["events"] if e["event_type"] == "GM_RIDER"]
    assert len(lines) == 1
    line = lines[0]
    assert not BAD.search(line), line
    for wording in ("Stitch the Falling Body", "reaction", "1 cultivation point", "Martial Focus",
                    "falls", "pushed or pulled", "Prone", "5 times", "10 feet", "Dexterity",
                    "whichever is higher"):
        assert wording in line
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    fresh = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert [e["summary"] for e in fresh.events(mid, 0)["events"] if e["event_type"] == "GM_RIDER"] == lines


def test_all_rules_and_reviewed_player_strings_have_no_authoring_schema():
    rules = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    strings = set(rules.values())
    def visit(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"riders", "evidence", "description", "text", "gm_text", "display_name"}:
                    collect(value)
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)
    def collect(node):
        if isinstance(node, str):
            strings.add(node)
        elif isinstance(node, list):
            for item in node:
                collect(item)
    visit(authority()["mechanics"])
    from combat.condition_text import all_conditions
    visit(all_conditions())
    for raw in sorted(strings):
        shown = clean(raw)
        assert not BAD.search(shown), shown
        for payload in ({"rider": raw}, {"rider": raw, "automated": True}):
            line = rider_text(payload, "Mira", "An ability", "Ren") or ""
            assert not BAD.search(line), line


@pytest.mark.parametrize("text", [
    "TAL_THREAD_STITCH_THE_FALLING_BODY protects condition:typed.prone after action:typed.example",
    "#### New ability\nTalent Type: Protection.\nPrerequisite: CL 5.\nAction Type: Reaction\nTrigger: An ally falls.\nEffect: Catch them.",
])
def test_future_and_legacy_prose_use_same_guard(text):
    assert not BAD.search(clean(text))
    assert not BAD.search(rider_text({"rider": text}, "Mira", "Protection", "Ren") or "")


def test_hook_traceback_is_evidence_not_a_player_rule():
    raw = "combat.ext.blacksmith_forge.forge_mark_expires_one_at_a_time (effect_expiring) failed: AttributeError: private detail"
    assert clean(raw) == ""
    assert rider_text({"rider": raw}, "Mira", "Forge", "Ren") is None


def test_sheet_library_uses_projection_without_mutating_source():
    from combat.tabletop import sheet_library
    raw = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())[KEY]
    sheet = {"selected_record_sections": {"talents": [{"record_id": KEY,
        "display_name": "Stitch the Falling Body", "full_description": raw}]}}
    library = sheet_library(sheet, [], set())
    def strings(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in {"name", "text", "summary", "automation"} and isinstance(value, str):
                    yield value
                yield from strings(value)
        elif isinstance(node, list):
            for value in node:
                yield from strings(value)
    shown = list(strings(library))
    assert any("Reduce its falling damage by 5 times" in value for value in shown)
    assert all(not BAD.search(value) for value in shown)
    assert sheet["selected_record_sections"]["talents"][0]["full_description"] == raw


def test_builder_projection_is_current_and_plain():
    from factory_authoring.player_rules import build_player_text
    rules = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())
    edits = json.loads((ROOT / "authority/typed_mechanics/owner_text_edits.json").read_text())["records"]
    data = json.loads((ROOT / "authority/typed_mechanics/player_text.json").read_text())
    assert data == build_player_text(rules, edits)
    # Trigger is an intentional player header in CLARITY4. Ordinary sentences
    # can also name an action type; authoring fields at line starts still fail.
    card_bad = re.compile(r'(?m)^(?:Talent Type|Prerequisite|Action Type|Effect)\s*:|'
                          r'#{1,6}\s|\b(?:action:typed\.|condition:typed\.|TAL_)', re.I)
    assert all(not card_bad.search(text) for text in data["records"].values())


def test_sus2_blocked_note_preserves_the_rule_and_all_its_restrictions():
    # The Illusion range rider was automated (f289f6da riders lane 9; reviewed wording in
    # review_sw-hunger.json), so its current record no longer carries a "blocked:" note.
    # The rule and its restriction ("when targeting inside the Domain") must still show.
    raw = next(r for r in authority()["mechanics"]["TAL_ILLUSION_COURT_FALSE_PREMISES"]["riders"]
               if r.startswith("Your Illusion talents gain 30 feet of range"))
    line = rider_text({"rider": raw}, "Mira", "Illusion Domain", "Ren")
    assert "blocked:" not in line
    assert "gain 30 feet of range" in line
    assert "when targeting inside the Domain" in line


@pytest.mark.parametrize("flag", ["automated", "adjudication_text"])
def test_recorded_outcomes_keep_rules_after_a_heading(flag):
    text = "Caught the ally. / #### Safety\nEffect: Keep the ally hanging until released."
    line = rider_text({"rider": text, flag: True}, "Mira", "Threads", "Ren")
    assert "Caught the ally" in line and "until released" in line
    assert not BAD.search(line)


def test_compiled_manual_ability_keeps_its_late_cost_and_action_exception():
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet
    bundle = compile_character(sheet(["TAL_ILLUSION_COURT_FALSE_PREMISES"], cl=15), actor_id="actor:factory.sol183-glamer")
    text = next(a["parameters"]["typed"]["gm_text"] for a in bundle["action_catalog"] if a["display_name"] == "Apply Glamer")
    assert not BAD.search(text)
    assert "remaining duration without Concentration" in text
    assert "without using an Action" in text
    assert "2 cultivation points" in text
    assert "true position do not change" in text


def test_burden_manual_reminder_at_table_keeps_rule_and_review_evidence(tmp_path):
    record = json.loads((ROOT / "authority/typed_mechanics/reviewed_final.d/gu.json").read_text())["mechanics"]["TAL_GRAVITY_EXTERNAL_WEIGHT_SHIFT"]
    def evidence(node):
        if isinstance(node, dict):
            for value in node.values():
                yield from evidence(value)
        elif isinstance(node, list):
            for value in node:
                yield from evidence(value)
        elif isinstance(node, str) and "Jump-distance halving" in node:
            yield node
    raw = next(evidence(record))
    combat, table, mid = fight(tmp_path, ["POISON_BASE_DELIVER_THE_DOSE"], effects=[{"type": "rider", "evidence": raw}])
    turn(table, mid, LEFT)
    assert act(table, mid, "Test setup")["status"] == "COMMITTED"
    engine = reload(combat, mid)
    assert [e.payload["rider"] for e in engine.events if e.event_type == "GM_RIDER"] == [raw]
    [line] = [e["summary"] for e in table.events(mid, 0)["events"] if e["event_type"] == "GM_RIDER"]
    assert "unwilling creature" in line and "halve its jump distance" in line
    assert "end of each of its turns" in line and "success ends Burden" in line
    assert "not tracked" not in line and "not modeled" not in line and "machinery" not in line
