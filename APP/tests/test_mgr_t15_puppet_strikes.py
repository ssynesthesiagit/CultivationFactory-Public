"""F15R2 B2: the acquired-vessel table strikes, split out of test_mgr_t15_puppet_initiation.py so each file fits the CI shard.

The owner is learned, rested and journeyed exactly as in that file (learn_and_journey), then plays real table strikes.
"""
import json
import zipfile
from pathlib import Path

import pytest

from canonical_catalog import CanonicalCatalogAuthorityService
from combat.gate5_service import CombatService
from combat.gate2_runtime_content import AN
from combat.tabletop_service import TabletopService
from combat.tabletop import TabletopError
from combat.ext.puppet_initiation import SOURCE, SPHERE, TOOLS, SKILL
from tests.h1_support import sheet
from tests.auto28_puppetry_support import turn, resolve

ROOT = Path(__file__).resolve().parents[1]
PID = "0badc0de-0000-4000-8000-000000000015"
OTHER = "0badc0de-0000-4000-8000-000000000016"
A = "actor:factory." + PID
B = "actor:factory." + OTHER
ARENA = "battlefield:map.builtin-mountain-pass"
# Shipped inputs used by native advancement (also public-CI resource discovery).
RESOURCES = (ROOT / "authority/Tianxia_Sphere_Path_Access_R1.json",
             ROOT / "authority/Tianxia_Forged_Technique_Authority_R1.json")


def _rules():
    return json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text())



def native(tmp_path, *, prior=None, cl=1):
    assert all(p.is_file() for p in RESOURCES)
    for pid in (PID, OTHER):
        doc = sheet([], cl=cl, key="INT", name="Puppeteer" if pid == PID else "Observer")
        doc["identity"]["proficiency_bonus"] = 2 + max(0, cl - 1) // 4
        doc["path_and_subpath"] = {"path_record_ids": ["tianxia.path.qi_cultivation"]}
        if prior and pid == PID:
            if prior == SKILL:
                doc["ability_scores_and_statistics"]["skills"] = [
                    {"skill": SKILL, "bonus": 4, "proficiency_multiplier": 1}]
            else:
                doc["ability_scores_and_statistics"]["tool_proficiencies"] = [prior]
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
    return cold(tmp_path)


def cold(tmp_path):
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    table.canonical_catalog = CanonicalCatalogAuthorityService(ROOT)
    return combat, table


def choose(table, proficiency, project_id=PID):
    rows = table.learning_preview(project_id, SPHERE, {"proficiency": proficiency})["learning_choices"]
    selected = {"proficiency": proficiency, "free": rows[1]["options"][0]["id"]}
    rows = table.learning_preview(project_id, SPHERE, selected)["learning_choices"]
    if len(rows) == 3:
        selected["bonus"] = next(o["id"] for o in rows[2]["options"] if o["id"] != selected["free"])
    return selected


def learn_and_journey(tmp_path, *, automatic=False):
    combat, table = native(tmp_path)
    table.add_advancement(PID, "sphere", SPHERE, learning_choices=choose(table, TOOLS[0]))
    state = combat.create_journey(project_ids=[PID, OTHER], arena_id=ARENA,
        positions={A: {"x": 3, "y": 6}, B: {"x": 4, "y": 6}},
        base_paces={A: 12000, B: 12000}, control_modes={A: "LOCAL_AUTO" if automatic else "MANUAL", B: "MANUAL"})
    return combat, table, state["journey_id"]

def _raise_at(table, combat, mid, aid, at):
    turn(table, mid, aid)
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.actor_id == aid
                     and c.display_name.startswith("Raise the Vessel") and c.destination
                     and (at is None or (c.destination.x, c.destination.y) == at))
    view = table.state(mid)
    menu = view["menu"]
    return resolve(lambda answers: table.act(mid, candidate.candidate_id, menu["decision_id"],
        menu["state_version"], view["last_sequence"], answers), {"choice:needle.vessel_raise_move": []})



