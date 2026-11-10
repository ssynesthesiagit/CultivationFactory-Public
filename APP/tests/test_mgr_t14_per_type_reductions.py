"""Per-damage-type reduction allowances on a native mixed-damage hit (Mantis F19 review fix).

Damage Adaptation prints its allowance per damage type: "the first packet of that
type each round is reduced by your Proficiency Bonus" (authority
riders_c7.json:2040), and Ten Thousand Answers keeps one allowance per adapted
type (":2212"). A creature adapted to Bludgeoning and Piercing that takes both in
one native thousand-cuts packet therefore loses the Proficiency Bonus twice, once
off each component, and each of those two allowances is spent.

A ``damage_reduction`` plug-in states which it is: a plain int is one amount for
the triggering attack (Stand Against the Calamity, Ironclad Line, Refined Golden
Bell's first packet), which a mixed hit spends once across the components it
covers; ``{"amount": n, "scope": "type"}`` is a per-damage-type allowance, which
each covered type spends on its own component and which is told it applied for
every type it actually reduced. The old single ``max(answers)`` capacity spent only
one type's allowance across the whole hit, so a two-component packet lost the
Proficiency Bonus once and the other type's allowance stayed unspent.

The first regression drives the real provider through
typed_reactions.defend_components, the seam combat/gate2_engine.py uses whenever a
hit carries components, with a committed two-component packet. The second plays a
real Mantis thousand-cuts hit at the table -- acquiring the defender's two
adaptations from two earlier committed strikes, each proved by a cold reload --
and reads the committed packet and both allowances it recorded.

Whole-hit providers keep their contract; tests/test_mgr_t14_mixed_packet_reductions.py
covers them.
"""
from combat.ext import adaptations
from combat.gate2_runtime_models import ActionIntent
from tests.test_mgr_mantis_native import DECLINE, P, hit, native
from tests.test_riders_c7 import ADAPT, FOE, ME, answers, bundle, fight
from tests.test_riders_c7 import _typed_foe
from tests.worker2_support import FOE as DEFENDER, OWNER as MANTIS, reload, turn

FLESH = ADAPT + "flesh_remembers_pain"
ANSWERS = ADAPT + "ten_thousand_answers"
RECORD = "condition:typed.adaptations"
CONSUMED = "_round_adapted_first_"


def _adapted(engine, me):
    """The engine side of the regression: one creature adapted to both types of the packet."""
    answers(engine)  # a Reaction window may open; the real providers decide, this test declines it
    for kind in ("BLUDGEONING", "PIERCING"):
        adaptations.acquire(engine, me, "damage", {"type": kind, "by": FOE}, source=FLESH)
    return engine, me


def _commit(engine, target_id, components, attacker_id=FOE):
    """Commit one component packet the way combat/gate2_engine.py commits a native mixed hit."""
    candidate = next(iter(engine.legal_candidates()))
    intent = ActionIntent(intent_id=f"mixed-{len(engine.events)}", decision_id=candidate.decision_id,
                          candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                          actor_id=attacker_id, target_ids=(target_id,))
    start = len(engine.events)
    engine._active_intent = intent
    engine._typed_pending_damage_type = "MIXED"
    try:
        engine._commit_damage(engine.state.actors[target_id], sum(amount for amount, _kind in components), "MIXED",
                              source_definition_id="test:hostile", source_actor_id=attacker_id,
                              intent=intent, reaction_depth=0, components=components)
    finally:
        engine._active_intent = None
    return next(event for event in engine.events[start:] if event.event_type == "DAMAGE_COMMITTED").payload


