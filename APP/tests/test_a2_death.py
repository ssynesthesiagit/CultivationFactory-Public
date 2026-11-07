"""Second-pass Death mechanics through real table commits and cold replay.

Test-only sealed setup actions create represented scenery; no live data, engine
patching or browser is used. Every ability executes via the service transaction.
"""
import pytest

from combat.canonical import canonical_sha256
from combat.ext import effect
from combat.ext.death_riders import FREE_HAND, SOVEREIGN, grave_anchors
from combat.gate2_runtime_models import ActionIntent, Position, RuntimeObjectState
from combat import flight
from tests.worker2_support import (OWNER, ALLY, FOE, fixture, turn, candidate,
                                   settle, reload, sealed_native_attack)


@effect("test_a2_death_scenery")
def scenery(ctx, row):
    """Evented setup, so the object is present in both journal and cold state."""
    if row["kind"] == "actor_corpse":
        from combat.ext.life_state import die
        die(ctx.engine, ctx.engine.state.actors[ALLY], "Scenario begins with a recorded corpse", ctx.source)
        return
    ctx.engine._update_object(RuntimeObjectState(
        object_id="object:test.grave", object_kind=row["kind"], position=Position(x=row["x"], y=6),
        ac=14, current_hp=20, maximum_hp=20, unattended=True, flammable=False,
        component={"name": "Funerary remains", "blocks": False,
                   **({"death_anchor_owner": row["owner"]} if row.get("owner") else {})}), ctx.source)


def seal_setup(bundle, row):
    source = "action:test.a2_death_scenery"
    bundle["action_catalog"].append({
        "source_definition_id": source, "display_name": "Place funerary remains", "owner_id": OWNER,
        "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "SELF", "costs": [],
        "parameters": {"typed": {"effects": [{"type": "test_a2_death_scenery", **row}],
                                  "numbers": {}, "duration": {"kind": "instant"}, "riders": []}, "expected_damage": 0,
                                  "free_primary": True}})  # Explicit scenario-only free setup activation (ad49b65f)
    bundle["actor_template"]["action_ids"].append(source)
    bundle["summons"] = []  # These anchor cases explicitly begin without a servant.
    bundle.pop("bundle_sha256", None)
    bundle["bundle_sha256"] = canonical_sha256(bundle)


def use(combat, table, mid, name, *, target=None, at=None, choices=None):
    chosen = candidate(combat, mid, name, target=target, at=at)
    return settle(table, mid, chosen.candidate_id, choices=choices or {})


def actions(combat, mid, source):
    engine = combat._load_session(mid).engine
    return [c for c in engine.legal_candidates()
            if c.source_definition_id in engine.action_catalog
            and ((engine.action_catalog[c.source_definition_id].parameters or {}).get("typed") or {}).get("source") == source]


def execute_hand(combat, mid, name):
    """Journal the exact mode, rather than selecting the first Hand candidate."""
    c = candidate(combat, mid, name, target=FOE)
    combat._load_session(mid).mechanical.execute_intent(ActionIntent(
        intent_id="a2-hand-" + c.candidate_id, decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=OWNER,
        target_ids=c.target_ids, destination=c.destination))
    return c.source_definition_id


@pytest.mark.parametrize("ranged", [False, True], ids=["melee", "ranged"])
@pytest.mark.parametrize("cl,count", [(1, 1), (5, 2), (11, 3), (17, 4)])
def test_ordinary_hand_modes_scaled_damage_table_reload(tmp_path, ranged, cl, count):
    _hand_mode_table(tmp_path, ranged=ranged, cl=cl, count=count, form=False, free=False)


@pytest.mark.parametrize("ranged", [False, True], ids=["melee", "ranged"])
@pytest.mark.parametrize("free", [False, True], ids=["ordinary", "free"])
def test_sovereign_hand_modes_replacement_table_reload(tmp_path, ranged, free):
    _hand_mode_table(tmp_path, ranged=ranged, cl=15, count=6, form=True, free=free)


