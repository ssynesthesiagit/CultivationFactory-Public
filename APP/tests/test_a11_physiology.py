"""Printed breathing gates through real table transactions and saved reloads."""
from types import SimpleNamespace

import pytest

from combat import ext
from combat.canonical import canonical_sha256
from combat.creature_types import from_record, types_for
from combat.factory_compiler import compile_character
from combat.physiology import trait
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE, SECOND
from tests.test_r1i_round3 import reload

EDICT = "TAL_AIR_EMPTY_LUNG_EDICT"
CHAMBER = "TAL_AIR_BREATHLESS_CHAMBER"
PALM = "TAL_AIR_BREATH_STEALING_PALM"


def test_factory_identity_printed_physiology_uses_existing_saved_string_labels():
    from tests.h1_support import sheet
    doc = sheet([], cl=17)
    doc["identity"].update(creature_type="Construct", physiology={"breath_dependent": True})
    template = compile_character(doc, actor_id=OWNER)["actor_template"]
    assert template["creature_types"] == ["Construct", "physiology:breath_dependent:1"]
    assert trait(SimpleNamespace(creature_types=template["creature_types"]), "breath_dependent") is True


def physiology_setup(kind, traits=None):
    def prepare(bundles):
        foe = bundles[1]
        foe["actor_template"]["creature_types"] = list(from_record(
            {"creature_type": kind, "physiology": traits or {}}))
        foe.pop("bundle_sha256", None)
        foe["bundle_sha256"] = canonical_sha256(foe)
    return prepare


@pytest.mark.parametrize("kind,printed,expected", [
    ("Construct", {}, False), ("Undead", {}, False), ("Humanoid", {}, True),
    (None, {}, True), ("Construct", {"breath_dependent": True}, True),
    ("Humanoid", {"breath_dependent": False}, False),
    ("Beast", {"water_breathing": True}, True),
])
def test_printed_breathing_overrides_type_and_water_breathing_still_needs_breath(kind, printed, expected):
    actor = SimpleNamespace(creature_types=from_record({"creature_type": kind, "physiology": printed}))
    assert trait(actor, "breath_dependent") is expected
    assert trait(actor, "has_body") is None
    assert all(not label.startswith("physiology:") for label in types_for(actor))


@pytest.mark.parametrize("printed", [{"breath_dependent": "false"}, {"unknown": True}, []])
def test_invalid_printed_physiology_fails_before_a_fight_is_created(printed):
    with pytest.raises(ValueError, match="physiology"):
        from_record({"physiology": printed})


@pytest.mark.parametrize("field", ["creature_type", "creature_types"])
@pytest.mark.parametrize("label", [
    "physiology:breath_dependent:no", "physiology:breath_dependent:2",
    "physiology:breath_dependent:", "physiology:breath_dependent",
    "physiology:", "physiology:unknown:0", "physiology:breath_dependent:0:1",
    "Physiology:breath_dependent:0", "physiology:BREATH_DEPENDENT:0",
])
def test_factory_rejects_malformed_reserved_labels(field, label):
    from tests.h1_support import sheet
    doc = sheet([], cl=17)
    doc["identity"][field] = label if field == "creature_type" else [label]
    with pytest.raises(ValueError, match="physiology"):
        compile_character(doc, actor_id=FOE)


@pytest.mark.parametrize("record", [
    {"creature_type": "Construct", "creature_types": ["physiology:breath_dependent:1"],
     "physiology": {"breath_dependent": False}},
    {"creature_types": ["physiology:breath_dependent:0", "physiology:breath_dependent:1"]},
    {"creature_type": "physiology:breath_dependent:0",
     "creature_types": ["physiology:breath_dependent:1"]},
    {"creature_types": ["physiology:breath_dependent:0"], "physiology": {"breath_dependent": True}},
])
def test_factory_rejects_conflicting_reserved_declarations(record):
    from tests.h1_support import sheet
    doc = sheet([], cl=17)
    doc["identity"].update(record)
    with pytest.raises(ValueError, match="conflicting physiology"):
        compile_character(doc, actor_id=FOE)


