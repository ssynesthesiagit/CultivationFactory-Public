"""Guards for reusable seams; synthetic Source rows here are transport fixtures.

Whole-feature proof lives in test_mgr_t14_ling_subpath_cycle_rebirth.py. These
fixtures exercise declarations, compound settlement and explicitly authored
suppression without claiming that an existing Source grants new powers.
"""
from copy import deepcopy

import pytest

from combat import ext
from combat.canonical import canonical_sha256
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.ext import mgr_t14_cycle_rebirth as R
from tests.test_mgr_t14_ling_subpath_cycle_rebirth import acquired, ready, commit, cold, ME, FOE


def fixture_bundle(doc, actor_id, *, alignments=("fire", "earth"), effects=(), cost=1, cost_resource=R.QI):
    from combat.factory_compiler import compile_character
    result = compile_character(deepcopy(doc), actor_id=actor_id)
    source = "action:test.cycle.seam"
    action = ActionDefinition(source_definition_id=source, owner_id=actor_id,
        display_name="Test elemental technique", economy=EconomyKind.ACTION, target_kind="SELF", resolution_kind="TYPED",
        costs=((cost_resource, cost),), parameters={"typed": {"source": "test:elemental_source",
            "elemental_alignments": list(alignments), "power_resource": R.QI,
            "effects": list(effects), "numbers": {"cl": 6, "pb": 3}, "duration": {"kind": "instant"}, "riders": []}})
    result["action_catalog"].append(action.model_dump(mode="json"))
    result["actor_template"]["action_ids"].append(source)
    result.pop("bundle_sha256", None)
    result["bundle_sha256"] = canonical_sha256(result)
    return result


def guard_table(tmp_path, doc, **kwargs):
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import sheet
    from tests.test_mgr_t14_ling_subpath_cycle_rebirth import ROOT
    from combat.factory_compiler import compile_character
    combat = CombatService(ROOT, tmp_path)
    bundles = [fixture_bundle(doc, ME, **kwargs), compile_character(sheet([], cl=6, name="Opponent"), actor_id=FOE)]
    arena = combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"]
    mid = combat._finish_factory_match(bundles, [ME, FOE], {ME: "team:a", FOE: "team:b"},
        {ME: {"x": 3, "y": 6}, FOE: {"x": 5, "y": 6}}, arena, [ME], [FOE],
        control_modes={ME: "MANUAL", FOE: "MANUAL"}, match_seed="CYCLE-SEAM", maximum_rounds=10,
        display_name="Elemental seam guard")["match_id"]
    table = TabletopService(combat, tmp_path)
    ready(combat, table, mid, "fire")
    return combat, table, mid


@pytest.mark.parametrize("alignment,expected", [("fire", "earth"), ("earth", "fire")])
def test_multiple_alignments_are_declared_before_effects_and_replayed(tmp_path, acquired, monkeypatch, alignment, expected):
    seen = []
    def observe(ctx, row):
        seen.append((ctx.typed.get("declared_element"), R.state(ctx.actor).data["active"]))
    monkeypatch.setitem(ext.effects(), "test_cycle_observe", observe)
    combat, table, mid = guard_table(tmp_path, acquired["fire"], effects=[{"type": "test_cycle_observe"}])
    # The Source fixture is compiled and hashed before match creation; its
    # observer is a generic effect, not a stand-in completion/ownership signal.
    engine = combat._load_session(mid).engine
    action = engine.action_catalog["action:test.cycle.seam"]
    # Pure declaration receives the complete source roster and can pause at
    # the table even when another creature owns the foreground turn.
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == action.source_definition_id)
    prompts = commit(table, mid, candidate.candidate_id, alignment=alignment)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.elemental_alignment" for p in prompts)
    assert seen and all(row == (alignment, "fire") for row in seen)
    engine = cold(tmp_path, mid)
    assert R.state(engine.state.actors[ME]).data["active"] == expected
    assert engine.action_catalog[action.source_definition_id].parameters["typed"].get("declared_element") is None


