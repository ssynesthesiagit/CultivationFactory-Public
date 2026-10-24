"""RW004 - Spear-Sovereign Incarnation and the Spear Intent producer on Spear Thrust.

Printed, quoted from ``authority/typed_mechanics/rules_text.json``
(``TAL_SPEAR_SPEAR_SOVEREIGN_INCARNATION``, 15 CP, 1 minute, once per long rest, CL 15):

    Gain Fly Speed 40 feet and Hover. Increase Spear Line by 10 feet for Spear talents, opportunity
    attacks, and ordinary approved Spear weapon attacks. Spear Intent lasts until the end of your next turn.
    Once per turn when a creature enters your Spear Line, make one approved
    Spear weapon attack against it without spending a Reaction; once per turn when you hit a creature
    bearing your Spear Intent, move 10 feet toward it or push it 10 feet; ordinary Disarm effects fail
    against you.

and ``SPEAR_BASE_SPEAR_THRUST`` ("Replace one attack with one attack using an approved Spear weapon",
then choose one: "Apply Spear Intent until the start of your next turn", "Push Target", "Close Distance",
"Reduce Speed", "Gain AC").

OD-1: the printed "15 Spear Resource" has no pool in the typed authority, so the record keeps the 15 CP
cost (``cost: [[{"resource": "cp", "amount": 15}]]``) and this packet adds no resource subsystem.

Rider 3 (the free attack when a creature enters your Spear Line) is not wired: the engine has no seam for
it, so it stays an open gap and nothing here asserts it. Spear Line's *area length* is likewise not
claimed; the seam this packet uses (``attack_reach_bonus``) expresses the printed flat +10 feet to
attacks, which is the whole of "increase Spear Line by 10 feet for Spear talents, opportunity attacks, and
ordinary approved Spear weapon attacks" that a reach contribution can carry.
"""
from combat import attack_reach, flight
from combat import typed_executor as te
from combat import typed_reactions
from tests.test_auto56_spear import AN, ME, _answers, _fight, _ready, _use

SOVEREIGN_ID = "TAL_SPEAR_SPEAR_SOVEREIGN_INCARNATION"
SOVEREIGN = "Spear-Sovereign Incarnation"
THRUST_INTENT = "Spear Thrust: Apply Spear Intent"
STATE = "condition:typed.state.spear_sovereign_incarnation"
MARK_PREFIX = "mark.spear_intent"


# ---------------------------------------------------------------- helpers
def _cast(engine):
    """Cast the Incarnation and return the refreshed fighter."""
    _ready(engine)
    _answers(engine, {})
    _use(engine, SOVEREIGN)
    return engine.state.actors[ME]


def _thrust(engine, picks=None):
    """Use the Spear Thrust menu option that applies Spear Intent (the printed producer)."""
    _ready(engine)
    asked = _answers(engine, picks or {})
    _use(engine, THRUST_INTENT)
    return asked


def _spear_action(engine):
    return next(row for row in engine.action_catalog.values() if row.owner_id == ME
                and str(row.source_definition_id).endswith(".weapon.qiang"))


def _packets(engine, foe):
    """Every damage packet this fighter committed to ``foe`` so far (weapon, rider, extra dice)."""
    return [event.payload for event in engine.events
            if event.event_type == "DAMAGE_COMMITTED" and foe.entity_id in (event.target_ids or ())
            and event.actor_id == ME]


def _mark(actor):
    return next((row for row in actor.conditions.values() if MARK_PREFIX in str(row.condition_id)), None)


def _ids(actor):
    return sorted(str(row.condition_id) for row in actor.conditions.values())


def _damage(engine, applier, subject, damage_type, amount=20):
    """One flat typed damage packet from ``applier`` to ``subject``; returns the HP actually lost."""
    action = _spear_action(engine)
    context = te.Context(engine, applier, action, None, dict((action.parameters or {}).get("typed") or {}),
                         [subject], subject, {}, effect_resolution="nested")
    before = subject.current_hp
    te.run_effects(context, [{"type": "damage", "applies_to": "target", "flat": amount, "formula": "none",
                              "damage_types": [damage_type]}])
    return before - engine.state.actors[subject.entity_id].current_hp


