"""Rider lane C16 (owner standing rule: fill sphere gaps from the owner's books, then Spheres 5e, then D&D 5.5e; do not ask): the
sphere chassis the blocked-line census listed as "not built" -- Guardian (Interpose, Held Harm, Patrol), Brute (the Brutal Shove
contest, Overrun) and Verdant Growth (Living Claims, Growth Marks, Verdant Responses). Every test compiles a real character and runs
the engine; the table tests go through the tabletop service with a commit and a reload.

Overrides: authority/typed_mechanics/reviewed_final.d/riders_c16.json; rows: combat/rules/feature_blocks.d/riders_c16.json.
Plug-ins: combat/ext/guardian_chassis.py, combat/ext/guardian_patrol.py, combat/ext/granted_moves.py (and the Brute / Verdant ones).
"""
from __future__ import annotations

import pytest

from combat import typed_executor
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine
from tests.h1_support import ROOT, sheet

ME, ALLY, FOE = "actor:factory.c16_me", "actor:factory.c16_ally", "actor:factory.c16_foe"
SEED = "TAL_VERDANT_GROWTH_SEED_THORN_STRIKE"
CHALLENGE, PATROL = "GUARDIAN_BASE_CHALLENGE_PRACTICE", "GUARDIAN_BASE_PATROL_PRACTICE"
G = "TAL_GUARDIAN_"
FOCUS = "resource:core.martial_focus"


# ------------------------------------------------------------------------------------------------------- harness
def bundle(*mids, cl=10, dc=16, actor_id=ME, score=14, hp=60):
    doc = sheet(list(mids), cl=cl, dc=dc, score=score)
    doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = hp
    return compile_character(doc, actor_id=actor_id)


def fight(me, *, foe=None, ally=None, me_at=(3, 6), foe_at=(6, 6), ally_at=(3, 8), seed="C16"):
    foe = foe or bundle(SEED, actor_id=FOE, cl=5)
    bundles = [me, foe] + ([ally] if ally else [])
    ids = [b["actor_id"] for b in bundles]
    teams = {ME: "team:a", FOE: "team:b", ALLY: "team:a"}
    spots = {ME: me_at, FOE: foe_at, ALLY: ally_at}
    engine = Gate4ControllerEngine(ROOT, match_seed=seed, typed_bundles=tuple(bundles), roster_setup={
        "primary_actor_ids": ids, "team_by_actor": {i: teams[i] for i in ids},
        "starting_positions": {i: {"x": spots[i][0], "y": spots[i][1]} for i in ids}})
    turn(engine, ME)
    return engine


def turn(engine, actor_id):
    while engine.state.current_actor_id != actor_id:
        engine.end_turn()
    actor = engine.state.actors[actor_id]
    actor.action_available, actor.bonus_action_available, actor.reaction_available = True, True, True
    return actor


def use(engine, name, *, target=None, at=None):
    actor_id = engine.state.current_actor_id
    rows = [c for c in engine.legal_candidates() if (c.display_name == name or c.display_name.startswith(name + " at "))
            and (target is None or target in (c.target_ids or ()))
            and (at is None or (c.destination is not None and (c.destination.x, c.destination.y) == tuple(at)))]
    assert rows, f"{name!r} is not legal; legal: {sorted({c.display_name.split(' at ')[0] for c in engine.legal_candidates()})[:80]}"
    c = rows[0]
    before = len(engine.events)
    engine.execute_intent(ActionIntent(intent_id=f"i-{name}-{before}", decision_id=c.decision_id, candidate_id=c.candidate_id,
                                       state_version=c.state_version, actor_id=actor_id,
                                       target_ids=c.target_ids or ((target,) if target else ()), destination=c.destination))
    return engine.events[before:]


def held(actor, name):
    return [c for c in actor.conditions.values() if c.condition_id == f"condition:typed.{name}"]


def logs(events):
    return [str((e.payload or {}).get("log") or "") for e in events if e.event_type == "PASSIVE_TRIGGERED"]


def sure_hit(engine, *ids):
    for actor_id in ids:
        engine.state.actors[actor_id].armor_class = -50


# ================================================================================================= GUARDIAN: Interpose
def test_interpose_moves_beside_the_ally_and_takes_the_attack():
    """Core Guardian Rules, Interpose: "Trigger: One ally within 10 feet is targeted by an attack roll ... Move up to 10 feet into one
    legal unoccupied space adjacent to the ally ... If you are a legal target for the triggering attack, become its target instead.\""""
    guardian = bundle(CHALLENGE, hp=200)
    ally = bundle(actor_id=ALLY, hp=20)
    engine = fight(guardian, ally=ally, me_at=(3, 6), ally_at=(3, 8), foe_at=(6, 9))
    sure_hit(engine, ME, ALLY)
    turn(engine, FOE)
    events = use(engine, "Seed-Thorn Strike", target=ALLY)
    retarget = [e for e in events if e.event_type == "ATTACK_RETARGETED"]
    assert retarget and retarget[0].target_ids == (ME,) and retarget[0].payload["original_target_id"] == ALLY
    me, ally_state = engine.state.actors[ME], engine.state.actors[ALLY]
    assert engine._distance_actor_to_actor(me, ally_state) <= 5  # it stepped beside the ally
    assert ally_state.current_hp == ally_state.maximum_hp and not me.reaction_available
    assert any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == ME and e.payload.get("cost_ft") == 0 for e in events)


