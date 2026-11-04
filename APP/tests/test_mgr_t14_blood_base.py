"""Native table regressions for the assigned Blood base rows; no model or GUI.

Characters acquire Blood through table advancement, then compile its automatic
base grants. Every action commits through TabletopService; C5's transaction
helper also compares a cold CombatService reload after every commit.
"""
import copy

import pytest

from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from canonical_catalog.service import CanonicalCatalogAuthorityService
from combat.typed_executor import bears_mark
from tests import test_c5_review as R
from tests import test_table_advance as A

ROOT, ME, FOE = R.C.ROOT, R.C.ME, R.C.AN
BLOOD = "tianxia.sphere.blood"


def _acquire(path, cl):
    source = A._service(path, CanonicalCatalogAuthorityService(ROOT))
    source.add_advancement(A.PID, "sphere", BLOOD)
    sheet = copy.deepcopy(source.combat._factory_owner_sheet(A.PID))
    sheet["identity"]["cultivation_level"] = cl
    block = sheet["spheres_and_talents"]
    assert {"BLOOD_BASE_BLOOD_THREAD", "BLOOD_BASE_COAGULATE"} <= set(block["automatic_sphere_component_record_ids"])
    assert "BLOOD_BASE_COAGULATE" not in block["learned_talent_record_ids"]
    # Keep this packet's native encounter limited to the acquired Blood sphere.
    block["sphere_record_ids"] = [BLOOD]
    block["learned_talent_record_ids"] = []
    return sheet


def _table(tmp_path, *, cl=10):
    sheet = _acquire(tmp_path / "learning", cl)
    bundles = [compile_character(sheet, actor_id=who, reaction_plan={"ask": True}) for who in (ME, FOE)]
    for i, bundle in enumerate(bundles):
        bundle["actor_template"].update(initiative_bonus=1000 if not i else -1000, maximum_hp=2000)
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
    combat = CombatService(ROOT, tmp_path / "combat")
    session = combat.persistence.create_match(match_seed="BLOOD-BASE-T14", typed_bundles=tuple(bundles),
        roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    combat._read_metadata(session.match_id, session)
    for who in (ME, FOE):
        combat.set_controller_mode(session.match_id, actor_id=who, controller_mode="MANUAL")
    return combat, TabletopService(combat, combat.userdata_root), session.match_id


def _name(combat, mid, prefix, target):
    return next(c["display_name"] for c in combat.decision(mid)["context"]["legal_candidates"]
                if c["display_name"].startswith(prefix) and c["target_ids"] == [target])


def _use(combat, table, mid, prefix, target, accept=True):
    return R._act(combat, table, mid, _name(combat, mid, prefix, target), target=target,
                  choices={"consent": lambda options: ["accept" if accept else "refuse"]})


def _auto_use(combat, table, mid, prefix, target, accept, monkeypatch):
    from combat.gate4_adapters import ManualControllerAdapter

    # Select only the AI's primary action deterministically. Native automatic
    # recipient decisions, human prompts, payments and commits remain intact.
    def choose(context):
        candidate = next(c for c in context.legal_candidates
                         if c.display_name.startswith(prefix) and c.target_ids == (target,))
        return ManualControllerAdapter(lambda context: (candidate.candidate_id, ())).choose_primary_action(context)

    monkeypatch.setattr(combat.controller, "choose_primary_action", choose)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    answers, prompts = [], []
    for _ in range(4):
        result = table.auto_step(mid, 0, answers)
        if result["status"] == "COMMITTED":
            loaded = CombatService(ROOT, combat.userdata_root)._load_session(mid).engine
            assert loaded.state.model_dump(mode="json") == combat._load_session(mid).engine.state.model_dump(mode="json")
            return loaded, prompts
        assert result["status"] == "REACTION_REQUIRED", result
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        prompt = result["reaction"]
        prompts.append(prompt)
        answers.append({**prompt["context"], "selection": "USE", "option_ids": ["accept" if accept else "refuse"]})
    raise AssertionError("AI action did not finish recipient consent")


@pytest.mark.parametrize("accept", [True, False])
def test_willing_hostile_thread_asks_recipient_and_commits_without_attack(tmp_path, accept):
    combat, table, mid = _table(tmp_path)
    before = dict(combat._load_session(mid).engine.state.actors[ME].resources)
    engine, prompts = _use(combat, table, mid, "Blood Thread: willing creature (", FOE, accept)
    target = engine.state.actors[FOE]
    assert bears_mark(target, ME, "Blood Thread") is accept
    assert target.current_hp == target.maximum_hp
    assert engine.state.actors[ME].resources == before
    assert len(prompts) == 1 and prompts[0]["context"]["reactor_id"] == FOE
    assert not any(e.event_type == "ATTACK_ROLLED" for e in engine.events)
    if accept:
        mark = next(c for c in target.conditions.values() if "blood_thread" in c.condition_id)
        from combat.ext.effect_durations import round_token
        assert mark.expires_on == round_token(engine, 10)


@pytest.mark.parametrize("caster_mode", ["MANUAL", "LOCAL_AUTO"])
@pytest.mark.parametrize("accept", [True, False])
def test_coagulate_manual_recipient_consents_on_human_and_ai_turns(tmp_path, caster_mode, accept, monkeypatch):
    combat, table, mid = _table(tmp_path)
    engine, _ = _use(combat, table, mid, "Blood Thread: willing creature (", FOE)
    before = dict(engine.state.actors[ME].resources)
    combat.set_controller_mode(mid, actor_id=ME, controller_mode=caster_mode)
    if caster_mode == "LOCAL_AUTO":
        engine, prompts = _auto_use(combat, table, mid, "Coagulate: Temporary HP (", FOE, accept, monkeypatch)
    else:
        engine, prompts = _use(combat, table, mid, "Coagulate: Temporary HP (", FOE, accept)
    assert len(prompts) == 1 and prompts[0]["context"]["reactor_id"] == FOE
    action = next(a for a in engine.action_catalog.values() if a.owner_id == ME and a.display_name == "Coagulate: Temporary HP")
    numbers = action.parameters["typed"]["numbers"]
    assert engine.state.actors[FOE].temporary_hp == (numbers["pb"] + numbers["key_mod"] if accept else 0)
    assert sum(before.values()) - sum(engine.state.actors[ME].resources.values()) == 1


def test_ai_hostile_recipient_refuses_automatically(tmp_path):
    combat, table, mid = _table(tmp_path)
    combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")
    engine, prompts = _use(combat, table, mid, "Blood Thread: willing creature (", FOE)
    assert not prompts
    assert not bears_mark(engine.state.actors[FOE], ME, "Blood Thread")


def test_coagulate_requires_the_casters_thread_not_another_owners(tmp_path):
    combat, table, mid = _table(tmp_path)
    R._act(combat, table, mid, "End turn")
    _use(combat, table, mid, "Blood Thread: willing creature", FOE)
    R._act(combat, table, mid, "End turn")
    candidates = combat.decision(mid)["context"]["legal_candidates"]
    assert not any(c["display_name"].startswith("Coagulate") and FOE in c["target_ids"] for c in candidates)


def test_unowned_characters_get_no_blood_actions():
    sheet = copy.deepcopy(A.BASE)
    bundle = compile_character(sheet, actor_id=ME)
    assert not any(a["display_name"].startswith(("Blood Thread", "Coagulate")) for a in bundle["action_catalog"])
