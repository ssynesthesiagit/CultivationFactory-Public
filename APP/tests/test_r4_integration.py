"""Round 17 rider integration through table preview, commit and reload."""
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

BREATH = "TAL_SNIPER_BREATH_HELD_SHOT"
CANON = "TAL_METAL_WHITE_TIGER_SEVEN_SLAUGHTER_CANON"
MOUNTAIN = "TAL_METAL_MOUNTAIN_ORE_DICTATE"
BINDING = "TAL_THREAD_BINDING_SLEEVE_METHOD"
P, F, S = [FACTORY_ACTOR_PREFIX + "r4-" + name for name in ("player", "foe", "second")]


def fixture(tmp_path, mids, second=(), *, bow=False, miss=False, seed="R4-INTEGRATION", foe_mids=(), foe_score=14, foe_ac=None, configure=None):
    documents = [sheet(mids, cl=20, dc=50), sheet(foe_mids, cl=20, score=foe_score), sheet(second, cl=20, dc=50)]
    if foe_ac is not None:
        documents[1]["ability_scores_and_statistics"]["armor_class"]["base_value"] = foe_ac
    ids = [P, F, S] if second else [P, F]
    for document in documents:
        document["equipment"] = [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.jian", "quantity": 1}]}}]
    if bow:
        for document in documents:
            document["equipment"] = [{"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.gong_jian", "quantity": 1}]}}]
        for document in (documents[0], documents[2]):
            document["ability_scores_and_statistics"]["abilities"] = [
                {"ability": a, "score": 100, "modifier": 45} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")]
    if miss:
        documents[1]["ability_scores_and_statistics"]["armor_class"]["base_value"] = 1000
    if BINDING in mids:
        documents[1]["ability_scores_and_statistics"]["abilities"] = [
            {"ability": a, "score": 500, "modifier": 245} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")]
    bundles = []
    for aid, document in zip(ids, documents):
        document["identity"]["display_name"] = {P: "Rider Player", F: "Rider Foe", S: "Second Binder"}[aid]
        document["ability_scores_and_statistics"]["hit_points"]["maximum"] = 2000
        document["ability_scores_and_statistics"]["technique_attack_bonus"] = 100
        folder = tmp_path / "portable_characters" / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
        bundles.append(compile_character(document, actor_id=aid, reaction_plan={"ask": True}))
    if configure is not None:
        configure(bundles)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        bundles, ids, {P: "team:a", F: "team:b", S: "team:a"},
        {P: {"x": 3, "y": 6}, F: {"x": 4 if second else 6, "y": 6}, S: {"x": 4, "y": 7}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [i for i in ids if i != F], [F],
        control_modes={i: "MANUAL" for i in ids}, match_seed=seed,
        display_name="R4 integration", maximum_rounds=10)["match_id"]
    return combat, table, mid


def send(table, mid, cid, answers=()):
    menu = table.state(mid)["menu"]
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))


def auto_candidate(combat, mid, actor, cid):
    real = combat.controller

    class FixedController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(real, name)

    combat.controller = FixedController()
    combat.set_controller_mode(mid, actor_id=actor, controller_mode="LOCAL_AUTO")


def reach(table, mid, actor):
    for _ in range(8):
        menu = table.state(mid)["menu"]
        if menu["actor_id"] == actor:
            return
        assert send(table, mid, menu["end_turn"])["status"] == "COMMITTED"
    raise AssertionError("actor turn not reached")


def candidate(table, mid, name, target=None):
    options = [(g["label"], o) for g in table.state(mid)["menu"]["actions"] for o in g["options"]]
    found = [o["candidate_id"] for label, o in options
             if name in o.get("label", label) and not o.get("label", label).startswith("Choose ")
             and (target is None or target in o.get("target_ids", []))]
    assert found, [(label, o.get("label"), o.get("target_ids")) for label, o in options]
    return found[0]