def _condition(engine, applier, subject, condition):
    """The printed Disarm (or another condition) applied by ``applier`` to ``subject``, as a maneuver does."""
    action = _spear_action(engine)
    context = te.Context(engine, applier, action, None, dict((action.parameters or {}).get("typed") or {}),
                         [subject], subject, {}, effect_resolution="nested")
    te.run_effects(context, [{"type": "condition", "condition": condition, "applies_to": "target",
                              "duration": {"kind": "until_start_of_your_next_turn"}}])


def _next_turn(engine):
    """Run the foe's turn and come back to this fighter's."""
    engine.end_turn()
    engine.end_turn()
    return engine.state.actors[ME]


# ---------------------------------------------------------------- state-gated effects
def test_spear_sovereign_incarnation_grants_fly_40_and_hover():
    """"Gain Fly Speed 40 feet and Hover" is typed state data, not a fly speed this plug-in invents."""
    bundle, engine, me, foe, _, _ = _fight(SOVEREIGN_ID)
    assert flight.profile(engine, me).speed_ft == 0, "the fighter does not fly before the Incarnation"

    me = _cast(engine)
    assert STATE in _ids(me), _ids(me)
    profile = flight.profile(engine, me)
    assert profile.speed_ft == 40, profile
    assert profile.hover, "Hover is printed alongside the Fly Speed"


def test_spear_sovereign_incarnation_resists_piercing_and_force_only():
    """"Resistance to Piercing and Force" - and nothing else."""
    bundle, engine, me, foe, _, _ = _fight(SOVEREIGN_ID)
    me.current_hp = 4000
    assert _damage(engine, foe, me, "piercing") == 20, "no Resistance before the Incarnation"

    me = _cast(engine)
    me.current_hp = 4000
    assert _damage(engine, foe, me, "piercing") == 10, "Resistance to Piercing halves a 20-point packet"
    assert _damage(engine, foe, me, "force") == 10, "Resistance to Force halves a 20-point packet"
    assert _damage(engine, foe, me, "slashing") == 20, "no Resistance to Slashing"


def test_spear_line_adds_ten_feet_to_ordinary_spear_attacks_and_opportunity_attacks():
    """"increase Spear Line by 10 feet for Spear talents, opportunity attacks, and ordinary approved Spear
    weapon attacks." The Qiang prints Reach, so its opportunity range is 10 feet before the Incarnation and
    20 after - the +10 is a contribution, never a replacement.

    Spear Thrust's own option attacks are covered by test_rw004f1_spear_thrust_reaches_the_spear_line_plus_ten."""
    bundle, engine, me, foe, _, _ = _fight(SOVEREIGN_ID)
    spear = _spear_action(engine)
    unarmed = next(row for row in engine.action_catalog.values() if row.owner_id == ME
                   and row.display_name == "Unarmed Strike")
    assert attack_reach.maximum(engine, me, spear) == 10, "the ordinary Spear attack starts at the Reach"
    assert typed_reactions.opportunity_reach(engine, me) == 10

    me = _cast(engine)
    assert attack_reach.maximum(engine, me, spear) == 20, "ordinary approved Spear weapon attacks gain 10"
    assert typed_reactions.opportunity_reach(engine, me) == 20, "opportunity attacks gain 10"
    assert attack_reach.maximum(engine, me, unarmed) == 5, "only Spear attacks gain the line"


def test_spear_intent_lasts_until_the_end_of_your_next_turn_while_sovereign_is_active():
    """"Spear Intent lasts until the end of your next turn." The printed option the producer applies says
    "until the start of your next turn"; the Incarnation is what extends it by a turn, so the mark the
    producer applies carries the later expiry."""
    bundle, engine, me, foe, _, _ = _fight(SOVEREIGN_ID)
    me = _cast(engine)
    _thrust(engine)
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    mark = _mark(foe)
    assert mark is not None, _ids(foe)
    assert mark.expires_on == "END_OF_SOURCE_TURN_AT:%d" % (me.turns_started + 1), mark.expires_on

    _next_turn(engine)
    assert _mark(engine.state.actors[AN]) is not None, "the mark survives the start of your next turn"
    _next_turn(engine)
    assert _mark(engine.state.actors[AN]) is None, "and ends with it"