@pytest.mark.parametrize("form", [False, True], ids=["ordinary", "sovereign"])
def test_hand_modes_reject_targets_beyond_sixty_feet_after_reload(tmp_path, form):
    talents = ["TAL_DEATH_WITHERING_HAND"]
    if form:
        talents.append("TAL_DEATH_DEATH_SOVEREIGN_INCARNATION")
    combat, table, mid = fixture(tmp_path, talents,
        positions={OWNER: {"x": 3, "y": 5}, ALLY: {"x": 3, "y": 7}, FOE: {"x": 16, "y": 5}})
    if form:
        use(combat, table, mid, "Death-Sovereign Incarnation")
    engine = reload(tmp_path, mid)
    assert engine._distance_actor_to_actor(engine.state.actors[OWNER], engine.state.actors[FOE]) == 65
    assert not any(c.target_ids == (FOE,) for c in actions(combat, mid, "TAL_DEATH_WITHERING_HAND"))


def _hand_mode_table(tmp_path, *, ranged, cl, count, form, free):
    def prepare(bundles):
        # Keep the seeded attack deterministic and isolate the Hand packet from
        # the form's aura and servant turns. No runtime engine patching.
        for bundle in bundles:
            bundle["summons"] = []
            if bundle["actor_id"] == FOE:
                bundle["actor_template"]["maximum_hp"] = 1000
            if bundle["actor_id"] == OWNER:
                for action in bundle["action_catalog"]:
                    typed = action.get("parameters", {}).get("typed", {})
                    if typed.get("source") == "TAL_DEATH_WITHERING_HAND":
                        typed["numbers"]["attack_bonus"] = 100
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
    talents = ["TAL_DEATH_WITHERING_HAND"]
    if form:
        talents.append("TAL_DEATH_DEATH_SOVEREIGN_INCARNATION")
    combat, table, mid = fixture(tmp_path, talents, cl=cl, bundle_transform=prepare,
                                positions={OWNER: {"x": 3, "y": 5}, ALLY: {"x": 3, "y": 7},
                                           FOE: {"x": 15 if ranged else 4, "y": 5}})
    if form:
        use(combat, table, mid, "Death-Sovereign Incarnation")
    engine = reload(tmp_path, mid)
    name = "Withering Hand" + (" (ranged)" if ranged else "")
    if free:
        name += " (Death-Sovereign, no Action)"
    # Both the ordinary and free melee variants must reject this distant foe.
    if ranged:
        assert not any(c.target_ids == (FOE,) and not c.source_definition_id.split(".sovereign_free")[0].endswith(".ranged")
                       for c in actions(combat, mid, "TAL_DEATH_WITHERING_HAND"))
    chosen = candidate(combat, mid, name, target=FOE)
    action = engine.action_catalog[chosen.source_definition_id]
    assert action.range_ft == (60 if ranged else 5)
    assert action.parameters["typed"]["effects"][0]["attack_kind"] == ("cultivation_ranged" if ranged else "cultivation_melee")
    before_hp = engine.state.actors[FOE].current_hp
    before_sequence = engine.state.event_sequence
    source = execute_hand(combat, mid, name)
    engine = reload(tmp_path, mid)
    packets = [e for e in engine.events if e.sequence > before_sequence and e.event_type == "DAMAGE_COMMITTED"
               and e.source_definition_id == source and FOE in e.target_ids]
    assert len(packets) == 1
    assert packets[0].payload["damage_type"] == "NECROTIC"
    damage = next(r for r in reversed(engine.rolls) if r.actor_id == OWNER and r.reason.startswith("DAMAGE"))
    assert damage.expression in {f"{count}d{10 if form else 8}+0", f"{count * 2}d{10 if form else 8}+0"}
    assert packets[0].payload["hp_damage"] == damage.total > 0
    assert engine.state.actors[FOE].current_hp == before_hp - damage.total
    owner = engine.state.actors[OWNER]
    assert owner.action_available is free
    assert owner.resources["resource:core.qi"] == (85 if form else 100)
    if free:
        assert owner.turn_flags[FREE_HAND] == owner.turns_started
        # Melee and ranged share a single allowance, even after cold reload.
        assert not any(engine.action_catalog[c.source_definition_id].parameters["typed"].get(FREE_HAND)
                       for c in actions(combat, mid, "TAL_DEATH_WITHERING_HAND"))
        assert candidate(combat, mid, "Withering Hand" + (" (ranged)" if ranged else ""), target=FOE)


@pytest.mark.parametrize("kinds", [["Undead Spirit"], ["Incorporeal Undead"],
                                 ["Humanoid", "Spirit", "Undead"], ["Humanoid", "Undead Spirit", "Elemental"]])
