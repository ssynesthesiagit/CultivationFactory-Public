"""L41 real-owner table regressions; private inputs stay outside the repository.

Ning Kai is compiled unchanged. Test-only actions provide controlled damage,
not character abilities. An evented preparation action wounds him to 4 HP
without a reaction checkpoint, then the measured blow uses the normal intent
and damage handoff. No engine method or state is patched. All stimuli, choices,
and resulting state are sealed in table transactions and mechanically replayed.
"""
import json
import os
from pathlib import Path
import zipfile

import pytest

from combat import ext
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.r1i_service_support import force_ai_candidate

PID = "b95b3754-eeae-49d6-9dbd-6bbd4bb9d4f9"
ME = "actor:factory." + PID
FOE = "actor:factory.l41-opponent"
GUARD = "tianxia.path.body_refining.feature.stamina_guard"
BLOOD = "tianxia.path.body_refining.feature.blood_pump"
USE_POOL = "resource:uses.reaction:typed." + BLOOD
STAMINA = "resource:core.stamina"


def fresh(path, mid):
    combat = CombatService(ROOT, path)
    return combat, TabletopService(combat, path), combat._load_session(mid)


def send(table, mid, needle, answers=(), *, auto=False):
    menu = table.state(mid)["menu"]
    if auto:
        return table.auto_step(mid, 0, list(answers))
    cid = menu["end_turn"] if needle == "end" else next(
        o["candidate_id"] for g in menu["actions"] if needle in g["source_definition_id"]
        for o in g["options"] if not o.get("target_ids") or ME in o["target_ids"])
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))


