"""HUNT212 #2/#3/#4/#6: native table commits, cold loads and replay.

Printed rules are quoted beside the regression they govern. Initial bundles
set extreme statistics to isolate hit/save/check outcomes; production effects,
costs, choices and turn clocks are never replaced.
"""
import pytest

from combat.factory_compiler import compile_character
from tests.h1_support import sheet
from tests.cw2_service_support import seal
from tests.worker2_support import OWNER, ALLY, FOE, fixture, candidate, settle, reload, turn

L = "TAL_LIGHTNING_"
DOWNBURST = "TAL_AIR_DOWNBURST_SEAL"
REFLECTION = "tianxia.talent.talismans.talisman_reflection"
HEAL = "tianxia.talent.talismans.healing_talisman"
GEN = "foundation.divine_king_body_v0_2B.generate_moon_sea_radiance"
RADIANCE = "resource:foundation.moon_sea_radiance"


def prepare(bundles):
    for bundle, initiative in zip(bundles, (100, -100, 0)):
        template = bundle["actor_template"]
        template["initiative_bonus"] = initiative
        template["maximum_hp"] = 1000
        template["armor_class"] = 0
        for action in bundle["action_catalog"]:
            if "typed" in action["parameters"]:
                action["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
        seal(bundle)


def events(engine, kind, source=None):
    return [e for e in engine.events if e.event_type == kind
            and (source is None or e.source_definition_id == source)]


def test_first_named_hit_wording_is_deferred_for_any_method():
    from factory_authoring.typed_structure import mark_deferred
    effect = {"type": "extra_damage", "evidence": "Your first Example Method hit each turn deals additional fire damage equal to 1d8."}
    assert mark_deferred([effect])[0]["deferred"] is True


@pytest.mark.parametrize("dc,prone", [(100, True), (-100, False)])
def test_forged_downburst_keeps_its_grounded_knockdown(tmp_path, dc, prone):
    # "Failed Save: A creature takes Wind Lash damage, is pushed to the ground,
    # and falls Prone if it is on a surface." "Successful Save: It takes half
    # damage and does not fall Prone."
    doc = sheet([DOWNBURST], cl=17, dc=dc)
    doc["forged_techniques"] = [{"technique_id": "forged:h212.downburst", "name": "Forged Downburst",
        "primary_sphere_effect": {"talent_id": DOWNBURST}, "base_form": {"form_id": "burst"},
        "drawbacks": [], "augments": [], "table_choices": {}, "cp_cost": {"final": 1}, "action_type": "action"}]
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={"ask": True})
    combat, table, mid = fixture(tmp_path, [DOWNBURST], owner_bundle=owner,
        bundle_transform=prepare, seed=f"H212-DOWN-{dc}")
    cast = candidate(combat, mid, "Forged Downburst", at=(6, 6))
    action = combat._load_session(mid).engine.action_catalog[cast.source_definition_id]
    assert action.parameters["typed"]["forged_from"] == DOWNBURST
    settle(table, mid, cast.candidate_id)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id.endswith(".prone") for c in engine.state.actors[FOE].conditions.values()) is prone
    saves = [e for e in events(engine, "SAVE_ROLLED", cast.source_definition_id) if e.actor_id == FOE]
    assert saves and saves[-1].payload["success"] is not prone
    assert events(engine, "DAMAGE_COMMITTED", cast.source_definition_id)


def test_moon_sea_gain_expires_at_end_of_next_owner_turn(tmp_path):
    # "Gain 1 Moon-Sea Radiance. Maximum 1." "It expires at the end of your
    # next turn." HUNT212 F7 gained at 188 and wrongly remained after 225/554.
    foundation = {"foundation_id": "divine_king_body_v0_2B", "stage": "Awakened",
        "resource": {"name": "Moon-Sea Radiance", "resource_id": "foundation.resource.divine_king_body_v0_2B",
                     "maximum": 1, "current": 0}}
    # The visible pressure save provides the native own_save_failed producer.
    doc = sheet([GEN, "TAL_FORCE_PRESSURE_PIN"], cl=17, dc=100, foundation=foundation)
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={"ask": True})
    combat, table, mid = fixture(tmp_path, [GEN], owner_bundle=owner,
        bundle_transform=prepare, foe_position={"x": 4, "y": 7}, seed="H212-MOON")
    cast = candidate(combat, mid, "Pressure Pin", target=FOE)
    settle(table, mid, cast.candidate_id, picks={GEN: "first"})
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[RADIANCE] == 1
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    assert reload(tmp_path, mid).state.actors[OWNER].resources[RADIANCE] == 1
    turn(table, mid, OWNER)
    settle(table, mid, table.state(mid)["menu"]["end_turn"])
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].resources[RADIANCE] == 0
    assert any(e.source_definition_id == "passive:resource_clock.expired"
               for e in events(engine, "RESOURCE_SPENT"))


