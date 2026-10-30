"""A2TAL: printed talisman choices via service commits and cold replay.

Only genesis setup adds synthetic injury/concealment and a second healing roll.
Every actual action goes through session.mechanical or the table transaction.
No live actor state is edited and no GUI or bare-engine intent is executed.
"""
from copy import deepcopy

import pytest

from combat.canonical import canonical_sha256
from combat.ext.talismans import PREPARED, TALENT
from combat.gate2_runtime_models import ActionIntent
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn
from tests.h1_support import script, sheet
from tests.hunt12_support import send

BINDING = TALENT + "binding_talisman"
HEALING = TALENT + "healing_talisman"
EMBER = TALENT + "ember_talisman"
DEMON = TALENT + "demon_subduing_tag"
PURIFY = TALENT + "purifying_talisman"
REMOTE = TALENT + "remote_activation"
AFFINITY = TALENT + "talisman_affinity"
FAMILY = "condition:typed.talisman_affinity"
HOLD = "condition:typed.demon_subduing_site"
CHOOSE = "Talisman Affinity: choose a formula family"
PICK = "choice:needle.talisman_affinity_family"
CRAFT = "choice:needle.talisman_affinity_benefit"


def setup(bundles, *, double_healing=False):
    """Seal a free self-injury and a free ally-concealment in test genesis."""
    bundle = bundles[0]
    base = deepcopy(next(row for row in bundle["action_catalog"] if row.get("resolution_kind") == "TYPED"))
    for name, effects, target in (
        ("Test injury", [{"type": "damage", "applies_to": "self", "flat": 40, "damage_types": ["force"]}], "SELF"),
        ("Test concealment", [{"type": "condition", "condition": "invisible", "applies_to": "target",
                              "expires_on": "UNTIL_REMOVED"}], "ALLY_OR_SELF"),
        ("Test separate restraint", [{"type": "condition", "condition": "restrained", "applies_to": "target",
                                     "expires_on": "UNTIL_REMOVED"}], "HOSTILE_ENTITY")):
        action = deepcopy(base)
        action.update(source_definition_id="test:talismans." + name, display_name=name,
                      economy="NONE", target_kind=target, range_ft=60, costs=[])
        typed = action["parameters"]["typed"]
        typed.update(source="test:talismans." + name, effects=effects, riders=[], duration={"kind": "instant"})
        # A free activation: combat/primary_intents.allows_primary only offers an EconomyKind.NONE action that says so,
        # so without this the synthetic test actions never reach the menu (corkboard #5175).
        action["parameters"]["free_primary"] = True
        action["parameters"].pop("remote_activation", None)
        action["parameters"].pop("remote_perception_required", None)
        bundle["action_catalog"].append(action)
        bundle["actor_template"]["action_ids"].append(action["source_definition_id"])
    if double_healing:
        action = next(row for row in bundle["action_catalog"] if row["source_definition_id"].endswith(HEALING))
        effects = action["parameters"]["typed"]["effects"]
        healing = next(row for row in effects if row["type"] == "healing")
        effects.append(deepcopy(healing))
    bundle["bundle_sha256"] = canonical_sha256({k: v for k, v in bundle.items() if k != "bundle_sha256"})


def scrambled_invisibility(bundles):
    """A deny-invisibility effect whose printed sentence is pseudo-words (the public export scrambles prose).

    The typed duration is untouched, so it must decide the expiry: F10 batch, Demon-Subduing Tag's
    `deny_invisible` row fell back to `START_OF_SOURCE_NEXT_TURN` and the ordinary tag's conditions then
    outlived the caster's next turn on the public export.
    """
    bundle = bundles[0]
    base = deepcopy(next(row for row in bundle["action_catalog"] if row.get("resolution_kind") == "TYPED"))
    action = deepcopy(base)
    action.update(source_definition_id="test:talismans.scrambled invisibility",
                  display_name="Test scrambled invisibility", economy="NONE", target_kind="HOSTILE_ENTITY",
                  range_ft=60, costs=[])
    typed = action["parameters"]["typed"]
    typed.update(source="test:talismans.scrambled invisibility", riders=[], duration={"kind": "instant"}, effects=[
        {"type": "deny_invisible", "applies_to": "target", "duration": "until_end_of_your_next_turn",
         "evidence": "ehfufy turn lfamgeofm mlvpg the end of monc gphg turn"}])
    action["parameters"]["free_primary"] = True
    action["parameters"].pop("remote_activation", None)
    action["parameters"].pop("remote_perception_required", None)
    bundle["action_catalog"].append(action)
    bundle["actor_template"]["action_ids"].append(action["source_definition_id"])
    bundle["bundle_sha256"] = canonical_sha256({k: v for k, v in bundle.items() if k != "bundle_sha256"})


