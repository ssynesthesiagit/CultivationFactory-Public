"""Native learning -> completed rest -> table; no injected ownership receipts."""
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from canonical_catalog import CanonicalCatalogAuthorityService
from combat.gate5_service import CombatService
from combat.gate2_runtime_content import AN
from combat.tabletop_service import TabletopService
from combat.tabletop import TabletopError
from combat.ext.puppet_initiation import SOURCE, SHA, SPHERE, TOOLS, SKILL
from tests.h1_support import sheet
from tests.auto28_puppetry_support import turn, resolve

ROOT = Path(__file__).resolve().parents[1]
PID = "0badc0de-0000-4000-8000-000000000015"
OTHER = "0badc0de-0000-4000-8000-000000000016"
A = "actor:factory." + PID
B = "actor:factory." + OTHER
ARENA = "battlefield:map.builtin-mountain-pass"
# Shipped inputs used by native advancement (also public-CI resource discovery).
RESOURCES = (ROOT / "authority/Tianxia_Sphere_Path_Access_R1.json",
             ROOT / "authority/Tianxia_Forged_Technique_Authority_R1.json")


def native(tmp_path, *, prior=None, cl=1):
    assert all(p.is_file() for p in RESOURCES)
    for pid in (PID, OTHER):
        doc = sheet([], cl=cl, key="INT", name="Puppeteer" if pid == PID else "Observer")
        doc["identity"]["proficiency_bonus"] = 2 + max(0, cl - 1) // 4
        doc["path_and_subpath"] = {"path_record_ids": ["tianxia.path.qi_cultivation"]}
        if prior and pid == PID:
            if prior == SKILL:
                doc["ability_scores_and_statistics"]["skills"] = [
                    {"skill": SKILL, "bonus": 4, "proficiency_multiplier": 1}]
            else:
                doc["ability_scores_and_statistics"]["tool_proficiencies"] = [prior]
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    return cold(tmp_path)


def cold(tmp_path):
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    return combat, table


def choose(table, proficiency, project_id=PID):
    rows = table.learning_preview(project_id, SPHERE, {"proficiency": proficiency})["learning_choices"]
    selected = {"proficiency": proficiency, "free": rows[1]["options"][0]["id"]}
    rows = table.learning_preview(project_id, SPHERE, selected)["learning_choices"]
    if len(rows) == 3:
        selected["bonus"] = next(o["id"] for o in rows[2]["options"] if o["id"] != selected["free"])
    return selected


@pytest.mark.parametrize("proficiency", (*TOOLS, SKILL))
def test_each_printed_learning_choice_persists_without_bonus(tmp_path, proficiency):
    combat, table = native(tmp_path)
    selected = choose(table, proficiency)
    table.add_advancement(PID, "sphere", SPHERE, learning_choices=selected)
    combat, table = cold(tmp_path)
    doc = combat._factory_owner_sheet(PID)
    stats = doc["ability_scores_and_statistics"]
    if proficiency == SKILL:
        row = next(s for s in stats["skills"] if s["skill"] == SKILL)
        assert row["proficiency_multiplier"] == 1 and row["bonus"] == 4
    else:
        assert proficiency in stats["tool_proficiencies"]
    learned = doc["spheres_and_talents"]["learned_talent_record_ids"]
    assert learned == [selected["free"]]
    assert "vessel" not in doc["puppet_initiation"]
    receipt = table.advancement(PID)["added"]["spheres"][0]["learning_receipts"][0]
    assert receipt["source_sha256"] == SHA and receipt["conditional_bonus_earned"] == 0
    assert hashlib.sha256(json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())[SOURCE].encode()).hexdigest() == SHA


@pytest.mark.parametrize("proficiency", (TOOLS[0], SKILL))
def test_prior_proficiency_requires_exactly_one_valid_bonus(tmp_path, proficiency):
    combat, table = native(tmp_path, prior=proficiency)
    selected = choose(table, proficiency)
    for invalid in ({k: v for k, v in selected.items() if k != "bonus"},
                    {**selected, "bonus": "tianxia.talent.puppetry.thousand_puppet_incarnation"},
                    {**selected, "bonus": selected["free"]}):
        with pytest.raises(TabletopError):
            table.add_advancement(PID, "sphere", SPHERE, learning_choices=invalid)
        assert SPHERE not in combat._factory_owner_sheet(PID).get("spheres_and_talents", {}).get("sphere_record_ids", [])
    table.add_advancement(PID, "sphere", SPHERE, learning_choices=selected)
    combat, table = cold(tmp_path)
    doc = combat._factory_owner_sheet(PID)
    assert set(doc["spheres_and_talents"]["learned_talent_record_ids"]) == {selected["free"], selected["bonus"]}
    r = table.advancement(PID)["added"]["spheres"][0]["learning_receipts"][0]
    assert r["conditional_bonus_earned"] == 1 and r["slot_cost"] == 0


def learn_and_journey(tmp_path, *, automatic=False):
    combat, table = native(tmp_path)
    table.add_advancement(PID, "sphere", SPHERE, learning_choices=choose(table, TOOLS[0]))
    state = combat.create_journey(project_ids=[PID, OTHER], arena_id=ARENA,
        positions={A: {"x": 3, "y": 6}, B: {"x": 4, "y": 6}},
        base_paces={A: 12000, B: 12000}, control_modes={A: "LOCAL_AUTO" if automatic else "MANUAL", B: "MANUAL"})
    return combat, table, state["journey_id"]