@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
@pytest.mark.parametrize("ai_owner", [False, True])
def test_breath_refund_optional_preview_reload(tmp_path, selection, ai_owner):
    combat, table, mid = fixture(tmp_path, [BREATH], bow=True, miss=True)
    reach(table, mid, P)
    cid = candidate(table, mid, "Breath-Held Shot (Martial Focus)", F)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    if ai_owner:
        auto_candidate(combat, mid, P, cid)
        result = table.auto_step(mid, 0)
        assert result["status"] == "COMMITTED"
        used = True
    else:
        result = send(table, mid, cid)
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        assert prompt["choice"]["allow_decline"] and len(prompt["choice"]["options"]) == 1
        for text in ("Breath-Held Shot", "Snipe Shot", "Rider Foe"):
            assert text in prompt["moment"]
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        answer = {**prompt["context"], "selection": selection, "option_ids": [prompt["choice"]["options"][0]["id"]] if selection == "USE" else []}
        assert send(table, mid, cid, [answer])["status"] == "COMMITTED"
        used = selection == "USE"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[P]
    assert actor.resources["resource:core.martial_focus"] == int(used)
    assert any(c.condition_id == "condition:typed.still_aim" for c in actor.conditions.values()) == used
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("effect", ["Buried iron edges", "Pull toward the center"])
def test_mountain_repeat_asks_owner_on_other_actors_end_turn(tmp_path, auto_turn, effect):
    combat, table, mid = fixture(tmp_path, [MOUNTAIN])
    reach(table, mid, P)
    cid = candidate(table, mid, "Mountain-Ore Dictate at 6,6")
    assert send(table, mid, cid)["status"] == "COMMITTED"
    assert send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    menu = table.state(mid)["menu"]
    assert menu["actor_id"] == F
    cid = menu["end_turn"]
    if auto_turn:
        auto_candidate(combat, mid, F, cid)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    call = lambda answers=(): table.auto_step(mid, 0, list(answers)) if auto_turn else send(table, mid, cid, answers)
    result = call()
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == P
    assert prompt["context"]["reaction_source_id"] == "choice:needle.mountain_ore_repeat"
    for text in ("Mountain-Ore Dictate", "turn starts", "Rider Foe"):
        assert text in prompt["moment"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert call()["reaction"] == prompt
    position = before["actors"][F]["position"]
    hp = before["actors"][F]["current_hp"]
    answer = {**prompt["context"], "selection": "USE", "option_ids": [effect]}
    assert call([answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    if effect == "Pull toward the center":
        assert loaded.engine.state.actors[F].position.model_dump(mode="json") == position
    else:
        assert loaded.engine.state.actors[F].current_hp == hp
        assert any(e.event_type == "GM_RIDER" and "deferred damage checkpoint" in e.payload.get("rider", "") for e in loaded.engine.events)
    assert not any(c.condition_id == "condition:typed.mountain_ore_repeat" for c in loaded.engine.state.actors[P].conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


def configured_binding(combat, table, mid, option, target):
    """Use the approved persistent modifier controls, then the base attack."""
    engine = combat._load_session(mid).engine
    parent = next(a.source_definition_id for a in engine.action_catalog.values()
                  if a.display_name == "Binding Knot" and a.owner_id == engine.state.current_actor_id)
    for field, value in (("on", "toggle"), ("option", option), ("payment", "0")):
        engine = combat._load_session(mid).engine
        source = next(a.source_definition_id for a in engine.action_catalog.values()
                      if (a.parameters.get("attack_modifier_setting") or {}) == {
                          "family": parent, "modifier": BINDING, "name": "Binding Sleeve Method",
                          "field": field, "value": value})
        cid = next(c.candidate_id for c in engine.legal_candidates() if c.source_definition_id == source)
        assert send(table, mid, cid)["status"] == "COMMITTED"
    return next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
                if c.source_definition_id == parent and target in c.target_ids)


def test_bound_hand_does_not_penalize_unrelated_attacks_after_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, [BINDING, "tianxia.talent.thread.binding_knot"], second=["TAL_METAL_NEEDLE_FLICK"])
    reach(table, mid, P)
    cid = configured_binding(combat, table, mid, "0", F)
    assert send(table, mid, cid)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    from combat.typed_executor import condition_rules
    target = loaded.engine.state.actors[F]
    assert any(c.condition_id == "condition:typed.bound_limb" for c in target.conditions.values())
    assert not any(row.get("attacks_have") == "DISADVANTAGE" for row in condition_rules(target))
    assert any(e.event_type == "GM_RIDER" and "bound hand" in e.payload.get("rider", "") for e in loaded.engine.events)
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_binding_escape_preserves_other_binder_commit_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, [BINDING, "tianxia.talent.thread.binding_knot"],
                                second=[BINDING, "tianxia.talent.thread.binding_knot"])
    for binder in (P, S):
        reach(table, mid, binder)
        cid = configured_binding(combat, table, mid, "1", F)
        assert send(table, mid, cid)["status"] == "COMMITTED"
        assert send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    reach(table, mid, F)
    states = [c for c in combat._load_session(mid).engine.state.actors[F].conditions.values() if c.condition_id == "condition:typed.bound_limb"]
    assert {c.source_actor_id for c in states} == {P, S}
    cid = candidate(table, mid, "Escape the binding")
    result = send(table, mid, cid)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    chosen = next(c.instance_id for c in states if c.source_actor_id == P)
    answer = {**prompt["context"], "selection": "USE", "option_ids": [chosen]}
    assert send(table, mid, cid, [answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    remaining = [c for c in loaded.engine.state.actors[F].conditions.values() if c.condition_id in ("condition:typed.bound_limb", "condition:typed.bound_footwork")]
    assert remaining and {c.source_actor_id for c in remaining} == {S}
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ai_owner", [False, True])
def test_canon_hit_sign_asks_at_trigger_and_persists(tmp_path, ai_owner):
    combat, table, mid = fixture(tmp_path, [CANON, "TAL_METAL_NEEDLE_FLICK"], seed="R4-CANON")
    reach(table, mid, P)
    cid = candidate(table, mid, "White Tiger Seven-Slaughter Canon")
    assert send(table, mid, cid)["status"] == "COMMITTED"
    cid = candidate(table, mid, "Needle Flick", F)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    if ai_owner:
        auto_candidate(combat, mid, P, cid)
        assert table.auto_step(mid, 0)["status"] == "COMMITTED"
    else:
        result = send(table, mid, cid)
        assert result["status"] == "REACTION_REQUIRED"
        prompt = result["reaction"]
        assert prompt["context"]["reaction_source_id"] == "choice:needle.metal_canon_sign"
        for text in ("Seven-Slaughter Canon", "Needle Flick", "Rider Foe"):
            assert text in prompt["moment"]
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        answer = {**prompt["context"], "selection": "USE", "option_ids": ["Open the Guard"]}
        assert send(table, mid, cid, [answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[P]
    assert actor.turn_flags["typed_modifier_once:" + CANON]
    if not ai_owner:
        assert any(c.condition_id == "condition:typed.exposed" for c in loaded.engine.state.actors[F].conditions.values())
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_remove_projectile_preserves_other_shooter_commit_reload(tmp_path):
    hinder = "TAL_SNIPER_HINDERING_PROJECTILE"
    combat, table, mid = fixture(tmp_path, [hinder], second=[hinder], bow=True, seed="R4-PROJECTILES")
    for shooter in (P, S):
        reach(table, mid, shooter)
        cid = candidate(table, mid, "Hindering Projectile", F)
        assert send(table, mid, cid)["status"] == "COMMITTED"
        assert send(table, mid, table.state(mid)["menu"]["end_turn"])["status"] == "COMMITTED"
    reach(table, mid, F)
    states = [c for c in combat._load_session(mid).engine.state.actors[F].conditions.values()
              if c.condition_id == "condition:typed.hindered"]
    assert {c.source_actor_id for c in states} == {P, S}
    cid = candidate(table, mid, "Remove the projectile")
    result = send(table, mid, cid)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    chosen = next(c.instance_id for c in states if c.source_actor_id == P)
    answer = {**prompt["context"], "selection": "USE", "option_ids": [chosen]}
    assert send(table, mid, cid, [answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    remaining = [c for c in loaded.engine.state.actors[F].conditions.values() if c.condition_id == "condition:typed.hindered"]
    assert len(remaining) == 1 and remaining[0].source_actor_id == S
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_projectile_healing_sufficiency_stays_with_gm_after_reload(tmp_path):
    combat, table, mid = fixture(tmp_path, ["TAL_SNIPER_HINDERING_PROJECTILE"], bow=True,
                                foe_mids=["tianxia.talent.life.restorative_mend"], seed="R4-HEALING")
    reach(table, mid, P)
    assert send(table, mid, candidate(table, mid, "Hindering Projectile", F))["status"] == "COMMITTED"
    reach(table, mid, F)
    before = combat._load_session(mid).engine.state.actors[F]
    assert any(c.condition_id == "condition:typed.hindered" for c in before.conditions.values())
    assert send(table, mid, candidate(table, mid, "Restorative Mend", F))["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[F]
    assert actor.current_hp > before.current_hp
    assert any(c.condition_id == "condition:typed.hindered" for c in actor.conditions.values())
    assert any(e.event_type == "GM_RIDER" and "sufficiently seals" in e.payload.get("rider", "") for e in loaded.engine.events)
    assert loaded.mechanical.replay()["status"] == "PASS"
