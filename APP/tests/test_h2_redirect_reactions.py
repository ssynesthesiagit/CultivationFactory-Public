"""Automation lane H2: reactions that re-aim an attack before it is rolled (combat/ext/redirect_reactions.py, on the lock-round-2
``retarget_attack`` hook through combat/ext/redirection.py).

Real compiled Factory fighters: the owner (ME), a foe (FOE) and the foe's ally (FOE2) standing beside it.
"""

from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events
from combat.gate4_engine import Gate4ControllerEngine
from tests.test_auto_docket import ME, ROOT, WEAPON, _sheet
from tests.test_auto_tabik import _turn
from tests.test_carry import KIT
from tests.test_zones import SHEET

FOE, FOE2 = "actor:factory.h2foe", "actor:factory.h2foe2"


def _three(talents, spheres, *, me_at=(3, 6), foe_at=(4, 6), foe2_at=(5, 6), seed="H2-REDIRECT", kit=None):
    foe_sheet = {**SHEET, "equipment": [{"starting_kit": KIT}], "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []}}
    mine = _sheet(list(talents), list(spheres), **WEAPON)
    mine["equipment"] = [{"starting_kit": kit or KIT}]
    bundles = (compile_character(mine, actor_id=ME),
               compile_character(foe_sheet, actor_id=FOE), compile_character(foe_sheet, actor_id=FOE2))
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=bundles,
                                   roster_setup={"primary_actor_ids": [ME, FOE, FOE2], "team_by_actor": {ME: "team:a", FOE: "team:b", FOE2: "team:b"},
                                                 "starting_positions": {ME: {"x": me_at[0], "y": me_at[1]}, FOE: {"x": foe_at[0], "y": foe_at[1]},
                                                                        FOE2: {"x": foe2_at[0], "y": foe2_at[1]}}})
    _turn(engine, ME)
    return engine


def _table(engine, *, choice=None, choice_source="", decline_mine=False, uses=()):
    """The table: the foes take their Opportunity Attacks; ME answers ``choice_source`` choices with ``choice`` (or declines)."""
    asked = []

    def provider(request):
        asked.append(request)
        checkpoint, source = request["checkpoint"], request["reaction_source_id"]

        def answer(selection, options=()):
            return ReactionDecision(checkpoint=checkpoint, reactor_id=request["reactor_id"], reaction_source_id=source,
                                    selection=selection, option_ids=tuple(options)), None

        if request["reactor_id"] != ME:
            return answer("USE", request.get("legal_option_ids") or ())
        if choice_source and choice_source in source and not decline_mine:
            return answer("USE", (choice,) if choice else request.get("legal_option_ids") or ())
        if source in uses:
            return answer("USE", request.get("legal_option_ids") or ())
        return answer("DECLINE")

    engine.set_reaction_provider(provider)
    return asked


def _intent(engine, candidate):
    return ActionIntent(intent_id=f"h2r:{engine.state.event_sequence}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                        state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=candidate.target_ids,
                        option_ids=candidate.option_ids, destination=candidate.destination)


def _step_to(engine, x, y):
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == ME and c.destination is not None
                     and (c.destination.x, c.destination.y) == (x, y) and c.kind == "MOVE")
    before = len(engine.events)
    engine.execute_intent(_intent(engine, candidate))
    return engine.events[before:]


def _set_bonus(engine, owner, bonus):
    for action in engine.action_catalog.values():
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id == owner and typed.get("numbers") is not None:
            typed["numbers"] = {**typed["numbers"], "attack_bonus": bonus}
    for rows in (getattr(engine, "typed_reaction_rows", {}) or {}).get(owner, []), (getattr(engine, "typed_passive_rows", {}) or {}).get(owner, []):
        for row in rows:
            if isinstance(row.get("numbers"), dict):
                row["numbers"]["attack_bonus"] = bonus


def _rolled(events, attacker, target):
    return [e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == attacker and target in (e.target_ids or ())]


def _compiled_opened(events):
    return [e for e in events if e.event_type == "REACTION_WINDOW_OPENED" and e.source_definition_id == "TAL_SCOUNDREL_MISDIRECTED_ATTACK"]


# ------------------------------------------------------------------------------------------------ Misdirected Attack
MISDIRECTED = (["TAL_SCOUNDREL_MISDIRECTED_ATTACK"], ["tianxia.sphere.scoundrel"])