@pytest.mark.parametrize("automatic", (False, True))
def test_completed_native_rest_creates_one_real_vessel_and_table_raises_it(tmp_path, automatic):
    combat, table, jid = learn_and_journey(tmp_path, automatic=automatic)
    assert not combat.journeys.actor_preparations(A)
    assert not any(o["kind"] == "puppet_initiation_rest" for o in combat.journey_menu(jid, B)["options"])
    options = [o for o in combat.journey_menu(jid, A)["options"] if o["kind"] == "puppet_initiation_rest"]
    assert len(options) == 3
    option = options[1]
    if automatic:
        state = combat.journey_auto_step(jid, 0, A, option["id"])
    else:
        state = combat.journey_act(jid, 0, A, option["kind"], option["payload"])
    assert state["seconds"] == 28800 and state["actors"][A]["long_rests"] == 1
    item = state["actors"][A]["rest_preparations"][SOURCE]
    assert item["source_id"] == SOURCE and item["form"] == "piercing" and item["owner_id"] == A
    combat, table = cold(tmp_path)
    assert combat._factory_owner_sheet(PID)["puppet_initiation"]["vessel"] == item
    from combat.factory_compiler import compile_character, equipment_list
    for _ in range(2):
        doc = combat._factory_owner_sheet(PID)
        carried = equipment_list(doc)["items"]
        assert len([r for r in carried if r["key"] == item["item_instance_id"]]) == 1
        rebuilt = compile_character(doc, actor_id=A)
        assert rebuilt["puppet_initiation"]["vessel"] == item
    assert combat.journeys.actor_preparations(A)[SOURCE] == item
    assert not any(o["kind"] == "puppet_initiation_rest" for o in combat.journey_menu(jid, A)["options"])
    # An ordinary second completed rest cannot mint a second initiation item.
    state = combat.journey_act(jid, state["revision"], A, "long_rest", {})
    assert state["actors"][A]["rest_preparations"][SOURCE] == item
    result = combat.journey_start_combat(jid, state["revision"], {A: "team:a", B: "team:b"})
    mid = result["match_id"]
    if automatic:
        # LOCAL_AUTO only covers the travel rest; the table's Raise is a manual act.
        combat.set_controller_mode(mid, actor_id=A, controller_mode="MANUAL")
    turn(table, mid, A)
    engine = combat._load_session(mid).engine
    candidates = [c for c in engine.legal_candidates() if c.actor_id == A and c.display_name.startswith("Raise the Vessel")]
    assert candidates
    candidate = next(c for c in candidates if c.destination and (c.destination.x, c.destination.y) == (5, 6))
    before = engine.state.actors[A].resources["resource:core.qi"]
    menu = table.state(mid)["menu"]
    committed, _ = resolve(lambda answers: table.act(mid, candidate.candidate_id, menu["decision_id"],
        menu["state_version"], table.state(mid)["last_sequence"], answers), {"choice:needle.vessel_raise_move": []})
    assert committed["status"] == "COMMITTED"
    combat, table = cold(tmp_path)
    loaded = combat._load_session(mid)
    assert loaded.engine.state.actors[A].resources["resource:core.qi"] == before - 1
    assert not loaded.engine.state.actors[A].action_available
    # placed.data is the public placed-object representation.
    from combat.ext import placed
    zones = [z for z in loaded.engine.state.zones.values() if placed.data(z).get("item_instance_id") == item["item_instance_id"]]
    assert len(zones) == 1 and placed.data(zones[0])["form"] == "piercing"
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_unprepared_acquisition_cannot_raise_and_compile_cannot_create(tmp_path):
    combat, table = native(tmp_path)
    table.add_advancement(PID, "sphere", SPHERE, learning_choices=choose(table, TOOLS[0]))
    result = combat.create_factory_match(project_ids=[PID], opponent_actor_ids=[AN],
        control_modes={A: "MANUAL"}, match_seed="PUPPET-UNPREPARED")
    engine = combat._load_session(result["match_id"]).engine
    assert not any(c.actor_id == A and c.display_name.startswith("Raise the Vessel") for c in engine.legal_candidates())
    assert not combat.journeys.actor_preparations(A)