def execute(combat, mid, chosen, *, dice=None):
    """Explicit persisted service/session path, per corkboard #1545."""
    session = combat._load_session(mid)
    if dice is not None:
        script(session.mechanical.engine, dice)
    session.mechanical.execute_intent(ActionIntent(
        intent_id=f"a2tal:{len(session.engine.events)}", decision_id=chosen.decision_id,
        candidate_id=chosen.candidate_id, state_version=chosen.state_version, actor_id=chosen.actor_id,
        target_ids=chosen.target_ids or (), destination=chosen.destination))


def take(combat, table, mid, name, target=None, choices=None):
    chosen = candidate(combat, mid, name, target=target)
    return settle(table, mid, chosen.candidate_id, choices=choices or {})


def family(combat, table, mid, name):
    return take(combat, table, mid, CHOOSE, choices={PICK: name})


@pytest.mark.parametrize("distance", [35, 60])
def test_binding_throw_reaches_beyond_normal_range_and_reloads(tmp_path, distance):
    combat, table, mid = fixture(tmp_path, [BINDING], owner_dc=100,
                                positions={OWNER: {"x": 1, "y": 1}, ALLY: {"x": 2, "y": 1},
                                           FOE: {"x": 1 + distance // 5, "y": 1}})
    engine = combat._load_session(mid).engine
    assert not any(c.display_name == "Binding Talisman" and c.target_ids == (FOE,)
                   for c in engine.legal_candidates())
    before = engine.state.actors[OWNER].resources[PREPARED]
    execute(combat, mid, candidate(combat, mid, "Binding Talisman (throw, 20/60 feet)", target=FOE))
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[PREPARED] == before - 1
    restrained = [c for c in engine.state.actors[FOE].conditions.values()
                  if c.condition_id == "condition:typed.restrained"]
    assert len(restrained) == 1 and restrained[0].data["repeat_save"]["ability"] == "STR"
    assert len([r for r in engine.rolls if r.reason.startswith("SAVE:") and ":STR" in r.reason]) == 1
    assert not any(e.event_type == "GM_RIDER" for e in engine.events if e.source_definition_id.endswith(BINDING))


def test_binding_throw_cannot_exceed_sixty_feet(tmp_path):
    combat, table, mid = fixture(tmp_path, [BINDING],
                                positions={OWNER: {"x": 1, "y": 1}, ALLY: {"x": 2, "y": 1},
                                           FOE: {"x": 14, "y": 1}})
    assert not any(c.display_name.startswith("Binding Talisman") and c.target_ids == (FOE,)
                   for c in combat._load_session(mid).engine.legal_candidates())
    execute(combat, mid, next(c for c in combat._load_session(mid).engine.legal_candidates()
                              if c.display_name == "End turn"))
    reload(tmp_path, mid)


def test_binding_throw_with_remote_activation_keeps_its_thrown_reach(tmp_path):
    combat, table, mid = fixture(tmp_path, [BINDING, REMOTE], owner_dc=100, positions={
        OWNER: {"x": 1, "y": 1}, ALLY: {"x": 2, "y": 1}, FOE: {"x": 13, "y": 1}})
    prompts = take(combat, table, mid, "Binding Talisman (throw, 20/60 feet)", FOE,
                   {"choice:needle.talisman_remote_holder": ALLY,
                    "choice:needle.talisman_remote": "lets it happen"})
    holder = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.talisman_remote_holder")
    assert ALLY in {o["id"] for o in holder["choice"]["options"]}
    consent = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.talisman_remote")
    assert consent["context"]["reactor_id"] == ALLY
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == "condition:typed.restrained" for c in engine.state.actors[FOE].conditions.values())
    assert not any("cannot affect" in str(e.payload) for e in engine.events)


@pytest.mark.parametrize("dc, consumed", [(100, True), (1, False)])
def test_thrown_remote_unwilling_holder_save_controls_consumption(tmp_path, dc, consumed):
    combat, table, mid = fixture(tmp_path, [BINDING, REMOTE], owner_dc=dc)
    before = combat._load_session(mid).engine.state.actors[OWNER].resources[PREPARED]
    prompts = take(combat, table, mid, "Binding Talisman (throw, 20/60 feet)", FOE,
                   {"choice:needle.talisman_remote_holder": FOE,
                    "choice:needle.talisman_remote": "refuses"})
    assert any(p["context"]["reaction_source_id"] == "choice:needle.talisman_remote_holder" for p in prompts)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.talisman_remote"
               and p["context"]["reactor_id"] == FOE for p in prompts)
    engine = reload(tmp_path, mid)
    saves = [e for e in engine.events if e.event_type == "SAVE_ROLLED"]
    assert any(":WIS" in str(e.payload) for e in saves)
    assert bool(any(":STR" in str(e.payload) for e in saves)) == consumed
    assert engine.state.actors[OWNER].resources[PREPARED] == before - int(consumed)


def test_thrown_binding_preserves_seal_reaction_and_changed_save(tmp_path, monkeypatch):
    from combat.ext.save_recheck import SEAL
    import tests.worker2_support as support

    original = support.sheet

    def sealed_sheet(talents, **kwargs):
        if SEAL in talents:
            kwargs["foundation"] = {"foundation_id": "golden_mandate_seal_v0_2B", "stage": "Perfected", "status": "active",
                                    "resource": {"name": "Edict Seal", "resource_id": "edict_seal",
                                                 "maximum": 1, "current": 1}}
        return original(talents, **kwargs)

    monkeypatch.setattr(support, "sheet", sealed_sheet)
    combat, table, mid = fixture(tmp_path, [BINDING, SEAL], owner_dc=16)
    prompts = take(combat, table, mid, "Binding Talisman (throw, 20/60 feet)", FOE,
                   {"reaction:typed." + SEAL: "USE"})
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == "reaction:typed." + SEAL)
    assert prompt["context"]["reactor_id"] == OWNER
    assert "Binding Talisman" in str(prompt) and "Seal of Final Authority" in str(prompt)
    engine = reload(tmp_path, mid)
    save = next(e for e in reversed(engine.events) if e.event_type == "SAVE_ROLLED")
    assert save.payload["success"] is False
    rewrite = next(e for e in engine.events if e.event_type == "D20_REWRITTEN" and e.source_definition_id == SEAL)
    assert rewrite.payload["original"]["total"] >= save.payload["dc"] > rewrite.payload["result"]["total"]
    assert any(c.condition_id == "condition:typed.restrained" for c in engine.state.actors[FOE].conditions.values())
    assert any(c.condition_id == "condition:typed.reaction_denied" for c in engine.state.actors[FOE].conditions.values())
    assert any(e.event_type == "RESOURCE_SPENT" and e.source_definition_id == SEAL
               and e.payload["resource_id"] == "resource:foundation.edict_seal" and e.payload["amount"] == 1
               for e in engine.events)
    # Golden Mandate generates an Edict Seal when its Binding command succeeds.
    assert engine.state.actors[OWNER].resources["resource:foundation.edict_seal"] == 1


