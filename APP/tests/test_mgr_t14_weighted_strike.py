"""Whole-row Weighted Strike receipts from accepted table intents and cold replay.

Characters acquire the Gravity base package on their portable sheet; no effect,
mode, hit, movement, or resource receipt is inserted into a running fight.
"""
import json
import re
import zipfile
from pathlib import Path

import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import sheet
from tests import test_a2_gravity as G

ROOT = Path(__file__).resolve().parents[1]
ME, FOE, OTHER = G.ME, G.FOE, G.ALLY
OWNER = "GRAVITY_BASE_WEIGHTED_STRIKE"
STAMINA, QI = "resource:core.stamina", "resource:core.qi"


def fight(tmp_path, *, cl=1, dc=50, primary="Stamina", owner=True,
          foe_hp=1000, stamina=30, mode="MANUAL", other_position=None, seed="WEIGHTED-NORMAL"):
    bundles = []
    for actor_id in (ME, FOE, OTHER):
        doc = sheet([G.WS] if actor_id == ME and owner else [], cl=cl,
                    dc=dc, primary=primary, score=30, name=actor_id.rsplit('-', 1)[-1],
                    kit={"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.fu", "quantity": 1}]}})
        # Base components are acquisition output, not learned talent choices.
        doc.setdefault("spheres_and_talents", {})["learned_talent_record_ids"] = []
        if actor_id == ME and owner:
            from canonical_catalog.service import CanonicalCatalogAuthorityService
            from sphere_component_authority import attach_sphere_automatic_component_receipt
            ledger = {}
            packet = attach_sphere_automatic_component_receipt(ledger,
                CanonicalCatalogAuthorityService(ROOT).get_sphere('tianxia.sphere.gravity'), {
                    'event_id': 'native-weighted-strike-acquisition', 'legal_channel': 'sphere_acquisition',
                    'advancement': {'target_cl': cl}})
            assert G.WS in packet['component_ids']
            doc['spheres_and_talents'] = {'sphere_record_ids': ['tianxia.sphere.gravity'],
                'learned_talent_record_ids': [], 'automatic_sphere_component_record_ids': packet['component_ids'],
                'automatic_sphere_component_receipts': ledger['automatic_sphere_component_receipts'],
                'automatic_sphere_components': ledger['automatic_sphere_components']}
        stats = doc["ability_scores_and_statistics"]
        stats["armor_class"]["base_value"] = 0
        stats["hit_points"]["maximum"] = foe_hp if actor_id == FOE else 1000
        if actor_id == ME:
            stats["primary_resource"]["maximum"] = stamina
        folder = tmp_path / "portable_characters" / actor_id.removeprefix("actor:factory.")
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as z:
            z.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundles.append(compile_character(doc, actor_id=actor_id, reaction_plan={"ask": True}))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    ids = [ME, FOE, OTHER]
    mid = combat._finish_factory_match(
        bundles, ids, {ME: "a", FOE: "b", OTHER: "b"},
        {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}, OTHER: other_position or {"x": 12, "y": 2}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [ME], [FOE, OTHER], control_modes={ME: mode, FOE: "MANUAL", OTHER: "MANUAL"},
        match_seed=seed, display_name="Weighted Strike", maximum_rounds=15)["match_id"]
    G.advance(combat, table, mid, ME)
    return combat, table, mid


def cold(tmp_path, mid):
    combat = CombatService(ROOT, tmp_path)
    session = combat._load_session(mid)
    assert session.verify()["status"] == "PASS"
    assert session.mechanical.replay()["status"] == "PASS"
    return combat, TabletopService(combat, tmp_path), session.engine


def answer(blow="heavying", pool="stamina", outcome="prone", step="cell:1,6"):
    def choose(prompt, choice):
        source = prompt["context"]["reaction_source_id"]
        if source.endswith("gravity_weighted_strike"):
            assert all(s in str(prompt) for s in ("Weighted Strike", "me", "foe"))
            return [f"{blow}:{pool}"]
        if source.endswith("gravity_heavying"):
            return [outcome]
        if source.endswith("rider_step"):
            return [step]
        return False
    return choose


def force_rolls(engine):
    return [e.payload["expression"].removesuffix("+0") for e in engine.events if e.event_type == "DAMAGE_ROLLED"
            and re.fullmatch(r"\d+d6(?:\+0)?", e.payload.get("expression", ""))]


def held(engine, actor_id, name):
    return [c for c in engine.state.actors[actor_id].conditions.values() if c.condition_id.endswith(name)]