def test_spear_intent_keeps_its_printed_expiry_without_the_incarnation():
    """The extension is state-gated: Spear Thrust's own printed expiry ("until the start of your next turn")
    still applies to a fighter who is not incarnate."""
    bundle, engine, me, foe, _, _ = _fight(SOVEREIGN_ID)
    _thrust(engine)
    foe = engine.state.actors[AN]
    mark = _mark(foe)
    assert mark is not None, _ids(foe)
    assert mark.expires_on == "START_OF_MARKER_NEXT_TURN", mark.expires_on
    _next_turn(engine)
    assert _mark(engine.state.actors[AN]) is None, "the printed expiry ends it at the start of your next turn"


# ---------------------------------------------------------------- rider 4: move 10 or push 10
def test_spear_sovereign_ride_pushes_ten_feet_away():
    """"once per turn when you hit a creature bearing your Spear Intent, move 10 feet toward it or push it 10
    feet." This engine's only choice transport is the needle prompt, so the two printed options are its two
    options; pushing moves the marked creature and never the fighter."""
    bundle, engine, me, foe, _, _ = _fight(SOVEREIGN_ID)
    me = _cast(engine)
    start = engine.state.actors[AN].position
    asked = _thrust(engine, {"spear_sovereign_ride": lambda options: ["push"]})
    assert [row["reaction_source_id"] for row in asked] == ["choice:needle.spear_sovereign_ride"], asked
    assert list(asked[0]["legal_option_ids"])[:2] == ["move", "push"], asked[0]["legal_option_ids"]
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    assert (foe.position.x, foe.position.y) == (start.x + 2, start.y), "pushed 10 feet away (5 feet a cell)"
    assert (me.position.x, me.position.y) == (3, 6), "the fighter is not moved"
    assert me.turn_flags.get("spear_sovereign_ride"), "the once-per-turn rider is spent"


def test_spear_sovereign_ride_moves_ten_feet_toward_and_is_spent_once_per_turn():
    """The other printed option grants the fighter 10 feet of movement toward the marked creature, and the rider
    is spent for the turn after the first hit; the next turn asks again, on any hit and not only a Spear Thrust."""
    bundle, engine, me, foe, _, _ = _fight(SOVEREIGN_ID)
    me = _cast(engine)
    start = engine.state.actors[AN].position
    asked = _thrust(engine, {"spear_sovereign_ride": lambda options: ["move"]})
    assert [row["reaction_source_id"] for row in asked] == ["choice:needle.spear_sovereign_ride"], asked
    me, foe = engine.state.actors[ME], engine.state.actors[AN]
    granted = [event.payload for event in engine.events
               if event.event_type == "MOVEMENT_GRANTED"
               and str(event.source_definition_id).endswith("SPEAR_BASE_SPEAR_THRUST#opt4")]
    assert granted and granted[-1]["distance_ft"] == 10, granted
    assert (foe.position.x, foe.position.y) == (start.x, start.y), "the marked creature is not moved"
    assert me.turn_flags.get("spear_sovereign_ride")

    # A second hit in the same turn asks nothing and grants nothing.
    turn = engine.state.actors[ME].turns_started
    granted_before = len([event for event in engine.events if event.event_type == "MOVEMENT_GRANTED"])
    _ready(engine)
    asked_again = _answers(engine, {"spear_sovereign_ride": lambda options: ["move"]})
    _use(engine, THRUST_INTENT)
    assert engine.state.current_actor_id == ME and engine.state.actors[ME].turns_started == turn, "same turn"
    assert not [row for row in asked_again if row["reaction_source_id"].endswith("spear_sovereign_ride")], \
        "once per turn: no second prompt"
    assert len([event for event in engine.events if event.event_type == "MOVEMENT_GRANTED"]) == granted_before, \
        "no second 10 feet"

    # The next turn rides again, on an ordinary Spear attack as well as on a Spear Thrust.
    _next_turn(engine)
    _ready(engine)
    asked_next = _answers(engine, {"spear_sovereign_ride": lambda options: ["push"]})
    _use(engine, "Qiang (Spear) attack")
    assert [row["reaction_source_id"] for row in asked_next] == ["choice:needle.spear_sovereign_ride"], asked_next


