"""SOL150: exercise the table's committed feed, saved state and paused decisions.

Test-only effects drive isolated lifecycle checkpoints through real table actions;
they do not replace engine methods or access any live fight.
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

from combat import ext
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_tabletop_pending_action_resume import reopen, resume

ME, FOE, CASTER = (f"actor:factory.sol150-{name}" for name in ("tabik", "wen", "lingfeng"))


def fight(path, mids=(), *, actions=(), third=False, action_owner=ME):
    docs = [sheet(list(mids), cl=12, primary="Stamina"), sheet([], cl=12)]
    ids = [ME, FOE]
    if third:
        docs.append(sheet(["DISEASE_BASE_RAISE_THE_QUARANTINE_VEIL"], cl=12))
        ids.append(CASTER)
    bundles = []
    for aid, doc, name in zip(ids, docs, ("Tabik", "Wen Xue", "Lingfeng")):
        doc["identity"]["display_name"] = name
        bundles.append(compile_character(doc, actor_id=aid, reaction_plan={"ask": True}))
    for label, effects, duration in actions:
        action = ActionDefinition(source_definition_id=f"action:typed.sol150.{label.replace(' ', '_')}",
            display_name=label, owner_id=action_owner, economy="ACTION", resolution_kind="TYPED", target_kind="SELF",
            concentration=bool(duration.get("concentration")),
            parameters={"typed": {"effects": effects, "duration": duration, "riders": [], "numbers": {"cl": 12}}})
        bundle = bundles[ids.index(action_owner)]
        bundle["action_catalog"].append(action.model_dump(mode="json"))
        bundle["actor_template"]["action_ids"].append(action.source_definition_id)
    combat = CombatService(ROOT, path)
    table = TabletopService(combat, path)
    bundles = [combat._with_prefight(bundle, {aid: [] for aid in ids}) for bundle in bundles]
    teams = {aid: "team:factory" if aid == ME else "team:opponents" for aid in ids}
    positions = {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, CASTER: {"x": 2, "y": 7}}
    mid = combat._finish_factory_match(bundles, ids, teams, {aid: positions[aid] for aid in ids},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], ids[1:],
        control_modes={aid: "MANUAL" for aid in ids}, match_seed="SOL150", display_name="Text regression",
        maximum_rounds=10)["match_id"]
    return combat, table, mid


def act(table, mid, label=None, *, answers=(), at=None):
    state = table.state(mid)
    menu = state["menu"]
    if label is None:
        cid = menu["end_turn"]
    else:
        groups = [g for g in menu["actions"] if g["label"] == label]
        assert groups, (label, [g["label"] for g in menu["actions"]])
        options = groups[0]["options"]
        matching = [o for o in options if at is None or (o.get("destination") is not None
                    and all(o["destination"].get(key, 0) == value for key, value in at.items()))]
        assert matching, (label, at, [o.get("destination") for o in options])
        cid = matching[0]["candidate_id"]
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], list(answers))


def my_turn(table, mid, actor_id=ME):
    for _ in range(8):
        if table.state(mid)["menu"]["actor_id"] == actor_id:
            return
        assert act(table, mid)["status"] == "COMMITTED"
    pytest.fail("player's turn did not arrive")


def feed(table, mid):
    return table.events(mid, 0)["events"]


@pytest.mark.parametrize("kind,word", [("healing", "healing"), ("temporary_hp", "temporary HP")])
def test_benefit_roll_is_not_damage_in_committed_table_feed(tmp_path, kind, word):
    effect_kind = "temp_hp" if kind == "temporary_hp" else kind
    combat, table, mid = fight(tmp_path, actions=[("Restoration", [{"type": effect_kind,
        "applies_to": "self", "dice": {"count": 1, "sides": 8}}], {"kind": "instant"})])
    my_turn(table, mid)
    assert act(table, mid, "Restoration")["status"] == "COMMITTED"
    table = reopen(table, tmp_path)
    lines = [e["summary"] for e in feed(table, mid) if e["event_type"] == "DAMAGE_ROLLED"]
    assert lines and all(word in line and "damage" not in line.lower() for line in lines)


def test_meld_replacement_and_concentration_end_are_committed_and_reload(tmp_path, monkeypatch):
    ext.effects()
    def end(ctx, effect):
        ctx.engine._end_concentration(ctx.actor, "TEST_END")
    monkeypatch.setitem(ext._EFFECTS, "sol150_end", end)
    mids = ["TAL_DARK_MELD", "TAL_DARK_PERSISTENT_MELD", "TAL_DARK_DARKVISION", "TAL_DARK_DARK_SLAUGHTER", "TAL_DARK_CLEARSIGHT"]
    _combat, table, mid = fight(tmp_path, mids, actions=[("End test concentration", [{"type": "sol150_end"}], {"kind": "instant"})])
    my_turn(table, mid)
    assert act(table, mid, "Meld: Darkvision")["status"] == "COMMITTED"
    assert any(c["condition_id"] == "condition:typed.meld_set" for c in table.state(mid)["presentation"]["actors"][0]["conditions"])
    act(table, mid); my_turn(table, mid)
    assert act(table, mid, "Meld: Darkvision (Persistent)")["status"] == "COMMITTED"
    assert any("was replaced by" in e["summary"] and "Meld" in e["summary"] for e in feed(table, mid))
    act(table, mid); my_turn(table, mid)
    assert act(table, mid, "Meld: Clearsight")["status"] == "COMMITTED"
    act(table, mid); my_turn(table, mid)
    assert act(table, mid, "End test concentration")["status"] == "COMMITTED"
    table = reopen(table, tmp_path)
    actor = table.combat._load_session(mid).engine.state.actors[ME]
    melds = [c for c in actor.conditions.values() if c.condition_id == "condition:typed.meld_set"]
    assert len(melds) == 1 and melds[0].data["talent"] == "TAL_DARK_DARKVISION"
    assert not melds[0].data["concentration"]


def test_zone_save_prompt_names_owner_and_source_then_clears_after_other_client_answers(tmp_path, monkeypatch):
    ext.effects()
    def tick(ctx, effect):
        source = next(a.source_definition_id for a in ctx.engine.action_catalog.values()
                      if a.owner_id == CASTER and "DISEASE_BASE_RAISE_THE_QUARANTINE_VEIL" in a.source_definition_id)
        ctx.engine._roll_save(ctx.engine.state.actors[ME], "CON", 99, source,
                             roll_context={"source_actor_id": CASTER, "named": ["damage:poison"]})
    monkeypatch.setitem(ext._EFFECTS, "sol150_tick", tick)
    _combat, table, mid = fight(tmp_path, ["tianxia.path.body_refining.feature.indomitable_body"],
        actions=[("End Wen Xue's test turn", [{"type": "sol150_tick"}], {"kind": "instant"})], third=True, action_owner=FOE)
    my_turn(table, mid, FOE)
    response = act(table, mid, "End Wen Xue's test turn")
    assert response["status"] == "REACTION_REQUIRED"
    trigger = response["reaction"]["trigger"]
    assert "Tabik" in trigger and "Lingfeng" in trigger and "Raise the Quarantine Veil" in trigger
    assert "Wen Xue" not in trigger
    pending = table.state(mid)["pending_action"]
    other = reopen(table, tmp_path)
    answer = {**pending["reaction"]["context"], "selection": "DECLINE"}
    assert resume(other, mid, pending, [answer])["status"] == "COMMITTED"
    assert reopen(table, tmp_path).state(mid)["pending_action"] is None


def test_legacy_concentration_meld_marker_is_removed_after_table_reload(tmp_path, monkeypatch):
    ext.effects()
    def legacy(ctx, effect):
        ctx.engine._apply_condition(ctx.actor, "condition:typed.meld_set", ctx.source, ME,
            expires_on="UNTIL_REMOVED", data={"concentration": True, "source": ctx.source,
                "talent": "TAL_DARK_DARKVISION", "label": "Meld: Darkvision (Concentration)"})
    def end(ctx, effect):
        ctx.engine._end_concentration(ctx.actor, "TEST_END")
    monkeypatch.setitem(ext._EFFECTS, "sol150_legacy_meld", legacy)
    monkeypatch.setitem(ext._EFFECTS, "sol150_end", end)
    _combat, table, mid = fight(tmp_path, ["TAL_DARK_DARKVISION"], actions=[
        ("Legacy Meld", [{"type": "sol150_legacy_meld"}], {"kind": "hours", "amount": 1, "concentration": True}),
        ("End legacy concentration", [{"type": "sol150_end"}], {"kind": "instant"})])
    my_turn(table, mid)
    assert act(table, mid, "Legacy Meld")["status"] == "COMMITTED"
    table = reopen(table, tmp_path)
    actor = table.combat._load_session(mid).engine.state.actors[ME]
    assert any(c.condition_id == "condition:typed.meld_set" and c.expires_on == "UNTIL_REMOVED" for c in actor.conditions.values())
    act(table, mid); my_turn(table, mid)
    assert act(table, mid, "End legacy concentration")["status"] == "COMMITTED"
    table = reopen(table, tmp_path)
    actor = table.combat._load_session(mid).engine.state.actors[ME]
    assert not any(c.condition_id == "condition:typed.meld_set" for c in actor.conditions.values())


def test_death_hover_tally_and_log_survive_table_reload(tmp_path, monkeypatch):
    from combat.ext import life_state
    ext.effects()
    def dying(ctx, effect):
        actor = ctx.actor
        ctx.engine._commit_damage(actor, actor.maximum_hp, "NECROTIC", ctx.source, actor.entity_id, ctx.intent, reaction_depth=0)
        # Drive the recorded tally to the playtest's exact display case.
        actor.turn_flags["life_round_record"] = {"ok": 1, "bad": 2}
    monkeypatch.setitem(ext._EFFECTS, "sol150_dying", dying)
    monkeypatch.setattr(life_state, "DEATH_SAVES_FOR_ALL", True)
    _combat, table, mid = fight(tmp_path, actions=[
        ("Become dying", [{"type": "sol150_dying"}], {"kind": "instant"})])
    my_turn(table, mid)
    assert act(table, mid, "Become dying")["status"] == "COMMITTED"
    table = reopen(table, tmp_path)
    row = next(r for r in table.state(mid)["presentation"]["actors"] if r["entity_id"] == ME)
    assert row["life_status_text"] == "Dying — 1 success, 2 failures"
    # The next death save uses the normal turn-start lifecycle inside a table commit.
    def fail(engine, roll, intent):
        if roll.actor_id == ME and roll.reason == "SAVE:death":
            return {"source_id": "test:death", "operation": "replace", "natural_result": 1}
    monkeypatch.setitem(ext._HOOKS, "d20_result", [*ext._HOOKS.get("d20_result", []), fail])
    for _ in range(5):
        if any(r.get("life_status_text") == "Dead" for r in table.state(mid)["presentation"]["actors"]):
            break
        assert act(table, mid)["status"] == "COMMITTED"
    table = reopen(table, tmp_path)
    row = next(r for r in table.state(mid)["presentation"]["actors"] if r["entity_id"] == ME)
    assert row["life_status_text"] == "Dead"
    defeated = [e["summary"] for e in feed(table, mid) if e["event_type"] == "ENTITY_DEFEATED"]
    assert "Tabik died." in defeated and not any("Nonlethal" in line for line in defeated)


def test_fireball_logs_only_manual_leftovers_without_unselected_overheat(tmp_path):
    _combat, table, mid = fight(tmp_path, ["FIRE_TAL_FIREBALL_ART"])
    my_turn(table, mid)
    assert act(table, mid, "Fireball Art", at={"x": 4, "y": 6, "z": 0})["status"] == "COMMITTED"
    rows = feed(reopen(table, tmp_path), mid)
    lines = [r["summary"] for r in rows if r["event_type"] == "GM_RIDER" and "Fireball Art" in r["summary"]]
    assert len(lines) == 1 and "Unattended flammable objects ignite" in lines[0]
    assert "Overheat" not in lines[0] and "Increase damage" not in lines[0] and "radius sphere" not in lines[0]
    assert any(r["event_type"] == "DAMAGE_COMMITTED" for r in rows)


def test_old_feed_area_headers_and_unselected_augments_are_not_manual_effects():
    from combat.history_feed import format_history_feed
    source = "action:typed.sol150.old"
    events = [{"sequence": 1, "event_type": "GM_RIDER", "actor_id": ME, "target_ids": [FOE],
        "source_definition_id": source, "payload": {"rider": "20-foot-radius sphere"}},
        {"sequence": 2, "event_type": "GM_RIDER", "actor_id": ME, "target_ids": [FOE],
        "source_definition_id": source, "payload": {"rider": "Unattended flammable objects ignite. Augment - 2 CP: Increase damage by 2d6."}}]
    rows = format_history_feed(events, [], pre_state=None, post_state={},
        actor_names={ME: "Tabik", FOE: "Wen Xue"}, definition_names={source: "Fireball Art"},
        action_profiles={source: {"area": {"shape": "sphere", "size_ft": 20}, "augments": []}})
    assert len(rows) == 1
    assert "Unattended flammable objects ignite" in rows[0]["summary"]
    assert "Augment" not in rows[0]["summary"] and "Increase damage" not in rows[0]["summary"]


def test_legacy_fireball_card_hides_applied_effects_but_preserves_reaction_remainders():
    from combat.history_feed import format_history_feed
    source = "action:typed.sol150.FIRE_TAL_FIREBALL_ART"
    copied = ("A compressed fire pearl erupts. / Unattended flammable objects ignite. / "
        "Cultivation Level Damage: 5-10: 6d6; 11-16: 8d6; 17-20: 10d6. / "
        "Augment - 2 CP: Increase damage by 2d6. After the attack resolves, take Fire damage equal to twice your Proficiency Bonus.")
    reaction = "Empty Bank Evasion: Tabik takes no damage; it may move 10 feet without provoking Opportunity Attacks from the creature (GM)."
    events = [{"sequence": i, "event_type": "GM_RIDER", "actor_id": FOE, "target_ids": [ME],
               "source_definition_id": source, "payload": {"rider": text}}
              for i, text in enumerate(("20-foot-radius sphere", copied, reaction), 1)]
    rows = format_history_feed(events, [], pre_state=None, post_state={},
        actor_names={ME: "Tabik", FOE: "Wen Xue"}, definition_names={source: "Fireball Art"})
    assert len(rows) == 2 and "Unattended flammable objects ignite" in rows[0]["summary"]
    assert all(word not in rows[0]["summary"] for word in ("Augment", "Increase damage", "pearl", "6d6", "radius"))
    assert "may move 10 feet" in rows[1]["summary"]
    assert "takes no damage" not in rows[1]["summary"]
    assert events[1]["payload"]["rider"] == copied


def test_healing_hymn_end_turn_roll_reads_as_healing(tmp_path):
    _combat, table, mid = fight(tmp_path, ["tianxia.talent.music.healing_hymn"])
    my_turn(table, mid)
    assert act(table, mid, "Healing Hymn")["status"] == "COMMITTED"
    result = act(table, mid)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    choice = next(o["id"] for o in prompt["choice"]["options"] if "Heal Tabik" in o["label"])
    pending = table.state(mid)["pending_action"]
    before = table.state(mid)["last_sequence"]
    answer = {**prompt["context"], "selection": "USE", "option_ids": [choice]}
    assert resume(table, mid, pending, [answer])["status"] == "COMMITTED"
    lines = [e["summary"] for e in feed(reopen(table, tmp_path), mid) if e["event_type"] == "DAMAGE_ROLLED"]
    assert any("Healing Hymn healing" in line for line in lines)
    assert all("damage" not in line.lower() for line in lines)
    # Replay client A's wait against client B's actual saved commit and feed.
    journal = tmp_path / "remote-journal.json"
    journal.write_text(json.dumps({"prompt": prompt, "after": before,
        "state": table.state(mid), "events": table.events(mid, before)}))
    result = subprocess.run(["node", str(ROOT / "tests/sol150_table_text.test.mjs")],
        env={**os.environ, "SOL150_SERVICE_JOURNAL": str(journal)}, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_client_prompt_and_hover_regressions_without_a_browser():
    result = subprocess.run(["node", "--test", str(ROOT / "tests/sol150_table_text.test.mjs")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("automatic", [False, True])
def test_saved_replacement_answer_consumes_only_new_service_events(tmp_path, automatic):
    from tests.test_hunt5_player_choices import fixture, FOE
    combat, table, mid, cid, send = fixture(tmp_path, "TAL_FENCING_FOOTWORK")
    if automatic:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    result = table.auto_step(mid, 0) if automatic else send(cid)
    assert result["status"] == "REACTION_REQUIRED"
    table = reopen(table, tmp_path)
    state = table.state(mid)
    pending = state["pending_action"]
    assert pending["request"]["after"] == 0 < state["last_sequence"]
    catchup = table.events(mid, 0)
    assert catchup["events"]
    prompt = pending["reaction"]
    answer = {**prompt["context"], "selection": "DECLINE"}
    # The service permits changing only the feed cursor, preserving the saved
    # action binding. Retain its actual overlapping and consumed windows.
    request = {**pending["request"], "after": state["last_sequence"]}
    committed = getattr(table, pending["method"])(mid, **request, reactions=[answer])
    assert committed["status"] == "COMMITTED"
    table = reopen(table, tmp_path)
    new = table.events(mid, state["last_sequence"])
    overlap = table.events(mid, 0)
    assert new["events"] and overlap["events"] == catchup["events"] + new["events"]
    session = table.combat._load_session(mid)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"
    journal = tmp_path / "replacement-journal.json"
    journal.write_text(json.dumps({"after": 0, "state": state, "pending": pending,
        "events": catchup, "committed": overlap,
        "responses": {"0": overlap, str(state["last_sequence"]): new}}))
    result = subprocess.run(["node", str(ROOT / "tests/sol150_table_text.test.mjs")],
        env={**os.environ, "SOL150_REPLACEMENT_JOURNAL": str(journal)}, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_departing_lingering_soul_still_logs_death_after_its_marker_is_removed():
    from combat.history_feed import format_history_feed
    events = [{"event_type": kind, "actor_id": ME, "target_ids": [ME], "source_definition_id": "system:death_save",
               "payload": {"condition_id": marker}}
              for kind, marker in (("CONDITION_APPLIED", "condition:typed.soul_lingering"),
                                   ("CONDITION_APPLIED", "condition:typed.death_finalized"),
                                   ("CONDITION_REMOVED", "condition:typed.soul_lingering"),
                                   ("ENTITY_DEFEATED", ""))]
    rows = format_history_feed(events, [], pre_state=None, post_state={}, actor_names={ME: "Tabik"}, definition_names={})
    assert rows[-1]["summary"] == "Tabik died."
