"""Persisted table coverage for paid consent and complete defeat chains.

Synthetic consumer rows count each generic notification independently. Damage
still goes through real table candidates, typed attacks and the shipped
Mountain-Rending after-hit plug-in; no runtime methods are patched.
"""
import copy

import pytest

from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ActionDefinition
from tests.h48_table_support import ESSENCE, FOE, OWNER, SECOND, candidate, fixture, assert_reload_verify_replay

RETAINER = "TAL_DAEMONIC_CULTIVATION_DEMON_COURT_RETAINER"
CTE = "tianxia.path.body_refining.feature.core_tempering_expression"
PAID_PASSIVES = [
    RETAINER,
    "foundation.divine_king_body_v0_2B.moon_disc_descent",
    "foundation.dragon_wind_vessel_v0_2E.momentum_drive",
    "foundation.weak_reed_tendons_v0_2B.reed_slip",
    "tianxia.path.body_refining.feature.blood_pump",
    "tianxia.subpath.body.bojutsu.feature.sweeping_strike",
    "tianxia.subpath.body.bone_monarch.feature.sovereign_reconstruction",
    "tianxia.subpath.body.bone_monarch.feature.unbroken_bones#marrow_memory",
    "tianxia.subpath.body.goruden.feature.immortal_gold",
    "tianxia.subpath.body.hundred_beast_scripture.feature.beast_king_s_technique",
    "tianxia.subpath.body.iron_shirt.feature.invincible_iron",
    "tianxia.subpath.body.oni_blood.feature.crimson_oni",
    "tianxia.subpath.body.still_water_draw_body.feature.one_breath_three_horizons",
    "tianxia.subpath.body.white_heron_crescent_body.feature.crescent_reaping_circle",
    "tianxia.subpath.qi.heaven_anvil_maul_cultivator.feature.hammer_the_core_out_of_rhythm",
    "tianxia.subpath.qi.saber_wind_cultivator.feature.crescent_wind",
    "tianxia.subpath.qi.star_piercing_greatbow_cultivator.feature.sky_nailing_arrow",
    "tianxia.talent.puppetry.heaven_s_spare_body",
    "tianxia.tradition.spirit.dreamweaver.feature.eternal_dream_refuge",
]


@pytest.mark.parametrize("mid", PAID_PASSIVES)
def test_other_paid_passives_keep_consent_separate_from_reaction(mid):
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet

    bundle = compile_character(sheet([mid], cl=20, primary="Stamina"), actor_id=OWNER, reaction_plan={"ask": True})
    rows = [r for r in bundle["typed_reactions"] if r["feature_id"] == mid]
    if mid == "foundation.weak_reed_tendons_v0_2B.reed_slip":
        # Actual movement and the optional paid destination/exemption choice
        # belong to one native plug-in, not a second generic own-action spend.
        assert not rows
        assert any(r.get("feature_id") == mid and r.get("block") == "reed_slip"
                   and r.get("trigger_owner") for r in bundle["typed_passives"])
        return
    if mid == "tianxia.subpath.body.hundred_beast_scripture.feature.beast_king_s_technique":
        # Its existing after-hit plug-in owns the optional choice and payment;
        # a second generic paid trigger would spend twice. The real current and
        # legacy table payment checks live in test_r24_plugin_activation.py.
        assert not rows
        assert [r for r in bundle["typed_passives"] if r.get("feature_id") == mid
                and r.get("block") == "path_rider" and r.get("role") == "king"]
        return
    if mid == "tianxia.tradition.spirit.dreamweaver.feature.eternal_dream_refuge":
        # Round 23's Dreamweaver plug-in owns this choice, replacing the old
        # generic reaction row. Keep a single implementation for the ability.
        assert not rows
        assert any(r.get("feature_id") == mid and r.get("block") == "spirit_tradition"
                   for r in bundle["typed_passives"])
        return
    if mid == "tianxia.subpath.body.bojutsu.feature.sweeping_strike":
        # Round 24's 71a31748 "Stop compiling a second generic reaction for Sweeping
        # Strike" removed this row deliberately: combat/ext/bojutsu.py already owns
        # the optional Staff-hit choice, its single Stamina payment, the save and the
        # chosen result, so the feature is marked already_applied in
        # rules/feature_blocks.d/subpaths.json. The generic paid-hit row was the one
        # charging twice (a USE paid 2 Stamina, and a DECLINE of the plug-in's own
        # choice still paid 1), so one implementation is the fix, not a regression.
        # Consent still belongs to the owner's choice: the plug-in row owns it
        # (choice_owner) instead of the generic row's ask flag, and the real
        # consent-and-payment checks -- asked on the player's and the AI's turn,
        # paid once on USE and not at all on DECLINE -- are the unchanged r13
        # cases test_r13_integration.py::test_paid_rider_table_choice_decline_and_reload
        # (rider=sweep).
        assert not rows
        assert any(r.get("feature_id") == mid and r.get("block") == "bojutsu"
                   and r.get("choice_owner") for r in bundle["typed_passives"])
        return
    assert rows
    assert all(r["free"] and r["optional"] and r["ask"] and r["costs"] for r in rows)
    assert mid in {r["id"] for r in bundle["reaction_plan"]["choices"]}