@pytest.mark.parametrize("auto_attacker", [False, True])
@pytest.mark.parametrize("ai_guardian", [False, True])
def test_interpose_destination_preference_and_player_choice_at_table(tmp_path, auto_attacker, ai_guardian):
    """AI takes the shortest protecting route; the player may choose a different offered square."""
    from combat.canonical import canonical_sha256
    from tests.r1i_service_support import FOE as TFOE, OWNER, SECOND, candidate, fixture, force_ai_candidate
    from tests.test_r1i_round3 import reload, resolve

    def melee_attack(bundles):
        foe = next(b for b in bundles if b["actor_id"] == TFOE)
        strike = next(a for a in foe["action_catalog"] if a["display_name"] == "Seed-Thorn Strike")
        strike.update(resolution_kind="ATTACK", range_ft=5, attack_bonus=100, damage_type="PIERCING",
                      damage={"count": 1, "sides": 6, "modifier": 2})
        foe.pop("bundle_sha256", None)
        foe["bundle_sha256"] = canonical_sha256(foe)

    combat, table, mid, send, commit = fixture(
        tmp_path, [CHALLENGE, G + "BODYGUARD"], owner_ac=100, foe_talents=[SEED], allies=(SECOND,),
        seed="C16-INTERPOSE-DESTINATION", bundle_transform=melee_attack,
        positions={OWNER: {"x": 3, "y": 6}, SECOND: {"x": 3, "y": 8}, TFOE: {"x": 4, "y": 9}})
    while table.state(mid)["menu"]["actor_id"] != TFOE:
        commit(table.state(mid)["menu"]["end_turn"])
    if ai_guardian:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    cid = candidate(table, mid, "Seed-Thorn Strike", SECOND)
    before_events = len(reload(tmp_path, mid).events)
    if auto_attacker:
        force_ai_candidate(combat, mid, TFOE, cid)
    before, prompts = resolve(combat, mid, send, cid, {
        "choice:needle.interpose": "interpose", "choice:needle.interpose_destination": "cell:3,9"}, auto=auto_attacker)
    if ai_guardian:
        assert not prompts
    else:
        choice = next(p["choice"] for p in prompts
                      if p["context"]["reaction_source_id"] == "choice:needle.interpose_destination")
        options = [o["id"] for o in choice["options"]]
        assert {"cell:2,7", "cell:4,8", "cell:3,9"} <= set(options)
        assert options[0] == "cell:2,7"  # beside the ally, but outside the attacker's five-foot reach
        assert choice["preferred"] == ["cell:4,8"]  # shortest legal interception, not lexical order
    engine = reload(tmp_path, mid)
    guardian = engine.state.actors[OWNER]
    expected_position = {"x": 4, "y": 8} if ai_guardian else {"x": 3, "y": 9}
    assert guardian.position.model_dump(mode="json") == expected_position
    assert not guardian.reaction_available
    events = engine.events[before_events:]
    assert [e.target_ids for e in events if e.event_type == "ATTACK_RETARGETED"] == [(OWNER,)]
    assert [e.target_ids for e in events if e.event_type == "ATTACK_ROLLED"] == [(OWNER,)]
    assert engine.state.actors[SECOND].current_hp == before["actors"][SECOND]["current_hp"]
    rolled = next(e for e in events if e.event_type == "DAMAGE_ROLLED")
    committed = [e for e in events if e.event_type == "DAMAGE_COMMITTED"]
    assert [e.target_ids for e in committed] == [(OWNER,)]
    assert [e.payload["hp_damage"] for e in committed] == [int(rolled.payload["total"]) // 2]
    assert before["actors"][OWNER]["current_hp"] - guardian.current_hp == int(rolled.payload["total"]) // 2


def test_interpose_is_inert_for_a_creature_without_guardian():
    plain = bundle(SEED, hp=200)
    ally = bundle(actor_id=ALLY, hp=20)
    engine = fight(plain, ally=ally, me_at=(3, 6), ally_at=(3, 8), foe_at=(6, 9))
    sure_hit(engine, ME, ALLY)
    turn(engine, FOE)
    events = use(engine, "Seed-Thorn Strike", target=ALLY)
    assert not [e for e in events if e.event_type == "ATTACK_RETARGETED"]


def test_interpose_out_of_range_is_not_offered():
    guardian = bundle(CHALLENGE, hp=200)
    ally = bundle(actor_id=ALLY, hp=20)
    engine = fight(guardian, ally=ally, me_at=(1, 1), ally_at=(6, 8), foe_at=(9, 9))
    turn(engine, FOE)
    events = use(engine, "Seed-Thorn Strike", target=ALLY)
    assert not [e for e in events if e.event_type == "ATTACK_RETARGETED"]


def test_bodyguard_reaches_twenty_feet_and_resists_the_attack():
    """Bodyguard: "its range increases to 20 feet; you may move up to 20 feet when using it; gain Resistance to the triggering attack's
    damage until that attack resolves.\""""
    guardian = bundle(CHALLENGE, G + "BODYGUARD", hp=200)
    ally = bundle(actor_id=ALLY, hp=20)
    engine = fight(guardian, ally=ally, me_at=(3, 4), ally_at=(3, 8), foe_at=(7, 9))
    sure_hit(engine, ME, ALLY)
    turn(engine, FOE)
    events = use(engine, "Seed-Thorn Strike", target=ALLY)
    assert [e for e in events if e.event_type == "ATTACK_RETARGETED"]
    me = engine.state.actors[ME]
    assert engine.grid.distance_ft(me.position, engine.state.actors[ALLY].position) <= 5  # moved 15 feet: beyond plain Interpose's 10
    rolled = next(e for e in events if e.event_type == "DAMAGE_ROLLED")
    from combat.ext import guardian_chassis
    assert guardian_chassis.stored(me) == 0
    assert any("Held Harm is unavailable" in e.payload.get("log", "") for e in events if e.event_type == "PASSIVE_TRIGGERED")
    from combat.ext import attack_defenses

    assert not attack_defenses.packet_resistances(engine, me, "PIERCING", {}, FOE)  # the triggering attack has resolved


@pytest.mark.parametrize("auto_attacker", [False, True])
@pytest.mark.parametrize("outcome", ["hit", "miss", "decline", "no_bodyguard", "ai_guardian"])
@pytest.mark.parametrize("delivery", ["typed", "native", "typed_on_hit"])
def test_bodyguard_attack_scope_at_table(tmp_path, auto_attacker, outcome, delivery):
    """Interpose resists its attack only, never a later non-attack packet on that same turn."""
    from combat.canonical import canonical_sha256
    from combat.ext import attack_defenses, guardian_chassis
    from tests.r1i_service_support import FOE as TFOE, OWNER, SECOND, candidate, fixture, force_ai_candidate
    from tests.test_r1i_round3 import reload, resolve

    def separate_damage(bundles):
        from copy import deepcopy

        foe = next(b for b in bundles if b["actor_id"] == TFOE)
        strike = next(a for a in foe["action_catalog"] if a["display_name"] == "Seed-Thorn Strike")
        probe = deepcopy(strike)
        probe.update(source_definition_id=probe["source_definition_id"] + ".probe", display_name="Separate damage probe",
                     economy="BONUS_ACTION")
        probe["parameters"]["typed"]["effects"] = [{
            "type": "damage", "applies_to": "target", "flat": 7, "damage_types": ["PIERCING"]}]
        foe["action_catalog"].append(probe)
        foe["actor_template"]["action_ids"].append(probe["source_definition_id"])
        if delivery == "native":
            strike.update(resolution_kind="ATTACK", attack_bonus=100, damage_type="PIERCING",
                          damage={"count": 1, "sides": 6, "modifier": 2})
        elif delivery == "typed_on_hit":
            attack = next(e for e in strike["parameters"]["typed"]["effects"] if e["type"] == "attack")
            attack["on_hit"].append({"type": "damage", "applies_to": "target", "flat": 9, "damage_types": ["PIERCING"]})
        foe.pop("bundle_sha256", None)
        foe["bundle_sha256"] = canonical_sha256(foe)

    talents = [CHALLENGE] + ([] if outcome == "no_bodyguard" else [G + "BODYGUARD"])
    combat, table, mid, send, commit = fixture(
        tmp_path, talents, foe_talents=[SEED], allies=(SECOND,),
        owner_ac=1000 if outcome == "miss" else 100 if outcome == "ai_guardian" else 0, seed="C16-BODYGUARD-SCOPE",
        positions={OWNER: {"x": 3, "y": 6}, SECOND: {"x": 3, "y": 8}, TFOE: {"x": 5, "y": 9}},
        bundle_transform=separate_damage)
    while table.state(mid)["menu"]["actor_id"] != TFOE:
        commit(table.state(mid)["menu"]["end_turn"])
    if outcome == "ai_guardian":
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    cid = candidate(table, mid, "Seed-Thorn Strike", SECOND)
    before = len(reload(tmp_path, mid).events)
    if auto_attacker:
        force_ai_candidate(combat, mid, TFOE, cid)
    before_state, prompts = resolve(combat, mid, send, cid, {
        "choice:needle.interpose": None if outcome == "decline" else "interpose",
        "choice:needle.interpose_destination": "$first",
        "choice:needle.held_harm": "all"}, auto=auto_attacker)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.interpose" for p in prompts) == (outcome != "ai_guardian")
    engine = reload(tmp_path, mid)
    events = engine.events[before:]
    rolls = [e for e in events if e.event_type == "ATTACK_ROLLED"]
    assert len(rolls) == 1
    assert bool(rolls[0].payload["provisional_hit"]) == (outcome != "miss")
    assert rolls[0].target_ids == ((SECOND,) if outcome == "decline" else (OWNER,))
    rolled_damage = [e for e in events if e.event_type == "DAMAGE_ROLLED" and e.source_definition_id == rolls[0].source_definition_id]
    resisted = outcome in ("hit", "ai_guardian")
    expected_packets = [int(e.payload["total"]) // (2 if resisted else 1) for e in rolled_damage]
    if delivery == "typed_on_hit" and outcome != "miss":
        expected_packets.append(4 if resisted else 9)  # flat damage emits no DAMAGE_ROLLED
    recipient = SECOND if outcome == "decline" else OWNER
    committed = [e for e in events if e.event_type == "DAMAGE_COMMITTED"]
    assert [e.target_ids for e in committed] == [(recipient,)] * len(expected_packets)
    assert [int(e.payload["hp_damage"]) for e in committed] == expected_packets
    for who in (OWNER, SECOND):
        expected = sum(expected_packets) if who == recipient else 0
        assert before_state["actors"][who]["current_hp"] - engine.state.actors[who].current_hp == expected
    if outcome != "decline":
        assert len(rolled_damage) == (0 if outcome == "miss" else 1)
        assert guardian_chassis.stored(engine.state.actors[OWNER]) == 0
        assert any("Held Harm is unavailable" in e.payload.get("log", "") for e in events if e.event_type == "PASSIVE_TRIGGERED") == (outcome != "miss")
    assert not attack_defenses.packet_resistances(engine, engine.state.actors[OWNER], "PIERCING", {}, TFOE)
    assert "guardian_bodyguard" not in engine.state.actors[OWNER].turn_flags
    # Reload, then damage the Guardian without an attack from that same enemy on
    # that same turn. All seven points must be committed, not three.
    if auto_attacker:
        combat.set_controller_mode(mid, actor_id=TFOE, controller_mode="MANUAL")
    cid = candidate(table, mid, "Separate damage probe", OWNER)
    before = len(engine.events)
    if auto_attacker:
        force_ai_candidate(combat, mid, TFOE, cid)
    probe_before, _ = resolve(combat, mid, send, cid, {"choice:needle.held_harm": "all"}, auto=auto_attacker)
    engine = reload(tmp_path, mid)
    second_probe_events = engine.events[before:]
    committed = [e for e in second_probe_events if e.event_type == "DAMAGE_COMMITTED"]
    assert [e.target_ids for e in committed] == [(OWNER,)]
    assert [int(e.payload["hp_damage"]) for e in committed] == [7]
    assert probe_before["actors"][OWNER]["current_hp"] - engine.state.actors[OWNER].current_hp == 7
    assert engine.state.actors[SECOND].current_hp == probe_before["actors"][SECOND]["current_hp"]
    assert guardian_chassis.stored(engine.state.actors[OWNER]) == 0
    assert any("Held Harm is unavailable" in e.payload.get("log", "") for e in second_probe_events if e.event_type == "PASSIVE_TRIGGERED")


@pytest.mark.parametrize("abort", [False, True])
def test_attack_only_resistance_native_nested_packets_and_unwind(abort):
    """The shared seam cannot lend a parent's grant to the same source's nested attack."""
    from combat.damage_context import AttackDamage
    from combat.ext import attack_defenses

    engine = fight(bundle(SEED, hp=200))
    target, attacker = engine.state.actors[ME], engine.state.actors[FOE]
    source = "test:declared_attack"

    def roll(roll_id):
        engine._append_event("ATTACK_ROLLED", source, actor_id=FOE, target_ids=(ME,),
                             payload={"reason": f"ATTACK:{source}:1", "roll_id": roll_id})
        return AttackDamage(source, FOE, ME, 1, roll_id, 10, 100, False)

    def packet(context):
        hp = target.current_hp
        engine._commit_damage(target, 10, "PIERCING", source, FOE, None, reaction_depth=0, attack_context=context)
        return hp - target.current_hp

    # Exercise real native scope callbacks, but construct the packet metadata
    # explicitly to test identical source/actor/index with distinct roll IDs.
    frame = {"kind": "attack", "actor_id": FOE, "source_id": source, "attack_index": 1, "spec": {}}
    with attack_defenses.declaration_resolution(engine), engine.d20_scope(frame):
        spec = attack_defenses.declaration_spec(engine, attacker, source, 1)
        attack_defenses.grant_resistance(spec, target, G + "BODYGUARD")
        outer = roll("outer-roll")
        assert packet(outer) == 5
        try:
            with engine.d20_scope(frame):
                attack_defenses.declaration_spec(engine, attacker, source, 1)  # no grant for the nested attack
                nested = roll("nested-roll")
                assert packet(nested) == 10
                assert packet(None) == 10
                if abort:
                    raise RuntimeError("cancel nested attack")
        except RuntimeError:
            assert abort
        assert packet(outer) == 5  # parent restored, even when child unwinds
    assert packet(outer) == 10  # no leftover grant after the outer scope exits
    with pytest.raises(RuntimeError, match="cancel portable attack"):
        with attack_defenses.declaration_resolution(engine):
            spec = attack_defenses.declaration_spec(engine, attacker, source, 1)
            attack_defenses.grant_resistance(spec, target, G + "BODYGUARD")
            portable = roll("portable-roll")
            assert packet(portable) == 5
            raise RuntimeError("cancel portable attack")
    assert packet(portable) == 10


@pytest.mark.parametrize("auto_attacker", [False, True])
def test_bodyguard_multi_ray_redirected_damage_at_table(tmp_path, auto_attacker):
    """A ray rolls before its damage effect; Interpose still protects its actual recipient."""
    from combat.ext import guardian_chassis
    from tests.r1i_service_support import FOE as TFOE, OWNER, SECOND, candidate, fixture, force_ai_candidate
    from tests.test_r1i_round3 import reload, resolve

    combat, table, mid, send, commit = fixture(
        tmp_path, [CHALLENGE, G + "BODYGUARD"], owner_ac=0,
        foe_talents=["tianxia.talent.destruction.heaven_piercing_ray"], allies=(SECOND,),
        seed="C16-BODYGUARD-RAY", positions={OWNER: {"x": 3, "y": 6}, SECOND: {"x": 3, "y": 8}, TFOE: {"x": 5, "y": 9}})
    while table.state(mid)["menu"]["actor_id"] != TFOE:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, "Heaven-Piercing Ray (Multi-Ray", SECOND)
    before = len(reload(tmp_path, mid).events)
    if auto_attacker:
        force_ai_candidate(combat, mid, TFOE, cid)
    # "No creature or object may be targeted by more than one ray". This
    # three-creature fixture has two hostile recipients, so use both rather
    # than the obsolete five-rays-at-SECOND delivery. Interpose may redirect
    # the first ray; it does not change who was originally chosen for either.
    before_state = reload(tmp_path, mid).state.model_dump(mode='json')
    answers = []
    picks = {'choice:needle.interpose': ['interpose'],
             'choice:needle.held_harm': ['all'],
             'choice:needle.rider_targets': [SECOND, OWNER]}
    for _ in range(16):
        result = send(cid, answers, auto=auto_attacker)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED', result
        prompt = result['reaction']
        source = prompt['context']['reaction_source_id']
        selected = picks.get(source, [])
        if source == 'choice:needle.interpose_destination':
            selected = [prompt['choice']['options'][0]['id']]
        assert reload(tmp_path, mid).state.model_dump(mode='json') == before_state
        answer = {**prompt['context'], 'selection': 'USE' if selected else 'DECLINE'}
        if selected:
            assert set(selected) <= {o['id'] for o in prompt['choice']['options']}
            answer['option_ids'] = selected
        answers.append(answer)
    else:
        pytest.fail('distinct-ray choices did not commit')
    engine = reload(tmp_path, mid)
    events = engine.events[before:]
    rolls = [e for e in events if e.event_type == "ATTACK_ROLLED"]
    damage = [e for e in events if e.event_type == "DAMAGE_ROLLED"]
    assert len(rolls) == len(damage) == 2  # up to five rays; two distinct targets
    assert rolls[0].target_ids == damage[0].target_ids == (OWNER,)
    assert [e.target_ids for e in rolls] == [e.target_ids for e in damage]
    committed = [e for e in events if e.event_type == "DAMAGE_COMMITTED"]
    expected_packets = [int(e.payload["total"]) // (2 if i == 0 else 1) for i, e in enumerate(damage)]
    assert [e.target_ids for e in committed] == [e.target_ids for e in damage]
    assert [int(e.payload["hp_damage"]) for e in committed] == expected_packets
    for who in (OWNER, SECOND):
        expected = sum(amount for e, amount in zip(damage, expected_packets) if who in e.target_ids)
        assert before_state["actors"][who]["current_hp"] - engine.state.actors[who].current_hp == expected
    assert guardian_chassis.stored(engine.state.actors[OWNER]) == 0
    assert any("Held Harm is unavailable" in e.payload.get("log", "") for e in events if e.event_type == "PASSIVE_TRIGGERED")


# ================================================================================================= GUARDIAN: Held Harm
def test_held_harm_waits_for_damage_deferral_seam():
    """Held Harm: "redirect any amount of the remaining damage into your Held Harm Pool ... At the end of each of your turns: take all
    damage stored in your Held Harm Pool as one damage instance ... then reduce your Held Harm Pool to 0." Pool: 3 x CL."""
    guardian = bundle(CHALLENGE, cl=10, hp=200)
    engine = fight(guardian, me_at=(3, 6), foe_at=(6, 6))
    sure_hit(engine, ME)
    me = engine.state.actors[ME]
    turn(engine, FOE)
    hp = me.current_hp
    events = use(engine, "Seed-Thorn Strike", target=ME)
    dealt = next(e for e in events if e.event_type == "DAMAGE_COMMITTED" and ME in e.target_ids)
    assert dealt.payload["hp_damage"] > 0 and me.current_hp == hp - dealt.payload["hp_damage"]
    assert not held(me, "held_harm")
    assert any("Held Harm is unavailable" in e.payload.get("log", "") for e in events if e.event_type == "PASSIVE_TRIGGERED")


def test_held_harm_pool_is_three_times_cl_plus_deep_reservoir():
    from combat.ext import guardian_chassis

    engine = fight(bundle(CHALLENGE, G + "DEEP_RESERVOIR", cl=7))
    assert guardian_chassis.maximum(engine, engine.state.actors[ME]) == 3 * 7 + 7
    plain = fight(bundle(PATROL, cl=7))
    assert guardian_chassis.maximum(plain, plain.state.actors[ME]) == 21  # a Patrol-only Guardian has the pool too
    none = fight(bundle(SEED, cl=7))
    assert guardian_chassis.core_row(none, none.state.actors[ME]) is None


def test_healing_over_maximum_reduces_held_harm():
    from combat.ext import guardian_chassis

    engine = fight(bundle(CHALLENGE, cl=10, hp=60))
    me = engine.state.actors[ME]
    guardian_chassis._set_stored(engine, me, 12, guardian_chassis.HELD_SOURCE)
    ctx = typed_executor.Context(engine, me, engine.action_catalog[me.action_ids[0]], None,
                                 {"numbers": {"pb": 4, "cl": 10}, "effects": []}, [me], me, {})
    typed_executor.run_effects(ctx, [{"type": "healing", "applies_to": "self", "flat": 5}])
    assert guardian_chassis.stored(me) == 7  # at full HP, all 5 points were excess


def test_interpose_and_held_harm_at_the_table_ask_the_player_and_survive_reload(tmp_path):
    """At the table, a manual Guardian set to Ask me is asked twice when a foe attacks its ally: Interpose (naming the attack, the
    attacker and the ally) and Held Harm for the damage; after a commit and a reload the Guardian stands beside the ally, holds the
    damage, and the fight replays."""
    from tests.r1i_service_support import FOE as TFOE, OWNER, SECOND, fixture
    from tests.test_r1i_round3 import reload, resolve

    combat, table, mid, send, commit = fixture(tmp_path, [CHALLENGE], foe_talents=[SEED], allies=(SECOND,),
                                                positions={OWNER: {"x": 3, "y": 6}, SECOND: {"x": 3, "y": 8}, TFOE: {"x": 5, "y": 9}})
    while table.state(mid)["menu"]["actor_id"] != TFOE:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if g["label"].startswith("Seed-Thorn Strike")
               for o in g["options"] if SECOND in o.get("target_ids", []))
    _before, prompts = resolve(combat, mid, send, cid, {"choice:needle.interpose": "interpose", "choice:needle.interpose_destination": "$first",
                                                         "choice:needle.held_harm": "all"})
    asked = {p["context"]["reaction_source_id"]: str(p) for p in prompts}
    assert "choice:needle.interpose" in asked and "choice:needle.interpose_destination" in asked
    assert all(word in asked["choice:needle.interpose"] for word in ("Interpose", "Seed-Thorn Strike", "Second", "Foe"))
    engine = reload(tmp_path, mid)
    owner, second = engine.state.actors[OWNER], engine.state.actors[SECOND]
    assert engine._distance_actor_to_actor(owner, second) <= 5 and second.current_hp == second.maximum_hp
    assert not held(owner, "held_harm") and owner.current_hp < owner.maximum_hp
    assert any("Held Harm is unavailable" in e.payload.get("log", "") for e in engine.events if e.event_type == "PASSIVE_TRIGGERED")


def test_held_harm_disabled_route_is_logged_at_the_table(tmp_path):
    """The owner may redirect any amount up to capacity; the chosen pool value survives a table commit and reload."""
    from tests.r1i_service_support import FOE as TFOE, OWNER, fixture, candidate
    from tests.test_r1i_round3 import reload, resolve

    combat, table, mid, send, commit = fixture(tmp_path, [CHALLENGE], foe_talents=[SEED], foe_ac=0,
                                                positions={OWNER: {"x": 3, "y": 6}, TFOE: {"x": 5, "y": 9}})
    while table.state(mid)["menu"]["actor_id"] != TFOE:
        commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, "Seed-Thorn Strike", OWNER)
    resolve(combat, mid, send, cid, {})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert not held(owner, "held_harm")
    assert any("Held Harm is unavailable" in e.payload.get("log", "") for e in engine.events if e.event_type == "PASSIVE_TRIGGERED")
    damage = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and OWNER in e.target_ids]
    assert damage and damage[-1].payload["hp_damage"] > 0 and owner.current_hp < owner.maximum_hp


