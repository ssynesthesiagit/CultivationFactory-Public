"""REACTUI2: one hit's defenses share one payload and one inline-choice card."""
import os
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.r10_fixup_support import fixed_dice
from tests.test_carry import KIT
from tests.test_tabletop_hunt6 import LEFT, RIGHT, HOLD, on_hold

FOREARM = "TAL_IRON_FIST_IRON_FOREARM_GUARD"
GUARD = "tianxia.path.body_refining.feature.stamina_guard"
DAWN = "tianxia.talent.radiance.dawn_ward"


def hit_table(monkeypatch, tmp_path, *, free=False, hits=1, native=False, nested=False, ineffective=False,
              damage_type="bludgeoning", defender_talents=None):
    bundles = []
    for actor in (LEFT, RIGHT):
        bundle = compile_character(sheet((defender_talents if defender_talents is not None else [FOREARM, GUARD])
            if actor == LEFT else [], cl=15,
            primary="Stamina", kit={"starting_kit": KIT}), actor_id=actor, reaction_plan={"ask": True})
        bundle["actor_template"].update(maximum_hp=400, initiative_bonus=-100 if actor == LEFT else 100)
        if free and actor == LEFT:
            # Transport fixture: a paid defense converted to an optional free
            # response in the saved bundle. No production ability rule changes.
            row = next(row for row in bundle["typed_reactions"] if row["feature_id"] == FOREARM)
            row.update(free=True, optional=True)
        if ineffective and actor == LEFT:
            # A legal zero-benefit response exercises the presentation fallback.
            # It remains executable, never removed from the transport.
            row = next(row for row in bundle["typed_reactions"] if row["feature_id"] == FOREARM)
            row["effects"] = [{"type": "damage_modifier", "applies_to": "self", "flat": 0}]
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed="REACTUI2", typed_bundles=tuple(bundles),
        roster_setup={"primary_actor_ids": [LEFT, RIGHT], "team_by_actor": {LEFT: "team:a", RIGHT: "team:b"},
                      "starting_positions": {LEFT: {"x": 3, "y": 4}, RIGHT: {"x": 4, "y": 4}}})
    mid = session.match_id
    table = TabletopService(combat, tmp_path)
    fixed_dice(monkeypatch, [10] * 200)
    attack_source = next(action["source_definition_id"] for action in bundles[1]["action_catalog"]
                         if ".weapon." in action["source_definition_id"])

    def child_hit(engine):
        from combat import typed_executor
        action = engine.action_catalog[attack_source]
        target = engine.state.actors[LEFT]
        if native:
            from combat.gate2_runtime_models import DiceSpec
            for index in range(hits):
                engine._resolve_attack_spec(engine.state.actors[RIGHT], target,
                    {"attack_bonus": 60, "damage": DiceSpec(count=1, sides=10, modifier=60),
                     "damage_type": damage_type.upper(), "reach_ft": 5}, engine._active_intent,
                    source_definition_id=attack_source, attack_index=index + 1)
            return
        ctx = typed_executor.Context(engine, engine.state.actors[RIGHT], action, engine._active_intent,
            {**action.parameters["typed"], "numbers": {"attack_bonus": 60}}, [target], target, {})
        typed_executor.block_attack(ctx, {"type": "attack", "attack_kind": "weapon", "count": hits,
            "on_hit": [{"type": "damage", "flat": 60, "damage_types": [damage_type]}]})

    def hit(engine):
        if nested:
            from combat.pending_damage import scope
            # A counterattack starts while an unrelated parent's packet is
            # still open. The child must discover its own hit + damage card.
            with scope(engine, engine.state.actors[RIGHT], 17, "FORCE", "parent", LEFT):
                child_hit(engine)
        else:
            child_hit(engine)

    on_hold(monkeypatch, hit)
    menu = table.state(mid)["menu"]
    assert menu["actor_id"] == RIGHT
    cid = next(option["candidate_id"] for group in menu["actions"] if group["source_definition_id"] == HOLD
               for option in group["options"])
    def send(answers=(), service=table):
        return service.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))
    return combat, table, mid, send


def answer(prompt, selection="DECLINE", **extra):
    return {**prompt["context"], "selection": selection, **extra}