@pytest.mark.parametrize("automatic", [False, True])
def test_site_repeat_save_offers_affliction_response_with_caster_and_hazard(tmp_path, automatic):
    from combat.ext.d20_rewrite_rules import COUNTER_EVOLUTION

    def names(bundles):
        for bundle in bundles:
            bundle["actor_template"]["display_name"] = "Seal caster" if bundle["actor_id"] == OWNER else "Seal defender"
            bundle["bundle_sha256"] = canonical_sha256({k: v for k, v in bundle.items() if k != "bundle_sha256"})

    combat, table, mid = fixture(tmp_path, [DEMON], owner_dc=100, cl=18,
                                foe_sheet=sheet([COUNTER_EVOLUTION], cl=18, primary="Stamina"), bundle_transform=names)
    rid = "reaction:typed." + COUNTER_EVOLUTION
    # The initial save asks this manual defender during the hostile caster's turn.
    initial = take(combat, table, mid, "Demon-Subduing Tag (prepared site seal)", FOE, {rid: None})
    assert any(p["context"]["reactor_id"] == FOE and p["context"]["reaction_source_id"] == rid for p in initial)
    reload(tmp_path, mid)
    turn(table, mid, FOE)
    if automatic:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    before = combat._load_session(mid).engine.state.actors[FOE].resources["resource:core.stamina"]
    end = next(c for c in combat._load_session(mid).engine.legal_candidates() if c.display_name == "End turn")
    if automatic:
        assert send(combat, table, mid, end, auto=True)["status"] == "COMMITTED"
    else:
        prompts = settle(table, mid, end.candidate_id, choices={rid: "USE"})
        prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == rid)
        assert prompt["context"]["reactor_id"] == FOE
        assert "Perfect Counter-Evolution" in str(prompt) and "Demon-Subduing Tag" in str(prompt)
        assert prompt["by"] == "Seal caster" and prompt["affected"] == "Seal defender"
    engine = reload(tmp_path, mid)
    # Perfect Counter-Evolution is a Reaction that spends exactly 2 Stamina. The automatic seat may also take
    # Meridians Remember Affliction's *passive* end-of-turn repeat (a separate feature, also 2 Stamina) on the
    # same save, so the auto branch pins the Reaction's own spend instead of the seat's total spend.
    spends = [e for e in engine.events if e.event_type == "RESOURCE_SPENT"
              and e.source_definition_id == COUNTER_EVOLUTION]
    assert [(e.actor_id, e.payload["resource_id"], e.payload["amount"]) for e in spends] == [
        (FOE, "resource:core.stamina", 2)]
    if automatic:
        assert engine.state.actors[FOE].resources["resource:core.stamina"] <= before - 2
    else:
        assert engine.state.actors[FOE].resources["resource:core.stamina"] == before - 2
    assert any(e.event_type == "D20_REWRITTEN" and e.source_definition_id == COUNTER_EVOLUTION for e in engine.events)
    assert any(c.condition_id == HOLD for c in engine.state.actors[FOE].conditions.values())


