"""C12 review: real Catch Step and linked Phantasm transactions and saved escapes.

No browser is launched. All portable characters and fights are test-owned.
"""
import pytest

from combat.ext import escape_options, ice_fracture
from tests.r1i_service_support import fixture, candidate, force_ai_candidate, OWNER, FOE, SECOND
from tests.test_r1i_round3 import resolve, reload


@pytest.mark.parametrize("choose_target", [False, True])
def test_substantial_figment_decline_or_successful_save_leaves_no_hold(tmp_path, choose_target):
    from combat.ext.illusion_riders import SUBSTANTIAL
    combat, table, mid, send, commit = fixture(tmp_path, [SUBSTANTIAL], owner_dc=-100)
    cid = next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"]
               if g["label"] == "Create Figment + Substantial Phantasm (3 CP; Grappled)"
               for o in g["options"] if o.get("destination") == {"x": 4, "y": 6})
    before = reload(tmp_path, mid)
    resolve(combat, mid, send, cid, {"choice:needle.substantial_phantasm": FOE} if choose_target else {})
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events[len(before.events):] if e.event_type == "SAVE_ROLLED"]
    assert len(saves) == int(choose_target)
    assert all(e.payload["success"] for e in saves)
    assert not any(c.source_definition_id == SUBSTANTIAL for a in engine.state.actors.values() for c in a.conditions.values())


def test_substantial_figment_variants_require_the_owned_talent():
    from tests.h1_support import bundle
    actions = bundle("TAL_ILLUSION_CREATE_FIGMENT")["action_catalog"]
    assert any(a["display_name"] == "Create Figment" for a in actions)
    assert not any("Substantial Phantasm" in a["display_name"] for a in actions)