@pytest.mark.parametrize("servant", [False, True], ids=["passage-anchor", "foreign-explosion-servant"])
def test_compound_undead_sources_table_reload(tmp_path, kinds, servant):
    from tests.h1_support import sheet
    def prepare(bundles):
        bundles[0]["summons"] = []
        if servant:
            for row in bundles[2]["summons"]:
                row["summon"]["command_group"] = "foreign_test"
                row["actor_template"]["creature_types"] = kinds
                row["actor_template"]["maximum_hp"] = 1000
        else:
            bundles[2]["summons"] = []
            bundles[2]["actor_template"]["creature_types"] = kinds
        for bundle in bundles:
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)
    talent = "TAL_DEATH_CORPSE_EXPLOSION" if servant else "TAL_DEATH_DEATHLY_PASSAGE"
    combat, table, mid = fixture(tmp_path, [talent], cl=5, bundle_transform=prepare,
                                foe_sheet=sheet(["TAL_DEATH_WITHERING_HAND"] if servant else [], cl=5))
    engine = reload(tmp_path, mid)
    subject = next(a for a in engine.state.actors.values() if a.summon and a.summon.get("owner") == FOE) if servant else engine.state.actors[FOE]
    assert list(subject.creature_types) == kinds
    if servant:
        assert subject.summon["command_group"] != "death"
    offered = actions(combat, mid, talent)
    assert offered
    if servant:
        use(combat, table, mid, "Corpse Explosion", at=(subject.position.x, subject.position.y),
            choices={"choice:needle.corpse_explosion_source": [subject.entity_id],
                     "choice:needle.corpse_explosion_damage": ["PIERCING"]})
        engine = reload(tmp_path, mid)
        survivor = engine.state.actors[subject.entity_id]
        assert survivor.active and 0 < survivor.current_hp < survivor.maximum_hp
        assert not any(e.event_type == "ENTITY_DEFEATED" and e.actor_id == subject.entity_id for e in engine.events)
    else:
        assert all(c.destination and engine.grid.distance_ft(c.destination, subject.position) <= 5 for c in offered)
        settle(table, mid, offered[0].candidate_id)
        engine = reload(tmp_path, mid)
        assert engine.state.actors[OWNER].position != Position(x=3, y=6)
        assert engine.grid.distance_ft(engine.state.actors[OWNER].position, subject.position) <= 5
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == (97 if servant else 98)


@pytest.mark.parametrize("kind,x,bonus", [("grave_marker", 4, True), ("bone_pile", 4, True),
                                         ("funerary_object", 4, True), ("corpse", 4, True),
                                         ("grave_marker", 10, False), ("crate", 4, False)])
def test_bone_ward_conditional_bonus_table_reload(tmp_path, kind, x, bonus):
    def prepare(bundles):
        seal_setup(bundles[0], {"kind": kind, "x": x})
        sealed_native_attack(bundles[2], "Grave test blow", damage_type="FIRE", count=1, sides=2, modifier=40)
    combat, table, mid = fixture(tmp_path, ["TAL_DEATH_BONE_WARD"], cl=10, bundle_transform=prepare)
    use(combat, table, mid, "Place funerary remains")
    engine = reload(tmp_path, mid)
    row = next(r for r in engine.typed_reaction_rows[OWNER] if r.get("feature_id") == "TAL_DEATH_BONE_WARD")
    from combat.ext.death_riders import bone_ward_remains
    assert bone_ward_remains(engine, engine.state.actors[OWNER], engine.state.actors[ALLY], None, row) == (4 if bonus else 0)
    turn(table, mid, FOE)
    use(combat, table, mid, "Grave test blow", target=ALLY,
        choices={"reaction:typed.TAL_DEATH_BONE_WARD": "first"})
    engine = reload(tmp_path, mid)
    reductions = [e for e in engine.events if e.event_type == "REACTION_RESOLVED"
                  and e.actor_id == OWNER]
    assert reductions
    reduction_roll = next(r for r in reversed(engine.rolls) if r.actor_id == OWNER and r.expression.startswith("1d8"))
    assert reductions[-1].payload["reduction"] == reduction_roll.total + (4 if bonus else 0)
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == 99
    assert engine.state.actors[ALLY].current_hp < engine.state.actors[ALLY].maximum_hp


