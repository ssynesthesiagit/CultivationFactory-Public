"""Arrow-Turning honors existing bans at the saved table, including free uses."""
import pytest

from test_riders_c9 import ROOT, BOW, bundle, _portable


@pytest.mark.parametrize("control", ["manual", "attacker-ai", "guard-ai"])
@pytest.mark.parametrize("sovereign", [False, True])
@pytest.mark.parametrize("ban", ["native", "data", "attacker", "other-attacker", "none"])
def test_arrow_prohibitions_commit_reload(monkeypatch, tmp_path, control, sovereign, ban):
    from combat.gate2_runtime_content import ACTORS, BAI
    from combat.gate2_rolls import DeterministicRollAuthority
    from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
    from combat.tabletop_service import TabletopService
    from combat.tabletop import ButtonStore
    from combat.ext.air_currents import ARROW_PENDING, SOVEREIGN_FREE
    from combat.unmaking import NO_REACTIONS_AGAINST

    guard, defender, archer = [FACTORY_ACTOR_PREFIX + s for s in ("22222222", "11111111", "33333333")]
    talents = ["TAL_AIR_ARROW_TURNING_BREATH"]
    if sovereign:
        talents.append("TAL_AIR_SKY_SOVEREIGN_INCARNATION")
    _portable(tmp_path, "22222222", talents, cl=17, sphere="tianxia.sphere.air", ac=100)
    _portable(tmp_path, "11111111", [], ac=0)
    _portable(tmp_path, "33333333", [], items=(BOW,))
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions("22222222", {"mode": "ask"}, set())
    bundles = [bundle(talents, actor_id=guard, cl=17, sphere="tianxia.sphere.air", ac=100),
               bundle([], actor_id=BAI), bundle([], actor_id=archer, items=(BOW,)),
               bundle([], actor_id=defender, ac=0)]
    for bonus, row in zip((100, 90, 80, 70), bundles):
        row["actor_template"]["initiative_bonus"] = bonus
    # Palm damages the guard during setup. Keep it healthier than the defender
    # so the unmodified AI still selects the ally whose protection is tested.
    bundles[0]["actor_template"]["maximum_hp"] = 1000
    # Native Palm is executed unchanged, using Bai's real resource and action.
    # The other representations use a sealed typed fixture action, not an engine
    # patch or an out-of-journal state edit. All setup actions commit and replay.
    bai_bundle = bundles[1]
    bai_bundle["actor_template"]["resources"] = [r.model_dump(mode="json") for r in ACTORS[BAI].resources]
    bai_bundle["actor_template"]["action_ids"].append("action:bai_meizhen.numbing_venom_palm")
    if ban in ("data", "attacker", "other-attacker"):
        condition = "fixture_reaction_ban" if ban == "data" else "no_reactions_against"
        data = {"reaction_denied": True} if ban == "data" else {"against": archer if ban == "attacker" else BAI}
        fixture_id = "action:typed.c9_prohibition_fixture"
        bai_bundle["action_catalog"].append({
            "source_definition_id": fixture_id, "display_name": "Fixture reaction prohibition",
            "owner_id": BAI, "economy": "ACTION", "resolution_kind": "TYPED",
            "target_kind": "HOSTILE_ENTITY", "range_ft": 30, "costs": [],
            "parameters": {"typed": {"numbers": {"pb": 4}, "effects": [{
                "type": "condition", "condition": condition, "condition_data": data,
                "applies_to": "target", "expires_on": "START_OF_SOURCE_NEXT_TURN"}]}}})
        bai_bundle["actor_template"]["action_ids"].append(fixture_id)
    service = CombatService(ROOT, tmp_path)
    service.tabletop_maps.save({"display_name": "C9 prohibition yard", "width_squares": 15,
        "height_squares": 10, "walls": [], "starts": {"team1": [[3, 4], [3, 5]], "team2": [[4, 4], [8, 5]]}})
    primary = [guard, BAI, archer, defender]
    mid = service._finish_factory_match(bundles, primary,
        {guard: "team:1", defender: "team:1", BAI: "team:2", archer: "team:2"},
        {guard: {"x": 3, "y": 4}, defender: {"x": 3, "y": 5}, BAI: {"x": 4, "y": 4}, archer: {"x": 8, "y": 5}},
        service.factory_arenas()["battlefield:map.c9-prohibition-yard"], [guard, archer, defender], [BAI],
        control_modes={a: "MANUAL" for a in primary}, match_seed="C9-PROHIBITIONS",
        display_name="C9 prohibition yard", maximum_rounds=5)["match_id"]
    table = TabletopService(service, tmp_path)
    original = DeterministicRollAuthority.d20

    def fixed(self, **kwargs):
        record = original(self, **kwargs)
        reason = kwargs["reason"]
        total = (120 if "numbing_venom_palm" in reason else 15) if reason.startswith("ATTACK:") else 16 if reason.startswith("CHECK:TAL_AIR_ARROW_TURNING") else 1 if reason.startswith("SAVE:") else None
        if total is not None:
            return record.model_copy(update={"dice": (15,), "natural_result": 15,
                "modifier": total - 15, "total": total, "discarded": ()})
        return record
    monkeypatch.setattr(DeterministicRollAuthority, "d20", fixed)

    def reload():
        return CombatService(ROOT, tmp_path)._load_session(mid)

    def act(name=None, target=None, *, end=False, replies=()):
        state = table.state(mid)
        menu = state["menu"]
        candidate = menu["end_turn"] if end else next(o["candidate_id"] for g in menu["actions"]
            if g["label"] == name for o in g["options"] if target is None or target in o.get("target_ids", []))
        return table.act(mid, candidate, menu["decision_id"], menu["state_version"], state["last_sequence"], list(replies))

    assert table.state(mid)["menu"]["actor_id"] == guard
    if sovereign:
        assert act("Sky-Sovereign Incarnation")["status"] == "COMMITTED"
    act(end=True)
    assert table.state(mid)["menu"]["actor_id"] == BAI
    if ban != "none":
        assert act("Numbing Venom Palm" if ban == "native" else "Fixture reaction prohibition", guard)["status"] == "COMMITTED"
    act(end=True)
    assert table.state(mid)["menu"]["actor_id"] == archer
    held = reload().engine.state.actors[guard].conditions.values()
    condition_id = {"native": "condition:core.reaction_denied", "data": "condition:typed.fixture_reaction_ban",
                    "attacker": NO_REACTIONS_AGAINST, "other-attacker": NO_REACTIONS_AGAINST}.get(ban)
    if condition_id:
        assert any(c.condition_id == condition_id for c in held)
    assert reload().engine.state.actors[guard].reaction_available
    assert reload().mechanical.replay()["status"] == "PASS"
    if control == "guard-ai":
        service.set_controller_mode(mid, actor_id=guard, controller_mode="LOCAL_AUTO")
    if control == "attacker-ai":
        service.set_controller_mode(mid, actor_id=archer, controller_mode="LOCAL_AUTO")
    start = len(reload().engine.events)
    before = reload().engine.state.model_dump(mode="json")
    seen_arrow = False
    for _ in range(10):
        replies = []
        def attack():
            if control == "attacker-ai":
                return table.auto_step(mid, table.state(mid)["last_sequence"], reactions=replies)
            state = table.state(mid)
            name = next(g["label"] for g in state["menu"]["actions"] if g["label"].startswith("Gong Jian"))
            return act(name, defender, replies=replies)
        result = attack()
        while result["status"] == "REACTION_REQUIRED":
            prompt = result["reaction"]
            arrow = "Arrow-Turning Breath" in str(prompt)
            seen_arrow |= arrow
            assert reload().engine.state.model_dump(mode="json") == before
            replies.append({**prompt["context"], "selection": "USE" if arrow else "DECLINE", "option_ids": ["use"] if arrow else []})
            result = attack()
        assert result["status"] == "COMMITTED"
        if any(e.event_type == "ATTACK_ROLLED" for e in reload().engine.events[start:]):
            break
        before = reload().engine.state.model_dump(mode="json")
    loaded = reload()
    allowed = ban in ("none", "other-attacker")
    events = loaded.engine.events[start:]
    assert any(e.event_type == "ATTACK_ROLLED" and defender in e.target_ids for e in events)
    assert any(e.event_type == "CONDITION_APPLIED" and e.payload.get("condition_id") == ARROW_PENDING for e in events) is allowed
    assert seen_arrow is (allowed and control != "guard-ai")
    actor = loaded.engine.state.actors[guard]
    if condition_id:
        assert any(c.condition_id == condition_id for c in actor.conditions.values())
    assert actor.reaction_available is (not allowed or sovereign)
    assert (actor.turn_flags.get(SOVEREIGN_FREE) == str(loaded.engine.state.round_number)) is (allowed and sovereign)
    assert not any(c.condition_id == ARROW_PENDING for a in loaded.engine.state.actors.values() for c in a.conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"
