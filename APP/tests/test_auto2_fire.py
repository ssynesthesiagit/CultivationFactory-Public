"""Printed Fire choices through the table, session execution and cold reload."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from combat.gate3_reducer import canonical_state_document
from combat.gate5_service import CombatService
from tests.r1i_service_support import OWNER, FOE, SECOND, fixture, candidate
from tests.test_auto77f1_fire_service import _run, _candidate

FOCUS = "tianxia.talent.fire.white_hot_focus"
LANCE = "FIRE_TAL_INCINERATING_LANCE"
WARD = "tianxia.talent.fire.blazing_armor"


def cold(combat, mid, tmp_path):
    before = canonical_state_document(combat._load_session(mid).engine.state)
    fresh = CombatService(combat.source_root, tmp_path)._load_session(mid)
    assert canonical_state_document(fresh.engine.state) == before
    assert fresh.verify()["status"] == "PASS"
    assert fresh.mechanical.replay()["status"] == "PASS"
    if os.environ.get("A2_FIRE_CAPTURE"):
        dest = Path(os.environ["A2_FIRE_CAPTURE"]) / tmp_path.name
        shutil.copytree(tmp_path, dest, dirs_exist_ok=True)
    return fresh.engine


def damage(engine, target):
    return [e.payload for e in engine.events if e.event_type == "DAMAGE_COMMITTED" and target in e.target_ids]


def ward(table, mid, commit, target):
    # Each combatant's real Blazing Armor grants the defense; no direct engine mutation.
    commit(candidate(table, mid, "Blazing Armor", target))
    commit(table.state(mid)["menu"]["end_turn"])


def resistant_fixture(tmp_path, talents, *, immune=False, dc=50, hidden=False):
    # Immunity is a declarative fixture condition on the defender's real Ward.
    def prepare(bundles):
        if not immune and not hidden:
            return
        from combat.canonical import canonical_sha256
        for b in bundles:
            for a in b["action_catalog"]:
                if a["display_name"].startswith("Blazing Armor"):
                    if immune and b["actor_id"] == FOE:
                        a["parameters"]["typed"]["effects"].append({"type": "immunity", "damage_types": ["fire"],
                            "applies_to": "self", "duration": "one_minute"})
                    if hidden and b["actor_id"] == SECOND:
                        a["parameters"]["typed"]["effects"].append({"type": "condition", "condition": "invisible",
                            "applies_to": "self", "duration": "one_minute"})
            b.pop("bundle_sha256", None)
            b["bundle_sha256"] = canonical_sha256(b)
    combat, table, mid, send, commit = fixture(tmp_path, talents, foe_talents=[WARD], second_talents=[WARD],
                                             owner_dc=dc, bundle_transform=prepare, seed="A2FIRE-CHOICES")
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        who = table.state(mid)["menu"]["actor_id"]
        ward(table, mid, commit, who)
    return combat, table, mid, send, commit


@pytest.mark.parametrize("chosen", [FOE, SECOND])
@pytest.mark.parametrize("dc", [50, -20])
def test_lance_bypasses_only_chosen_creature_on_failed_or_successful_save(tmp_path, chosen, dc):
    combat, table, mid, send, commit = resistant_fixture(tmp_path, [LANCE], dc=dc)
    prompts = []
    def answer(prompt, choice, ids):
        if prompt["context"]["reaction_source_id"] == "choice:activation_resistance.target":
            prompts.append(choice)
            return [chosen]
        return ids[:1]
    _run(table, mid, _candidate(combat, table, mid, "Incinerating Lance", SECOND), answer)
    engine = cold(combat, mid, tmp_path)
    assert len(prompts) == 1
    assert {o["id"] for o in prompts[0]["options"]} == {OWNER, FOE, SECOND}
    packets = {who: damage(engine, who)[-1] for who in (FOE, SECOND)}
    other = SECOND if chosen == FOE else FOE
    assert packets[chosen]["reduced_to"] > packets[other]["reduced_to"]
    assert packets[other]["reduced_to"] == packets[chosen]["reduced_to"] // 2
    # A later ordinary Ignite receives no bypass from the expired activation.
    commit(table.state(mid)["menu"]["end_turn"])
    while table.state(mid)["menu"]["actor_id"] != OWNER:
        who = table.state(mid)["menu"]["actor_id"]
        ward(table, mid, commit, who)
    commit(candidate(table, mid, "Ignite", chosen))
    engine = cold(combat, mid, tmp_path)
    assert damage(engine, chosen)[-1]["reduced_to"] == damage(engine, chosen)[-1]["rolled_or_pending_damage"] // 2


def test_white_hot_focus_advantage_only_one_roll_and_cold_armed_state(tmp_path):
    combat, table, mid, send, commit = fixture(tmp_path, [FOCUS, "FIRE_TAL_SCORCHING_RAY_ART"], seed="A2FIRE-ADV",
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 7, "y": 6}, SECOND: {"x": 8, "y": 6}})
    commit(candidate(table, mid, "Advantage on one attack roll"))
    assert not damage(combat._load_session(mid).engine, OWNER)
    cold(combat, mid, tmp_path)
    _run(table, mid, next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"] if g["label"] == "Scorching Ray Art" for o in g["options"] if FOE in o.get("target_ids", [])),
         lambda prompt, choice, ids: [FOE] if FOE in ids else ids[:1])
    engine = cold(combat, mid, tmp_path)
    rolls = [e.payload for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER]
    assert rolls[0]["mode"] == "ADVANTAGE"
    assert all(r["mode"] == "NORMAL" for r in rolls[1:])
    assert len(rolls) >= 2
    assert not any("white_hot_focus" in c.condition_id for c in engine.state.actors[OWNER].conditions.values())
    assert damage(engine, OWNER)[-1]["reduced_to"] == 4


@pytest.mark.parametrize("immune", [False, True])
def test_focus_resistance_choice_applies_to_one_target_and_keeps_immunity(tmp_path, immune):
    combat, table, mid, send, commit = resistant_fixture(tmp_path, [FOCUS, "FIRE_TAL_FIREBALL_ART"], immune=immune)
    commit(candidate(table, mid, "ignore one target's Resistance"))
    assert not damage(combat._load_session(mid).engine, OWNER)
    cold(combat, mid, tmp_path)
    _run(table, mid, _candidate(combat, table, mid, "Fireball", FOE),
         lambda prompt, choice, ids: [FOE] if FOE in ids else ids[:1])
    engine = cold(combat, mid, tmp_path)
    first, second = damage(engine, FOE)[-1], damage(engine, SECOND)[-1]
    if immune:
        assert first["reduced_to"] == 0
    else:
        assert second["reduced_to"] == first["reduced_to"] // 2
    assert damage(engine, OWNER)[-1]["reduced_to"] == 4
    assert not any("white_hot_focus" in c.condition_id for c in engine.state.actors[OWNER].conditions.values())


@pytest.mark.parametrize("benefit", ["Advantage on one attack roll", "ignore one target's Resistance",
                                      "saving throw against your next Fire talent", "one Fire damage roll"])
def test_unused_focus_expires_without_backlash(tmp_path, benefit):
    combat, table, mid, send, commit = fixture(tmp_path, [FOCUS])
    commit(candidate(table, mid, benefit))
    cold(combat, mid, tmp_path)
    commit(table.state(mid)["menu"]["end_turn"])
    engine = cold(combat, mid, tmp_path)
    assert not damage(engine, OWNER)
    assert not any("white_hot_focus" in c.condition_id for c in engine.state.actors[OWNER].conditions.values())


def test_countered_fire_talent_spends_new_focus_and_settles_backlash_once(tmp_path):
    def ask_counter(bundles):
        from combat.canonical import canonical_sha256
        for b in bundles:
            if b["actor_id"] == FOE:
                for row in b["typed_reactions"]:
                    if row.get("feature_id") == "TAL_QIWEAVING_COUNTERWEAVE":
                        row["ask"] = True
                b.pop("bundle_sha256", None)
                b["bundle_sha256"] = canonical_sha256(b)
    combat, table, mid, send, commit = fixture(tmp_path, [FOCUS, "FIRE_TAL_FIREBALL_ART"],
        foe_talents=["TAL_QIWEAVING_COUNTERWEAVE"], seed="A2FIRE-COUNTER", bundle_transform=ask_counter)
    # Manual defender declines to counter the Focus itself.
    commit(candidate(table, mid, "ignore one target's Resistance"))
    cold(combat, mid, tmp_path)
    cid = _candidate(combat, table, mid, "Fireball", FOE)
    answers = []
    for _ in range(20):
        result = send(cid, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        reply = {**prompt["context"], "selection": "DECLINE"}
        if "COUNTERWEAVE" in prompt["context"]["reaction_source_id"].upper():
            reply["selection"] = "USE"
        if prompt.get("choice"):
            ids = [o["id"] for o in prompt["choice"]["options"]]
            reply.update(selection="USE", option_ids=[FOE] if FOE in ids else ids[:1])
        answers.append(reply)
    else:
        raise AssertionError("too many pauses")
    engine = cold(combat, mid, tmp_path)
    assert any(e.event_type == "RESOURCE_SPENT" and e.actor_id == FOE and
               e.payload.get("resource_id") == "resource:core.martial_focus" for e in engine.events)
    assert not damage(engine, FOE), "Counterweave stopped the area damage"
    assert [p["reduced_to"] for p in damage(engine, OWNER)] == [4]
    assert not any("white_hot_focus" in c.condition_id for c in engine.state.actors[OWNER].conditions.values())


def test_automatic_owner_uses_focus_advantage_without_a_player_pause(tmp_path):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid, send, commit = fixture(tmp_path, [FOCUS], seed="A2FIRE-AI",
        positions={OWNER: {"x": 3, "y": 6}, FOE: {"x": 7, "y": 6}, SECOND: {"x": 8, "y": 6}})
    commit(candidate(table, mid, "Advantage on one attack roll"))
    cold(combat, mid, tmp_path)
    real = combat.controller
    class Fixed:
        def choose_primary_action(self, context):
            chosen = next(row for row in context.legal_candidates if row.display_name.startswith("Ignite")
                          and FOE in row.target_ids and "Overheat" not in row.display_name)
            return ManualControllerAdapter(lambda _context: (chosen.candidate_id, ())).choose_primary_action(context)
        def __getattr__(self, name):
            return getattr(real, name)
    combat.controller = Fixed()
    combat.set_controller_mode(mid, actor_id=OWNER, controller_mode="LOCAL_AUTO")
    assert table.auto_step(mid, 0, [])["status"] == "COMMITTED"
    engine = cold(combat, mid, tmp_path)
    rolls = [e.payload for e in engine.events if e.event_type == "ATTACK_ROLLED" and e.actor_id == OWNER]
    assert rolls[-1]["mode"] == "ADVANTAGE"
    assert damage(engine, OWNER)[-1]["reduced_to"] == 4


@pytest.mark.parametrize("focus", [False, True])
def test_bypass_picker_excludes_unperceived_area_occupants(tmp_path, focus):
    from combat.target_knowledge import knowledge
    talents = [FOCUS, "FIRE_TAL_FIREBALL_ART"] if focus else [LANCE]
    combat, table, mid, send, commit = resistant_fixture(tmp_path, talents, hidden=True)
    engine = combat._load_session(mid).engine
    assert knowledge(engine, engine.state.actors[OWNER], engine.state.actors[SECOND]).mode != "DIRECT"
    if focus:
        commit(candidate(table, mid, "ignore one target's Resistance"))
    options = []
    def choose(prompt, choice, ids):
        if prompt["context"]["reaction_source_id"] in ("choice:activation_resistance.target", "choice:fire.white_hot_focus_target"):
            options.append(ids)
            return [FOE]
        return ids[:1]
    _run(table, mid, _candidate(combat, table, mid, "Fireball" if focus else "Incinerating Lance", FOE), choose)
    engine = cold(combat, mid, tmp_path)
    assert len(options) == 1 and SECOND not in options[0]
    assert damage(engine, SECOND)[-1]["reduced_to"] > 0, "The actual area still affects its concealed occupants"
