"""A critical hit always lands, but it can still be softened (MMX53, hunt 80 P2 #1; MMX58 review fixes).

A natural 20 can never be turned into a miss, so a reaction whose only effect is to change the hit/miss
comparison has nothing to do against one -- and neither does a rider printed to follow the miss ("If this
causes the attack to miss, you may move 5 feet"). Anything else a reaction carries -- a damage
reduction, a condition, a retaliation -- still does its work on a critical hit and must be offered
normally. Before the original fix every generic "hit" reaction was skipped on a natural 20, so Parry and
Riposte was never offered against a critical, including when a riposte was met by another riposte.

MMX58 (the independent review) fixed three things in that repair:
  1. a mixed row whose extra rider follows the miss must stay blocked on a critical, while the rest of
     the row (a damage reduction) still applies -- the rider is held back by ``only_if_miss``;
  2. the critical decision is ONE function, also read by the ranked readiness path, so a higher-ranked
     row that cannot act on a natural 20 no longer makes a lower-ranked row that can wait for it;
  3. the AC-only control used a melee attack against a ranged-only reaction, so it passed whatever the
     guard did. It is now a qualifying ranged attack with an ordinary-hit positive control.

These run through the table: preview, a manual Ask-me owner or an AI owner, a commit, and a reload.

MMX60 (the second review) added the direction that was still missing: the attacker is the AI and the
defender is a player on Ask me. An AI turn pauses in a different place than a manual one -- the service
runs the AI's action on a copy first -- so the player's parry being asked, held and then resumed there
needed its own table test.
"""
import json

import pytest
from combat.gate4_engine import Gate4ControllerEngine
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet, script
from tests.hunt12_support import ME, FOE, reload

PARRY = "TAL_FENCING_PARRY_AND_RIPOSTE"
QI_ARMOR = "tianxia.path.qi_cultivation.feature.qi_armor"
SHIELD_TALISMAN = "tianxia.talent.talismans.shield_talisman"
CAULDRON_GUARD = "TAL_ALCHEMY_CAULDRON_GUARD"
WEAPON_GUARD = "tianxia.talent.weapons.weapon_guard"
IRON_LINK_GUARD = "tianxia.talent.chains.iron_link_guard"
FOCUS = "resource:core.martial_focus"
DAGGER = {"starting_kit": {"items": [
    {"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)", "quantity": 1}]}}
ALLY = "actor:factory.mmx58-ally"


def fight(tmp_path, *, mids=(PARRY,), foe_mids=(), ally_mids=(), foe_kit=DAGGER, foe_mode="MANUAL",
          me_mode="MANUAL", me_plan=None, me_primary="Stamina", positions=None):
    """A table where both sides carry a weapon and the reactor's reactions are asked or left to it.

    ``me_mode`` "MANUAL" uses Ask me (the player is prompted); any other supported mode ("LOCAL_AUTO")
    lets the actor decide for itself, which is what an AI-controlled creature does. ``me_primary`` is
    the pool the reactor's printed costs are paid from (Qi Armor costs 1 Qi, so it needs a Qi character).
    """
    from combat.factory_compiler import compile_character

    me = sheet(list(mids), cl=18, dc=100, primary=me_primary, score=18, kit=DAGGER)
    foe = sheet(list(foe_mids), cl=18, primary="Stamina", kit=foe_kit)
    foe["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1000
    bundles = [compile_character(me, actor_id=ME, reaction_plan=me_plan or {"ask": True}),
               compile_character(foe, actor_id=FOE, reaction_plan={"ask": True})]
    primary, opponents, teams, spots = [ME], [FOE], {ME: "team:factory", FOE: "team:opponents"}, \
        {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}
    if ally_mids:
        ally = sheet(list(ally_mids), cl=18, primary="Stamina", kit=DAGGER)
        ally["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1000
        bundles.append(compile_character(ally, actor_id=ALLY))
        primary.append(ALLY)
        teams[ALLY] = "team:factory"
        spots[ALLY] = positions or {"x": 3, "y": 7}
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [ME, FOE] + ([ALLY] if ally_mids else []), teams,
        spots, combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], primary, opponents,
        control_modes={ME: me_mode, FOE: foe_mode}, match_seed="MMX53", display_name="MMX53 critical reactions",
        maximum_rounds=20)["match_id"]
    # Roll and commit initiative now, before any test installs a scripted die: initiative is settled on
    # the first state() call, and a queued script would otherwise spend its first values there instead
    # of on the attack roll the test is about.
    table.state(mid)
    return combat, table, mid


