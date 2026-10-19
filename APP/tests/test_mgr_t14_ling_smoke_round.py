"""MGR-T14 Ling: the Smoke Trace placement's once-per-round clock is the round.

The printed "once per round" is tracked against the actual round identity,
independently of the trace's own printed lifetime (until the end of the owner's
next turn) and of the shared Smoke Response allowance. The old self-mark cleared
at the start of the owner's next turn -- a turn clock -- so a placement made
before the owner's turn would free a second placement the moment that turn
began, inside the same round. The clock is now the current round number in
evented, saved, owned state, queried purely by ``candidate_allowed`` and
consumed only when a placement actually commits. These native tests cover menu
preview/abandonment, not an AI estimate or submitted-then-declined placement.
Off-turn placement followed by the owner's same-round turn is not exposed by
the current manual placement interface. The same-round tests cover another
creature's real turn transition and the owner's native start-turn boundary on
a disposable loaded session; the latter is not saved or claimed as replay
evidence. Single-target placement commits immediately on submission."""

from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.typed_executor import bears_mark

from tests.h1_support import sheet

import tests.test_auto43r1f1_smoke_table as T

ROOT = Path(__file__).resolve().parents[1]
ME, FOE = T.OWNER, T.FOE
FOE2 = "actor:factory.foe2"
ROUND_USE = "condition:typed.smoke_trace_round"
OLD_TURN_MARK = "condition:typed.mark.smoke_trace_placed_this_round"
# A seed whose initiative puts the foe first, so the owner acts second and the
# round boundary is observable before the owner's own turn.
FOE_FIRST_SEED = "LING-R2"


def _bundles(docs):
    out = []
    for index, (actor_id, doc) in enumerate(docs):
        doc["identity"]["display_name"] = "Smoke Keeper" if index == 0 else f"Fire Caller {index}"
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 300
        out.append(compile_character(doc, actor_id=actor_id))
    return out