@pytest.mark.parametrize("marked_owner,legal", [(OWNER, True), (FOE, False), (None, False)])
def test_deathly_passage_owned_anchor_choice_and_reload(tmp_path, marked_owner, legal):
    def prepare(bundles):
        seal_setup(bundles[0], {"kind": "funerary_object", "x": 8, "owner": marked_owner})
    combat, table, mid = fixture(tmp_path, ["TAL_DEATH_DEATHLY_PASSAGE"], bundle_transform=prepare)
    use(combat, table, mid, "Place funerary remains")
    engine = reload(tmp_path, mid)
    offered = actions(combat, mid, "TAL_DEATH_DEATHLY_PASSAGE")
    assert bool(offered) is legal
    if not legal:
        assert not grave_anchors(engine, engine.state.actors[OWNER])
        return
    assert all(c.destination and engine.grid.distance_ft(c.destination, Position(x=8, y=6)) <= 5 for c in offered)
    chosen = offered[0]
    prompts = settle(table, mid, chosen.candidate_id)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.teleport_destination" for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].position != Position(x=3, y=6)
    assert engine.grid.distance_ft(engine.state.actors[OWNER].position, Position(x=8, y=6)) <= 5
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == 98


def test_sovereign_form_hand_flight_resistance_and_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, ["TAL_DEATH_WITHERING_HAND", "TAL_DEATH_DEATH_SOVEREIGN_INCARNATION"],
                                foe_position={"x": 5, "y": 6})
    engine = reload(tmp_path, mid)
    assert not any(engine.action_catalog[c.source_definition_id].parameters["typed"].get(FREE_HAND)
                   for c in actions(combat, mid, "TAL_DEATH_WITHERING_HAND"))
    assert not any("Incarnation" in engine.action_catalog[c.source_definition_id].display_name
                   for c in actions(combat, mid, "TAL_DEATH_WITHERING_HAND"))
    use(combat, table, mid, "Death-Sovereign Incarnation")
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert any(c.condition_id == SOVEREIGN for c in owner.conditions.values())
    from combat.ext.death_riders import sovereign_flight, sovereign_physical_defenses
    assert flight.profile(engine, owner).speed_ft == 40
    assert flight.profile(engine, owner).hover
    assert engine._effective_speed(owner) == owner.speed_ft
    assert sovereign_physical_defenses(engine, owner, "SLASHING", {}, FOE)[0]["mundane_only"]
    free = [c for c in actions(combat, mid, "TAL_DEATH_WITHERING_HAND")
            if engine.action_catalog[c.source_definition_id].parameters["typed"].get(FREE_HAND)]
    assert free
    session = combat._load_session(mid)
    c = free[0]
    # The journaled session path, never the bare engine's execute_intent.
    session.mechanical.execute_intent(ActionIntent(intent_id="a2-free-hand", decision_id=c.decision_id,
        candidate_id=c.candidate_id, state_version=c.state_version, actor_id=OWNER,
        target_ids=c.target_ids, destination=c.destination))
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    assert owner.action_available
    assert owner.turn_flags[FREE_HAND] == owner.turns_started
    assert any(r.actor_id == OWNER and r.expression.startswith(("6d10", "12d10")) for r in engine.rolls)
    assert not any(engine.action_catalog[c.source_definition_id].parameters["typed"].get(FREE_HAND)
                   for c in actions(combat, mid, "TAL_DEATH_WITHERING_HAND"))
    # Ordinary Hand remains, and also receives the active replacement.
    from combat.ext.death_riders import sovereign_hand_damage
    from combat.typed_executor import Context
    action = next(a for a in engine.action_catalog.values() if a.owner_id == OWNER
                  and ((a.parameters or {}).get("typed") or {}).get("source") == "TAL_DEATH_WITHERING_HAND")
    ctx = Context(engine, owner, action, None, action.parameters["typed"], [])
    dice = sovereign_hand_damage(ctx, None)
    assert (dice.count, dice.sides, dice.modifier) == (6, 10, 0)
    assert sovereign_flight(engine, engine.state.actors[ALLY]) is None


