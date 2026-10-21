"""STALEMATE1: the built-in AI must end its turn after one free setting declaration.

Calibration 2026-10-21 (main 6475f0cb): Mei Jiang vs Hua Muruo was 0 damage on all ten seeds and never reached a
terminal result in 900 decisions, all in round 1. The cause is not the fight: "Set current workpiece" is a
``setting_only`` action with no economy, so the engine offers it again immediately, and its candidate keeps
scoring above End turn (a primary-combatant target priority on its self target). The AI alternated "a carried
item" and "clear item selection" forever.

This test drives the same AI-vs-AI loop the Tricky bench uses (real CombatService match, native decisions) with a
synthetic Blacksmith sheet, so it needs no owner data or Git history. It fails without the restraint in
combat/ext/ai_restraint.py (120 decisions, round 1, no terminal result) and passes with it.
"""
from combat import menu_rank
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_context import build_decision_context, build_reaction_context
from combat.gate4_controller import LocalDeterministicController
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.ai_tiers_native_support import fight

TALENTS = [
    "tianxia.talent.blacksmith.quench_against_the_grain",
    "tianxia.talent.blacksmith.steady_hammer_breathing",
]
SETTING = "Set current workpiece"
FLAG = "ai_restraint_setting_taken"  # per creature per turn; see combat/ext/ai_restraint.py


def drive(combat, session, *, max_steps=120):
    engine = session.engine
    controller = LocalDeterministicController()

    def reaction(request):
        policy, _ = combat.policies.for_actor(request["reactor_id"])
        choice = controller.choose_reaction(build_reaction_context(engine, policy, request))
        return choice.decision, choice.record.model_dump(mode="json")

    engine.set_reaction_provider(reaction)
    choices, steps = [], 0
    while engine.state.terminal_result is None and steps < max_steps:
        policy, _ = combat.policies.for_actor(engine.state.current_actor_id)
        context = build_decision_context(engine, policy, for_ai=True)
        choice = controller.choose_primary_action(context)
        picked = next(c for c in context.legal_candidates if c.candidate_id == choice.intent.candidate_id)
        choices.append((engine.state.round_number, engine.state.current_actor_id, picked.display_name))
        engine.execute_intent(choice.intent)
        steps += 1
    return steps, choices


def test_ai_ends_its_turn_after_one_free_setting(tmp_path):
    combat, _mid, session = fight(tmp_path, talents=TALENTS, maximum_rounds=3,
                                  arena_id="battlefield:factory_pillar_arena")
    steps, choices = drive(combat, session)
    engine = session.engine
    assert engine.state.terminal_result is not None, (
        f"no terminal result after {steps} decisions, still round {engine.state.round_number}: "
        f"{[name for _, _, name in choices[-6:]]}")
    assert steps < 60, f"a capped 3-round duel took {steps} decisions"
    settings = [(round_number, actor) for round_number, actor, name in choices if name.startswith(SETTING)]
    turns = {(round_number, actor) for round_number, actor, _ in choices}
    assert len(settings) <= len(turns), f"more than one free setting per turn: {settings}"
    assert settings, "the AI never made a free setting declaration; this test no longer covers the loop"


def test_the_restraint_is_ai_only(tmp_path):
    """After the AI makes its declaration, only its own menu loses the rest of the settings (owner rule 15: a
    person's menu keeps every choice)."""
    combat, _mid, session = fight(tmp_path, talents=TALENTS, maximum_rounds=3,
                                  arena_id="battlefield:factory_pillar_arena")
    engine = session.engine
    actor_id = engine.state.current_actor_id
    policy, _ = combat.policies.for_actor(actor_id)
    context = build_decision_context(engine, policy, for_ai=True)
    setting = next(c for c in context.legal_candidates if c.display_name.startswith(SETTING))
    engine.execute_intent(ActionIntent(
        intent_id="test:free-setting", decision_id=setting.decision_id, candidate_id=setting.candidate_id,
        state_version=setting.state_version, actor_id=setting.actor_id, target_ids=setting.target_ids,
        destination=setting.destination))
    assert engine.state.current_actor_id == actor_id, "the free setting must not end the turn"
    ai_menu = [c.display_name for c in build_decision_context(engine, policy, for_ai=True).legal_candidates]
    person_menu = [c.display_name for c in build_decision_context(engine, policy, for_ai=False).legal_candidates]
    assert not any(name.startswith(SETTING) for name in ai_menu), f"AI menu kept the settings: {ai_menu}"
    assert any(name.startswith(SETTING) for name in person_menu), f"person's menu lost the settings: {person_menu}"


