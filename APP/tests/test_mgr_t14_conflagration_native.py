"""Whole Conflagration row through canonical grants, table commits and cold loads.

No effects or combat facts are injected. The source documents acquire the real
Fire automatic-component packet; the only controller fake selects a legal action.
"""
import hashlib
import json
import zipfile

import pytest

from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from sphere_component_authority import attach_sphere_automatic_component_receipt
from tests.h1_support import ROOT, sheet
from tests.r1i_service_support import OWNER, FOE, SECOND, force_ai_candidate
from tests.r10_fixup_support import cast_sender, commit

ROW = "FIRE_BASE_CONFLAGRATION"
QI = "resource:core.qi"


def fire_table(tmp_path, *, cl=17, dc=50, self_area=False, cp=30):
    sphere = CanonicalCatalogAuthorityService(ROOT).get_sphere("tianxia.sphere.fire")
    ledger = {}
    packet = attach_sphere_automatic_component_receipt(ledger, sphere, {
        "event_id": "conflagration-source-acquisition", "advancement": {"target_cl": cl},
        "legal_channel": "sphere_acquisition",
    })
    component = next(c for c in packet["components"] if c["component_id"] == ROW)
    assert component["automatic_grant"] and not component["counts_as_talent_choice"]
    assert not component["owner_removable"]
    text = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())[ROW]
    assert hashlib.sha256(text.encode()).hexdigest() == "ff4fd468793c0e9573acfdb310f094ae9b2cb4dae10fb1a222d313176cb5ca11"

    bundles = []
    for aid in (OWNER, FOE, SECOND):
        # The same source receipt -> automatic IDs projection used by the sheet
        # service. The portable source and compiled bundle contain identical IDs.
        doc = sheet([], cl=cl, dc=dc)
        doc["identity"]["display_name"] = aid.split("r1i-")[-1].title()
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
        doc["ability_scores_and_statistics"]["primary_resource"]["maximum"] = cp
        doc["spheres_and_talents"] = {
            "sphere_record_ids": [packet["parent_sphere_id"]],
            "learned_talent_record_ids": [],
            "automatic_sphere_component_record_ids": packet["component_ids"],
            **ledger,
        } if aid == OWNER else {}
        folder = tmp_path / "portable_characters" / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundles.append(compile_character(doc, actor_id=aid, reaction_plan={"ask": True}))

    positions = {OWNER: {"x": 3, "y": 6}, FOE: {"x": 15, "y": 6}, SECOND: {"x": 18, "y": 6}}
    if self_area:
        positions = {OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 7, "y": 6}}
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    saved = combat.tabletop_maps.save({"display_name": "Conflagration open ground",
        "width_squares": 20, "height_squares": 14, "walls": [], "terrain": [],
        "starts": {"team1": [[3, 6]], "team2": [[15, 6]]}})
    arena = combat.factory_arenas()["battlefield:map." + saved["map_id"]]
    mid = combat._finish_factory_match(bundles, [OWNER, FOE, SECOND],
        {OWNER: "team:a", FOE: "team:b", SECOND: "team:a"}, positions, arena,
        [OWNER, SECOND], [FOE], control_modes={aid: "MANUAL" for aid in (OWNER, FOE, SECOND)},
        match_seed="MGR-T14-CONFLAGRATION", display_name="Conflagration native acceptance",
        maximum_rounds=12)["match_id"]
    for _ in range(3):
        menu = table.state(mid)["menu"]
        if menu["actor_id"] == OWNER:
            break
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)["status"] == "COMMITTED"
    return combat, table, mid


def cold(tmp_path, mid):
    combat = CombatService(ROOT, tmp_path)
    return combat, TabletopService(combat, tmp_path), combat._load_session(mid)


def conditions(actor, name):
    return [c for c in actor.conditions.values() if c.condition_id == "condition:typed." + name]


def cast_candidates(engine):
    return [c for c in engine.legal_candidates()
            if (action := engine.action_catalog.get(c.source_definition_id)) is not None
            and action.display_name == "Conflagration"]


@pytest.mark.parametrize("cl,count,dc", [(1, 2, 50), (10, 2, -50), (11, 4, 50),
                                        (16, 4, -50), (17, 6, 50), (20, 6, -50)])
