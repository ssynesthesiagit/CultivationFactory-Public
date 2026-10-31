"""N3: one read-only log builder for recorded outcomes and owner-roster names."""
import copy
import json
import re
import subprocess
import zipfile
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.history_feed import format_history_feed
from combat.history_text import expiry_text, history_name
from combat.tabletop_service import TabletopService


def feed(events, names=None):
    return format_history_feed(events, [], pre_state=None, post_state={},
                               actor_names={"a": "Mira", "b": "Ren"}, definition_names=names or {})


def event(kind, payload, source="tianxia.path.body_refining.feature.stamina_guard", targets=None):
    return {"sequence": 1, "event_type": kind, "actor_id": "a", "target_ids": targets or [],
            "source_definition_id": source, "payload": payload}


def test_recorded_changes_costs_targets_and_expiry_without_mutating_events():
    events = [
        event("RESOURCE_SPENT", {"resource_id": "resource:core.stamina", "amount": 4, "remaining": 6}),
        event("REACTION_RESOLVED", {"reduction": 29, "spend": 4, "pending_before": 40, "pending_after": 11}, targets=["a"]),
        event("MODIFIER_APPLIED", {"target_field": "speed_ft", "operation": "ADD", "value": -10,
                                  "expires_on": "START_OF_TURN_AT:b:2"}, "TAL_METAL_HEAVEN_PIERCING_NAIL", ["b"]),
        event("CONDITION_APPLIED", {"condition_id": "condition:core.prone", "expires_on": "STAND_UP"}, targets=["b"]),
        event("RESOURCE_SPENT", {"resource_id": "resource:uses.action:typed.7b7a5816da.TAL_SCOUNDREL_HIDDEN_TOOL_CACHE",
                                 "amount": 1, "remaining": 0}, "action:typed.7b7a5816da.TAL_SCOUNDREL_HIDDEN_TOOL_CACHE"),
    ]
    before = copy.deepcopy(events)
    text = [r["summary"] for r in feed(events)]
    assert "Damage reduced by 29; spent 4 Stamina" in text[1]
    assert text[2] == "Ren: Speed -10 feet from Heaven-Piercing Nail; until Ren's turn 2 starts."
    # LOG1 (eb92fbbdc, round22 merge cac068a1) intentionally names the
    # condition's source. Keep actor, target, condition and expiry exact.
    assert text[3] == "Mira applied Prone to Ren (Stamina Guard); until standing up."
    assert text[4] == "Mira used Hidden Tool Cache; 0 uses remain in this fight."
    assert events == before
    # A reduction roll can exceed the incoming damage. Show the actual change.
    events[1]["payload"].update(pending_before=10, pending_after=0)
    assert "Damage reduced by 10" in feed(events)[1]["summary"]


def test_zone_triggers_preparations_and_choice_plumbing():
    events = [
        event("PASSIVE_TRIGGERED", {"zone_id": "zone:typed.a.123", "moment": "start", "trigger": "World of Pestilence"}, targets=["b"]),
        event("CONDITION_APPLIED", {"condition_id": "condition:typed.wall_plan", "gate3_condition_after": {
            "data": {"points": [[3, 6]], "label": "Its next wall runs through (3,6)"}}}),
        event("MODIFIER_APPLIED", {"target_field": "typed_watch", "operation": "ADD", "value": "private:123"}),
        event("CHOICE_RESOLVED", {"choice_id": "choice:hash"}),
        event("REACTION_WINDOW_OPENED", {}),
    ]
    rows = feed(events)
    assert len(rows) == 2
    assert rows[0]["summary"] == "Ren starts its turn in Mira's World of Pestilence; the area's effects resolve below."
    assert "next wall runs through (3,6)" in rows[1]["summary"]
    assert all("Typed" not in row["summary"] for row in rows)


