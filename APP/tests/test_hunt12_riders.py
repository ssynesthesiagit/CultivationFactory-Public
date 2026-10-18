"""Repair history remains review metadata, never player-facing battle riders."""
import json
from pathlib import Path
import re
import pytest
from tests.hunt12_support import ME, FOE, candidate, fight, reload, send
from tests.test_hunt12_scaling import MARROW


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("mechanic", [MARROW, "TAL_DEATH_WITHERING_HAND", "TAL_UNMAKING_FOURTH_RUIN_FORM_BLACK_VEIN_BODY", "TAL_DEATH_GRAVE_CHILL", "TAL_ATHLETICS_COURT_OF_TEN_THOUSAND_STEPS"])
def test_no_developer_repair_note_in_committed_history(tmp_path, auto, mechanic):
    combat, table, mid = fight(tmp_path, [mechanic])
    name = {MARROW: "Marrow Regeneration", "TAL_DEATH_WITHERING_HAND": "Withering Hand",
            "TAL_UNMAKING_FOURTH_RUIN_FORM_BLACK_VEIN_BODY": "Fourth Ruin Form: Black-Vein Body",
            "TAL_DEATH_GRAVE_CHILL": "Grave Chill",
            "TAL_ATHLETICS_COURT_OF_TEN_THOUSAND_STEPS": "Court of Ten Thousand Steps"}[mechanic]
    chosen = candidate(combat, mid, lambda c: c.display_name == name)
    if auto:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    assert send(combat, table, mid, chosen, auto=auto)["status"] == "COMMITTED"
    loaded = reload(tmp_path, mid)
    history = json.dumps(combat.history(mid))
    assert "bonus_formula" not in history
    assert "old typing" not in history
    assert "Was mistyped" not in history
    assert "no hook fires" not in history
    assert "after_strain_gained" not in history
    assert "combat/unmaking.py" not in history
    assert "previous typing" not in history
    assert "Was hard-coded" not in history
    if mechanic == "TAL_ATHLETICS_COURT_OF_TEN_THOUSAND_STEPS":
        # Changed by lane AUTO8 because the printed rules require it: the table now runs every Court of Ten Thousand
        # Steps clause itself (combat/ext/athletics.py), so there is no GM line left to read. The history must still
        # carry the stance and the +20 feet, and must carry no developer note.
        riders = [e.payload.get("rider", "") for e in loaded.events if e.event_type == "GM_RIDER"]
        text = " ".join(riders)
        assert ".py" not in history
        assert "Court of Ten Thousand Steps" in history
        assert "difficult terrain ignored" in history, "the printed clause now happens at the table"
        assert "GM applies these benefits" not in text and "the table does not apply" not in text
    if mechanic == "TAL_DEATH_GRAVE_CHILL":
        riders = [e.payload.get("rider", "") for e in loaded.events if e.event_type == "GM_RIDER"]
        text = " ".join(riders)
        # AUTO Death removed the GM reminders because both save outcomes now run.
        assert not text
        assert any(m.target_field == "healing_reduction" for m in loaded.state.actors[FOE].modifiers.values())
    if mechanic == "TAL_UNMAKING_FOURTH_RUIN_FORM_BLACK_VEIN_BODY":
        riders = [e.payload.get("rider", "") for e in loaded.events if e.event_type == "GM_RIDER"]
        text = " ".join(riders)
        # AUTO84 removed duplicated GM summaries for the executed stance.
        assert not text
        assert "Black-Vein Body" in history
        assert any(c.condition_id == "condition:typed.stance.fourth_ruin_form" for c in loaded.state.actors[ME].conditions.values())


def test_reviewed_riders_contain_no_repair_history():
    root = Path(__file__).resolve().parents[1] / "authority/typed_mechanics/reviewed_final.d"
    repair = re.compile(
        r"old typing|executor never|fixed to|repair note|developer|bug fix|typing (?:error|bug)|bonus_formula|was mistyped"
        r"|\bno hook fires\b|\btimed self-buff\b|\.py\s+[a-z]+_[a-z_]+\b"
        r"|\bprevious typing\b|\bOwner\s+\d{4}-\d{2}-\d{2}\b|\bwas hard-coded\b",
        re.I,
    )

    def riders(value):
        if isinstance(value, dict):
            yield from (r for r in value.get("riders", []) if isinstance(r, str))
            for key, child in value.items():
                if key != "riders":
                    yield from riders(child)
        elif isinstance(value, list):
            for child in value:
                yield from riders(child)

    paths = [*root.glob("*.json"), root.parents[1] / "Tianxia_Typed_Mechanics_Authority_R1.json"]
    assert not [(p.name, text) for p in paths for text in riders(json.loads(p.read_text())) if repair.search(text)]


@pytest.mark.parametrize("group", ["bodyb", "elements"])
def test_reviewed_groups_contain_no_source_annotations(group):
    """Expand path-free coverage as each legacy authority group is cleaned."""
    authority = Path(__file__).resolve().parents[1] / "authority"
    overrides = json.loads((authority / f"typed_mechanics/reviewed_final.d/{group}.json").read_text())["mechanics"]
    generated = json.loads((authority / "Tianxia_Typed_Mechanics_Authority_R1.json").read_text())
    source = re.compile(r"\b[\w/.-]+\.py\b|\b(?:turn_flags|zone_spec|ignore_difficult)\b", re.I)

    def scan(value, path):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "riders":
                    for text in child:
                        if isinstance(text, str) and source.search(text):
                            yield path, text
                else:
                    yield from scan(child, f"{path}/{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                yield from scan(child, f"{path}/{index}")

    # Check the reviewed group and every generated row owned by that group.
    rows = generated["mechanics"]
    assert not list(scan(overrides, group))
    assert not list(scan({key: rows[key] for key in overrides}, f"generated/{group}"))


def test_burden_the_blade_rider_explains_the_rule_and_manual_resistance():
    """Unsupported attack delivery keeps a plain manual reminder of the rule."""
    authority = Path(__file__).resolve().parents[1] / "authority"
    rows = json.loads((authority / "Tianxia_Typed_Mechanics_Authority_R1.json").read_text())["mechanics"]
    text = " ".join(rows["TAL_EARTH_BURDEN_THE_BLADE"]["riders"])
    assert "Automated" not in text
    assert "For weapon attacks that do not offer this response" in text
    assert "spend your Burden Mark" in text
    assert "give the target resistance to that hit" in text
    assert "bludgeoning, piercing and slashing" in text
    assert "same weapon or limb has disadvantage before the end of its next turn" in text
    assert "at most once per round" in text