@pytest.mark.parametrize("response", ("Tug the Joint", "Cross the Limb", "Guarding Vessel", "Snap the Thread"))
@pytest.mark.parametrize("automatic", (False, True))
def test_acquired_vessel_strikes_and_pays_each_basic_response_through_table(tmp_path, monkeypatch, response, automatic):
    from combat.gate2_rolls import DeterministicRollAuthority
    from combat.typed_executor import bears_mark
    from combat.ext import placed, vessel
    original = DeterministicRollAuthority.d20
    def roll(self, **kwargs):
        result = original(self, **kwargs)
        # Only deterministic dice are replaced; no action, ownership, receipt,
        # mark, hit effect or choice transport is installed by the test.
        attack = "ATTACK" in kwargs.get("reason", "").upper()
        return result.model_copy(update={"natural_result": 15 if attack else 1, "total": 100 if attack else 1})
    monkeypatch.setattr(DeterministicRollAuthority, "d20", roll)
    combat, table, jid = learn_and_journey(tmp_path)
    option = next(o for o in combat.journey_menu(jid, A)["options"] if o["kind"] == "puppet_initiation_rest")
    state = combat.journey_act(jid, 0, A, option["kind"], option["payload"])
    mid = combat.journey_start_combat(jid, state["revision"], {A: "team:a", B: "team:b"})["match_id"]
    turn(table, mid, A)
    def act(label, target=None, destination=None, automatic=False):
        engine = combat._load_session(mid).engine
        c = next(c for c in engine.legal_candidates() if c.actor_id == A
                 and c.display_name.startswith(label) and (target is None or target in c.target_ids)
                 and (destination is None or c.destination and (c.destination.x, c.destination.y) == destination))
        state = table.state(mid)
        menu = state["menu"]
        if automatic:
            from combat.gate4_adapters import ManualControllerAdapter
            real = combat.controller
            class Controller:
                def choose_primary_action(self, context):
                    return ManualControllerAdapter(lambda _: (c.candidate_id, ())).choose_primary_action(context)
                def __getattr__(self, name):
                    return getattr(real, name)
            combat.controller = Controller()
            combat.set_controller_mode(mid, actor_id=A, controller_mode="LOCAL_AUTO")
            try:
                return resolve(lambda answers: table.auto_step(mid, table.state(mid)["last_sequence"], answers))
            finally:
                combat.controller = real
                combat.set_controller_mode(mid, actor_id=A, controller_mode="MANUAL")
        return resolve(lambda answers: table.act(mid, c.candidate_id, menu["decision_id"], menu["state_version"],
            state["last_sequence"], answers), {"choice:needle.vessel_raise_move": []})
    act("Raise the Vessel", destination=(3, 5))
    turn(table, mid, B)
    turn(table, mid, A)
    before = combat._load_session(mid).engine
    hp = before.state.actors[B].current_hp
    act("Puppet Strike (from the vessel)", B)
    engine = combat._load_session(mid).engine
    assert engine.state.actors[B].current_hp < hp
    assert bears_mark(engine.state.actors[B], A, vessel.MARK)
    hp = engine.state.actors[B].current_hp
    position = engine.state.actors[B].position
    cp = engine.state.actors[A].resources["resource:core.qi"]
    _, prompts = act("Tension Response: " + response, A if response == "Guarding Vessel" else B, automatic=automatic)
    combat, table = cold(tmp_path)
    loaded = combat._load_session(mid)
    engine = loaded.engine
    assert not bears_mark(engine.state.actors[B], A, vessel.MARK)
    assert engine.state.actors[A].resources["resource:core.qi"] == cp
    if response == "Tug the Joint":
        assert engine.state.actors[B].position != position
        assert automatic or any("Tug" in p.get("moment", "") for p in prompts)
    elif response == "Cross the Limb":
        assert any(m.target_field == "attack_mode" and m.value == "DISADVANTAGE" for m in engine.state.actors[B].modifiers.values())
    elif response == "Guarding Vessel":
        assert any(c.condition_id == vessel.GUARDED for c in engine.state.actors[A].conditions.values())
    else:
        assert engine.state.actors[B].current_hp < hp
    assert loaded.mechanical.replay()["status"] == "PASS"
    if response != "Snap the Thread":
        return
    # Dismissal ends the thread while preserving the physical item's identity,
    # form and last square; reclaiming cannot duplicate it at a different cell.
    item = next(c.data for c in engine.state.actors[A].conditions.values() if c.condition_id == vessel.PREPARED_ITEM)
    act("Dismiss Vessel")
    turn(table, mid, B)
    turn(table, mid, A)
    act("Raise the Vessel", destination=(item["x"], item["y"]))
    loaded = combat._load_session(mid)
    owned = placed.of(loaded.engine, "vessel", owner_id=A)
    assert len(owned) == 1 and placed.data(owned[0])["item_instance_id"] == item["item_instance_id"]
    for _ in range(10):
        turn(table, mid, B)
        turn(table, mid, A)
    loaded = cold(tmp_path)[0]._load_session(mid)
    assert not placed.of(loaded.engine, "vessel", owner_id=A)
    saved = next(c.data for c in loaded.engine.state.actors[A].conditions.values() if c.condition_id == vessel.PREPARED_ITEM)
    assert saved["item_instance_id"] == item["item_instance_id"] and saved["broken"] == 0
    assert combat.journeys.actor_preparations(A)[SOURCE]["item_instance_id"] == item["item_instance_id"]
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_an_unprepared_puppeteer_cannot_control_another_owners_actual_vessel(tmp_path):
    combat, table = native(tmp_path)
    for pid in (PID, OTHER):
        table.add_advancement(pid, "sphere", SPHERE, learning_choices=choose(table, TOOLS[0], pid))
    state = combat.create_journey(project_ids=[PID, OTHER], arena_id=ARENA,
        positions={A: {"x": 3, "y": 6}, B: {"x": 4, "y": 6}}, base_paces={A: 12000, B: 12000})
    jid = state["journey_id"]
    option = next(o for o in combat.journey_menu(jid, B)["options"] if o["kind"] == "puppet_initiation_rest")
    state = combat.journey_act(jid, 0, B, option["kind"], option["payload"])
    item = state["actors"][B]["rest_preparations"][SOURCE]
    assert not combat.journeys.actor_preparations(A)
    mid = combat.journey_start_combat(jid, state["revision"], {A: "team:a", B: "team:b"})["match_id"]
    turn(table, mid, B)
    engine = combat._load_session(mid).engine
    c = next(c for c in engine.legal_candidates() if c.actor_id == B and c.display_name.startswith("Raise the Vessel")
             and c.destination and (c.destination.x, c.destination.y) == (5, 6))
    state = table.state(mid)
    menu = state["menu"]
    resolve(lambda answers: table.act(mid, c.candidate_id, menu["decision_id"], menu["state_version"],
        state["last_sequence"], answers), {"choice:needle.vessel_raise_move": []})
    turn(table, mid, A)
    combat, table = cold(tmp_path)
    loaded = combat._load_session(mid)
    from combat.ext import placed
    assert placed.data(placed.of(loaded.engine, "vessel", owner_id=B)[0])["item_instance_id"] == item["item_instance_id"]
    offered = [c.display_name for c in loaded.engine.legal_candidates() if c.actor_id == A]
    assert not any(label.startswith(("Raise the Vessel", "Move Vessel", "Dismiss Vessel", "Puppet Strike (from the vessel)", "Tension Response")) for label in offered)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_actual_substitute_harm_damage_breaks_the_acquired_item_without_recreating_it(tmp_path, monkeypatch):
    from combat.ext import placed, vessel
    from combat.gate2_rolls import DeterministicRollAuthority
    original = DeterministicRollAuthority.d20
    def hit(self, **kwargs):
        result = original(self, **kwargs)
        if "ATTACK" in kwargs.get("reason", "").upper():
            return result.model_copy(update={"natural_result": 15, "total": 100})
        return result
    monkeypatch.setattr(DeterministicRollAuthority, "d20", hit)
    combat, table = native(tmp_path, cl=5)
    for pid in (PID, OTHER):
        selected = choose(table, TOOLS[0], pid)
        if pid == PID:
            selected["free"] = vessel.HARM_BODY
        table.add_advancement(pid, "sphere", SPHERE, learning_choices=selected)
    table.save_reactions(PID, {"mode": "ask"})
    state = combat.create_journey(project_ids=[PID, OTHER], arena_id=ARENA,
        positions={A: {"x": 3, "y": 6}, B: {"x": 4, "y": 6}}, base_paces={A: 12000, B: 12000})
    jid = state["journey_id"]
    for aid in (A, B):
        option = next(o for o in combat.journey_menu(jid, aid)["options"] if o["kind"] == "puppet_initiation_rest")
        state = combat.journey_act(jid, state["revision"], aid, option["kind"], option["payload"])
    item = state["actors"][A]["rest_preparations"][SOURCE]
    mid = combat.journey_start_combat(jid, state["revision"], {A: "team:a", B: "team:b"})["match_id"]
    def act(aid, prefix, target=None, at=None):
        turn(table, mid, aid)
        engine = combat._load_session(mid).engine
        candidate = next(c for c in engine.legal_candidates() if c.actor_id == aid and c.display_name.startswith(prefix)
                         and (target is None or target in c.target_ids)
                         and (at is None or c.destination and (c.destination.x, c.destination.y) == at))
        view = table.state(mid)
        menu = view["menu"]
        return resolve(lambda answers: table.act(mid, candidate.candidate_id, menu["decision_id"],
            menu["state_version"], view["last_sequence"], answers), {"choice:needle.vessel_raise_move": []})
    act(A, "Raise the Vessel", at=(3, 5))
    act(B, "Raise the Vessel", at=(4, 5))
    turn(table, mid, A)
    broken = False
    for _ in range(8):
        act(B, "Puppet Strike (from the vessel)", target=A)
        loaded = cold(tmp_path)[0]._load_session(mid)
        saved = next(c.data for c in loaded.engine.state.actors[A].conditions.values() if c.condition_id == vessel.PREPARED_ITEM)
        if saved["broken"]:
            broken = True
            break
        turn(table, mid, A)
    assert broken, "The native Substitute Harm Body reaction must damage and eventually break its real vessel."
    assert saved["item_instance_id"] == item["item_instance_id"] and saved["hp"] == 0
    assert not placed.of(loaded.engine, "vessel", owner_id=A)
    assert any(e.event_type == "REACTION_RESOLVED" and e.source_definition_id == vessel.HARM_BODY for e in loaded.engine.events)
    turn(table, mid, A)
    loaded = cold(tmp_path)[0]._load_session(mid)
    assert not any(c.actor_id == A and c.display_name.startswith("Raise the Vessel") for c in loaded.engine.legal_candidates())
    stored = combat.journeys.actor_preparations(A)[SOURCE]
    assert stored["item_instance_id"] == item["item_instance_id"] and stored["broken"] == 1
    assert loaded.mechanical.replay()["status"] == "PASS"
    fresh = cold(tmp_path)[0]
    assert fresh._factory_owner_sheet(PID)["puppet_initiation"]["vessel"]["broken"] == 1
    mid2 = fresh.create_factory_match(project_ids=[PID], opponent_actor_ids=[AN],
        control_modes={A: "MANUAL", AN: "MANUAL"}, match_seed="PUPPET-BROKEN-NEW-FIGHT")["match_id"]
    table2 = TabletopService(fresh, tmp_path)
    turn(table2, mid2, A)
    assert not any(c.actor_id == A and c.display_name.startswith("Raise the Vessel")
                   for c in fresh._load_session(mid2).engine.legal_candidates())