AXE = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu", "name": "Fu (Short Axe)", "quantity": 1}]}}


def weapon(engine, actor_id=ME):
    return next(engine.action_catalog[a].display_name for a in engine.state.actors[actor_id].action_ids
                if engine.action_catalog[a].display_name.endswith(" attack") and "Improvised" not in engine.action_catalog[a].display_name)


def foe_context(engine, *, dc=50):
    foe = engine.state.actors[FOE]
    action = engine.action_catalog[next(a for a in foe.action_ids if engine.action_catalog[a].display_name.startswith("Seed-Thorn"))]
    typed = {**action.parameters["typed"], "numbers": {**action.parameters["typed"]["numbers"], "save_dc": dc, "pb": 3}}
    me = engine.state.actors[ME]
    return typed_executor.Context(engine, foe, action, None, typed, [me], me, {})


def frighten(engine):
    typed_executor.run_effects(foe_context(engine), [{"type": "save", "ability": "wis", "applies_to": "target", "on_success": [],
                                                      "on_fail": [{"type": "condition", "condition": "frightened", "applies_to": "target",
                                                                   "duration": "until_end_of_target_next_turn"}]}])


def test_durable_disabled_route_leaves_condition_immediate():
    """Durable: "When you fail a saving throw against ... Frightened ... you may reserve 10 points of empty space in your Held Harm Pool
    ... delay the effect until the end of your next turn. The reserved space counts against your Held Harm maximum.\""""
    from combat.ext import guardian_chassis

    engine = fight(bundle(CHALLENGE, G + "DURABLE", cl=10))
    me = engine.state.actors[ME]
    frighten(engine)
    assert held(me, "frightened") and not held(me, "guardian_delay")
    assert guardian_chassis.room(engine, me) == 30
    assert any("Delaying a condition" in e.payload.get("log", "") for e in engine.events if e.event_type == "PASSIVE_TRIGGERED")


def test_durable_disabled_route_at_table_commits_and_reloads(tmp_path):
    """The table records the immediate condition and GM note, with no delayed reservation after reload."""
    from copy import deepcopy
    from combat.canonical import canonical_sha256
    from tests.r1i_service_support import FOE as TFOE, OWNER, fixture, candidate
    from tests.test_r1i_round3 import reload, resolve

    def add_frighten_probe(bundles):
        foe = next(b for b in bundles if b["actor_id"] == TFOE)
        base = next(a for a in foe["action_catalog"] if a["display_name"] == "Seed-Thorn Strike")
        probe = deepcopy(base)
        probe.update(source_definition_id="test:c16.frighten_probe", display_name="Frighten Probe",
                     target_kind="HOSTILE_ENTITY", range_ft=60, economy="NONE")
        probe["parameters"]["typed"].update(source="test:c16.frighten_probe", range_ft=60, effects=[{
            "type": "save", "ability": "wis", "dc": 50, "applies_to": "target", "on_success": [],
            "on_fail": [{"type": "condition", "condition": "frightened", "applies_to": "target",
                         "duration": "until_end_of_target_next_turn"}],
            "evidence": "Failed save: the target is Frightened until the end of its next turn."}])
        foe["action_catalog"].append(probe)
        foe["actor_template"]["action_ids"].append(probe["source_definition_id"])
        foe.pop("bundle_sha256", None)
        foe["bundle_sha256"] = canonical_sha256(foe)

    combat, table, mid, send, commit = fixture(tmp_path, [CHALLENGE, G + "DURABLE"], foe_talents=[SEED],
        bundle_transform=add_frighten_probe, positions={OWNER: {"x": 3, "y": 6}, TFOE: {"x": 5, "y": 9}})
    while table.state(mid)["menu"]["actor_id"] != TFOE:
        commit(table.state(mid)["menu"]["end_turn"])
    resolve(combat, mid, send, candidate(table, mid, "Frighten Probe", OWNER), {})
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert held(owner, "frightened") and not held(owner, "guardian_delay")
    assert any("Delaying a condition" in e.payload.get("log", "") for e in engine.events if e.event_type == "PASSIVE_TRIGGERED")


def test_without_durable_the_condition_lands_at_once():
    engine = fight(bundle(CHALLENGE, cl=10))
    frighten(engine)
    assert held(engine.state.actors[ME], "frightened")


