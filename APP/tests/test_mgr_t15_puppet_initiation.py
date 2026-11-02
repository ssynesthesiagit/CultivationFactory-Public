"""Native learning -> completed rest -> table; no injected ownership receipts."""
import hashlib
import json

import pytest

from combat.gate2_runtime_content import AN
from combat.tabletop import TabletopError
from combat.ext.puppet_initiation import SOURCE, SHA, SPHERE, TOOLS, SKILL
from tests.auto28_puppetry_support import turn, resolve
from tests.puppet_scene_support import (
    A, B, PID, OTHER, ROOT, native, cold, choose, scene_arena, _raise_at, printed_text,
)


ARENA = "battlefield:map.builtin-mountain-pass"


def _rules():
    return json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())


def _printed_text_matches_pin(text):
    """The exact SHA is the hash of the approved printed text. A text without the printed sentence does not pass."""
    return hashlib.sha256(text.encode()).hexdigest() == SHA


def test_scene_vessel_damage_uses_the_physical_props_hit_points(tmp_path, monkeypatch):
    """A saved map prop stays the vessel's HP authority through committed actions and reloads."""
    from combat.ext import placed
    from combat.tabletop import normalize_map
    from combat.gate2_rolls import DeterministicRollAuthority
    original = DeterministicRollAuthority.d20
    def hit(self, **kwargs):
        result = original(self, **kwargs)
        if "ATTACK" in kwargs.get("reason", "").upper():
            return result.model_copy(update={"natural_result": 15, "total": 100})
        return result
    monkeypatch.setattr(DeterministicRollAuthority, "d20", hit)
    combat, table = native(tmp_path)
    table.add_advancement(PID, "sphere", SPHERE, learning_choices=choose(table, TOOLS[0]))
    saved_map = combat.tabletop_maps.save(normalize_map({
        "map_id": "puppet-scene-hp", "display_name": "Puppet scene HP",
        "width_squares": 12, "height_squares": 8,
        "starts": {"team1": [[3, 6]], "team2": [[10, 6]]},
        "objects": [{"id": 1, "kind": "crate", "name": "wooden puppet prop", "x": 4, "y": 6, "hp": 50}],
    }))
    mid = combat.create_factory_match(project_ids=[PID], opponent_actor_ids=[AN],
        arena_id="battlefield:map." + saved_map["map_id"],
        control_modes={A: "MANUAL", AN: "MANUAL"}, match_seed="SCENE-VESSEL-HP")["match_id"]

    def committed(prefix, *, target=None, destination=None):
        nonlocal combat, table
        turn(table, mid, A)
        engine = combat._load_session(mid).engine
        candidate = next(c for c in engine.legal_candidates() if c.actor_id == A
                         and c.display_name.startswith(prefix)
                         and (target is None or target in c.target_ids)
                         and (destination is None or c.destination and (c.destination.x, c.destination.y) == destination))
        view = table.state(mid)
        menu = view["menu"]
        result, _ = resolve(lambda answers: table.act(mid, candidate.candidate_id, menu["decision_id"],
            menu["state_version"], view["last_sequence"], answers), {"choice:needle.vessel_raise_move": []})
        assert result["status"] == "COMMITTED"
        combat, table = cold(tmp_path)
        return combat._load_session(mid).engine

    engine = cold(tmp_path)[0]._load_session(mid).engine
    prop = engine.state.objects["object:map.1"]
    assert prop.current_hp == 50 and not prop.destroyed
    engine = committed("Raise the Vessel", destination=(4, 6))
    zone = next(z for z in placed.of(engine, "vessel", owner_id=A)
                if placed.data(z).get("scene_object_id") == "object:map.1")
    assert "hp" not in placed.data(zone) and "max_hp" not in placed.data(zone)
    assert engine.state.objects["object:map.1"].current_hp == 50
    # The object attack is committed on the puppeteer's next turn and updates the same map prop.
    turn(table, mid, AN)
    engine = committed("Attack an object", target="object:map.1")
    damaged_hp = engine.state.objects["object:map.1"].current_hp
    assert 0 < damaged_hp < 50 and not engine.state.objects["object:map.1"].destroyed
    assert next(z for z in placed.of(engine, "vessel", owner_id=A)
                if placed.data(z).get("scene_object_id") == "object:map.1")
    # Dismissal removes only the thread. Re-raising after a cold reload sees the prop's damaged HP.
    engine = committed("Dismiss Vessel")
    assert not placed.of(engine, "vessel", owner_id=A)
    assert engine.state.objects["object:map.1"].current_hp == damaged_hp
    turn(table, mid, AN)  # Dismissal is free, but the object attack spent this turn’s Action.
    engine = committed("Raise the Vessel", destination=(4, 6))
    zone = next(z for z in placed.of(engine, "vessel", owner_id=A)
                if placed.data(z).get("scene_object_id") == "object:map.1")
    assert engine.state.objects["object:map.1"].current_hp == damaged_hp


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
    assert _printed_text_matches_pin(_rules()[SOURCE])


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
    # No acquired item means empty squares cannot be promoted into physical vessels.
    assert not any(c.actor_id == A and c.destination for c in engine.legal_candidates()
                   if c.display_name.startswith("Raise the Vessel"))


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
    # A does not control B's vessel: no A candidate may target that physical item's square or
    # act on its identity. Other suitable vessels stay legal, so the check is on the excluded item.
    b_vessel = placed.of(loaded.engine, "vessel", owner_id=B)[0]
    b_item = placed.data(b_vessel)["item_instance_id"]
    b_cells = {(cell.x, cell.y) for cell in b_vessel.affected_cells}
    control_rows = [c.display_name for c in loaded.engine.legal_candidates() if c.actor_id == A
                    and c.display_name.startswith(("Raise the Vessel", "Move Vessel", "Dismiss Vessel",
                                                   "Puppet Strike (from the vessel)", "Tension Response"))
                    and c.destination and (c.destination.x, c.destination.y) in b_cells]
    assert not control_rows, control_rows
    assert b_item == item["item_instance_id"]
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_actual_substitute_harm_damage_breaks_the_acquired_item_without_recreating_it(tmp_path, monkeypatch):
    from combat.ext import placed, vessel
    from combat.tabletop import normalize_map
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
    scene = combat.tabletop_maps.save(normalize_map({
        "map_id": "puppet-broken-replacement", "display_name": "Puppet broken replacement",
        "width_squares": 12, "height_squares": 8,
        "starts": {"team1": [[3, 6]], "team2": [[10, 6]]},
        "objects": [{"id": 1, "kind": "crate", "name": "replacement prop", "x": 6, "y": 6, "hp": 20}],
    }))
    state = combat.create_journey(project_ids=[PID, OTHER], arena_id="battlefield:map." + scene["map_id"],
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
    # The broken item is not raisable again: no reclaim of this physical item appears as a Raise.
    # Other suitable vessels may stay legal, so the check is on the broken item's identity.
    stored = combat.journeys.actor_preparations(A)[SOURCE]
    # A broken item is not on the board: no placed vessel carries its identity.
    assert not [z for z in placed.of(loaded.engine, "vessel", owner_id=A)
                if placed.data(z).get("item_instance_id") == stored["item_instance_id"]]
    assert stored["item_instance_id"] == item["item_instance_id"] and stored["broken"] == 1
    assert "object:map.1" in loaded.engine.state.objects
    turn(table, mid, A)
    menu_engine = combat._load_session(mid).engine
    candidates = [c for c in menu_engine.legal_candidates() if c.actor_id == A
                  and c.display_name.startswith("Raise the Vessel") and c.destination]
    assert candidates, "Breaking the prepared item must not remove ordinary free-square Raise options."
    assert loaded.mechanical.replay()["status"] == "PASS"
    fresh = cold(tmp_path)[0]
    assert fresh._factory_owner_sheet(PID)["puppet_initiation"]["vessel"]["broken"] == 1
    mid2 = fresh.create_factory_match(project_ids=[PID], opponent_actor_ids=[AN],
        control_modes={A: "MANUAL", AN: "MANUAL"}, match_seed="PUPPET-BROKEN-NEW-FIGHT")["match_id"]
    table2 = TabletopService(fresh, tmp_path)
    turn(table2, mid2, A)
    # A broken item is never bound to a square: an ordinary raise on any square is an ordinary vessel
    # (vessel.raise_vessel), so the check is that no placed vessel carries the broken item's identity.
    engine2 = fresh._load_session(mid2).engine
    assert not [z for z in placed.of(engine2, "vessel", owner_id=A)
                if placed.data(z).get("item_instance_id") == item["item_instance_id"]]


def test_native_inventory_leave_behind_controls_the_same_acquired_item(tmp_path):
    from combat.ext import vessel
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
        # Only this physical item's presence is checked; other suitable raises may remain legal.
        # vessel.py: the initiation vessel stays on the owner's action only when the item was carried, since a left-behind
        # item is popped from the initiation and sets left_behind.
        engine = combat._load_session(mid).engine
        init_vessels = [(action.parameters or {}).get("vessel_initiation", {}).get("vessel") for action in engine.action_catalog.values()
                        if action.owner_id == A and (action.parameters or {}).get("vessel_kit")]
        held = any(v and v.get("item_instance_id") == item["item_instance_id"] for v in init_vessels)
        assert held is not left, "a left-behind item must not be on hand; a carried one must be"
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
    arena_id = scene_arena(combat, "scene-two-body", [(5, 6), (5, 7)])
    state = combat.create_journey(project_ids=[PID, OTHER], arena_id=arena_id,
        positions={A: {"x": 3, "y": 6}, B: {"x": 4, "y": 6}}, base_paces={A: 12000, B: 12000})
    jid = state["journey_id"]
    option = next(o for o in combat.journey_menu(jid, A)["options"] if o["kind"] == "puppet_initiation_rest")
    state = combat.journey_act(jid, 0, A, option["kind"], option["payload"])
    item = state["actors"][A]["rest_preparations"][SOURCE]
    mid = combat.journey_start_combat(jid, state["revision"], {A: "team:a", B: "team:b"})["match_id"]

    def raise_at(exclude=None):
        turn(table, mid, A)
        engine = combat._load_session(mid).engine
        target = (5, 6) if exclude is None else (5, 7)
        prop = next(obj for obj in engine.state.objects.values() if (obj.position.x, obj.position.y) == target)
        assert prop.current_hp == 1, "The durable scene prop must survive table reload before Raise."
        candidate = next(c for c in engine.legal_candidates() if c.actor_id == A
                         and c.display_name.startswith("Raise the Vessel") and c.destination
                         and (c.destination.x, c.destination.y) == target)
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
    item_zone = next(z for z in zones if placed.data(z).get("item_instance_id") == item["item_instance_id"])
    assert placed.data(item_zone)["hp"] > 1  # The prepared item uses its own stats, not the 1-HP prop.
    assert not placed.data(item_zone).get("scene_object_id")
    first_prop = next(obj for obj in engine.state.objects.values() if (obj.position.x, obj.position.y) == (5, 6))
    assert first_prop.unattended and first_prop.current_hp == 1
    assert sum(1 for identity in identities if not identity) == 1
    scene_zone = next(z for z in zones if placed.data(z).get("scene_object_id"))
    scene_object_id = placed.data(scene_zone)["scene_object_id"]
    assert engine.state.actors[A].resources["resource:core.qi"] == before - 2
    physical = engine.state.objects[scene_object_id]
    assert physical.owner_id == A and not physical.unattended
    assert (physical.position.x, physical.position.y) == (scene_zone.center.x, scene_zone.center.y)
    saved = next(c.data for c in engine.state.actors[A].conditions.values() if c.condition_id == vessel.PREPARED_ITEM)
    assert saved["item_instance_id"] == item["item_instance_id"] and not saved["broken"]
    assert combat.journeys.actor_preparations(A)[SOURCE]["item_instance_id"] == item["item_instance_id"]
    assert loaded.mechanical.replay()["status"] == "PASS"
    # The physical prop, not only the placed zone, retains its claimed location across reload.
    reload_obj = cold(tmp_path)[0]._load_session(mid).engine.state.objects[scene_object_id]
    assert reload_obj.owner_id == A and not reload_obj.unattended
    assert (reload_obj.position.x, reload_obj.position.y) == (scene_zone.center.x, scene_zone.center.y)

    # Ending a thread does not destroy the prop: it becomes unattended and remains eligible
    # for a later Raise. This also exercises the strict ZONE_REMOVED event field contract.
    placed.drop(engine, scene_zone, "DISMISSED")
    released = engine.state.objects[scene_object_id]
    assert released.unattended and not released.destroyed
    assert vessel._scene_vessel(engine, engine.state.actors[A], released.position) is released


def replacement_scene(combat):
    """Save a physical replacement prop so it survives table reloads."""
    from combat.tabletop import normalize_map
    return combat.tabletop_maps.save(normalize_map({
        "map_id": "puppet-replacement", "display_name": "Puppet replacement",
        "width_squares": 12, "height_squares": 8,
        "starts": {"team1": [[3, 6]], "team2": [[10, 6]]},
        "objects": [{"id": 1, "kind": "crate", "name": "replacement puppet", "x": 5, "y": 6, "hp": 20}],
    }))


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
    scene = replacement_scene(combat)
    state = combat.create_journey(project_ids=[PID, OTHER], arena_id="battlefield:map." + scene["map_id"],
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
        # Read the durable product, not the encounter condition: the condition exists only while the
        # vessel is on the board, and breakage removes it from the encounter.
        saved = combat.journeys.actor_preparations(A)[SOURCE]
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
        turn(table, older, AN)
        turn(table, older, A)
    assert older_item()["state_revision"] > revision and older_item()["broken"] == 0
    # Even a higher local counter cannot make an older ancestry overwrite the break.
    engine = combat._load_session(older).engine
    stale = next(dict(c.data) for c in engine.state.actors[A].conditions.values() if c.condition_id == vessel.PREPARED_ITEM)
    assert stale["broken"] == 0
    stale_lineage = stale["lineage"]
    stale.update(state_revision=revision + 1, parent_lineage=stale_lineage, lineage="stale-successor")
    assert combat.journeys.update_preparation(A, SOURCE, stale, ancestry=[stale_lineage]) is False
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


def test_journey_save_reads_the_persistent_field_hook_once_not_once_per_actor(tmp_path, monkeypatch):
    """F15R2 optional: the persistent-field hook list is per save, not per actor.

    A two-actor journey save used to dispatch journey_persistent_fields once per actor; the same
    reply list is needed once for the whole registry write.
    """
    import combat.journey as journey_module
    combat, table, jid = learn_and_journey(tmp_path)
    session = combat.journeys.load(jid)
    assert A in session.state["actors"] and B in session.state["actors"]
    calls = []
    original = journey_module.run_strict
    def counting(name, *args, **kwargs):
        if name == "journey_persistent_fields":
            calls.append(name)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(journey_module, "run_strict", counting)
    combat.journeys.save(session)
    assert calls == ["journey_persistent_fields"]


def test_post_commit_product_sync_failure_logs_its_traceback(tmp_path, monkeypatch, caplog):
    """Optional F16R: the broad catch must not hide a defect. The action still commits and the failure is reported,
    but the traceback is logged so a programming error stays visible."""
    import logging
    import combat.ext as ext_pkg
    combat, _table = cold(tmp_path)

    def boom(*args, **kwargs):
        raise KeyError("product row")

    monkeypatch.setattr(ext_pkg, "run_strict", boom)
    with caplog.at_level(logging.ERROR, logger="combat.gate5_service"):
        assert combat._sync_committed_products(object()) == "'product row'"
    records = [r for r in caplog.records if r.name == "combat.gate5_service"]
    assert records and records[0].exc_info and records[0].exc_info[0] is KeyError


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
    assert durable["broken"] == 1 and durable["item_instance_id"] == item["item_instance_id"]
    assert durable["hp"] == 0
    combat2, table2 = cold(tmp_path)
    assert combat2._factory_owner_sheet(PID)["puppet_initiation"]["vessel"]["broken"] == 1
    # The journey already entered combat, so a later encounter is a standalone factory match.
    scene = replacement_scene(combat2)
    mid2 = combat2.create_factory_match(project_ids=[PID], opponent_actor_ids=[AN],
        arena_id="battlefield:map." + scene["map_id"],
        control_modes={A: "MANUAL", AN: "MANUAL"}, match_seed="PUPPET-SPARED")["match_id"]
    # The broken doll is never offered again at its own square (empty floor here, so no prop can stand in for it).
    turn(table2, mid2, A)
    offered = [c for c in combat2._load_session(mid2).engine.legal_candidates() if c.actor_id == A
               and c.display_name.startswith("Raise the Vessel") and c.destination
               and (c.destination.x, c.destination.y) == (3, 5)]
    assert not offered
    _raise_at(table2, combat2, mid2, A, (5, 6))
    engine2 = combat2._load_session(mid2).engine
    replacement = next(z for z in placed.of(engine2, "vessel", owner_id=A)
                       if placed.data(z).get("scene_object_id") == "object:map.1")
    assert placed.data(replacement).get("item_instance_id") != item["item_instance_id"]


def test_heavens_spare_body_destroys_a_scene_vessel_through_table_reload(tmp_path, monkeypatch):
    """The committed Spare Body reaction destroys the physical map prop, not a zone HP copy.

    The sheet reaches Spare Body through real table advancement (Substitute Harm Body, then Marionette
    Substitution Body, then Spare Body) at its real Hit Point maximum. Only the dice are rigged: the attack
    hits, and its damage equals the puppeteer's Hit Point maximum, which is lethal at full HP but not
    massive. Marionette Substitution Body is declined so the zero-HP window reaches Spare Body.
    """
    from combat.ext import placed
    from combat.ext.vessel import HARM_BODY, SUBSTITUTION, SPARE_BODY
    from combat.tabletop import normalize_map
    from combat.gate2_rolls import DeterministicRollAuthority
    original_d20 = DeterministicRollAuthority.d20
    original_roll = DeterministicRollAuthority.roll
    rig = {}
    def hit(self, **kwargs):
        result = original_d20(self, **kwargs)
        if "ATTACK" in kwargs.get("reason", "").upper():
            return result.model_copy(update={"natural_result": 15, "total": 100})
        return result
    def lethal(self, dice, **kwargs):
        roll = original_roll(self, dice, **kwargs)
        if kwargs.get("reason", "").startswith("DAMAGE:") and kwargs.get("actor_id") == B and "total" in rig:
            return roll.model_copy(update={"total": rig["total"]})
        return roll
    monkeypatch.setattr(DeterministicRollAuthority, "d20", hit)
    monkeypatch.setattr(DeterministicRollAuthority, "roll", lethal)
    combat, table = native(tmp_path, cl=15)
    table.add_advancement(PID, "sphere", SPHERE, learning_choices=choose(table, TOOLS[0]))
    for talent in (HARM_BODY, SUBSTITUTION, SPARE_BODY):
        table.add_advancement(PID, "talent", talent)
    table.add_advancement(OTHER, "sphere", SPHERE, learning_choices=choose(table, TOOLS[0], OTHER))
    table.save_reactions(PID, {"mode": "ask"})
    scene = combat.tabletop_maps.save(normalize_map({
        "map_id": "puppet-spare-scene", "display_name": "Puppet spare scene",
        "width_squares": 12, "height_squares": 8,
        "starts": {"team1": [[3, 6]], "team2": [[4, 5]]},
        "objects": [{"id": 1, "kind": "crate", "name": "scene puppet", "x": 4, "y": 6, "hp": 20}],
    }))
    state = combat.create_journey(project_ids=[PID, OTHER], arena_id="battlefield:map." + scene["map_id"],
        positions={A: {"x": 3, "y": 6}, B: {"x": 4, "y": 5}}, base_paces={A: 12000, B: 12000})
    jid = state["journey_id"]
    for aid in (A, B):
        option = next(o for o in combat.journey_menu(jid, aid)["options"] if o["kind"] == "puppet_initiation_rest")
        state = combat.journey_act(jid, state["revision"], aid, option["kind"], option["payload"])
    mid = combat.journey_start_combat(jid, state["revision"], {A: "team:a", B: "team:b"})["match_id"]
    # A hit of exactly the puppeteer's Hit Point maximum (M). It takes the puppeteer from M to 0, which is inside
    # the drop-to-zero window (M <= hp_loss < current + massive = 2M), so the zero-HP offer appears.
    rig["total"] = combat._load_session(mid).engine.state.actors[A].maximum_hp
    # Printed order: the intact carried doll is the puppeteer's own prepared item, so it claims its own empty square
    # first; Raise at the prop's square then claims the prop, and the placed doll goes inactive.
    _raise_at(table, combat, mid, A, (3, 5))
    turn(table, mid, B)
    turn(table, mid, A)
    engine = cold(tmp_path)[0]._load_session(mid).engine
    assert engine.state.objects["object:map.1"].current_hp == 20
    raise_action = next(c for c in engine.legal_candidates() if c.actor_id == A
                        and c.display_name.startswith("Raise the Vessel") and c.destination
                        and (c.destination.x, c.destination.y) == (4, 6))
    view = table.state(mid)
    menu = view["menu"]
    result, _ = resolve(lambda answers: table.act(mid, raise_action.candidate_id, menu["decision_id"],
        menu["state_version"], view["last_sequence"], answers), {"choice:needle.vessel_raise_move": []})
    assert result["status"] == "COMMITTED"
    combat, table = cold(tmp_path)
    engine = combat._load_session(mid).engine
    zone = next(z for z in placed.of(engine, "vessel", owner_id=A)
                if placed.data(z).get("scene_object_id") == "object:map.1")
    # A raised scene vessel keeps no HP copy: the map prop is the HP authority (see
    # test_scene_vessel_damage_uses_the_physical_props_hit_points).
    assert "hp" not in placed.data(zone) and "max_hp" not in placed.data(zone)
    assert not placed.data(zone).get("item_instance_id")
    assert engine.state.objects["object:map.1"].current_hp == 20
    assert engine.state.objects["object:map.1"].owner_id == A
    assert not engine.state.objects["object:map.1"].unattended
    turn(table, mid, B)
    engine = combat._load_session(mid).engine
    attack = next(c for c in engine.legal_candidates() if c.actor_id == B
                  and c.display_name.startswith("Unarmed Strike") and A in c.target_ids)
    view = table.state(mid)
    menu = view["menu"]
    result = _answer_reactions(lambda answers: table.act(mid, attack.candidate_id, menu["decision_id"],
        menu["state_version"], view["last_sequence"], answers))
    assert result["status"] == "COMMITTED"
    combat, _ = cold(tmp_path)
    loaded = combat._load_session(mid)
    prop = loaded.engine.state.objects["object:map.1"]
    assert prop.current_hp == 0 and prop.destroyed
    assert not any(placed.data(z).get("scene_object_id") == "object:map.1" for z in placed.of(loaded.engine, "vessel", owner_id=A))
    assert all(placed.data(z)["state"] == "inactive" for z in placed.of(loaded.engine, "vessel", owner_id=A))
    assert loaded.engine.state.actors[A].current_hp == 1
    assert any(event.event_type == "OBJECT_UPDATED" and "object:map.1" in event.target_ids
               and event.payload["object"]["destroyed"] for event in loaded.engine.events)


def _answer_reactions(send):
    """Use Spare Body at zero HP and decline Marionette Substitution Body, which would keep the puppeteer above zero."""
    from combat.ext.vessel import SPARE_BODY
    answers = []
    for _ in range(12):
        result = send(answers)
        if result["status"] != "REACTION_REQUIRED":
            return result
        prompt = result["reaction"]
        context = prompt["context"]
        options = [o["id"] for o in (prompt.get("choice") or {}).get("options", [])]
        use = SPARE_BODY in context["reaction_source_id"]
        answers.append({**context, "selection": "USE" if use or not prompt.get("choice") else "DECLINE",
                        "option_ids": options[:1] if use else []})
    raise AssertionError("too many reaction answers")


def test_learning_never_reads_the_authority_file_at_player_time(tmp_path, monkeypatch):
    """Finding 1: learning checks the pinned SHA in code; no player-time read of rules_text.json can block it.

    The spy covers every Path read entry point (read_text, read_bytes, open), not only read_text.
    """
    reads = []
    originals = {name: getattr(Path, name) for name in ("read_text", "read_bytes", "open")}
    def spy(name):
        def counting(self, *args, **kwargs):
            if self.name == "rules_text.json":
                reads.append(str(self))
            return originals[name](self, *args, **kwargs)
        return counting
    combat, table = native(tmp_path)
    for name in originals:
        monkeypatch.setattr(Path, name, spy(name))
    table.add_advancement(PID, "sphere", SPHERE, learning_choices=choose(table, TOOLS[0]))
    for name, original in originals.items():
        monkeypatch.setattr(Path, name, original)
    assert reads == []


def test_pinned_puppet_initiation_sha_matches_the_committed_authority():
    """Finding 2: the approved printed text is pinned exactly, and the check never passes on a missing sentence.

    The quoted clause (12+ words) keeps this file local in the public export, which scrambles owner prose.
    """
    text = _rules()[SOURCE]
    assert _printed_text_matches_pin(printed_text())
    assert _printed_text_matches_pin(text)


def test_pin_check_fails_when_the_printed_sentence_is_missing():
    """Finding 2 regression: the old gate returned True for any text without the printed sentence, so a changed or
    scrambled authority passed the pin. The strict check must reject it."""
    assert not _printed_text_matches_pin("Puppet Initiation: a text without the printed sentence.")


def test_puppetry_base_grants_match_the_printed_learn_clause():
    """F16R clause check: 'learn Raise the Vessel, Puppet Strike, and the basic Tension Responses'.

    The Puppetry base index must grant Raise the Vessel and Puppet Strike; the Tension Responses come from the vessel
    actions, which are offered to a Puppetry owner. A dropped grant fails here instead of silently at the table."""
    from combat import table_advance
    granted = table_advance.base_ability_index()["tianxia.sphere.puppetry"]
    assert "PUPPETRY_BASE_RAISE_THE_VESSEL" in granted
    assert "PUPPETRY_BASE_PUPPET_STRIKE" in granted
    assert "PUPPETRY_BASE_PUPPET_INITIATION" in granted


def test_journey_saved_before_rest_preparations_existed_still_loads_and_offers_the_rest(tmp_path):
    """Finding 4: a pre-change journey save without rest_preparations loads and keeps its rest options."""
    import json
    combat, table, jid = learn_and_journey(tmp_path)
    path = combat.journeys.path(jid)
    registry = json.loads(path.read_text())
    registry["sessions"][jid]["actors"][A].pop("rest_preparations")
    for actor in registry["actors"].values():
        actor.pop("rest_preparations", None)
    path.write_text(json.dumps(registry))
    combat2, table2 = cold(tmp_path)
    assert any(o["kind"] == "puppet_initiation_rest" for o in combat2.journey_menu(jid, A)["options"])
    assert combat2.journeys.load(jid).state["actors"][A]["rest_preparations"] == {}


def test_fight_end_carries_a_breakage_the_post_commit_sync_failed_to_write(tmp_path, monkeypatch):
    """Finding 2: the post-commit sync is best-effort; the finished fight still writes the broken vessel durably."""
    from combat.ext import run_strict, vessel, placed
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
    mid = combat.journey_start_combat(jid, state["revision"], {A: "team:a", B: "team:b"})["match_id"]
    # The post-commit sync fails on every commit of this fight, so only the settlement can carry the breakage.
    monkeypatch.setattr(type(combat), "_sync_committed_products", lambda self, engine: "sync refused")
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
    assert broken
    assert combat.journeys.actor_preparations(A)[SOURCE].get("broken", 0) == 0
    session = combat.journeys.load(jid)
    run_strict("journey_encounter_settled", session, A, loaded.engine, loaded.engine.state.actors[A])
    assert session.state["actors"][A]["rest_preparations"][SOURCE]["broken"] == 1
