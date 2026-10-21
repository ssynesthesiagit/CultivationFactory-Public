"""Decision explanations at table boundaries; optional read-only owner-roster coverage."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from combat.decision_text import build_decision_text
from combat.factory_compiler import compile_character
from combat.tabletop_service import _rules_texts
from tests.test_lock2_persistence import act
from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, ALLY, RIGHT, HOLD


@pytest.mark.parametrize("kind", ["damage", "condition", "zero", "reaction"])
def test_table_prompt_explains_actual_pending_trigger_and_rules(monkeypatch, tmp_path, kind):
    talents = {"damage": ["TAL_DEATH_BONE_WARD"],
               "condition": ["TAL_THREAD_STITCH_THE_FALLING_BODY"],
               "zero": ["TAL_DEATH_HARVEST_THE_FALLEN"],
               "reaction": ["TAL_LIGHTNING_CHARGED_COUNTERMEASURE"]}[kind]
    combat, table, mid = table_fight(tmp_path, talents, ask=True, ally_talents=[])

    def trigger(engine):
        from combat import typed_reactions
        me, ally, foe = (engine.state.actors[key] for key in (LEFT, ALLY, RIGHT))
        if kind == "damage":
            typed_reactions.on_damage(engine, me, 24, 0, "system:combat.hold_position", RIGHT)
        elif kind == "condition":
            typed_reactions.offer_condition_gained(engine, ally, foe, "prone")
        elif kind == "zero":
            typed_reactions.on_creature_event(engine, foe, "any_drop_to_zero")
        else:
            typed_reactions._open(engine, {"feature_id": "test:reaction", "name": "Test Guard"}, foe, (LEFT,), "TEST")

    on_hold(monkeypatch, trigger)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = act(table, mid, HOLD)
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["summary"] and prompt["rules"] and prompt["cost"]
    assert "CP" not in prompt["cost"]
    assert "actor:" not in prompt["trigger"]
    assert prompt["moment"] == prompt["trigger"]
    expected = {"damage": "Left is about to take 24 damage", "condition": "Ally would become prone",
                "zero": "Right dropped to 0 HP", "reaction": "Right used Test Guard"}[kind]
    assert expected in prompt["trigger"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert act(table, mid, HOLD)["reaction"] == prompt
    # A choose-one reaction exposes each mode at this checkpoint. Declining
    # just the first must leave the remaining modes available (owner addendum).
    answers = [{**row["context"], "selection": "DECLINE"}
               for row in prompt.get("alternatives") or [prompt]]
    state = table.state(mid)
    menu = state["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == HOLD)
    assert table.act(mid, cid, menu["decision_id"], menu["state_version"], state["last_sequence"], answers)["status"] == "COMMITTED"
    from combat.gate5_service import CombatService
    assert CombatService(combat.source_root, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("court", ["inactive", "active", "without_two_answers"])
@pytest.mark.parametrize("intercept", [False, True])
def test_counterstrike_preparation_options_explain_effect_expiry_and_cost(tmp_path, court, intercept):
    from tests.r10_fixup_support import cast_sender, commit
    kit = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.gun", "name": "Gun (Staff)", "quantity": 1}]}}
    talents = ["RETRIBUTION_BASE_COUNTERSTRIKE", "TAL_RETRIBUTION_COURT_OF_THE_AWAITING_BLADE"]
    if court != "without_two_answers":
        talents.append("TAL_RETRIBUTION_TWO_ANSWERS_WITHIN_ONE_BREATH")
    if intercept:
        talents.append("TAL_RETRIBUTION_INTERCEPTING_STRIKE")
    combat, table, mid = table_fight(tmp_path, talents, cl=17, kit=kit, ask=True, ally_talents=[])
    if court != "inactive":
        commit(cast_sender(combat, table, mid, "Court of the Awaiting Blade"))
    expected_limit = "two Counterstrikes per round" if court == "active" else "one Counterstrike per round"
    send = cast_sender(combat, table, mid, "Counterstrike")
    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert "Action" in prompt["cost"] and "Reaction" in prompt["summary"]
    assert "start of your next turn" in prompt["limits"]
    assert expected_limit in prompt["limits"]
    if court == "active":
        assert "same creature's turn" in prompt["limits"]
    if intercept:
        assert "instead of attacking its attacker" in prompt["summary"]
    for option in prompt["choice"]["options"]:
        assert "Preparation:" in option["description"]
        assert "trigger" in option["description"] and "Expires" in option["description"]
        if option["id"].startswith("intercept:"):
            assert "equal or higher" in option["description"]
            assert "do not attack the creature" in option["description"]
            assert "spell attacks" in option["description"] and "area effects" in option["description"]
            assert "Massive projectiles" in option["description"]
            assert "Reactive Interception:" in option["description"]  # Intercepting Strike's printed rules, not a Counter modifier
            assert "make this attack before" not in option["description"]
    if intercept:
        option = next(o for o in prompt["choice"]["options"]
                      if o["id"].startswith("intercept:") and "a melee weapon attack" in o["label"])
    else:
        option = next(o for o in prompt["choice"]["options"] if "targets you" in o["label"])
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    assert send()["reaction"] == prompt
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    commit(send, lambda p: (option["id"], True) if p["context"] == prompt["context"] else (None, False))
    assert act(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    attack = cast_sender(combat, table, mid, "Gun (Staff) attack", target=LEFT)
    result = attack()
    assert result["status"] == "REACTION_REQUIRED"
    discharge = result["reaction"]
    assert "Reaction now" in discharge["cost"] and "paid earlier" in discharge["cost"]
    assert "Right" in discharge["trigger"] and "Gun (Staff) attack" in discharge["trigger"]
    assert "No printed" not in discharge["summary"]
    assert expected_limit in discharge["limits"]
    if court == "active":
        assert "same creature's turn" in discharge["limits"]
    if intercept:
        assert "equal or higher" in discharge["summary"] and "intercept" in discharge["summary"]
    answers = [{**discharge["context"], "selection": "USE"}]
    for _ in range(8):
        result = attack(answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED"
        answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
    assert result["status"] == "COMMITTED"
    from combat.gate5_service import CombatService
    assert CombatService(combat.source_root, tmp_path)._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_raging_bull_table_limits_allow_charge_from_outside_reach(tmp_path):
    from combat.gate5_service import CombatService
    from tests.r10_fixup_support import cast_sender, commit

    staff = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.gun"}]}}
    bow = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.gong_jian"}]}}
    combat, table, mid = table_fight(tmp_path,
        ["RETRIBUTION_BASE_COUNTERSTRIKE", "TAL_RETRIBUTION_RAGING_BULL"],
        kits={"left": staff, "right": bow}, ask=True, ally_talents=[])
    # Use real table movement to leave the foe 20 feet away, with a clear charge path.
    commit(cast_sender(combat, table, mid, "Move", at=(0, 4)))
    engine = combat._load_session(mid).engine
    assert engine._distance_actor_to_actor(engine.state.actors[LEFT], engine.state.actors[RIGHT]) == 20
    prepare = cast_sender(combat, table, mid, "Counterstrike + Raging Bull")
    preparation = prepare()["reaction"]
    option = next(o for o in preparation["choice"]["options"] if "targets you" in o["label"])

    def check_limits(prompt):
        text = prompt["limits"]
        assert "Raging Bull" in text and "initially outside reach" in text
        assert "half your Speed" in text and "straight line" in text
        assert "must end with the triggering creature within your reach" in text
        assert "movement for the round" in text and "Opportunity Attacks" in text
        assert "occupied spaces or sealed barriers" in text
        assert "Each requires an available Reaction and a legal chosen trigger and target within reach" not in text

    check_limits(preparation)
    assert "half your Speed" in option["description"]  # Printed variant rule remains visible.
    before = engine.state.model_dump(mode="json")
    assert prepare()["reaction"] == preparation
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    commit(prepare, lambda p: (option["id"], True) if p["context"] == preparation["context"] else (None, False))
    engine = combat._load_session(mid).engine
    held = next(c for c in engine.state.actors[LEFT].conditions.values()
                if c.source_definition_id == "ready:retribution.counterstrike")
    prepared_weapon = engine.action_catalog[held.data["data"]["weapon"]]
    reach = int(prepared_weapon.reach_ft or prepared_weapon.range_ft or 5)
    assert engine._distance_actor_to_actor(engine.state.actors[LEFT], engine.state.actors[RIGHT]) > reach
    assert act(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    assert engine._distance_actor_to_actor(engine.state.actors[LEFT], engine.state.actors[RIGHT]) > reach
    weapon = next(c.display_name for c in engine.legal_candidates()
                  if LEFT in c.target_ids and c.source_definition_id in engine.action_catalog
                  and engine.action_catalog[c.source_definition_id].parameters.get("typed", {}).get("weapon")
                  and engine.action_catalog[c.source_definition_id].parameters["typed"].get("range_ft"))
    attack = cast_sender(combat, table, mid, weapon, target=LEFT)
    discharge = attack()["reaction"]
    check_limits(discharge)
    assert "Right" in discharge["trigger"] and weapon in discharge["trigger"]
    assert "Raging Bull" in discharge["summary"]
    before = engine.state.model_dump(mode="json")
    assert attack()["reaction"] == discharge
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    answers = [{**discharge["context"], "selection": "USE"}]
    for _ in range(8):
        result = attack(answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED"
        answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
    assert result["status"] == "COMMITTED"
    loaded = CombatService(combat.source_root, tmp_path)._load_session(mid)
    moves = [e for e in loaded.engine.events if e.event_type == "MOVEMENT_COMMITTED"
             and e.actor_id == LEFT and e.payload.get("counterstrike") == "raging_bull"]
    assert len(moves) == 1 and 0 < moves[0].payload["cost_ft"] <= 15
    assert loaded.engine._distance_actor_to_actor(loaded.engine.state.actors[LEFT], loaded.engine.state.actors[RIGHT]) <= reach
    assert any(e.event_type == "REACTION_RESOLVED" and e.actor_id == LEFT for e in loaded.engine.events)
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_intercepting_shot_ready_prompt_names_attack_and_survives_table_reload(tmp_path, selection):
    """Ready's second plugin must explain a real off-turn table decision, including Pass."""
    from combat.gate5_service import CombatService
    from combat.prepared_actions import CONDITION
    from tests.r10_fixup_support import cast_sender

    kit = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.gong_jian"}]}}
    combat, table, mid = table_fight(tmp_path, ["TAL_SNIPER_INTERCEPTING_SHOT"],
                                     kit=kit, ask=True, ally_talents=[])
    ready = cast_sender(combat, table, mid, "Ready: Intercepting Shot (")
    assert ready()["status"] == "COMMITTED"
    loaded = CombatService(combat.source_root, tmp_path)._load_session(mid)
    assert any(c.condition_id == CONDITION for c in loaded.engine.state.actors[LEFT].conditions.values())
    assert act(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != RIGHT:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    engine = combat._load_session(mid).engine
    weapon = next(c.display_name for c in engine.legal_candidates()
                  if LEFT in c.target_ids and c.source_definition_id in engine.action_catalog
                  and engine.action_catalog[c.source_definition_id].parameters.get("typed", {}).get("weapon")
                  and engine.action_catalog[c.source_definition_id].parameters["typed"].get("range_ft"))
    attack = cast_sender(combat, table, mid, weapon, target=LEFT)
    before = engine.state.model_dump(mode="json")
    result = attack()
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reaction_source_id"] == "ready:sniper.intercepting_shot"
    assert "Right" in prompt["trigger"] and "Left" in prompt["trigger"] and weapon in prompt["trigger"]
    assert "higher attack roll negates" in prompt["summary"]
    assert prompt["cost"] == "Reaction now; the Action to prepare was spent earlier"
    assert "start of your next turn" in prompt["limits"]
    assert "spell attacks" in prompt["limits"]
    assert "comparable in scale" in prompt["rules"]
    assert "Pass keeps your preparation" in prompt["table_note"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert attack()["reaction"] == prompt
    answers = [{**prompt["context"], "selection": selection}]
    # Passing the Ready can also offer the separate Martial Focus reaction; decline it.
    for _ in range(8):
        result = attack(answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED"
        answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
    assert result["status"] == "COMMITTED"
    loaded = CombatService(combat.source_root, tmp_path)._load_session(mid)
    held = any(c.condition_id == CONDITION for c in loaded.engine.state.actors[LEFT].conditions.values())
    assert held == (selection == "DECLINE")
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_dialog_renderer_escapes_rules_and_keeps_complete_effect_text():
    import subprocess
    script = Path(__file__).resolve().parents[1] / "static/tabletop/tabletop.js"
    program = r'''
const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync(process.argv[1], 'utf8');
const start = source.indexOf('function decisionText('), end = source.indexOf('\nfunction askChoice(', start);
const sandbox = {escapeHtml: text => String(text).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')};
vm.createContext(sandbox); vm.runInContext(source.slice(start,end), sandbox);
const long = 'Complete effect '.repeat(200) + '<img src=x onerror=alert(1)>';
const html = sandbox.decisionText({reactor:'Player', reaction:'Ability', trigger:'Opponent fell to 0 HP',
  cost:'2 Stamina', summary:'Move an ally 10 feet', limits:'Once per round', rules:long, table_note:'GM handles the rider'});
assert(html.includes('Opponent fell to 0 HP')); assert(html.includes('2 Stamina'));
assert(html.includes('&lt;img')); assert(!html.includes('<img')); assert(html.includes('Complete effect '.repeat(200)));
assert(html.includes('<details>')); assert(html.includes('Once per round')); assert(html.includes('GM handles the rider'));
console.log('decision renderer PASS');
'''
    assert "PASS" in subprocess.run(["node", "-e", program, str(script)], check=True, capture_output=True, text=True).stdout


def test_owner_roster_compiled_reactions_have_printed_effects_named_costs_and_limits():
    root = os.environ.get("N1_CHARACTER_ROOT")
    if not root:
        pytest.skip("Set N1_CHARACTER_ROOT to read-only portable character copies")
    paths = sorted(Path(root).glob("*/current.zip"))
    assert paths
    checked = set()
    for path in paths:
        with zipfile.ZipFile(path) as archive:
            sheet = json.loads(archive.read("Tianxia_Owner_Character_Sheet_v1.json"))
        bundle = compile_character(sheet, actor_id="actor:coverage")
        rows = bundle.get("typed_reactions") or []
        engine = SimpleNamespace(typed_reaction_rows={"actor:coverage": rows}, typed_passive_rows={}, action_catalog={},
                                 state=SimpleNamespace(actors={}))
        for row in rows:
            if row.get("block") == "opportunity":
                continue
            context = {"reactor_id": "actor:coverage", "reaction_source_id": "reaction:typed." + row["feature_id"],
                       "checkpoint": "TYPED:ATTACK_DECLARED@1", "choice_trigger": {"actor_id": "actor:foe", "target_id": "actor:coverage"}}
            prompt = build_decision_text(engine, context, {"reactor": "Player", "reaction": row.get("name") or "",
                "moment": "is attacked"}, {"actor:coverage": "Player", "actor:foe": "Opponent"}, {}, _rules_texts())
            assert prompt["rules"] and prompt["summary"], row["feature_id"]
            assert "No printed rule" not in prompt["summary"], row["feature_id"]
            assert "CP" not in prompt["cost"], row["feature_id"]
            assert "actor:" not in prompt["trigger"]
            checked.add(row["feature_id"])
    assert len(checked) > 20


def test_all_23_retained_audit_prompts_have_source_backed_rules():
    """The original audit occurrences remain covered even if current seeded fights take different paths."""
    root, audit_root = os.environ.get("N1_CHARACTER_ROOT"), os.environ.get("N1_AUDIT_ROOT")
    if not root or not audit_root:
        pytest.skip("Set N1_CHARACTER_ROOT and N1_AUDIT_ROOT to read-only audit inputs")
    from combat.gate2_runtime_models import ActionDefinition
    bundles = {}
    for path in Path(root).glob("*/current.zip"):
        with zipfile.ZipFile(path) as archive:
            sheet = json.loads(archive.read("Tianxia_Owner_Character_Sheet_v1.json"))
        actor_id = "actor:factory." + path.parent.name
        bundles[actor_id] = compile_character(sheet, actor_id=actor_id)
    count = 0
    for path in sorted(Path(audit_root).glob("fight-*.json")):
        data = json.loads(path.read_text())
        for old in data["prompts"]:
            context = old["context"]
            actor_id = context["reactor_id"]
            bundle = bundles[actor_id]
            engine = SimpleNamespace(typed_reaction_rows={actor_id: bundle.get("typed_reactions") or []},
                typed_passive_rows={actor_id: bundle.get("typed_passives") or []},
                action_catalog={a["source_definition_id"]: ActionDefinition.model_validate(a) for a in bundle["action_catalog"]},
                state=SimpleNamespace(actors={actor_id: SimpleNamespace(conditions={}, entity_id=actor_id)}))
            prompt = build_decision_text(engine, context, old, {actor_id: old["reactor"]}, {}, _rules_texts())
            assert prompt["rules"] and "No printed rule" not in prompt["summary"], old["reaction"]
            assert prompt["cost"] and "CP" not in prompt["cost"], old["reaction"]
            count += 1
    assert count == 23