@pytest.mark.parametrize("kind", ["cl", "element"])
def test_native_restriction_effect_persists_and_expires_without_erasing_knowledge(tmp_path, acquired, kind):
    limit = {"type": "cultivation_limit", "applies_to": "self", "expires_on": "START_OF_SELF_NEXT_TURN",
             **({"cl_cap": 5} if kind == "cl" else {"element": "fire"})}
    combat, table, mid = guard_table(tmp_path, acquired["fire"], alignments=("fire",), effects=[limit])
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:test.cycle.seam")
    commit(table, mid, candidate.candidate_id)
    engine = cold(tmp_path, mid)
    actor = engine.state.actors[ME]
    assert R.state(actor).data["active"] == "fire"
    assert R.state(actor).data["known"] == "fire,earth,metal"
    from combat.cultivation_access import effective_cl, alignment_available
    assert effective_cl(engine, actor, 6) == (5 if kind == "cl" else 6)
    assert alignment_available(engine, actor, "fire") is (kind == "cl")
    assert alignment_available(engine, actor, "earth")
    if kind == "element":
        sources = {(engine.action_catalog[c.source_definition_id].parameters.get("typed") or {}).get("source")
                   for c in engine.legal_candidates() if c.source_definition_id in engine.action_catalog}
        assert "FIRE_BASE_IGNITE" not in sources
        assert "TAL_METAL_CONDUCTOR_S_PALM" in sources
    commit(table, mid, table.state(mid)["menu"]["end_turn"], active="fire")
    ready(combat, table, mid, "fire")
    engine = cold(tmp_path, mid)
    assert effective_cl(engine, engine.state.actors[ME], 6) == 6
    assert alignment_available(engine, engine.state.actors[ME], "fire")


def test_without_completed_consumer_the_native_regression_detects_missing_shift(tmp_path, acquired, monkeypatch):
    from tests.test_mgr_t14_ling_subpath_cycle_rebirth import build, use
    combat, table, mid = build(tmp_path, acquired["fire"])
    ready(combat, table, mid, "fire")
    monkeypatch.setitem(ext._HOOKS, "technique_resolved", [f for f in ext._HOOKS["technique_resolved"] if f is not R.rebirth])
    use(combat, table, mid, "FIRE_BASE_IGNITE")
    assert R.state(combat._load_session(mid).engine.state.actors[ME]).data["active"] == "fire"


def test_compound_effects_and_final_riders_finish_before_the_shift(tmp_path, acquired, monkeypatch):
    seen = []
    def observe(ctx, row):
        seen.append((row["step"], ctx.typed["declared_element"], R.state(ctx.actor).data["active"]))
    monkeypatch.setitem(ext.effects(), "test_cycle_compound", observe)
    def final(engine, actor, action, candidate, intent):
        if action.source_definition_id == "action:test.cycle.seam":
            seen.append(("final", action.parameters["typed"]["declared_element"], R.state(actor).data["active"]))
    monkeypatch.setitem(ext._HOOKS, "resolution_final", [*ext._HOOKS.get("resolution_final", []), final])
    combat, table, mid = guard_table(tmp_path, acquired["fire"], alignments=("fire",), effects=[
        {"type": "test_cycle_compound", "step": "first"}, {"type": "test_cycle_compound", "step": "second"}])
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:test.cycle.seam")
    commit(table, mid, candidate.candidate_id)
    assert seen and all(element == active == "fire" for _, element, active in seen)
    assert {step for step, _, _ in seen} == {"first", "second", "final"}
    assert R.state(cold(tmp_path, mid).state.actors[ME]).data["active"] == "earth"


def test_final_rider_refund_is_in_the_actual_settlement_receipt(tmp_path, acquired, monkeypatch):
    def refund(engine, actor, action, candidate, intent):
        if action.source_definition_id == "action:test.cycle.seam":
            engine._gain_resource(actor, R.QI, 1, "test:late_refund", cost_source_id=action.source_definition_id)
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "resolution_final", [*ext._HOOKS.get("resolution_final", []), refund])
    combat, table, mid = guard_table(tmp_path, acquired["fire"], alignments=("fire",))
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:test.cycle.seam")
    commit(table, mid, candidate.candidate_id)
    assert R.state(cold(tmp_path, mid).state.actors[ME]).data["active"] == "fire"