@pytest.mark.parametrize("blow", ["heavying", "lightening"])
def test_weighted_strike_retains_the_confirmed_critical_hit(tmp_path, blow):
    # Three initiative dice precede the natural 20; no roll is patched or
    # declared by the player. Both the hit and its bonus survive cold replay.
    combat, table, mid = fight(tmp_path, seed="WEIGHTED-CRITICAL-2")
    G.use(combat, table, mid, "Weight Shift: Body Lightening")
    G.use(combat, table, mid, "Fu (Short Axe)", answer(blow))
    _, _, engine = cold(tmp_path, mid)
    assert force_rolls(engine) == ['2d6']
    rolls = [e for e in engine.events if e.event_type == "DAMAGE_ROLLED"
             and re.fullmatch(r"2d6(?:\+0)?", e.payload.get("expression", ""))]
    assert len(rolls) == 1
    assert rolls[0].payload.get("critical") is True
    assert len(rolls[0].payload["dice"]) == 2
    assert engine.state.actors[ME].resources[STAMINA] == 29


def test_native_gravity_base_retains_consumers_without_optional_feature_shard(tmp_path, monkeypatch):
    from combat import typed_reactions
    rules = json.loads(json.dumps(typed_reactions.rules()))
    for source in (G.WS, OWNER):
        rules['features'].pop(source, None)
    path = tmp_path / 'portable-feature-blocks.json'
    path.write_text(json.dumps(rules))
    monkeypatch.setattr(typed_reactions, 'RULES_PATH', path)
    monkeypatch.setattr(typed_reactions, '_CACHE', {})
    combat, table, mid = fight(tmp_path)
    engine = combat._load_session(mid).engine
    assert len([r for r in engine.typed_passive_rows[ME] if r.get('feature_id') == OWNER]) == 1
    assert not any(r.get('feature_id') == OWNER for r in engine.typed_passive_rows.get(FOE, []))
    G.use(combat, table, mid, 'Weight Shift: Body Lightening')
    G.use(combat, table, mid, 'Fu (Short Axe)', answer())
    _, _, engine = cold(tmp_path, mid)
    assert force_rolls(engine) == ['1d6']
    assert engine.state.actors[ME].resources[STAMINA] == 29
    assert held(engine, FOE, 'prone')


@pytest.mark.parametrize("cl,count", [(1, 1), (4, 1), (5, 2), (10, 2), (11, 3), (16, 3), (17, 4)])
@pytest.mark.parametrize("blow", ["heavying", "lightening"])
def test_native_base_acquisition_cost_scaling_and_step(tmp_path, cl, count, blow):
    combat, table, mid = fight(tmp_path, cl=cl)
    engine = combat._load_session(mid).engine
    rows = engine.typed_passive_rows[ME]
    assert len([r for r in rows if r.get("feature_id") == OWNER]) == 1
    assert not any(r.get("feature_id") == OWNER for r in engine.typed_passive_rows.get(FOE, []))
    G.use(combat, table, mid, "Weight Shift: Body Lightening")
    combat, table, _ = cold(tmp_path, mid)
    _, asked = G.use(combat, table, mid, "Fu (Short Axe)", answer(blow))
    _, _, engine = cold(tmp_path, mid)
    assert force_rolls(engine) == [f"{count}d6"]
    assert not any(e.payload.get('critical') for e in engine.events if e.event_type == 'DAMAGE_ROLLED')
    assert any(e.event_type == "DAMAGE_COMMITTED" and e.payload.get("damage_type") == "FORCE"
               and e.target_ids == (FOE,) for e in engine.events)
    assert engine.state.actors[ME].resources[STAMINA] == 29
    assert engine.state.actors[FOE].resources[STAMINA] == 30
    first = next(q for q in asked if q["context"]["reaction_source_id"].endswith("gravity_weighted_strike"))
    options = {o["id"] for o in first["choice"]["options"]}
    assert {"heavying:stamina", "lightening:stamina"} <= options
    if blow == "lightening":
        actor = engine.state.actors[ME]
        assert (actor.position.x, actor.position.y) == (1, 6)
        assert not any(e.event_type == "ATTACK_ROLLED" and e.actor_id == FOE for e in engine.events)
        prompt = next(q for q in asked if q["context"]["reaction_source_id"].endswith("rider_step"))
        assert "cannot make an Opportunity Attack" in str(prompt)
    else:
        assert held(engine, FOE, "prone")


@pytest.mark.parametrize("outcome,x", [("push", 5), ("pull", 4), ("prone", 4)])
def test_heavying_choices_are_the_attacker_choices(tmp_path, outcome, x):
    combat, table, mid = fight(tmp_path)
    G.use(combat, table, mid, "Weight Shift: Body Heavying")
    _, asked = G.use(combat, table, mid, "Fu (Short Axe)", answer(outcome=outcome))
    _, _, engine = cold(tmp_path, mid)
    q = next(q for q in asked if q["context"]["reaction_source_id"].endswith("gravity_heavying"))
    assert q["context"]["reactor_id"] == ME
    assert {o["id"] for o in q["choice"]["options"]} == {"push", "pull", "prone"}
    assert engine.state.actors[FOE].position.x == x
    # Adjacent targets cannot be pulled into the occupied attacker's square.
    assert bool(held(engine, FOE, "prone")) == (outcome == "prone")