def test_modifier_removal_names_the_original_ability_and_suppresses_watchers():
    applied = event("MODIFIER_APPLIED", {"modifier_id": "m", "target_field": "armor_class",
                                        "operation": "ADD", "value": 2, "expires_on": "END_OF_CURRENT_TURN"})
    removed = event("MODIFIER_REMOVED", {"modifier_id": "m"}, "system:turn_expiration")
    assert "effect of Stamina Guard ended for Mira" in feed([applied, removed])[1]["summary"]
    applied["payload"]["target_field"] = "typed_watch"
    assert feed([applied, removed]) == []


@pytest.mark.parametrize("source", ["TAL_FLOWING_RIVER_BEND_THE_BLADE", "TAL_SHIELD_REDIRECTING_SHIELD"])
@pytest.mark.parametrize("hit", [True, False])
def test_passive_redirects_show_the_recorded_attack_target_and_result(source, hit):
    recorded = event("PASSIVE_TRIGGERED", {"trigger": source, "total": 17, "ac": 16, "hit": hit},
                     "passive:" + source, ["b", "a"])
    before = copy.deepcopy(recorded)
    row = feed([recorded])[0]
    assert ("used Bend the Blade:" if source == "TAL_FLOWING_RIVER_BEND_THE_BLADE"
            else "used Redirecting Shield:") in row["summary"]
    assert "Ren's attack now targets Mira; attack total 17 against AC 16" in row["summary"]
    assert row["summary"].endswith("— Hit." if hit else "— Miss.")
    assert "TAL_" not in row["summary"] and "passive:" not in row["summary"]
    assert recorded == before


def test_passive_ac_recheck_and_named_trigger_weapon_are_readable():
    records = [event("PASSIVE_TRIGGERED", {"ac_bonus": 3, "new_ac": 20, "against": "ranged",
                                          "hit_after_recheck": False}, "TAL_SHIELD_REDIRECTING_SHIELD", ["b"]),
               event("PASSIVE_TRIGGERED", {"trigger": "TAL_SCOUNDREL_TWIST_THE_KNIFE", "with": "Dagger"},
                     "passive:TAL_SCOUNDREL_TWIST_THE_KNIFE", ["b"])]
    text = [row["summary"] for row in feed(records)]
    assert "AC +3 against the ranged attack from Ren, now AC 20; the attack misses" in text[0]
    assert text[1] == "Mira triggered Twist The Knife using Dagger against Ren."
    assert feed([event("PASSIVE_TRIGGERED", {})])[0]["detailed_breakdown_recorded"] is False


def test_attack_retargeting_names_the_attack_old_target_and_new_target():
    recorded = event("ATTACK_RETARGETED", {"original_target_id": "a", "attack_source_id": "action:weapon.sword",
                                          "cover_bonus": 2}, "TAL_SCOUNDREL_MISDIRECTED_ATTACK", ["b"])
    row = feed([recorded], {"action:weapon.sword": "Longsword"})[0]
    assert row["summary"] == ("Misdirected Attack redirected Mira's Longsword from Mira to Ren. "
                              "The new target has +2 AC from cover.")
    assert row["raw"] == recorded


def test_real_redirected_attack_feed_preserves_events_and_reducer_replay():
    from combat.gate3_reducer import Gate3EventReducer, enrich_committed_events
    from tests.test_h2_redirect_reactions import (FOE2, ME, _foe_swings, _shielded, _table)

    engine = _shielded()
    _table(engine, choice=FOE2, choice_source="redirecting_shield", uses=("SHIELD_BASE_ACTIVE_DEFENSE",))
    before = engine.state.model_copy(deep=True)
    start = len(engine.events)
    events = _foe_swings(engine)
    raw = [row.model_dump(mode="json") for row in events]
    saved_bytes = json.dumps(raw, sort_keys=True)
    replay_events = enrich_committed_events(engine.events[start:], post_engine=engine)
    reducer = Gate3EventReducer()
    replay = reducer.apply_events(before, replay_events).model_dump(mode="json")
    rows = format_history_feed(raw, [], pre_state=before.model_dump(mode="json"),
                               post_state=engine.state.model_dump(mode="json"),
                               actor_names={key: actor.display_name for key, actor in engine.state.actors.items()},
                               definition_names={})
    redirect = next(row for row in rows if row["event_type"] == "PASSIVE_TRIGGERED"
                    and row["source_definition_id"] == "passive:TAL_SHIELD_REDIRECTING_SHIELD")
    assert "Redirecting Shield" in redirect["summary"] and "attack now targets" in redirect["summary"]
    assert "attack total" in redirect["summary"] and "— Hit." in redirect["summary"]
    assert json.dumps(raw, sort_keys=True) == saved_bytes
    assert [row.model_dump(mode="json") for row in events] == raw
    assert reducer.apply_events(before, replay_events).model_dump(mode="json") == replay
    assert replay["actors"][FOE2]["current_hp"] == engine.state.actors[FOE2].current_hp
    assert replay["actors"][ME]["resources"]["resource:core.martial_focus"] == 0