@pytest.mark.parametrize("score,redirect", [(50, True), (0, False)])
@pytest.mark.parametrize("auto", [False, True])
def test_reflection_rolls_crafting_check_and_redirects_only_on_success(tmp_path, score, redirect, auto):
    # "Make a Talisman Crafting Check against DC 10 + the attacker’s Proficiency
    # Bonus + the attacker’s relevant ability modifier." "On a success,
    # redirect the effect toward its source or another legal target within the
    # effect’s original range." "On a failure, the talisman is consumed and
    # the effect resolves normally." Core Talisman Rules:
    # "Check: d20 + Proficiency Bonus + Intelligence modifier".
    doc = sheet([REFLECTION, HEAL], cl=17, score=score)
    # Deliberately keep the key modifier different from INT: this is Crafting,
    # not a Cultivation Check using the Path's key ability.
    for ability in doc["ability_scores_and_statistics"]["abilities"]:
        if ability["ability"] != "INT":
            ability.update(score=14, modifier=2)
    owner = compile_character(doc, actor_id=OWNER, reaction_plan={"ask": True})
    combat, table, mid = fixture(tmp_path, [REFLECTION, HEAL], owner_bundle=owner,
        foe_sheet=sheet([L + "LIGHTNING_LASH"], cl=17, score=14 if redirect else 50), bundle_transform=prepare,
        foe_position={"x": 4, "y": 7}, seed=f"H212-REFLECT-{score}-{auto}", named=True)
    turn(table, mid, FOE)
    cast = candidate(combat, mid, "Lightning Lash: Jolt", target=OWNER)
    before = reload(tmp_path, mid).state.actors[OWNER]
    qi = before.resources["resource:core.qi"]
    prepared = before.resources["resource:named.prepared_talismans"]
    if auto:
        from tests.r1i_service_support import force_ai_candidate
        force_ai_candidate(combat, mid, FOE, cast.candidate_id)
    prompts = settle(table, mid, cast.candidate_id, picks={"reaction:typed." + REFLECTION: "first",
        "choice:needle.talisman_reflect": FOE}, auto=auto)
    engine = reload(tmp_path, mid)
    checks = events(engine, "CHECK_ROLLED", REFLECTION)
    assert len(checks) == 1, [(e.event_type, e.payload) for e in engine.events if e.source_definition_id == REFLECTION]
    check = checks[0].payload
    assert check["check"] == "Talisman Crafting Check" and check["dc"] == (16 if redirect else 34)
    assert check["actor"]["modifier"] == 4 + (score - 10) // 2
    assert check["success"] is redirect
    me = engine.state.actors[OWNER]
    assert me.resources["resource:core.qi"] == qi - 5
    assert me.resources["resource:named.prepared_talismans"] == prepared - 1
    assert not me.reaction_available
    damage = events(engine, "DAMAGE_COMMITTED", cast.source_definition_id)
    assert damage and all((FOE if redirect else OWNER) in e.target_ids for e in damage)
    assert any(p["context"]["reaction_source_id"] == "reaction:typed." + REFLECTION for p in prompts)
    choices = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.talisman_reflect"]
    assert bool(choices) is redirect
    if redirect:
        assert ALLY in {o["id"] for o in choices[-1]["choice"]["options"]}
    assert not any("GM" in e.event_type for e in engine.events if e.source_definition_id == REFLECTION)


def _chain_bundles(bundles, ally):
    # Same extreme-statistics transform as ``prepare`` for the replacement
    # recipient bundle, so only the outcomes under test are isolated.
    for bundle, initiative in zip(bundles, (100, -200, 0)):
        template = bundle["actor_template"]
        template["initiative_bonus"] = initiative
        template["maximum_hp"] = 1000
        template["armor_class"] = 0
        for action in bundle["action_catalog"]:
            if "typed" in action["parameters"]:
                action["parameters"]["typed"]["numbers"]["attack_bonus"] = 100
        seal(bundle)
    bundles[1] = ally
    template = ally["actor_template"]
    template["initiative_bonus"] = -200
    template["maximum_hp"] = 1000
    template["armor_class"] = 0
    seal(ally)