def test_mandatory_free_resource_generation_stays_automatic():
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet

    mid = "foundation.divine_king_body_v0_2B.generate_moon_sea_radiance"
    bundle = compile_character(sheet([mid], cl=20), actor_id=OWNER, reaction_plan={"ask": True})
    generators = [r for r in bundle["typed_reactions"] if r.get("free") and not r.get("costs")]
    assert generators
    assert all(not r.get("optional") and not r.get("ask") for r in generators)


def seal(bundles):
    for bundle in bundles:
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)


def add_action(bundle, label, effects, *, economy="NONE", area=None, cost=()):
    """A synthetic table action for these regressions.

    A NONE-economy action is not a primary turn intent by itself (combat/primary_intents.py), so a synthetic free
    activation declares ``free_primary``; otherwise the engine would never offer the row these tests drive.
    """
    source = "test:h48." + label
    free = str(economy) == "NONE"
    action = ActionDefinition(
        source_definition_id=source, display_name=label, owner_id=bundle["actor_id"],
        economy=economy, resolution_kind="TYPED", target_kind="CELL" if area else "HOSTILE_ENTITY",
        range_ft=30, costs=tuple(cost), parameters={"typed": {
            "effects": effects, "numbers": {"pb": 4, "cl": 17, "attack_bonus": 100, "save_dc": 50},
            "duration": {"kind": "minutes", "amount": 1}, "area": area, "range_ft": 30,
            "riders": [], "weapon": None}, "expected_damage": 1, **({"free_primary": True} if free else {})},
    ).model_dump(mode="json")
    bundle["action_catalog"].append(action)
    bundle["actor_template"]["action_ids"].append(source)
    return source


def resolve(send, cid, selection="USE", answers=()):
    answers, prompts = list(answers), []
    for _ in range(30):
        result = send(cid, answers)
        if result["status"] == "COMMITTED":
            return prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        choice = selection if RETAINER in prompt["context"]["reaction_source_id"] else "DECLINE"
        answer = {**prompt["context"], "selection": choice}
        if prompt.get("choice") and not (choice == "DECLINE" and prompt["choice"].get("allow_decline")):
            answer.update(selection="USE", option_ids=(prompt["choice"].get("preferred") or
                          [prompt["choice"]["options"][0]["id"]])[:1])
        answers.append(answer)
    raise AssertionError("Repeated prompt without commit")


@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_retainer_asks_before_spending_and_preserves_reaction(tmp_path, selection):
    def initial(bundles):
        for pool in bundles[0]["actor_template"]["resources"]:
            if pool["resource_id"] == ESSENCE:
                pool["initial"] = 8
        bundles[1]["actor_template"]["maximum_hp"] = 1
        seal(bundles)

    combat, table, mid, send, _ = fixture(tmp_path, [RETAINER, "TAL_DAEMONIC_CULTIVATION_DEMON_MARK"],
        seed="H48-CONSENT", extra_foe=True, bundle_transform=initial)
    cid = candidate(table, mid, "Demon Mark + Daemonic Augment: Bonus Damage", FOE)
    before = combat._load_session(mid).engine.state.actors[OWNER].resources[ESSENCE]
    preview = send(cid)
    # Preview pauses are transactional: no payment is persisted.
    assert preview["status"] == "REACTION_REQUIRED"
    assert combat._load_session(mid).engine.state.actors[OWNER].resources[ESSENCE] == before
    prompts = resolve(send, cid, selection)
    retainer = [p for p in prompts if RETAINER in p["context"]["reaction_source_id"]]
    assert len(retainer) == 1
    assert "Foe" in retainer[0]["trigger"], retainer[0]
    assert "Augment" in retainer[0]["trigger"], retainer[0]
    assert "Demon Court Retainer" in str(retainer[0])
    assert retainer[0]["cost"] == "2 Devoured Essence"
    assert retainer[0]["title"] == "Demon Court Retainer"
    engine = combat._load_session(mid).engine
    payments = [e for e in engine.events if e.event_type == "RESOURCE_SPENT" and e.source_definition_id == RETAINER]
    assert len(payments) == (selection == "USE")
    if payments:
        assert payments[0].payload["amount"] == 2
    assert engine.state.actors[OWNER].reaction_available
    assert_reload_verify_replay(combat, mid, tmp_path)