def test_binding_normal_delivery_does_not_roll_its_repeat_save_immediately(tmp_path):
    combat, table, mid = fixture(tmp_path, [BINDING], owner_dc=100)
    execute(combat, mid, candidate(combat, mid, "Binding Talisman", target=FOE))
    engine = reload(tmp_path, mid)
    assert len([r for r in engine.rolls if r.reason.startswith("SAVE:") and ":STR" in r.reason]) == 1


def test_binding_throw_respects_intervening_pillars(tmp_path):
    combat, table, mid = fixture(tmp_path, [BINDING], positions={
        OWNER: {"x": 1, "y": 6}, ALLY: {"x": 2, "y": 6}, FOE: {"x": 13, "y": 6}})
    assert not any(c.display_name.startswith("Binding Talisman") and c.target_ids == (FOE,)
                   for c in combat._load_session(mid).engine.legal_candidates())
    execute(combat, mid, next(c for c in combat._load_session(mid).engine.legal_candidates() if c.display_name == "End turn"))
    reload(tmp_path, mid)


@pytest.mark.parametrize("benefit, family_name, formula", [
    ("save", "Binding", "Binding Talisman"), ("attack", "Attack", "Ember Talisman")])
def test_affinity_adds_only_the_declared_stored_number(tmp_path, benefit, family_name, formula):
    combat, table, mid = fixture(tmp_path, [AFFINITY, BINDING, EMBER], owner_dc=100)
    family(combat, table, mid, family_name)
    cold = reload(tmp_path, mid)
    assert any(c.condition_id.startswith(FAMILY) for c in cold.state.actors[OWNER].conditions.values())
    action = next(a for a in cold.action_catalog.values() if a.display_name == formula)
    numbers = deepcopy(action.parameters["typed"]["numbers"])
    prepared = cold.state.actors[OWNER].resources[PREPARED]
    prompts = take(combat, table, mid, formula, FOE, {CRAFT: benefit})
    assert any(p["context"]["reaction_source_id"] == CRAFT for p in prompts)
    engine = reload(tmp_path, mid)
    assert engine.action_catalog[action.source_definition_id].parameters["typed"]["numbers"] == numbers
    assert engine.state.actors[OWNER].resources[PREPARED] == prepared - 1
    if benefit == "save":
        events = [e for e in engine.events if e.event_type == "SAVE_ROLLED" and e.source_definition_id == action.source_definition_id]
        assert events and events[-1].payload["dc"] == numbers["save_dc"] + 1
    else:
        events = [e for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.source_definition_id == action.source_definition_id]
        assert events and events[-1].payload["modifier"] == numbers["attack_bonus"] + 1


