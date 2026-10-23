"""Round17 lane5 regressions through the table, persistence, and replay.

Fixture-only free seed actions establish prerequisites through ordinary commits;
no runtime combat methods are replaced. Court's boundary fixture supplies a
Wax save trigger to isolate its owner choice from concentration setup.
"""
import copy
import json
import zipfile

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

PLAYER = "actor:factory.r5i-player"
OTHER = "actor:factory.r5i-other"
COURT = "TAL_WAX_COURT_OF_TEN_THOUSAND_CANDLES"
HUNDRED = "TAL_WAX_HUNDRED_SEAL_CONFLAGRATION"


def seed(bundle, name, effects, *, target="HOSTILE_ENTITY"):
    action = copy.deepcopy(next(a for a in bundle["action_catalog"] if a["resolution_kind"] == "TYPED"))
    action.update(source_definition_id=f"test:{name}", display_name=name, economy="NONE",
                  concentration=False, target_kind=target, range_ft=60, costs=[])
    action["parameters"] = {"typed": {"source": f"test:{name}", "effects": effects,
                                      "numbers": {"pb": 4, "save_dc": 50}, "duration": {"kind": "instant"}}}
    bundle["action_catalog"].append(action)
    bundle["actor_template"]["action_ids"].append(action["source_definition_id"])


def mark(name):
    return {"type": "mark", "mark": name, "applies_to": "target", "duration": {"kind": "until_removed"}}


def fixture(tmp_path, talents, *, other_talents=(), allied=False, configure=None, positions=None):
    docs = [sheet(talents, cl=15, dc=50), sheet(other_talents, cl=15, dc=50)]
    for doc, name in zip(docs, ("Wax Keeper", "Sound Guest")):
        doc["identity"]["display_name"] = name
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 900
        doc["ability_scores_and_statistics"]["primary_resource"]["maximum"] = 200
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={"ask": True})
               for doc, aid in zip(docs, (PLAYER, OTHER))]
    if configure:
        configure(*bundles)
    for bundle in bundles:
        bundle["bundle_sha256"] = canonical_sha256({k: v for k, v in bundle.items() if k != "bundle_sha256"})
    for pid, doc in zip(("r5i-player", "r5i-other"), docs):
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [PLAYER, OTHER, AN], {PLAYER: "team:a", OTHER: "team:a" if allied else "team:b", AN: "team:b"},
        positions or {PLAYER: {"x": 3, "y": 6}, OTHER: {"x": 4, "y": 6}, AN: {"x": 4, "y": 7}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [PLAYER, OTHER], [AN],
        control_modes={aid: "MANUAL" for aid in (PLAYER, OTHER, AN)}, match_seed="R5I-TABLE",
        display_name="R5 integration", maximum_rounds=15)["match_id"]
    return combat, table, mid


def act(table, mid, cid, answers=()):
    menu = table.state(mid)["menu"]
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))


def turn(table, mid, aid):
    for _ in range(4):
        menu = table.state(mid)["menu"]
        if menu["actor_id"] == aid:
            return
        assert act(table, mid, menu["end_turn"])["status"] == "COMMITTED"
    raise AssertionError("fixture did not reach requested turn")


def candidate(combat, mid, name, target=None):
    return next(c for c in combat._load_session(mid).engine.legal_candidates()
                if c.display_name == name and (target is None or target in c.target_ids)).candidate_id


def answer(result, selection="USE", options=()):
    return {**result["reaction"]["context"], "selection": selection, "option_ids": list(options)}


def check_reload(combat, mid, tmp_path):
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.model_dump(mode="json") == before
    assert loaded.mechanical.replay()["status"] == "PASS"
    return loaded.engine


