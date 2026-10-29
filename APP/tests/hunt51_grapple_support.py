"""Local test support for Hunt 51 service-level grapple fixtures."""

from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet

IDS = ["actor:factory.luna38-a", "actor:factory.luna38-b", "actor:factory.luna38-c", "actor:factory.luna38-d"]
NAMES = {IDS[0]: "First Grappler", IDS[1]: "Second Grappler", IDS[2]: "Held Fighter", IDS[3]: "Heavenquake User"}


def fight(tmp_path, name, *, six=False, heavenquake=False, dragon_clinch=False,
          concentration=False, ask=True, fixture_conditions=(), heaven_clinch=False,
          equipment=(), talents=(), owner_items=None, legacy_weapon_metadata=False, saved_bundle=None,
          actor_scores=None, share_weapons=False, legacy_delivery_metadata=False, wielded=()):
    user = tmp_path / name
    user.mkdir()
    app = Path(__file__).resolve().parents[1]
    service = CombatService(app, user)
    table = TabletopService(service, user)
    ids = IDS[:2] + (["actor:factory.luna38-e"] if six else []) + IDS[2:] + (["actor:factory.luna38-f"] if six else [])
    names = {**NAMES, "actor:factory.luna38-e": "Third Ally", "actor:factory.luna38-f": "Third Enemy"}
    bundles = []
    for index, actor_id in enumerate(ids):
        mids = []
        if heavenquake and actor_id == IDS[3]:
            mids.append("TAL_IRON_FIST_ONE_INCH_HEAVENQUAKE")
        if dragon_clinch and actor_id == IDS[0]:
            mids.append("TAL_IRON_FIST_DRAGON_STEP_CLINCH")
            if heaven_clinch:
                mids.append("TAL_IRON_FIST_HEAVEN_SEIZING_CLINCH")
        if concentration and actor_id == IDS[0]:
            mids.append("FIRE_TAL_BURNING_WEAPON")
        score = 30 if index < len(ids) // 2 or (heavenquake and actor_id == IDS[3]) else 10
        score = (actor_scores or {}).get(actor_id, score)
        if actor_id == IDS[0]:
            mids.extend(talents)
        doc = sheet(mids, cl=18, dc=30, primary="Stamina", score=score)
        if actor_id == IDS[0]:
            if equipment:
                from factory_authoring.starting_kits import item_definition
                doc["equipment"] = [{"starting_kit": {"items": [
                    {"item_id": item, "name": item_definition(item)["name"], "quantity": 1} for item in equipment],
                    **({"wielded": list(wielded)} if wielded else {})}}]
        doc["identity"]["display_name"] = names[actor_id]
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1000
        bundle = compile_character(doc, actor_id=actor_id, reaction_plan={"ask": ask},
                                   held_weapons=[row for earlier in bundles for row in earlier.get("weapons", [])]
                                   if share_weapons else None,
                                   owner_items=owner_items if actor_id == IDS[0] else None)
        if actor_id == IDS[0] and saved_bundle is not None:
            from copy import deepcopy
            bundle = deepcopy(saved_bundle)
        if legacy_weapon_metadata:
            for action in bundle["action_catalog"]:
                action["parameters"].pop("requires_hands", None)
        if legacy_delivery_metadata:
            for action in bundle["action_catalog"]:
                action["parameters"].get("typed", {}).pop("weapon_source_id", None)
        # Synthetic condition actions exercise the shipped typed-condition pipeline,
        # not a test-only event dispatch or a claim about an invented ability.
        if actor_id in (IDS[0], IDS[3]):
            from combat.gate2_runtime_models import ActionDefinition, EconomyKind

            for condition in fixture_conditions:
                action = ActionDefinition(
                    source_definition_id=f"action:test.{actor_id.removeprefix('actor:factory.')}.{condition}",
                    display_name=f"Fixture: {condition.title()}",
                    owner_id=actor_id, economy=EconomyKind.ACTION, resolution_kind="TYPED", target_kind="HOSTILE_ENTITY",
                    range_ft=5, parameters={"typed": {"numbers": {"save_dc": 30}, "effects": [
                        {"type": "condition", "condition": condition, "applies_to": "target", "duration": "until_removed"}]}})
                bundle["action_catalog"].append(action.model_dump(mode="json"))
                bundle["actor_template"]["action_ids"].append(action.source_definition_id)
        bundles.append(bundle)
    coords = ([{"x": 3, "y": 3}, {"x": 1, "y": 8}, {"x": 10, "y": 8}, {"x": 4, "y": 3},
               {"x": 4, "y": 4}, {"x": 3, "y": 4}] if six else
              [{"x": 3, "y": 3}, {"x": 1, "y": 8}, {"x": 4, "y": 3}, {"x": 3, "y": 4}])
    positions = dict(zip(ids, coords))
    arena = service.tabletop_maps.save({"display_name": name, "width_squares": 12, "height_squares": 10,
                                        "walls": [], "materials": [], "starts": {"team1": [[3, 3], [3, 5]], "team2": [[4, 3], [9, 8]]}})
    midpoint = len(ids) // 2
    teams = dict.fromkeys(ids[:midpoint], "team:factory") | dict.fromkeys(ids[midpoint:], "team:opponents")
    match = service._finish_factory_match(
        bundles, ids, teams, positions, service.factory_arenas()["battlefield:map." + arena["map_id"]],
        ids[:midpoint], ids[midpoint:], control_modes=dict.fromkeys(ids, "MANUAL"), match_seed="LUNA38-" + name,
        display_name=name, maximum_rounds=10,
    )["match_id"]
    return user, service, table, match, ids


def send(table, match, pick=None, reaction_pick=None):
    state = table.state(match)
    menu = state["menu"]
    after = state["last_sequence"]
    options = [{**option, "source_definition_id": group["source_definition_id"]}
               for group in menu.get("actions", []) for option in group["options"]] + menu.get("moves", [])
    chosen = next((option for option in options if pick and pick(option)), None)
    if pick and chosen is None:
        raise AssertionError("requested TabletopService candidate is missing")
    candidate = chosen["candidate_id"] if chosen else menu["end_turn"]
    answers = []
    for _ in range(40):
        result = table.act(match, candidate, menu["decision_id"], menu["state_version"], after, answers)
        if result["status"] != "REACTION_REQUIRED":
            break
        reaction = result["reaction"]
        answer = {**reaction["context"], "selection": "DECLINE"}
        if reaction.get("choice") and not reaction["choice"].get("allow_decline"):
            choice = reaction["choice"]
            option_ids = reaction_pick(choice) if reaction_pick else [choice["options"][0]["id"]]
            answer.update(selection="USE", option_ids=option_ids)
        answers.append(answer)
    assert result["status"] == "COMMITTED", result
    return result


def on_turn(table, match, actor_id):
    for _ in range(40):
        if table.state(match)["menu"]["actor_id"] == actor_id:
            return
        send(table, match)
    raise AssertionError("actor turn did not arrive")


def grapple(target):
    return lambda option: "Grapple" in str(option.get("label", "")) \
        and "Fixture:" not in str(option.get("label", "")) and option.get("target_ids") == [target]


def verify_reloaded(user, service, match):
    fresh = CombatService(Path(__file__).resolve().parents[1], user)._load_session(match)
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"
    assert fresh.engine.state.model_dump(mode="json") == service._load_session(match).engine.state.model_dump(mode="json")