def test_default_client_log_keeps_resource_costs_and_automation_limits_visible():
    script = Path(__file__).resolve().parents[1] / "static/tabletop/tabletop.js"
    # Execute the shipped rendering function with a small DOM stand-in.
    code = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
// Load the real presentation dependency along with the extracted renderer.
eval(fs.readFileSync(require('path').join(require('path').dirname(process.argv[1]),
  'feed-presentation.js'), 'utf8').replace('export function mapObjectFeed', 'function mapObjectFeed'));
const items = [];
const feed = {appendChild: item => items.push(item)};
const $ = selector => selector === '#ttFeed' ? feed : {checked: false};
const document = {createElement: () => ({dataset: {}, style: {}})};
const feedClass = () => '';
const settleFeed = () => {};
eval(source.match(/const NOISE = .*?;/)[0].replace('const NOISE', 'var NOISE'));
eval(source.slice(source.indexOf('function appendFeed('), source.indexOf('function appendTableLine(')));
appendFeed([{event_type: 'RESOURCE_SPENT', summary: 'Mira spent 4 Stamina; 6 remained.'},
            {event_type: 'GM_RIDER', summary: 'Not automated — consult the GM for moving this object.'},
            {event_type: 'INTENT_ACCEPTED', summary: 'Mira — Stamina Guard.'},
            {event_type: 'TURN_ENDED', summary: 'Turn ended: Mira.'}]);
