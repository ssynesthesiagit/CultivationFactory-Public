"""Automation lane H2: interceptions and preparations on the lock-round-2 prepared-action hooks.

Intercepting Strike (Retribution Guard) is one of Counterstrike's choices when prepared (combat/ext/counterstrike.py) and, for Martial
Focus, its own compiled Reaction (Reactive Interception); Patient Breath gives Martial Focus back for a preparation that expires
unused. Each scenario is a real compiled Retribution fighter against a real compiled Factory fighter whose weapon attack is typed.
"""

from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent, ReactionDecision
from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events
from combat.gate4_engine import Gate4ControllerEngine
from combat.prepared_actions import CONDITION
from tests.test_auto_docket import ME, ROOT, WEAPON, _sheet
from tests.test_auto_tabik import _turn
from tests.test_carry import KIT
from tests.test_zones import SHEET

FOE = "actor:factory.h2foe"
FOCUS = "resource:core.martial_focus"
RETRIBUTION = ["RETRIBUTION_BASE_COUNTERSTRIKE", "TAL_RETRIBUTION_INTERCEPTING_STRIKE", "TAL_RETRIBUTION_PATIENT_BREATH"]


def _duel(talents=RETRIBUTION, spheres=("tianxia.sphere.retribution",), *, me_at=(3, 6), foe_at=(4, 6), seed="H2-INTERCEPT"):
    mine = compile_character(_sheet(list(talents), list(spheres), **WEAPON), actor_id=ME)
    theirs = compile_character({**SHEET, "equipment": [{"starting_kit": KIT}],
                                "spheres_and_talents": {"sphere_record_ids": [], "learned_talent_record_ids": []}}, actor_id=FOE)
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=(mine, theirs),
                                   roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                                                 "starting_positions": {ME: {"x": me_at[0], "y": me_at[1]}, FOE: {"x": foe_at[0], "y": foe_at[1]}}})
    _turn(engine, ME)
    return engine


def _answer(engine, label_has=None, *, use="USE", reactions=()):
    """The table: the declaration's choice (the option whose label contains ``label_has``), Use/Decline on the Ready prompt, and
    USE for the named generic reactions."""
    asked = []

    def provider(request):
        asked.append(request)
        checkpoint, source = request["checkpoint"], request["reaction_source_id"]
        answer = lambda selection, options=(): (ReactionDecision(checkpoint=checkpoint, reactor_id=request["reactor_id"],  # noqa: E731
                                                                 reaction_source_id=source, selection=selection, option_ids=tuple(options)), None)
        if checkpoint.startswith("READY:"):
            return answer(use, request["legal_option_ids"] if use == "USE" else ())
        labels = (request.get("choice_trigger") or {}).get("labels") or {}
        if label_has is not None and labels:
            picked = [key for key, label in labels.items() if label_has in label]
            if picked:
                return answer("USE", picked[:1])
        if any(name in source for name in reactions):
            return answer("USE", request.get("legal_option_ids") or ())
        return answer("DECLINE")

    engine.set_reaction_provider(provider)
    return asked


def _request(engine, candidate):
    return ActionIntent(intent_id=f"h2i:{engine.state.event_sequence}", decision_id=candidate.decision_id, candidate_id=candidate.candidate_id,
                        state_version=candidate.state_version, actor_id=candidate.actor_id, target_ids=candidate.target_ids,
                        option_ids=candidate.option_ids, destination=candidate.destination)


def _use(engine, name):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    engine.execute_intent(_request(engine, candidate))


def _foe_strikes(engine, *, ranged=False, bonus=None):
    """The foe's typed weapon attack on ME (one attack), optionally with a fixed attack bonus; returns the new events."""
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == FOE and ".weapon." in c.source_definition_id
                     and ME in (c.target_ids or ()) and bool(engine.action_catalog[c.source_definition_id].parameters["typed"].get("range_ft")) == ranged)
    typed = engine.action_catalog[candidate.source_definition_id].parameters["typed"]
    next(row for row in typed["effects"] if row.get("type") == "attack")["count"] = 1
    if bonus is not None:
        typed["numbers"] = {**typed["numbers"], "attack_bonus": bonus}
    before = len(engine.events)
    engine.execute_intent(_request(engine, candidate))
    return engine.events[before:]


def _my_weapon_bonus(engine, bonus):
    for action in engine.action_catalog.values():
        typed = (action.parameters or {}).get("typed") or {}
        if action.owner_id == ME and typed.get("weapon"):
            typed["numbers"] = {**(typed.get("numbers") or {}), "attack_bonus": bonus}


def _rolled_at_me(events):
    return [e for e in events if e.event_type == "ATTACK_ROLLED" and e.actor_id == FOE and ME in (e.target_ids or ())]


def _riders(events):
    return " ".join(str((e.payload or {}).get("rider") or "") for e in events if e.event_type == "GM_RIDER")


def _replayed(engine, before, start):
    return Gate3EventReducer().apply_events(before, enrich_committed_events(engine.events[start:], post_engine=engine))