def test_native_inventory_leave_behind_controls_the_same_acquired_item(tmp_path):
    combat, table, jid = learn_and_journey(tmp_path)
    option = next(o for o in combat.journey_menu(jid, A)["options"] if o["kind"] == "puppet_initiation_rest")
    state = combat.journey_act(jid, 0, A, option["kind"], option["payload"])
    item = state["actors"][A]["rest_preparations"][SOURCE]
    table.save_left_behind(PID, [item["item_instance_id"]])
    for left in (True, False):
        if not left:
            table.save_left_behind(PID, [])
        mid = combat.create_factory_match(project_ids=[PID], opponent_actor_ids=[AN],
            control_modes={A: "MANUAL", AN: "MANUAL"}, match_seed="PUPPET-INVENTORY-" + str(left))["match_id"]
        turn(table, mid, A)
        offered = combat._load_session(mid).engine.legal_candidates()
        assert any(c.actor_id == A and c.display_name.startswith("Raise the Vessel") for c in offered) is not left
        assert combat.journeys.actor_preparations(A)[SOURCE]["item_instance_id"] == item["item_instance_id"]


def test_level_zero_does_not_become_level_one_for_native_sphere_learning(tmp_path):
    combat, table = native(tmp_path, cl=0)
    with pytest.raises(TabletopError) as refused:
        table.add_advancement(PID, "sphere", SPHERE, learning_choices={"proficiency": TOOLS[0]})
    assert refused.value.code == "TABLETOP_ADVANCE_NOT_LEGAL"
    assert "puppet_initiation" not in combat._factory_owner_sheet(PID)