@pytest.mark.parametrize("pick_second", [False, True], ids=["pass-all", "pick-second"])
@pytest.mark.parametrize("native", [False, True], ids=["typed", "native"])
def test_one_hit_payload_has_both_checkpoints_and_second_choice_commits(monkeypatch, tmp_path, pick_second, native):
    combat, table, mid, send = hit_table(monkeypatch, tmp_path, native=native)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    choices = result["reaction"]["alternatives"]
    assert [row["reaction"] for row in choices] == ["Iron Forearm Guard", "Stamina Guard"]
    assert len({row["context"]["checkpoint"] for row in choices}) == 2
    assert all(row["cost"] and row["summary"] for row in choices)
    assert [option["id"] for option in choices[1]["choice"]["options"]] == ["1", "2", "3", "4"]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert reopened.state(mid)["pending_action"]["reaction"] == result["reaction"]
    answers = [answer(row) for row in choices]
    if pick_second:
        answers[1] = answer(choices[1], "USE", option_ids=["3"])
    committed = send(answers, service=reopened)
    assert committed["status"] == "COMMITTED"
    assert committed["state"]["pending_action"] is None
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    resolved = [event for event in loaded.engine.events if event.event_type == "REACTION_RESOLVED" and event.actor_id == LEFT]
    assert [event.source_definition_id for event in resolved] == ([GUARD] if pick_second else [])
    if pick_second:
        assert resolved[0].payload["spend"] == 3
    assert loaded.engine.state.actors[LEFT].reaction_available == (not pick_second)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_free_response_keeps_remaining_defense_in_the_card_payload(monkeypatch, tmp_path):
    combat, table, mid, send = hit_table(monkeypatch, tmp_path, free=True)
    choices = send()["reaction"]["alternatives"]
    result = send([answer(choices[0], "USE")])
    assert result["status"] == "REACTION_REQUIRED"
    remaining = result["reaction"]["alternatives"]
    assert [row["reaction"] for row in remaining] == ["Stamina Guard"]
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert reopened.state(mid)["pending_action"]["reaction"] == result["reaction"]
    assert send([answer(choices[0], "USE"), answer(remaining[0], "USE", option_ids=["1"])], service=reopened)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert [event.source_definition_id for event in loaded.engine.events
            if event.event_type == "REACTION_RESOLVED" and event.actor_id == LEFT] == [FOREARM, GUARD]
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("reactor_mode", ["MANUAL", "SUGGESTED"])
def test_grouped_hit_menu_on_ai_turn_keeps_player_and_assisted_decisions(monkeypatch, tmp_path, reactor_mode):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid, _send = hit_table(monkeypatch, tmp_path)
    combat.set_controller_mode(mid, actor_id=LEFT, controller_mode=reactor_mode)
    combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="LOCAL_AUTO")
    base = combat.controller

    class HoldController:
        def choose_primary_action(self, context):
            cid = next(candidate.candidate_id for candidate in context.legal_candidates
                       if candidate.source_definition_id == HOLD)
            return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(base, name)

    combat.controller = HoldController()
    result = table.auto_step(mid, 0)
    assert result["status"] == "REACTION_REQUIRED"
    choices = result["reaction"]["alternatives"]
    assert [row["reaction"] for row in choices] == ["Iron Forearm Guard", "Stamina Guard"]
    result = table.auto_step(mid, 0, [answer(choices[0]), answer(choices[1], "USE", option_ids=["2"])])
    assert result["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert [event.source_definition_id for event in loaded.engine.events
            if event.event_type == "REACTION_RESOLVED" and event.actor_id == LEFT] == [GUARD]
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("pick_second", [False, True], ids=["skip", "later-defense"])
def test_api_combined_card_answers_survive_reload(monkeypatch, tmp_path, pick_second):
    from combat.gate5_service import CombatServiceError

    combat, table, mid, _send = hit_table(monkeypatch, tmp_path)
    combat.set_controller_mode(mid, actor_id=RIGHT, controller_mode="API_AUTO")

    class FakeProvider:
        calls = 0

        def status(self):
            return {"ready": True}

        def complete_json(self, *, prompt_text, **kwargs):
            self.calls += 1
            assert self.calls == 1, "Continuation must reuse the checked provider decision."
            frame = json.loads(prompt_text.split("\n\n", 1)[1])
            selected = next(c for c in frame["legal_candidates"] if c["source_definition_id"] == HOLD)
            return {"provider_id": "fake", "model": "offline", "value": {
                "schema": "TianxiaFactoryCombatAIIntent.v1", "action_intent": {
                    "decision_id": frame["decision_id"], "state_version": frame["state_version"],
                    **{key: selected[key] for key in ("candidate_id", "actor_id", "target_ids", "destination", "option_ids")}}}}

    provider = FakeProvider()
    combat.ai_provider = provider
    result = table.auto_step(mid, 0)
    assert result["status"] == "REACTION_REQUIRED"
    choices = result["reaction"]["alternatives"]
    assert [row["reaction"] for row in choices] == ["Iron Forearm Guard", "Stamina Guard"]
    reopened_combat = CombatService(ROOT, tmp_path)
    reopened = TabletopService(reopened_combat, tmp_path)
    assert reopened.state(mid)["pending_action"]["reaction"] == result["reaction"]
    before = reopened_combat._load_session(mid).engine.state.model_dump(mode="json")
    pending = reopened_combat._read_metadata(mid)["pending_provider_decision"]
    # Only an offered prefix is valid; rejecting a forged/skipped key must not
    # commit the action, change its state binding, or lose the saved decision.
    for bad in ([answer(choices[1])], [answer(choices[0]), answer(choices[1], checkpoint="TYPED:DAMAGE_APPLICATION@9999")]):
        with pytest.raises(CombatServiceError) as error:
            reopened.auto_step(mid, 0, bad)
        assert error.value.status_code == 409
        assert reopened_combat._load_session(mid).engine.state.model_dump(mode="json") == before
        assert reopened_combat._read_metadata(mid)["pending_provider_decision"] == pending
    answers = [answer(row) for row in choices]
    if pick_second:
        answers[1] = answer(choices[1], "USE", option_ids=["2"])
    committed = reopened.auto_step(mid, 0, answers)
    assert committed["status"] == "COMMITTED"
    assert committed["state"]["pending_action"] is None
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    resolved = [event for event in loaded.engine.events if event.event_type == "REACTION_RESOLVED" and event.actor_id == LEFT]
    assert [event.source_definition_id for event in resolved] == ([GUARD] if pick_second else [])
    if pick_second:
        assert resolved[0].payload["spend"] == 2
    assert loaded.engine.state.actors[LEFT].reaction_available == (not pick_second)
    assert "pending_provider_decision" not in reopened_combat._read_metadata(mid)
    assert provider.calls == 1
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


