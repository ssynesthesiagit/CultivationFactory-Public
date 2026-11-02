"""Winter Stores the Blow's paid fracture survives real table transactions."""

import json
import zipfile

import pytest

from combat.ext.ice_fracture import STORED, T
from combat.factory_compiler import compile_character
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_carry import KIT
from tests.test_r9i_karma_persistence import PLAYER, FOE, act, end_turn, attack_id


def fixture(tmp_path, prepare=None):
    documents = [sheet([T + "WINTER_STORES_THE_BLOW", T + "SHATTER_BLOOM"], cl=15),
                 sheet([], cl=15, kit={"starting_kit": KIT})]
    documents[0]["ability_scores_and_statistics"]["armor_class"]["base_value"] = 1
    documents[0]["ability_scores_and_statistics"]["primary_resource"]["maximum"] = 80
    for pid, document in zip(("r9k-player", "r9k-foe"), documents):
        folder = tmp_path / "portable_characters" / pid
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    bundles = [compile_character(documents[0], actor_id=PLAYER, reaction_plan={"ask": True}),
               compile_character(documents[1], actor_id=FOE)]
    if prepare:
        from combat.canonical import canonical_sha256
        for bundle in bundles:
            prepare(bundle)
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
    mid = combat._finish_factory_match(
        bundles, [PLAYER, FOE], {PLAYER: "team:factory", FOE: "team:opponents"},
        {PLAYER: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [PLAYER], [FOE],
        control_modes={PLAYER: "MANUAL", FOE: "MANUAL"}, match_seed="H5-CHOICES",
        display_name="Ice persistence", maximum_rounds=10)["match_id"]
    if table.state(mid)["menu"]["actor_id"] == FOE:
        end_turn(table, mid)
    cid = action_id(table, mid, "Crystallize Path")
    assert act(table, mid, cid)["status"] == "COMMITTED"
    end_turn(table, mid)
    return combat, table, mid


def action_id(table, mid, label):
    return next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"]
                if g["label"] == label for o in g["options"])