@pytest.mark.parametrize("ranged", [False, True], ids=["melee", "ranged"])
def test_countered_free_hand_spent_at_activation_table_reload_next_turn(tmp_path, ranged):
    from combat.gate2_runtime_models import ReactionDecision
    from tests.h1_support import sheet
    from tests.test_r9i_karma_persistence import act

    counter = "TAL_VOID_RETURN_THE_TECHNIQUE_TO_NOTHING"
    reaction_source = "reaction:typed." + counter

    def free_modes(engine):
        return {row.source_definition_id for row in engine.legal_candidates()
                if row.source_definition_id in engine.action_catalog
                and engine.action_catalog[row.source_definition_id].parameters.get("typed", {}).get(FREE_HAND)}

    def prepare(bundles):
        for bundle in bundles:
            bundle["summons"] = []
            bundle["actor_template"]["maximum_hp"] = 2000
            if bundle["actor_id"] == FOE:
                reaction = next(r for r in bundle["typed_reactions"] if r["feature_id"] == counter)
                # Seal a guaranteed successful real counter contest, not an engine patch.
                reaction["numbers"]["key_mod"] = 100
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, mid = fixture(tmp_path,
        ["TAL_DEATH_WITHERING_HAND", "TAL_DEATH_DEATH_SOVEREIGN_INCARNATION"],
        foe_sheet=sheet([counter], cl=17), bundle_transform=prepare,
        positions={OWNER: {"x": 3, "y": 5}, ALLY: {"x": 3, "y": 7}, FOE: {"x": 4, "y": 5}})
    # Decline the counter to the form itself; reserve it for the free Hand.
    use(combat, table, mid, "Death-Sovereign Incarnation")
    name = "Withering Hand" + (" (ranged)" if ranged else "") + " (Death-Sovereign, no Action)"
    c = candidate(combat, mid, name, target=FOE)
    before = reload(tmp_path, mid).state.model_dump(mode="json")
    pending = act(table, mid, c.candidate_id)
    assert pending["status"] == "REACTION_REQUIRED"
    context = pending["reaction"]["context"]
    assert context["reaction_source_id"] == reaction_source
    # A pending Ask-me response must roll the early allowance spend back.
    assert reload(tmp_path, mid).state.model_dump(mode="json") == before
    session = combat._load_session(mid)
    assert len(free_modes(reload(tmp_path, mid))) == 2
    sequence = session.engine.state.event_sequence
    session.mechanical.execute_intent(ActionIntent(
        intent_id="a2-countered-free-hand", decision_id=c.decision_id, candidate_id=c.candidate_id,
        state_version=c.state_version, actor_id=OWNER, target_ids=c.target_ids,
        reaction_decisions=(ReactionDecision(
            checkpoint=context["checkpoint"], reactor_id=context["reactor_id"],
            reaction_source_id=reaction_source, selection="USE"),)))
    engine = reload(tmp_path, mid)
    assert any("fails to take hold" in str(e.payload) for e in engine.events if e.sequence > sequence)
    assert not any(e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == c.source_definition_id
                   for e in engine.events if e.sequence > sequence)
    owner = engine.state.actors[OWNER]
    assert owner.action_available
    assert owner.turn_flags[FREE_HAND] == owner.turns_started
    assert not engine.state.actors[FOE].reaction_available
    assert not free_modes(engine)
    old_turn = owner.turns_started
    # End via the persisted session, then advance the table to the next owner turn.
    from combat.gate2_runtime_models import CandidateKind
    end = next(row for row in engine.legal_candidates() if row.kind == CandidateKind.END_TURN)
    combat._load_session(mid).mechanical.execute_intent(ActionIntent(
        intent_id="a2-countered-hand-end", decision_id=end.decision_id, candidate_id=end.candidate_id,
        state_version=end.state_version, actor_id=OWNER))
    turn(table, mid, OWNER)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].turns_started == old_turn + 1
    assert len(free_modes(engine)) == 2


@pytest.mark.parametrize("cl,expression", [(5, "4d6"), (11, "6d6"), (17, "8d6")])
def test_corpse_explosion_uses_and_destroys_its_corpse_table_reload(tmp_path, cl, expression):
    def prepare(bundles):
        seal_setup(bundles[0], {"kind": "corpse", "x": 8})
    combat, table, mid = fixture(tmp_path, ["TAL_DEATH_CORPSE_EXPLOSION"], cl=cl, bundle_transform=prepare,
                                foe_position={"x": 7, "y": 6}, owner_dc=50)
    use(combat, table, mid, "Place funerary remains")
    engine = reload(tmp_path, mid)
    offered = actions(combat, mid, "TAL_DEATH_CORPSE_EXPLOSION")
    assert offered and all(c.destination == Position(x=8, y=6) for c in offered)
    blast_source = offered[0].source_definition_id
    prompts = use(combat, table, mid, "Corpse Explosion", at=(8, 6),
                  choices={"choice:needle.corpse_explosion_damage": "PIERCING"})
    assert sum(p["context"]["reaction_source_id"] == "choice:needle.corpse_explosion_damage" for p in prompts) == 1
    engine = reload(tmp_path, mid)
    assert engine.state.objects["object:test.grave"].destroyed
    assert any(r.expression.startswith(expression) for r in engine.rolls)
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == 97
    assert engine.state.actors[FOE].current_hp < engine.state.actors[FOE].maximum_hp
    packets = [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and e.actor_id == OWNER
               and e.source_definition_id == blast_source]
    assert packets and all(e.payload["damage_type"] == "PIERCING" for e in packets)
    assert not actions(combat, mid, "TAL_DEATH_CORPSE_EXPLOSION")  # Action spent too
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    assert not actions(combat, mid, "TAL_DEATH_CORPSE_EXPLOSION")  # source gone after reload