def commit(table, mid, needle):
    answers = []
    for _ in range(20):
        result = send(table, mid, needle, answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return
        answers.append({**result["reaction"]["context"], "selection": "DECLINE"})
    pytest.fail("Repeated unrelated prompt")


def fixture(path, monkeypatch, *, ask=True, bell=False, buffered=False,
            affordable=None, used=False):
    source = Path(os.environ.get("L41_PORTABLE_ROOT",
        "/var/tmp/auto-audit/astra/lock3-inputs/portable_characters")) / PID / "current.zip"
    if not source.exists():
        pytest.skip("Set L41_PORTABLE_ROOT to the owner's portable-character inputs")
    with zipfile.ZipFile(source) as archive:
        owner = json.loads(archive.read("Tianxia_Owner_Character_Sheet_v1.json"))
    owned = owner["path_and_subpath"]["path_feature_record_ids"]
    assert {GUARD, BLOOD, "tianxia.path.body_refining.feature.core_tempering_expression",
            "tianxia.path.body_refining.feature.perfected_core_tempering"} <= set(owned)
    mine = compile_character(owner, actor_id=ME)
    # Auto/custom holds unrelated defenses back; Ask me instead declines them.
    off = [r["feature_id"] for r in mine["typed_reactions"] if r["feature_id"] not in {GUARD, BLOOD}]
    mine = compile_character(owner, actor_id=ME, reaction_plan={"ask": ask, "off": off})
    opponent = compile_character(sheet([], cl=20), actor_id=FOE)

    def prepare(ctx, effect):
        target = ctx.engine.state.actors[ME]
        ctx.engine._commit_damage(target, target.current_hp - 4, "FORCE", ctx.source,
                                 ctx.actor.entity_id, None, reaction_depth=0)
        if buffered:
            ctx.engine._grant_temp_hp(target, 100, ctx.source, ctx.actor.entity_id)
        if affordable is not None:
            ctx.engine._spend_resource(target, STAMINA,
                target.resources[STAMINA] - affordable, ctx.source)
        if used:
            ctx.engine._spend_resource(target, USE_POOL, 1, ctx.source)

    def blow(ctx, effect):
        ctx.engine._commit_damage(ctx.engine.state.actors[ME], 80, "FORCE", ctx.source,
                                 ctx.actor.entity_id, ctx.intent, reaction_depth=0)

    ext.effects()
    monkeypatch.setitem(ext._EFFECTS, "l41_prepare", prepare)
    monkeypatch.setitem(ext._EFFECTS, "l41_blow", blow)
    for bundle in [mine, opponent]:
        aid = bundle["actor_id"]
        for name in (["prepare", "blow"] if aid == ME else ["blow"]):
            action = ActionDefinition(source_definition_id=f"action:l41.{aid}.{name}",
                display_name="Prepare wounds" if name == "prepare" else "Training blow",
                owner_id=aid, economy=EconomyKind.NONE if name == "prepare" else EconomyKind.ACTION,
                resolution_kind="TYPED", target_kind="SELF" if aid == ME else "HOSTILE_ENTITY",
                range_ft=5, parameters={"typed": {"effects": [{"type": "l41_" + name}],
                    "numbers": {}, "riders": []}})
            bundle["action_catalog"].append(action.model_dump(mode="json"))
            bundle["actor_template"]["action_ids"].append(action.source_definition_id)
        bundle.pop("bundle_sha256")
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    combat = CombatService(ROOT, path)
    table = TabletopService(combat, path)
    mid = combat._finish_factory_match([mine, opponent], [ME, FOE],
        {ME: "team:a", FOE: "team:b"}, {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [FOE],
        control_modes={ME: "MANUAL", FOE: "MANUAL"}, match_seed="SOL41",
        display_name="L41 regression", maximum_rounds=10)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != ME:
        commit(table, mid, "end")
    if bell:
        commit(table, mid, "core_tempering_expression.golden_bell")
        commit(table, mid, "golden_bell_circulation")
    commit(table, mid, ".prepare")
    assert fresh(path, mid)[2].engine.state.actors[ME].current_hp == 4
    return combat, table, mid


def exercise(path, monkeypatch, *, selection="USE", ai_turn=False, automatic=False,
             ai_reactor=False, bell=False, buffered=False, affordable=None, used=False):
    combat, table, mid = fixture(path, monkeypatch, ask=not automatic, bell=bell,
                                buffered=buffered, affordable=affordable, used=used)
    if ai_turn:
        commit(table, mid, "end")
        while table.state(mid)["menu"]["actor_id"] != FOE:
            commit(table, mid, "end")
    if ai_reactor:
        combat.set_controller_mode(mid, actor_id=ME, controller_mode="LOCAL_AUTO")
    before = fresh(path, mid)[2].engine.state.model_dump(mode="json")
    answers, prompts = [], []
    for _ in range(20):
        # Reconstruct the table/service between every Ask me answer as well as
        # after commit. The action's deterministic preview must ask only once.
        combat, table, _ = fresh(path, mid)
        if ai_turn or ai_reactor:
            engine = combat._load_session(mid).engine
            cid = next(c.candidate_id for c in engine.legal_candidates()
                       if c.source_definition_id.endswith(".blow") and ME in c.target_ids)
            force_ai_candidate(combat, mid, ME if ai_reactor else FOE, cid)
        result = send(table, mid, ".blow", answers, auto=ai_turn or ai_reactor)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            break
        prompt = result["reaction"]
        prompts.append(prompt)
        assert fresh(path, mid)[2].engine.state.model_dump(mode="json") == before
        guard = prompt["reaction"] == "Stamina Guard"
        # Ask me can expose source-backed plug-in defenses outside the shared
        # reaction rows; decline them without altering Ning Kai's abilities.
        pump = prompt["reaction"] == "Blood Pump"
        answer = {**prompt["context"], "selection": "USE" if guard else selection if pump else "DECLINE"}
        if answer["selection"] == "USE":
            answer["option_ids"] = ["1" if guard else "use"]
        answers.append(answer)
    else:
        pytest.fail("Reaction offered more than once")
    loaded = fresh(path, mid)[2]
    assert loaded.verify()["status"] == "PASS"
    assert loaded.mechanical.replay()["status"] == "PASS"
    assert loaded.engine.state.model_dump(mode="json") == combat._load_session(mid).engine.state.model_dump(mode="json")
    events = loaded.engine.events
    guards = [e for e in events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == GUARD]
    pumps = [e for e in events if e.event_type == "REACTION_RESOLVED" and e.source_definition_id == BLOOD]
    assert len(guards) == 1
    rolls = [r for r in loaded.engine.rolls if r.reason == "DAMAGE_SOAK:" + GUARD]
    assert len(rolls) == 1
    assert rolls[0].expression == f"{guards[0].payload['spend']}d{12 if bell else 10}+0"
    actor = loaded.engine.state.actors[ME]
    eligible = not buffered and not used and (affordable is None or affordable >= 7)
    pump_used = eligible and (selection == "USE" or automatic or ai_reactor)
    assert len(pumps) == int(pump_used)
    assert actor.resources[USE_POOL] == (0 if used or pump_used else 1)
    assert actor.resources[STAMINA] == before["actors"][ME]["resources"][STAMINA] - guards[0].payload["spend"] - 6 * pump_used
    assert actor.current_hp == (4 if buffered else 1 if pump_used else 0)
    assert not actor.reaction_available
    asks = [p for p in prompts if p["reaction"] == "Blood Pump"]
    assert len(asks) == int(eligible and not ai_reactor)
    if asks:
        assert "6 Stamina" in asks[0]["cost"]
        assert "Ning Kai" in asks[0]["trigger"]
        assert asks[0]["action"] == "Training blow"
        assert "Training blow" in asks[0]["trigger"]
        assert asks[0]["affected"] == "Ning Kai"
    if buffered:
        assert actor.temporary_hp == 100 - guards[0].payload["pending_after"]
    return loaded


@pytest.mark.parametrize("ai_turn", [False, True])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_lethal_guard_then_blood_pump_once(tmp_path, monkeypatch, ai_turn, selection):
    exercise(tmp_path, monkeypatch, ai_turn=ai_turn, selection=selection)


@pytest.mark.parametrize("ai_reactor", [False, True])
def test_automatic_survival(tmp_path, monkeypatch, ai_reactor):
    exercise(tmp_path, monkeypatch, automatic=not ai_reactor, ai_reactor=ai_reactor)


@pytest.mark.parametrize("ai_turn", [False, True])
def test_temporary_hp_prevents_false_survival_offer(tmp_path, monkeypatch, ai_turn):
    exercise(tmp_path, monkeypatch, ai_turn=ai_turn, buffered=True)


def test_perfected_bell_records_d12_and_replays(tmp_path, monkeypatch):
    exercise(tmp_path, monkeypatch, bell=True, ai_turn=True)


@pytest.mark.parametrize("options", [{"affordable": 6}, {"used": True}])
def test_unavailable_pump_is_not_offered(tmp_path, monkeypatch, options):
    exercise(tmp_path, monkeypatch, **options)
