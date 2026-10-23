"""Severed Thread Recovery through sealed CombatService fights and reloads.

The owner's own turns drive the real Puppetry features through the
table (session execute_intent), so the printed trigger -- "when a
control thread ends" -- fires from the engine's own turn-end and from
its Substitute Harm Body resolution. Every assertion reads a
cold-reloaded saved fight.

The printed rule has four parts, each with its own regression:

* the owner regains 1 Cultivation Point when a control thread ends
  because the puppet vessel is left outside the 60-foot control
  range at the end of the owner's turn;
* the same regain fires when a vessel is reduced to 0 Hit Points by
  Substitute Harm Body, and the once-per-scene allowance is spent by
  the first end, so no second end in the same fight regains again
  (the count survives a cold reload);
* at CL 15+ the allowance is two ends;
* a fighter without the Insight is never granted the recovery.
"""

from combat.ext import placed
from combat.ext.puppetry_defenses import RECOVERY, BLOCK
from combat.ext.passive_rows import row_of

USES = "puppetry_recovery_round_scene_uses"
from combat.ext.vessel import HARM_BODY
from tests.auto_worker1_support import LEFT, RIGHT, act, action_sender, fight, reload, turn
from tests.auto28_puppetry_support import resolve

SPHERE = "tianxia.sphere.puppetry"
RAISE = "PUPPETRY_BASE_RAISE_THE_VESSEL"
STRIKE = "PUPPETRY_BASE_PUPPET_STRIKE"
VESSEL_AT = (4, 7)  # one square from the owner's start (3, 6)


def puppet_fight(tmp_path, *, insight=True, cl=15, harm_body=False):
    """A Puppetry duel whose left fighter holds (or lacks) the Insight."""
    talents = [RAISE, STRIKE] + ([HARM_BODY] if harm_body else [])
    cause = ([{"type": "damage", "flat": 100, "damage_type": "FORCE",
               "applies_to": "target"}] if harm_body else [])

    def sheet_edit(doc, aid):
        fields = doc["spheres_and_talents"]
        fields["sphere_record_ids"] = [SPHERE]
        fields["automatic_sphere_component_record_ids"] = []
        fields["cultivation_insight_record_ids"] = [RECOVERY] if insight else []

    return fight(tmp_path, talents, spheres=[SPHERE], cl=cl,
                 sheet_edit=sheet_edit, cause=cause,
                 positions={LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}})


def active_vessels(engine):
    """The owner's live puppet vessels (a broken or ranged-out thread
    leaves none of these: the engine clears the zone, and a ranged-out
    vessel is reshaped inactive)."""
    return [zone for zone in engine.state.zones.values()
            if zone.active and zone.owner_id == LEFT
            and placed.data(zone).get("tag") == "vessel"
            and placed.data(zone).get("state") == "active"]


def raise_the_vessel(combat, table, mid, where):
    """The owner raises the real puppet vessel (1 Cultivation Point)."""
    state = table.state(mid)
    menu = state["menu"]
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates()
                     if c.display_name.startswith("Raise the Vessel (1 CP)")
                     and (c.destination.x, c.destination.y) == where)
    resolve(lambda answers: table.act(mid, candidate.candidate_id, menu["decision_id"],
                                      menu["state_version"], state["last_sequence"], answers),
            {"choice:needle.vessel_raise_move": []})