# ---------------------------------------------------------------- Disarm immunity
def test_spear_sovereign_ignores_disarm_but_not_other_conditions():
    """"ordinary Disarm effects fail against you" - read from the creature the condition would land on, and
    only for Disarm; every other condition still lands."""
    plain, engine, me, foe, _, _ = _fight(SOVEREIGN_ID)
    _condition(engine, foe, engine.state.actors[ME], "disarmed")
    assert any(one.endswith("disarmed") for one in _ids(engine.state.actors[ME])), \
        "no immunity before the Incarnation"

    bundle, engine, me, foe, _, _ = _fight(SOVEREIGN_ID)
    me = _cast(engine)
    foe = engine.state.actors[AN]
    _condition(engine, foe, me, "disarmed")
    assert not any(one.endswith("disarmed") for one in _ids(me)), _ids(me)
    _condition(engine, foe, me, "prone")
    assert any(one.endswith("prone") for one in _ids(me)), _ids(me)


# ---------------------------------------------------------------- the printed producer (outcome 3)
def test_spear_thrust_menu_offers_apply_spear_intent():
    """The printed Spear Thrust menu is in the authority, so the rider is wired to it rather than to a
    plug-in-only keyword: the option is compiled, it is offered to the fighter, and its on-hit row applies the
    typed Spear Intent mark."""
    bundle, engine, me, foe, _, _ = _fight(SOVEREIGN_ID)
    _ready(engine)
    offered = [row.display_name for row in engine.legal_candidates() if row.actor_id == ME]
    assert THRUST_INTENT in offered, [name for name in offered if name.startswith("Spear Thrust")]

    option = next(row for row in engine.action_catalog.values() if row.owner_id == ME
                  and str(row.source_definition_id).endswith("SPEAR_BASE_SPEAR_THRUST#opt4"))
    typed = dict((option.parameters or {}).get("typed") or {})
    attack = next(row for row in typed["effects"] if row["type"] == "attack")
    marks = [row for row in attack["on_hit"] if row["type"] == "mark"]
    assert marks and marks[0]["mark"] == "Spear Intent", marks
    assert marks[0]["duration"] == {"kind": "until_start_of_next_turn"}, marks[0]["duration"]

    _use(engine, THRUST_INTENT)
    assert _mark(engine.state.actors[AN]) is not None, "the printed option applies Spear Intent"


# ---------------------------------------------------------------- outcome 4: 3d10 while incarnate
def test_spear_sovereign_adds_three_d10_to_spear_thrust_only_on_a_hit():
    """While the Incarnation is active, a Spear Thrust hit adds the printed 3d10 (Piercing or Force) once. The
    row is typed data on the record (``deferred``), so casting the Incarnation damages nobody; the same row is
    committed on the confirmed hit, once per hit, and never on a miss, without the state, or on an ordinary
    Spear attack."""
    bundle, engine, me, foe, _, _ = _fight(SOVEREIGN_ID)
    hp = me.current_hp
    me = _cast(engine)
    assert me.current_hp == hp, "casting the Incarnation damages nobody"
    assert not _packets(engine, foe), "casting the Incarnation damages nothing"

    _thrust(engine)
    packets = _packets(engine, foe)
    assert len(packets) == 2, "weapon damage plus one 3d10 packet: %r" % (packets,)
    extra = packets[-1]
    assert 3 <= extra["rolled_or_pending_damage"] <= 30, extra
    assert extra["damage_type"] in ("PIERCING", "FORCE"), extra

    # A later hit while the foe already bears the Intent (rider 4 rides the same hit) still adds it once.
    _next_turn(engine)
    before = len(_packets(engine, engine.state.actors[AN]))
    _thrust(engine, {"spear_sovereign_ride": lambda options: ["push"]})
    assert len(_packets(engine, engine.state.actors[AN])) - before == 2, \
        "one weapon packet, one 3d10 packet"

    # An ordinary Spear attack adds nothing.
    before = len(_packets(engine, engine.state.actors[AN]))
    _ready(engine)
    _answers(engine, {})
    _use(engine, "Qiang (Spear) attack")
    assert len(_packets(engine, engine.state.actors[AN])) - before == 1, "no 3d10 off a plain Spear attack"


def test_spear_thrust_without_the_incarnation_adds_no_three_d10():
    """The extra dice are gated on the state, not on the action."""
    bundle, engine, me, foe, _, _ = _fight(SOVEREIGN_ID)
    _thrust(engine)
    packets = _packets(engine, foe)
    assert len(packets) == 1, packets


