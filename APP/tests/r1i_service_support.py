"""Real portable-character table harness for rider integration regressions."""
import json
import zipfile
from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

OWNER, FOE, SECOND = [FACTORY_ACTOR_PREFIX + "r1i-" + k for k in ("owner", "foe", "second")]
THIRD = FACTORY_ACTOR_PREFIX + "r1i-third"


def fixture(tmp_path, talents, *, foe_ac=14, seed="R1I-SERVICE", owner_dc=50, owner_cl=17,
            owner_path="Qi Cultivation", owner_resource="Qi", foe_talents=(), foe_score=14,
            owner_ac=14, owner_pb=4, owner_kit=None, positions=None, bundle_transform=None, extra_foe=False,
            second_talents=(), allies=(), wide=False, before_turns=None, map_terrain=None):
    ids = [OWNER, FOE, SECOND]
    owner_doc = sheet(talents, cl=owner_cl, dc=owner_dc, kit=owner_kit)
    owner_doc["identity"]["path"] = owner_path
    owner_doc["ability_scores_and_statistics"]["primary_resource"]["name"] = owner_resource
    docs = [owner_doc, sheet(foe_talents, cl=17, score=foe_score), sheet(second_talents, cl=17)]
    if extra_foe:
        ids.append(THIRD)
        docs.append(sheet([], cl=17))
    for aid, doc in zip(ids, docs):
        doc["identity"]["display_name"] = aid.split("r1i-")[-1].title()
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 500
        doc["ability_scores_and_statistics"]["technique_attack_bonus"] = 100
        if aid == OWNER:
            doc["identity"]["proficiency_bonus"] = owner_pb
            doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = owner_ac
        if aid != OWNER:
            doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = foe_ac
        folder = tmp_path / "portable_characters" / aid.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={"ask": True} if aid == OWNER or aid == SECOND and second_talents else None)
               for aid, doc in zip(ids, docs)]
    if bundle_transform:
        bundle_transform(bundles)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    if wide:
        saved = combat.tabletop_maps.save({"display_name": "R1i Wide", "width_squares": 40, "height_squares": 20,
            "walls": [], "terrain": map_terrain or [], "starts": {"team1": [[3, 6]], "team2": [[4, 6], [5, 6]]}})
        arena = combat.factory_arenas()["battlefield:map." + saved["map_id"]]
    mid = combat._finish_factory_match(bundles, ids, {aid: "team:a" if aid == OWNER or aid in allies else "team:b" for aid in ids},
        positions or {OWNER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, SECOND: {"x": 5, "y": 6}},
        arena, [OWNER], ids[1:],
        control_modes={aid: "MANUAL" for aid in ids}, match_seed=seed, display_name="R1i", maximum_rounds=10)["match_id"]
    def send(cid, answers=(), auto=False):
        if auto:
            return table.auto_step(mid, 0, list(answers))
        menu = table.state(mid)["menu"]
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))
    def commit(cid):
        answers = []
        for _ in range(16):
            result = send(cid, answers)
            if result["status"] == "COMMITTED":
                return result
            assert result["status"] == "REACTION_REQUIRED", result
            p = result["reaction"]
            a = {**p["context"], "selection": "DECLINE"}
            if p.get("choice"):
                a.update(selection="USE", option_ids=(p["choice"].get("preferred") or [p["choice"]["options"][0]["id"]])[:1])
            answers.append(a)
        raise AssertionError("too many prompts")
    if before_turns is not None:
        before_turns(combat, table, mid, send, commit)
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        commit(table.state(mid)["menu"]["end_turn"])
    return combat, table, mid, send, commit


def candidate(table, mid, label, target=None):
    return next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if label in g["label"]
                for o in g["options"] if target is None or target in o.get("target_ids", []))