def test_ranking_a_persons_menu_keeps_its_setting_rows_scored(tmp_path):
    """menu_rank scores a person's menu from CombatService.menu_ranking_context. That context is the AI's
    projection, so the built-in AI's restraint used to run inside it: once the person had declared one
    setting, their own remaining setting rows vanished from the ranking context, got no score, and sorted
    below End turn (review 2026-10-21, Fix 1). The restraint applies to an AI decision only."""
    combat, _mid, session = fight(tmp_path, talents=TALENTS, maximum_rounds=3,
                                  arena_id="battlefield:factory_pillar_arena")
    engine = session.engine
    actor_id = engine.state.current_actor_id
    policy, _ = combat.policies.for_actor(actor_id)
    setting = next(c for c in build_decision_context(engine, policy, for_ai=False).legal_candidates
                   if c.display_name == f"{SETTING}: a carried item")
    engine.execute_intent(ActionIntent(
        intent_id="test:free-setting-rank", decision_id=setting.decision_id, candidate_id=setting.candidate_id,
        state_version=setting.state_version, actor_id=setting.actor_id, target_ids=setting.target_ids,
        destination=setting.destination))
    assert engine.state.current_actor_id == actor_id, "the free setting must not end the turn"
    person = build_decision_context(engine, policy, for_ai=False)
    remaining = {c.candidate_id for c in person.legal_candidates if c.display_name.startswith(SETTING)}
    end_turn = next(c for c in person.legal_candidates if c.kind == "END_TURN")
    assert remaining, "the person's own menu lost the rest of its settings"
    ranking = combat.menu_ranking_context(session)
    assert remaining <= {c.candidate_id for c in ranking.legal_candidates}, (
        "the ranking context for a person's menu dropped their own setting rows")
    known = {a.entity_id for a in ranking.actors} | {actor_id}
    scores = menu_rank.native_scores(combat, engine, known, session=session,
                                     candidate_ids=remaining | {end_turn.candidate_id})
    assert remaining | {end_turn.candidate_id} <= set(scores), (
        f"unscored rows: {remaining | {end_turn.candidate_id} - set(scores)}")
    assert min(scores[cid] for cid in remaining) > scores[end_turn.candidate_id], (
        "the person's setting rows rank below End turn")


def test_free_setting_flag_survives_a_table_commit_and_clears_next_turn(tmp_path):
    """The restraint's per-turn flag is saved fight state (review 2026-10-21, finding 4).

    ``ai_restraint_setting_taken`` is an int in ``actor.turn_flags``, so it must travel with the saved fight: a table
    commit plus a cold reload keep it for the rest of that creature's turn, and the engine's turn reset
    (combat/gate2_engine.py, which keeps only ``_round_`` and ``once_per_round:`` keys) drops it at the next turn. The
    test declares through the table's own commit path (``TabletopService.act``) and reads every later state back from
    disk, so a flag that only lived in memory would fail here.
    """
    combat, mid, _session = fight(tmp_path, talents=TALENTS, maximum_rounds=4)
    table = TabletopService(combat, tmp_path)
    menu = table.state(mid)["menu"]
    actor_id = menu["actor_id"]
    setting = next(option["candidate_id"] for group in menu["actions"] if SETTING in group["label"]
                   for option in group["options"]
                   if (option.get("label") or "").startswith(f"{SETTING}: a carried item"))
    committed = table.act(mid, setting, menu["decision_id"], menu["state_version"], 0, [])
    assert committed["status"] == "COMMITTED", committed
    reloaded = CombatService(combat.source_root, combat.userdata_root)._load_session(mid).engine.state
    assert reloaded.current_actor_id == actor_id, "the free setting must not end the turn"
    assert reloaded.actors[actor_id].turn_flags.get(FLAG) == 1, (
        "the per-turn restraint flag did not survive the table commit and cold reload")
    for _ in range(8):
        menu = table.state(mid)["menu"]
        table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], 0, [])
        engine = combat._load_session(mid).engine
        if engine.state.terminal_result is not None or engine.state.current_actor_id == actor_id:
            break
    engine = CombatService(combat.source_root, combat.userdata_root)._load_session(mid).engine
    assert engine.state.terminal_result is None, "the fixture ended before the owner's next turn"
    assert engine.state.current_actor_id == actor_id, "the round did not come back to the owner"
    assert FLAG not in engine.state.actors[actor_id].turn_flags, (
        "the restraint flag outlived its turn; the creature would never make another free setting")