def test_two_body_control_raises_the_acquired_vessel_and_a_second_distinct_vessel(tmp_path):
    """Puppet Initiation's item is one suitable vessel, never the only one Raise can claim.

    Two-Body Control lets the puppeteer keep two active vessels. Binding Raise
    exclusively to the single prepared item made that printed capacity
    unreachable: once the item's vessel stood, every other square was refused.
    Both vessels now stand, the item keeps its own identity, and the extra
    vessel has its own, with no repair or duplication of the durable item.
    """
    from combat.ext import placed, vessel
    combat, table = native(tmp_path, cl=5)
    offered = table.learning_preview(PID, SPHERE, {"proficiency": TOOLS[0]})["learning_choices"]
    assert vessel.TWO_BODY in {o["id"] for o in offered[1]["options"]}
    table.add_advancement(PID, "sphere", SPHERE,
                          learning_choices={"proficiency": TOOLS[0], "free": vessel.TWO_BODY})
    state = combat.create_journey(project_ids=[PID, OTHER], arena_id=ARENA,
        positions={A: {"x": 3, "y": 6}, B: {"x": 4, "y": 6}}, base_paces={A: 12000, B: 12000})
    jid = state["journey_id"]
    option = next(o for o in combat.journey_menu(jid, A)["options"] if o["kind"] == "puppet_initiation_rest")
    state = combat.journey_act(jid, 0, A, option["kind"], option["payload"])
    item = state["actors"][A]["rest_preparations"][SOURCE]
    mid = combat.journey_start_combat(jid, state["revision"], {A: "team:a", B: "team:b"})["match_id"]

    def raise_at(exclude=None):
        turn(table, mid, A)
        engine = combat._load_session(mid).engine
        candidate = next(c for c in engine.legal_candidates() if c.actor_id == A
                         and c.display_name.startswith("Raise the Vessel") and c.destination
                         and (exclude is None or (c.destination.x, c.destination.y) != exclude))
        view = table.state(mid)
        menu = view["menu"]
        committed, _ = resolve(lambda answers: table.act(mid, candidate.candidate_id, menu["decision_id"],
            menu["state_version"], view["last_sequence"], answers), {"choice:needle.vessel_raise_move": []})
        assert committed["status"] == "COMMITTED"
        return (candidate.destination.x, candidate.destination.y)

    before = combat._load_session(mid).engine.state.actors[A].resources["resource:core.qi"]
    first = raise_at()
    turn(table, mid, B)
    second = raise_at(exclude=first)
    assert first != second
    loaded = cold(tmp_path)[0]._load_session(mid)
    engine = loaded.engine
    zones = placed.of(engine, "vessel", owner_id=A)
    assert len(zones) == 2
    assert all(placed.data(z)["state"] == "active" for z in zones)
    identities = [placed.data(z).get("item_instance_id") for z in zones]
    assert identities.count(item["item_instance_id"]) == 1
    assert sum(1 for identity in identities if not identity) == 1
    assert engine.state.actors[A].resources["resource:core.qi"] == before - 2
    saved = next(c.data for c in engine.state.actors[A].conditions.values() if c.condition_id == vessel.PREPARED_ITEM)
    assert saved["item_instance_id"] == item["item_instance_id"] and not saved["broken"]
    assert combat.journeys.actor_preparations(A)[SOURCE]["item_instance_id"] == item["item_instance_id"]
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_a_stale_encounter_cannot_restore_the_durable_broken_item(tmp_path, monkeypatch):
    """Only a strictly newer revision of the prepared item replaces the durable product.

    Two encounters can exist for the same project and carried item. Breaking
    the item in one, then committing an unrelated action in the older one, must
    not replace the durable broken=1 / 0-HP state with the older intact
    snapshot; both carry the same immutable creation identity.
    """
    from combat.ext import vessel, placed
    from combat.gate2_rolls import DeterministicRollAuthority
    original = DeterministicRollAuthority.d20
    def hit(self, **kwargs):
        result = original(self, **kwargs)
        if "ATTACK" in kwargs.get("reason", "").upper():
            return result.model_copy(update={"natural_result": 15, "total": 100})
        return result
    monkeypatch.setattr(DeterministicRollAuthority, "d20", hit)
    combat, table = native(tmp_path, cl=5)
    for pid in (PID, OTHER):
        selected = choose(table, TOOLS[0], pid)
        if pid == PID:
            selected["free"] = vessel.HARM_BODY
        table.add_advancement(pid, "sphere", SPHERE, learning_choices=selected)
    table.save_reactions(PID, {"mode": "ask"})
    state = combat.create_journey(project_ids=[PID, OTHER], arena_id=ARENA,
        positions={A: {"x": 3, "y": 6}, B: {"x": 4, "y": 6}}, base_paces={A: 12000, B: 12000})
    jid = state["journey_id"]
    for aid in (A, B):
        option = next(o for o in combat.journey_menu(jid, aid)["options"] if o["kind"] == "puppet_initiation_rest")
        state = combat.journey_act(jid, state["revision"], aid, option["kind"], option["payload"])
    item = state["actors"][A]["rest_preparations"][SOURCE]

    def act(mid, aid, prefix, target=None, at=None):
        turn(table, mid, aid)
        engine = combat._load_session(mid).engine
        candidate = next(c for c in engine.legal_candidates() if c.actor_id == aid and c.display_name.startswith(prefix)
                         and (target is None or target in c.target_ids)
                         and (at is None or c.destination and (c.destination.x, c.destination.y) == at)
                         and (not prefix.startswith("Raise") or c.destination))
        view = table.state(mid)
        menu = view["menu"]
        return resolve(lambda answers: table.act(mid, candidate.candidate_id, menu["decision_id"],
            menu["state_version"], view["last_sequence"], answers), {"choice:needle.vessel_raise_move": []})

    # The older encounter raises the item now, so it holds its own intact
    # prepared-item condition before the newer encounter changes anything.
    older = combat.create_factory_match(project_ids=[PID], opponent_actor_ids=[AN],
        control_modes={A: "MANUAL", AN: "MANUAL"}, match_seed="PUPPET-STALE")["match_id"]
    act(older, A, "Raise the Vessel")
    assert combat.journeys.actor_preparations(A)[SOURCE]["state_revision"] == 1

    mid = combat.journey_start_combat(jid, state["revision"], {A: "team:a", B: "team:b"})["match_id"]
    act(mid, A, "Raise the Vessel", at=(3, 5))
    act(mid, B, "Raise the Vessel", at=(4, 5))
    turn(table, mid, A)
    broken = False
    for _ in range(8):
        act(mid, B, "Puppet Strike (from the vessel)", target=A)
        saved = next(c.data for c in cold(tmp_path)[0]._load_session(mid).engine.state.actors[A].conditions.values()
                     if c.condition_id == vessel.PREPARED_ITEM)
        if saved["broken"]:
            broken = True
            break
        turn(table, mid, A)
    assert broken, "A native Substitute Harm Body reaction must break the real prepared vessel."
    stored = combat.journeys.actor_preparations(A)[SOURCE]
    assert stored["broken"] == 1 and stored["hp"] == 0
    revision = stored["state_revision"]
    assert revision > 1
    # Finding 4: the broken item must not disable Raise on other squares. An ordinary raise on a free
    # square is legal and does not touch the broken item.
    turn(table, mid, A)
    engine = combat._load_session(mid).engine
    raises = [c for c in engine.legal_candidates() if c.actor_id == A and c.display_name.startswith("Raise the Vessel") and c.destination]
    free = sorted({(c.destination.x, c.destination.y) for c in raises})
    assert free, "a broken prepared item must not disable Raise on other suitable squares"
    act(mid, A, "Raise the Vessel", at=free[0])
    after_raise = combat._load_session(mid).engine
    new = [placed.data(z) for z in placed.of(after_raise, "vessel", owner_id=A) if placed.data(z)["state"] == "active"]
    assert new and all(d.get("item_instance_id") != item["item_instance_id"] for d in new)
    assert combat.journeys.actor_preparations(A)[SOURCE]["broken"] == 1

    # The older encounter commits an unrelated action; its intact snapshot must
    # not resurrect the item or undo the committed breakage.
    from tests.hunt15_support import act as table_act
    resolve(lambda answers: table_act(table, older, "end", answers))
    after = combat.journeys.actor_preparations(A)[SOURCE]
    assert after["broken"] == 1 and after["item_instance_id"] == item["item_instance_id"]
    assert after["state_revision"] == revision
    assert cold(tmp_path)[0]._factory_owner_sheet(PID)["puppet_initiation"]["vessel"]["broken"] == 1
    # Finding 2: the older encounter keeps its own intact item and changes it past the durable counter
    # (dismiss, then reclaim at the same square). Its ancestry never held the durable broken state, so
    # the locked store must refuse it whatever its counter.
    def older_item():
        engine = combat._load_session(older).engine
        return next(dict(c.data) for c in engine.state.actors[A].conditions.values() if c.condition_id == vessel.PREPARED_ITEM)
    for _ in range(12):
        if older_item()["state_revision"] > revision:
            break
        act(older, A, "Dismiss Vessel")
        spot = older_item()
        act(older, A, "Raise the Vessel", at=(spot["x"], spot["y"]))
    assert older_item()["state_revision"] > revision and older_item()["broken"] == 0
    durable_now = combat.journeys.actor_preparations(A)[SOURCE]
    assert durable_now["broken"] == 1 and durable_now["hp"] == 0 and durable_now["state_revision"] == revision