def place(table, mid, label, destination, reactions=()):
    """Commit an exact square through the real eager menu or lazy map picker."""
    from combat.ext.needle import cell_id
    from combat.gate2_runtime_models import Position
    from combat.placement_menu import CHOICE

    state = table.state(mid)
    menu = state["menu"]
    group = next(g for g in menu["actions"] if g["label"] == label)
    wanted = Position.model_validate(destination)
    option = (group["options"][0] if group.get("placement_picker") else
              next(o for o in group["options"] if Position.model_validate(o["destination"]) == wanted))
    answers = list(reactions)
    for _ in range(8):
        result = table.act(mid, option["candidate_id"], menu["decision_id"], menu["state_version"],
                           state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            return result
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        assert prompt["context"]["reaction_source_id"] == CHOICE, prompt
        selected = cell_id(wanted, include_altitude=True)
        assert selected in {o["id"] for o in prompt["choice"]["options"]}
        answers.append({**prompt["context"], "selection": "USE", "option_ids": [selected]})
    raise AssertionError("Unresolved square choice")


def force_ai_candidate(combat, mid, actor, cid):
    real = combat.controller
    class FixedController:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _context: (cid, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = FixedController()
    combat.set_controller_mode(mid, actor_id=actor, controller_mode="LOCAL_AUTO")


def charge_setup(bundles):
    """Add a bare compiled Charge hit for setup, reserving the tested economy.

    riders/c13 (14cd285f; approved C13r3.review.md, merged 51edf97d)
    enforces Gather Charge's willing-creature target. These fixtures therefore
    use Lightning Lash: Charge. Compile the setup action without optional
    modifiers, so Crackling Arrow cannot consume the Charge we are establishing.
    The tested owner's actions/effects are unchanged; only this extra setup
    action waives its economy. Hit, mark, commit and reload use native paths.
    """
    from combat.canonical import canonical_sha256

    owner = next(b for b in bundles if b["actor_id"] == OWNER)
    bare = compile_character(sheet(["TAL_LIGHTNING_LIGHTNING_LASH"], cl=17, dc=50), actor_id=OWNER)
    action = next(a for a in bare["action_catalog"] if a["display_name"] == "Lightning Lash: Charge")
    original = next(a for a in owner["action_catalog"] if a["display_name"] == "Lightning Lash: Charge")
    action["attack_bonus"] = original["attack_bonus"]
    action["parameters"]["typed"]["numbers"]["attack_bonus"] = original["parameters"]["typed"]["numbers"]["attack_bonus"]
    action["source_definition_id"] = "test:r1i.setup_charge"
    action["display_name"] = "Setup Charge Hit"
    action["economy"] = "NONE"
    action["parameters"]["free_primary"] = True  # setup hit reserves the tested turn economy
    owner["action_catalog"].append(action)
    owner["actor_template"]["action_ids"].append(action["source_definition_id"])
    owner.pop("bundle_sha256", None)
    owner["bundle_sha256"] = canonical_sha256(owner)


def commit_charge(table, mid, send, target):
    """Charge through a hit, declining optional riders that could spend it.

    Uses charge_setup's C13-reviewed targeting correction. The plain Lash is
    selected exactly so a free-use alias or Chains variant cannot replace it.
    """
    from combat import typed_executor as te

    cid = next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"]
               if g["label"] == "Setup Charge Hit" for o in g["options"]
               if target in o.get("target_ids", []))
    answers = []
    for _ in range(16):
        result = send(cid, answers)
        if result["status"] == "COMMITTED":
            # A natural 1 can miss even with a high attack bonus. A fixture must
            # establish the precondition, rather than silently test no Charge.
            engine = table.combat._load_session(mid).engine
            assert te.bears_mark(engine.state.actors[target], OWNER, "Charged"), [
                {k: e.payload[k] for k in ("reason", "natural_result", "provisional_hit")}
                for e in engine.events if e.event_type == "ATTACK_ROLLED"]
            return result
        assert result["status"] == "REACTION_REQUIRED", result
        p = result["reaction"]
        a = {**p["context"], "selection": "DECLINE"}
        if p.get("choice") and not p["choice"].get("allow_decline"):
            minimum = p["choice"].get("minimum_selections", 1)
            a.update(selection="USE", option_ids=[o["id"] for o in p["choice"]["options"]][:minimum])
        answers.append(a)
    raise AssertionError("too many setup Charge prompts")


def immobilize_on_action(label, condition):
    """Persist a typed immobilization through a real action, before its rider.

    Only test bundles change; production authority and the engine stay intact.
    """
    from combat.canonical import canonical_sha256

    def prepare(bundles):
        if condition is None:
            return
        owner = next(b for b in bundles if b["actor_id"] == OWNER)
        for action in owner["action_catalog"]:
            if label in action["display_name"]:
                effect = {"type": "speed", "flat": -30, "applies_to": "self", "expires_on": "UNTIL_REMOVED"} if condition == "speed_zero" else {
                    "type": "condition", "condition": condition, "applies_to": "self",
                    "expires_on": "UNTIL_REMOVED"}
                action["parameters"]["typed"]["effects"].insert(0, effect)
        owner.pop("bundle_sha256", None)
        owner["bundle_sha256"] = canonical_sha256(owner)
    return prepare