# ------------------------------------------------------------------------------------------------ Intercepting Strike, prepared
def test_counterstrike_offers_intercepting_strike_and_a_winning_roll_negates_the_foes_melee_attack():
    engine = _duel()
    me = engine.state.actors[ME]
    asked = _answer(engine, "Intercepting Strike (")
    _use(engine, "Counterstrike")
    labels = next(r for r in asked if r["reaction_source_id"] == "choice:needle.counterstrike")["choice_trigger"]["labels"]
    assert any(label.startswith("Intercepting Strike (") and "a melee weapon attack is made within your reach" in label for label in labels.values())
    assert any("a physical projectile targets a creature within your reach" in label for label in labels.values())
    held = next(c for c in me.conditions.values() if c.condition_id == CONDITION)
    assert held.data["data"]["intercept"] is True and held.data["data"]["trigger"] == "melee_in_reach"
    focus = me.resources.get(FOCUS, 0)
    _my_weapon_bonus(engine, 100)  # the interception roll always equals or beats the foe's
    before, start = engine.state.model_copy(deep=True), len(engine.events)
    _turn(engine, FOE)
    events = _foe_strikes(engine, bonus=5)
    assert _rolled_at_me(events) == []  # negated: no attack roll against me
    assert "Intercepting Strike: the attack on" in _riders(events) and "is negated" in _riders(events)
    assert me.reaction_available is False and me.resources.get(FOCUS, 0) == focus  # prepared: the Reaction, no Martial Focus
    assert any(c.condition_id == CONDITION for c in me.conditions.values())  # it stands until my next turn (one per round)
    replay = _replayed(engine, before, start)
    assert replay.actors[ME].reaction_available is False and replay.actors[FOE].current_hp == engine.state.actors[FOE].current_hp


def test_a_losing_interception_roll_leaves_the_attack_to_be_rolled():
    engine = _duel()
    _answer(engine, "Intercepting Strike (")
    _use(engine, "Counterstrike")
    _my_weapon_bonus(engine, -100)
    _turn(engine, FOE)
    events = _foe_strikes(engine, bonus=5)
    assert len(_rolled_at_me(events)) == 1
    assert "is not negated" in _riders(events)
    assert engine.state.actors[ME].reaction_available is False


def test_the_projectile_interception_ignores_melee_attacks_and_the_melee_one_ignores_arrows():
    engine = _duel(foe_at=(8, 6))
    _answer(engine, "when a physical projectile targets a creature within your reach")
    _use(engine, "Counterstrike")
    _my_weapon_bonus(engine, 100)
    _turn(engine, FOE)
    events = _foe_strikes(engine, ranged=True, bonus=5)
    assert _rolled_at_me(events) == [] and "is negated" in _riders(events)

    engine = _duel(foe_at=(8, 6))
    _answer(engine, "Intercepting Strike (")  # the melee one (first listed)
    _use(engine, "Counterstrike")
    _turn(engine, FOE)
    events = _foe_strikes(engine, ranged=True, bonus=5)
    assert len(_rolled_at_me(events)) == 1 and engine.state.actors[ME].reaction_available is True


# ------------------------------------------------------------------------------------------------ Reactive Interception
def test_reactive_interception_needs_and_spends_martial_focus():
    engine = _duel(["TAL_RETRIBUTION_INTERCEPTING_STRIKE"])
    me = engine.state.actors[ME]
    _answer(engine, reactions=("INTERCEPTING_STRIKE",))
    _my_weapon_bonus(engine, 100)
    me.resources[FOCUS] = 0
    _turn(engine, FOE)
    events = _foe_strikes(engine, bonus=5)
    assert len(_rolled_at_me(events)) == 1 and me.reaction_available is True  # no Martial Focus: it cannot be used

    engine = _duel(["TAL_RETRIBUTION_INTERCEPTING_STRIKE"])
    me = engine.state.actors[ME]
    _answer(engine, reactions=("INTERCEPTING_STRIKE",))
    _my_weapon_bonus(engine, 100)
    me.resources[FOCUS] = 1
    _turn(engine, FOE)
    events = _foe_strikes(engine, bonus=5)
    assert me.resources[FOCUS] == 0 and me.reaction_available is False


# ------------------------------------------------------------------------------------------------ Patient Breath
def test_patient_breath_gives_martial_focus_back_only_for_an_unused_preparation():
    engine = _duel(foe_at=(9, 6))
    me = engine.state.actors[ME]
    _answer(engine, "when a foe starts an action that targets you")
    _use(engine, "Counterstrike")
    me.resources[FOCUS] = 0
    before, start = engine.state.model_copy(deep=True), len(engine.events)
    _turn(engine, FOE)
    _turn(engine, ME)  # expired unused
    assert me.resources[FOCUS] == 1
    assert any(e.event_type == "RESOURCE_GAINED" and e.source_definition_id == "passive:TAL_RETRIBUTION_PATIENT_BREATH" for e in engine.events)
    assert _replayed(engine, before, start).actors[ME].resources[FOCUS] == 1

    engine = _duel()
    me = engine.state.actors[ME]
    _answer(engine, "when a foe starts an action that targets you")
    _use(engine, "Counterstrike")
    _turn(engine, FOE)
    _foe_strikes(engine, bonus=5)  # the Counterstrike is made
    me.resources[FOCUS] = 0
    _turn(engine, ME)
    assert me.resources[FOCUS] == 0


