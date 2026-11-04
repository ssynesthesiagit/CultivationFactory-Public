"""AUTO84 review fixes (findings 1-7): the repaired Unmaking paths at the level the bug showed.

Every test here drives the real service: a portable character in a real table match, real commits, a fresh
CombatService reading the journal off disk, and the real turn boundary. Checklist 7 wants a regression at the level the
bug showed, and the review asked for service/turn-boundary and commit/reload coverage rather than calls on a plug-in
function. Where a test has to steer the dice it uses the documented ``d20_result`` seam (a d20 the table rolls is replaced
and the rewrite is recorded), never a patched engine.

    finding 1  the Fifth Ruin Form upkeep price "reduce your current and maximum HP by 10 until you finish a Long Rest"
               raised NameError instead of paying (covered at the turn boundary in the engine-level suite).
    finding 2  a maximum-HP price subtracts current Hit Points and accumulates instead of overwriting itself.
    finding 3  First Ruin Form: External Vessel Mandate -- "you may immediately make one Black Trace attack against a
               creature within 30 feet as the weapon dies" is offered at the real end of the form's owner's turn.
    finding 5  the form asks which held weapon or implement is its Channel; only that Channel's Crack is delayed, and
               only a Channel that dies as the form ends earns the free Black Trace.
    finding 6  Crack the Guard: the defender's own Strength-or-Constitution choice is asked on an AI attacker's turn.
"""

from __future__ import annotations

import json
import zipfile

from combat import ext, unmaking
from combat.ext import unmaking_channels, unmaking_forms
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, script as queue_dice
from tests.h1_support import sheet as character_sheet
from tests.test_tabletop_hunt6 import ALLY, LEFT, PROJECTS, RIGHT, table_fight

FORM_SOURCE = "TAL_UNMAKING_FIRST_RUIN_FORM_EXTERNAL_VESSEL_MANDATE"
VESSEL = ["TAL_UNMAKING_FIRST_RUIN_FORM_EXTERNAL_VESSEL_MANDATE", "TAL_UNMAKING_RUIN_CHANNEL", "TAL_UNMAKING_LAST_INCH_CONTROL"]
GUARD = ["TAL_UNMAKING_RUIN_CHANNEL", "TAL_UNMAKING_CRACK_THE_GUARD"]
MOMENT = ["tianxia.talent.unmaking.the_moment_nothing_answers", *VESSEL[1:]]
DAGGER = {"starting_kit": {"items": [{"item_id": "tianxia.mortal.weapon.bi_shou",
                                      "name": "Bi Shou (Dagger)", "quantity": 1}]}}


# ------------------------------------------------------------------------------------------------ helpers
def append_hook(monkeypatch, point, function):
    """Add a test's own hook beside the shipped ones (combat/ext.run is the documented registry)."""
    ext.effects()
    monkeypatch.setitem(ext._HOOKS, point, [*ext._HOOKS.get(point, []), function])


def force_hits(monkeypatch, *needles):
    """Make the listed d20 rolls land, through the documented d20_result seam (combat/ext/__init__.py:1940). A natural
    20 is recorded as a rewrite in the fight log, so nothing is hidden from the review."""
    def rewrite(engine, roll, intent):
        if roll.natural_result is None or not any(str(needle) in str(roll.reason) for needle in needles):
            return None
        return {"source_id": "test:auto84f1", "operation": "replace", "natural_result": 20}

    append_hook(monkeypatch, "d20_result", rewrite)


def dice_for(monkeypatch, actor_id, values):
    """Name the dice this fighter's own next committed action rolls, from inside the accepted intent."""
    def dispatch(engine, event_type, kwargs):
        if event_type == "INTENT_ACCEPTED" and (kwargs or {}).get("actor_id") == actor_id:
            queue_dice(engine, list(values))

    append_hook(monkeypatch, "event", dispatch)


def grant_charge(monkeypatch, actor_id, source):
    """Put the Ruin Channel this fighter is already carrying when its turn starts: the printed "If the duration ends
    without a hit, the Channel remains active until the duration ends" (Ruin Sheath Method keeps it into the next turn).
    A starting state for the test, not a change of rules."""
    def dispatch(engine, event_type, kwargs):
        if event_type == "TURN_STARTED" and (kwargs or {}).get("actor_id") == actor_id:
            actor = engine.state.actors[actor_id]
            engine._apply_condition(actor, unmaking.CHANNEL, source, actor_id,
                                    expires_on=f"END_OF_SOURCE_TURN_AT:{int(actor.turns_started) + 1}",
                                    data={"label": "Ruin Channel (charged, from the turn before)"})

    append_hook(monkeypatch, "event", dispatch)