def test_a_superseded_predecessor_is_refused_under_the_lock_regardless_of_counter(tmp_path):
    """The durable item changes only when the writer descends from the current committed lineage.

    A stale encounter can hold a higher state_revision after many local changes;
    its expected predecessor no longer matches, so the locked store refuses it.
    """
    combat, table, jid = learn_and_journey(tmp_path)
    option = next(o for o in combat.journey_menu(jid, A)["options"] if o["kind"] == "puppet_initiation_rest")
    state = combat.journey_act(jid, 0, A, option["kind"], option["payload"])
    durable = state["actors"][A]["rest_preparations"][SOURCE]
    current = durable["lineage"]
    superseded = dict(durable, state_revision=durable["state_revision"] + 5, broken=1, hp=0,
                      parent_lineage="superseded-predecessor", lineage="stale-successor")
    assert combat.journeys.update_preparation(A, SOURCE, superseded, ancestry=["superseded-predecessor"]) is False
    assert combat.journeys.actor_preparations(A)[SOURCE] == durable
    current_successor = dict(durable, state_revision=1, broken=1, hp=0, parent_lineage=current, lineage="next")
    assert combat.journeys.update_preparation(A, SOURCE, current_successor, ancestry=[current]) is True
    assert combat.journeys.actor_preparations(A)[SOURCE]["broken"] == 1


