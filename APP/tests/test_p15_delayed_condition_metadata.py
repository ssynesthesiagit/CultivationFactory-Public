"""P15: delayed Poisoned retains its saved repeat/DC and condition metadata.

The service case casts the real compiled Venom Pill at a character who owns
Swallow the Poison. Other reactions are declined so the exercised path is the
condition-delay choice. The raw-record cases isolate JSON ownership and the
optional field's compatibility with a previously saved delay.
"""

import json
import zipfile

import pytest

from combat import typed_executor as te
from combat.ext import effect_durations, hundred_venom
from combat.gate2_runtime_models import ActionDefinition, ConditionInstance, EconomyKind
from combat.gate5_service import CombatService
from combat.tabletop import ButtonStore
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, ME, FOE, duel, sheet
from tests.test_lock2_persistence import act
from tests.test_p15_save_condition_duration import pin_dice  # noqa: F401 -- shared pytest fixture
from tests.test_tabletop_hunt6 import PROJECTS, LEFT, ALLY, RIGHT


POISON_PILL = "TAL_ALCHEMY_POISON_PILL"
VENOM_SUFFIX = POISON_PILL + "#opt0"
POISONED = "condition:typed.poisoned"
DELAY_CHOICE = "choice:needle.swallow_the_poison_delay"
SYNTHETIC_SOURCE = "test:p15.delayed_poison"


def _condition(engine, actor_id, condition_id):
    found = [row for row in engine.state.actors[actor_id].conditions.values()
             if row.condition_id == condition_id]
    assert len(found) <= 1
    return found[0] if found else None


def _reload(tmp_path, match_id):
    return CombatService(ROOT, tmp_path)._load_session(match_id)


def _assert_replay(session):
    replay = session.mechanical.replay()
    assert replay["status"] == "PASS"
    assert replay["state"] == session.engine.state.model_dump(mode="json", by_alias=True)


def _pill_saves(engine):
    return [event for event in engine.events if event.event_type == "SAVE_ROLLED"
            and event.actor_id == RIGHT and event.source_definition_id.endswith(VENOM_SUFFIX)]


def _table_with_swallow(tmp_path):
    """Existing portable-character fixture pattern, with the defender's own talent.

    test_tabletop_hunt6.table_fight always gives the right-hand character no
    talents; these ordinary sheets give that opponent Swallow the Poison.
    """
    for name, owned, primary in (("left", [POISON_PILL], "Qi"),
                                 ("ally", [], "Qi"),
                                 ("right", [hundred_venom.SWALLOW], "Stamina")):
        document = sheet(owned, cl=15, primary=primary)
        document["identity"]["display_name"] = name.title()
        folder = tmp_path / "portable_characters" / PROJECTS[name]
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document))
    ButtonStore(tmp_path / "tabletop_buttons").save_reactions(
        PROJECTS["right"], {"mode": "ask"}, {"opportunity_attack"})
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({
        "display_name": "P15 delay yard", "width_squares": 12, "height_squares": 8,
        "walls": [], "starts": {"team1": [[3, 4], [3, 5]], "team2": [[4, 4]]},
    })
    match_id = combat.create_factory_match(
        project_ids=[PROJECTS["left"], PROJECTS["ally"]], opponent_actor_ids=[RIGHT],
        control_modes={actor_id: "MANUAL" for actor_id in (LEFT, ALLY, RIGHT)},
        arena_id="battlefield:map.p15-delay-yard", match_seed="P15-DELAY-TABLE")["match_id"]
    table = TabletopService(combat, tmp_path)
    for _ in combat._load_session(match_id).engine.state.initiative_order:
        if table.state(match_id)["menu"]["actor_id"] == LEFT:
            return combat, table, match_id
        assert act(table, match_id, "end")["status"] == "COMMITTED"
    raise AssertionError("the caster did not receive its opening turn")


def _cast_with_delay(table, match_id):
    state = table.state(match_id)
    menu = state["menu"]
    group, = [group for group in menu["actions"]
              if group["source_definition_id"].endswith(VENOM_SUFFIX)]
    option, = [option for option in group["options"] if option["target_ids"] == [RIGHT]]
    answers, delayed = [], False
    for _ in range(12):
        result = table.act(match_id, option["candidate_id"], menu["decision_id"],
                           menu["state_version"], state["last_sequence"], answers)
        if result["status"] == "COMMITTED":
            assert delayed, "the target must explicitly choose its actual delay reaction"
            return
        assert result["status"] == "REACTION_REQUIRED", result
        prompt = result["reaction"]
        take = prompt["context"]["reaction_source_id"] == DELAY_CHOICE
        if take:
            assert prompt["context"]["reactor_id"] == RIGHT
            assert {row["id"] for row in prompt["choice"]["options"]} == {"delay"}
            delayed = True
        else:
            assert not prompt.get("choice") or prompt["choice"]["allow_decline"], prompt
        answers.append({**prompt["context"], "selection": "USE" if take else "DECLINE",
                        "option_ids": ["delay"] if take else []})
    raise AssertionError("Venom Pill did not complete after its bounded reaction choices")