@pytest.mark.parametrize("resource", [R.QI, "resource:core.stamina"])
def test_fully_refunded_cost_substitution_does_not_cycle(tmp_path, acquired, monkeypatch, resource):
    # A synthetic Source explicitly remains Qi-powered when paying another
    # admitted pool. Its price/refund still travels through real native costs;
    # no completion/payment receipt is fabricated by this guard.
    def refund(engine, actor, action, candidate, intent):
        if action.source_definition_id == "action:test.cycle.seam":
            engine._gain_resource(actor, resource, 1, "test:substituted_refund", cost_source_id=action.source_definition_id)
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "resolution_final", [*ext._HOOKS.get("resolution_final", []), refund])
    doc = deepcopy(acquired["fire"])
    doc["ability_scores_and_statistics"]["primary_resource"]["definitions"] = [{"name": "Stamina", "maximum": 30}]
    combat, table, mid = guard_table(tmp_path, doc, alignments=("fire",), cost_resource=resource)
    engine = combat._load_session(mid).engine
    before = engine.state.actors[ME].resources[resource]
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:test.cycle.seam")
    commit(table, mid, candidate.candidate_id)
    engine = cold(tmp_path, mid)
    assert engine.state.actors[ME].resources[resource] == before
    assert R.state(engine.state.actors[ME]).data["active"] == "fire"


def test_partial_activation_refund_does_not_cycle(tmp_path, acquired, monkeypatch):
    # The printed prohibition says refunded activation, without a full-refund
    # exception. A discount before payment is distinct from returning paid Qi.
    def refund(engine, actor, action, candidate, intent):
        if action.source_definition_id == "action:test.cycle.seam":
            engine._gain_resource(actor, R.QI, 1, "test:partial_refund", cost_source_id=action.source_definition_id)
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, "resolution_final", [*ext._HOOKS.get("resolution_final", []), refund])
    combat, table, mid = guard_table(tmp_path, acquired["fire"], alignments=("fire",), cost=2)
    engine = combat._load_session(mid).engine
    before = engine.state.actors[ME].resources[R.QI]
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:test.cycle.seam")
    commit(table, mid, candidate.candidate_id)
    engine = cold(tmp_path, mid)
    assert engine.state.actors[ME].resources[R.QI] == before - 1
    assert R.state(engine.state.actors[ME]).data["active"] == "fire"


def test_next_independent_action_callback_sees_the_completed_shift(tmp_path, acquired, monkeypatch):
    from combat import typed_reactions
    from tests.test_mgr_t14_ling_subpath_cycle_rebirth import build, use
    seen = []
    original = typed_reactions.on_action_completed
    def observe(engine, actor, economy, source):
        if actor.entity_id == ME:
            seen.append(R.state(actor).data["active"])
        return original(engine, actor, economy, source)
    monkeypatch.setattr(typed_reactions, "on_action_completed", observe)
    combat, table, mid = build(tmp_path, acquired["fire"])
    ready(combat, table, mid, "fire")
    use(combat, table, mid, "FIRE_BASE_IGNITE")
    assert seen and all(active == "earth" for active in seen)
    assert R.state(cold(tmp_path, mid).state.actors[ME]).data["active"] == "earth"


def test_neutral_source_never_infers_alignment_from_its_label_or_qi_cost(tmp_path, acquired):
    combat, table, mid = guard_table(tmp_path, acquired["fire"], alignments=())
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.source_definition_id == "action:test.cycle.seam")
    assert not commit(table, mid, candidate.candidate_id)
    assert R.state(cold(tmp_path, mid).state.actors[ME]).data["active"] == "fire"


