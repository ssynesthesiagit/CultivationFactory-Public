"""R9 integration: paid Karma obligations and limits survive table transactions."""

import json
import zipfile

import pytest

from combat.canonical import canonical_sha256
from combat.ext.karma_riders import BORROWED_ID, DEFERRED_ID
from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_carry import KIT

PLAYER = FACTORY_ACTOR_PREFIX + "r9k-player"
FOE = FACTORY_ACTOR_PREFIX + "r9k-foe"
DEFERRED = "condition:typed.karma_deferred"
BORROWED_SPENT = "_round_karma_borrowed_tomorrow"


def fixture(tmp_path, talent):
    documents = [sheet([talent], cl=15), sheet([], cl=15, kit={"starting_kit": KIT})]
    stats = documents[0]["ability_scores_and_statistics"]
    stats["hit_points"]["maximum"] = 1
    stats["armor_class"]["base_value"] = 1
    stats["primary_resource"]["maximum"] = 80
    for pid, document in zip(("r9k-player", "r9k-foe"), documents):
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    bundles = [compile_character(documents[0], actor_id=PLAYER, reaction_plan={"ask": True}),
               compile_character(documents[1], actor_id=FOE)]
    mid = combat._finish_factory_match(
        bundles, [PLAYER, FOE], {PLAYER: "team:factory", FOE: "team:opponents"},
        {PLAYER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [PLAYER], [FOE],
        control_modes={PLAYER: "MANUAL", FOE: "MANUAL"}, match_seed="H5-CHOICES",
        display_name="Karma persistence", maximum_rounds=10)["match_id"]
    if table.state(mid)["menu"]["actor_id"] == PLAYER:
        end_turn(table, mid)
    return combat, table, mid


def act(table, mid, cid, answers=()):
    menu = table.state(mid)["menu"]
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))


def end_turn(table, mid):
    result = act(table, mid, table.state(mid)["menu"]["end_turn"])
    assert result["status"] == "COMMITTED"
    return result


def attack_id(table, mid):
    return next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"]
                if g["label"] == "Bi Shou (Dagger) attack" for o in g["options"]
                if o.get("target_ids") == [PLAYER])


def settle_record_the_deed(send, answers=()):
    answers = list(answers)
    result = send(answers)
    if result["status"] == "REACTION_REQUIRED":
        context = result["reaction"]["context"]
        assert context["reaction_source_id"] == "reaction:typed.TAL_KARMA_RECORD_THE_DEED"
        result = send([*answers, {**context, "selection": "DECLINE"}])
    return result


@pytest.mark.parametrize("talent,cost", [(DEFERRED_ID, 5), (BORROWED_ID, 8)])
@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
def test_paid_karma_reaction_preview_commit_reload(tmp_path, talent, cost, auto_turn, selection):
    combat, table, mid = fixture(tmp_path, talent)
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

    before = combat._load_session(mid).engine.state.model_dump(mode="json")

    def send(answers=()):
        return table.auto_step(mid, 0, list(answers)) if auto_turn else act(table, mid, cid, answers)

    result = send()
    assert result["status"] == "REACTION_REQUIRED"
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == PLAYER
    assert prompt["context"]["reaction_source_id"] == "choice:needle." + talent.rsplit(".", 1)[1]
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    assert send()["reaction"] == prompt  # Preview cannot spend the limit or lose the obligation.
    answer = {**prompt["context"], "selection": selection}
    if selection == "USE":
        answer["option_ids"] = [prompt["choice"]["options"][0]["id"]]
    result = settle_record_the_deed(send, [answer])
    assert result["status"] == "COMMITTED", result.get("reaction")
    # A fresh service must reconstruct from disk, rather than retain engine dictionaries.
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    loaded = combat._load_session(mid)
    player = loaded.engine.state.actors[PLAYER]
    assert player.resources["resource:core.qi"] == 80 - (cost if selection == "USE" else 0)
    obligations = [c for c in player.conditions.values() if c.condition_id == DEFERRED]
    assert len(obligations) == (talent == DEFERRED_ID and selection == "USE")
    assert bool(player.turn_flags.get(BORROWED_SPENT)) == (talent == BORROWED_ID and selection == "USE")
    if obligations:
        assert obligations[0].data["amount"] > 0
        assert obligations[0].data["due"] == before["actors"][PLAYER]["turns_started"] + 1
        assert all(type(v) in (int, str) for v in obligations[0].data.values())
    assert loaded.mechanical.replay()["status"] == "PASS"
    if selection == "DECLINE":
        assert player.current_hp == 0
        return
    assert player.current_hp == 1
    if auto_turn:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="MANUAL")
    end_turn(table, mid)
    assert table.state(mid)["menu"]["actor_id"] == PLAYER
    end_turn(table, mid)  # The protected creature's next turn ends.
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    player = loaded.engine.state.actors[PLAYER]
    assert loaded.mechanical.replay()["status"] == "PASS"
    if talent == DEFERRED_ID:
        arrived = [e for e in loaded.engine.events if e.event_type == "DAMAGE_COMMITTED"
                   and e.source_definition_id == DEFERRED_ID]
        assert len(arrived) == 1
        assert arrived[0].payload["rolled_or_pending_damage"] == obligations[0].data["amount"]
        assert arrived[0].actor_id == PLAYER
        assert not any(c.condition_id == DEFERRED for c in player.conditions.values())
        assert player.current_hp == 0
    else:
        assert player.turn_flags[BORROWED_SPENT] == 1  # Survives turn-start reset, too.
        cid = attack_id(table, mid)
        result = settle_record_the_deed(lambda answers: act(table, mid, cid, answers))
        assert result["status"] == "COMMITTED", result.get("reaction")
        reloaded = CombatService(ROOT, tmp_path)._load_session(mid)
        assert reloaded.engine.state.actors[PLAYER].current_hp == 0
        assert reloaded.engine.state.actors[PLAYER].resources["resource:core.qi"] == 72
        assert reloaded.mechanical.replay()["status"] == "PASS"


def test_borrowed_limit_is_shared_by_save_and_damage_branches():
    from combat.ext import d20_rewrite, karma_riders
    from tests.test_riders_lane9 import ALLY, ME, _karma_fight

    engine = _karma_fight(["borrowed_tomorrow"])
    actor, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    rule = d20_rewrite.RULES["borrowed_tomorrow"]
    holder = next(h for h in rule.finder(engine) if h.actor.entity_id == ME)
    rc = type("SaveContext", (), {"roller": ally})()
    rule.after(engine, holder, rc, None)
    clone = CombatService._clone_engine(ROOT, engine)
    assert not karma_riders.borrowed_hold(clone, clone.state.actors[ALLY], 100, None)
    assert not rule.guard(clone, next(h for h in rule.finder(clone) if h.actor.entity_id == ME), rc)
    assert canonical_sha256(engine.state.model_dump(mode="json")) == canonical_sha256(clone.state.model_dump(mode="json"))
    del actor.turn_flags[BORROWED_SPENT]
    karma_riders.borrowed_hold(engine, ally, 100, None)
    actor.reaction_available = True
    assert not rule.guard(engine, holder, rc)