def consumers(bundle):
    # Repeatable probes: neither a once-limit nor a consumed watch can hide
    # duplicate own_kill/any_drop_to_zero announcements.
    template = next(r for r in bundle["typed_reactions"] if r["feature_id"] == RETAINER)
    pool = next(r["resource_id"] for r in bundle["actor_template"]["resources"]
                if r["resource_id"] in ("resource:core.qi", "resource:core.stamina"))
    for kind in ("own_kill", "any_drop_to_zero"):
        row = {**copy.deepcopy(template), "feature_id": "test:h48." + kind,
               "name": kind, "kind": kind, "ask": False, "optional": False,
               "costs": [], "effects": [{"type": "gain_resource", "resource_id": pool, "flat": 1}]}
        bundle["typed_reactions"].append(row)
    add_action(bundle, "Watch defeat", [{"type": "gain_resource", "resource_id": pool, "flat": 1,
        "deferred": True, "evidence": "When the target drops to 0 HP, gain 1 Qi."}])


def assert_consumers(combat, mid, count):
    engine = combat._load_session(mid).engine
    for kind in ("own_kill", "any_drop_to_zero"):
        events = [e for e in engine.events if e.event_type == "REACTION_RESOLVED" and
                  e.source_definition_id == "test:h48." + kind]
        assert len(events) == count, (kind, [(e.target_ids, e.payload) for e in events])
        assert len({e.target_ids for e in events}) == count
    watches = [e for e in engine.events if e.event_type == "MODIFIER_REMOVED" and
               e.source_definition_id == "test:h48.Watch defeat" and e.payload.get("reason") == "CONSUMED"]
    assert len(watches) == count
    for source in ("test:h48.own_kill", "test:h48.any_drop_to_zero", "test:h48.Watch defeat"):
        gains = [e for e in engine.events if e.event_type == "RESOURCE_GAINED" and e.source_definition_id == source]
        assert len(gains) == count, (source, gains)
        assert all(e.payload["gained"] == 1 for e in gains)
    assert not hasattr(engine, "_typed_defeat_chain")