def test_without_patient_breath_nothing_comes_back():
    engine = _duel(["RETRIBUTION_BASE_COUNTERSTRIKE"], foe_at=(9, 6))
    me = engine.state.actors[ME]
    _answer(engine, "when a foe starts an action that targets you")
    _use(engine, "Counterstrike")
    me.resources[FOCUS] = 0
    _turn(engine, FOE)
    _turn(engine, ME)
    assert me.resources.get(FOCUS, 0) == 0


# ------------------------------------------------------------------------------------------------ Intercepting Shot (Sniper)
SNIPER = (["TAL_SNIPER_INTERCEPTING_SHOT"], ("tianxia.sphere.sniper",))


def _ready_shot(engine):
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == ME and c.display_name.startswith("Ready: Intercepting Shot ("))
    engine.execute_intent(_request(engine, candidate))
    return candidate


def test_ready_intercepting_shot_spends_the_action_and_a_higher_roll_negates_the_arrow():
    engine = _duel(*SNIPER, foe_at=(9, 6))
    me = engine.state.actors[ME]
    asked = _answer(engine)
    candidate = _ready_shot(engine)
    assert "when a ranged attack you can see is made" in candidate.display_name
    assert me.action_available is False and any(c.condition_id == CONDITION for c in me.conditions.values())
    me.resources[FOCUS] = 1
    _my_weapon_bonus(engine, 100)
    before, start = engine.state.model_copy(deep=True), len(engine.events)
    _turn(engine, FOE)
    events = _foe_strikes(engine, ranged=True, bonus=5)
    assert [r["reaction_source_id"] for r in asked if r["checkpoint"].startswith("READY:")] == ["ready:sniper.intercepting_shot"]
    assert _rolled_at_me(events) == [] and "Intercepting Shot (" in _riders(events) and "is negated" in _riders(events)
    assert me.reaction_available is False and me.resources[FOCUS] == 1  # the Ready: the Reaction, no Martial Focus
    assert not any(c.condition_id == CONDITION for c in me.conditions.values())  # a Ready is used once
    assert _replayed(engine, before, start).actors[ME].reaction_available is False


def test_a_lower_roll_does_not_negate_and_a_melee_attack_is_not_its_trigger():
    engine = _duel(*SNIPER, foe_at=(9, 6))
    _answer(engine)
    _ready_shot(engine)
    _my_weapon_bonus(engine, -100)
    _turn(engine, FOE)
    events = _foe_strikes(engine, ranged=True, bonus=5)
    assert len(_rolled_at_me(events)) == 1 and "is not negated" in _riders(events)

    engine = _duel(*SNIPER)  # adjacent: the foe swings instead
    _answer(engine)
    _ready_shot(engine)
    _turn(engine, FOE)
    events = _foe_strikes(engine, bonus=5)
    assert len(_rolled_at_me(events)) == 1 and engine.state.actors[ME].reaction_available is True


def test_intercepting_shot_as_a_reaction_costs_martial_focus():
    engine = _duel(*SNIPER, foe_at=(9, 6))
    me = engine.state.actors[ME]
    _answer(engine, reactions=("INTERCEPTING_SHOT",))
    _my_weapon_bonus(engine, 100)
    me.resources[FOCUS] = 1
    _turn(engine, FOE)
    events = _foe_strikes(engine, ranged=True, bonus=5)
    assert _rolled_at_me(events) == [] and me.resources[FOCUS] == 0 and me.reaction_available is False

    engine = _duel(*SNIPER, foe_at=(9, 6))
    me = engine.state.actors[ME]
    _answer(engine, reactions=("INTERCEPTING_SHOT",))
    me.resources[FOCUS] = 0
    _turn(engine, FOE)
    events = _foe_strikes(engine, ranged=True, bonus=5)
    assert len(_rolled_at_me(events)) == 1 and me.reaction_available is True


def test_the_built_in_ai_does_not_ready_it_and_other_fighters_get_no_button():
    from combat import ext

    engine = _duel(*SNIPER, foe_at=(9, 6))
    ready = next(c for c in engine.legal_candidates() if c.display_name.startswith("Ready: Intercepting Shot ("))
    assert ext.any_false("ai_candidate_allowed", engine, engine.state.actors[ME], ready, None)  # the controller's AI menu drops it
    plain = _duel(["RETRIBUTION_BASE_COUNTERSTRIKE"])
    assert not any(c.display_name.startswith("Ready:") for c in plain.legal_candidates())