def fractures(combat, mid):
    return [c for c in combat._load_session(mid).engine.state.actors[PLAYER].conditions.values()
            if c.condition_id == STORED]


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("selection", ["USE", "DECLINE"])
@pytest.mark.parametrize("shatter", [False, True])
def test_winter_fracture_preview_commit_reload_consume_or_expire(tmp_path, auto_turn, selection, shatter):
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
        return table.auto_step(mid, 0, list(answers)) if auto_turn else act(table, mid, cid, answers)

    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    result = send()
    assert result["status"] == "REACTION_REQUIRED", result
    prompt = result["reaction"]
    assert prompt["context"]["reactor_id"] == PLAYER
    assert prompt["context"]["reaction_source_id"] == "choice:needle.winter_stores"
    assert send()["reaction"] == prompt
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    answer = {**prompt["context"], "selection": selection}
    if selection == "USE":
        answer["option_ids"] = [prompt["choice"]["options"][0]["id"]]
    answers = [answer]
    result = send(answers)
    if selection == "USE":
        assert result["status"] == "REACTION_REQUIRED", result
        space = result["reaction"]
        assert space["context"]["reactor_id"] == PLAYER
        assert space["context"]["reaction_source_id"] == "choice:needle.winter_stores_space"
        assert "cell:3,6" in {o["id"] for o in space["choice"]["options"]}
        assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
        answers.append({**space["context"], "selection": "USE", "option_ids": ["cell:3,6"]})
        result = send(answers)
    assert result["status"] == "COMMITTED", result
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    loaded = combat._load_session(mid)
    assert loaded.mechanical.replay()["status"] == "PASS"
    stored = fractures(combat, mid)
    assert len(stored) == (selection == "USE")
    hit = next(e for e in reversed(loaded.engine.events) if e.event_type == "DAMAGE_COMMITTED")
    if stored:
        assert stored[0].data["amount"] == hit.payload["rolled_or_pending_damage"] - hit.payload["reduced_to"]
        assert stored[0].data["amount"] > 0
        assert (stored[0].data["x"], stored[0].data["y"]) == (3, 6)
        assert all(type(v) in (int, str) for v in stored[0].data.values())
    if auto_turn:
        combat.set_controller_mode(mid, actor_id=FOE, controller_mode="MANUAL")
    end_turn(table, mid)
    assert len(fractures(combat, mid)) == len(stored)  # Valid throughout the owner's next turn.
    if shatter:
        cid = action_id(table, mid, "Shatter Bloom")
        previous = len(combat._load_session(mid).engine.events)
        result = act(table, mid, cid)
        answers = []
        while result["status"] == "REACTION_REQUIRED":
            context = result["reaction"]["context"]
            assert len(fractures(combat, mid)) == len(stored)  # Paused preview cannot consume it.
            source = context["reaction_source_id"]
            if source == "choice:needle.bloom_spaces":
                answers.append({**context, "selection": "USE", "option_ids": ["3,6"]})
            elif source == "choice:needle.bloom_type":
                answers.append({**context, "selection": "USE", "option_ids": ["COLD"]})
            else:
                assert source == "choice:needle.winter_stores"
                answers.append({**context, "selection": "DECLINE"})
            result = act(table, mid, cid, answers)
        assert result["status"] == "COMMITTED", result
        loaded = CombatService(ROOT, tmp_path)._load_session(mid)
        events = loaded.engine.events[previous:]
        rolls = [r.total for r in loaded.engine.rolls
                 if r.reason == "DAMAGE:" + next(
                     a.source_definition_id for a in loaded.engine.action_catalog.values() if a.display_name == "Shatter Bloom")]
        damages = [e.payload["rolled_or_pending_damage"] for e in events if e.event_type == "DAMAGE_COMMITTED"
                   and "SHATTER_BLOOM" in str(e.source_definition_id).upper()]
        assert len(damages) == len(rolls) == 2
        saves = [e.payload["success"] for e in events if e.event_type == "SAVE_ROLLED" and "SHATTER_BLOOM" in str(e.source_definition_id).upper()]
        assert damages == [r // 2 if saved else r for r, saved in zip(rolls, saves)]
        if stored:
            damage_roll = next(r for r in loaded.engine.rolls if r.reason.startswith("DAMAGE:") and "SHATTER_BLOOM" in r.reason.upper())
            assert damage_roll.modifier >= stored[0].data["amount"]
        assert not fractures(combat, mid)
        assert loaded.mechanical.replay()["status"] == "PASS"
    end_turn(table, mid)
    reloaded = CombatService(ROOT, tmp_path)
    assert not fractures(reloaded, mid)
    assert reloaded._load_session(mid).mechanical.replay()["status"] == "PASS"


def test_shatter_space_consumes_saved_bonus_once_after_clone():
    from combat.ext import ice_fracture
    from tests.test_riders_lane9 import ME, ALLY, THEM, _ice_fight, _lattice_under, _stab

    engine = _ice_fight(["WINTER_STORES_THE_BLOW"], them_at=(4, 7), ally_at=(3, 7))
    _lattice_under(engine, ALLY)
    engine.state.actors[ALLY].armor_class = -50
    _stab(engine, target=ALLY)
    clone = CombatService._clone_engine(ROOT, engine)
    caster = clone.state.actors[ME]
    stored = next(c for c in caster.conditions.values() if c.condition_id == STORED)
    clone.state.actors[THEM].position = clone.state.actors[ALLY].position
    before = len(clone.events)
    ice_fracture._shatter(clone, caster, clone.state.actors[THEM], 15, 4)
    hit = next(e for e in clone.events[before:] if e.event_type == "DAMAGE_COMMITTED")
    roll = next(r for r in reversed(clone.rolls) if r.reason == "DAMAGE:" + ice_fracture.BASE)
    save = next(e for e in reversed(clone.events) if e.event_type == "SAVE_ROLLED")
    assert roll.modifier == stored.data["amount"]
    assert hit.payload["rolled_or_pending_damage"] == (roll.total // 2 if save.payload["success"] else roll.total)
    assert not any(c.condition_id == STORED for c in caster.conditions.values())
    assert ice_fracture._take_stored(clone, caster, (3, 7)) == 0
    assert any(c.condition_id == STORED for c in engine.state.actors[ME].conditions.values())


def test_saved_fracture_cannot_transfer_to_a_replacement_space_or_another_owner():
    from combat.ext import ice_fracture
    from tests.test_riders_lane9 import ME, ALLY, _ice_fight, _lattice_under, _stab

    engine = _ice_fight(["WINTER_STORES_THE_BLOW"], them_at=(4, 7), ally_at=(3, 7))
    _lattice_under(engine, ALLY)
    engine.state.actors[ALLY].armor_class = -50
    _stab(engine, target=ALLY)
    caster = engine.state.actors[ME]
    stored = next(c for c in caster.conditions.values() if c.condition_id == STORED)
    engine._apply_condition(caster, STORED, T + "WINTER_STORES_THE_BLOW", ALLY,
                            expires_on=stored.expires_on, data=dict(stored.data))
    other = next(c for c in caster.conditions.values() if c.source_actor_id == ALLY)
    ice_fracture._end_space(engine, ME, (3, 7))
    _lattice_under(engine, ALLY)
    assert ice_fracture._take_stored(engine, caster, (3, 7)) == 0
    assert other.instance_id in caster.conditions
    assert stored.instance_id not in caster.conditions