def test_initial_save_damage_all_tiers_and_friend_boundary(tmp_path, cl, count, dc):
    combat, table, mid = fire_table(tmp_path, cl=cl, dc=dc)
    before = combat._load_session(mid).engine
    assert not any("Lingering Conflagration" in c.display_name for c in before.legal_candidates())
    centers = {(c.destination.x, c.destination.y) for c in cast_candidates(before)}
    assert (15, 6) in centers and (16, 6) not in centers  # 60 feet, not 65
    qi = before.state.actors[OWNER].resources[QI]
    seq = before.state.event_sequence
    commit(cast_sender(combat, table, mid, "Conflagration", at=(15, 6)))
    combat, table, session = cold(tmp_path, mid)
    engine = session.engine
    events = [e for e in engine.events if e.sequence > seq]
    rolls = [e for e in events if e.event_type == "DAMAGE_ROLLED"]
    assert rolls and all(e.payload["expression"].removesuffix("+0") == f"{count}d6" for e in rolls)
    saves = [e for e in events if e.event_type == "SAVE_ROLLED"]
    assert {e.actor_id for e in saves} == {FOE, SECOND}, saves
    # The ally exactly 15 feet from the center is included; the caster at 60 is not.
    expected = rolls[0].payload["total"] // (2 if dc < 0 else 1)
    for aid in (FOE, SECOND):
        actor = engine.state.actors[aid]
        assert actor.current_hp == 500 - expected
        assert bool(conditions(actor, "kindled")) is (dc < 0)
        assert bool(conditions(actor, "burning")) is (dc > 0)
    assert engine.state.actors[OWNER].current_hp == 500
    assert engine.state.actors[OWNER].resources[QI] == qi - 2
    assert not engine.state.actors[OWNER].action_available
    zone, = [z for z in engine.state.zones.values() if z.active]
    assert zone.radius_cells == 3 and zone.duration_rounds == 10 and zone.concentration_link
    assert "fire terrain" in zone.trigger_profile["terrain"]
    assert zone.trigger_profile["obscured"] == "light"
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("automatic", [False, True])
def test_lingering_paid_free_action_cold_reload_and_original_expiry(tmp_path, automatic):
    combat, table, mid = fire_table(tmp_path, dc=-50)
    commit(cast_sender(combat, table, mid, "Conflagration", at=(15, 6)))
    combat, table, session = cold(tmp_path, mid)
    zone, = [z for z in session.engine.state.zones.values() if z.active]
    zid, made = zone.zone_id, zone.created_round
    # Apply later on the owner's next turn: the minute must not restart.
    commit(lambda answers=(): table.act(mid, table.state(mid)["menu"]["end_turn"],
        table.state(mid)["menu"]["decision_id"], table.state(mid)["menu"]["state_version"], 0, list(answers)))
    for _ in range(3):
        if table.state(mid)["menu"]["actor_id"] == OWNER:
            break
        engine = combat._load_session(mid).engine
        assert not any("Conflagration" in c.display_name for c in engine.legal_candidates())
        menu = table.state(mid)["menu"]
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    assert engine.state.current_actor_id == OWNER
    assert not conditions(engine.state.actors[FOE], "kindled")
    owner = engine.state.actors[OWNER]
    qi, action, bonus = owner.resources[QI], owner.action_available, owner.bonus_action_available
    augment, = [c for c in engine.legal_candidates() if "Lingering Conflagration" in c.display_name]
    if automatic:
        force_ai_candidate(combat, mid, OWNER, augment.candidate_id)
        assert table.auto_step(mid, 0)["status"] == "COMMITTED"
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="MANUAL")
    else:
        commit(cast_sender(combat, table, mid, "Lingering Conflagration"))
    combat, table, session = cold(tmp_path, mid)
    owner = session.engine.state.actors[OWNER]
    assert owner.resources[QI] == qi - 2 and owner.concentration is None
    assert owner.action_available == action and owner.bonus_action_available == bonus
    assert session.engine.state.zones[zid].active and not session.engine.state.zones[zid].concentration_link
    assert session.engine.state.zones[zid].created_round == made
    assert not any("Lingering Conflagration" in c.display_name for c in session.engine.legal_candidates())
    # Only legal end-turn commits move the clock; no injected duration receipts.
    for _ in range(34):
        engine = combat._load_session(mid).engine
        if not engine.state.zones[zid].active:
            break
        assert engine.state.round_number - made <= 10
        menu = table.state(mid)["menu"]
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)["status"] == "COMMITTED"
    combat, table, session = cold(tmp_path, mid)
    assert not session.engine.state.zones[zid].active
    assert session.engine.state.round_number - made == 10
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