def test_success_denies_reactions_until_target_next_turn(tmp_path):
    combat, table, mid = fight(tmp_path, dc=1)
    G.use(combat, table, mid, "Weight Shift: Body Heavying")
    G.use(combat, table, mid, "Fu (Short Axe)", answer())
    combat, table, engine = cold(tmp_path, mid)
    assert force_rolls(engine) == ["1d6"]
    assert held(engine, FOE, "reaction_denied")
    assert not held(engine, FOE, "prone")
    G.use(combat, table, mid, "End Turn")
    G.advance(combat, table, mid, FOE)
    _, _, engine = cold(tmp_path, mid)
    assert not held(engine, FOE, "reaction_denied")


@pytest.mark.parametrize("case", ["no-mode", "wrong-owner", "no-points", "decline", "thrown"])
def test_native_boundaries_do_not_spend_or_apply_rider(tmp_path, case):
    combat, table, mid = fight(tmp_path, owner=case != "wrong-owner", stamina=0 if case == "no-points" else 30)
    if case not in {"wrong-owner", "no-mode"}:
        G.use(combat, table, mid, "Weight Shift: Body Lightening")
    _, asked = G.use(combat, table, mid, "Fu (Short Axe) thrown" if case == "thrown" else "Fu (Short Axe)",
                     (lambda *_: False) if case == "decline" else answer())
    _, _, engine = cold(tmp_path, mid)
    assert not force_rolls(engine)
    assert engine.state.actors[ME].resources.get(STAMINA, 0) == (0 if case == "no-points" else 30)
    assert any(q["context"]["reaction_source_id"].endswith("gravity_weighted_strike") for q in asked) == (case == "decline")


def test_lightening_step_after_finishing_hit(tmp_path):
    combat, table, mid = fight(tmp_path, foe_hp=1)
    G.use(combat, table, mid, "Weight Shift: Body Lightening")
    G.use(combat, table, mid, "Fu (Short Axe)", answer("lightening"))
    _, _, engine = cold(tmp_path, mid)
    assert not engine.state.actors[FOE].active
    assert (engine.state.actors[ME].position.x, engine.state.actors[ME].position.y) == (1, 6), [
        (e.event_type, e.actor_id, {k: v for k, v in e.payload.items()
            if k in ('log', 'natural_result', 'hit', 'critical', 'destination', 'reason')})
        for e in engine.events if e.event_type in ('ATTACK_ROLLED', 'MOVEMENT_COMMITTED', 'PASSIVE_TRIGGERED')]
    assert engine.state.actors[ME].resources[STAMINA] == 29


def test_lightening_exempts_only_its_hit_target_from_opportunity_attacks(tmp_path):
    combat, table, mid = fight(tmp_path, other_position={'x': 3, 'y': 5})
    G.use(combat, table, mid, 'Weight Shift: Body Lightening')
    engine = combat._load_session(mid).engine
    use = next(c for c in engine.legal_candidates()
        if getattr(engine.action_catalog.get(c.source_definition_id), 'display_name', None) == 'Fu (Short Axe)'
        and c.target_ids == (FOE,))
    assert use.source_definition_id.endswith('.weapon.fu')  # the thrown sibling is not this trigger
    answers = []
    for _ in range(12):
        state = table.state(mid)
        result = table.act(mid, use.candidate_id, state['menu']['decision_id'],
            state['menu']['state_version'], state['last_sequence'], answers)
        if result['status'] == 'COMMITTED':
            break
        assert result['status'] == 'REACTION_REQUIRED'
        prompt = result['reaction']
        choice = prompt.get('choice') or {}
        reply = {**prompt['context'], 'selection': 'DECLINE'}
        if prompt['context']['reactor_id'] == OTHER:
            reply['selection'] = 'USE'
            if choice:
                axe = next((o['id'] for o in choice['options'] if 'fu' in o['id'].lower()
                            or 'short axe' in str(o.get('label', '')).lower()), None)
                reply['option_ids'] = [axe] if axe else (choice.get('preferred') or [choice['options'][0]['id']])[:1]
        else:
            picked = answer('lightening')(prompt, choice)
            if choice and picked is not False:
                reply.update(selection='USE', option_ids=list(picked))
        answers.append(reply)
    else:
        raise AssertionError('Lightening movement did not commit')
    _, _, engine = cold(tmp_path, mid)
    assert (engine.state.actors[ME].position.x, engine.state.actors[ME].position.y) == (1, 6), [
        (e.event_type, e.actor_id, {k: v for k, v in e.payload.items()
            if k in ('log', 'natural_result', 'hit', 'critical', 'destination', 'reason')})
        for e in engine.events if e.event_type in ('ATTACK_ROLLED', 'MOVEMENT_COMMITTED', 'PASSIVE_TRIGGERED')]
    assert any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == OTHER for e in engine.events)
    assert not any(e.event_type == 'ATTACK_ROLLED' and e.actor_id == FOE for e in engine.events)
    force = next(i for i, e in enumerate(engine.events) if e.event_type == 'DAMAGE_COMMITTED'
                 and e.actor_id == ME and e.payload.get('damage_type') == 'FORCE')
    other_attack = next(i for i, e in enumerate(engine.events) if e.event_type == 'ATTACK_ROLLED' and e.actor_id == OTHER)
    assert other_attack > force