# --- RB2 regression tests: one per reviewed finding (each fails without its fix). ---


def test_talent_gate_reads_only_acquisition_constraints_not_a_fallback_field(tmp_path):
    """Finding 1: talent_status reads typed_constraints only (main's contract), never typed_prerequisites.

    Catalog-wide: every shipped talent carries identical typed_constraints and typed_prerequisites, so
    dropping the fallback changes no real row. A row with an empty constraint list is then judged by its
    constraints alone, not by a fallback field.
    """
    from combat import table_advance
    catalog = CanonicalCatalogAuthorityService(ROOT)
    rows = catalog.list_talents().get("records") or []
    assert rows and all((r.get("typed_constraints") or []) == (r.get("typed_prerequisites") or []) for r in rows)
    have = table_advance.known(sheet([], cl=1, key="INT", name="Gate"))
    restricted = next(r for r in rows if r.get("typed_prerequisites"))
    bare = dict(restricted, typed_constraints=[], typed_prerequisites=restricted["typed_prerequisites"])
    empty = dict(restricted, typed_constraints=[], typed_prerequisites=[])
    assert table_advance.talent_status(bare, have)["legal"] == table_advance.talent_status(empty, have)["legal"]


def test_post_commit_product_sync_failure_is_reported_not_raised(tmp_path, monkeypatch):
    """Finding 2: the journal already holds the action; a failing committed_products sync is reported, not raised."""
    import combat.ext as ext_pkg
    combat, _table = cold(tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("sync refused")

    monkeypatch.setattr(ext_pkg, "run_strict", boom)
    assert combat._sync_committed_products(object()) == "sync refused"
    monkeypatch.setattr(ext_pkg, "run_strict", lambda *a, **k: [])
    assert combat._sync_committed_products(object()) is None


def test_stale_writer_with_same_lineage_but_not_newer_revision_is_refused(tmp_path):
    """Finding 3: the revision fence is decided under the journey lock, not by the caller's pre-read.

    Same lineage as the durable product but no newer state_revision: a replayed snapshot, refused (False).
    """
    combat, table, jid = learn_and_journey(tmp_path)
    option = next(o for o in combat.journey_menu(jid, A)["options"] if o["kind"] == "puppet_initiation_rest")
    state = combat.journey_act(jid, 0, A, option["kind"], option["payload"])
    durable = state["actors"][A]["rest_preparations"][SOURCE]
    replay = dict(durable, broken=1, hp=0)
    assert combat.journeys.update_preparation(A, SOURCE, replay, ancestry=[durable["lineage"]]) is False
    assert combat.journeys.actor_preparations(A)[SOURCE] == durable


def test_a_reclaimed_vessel_at_zero_hit_points_stays_at_zero(tmp_path):
    """Finding 4: a stored 0 HP is a real (damaged) value; only a missing value falls back to full HP."""
    from combat.ext.vessel import carried_hp
    assert carried_hp({"hp": 0}, 12) == 0
    assert carried_hp({"hp": 5}, 12) == 5
    assert carried_hp({}, 12) == 12

# --- RB3 regression tests: one per F9R finding (each fails without its fix). ---


def test_journey_saves_wait_for_the_registry_lock_that_product_writes_hold(tmp_path):
    """F9R fix 1: save() rewrites State.json from its own read, so it must take the same lock as
    update_preparation. A save started while the registry lock is held has to wait for it.
    Without the lock in save(), it finishes at once and this test fails."""
    import threading
    combat, table, jid = learn_and_journey(tmp_path)
    store = combat.journeys
    session = store.load(jid)
    errors, finished = [], threading.Event()

    def writer():
        try:
            store.save(session)
        except Exception as exc:  # surfaced below, never swallowed
            errors.append(exc)
        finally:
            finished.set()

    with store.registry_lock():
        thread = threading.Thread(target=writer)
        thread.start()
        assert not finished.wait(0.5), "save() must wait while another registry writer holds the lock"
    assert finished.wait(10)
    thread.join()
    assert not errors


def test_product_updates_wait_for_the_journey_lock_held_by_a_writer(tmp_path):
    """F9R fix 1: update_preparation takes the same registry lock as a journey-level writer."""
    import threading
    combat, table, jid = learn_and_journey(tmp_path)
    option = next(o for o in combat.journey_menu(jid, A)["options"] if o["kind"] == "puppet_initiation_rest")
    state = combat.journey_act(jid, 0, A, option["kind"], option["payload"])
    durable = state["actors"][A]["rest_preparations"][SOURCE]
    update = dict(durable, state_revision=durable["state_revision"] + 1, broken=1, hp=0,
                  parent_lineage=durable["lineage"], lineage="next-lineage")
    results, finished = [], threading.Event()

    def writer():
        results.append(combat.journeys.update_preparation(A, SOURCE, update, ancestry=[durable["lineage"]]))
        finished.set()

    with combat.journeys.locked(jid):
        thread = threading.Thread(target=writer)
        thread.start()
        assert not finished.wait(0.5), "update_preparation must wait for the journey lock"
    assert finished.wait(10)
    thread.join()
    assert results == [True]
    assert combat.journeys.actor_preparations(A)[SOURCE]["broken"] == 1


def test_two_lifecycle_events_in_one_action_still_persist_the_item(tmp_path):
    """F9R fix 3: one action fires two lifecycle events, so the saved item's parent_lineage is the
    intermediate lineage, not the durable one. The durable lineage is the fence and the update lands."""
    from types import SimpleNamespace
    from combat.ext.puppet_initiation import persist_item_state
    from combat.ext.vessel import PREPARED_ITEM
    combat, table, jid = learn_and_journey(tmp_path)
    option = next(o for o in combat.journey_menu(jid, A)["options"] if o["kind"] == "puppet_initiation_rest")
    state = combat.journey_act(jid, 0, A, option["kind"], option["payload"])
    durable = state["actors"][A]["rest_preparations"][SOURCE]
    rev = durable["state_revision"]
    saved = dict(durable, state_revision=rev + 2, parent_lineage="intermediate-lineage",
                 lineage="end-lineage", hp=0, broken=1,
                 ancestry=f"{durable['lineage']},intermediate-lineage,end-lineage")
    condition = SimpleNamespace(condition_id=PREPARED_ITEM, data=saved)
    engine = SimpleNamespace(state=SimpleNamespace(actors={
        A: SimpleNamespace(entity_id=A, conditions={"item": condition})}))
    persist_item_state(combat, engine)
    after = combat.journeys.actor_preparations(A)[SOURCE]
    assert after["broken"] == 1 and after["lineage"] == "end-lineage" and after["state_revision"] == rev + 2


# --- RB2 addendum and finding 3: durable registration and Spare Body destruction. ---


def _raise_at(table, combat, mid, aid, at):
    turn(table, mid, aid)
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == aid
                     and c.display_name.startswith("Raise the Vessel") and c.destination
                     and (at is None or (c.destination.x, c.destination.y) == at))
    view = table.state(mid)
    menu = view["menu"]
    return resolve(lambda answers: table.act(mid, candidate.candidate_id, menu["decision_id"],
        menu["state_version"], view["last_sequence"], answers), {"choice:needle.vessel_raise_move": []})