@pytest.mark.parametrize("owner_auto", [False, True])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_retainer_on_ai_turn_asks_manual_owner_and_auto_uses_for_ai_owner(tmp_path, owner_auto, selection):
    def initial(bundles):
        # Isolate Retainer's economy: Devour Essence is a separate optional
        # ability whose AI use legitimately spends a Reaction on this kill.
        bundles[0]["typed_passives"] = [r for r in bundles[0]["typed_passives"] if r.get("block") != "devour_essence"]
        bundles[1]["actor_template"]["maximum_hp"] = 1
        for pool in bundles[0]["actor_template"]["resources"]:
            if pool["resource_id"] == ESSENCE:
                pool["initial"] = 8
        template = next(r for r in bundles[0]["typed_reactions"] if r["feature_id"] == RETAINER)
        bundles[0]["typed_reactions"] = [template]
        # A test-only Daemonic counter routes damage through a real generic
        # reaction while the enemy's table action is resolving.
        bundles[0]["typed_reactions"].append({**copy.deepcopy(template), "feature_id": "test:h48.Daemonic counter",
            "name": "Daemonic counter", "kind": "damaged", "ask": False, "optional": False,
            "costs": [], "effects": [{"type": "damage", "flat": 1, "damage_types": ["force"], "applies_to": "target"}]})
        add_action(bundles[1], "Enemy hit", [{"type": "damage", "flat": 1, "damage_types": ["force"]}])
        seal(bundles)

    combat, table, mid, _, commit = fixture(tmp_path, [RETAINER], seed="H48-AI-CONSENT",
        extra_foe=True, bundle_transform=initial)
    for _ in range(10):
        if table.state(mid)["menu"]["actor_id"] == FOE:
            break
        commit(table.state(mid)["menu"]["end_turn"])
    engine = combat._load_session(mid).engine
    selected = next(c for c in engine.legal_candidates() if c.display_name == "Enemy hit" and OWNER in c.target_ids)
    from combat.gate4_adapters import ManualControllerAdapter

    original = combat.controller

    class SelectedController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (selected.candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(original, name)

    combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    if owner_auto:
        combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    combat.controller = SelectedController()
    try:
        prompts = resolve(lambda _cid, answers: table.auto_step(mid, 0, list(answers)), selected.candidate_id, selection)
    finally:
        combat.controller = original
    retainer = [p for p in prompts if RETAINER in p["context"]["reaction_source_id"]]
    assert len(retainer) == (not owner_auto)
    if retainer:
        assert "Daemonic counter" in retainer[0]["trigger"]
        assert "Foe" in retainer[0]["trigger"]
    engine = combat._load_session(mid).engine
    assert len([e for e in engine.events if e.event_type == "RESOURCE_SPENT" and e.source_definition_id == RETAINER]) == (owner_auto or selection == "USE")
    assert engine.state.actors[OWNER].reaction_available
    assert_reload_verify_replay(combat, mid, tmp_path)


@pytest.mark.parametrize("kind", ["damage", "rider", "reaction", "area"])
def test_all_defeat_consumers_once_per_creature_across_chain(tmp_path, kind):
    def initial(bundles):
        consumers(bundles[0])
        # Leave capacity for the consumer counters.
        for resource in bundles[0]["actor_template"]["resources"]:
            resource["initial"] = min(10, resource["maximum"])
        bundles[1]["actor_template"]["maximum_hp"] = 3 if kind == "rider" else 1
        bundles[2]["actor_template"]["maximum_hp"] = 1
        if kind == "rider":
            add_action(bundles[0], "Prime pulse", [{"type": "rider", "evidence": "Spend Stamina to prime Mountain-Rending Pulse."}],
                       cost=(("resource:core.stamina", 1),))
            add_action(bundles[0], "Pulse attack", [{"type": "attack", "attack_kind": "unarmed", "on_hit": [
                {"type": "damage", "dice": {"count": 1, "sides": 1}, "damage_types": ["bludgeoning"]}]}])
        elif kind == "reaction":
            template = next(r for r in bundles[0]["typed_reactions"] if r["feature_id"] == RETAINER)
            bundles[0]["typed_reactions"].append({**copy.deepcopy(template), "feature_id": "test:h48.Counter",
                "name": "Counter", "kind": "damaged", "ask": False, "optional": False, "costs": [],
                "effects": [{"type": "damage", "flat": 1, "damage_types": ["force"], "applies_to": "target"}]})
            add_action(bundles[1], "Enemy hit", [{"type": "damage", "flat": 1, "damage_types": ["force"]}])
        else:
            add_action(bundles[0], "Lethal damage", [{"type": "damage", "flat": 1, "damage_types": ["force"]}],
                       area={"shape": "sphere", "size_ft": 5} if kind == "area" else None)
        seal(bundles)

    combat, table, mid, send, commit = fixture(tmp_path, [RETAINER], seed="H48-CHAIN-" + kind + "-2",
        extra_foe=True, bundle_transform=initial, primary="Stamina" if kind == "rider" else "Qi",
        path_features=[CTE] if kind == "rider" else [])
    commit(candidate(table, mid, "Watch defeat", FOE))
    if kind == "area":
        commit(candidate(table, mid, "Watch defeat", SECOND))
    if kind == "rider":
        commit(candidate(table, mid, "Core Tempering Expression: Mountain-Rending Pulse"))
        commit(candidate(table, mid, "Prime pulse", FOE))
        resolve(send, candidate(table, mid, "Pulse attack", FOE))
        events = combat._load_session(mid).engine.events
        damage = [e for e in events if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids]
        assert len(damage) == 2  # Base hit survives; actual after_hit plug-in kills.
    elif kind == "reaction":
        for _ in range(10):
            if table.state(mid)["menu"]["actor_id"] == FOE:
                break
            commit(table.state(mid)["menu"]["end_turn"])
        resolve(send, candidate(table, mid, "Enemy hit", OWNER))
    elif kind == "area":
        # Placement is lazy (combat/placement_menu.py): the action opens a square picker, and the square the test
        # wants is chosen from that prompt rather than being a menu option of its own.
        group = next(g for g in table.state(mid)["menu"]["actions"] if g["label"] == "Lethal damage")
        picker = group["options"][0]["candidate_id"]
        result = send(picker)
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        square = next(o for o in prompt["choice"]["options"] if o.get("cell") == {"x": 4, "y": 6, "z": 0})
        resolve(send, picker, answers=[{**prompt["context"], "selection": "USE", "option_ids": [square["id"]]}])
    else:
        resolve(send, candidate(table, mid, "Lethal damage", FOE))
    assert_consumers(combat, mid, 2 if kind == "area" else 1)
    assert_reload_verify_replay(combat, mid, tmp_path)