console.log(JSON.stringify(items.map(item => item.textContent)));
"""
    rendered = json.loads(subprocess.check_output(["node", "-e", code, str(script)], text=True))
    assert rendered == ["Mira spent 4 Stamina; 6 remained.",
                        "Not automated — consult the GM for moving this object.", "Mira — Stamina Guard."]


@pytest.mark.parametrize("token,words", [
    ("START_OF_SOURCE_NEXT_TURN", "Mira's next turn starts"),
    ("END_OF_HOLDER_NEXT_TURN", "Ren's next turn ends"),
    ("END_OF_TURN_AT:b:3", "Ren's turn 3 ends"),
    ("START_OF_SLOT_AT:4:0", "round 4, turn 1 starts"),
    ("CONCENTRATION_END", "concentration ends"),
])
def test_expiry_is_readable(token, words):
    assert words in expiry_text(token, {"b": "Ren"}, "Mira", "Ren")


def test_table_feed_reload_is_read_only_and_replay_hashes_identical(tmp_path):
    from tests.test_tabletop_hunt8 import cast_lava, fight
    from tests.tree_hash_support import _tree_hashes

    combat, table, mid = fight(tmp_path, [], caster_talents=["TAL_MAGMA_LAVA_FLOW"])
    cast_lava(combat, table, mid)
    state = table.state(mid)
    result = table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"],
                       state["menu"]["state_version"], state["last_sequence"], [])
    assert result["status"] == "COMMITTED"
    session = combat._load_session(mid)
    before = _tree_hashes(session.mechanical.store.match_dir)
    replay = session.mechanical.replay()
    assert replay["status"] == "PASS"
    fresh = CombatService(combat.source_root, tmp_path)
    rows = TabletopService(fresh, tmp_path).events(mid, 0)["events"]
    history = fresh.history(mid)
    assert _tree_hashes(session.mechanical.store.match_dir) == before
    assert fresh._load_session(mid).mechanical.replay() == replay
    assert history["canonical_event_log_sha256"] == replay["canonical_event_log_sha256"]
    triggers = [r for r in rows if r["event_type"] == "PASSIVE_TRIGGERED" and r["raw"]["payload"].get("zone_id")]
    assert triggers and all("starts its turn in" in r["summary"] and "Lava Flow" in r["summary"] for r in triggers)
    assert any("spent" in r["summary"] and "Qi" in r["summary"] for r in rows)
    assert all("Typed" not in r["summary"] and "recorded modifier" not in r["summary"] for r in rows)


@pytest.mark.parametrize("kind", ["markers", "temporary_hp"])
def test_producer_outcomes_survive_table_commit_reload(monkeypatch, tmp_path, kind):
    """Test-only prepared action calls real producers, never fabricates events.

    The marker calls match the native attack/save producers' integer schemas;
    halved Speed runs the typed block. The table adds the persisted scope record.
    This fixture tests presentation/persistence, not an ability's activation rules.
    """
    from combat.gate2_runtime_models import ActionDefinition, EconomyKind
    from combat.prepared_actions import SOURCE
    from combat.typed_executor import Context, block_speed
    from tests.tree_hash_support import _tree_hashes
    from tests.test_lock2_persistence import act, table_match
    from tests.test_lock_choices import install

    install(monkeypatch, "prepare_options", lambda *args: [{
        "option_id": "guard", "source_id": "test:guard", "label": "Guard",
        "trigger": "HOLD_POSITION_COMMITTED"}])
    install(monkeypatch, "prepared_trigger", lambda *args: True)

    def resolve(engine, actor, option, trigger, intent):
        source = option["source_id"]
        if kind == "markers":
            action = ActionDefinition(source_definition_id=source, display_name="Guard",
                                      owner_id=actor.entity_id, economy=EconomyKind.ACTION,
                                      resolution_kind="TYPED", target_kind="SELF")
            ctx = Context(engine, actor, action, intent, {}, [actor], target=actor)
            block_speed(ctx, {"halved": True, "applies_to": "self",
                              "expires_on": "START_OF_SOURCE_NEXT_TURN"})
            engine._add_modifier(actor, source, "incoming_attack_mode", "ADVANTAGE", 1,
                                 "NEXT_ATTACK", expires_on="CONSUMED")
            engine._add_modifier(actor, source, "attack_mode", "DISADVANTAGE", 1,
                                 "NEXT_ATTACK", expires_on="END_OF_TARGET_NEXT_TURN_OR_CONSUMED")
        else:
            # Three distinct offers, with the lower offer preserving the first pool.
            for amount in (10, 5, 15):
                engine._grant_temp_hp(actor, amount, source, actor.entity_id)
        return True

    install(monkeypatch, "prepared_action", resolve)
    combat, table, mid = table_match(tmp_path)
    holder = table.state(mid)["menu"]["actor_id"]
    assert act(table, mid, SOURCE)["status"] == "COMMITTED"
    assert act(table, mid, "end")["status"] == "COMMITTED"
    pending = act(table, mid, "system:combat.hold_position")
    assert pending["status"] == "REACTION_REQUIRED"
    state, menu = pending["state"], pending["state"]["menu"]
    answer = {**pending["reaction"]["context"], "selection": "USE"}
    group = next(g for g in menu["actions"]
                 if g["source_definition_id"] == "system:combat.hold_position")
    committed = table.act(mid, group["options"][0]["candidate_id"], menu["decision_id"],
                          menu["state_version"], state["last_sequence"], [answer])
    assert committed["status"] == "COMMITTED"
    session = combat._load_session(mid)
    hashes = _tree_hashes(session.mechanical.store.match_dir)
    replay = session.mechanical.replay()
    assert replay["status"] == "PASS"
    fresh = CombatService(combat.source_root, tmp_path)
    fresh_table = TabletopService(fresh, tmp_path)
    rows = [row for row in fresh_table.events(mid, 0)["events"]
            if row["source_definition_id"] == "test:guard"]
    assert rows == [row for row in table.events(mid, 0)["events"]
                    if row["source_definition_id"] == "test:guard"]
    saved_actor = fresh._load_session(mid).engine.state.actors[holder]
    if kind == "markers":
        modifiers = {row["raw"]["payload"]["target_field"]: row for row in rows
                     if row["event_type"] == "MODIFIER_APPLIED"}
        assert "Speed halved" in modifiers["speed_halved"]["summary"]
        assert "until" in modifiers["speed_halved"]["summary"]
        for field, words, operation in (
                ("incoming_attack_mode", "advantage on the next attack roll against them", "ADVANTAGE"),
                ("attack_mode", "disadvantage on their next attack roll", "DISADVANTAGE")):
            row = modifiers[field]
            payload = row["raw"]["payload"]
            assert payload["operation"] == operation and payload["value"] == 1
            assert payload["gate3_modifier_after"]["applies_to"] == "NEXT_ATTACK"
            assert words in row["summary"]
        assert all("+1" not in row["summary"] and "changes by 1" not in row["summary"]
                   for row in modifiers.values())
        assert {m.target_field for m in saved_actor.modifiers.values()} >= set(modifiers)
    else:
        grants = [row for row in rows if row["event_type"] == "TEMP_HP_GRANTED"]
        assert [row["raw"]["payload"] for row in grants] == [
            {"offered": 10, "before": 0, "after": 10},
            {"offered": 5, "before": 10, "after": 10},
            {"offered": 15, "before": 10, "after": 15}]
        assert "5 temporary HP; it did not replace their existing 10 temporary HP" in grants[1]["summary"]
        assert "15 temporary HP; their pool changed from 10 to 15 temporary HP" in grants[2]["summary"]
        assert all("temporary HP does not stack" in row["summary"] for row in grants)
        assert all("received" not in row["summary"] for row in grants)
        assert saved_actor.temporary_hp == 15
    assert _tree_hashes(session.mechanical.store.match_dir) == hashes
    assert fresh._load_session(mid).mechanical.replay() == replay


def test_owner_roster_log_name_coverage():
    """Read portable sheets in place; retain no owner data in the repository.

    Optional outside the owner checkout; the lane report records the actual count.
    All compiled actions/resources go through the same builder as the table feed.
    """
    root = Path("/var/tmp/auto-audit/astra/lock3-inputs/portable_characters")
    if not root.exists():
        pytest.skip("owner read-only portable roster is not available")
    archives = sorted(root.glob("*/current.zip"))
    assert archives
    count = 0
    for archive in archives:
        with zipfile.ZipFile(archive) as zipped:
            sheet = json.loads(zipped.read("Tianxia_Owner_Character_Sheet_v1.json"))
        bundle = compile_character(sheet, actor_id="actor:roster")
        names = {row["source_definition_id"]: row["display_name"] for row in bundle["action_catalog"]}
        for row in bundle["typed_reactions"]:
            if row.get("name"):
                names[row["feature_id"]] = row["name"]
        ids = [*names, *(r["resource_id"] for r in bundle["actor_template"]["resources"])]
        for stable_id in ids:
            label = history_name(stable_id, names)
            assert not re.search(r"\bTyped\b|resource:|action:|core[._]|\b[a-f0-9]{10,}\b|#opt|\bTAL_", label), (archive.parent.name, stable_id, label)
            triggered = feed([event("PASSIVE_TRIGGERED", {"trigger": stable_id}, stable_id, ["b"])], names)[0]["summary"]
            assert not re.search(r"\bTyped\b|resource:|action:|core[._]|\b[a-f0-9]{10,}\b|#opt|\bTAL_", triggered), (archive.parent.name, stable_id, triggered)
            count += 1
    print(f"Owner roster: {len(archives)} characters, {count} action/reaction/resource labels")
