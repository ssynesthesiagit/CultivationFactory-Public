"""MGR-T14 -- Written Rebuke (tianxia.tradition.spirit.echo_scribe.feature.written_rebuke).

The assigned record's delivered clause chain on the one trigger the codebase can legally wire (a Resonance Marked
creature's audible/named technique): real source acquisition (the Resonance Mark comes from the sibling Name on the
Page action, a committed table action, not an injected condition), the triggering creature's action through the
engine, the committed reaction choice, the Charisma save, the `4d8 + Wisdom modifier` Psychic damage and Strike the
Phrase's Disadvantage on the triggering attack roll.

Controls are the same chain without the licensing fact: no Resonance Mark, and a creature that owns a sibling Echo
Scribe feature but not Written Rebuke. Neither may offer, spend or deliver the rebuke.

The engine harness is tests/test_riders_c8.py's own (the committed regression for this feature lives there).  The
service/table harness of tests/test_a2_group_traditions_2.py currently cannot offer its probe actions at all on this
base (every probe candidate is missing -> StopIteration in ``use``), which that file's own tests show too; a table
commit/cold-reload variant is reported as a residual rather than shipped as a failing test.
"""

from tests.test_riders_c8 import ES, fight, turn, use, payloads, ME, FOE

FEATURES = [ES + "written_rebuke", ES + "name_on_the_page"]  # Name on the Page is the native Resonance Mark producer
SIBLING_ONLY = [ES + "ink_remembers", ES + "name_on_the_page"]  # tradition without Written Rebuke
RESONANCE = "resource:core.resonance"


def _mark_foe(engine):
    """The mark is placed by the sibling feature's own committed action, through its Charisma save."""
    use(engine, "Name on the Page", FOE)
    foe = engine.state.actors[FOE]
    assert [c for c in foe.conditions.values() if "resonance" in c.condition_id], "the mark must be committed natively"


def _scribe_reacted(events):
    return [e for e in events if e.event_type == "REACTION_RESOLVED" and e.actor_id == ME]


def _attack(engine):
    """The marked creature spends its turn on a real named technique aimed at the scribe."""
    me, foe = engine.state.actors[ME], engine.state.actors[FOE]
    turn(engine, FOE)
    me.reaction_available = True
    hp, before = foe.current_hp, me.resources[RESONANCE]
    events = use(engine, "Paired Bi Shou Assault", ME, actor_id=FOE)
    return events, me, foe, hp, before


def test_written_rebuke_strike_costs_3_resonance_damages_and_grants_disadvantage():
    engine = fight(FEATURES, dc=40, foe_at=(4, 6))
    _mark_foe(engine)
    events, me, foe, hp, before = _attack(engine)

    assert me.resources[RESONANCE] == before - 3  # Cost: 3 Resonance, paid once for one Reaction
    assert foe.current_hp < hp  # failed Charisma save: 4d8 + Wisdom modifier Psychic damage
    first = payloads(events, "ATTACK_ROLLED")[0]
    assert len(first.get("dice") or ()) == 2  # Strike the Phrase: the triggering attack roll has Disadvantage


def test_written_rebuke_is_not_offered_spent_or_delivered_without_the_mark():
    engine = fight(FEATURES, dc=40, foe_at=(4, 6))  # no Name on the Page, so no Resonance Mark
    events, me, foe, hp, before = _attack(engine)

    assert me.resources[RESONANCE] == before  # no cost may be paid without the trigger's licensing fact
    assert not _scribe_reacted(events)  # the scribe never answers
    assert len(payloads(events, "ATTACK_ROLLED")[0].get("dice") or ()) == 1  # no Disadvantage on the roll


def test_written_rebuke_is_not_offered_spent_or_delivered_without_owning_the_feature():
    engine = fight(SIBLING_ONLY, dc=40, foe_at=(4, 6))  # wrong owner: tradition owned, mark placed, feature absent
    _mark_foe(engine)
    events, me, foe, hp, before = _attack(engine)

    assert me.resources[RESONANCE] == before  # a sibling Echo Scribe feature may not pay for this one
    assert not _scribe_reacted(events)
    assert len(payloads(events, "ATTACK_ROLLED")[0].get("dice") or ()) == 1