def reloaded(tmp_path, mid):
    """A brand new service: this reads the committed journal off disk, it is not a cached view."""
    return CombatService(ROOT, tmp_path)._load_session(mid)


def _own(engine, actor, needle):
    """One of this fighter's own compiled action ids whose source contains ``needle``."""
    return next(key for key, action in sorted(engine.action_catalog.items())
                if action.owner_id == actor.entity_id and needle in key)


def said(engine, start=0):
    return " ".join(str(event.payload.get("rider") or event.payload.get("log") or "")
                    for event in engine.events[start:])


def play(table, mid, needle, answers=()):
    """Use the first menu entry whose source contains ``needle``, answering any pause with ``answers``."""
    state = table.state(mid)
    group = next((g for g in state["menu"]["actions"] if needle in g["source_definition_id"]), None)
    if group is None:
        return {"status": "NOT_OFFERED"}
    return table.act(mid, group["options"][0]["candidate_id"], state["menu"]["decision_id"],
                     state["menu"]["state_version"], state["last_sequence"], list(answers))


def end_turn(table, mid, answers=()):
    state = table.state(mid)
    return table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"], state["menu"]["state_version"],
                     state["last_sequence"], list(answers))


def answer(prompt, options):
    """What a client sends back for a prompt the table raised."""
    return [{**prompt["context"], "selection": "USE" if options else "DECLINE", "option_ids": list(options)}]


def vessel_table(tmp_path, mids, *, kit=DAGGER):
    """A table match whose Unmaking fighter takes First Ruin Form and names its Channel; returns the offer prompt when
    the fight paused to ask, or None when there was nothing in hand to ask about."""
    combat, table, mid = table_fight(tmp_path, mids, ally_talents=[], kit=kit, cl=12)
    result = play(table, mid, FORM_SOURCE)
    if result["status"] != "REACTION_REQUIRED":
        return combat, table, mid, None
    prompt = result["reaction"]
    play(table, mid, FORM_SOURCE, answer(prompt, [row["id"] for row in prompt["choice"]["options"]]))
    return combat, table, mid, prompt


def hold_back_the_cracking_crack(monkeypatch, actor_id, amount=3):
    """Let the printed d6 hold the Channel's breaking Crack back until the form ends.

    The delay d6 is the seeded roller's own, which a service test cannot steer, so this writes the state the printed d6
    writes at the printed moment -- the weapon hit -- through the same public helper the rules call
    (combat/ext/unmaking_channels.delay_or_crack), with a named 6. The Channel goes to 2 Crack on the hit and the third
    is held back, so the form's end breaks it.
    """
    def dispatch(engine, event_type, kwargs):
        if event_type != "DAMAGE_COMMITTED" or (kwargs or {}).get("actor_id") != actor_id:
            return
        me = engine.state.actors[actor_id]
        weapon = unmaking_channels.chosen_channel(me)
        if unmaking_channels.vessel_form(me) is None or not weapon or unmaking_channels.delayed_crack(me) is not None:
            return
        unmaking_channels.crack(engine, me, weapon, amount - 1, "test:the_channel_was_at_two")
        queue_dice(engine, [6])
        unmaking_channels.delay_or_crack(
            unmaking_forms.context_of(engine, me, _own(engine, me, ".weapon."), me), weapon, 1)

    append_hook(monkeypatch, "event", dispatch)


def charged_hit(table, mid, monkeypatch):
    """Charge the Ruin Channel on this owner's own turn and land the hit with the held Channel, paying the printed
    "choose one" price with its own printed self-damage option so the Crack bookkeeping stays on the delayed path."""
    for _ in range(12):
        if table.state(mid)["menu"]["actor_id"] != LEFT:
            if end_turn(table, mid)["status"] != "COMMITTED":
                return False
            continue
        if play(table, mid, ".TAL_UNMAKING_RUIN_CHANNEL")["status"] != "COMMITTED":
            if end_turn(table, mid)["status"] != "COMMITTED":   # one Bonus Action a turn, as printed
                return False
            continue
        force_hits(monkeypatch, ".weapon.bi_shou")
        result = play(table, mid, ".weapon.bi_shou")
        if result["status"] != "REACTION_REQUIRED":
            return result["status"] == "COMMITTED"
        price = result["reaction"]
        options = [row["id"] for row in price["choice"]["options"] if row["label"].startswith("Take ")]
        return play(table, mid, ".weapon.bi_shou", answer(price, options))["status"] == "COMMITTED"
    return False