# The untouched resolver, captured once: every script below wraps THIS, so a second scripted roll in
# one test replaces the first instead of nesting inside it and re-queuing over the newer natural.
_PRISTINE_RESOLVE = Gate4ControllerEngine._resolve_attack_spec


def crits(monkeypatch, *, only=None, natural=20):
    """Force every attack roll -- or only ``only``'s -- to a natural, with flat damage dice."""
    def resolve(engine, actor, *args, **kwargs):
        if only is None or getattr(actor, "entity_id", None) == only:
            script(engine, [natural, *([1] * 60)])
        return _PRISTINE_RESOLVE(engine, actor, *args, **kwargs)

    monkeypatch.setattr(Gate4ControllerEngine, "_resolve_attack_spec", resolve)


_FLOOR = {}


def flippable_natural(tmp_path, *, ranged):
    """The d20 that makes the attack HIT by exactly one and miss by an AC bonus.

    A reaction is only offered on an ordinary hit when its bonus is what turns the attack into a miss,
    and a "hit" reaction never runs at all if the attack misses outright -- so a positive control needs
    the attack to land right on the defender's armour class, not far below it. Measured once from the
    fixture itself (a scripted roll the engine records) rather than hardcoded, so it follows the sheet.
    """
    key = bool(ranged)
    if key not in _FLOOR:
        # Its own directory: a probe built from a different sheet would collide with the test's own
        # match id and trip the immutable-file hash check.
        probe = tmp_path / f"flippable-probe-{int(ranged)}"
        combat, table, mid = fight(probe, mids=())

        def resolve(engine, actor, *args, **kwargs):
            if getattr(actor, "entity_id", None) == FOE:
                script(engine, [20, *([1] * 60)])
            return _PRISTINE_RESOLVE(engine, actor, *args, **kwargs)

        Gate4ControllerEngine._resolve_attack_spec = resolve
        try:
            to_turn(table, mid, FOE)
            ask(table, mid, attack_on(combat, mid, ME, ranged=ranged))
        finally:
            Gate4ControllerEngine._resolve_attack_spec = _PRISTINE_RESOLVE
        rolled = [e for e in combat._load_session(mid).engine.events
                  if e.event_type == "ATTACK_ROLLED" and e.actor_id == FOE][-1]
        _FLOOR[key] = int(rolled.payload["target_ac"]) - int(rolled.payload["modifier"]) + 1
    return _FLOOR[key]


def attack_on(combat, mid, who, *, ranged=None):
    """A plain attack aimed at ``who`` as a candidate id.

    The dagger has two attacks, so one fixture covers both cases: the swing (5 ft, melee) and the
    throw (60 ft, ranged), which is what a ranged-only reaction like Qi Armor needs to be tested with.
    """
    engine = combat._load_session(mid).engine
    for c in engine.legal_candidates():
        if tuple(c.target_ids) != (who,) or c.kind.value in ("MOVE", "END_TURN"):
            continue
        action = engine.action_catalog.get(c.source_definition_id)
        name = str(getattr(action, "display_name", "")).lower()
        if not any(word in name for word in ("attack", "shot", "thrown")):
            continue
        is_ranged = int(getattr(action, "range_ft", 0) or 0) > 5
        if ranged is not None and is_ranged is not ranged:
            continue
        return c.candidate_id
    raise AssertionError(f"no {'ranged' if ranged else 'melee'} attack on {who}")


