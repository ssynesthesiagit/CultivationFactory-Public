"""Second C13 review: native granted moves, actual reactions and saved commits."""
import copy

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate4_persistence import Gate4Persistence
from tests import test_riders_c13 as C
from tests.test_c13_review_fixup import accept, intent

WATCHER = "actor:accounting.watcher"
CHAIN = "tianxia.talent.chains.chain_counter"


def seal(bundle):
    bundle["bundle_sha256"] = canonical_sha256({k: v for k, v in bundle.items() if k != "bundle_sha256"})
    return bundle


def mover_bundle(kind):
    bundle = C._bundle(C.DRUNKEN, items=C.AXE_ITEMS, dc=60)
    if kind == "swaying":
        from combat.ext.drunken_style import OFF_RHYTHM_ROW
        bundle["actor_template"]["armor_class"] = 100
        seed = copy.deepcopy(next(a for a in bundle["action_catalog"]
                                  if a["display_name"] == "Broken-Rhythm Strike: Fu (Short Axe)"))
        seed.update(source_definition_id="test:accounting.seed", display_name="Seed Off-Rhythm", economy="BONUS_ACTION")
        seed["parameters"]["typed"]["effects"] = [copy.deepcopy(OFF_RHYTHM_ROW)]
        bundle["action_catalog"].append(seed)
        bundle["actor_template"]["action_ids"].append(seed["source_definition_id"])
    return seal(bundle)


def session_for(tmp_path, kind, watcher, watcher_at, foe_at=(4, 6), reaction_change=0, mover_ac=None):
    foe = compile_character(C._sheet("tianxia.sphere.athletics", items=C.AXE_ITEMS), actor_id=C.FOE)
    for bundle in (foe, watcher):
        if reaction_change and (kind != "swaying" or bundle is watcher):
            for action in bundle["action_catalog"]:
                effects = (action["parameters"].get("typed") or {}).get("effects") or []
                if any(row["type"] == "attack" for row in effects):
                    # Synthetic native reaction effect independent of its hit,
                    # so the budget/terrain interaction does not rely on dice.
                    effects.append({"type": "remaining_movement", "flat": reaction_change, "applies_to": "target"})
        for row in bundle["typed_reactions"]:
            row["ask"] = True
        seal(bundle)
    mover = mover_bundle(kind)
    if mover_ac is not None:
        # Hit guarantees belong to the sealed genesis bundle, so event replay
        # never depends on an unrecorded live Armor Class mutation.
        mover['actor_template']['armor_class'] = mover_ac
        seal(mover)
    persistence = Gate4Persistence(C.ROOT, tmp_path)
    session = persistence.create_match(match_seed="C13-ACCOUNTING-" + kind,
        typed_bundles=(mover, foe, watcher),
        roster_setup={"primary_actor_ids": [C.ME, C.FOE, WATCHER],
            "team_by_actor": {C.ME: "team:a", C.FOE: "team:b", WATCHER: "team:b"},
            "starting_positions": {C.ME: {"x": 3, "y": 6}, C.FOE: {"x": foe_at[0], "y": foe_at[1]},
                                   WATCHER: {"x": watcher_at[0], "y": watcher_at[1]}}})
    while session.engine.state.current_actor_id != C.ME:
        session.submit_intent(intent(session.engine, "End turn"), primary_decision_record=None, reaction_provider=None)
    session.engine.typed_ask_reactors = frozenset({C.ME, C.FOE, WATCHER})
    return persistence, session


def swaying_turn(session):
    session.submit_intent(intent(session.engine, "Seed Off-Rhythm"), primary_decision_record=None, reaction_provider=None)
    session.submit_intent(intent(session.engine, "End turn"), primary_decision_record=None, reaction_provider=None)
    while session.engine.state.current_actor_id != C.FOE:
        session.submit_intent(intent(session.engine, "End turn"), primary_decision_record=None, reaction_provider=None)


