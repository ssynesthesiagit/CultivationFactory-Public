"""Player choices use actual table preview, answer and reload transport."""
import pytest

from combat.ext import fate_riders as F
from combat.gate4_adapters import ManualControllerAdapter
from combat.gate5_service import CombatService
from tests.h1_support import ROOT
from tests.test_r9i_fate_persistence import fixture, PLAYER, ALLY, FOE
from tests.test_r9i_karma_persistence import act, end_turn


def resolve(send, choices):
    answers = []
    result = send(answers)
    seen = []
    while result["status"] == "REACTION_REQUIRED":
        prompt = result["reaction"]
        assert send(answers)["reaction"] == prompt
        context = prompt["context"]
        source = context["reaction_source_id"]
        seen.append(source)
        picked = choices.get(source)
        answers.append({**context, "selection": "USE" if picked else "DECLINE",
                        **({"option_ids": picked} if picked else {})})
        result = send(answers)
    assert result["status"] == "COMMITTED", result
    return seen


def action(table, mid, name, target=None):
    return next(o["candidate_id"] for g in table.state(mid)["menu"]["actions"]
                if name in g["label"] for o in g["options"]
                if target is None or o.get("target_ids") == [target])


def finish_turn(table, mid, choices=None):
    cid = table.state(mid)["menu"]["end_turn"]
    return resolve(lambda answers: act(table, mid, cid, answers), choices or {})


@pytest.mark.parametrize("auto_turn", [False, True])
@pytest.mark.parametrize("use", [False, True])
@pytest.mark.parametrize("talent,label,choice", [(F.COURT, "Court of the Heavenly Ledger", "court_bonus"),
                                                 (F.SERENDIPITY, "Serendipity Edict", "serendipity")])