def test_punishment_returned_sends_the_held_damage_back():
    """Punishment Returned: a melee weapon hit while the pool holds damage, Martial Focus: "The target makes a Constitution saving
    throw. Failed Save: Take additional damage equal to the current damage stored in your Held Harm Pool ... Punishment Returned does
    not empty or reduce your Held Harm Pool.\""""
    from combat.ext import guardian_chassis

    guardian = compile_character(sheet([CHALLENGE, G + "PUNISHMENT_RETURNED"], cl=10, dc=50, kit=AXE), actor_id=ME)
    engine = fight(guardian, foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    sure_hit(engine, FOE)
    me.resources[FOCUS] = 1
    guardian_chassis._set_stored(engine, me, 9, guardian_chassis.HELD_SOURCE)
    hp = foe.current_hp
    events = use(engine, weapon(engine), target=FOE)
    returned = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids and e.payload["rolled_or_pending_damage"] == 9]
    assert returned and me.resources[FOCUS] == 0 and guardian_chassis.stored(me) == 9 and foe.current_hp < hp - 9 + 1


def test_court_cover_is_inert_without_a_guardian():
    """An unrelated fight must not receive a cover answer from Guardian's plug-in."""
    from combat import ext

    engine = fight(bundle(), ally=bundle(actor_id=ALLY))
    ally, foe = (engine.state.actors[i] for i in (ALLY, FOE))
    assert ext.run("cover", engine, foe, ally) == []


def test_court_of_the_unbroken_gate_raises_the_pool_and_shields_allies():
    """Court of the Unbroken Gate: "Increase your Held Harm Pool maximum by your Cultivation Level ... Allies Inside the Court: Gain +1
    AC ... Enemies Inside the Court: Treat spaces adjacent to you as difficult terrain.\""""
    from combat import ext, zones
    from combat.ext import guardian_chassis

    engine = fight(bundle(CHALLENGE, G + "COURT_OF_THE_UNBROKEN_GATE", cl=12), ally=bundle(actor_id=ALLY), ally_at=(3, 8), foe_at=(8, 6))
    me, ally, foe = (engine.state.actors[i] for i in (ME, ALLY, FOE))
    assert ext.run("cover", engine, foe, ally) == []  # owning the talent alone grants nothing
    me.resources[FOCUS] = 1
    ac, ally_ground = engine._ac_modifier(ally), zones.difficult_cells(engine, ally)
    use(engine, "Court of the Unbroken Gate")
    assert guardian_chassis.court_active(engine, me) and guardian_chassis.maximum(engine, me) == 3 * 12 + 12
    assert engine._ac_modifier(ally) == ac + 1
    assert ext.run("cover", engine, foe, ally) == [2]  # Half Cover inside 10 feet
    assert ext.run("cover", engine, foe, me) == []  # the Guardian is not its own ally
    assert ext.run("cover", engine, me, foe) == []  # enemies receive no cover
    from combat.gate2_runtime_models import Position

    near = ally.position
    ally.position = Position(x=3, y=9)
    assert ext.run("cover", engine, foe, ally) == []  # 15 feet: inside Court, outside its cover
    ally.position = near
    (ground,) = guardian_chassis.court_ground(engine)
    beside = {(c.x, c.y) for c in ground.affected_cells}
    assert (4, 6) in beside and beside <= zones.difficult_cells(engine, foe) and zones.difficult_cells(engine, ally) == ally_ground


def test_patrol_responds_to_a_hostile_moving_through_and_stand_still_stops_it():
    """Patrol Practice: "When a hostile creature you can perceive moves into, out of, or through your Patrol Zone, you may make one Patrol
    Response ... move up to your remaining Patrol Movement ... make one opportunity attack against that creature." Stand Still: "When you
    hit a hostile creature with a Patrol attack, reduce its Speed to 0 until the start of its next turn.\""""
    engine = fight(bundle(PATROL, G + "STAND_STILL", hp=200), foe_at=(9, 3))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    sure_hit(engine, FOE)
    events = use(engine, "Patrol Practice")
    (state,) = held(me, "guardian_patrol")
    assert state.data["zones"] == "stand_still" and state.data["radius_ft"] == 15
    turn(engine, FOE)
    hp = foe.current_hp
    events = use(engine, "Move to 5,4")
    assert not any(e.event_type == "REACTION_RESOLVED" and e.payload.get("reaction") == "patrol_response" for e in events)
    assert foe.current_hp == hp and me.reaction_available
    assert any("unavailable until movement validates opportunity attacks" in e.payload.get("log", "")
               for e in events if e.event_type == "PASSIVE_TRIGGERED")


def test_steel_hedge_and_assist_the_line_follow_the_patrol():
    from combat import zones

    guardian = bundle(PATROL, G + "STEEL_HEDGE", "tianxia.talent.guardian.assist_the_line", G + "COMPLEX_PATROL")
    engine = fight(guardian, ally=bundle(actor_id=ALLY), ally_at=(3, 8), foe_at=(12, 6))
    me, ally, foe = (engine.state.actors[i] for i in (ME, ALLY, FOE))
    me.resources[FOCUS] = 1
    ac = engine._ac_modifier(ally)
    use(engine, "Patrol Practice")
    (state,) = held(me, "guardian_patrol")
    assert set(state.data["zones"].split(",")) == {"steel_hedge", "assist_the_line"} and me.resources[FOCUS] == 0  # Complex Patrol
    from combat.ext import guardian_patrol

    (hedge,) = guardian_patrol.steel_hedge(engine)
    cells = {(c.x, c.y) for c in hedge.affected_cells}
    assert (5, 6) in cells and cells <= zones.difficult_cells(engine, foe) and not cells <= zones.difficult_cells(engine, ally)
    assert engine._ac_modifier(ally) == ac + 1


POLEARM = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.ge", "name": "Ge (Dagger-Axe)", "quantity": 1}]}}


@pytest.mark.parametrize("ai_mover", [False, True])
@pytest.mark.parametrize("spent_by", ["patrol", "interpose"])
def test_patrol_physical_reach_survives_spent_reaction_table(tmp_path, ai_mover, spent_by):
    """A reach weapon keeps its 20-foot zone and 10-foot response reach after a Reaction is spent."""
    from combat.ext import guardian_patrol
    from tests.r1i_service_support import FOE as TFOE, OWNER, SECOND, candidate, fixture, force_ai_candidate
    from tests.test_r1i_round3 import reload, resolve

    combat, table, mid, send, commit = fixture(
        tmp_path, [PATROL, G + "STEEL_HEDGE"], owner_kit=POLEARM, foe_talents=[SEED], foe_ac=0,
        allies=[SECOND] if spent_by == "interpose" else (),
        positions={OWNER: {"x": 3, "y": 6}, TFOE: {"x": 5, "y": 6}, SECOND: {"x": 3, "y": 8}})
    commit(candidate(table, mid, "Patrol Practice"))
    while table.state(mid)["menu"]["actor_id"] != TFOE:
        commit(table.state(mid)["menu"]["end_turn"])
    if spent_by == "patrol":
        cid = next(o["candidate_id"] for o in table.state(mid)["menu"]["moves"] if o["destination"] == {"x": 5, "y": 5})
        picks = {"choice:needle.patrol_response": "respond"}
    else:
        cid = candidate(table, mid, "Seed-Thorn Strike", SECOND)
        picks = {"choice:needle.interpose": "interpose", "choice:needle.interpose_destination": "$first"}
    if ai_mover:
        force_ai_candidate(combat, mid, TFOE, cid)
    _, prompts = resolve(combat, mid, send, cid, picks, auto=ai_mover)
    assert any(p["context"]["reaction_source_id"] in picks for p in prompts)
    engine = reload(tmp_path, mid)
    guardian = engine.state.actors[OWNER]
    # The unrelated ordinary opportunity attack may consume a Reaction; the
    # disabled Patrol route itself leaves no Patrol Response event or movement.
    assert guardian_patrol.radius(engine, guardian) == 20
    if spent_by == "patrol":
        assert guardian.position.model_dump(mode="json") == {"x": 3, "y": 6}
        combat.set_controller_mode(mid, actor_id=TFOE, controller_mode="MANUAL")
        commit(table.state(mid)["menu"]["end_turn"])
        while table.state(mid)["menu"]["actor_id"] != SECOND:
            commit(table.state(mid)["menu"]["end_turn"])
        # This path ends outside the Ge's 10-foot reach, so a response would
        # have to move and must take the disabled route.
        cid = next(o["candidate_id"] for o in table.state(mid)["menu"]["moves"] if o["destination"] == {"x": 7, "y": 7})
        _, prompts = resolve(combat, mid, send, cid, picks)
        engine = reload(tmp_path, mid)
        guardian = engine.state.actors[OWNER]
        assert guardian.position.model_dump(mode="json") == {"x": 3, "y": 6}
        assert any("unavailable until movement validates opportunity attacks" in e.payload.get("log", "")
                   for e in engine.events if e.event_type == "PASSIVE_TRIGGERED")
        assert guardian_patrol.radius(engine, guardian) == 20
    (hedge,) = guardian_patrol.steel_hedge(engine)
    assert any(engine._distance_actor_to_cell(guardian, cell) == 20 for cell in hedge.affected_cells)


# ================================================================================================= BRUTE: the Brutal Shove contest
SHOVE, BR = "BRUTE_BASE_BRUTAL_SHOVE", "TAL_BRUTE_"


def brute(*talents, cl=10, score=16, dc=16):
    return bundle(SHOVE, "BRUTE_BASE_BRUTE_MANEUVERS", *talents, cl=cl, score=score, dc=dc)


def resists(engine, who, value):
    engine.state.actors[who].skills = {"Athletics": value, "Acrobatics": value}


def checks(events, who):
    return [e for e in events if e.event_type == "CHECK_ROLLED" and who in (e.target_ids or ())]


def test_brutal_shove_is_an_athletics_contest_the_target_can_win():
    """Brutal Shove: "Make: Strength (Athletics) contested by the target's: Strength (Athletics) or Dexterity (Acrobatics)" -- no
    attack roll; a target that wins the contest stays where it is, unharmed."""
    engine = fight(brute(), foe_at=(4, 6))
    resists(engine, FOE, 100)
    foe = engine.state.actors[FOE]
    where, hp = foe.position, foe.current_hp
    events = use(engine, "Brutal Shove", target=FOE)
    (contest,) = checks(events, FOE)
    assert not contest.payload["success"] and contest.payload["against"] in ("Athletics", "Acrobatics")
    assert not [e for e in events if e.event_type == "ATTACK_ROLLED"]
    assert foe.position == where and foe.current_hp == hp and not held(foe, "prone")