@pytest.mark.parametrize("repeat_succeeds", [False, True])
def test_real_venom_pill_delay_preserves_repeat_through_table_commit_reload(
        tmp_path, pin_dice, repeat_succeeds):
    combat, table, match_id = _table_with_swallow(tmp_path)
    before = combat._load_session(match_id).engine
    original_stamina = before.state.actors[RIGHT].resources[hundred_venom.STAMINA]
    # An unrescuably low CON save leaves the target's reaction available for
    # delaying the condition. Minimum real damage keeps it alive for the repeat.
    pin_dice(before, [1, *([1] * 6)])
    _cast_with_delay(table, match_id)
    loaded = _reload(tmp_path, match_id)
    initial, = _pill_saves(loaded.engine)
    assert initial.payload["natural_result"] == 1
    assert initial.payload["success"] is False
    delayed = _condition(loaded.engine, RIGHT, hundred_venom.DELAYED)
    assert delayed is not None and _condition(loaded.engine, RIGHT, POISONED) is None
    expected_save = {"ability": "CON", "when": "end", "dc": 16}
    assert delayed.data["condition_data"] == {"repeat_save": expected_save}
    assert delayed.source_actor_id == LEFT
    assert delayed.data["source"] == initial.source_definition_id
    assert effect_durations.parse_round(delayed.data["expires_on"]) == (
        before.state.round_number + 10, before.state.current_slot_index)
    assert loaded.engine.state.actors[RIGHT].resources[hundred_venom.STAMINA] == original_stamina - 1
    saved_delay = json.loads(json.dumps(delayed.model_dump(mode="json")))
    assert _condition(_reload(tmp_path, match_id).engine, RIGHT,
                      hundred_venom.DELAYED).model_dump(mode="json") == saved_delay
    _assert_replay(loaded)

    # A fresh table/service pair ends real turns until the holder's delayed
    # condition arrives. No repeat is due while the delay itself is held.
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    for _ in range(2 * len(loaded.engine.state.initiative_order)):
        assert act(table, match_id, "end")["status"] == "COMMITTED"
        loaded = _reload(tmp_path, match_id)
        assert len(_pill_saves(loaded.engine)) == 1
        poison = _condition(loaded.engine, RIGHT, POISONED)
        if poison is not None:
            break
        assert _condition(loaded.engine, RIGHT, hundred_venom.DELAYED).model_dump(mode="json") == saved_delay
    else:
        raise AssertionError("the delayed poison did not arrive at the holder's next turn end")
    assert _condition(loaded.engine, RIGHT, hundred_venom.DELAYED) is None
    assert poison.source_definition_id == initial.source_definition_id
    assert poison.source_actor_id == LEFT
    assert poison.expires_on == saved_delay["data"]["expires_on"]
    assert poison.data["repeat_save"] == expected_save
    poison_id = poison.instance_id
    _assert_replay(loaded)

    # Reopen again before the first subsequent holder-end save. The surviving
    # snapshot, not the discarded cast Context, supplies that save's DC/source.
    table = TabletopService(CombatService(ROOT, tmp_path), tmp_path)
    for _ in loaded.engine.state.initiative_order:
        target_ends = loaded.engine.state.current_actor_id == RIGHT
        if target_ends:
            pin_dice(loaded.engine, [20 if repeat_succeeds else 1])
        result=act(table, match_id, "end")
        if result['status']=='REACTION_REQUIRED':
            # The printed failed-save response remains legal even when PB
            # cannot rescue this total. Explicitly decline that actual choice;
            # retain every existing onset/DC/source/replay assertion below.
            prompt=result['reaction']
            assert target_ends and not repeat_succeeds
            assert prompt['context']['reaction_source_id']=='reaction:typed.'+hundred_venom.SWALLOW
            assert prompt['context']['reactor_id']==RIGHT
            state=table.state(match_id);menu=state['menu']
            result=table.act(match_id,menu['end_turn'],menu['decision_id'],menu['state_version'],state['last_sequence'],
                             [{**prompt['context'],'selection':'DECLINE'}])
        assert result['status']=='COMMITTED'
        loaded = _reload(tmp_path, match_id)
        if target_ends:
            break
        assert len(_pill_saves(loaded.engine)) == 1
    else:
        raise AssertionError("the poisoned holder did not finish another turn")
    initial_again, repeated = _pill_saves(loaded.engine)
    assert initial_again.sequence == initial.sequence
    assert repeated.payload["dc"] == 16
    assert repeated.payload["reason"] == f"SAVE:{initial.source_definition_id}:CON"
    assert repeated.payload["success"] is repeat_succeeds
    remaining = _condition(loaded.engine, RIGHT, POISONED)
    if repeat_succeeds:
        assert remaining is None
        removal, = [event for event in loaded.engine.events
                    if event.event_type == "CONDITION_REMOVED"
                    and event.payload.get("instance_id") == poison_id]
        assert removal.payload["repeat_save"] is True
        assert removal.payload["checkpoint"] == "END_OF_TURN"
    else:
        assert remaining.instance_id == poison_id
        assert remaining.data["repeat_save"] == expected_save
        assert remaining.source_actor_id == LEFT
    _assert_replay(loaded)