def _build(tmp_path, foe_ids=(FOE,), seed=FOE_FIRST_SEED, *, owner_first=False):
    """A native table match: the smoke owner against the given foes."""
    all_ids = (ME,) + tuple(foe_ids)
    docs = [(ME, sheet([T.VEIL, *T.BASES], cl=15, dc=50, primary="Stamina"))]
    if owner_first:
        # Native character statistic, not a mutation of the fight's turn order.
        docs[0][1]["ability_scores_and_statistics"]["initiative"] = {"bonus": 100}
    for foe in foe_ids:
        docs.append((foe, sheet([], cl=15, dc=15, primary="Stamina")))
    bundles = _bundles(docs)
    combat = CombatService(ROOT, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    teams = {actor_id: ("team:a" if actor_id == ME else "team:b") for actor_id in all_ids}
    positions = {ME: {"x": 3, "y": 6}}
    for index, foe in enumerate(foe_ids):
        positions[foe] = {"x": 5 + 2 * index, "y": 6}
    mid = combat._finish_factory_match(
        bundles, list(all_ids), teams, positions, arena, [ME], list(foe_ids),
        control_modes={actor_id: "MANUAL" for actor_id in all_ids},
        match_seed=seed, display_name="MGR-T14 Ling smoke round clock",
        maximum_rounds=8)["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def _advance(table, mid, actor):
    """Commit end-turn through the table until it is ``actor``'s turn."""
    while table.state(mid)["menu"]["actor_id"] != actor:
        T._commit(table, mid, table.state(mid)["menu"]["end_turn"])


def _candidate(table, mid, label):
    for group in table.state(mid)["menu"]["actions"]:
        for option in group.get("options", []):
            if label in option["label"]:
                return option["candidate_id"]
    raise AssertionError(f"no candidate labelled {label!r}")


def _act(table, mid, candidate_id, answers=()):
    """Commit a candidate through the table, answering any choice prompt."""
    state = table.state(mid)
    res = table.act(mid, candidate_id, state["menu"]["decision_id"],
                    state["menu"]["state_version"], state["last_sequence"])
    for answer in answers:
        state = table.state(mid)
        res = table.act(mid, candidate_id, state["menu"]["decision_id"],
                        state["menu"]["state_version"], state["last_sequence"], [answer])
    return res


def _target_answer(reaction, target):
    choice = reaction["choice"]
    option = next(opt for opt in choice["options"] if opt.get("actor_id") == target)
    return {**reaction["context"], "selection": "USE", "option_ids": [option["option_id"]]}


def _use(table, mid, label, target=None):
    """Drive a named placement through the native table path (real roll/provenance)."""
    state = table.state(mid)
    res = table.act(mid, _candidate(table, mid, label), state["menu"]["decision_id"],
                    state["menu"]["state_version"], state["last_sequence"])
    if res["status"] == "REACTION_REQUIRED" and target is not None:
        answer = _target_answer(res["reaction"], target)
        state = table.state(mid)
        res = table.act(mid, _candidate(table, mid, label), state["menu"]["decision_id"],
                        state["menu"]["state_version"], state["last_sequence"], [answer])
    assert res["status"] == "COMMITTED", res
    return res


def _engine_of(combat, mid):
    """The engine behind a CombatService or an already-loaded session."""
    return combat.engine if hasattr(combat, "engine") else combat._load_session(mid).engine


def _round_use(combat, mid):
    owner = _engine_of(combat, mid).state.actors[ME]
    return next((c for c in owner.conditions.values() if c.condition_id == ROUND_USE), None)


def _placement_legal(combat, mid):
    engine = _engine_of(combat, mid)
    return any(c.display_name == "Place Smoke Trace" for c in engine.legal_candidates())


def _reload(combat, mid, tmp_path):
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert reloaded.verify()["status"] == "PASS"
    assert reloaded.mechanical.replay()["status"] == "PASS"
    return reloaded


def test_placement_clock_is_the_round_identity_evented_and_saved(tmp_path):
    """A committed placement records the current round number as evented, saved state."""
    combat, table, mid = _build(tmp_path)
    _advance(table, mid, ME)
    engine = combat._load_session(mid).engine
    round_now = engine.state.round_number

    _use(table, mid, "Place Smoke Trace", target=FOE)

    engine = combat._load_session(mid).engine
    condition = _round_use(combat, mid)
    assert condition is not None, "placement must record its round clock"
    assert condition.data["round"] == round_now == engine.state.round_number
    # Evented: the clock's CONDITION_APPLIED is in the fight's own journal.
    assert any(event.event_type == "CONDITION_APPLIED"
               and (event.payload or {}).get("condition_id") == ROUND_USE
               for event in engine.events)
    # The trace's own printed lifetime is separate and lands on the target.
    assert bears_mark(engine.state.actors[FOE], ME, "Smoke Trace")
    # A second placement is not offered in the same round.
    assert not _placement_legal(combat, mid)
    # The clock is independent of the shared Smoke Response allowance.
    from combat.ext import response_limits
    assert response_limits.available(engine, engine.state.actors[ME], "smoke")


def test_the_round_clock_survives_a_cold_reload(tmp_path):
    """Reload retains the placement usage."""
    combat, table, mid = _build(tmp_path)
    _advance(table, mid, ME)
    _use(table, mid, "Place Smoke Trace", target=FOE)
    before = _round_use(combat, mid)
    assert before is not None

    reloaded = _reload(combat, mid, tmp_path)

    engine = reloaded.engine
    condition = _round_use(reloaded, mid)
    assert condition is not None, "usage must survive a cold reload"
    assert condition.data["round"] == before.data["round"]
    assert not _placement_legal(reloaded, mid)


def test_actual_round_advancement_restores_placement(tmp_path):
    """A new round is a fresh once-per-round."""
    combat, table, mid = _build(tmp_path)
    _advance(table, mid, ME)
    _use(table, mid, "Place Smoke Trace", target=FOE)
    assert not _placement_legal(combat, mid)

    _advance(table, mid, FOE)        # end the owner's turn
    _advance(table, mid, ME)         # the next round, owner's turn again

    engine = combat._load_session(mid).engine
    assert engine.state.round_number > 1
    assert _round_use(combat, mid) is None, "the stale round clock must be retired"
    assert _placement_legal(combat, mid), "a new round restores the placement"


def test_usage_retires_at_the_round_boundary_before_the_owners_turn(tmp_path):
    """The clock is keyed to the round, not the owner's turn: it retires when the
    next round begins -- before the owner's own turn, with the foe acting first."""
    combat, table, mid = _build(tmp_path)          # initiative: foe, then owner
    _advance(table, mid, ME)
    _use(table, mid, "Place Smoke Trace", target=FOE)
    engine = combat._load_session(mid).engine
    assert engine.state.round_number == 1

    _advance(table, mid, FOE)                      # end the owner's turn -> round 2, foe's turn
    engine = combat._load_session(mid).engine
    assert engine.state.round_number == 2
    assert engine.state.current_actor_id == FOE    # still before the owner's turn

    owner = engine.state.actors[ME]
    # The round clock retired the usage at the round boundary; no turn-expiring
    # "placed this round" tracker may survive into the new round either.
    assert not any(c.condition_id == ROUND_USE for c in owner.conditions.values())
    assert not any(c.condition_id.startswith(OLD_TURN_MARK) for c in owner.conditions.values())


def test_same_round_owner_turn_start_preserves_committed_usage(tmp_path):
    """Exercise the native session turn-start boundary without a round change.

    Manual placement is active-owner-turn only. Commit normally, cold reload,
    then invoke the engine's real start-turn boundary on that session. This
    isolates its expiry behavior; it is NOT an off-turn placement simulation.
    The boundary probe is disposable and is not written into the saved fight.
    """
    combat, table, mid = _build(tmp_path)
    _advance(table, mid, ME)
    _use(table, mid, "Place Smoke Trace", target=FOE)
    session = _reload(combat, mid, tmp_path)
    engine = session.engine
    round_before = engine.state.round_number
    starts_before = engine.state.actors[ME].turns_started
    events_before = len(engine.events)
    assert engine.state.current_actor_id == ME
    assert not _placement_legal(session, mid)

    engine._system_start_turn()

    assert engine.state.round_number == round_before
    assert engine.state.actors[ME].turns_started == starts_before + 1
    assert any(event.event_type == "TURN_STARTED" and event.actor_id == ME
               and event.payload["round"] == round_before
               for event in engine.events[events_before:])
    assert not _placement_legal(session, mid), "turn start must not free a second placement in this round"
    condition = _round_use(session, mid)
    assert condition is not None and condition.data["round"] == round_before

    # Independently recheck denial on the committed save. The synthetic boundary
    # above is not replay evidence; the original table transaction is.
    saved = _reload(combat, mid, tmp_path)
    assert saved.engine.state.round_number == round_before
    assert not _placement_legal(saved, mid)


def test_abandoning_the_placement_menu_leaves_usage_unspent_after_reload(tmp_path):
    """Reading a candidate and leaving the menu submits no action or decline."""
    combat, table, mid = _build(tmp_path)
    _advance(table, mid, ME)

    sequence_before = table.state(mid)["last_sequence"]
    # The player reads the placement candidate and leaves without submitting it.
    for _ in range(2):
        _candidate(table, mid, "Place Smoke Trace")
    assert table.state(mid)["last_sequence"] == sequence_before
    assert _round_use(combat, mid) is None, "menu abandonment must not consume the round"
    assert _placement_legal(combat, mid), "backing out spent nothing, so it is still offered"

    saved = _reload(combat, mid, tmp_path)
    assert _round_use(saved, mid) is None
    assert _placement_legal(saved, mid)


def test_same_round_turn_start_preserves_committed_usage_after_reload(tmp_path):
    """Supported fallback: another creature starts its turn in the same round.

    Placement is only offered on the owner's active turn; this is not off-turn
    placement followed by that owner's turn. No extra turn or trigger is added
    to manufacture that unsupported acceptance sequence.
    """
    from combat import ext

    combat, table, mid = _build(tmp_path, owner_first=True)
    engine = combat._load_session(mid).engine
    assert engine.state.current_actor_id == ME
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name == "Place Smoke Trace")
    action = engine.action_catalog[candidate.source_definition_id]
    round_now = engine.state.round_number
    _use(table, mid, "Place Smoke Trace", target=FOE)
    assert not _placement_legal(combat, mid)

    _advance(table, mid, FOE)
    engine = combat._load_session(mid).engine
    assert engine.state.round_number == round_now
    assert engine.state.current_actor_id == FOE
    assert any(e.event_type == "TURN_STARTED" and e.actor_id == FOE
               and e.payload["round"] == round_now for e in engine.events)
    assert _round_use(combat, mid).data["round"] == round_now
    # The active menu belongs to the foe now. Query the documented admission
    # hook with the owner's actual previously offered placement instead of
    # mistaking the absence of an owner action from a foe menu for denial.
    assert False in ext.run("candidate_allowed", engine, engine.state.actors[ME], candidate, action)

    reloaded = _reload(combat, mid, tmp_path)
    assert reloaded.engine.state.round_number == round_now
    assert reloaded.engine.state.current_actor_id == FOE
    assert _round_use(reloaded, mid).data["round"] == round_now
    assert False in ext.run("candidate_allowed", reloaded.engine,
                            reloaded.engine.state.actors[ME], candidate, action)


def test_menu_abandonment_leaves_placement_unspent_after_reload(tmp_path):
    """Reading an offered candidate without submitting it leaves usage unspent.

    This is menu abandonment, not submitted-then-declined cancellation. The
    native single-target Smoke placement resolves immediately on submission.
    """
    combat, table, mid = _build(tmp_path)
    _advance(table, mid, ME)

    # Read the offered candidate but never submit an action.
    for _ in range(2):
        _candidate(table, mid, "Place Smoke Trace")
    assert table.state(mid)["pending_action"] is None
    assert _round_use(combat, mid) is None
    assert _placement_legal(combat, mid)

    reloaded = _reload(combat, mid, tmp_path)
    assert _round_use(reloaded, mid) is None
    assert _placement_legal(reloaded, mid)
    cold_combat = CombatService(ROOT, tmp_path)
    cold_table = TabletopService(cold_combat, tmp_path)
    assert cold_table.state(mid)["pending_action"] is None
    _candidate(cold_table, mid, "Place Smoke Trace")

    # Contrast: carrying the same placement through to resolution does spend it.
    res = _use(cold_table, mid, "Place Smoke Trace", target=FOE)
    assert res["status"] == "COMMITTED"
    assert cold_table.state(mid)["pending_action"] is None
    assert _round_use(cold_combat, mid) is not None
    assert not _placement_legal(cold_combat, mid)
    committed = _reload(cold_combat, mid, tmp_path)
    assert _round_use(committed, mid) is not None
    assert not _placement_legal(committed, mid)


def test_a_menu_preview_does_not_consume_the_round(tmp_path):
    """Merely reading the menu (preview) leaves the placement unspent."""
    combat, table, mid = _build(tmp_path)
    _advance(table, mid, ME)

    for _ in range(3):
        menu = table.state(mid)["menu"]
        assert any("Place Smoke Trace" in option["label"]
                   for group in menu["actions"] for option in group.get("options", []))

    assert _round_use(combat, mid) is None
    assert _placement_legal(combat, mid)


def test_the_trace_printed_lifetime_is_separate_and_expires_through_the_next_turn(tmp_path):
    """The Smoke Trace mark keeps its own printed lifetime -- until the end of the
    owner's next turn -- independently of the placement's round clock."""
    combat, table, mid = _build(tmp_path)
    _advance(table, mid, ME)
    _use(table, mid, "Place Smoke Trace", target=FOE)

    engine = combat._load_session(mid).engine
    assert bears_mark(engine.state.actors[FOE], ME, "Smoke Trace")   # placed, round 1

    _advance(table, mid, FOE)   # round 2 begins; the trace outlives the round clock
    _advance(table, mid, ME)    # the owner's next turn, still round 2
    engine = combat._load_session(mid).engine
    assert engine.state.round_number == 2
    assert bears_mark(engine.state.actors[FOE], ME, "Smoke Trace"), \
        "the trace lasts until the end of the owner's next turn"

    _advance(table, mid, FOE)   # the owner's next turn has now ended
    engine = combat._load_session(mid).engine
    assert not bears_mark(engine.state.actors[FOE], ME, "Smoke Trace"), \
        "the printed trace expires at the end of the owner's next turn"