def test_affinity_family_mismatch_never_asks_or_adds_bonus(tmp_path):
    combat, table, mid = fixture(tmp_path, [AFFINITY, BINDING, EMBER], owner_dc=100)
    family(combat, table, mid, "Attack")
    prompts = take(combat, table, mid, "Binding Talisman", FOE)
    assert not any(p["context"]["reaction_source_id"] == CRAFT for p in prompts)
    engine = reload(tmp_path, mid)
    assert next(e for e in reversed(engine.events) if e.event_type == "SAVE_ROLLED").payload["dc"] == 100


def test_affinity_healing_bonus_is_one_actual_roll(tmp_path):
    combat, table, mid = fixture(tmp_path, [AFFINITY, HEALING], bundle_transform=lambda b: setup(b, double_healing=True))
    execute(combat, mid, candidate(combat, mid, "Test injury"))
    family(combat, table, mid, "Restoration")
    take(combat, table, mid, "Healing Talisman", OWNER, {CRAFT: "healing"})
    engine = reload(tmp_path, mid)
    records = [r for r in engine.rolls if r.reason.startswith("HEALING:")]
    assert len(records) == 2
    assert records[0].modifier - records[1].modifier == engine.state.actors[OWNER].proficiency_bonus


def test_affinity_family_can_only_be_selected_once_per_learning(tmp_path):
    combat, table, mid = fixture(tmp_path, [AFFINITY, HEALING])
    family(combat, table, mid, "Restoration")
    engine = reload(tmp_path, mid)
    assert not any(c.display_name == CHOOSE for c in engine.legal_candidates())


def test_automatic_affinity_owner_does_not_invent_a_stored_crafting_bonus(tmp_path):
    combat, table, mid = fixture(tmp_path, [AFFINITY, EMBER])
    family(combat, table, mid, "Attack")
    action = candidate(combat, mid, "Ember Talisman", target=FOE)
    numbers = combat._load_session(mid).engine.action_catalog[action.source_definition_id].parameters["typed"]["numbers"]
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    assert send(combat, table, mid, action, auto=True)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    roll = next(e for e in reversed(engine.events) if e.event_type == "ATTACK_ROLLED")
    assert roll.payload["modifier"] == numbers["attack_bonus"]


def test_remote_holder_choices_require_perception(tmp_path):
    combat, table, mid = fixture(tmp_path, [PURIFY, REMOTE], bundle_transform=setup)
    execute(combat, mid, candidate(combat, mid, "Test concealment", target=ALLY))
    reload(tmp_path, mid)
    prompts = take(combat, table, mid, "Purifying Talisman", OWNER,
                   {"choice:needle.talisman_remote_holder": ""})
    holder = next(p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.talisman_remote_holder")
    assert ALLY not in {o["id"] for o in holder["choice"]["options"]}
    reload(tmp_path, mid)


def test_demon_subduing_ordinary_expiry_tracks_caster(tmp_path):
    combat, table, mid = fixture(tmp_path, [DEMON], owner_dc=100)
    execute(combat, mid, candidate(combat, mid, "Demon-Subduing Tag", target=FOE))
    engine = reload(tmp_path, mid)
    rows = [c for c in engine.state.actors[FOE].conditions.values() if c.source_definition_id.endswith(DEMON)]
    assert len(rows) == 3 and all(c.expires_on.startswith("END_OF_TURN_AT:" + OWNER + ":")
                                or c.expires_on.startswith("END_OF_SOURCE_TURN_AT:") for c in rows)
    turn(table, mid, FOE)
    execute(combat, mid, next(c for c in combat._load_session(mid).engine.legal_candidates() if c.display_name == "End turn"))
    assert len([c for c in reload(tmp_path, mid).state.actors[FOE].conditions.values() if c.source_definition_id.endswith(DEMON)]) == 3
    turn(table, mid, OWNER)
    execute(combat, mid, next(c for c in combat._load_session(mid).engine.legal_candidates() if c.display_name == "End turn"))
    assert not any(c.source_definition_id.endswith(DEMON) for c in reload(tmp_path, mid).state.actors[FOE].conditions.values())


def test_deny_invisible_reads_its_typed_duration_when_the_printed_sentence_is_scrambled(tmp_path):
    combat, table, mid = fixture(tmp_path, [DEMON], owner_dc=100, bundle_transform=scrambled_invisibility)
    execute(combat, mid, candidate(combat, mid, "Test scrambled invisibility", target=FOE))
    engine = reload(tmp_path, mid)
    owner = engine.state.actors[OWNER]
    rows = [c for c in engine.state.actors[FOE].conditions.values()
            if c.condition_id == "condition:typed.no_invisible"]
    assert [c.expires_on for c in rows] == [f"END_OF_SOURCE_TURN_AT:{owner.turns_started + 1}"]


def test_demon_subduing_site_has_one_shared_repeat_save(tmp_path):
    combat, table, mid = fixture(tmp_path, [DEMON], owner_dc=100)
    execute(combat, mid, candidate(combat, mid, "Demon-Subduing Tag (prepared site seal)", target=FOE))
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == HOLD for c in engine.state.actors[FOE].conditions.values())
    rows = [c for c in engine.state.actors[FOE].conditions.values() if c.source_definition_id.endswith(DEMON)]
    assert len(rows) == 4 and len({c.expires_on for c in rows}) == 1
    assert rows[0].expires_on.startswith("START_OF_SLOT_AT:")
    turn(table, mid, FOE)
    start = len(combat._load_session(mid).engine.rolls)
    execute(combat, mid, next(c for c in combat._load_session(mid).engine.legal_candidates() if c.display_name == "End turn"))
    engine = reload(tmp_path, mid)
    saves = [r for r in engine.rolls[start:] if ":CHA" in r.reason]
    assert len(saves) == 1
    assert any(c.condition_id == HOLD for c in engine.state.actors[FOE].conditions.values())