def test_a_successful_shove_knocks_prone_moves_by_the_margin_and_deals_strength_damage():
    """"Success: Choose to push the target 5 feet away or give it the Prone condition. Then: move it an additional 5 feet for every 5
    points by which your Athletics check exceeds its opposing check; apply this additional movement even when you chose Prone; deal
    Bludgeoning damage equal to your Strength modifier, minimum 0." (the built-in AI knocks a standing target Prone)"""
    engine = fight(brute(score=16), foe_at=(4, 6))
    resists(engine, FOE, -20)
    foe = engine.state.actors[FOE]
    x0, hp = foe.position.x, foe.current_hp
    events = use(engine, "Brutal Shove", target=FOE)
    (contest,) = checks(events, FOE)
    margin = contest.payload["actor"]["total"] - contest.payload["target"]["total"]
    assert contest.payload["success"] and held(foe, "prone")
    assert (foe.position.x - x0) * 5 == min(5 * (margin // 5), (19 - x0) * 5)  # the extra movement, even after Prone (map edge at x=19)
    assert hp - foe.current_hp == 3  # Strength 16: +3 Bludgeoning


def test_greater_brute_is_expertise_in_the_contest():
    """Greater Brute: "Gain Expertise in Strength (Athletics)" -- the contest adds twice the Proficiency Bonus."""
    engine = fight(brute(BR + "GREATER_BRUTE", score=16), foe_at=(4, 6))
    events = use(engine, "Brutal Shove", target=FOE)
    (contest,) = checks(events, FOE)
    assert contest.payload["actor"]["modifier"] == 3 + 2 * 4


def test_rooted_stance_resists_shoves_with_advantage_and_one_size_larger():
    """Rooted Stance (holding Martial Focus): "gain Advantage on checks and saving throws against forced movement ... count as one size
    larger when resisting Shove and Overrun"."""
    from combat.ext import brute_shove

    engine = fight(bundle(SEED, actor_id=ME), foe=bundle(SHOVE, BR + "ROOTED_STANCE", actor_id=FOE), foe_at=(4, 6))
    foe = engine.state.actors[FOE]
    foe.resources[FOCUS] = 1
    ctx = typed_executor.Context(engine, engine.state.actors[ME], engine.action_catalog[engine.state.actors[ME].action_ids[0]], None,
                                 {"numbers": {"pb": 4}}, [foe], foe, {})
    row = {"type": "brutal_shove"}
    assert typed_executor.size_width(ctx, foe, "subject", row) == 2
    assert brute_shove.rooted_stance_contest(engine, foe, "resist", "shove", engine.state.actors[ME]) == "ADVANTAGE"
    foe.resources[FOCUS] = 0
    assert typed_executor.size_width(ctx, foe, "subject", row) == 1


def test_manhandle_variants_ride_a_successful_shove_only():
    """Manhandle talents: "A Manhandle talent modifies one Brutal Shove ... apply it only on a successful shove." Humiliate: "The target
    makes a Dexterity saving throw. Failed Save: Its Speed becomes 0 until the end of its next turn.\""""
    engine = fight(brute(BR + "HUMILIATE", BR + "DIZZY_SPIN", BR + "THROW", dc=50), foe_at=(4, 6))
    names = {c.display_name for c in engine.legal_candidates()}
    assert {"Brutal Shove + Humiliate", "Brutal Shove + Dizzy Spin", "Brutal Shove + Throw"} <= names
    resists(engine, FOE, 100)
    events = use(engine, "Brutal Shove + Humiliate", target=FOE)
    assert not [e for e in events if e.event_type == "SAVE_ROLLED"]  # a failed shove applies no Manhandle talent
    turn(engine, ME)
    resists(engine, FOE, -50)
    events = use(engine, "Brutal Shove + Humiliate", target=FOE)
    assert [e for e in events if e.event_type == "SAVE_ROLLED" and FOE == e.actor_id or FOE in (e.target_ids or ())]
    assert engine._effective_speed(engine.state.actors[FOE]) == 0


@pytest.mark.parametrize("legacy", [False, True])
def test_overrun_contest_does_not_fabricate_movement(legacy):
    """Brute Maneuvers, Overrun: "As an Action or Bonus Action, attempt to move through one hostile creature's space. Make: Strength
    (Athletics) contested by the target's: Strength (Athletics) ... Success: Move through the hostile creature's space ... Treat that
    space as difficult terrain, and do not end movement in an occupied space.\""""
    packet = brute()
    if legacy:
        from tests.cw2_service_support import seal
        for action in packet['action_catalog']:
            for row in ((action.get('parameters') or {}).get('typed') or {}).get('effects') or []:
                row.pop('named_passage', None)
        seal(packet)
    engine = fight(packet, foe_at=(4, 6))
    me = engine.state.actors[ME]
    resists(engine, FOE, -50)
    assert {"Overrun", "Overrun (Bonus Action)"} <= {c.display_name for c in engine.legal_candidates()}
    start = (me.position.x, me.position.y)
    moved = me.movement_remaining_ft
    events = use(engine, "Overrun (Bonus Action)", target=FOE)
    (contest,) = checks(events, FOE)
    assert contest.payload["contest"] == "overrun" and contest.payload["against"] == "Athletics"
    assert (me.position.x, me.position.y) == start and me.movement_remaining_ft == moved
    if legacy:
        assert any("GM must move" in line and "by hand" in line for line in logs(events))
    else:
        assert any("once this turn using your movement" in line for line in logs(events))
    assert any(c.condition_id == 'condition:typed.named_creature_passage' for c in me.conditions.values()) == (not legacy)
    assert not me.bonus_action_available and me.action_available


@pytest.mark.parametrize("legacy", [False, True])
def test_overrun_at_table_commits_note_without_moving_actor(tmp_path, legacy):
    """Winning grants optional passage; historical unmarked packets keep their old GM note."""
    from combat.canonical import canonical_sha256
    from tests.r1i_service_support import FOE as TFOE, OWNER, candidate, fixture
    from tests.test_r1i_round3 import reload, resolve

    def clumsy(bundles):
        for b in bundles:
            if legacy:
                for action in b['action_catalog']:
                    for row in ((action.get('parameters') or {}).get('typed') or {}).get('effects') or []:
                        row.pop('named_passage', None)
            if b["actor_id"] == TFOE:
                b["skills"] = {"Athletics": -50, "Acrobatics": -50}
            b.pop("bundle_sha256", None)
            b["bundle_sha256"] = canonical_sha256(b)

    combat, table, mid, send, _commit = fixture(
        tmp_path, [SHOVE, "BRUTE_BASE_BRUTE_MANEUVERS"],
        positions={OWNER: {"x": 3, "y": 6}, TFOE: {"x": 4, "y": 6}}, bundle_transform=clumsy)
    before = reload(tmp_path, mid)
    start = before.state.actors[OWNER].position.model_dump(mode="json")
    cid = candidate(table, mid, "Overrun", TFOE)
    resolve(combat, mid, send, cid, {})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].position.model_dump(mode="json") == start
    notes = [str((e.payload or {}).get("log") or "") for e in engine.events if e.event_type == "PASSIVE_TRIGGERED"]
    if legacy:
        assert any("wins the Overrun contest" in line and "GM must move" in line and "by hand" in line for line in notes)
    else:
        assert any("once this turn using your movement" in line for line in notes)
    assert any(c.condition_id == 'condition:typed.named_creature_passage' for c in engine.state.actors[OWNER].conditions.values()) == (not legacy)
    assert not [e for e in engine.events if e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == OWNER]


def test_shove_aside_has_disadvantage_unless_alternative_maneuvers():
    """Shove Aside: "Make the Brutal Shove contest with Disadvantage"; Alternative Maneuvers: "You do not suffer Disadvantage when using
    Shove Aside.\""""
    engine = fight(brute(), foe_at=(4, 6))
    resists(engine, FOE, -50)
    events = use(engine, "Shove Aside", target=FOE)
    (contest,) = checks(events, FOE)
    assert contest.payload["actor"]["mode"] == "DISADVANTAGE" and contest.payload["success"]
    foe = engine.state.actors[FOE]
    assert (foe.position.x, foe.position.y) != (4, 6) and engine._distance_actor_to_actor(engine.state.actors[ME], foe) <= 5
    alt = fight(brute("tianxia.talent.brute.alternative_maneuvers"), foe_at=(4, 6))
    events = use(alt, "Shove Aside", target=FOE)
    assert checks(events, FOE)[0].payload["actor"]["mode"] != "DISADVANTAGE"


def test_shove_aside_uses_weapon_reach_after_reaction_is_spent():
    """Shove Aside's own legal-space radius uses the weapon profile, not Reaction availability."""
    engine = fight(compile_character(sheet([SHOVE, "BRUTE_BASE_BRUTE_MANEUVERS"], kit=POLEARM), actor_id=ME), foe_at=(4, 6))
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    from combat.typed_reactions import physical_melee_reach

    assert physical_melee_reach(engine, me) == 10
    resists(engine, FOE, -50)
    me.reaction_available = False
    events = use(engine, "Shove Aside", target=FOE)
    assert checks(events, FOE)[0].payload["success"]
    assert engine.grid.distance_between_cell_sets_ft(engine._actor_cells(me), engine._actor_cells(foe)) == 10


def test_shove_aside_spent_reaction_uses_weapon_reach_at_table(tmp_path):
    """A spent Reaction does not reduce Shove Aside's weapon-reach choices in the table flow."""
    from tests.r1i_service_support import FOE as TFOE, OWNER, fixture
    from tests.test_r1i_round3 import reload

    from combat.canonical import canonical_sha256

    def clumsy(bundles):
        for actor in bundles:
            if actor["actor_id"] == TFOE:
                actor["skills"] = {"Athletics": -50, "Acrobatics": -50}
                actor.pop("bundle_sha256", None)
                actor["bundle_sha256"] = canonical_sha256(actor)

    combat, table, mid, _send, _commit = fixture(
        tmp_path, [SHOVE, "BRUTE_BASE_BRUTE_MANEUVERS"], owner_kit=POLEARM,
        positions={OWNER: {"x": 3, "y": 6}, TFOE: {"x": 4, "y": 6}}, bundle_transform=clumsy)

    # A reaction may be spent before this actor's action on its turn. Seed that
    # valid state at the service load boundary; the action itself still enters
    # through the ordinary table candidate, choice, commit and reload paths.
    load_session = combat._load_session
    def load_with_spent_reaction(match_id):
        session = load_session(match_id)
        session.engine.state.actors[OWNER].reaction_available = False
        return session
    combat._load_session = load_with_spent_reaction

    menu = table.state(mid)["menu"]
    action = next(group for group in menu["actions"] if "Shove Aside" in group["label"])
    option = next(item for item in action["options"] if TFOE in item.get("target_ids", []))
    before_events = len(combat._load_session(mid).engine.events)

    answers = []
    result = None
    for _ in range(8):
        result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"], before_events, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        choice = prompt.get("choice") or {}
        options = choice.get("options", [])
        selected = next((o["id"] for o in options if o["id"] == "cell:3,8"), None)
        if prompt["context"]["reaction_source_id"] == "choice:needle.shove_aside":
            assert selected is not None
        else:
            selected = next(iter(choice.get("preferred", [])), None)
            if selected is None and options:
                selected = options[0]["id"]
        answer = {**prompt["context"], "selection": "USE" if selected else "DECLINE"}
        if selected:
            answer["option_ids"] = [selected]
        answers.append(answer)
        menu = result["state"]["menu"]
    assert result["status"] == "COMMITTED"

    engine = reload(tmp_path, mid)
    assert engine.state.actors[TFOE].position.model_dump(mode="json") == {"x": 3, "y": 8}
    assert any(e.event_type == "MOVEMENT_COMMITTED" and e.actor_id == TFOE for e in engine.events[before_events:])


def test_brutal_shove_at_the_table_asks_both_sides_and_survives_reload(tmp_path):
    """At the table: the target chooses its skill ("The target chooses its skill") and the shover chooses push or Prone; Brutal
    Manhandle asks for a second Manhandle talent for Martial Focus. After a commit and a reload the result stands and the fight
    replays."""
    from tests.r1i_service_support import FOE as TFOE, OWNER, fixture
    from tests.test_r1i_round3 import reload, resolve
    from combat.canonical import canonical_sha256

    def clumsy(bundles):
        for b in bundles:
            if b["actor_id"] == TFOE:
                b["skills"] = {"Athletics": -50, "Acrobatics": -50}
                b.pop("bundle_sha256", None)
                b["bundle_sha256"] = canonical_sha256(b)

    from tests.r1i_service_support import SECOND as TSECOND

    combat, table, mid, send, commit = fixture(tmp_path, [SHOVE, BR + "HUMILIATE", BR + "DIZZY_SPIN", BR + "BRUTAL_MANHANDLE"],
                                                bundle_transform=clumsy,
                                                positions={OWNER: {"x": 3, "y": 6}, TFOE: {"x": 4, "y": 6}, TSECOND: {"x": 3, "y": 11}})
    owner = combat._load_session(mid).engine.state.actors[OWNER]
    assert owner.resources.get(FOCUS, 0) >= 1
    cid = next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if g["label"] == "Brutal Shove + Humiliate"
               for o in g["options"] if TFOE in o.get("target_ids", []))
    _before, prompts = resolve(combat, mid, send, cid, {"choice:needle.brute_contest_skill": "Acrobatics",
                                                        "choice:needle.brutal_shove_result": "push",
                                                        "choice:needle.brutal_manhandle": "Dizzy Spin"})
    asked = {p["context"]["reaction_source_id"]: str(p) for p in prompts}
    assert {"choice:needle.brute_contest_skill", "choice:needle.brutal_shove_result", "choice:needle.brutal_manhandle"} <= set(asked)
    assert "Brutal Shove" in asked["choice:needle.brute_contest_skill"] and "Owner" in asked["choice:needle.brute_contest_skill"]
    engine = reload(tmp_path, mid)
    foe = engine.state.actors[TFOE]
    contest = next(e for e in reversed(engine.events) if e.event_type == "CHECK_ROLLED")
    assert contest.payload["against"] == "Acrobatics" and contest.payload["success"]
    assert foe.position.x > 4 and not held(foe, "prone")  # pushed (the shover's choice), not knocked Prone
    assert engine.state.actors[OWNER].resources.get(FOCUS, 0) == 0  # Brutal Manhandle spent Martial Focus
    assert any(e.event_type == "SAVE_ROLLED" and e.actor_id == TFOE for e in engine.events)


