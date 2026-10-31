"""Synthetic persisted tables for Hidden Strike and Nullifying Strike regressions."""
import copy
import json
import zipfile

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from combat.gate4_adapters import ManualControllerAdapter
from tests.h1_support import ROOT, sheet
from tests.test_carry import KIT

LEFT, RIGHT = "actor:factory.36000001", "actor:factory.36000002"
HIDDEN = "tianxia.subpath.qi.ninpo_adept.feature.hidden_strike"
VEIL = "tianxia.subpath.qi.ninpo_adept.feature.smoke_veil"


def fight(tmp_path, owned=(), *, effects=None, seed="HUNT36-HIDDEN", kit=None, foe_hp=1000, foe_ac=1, right=(), primary="Qi",
          positions=None, checks=False, right_effects=None, legacy_hidden=False, cl=15, stamina=None,
          actor_template_overrides=None):
    bundles = []
    for aid, mids in ((LEFT, owned), (RIGHT, right)):
        document = sheet(list(mids), cl=cl, primary=primary, kit=kit if aid == LEFT and kit else {"starting_kit": KIT})
        if aid == RIGHT:
            document["ability_scores_and_statistics"]["hit_points"]["maximum"] = foe_hp
            document["ability_scores_and_statistics"]["armor_class"]["base_value"] = foe_ac
        document["identity"]["display_name"] = "River Keeper" if aid == LEFT else "Visiting Fighter"
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
        bundle = compile_character(document, actor_id=aid, reaction_plan={"ask": aid == LEFT})
        # Bind scenario traits into genesis so table reloads and mechanical replay see the same actors.
        bundle["actor_template"].update((actor_template_overrides or {}).get(aid, {}))
        if aid == RIGHT:
            # Scenario AC controls hit/miss cases, rather than the worn kit's
            # now-authoritative armour calculation replacing this test value.
            bundle["actor_template"]["armor_class"] = foe_ac
        if aid == LEFT and stamina is not None:
            for resource in bundle["actor_template"]["resources"]:
                if resource["resource_id"] == "resource:core.stamina":
                    resource["maximum"] = resource["initial"] = stamina
        setup_effects = effects if aid == LEFT else right_effects
        if legacy_hidden:
            for row in bundle["typed_passives"]:
                if row.get("kind") == "hidden_strike":
                    row.pop("choice_owner", None)
        if setup_effects is not None:
            action = copy.deepcopy(next(a for a in bundle["action_catalog"] if a["resolution_kind"] == "TYPED"))
            action.update(source_definition_id=f"action:test.h36.{aid}", display_name="Test setup", economy="ACTION", target_kind="SELF", costs=[], range_ft=60)
            action["parameters"] = {"typed": {"effects": setup_effects, "numbers": {"cl": 15, "pb": 4, "save_dc": 100}, "duration": {"kind": "instant"}, "riders": []}}
            bundle["action_catalog"].append(action)
            bundle["actor_template"]["action_ids"].append(action["source_definition_id"])
        if checks and aid == LEFT:
            action = copy.deepcopy(next(a for a in bundle["action_catalog"] if a["resolution_kind"] == "TYPED"))
            action.update(source_definition_id="action:test.h36.stealth", display_name="Test Stealth check", economy="NONE", target_kind="SELF", costs=[], range_ft=5)
            action["parameters"] = {"free_primary": True, "typed": {"effects": [{"type": "remove_condition", "condition": "hidden", "applies_to": "self"}, {"type": "hide", "bonus": 0}],
                "numbers": {"cl": 15, "pb": 4, "save_dc": 15}, "duration": {"kind": "instant"}, "riders": []}}
            bundle["action_catalog"].append(action)
            bundle["actor_template"]["action_ids"].append(action["source_definition_id"])
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(bundles, [LEFT, RIGHT], {LEFT: "team:factory", RIGHT: "team:opponents"},
        positions or {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}}, combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [LEFT], [RIGHT], control_modes={LEFT: "MANUAL", RIGHT: "MANUAL"}, match_seed=seed,
        display_name="Hunt 36 regression", maximum_rounds=10)["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def reload(combat, mid):
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid)
    assert before == loaded.engine.state.model_dump(mode="json")
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"
    return loaded.engine


def send(combat, table, mid, cid, *, ai=False, pick=None, decline=None):
    if ai:
        real = combat.controller
        class SelectedController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)
            def __getattr__(self, name):
                return getattr(real, name)
        combat.controller = SelectedController()
        combat.set_controller_mode(mid, actor_id=combat._load_session(mid).engine.state.current_actor_id, controller_mode="LOCAL_AUTO")
    answers, prompts = [], []
    for _ in range(12):
        state = table.state(mid)
        menu = state["menu"]
        result = table.auto_step(mid, state["last_sequence"], answers) if ai else table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            reload(combat, mid)
            return prompts
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        prompts.append(prompt)
        answer = {**prompt["context"], "selection": "USE"}
        if decline and decline(prompt, len(prompts)):
            answer["selection"] = "DECLINE"
        if prompt.get("choice") and answer["selection"] != "DECLINE":
            options = prompt["choice"]["options"]
            answer["option_ids"] = [next((o["id"] for o in options if pick and pick(o)), options[0]["id"])]
        answers.append(answer)
    raise AssertionError("choice loop did not commit")


def act(combat, table, mid, label, **kwargs):
    menu = table.state(mid)["menu"]
    if label == "end" and "end_turn" not in menu:
        cid = next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates() if c.kind.value == "END_TURN")
        kwargs["ai"] = True
    else:
        cid = menu["end_turn"] if label == "end" else next(o["candidate_id"] for g in menu["actions"] if g["label"] == label for o in g["options"])
    return send(combat, table, mid, cid, **kwargs)


def turn(combat, table, mid, actor=LEFT):
    for _ in range(3):
        if table.state(mid)["menu"]["actor_id"] == actor:
            return
        act(combat, table, mid, "end")
    raise AssertionError("turn did not advance")


def setup_hidden(tmp_path, *, smoke=False, owned=True, right=(), extra=(), **kwargs):
    effects = [{"type": "condition", "condition": "invisible", "applies_to": "self", "expires_on": "UNTIL_REMOVED"}]
    combat, table, mid = fight(tmp_path, [*([HIDDEN] if owned else []), *([VEIL] if smoke else []), *extra], effects=effects, right=right, **kwargs)
    turn(combat, table, mid)
    act(combat, table, mid, "Test setup")
    if smoke:
        menu = table.state(mid)["menu"]
        cid = next(o["candidate_id"] for g in menu["actions"] if g["label"] == "Smoke Veil" for o in g["options"] if o.get("destination") == {"x": 3, "y": 6})
        send(combat, table, mid, cid)
    act(combat, table, mid, "end")
    turn(combat, table, mid)
    return combat, table, mid


def weapon(combat, mid):
    return next(c for c in combat._load_session(mid).engine.legal_candidates() if ".weapon." in c.source_definition_id and "#" not in c.source_definition_id and tuple(c.target_ids) == (RIGHT,))