def test_reserved_labels_reconcile_and_round_trip_without_becoming_creature_kinds():
    import json
    labels = from_record({
        "creature_type": " Humanoid ",
        "creature_types": ["physiology:breath_dependent:0", "physiology:breath_dependent:0", "humanoid"],
        "physiology": {"breath_dependent": False, "water_breathing": True},
    })
    assert labels == ("Humanoid", "physiology:breath_dependent:0", "physiology:water_breathing:1")
    restored = from_record(json.loads(json.dumps({"creature_types": labels})))
    assert restored == labels
    actor = SimpleNamespace(creature_types=restored)
    assert types_for(actor) == ("Humanoid",)
    assert trait(actor, "breath_dependent") is False
    assert trait(actor, "water_breathing") is True


@pytest.mark.parametrize("label", ["physiology:breath_dependent:no", "physiology:breath_dependent:1"])
def test_table_creation_rejects_invalid_nonbreather_before_eligibility_can_fail_open(tmp_path, label):
    import json
    import zipfile
    from combat.gate5_service import CombatService
    from tests.h1_support import ROOT, sheet
    for actor, talents in [(OWNER, [EDICT]), (FOE, [])]:
        doc = sheet(talents, cl=17)
        if actor == FOE:
            doc["identity"].update(creature_type="Construct", creature_types=[label],
                                   physiology={"breath_dependent": False})
        folder = tmp_path / "portable_characters" / actor.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    service = CombatService(ROOT, tmp_path)
    with pytest.raises(ValueError, match="physiology"):
        service.create_factory_match(project_ids=[OWNER.removeprefix("actor:factory.")],
                                     opponent_actor_ids=[FOE], match_seed="SOL94R-REJECT")