def test_player_turn_choice_still_asks_during_an_ai_creatures_turn(tmp_path, acquired):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = guard_table(tmp_path, acquired["fire"])
    commit(table, mid, table.state(mid)["menu"]["end_turn"])
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    original = combat.controller
    class EndTurn:
        def choose_primary_action(self, context):
            legal = combat._load_session(mid).engine.legal_candidates()
            candidate = next(c for c in legal if c.kind == "END_TURN")
            return ManualControllerAdapter(lambda _: (candidate.candidate_id, ())).choose_primary_action(
                context.model_copy(update={"legal_candidates": tuple(legal)}))
        def __getattr__(self, name):
            return getattr(original, name)
    combat.controller = EndTurn()
    after = table.state(mid)["last_sequence"]
    result = table.auto_step(mid, after)
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == ME
    assert {o["id"] for o in prompt["choice"]["options"]} == {"fire", "earth", "metal"}
    answer = {**prompt["context"], "selection": "USE", "option_ids": ["metal"]}
    result = table.auto_step(mid, after, reactions=[answer])
    assert result["status"] == "COMMITTED", result
    assert R.state(cold(tmp_path, mid).state.actors[ME]).data["active"] == "metal"


def test_ai_owned_declaration_uses_only_its_own_source_options(tmp_path, acquired):
    from combat.gate4_adapters import ManualControllerAdapter
    combat, table, mid = guard_table(tmp_path, acquired["fire"], alignments=("fire", "water"))
    combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    original = combat.controller
    class ChooseTechnique:
        def choose_primary_action(self, context):
            legal = combat._load_session(mid).engine.legal_candidates()
            candidate = next(c for c in legal if c.source_definition_id == "action:test.cycle.seam")
            return ManualControllerAdapter(lambda _: (candidate.candidate_id, ())).choose_primary_action(
                context.model_copy(update={"legal_candidates": tuple(legal)}))
        def __getattr__(self, name):
            return getattr(original, name)
    combat.controller = ChooseTechnique()
    result = table.auto_step(mid, table.state(mid)["last_sequence"])
    assert result["status"] == "COMMITTED", result
    assert R.state(cold(tmp_path, mid).state.actors[ME]).data["active"] == "earth"


def test_builder_acquisition_controls_keep_all_options_and_require_a_selection():
    import json
    from pathlib import Path
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node is not installed")
    app = Path(__file__).resolve().parents[1]
    script = r'''
const fs = require('node:fs'), vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const nodes = {};
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.value = ''; }
  appendChild(node) { this.children.push(node); return node; }
  after(node) { nodes[node.id] = node; }
}
nodes.sheetSubpath = new Element('select');
const selected = new Set();
const all = node => [node, ...node.children.flatMap(all)];
const document = {getElementById: key => nodes[key] || null, createElement: tag => new Element(tag),
 querySelectorAll: () => Object.values(nodes).flatMap(all).filter(n => n.dataset.acquisitionChoice)};
const context = {document, characterBuilderOptions: {acquisition_choices: input.definitions},
 selectedSet: () => selected, planningIsEditable: () => true, clearNode: node => {node.children = [];}};
vm.createContext(context);
const source = fs.readFileSync(input.source, 'utf8');
for (const name of ['renderAcquisitionChoices', 'collectAcquisitionChoices']) {
 const start = source.indexOf(`function ${name}(`), end = source.indexOf('\nfunction ', start + 1);
 vm.runInContext(source.slice(start, end < 0 ? source.length : end), context);
}
context.renderAcquisitionChoices();
if (document.querySelectorAll().length) throw Error('unowned choices shown');
selected.add(input.parent); context.renderAcquisitionChoices();
let select = document.querySelectorAll()[0];
if (select.value !== '' || select.children.length !== 6) throw Error('missing choice or options cut');
select.value = 'water'; context.renderAcquisitionChoices();
if (context.collectAcquisitionChoices().five_elements_start !== 'water') throw Error('choice lost');
selected.clear(); context.renderAcquisitionChoices();
if (Object.keys(context.collectAcquisitionChoices()).length) throw Error('unowned selection leaked');
console.log('All five choices remain available; no selection is fabricated.');
'''
    from character_creation.acquisition_choices import definitions
    result = subprocess.run(["node", "-e", script], input=json.dumps({
        "source": str(app / "static/app.js"), "definitions": definitions(), "parent": R.PARENT}),
        text=True, capture_output=True, check=True)
    assert "All five choices" in result.stdout