def walk_away(combat, table, mid):
    """The owner's ordinary move, the legal walking destination that
    puts the most distance between the owner and the vessel."""
    state = table.state(mid)
    menu = state["menu"]
    engine = combat._load_session(mid).engine
    vessel = active_vessels(engine)
    assert vessel, "no live vessel to walk away from"
    vessel = vessel[0]
    candidate = max((c for c in engine.legal_candidates()
                     if c.source_definition_id == "system:combat.movement"),
                    key=lambda c: (engine.grid.distance_ft(c.destination, vessel.center),
                                   engine.grid.distance_ft(c.destination,
                                                           engine.state.actors[LEFT].position),
                                   c.destination.x, c.destination.y))
    result = table.act(mid, candidate.candidate_id, menu["decision_id"],
                       menu["state_version"], state["last_sequence"], [])
    while result["status"] == "REACTION_REQUIRED":
        prompt = result["reaction"]
        answers = [{**prompt["context"], "selection": "DECLINE", "option_ids": []}]
        result = table.act(mid, prompt["context"].get("candidate_id", candidate.candidate_id),
                           menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
    assert result["status"] == "COMMITTED", result


def end_a_control_thread(combat, table, mid):
    """Walk away on the owner's own turns until the vessel is outside
    the 60-foot control range at the end of the owner's turn: the
    printed control-thread end."""
    for _ in range(12):
        if table.state(mid)["menu"]["actor_id"] != LEFT:
            assert act(table, mid, "end")["status"] == "COMMITTED"
            continue
        walk_away(combat, table, mid)
        assert act(table, mid, "end")["status"] == "COMMITTED"
        engine = reload(combat, mid)
        if not active_vessels(engine):
            return engine
    raise AssertionError("the control thread never ended")


def soak_until_the_vessel_breaks(combat, table, mid):
    """The foe attacks; Substitute Harm Body soaks each blow onto the
    vessel until the vessel is reduced to 0 Hit Points. Returns the
    owner's Cultivation Points just before the breaking blow."""
    turn(table, mid, RIGHT)
    send = action_sender(combat, table, mid, "Cause", target_id=LEFT)
    for _ in range(6):
        before = reload(combat, mid).state.actors[LEFT].resources["resource:core.qi"]
        result = send([])
        while result["status"] == "REACTION_REQUIRED":
            prompt = result["reaction"]
            if "Substitute Harm Body" in str(prompt):
                result = send([{**prompt["context"], "selection": "USE", "option_ids": []}])
            else:
                result = send([{**prompt["context"], "selection": "DECLINE", "option_ids": []}])
        assert result["status"] == "COMMITTED", result
        engine = reload(combat, mid)
        if not active_vessels(engine):
            return before
        turn(table, mid, LEFT)
        turn(table, mid, RIGHT)
    raise AssertionError("the vessel never broke")


def raise_spot(engine):
    """A free square next to the owner for the next vessel."""
    here = engine.state.actors[LEFT].position
    spots = [(here.x, here.y + 1), (here.x + 1, here.y),
             (here.x, here.y - 1), (here.x - 1, here.y)]
    return next(spot for spot in spots
                if 0 <= spot[0] < 20 and 0 <= spot[1] < 14)


def test_a_control_thread_ending_out_of_range_regains_1_cp_once_per_scene(tmp_path):
    combat, table, mid = puppet_fight(tmp_path, cl=8)
    engine = reload(combat, mid)
    assert row_of(engine, LEFT, BLOCK, "recovery") is not None
    raise_the_vessel(combat, table, mid, VESSEL_AT)
    engine = reload(combat, mid)
    # the raise spent 1 Cultivation Point
    assert engine.state.actors[LEFT].resources["resource:core.qi"] == 99
    end_a_control_thread(combat, table, mid)
    engine = reload(combat, mid)
    owner = engine.state.actors[LEFT]
    # the printed regain, and the once-per-scene allowance is spent
    assert owner.resources["resource:core.qi"] == 100
    assert owner.turn_flags.get(USES) == 1
    # a second thread in the same fight regains nothing: the count
    # survived the cold reload above
    turn(table, mid, LEFT)
    raise_the_vessel(combat, table, mid, raise_spot(reload(combat, mid)))
    engine = reload(combat, mid)
    assert engine.state.actors[LEFT].resources["resource:core.qi"] == 99
    end_a_control_thread(combat, table, mid)
    engine = reload(combat, mid)
    owner = engine.state.actors[LEFT]
    assert owner.resources["resource:core.qi"] == 99
    assert owner.turn_flags.get(USES) == 1


def test_at_cl15_the_allowance_is_two_ends(tmp_path):
    combat, table, mid = puppet_fight(tmp_path, cl=15)
    engine = reload(combat, mid)
    assert row_of(engine, LEFT, BLOCK, "recovery") is not None
    spot = VESSEL_AT
    for expected_uses in (1, 2):
        raise_the_vessel(combat, table, mid, spot)
        end_a_control_thread(combat, table, mid)
        engine = reload(combat, mid)
        owner = engine.state.actors[LEFT]
        assert owner.resources["resource:core.qi"] == 100
        assert owner.turn_flags.get(USES) == expected_uses
        turn(table, mid, LEFT)
        spot = raise_spot(reload(combat, mid))


def test_a_vessel_reduced_to_zero_hit_points_regains_1_cp(tmp_path):
    combat, table, mid = puppet_fight(tmp_path, cl=8, harm_body=True)
    engine = reload(combat, mid)
    assert row_of(engine, LEFT, BLOCK, "recovery") is not None
    raise_the_vessel(combat, table, mid, VESSEL_AT)
    before = soak_until_the_vessel_breaks(combat, table, mid)
    engine = reload(combat, mid)
    owner = engine.state.actors[LEFT]
    # the soak spent 1 Cultivation Point and the printed regain paid
    # it back: the breaking blow is Cultivation-Point-neutral
    assert owner.resources["resource:core.qi"] == before
    assert owner.turn_flags.get(USES) == 1
    # the scene allowance is spent: a second broken vessel regains nothing
    turn(table, mid, LEFT)
    raise_the_vessel(combat, table, mid, (VESSEL_AT[0] + 1, VESSEL_AT[1]))
    before = soak_until_the_vessel_breaks(combat, table, mid)
    engine = reload(combat, mid)
    owner = engine.state.actors[LEFT]
    assert owner.resources["resource:core.qi"] == before - 1
    assert owner.turn_flags.get(USES) == 1


def test_a_fighter_without_the_insight_is_never_granted_the_recovery(tmp_path):
    combat, table, mid = puppet_fight(tmp_path, cl=8, insight=False)
    engine = reload(combat, mid)
    assert row_of(engine, LEFT, BLOCK, "recovery") is None
    raise_the_vessel(combat, table, mid, VESSEL_AT)
    end_a_control_thread(combat, table, mid)
    engine = reload(combat, mid)
    owner = engine.state.actors[LEFT]
    # only the raise's cost: no regain, no allowance spent
    assert owner.resources["resource:core.qi"] == 99
    assert USES not in owner.turn_flags