def test_sovereign_resists_only_nonmagical_physical_packets_at_table(tmp_path):
    def prepare(bundles):
        for name, mundane in [("Ordinary grave blow", True), ("Magical grave blow", False)]:
            source = sealed_native_attack(bundles[2], name, damage_type="SLASHING", sides=2, modifier=20)
            action = next(a for a in bundles[2]["action_catalog"] if a["source_definition_id"] == source)
            action["economy"] = "NONE"  # test creature can deliver both packets in one turn
            action["parameters"]["typed"] = {"mundane": mundane}
            action["parameters"]["free_primary"] = True  # explicit free activation; NONE alone is not a turn intent (ad49b65f)
        bundles[2].pop("bundle_sha256", None)
        bundles[2]["bundle_sha256"] = canonical_sha256(bundles[2])
    combat, table, mid = fixture(tmp_path, ["TAL_DEATH_DEATH_SOVEREIGN_INCARNATION"], bundle_transform=prepare)
    use(combat, table, mid, "Death-Sovereign Incarnation")
    turn(table, mid, FOE)
    for name, divisor in [("Ordinary grave blow", 2), ("Magical grave blow", 1)]:
        use(combat, table, mid, name, target=OWNER)
        engine = reload(tmp_path, mid)
        source = next(a.source_definition_id for a in engine.action_catalog.values() if a.display_name == name)
        packet = next(e for e in reversed(engine.events) if e.event_type == "DAMAGE_COMMITTED" and e.source_definition_id == source)
        roll = next(r for r in reversed(engine.rolls) if r.actor_id == FOE and r.reason.startswith("DAMAGE"))
        assert packet.payload["hp_damage"] == roll.total // divisor


def test_corpse_explosion_destroys_its_servant_and_cannot_reuse_it(tmp_path):
    combat, table, mid = fixture(tmp_path, ["TAL_DEATH_CORPSE_EXPLOSION"], cl=5)
    engine = reload(tmp_path, mid)
    servant = next(a for a in engine.state.actors.values() if a.summon and a.summon.get("owner") == OWNER)
    use(combat, table, mid, "Corpse Explosion", at=(servant.position.x, servant.position.y))
    engine = reload(tmp_path, mid)
    assert not engine.state.actors[servant.entity_id].active
    destroyed = [e for e in engine.events if e.event_type == "ENTITY_DEFEATED" and e.actor_id == servant.entity_id]
    assert len(destroyed) == 1
    from combat.ext.death_riders import explosion_sources
    assert servant.entity_id not in explosion_sources(engine, engine.state.actors[OWNER])


def test_corpse_explosion_consumes_a_recorded_actor_corpse_after_reload(tmp_path):
    from combat.ext.death_riders import explosion_sources
    from combat.ext.life_state import is_deceased

    combat, table, mid = fixture(tmp_path, ["TAL_DEATH_CORPSE_EXPLOSION"], cl=5,
        bundle_transform=lambda bundles: seal_setup(bundles[0], {"kind": "actor_corpse", "x": 4}))
    use(combat, table, mid, "Place funerary remains")
    engine = reload(tmp_path, mid)
    assert is_deceased(engine.state.actors[ALLY])
    assert ALLY in explosion_sources(engine, engine.state.actors[OWNER])
    body = engine.state.actors[ALLY]
    use(combat, table, mid, "Corpse Explosion", at=(body.position.x, body.position.y),
        choices={"choice:needle.corpse_explosion_source": [ALLY],
                 "choice:needle.corpse_explosion_damage": ["PIERCING"]})
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == "condition:typed.corpse_consumed"
               for c in engine.state.actors[ALLY].conditions.values())
    assert ALLY not in explosion_sources(engine, engine.state.actors[OWNER])
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == 97


