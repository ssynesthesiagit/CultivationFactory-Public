"""Free scene-start Mantle selection through the native setup transaction."""
import json
import zipfile

import pytest

from combat.ext import mantles
from combat.factory_compiler import compile_character
from combat.fight_setup import SOURCE
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_carry import KIT

OWNER, ALLY, FOE, FOE2 = ["actor:factory.h25" + name for name in ("owner", "ally", "foe", "foe2")]


def fixture(tmp_path, *, ask=True, manual_owner=True, ai_first=True):
    ids = [OWNER, ALLY, FOE, FOE2]
    docs = [sheet([mantles.FEATURE], cl=20, kit={"starting_kit": KIT})] + [
        sheet([], cl=20, kit={"starting_kit": KIT}) for _ in range(3)]
    for aid, doc, name in zip(ids, docs, ("You", "Ally", "Enemy", "Enemy Two")):
        doc["identity"]["display_name"] = name
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    combat = CombatService(ROOT, tmp_path)
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={"ask": ask} if aid == OWNER else None)
               for aid, doc in zip(ids, docs)]
    mid = combat._finish_factory_match(
        bundles, ids, {OWNER: "team:factory", ALLY: "team:factory", FOE: "team:opponents", FOE2: "team:opponents"},
        {OWNER: {"x": 3, "y": 6}, ALLY: {"x": 3, "y": 7}, FOE: {"x": 4, "y": 6}, FOE2: {"x": 5, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [OWNER, ALLY], [FOE, FOE2],
        control_modes={OWNER: "MANUAL" if manual_owner else "LOCAL_AUTO"},
        match_seed="H25-FOCUS-0", maximum_rounds=2, display_name="Hunt25 Mantle setup")["match_id"]
    first = combat._load_session(mid).engine.state.current_actor_id
    assert first != OWNER  # The original focus seed starts on another creature's turn.
    if not ai_first:
        combat.set_controller_mode(mid, actor_id=first, controller_mode="MANUAL")
    return combat, TabletopService(combat, tmp_path), mid


def send(table, mid, answers=()):
    state = table.state(mid)
    menu = state["menu"]
    if menu.get("manual"):
        cid = next(o["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == SOURCE for o in g["options"])
        return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))
    return table.auto_step(mid, state["last_sequence"], list(answers))


@pytest.mark.parametrize("ai_first", [False, True])
@pytest.mark.parametrize("ask", [False, True])
def test_manual_initial_mantle_is_free_transactional_and_reloads(tmp_path, ai_first, ask):
    combat, table, mid = fixture(tmp_path, ask=ask, ai_first=ai_first)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    assert not mantles.active(combat._load_session(mid).engine.state.actors[OWNER])
    assert len(before["setup_tasks"]) == 1
    result = send(table, mid)
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == OWNER
    assert "Former-Life Mantle" in prompt["reaction"]
    assert "before the first turn" in prompt["moment"] and "You" in prompt["moment"]
    assert not prompt["choice"]["allow_decline"]
    assert {o["id"] for o in prompt["choice"]["options"]} == set(list(mantles.MANTLES)[:3])
    # A paused preview must not pick a Mantle, begin turn one or spend anything.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send(table, mid)["reaction"] == prompt
    answer = {**prompt["context"], "selection": "USE", "option_ids": ["Wandering Sword-Saint"]}
    assert send(table, mid, [answer])["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[OWNER]
    assert mantles.active(actor) == ["Wandering Sword-Saint"]
    assert actor.resources == before["actors"][OWNER]["resources"]
    assert actor.action_available and actor.bonus_action_available and actor.reaction_available
    assert loaded.engine._effective_speed(actor) == actor.speed_ft + 10
    assert not loaded.engine.state.setup_tasks
    kinds = [e.event_type for e in loaded.engine.events]
    application = next(i for i, e in enumerate(loaded.engine.events)
                       if e.event_type == "CONDITION_APPLIED" and e.payload.get("condition_id") == mantles.ACTIVE)
    assert application < kinds.index("FIGHT_SETUP_COMPLETED") < kinds.index("ROUND_STARTED") < kinds.index("TURN_STARTED")
    assert loaded.verify()["status"] == "PASS"
    # Continue the scene; reload cannot ask again or silently restore the first known Mantle.
    state = table.state(mid)
    if state["menu"].get("manual"):
        menu = state["menu"]
        result = table.act(mid, menu["end_turn"], menu["decision_id"], menu["state_version"], state["last_sequence"], [])
    else:
        result = table.auto_step(mid, state["last_sequence"], [])
    assert result["status"] == "COMMITTED"
    fresh = CombatService(ROOT, tmp_path)._load_session(mid)
    assert mantles.active(fresh.engine.state.actors[OWNER]) == ["Wandering Sword-Saint"]
    assert fresh.verify()["status"] == "PASS"


def test_ai_initial_mantle_is_chosen_automatically_and_reloads(tmp_path):
    combat, table, mid = fixture(tmp_path, manual_owner=False)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    assert len(before["setup_tasks"]) == 1
    assert send(table, mid)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    actor = loaded.engine.state.actors[OWNER]
    assert mantles.active(actor) == ["Warrior of a Fallen Age"]
    assert actor.resources == before["actors"][OWNER]["resources"]
    assert actor.action_available and actor.bonus_action_available and actor.reaction_available
    assert not loaded.engine.state.setup_tasks
    assert loaded.verify()["status"] == "PASS"


@pytest.mark.parametrize(("name", "benefits"), [
    ("Warrior of a Fallen Age", ["Proficiency with one weapon group"]),
    ("Forgotten Scholar", ["Intelligence- or Wisdom-based skill", "+2 to checks", "Once per turn, add 1d4"]),
])
def test_setup_table_discloses_and_logs_gm_applied_mantle_benefits(tmp_path, name, benefits):
    combat, table, mid = fixture(tmp_path)
    prompt = send(table, mid)["reaction"]
    assert "GM applies" in prompt["moment"]
    assert "not automated" in prompt["moment"]
    assert "while this Mantle is active" in prompt["moment"]
    assert "costs no Action, Reaction or Qi" in prompt["moment"]
    assert "(Arrival) do not apply" in prompt["moment"]
    labels = {option["id"]: option["label"] for option in prompt["choice"]["options"]}
    label = labels[name]
    assert "GM applies (not automated):" in label
    for benefit in benefits:
        assert benefit in label
    assert "Automated:" in labels["Wandering Sword-Saint"]
    assert "GM applies" not in labels["Wandering Sword-Saint"]
    if name == "Warrior of a Fallen Age":
        assert "Automated: Once per turn, a weapon hit adds your Proficiency Bonus to damage" in label
    answer = {**prompt["context"], "selection": "USE", "option_ids": [name]}
    result = send(table, mid, [answer])
    assert result["status"] == "COMMITTED"
    # Inspect the actual player-visible table history, including after fresh loading.
    fresh_table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    feed = fresh_table.events(mid, 0)["events"]
    notice = next(row["summary"] for row in feed if name in row["summary"] and "GM applies" in row["summary"])
    assert "Former-Life Mantle" in notice and "for You" in notice
    assert "Until you switch Mantles" in notice and "not automated" in notice
    for benefit in benefits:
        assert benefit in notice
    assert "Arrival" not in notice
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert mantles.active(loaded.engine.state.actors[OWNER]) == [name]
    assert loaded.verify()["status"] == "PASS"