@pytest.mark.parametrize("auto", [False, True])
def test_redirected_recipient_keeps_its_own_target_reactions(tmp_path, auto):
    # "On a success, redirect the effect toward its source or another legal
    # target within the effect's original range." Core Talisman Rules. The
    # creature a redirect lands on is the declaration's target now, so it
    # answers with its own target-triggered reactions: here a second Talisman
    # Reflection (Wren reflects Lightning Lash to Tobin, Tobin reflects it
    # on to Mara, and Mara finally takes the hit).
    owner = compile_character(sheet([REFLECTION, HEAL], cl=17, score=50), actor_id=OWNER, reaction_plan={"ask": True})
    ally = compile_character(sheet([REFLECTION], cl=17, score=50), actor_id=ALLY, reaction_plan={"ask": True})
    combat, table, mid = fixture(tmp_path, [REFLECTION, HEAL], owner_bundle=owner,
        bundle_transform=lambda bundles: _chain_bundles(bundles, ally),
        foe_sheet=sheet([L + "LIGHTNING_LASH"], cl=17, score=14),
        foe_position={"x": 4, "y": 7}, seed=f"H212-CHAIN-{auto}", named=True)
    turn(table, mid, FOE)
    cast = candidate(combat, mid, "Lightning Lash: Jolt", target=OWNER)
    purses = {aid: reload(tmp_path, mid).state.actors[aid] for aid in (OWNER, ALLY)}
    prompts = settle(table, mid, cast.candidate_id, picks={"reaction:typed." + REFLECTION: "first",
        "choice:needle.talisman_reflect": (ALLY, FOE)}, auto=auto)
    engine = reload(tmp_path, mid)
    checks = events(engine, "CHECK_ROLLED", REFLECTION)
    assert len(checks) == 2, [(e.event_type, e.actor_id, e.payload) for e in checks]
    assert [e.actor_id for e in checks] == [OWNER, ALLY]
    assert all(e.payload["success"] for e in checks)
    for aid in (OWNER, ALLY):
        me = engine.state.actors[aid]
        assert me.resources["resource:core.qi"] == purses[aid].resources["resource:core.qi"] - 5
        assert me.resources["resource:named.prepared_talismans"] == purses[aid].resources["resource:named.prepared_talismans"] - 1
        assert not me.reaction_available
    damage = events(engine, "DAMAGE_COMMITTED", cast.source_definition_id)
    assert damage and all(FOE in e.target_ids for e in damage)
    assert not any(OWNER in e.target_ids or ALLY in e.target_ids for e in damage)
    reflects = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.talisman_reflect"]
    assert len(reflects) == 2, [(p["context"], p.get("choice")) for p in prompts]
    assert ALLY in {o["id"] for o in reflects[0]["choice"]["options"]}


def test_redirect_cycle_ends_at_an_already_answered_recipient(tmp_path):
    # Tobin hands the Lash back to Mara: a creature that already answered this
    # activation is never asked again (visited/termination guard), and the
    # redirected effect resolves against her.
    owner = compile_character(sheet([REFLECTION, HEAL], cl=17, score=50), actor_id=OWNER, reaction_plan={"ask": True})
    ally = compile_character(sheet([REFLECTION], cl=17, score=50), actor_id=ALLY, reaction_plan={"ask": True})
    combat, table, mid = fixture(tmp_path, [REFLECTION, HEAL], owner_bundle=owner,
        bundle_transform=lambda bundles: _chain_bundles(bundles, ally),
        foe_sheet=sheet([L + "LIGHTNING_LASH"], cl=17, score=14),
        foe_position={"x": 4, "y": 7}, seed="H212-CYCLE", named=True)
    turn(table, mid, FOE)
    cast = candidate(combat, mid, "Lightning Lash: Jolt", target=OWNER)
    before = reload(tmp_path, mid).state.actors[OWNER]
    qi, talismans = before.resources["resource:core.qi"], before.resources["resource:named.prepared_talismans"]
    prompts = settle(table, mid, cast.candidate_id, picks={"reaction:typed." + REFLECTION: "first",
        "choice:needle.talisman_reflect": (ALLY, OWNER)})
    engine = reload(tmp_path, mid)
    checks = events(engine, "CHECK_ROLLED", REFLECTION)
    assert [e.actor_id for e in checks] == [OWNER, ALLY], [(e.actor_id, e.payload) for e in checks]
    me = engine.state.actors[OWNER]
    assert not me.reaction_available and me.resources["resource:core.qi"] == qi - 5
    assert me.resources["resource:named.prepared_talismans"] == talismans - 1
    damage = events(engine, "DAMAGE_COMMITTED", cast.source_definition_id)
    assert damage and all(OWNER in e.target_ids for e in damage)
    assert not any(ALLY in e.target_ids or FOE in e.target_ids for e in damage)
    reflects = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.talisman_reflect"]
    assert len(reflects) == 2, [(p["context"], p.get("choice")) for p in prompts]