@pytest.mark.parametrize("kind,cost,destination,after_pull", [
    ("reeling", 10, "cell:4,4", (5, 5)),
    ("swaying", 5, "cell:3,5", (3, 4)),
])
def test_post_move_chain_counter_pull_preserves_ordinary_pool_after_reload(tmp_path, kind, cost, destination, after_pull):
    watcher = compile_character(C._sheet("tianxia.sphere.chains", talents=(CHAIN,), dc=60), actor_id=WATCHER,
                                reaction_plan={"options": {CHAIN: 1}})
    # Keep the actual printed enter-reach reaction, without the independent
    # melee-attack trigger consuming the watcher's Reaction before the move.
    watcher["typed_reactions"] = [r for r in watcher["typed_reactions"] if r.get("kind") != "creature_d20"]
    persistence, session = session_for(tmp_path, kind, seal(watcher), (6, 6) if kind == "reeling" else (3, 3))
    if kind == "swaying":
        swaying_turn(session)
    engine = session.engine
    ordinary = engine.state.actors[C.ME].movement_remaining_ft
    requests = []
    def provider(request):
        requests.append(request)
        key = str(request["reaction_source_id"])
        options = request.get("legal_option_ids") or ()
        picks = [destination] if key.endswith(("drunken_reeling_move", "drunken_swaying_step")) else options[:1]
        return accept(request, picks)
    start = len(engine.events)
    action = intent(engine, "Reeling Step") if kind == "reeling" else intent(engine, "Fu (Short Axe) attack", C.FOE)
    session.submit_intent(action, primary_decision_record=None, reaction_provider=provider)
    commits = [e for e in engine.events[start:] if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == C.ME]
    assert len(commits) == 2, requests
    assert commits[0].payload["cost_ft"] == 0
    assert commits[0].payload["granted_cost_ft"] == cost and not commits[0].payload.get("forced")
    assert commits[1].payload["cost_ft"] == 0 and commits[1].payload["forced"]
    assert len(commits[1].payload["path"]) > 1  # a real pull, not just a zero-cost event
    assert any("CHAIN_COUNTER" in r["reaction_source_id"].upper() for r in requests), requests
    assert not engine.state.actors[WATCHER].reaction_available
    assert engine.state.actors[C.ME].movement_remaining_ft == ordinary
    loaded = persistence.load_match(session.match_id)
    mover = loaded.engine.state.actors[C.ME]
    assert mover.movement_remaining_ft == ordinary
    assert (mover.position.x, mover.position.y) == after_pull
    assert not getattr(loaded.engine, "_granted_movement_budget", None)
    assert not getattr(loaded.engine, "_granted_movement_oa", None)
    assert loaded.verify()["status"] == "PASS"


@pytest.mark.parametrize("ordinary", [0, 30])
@pytest.mark.parametrize("reaction_change", [-5, 0, 5])
@pytest.mark.parametrize("kind,cost,destination,stopped_at", [
    ("reeling", 5, "cell:1,6", (2, 6)),
    ("swaying", 0, "cell:3,5", (3, 6)),
])
def test_dynamic_terrain_cost_never_borrows_ordinary_movement(tmp_path, ordinary, reaction_change, kind, cost, destination, stopped_at):
    watcher = compile_character(C._sheet("tianxia.sphere.athletics", items=C.AXE_ITEMS), actor_id=WATCHER)
    _, session = session_for(tmp_path, kind, watcher, (3, 7) if kind == "swaying" else (8, 6),
                             foe_at=(4, 6) if kind == "swaying" else (3, 7), reaction_change=reaction_change)
    if kind == "swaying":
        swaying_turn(session)
    engine = session.engine
    mover = engine.state.actors[C.ME]
    mover.movement_remaining_ft = ordinary
    mover.armor_class = -50 if kind == "reeling" else 100
    requests = []
    def provider(request):
        requests.append(request)
        key = str(request["reaction_source_id"])
        options = request.get("legal_option_ids") or ()
        if "LEAVE_REACH" in request["checkpoint"]:
            # The real native leave-reach window changes the selected next
            # square's cost before the Opportunity Attack resolves.
            cell = (1, 6) if kind == "reeling" else (3, 5)
            engine.grid.base_movement_cost[cell] = 2
        picks = [WATCHER] if key.endswith("drunken_reeling_oa") else [destination] if key.endswith(
            ("drunken_reeling_move", "drunken_swaying_step")) else options[:1]
        return accept(request, picks)
    start = len(engine.events)
    session.submit_intent(intent(engine, "Reeling Step") if kind == "reeling" else intent(engine, "Fu (Short Axe) attack", C.FOE),
                          primary_decision_record=None, reaction_provider=provider)
    assert any("LEAVE_REACH" in r["checkpoint"] for r in requests), requests
    commit = next(e for e in engine.events[start:] if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == C.ME)
    assert commit.payload["interrupted"] and commit.payload["cost_ft"] == 0
    assert commit.payload["granted_cost_ft"] == cost
    assert (mover.position.x, mover.position.y) == stopped_at
    assert mover.movement_remaining_ft == max(0, ordinary + reaction_change), [
        (e.event_type, e.actor_id, e.payload) for e in engine.events[start:]
        if e.event_type in {"ATTACK_ROLLED", "MOVEMENT_GRANTED"}]