def test_completed_rest_product_survives_journey_save_and_reload(tmp_path):
    """RB2 addendum (F10 P1): rest_preparations is durable actor state through the journey seam.

    Without the journey_persistent_fields registration, a save/reload of the journey drops the product,
    so actor_preparations() is empty and the one-item guard is lost for the next encounter.
    """
    combat, table, jid = learn_and_journey(tmp_path)
    option = next(o for o in combat.journey_menu(jid, A)["options"] if o["kind"] == "puppet_initiation_rest")
    state = combat.journey_act(jid, 0, A, option["kind"], option["payload"])
    item = state["actors"][A]["rest_preparations"][SOURCE]
    combat.journeys.save(combat.journeys.load(jid))
    combat2, table2 = cold(tmp_path)
    assert combat2.journeys.actor_preparations(A)[SOURCE] == item
    assert combat2.journeys.load(jid).state["actors"][A]["rest_preparations"][SOURCE] == item


def test_heavens_spare_body_destroys_the_initiation_vessel_for_good(tmp_path):
    """F10 finding 3: Spare Body sacrifices the acquired item; the destruction survives reload.

    The removal reason SPARED must mark the durable item broken, so Raise cannot reclaim it at its last
    square and a later encounter cannot carry it again.
    """
    from combat.ext import placed
    from combat.ext.puppet_initiation import persist_item_state
    combat, table, jid = learn_and_journey(tmp_path)
    option = next(o for o in combat.journey_menu(jid, A)["options"] if o["kind"] == "puppet_initiation_rest")
    state = combat.journey_act(jid, 0, A, option["kind"], option["payload"])
    item = state["actors"][A]["rest_preparations"][SOURCE]
    mid = combat.journey_start_combat(jid, state["revision"], {A: "team:a", B: "team:b"})["match_id"]
    _raise_at(table, combat, mid, A, (3, 5))
    engine = combat._load_session(mid).engine
    zone = next(z for z in placed.of(engine, "vessel", owner_id=A)
                if placed.data(z).get("item_instance_id") == item["item_instance_id"])
    placed.drop(engine, zone, "SPARED")
    persist_item_state(combat, engine)
    durable = combat.journeys.actor_preparations(A)[SOURCE]
    assert durable["broken"] == 1 and durable["hp"] == 0 and durable["item_instance_id"] == item["item_instance_id"]
    combat2, table2 = cold(tmp_path)
    assert combat2._factory_owner_sheet(PID)["puppet_initiation"]["vessel"]["broken"] == 1
    # The journey already entered combat, so a later encounter is a standalone factory match.
    mid2 = combat2.create_factory_match(project_ids=[PID], opponent_actor_ids=[AN],
        control_modes={A: "MANUAL", AN: "MANUAL"}, match_seed="PUPPET-SPARED")["match_id"]
    _raise_at(table2, combat2, mid2, A, None)
    engine2 = combat2._load_session(mid2).engine
    assert all(placed.data(z).get("item_instance_id") != item["item_instance_id"]
               for z in placed.of(engine2, "vessel", owner_id=A))
