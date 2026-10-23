"""Hunt 27: real table transactions, with a fresh saved-fight load per commit."""
import json
import zipfile

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_carry import KIT

ME, ALLY, FOE, FOE2 = ["actor:factory.h27" + n for n in ("probe", "ally", "foe", "foe2")]
ICE = ["TAL_ICE_ICE_DOMAIN_PALACE_OF_WRITTEN_WINTER", "TAL_ICE_WINTER_STORES_THE_BLOW",
       "TAL_ICE_SHATTER_BLOOM", "TAL_ICE_FROST_SHEATHED_GUARD"]
WATER = ["TAL_WATER_COURT_OF_THE_ENDLESS_TIDE", "TAL_WATER_TEN_THOUSAND_RETURNING_STREAMS"]
WEATHER = ["TAL_WEATHER_COURT_OF_CHANGING_SKIES", "TAL_WEATHER_LINGERING_MANTLE", "TAL_WEATHER_QUICK_MANTLE"]


def arena(tmp_path, talents, topic, manual=True, cl=20, maximum_rounds=4, ask_actors=(), foe_ac=14):
    ids = [ME, ALLY, FOE, FOE2]
    docs = [sheet(talents, cl=cl, dc=22, kit={"starting_kit": KIT})] + [
        sheet([], cl=20, kit={"starting_kit": KIT}) for _ in range(3)]
    for aid, doc, name in zip(ids, docs, ("You", "Ally", "East foe", "West foe")):
        doc["identity"]["display_name"] = name
        doc["ability_scores_and_statistics"]["hit_points"]["maximum"] = 200
        doc["ability_scores_and_statistics"]["primary_resource"]["maximum"] = 100
        if aid in (FOE, FOE2):
            doc["ability_scores_and_statistics"]["armor_class"]["base_value"] = foe_ac
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={"ask": True} if aid == ME or aid in ask_actors else None)
               for aid, doc in zip(ids, docs)]
    # These scenarios choose the target's actual AC, independent of the kit's
    # armour. A sheet base calculation is no longer an override of worn armour.
    for aid, bundle in zip(ids, bundles):
        if aid in (FOE, FOE2):
            bundle["actor_template"]["armor_class"] = foe_ac
    mid = combat._finish_factory_match(
        bundles, ids, {ME: "team:factory", ALLY: "team:factory", FOE: "team:opponents", FOE2: "team:opponents"},
        {ME: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 7}, FOE: {"x": 4, "y": 6}, FOE2: {"x": 5, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME, ALLY], [FOE, FOE2],
        control_modes={ME: "MANUAL" if manual else "LOCAL_AUTO", **{aid: "MANUAL" for aid in ask_actors}}, match_seed=f"H27-{topic}-0",
        maximum_rounds=maximum_rounds, display_name="Hunt27 regression")["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


def commit(combat, table, mid, tmp_path, cid=None, choose=None):
    view = table.state(mid)
    menu = view["menu"]
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    real_controller = combat.controller
    if cid and not menu.get("manual"):
        from combat.gate4_adapters import ManualControllerAdapter
        requested = next(c for c in combat._load_session(mid).engine.legal_candidates() if c.candidate_id == cid)

        class Controller:
            def choose_primary_action(self, context):
                # The ordinary AI context may retain only representative area
                # destinations. Select the same ability from that legal menu.
                selected = next((c for c in context.legal_candidates if c.candidate_id == cid), None)
                if selected is None:
                    selected = next(c for c in context.legal_candidates if c.source_definition_id == requested.source_definition_id
                                    and c.target_ids == requested.target_ids)
                return ManualControllerAdapter(lambda _context: (selected.candidate_id, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real_controller, name)

        combat.controller = Controller()
    answers = []
    for _ in range(40):
        result = (table.act(mid, cid or menu["end_turn"], menu["decision_id"], menu["state_version"], view["last_sequence"], answers)
                  if menu.get("manual") else table.auto_step(mid, view["last_sequence"], answers))
        if result["status"] != "REACTION_REQUIRED":
            break
        assert CombatService(ROOT, tmp_path)._load_session(mid).engine.state.model_dump(mode="json") == before
        prompt = result["reaction"]
        answer = {**prompt["context"], "selection": "USE"}
        if prompt.get("choice"):
            choice = prompt["choice"]
            selected = (choose(prompt) if choose else
                        [o["id"] for o in choice["options"][:choice.get("minimum", 1)]])
            answer["option_ids"] = selected or []
            if selected is None:
                answer["selection"] = "DECLINE"
        assert answer not in answers
        answers.append(answer)
    assert result["status"] == "COMMITTED", result
    combat.controller = real_controller
    expected = combat._load_session(mid).engine.state.model_dump(mode="json")
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert fresh.engine.state.model_dump(mode="json") == expected
    assert fresh.mechanical.replay()["status"] == "PASS"
    return answers


def owner_turn(combat, table, mid, tmp_path, idle=False):
    for _ in range(60):
        if combat._load_session(mid).engine.state.current_actor_id == ME:
            return
        # Focused buff tests keep the adjacent ally in Touch range, using real
        # table end-turn transactions rather than changing saved positions.
        cid = next((c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
                    if c.kind.value == "END_TURN"), None) if idle else None
        commit(combat, table, mid, tmp_path, cid)
    pytest.fail("owner never reached its turn")


def action(combat, mid, name, target=ME):
    return next(c.candidate_id for c in combat._load_session(mid).engine.legal_candidates()
                if (c.display_name.startswith(name) if target is None else c.display_name == name)
                and (target is None or target in c.target_ids))


def test_hunt27_ice_focus_reopens_past_step_11(tmp_path):
    combat, table, mid = arena(tmp_path, ICE, "ice")
    wanted = ["Ice Domain: Palace of Written Winter", "Crystallize Path", "Frost-Sheathed Guard", "Shatter Bloom"]
    used, picks, turn = {}, [], None
    choices = []
    for step in range(35):
        engine = combat._load_session(mid).engine
        key = (engine.state.round_number, engine.state.current_actor_id)
        if key != turn:
            turn, picks = key, []
        view = table.state(mid)
        cid = None
        if view["menu"].get("manual"):
            options = [(used.get(g["label"], 0) * 100 + wanted.index(g["label"]), g)
                       for g in view["menu"]["actions"] if g["label"] in wanted and g["label"] not in picks]
            if options:
                group = min(options, key=lambda row: row[0])[1]
                option = next((o for o in group["options"] if "Guard" in group["label"] and ME in o.get("target_ids", [])), group["options"][0])
                cid = option["candidate_id"]
                picks.append(group["label"])
                used[group["label"]] = used.get(group["label"], 0) + 1
        choices.extend(commit(combat, table, mid, tmp_path, cid))
    engine = combat._load_session(mid).engine
    linked = [e.payload["zone"] for e in engine.events if e.event_type == "ZONE_CREATED"
              and e.payload["zone"]["trigger_profile"].get("ends_with")]
    assert linked
    assert any(a["reaction_source_id"] == "choice:needle.domain_lattice" for a in choices)
    assert any(not z.active and z.trigger_profile.get("ends_with") for z in engine.state.zones.values())