def pin_ai(combat, mid, aid, cid):
    combat.set_controller_mode(mid, actor_id=aid, controller_mode="LOCAL_AUTO")
    real = combat.controller

    class PinnedController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = PinnedController()


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_court_boundary_owner_can_decline_on_manual_and_ai_turns(tmp_path, auto_turn, selection):
    def configure(bundle, other):
        court = next(a for a in bundle["action_catalog"] if a["parameters"].get("typed", {}).get("source") == COURT)
        # Add only the trigger used to test a turn-start Wax save in an existing
        # court. Neither its optional choice nor its execution code is replaced.
        court["parameters"]["typed"]["zone_spec"]["triggers"] = [{
            "id": COURT + ":fixture", "name": "Wax Court boundary save", "on": ["start"], "who": "hostile",
            "effects": [{"type": "save", "ability": "dex", "on_fail": [], "on_success": []}]}]
        court["parameters"]["typed"]["zone_spec"].update(shape="square", size_ft=5)

    combat, table, mid = fixture(tmp_path, [COURT], configure=configure)
    turn(table, mid, PLAYER)
    engine = combat._load_session(mid).engine
    order = list(engine.state.initiative_order)
    index = order.index(PLAYER)
    advancing, victim = order[(index + 1) % 3], order[(index + 2) % 3]
    position = engine.state.actors[victim].position
    cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
               if c.display_name.startswith("Court of Ten Thousand Candles") and c.destination == position)
    assert act(table, mid, cid)["status"] == "COMMITTED"
    assert act(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    assert table.state(mid)["menu"]["actor_id"] == advancing
    cid = table.state(mid)["menu"]["end_turn"]
    if auto_turn:
        pin_ai(combat, mid, advancing, cid)
    send = lambda answers=(): table.auto_step(mid, 0, list(answers)) if auto_turn else act(table, mid, cid, answers)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["reaction"] == "Court of Ten Thousand Candles"
    assert "failed a save against Court of Ten Thousand Candles" in prompt["moment"] and prompt["by"]
    assert prompt["choice"]["allow_decline"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send([answer(result, selection, ["seal"] if selection == "USE" else [])])["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    seals = [c for a in engine.state.actors.values() for c in a.conditions.values()
             if c.condition_id == f"condition:typed.mark.wax_seal.{PLAYER}"]
    assert bool(seals) == (selection == "USE")
    assert engine.state.actors[PLAYER].turn_flags["wax_court_round_used"] == engine.state.round_number


@pytest.mark.parametrize("targets", [[], [OTHER]])
def test_hundred_selects_seals_and_targets_and_preserves_other_owned_instances(tmp_path, targets):
    def configure(bundle, other):
        seed(bundle, "Seed Wax", [mark("Wax Seal")])
        seed(other, "Other Wax", [mark("Wax Seal")])
    combat, table, mid = fixture(tmp_path, [HUNDRED], other_talents=[HUNDRED], configure=configure)
    turn(table, mid, OTHER)
    assert act(table, mid, candidate(combat, mid, "Other Wax", PLAYER))["status"] == "COMMITTED"
    turn(table, mid, PLAYER)
    for target in (OTHER, AN):
        assert act(table, mid, candidate(combat, mid, "Seed Wax", target))["status"] == "COMMITTED"
    cid = candidate(combat, mid, "Hundred-Seal Conflagration", OTHER)
    first = act(table, mid, cid)
    assert first["status"] == "REACTION_REQUIRED"
    second = act(table, mid, cid, [answer(first, options=[OTHER])])
    assert second["status"] == "REACTION_REQUIRED"
    assert second["reaction"]["choice"]["maximum"] == 3
    assert second["reaction"]["choice"]["allow_decline"]
    hp = combat._load_session(mid).engine.state.actors[OTHER].current_hp
    assert act(table, mid, cid, [answer(first, options=[OTHER]), answer(second, options=targets)])["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    assert (engine.state.actors[OTHER].current_hp < hp) == bool(targets)
    assert not any(c.condition_id == f"condition:typed.mark.wax_seal.{PLAYER}" for c in engine.state.actors[OTHER].conditions.values())
    assert any(c.condition_id == f"condition:typed.mark.wax_seal.{PLAYER}" for c in engine.state.actors[AN].conditions.values())
    assert any(c.condition_id == f"condition:typed.mark.wax_seal.{OTHER}" for c in engine.state.actors[PLAYER].conditions.values())


def test_consuming_seal_removes_only_its_linked_speed_modifier(tmp_path):
    combat, table, mid = fixture(tmp_path, ["TAL_WAX_PRESS_SEAL"], other_talents=["TAL_WAX_PRESS_SEAL"], allied=True)
    turn(table, mid, OTHER)
    assert act(table, mid, candidate(combat, mid, "Press Seal", AN))["status"] == "COMMITTED"
    turn(table, mid, PLAYER)
    assert act(table, mid, candidate(combat, mid, "Press Seal", AN))["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    modifiers = [m for m in engine.state.actors[AN].modifiers.values() if m.target_field == "speed_ft"]
    assert {m.source_actor_id for m in modifiers} == {PLAYER, OTHER}
    retained = [m.model_dump(mode="json") for m in modifiers if m.source_actor_id == OTHER]
    cid = candidate(combat, mid, "Kindle Wax: Release Seal", AN)
    result = act(table, mid, cid)
    assert result["status"] == "REACTION_REQUIRED"
    committed = act(table, mid, cid, [answer(result, options=[f"seal:{AN}"])])
    if committed["status"] == "REACTION_REQUIRED":
        assert committed["reaction"]["context"]["reaction_source_id"] == "reaction:core.stamina_guard"
        committed = act(table, mid, cid, [answer(result, options=[f"seal:{AN}"]), answer(committed, "DECLINE")])
    assert committed["status"] == "COMMITTED", committed.get("reaction")
    engine = check_reload(combat, mid, tmp_path)
    assert [m.model_dump(mode="json") for m in engine.state.actors[AN].modifiers.values()
            if m.target_field == "speed_ft"] == retained


def test_candleflare_measures_range_to_wax_not_the_affected_creature(tmp_path):
    def configure(bundle, other):
        seed(bundle, "Seed Wax", [mark("Wax Seal")])
    combat, table, mid = fixture(tmp_path, ["TAL_WAX_PRESS_SEAL"], configure=configure,
        positions={PLAYER: {"x": 3, "y": 1}, OTHER: {"x": 15, "y": 1}, AN: {"x": 16, "y": 1}})
    turn(table, mid, PLAYER)
    assert act(table, mid, candidate(combat, mid, "Seed Wax", OTHER))["status"] == "COMMITTED"
    hp = combat._load_session(mid).engine.state.actors[AN].current_hp
    cid = candidate(combat, mid, "Kindle Wax: Candleflare", AN)
    result = act(table, mid, cid)
    assert result["status"] == "REACTION_REQUIRED"
    committed = act(table, mid, cid, [answer(result, options=[f"seal:{OTHER}"])])
    if committed["status"] == "REACTION_REQUIRED":
        assert committed["reaction"]["context"]["reaction_source_id"] == "reaction:core.stamina_guard"
        committed = act(table, mid, cid, [answer(result, options=[f"seal:{OTHER}"]), answer(committed, "DECLINE")])
    assert committed["status"] == "COMMITTED"
    assert check_reload(combat, mid, tmp_path).state.actors[AN].current_hp < hp


def test_ai_owned_willing_decision_is_automatic(tmp_path):
    combat, table, mid = fixture(tmp_path, ["TAL_WAX_PRESS_SEAL"], allied=True)
    turn(table, mid, PLAYER)
    cid = candidate(combat, mid, "Seal a Willing Creature (Press Seal)", OTHER)
    combat.set_controller_mode(mid, actor_id=OTHER, controller_mode="LOCAL_AUTO")
    pin_ai(combat, mid, PLAYER, cid)
    assert table.auto_step(mid, 0)["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    assert any(c.condition_id == f"condition:typed.mark.wax_seal.{PLAYER}" for c in engine.state.actors[OTHER].conditions.values())


def test_sonic_cage_repeat_save_hooks_receive_the_turn_transaction(tmp_path, monkeypatch):
    from combat import ext
    feature = "TAL_SOUND_SONIC_CAGE"
    def configure(bundle, other):
        seed(bundle, "Seed Resonance", [mark("Resonance")])
    combat, table, mid = fixture(tmp_path, [feature], configure=configure)
    turn(table, mid, PLAYER)
    assert act(table, mid, candidate(combat, mid, "Seed Resonance", OTHER))["status"] == "COMMITTED"
    assert act(table, mid, candidate(combat, mid, "Sonic Cage", OTHER))["status"] == "COMMITTED"
    turn(table, mid, OTHER)
    observed = []
    ext.effects()
    def observe(ctx, subject, ability, named):
        if ctx.typed.get("source") == feature:
            observed.append(ctx.intent)
    monkeypatch.setitem(ext._HOOKS, "save", [*ext._HOOKS["save"], observe])
    cid = table.state(mid)["menu"]["end_turn"]
    assert act(table, mid, cid)["status"] == "COMMITTED"
    assert observed and all(intent is not None and intent.candidate_id == cid and intent.actor_id == OTHER for intent in observed)
    check_reload(combat, mid, tmp_path)


@pytest.mark.parametrize("auto_turn", [False, True])
def test_harmonic_optional_recipient_decline_survives_ai_turn_commit_reload(tmp_path, auto_turn):
    feature = "TAL_SOUND_HARMONIC_HEALING_TONE"
    def configure(bundle, other):
        seed(other, "Seed Deafened", [{"type": "condition", "condition": "deafened", "applies_to": "target",
                                     "duration": {"kind": "until_removed"}}], target="ALLY_OR_SELF")
    combat, table, mid = fixture(tmp_path, [feature], other_talents=[feature], allied=True, configure=configure)
    turn(table, mid, OTHER)
    assert act(table, mid, candidate(combat, mid, "Seed Deafened", PLAYER))["status"] == "COMMITTED"
    cid = candidate(combat, mid, "Harmonic Healing Tone", PLAYER)
    if auto_turn:
        pin_ai(combat, mid, OTHER, cid)
    send = lambda answers=(): table.auto_step(mid, 0, list(answers)) if auto_turn else act(table, mid, cid, answers)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    assert result["reaction"]["context"]["reactor_id"] == PLAYER
    consent = answer(result, options=["accept"])
    result = send([consent])
    assert result["status"] == "REACTION_REQUIRED"
    assert "Harmonic Healing Tone" in result["reaction"]["moment"] and "Wax Keeper" in result["reaction"]["moment"]
    assert result["reaction"]["choice"]["allow_decline"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send([consent, answer(result, "DECLINE")])["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    assert any(c.condition_id == "condition:typed.deafened" for c in engine.state.actors[PLAYER].conditions.values())


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("accept", [False, True])
def test_harmonic_willing_foe_consent_on_manual_and_ai_turns(tmp_path, auto_turn, accept):
    feature = "TAL_SOUND_HARMONIC_HEALING_TONE"
    def configure(bundle, other):
        seed(bundle, "Seed Injury", [{"type": "damage", "applies_to": "target", "flat": 80,
                                      "formula": "none", "damage_types": ["force"]}])
    combat, table, mid = fixture(tmp_path, [feature], configure=configure)
    turn(table, mid, PLAYER)
    assert act(table, mid, candidate(combat, mid, "Seed Injury", OTHER))["status"] == "COMMITTED"
    cid = candidate(combat, mid, "Harmonic Healing Tone (willing creature)", OTHER)
    if auto_turn:
        pin_ai(combat, mid, PLAYER, cid)
    send = lambda answers=(): table.auto_step(mid, 0, list(answers)) if auto_turn else act(table, mid, cid, answers)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    assert result["reaction"]["context"]["reactor_id"] == OTHER
    assert "Harmonic Healing Tone" in result["reaction"]["moment"]
    assert "Wax Keeper" in result["reaction"]["moment"] and "Sound Guest" in result["reaction"]["moment"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    response = answer(result, options=["accept"] if accept else ["refuse"])
    assert send([response])["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    hp_before = before["actors"][OTHER]["current_hp"]
    if accept:
        assert engine.state.actors[OTHER].current_hp > hp_before
    else:
        assert engine.state.actors[OTHER].current_hp == hp_before
    assert engine.state.actors[PLAYER].current_hp == before["actors"][PLAYER]["current_hp"]
    assert engine.state.actors[AN].current_hp == before["actors"][AN]["current_hp"]
    assert engine.state.actors[OTHER].reaction_available == before["actors"][OTHER]["reaction_available"]
    pool = "resource:core.qi"
    assert engine.state.actors[PLAYER].resources[pool] == before["actors"][PLAYER]["resources"][pool] - 3


def test_harmonic_ai_foe_refuses_without_a_player_prompt(tmp_path):
    feature = "TAL_SOUND_HARMONIC_HEALING_TONE"
    def configure(bundle, other):
        seed(bundle, "Seed Injury", [{"type": "damage", "applies_to": "target", "flat": 80,
                                      "formula": "none", "damage_types": ["force"]}])
    combat, table, mid = fixture(tmp_path, [feature], configure=configure)
    turn(table, mid, PLAYER)
    assert act(table, mid, candidate(combat, mid, "Seed Injury", OTHER))["status"] == "COMMITTED"
    combat.set_controller_mode(mid, actor_id=OTHER, controller_mode="LOCAL_AUTO")
    before = combat._load_session(mid).engine.state.actors[OTHER].current_hp
    assert act(table, mid, candidate(combat, mid, "Harmonic Healing Tone (willing creature)", OTHER))["status"] == "COMMITTED"
    assert check_reload(combat, mid, tmp_path).state.actors[OTHER].current_hp == before


@pytest.mark.parametrize("distance,offered", [(30, True), (35, False)])
def test_harmonic_willing_foe_keeps_printed_range(tmp_path, distance, offered):
    combat, table, mid = fixture(tmp_path, ["TAL_SOUND_HARMONIC_HEALING_TONE"],
                               positions={PLAYER: {"x": 2, "y": 1}, OTHER: {"x": 2 + distance // 5, "y": 1},
                                          AN: {"x": 4, "y": 7}})
    turn(table, mid, PLAYER)
    targets = [c.target_ids for c in combat._load_session(mid).engine.legal_candidates()
               if c.display_name == "Harmonic Healing Tone (willing creature)"]
    assert any(OTHER in ids for ids in targets) == offered


def test_willing_non_ally_variant_is_inert_without_the_typed_opt_in():
    from combat.ext.willing_targets import willing_non_allies
    from combat.gate2_runtime_models import ActionDefinition

    bundle = compile_character(sheet(["TAL_SOUND_HARMONIC_HEALING_TONE"], cl=15), actor_id=PLAYER)
    original = next(a for a in bundle["action_catalog"] if a["display_name"] == "Harmonic Healing Tone")
    original["parameters"]["typed"]["effects"][0].pop("allow_hostile_target")
    assert willing_non_allies({"actions": [ActionDefinition.model_validate(original)]}) is None
    assert willing_non_allies({"actions": []}) is None


def test_kindle_selects_exact_owned_wax_and_wick_expires_on_owner_edges(tmp_path):
    def configure(bundle, other):
        seed(bundle, "Seed Wax", [mark("Wax Seal")])
    combat, table, mid = fixture(tmp_path, ["TAL_WAX_SMOKE_WICK"], configure=configure)
    turn(table, mid, PLAYER)
    for target in (OTHER, AN):
        assert act(table, mid, candidate(combat, mid, "Seed Wax", target))["status"] == "COMMITTED"
    cid = candidate(combat, mid, "Kindle Wax: Smoke Puff", OTHER)
    result = act(table, mid, cid)
    assert result["status"] == "REACTION_REQUIRED"
    assert result["reaction"]["reaction"] == "Kindle Wax"
    assert act(table, mid, cid, [answer(result, options=[f"seal:{AN}"])])["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    own_seal = f"condition:typed.mark.wax_seal.{PLAYER}"
    assert any(c.condition_id == own_seal for c in engine.state.actors[OTHER].conditions.values())
    assert not any(c.condition_id == own_seal for c in engine.state.actors[AN].conditions.values())
    smoke = lambda e: sorted(z.trigger_profile.get("obscured") for z in e.state.zones.values() if z.active and z.trigger_profile.get("wax_smoke_edge"))
    assert smoke(engine) == ["heavy", "light"]
    assert all(z.center == engine.state.actors[AN].position for z in engine.state.zones.values()
               if z.active and z.trigger_profile.get("wax_smoke_edge"))
    assert act(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    assert smoke(check_reload(combat, mid, tmp_path)) == ["heavy", "light"]
    turn(table, mid, PLAYER)
    assert smoke(check_reload(combat, mid, tmp_path)) == ["light"]
    assert act(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    assert smoke(check_reload(combat, mid, tmp_path)) == []


@pytest.mark.parametrize("auto_turn", [False, True])
def test_press_seal_willing_recipient_can_refuse_on_manual_and_ai_turns(tmp_path, auto_turn):
    combat, table, mid = fixture(tmp_path, ["TAL_WAX_PRESS_SEAL"], allied=True)
    turn(table, mid, PLAYER)
    cid = candidate(combat, mid, "Seal a Willing Creature (Press Seal)", OTHER)
    if auto_turn:
        pin_ai(combat, mid, PLAYER, cid)
    send = lambda answers=(): table.auto_step(mid, 0, list(answers)) if auto_turn else act(table, mid, cid, answers)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    assert result["reaction"]["context"]["reactor_id"] == OTHER
    assert "Press Seal" in result["reaction"]["moment"] and "Sound Guest" in result["reaction"]["moment"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send([answer(result, options=["refuse"])])["status"] == "COMMITTED"
    engine = check_reload(combat, mid, tmp_path)
    assert not any(c.condition_id == f"condition:typed.mark.wax_seal.{PLAYER}" for c in engine.state.actors[OTHER].conditions.values())
