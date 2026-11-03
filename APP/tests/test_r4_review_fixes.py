"""Table regressions for the R4 review's provenance, escape and movement interactions.

Setup actions apply ordinary typed effects through table commits; no engine
function replacement or unpersisted state mutation is used.
"""
import pytest

from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate2_runtime_models import RollRecord
from combat.gate5_service import CombatService
from combat.ext import d20_floor, d20_rewrite_auspices
from tests.h1_support import ROOT
from tests.test_r4_integration import BREATH, P, S, auto_candidate, candidate, fixture, reach, send

STITCH = "TAL_THREAD_MERIDIAN_STITCH"
FLOOR = "condition:typed.d20_floor"
BOUND = "condition:typed.bound_limb"


def add_setup(bundle, name, effects, *, numbers=None):
    aid = bundle["actor_id"]
    row = ActionDefinition(source_definition_id=f"action:test.{aid}.{name}", display_name=name,
        owner_id=aid, economy=EconomyKind.NONE, resolution_kind="TYPED", target_kind="SELF",
        parameters={"typed": {"source": "test:review_setup", "effects": effects,
                    "numbers": numbers or {"save_dc": 12}, "duration": {"kind": "instant"}, "riders": []}})
    bundle["action_catalog"].append(row.model_dump(mode="json"))
    bundle["actor_template"]["action_ids"].append(row.source_definition_id)


def cast(table, mid, name, target=None):
    assert send(table, mid, candidate(table, mid, name, target))["status"] == "COMMITTED"