def test_pass_all_one_hit_does_not_pass_the_next_hit(monkeypatch, tmp_path):
    _combat, _table, _mid, send = hit_table(monkeypatch, tmp_path, hits=2)
    first = send()["reaction"]["alternatives"]
    assert len(first) == 2
    result = send([answer(row) for row in first])
    assert result["status"] == "REACTION_REQUIRED"
    second = result["reaction"]["alternatives"]
    assert [row["reaction"] for row in second] == ["Iron Forearm Guard", "Stamina Guard"]
    assert set(row["context"]["checkpoint"] for row in first).isdisjoint(row["context"]["checkpoint"] for row in second)
    assert send([answer(row) for row in first + second])["status"] == "COMMITTED"


def test_discovery_stops_at_a_mandatory_choice():
    from combat.reaction_menu import ReactionMenuProbe, MenuBoundary
    first = SimpleNamespace(checkpoint="TYPED:DAMAGE_APPLICATION@7", reactor_id=LEFT,
                            reaction_source_id="reaction:first", extension_choice=None)
    discovery = ReactionMenuProbe(first)
    discovery.answer(first)
    with pytest.raises(MenuBoundary):
        discovery.answer(SimpleNamespace(**{**vars(first), "reaction_source_id": "choice:required",
            "extension_choice": SimpleNamespace(allow_decline=False)}))
    assert discovery.contexts == [first]