def test_cp_payment_comes_from_attacker_qi(tmp_path):
    combat, table, mid = fight(tmp_path, primary="Qi")
    G.use(combat, table, mid, "Weight Shift: Body Lightening")
    G.use(combat, table, mid, "Fu (Short Axe)", answer(pool="qi"))
    _, _, engine = cold(tmp_path, mid)
    assert engine.state.actors[ME].resources[QI] == 29
    assert engine.state.actors[FOE].resources[QI] == 30
    assert force_rolls(engine) == ["1d6"]


def test_unarmed_hit_can_choose_a_rider(tmp_path):
    combat, table, mid = fight(tmp_path)
    G.use(combat, table, mid, "Weight Shift: Body Heavying")
    G.use(combat, table, mid, "Unarmed Strike", answer())
    _, _, engine = cold(tmp_path, mid)
    assert held(engine, FOE, "prone")
    assert engine.state.actors[ME].resources[STAMINA] == 29


def local_primary(combat, candidate_id):
    """A deterministic local seat; no model transport is used."""
    from combat.gate4_adapters import ManualControllerAdapter
    original = combat.controller

    class Controller:
        def choose_primary_action(self, context):
            return ManualControllerAdapter(lambda _: (candidate_id, ())).choose_primary_action(context)

        def __getattr__(self, name):
            return getattr(original, name)

    combat.controller = Controller()


@pytest.mark.parametrize("auto_turn", [False, True])
def test_human_off_turn_opportunity_hit_prompts_and_resets_limit(tmp_path, auto_turn):
    combat, table, mid = fight(tmp_path)
    G.use(combat, table, mid, "Weight Shift: Body Lightening")
    # A use on our turn must not suppress the use on the mover's later turn.
    G.use(combat, table, mid, "Fu (Short Axe)", answer("lightening", step="cell:3,6"))
    combat, table, engine = cold(tmp_path, mid)
    assert engine.state.actors[ME].resources[STAMINA] == 29
    G.use(combat, table, mid, "End Turn")
    G.advance(combat, table, mid, FOE)
    state = table.state(mid)
    move = next(m for m in state["menu"]["moves"] if m["destination"] == {"x": 6, "y": 6})
    cid = move["candidate_id"]
    if auto_turn:
        local_primary(combat, cid)
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    answers, asked = [], []
    for _ in range(12):
        result = table.auto_step(mid, 0, answers) if auto_turn else G.G._table_send(table, mid, cid, answers)
        if result["status"] == "COMMITTED":
            break
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        asked.append(prompt)
        reply = {**prompt["context"], "selection": "USE"}
        choice = prompt.get("choice")
        if choice:
            source = prompt["context"]["reaction_source_id"]
            if source.endswith("gravity_weighted_strike"):
                assert prompt["context"]["reactor_id"] == ME
                assert "Opportunity Attack" in str(prompt) and "foe" in str(prompt)
                reply["option_ids"] = ["lightening:stamina"]
            elif source.endswith("rider_step"):
                reply["option_ids"] = ["cell:3,6"]
            else:
                reply["selection"] = "DECLINE"
        answers.append(reply)
    assert result["status"] == "COMMITTED"
    assert any(q["context"]["reaction_source_id"].endswith("gravity_weighted_strike") for q in asked)
    _, _, engine = cold(tmp_path, mid)
    assert engine.state.actors[ME].resources[STAMINA] == 28


def test_automatic_actor_chooses_without_human_prompt(tmp_path):
    combat, table, mid = fight(tmp_path)
    G.use(combat, table, mid, "Weight Shift: Body Heavying")
    engine = combat._load_session(mid).engine
    candidate = next(c for c in engine.legal_candidates() if c.display_name == "Fu (Short Axe) attack" and FOE in c.target_ids)
    local_primary(combat, candidate.candidate_id)
    combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    result = table.auto_step(mid, 0)
    assert result["status"] == "COMMITTED", result
    _, _, engine = cold(tmp_path, mid)
    assert engine.state.actors[ME].resources[STAMINA] == 29
    assert force_rolls(engine) == ["1d6"]