@pytest.mark.parametrize("chosen", ["Meridian constriction", "Tendon injury"])
def test_stitch_qualifies_and_player_selects_exact_instance_reload(tmp_path, chosen):
    def setup(bundles):
        for name, tag in [("Command motion", "command_motion"), ("Unknown slow", None),
                          ("Meridian constriction", "meridian_constriction"), ("Tendon injury", "tendon_injury")]:
            add_setup(bundles[0], name, [{"type": "speed", "applies_to": "self", "flat": -5,
                "expires_on": "UNTIL_REMOVED", **({"provenance": tag} if tag else {})}])
    combat, table, mid = fixture(tmp_path, [STITCH], configure=setup)
    reach(table, mid, P)
    for name in ("Command motion", "Unknown slow", "Meridian constriction", "Tendon injury"):
        cast(table, mid, name)
    cid = candidate(table, mid, "Meridian Stitch: End Speed Reduction", P)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send(table, mid, cid)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert "Meridian Stitch" in prompt["moment"] and "Rider Player" in prompt["moment"]
    options = prompt["choice"]["options"]
    assert len(options) == 2
    assert {o["label"].split(" from ")[0] for o in options} == {"Meridian constriction", "Tendon injury"}
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send(table, mid, cid)["reaction"] == prompt
    picked = next(o["id"] for o in options if o["label"].startswith(chosen))
    answer = {**prompt["context"], "selection": "USE", "option_ids": [picked]}
    assert send(table, mid, cid, [answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    mods = loaded.engine.state.actors[P].modifiers
    assert picked not in mods and len(mods) == 3
    assert any(e.event_type == "GM_RIDER" and "GM decides" in str(e.payload) for e in loaded.engine.events)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_stitch_known_nonmatching_only_is_not_offered_after_reload(tmp_path):
    def setup(bundles):
        add_setup(bundles[0], "Command motion", [{"type": "speed", "applies_to": "self", "flat": -5,
            "expires_on": "UNTIL_REMOVED", "provenance": "command_motion"}])
    combat, table, mid = fixture(tmp_path, [STITCH], configure=setup)
    reach(table, mid, P)
    cast(table, mid, "Command motion")
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    assert len(before["actors"][P]["modifiers"]) == 1
    table = type(table)(CombatService(ROOT, tmp_path), tmp_path)
    options = [(g["label"], o) for g in table.state(mid)["menu"]["actions"] for o in g["options"]]
    assert not any("Meridian Stitch: End Speed Reduction" in o.get("label", label)
                   and P in o.get("target_ids", []) for label, o in options)
    # Only the ineligible option disappears; other Stitch uses remain available.
    assert candidate(table, mid, "Meridian Stitch: Restore CP", P)
    loaded = table.combat._load_session(mid)
    assert loaded.engine.state.model_dump(mode="json") == before
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_stitch_unknown_provenance_is_gm_only(tmp_path):
    def setup(bundles):
        add_setup(bundles[0], "Unknown slow", [{"type": "speed", "applies_to": "self", "flat": -5,
                                               "expires_on": "UNTIL_REMOVED"}])
    combat, table, mid = fixture(tmp_path, [STITCH], configure=setup)
    reach(table, mid, P)
    cast(table, mid, "Unknown slow")
    cast(table, mid, "Meridian Stitch: End Speed Reduction", P)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert len(loaded.engine.state.actors[P].modifiers) == 1
    assert any(e.event_type == "GM_RIDER" and "GM decides" in str(e.payload) for e in loaded.engine.events)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_stitch_ai_selects_only_an_eligible_instance(tmp_path):
    def setup(bundles):
        for name, tag in [("Command motion", "command_motion"), ("Unknown slow", None),
                          ("Meridian constriction", "meridian_constriction")]:
            add_setup(bundles[0], name, [{"type": "speed", "applies_to": "self", "flat": -5,
                "expires_on": "UNTIL_REMOVED", **({"provenance": tag} if tag else {})}])
    combat, table, mid = fixture(tmp_path, [STITCH], configure=setup)
    reach(table, mid, P)
    for name in ("Command motion", "Unknown slow", "Meridian constriction"):
        cast(table, mid, name)
    cid = candidate(table, mid, "Meridian Stitch: End Speed Reduction", P)
    auto_candidate(combat, mid, P, cid)
    assert table.auto_step(mid, 0)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    names = {loaded.engine.action_catalog[m.source_definition_id].display_name
             for m in loaded.engine.state.actors[P].modifiers.values()}
    assert names == {"Command motion", "Unknown slow"}
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("escape", ["Escape the binding", "Escape grapple"])
@pytest.mark.parametrize("release", ["own", "USE", "DECLINE", "ai"])
def test_escape_ordinary_floor_and_off_turn_ally_release(tmp_path, escape, release):
    def setup(bundles):
        action = next(row for row in bundles[0]["action_catalog"] if row["display_name"] == escape)
        typed = action["parameters"]["typed"]
        bonus = typed["effects"][0].get("bonus", typed["numbers"].get("escape_bonus", 0))
        effect = {"type": "bind_limb", "applies_to": "self", "mode": "footwork"} if escape == "Escape the binding" else {
            "type": "condition", "condition": "grappled", "applies_to": "self", "escape_dc": 10 + bonus,
            "expires_on": "UNTIL_REMOVED"}
        add_setup(bundles[0], "Setup hold", [effect], numbers={"save_dc": 10 + bonus})
    auspice = "TAL_FATE_COMPLETE_MANDALA_AUSPICE"
    combat, table, mid = fixture(tmp_path, [auspice], second=[auspice], seed="R4-ESCAPE-2", configure=setup)
    reach(table, mid, P if release == "own" else S)
    caster = P if release == "own" else S
    cast(table, mid, "Complete Mandala Auspice", caster)
    if release == "own":
        assert send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    reach(table, mid, P)
    cast(table, mid, "Setup hold")
    cid = candidate(table, mid, escape)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    if release == "ai":
        # The actor rolls on an AI turn; the manual ally still owns its Release.
        auto_candidate(combat, mid, P, cid)
        result = table.auto_step(mid, 0)
    else:
        result = send(table, mid, cid)
    if release != "own":
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        assert prompt["context"]["reactor_id"] == S
        assert "Complete Mandala Auspice" in str(prompt)
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        answer = {**prompt["context"], "selection": "DECLINE" if release == "DECLINE" else "USE"}
        result = table.auto_step(mid, 0, [answer]) if release == "ai" else send(table, mid, cid, [answer])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    checks = [e.payload for e in loaded.engine.events if e.event_type == "CHECK_ROLLED"]
    assert len(checks) == 1 and checks[0]["actor"]["natural_result"] < 10
    success = release != "DECLINE"
    assert checks[0]["success"] == success
    actor, bearer = loaded.engine.state.actors[P], loaded.engine.state.actors[caster]
    assert any(c.condition_id == (BOUND if escape == "Escape the binding" else "condition:typed.grappled")
               for c in actor.conditions.values()) == (not success)
    assert any(c.condition_id == FLOOR for c in bearer.conditions.values()) == (release in ("own", "DECLINE"))
    assert bearer.reaction_available == (release in ("own", "DECLINE"))
    if release not in ("own", "DECLINE"):
        assert bearer.concentration is None
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ability,cast_name,condition", [
    ("TAL_FATE_COMPLETE_MANDALA_AUSPICE", "Complete Mandala Auspice", "d20_floor"),
    ("TAL_FATE_EMPTY_ROAD_AUSPICE", "Empty Road Auspice", "d20_auspice"),
])
def test_suppressed_d20_auspice_stops_and_restores_its_rule_through_table(tmp_path, ability, cast_name, condition):
    def setup(bundles):
        actor = bundles[1]["actor_template"]["entity_id"]
        row = ActionDefinition(
            source_definition_id=f"action:test.{actor}.suppress_{condition}", display_name="Suppress Auspice",
            owner_id=actor, economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
            range_ft=60, parameters={"typed": {"source": "test:suppression", "numbers": {"save_dc": 12},
                "duration": {"kind": "instant"}, "riders": [], "effects": [{"type": "end_effect",
                    "applies_to": "target", "conditions": [condition], "select": "any", "on_success": "suppress"}]}})
        bundles[1]["action_catalog"].append(row.model_dump(mode="json"))
        bundles[1]["actor_template"]["action_ids"].append(row.source_definition_id)

    from tests.test_r4_integration import F

    combat, table, mid = fixture(tmp_path, [ability], configure=setup)
    reach(table, mid, P)
    cast(table, mid, cast_name, P)
    engine = combat._load_session(mid).engine
    bearer = engine.state.actors[P]
    floor_roll = RollRecord(roll_id="suppression-floor", counter_start=0, counter_end=1, expression="1d20+0",
                            actor_id=P, reason="CHECK:test", dice=(3,), modifier=0, total=3, natural_result=3)
    if condition == "d20_floor":
        assert d20_floor.check_floor(engine, bearer, floor_roll, 12) == 10
    else:
        assert len(d20_rewrite_auspices.bearing("empty_road")(engine)) == 1

    reach(table, mid, F)
    cast(table, mid, "Suppress Auspice", P)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    bearer = loaded.engine.state.actors[P]
    held = next(c for c in bearer.conditions.values() if c.condition_id == f"condition:typed.suppressed.{condition}")
    if condition == "d20_floor":
        assert d20_floor.check_floor(loaded.engine, bearer, floor_roll, 12) is None
    else:
        assert not d20_rewrite_auspices.bearing("empty_road")(loaded.engine)
    assert loaded.verify()["status"] == "PASS"

    # Suppression ends at the end of the bearer’s next turn; persist that
    # table commit and confirm the restored condition grants its rule again.
    for _ in range(6):
        menu = table.state(mid)["menu"]
        assert send(table, mid, menu["end_turn"])["status"] == "COMMITTED"
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        bearer = loaded.engine.state.actors[P]
        if any(c.condition_id == f"condition:typed.{condition}" for c in bearer.conditions.values()):
            break
    else:
        raise AssertionError("suppressed condition did not return during the bearer’s next turn")
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
    bearer = loaded.engine.state.actors[P]
    if condition == "d20_floor":
        assert d20_floor.check_floor(loaded.engine, bearer, floor_roll, 12) == 10
    else:
        assert len(d20_rewrite_auspices.bearing("empty_road")(loaded.engine)) == 1