def test_corpse_explosion_does_not_instantly_destroy_another_casters_servant(tmp_path):
    from tests.h1_support import sheet

    def durable_foreign_servant(bundles):
        bundles[0]["summons"] = []
        for servant in bundles[2]["summons"]:
            servant["actor_template"]["maximum_hp"] = 1000
        for bundle in (bundles[0], bundles[2]):
            bundle.pop("bundle_sha256", None)
            bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, mid = fixture(tmp_path, ["TAL_DEATH_CORPSE_EXPLOSION"], cl=5,
                                foe_sheet=sheet(["TAL_DEATH_WITHERING_HAND"], cl=5),
                                bundle_transform=durable_foreign_servant)
    engine = reload(tmp_path, mid)
    servant = next(a for a in engine.state.actors.values() if a.summon and a.summon.get("owner") == FOE)
    use(combat, table, mid, "Corpse Explosion", at=(servant.position.x, servant.position.y),
        choices={"choice:needle.corpse_explosion_source": [servant.entity_id],
                 "choice:needle.corpse_explosion_damage": ["PIERCING"]})
    engine = reload(tmp_path, mid)
    survivor = engine.state.actors[servant.entity_id]
    assert survivor.active and 0 < survivor.current_hp < survivor.maximum_hp
    assert not any(e.event_type == "ENTITY_DEFEATED" and e.actor_id == servant.entity_id for e in engine.events)
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == 97


def test_declining_the_corpse_source_cancels_damage_and_consumption(tmp_path):
    combat, table, mid = fixture(tmp_path, ["TAL_DEATH_CORPSE_EXPLOSION"], cl=5,
                                bundle_transform=lambda bundles: seal_setup(bundles[0], {"kind": "corpse", "x": 8}))
    use(combat, table, mid, "Place funerary remains")
    use(combat, table, mid, "Corpse Explosion", at=(8, 6),
        choices={"choice:needle.corpse_explosion_source": None})
    engine = reload(tmp_path, mid)
    assert not engine.state.objects["object:test.grave"].destroyed
    assert engine.state.actors[FOE].current_hp == engine.state.actors[FOE].maximum_hp
    assert engine.state.actors[OWNER].resources["resource:core.qi"] == 97


def test_sovereign_free_use_refreshes_and_form_expires_after_ten_rounds(tmp_path):
    from tests.h1_support import sheet
    from combat.gate2_runtime_models import CandidateKind
    foe = sheet([], cl=15)
    foe["ability_scores_and_statistics"]["hit_points"]["maximum"] = 2000
    combat, table, mid = fixture(tmp_path, ["TAL_DEATH_DEATH_SOVEREIGN_INCARNATION"], foe_sheet=foe)
    use(combat, table, mid, "Death-Sovereign Incarnation")
    session = combat._load_session(mid)
    start_round = session.engine.state.round_number
    source_slot = session.engine.state.current_slot_index
    owner_turn = session.engine.state.actors[OWNER].turns_started
    for index in range(60):
        engine = session.engine
        if (engine.state.round_number == start_round + 10 and engine.state.current_slot_index == source_slot):
            break
        c = next(c for c in engine.legal_candidates() if c.kind == CandidateKind.END_TURN)
        session.mechanical.execute_intent(ActionIntent(intent_id=f"a2-expiry-{index}", decision_id=c.decision_id,
            candidate_id=c.candidate_id, state_version=c.state_version, actor_id=engine.state.current_actor_id,
            target_ids=c.target_ids))
        if engine.state.current_actor_id == OWNER and engine.state.actors[OWNER].turns_started == owner_turn + 1:
            assert any(engine.action_catalog[c.source_definition_id].parameters["typed"].get(FREE_HAND)
                       for c in actions(combat, mid, "TAL_DEATH_WITHERING_HAND"))
    else:
        raise AssertionError("The form's expiry boundary was not reached")
    engine = reload(tmp_path, mid)
    assert not any(c.condition_id == SOVEREIGN for c in engine.state.actors[OWNER].conditions.values())
    assert flight.profile(engine, engine.state.actors[OWNER]).speed_ft == 0
    assert not any(engine.action_catalog[c.source_definition_id].parameters["typed"].get(FREE_HAND)
                   for c in actions(combat, mid, "TAL_DEATH_WITHERING_HAND"))