def test_court_optional_bonus_table_on_manual_and_ai_ally_turn(tmp_path, auto_turn, use, talent, label, choice):
    combat, table, mid = fixture(tmp_path, talent)
    while table.state(mid)["menu"]["actor_id"] != PLAYER:
        finish_turn(table, mid)
    resolve(lambda answers: act(table, mid, action(table, mid, label), answers), {})
    finish_turn(table, mid)
    while table.state(mid)["menu"]["actor_id"] != ALLY:
        finish_turn(table, mid)
    assert table.state(mid)["menu"]["actor_id"] == ALLY
    cid = action(table, mid, "Dagger", FOE)
    if auto_turn:
        real = combat.controller

        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=ALLY, controller_mode="LOCAL_AUTO")
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    send = lambda answers: table.auto_step(mid, 0, answers) if auto_turn else act(table, mid, cid, answers)
    result = send([])
    assert result["status"] == "REACTION_REQUIRED"
    assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
    seen = resolve(send, {"choice:needle." + choice: ["add"] if use else None})
    ai_chooser = auto_turn and talent == F.SERENDIPITY
    assert ("choice:needle." + choice in seen) == (not ai_chooser)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    zone = F._zones(loaded.engine, talent)[0]
    assert F._once_a_round(loaded.engine, ("court" if talent == F.COURT else "serendipity", zone.zone_id), consume=False) == (not (use or ai_chooser))
    bonuses = [e for e in loaded.engine.events if e.event_type == "D20_REWRITTEN" and e.payload.get("operation") == "bonus"]
    if use or ai_chooser:
        assert bonuses
        assert bonuses[-1].payload["original"]["natural_result"] == bonuses[-1].payload["result"]["natural_result"]
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("use", [False, True])
@pytest.mark.parametrize("auto_turn", [False, True])
def test_vital_court_recipient_choice_through_table(tmp_path, monkeypatch, use, auto_turn):
    from tests.test_tabletop_hunt6 import table_fight, on_hold, LEFT, ALLY as A
    from tests.test_lock2_persistence import act as table_act
    from combat.typed_executor import mark_condition_id
    from combat.gate4_engine import Gate4ControllerEngine

    talent = "tianxia.talent.life.vital_court_field"
    combat, table, mid = table_fight(tmp_path, [talent], ally_talents=[], ask=True)
    resolve(lambda answers: act(table, mid, action(table, mid, "Vital Court Field"), answers), {})
    # Chosen Pulse Seals are fixture prerequisites. The accepted hold injects
    # a Life healing event to isolate recipient consent on either actor's turn.
    def heal(engine):
        healer, ally = engine.state.actors[LEFT], engine.state.actors[A]
        for target in (healer, ally):
            engine._apply_condition(target, mark_condition_id("Pulse Seal", LEFT), talent, LEFT, expires_on="UNTIL_REMOVED")
        engine._commit_damage(ally, 5, "FORCE", "test:injury", None, None, reaction_depth=1)
        before = ally.current_hp
        ally.current_hp += 3
        engine._append_event("HEALING_APPLIED", "action:typed.test.life.mend", actor_id=LEFT, target_ids=(A,),
                             payload={"offered": 3, "before": before, "after": ally.current_hp})

    on_hold(monkeypatch, heal)
    if auto_turn:
        finish_turn(table, mid)
        active = table.state(mid)["menu"]["actor_id"]
        real = combat.controller
        cid = action(table, mid, "Hold position")

        class Controller:
            def choose_primary_action(self, context):
                return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

            def __getattr__(self, name):
                return getattr(real, name)

        combat.controller = Controller()
        combat.set_controller_mode(mid, actor_id=active, controller_mode="LOCAL_AUTO")
        send = lambda answers: table.auto_step(mid, 0, answers)
    else:
        cid = action(table, mid, "Hold position")
        send = lambda answers: act(table, mid, cid, answers)
    before = combat._load_session(mid).engine.state.model_dump(mode="json")
    first = send([])
    assert first["status"] == "REACTION_REQUIRED"
    prompt = first["reaction"]["moment"]
    assert "Vital Court Field" in prompt and "regained Hit Points" in prompt
    assert "Pulse Seal when creating the field" in prompt and "4 Temporary HP (your Proficiency Bonus)" in prompt
    assert "until used up or replaced" in prompt and "once per round" in prompt
    assert "no additional CP" in prompt and "Concentration, up to 1 minute" in prompt
    seen = resolve(send, {"choice:needle.vital_court": [LEFT] if use else None})
    assert "choice:needle.vital_court" in seen
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.engine.state.actors[LEFT].temporary_hp == (4 if use else 0)
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("auto_transition", [False, True])
def test_sovereign_turn_start_target_and_boon_use_end_turn_transport(tmp_path, auto_transition):
    combat, table, mid = fixture(tmp_path, F.SOVEREIGN_ID)
    while table.state(mid)["menu"]["actor_id"] != PLAYER:
        finish_turn(table, mid)
    resolve(lambda answers: act(table, mid, action(table, mid, "Fate-Sovereign Incarnation"), answers), {})
    seen = []
    for index in range(3):
        cid = table.state(mid)["menu"]["end_turn"]
        automatic = auto_transition and index == 2
        if automatic:
            active = table.state(mid)["menu"]["actor_id"]
            assert active != PLAYER
            real = combat.controller

            class Controller:
                def choose_primary_action(self, context):
                    return ManualControllerAdapter(lambda _: (cid, ())).choose_primary_action(context)

                def __getattr__(self, name):
                    return getattr(real, name)

            combat.controller = Controller()
            combat.set_controller_mode(mid, actor_id=active, controller_mode="LOCAL_AUTO")
        before = combat._load_session(mid).engine.state.model_dump(mode="json")
        send = lambda answers: table.auto_step(mid, 0, answers) if automatic else act(table, mid, cid, answers)
        result = send([])
        if result["status"] == "REACTION_REQUIRED":
            assert combat._load_session(mid).engine.state.model_dump(mode="json") == before
            seen += resolve(send, {"choice:needle.sovereign_ally": [ALLY], "choice:needle.sovereign_boon": ["save"]})
        else:
            assert result["status"] == "COMMITTED"
    assert "choice:needle.sovereign_ally" in seen
    assert "choice:needle.sovereign_boon" in seen
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert F._held(loaded.engine.state.actors[ALLY], F.BOON)[0].data["boon"] == "save"
    assert loaded.mechanical.replay()["status"] == "PASS"


@pytest.mark.parametrize("damage_type", ["COLD", "PIERCING", None])
def test_bloom_chosen_space_damage_type_or_decline(tmp_path, damage_type):
    from tests.test_r9i_ice_persistence import fixture as ice_fixture, action_id, PLAYER as P, end_turn
    from combat.ext.ice_fracture import lattice_cells

    combat, table, mid = ice_fixture(tmp_path)
    end_turn(table, mid)
    cid = action_id(table, mid, "Shatter Bloom")
    before = combat._load_session(mid).engine
    cells = lattice_cells(before, P)
    state = before.state.model_dump(mode="json")
    seen = resolve(lambda answers: act(table, mid, cid, answers), {
        "choice:needle.bloom_spaces": ["3,6"] if damage_type else None,
        "choice:needle.bloom_type": [damage_type] if damage_type else None})
    assert "choice:needle.bloom_spaces" in seen
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    after = lattice_cells(loaded.engine, P)
    if damage_type:
        assert set(cells) - set(after) == {(3, 6)}
        assert "choice:needle.bloom_type" in seen
        damage = [e for e in loaded.engine.events if e.event_type == "DAMAGE_COMMITTED" and "SHATTER_BLOOM" in e.source_definition_id.upper()]
        assert damage and all(e.payload["damage_type"].upper() == damage_type for e in damage)
    else:
        assert after == cells
        assert "choice:needle.bloom_type" not in seen
    assert loaded.mechanical.replay()["status"] == "PASS"