@pytest.mark.parametrize("adjustment", ["Lower speed", "Extra allowance"])
@pytest.mark.parametrize("moved", [False, True])
def test_breath_held_uses_movement_history_after_allowance_change(tmp_path, adjustment, moved):
    def setup(bundles):
        add_setup(bundles[0], "Lower speed", [{"type": "speed", "applies_to": "self", "flat": -15,
                                              "expires_on": "UNTIL_REMOVED"}])
        # Ordinary Dash resolver, but free setup economy keeps an Action for the shot.
        add_setup(bundles[0], "Extra allowance", [{"type": "movement", "distance_ft": "speed"}])
    combat, table, mid = fixture(tmp_path, [BREATH], bow=True, configure=setup)
    reach(table, mid, P)
    if moved:
        move = next(m for m in table.state(mid)["menu"]["moves"] if m["cost_ft"] == 5)
        assert send(table, mid, move["candidate_id"])["status"] == "COMMITTED"
    cast(table, mid, adjustment)
    # Fresh service loads both the snapshot and the movement event history.
    table = type(table)(CombatService(ROOT, tmp_path), tmp_path)
    names = [o.get("label", g["label"]) for g in table.state(mid)["menu"]["actions"] for o in g["options"]]
    assert any("Breath-Held Shot" in n for n in names) == (not moved)
    loaded = table.combat._load_session(mid)
    actor = loaded.engine.state.actors[P]
    assert actor.movement_remaining_ft >= loaded.engine._effective_speed(actor)
    assert loaded.mechanical.replay()["status"] == "PASS"
    assert send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    reach(table, mid, P)
    assert candidate(table, mid, "Breath-Held Shot")