def test_reconciled_nonbreather_stays_immune_through_table_commit_reload(tmp_path):
    def prepare(bundles):
        foe = bundles[1]
        foe["actor_template"]["creature_types"] = list(from_record({
            "creature_type": "Humanoid", "creature_types": ["physiology:breath_dependent:0"],
            "physiology": {"breath_dependent": False},
        }))
        foe.pop("bundle_sha256")
        foe["bundle_sha256"] = canonical_sha256(foe)
    combat, table, mid, send, commit = fixture(tmp_path, [EDICT, CHAMBER], bundle_transform=prepare)
    engine = reload(tmp_path, mid)
    assert trait(engine.state.actors[FOE], "breath_dependent") is False
    assert not any(c.display_name == "Empty-Lung Edict" and FOE in c.target_ids
                   for c in engine.legal_candidates())
    cid = next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if "Breathless Chamber" in g["label"]
               for o in g["options"] if o.get("destination") == {"x": 4, "y": 6})
    assert commit(cid)["status"] == "COMMITTED"
    for _ in range(3):
        assert commit(table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    after = reload(tmp_path, mid)
    assert after.state.actors[FOE].creature_types == ("Humanoid", "physiology:breath_dependent:0")
    assert not after.state.actors[FOE].conditions
    assert not any(e.event_type == "SAVE_ROLLED" and e.actor_id == FOE for e in after.events)
    assert any(e.event_type == "SAVE_ROLLED" and e.actor_id == SECOND for e in after.events)


@pytest.mark.parametrize("auto", [False, True])
@pytest.mark.parametrize("kind,printed,allowed", [
    ("Undead", {}, False), ("Construct", {}, False), ("Humanoid", {}, True),
    ("Construct", {"breath_dependent": True}, True),
    ("Undead", {"animating_current": True}, True),
    ("Humanoid", {"breath_dependent": False}, False),
])
def test_empty_lung_edict_filters_targets_and_keeps_printed_exception_after_table_reload(tmp_path, auto, kind, printed, allowed):
    combat, table, mid, send, commit = fixture(tmp_path, [EDICT], bundle_transform=physiology_setup(kind, printed))
    engine = reload(tmp_path, mid)
    assert trait(engine.state.actors[FOE], "breath_dependent") == trait(
        SimpleNamespace(creature_types=from_record({"creature_type": kind, "physiology": printed})), "breath_dependent")
    offered = [c for c in engine.legal_candidates() if c.display_name == "Empty-Lung Edict" and FOE in c.target_ids]
    assert bool(offered) is allowed
    target = FOE if allowed else SECOND
    cid = candidate(table, mid, "Empty-Lung Edict", target)
    if auto:
        force_ai_candidate(combat, mid, OWNER, cid)
        assert send(cid, auto=True)["status"] == "COMMITTED"
    else:
        assert commit(cid)["status"] == "COMMITTED"
    after = reload(tmp_path, mid)
    affected = after.state.actors[target]
    assert any(c.condition_id.endswith("silenced") for c in affected.conditions.values())
    assert any(e.event_type == "SAVE_ROLLED" and e.actor_id == target for e in after.events)
    if not allowed:
        assert not after.state.actors[FOE].conditions


@pytest.mark.parametrize("kind", ["Undead", "Construct", "Humanoid"])
def test_breathless_chamber_filters_each_hostile_at_turn_start_after_table_reload(tmp_path, kind):
    combat, table, mid, send, commit = fixture(tmp_path, [CHAMBER], bundle_transform=physiology_setup(kind))
    cid = next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if "Breathless Chamber" in g["label"]
               for o in g["options"] if o.get("destination") == {"x": 4, "y": 6})
    assert commit(cid)["status"] == "COMMITTED"
    for _ in range(3):
        assert commit(table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    after = reload(tmp_path, mid)
    saved = {e.actor_id for e in after.events if e.event_type == "SAVE_ROLLED"}
    assert (FOE in saved) is (kind == "Humanoid")
    assert SECOND in saved and OWNER not in saved


@pytest.mark.parametrize("kind", ["Undead", "Humanoid"])
def test_breath_stealing_palm_does_not_save_against_nonbreathers_but_wind_lash_still_hits(tmp_path, kind):
    combat, table, mid, send, commit = fixture(tmp_path, ["AIR_BASE_WIND_LASH", PALM],
                                             bundle_transform=physiology_setup(kind))
    cid = candidate(table, mid, "Breath-Stealing Palm", FOE)
    assert commit(cid)["status"] == "COMMITTED"
    after = reload(tmp_path, mid)
    assert after.state.actors[FOE].current_hp < 500
    saves = [e for e in after.events if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert bool(saves) is (kind == "Humanoid")


def test_legacy_saved_edict_rows_without_physiology_gate_keep_their_original_behavior(tmp_path):
    def prepare(bundles):
        physiology_setup("Undead")(bundles)
        owner = bundles[0]
        action = next(a for a in owner["action_catalog"] if a["display_name"] == "Empty-Lung Edict")
        for row in action["parameters"]["typed"]["effects"]:
            row.pop("requires_physiology", None)
        owner.pop("bundle_sha256")
        owner["bundle_sha256"] = canonical_sha256(owner)
    combat, table, mid, send, commit = fixture(tmp_path, [EDICT], bundle_transform=prepare)
    assert commit(candidate(table, mid, "Empty-Lung Edict", FOE))["status"] == "COMMITTED"
    after = reload(tmp_path, mid)
    assert any(c.condition_id.endswith("silenced") for c in after.state.actors[FOE].conditions.values())


def test_unowned_physiology_hooks_leave_stock_saved_ai_continuation_byte_identical(monkeypatch):
    from tests.test_hunt32_inert_replay import _capture
    enabled = _capture()
    for point, callbacks in list(ext._HOOKS.items()):
        monkeypatch.setitem(ext._HOOKS, point, [f for f in callbacks if f.__module__ != "combat.ext.physiology"])
    assert _capture() == enabled
