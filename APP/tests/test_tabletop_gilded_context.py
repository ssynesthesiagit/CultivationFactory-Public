"""Gilded Guard names the action and attacker that caused its damage packet."""
import shutil
import pytest

from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_carry import KIT
from tests.test_tabletop_pending_action_resume import reopen, resume, commit_count

ME = "actor:factory.h58-gilded"
FOE = "actor:factory.h58-gilded-foe"
GUARD = "tianxia.path.body_refining.feature.stamina_guard"
GILDED = "tianxia.subpath.body.goruden.feature.gilded_bones"


def gilded_fight(actual):
    docs = [sheet([GUARD, GILDED], cl=12, primary="Stamina", kit={"starting_kit": KIT}),
            sheet([], cl=12, kit={"starting_kit": KIT})]
    for doc, name in zip(docs, ("Guard Owner", "Dagger Attacker")):
        doc["identity"]["display_name"] = name
    docs[0]["identity"]["path"] = "Body Refining"
    bundles = [compile_character(doc, actor_id=aid, reaction_plan={"ask": True} if aid == ME else None)
               for doc, aid in zip(docs, (ME, FOE))]
    combat = CombatService(ROOT, actual)
    table = TabletopService(combat, actual)
    match_id = combat._finish_factory_match(bundles, [ME, FOE], {ME: "team:factory", FOE: "team:opponents"},
        {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}, combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [ME], [FOE], control_modes={ME: "MANUAL", FOE: "MANUAL"}, match_seed="H58-GILDED",
        display_name="Gilded Guard prompt", maximum_rounds=10)["match_id"]
    return combat, table, match_id


def test_gilded_guard_prompt_identifies_damage_source_and_replays(tmp_path, monkeypatch):
    from tests.sol109_support import accurate_attacks
    accurate_attacks(monkeypatch, FOE)
    actual, reference = tmp_path / "actual", tmp_path / "reference"
    combat, table, match_id = gilded_fight(actual)
    shutil.copytree(actual, reference)
    ref = TabletopService(CombatService(ROOT, reference), reference)
    state = table.state(match_id)
    found = None
    committed_guard = False
    for _step in range(60):
        if state["presentation"]["terminal"]:
            break
        menu, after = state["menu"], state["last_sequence"]
        method = "act" if menu.get("manual") else "auto_step"
        cid = menu.get("end_turn")
        if menu["actor_id"] == FOE:
            cid = next((option["candidate_id"] for group in menu.get("actions", [])
                        if ".weapon." in group["source_definition_id"] and "#thrown" not in group["source_definition_id"]
                        for option in group["options"] if ME in option["target_ids"]), cid)
        prefix = (match_id, cid, menu["decision_id"], menu["state_version"], after) if method == "act" else (match_id, after)
        answers = []
        for _attempt in range(12):
            result = getattr(table, method)(*prefix, answers)
            assert result == getattr(ref, method)(*prefix, answers)
            if result["status"] != "REACTION_REQUIRED":
                break
            prompt = result["reaction"]
            answer = {**prompt["context"], "selection": "USE"}
            if prompt.get("choice"):
                answer["option_ids"] = [prompt["choice"]["options"][0]["id"]]
            if prompt["context"]["reaction_source_id"] == "choice:needle.gilded_guard":
                found = prompt
                pending = result["state"]["pending_action"]
                assert pending["reactions"] == answers and answers
                before = commit_count(table, match_id)
                table = reopen(table, actual)
                assert table.state(match_id)["pending_action"] == pending
                # An empty autoplay/click retry must not drop consent/spend answers.
                assert resume(table, match_id, pending, [])["reaction"] == prompt
            answers.append(answer)
        if found:
            assert result["status"] == "COMMITTED"
            assert commit_count(table, match_id) == before + 1
            committed_guard = True
            break
        state = result["state"]
    assert found is not None, "manual damage guard was not prompted"
    assert committed_guard
    assert found["action"] == "Bi Shou (Dagger) attack"
    assert "Dagger Attacker" in found["trigger"]
    assert found["affected"] == "Guard Owner"
    session = combat._load_session(match_id)
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"
    assert session.engine.state.model_dump(mode="json") == ref.combat._load_session(match_id).engine.state.model_dump(mode="json")


