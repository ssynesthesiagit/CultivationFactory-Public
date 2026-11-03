"""Borrowed Lifespan's per-creature use survives real table transactions."""

import json
import zipfile

import pytest

from combat.ext.fate_riders import BORROWED, borrowed_once_each
from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_carry import KIT
from tests.test_r9i_karma_persistence import PLAYER, FOE, act, end_turn

ALLY = FACTORY_ACTOR_PREFIX + "r9f-ally"
SPENT = "_round_fate_borrowed_lifespan:" + ALLY


def fixture(tmp_path, talent=BORROWED, *, ally_talents=(), ally_skills=(), caster_pb=4, ally_pb=4, ally_ask=False, caster_talents=()):
    documents = [sheet([talent, *caster_talents], cl=15), sheet(ally_talents, cl=15, kit={"starting_kit": KIT} if talent != BORROWED else None),
                 sheet([], cl=15, kit={"starting_kit": KIT})]
    documents[0]["identity"]["proficiency_bonus"] = caster_pb
    documents[1]["identity"]["proficiency_bonus"] = ally_pb
    if ally_skills:
        documents[1]["ability_scores_and_statistics"]["skills"] = list(ally_skills)
    documents[0]["ability_scores_and_statistics"]["primary_resource"]["maximum"] = 80
    documents[1]["ability_scores_and_statistics"]["hit_points"]["maximum"] = 1 if talent == BORROWED else 100
    documents[1]["ability_scores_and_statistics"]["armor_class"]["base_value"] = 1
    ids = (PLAYER, ALLY, FOE)
    for actor_id, document in zip(ids, documents):
        folder = tmp_path / "portable_characters" / actor_id.removeprefix(FACTORY_ACTOR_PREFIX)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    bundles = [compile_character(doc, actor_id=actor_id, reaction_plan={"ask": True} if actor_id == PLAYER or (actor_id == ALLY and ally_ask) else {})
               for actor_id, doc in zip(ids, documents)]
    mid = combat._finish_factory_match(
        bundles, list(ids), {PLAYER: "team:factory", ALLY: "team:factory", FOE: "team:opponents"},
        {PLAYER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 5, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [PLAYER, ALLY], [FOE],
        control_modes={a: "MANUAL" for a in ids}, match_seed="H5-CHOICES",
        display_name="Fate persistence", maximum_rounds=10)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != FOE:
        end_turn(table, mid)
    return combat, table, mid


def attack_id(table, mid):
    return next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"]
                if g["label"] == "Bi Shou (Dagger) attack" for o in g["options"]
                if o.get("target_ids") == [ALLY])


def pass_twist(send, answers=()):
    """Decline the automatic Fate base row so this test isolates the talisman."""
    result = send(answers)
    if result["status"] == "REACTION_REQUIRED":
        context = result["reaction"]["context"]
        if context["reaction_source_id"] == "reaction:typed.TAL_FATE_TWIST_OF_FATE":
            result = send([{**context, "selection": "DECLINE"}, *answers])
    return result


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("repayment", ["oath", "notice", "exhaustion", "necrotic", None])
def test_borrowed_lifespan_preview_commit_reload_limit(tmp_path, auto_turn, repayment):
    combat, table, mid = fixture(tmp_path)
    cid = attack_id(table, mid)
    if auto_turn:
        real = combat.controller

        class AttackController:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _context: (cid, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = AttackController()
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="LOCAL_AUTO")

    def send(answers=()):
        # Round 24 reserves every earlier answer with the pending request.
        # pass_twist supplied this prefix on the first call; retain it when
        # callers provide only the talisman's subsequent answers.
        pending = table.state(mid).get('pending_action') or {}
        prefix = [row for row in pending.get('reactions') or []
                  if row.get('reaction_source_id') == 'reaction:typed.TAL_FATE_TWIST_OF_FATE']
        answers = [*prefix, *answers]
        return pass_twist(lambda supplied: table.auto_step(mid, 0, list(supplied))
                          if auto_turn else act(table, mid, cid, supplied), answers)

    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send()
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == PLAYER
    assert prompt["context"]["reaction_source_id"].startswith("choice:life.survive:")
    assert prompt["context"]["reaction_source_id"].endswith(BORROWED)
    assert send()["reaction"] == prompt
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": "USE" if repayment else "DECLINE"}
    if repayment:
        answer["option_ids"] = ["use"]
    result = send([answer])
    if repayment:
        assert result["status"] == "REACTION_REQUIRED", result
        cost = result["reaction"]
        assert cost["context"]["reactor_id"] == PLAYER
        assert cost["context"]["reaction_source_id"] == "choice:needle.borrowed_lifespan"
        assert send([answer])["reaction"] == cost
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        result = send([answer, {**cost["context"], "selection": "USE", "option_ids": [repayment]}])
    assert result["status"] == "COMMITTED", result
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    loaded = combat._load_session(mid)
    player, ally = loaded.engine.state.actors[PLAYER], loaded.engine.state.actors[ALLY]
    assert player.resources["resource:core.qi"] == (70 if repayment else 80)
    assert player.turn_flags.get(SPENT, 0) == int(bool(repayment))
    assert ally.current_hp == (1 if repayment else 0)
    assert loaded.mechanical.replay()["status"] == "PASS"
    if not repayment:
        return
    if repayment == "necrotic":
        assert player.current_hp == 30
    elif repayment == "notice":
        from combat.ext.d20_rewrite import pool_id

        assert player.resources[pool_id(player, "heaven_s_notice")] == 2
    elif repayment == "exhaustion":
        assert any("exhaustion" in c.condition_id for c in ally.conditions.values())
    # Preview clones agree before any further turn, and turn-start resets cannot
    # reopen this creature's Long Rest use after a disk reload.
    clone = CombatService._clone_engine(ROOT, loaded.engine)
    assert borrowed_once_each(clone, clone.state.actors[PLAYER], clone.state.actors[ALLY], {"feature_id": BORROWED}) is False
    if auto_turn:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="MANUAL")
    end_turn(table, mid)
    while table.state(mid)["menu"]["actor_id"] != FOE:
        end_turn(table, mid)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[PLAYER].reaction_available
    assert loaded.engine.state.actors[PLAYER].turn_flags[SPENT] == 1
    assert pass_twist(lambda answers: act(table, mid, attack_id(table, mid), answers))["status"] == "COMMITTED"
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[ALLY].current_hp == 0
    assert loaded.engine.state.actors[PLAYER].resources["resource:core.qi"] == 70
    assert loaded.mechanical.replay()["status"] == "PASS"


def test_borrowed_limit_is_per_caster_per_creature_and_clone_inert_for_other_rows():
    from tests.test_riders_lane9 import ME, ALLY as ENGINE_ALLY, THEM, _fate_fight, _stab

    engine = _fate_fight(["BORROWED_LIFESPAN_TALISMAN"], them_at=(4, 7))
    ally = engine.state.actors[ENGINE_ALLY]
    ally.armor_class, ally.current_hp = -50, 1
    _stab(engine, target=ENGINE_ALLY)
    clone = CombatService._clone_engine(ROOT, engine)
    caster, protected, other = (clone.state.actors[a] for a in (ME, ENGINE_ALLY, THEM))
    row = {"feature_id": BORROWED}
    assert borrowed_once_each(clone, caster, protected, row) is False
    assert borrowed_once_each(clone, caster, other, row) is True
    assert borrowed_once_each(clone, other, protected, row) is True
    assert borrowed_once_each(clone, caster, protected, {"feature_id": "other"}) is None