def ask(table, mid, chosen):
    """Commit one action, answering every Ask-me reaction prompt with USE. Returns the prompts."""
    state = table.state(mid)
    menu = state["menu"]
    chosen = menu["end_turn"] if chosen == "end" else chosen
    answers, prompts = [], []
    for _ in range(20):
        result = table.act(mid, chosen, menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        answer = {**prompt["context"], "selection": "USE"}
        if prompt.get("choice"):
            answer["option_ids"] = [prompt["choice"]["options"][0]["id"]]
        answers.append(answer)
    raise AssertionError("repeated reaction prompt without a commit")


def to_turn(table, mid, actor):
    for _ in range(20):
        if table.state(mid)["menu"]["actor_id"] == actor:
            return
        ask(table, mid, "end")
    raise AssertionError("turn never reached " + actor)


def ai_attack(table, mid, combat, cid, monkeypatch):
    """Advance an AI-controlled attacker with Auto Step, answering every Ask-me prompt with USE.

    Everything about the step is the shipped one -- ``CombatService.local_step`` asks the real controller,
    runs the action on a copy first (gate5_service ``_ask_during_ai_step``) so a player-owned Ask me
    reaction surfaces as ``AWAITING_REACTION`` with nothing committed, then re-runs it through
    ``_AnsweringController`` once the answer arrives. Only the choice is steered: the generic policy
    scores a reposition (90) above this attack (56) in this fixture, so leaving the AI free would test
    a walking AI, not the pause. ``tests/anchor_support.py::push`` steers it the same way for the same
    reason -- which action a policy prefers is not what these regressions are about.

    Returns ``(prompts, waiting_state)``, where ``waiting_state`` is the engine state read while the
    attack was still parked at the prompt, so a test can prove the attack was preserved, not lost.
    """
    original = combat.controller.choose_primary_action

    def choose(context):
        choice = original(context)
        picked = next(c for c in context.legal_candidates if c.candidate_id == cid)
        return choice.model_copy(update={
            "intent": choice.intent.model_copy(update={"candidate_id": cid, "target_ids": picked.target_ids,
                                                       "option_ids": picked.option_ids,
                                                       "destination": picked.destination}),
            "record": choice.record.model_copy(update={"selected_candidate_id": cid,
                                                       "selected_option_ids": picked.option_ids})})

    monkeypatch.setattr(combat.controller, "choose_primary_action", choose)
    state = table.state(mid)
    answers, prompts, waiting = [], [], None
    for _ in range(20):
        result = table.auto_step(mid, state["last_sequence"], answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return prompts, waiting
        prompt = result["reaction"]
        prompts.append(prompt)
        if waiting is None:
            waiting = combat._load_session(mid).engine.state
        answer = {**prompt["context"], "selection": "USE"}
        if prompt.get("choice"):
            answer["option_ids"] = [prompt["choice"]["options"][0]["id"]]
        answers.append(answer)
    raise AssertionError("repeated reaction prompt without a commit")


def parries(events, actor=ME):
    return [e for e in events if e.event_type == "REACTION_RESOLVED"
            and e.actor_id == actor and "PARRY" in str(e.source_definition_id)]


def damage_to(events, who):
    return [e for e in events if e.event_type == "DAMAGE_COMMITTED" and who in (e.target_ids or ())]


def offered(prompts):
    return [p.get("reaction") for p in prompts]


# ------------------------------------------------------------------ the original repair
@pytest.mark.parametrize('natural', [20, 19])
def test_parry_and_riposte_is_offered_on_a_critical_hit_and_reduces_the_damage(tmp_path, monkeypatch, natural):
    combat, table, mid = fight(tmp_path)
    if natural == 19:
        from tests.test_lock_choices import install
        install(monkeypatch, 'attack_critical_range', lambda *args: 19)
    crits(monkeypatch, only=FOE, natural=natural)
    to_turn(table, mid, FOE)
    before = reload(tmp_path, mid).state.actors[ME]

    prompts = ask(table, mid, attack_on(combat, mid, ME, ranged=False))
    assert "Parry and Riposte" in offered(prompts), f"the critical hit never offered the parry: {offered(prompts)}"

    # The reaction survived the table commit and the reload, and it still leaves the hit a hit.
    engine = reload(tmp_path, mid)
    resolved = parries(engine.events)
    assert any(e.event_type == 'DAMAGE_ROLLED' and e.actor_id == FOE and e.payload.get('critical') is True
               for e in engine.events), 'the forced expanded-range roll must actually be critical'
    assert resolved, "the offered parry never resolved"
    assert resolved[0].payload.get("pending_damage_reduction"), "the parry parked no reduction"
    assert resolved[0].payload.get("hit_after_recheck") is True, "the parry turned the critical into a miss"

    # It reduced the damage the critical actually dealt.
    committed = damage_to(engine.events, ME)
    assert committed, "the critical dealt no damage event at all"
    taken = committed[0].payload
    assert taken["rolled_or_pending_damage"] > taken["hp_damage"], (
        f"the parry absorbed nothing: rolled {taken['rolled_or_pending_damage']}, took {taken['hp_damage']}")

    after = engine.state.actors[ME]
    assert after.resources.get(FOCUS) < before.resources.get(FOCUS), "the parry cost no Martial Focus"


def test_a_riposte_can_be_answered_by_another_riposte_on_a_critical_hit(tmp_path, monkeypatch):
    """Mid-chain: the retaliatory attack is itself an attack a critical can land on."""
    combat, table, mid = fight(tmp_path, foe_mids=[PARRY])
    crits(monkeypatch)  # both sides crit
    to_turn(table, mid, FOE)
    prompts = ask(table, mid, attack_on(combat, mid, ME, ranged=False))
    assert offered(prompts).count("Parry and Riposte") >= 2, f"the riposte was not itself answerable: {offered(prompts)}"
    engine = reload(tmp_path, mid)
    assert parries(engine.events, ME) and parries(engine.events, FOE), "only one side riposted"


def test_the_critical_still_hits_when_the_parry_reduces_it(tmp_path, monkeypatch):
    """The automatic hit survives the reaction: reducing a critical is not turning it into a miss."""
    combat, table, mid = fight(tmp_path)
    crits(monkeypatch, only=FOE)
    to_turn(table, mid, FOE)
    ask(table, mid, attack_on(combat, mid, ME, ranged=False))
    engine = reload(tmp_path, mid)
    rolled = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == FOE]
    assert rolled and rolled[0].payload.get("natural_result") == 20
    # The critical's damage was rolled and then reduced -- it was not skipped as a miss.
    damage_rolls = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED" and e.actor_id == FOE]
    assert damage_rolls and damage_rolls[0].payload.get("critical") is True
    assert damage_rolls[0].payload["combined_total"] > 0


# ------------------------------------------------------------------ MMX58 finding 1: mixed riders
@pytest.mark.parametrize("guard", [CAULDRON_GUARD, WEAPON_GUARD])
def test_a_miss_dependent_rider_is_not_offered_on_a_critical_hit(tmp_path, monkeypatch, guard):
    """"If this causes the attack to miss, you may move 5 feet": the step follows the miss, and a natural
    20 never misses, so spending the Reaction on the AC bonus would buy nothing at all."""
    combat, table, mid = fight(tmp_path, mids=[guard])
    crits(monkeypatch, only=FOE, natural=20)
    to_turn(table, mid, FOE)
    prompts = ask(table, mid, attack_on(combat, mid, ME, ranged=False))
    assert not prompts, f"{guard} was offered against a critical it cannot help: {offered(prompts)}"
    engine = reload(tmp_path, mid)
    assert not [e for e in engine.events if e.event_type == "MOVEMENT_GRANTED" and e.actor_id == ME], \
        "the step ran even though the attack never missed"


def test_the_same_miss_dependent_rider_still_runs_when_the_bonus_makes_the_attack_miss(tmp_path, monkeypatch):
    """The other half of the contract: hold the rider back on a critical, never on an ordinary hit. A
    natural 1 is flipped by Cauldron Guard's +2 AC, so the printed step is owed and must happen."""
    combat, table, mid = fight(tmp_path, mids=[CAULDRON_GUARD])
    crits(monkeypatch, only=FOE, natural=flippable_natural(tmp_path, ranged=False))
    to_turn(table, mid, FOE)
    prompts = ask(table, mid, attack_on(combat, mid, ME, ranged=False))
    assert "Cauldron Guard" in offered(prompts), f"the guard was not offered on a flippable hit: {offered(prompts)}"
    engine = reload(tmp_path, mid)
    resolved = [e for e in engine.events if e.event_type == "REACTION_RESOLVED" and e.actor_id == ME]
    assert resolved and resolved[0].payload.get("hit_after_recheck") is False, "the bonus did not turn the hit into a miss"
    moved = [e for e in engine.events if e.event_type == "MOVEMENT_GRANTED" and e.actor_id == ME]
    assert moved, "the printed step never ran after the attack actually missed"


def test_a_mixed_row_reduces_the_damage_on_a_critical_while_its_miss_rider_stays_blocked():
    """The review's exact case, on the shared seam both hit paths read: a row that carries a damage
    reduction AND a rider printed to follow the miss. On a critical the reduction is still worth the
    Reaction and still runs; the step is held back, because there was no miss. No shipped ability has
    this exact pairing, so it is exercised on the function the two paths call rather than invented as one."""
    from combat.typed_reactions import _changes_hit_miss_only, _remaining_rider_effects

    ac = {"type": "ac_bonus", "applies_to": "self", "flat": 2}
    step = {"type": "movement", "applies_to": "self", "distance_ft": 5, "only_if_miss": True}
    cut = {"type": "damage_modifier", "applies_to": "self", "flat": 2}
    row = {"effects": [ac, step, cut]}

    # The row is worth spending on a natural 20, because the reduction works there.
    assert not _changes_hit_miss_only(row)
    # ... and the step, which waits for a miss that a natural 20 can never be, is not run.
    on_critical = _remaining_rider_effects(row, hit_after=True, spent=[cut])
    assert step not in on_critical, "the miss rider ran against a critical"
    assert cut not in on_critical, "the reduction was re-run by the rider pass"
    # On an ordinary hit the bonus turned it into a miss, so the step is owed and runs.
    on_a_miss = _remaining_rider_effects(row, hit_after=False, spent=[cut])
    assert step in on_a_miss, "the printed step never runs when the attack really did miss"


# ------------------------------------------------------------------ MMX58 finding 2: ranked plans
def test_a_ranked_ac_only_reaction_does_not_suppress_parry_on_a_critical_hit(tmp_path, monkeypatch):
    """A ranked plan tries the most important reaction first, but a row that cannot act on a natural 20
    must not make a lower-ranked row that can wait for it. Shield Talisman (AC only) is ranked above
    Parry, so before the fix Parry was skipped as outranked and the critical landed unsoftened."""
    combat, table, mid = fight(tmp_path, mids=[PARRY, SHIELD_TALISMAN],
                               me_plan={"order": [SHIELD_TALISMAN, PARRY]})
    crits(monkeypatch, only=FOE)
    to_turn(table, mid, FOE)
    ask(table, mid, attack_on(combat, mid, ME, ranged=False))
    engine = reload(tmp_path, mid)
    assert parries(engine.events), "the higher-ranked AC-only row suppressed the parry on a critical"
    committed = damage_to(engine.events, ME)
    assert committed and committed[0].payload["rolled_or_pending_damage"] > committed[0].payload["hp_damage"], \
        "the critical landed unsoftened"


# ------------------------------------------------------------------ MMX58 finding 3: real AC controls
def test_qi_armor_is_offered_against_an_ordinary_ranged_hit_and_not_against_a_critical_one(tmp_path, monkeypatch):
    """Qi Armor's block is ranged_only and it costs Qi, so the old control (a melee attack, on a
    character with no Qi) was rejected for two reasons that had nothing to do with the natural roll: it
    passed whatever the critical guard did. This drives the real ATTACK_HIT_BEFORE_DAMAGE checkpoint
    with the spec a ranged attack actually carries -- a melee swing in this table reports no range at
    all -- and asks the same question both ways: on an ordinary hit the +5 AC turns the attack into a
    miss, on a natural 20 the reaction is not spent at all and the hit stands."""
    from combat.typed_reactions import on_attack_hit

    def fire(root, natural, total):
        # Auto, not Ask me: the checkpoint is called directly here, so there is no table prompt to
        # answer, and the reactor must decide the way an AI-controlled one would.
        combat, table, mid = fight(root, mids=[QI_ARMOR], me_primary="Qi", me_plan={"off": []})
        engine = combat._load_session(mid).engine
        me, foe = engine.state.actors[ME], engine.state.actors[FOE]
        effective_ac, still_hit = on_attack_hit(
            engine, foe, me, {"range_ft": 60, "source_definition_id": "action:test.ranged_shot",
                              "action_name": "Ranged shot"}, total, natural, me.armor_class)
        return engine, me, effective_ac, still_hit

    # An ordinary hit: the attack lands, and Qi Armor's +5 AC is what makes it miss.
    engine, me, ac_after, still_hit = fire(tmp_path / "ordinary", 9, 15)
    assert not still_hit, "the ordinary hit was not turned into a miss by the AC reaction"
    assert ac_after == me.armor_class + 5, f"the reaction did not raise AC: {ac_after}"
    spent = [e for e in engine.events if e.event_type == "REACTION_RESOLVED"]
    assert spent and spent[0].payload.get("hit_after_recheck") is False

    # A natural 20: nothing may turn it into a miss, so the reaction is not spent.
    engine, me, ac_after, still_hit = fire(tmp_path / "critical", 20, 25)
    assert still_hit, "the critical was turned into a miss"
    assert ac_after == me.armor_class, "the AC reaction was spent against a critical"
    assert not [e for e in engine.events if e.event_type == "REACTION_RESOLVED"], \
        "an AC-only reaction was offered against a critical"


def test_a_generic_ac_only_reaction_is_offered_on_an_ordinary_hit_and_not_on_a_critical_hit(tmp_path, monkeypatch):
    """The generic (typed) half of the same control, which the legacy hit_ac path does not cover at all.
    Shield Talisman's row is a single ac_bonus, so a natural 20 must not offer it, while a roll the
    bonus flips still must -- and that second half is what proves the first half means anything."""
    combat, table, mid = fight(tmp_path / "ordinary", mids=[SHIELD_TALISMAN])
    crits(monkeypatch, only=FOE, natural=flippable_natural(tmp_path, ranged=False))
    to_turn(table, mid, FOE)
    flippable = ask(table, mid, attack_on(combat, mid, ME, ranged=False))
    assert "Shield Talisman" in offered(flippable), \
        f"the generic AC reaction is not reachable by this fixture: {offered(flippable)}"

    combat, table, mid = fight(tmp_path / "critical", mids=[SHIELD_TALISMAN])
    crits(monkeypatch, only=FOE, natural=20)
    to_turn(table, mid, FOE)
    assert not ask(table, mid, attack_on(combat, mid, ME, ranged=False)), \
        "a generic AC-only reaction was offered against a critical"


# ------------------------------------------------------------------ the changed ally and AI paths
@pytest.mark.parametrize('natural', [20, 19])
def test_an_ally_reaction_that_reduces_damage_is_offered_on_a_critical_hit(tmp_path, monkeypatch, natural):
    """The ally_hit path shares the same classifier: an ally spends its own Reaction to cut the damage,
    which still works on a natural 20, so it must be offered there too. The attacked fighter owns no
    hit reaction of their own, so the ally's row is the one that has to be reached."""
    combat, table, mid = fight(tmp_path, mids=(), ally_mids=[IRON_LINK_GUARD])
    if natural == 19:
        from tests.test_lock_choices import install
        install(monkeypatch, 'attack_critical_range', lambda *args: 19)
    crits(monkeypatch, only=FOE, natural=natural)
    to_turn(table, mid, FOE)
    ask(table, mid, attack_on(combat, mid, ME, ranged=False))
    engine = reload(tmp_path, mid)
    saved = [e for e in engine.events if e.event_type == "REACTION_RESOLVED" and e.actor_id == ALLY]
    assert any(e.event_type == 'DAMAGE_ROLLED' and e.actor_id == FOE and e.payload.get('critical') is True
               for e in engine.events), 'the ally must be answering an actual critical'
    assert saved, "the ally never spent its Reaction against a critical"
    assert saved[0].payload.get("protects") == ME, "the ally reaction was not protecting the attacked fighter"
    taken = damage_to(engine.events, ME)
    assert taken, "the critical dealt no damage event at all"
    assert taken[0].payload["rolled_or_pending_damage"] > taken[0].payload["hp_damage"], \
        "the ally reaction absorbed nothing from the critical"


def test_an_ai_reactor_answers_a_critical_hit_on_the_other_actors_turn(tmp_path, monkeypatch):
    """A player-owned decision is asked, but an AI actor decides for itself and is not prompted. The
    reactor here is AI-controlled and reacting on the attacker's turn, off its own."""
    combat, table, mid = fight(tmp_path, me_mode="LOCAL_AUTO")
    crits(monkeypatch, only=FOE)
    to_turn(table, mid, FOE)
    prompts = ask(table, mid, attack_on(combat, mid, ME, ranged=False))
    assert not prompts, f"an AI-controlled fighter was asked instead of deciding: {offered(prompts)}"
    engine = reload(tmp_path, mid)
    assert parries(engine.events), "the AI reactor did not answer the critical off its own turn"
    taken = damage_to(engine.events, ME)
    assert taken and taken[0].payload["rolled_or_pending_damage"] > taken[0].payload["hp_damage"], \
        "the AI's own decision left the critical unsoftened"


def test_an_ai_attackers_critical_is_answered_by_the_manual_players_parry(tmp_path, monkeypatch):
    """The mirror image of the test above, and the case the MMX53r2 review asked for: the ATTACKER is
    the AI and the DEFENDER is a player on Ask me. The two directions pause in different places --
    ``TabletopService.act`` (step 16 of a manual attack) versus ``CombatService._ask_during_ai_step``,
    which runs the AI's action on a copy -- so the AI turn is driven through Auto Step here, letting the
    service pause, answer and resume the attack.

    Checklist item 9 is the claim under test: a player-owned decision is asked even on an AI turn.
    """
    combat, table, mid = fight(tmp_path, foe_mode="LOCAL_AUTO", me_mode="MANUAL")
    crits(monkeypatch, only=FOE)
    to_turn(table, mid, FOE)
    assert table.state(mid)["menu"]["actor_id"] == FOE, "the AI attacker never reached its own turn"
    before = combat._load_session(mid).engine.state.actors[ME].current_hp

    prompts, waiting = ai_attack(table, mid, combat, attack_on(combat, mid, ME, ranged=False), monkeypatch)

    # The player was asked, on the AI's turn, and the prompt says what it is and who it is aimed at.
    assert "Parry and Riposte" in offered(prompts), \
        f"the player's parry was never asked on the AI's critical hit: {offered(prompts)}"
    prompt = next(p for p in prompts if p.get("reaction") == "Parry and Riposte")
    assert prompt["context"]["reactor_id"] == ME, "the prompt was aimed at the wrong fighter"
    assert "attack" in json.dumps(prompt).lower(), f"the prompt does not name the attack: {prompt}"

    # The AI's attack is parked at the prompt, not lost: nothing was committed while the player decided.
    assert waiting is not None, "the AI step never paused for a player decision"
    assert waiting.actors[ME].current_hp == before, "the critical landed before the player was asked"

    # The answer resumes that same attack, through a commit and a reload from disk.
    engine = reload(tmp_path, mid)
    resolved = parries(engine.events)
    assert resolved, "the parry the player answered never resolved"
    assert resolved[0].payload.get("pending_damage_reduction"), "the parry parked no reduction"
    assert resolved[0].payload.get("hit_after_recheck") is True, "the parry turned the critical into a miss"
    taken = damage_to(engine.events, ME)
    assert taken, "the AI's critical dealt no damage event at all"
    assert taken[0].payload["rolled_or_pending_damage"] > taken[0].payload["hp_damage"], \
        "the player's parry left the AI's critical unsoftened"


# ------------------------------------------------------------------ the seam itself
def test_the_guard_is_classified_by_typed_effects_not_by_ability_name():
    """The seam reads each row's own effects, so a newly typed reaction needs no code change."""
    from combat.typed_reactions import _changes_hit_miss_only, _skipped_by_critical

    ac_only = {"effects": [{"type": "ac_bonus", "amount": 3}]}
    penalty_only = {"effects": [{"type": "attack_modifier", "applies_to": "attacker", "amount": 1}]}
    miss_rider = {"effects": [{"type": "ac_bonus", "amount": 2},
                              {"type": "movement", "distance_ft": 5, "only_if_miss": True}]}
    reduction = {"effects": [{"type": "damage_modifier", "applies_to": "self", "amount": 2}]}
    mixed = {"effects": [{"type": "ac_bonus", "amount": 3},
                         {"type": "condition", "applies_to": "target", "condition": "opened"}]}

    assert _changes_hit_miss_only(ac_only) and _changes_hit_miss_only(penalty_only)
    assert _changes_hit_miss_only(miss_rider), "a rider that waits for the miss cannot help on a critical"
    assert not _changes_hit_miss_only(reduction) and not _changes_hit_miss_only(mixed)

    assert _skipped_by_critical(20, ac_only) and _skipped_by_critical(20, penalty_only)
    assert _skipped_by_critical(20, miss_rider)
    assert not _skipped_by_critical(20, reduction) and not _skipped_by_critical(20, mixed)
    # An ordinary hit is offered to all of them, exactly as before.
    assert not any(_skipped_by_critical(12, row) for row in (ac_only, penalty_only, miss_rider, reduction, mixed))
    # Before the roll nothing is known, so nothing is ruled out.
    assert not _skipped_by_critical(None, ac_only)