def test_site_repeat_success_removes_only_its_own_restrictions(tmp_path):
    combat, table, mid = fixture(tmp_path, [DEMON], owner_dc=10, bundle_transform=setup)
    execute(combat, mid, candidate(combat, mid, "Test separate restraint", target=FOE))
    execute(combat, mid, candidate(combat, mid, "Demon-Subduing Tag (prepared site seal)", target=FOE), dice=[1])
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == HOLD for c in engine.state.actors[FOE].conditions.values())
    turn(table, mid, FOE)
    execute(combat, mid, next(c for c in combat._load_session(mid).engine.legal_candidates() if c.display_name == "End turn"), dice=[20])
    engine = reload(tmp_path, mid)
    rows = list(engine.state.actors[FOE].conditions.values())
    assert not any(c.source_definition_id.endswith(DEMON) for c in rows)
    assert any(c.condition_id == "condition:typed.restrained" and c.source_definition_id.startswith("test:") for c in rows)


def test_unowned_character_has_no_new_affinity_or_site_actions(tmp_path):
    combat, table, mid = fixture(tmp_path, [HEALING])
    engine = combat._load_session(mid).engine
    assert not any("Affinity" in a.display_name or "site seal" in a.display_name for a in engine.action_catalog.values())
    execute(combat, mid, candidate(combat, mid, "Healing Talisman", target=OWNER))
    reload(tmp_path, mid)


@pytest.mark.parametrize("cl, grants", [(1, False), (5, True)])
def test_purifying_next_save_uses_printed_level_and_source_expiry(tmp_path, cl, grants):
    combat, table, mid = fixture(tmp_path, [PURIFY], cl=cl)
    execute(combat, mid, candidate(combat, mid, "Purifying Talisman", target=ALLY))
    engine = reload(tmp_path, mid)
    rows = [c for c in engine.state.actors[ALLY].conditions.values()
            if c.condition_id == "condition:typed.save_against"]
    assert bool(rows) == grants
    if grants:
        assert len(rows) == 1
        assert rows[0].expires_on.startswith("END_OF_TURN_AT:" + OWNER + ":") or rows[0].expires_on.startswith("END_OF_SOURCE_TURN_AT:")
        assert rows[0].data["rule"]["save_against"]["next"]
        execute(combat, mid, next(c for c in combat._load_session(mid).engine.legal_candidates() if c.display_name == "End turn"))
        turn(table, mid, OWNER)
        execute(combat, mid, next(c for c in combat._load_session(mid).engine.legal_candidates() if c.display_name == "End turn"))
        assert not any(c.condition_id == "condition:typed.save_against"
                       for c in reload(tmp_path, mid).state.actors[ALLY].conditions.values())