# ================================================================================================= VERDANT GROWTH
VG = "TAL_VERDANT_GROWTH_"
SOWN = VG + "SOW_LIVING_CLAIM"


def verdant(*talents, cl=10, dc=16):
    return bundle(SOWN, SEED, VG + "FEED_THE_ROOT", *talents, cl=cl, dc=dc)


def claims_of(engine, who=ME):
    from combat.ext import verdant_chassis

    return verdant_chassis.claims(engine, engine.state.actors[who])


def growth(engine, who, owner=ME):
    from combat.ext import verdant_chassis

    return verdant_chassis.marks(engine.state.actors[who], engine.state.actors[owner])


def mark(engine, who, n=1, owner=ME):
    from combat.ext import verdant_chassis

    verdant_chassis.place(engine, engine.state.actors[owner], engine.state.actors[who], n, "test")


def test_sow_living_claim_makes_a_breakable_object_with_the_printed_numbers():
    """Living Claims: "occupies one 5-foot square ... lasts for 1 minute ... AC 10; HP equal to 5 + your Proficiency Bonus + your key
    ability modifier, minimum 5; vulnerability to Fire damage ...; immunity to Poison and Psychic damage." Sow Living Claim: Bonus Action,
    within 30 feet (Qi Cultivation); at most PB claims, an old one withers."""
    engine = fight(verdant(), foe_at=(9, 6))
    use(engine, "Sow Living Claim", at=(5, 6))
    (claim,) = claims_of(engine)
    assert (claim.position.x, claim.position.y) == (5, 6) and claim.ac == 10 and claim.current_hp == 5 + 4 + 2
    assert {"POISON", "PSYCHIC"} <= set(claim.damage_immunities) and "FIRE" in claim.component["vulnerable"]
    assert not claim.component["blocks"] and not engine.state.actors[ME].bonus_action_available
    for x in (4, 6, 7, 8):  # PB 4: the fifth withers the oldest
        turn(engine, ME)
        use(engine, "Sow Living Claim", at=(x, 7))
    standing = claims_of(engine)
    assert len(standing) == 4 and (5, 6) not in {(c.position.x, c.position.y) for c in standing}


def test_growth_marks_count_up_to_pb_and_last_until_the_end_of_your_next_turn():
    """Growth Marks: "a target can hold a maximum number of your Growth Marks equal to your Proficiency Bonus; Growth Marks last until
    the end of your next turn". Seed-Thorn Strike: "place 1 Growth Mark on the target" (one, not two: Feed the Root's modifier no longer
    adds a second, endless one)."""
    engine = fight(verdant(), foe_at=(6, 6))
    sure_hit(engine, FOE)
    use(engine, "Seed-Thorn Strike", target=FOE)
    assert growth(engine, FOE) == 1
    mark(engine, FOE, 9)
    assert growth(engine, FOE) == 4
    engine.end_turn()
    assert growth(engine, FOE) == 4  # still there during the foe's turn
    turn(engine, ME)
    engine.end_turn()
    assert growth(engine, FOE) == 0  # gone at the end of the marker's next turn


LINEAGE = "tianxia.talent.verdant_growth.rooted_lineage_scripture"


@pytest.mark.parametrize("ai_owner", [False, True])
@pytest.mark.parametrize("contact", ["claim", "body", "none", "claim_lost", "body_lost", "other_claim"])
def test_rooted_lineage_extra_round_at_table_survives_reload_and_replays(tmp_path, ai_owner, contact):
    from combat.ext import verdant_chassis
    from tests.r1i_service_support import FOE as TFOE, OWNER, SECOND, candidate, fixture, force_ai_candidate
    from tests.test_r1i_round3 import reload

    combat, table, mid, send, commit = fixture(
        tmp_path, [SOWN, SEED, LINEAGE], second_talents=[SOWN] if contact == "other_claim" else (),
        positions={OWNER: {"x": 3, "y": 6}, TFOE: {"x": 4 if contact.startswith("body") else 6, "y": 6},
                   SECOND: {"x": 10, "y": 9}})

    def end_owner_turn():
        while table.state(mid)["menu"]["actor_id"] != OWNER:
            commit(table.state(mid)["menu"]["end_turn"])
        commit(table.state(mid)["menu"]["end_turn"])

    if contact.startswith("claim"):
        commit(next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if g["label"] == "Sow Living Claim"
                    for o in g["options"] if o.get("destination") == {"x": 6, "y": 6}))
    elif contact == "other_claim":
        commit(table.state(mid)["menu"]["end_turn"])
        while table.state(mid)["menu"]["actor_id"] != SECOND:
            commit(table.state(mid)["menu"]["end_turn"])
        commit(next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if g["label"] == "Sow Living Claim"
                    for o in g["options"] if o.get("destination") == {"x": 6, "y": 6}))
        while table.state(mid)["menu"]["actor_id"] != OWNER:
            commit(table.state(mid)["menu"]["end_turn"])
    cid = candidate(table, mid, "Seed-Thorn Strike", TFOE)
    if ai_owner:
        force_ai_candidate(combat, mid, OWNER, cid)
        assert send(cid, auto=True)["status"] == "COMMITTED"
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="MANUAL")
    else:
        commit(cid)
    end_owner_turn()  # the turn the mark was placed
    end_owner_turn()  # the normal deadline
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[TFOE]
    assert verdant_chassis.marks(foe, owner) == (0 if contact == "none" else 1)
    if contact != "none":
        condition = next(c for c in foe.conditions.values() if c.source_actor_id == OWNER and "growth_mark" in c.condition_id)
        assert "one additional round" in condition.data["label"]
        assert all(isinstance(v, (int, str)) for v in condition.data.values())
        if contact.endswith("_lost"):
            while table.state(mid)["menu"]["actor_id"] != TFOE:
                commit(table.state(mid)["menu"]["end_turn"])
            commit(next(o["candidate_id"] for o in table.state(mid)["menu"]["moves"]
                        if o["destination"] == {"x": 7, "y": 6}))
            engine = reload(tmp_path, mid)
            assert verdant_chassis.marks(engine.state.actors[TFOE], engine.state.actors[OWNER]) == 0
            return
        end_owner_turn()  # the additional round ends even if contact continues
        engine = reload(tmp_path, mid)
        assert verdant_chassis.marks(engine.state.actors[TFOE], engine.state.actors[OWNER]) == 0


@pytest.mark.parametrize("loses_contact", ["target_moves", "owner_moves", "claim_destroyed"])
def test_rooted_lineage_extension_ends_when_contact_is_lost(loses_contact):
    from combat.ext import verdant_chassis
    from combat.gate2_runtime_models import Position

    engine = fight(verdant(LINEAGE), foe_at=(4, 6) if loses_contact != "claim_destroyed" else (6, 6))
    if loses_contact == "claim_destroyed":
        use(engine, "Sow Living Claim", at=(6, 6))
    mark(engine, FOE, 3)
    engine.end_turn()
    turn(engine, ME)
    engine.end_turn()
    assert growth(engine, FOE) == 3
    assert verdant_chassis.spend(engine, engine.state.actors[ME], engine.state.actors[FOE], 1, "test")
    assert growth(engine, FOE) == 2  # spending preserves the extra-round deadline
    if loses_contact == "claim_destroyed":
        verdant_chassis.wither(engine, claims_of(engine)[0], "test destruction")
    else:
        who = FOE if loses_contact == "target_moves" else ME
        actor = engine.state.actors[who]
        from combat.ext.granted_moves import commit
        from combat.granted_movement import candidates
        intent = ActionIntent(intent_id='test:contact', decision_id='test:contact', candidate_id='test:contact',
                              actor_id=engine.state.current_actor_id, state_version=engine.state.state_version)
        # Use the native adjacent-space route, including occupied-square rules;
        # a two-point multi-square jump is not a legal granted walking path.
        route = next(c for c in candidates(engine, actor, 30, intent, 'test').values()
                     if c.destination == Position(x=7, y=6) and c.metadata.get('movement_mode', 'walk') == 'walk')
        commit(engine, actor, route.canonical_path, "test", budget_ft=30, intent=intent)
    assert growth(engine, FOE) == 0


def test_rooted_lineage_duration_accepts_another_cultivators_claim():
    from combat.ext import verdant_chassis

    engine = fight(verdant(LINEAGE), ally=bundle(SOWN, actor_id=ALLY), foe_at=(6, 6))
    turn(engine, ALLY)
    use(engine, "Sow Living Claim", at=(6, 6))
    turn(engine, ME)
    mark(engine, FOE)
    engine.end_turn()
    turn(engine, ME)
    engine.end_turn()
    assert growth(engine, FOE) == 1
    assert not [m for m in engine.state.actors[FOE].modifiers.values() if m.target_field == "speed_ft"]
    verdant_chassis.wither(engine, claims_of(engine, ALLY)[0], "test destruction")
    assert growth(engine, FOE) == 0