@pytest.mark.parametrize("response", ("Tug the Joint", "Cross the Limb", "Guarding Vessel", "Snap the Thread"))
@pytest.mark.parametrize("automatic", (False, True))
def test_acquired_vessel_strikes_and_pays_each_basic_response_through_table(tmp_path, monkeypatch, response, automatic):
    from combat.gate2_rolls import DeterministicRollAuthority
    from combat.typed_executor import bears_mark
    from combat.ext import placed, vessel
    original = DeterministicRollAuthority.d20
    def roll(self, **kwargs):
        result = original(self, **kwargs)
        # Only deterministic dice are replaced; no action, ownership, receipt,
        # mark, hit effect or choice transport is installed by the test.
        attack = "ATTACK" in kwargs.get("reason", "").upper()
        return result.model_copy(update={"natural_result": 15 if attack else 1, "total": 100 if attack else 1})
    monkeypatch.setattr(DeterministicRollAuthority, "d20", roll)
    combat, table, jid = learn_and_journey(tmp_path)
    option = next(o for o in combat.journey_menu(jid, A)["options"] if o["kind"] == "puppet_initiation_rest")
    state = combat.journey_act(jid, 0, A, option["kind"], option["payload"])
    mid = combat.journey_start_combat(jid, state["revision"], {A: "team:a", B: "team:b"})["match_id"]
    turn(table, mid, A)
    def act(label, target=None, destination=None, automatic=False):
        engine = combat._load_session(mid).engine
        c = next(c for c in engine.legal_candidates() if c.actor_id == A
                 and c.display_name.startswith(label) and (target is None or target in c.target_ids)
                 and (destination is None or c.destination and (c.destination.x, c.destination.y) == destination))
        state = table.state(mid)
        menu = state["menu"]
        if automatic:
            from combat.gate4_adapters import ManualControllerAdapter
            real = combat.controller
            class Controller:
                def choose_primary_action(self, context):
                    # The menu candidate was captured before this step; ids change when a reaction
                    # removes a response (Guarding Vessel on ATTACK_ROLLED). Pick the same action
                    # from the context's own legal candidates instead of the captured id.
                    current = next(x for x in context.legal_candidates if x.actor_id == c.actor_id
                                   and x.display_name == c.display_name and tuple(x.target_ids) == tuple(c.target_ids)
                                   and x.destination == c.destination)
                    return ManualControllerAdapter(lambda _: (current.candidate_id, ())).choose_primary_action(context)
                def __getattr__(self, name):
                    return getattr(real, name)
            combat.controller = Controller()
            combat.set_controller_mode(mid, actor_id=A, controller_mode="LOCAL_AUTO")
            try:
                return resolve(lambda answers: table.auto_step(mid, table.state(mid)["last_sequence"], answers))
            finally:
                combat.controller = real
                combat.set_controller_mode(mid, actor_id=A, controller_mode="MANUAL")
        return resolve(lambda answers: table.act(mid, c.candidate_id, menu["decision_id"], menu["state_version"],
            state["last_sequence"], answers), {"choice:needle.vessel_raise_move": []})
    act("Raise the Vessel", destination=(3, 5))
    turn(table, mid, B)
    turn(table, mid, A)
    before = combat._load_session(mid).engine
    hp = before.state.actors[B].current_hp
    act("Puppet Strike (from the vessel)", B)
    engine = combat._load_session(mid).engine
    assert engine.state.actors[B].current_hp < hp
    assert bears_mark(engine.state.actors[B], A, vessel.MARK)
    hp = engine.state.actors[B].current_hp
    position = engine.state.actors[B].position
    cp = engine.state.actors[A].resources["resource:core.qi"]
    _, prompts = act("Tension Response: " + response, A if response == "Guarding Vessel" else B, automatic=automatic)
    combat, table = cold(tmp_path)
    loaded = combat._load_session(mid)
    engine = loaded.engine
    assert not bears_mark(engine.state.actors[B], A, vessel.MARK)
    assert engine.state.actors[A].resources["resource:core.qi"] == cp
    if response == "Tug the Joint":
        assert engine.state.actors[B].position != position
        assert automatic or any("Tug" in p.get("moment", "") for p in prompts)
    elif response == "Cross the Limb":
        assert any(m.target_field == "attack_mode" and m.value == "DISADVANTAGE" for m in engine.state.actors[B].modifiers.values())
    elif response == "Guarding Vessel":
        assert any(c.condition_id == vessel.GUARDED for c in engine.state.actors[A].conditions.values())
    else:
        assert engine.state.actors[B].current_hp < hp
    assert loaded.mechanical.replay()["status"] == "PASS"
    if response != "Snap the Thread":
        return
    # Dismissal ends the thread while preserving the physical item's identity,
    # form and last square; reclaiming cannot duplicate it at a different cell.
    item = next(c.data for c in engine.state.actors[A].conditions.values() if c.condition_id == vessel.PREPARED_ITEM)
    act("Dismiss Vessel")
    turn(table, mid, B)
    turn(table, mid, A)
    act("Raise the Vessel", destination=(item["x"], item["y"]))
    loaded = combat._load_session(mid)
    owned = placed.of(loaded.engine, "vessel", owner_id=A)
    assert len(owned) == 1 and placed.data(owned[0])["item_instance_id"] == item["item_instance_id"]
    for _ in range(10):
        turn(table, mid, B)
        turn(table, mid, A)
    loaded = cold(tmp_path)[0]._load_session(mid)
    assert not placed.of(loaded.engine, "vessel", owner_id=A)
    saved = next(c.data for c in loaded.engine.state.actors[A].conditions.values() if c.condition_id == vessel.PREPARED_ITEM)
    assert saved["item_instance_id"] == item["item_instance_id"] and saved["broken"] == 0
    assert combat.journeys.actor_preparations(A)[SOURCE]["item_instance_id"] == item["item_instance_id"]
    assert loaded.mechanical.replay()["status"] == "PASS"