def test_spear_thrust_miss_adds_no_three_d10_and_no_intent():
    """Only a confirmed hit carries the rider: a miss deals nothing and applies no Spear Intent."""
    bundle, engine, me, foe, _, _ = _fight(SOVEREIGN_ID, sure_hit=False)
    _cast(engine)
    _thrust(engine)
    assert not _packets(engine, foe), _packets(engine, foe)
    assert _mark(engine.state.actors[AN]) is None, _ids(engine.state.actors[AN])


# ---------------------------------------------------------------- RW004F1 review findings
def _record_riders():
    """The reviewed record's riders array, read from the authority file the GM note is built from."""
    import json
    from pathlib import Path

    def find(node):
        if isinstance(node, dict):
            if SOVEREIGN_ID in node and isinstance(node[SOVEREIGN_ID], dict) and "riders" in node[SOVEREIGN_ID]:
                return node[SOVEREIGN_ID]["riders"]
            for value in node.values():
                found = find(value)
                if found is not None:
                    return found
        return None

    path = Path(__file__).resolve().parents[1] / "authority/typed_mechanics/reviewed_final.d/spear_auto56.json"
    riders = find(json.loads(path.read_text(encoding="utf-8")))
    assert riders is not None, "the Sovereign record has no riders array"
    return riders


def test_rw004f1_riders_are_trimmed_to_the_unbound_rider_and_the_partial_line():
    """Review finding 4: the GM note is built from the riders array, so it must list only what is still open (rider 3)
    and the partial rider 1 note, not the five printed sentences the engine now automates."""
    riders = _record_riders()
    assert len(riders) == 1, riders
    assert "NOT WIRED" in riders[0] and "once per turn when a creature enters your Spear Line" in riders[0], riders[0]
    assert not any("PARTIAL" in row or "Spear Thrust" in row or "Spear Line by 10" in row for row in riders), riders
    assert not any("move 10 feet toward it" in row or "ordinary Disarm effects" in row for row in riders), riders


def _thrust_option(engine, index=4):
    return next(row for row in engine.action_catalog.values() if row.owner_id == ME
                and str(row.source_definition_id).endswith(f"SPEAR_BASE_SPEAR_THRUST#opt{index}"))


def test_rw004f1_spear_thrust_reaches_the_spear_line_plus_ten():
    """Review finding 1 (rider 1 automated): Spear Thrust replaces an attack with an approved Spear weapon attack, so
    the printed +10 Spear Line applies to its option attacks. Their reach is the Spear's own 10 feet, and the
    Incarnation adds 10 more while it is up; without it the reach is the plain 10 feet."""
    bundle, engine, me, foe, _, _ = _fight(SOVEREIGN_ID)
    thrust = _thrust_option(engine)
    assert attack_reach.maximum(engine, me, thrust) == 10, "before the Incarnation, Thrust reaches the Spear's 10 feet"
    assert attack_reach.bonus(engine, me, thrust) == 0
    me = _cast(engine)
    thrust = _thrust_option(engine)
    assert attack_reach.bonus(engine, me, thrust) == 10, "the Spear Line +10 reaches Spear Thrust's option attacks"
    assert attack_reach.maximum(engine, me, thrust) == 20, "Thrust reaches 20 feet while the Incarnation is up"
    assert attack_reach.maximum(engine, me, _spear_action(engine)) == 20, "the ordinary Spear attack agrees"


def test_rw004f1_every_spear_thrust_option_is_melee_with_spear_line():
    """All five Spear Thrust options share the printed Spear Line range, so each reaches the same 20 feet."""
    bundle, engine, me, foe, _, _ = _fight(SOVEREIGN_ID)
    me = _cast(engine)
    for index in range(5):
        thrust = _thrust_option(engine, index)
        assert attack_reach.melee(thrust), f"option {index} is a melee attack"
        assert attack_reach.maximum(engine, me, thrust) == 20, f"option {index} reaches 20 feet"


def test_rw004f1_ride_prompt_explains_spear_intent_in_plain_words():
    """Review finding 4 (checklist 13): the ride prompt must say what Spear Intent is and how long it lasts."""
    import inspect
    from combat.ext import martial_spear

    source = inspect.getsource(martial_spear.spear_sovereign_ride)
    assert "Spear Intent (the mark" in source and "lasting until the end of your next turn" in source, source
