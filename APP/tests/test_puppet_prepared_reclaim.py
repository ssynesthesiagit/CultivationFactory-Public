"""A reclaimed prepared puppet remains the same durable physical item."""
from combat.ext import placed, vessel
from combat.gate2_rolls import DeterministicRollAuthority
from combat.gate2_runtime_content import AN
from combat.tabletop import normalize_map
from tests.auto28_puppetry_support import turn, resolve
from tests.puppet_scene_support import (
    A, B, PID, OTHER, SOURCE, SPHERE, TOOLS, choose, cold, native, _raise_at,
)


def test_reclaimed_prepared_vessel_breaks_durably(tmp_path, monkeypatch):
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
        "map_id": "prepared-reclaim", "display_name": "Prepared reclaim",
        "width_squares": 12, "height_squares": 8,
        "starts": {"team1": [[3, 6]], "team2": [[10, 6]]},
        "objects": [{"id": 1, "kind": "crate", "name": "scene puppet", "x": 6, "y": 6, "hp": 20}],
    }))
    state = combat.create_journey(project_ids=[PID, OTHER], arena_id="battlefield:map." + scene["map_id"],
        positions={A: {"x": 3, "y": 6}, B: {"x": 4, "y": 6}}, base_paces={A: 12000, B: 12000})
    jid = state["journey_id"]
    for aid in (A, B):
        option = next(o for o in combat.journey_menu(jid, aid)["options"]
                      if o["kind"] == "puppet_initiation_rest" and o["payload"]["form"] == ("piercing" if aid == A else "bludgeoning"))
        state = combat.journey_act(jid, state["revision"], aid, option["kind"], option["payload"])
    item = state["actors"][A]["rest_preparations"][SOURCE]
    mid = combat.journey_start_combat(jid, state["revision"], {A: "team:a", B: "team:b"})["match_id"]
    _raise_at(table, combat, mid, A, (3, 5))
    _raise_at(table, combat, mid, B, (4, 5))
    _raise_at(table, combat, mid, A, (6, 6))
    combat, table = cold(tmp_path)
    zones = placed.of(combat._load_session(mid).engine, "vessel", owner_id=A)
    doll = next(z for z in zones if placed.data(z).get("item_instance_id") == item["item_instance_id"])
    assert placed.data(doll)["state"] == "inactive"
    turn(table, mid, B)
    _raise_at(table, combat, mid, A, (3, 5))
    combat, table = cold(tmp_path)
    zones = placed.of(combat._load_session(mid).engine, "vessel", owner_id=A)
    doll = next(z for z in zones if placed.data(z).get("item_instance_id") == item["item_instance_id"])
    assert placed.data(doll)["state"] == "active"
    assert placed.data(doll)["item_source_id"] == item["source_id"]
    assert placed.data(doll)["form"] == "piercing"

    # Strike from the reclaimed body after a committed turn and cold reload.
    turn(table, mid, B)
    turn(table, mid, A)
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == A
                     and c.display_name.startswith("Puppet Strike (from the vessel)") and B in c.target_ids)
    view = table.state(mid)
    menu = view["menu"]
    result, _ = resolve(lambda answers: table.act(mid, candidate.candidate_id, menu["decision_id"],
        menu["state_version"], view["last_sequence"], answers))
    assert result["status"] == "COMMITTED"
    combat, table = cold(tmp_path)
    engine = combat._load_session(mid).engine
    damage = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"
              and e.actor_id == A and B in e.target_ids]
    assert damage and damage[-1].payload["damage_type"] == "PIERCING"

    for _ in range(8):
        turn(table, mid, B)
        engine = combat._load_session(mid).engine
        candidate = next(c for c in engine.legal_candidates() if c.actor_id == B
                         and c.display_name.startswith("Puppet Strike (from the vessel)") and A in c.target_ids)
        view = table.state(mid)
        menu = view["menu"]
        result, _ = resolve(lambda answers: table.act(mid, candidate.candidate_id, menu["decision_id"],
            menu["state_version"], view["last_sequence"], answers), {"choice:needle.vessel_raise_move": []})
        assert result["status"] == "COMMITTED"
        combat, table = cold(tmp_path)
        saved = combat.journeys.actor_preparations(A)[SOURCE]
        if saved["broken"]:
            break
        turn(table, mid, A)
    assert saved["item_instance_id"] == item["item_instance_id"]
    assert saved["hp"] == 0 and saved["broken"] == 1
    assert combat._factory_owner_sheet(PID)["puppet_initiation"]["vessel"]["broken"] == 1
    mid2 = combat.create_factory_match(project_ids=[PID], opponent_actor_ids=[AN],
        control_modes={A: "MANUAL", AN: "MANUAL"}, match_seed="RECLAIM-BROKEN")["match_id"]
    combat, table = cold(tmp_path)
    turn(table, mid2, A)
    engine = combat._load_session(mid2).engine
    assert not [z for z in placed.of(engine, "vessel", owner_id=A)
                if placed.data(z).get("item_instance_id") == item["item_instance_id"]]
    assert combat._factory_owner_sheet(PID)["puppet_initiation"]["vessel"]["broken"] == 1