def test_rooted_lineage_spending_preserves_deadline_and_new_marks_renew_it():
    from combat.ext import verdant_chassis

    engine = fight(verdant(LINEAGE), foe_at=(4, 6))
    mark(engine, FOE, 3)
    engine.end_turn()
    turn(engine, ME)
    engine.end_turn()
    owner, foe = engine.state.actors[ME], engine.state.actors[FOE]
    assert verdant_chassis.spend(engine, owner, foe, 1, "test")
    turn(engine, ME)
    engine.end_turn()
    assert growth(engine, FOE) == 0  # spending did not renew the additional round
    turn(engine, ME)
    mark(engine, FOE, 2)
    engine.end_turn()
    turn(engine, ME)
    engine.end_turn()
    turn(engine, ME)
    mark(engine, FOE)  # a fresh mark resets both the normal deadline and the one-time extension
    engine.end_turn()
    turn(engine, ME)
    engine.end_turn()
    assert growth(engine, FOE) == 3
    turn(engine, ME)
    engine.end_turn()
    assert growth(engine, FOE) == 0


def test_root_spends_a_mark_once_per_turn_and_bites_harder_on_a_claim():
    """Root: "Spend 1 Growth Mark on a creature you can see within 60 feet. Reduce the creature's Speed by 10 feet until the start of your
    next turn. If the creature is touching a Living Claim ... reduce its Speed by 15 feet instead." Once per turn; no action."""
    engine = fight(verdant(), foe_at=(6, 6))
    foe = engine.state.actors[FOE]
    assert "Verdant Response: Root" not in {c.display_name for c in engine.legal_candidates()}  # no mark, no Root
    mark(engine, FOE, 2)
    speed = engine._effective_speed(foe)
    use(engine, "Verdant Response: Root", target=FOE)
    assert engine._effective_speed(foe) == speed - 10 and growth(engine, FOE) == 1
    me = engine.state.actors[ME]
    assert me.action_available and me.bonus_action_available  # no action spent
    assert "Verdant Response: Root" not in {c.display_name for c in engine.legal_candidates()}  # one response per turn
    engine.end_turn()
    turn(engine, ME)  # the slow from the first Root ended as this turn started
    use(engine, "Sow Living Claim", at=(6, 6))  # in the foe's space: it touches the claim
    use(engine, "Verdant Response: Root", target=FOE)
    assert engine._effective_speed(foe) == speed - 15


def test_bind_grapples_and_ends_when_its_claim_is_destroyed():
    """Bind: "Spend 2 Growth Marks ... Strength saving throw. Failed Save: The creature is Grappled by your growth until the end of your
    next turn. The escape DC is your Verdant Growth Save DC ... This grapple ends early if the relevant Living Claim is destroyed.\""""
    from combat.ext import objects, verdant_chassis

    engine = fight(verdant(dc=50), foe_at=(6, 6))
    use(engine, "Sow Living Claim", at=(6, 6))
    mark(engine, FOE, 2)
    use(engine, "Verdant Response: Bind", target=FOE)
    foe = engine.state.actors[FOE]
    (hold,) = held(foe, "grappled")
    assert hold.data["escape_dc"] == 50 and growth(engine, FOE) == 0 and hold.expires_on.startswith("END_OF_SOURCE_TURN_AT:")
    (claim,) = claims_of(engine)
    objects.deal(engine, foe, claim, [(40, "FIRE")], "test")
    assert not held(foe, "grappled") and not claims_of(engine)
    assert verdant_chassis.claims(engine, engine.state.actors[ME]) == []


def test_bind_ends_when_caster_moves_out_of_contact_at_table(tmp_path):
    """Bind ends when its target loses contact with the caster's body, and the removal survives a table reload."""
    from tests.r1i_service_support import FOE as TFOE, OWNER, fixture, candidate
    from tests.test_r1i_round3 import reload

    incarnation = "tianxia.talent.verdant_growth.verdant_incarnation_body_becomes_the_ancient_tree"
    combat, table, mid, send, commit = fixture(
        tmp_path, [SOWN, SEED, incarnation], owner_dc=50,
        positions={OWNER: {"x": 3, "y": 6}, TFOE: {"x": 4, "y": 6}})
    commit(candidate(table, mid, "Verdant Incarnation"))
    commit(candidate(table, mid, "Seed-Thorn Strike", TFOE))
    # Let the owner take another turn; Incarnation makes Bind cost one mark instead of two.
    for _ in range(3):
        commit(table.state(mid)["menu"]["end_turn"])
    assert table.state(mid)["menu"]["actor_id"] == OWNER
    commit(candidate(table, mid, "Verdant Response: Bind", TFOE))
    engine = combat._load_session(mid).engine
    assert held(engine.state.actors[TFOE], "grappled")

    options = table.state(mid)["menu"]["moves"]
    move = next(o for o in options if abs(o["destination"]["x"] - 4) + abs(o["destination"]["y"] - 6) > 1)
    commit(move["candidate_id"])
    engine = reload(tmp_path, mid)
    assert not held(engine.state.actors[TFOE], "grappled")


def test_thorn_needs_contact_and_scales_with_cl():
    """Thorn: "Spend 1 Growth Mark on a creature in contact with your Living Claim, a plant, wood, soil, or your body. The creature takes
    Piercing damage equal to your Proficiency Bonus. At CL 5, increase this to 1d6 + Proficiency Bonus.\""""
    engine = fight(verdant(cl=5), foe_at=(8, 6))
    mark(engine, FOE, 1)
    assert "Verdant Response: Thorn" not in {c.display_name for c in engine.legal_candidates()}  # not touching anything of yours
    engine.state.actors[FOE].position = type(engine.state.actors[FOE].position)(x=4, y=6)  # next to you: "your body"
    hp = engine.state.actors[FOE].current_hp
    events = use(engine, "Verdant Response: Thorn", target=FOE)
    rolled = next(e for e in events if e.event_type == "DAMAGE_ROLLED")
    assert "1d6" in rolled.payload["expression"] and hp - engine.state.actors[FOE].current_hp >= 4 + 1


def test_shelter_needs_a_claim_and_feed_the_root_pays_for_it():
    """Shelter: "Spend 1 Growth Mark on a space, object, or ally ... touching a Living Claim" -- the AI gives Temporary HP equal to PB.
    Feed the Root: a Growth Mark placed on a creature touching your claim feeds that claim; "When you use a Verdant Response from or
    through that Living Claim, you may spend 1 Root Feed as if it were 1 Growth Mark.\""""
    engine = fight(verdant(), ally=bundle(actor_id=ALLY), ally_at=(3, 8), foe_at=(5, 8))
    assert "Verdant Response: Shelter" not in {c.display_name for c in engine.legal_candidates()}
    use(engine, "Sow Living Claim", at=(5, 8))  # under the foe
    mark(engine, FOE, 1)  # the foe touches the claim: Root Feed 1
    (claim,) = claims_of(engine)
    assert claim.component["feed"] == 1
    turn(engine, ME)
    use(engine, "Sow Living Claim", at=(3, 8))  # under the ally
    ally = engine.state.actors[ALLY]
    assert "Verdant Response: Shelter" not in {c.display_name for c in engine.legal_candidates()}  # no mark and no fed claim under it
    mark(engine, ALLY, 1)
    use(engine, "Verdant Response: Shelter", target=ALLY)
    assert ally.temporary_hp == 4 and growth(engine, ALLY) == 0


@pytest.mark.parametrize("ai_attacker", [False, True])
@pytest.mark.parametrize("case", ["hit", "miss", "decline", "expiry"])
def test_shelter_next_attack_cover_at_table(tmp_path, ai_attacker, case):
    """The chosen cover survives reload, protects one hit or miss, and expires unused."""
    from tests.r1i_service_support import FOE as TFOE, OWNER, SECOND, THIRD, candidate, fixture, force_ai_candidate
    from tests.test_r1i_round3 import reload, resolve

    base_ac = 1000 if case == "miss" else 14
    combat, table, mid, send, commit = fixture(
        tmp_path, [SOWN, VG + "GROVE_DOMAIN_COURT_OF_ROOT_AND_BRANCH"],
        foe_talents=[SEED], second_talents=[SEED], foe_ac=base_ac, extra_foe=True, allies=(THIRD,),
        seed="C16-SHELTER-NEXT-ATTACK",
        positions={OWNER: {"x": 3, "y": 6}, TFOE: {"x": 4, "y": 8},
                   SECOND: {"x": 5, "y": 8}, THIRD: {"x": 3, "y": 8}})
    commit(candidate(table, mid, "Grove Domain: Court of Root and Branch"))
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    commit(next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if g["label"] == "Sow Living Claim"
                for o in g["options"] if o.get("destination") == {"x": 3, "y": 8}))
    cid = candidate(table, mid, "Verdant Response: Shelter", THIRD)
    # Declining the cover option selects Temporary HP instead; Shelter requires one option.
    _, prompts = resolve(combat, mid, send, cid, {"choice:needle.verdant_shelter": "temp_hp" if case == "decline" else "cover"})
    engine = reload(tmp_path, mid)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.verdant_shelter" for p in prompts)
    assert all(word in str(prompts) for word in ("Shelter", "Third", "Half Cover"))
    assert bool(held(engine.state.actors[THIRD], "verdant_shelter_cover")) == (case != "decline")
    if case == "expiry":
        commit(table.state(mid)["menu"]["end_turn"])
        while table.state(mid)["menu"]["actor_id"] != OWNER:
            commit(table.state(mid)["menu"]["end_turn"])
        engine = reload(tmp_path, mid)
        assert not held(engine.state.actors[THIRD], "verdant_shelter_cover")
    commit(table.state(mid)["menu"]["end_turn"])
    rolls = []
    for attacker in (TFOE, SECOND):
        while table.state(mid)["menu"]["actor_id"] != attacker:
            commit(table.state(mid)["menu"]["end_turn"])
        engine = reload(tmp_path, mid)
        before = len(engine.events)
        cid = candidate(table, mid, "Seed-Thorn Strike", THIRD)
        if ai_attacker:
            force_ai_candidate(combat, mid, attacker, cid)
            assert send(cid, auto=True)["status"] == "COMMITTED"
            combat.set_controller_mode(mid, actor_id=attacker, controller_mode="MANUAL")
        else:
            commit(cid)
        engine = reload(tmp_path, mid)
        attack_rolls = [e for e in engine.events[before:] if e.event_type == "ATTACK_ROLLED" and THIRD in e.target_ids]
        assert len(attack_rolls) == 1
        rolls.append(attack_rolls[0])
        assert not held(engine.state.actors[THIRD], "verdant_shelter_cover")
        commit(table.state(mid)["menu"]["end_turn"])
    assert [e.payload["target_ac"] for e in rolls] == [base_ac + (2 if case in ("hit", "miss") else 0), base_ac]
    assert all(bool(e.payload["provisional_hit"]) == (case != "miss") for e in rolls)
    removed = [e for e in engine.events if e.event_type == "CONDITION_REMOVED"
               and e.payload.get("condition_id") == "condition:typed.verdant_shelter_cover"]
    assert len(removed) == (0 if case == "decline" else 1)