@pytest.mark.parametrize("native", [False, True], ids=["typed", "native"])
def test_fresh_nested_hit_combines_child_defenses_and_commits_after_reload(monkeypatch, tmp_path, native):
    _combat, _table, mid, send = hit_table(monkeypatch, tmp_path, native=native, nested=True)
    result = send()
    choices = result["reaction"]["alternatives"]
    assert [row["reaction"] for row in choices] == ["Iron Forearm Guard", "Stamina Guard"]
    assert len({row["context"]["checkpoint"] for row in choices}) == 2
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert reopened.state(mid)["pending_action"]["reaction"] == result["reaction"]
    assert send([answer(choices[0]), answer(choices[1], "USE", option_ids=["2"])], service=reopened)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert [e.source_definition_id for e in loaded.engine.events
            if e.event_type == "REACTION_RESOLVED" and e.actor_id == LEFT] == [GUARD]
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("ineffective", [False, True], ids=["useful", "other-reaction"])
def test_table_card_has_current_damage_estimates_and_keeps_other_responses(monkeypatch, tmp_path, ineffective):
    combat, _table, mid, send = hit_table(monkeypatch, tmp_path, ineffective=ineffective)
    choices = send()["reaction"]["alternatives"]
    forearm, guard = choices
    assert forearm["useful_now"] is (not ineffective)
    assert guard["useful_now"] is True
    # This compiled weapon contributes its +6 modifier to the flat 60 fixture.
    assert "66 damage by 1d10 per Stamina (base avg 5.5 each)" in guard["expected_effect"]
    assert guard["menu_priority"] > forearm["menu_priority"]
    # Hints are persisted as JSON primitives and do not change answer order.
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert reopened.state(mid)["pending_action"]["reaction"]["alternatives"] == choices
    assert send([answer(forearm, "USE")], service=reopened)["status"] == "COMMITTED"
    loaded = combat._load_session(mid)
    assert [e.source_definition_id for e in loaded.engine.events
            if e.event_type == "REACTION_RESOLVED" and e.actor_id == LEFT] == [FOREARM]
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("native", [False, True], ids=["typed", "native"])
@pytest.mark.parametrize("damage_type", ["bludgeoning", "radiant"])
def test_dawn_ward_table_estimate_matches_triggering_packet(monkeypatch, tmp_path, damage_type, native):
    from combat.typed_amounts import amount_bounds

    combat, _table, mid, send = hit_table(monkeypatch, tmp_path, damage_type=damage_type, native=native,
        defender_talents=[FOREARM, GUARD, DAWN])
    result = send()
    choices = result["reaction"]["alternatives"]
    ward = next(p for p in choices if p["reaction"] == "Dawn Ward")
    # The rendered answer context deliberately contains only binding keys.
    # Packet facts live in the saved preview context used to build the hints.
    raw = json.loads(_table._pending_action_path(mid).read_text())["reaction_context"]
    ward_context = next(c for c in raw["reaction_choices"]
                        if c["reaction_source_id"] == ward["context"]["reaction_source_id"])
    assert ward_context["choice_trigger"]["damage_type"].lower() == damage_type
    row = next(r for r in combat._load_session(mid).engine.typed_reaction_rows[LEFT] if r["feature_id"] == DAWN)
    expected_twice = 0
    for effect in row["effects"]:
        if effect.get("type") != "damage_modifier":
            continue
        if effect.get("only_damage_types") and damage_type.upper() not in [t.upper() for t in effect["only_damage_types"]]:
            continue
        low, high = amount_bounds(effect, row.get("numbers"), ability_mods=row.get("ability_mods"), weapon=row.get("weapon"))
        expected_twice += low + high
    expected = str(expected_twice // 2) + (".5" if expected_twice % 2 else "")
    pending = ward_context["choice_trigger"].get("damage_amount", ward_context.get("pending_damage"))
    assert ward["expected_effect"] == f"Reduce {pending} damage by {expected} (base average)."
    assert ward["menu_priority"] == expected_twice
    assert "Necrotic" in ward["rules"] and "Radiant" in ward["rules"]
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert reopened.state(mid)["pending_action"]["reaction"] == result["reaction"]
    assert send([answer(p) for p in choices], service=reopened)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("nested", [False, True], ids=["next-packet", "other-target"])
def test_discovery_never_groups_another_packet_even_in_the_same_roll(nested):
    from combat.reaction_menu import ReactionMenuProbe, MenuBoundary
    frame = {"kind": "attack", "actor_id": RIGHT, "target_id": LEFT, "source_id": "club"}
    engine = SimpleNamespace(d20_context=lambda: frame, events=[SimpleNamespace(event_type="ATTACK_ROLLED",
        actor_id=RIGHT, target_ids=(LEFT,), source_definition_id="club", payload={"roll_id": "roll:1"})])
    hit = SimpleNamespace(checkpoint="TYPED:ATTACK_HIT_BEFORE_DAMAGE@7", reactor_id=LEFT,
                         reaction_source_id="reaction:hit", extension_choice=None)
    discovery = ReactionMenuProbe(hit)
    discovery.answer(hit, engine)
    packet = dict(source_actor_id=RIGHT, target_id=LEFT, source_id="club", event_sequence=8)
    engine._pending_damage_context = SimpleNamespace(**packet)
    engine._pending_damage_scratch = {}
    damage = SimpleNamespace(**{**vars(hit), "checkpoint": "TYPED:DAMAGE_APPLICATION@8",
                                "reaction_source_id": "reaction:damage"})
    discovery.answer(damage, engine)
    # Nested packets can open without publishing an intervening event. Packet
    # scope, rather than the journal cursor, is the boundary.
    if nested:
        packet.update(target_id=RIGHT)
    engine._pending_damage_scratch = {}
    engine._pending_damage_context = SimpleNamespace(**packet)
    with pytest.raises(MenuBoundary):
        discovery.answer(damage, engine)


def test_damage_without_an_attack_groups_by_packet_scope_not_event_cursor():
    from combat.reaction_menu import ReactionMenuProbe, MenuBoundary
    engine = SimpleNamespace(d20_context=lambda: None, events=[], _pending_damage_scratch={},
                             _pending_damage_context=SimpleNamespace())
    first = SimpleNamespace(checkpoint="TYPED:DAMAGE_APPLICATION@7", reactor_id=LEFT,
                            reaction_source_id="reaction:first", extension_choice=None)
    second = SimpleNamespace(**{**vars(first), "checkpoint": "TYPED:DAMAGE_APPLICATION@8",
                                "reaction_source_id": "reaction:second"})
    discovery = ReactionMenuProbe(first)
    discovery.answer(first, engine)
    discovery.answer(second, engine)
    assert discovery.contexts == [first, second]
    # A nested attack's hit can still see the parent's pending packet. That
    # does not turn the child attack into another response to the parent.
    with pytest.raises(MenuBoundary):
        discovery.answer(SimpleNamespace(**{**vars(second), "checkpoint": "TYPED:ATTACK_HIT_BEFORE_DAMAGE@9"}), engine)
    engine._pending_damage_scratch = {}
    with pytest.raises(MenuBoundary):
        discovery.answer(second, engine)


@pytest.mark.parametrize("script", ["reactui2_card.test.mjs", "viewer_identity_dialog.test.mjs", "sol150_table_text.test.mjs"])
def test_node_single_reaction_card(script):
    result = subprocess.run(["node", "--test", "--test-isolation=none", str(Path(__file__).with_name(script))],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("ineffective", [False, True], ids=["ranked", "other-reactions"])
def test_ranked_card_inline_amount_reaches_fight(monkeypatch, tmp_path, ineffective):
    """Use the production card's answer, rather than handcrafting option_ids."""
    combat, table, mid, send = hit_table(monkeypatch, tmp_path, ineffective=ineffective)
    prompt = send()["reaction"]
    # Real ranking puts Guard first even though its checkpoint is second.
    # Exercise the same semantic entry selection as the opt-in browser check.
    result = subprocess.run(["node", "--input-type=module", "-e", r'''
        import {readFileSync} from 'node:fs';
        import assert from 'node:assert/strict';
        import {reactionCardHarness} from './tests/reaction_card_harness.mjs';
        import {functionSource} from './tests/viewer_identity_harness.mjs';
        import {runInNewContext} from 'node:vm';
        const prompt = JSON.parse(readFileSync(0, 'utf8'));
        const {context, dialog} = reactionCardHarness();
        context.askReaction = row => context.askReactionMenu(row);
        context.playEvents = async () => {};
        runInNewContext(functionSource('appendReactionAnswer') + '\n' + functionSource('withReactions'), context);
        let requests = 0, submitted;
        const pending = context.withReactions(async answers => {
            if (++requests === 1) return {status: 'REACTION_REQUIRED', reaction: prompt};
            submitted = JSON.parse(JSON.stringify(answers));
            return {status: 'COMMITTED'};
        });
        for (let n = 0; n < 10 && !dialog.open; n++) await Promise.resolve();
        const entries = dialog.querySelectorAll('[data-reaction-entry]');
        // The stub preserves attributes, but does not parse HTML text nodes.
        const entry = entries.find(node => node.querySelector('select')?.getAttribute('aria-label') === 'Stamina Guard choice');
        assert.equal(entry, entries[0], 'Guard ranks first but remains transport choice 1');
        entry.querySelector('select').value = '3';
        entry.querySelector('[data-reaction-use]').onclick();
        await pending;
        assert.deepEqual(submitted.at(-1).option_ids, ['3']);
        assert.equal(submitted.at(-1).selection, 'USE');
        console.log(JSON.stringify(submitted));
    '''], cwd=ROOT, input=json.dumps(prompt), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    answers = json.loads(result.stdout)
    assert answers == [answer(prompt["alternatives"][0]),
                       answer(prompt["alternatives"][1], "USE", option_ids=["3"])]
    before = combat._load_session(mid).engine.state.actors[LEFT].current_hp
    reopened = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    assert send(answers, service=reopened)["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    resolved = [event for event in loaded.engine.events
                if event.event_type == "REACTION_RESOLVED" and event.actor_id == LEFT]
    assert len(resolved) == 1 and resolved[0].source_definition_id == GUARD
    assert resolved[0].payload["spend"] == 3
    assert loaded.engine.state.actors[LEFT].current_hp == before - 36  # 66 damage minus three fixed d10s.
    assert loaded.verify()["status"] == loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.skipif(os.environ.get("REACTUI2_BROWSER") != "1", reason="Lead must run Chromium outside the sandbox")
@pytest.mark.parametrize("ineffective", [False, True], ids=["ranked", "other-reactions"])
def test_browser_single_card_and_inline_amount(monkeypatch, tmp_path, ineffective):
    from playwright.sync_api import sync_playwright
    _combat, _table, _mid, send = hit_table(monkeypatch, tmp_path, ineffective=ineffective)
    prompt = send()["reaction"]
    source = (ROOT / "static/tabletop/tabletop.js").read_text()
    functions = source[source.index("function decisionText("):source.index("// The Items panel")]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", args=["--no-sandbox"], headless=True)
        try:
            page = browser.new_page()
            page.set_content('<dialog id="ttReaction"><h2 id="ttReactionTitle"></h2><div id="ttReactionText"></div>'
                             '<button data-answer="USE">Use</button><button data-answer="DECLINE">Pass</button></dialog>')
            page.add_style_tag(path=str(ROOT / "static/tabletop/tabletop.css"))
            page.add_script_tag(content='const app = {matchId:"test"}; const $ = s => document.querySelector(s);'
                'const escapeHtml = s => String(s ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(\'"\',"&quot;");'
                'const toast = s => {throw Error(s)}; const resumeViewerDialogs = () => {if (!$("#ttReaction").open) $("#ttReaction").showModal()};'
                + functions)
            page.evaluate('(prompt) => {window.answer = askReactionMenu(prompt)}', prompt)
            assert page.locator('[data-reaction-entry]').count() == 2
            assert "Stamina Guard" in page.locator('[data-reaction-entry]').first.inner_text()
            assert "66 damage by 1d10 per Stamina" in page.locator('.tt-reaction-expected').first.inner_text()
            if ineffective:
                assert not page.locator('[data-other-reactions]').evaluate('(node) => node.open')
                page.locator('[data-other-reactions] > summary').click()
            assert page.get_by_text("Iron Forearm Guard", exact=True).first.is_visible()
            assert page.locator('[data-answer="DECLINE"]').inner_text() == "Skip"
            # Choice indexes follow checkpoint order; Use indexes follow ranked
            # group order. Select both controls within the named ability.
            guard = page.locator('[data-reaction-entry]').filter(
                has=page.get_by_role("heading", name="Stamina Guard", exact=True))
            guard.locator('select').select_option("3")
            guard.get_by_role("button", name="Use Stamina Guard", exact=True).click()
            answers = page.evaluate('() => window.answer')
            assert answers[-1]["selection"] == "USE" and answers[-1]["option_ids"] == ["3"]
        finally:
            browser.close()