def run_to_the_form_s_end(table, mid, tmp_path, limit=60):
    """End real turns until the form's printed minute runs out at the end of its owner's turn; returns the printed offer
    when the fight paused for it."""
    for _ in range(limit):
        if unmaking_channels.vessel_form(reloaded(tmp_path, mid).engine.state.actors[LEFT]) is None:
            return None, True
        result = end_turn(table, mid)
        if result["status"] == "REACTION_REQUIRED":
            return result["reaction"], False
        assert result["status"] == "COMMITTED", result
    raise AssertionError("the form never ended")


def unbased_table(tmp_path, talents, *, control_modes=None):
    """A table match for the AI-attacker test. The Unmaking fighter's sheet leaves the sphere's automatic base
    abilities out, so the weapon attack is the only attack its controller can choose -- the printed Crack the Guard
    trigger is a weapon Ruin Channel, and this keeps the Local Auto step deterministic."""
    def document(name, mids):
        sheet = character_sheet(mids, cl=12, kit=DAGGER if name == "left" else None, primary="Stamina")
        if name == "left":
            sheet["spheres_and_talents"]["automatic_sphere_component_record_ids"] = []
        sheet["identity"]["display_name"] = name.title()
        return sheet

    for name, mids in (("left", talents), ("ally", []), ("right", [])):
        folder = tmp_path / "portable_characters" / PROJECTS[name]
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(document(name, mids)))
    combat = CombatService(ROOT, tmp_path)
    combat.tabletop_maps.save({"display_name": "AUTO84f1 yard", "width_squares": 12, "height_squares": 8,
                               "walls": [], "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}})
    mid = combat.create_factory_match(project_ids=[PROJECTS["left"], PROJECTS["ally"]], opponent_actor_ids=[RIGHT],
                                      control_modes=control_modes or {actor: "MANUAL" for actor in (LEFT, ALLY, RIGHT)},
                                      arena_id="battlefield:map.auto84f1-yard", match_seed="AUTO84F1-AI")["match_id"]
    return combat, TabletopService(combat, tmp_path), mid


# ------------------------------------------------------------------------------------------------ finding 5: the Channel, kept
def test_first_ruin_form_asks_its_channel_and_keeps_it_through_a_table_commit_and_reload(tmp_path):
    """"Choose one held weapon or implement." The answer is stored on the form as one action id (a string), so a reload
    still knows which Channel's Crack may be delayed and which Channel dying earns the free Black Trace."""
    combat, table, mid, prompt = vessel_table(tmp_path, VESSEL)
    assert prompt is not None, "the printed choice of Channel is asked"
    assert "Channel" in prompt["reaction"], prompt["reaction"]
    session = reloaded(tmp_path, mid)
    me = session.engine.state.actors[LEFT]
    form = unmaking_channels.vessel_form(me)
    assert form is not None, "the printed form is up for its minute"
    channel = unmaking_channels.chosen_channel(me)
    assert channel and channel in unmaking_channels.channels(session.engine, me), \
        "one of this fighter's own held weapons, stored as a string on the form"
    assert form.data["channel"] == channel, "and it survived the commit as plain saved state"
    assert session.verify()["status"] == "PASS" and session.mechanical.replay()["status"] == "PASS"


def test_a_form_taken_with_nothing_in_hand_says_so_instead_of_naming_a_channel(tmp_path):
    combat, table, mid, prompt = vessel_table(tmp_path, VESSEL, kit=None)
    assert prompt is None, "no held weapon means no question to ask"
    session = reloaded(tmp_path, mid)
    me = session.engine.state.actors[LEFT]
    assert unmaking_channels.vessel_form(me) is not None
    assert not unmaking_channels.channels(session.engine, me), "this fighter really is unarmed"
    assert unmaking_channels.chosen_channel(me) is None
    assert "hold no weapon" in said(session.engine), said(session.engine)


# ------------------------------------------------------------------------------------------------ finding 3 + 5: the free Black Trace
def test_the_free_black_trace_is_offered_at_the_form_s_own_turn_end_and_pauses_for_its_owner(tmp_path, monkeypatch):
    """"If the Channel breaks when the form ends, you may immediately make one Black Trace attack against a creature within
    30 feet as the weapon dies. This attack cannot Overdraw." The form's printed minute runs out at the end of its owner's
    turn: the offer has to reach its owner there, and the table has to pause for the answer."""
    combat, table, mid, prompt = vessel_table(tmp_path, [*VESSEL, "TAL_UNMAKING_BLACK_TRACE"])
    assert prompt is not None
    session = reloaded(tmp_path, mid)
    weapon = unmaking_channels.chosen_channel(session.engine.state.actors[LEFT])
    assert weapon, "the form named its Channel"
    hold_back_the_cracking_crack(monkeypatch, LEFT)
    assert charged_hit(table, mid, monkeypatch), "the Ruin Channel landed on the held Channel"
    me = reloaded(tmp_path, mid).engine.state.actors[LEFT]
    assert unmaking_channels.cracks(me, weapon) == 2, "the Channel was at 2 Crack"
    assert unmaking_channels.delayed_crack(me) is not None, "and the printed d6 held the third Crack back"
    assert unmaking_channels.cracks(me, weapon) < 3, "so it has not broken yet"

    offer, _ended = run_to_the_form_s_end(table, mid, tmp_path)
    assert offer is not None, "the form ended, the Channel died and the free Black Trace was offered"
    assert "Black Trace" in json.dumps(offer), offer
    assert RIGHT in json.dumps(offer), "the creatures within 30 feet are offered"
    session = reloaded(tmp_path, mid)
    assert not any(c.condition_id.startswith(unmaking_channels.BROKEN)
                   for c in session.engine.state.actors[LEFT].conditions.values()), \
        "nothing is committed while the fight waits for the owner's answer"
    before = session.engine.state.actors[RIGHT].current_hp
    force_hits(monkeypatch, "BLACK_TRACE")
    state = table.state(mid)
    result = table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"], state["menu"]["state_version"],
                       state["last_sequence"], answer(offer, [RIGHT]))
    assert result["status"] == "COMMITTED", result
    session = reloaded(tmp_path, mid)
    assert any(c.condition_id.startswith(unmaking_channels.BROKEN)
               for c in session.engine.state.actors[LEFT].conditions.values()), "the Channel died as the form ended"
    assert session.engine.state.actors[RIGHT].current_hp < before, "the free Black Trace attacked the chosen creature"
    assert session.engine.state.actors[LEFT].resources.get(unmaking.STRAIN, 0) == 0, \
        "the printed 'This attack cannot Overdraw'"
    assert session.verify()["status"] == "PASS" and session.mechanical.replay()["status"] == "PASS"


def test_declining_the_free_black_trace_costs_nothing(tmp_path, monkeypatch):
    """The offer is the holder's own optional decision, so a decline is legal and hits nothing."""
    combat, table, mid, prompt = vessel_table(tmp_path, [*VESSEL, "TAL_UNMAKING_BLACK_TRACE"])
    assert prompt is not None
    hold_back_the_cracking_crack(monkeypatch, LEFT)
    assert charged_hit(table, mid, monkeypatch)
    offer, _ended = run_to_the_form_s_end(table, mid, tmp_path)
    assert offer is not None, "the form ended, the Channel died and the free Black Trace was offered"
    before = reloaded(tmp_path, mid).engine.state.actors[RIGHT].current_hp
    state = table.state(mid)
    result = table.act(mid, state["menu"]["end_turn"], state["menu"]["decision_id"], state["menu"]["state_version"],
                       state["last_sequence"], answer(offer, []))
    assert result["status"] == "COMMITTED", result
    session = reloaded(tmp_path, mid)
    assert any(c.condition_id.startswith(unmaking_channels.BROKEN)
               for c in session.engine.state.actors[LEFT].conditions.values()), "the Channel died as the form ended"
    assert session.engine.state.actors[RIGHT].current_hp == before, "declining the printed offer hits nothing"
    assert session.verify()["status"] == "PASS"


# ------------------------------------------------------------------------------------------------ finding 2: the printed HP prices
def test_the_moment_nothing_answers_price_survives_a_table_commit_and_reload(tmp_path, monkeypatch):
    """"reduce your current and maximum HP by 20 until you finish a Long Rest" -- taken out at the table, then read back
    from the committed journal by a brand new service."""
    combat, table, mid = table_fight(tmp_path, MOMENT, ally_talents=[], primary="Stamina", cl=17)
    before = combat._load_session(mid).engine.state.actors[LEFT]
    maximum, current = before.maximum_hp, before.current_hp
    dice_for(monkeypatch, LEFT, [1] * 24)          # the target's save fails first; the inheritance's own costs follow
    result = play(table, mid, "the_moment_nothing_answers")
    assert result["status"] == "COMMITTED", result
    session = reloaded(tmp_path, mid)
    me = session.engine.state.actors[LEFT]
    assert me.maximum_hp == maximum - 20, "the printed maximum Hit Point loss, read back from the commit"
    assert me.current_hp <= current - 20, "the printed current Hit Point loss"
    assert any(c.condition_id.startswith("condition:typed.maximum_hp_lost") for c in me.conditions.values())
    assert all(type(row.amount) is int for row in me.maximum_hp_adjustments.values()), "stored as integers"
    assert session.verify()["status"] == "PASS" and session.mechanical.replay()["status"] == "PASS"


# ------------------------------------------------------------------------------------------------ finding 6: the defender's choice
def test_crack_the_guard_asks_a_manual_defender_on_an_ai_attackers_turn(tmp_path, monkeypatch):
    """"the target must succeed on a Strength or Constitution saving throw, target's choice." The save is built when the hit
    lands, so combat/ext/save_choices.potential_targets cannot see it in a catalog row: without the enrollment
    gate5_service._ask_reactors leaves the manual defender out and the AI step decides the target's own save for them."""
    modes = {LEFT: "LOCAL_AUTO", ALLY: "MANUAL", RIGHT: "MANUAL"}
    combat, table, mid = unbased_table(tmp_path, GUARD, control_modes=modes)
    session = combat._load_session(mid)
    metadata = combat._read_metadata(mid, session)
    assert RIGHT in combat._ask_reactors(metadata, session), "the manual defender is enrolled to answer its own save"
    assert LEFT not in combat._ask_reactors(metadata, session), \
        "the AI attacker is not: its own questions are answered automatically"
    assert RIGHT in session.engine.typed_ask_reactors, "which is the set local_step's probe reads"

    grant_charge(monkeypatch, LEFT, "action:typed.test.ruin_channel")
    force_hits(monkeypatch, ".weapon.bi_shou")
    paused = None
    for _ in range(10):
        if table.state(mid).get("menu", {}).get("actor_id") != LEFT:
            if end_turn(table, mid)["status"] != "COMMITTED":
                break
            continue
        result = combat.auto_step(mid)
        if result["status"] == "AWAITING_REACTION":
            paused = result["reaction_context"]
            break
        if result["status"] != "COMMITTED":
            break
    assert paused is not None, "the Local Auto step put a question to a player"
    assert paused["reactor_id"] == RIGHT, "and it is the defender's own save, not the attacker's"
    assert set(paused["extension_choice"]["option_ids"]) == {"STR", "CON"}, paused["extension_choice"]
    result = combat.auto_step(mid, reactions=[{"checkpoint": paused["checkpoint"], "reactor_id": paused["reactor_id"],
                                               "reaction_source_id": paused["reaction_source_id"],
                                               "selection": "USE", "option_ids": ["CON"]}])
    assert result["status"] == "COMMITTED", result
    session = reloaded(tmp_path, mid)
    assert [event for event in session.engine.events if event.event_type == "SAVE_ROLLED"], \
        "the printed save was made after the choice"
    assert session.verify()["status"] == "PASS"


def test_crack_the_guard_enrolls_nobody_in_a_fight_with_no_cracker(tmp_path):
    combat, table, mid = table_fight(tmp_path, ["TAL_UNMAKING_RUIN_CHANNEL"], ally_talents=[], kit=DAGGER,
                                     control_modes={LEFT: "LOCAL_AUTO", ALLY: "MANUAL", RIGHT: "MANUAL"}, cl=12)
    session = combat._load_session(mid)
    metadata = combat._read_metadata(mid, session)
    assert RIGHT not in combat._ask_reactors(metadata, session), \
        "checklist 3: the enrollment belongs to the ability, not to every Unmaking fight"
    assert ALLY not in combat._ask_reactors(metadata, session)