def test_substantial_figment_cannot_hold_a_creature_that_recognizes_it(tmp_path):
    from combat.ext.illusion_riders import SUBSTANTIAL
    from combat.ext import placed
    combat, table, mid, send, commit = fixture(
        tmp_path, [SUBSTANTIAL, "TAL_ILLUSION_SELECTIVE_PREMISE"], owner_dc=-100, allies=[FOE])
    commit(candidate(table, mid, "Figment: Selective Premise"))
    cid = next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"]
               if g["label"] == "Create Figment + Substantial Phantasm (3 CP; Grappled)"
               for o in g["options"] if o.get("destination") == {"x": 4, "y": 6})
    _, prompts = resolve(combat, mid, send, cid, {"choice:needle.substantial_phantasm": SECOND})
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.substantial_phantasm")
    assert FOE not in [o["id"] for o in prompt["choice"]["options"]]
    engine = reload(tmp_path, mid)
    (zone,) = placed.of(engine, "figment")
    assert FOE in placed.data(zone)["recognized"]
    assert not any(e.event_type == "SAVE_ROLLED" and e.actor_id == FOE for e in engine.events)
    assert not escape_options.options(engine.state.actors[FOE])


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("hold,cost", [("grappled", 3), ("restrained", 5)])
def test_real_substantial_figment_study_clears_hold_immediately(tmp_path, monkeypatch, auto_turn, hold, cost):
    from combat.gate2_rolls import DeterministicRollAuthority
    from combat.ext.illusion_riders import SUBSTANTIAL

    real_d20 = DeterministicRollAuthority.d20

    def study_dice(roller, **kwargs):
        # Test-only dice: adjudication, transactions and recorded rolls stay real.
        wanted = (1 if kwargs["reason"].startswith("SAVE:") else 20
                  if kwargs["reason"].startswith("CHECK:") else None) if kwargs["actor_id"] == FOE else None
        while True:
            roll = real_d20(roller, **kwargs)
            if wanted is None or roll.natural_result == wanted:
                return roll

    monkeypatch.setattr(DeterministicRollAuthority, "d20", study_dice)

    combat, table, mid, send, commit = fixture(
        tmp_path, [SUBSTANTIAL], owner_dc=16,
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 8, "y": 6}})
    label = f"Create Figment + Substantial Phantasm ({cost} CP; {hold.title()})"
    cid = next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if g["label"] == label
               for o in g["options"] if o.get("destination") == {"x": 4, "y": 6})
    before = reload(tmp_path, mid)
    resources = dict(before.state.actors[OWNER].resources)
    resolve(combat, mid, send, cid, {"choice:needle.substantial_phantasm": FOE})
    engine = reload(tmp_path, mid)
    held = engine.state.actors[FOE]
    saves = [e for e in engine.events[len(before.events):] if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert len(saves) == 1 and not saves[0].payload["success"]
    guards = [c for c in held.conditions.values() if c.source_definition_id == SUBSTANTIAL and c.condition_id.endswith("." + hold)]
    assert len(guards) == 1
    ((key, record),) = escape_options.options(held)
    assert record.data["guards"] == [guards[0].instance_id]
    assert resources["resource:core.qi"] - engine.state.actors[OWNER].resources["resource:core.qi"] == cost
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    assert escape_options.options(reload(tmp_path, mid).state.actors[FOE])
    cid = candidate(table, mid, "Break free")
    if auto_turn:
        force_ai_candidate(combat, mid, FOE, cid)
    before = reload(tmp_path, mid)
    resolve(combat, mid, send, cid, {}, auto=auto_turn)
    engine = reload(tmp_path, mid)
    checks = [e for e in engine.events[len(before.events):] if e.event_type == "CHECK_ROLLED" and e.actor_id == FOE]
    assert len(checks) == 1 and checks[0].payload["success"]
    assert "Investigation" in checks[0].payload["check"]
    assert engine.state.current_actor_id == FOE
    assert engine.state.round_number == before.state.round_number
    assert not engine.state.actors[FOE].action_available
    assert not any(c.source_definition_id == SUBSTANTIAL for c in engine.state.actors[FOE].conditions.values())
    assert not escape_options.options(engine.state.actors[FOE])
    assert not any(m.source_definition_id == SUBSTANTIAL for m in engine.state.actors[FOE].modifiers.values())
    assert not any(c.display_name == "Break free" for c in engine.legal_candidates())


@pytest.mark.parametrize("auto_turn", [False, True])
def test_catch_step_creates_a_saved_repeat_save_action(tmp_path, auto_turn):
    combat, table, mid, send, commit = fixture(
        tmp_path, ["ICE_BASE_SPENDING_A_FRACTURE_MARK", "ICE_BASE_CRYSTALLIZE_PATH",
                   "ICE_BASE_SHARD_NEEDLE", "TAL_ICE_FROZEN_MERIDIAN_BIND"],
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 4}, SECOND: {"x": 8, "y": 6}})
    commit(candidate(table, mid, "Crystallize Path"))
    while True:
        commit(table.state(mid)["menu"]["end_turn"])
        if table.state(mid)["menu"]["actor_id"] == OWNER:
            break
    commit(candidate(table, mid, "Shard Needle", FOE))
    engine = reload(tmp_path, mid)
    held = engine.state.actors[FOE]
    assert ice_fracture.marked(held, OWNER)
    assert not ice_fracture.on_lattice(engine, OWNER, held)
    assert not escape_options.options(held)
    cp = dict(engine.state.actors[OWNER].resources)
    cid = table.state(mid)["menu"]["end_turn"]
    if auto_turn:
        force_ai_candidate(combat, mid, OWNER, cid)
    _, prompts = resolve(combat, mid, send, cid,
                         {"choice:needle.fracture_response": "catch"}, auto=auto_turn)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.fracture_response" for p in prompts) == (not auto_turn)
    engine = reload(tmp_path, mid)
    held = engine.state.actors[FOE]
    ((key, record),) = escape_options.options(held)
    assert record.data["kind"] == "save" and record.data["dc"] == 50
    assert record.source_definition_id == "TAL_ICE_FROZEN_MERIDIAN_BIND"
    assert all(held.conditions[g].source_definition_id == record.source_definition_id for g in record.data["guards"])
    assert any(cp[k] - engine.state.actors[OWNER].resources[k] == 1 for k in cp)
    assert not ice_fracture.marked(held, OWNER)
    assert "Frozen Meridian Bind" in record.data["label"]
    # Repeat the save using the prisoner's actual table menu after disk reload.
    while table.state(mid)["menu"]["actor_id"] != FOE:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, "Break free")
    if auto_turn:
        force_ai_candidate(combat, mid, FOE, cid)
    before = len(reload(tmp_path, mid).events)
    resolve(combat, mid, send, cid, {}, auto=auto_turn)
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events[before:] if e.event_type == "SAVE_ROLLED" and e.actor_id == FOE]
    assert len(saves) == 1 and not saves[0].payload["success"]
    assert key in engine.state.actors[FOE].conditions
    assert not engine.state.actors[FOE].action_available