@pytest.mark.parametrize("kind", ["hazard", "derived", "nested"])
def test_nonattack_gilded_damage_reopens_answers_commits_and_replays(tmp_path, monkeypatch, kind):
    """Inject packets through documented hooks inside an accepted table action.

    No core method patching: the normal packet/preview/journal paths run, including
    a nested non-attack packet inside an attack's incoming-damage hook.
    """
    from combat import ext
    from combat.damage_context import AttackDamage
    combat, table, mid = gilded_fight(tmp_path)
    ext.effects()
    source = next(a.source_definition_id for a in combat._load_session(mid).engine.action_catalog.values()
                  if a.owner_id == FOE and ".weapon." in a.source_definition_id)
    packet = AttackDamage(source, FOE, ME, 0, "roll:synthetic", 18, 24, False)
    def inject(engine, event_type, kwargs):
        if event_type != "HOLD_POSITION_COMMITTED":
            return
        target = engine.state.actors[ME]
        if kind == "nested":
            engine._commit_damage(target, 10, "PIERCING", source, FOE, engine._active_intent,
                                  reaction_depth=0, attack_context=packet)
        else:
            engine._commit_damage(target, 10, "FORCE", "test:" + kind, ME if kind == "hazard" else FOE,
                                  engine._active_intent, reaction_depth=0)
    def nested(engine, target, amount, damage_type, source_id, source_actor_id):
        if kind == "nested" and engine.damage_context() == packet:
            engine._commit_damage(target, 10, "FORCE", "test:derived", ME, engine._active_intent, reaction_depth=1)
            assert engine.damage_context() == packet  # restored after successful inner commit
    monkeypatch.setitem(ext._HOOKS, "event", [*ext._HOOKS.get("event", []), inject])
    monkeypatch.setitem(ext._HOOKS, "incoming_damage", [*ext._HOOKS.get("incoming_damage", []), nested])
    state = table.state(mid)
    menu = state["menu"]
    cid = next(g["options"][0]["candidate_id"] for g in menu["actions"] if g["source_definition_id"] == "system:combat.hold_position")
    answers, seen = [], False
    count = commit_count(table, mid)
    for _ in range(12):
        result = table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, answers)
        if result["status"] == "COMMITTED":
            break
        prompt = result["reaction"]
        if prompt["context"]["reaction_source_id"] == "choice:needle.gilded_guard":
            seen = True
            assert prompt["action"] == prompt["trigger_actor"] == ""
            assert "Dagger Attacker" not in prompt["trigger"]
            table = reopen(table, tmp_path)
            assert table.state(mid)["pending_action"]["reactions"] == answers
        answer = {**prompt["context"], "selection": "USE"}
        if prompt.get("choice"):
            answer["option_ids"] = [prompt["choice"]["options"][0]["id"]]
        answers.append(answer)
    assert seen and result["status"] == "COMMITTED"
    assert commit_count(table, mid) == count + 1
    session = table.combat._load_session(mid)
    assert session.engine.damage_context() is None
    assert session.verify()["status"] == session.mechanical.replay()["status"] == "PASS"


def test_gilded_context_uses_only_current_packet(monkeypatch):
    """Hazards/derived damage never inherit old attacks; nested attacks name themselves."""
    from types import SimpleNamespace
    from combat.damage_context import AttackDamage
    from combat.ext import goruden, needle
    target = SimpleNamespace(entity_id=ME, display_name="Guard Owner")
    attacker = SimpleNamespace(entity_id=FOE)
    nested = SimpleNamespace(entity_id="actor:nested")
    engine = SimpleNamespace(
        typed_passive_rows={ME: [{"block": "path_rider", "kind": "gilded_guard"}]},
        state=SimpleNamespace(actors={ME: target, FOE: attacker, nested.entity_id: nested}, event_sequence=9),
        events=[SimpleNamespace(actor_id=FOE, source_definition_id="old:attack", target_ids=[ME])],
        action_catalog={"nested:attack": SimpleNamespace(display_name="Opportunity Attack")})
    captured = []
    def ask(*args, **kwargs):
        captured.append(kwargs["prompt_context"])
        return ["standard"]
    monkeypatch.setattr(needle, "ask", ask)
    row = {"feature_id": GUARD}
    dice = SimpleNamespace(sides=10)
    for _kind in ("hazard", "derived", "nested non-attack"):
        engine.damage_context = lambda: None
        goruden.gilded_guard(engine, target, row, 1, dice)
        assert captured[-1] == {"source_definition_id": "", "action_name": "", "action_actor_id": "", "affected_id": ME}
    packet = AttackDamage("nested:attack", nested.entity_id, ME, 0, "roll:1", 19, 24, False)
    engine.damage_context = lambda: packet
    goruden.gilded_guard(engine, target, row, 1, dice)
    assert captured[-1]["action_actor_id"] == nested.entity_id
    assert captured[-1]["action_name"] == "Opportunity Attack"
    # Explicit unknown provenance also prevents the presentation layer inferring history.
    table = TabletopService.__new__(TabletopService)
    monkeypatch.setattr(table, "_names_for", lambda _: ({ME: "Guard Owner", FOE: "Old Attacker"}, {"old:attack": "Old Attack"}))
    prompt = table._reaction_prompt_fields("unused", {
        "reactor_id": ME, "reaction_source_id": "choice:needle.gilded_guard", "attacking_actor_id": FOE,
        "extension_choice": {"option_ids": ["standard"]},
        "recent_events": [{"actor_id": FOE, "source_definition_id": "old:attack"}],
        "choice_trigger": {"source_definition_id": "", "action_name": "", "action_actor_id": "", "affected_id": ME,
                           "prompt": "Choose dice against this damage."}})
    assert prompt["action"] == prompt["trigger_actor"] == ""
    assert "Old" not in prompt["moment"]