def test_each_adapted_type_spends_its_own_allowance_on_one_committed_mixed_hit():
    engine = fight(bundle([FLESH, ANSWERS]), foe=_typed_foe())
    engine, me = _adapted(engine, engine.state.actors[ME])
    pb = int(next(row for row in engine.typed_passive_rows[ME] if row.get("role") == "damage").get("pb")
             or me.proficiency_bonus)  # the compiled row's own Proficiency Bonus, as first_instance reads it
    payload = _commit(engine, ME, [(20, "BLUDGEONING"), (20, "PIERCING")])
    # Each component is first halved by Ten Thousand Answers' Resistance, then loses
    # its own adapted type's Proficiency Bonus: (20 // 2 - PB) twice, not once.
    expected = 2 * (20 // 2 - pb)
    assert payload["reduced_to"] == expected
    assert payload["hp_damage"] == expected
    for kind in ("BLUDGEONING", "PIERCING"):
        assert me.turn_flags.get(CONSUMED + kind) == engine.state.round_number
    # "The first packet of that type each round": the next packet this round is only
    # halved, so neither allowance was left over to pay for it.
    assert _commit(engine, ME, [(20, "BLUDGEONING"), (20, "PIERCING")])["reduced_to"] == 2 * (20 // 2)


def _adapted_types(engine, actor_id=DEFENDER):
    """The damage types the committed fight records on this creature's Adaptation record."""
    actor = engine.state.actors[actor_id]
    held = next((condition for condition in actor.conditions.values() if condition.condition_id == RECORD), None)
    return set() if held is None else {str(row["type"]).upper() for row in (held.data or {}).get("damage") or []}


def test_mixed_hit_offers_damage_adaptation_and_persists_selection(tmp_path):
    combat, table, mid = native(tmp_path, foe_talents=(FLESH, ANSWERS))
    prompts = hit(combat, table, mid, picks={**DECLINE,
        'choice:needle.iron_fist_damage_type': 'BLUDGEONING',
        'choice:needle.path_hit.' + P + 'death_of_a_thousand_cuts': 'No Reactions',
        'choice:needle.adapt_damage': 'PIERCING'})
    choices = [p for p in prompts if p['context']['reaction_source_id'] == 'choice:needle.adapt_damage']
    assert len(choices) == 1
    assert {o['id'] for o in choices[0]['choice']['options']} == {'BLUDGEONING', 'PIERCING'}
    engine = reload(tmp_path, mid)
    assert _adapted_types(engine) == {'PIERCING'}
    packet = next(e.payload for e in engine.events if e.event_type == 'DAMAGE_COMMITTED'
                  and e.actor_id == MANTIS and e.payload['damage_type'] == 'MIXED')
    assert packet['hp_damage'] > 0


def test_a_committed_mantis_mixed_hit_spends_both_allowances_and_reload_keeps_them(tmp_path):
    """The mixed thousand-cuts packet meets a defender the saved fight really records as adapted twice.

    Damage Adaptation is acquired from hostile damage that reaches the owner's Hit Points, one
    type per round (combat/ext/adaptations.py:damage_adaptation). So the two earlier Mantis
    strikes are the table setup itself: each is followed by a cold reload, and the reloaded
    record naming that type is the proof that the defender is adapted in the committed fight
    rather than in an engine object this test mutated. A CL18 Attack action is four strikes, so
    the hit under test is its one mixed packet (Death of a Thousand Cuts builds one per turn);
    the ordinary strikes stay legal and are not counted here. Flesh Remembers Pain asks its
    Reaction before each adapted-type component lands: accepting it once spends the Reaction and
    this round's marker, so the packet's second adapted type is not asked at the same checkpoint.
    """
    combat, table, mid = native(tmp_path, foe_talents=(FLESH, ANSWERS))

    def strike(kind):
        """Answer every printed damage-type choice of one strike, so the hit really deals ``kind``.

        Iron Fist asks once using the composed palette, including Mantis Hooks' types.
        """
        return {**DECLINE, "choice:needle.adapt_response": "use",
                "choice:needle.iron_fist_damage_type": kind}

    for kind in ("BLUDGEONING", "PIERCING"):
        prompts = hit(combat, table, mid, picks=strike(kind))
        ids = [p['context']['reaction_source_id'] for p in prompts]
        assert 'choice:needle.mantis_damage_type' not in ids
        assert 'choice:needle.iron_fist_damage_type' in ids
        assert kind in _adapted_types(reload(tmp_path, mid)), \
            "the committed fight does not record the %s Damage Adaptation" % kind.title()
        turn(table, mid, DEFENDER)
        turn(table, mid, MANTIS)

    mark = combat._load_session(mid).engine.state.event_sequence
    hit(combat, table, mid, picks={**strike("BLUDGEONING"),
                                   "choice:needle.path_hit." + P + "death_of_a_thousand_cuts": "No Reactions"})
    engine = reload(tmp_path, mid)
    defender = engine.state.actors[DEFENDER]
    packets = [event.payload for event in engine.events if event.sequence > mark
               and event.event_type == "DAMAGE_COMMITTED"
               and event.actor_id == MANTIS and event.target_ids == (DEFENDER,)]
    assert packets and packets[0]["damage_type"] == "MIXED", \
        f"the thousand-cuts packet is the first damage of the action, not: {packets}"
    mixed = [packet for packet in packets if packet["damage_type"] == "MIXED"]
    assert len(mixed) == 1, f"Death of a Thousand Cuts builds exactly one mixed packet, not {packets}"
    payload = mixed[0]
    components = payload["damage_components"]
    assert {row["damage_type"] for row in components} == {"BLUDGEONING", "PIERCING"}, payload
    role = next(row for row in engine.typed_passive_rows[DEFENDER] if row.get("role") == "damage")
    pb = int(role.get("pb") or defender.proficiency_bonus)
    # "The first packet of that type each round is reduced by Proficiency Bonus": Ten Thousand
    # Answers makes every adapted type Resistant, so each component is halved first and then
    # loses its own type's allowance, capped by what is left. A single whole-hit capacity
    # would have lost the Bonus once for the packet instead of once per adapted component.
    assert payload["reduced_to"] == sum(max(0, row["amount"] // 2 - pb) for row in components), payload
    assert _adapted_types(engine) == {"BLUDGEONING", "PIERCING"}
    for kind in ("BLUDGEONING", "PIERCING"):
        assert defender.turn_flags.get(CONSUMED + kind) == engine.state.round_number, payload