def test_thorned_warning_marks_a_creature_that_damages_a_claim():
    """Thorned Warning: "When a creature damages or destroys one of your Living Claims, place 1 Growth Mark on that creature if it is
    within 60 feet and you can perceive it.\""""
    from combat.ext import objects

    engine = fight(verdant(VG + "THORNED_WARNING"), foe_at=(6, 6))
    use(engine, "Sow Living Claim", at=(5, 6))
    (claim,) = claims_of(engine)
    objects.deal(engine, engine.state.actors[FOE], claim, [(2, "SLASHING")], "test")
    assert growth(engine, FOE) == 1


@pytest.mark.parametrize("ai_owner", [False, True])
@pytest.mark.parametrize("expired", [False, True])
def test_thorned_warning_off_turn_bonus_and_expiry_at_table(tmp_path, ai_owner, expired):
    """An enemy damages a claim off-turn; Thorn's bonus lasts through the owner's next turn, then ends."""
    from combat.ext import verdant_chassis
    from tests.r1i_service_support import FOE as TFOE, OWNER, SECOND, candidate, fixture, force_ai_candidate
    from tests.test_r1i_round3 import reload

    combat, table, mid, send, commit = fixture(
        tmp_path, [SOWN, SEED, VG + "THORNED_WARNING"], foe_ac=0,
        seed="C16-THORNED-OFF-TURN-1",
        positions={OWNER: {"x": 3, "y": 6}, TFOE: {"x": 4, "y": 6},
                   SECOND: {"x": 10, "y": 9}})
    commit(next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if g["label"] == "Sow Living Claim"
                for o in g["options"] if o.get("destination") == {"x": 4, "y": 6}))
    engine = reload(tmp_path, mid)
    claim_id = verdant_chassis.claims(engine, engine.state.actors[OWNER])[0].object_id
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != TFOE:
        commit(table.state(mid)["menu"]["end_turn"])
    commit(candidate(table, mid, "Attack an object", claim_id))
    engine = reload(tmp_path, mid)
    assert any(e.event_type == "OBJECT_UPDATED" and e.actor_id == TFOE
               and int((e.payload.get("damage") or {}).get("taken") or 0) > 0 for e in engine.events)
    assert verdant_chassis.marks(engine.state.actors[TFOE], engine.state.actors[OWNER]) == 1
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)  # the bug discarded its turn flag here
    warning_id = f"condition:typed.verdant_thorned.{TFOE}"
    warnings = [c for c in engine.state.actors[OWNER].conditions.values() if c.condition_id == warning_id]
    if expired:
        assert len(warnings) == 1
        assert all(isinstance(v, (int, str)) for v in warnings[0].data.values())
        commit(table.state(mid)["menu"]["end_turn"])
        engine = reload(tmp_path, mid)
        assert not any(c.condition_id == warning_id for c in engine.state.actors[OWNER].conditions.values())
        assert any(e.event_type == "CONDITION_REMOVED" and e.payload.get("condition_id") == warning_id
                   for e in engine.events)
        while table.state(mid)["menu"]["actor_id"] != OWNER:
            commit(table.state(mid)["menu"]["end_turn"])
        commit(candidate(table, mid, "Seed-Thorn Strike", TFOE))  # new ordinary mark, after Warning's deadline
        engine = reload(tmp_path, mid)
        assert verdant_chassis.marks(engine.state.actors[TFOE], engine.state.actors[OWNER]) == 1
    cid = candidate(table, mid, "Verdant Response: Thorn", TFOE)
    engine = reload(tmp_path, mid)
    before, hp = len(engine.events), engine.state.actors[TFOE].current_hp
    if ai_owner:
        force_ai_candidate(combat, mid, OWNER, cid)
        assert send(cid, auto=True)["status"] == "COMMITTED"
    else:
        commit(cid)
    engine = reload(tmp_path, mid)
    rolled = [e for e in engine.events[before:] if e.event_type == "DAMAGE_ROLLED" and TFOE in e.target_ids]
    assert len(rolled) == 1
    # The harness is CL 17, PB 4, key modifier +2: assert the exact packet, not just HP loss.
    assert rolled[0].payload["expression"] == f"3d6+{4 if expired else 6}"
    assert hp - engine.state.actors[TFOE].current_hp == rolled[0].payload["total"]
    if not expired:
        assert len(warnings) == 1
        assert all(isinstance(v, (int, str)) for v in warnings[0].data.values())


def test_bramble_refusal_spends_a_mark_against_a_marked_melee_attacker():
    """Bramble Refusal: "When a creature with one of your Growth Marks makes a melee attack against you ..., spend 1 Growth Mark. The
    creature takes 1d8 Piercing damage and makes a Dexterity saving throw. Failed Save: It has Disadvantage on the triggering attack.\""""
    from combat.ext import verdant_chassis

    engine = fight(verdant(VG + "BRAMBLE_REFUSAL", dc=50), foe_at=(4, 6))
    mark(engine, FOE, 2)
    foe = engine.state.actors[FOE]
    hp = foe.current_hp
    answer = verdant_chassis.bramble_refusal(engine, foe, engine.state.actors[ME], None, {"range_ft": 5, "effect": {"attack_kind": "melee"}})
    assert answer == {"mode": "DISADVANTAGE"} and growth(engine, FOE) == 1 and foe.current_hp < hp
    plain = fight(verdant(dc=50), foe_at=(4, 6))
    mark(plain, FOE, 2)
    assert verdant_chassis.bramble_refusal(plain, plain.state.actors[FOE], plain.state.actors[ME], None, {"range_ft": 5}) is None


def test_willow_bend_shortens_a_push_while_touching_a_claim():
    """Willow-Bend Defense: "When you are pushed ... while touching a Living Medium, reduce the forced movement by 10 feet.\""""
    from combat.ext import verdant_chassis

    engine = fight(verdant(VG + "WILLOW_BEND_DEFENSE"), foe_at=(4, 6))
    me = engine.state.actors[ME]
    ctx = typed_executor.Context(engine, engine.state.actors[FOE], engine.action_catalog[engine.state.actors[FOE].action_ids[0]], None,
                                 {"numbers": {"pb": 3}}, [me], me, {})
    assert verdant_chassis.willow_bend(ctx, me) is None  # not touching a Living Medium
    use(engine, "Sow Living Claim", at=(3, 6))  # on its own body
    assert verdant_chassis.willow_bend(ctx, me) == 10


def test_grove_domain_sows_marks_shelters_and_pays_one_response_a_round():
    """Grove Domain: "create one Living Claim at the start of each of your turns ...; enemies treat spaces containing your Living Claims as
    difficult terrain; when an enemy starts its turn in a Living Claim, place 1 Growth Mark on it; ... once per round, use one Verdant
    Response without spending a Growth Mark.\""""
    from combat import zones

    engine = fight(verdant(VG + "GROVE_DOMAIN_COURT_OF_ROOT_AND_BRANCH", cl=12), foe_at=(6, 6))
    use(engine, "Grove Domain: Court of Root and Branch")
    use(engine, "Verdant Response: Root", target=FOE)  # no mark needed: the Domain's free response
    turn(engine, ME)
    use(engine, "Sow Living Claim", at=(6, 6))
    assert (6, 6) in zones.difficult_cells(engine, engine.state.actors[FOE])
    turn(engine, FOE)  # starts its turn in the claim
    assert growth(engine, FOE) == 1
    turn(engine, ME)
    assert len(claims_of(engine)) == 2  # the free claim at the start of the turn


def test_verdant_at_the_table_sows_marks_and_roots_through_commit_and_reload(tmp_path):
    """At the table: Sow Living Claim at a square, Seed-Thorn Strike's Growth Mark, a Verdant Response; after a commit and a reload the
    claim, the marks and the slowed Speed stand and the fight replays."""
    from tests.r1i_service_support import FOE as TFOE, OWNER, fixture
    from tests.test_r1i_round3 import reload

    combat, table, mid, send, commit = fixture(tmp_path, [SOWN, SEED, VG + "FEED_THE_ROOT"])
    menu = table.state(mid)["menu"]
    sow_cid = next(o["candidate_id"] for g in menu["actions"] if g["label"] == "Sow Living Claim"
                   for o in g["options"] if o.get("destination") == {"x": 4, "y": 6})
    commit(sow_cid)
    commit(next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if g["label"] == "Seed-Thorn Strike"
                for o in g["options"] if TFOE in o.get("target_ids", [])))
    commit(next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if g["label"] == "Verdant Response: Root"
                for o in g["options"] if TFOE in o.get("target_ids", [])))
    engine = reload(tmp_path, mid)
    from combat.ext import verdant_chassis

    owner, foe = engine.state.actors[OWNER], engine.state.actors[TFOE]
    (claim,) = verdant_chassis.claims(engine, owner)
    assert (claim.position.x, claim.position.y) == (4, 6) and claim.component["feed"] == 1  # the foe stands in it: Feed the Root
    assert verdant_chassis.marks(foe, owner) == 0  # the one Seed-Thorn mark went into Root
    assert any(m.target_field == "speed_ft" and int(m.value) == -15 for m in foe.modifiers.values())


def test_a_saved_fights_attack_roll_brutal_shove_keeps_its_old_riders(tmp_path):
    """Control: recompiling the legacy authority types Brutal Shove as an attack roll and retains its old rider responses.

    This builds a fresh fight with the old authority; it does not load a pre-change save or compare complete replay captures.
    """
    import subprocess

    old = tmp_path / "authority_int_r22.json"
    old.write_bytes(subprocess.check_output(["git", "show", "int/r22:APP/authority/Tianxia_Typed_Mechanics_Authority_R1.json"], cwd=ROOT))
    talents = [SHOVE, BR + "BREAK_DEFENSES", BR + "FOCUSED_MIGHT", BR + "DOMINOES", BR + "COURT_OF_THE_MOVING_MOUNTAIN"]
    import json

    me = compile_character(sheet(talents, cl=12, dc=16, score=16), actor_id=ME, typed_authority=json.loads(old.read_bytes()))
    shove = next(a for a in me["action_catalog"] if a["display_name"] == "Brutal Shove")
    assert shove["parameters"]["typed"]["effects"][0]["type"] == "attack"  # the sealed attack-roll typing
    engine = fight(me, ally=bundle(actor_id=ALLY), foe_at=(4, 6), ally_at=(5, 6))
    engine.state.actors[ALLY].team_id = "team:b"
    sure_hit(engine, FOE, ALLY)
    engine.state.actors[ME].resources[FOCUS] = 1
    use(engine, "Court of the Moving Mountain")
    events = use(engine, "Brutal Shove", target=FOE)
    foe = engine.state.actors[FOE]
    assert [e for e in events if e.event_type == "ATTACK_ROLLED" and FOE in e.target_ids] and not checks(events, FOE)
    assert any(m.target_field == "incoming_attack_mode" for m in foe.modifiers.values())  # Break Defenses
    assert held(engine.state.actors[ME], "focused_might_ready")  # Focused Might
    free = [e for e in events if e.event_type == "ATTACK_ROLLED" and ALLY in e.target_ids]
    assert free and free[0].source_definition_id.endswith(".granted.dominoes")  # the attack-roll free shove