def test_misdirected_attack_turns_the_opportunity_attack_on_the_attackers_ally():
    engine = _three(*MISDIRECTED)
    me = engine.state.actors[ME]
    asked = _table(engine, choice=FOE2, choice_source="misdirected_attack")
    _set_bonus(engine, ME, 100)  # the Dirty Trick wins
    before, start = engine.state.model_copy(deep=True), len(engine.events)
    events = _step_to(engine, 2, 6)  # out of the foe's reach: it makes an Opportunity Attack
    request = next(r for r in asked if "misdirected_attack" in r["reaction_source_id"])
    assert set(request["choice_trigger"]["labels"]) == {FOE2}  # every other legal target in the attacker's reach
    retarget = [e for e in events if e.event_type == "ATTACK_RETARGETED"]
    assert len(retarget) == 1 and retarget[0].payload["original_target_id"] == ME and retarget[0].target_ids == (FOE2,)
    assert _rolled(events, FOE, ME) == [] and len(_rolled(events, FOE, FOE2)) == 1
    assert me.reaction_available is False
    assert len([e for e in events if e.event_type == "REACTION_RESOLVED"
                and e.source_definition_id == "TAL_SCOUNDREL_MISDIRECTED_ATTACK"
                and e.payload.get("success") is True]) == 1
    replay = Gate3EventReducer().apply_events(before, enrich_committed_events(engine.events[start:], post_engine=engine))
    assert replay.actors[FOE2].current_hp == engine.state.actors[FOE2].current_hp and replay.actors[ME].reaction_available is False


def test_a_failed_dirty_trick_spends_the_reaction_and_the_attack_stays_on_me():
    engine = _three(*MISDIRECTED)
    _table(engine, choice=FOE2, choice_source="misdirected_attack")
    _set_bonus(engine, ME, -100)
    events = _step_to(engine, 2, 6)
    assert not [e for e in events if e.event_type == "ATTACK_RETARGETED"]
    assert len(_rolled(events, FOE, ME)) == 1 and engine.state.actors[ME].reaction_available is False


def test_declining_or_having_no_other_target_leaves_the_compiled_reaction_alone():
    engine = _three(*MISDIRECTED)
    _table(engine, choice_source="misdirected_attack", decline_mine=True)
    events = _step_to(engine, 2, 6)
    assert not [e for e in events if e.event_type == "ATTACK_RETARGETED"] and len(_rolled(events, FOE, ME)) == 1
    assert not _compiled_opened(events)  # with somewhere to send it, declining the redirect declines the Reaction

    engine = _three(*MISDIRECTED, foe2_at=(9, 9))  # nobody else in the foe's reach
    asked = _table(engine, choice_source="misdirected_attack")
    events = _step_to(engine, 2, 6)
    assert not [r for r in asked if "choice:needle.misdirected_attack" == r["reaction_source_id"]]
    assert not [e for e in events if e.event_type == "ATTACK_RETARGETED"]
    assert _compiled_opened(events)  # nowhere to send it: the compiled reaction (negate on a success) answers


def test_a_fighter_without_the_talent_is_not_redirected():
    engine = _three(["TAL_SCOUNDREL_DIRTY_TRICK"], ["tianxia.sphere.scoundrel"])
    _table(engine, choice=FOE2, choice_source="misdirected_attack")
    events = _step_to(engine, 2, 6)
    assert not [e for e in events if e.event_type == "ATTACK_RETARGETED"] and len(_rolled(events, FOE, ME)) == 1


# ------------------------------------------------------------------------------------------------ Harmonious Body (Jujutsu CL14)
HARMONIOUS = "tianxia.subpath.body.jujutsu.feature.harmonious_body"
STAMINA = "resource:core.stamina"


def _jujutsu(**at):
    engine = _three([HARMONIOUS], [], **at)
    me = engine.state.actors[ME]
    me.resources[STAMINA] = 6
    me.resource_maximums[STAMINA] = max(6, me.resource_maximums.get(STAMINA, 0))
    return engine


def _dc(engine, dc):
    for row in (getattr(engine, "typed_reaction_rows", {}) or {}).get(ME, []):
        if row.get("feature_id") == HARMONIOUS:
            row["numbers"]["save_dc"] = dc


def _foe_swings(engine, bonus=5):
    _turn(engine, FOE)
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == FOE and ".weapon." in c.source_definition_id
                     and ME in (c.target_ids or ()) and not engine.action_catalog[c.source_definition_id].parameters["typed"].get("range_ft"))
    typed = engine.action_catalog[candidate.source_definition_id].parameters["typed"]
    next(row for row in typed["effects"] if row.get("type") == "attack")["count"] = 1
    typed["numbers"] = {**typed["numbers"], "attack_bonus": bonus}
    before = len(engine.events)
    engine.execute_intent(_intent(engine, candidate))
    return engine.events[before:]