def test_initial_area_includes_owner_but_excludes_creature_outside_radius(tmp_path):
    combat, table, mid = fire_table(tmp_path, self_area=True)
    seq = combat._load_session(mid).engine.state.event_sequence
    commit(cast_sender(combat, table, mid, "Conflagration", at=(3, 6)))
    _, _, session = cold(tmp_path, mid)
    events = [e for e in session.engine.events if e.sequence > seq and e.event_type == "SAVE_ROLLED"]
    assert {e.actor_id for e in events} >= {OWNER, FOE}
    assert all(SECOND != e.actor_id for e in events)
    assert session.engine.state.actors[SECOND].current_hp == 500


def test_fire_terrain_hostility_burn_clock_and_independent_concentration_copies(tmp_path):
    combat, table, mid = fire_table(tmp_path)
    commit(cast_sender(combat, table, mid, "Conflagration", at=(15, 6)))
    combat, table, session = cold(tmp_path, mid)
    zone, = [z for z in session.engine.state.zones.values() if z.active]
    zid = zone.zone_id
    hp = {aid: session.engine.state.actors[aid].current_hp for aid in (FOE, SECOND)}
    for _ in range(3):
        menu = table.state(mid)["menu"]
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)["status"] == "COMMITTED"
        if table.state(mid)["menu"]["actor_id"] == OWNER:
            break
    combat, table, session = cold(tmp_path, mid)
    assert session.engine.state.current_actor_id == OWNER
    # Both creatures' initial Burn ticks once for PB=4. Only the hostile
    # creature also takes Fire Terrain's failed-save PB damage at turn start.
    assert session.engine.state.actors[FOE].current_hp == hp[FOE] - 8
    assert session.engine.state.actors[SECOND].current_hp == hp[SECOND] - 4
    assert all(not conditions(session.engine.state.actors[aid], "burning") for aid in (FOE, SECOND))
    # The owner's unlimited-Concentration rule permits independent copies;
    # starting a second real cast must preserve the older held area.
    commit(cast_sender(combat, table, mid, "Conflagration", at=(5, 10)))
    _, _, session = cold(tmp_path, mid)
    assert session.engine.state.zones[zid].active
    assert len([z for z in session.engine.state.zones.values() if z.active]) == 2
    from combat import concentration
    assert any(state.zone_id == zid for _iid, state in concentration.held(session.engine.state.actors[OWNER]))
    newer = session.engine.state.actors[OWNER].concentration.zone_id
    made = session.engine.state.zones[zid].created_round
    for _ in range(34):
        engine = combat._load_session(mid).engine
        if not engine.state.zones[zid].active:
            break
        menu = table.state(mid)["menu"]
        assert table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0)["status"] == "COMMITTED"
    _, _, session = cold(tmp_path, mid)
    assert not session.engine.state.zones[zid].active
    assert session.engine.state.round_number - made == 10
    assert session.engine.state.zones[newer].active  # this copy was cast a round later
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("cp", [1, 3])
def test_cannot_create_or_linger_without_the_printed_two_cp(tmp_path, cp):
    combat, table, mid = fire_table(tmp_path, cp=cp)
    if cp == 1:
        assert not cast_candidates(combat._load_session(mid).engine)
        return
    commit(cast_sender(combat, table, mid, "Conflagration", at=(15, 6)))
    _, _, session = cold(tmp_path, mid)
    owner = session.engine.state.actors[OWNER]
    assert owner.resources[QI] == 1 and owner.concentration is not None
    assert not any("Lingering Conflagration" in c.display_name for c in session.engine.legal_candidates())