def _synthetic_context(engine, origin_save=None):
    typed = {"numbers": {"save_dc": 17, "pb": 4}, "duration": {"kind": "instant"}}
    action = ActionDefinition(source_definition_id=SYNTHETIC_SOURCE,
                              display_name="Synthetic saved poison", owner_id=FOE,
                              economy=EconomyKind.NONE, resolution_kind="TYPED",
                              target_kind="HOSTILE_ENTITY", range_ft=60,
                              parameters={"typed": typed})
    holder = engine.state.actors[ME]
    return te.Context(engine, engine.state.actors[FOE], action, None, typed,
                      [holder], holder, {}, origin_save=origin_save)


def _finish_delay(engine, holder_id):
    for _ in range(2 * len(engine.state.initiative_order)):
        engine.end_turn()
        poison = _condition(engine, holder_id, POISONED)
        if poison is not None:
            assert _condition(engine, holder_id, hundred_venom.DELAYED) is None
            return poison
    raise AssertionError("the serialized delay did not release its poison")


@pytest.mark.parametrize("save_kind", ["repeat", "origin", "none"])
def test_delayed_data_is_a_json_snapshot_and_does_not_recompute_the_casters_dc(save_kind):
    engine = duel([hundred_venom.SWALLOW], primary="Stamina")
    origin = None if save_kind == "none" else {"ability": "WIS", "dc": 17}
    ctx = _synthetic_context(engine, origin)
    effect = {"type": "condition", "condition": "poisoned", "applies_to": "target",
              "duration": "one_minute", "condition_label": "Original poison label",
              "condition_data": {"test_provenance": {"steps": ["captured"]}}}
    expected = {"test_provenance": {"steps": ["captured"]}, "label": "Original poison label"}
    if save_kind == "repeat":
        effect["repeat_save"] = {"ability": "CON", "when": "end"}
        expected["repeat_save"] = {"ability": "CON", "when": "end", "dc": 17}
    elif save_kind == "origin":
        expected["origin_save"] = {"ability": "WIS", "dc": 17}
    te.block_condition(ctx, effect)
    delayed = _condition(engine, ME, hundred_venom.DELAYED)
    assert delayed is not None and _condition(engine, ME, POISONED) is None
    assert delayed.data["condition_data"] == expected

    # Mutating the source inputs after capture must not mutate its delayed data.
    effect["condition_data"]["test_provenance"]["steps"].append("changed")
    effect["condition_label"] = "Changed label"
    ctx.typed["numbers"]["save_dc"] = 99
    if origin is not None:
        origin["dc"] = 99
    if "repeat_save" in effect:
        effect["repeat_save"]["when"] = "start"
    assert delayed.data["condition_data"] == expected
    encoded = json.dumps(delayed.model_dump(mode="json"))
    restored = ConditionInstance.model_validate(json.loads(encoded))
    engine.state.actors[ME].conditions[restored.instance_id] = restored
    poison = _finish_delay(engine, ME)
    assert poison.data == expected
    assert poison.source_definition_id == SYNTHETIC_SOURCE
    assert poison.source_actor_id == FOE
    assert poison.expires_on == restored.data["expires_on"]
    assert ("repeat_save" in poison.data) is (save_kind == "repeat")
    # Restoration must also detach the live condition from the retired record.
    restored.data["condition_data"]["test_provenance"]["steps"].append("retired")
    assert poison.data == expected


def test_prechange_delayed_record_without_condition_data_remains_loadable():
    engine = duel([hundred_venom.SWALLOW], primary="Stamina")
    holder = engine.state.actors[ME]
    original_expiry = effect_durations.round_token(engine, 10)
    engine._apply_condition(
        holder, hundred_venom.DELAYED, hundred_venom.SWALLOW, FOE,
        expires_on=effect_durations.token("end", ME, int(holder.turns_started) + 1),
        data={"label": "Swallow the Poison: Poisoned is delayed",
              "expires_on": original_expiry, "source": SYNTHETIC_SOURCE})
    legacy = _condition(engine, ME, hundred_venom.DELAYED)
    document = json.loads(json.dumps(legacy.model_dump(mode="json")))
    assert "condition_data" not in document["data"]
    holder.conditions[legacy.instance_id] = ConditionInstance.model_validate(document)
    poison = _finish_delay(engine, ME)
    assert poison.expires_on == original_expiry
    assert poison.source_actor_id == FOE
    assert poison.source_definition_id == SYNTHETIC_SOURCE
    assert poison.data == {"label": "Poisoned (delayed by Swallow the Poison)"}
    assert "repeat_save" not in poison.data and "origin_save" not in poison.data