def test_harmonious_body_on_a_failed_save_sends_the_attack_to_the_attackers_ally():
    engine = _jujutsu()
    me = engine.state.actors[ME]
    asked = _table(engine, choice=f"redirect:{FOE2}", choice_source="harmonious_body")
    _dc(engine, 100)  # the Strength save fails
    before, start = engine.state.model_copy(deep=True), len(engine.events)
    events = _foe_swings(engine)
    labels = next(r for r in asked if "harmonious_body" in r["reaction_source_id"])["choice_trigger"]["labels"]
    assert set(labels) == {f"redirect:{FOE2}", "prone", "move"}
    assert [e for e in events if e.event_type == "SAVE_ROLLED"]  # the attacker's Strength save, before the attack roll
    retarget = [e for e in events if e.event_type == "ATTACK_RETARGETED"]
    assert len(retarget) == 1 and retarget[0].target_ids == (FOE2,) and retarget[0].payload["original_target_id"] == ME
    assert _rolled(events, FOE, ME) == [] and len(_rolled(events, FOE, FOE2)) == 1
    assert me.resources[STAMINA] == 3 and me.reaction_available is False
    assert not [e for e in events if e.event_type == "REACTION_WINDOW_OPENED" and e.source_definition_id == HARMONIOUS][1:]  # opened once, by the provider
    replay = Gate3EventReducer().apply_events(before, enrich_committed_events(engine.events[start:], post_engine=engine))
    assert replay.actors[ME].resources[STAMINA] == 3 and replay.actors[FOE2].current_hp == engine.state.actors[FOE2].current_hp


def test_knock_prone_makes_the_attack_miss_without_a_roll():
    engine = _jujutsu()
    _table(engine, choice="prone", choice_source="harmonious_body")
    _dc(engine, 100)
    events = _foe_swings(engine)
    foe = engine.state.actors[FOE]
    assert any(c.condition_id.endswith("prone") for c in foe.conditions.values())
    assert _rolled(events, FOE, ME) == [] and not [e for e in events if e.event_type == "ATTACK_RETARGETED"]


def test_a_successful_save_resolves_the_attack_with_the_damage_reduction_parked_for_that_hit_only():
    engine = _jujutsu()
    me = engine.state.actors[ME]
    _table(engine, choice="prone", choice_source="harmonious_body")
    _dc(engine, -100)  # the save succeeds
    events = _foe_swings(engine, bonus=100)  # and the attack hits
    assert len(_rolled(events, FOE, ME)) == 1 and "if the attack hits, its damage is reduced by" in " ".join(
        str((e.payload or {}).get("rider")) for e in events if e.event_type == "GM_RIDER")
    assert f"typed_hit_reduction:{FOE}" not in me.turn_flags  # taken by the hit's damage

    engine = _jujutsu()
    me = engine.state.actors[ME]
    _table(engine, choice="prone", choice_source="harmonious_body")
    _dc(engine, -100)
    _foe_swings(engine, bonus=-100)  # a miss: nothing stays parked for its next hit
    assert f"typed_hit_reduction:{FOE}" not in me.turn_flags and f"harmonious_body_parked:{FOE}" not in me.turn_flags


def test_declining_harmonious_body_keeps_the_stamina_and_the_compiled_row_stays_silent():
    engine = _jujutsu()
    me = engine.state.actors[ME]
    _table(engine, choice_source="harmonious_body", decline_mine=True)
    events = _foe_swings(engine)
    assert me.resources[STAMINA] == 6 and me.reaction_available is True and len(_rolled(events, FOE, ME)) == 1
    assert not [e for e in events if e.event_type == "REACTION_WINDOW_OPENED" and e.source_definition_id == HARMONIOUS]


# ------------------------------------------------------------------------------------------------ the built-in AI
def _controller(engine):
    from combat.gate4_context import build_reaction_context
    from combat.gate4_controller import LocalDeterministicController
    from combat.gate4_policy import PolicyLibrary

    policy = PolicyLibrary(ROOT).fallback()
    engine.set_reaction_provider(lambda request: (LocalDeterministicController().choose_reaction(build_reaction_context(engine, policy, request)).decision, None))


def test_the_built_in_ai_turns_both_on_the_attackers_own_side():
    engine = _three(*MISDIRECTED)
    _controller(engine)
    _set_bonus(engine, ME, 100)
    events = _step_to(engine, 2, 6)
    assert [e.target_ids for e in events if e.event_type == "ATTACK_RETARGETED"] == [(FOE2,)]

    engine = _jujutsu()
    _controller(engine)
    _dc(engine, 100)
    events = _foe_swings(engine)
    assert [e.target_ids for e in events if e.event_type == "ATTACK_RETARGETED"] == [(FOE2,)]