@pytest.mark.parametrize("effect,remaining,arrived", [
    ({"type": "remaining_movement", "flat": -5}, 25, True),
    ({"type": "remaining_movement", "flat": 5}, 35, True),
    ({"type": "remaining_movement", "becomes": 0}, 0, False),
])
def test_native_opportunity_effect_keeps_real_movement_loss_or_gain(tmp_path, effect, remaining, arrived):
    watcher = compile_character(C._sheet("tianxia.sphere.athletics", items=C.AXE_ITEMS), actor_id=WATCHER)
    for action in watcher["action_catalog"]:
        for row in (action["parameters"].get("typed") or {}).get("effects") or []:
            if row["type"] == "attack":
                row.setdefault("on_hit", []).append({**effect, "applies_to": "target"})
    persistence, session = session_for(tmp_path, "reeling", seal(watcher), (3, 7), foe_at=(4, 6), mover_ac=0)
    engine = session.engine
    mover = engine.state.actors[C.ME]
    def provider(request):
        key = str(request["reaction_source_id"])
        options = request.get("legal_option_ids") or ()
        picks = [C.FOE] if key.endswith("drunken_reeling_oa") else ["cell:3,5"] if key.endswith("drunken_reeling_move") else options[:1]
        return accept(request, picks)
    session.submit_intent(intent(engine, "Reeling Step"), primary_decision_record=None,
                          reaction_provider=provider)
    assert not engine.state.actors[WATCHER].reaction_available
    assert mover.movement_remaining_ft == remaining
    assert (mover.position.x, mover.position.y) == ((3, 5) if arrived else (3, 6))
    # The reaction-adjusted ordinary pool and interruption result must survive
    # the committed session boundary, not only the live engine call.
    loaded = persistence.load_match(session.match_id)
    assert loaded.engine.state.actors[C.ME].movement_remaining_ft == remaining
    assert (loaded.engine.state.actors[C.ME].position.x,
            loaded.engine.state.actors[C.ME].position.y) == ((3, 5) if arrived else (3, 6))
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_legacy_opportunity_dying_mover_does_not_regain_ordinary_movement(monkeypatch):
    from combat.gate2_runtime_content import LEE
    from tests.test_lock_choices import install
    install(monkeypatch, "zero_hp", lambda *args: "DYING")
    engine = C.t.Gate4ControllerEngine(C.ROOT, match_seed="C13-LEGACY-LIFECYCLE", typed_bundles=(C._bundle(C.DRUNKEN, dc=60),),
        roster_setup={"primary_actor_ids": [C.ME, C.AN, LEE],
            "team_by_actor": {C.ME: "team:a", C.AN: "team:b", LEE: "team:b"},
            "starting_positions": {C.ME: {"x": 3, "y": 6}, C.AN: {"x": 4, "y": 6}, LEE: {"x": 8, "y": 6}}})
    mover, foe = engine.state.actors[C.ME], engine.state.actors[C.AN]
    assert foe.entity_id not in engine.typed_actor_ids
    # A second visible creature takes Reeling's exemption; the legacy foe's
    # real Opportunity Attack therefore still answers the native move.
    mover.current_hp = 1
    mover.armor_class = -50
    requests = []
    def provider(request):
        requests.append(request)
        key = str(request["reaction_source_id"])
        options = request.get("legal_option_ids") or ()
        picks = [LEE] if key.endswith("drunken_reeling_oa") else ["cell:2,6"] if key.endswith("drunken_reeling_move") else options[:1]
        return accept(request, picks)
    engine.set_reaction_provider(provider)
    C._use(engine, "Reeling Step", target=None)
    assert not foe.reaction_available
    assert mover.life_state == "DYING"
    assert mover.movement_remaining_ft == 0
    assert not getattr(engine, "_granted_movement_budget", None)


@pytest.mark.parametrize("budget_kind", ["missing", "other_mover"])
def test_native_granted_move_ignores_missing_or_foreign_extension_budget(budget_kind):
    engine, mover, other = C._fight(C.DRUNKEN, dc=60)
    candidate = next(c for c in engine.legal_candidates()
                     if c.kind == "MOVE" and c.destination is not None
                     and c.destination != mover.position and c.movement_cost_ft <= 5)
    action = intent(engine, "Reeling Step")
    if budget_kind == "missing":
        engine._granted_movement_budget = None
    else:
        engine._granted_movement_budget = {"actor": other, "grant": 0}
    before = mover.position
    engine._resolve_movement(mover, candidate, action, granted_ft=5,
                              ignore_oa_from=(C.FOE,))
    assert mover.position == candidate.destination
    assert mover.position != before