def test_with_nobody_else_in_reach_the_ai_knocks_the_attacker_prone():
    engine = _jujutsu(foe2_at=(9, 9))
    _controller(engine)
    _dc(engine, 100)
    events = _foe_swings(engine)
    assert _rolled(events, FOE, ME) == [] and any(c.condition_id.endswith("prone") for c in engine.state.actors[FOE].conditions.values())


# ------------------------------------------------------------------------------------------------ Redirecting Shield
SHIELD = (["SHIELD_BASE_ACTIVE_DEFENSE", "TAL_SHIELD_REDIRECTING_SHIELD"], ["tianxia.sphere.shield"])
FOCUS = "resource:core.martial_focus"


def _shielded(talents=SHIELD[0], **at):
    # Active Defense prints "Requirement: Wielding a Shield" (SHIELD_BASE_ACTIVE_DEFENSE) and the table now enforces
    # it (combat/ext/shield_wielding.py), so the Shield fighter under test carries one. AUTO55 2026-10-05.
    kit = {**KIT, "items": [*KIT["items"], {"item_id": "tianxia.mortal.armor.shield", "name": "Shield", "quantity": 1}]}
    engine = _three(talents, SHIELD[1], kit=kit, **at)
    me, foe2 = engine.state.actors[ME], engine.state.actors[FOE2]
    me.armor_class, foe2.armor_class = 100, -50  # the swing misses me and would hit anything else
    me.resources[FOCUS] = 1
    return engine


def test_redirecting_shield_sends_the_missed_swing_at_the_attackers_ally_for_martial_focus():
    engine = _shielded()
    me, foe2 = engine.state.actors[ME], engine.state.actors[FOE2]
    asked = _table(engine, choice=FOE2, choice_source="redirecting_shield", uses=("SHIELD_BASE_ACTIVE_DEFENSE",))
    hp = foe2.current_hp
    before, start = engine.state.model_copy(deep=True), len(engine.events)
    events = _foe_swings(engine)
    assert any(e.event_type == "REACTION_WINDOW_OPENED" and e.source_definition_id == "SHIELD_BASE_ACTIVE_DEFENSE" for e in events)
    assert any("redirecting_shield" in r["reaction_source_id"] for r in asked)
    triggered = [e for e in events if e.event_type == "PASSIVE_TRIGGERED" and e.source_definition_id == "passive:TAL_SHIELD_REDIRECTING_SHIELD"]
    assert len(triggered) == 1 and triggered[0].payload["hit"] is True and triggered[0].target_ids == (FOE, FOE2)
    assert me.resources[FOCUS] == 0 and foe2.current_hp < hp
    replay = Gate3EventReducer().apply_events(before, enrich_committed_events(engine.events[start:], post_engine=engine))
    assert replay.actors[FOE2].current_hp == foe2.current_hp and replay.actors[ME].resources[FOCUS] == 0


def test_without_martial_focus_or_active_defense_nothing_is_redirected():
    engine = _shielded()
    engine.state.actors[ME].resources[FOCUS] = 0
    _table(engine, choice=FOE2, choice_source="redirecting_shield", uses=("SHIELD_BASE_ACTIVE_DEFENSE",))
    events = _foe_swings(engine)
    assert not [e for e in events if e.event_type == "PASSIVE_TRIGGERED" and "REDIRECTING" in e.source_definition_id]

    engine = _shielded(["TAL_SHIELD_REDIRECTING_SHIELD"])  # no Active Defense to benefit from
    _table(engine, choice=FOE2, choice_source="redirecting_shield")
    events = _foe_swings(engine)
    assert not [e for e in events if e.event_type == "PASSIVE_TRIGGERED" and "REDIRECTING" in e.source_definition_id]


def test_the_built_in_ai_redirects_a_missed_swing_only_where_it_would_hit():
    engine = _shielded()
    _controller(engine)
    events = _foe_swings(engine)
    triggered = [e for e in events if e.event_type == "PASSIVE_TRIGGERED" and e.source_definition_id == "passive:TAL_SHIELD_REDIRECTING_SHIELD"]
    assert [e.target_ids for e in triggered] == [(FOE, FOE2)] and triggered[0].payload["hit"] is True

    engine = _shielded()
    engine.state.actors[FOE2].armor_class = 100  # nothing the roll would hit: keep the Martial Focus
    _controller(engine)
    events = _foe_swings(engine)
    assert not [e for e in events if e.event_type == "PASSIVE_TRIGGERED" and "REDIRECTING" in e.source_definition_id]
    assert engine.state.actors[ME].resources[FOCUS] == 1
