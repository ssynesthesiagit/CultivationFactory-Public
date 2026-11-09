"""The Scoundrel talents through the real table: what a player is asked, and what a saved fight keeps (AUTO11f1).

Every test here drives TabletopService over a real CombatService match built from real sheets (see
``tests/auto11_service_support.py``), so the questions are the ones the shipped controller renders and the answers are
the ones a player or an AI fighter actually sends. Nothing reads a plug-in's private state.

  choice transport    "choice:scoundrel.*" arrives as a menu with real option ids, readable labels and bounds
  Bob and Weave       all three printed questions are asked, on the table's own prompts
  Steal / Equipment   the printed allowance and eligibility, in the rendered prompt
  AI                  an AI Scoundrel answers its own menu and the action still resolves
  persistence         a stolen object survives a commit and a reload, as strings a saved fight can replay
  identity            two identical objects keep one record each, one name each, and their loads and hands
  an older record     one written before objects were named is still its own creature's own object
"""

from __future__ import annotations

import pytest

from combat import carry
from combat.ext import hand_occupancy, scoundrel_riders
from combat.tabletop_service import TabletopService
from tests import auto11_service_support as S

THIEF, VICTIM, ALLY, RIVAL = S.THIEF, S.VICTIM, S.ALLY, S.RIVAL
PACK_KEY, ARMOR_KEY = S.PACK_KEY, S.ARMOR_KEY
STEALERS = ["TAL_SCOUNDREL_DIRTY_TRICK", "TAL_SCOUNDREL_STEAL"]
EQUIPMENT = "Steal Equipment (take one worn thing)"


def _fight(tmp_path, talents, **kwargs):
    return S.fight(S.scratch(tmp_path), talents, **kwargs)


def _case(tmp_path, label):
    """Its own character folder per case, so one test can build several real fights."""
    return S.scratch(tmp_path / label)


def _labels(prompt):
    return {row["id"]: row["label"] for row in (prompt.get("choice") or {}).get("options") or []}


def _carried(engine, who):
    """What the fight says one creature is bearing and holding: pounds on its back, and the hands left free.

    Read from the load and the hand model the table itself uses (combat/carry.py, the shared hand occupancy), which is
    where a moved object has to show up: taking an object into a hand weighs on the thief and takes that hand, and
    giving it away or dropping it gives the weight back.
    """
    creature = engine.state.actors[who]
    return carry.weight(engine, creature), hand_occupancy.free_hands(engine, creature)


def _hands(engine, who):
    """Every hand this creature has, free or not."""
    return hand_occupancy.hand_parts(engine, engine.state.actors[who])


def _pack_pounds(engine, who):
    """What this creature's own bundle says its Explorer's Pack weighs."""
    item = carry.item_of(carry.carrying_of(engine, who), key=PACK_KEY)
    assert item is not None, "the harness gives every fighter a pack"
    return float(item["weight_lb"])


def _menu_prompt(prompts, suffix):
    return next(prompt for prompt in prompts if str(prompt["context"]["reaction_source_id"]).endswith(suffix))


def test_the_table_is_asked_which_object_with_options_it_can_answer(tmp_path):
    """Finding 1: these menus used to reach the controller as an empty Use/Pass window with no options at all."""
    _combat, table, mid = _fight(tmp_path, STEALERS)
    result, prompts = S.play(table, mid, S.candidate(table, mid, "STEAL", target=VICTIM))
    assert result["status"] == "COMMITTED"
    prompt = _menu_prompt(prompts, "steal_objects")
    choice = prompt["choice"]
    assert choice["options"], "the question carries the options it will be answered with"
    assert (choice["minimum"], choice["maximum"]) == (0, 1), "Steal prints one object"
    assert choice["allow_decline"] is True, "\"take nothing\" and declining are both allowed"
    labels = _labels(prompt)
    assert labels and all(label and "tianxia.mortal" not in label for label in labels.values()), \
        "every option a player sees is named, not an internal id"
    assert prompt["reactor"] == "Thief" and prompt["affected"] == "Victim", \
        "the prompt names who is asked and which creature it lands on"
    assert "Steal" in prompt["title"] and "Victim" in prompt["trigger"], \
        "and says which ability is choosing, and against whom"


def test_bob_and_weave_asks_all_three_printed_questions(tmp_path):
    """"One willing adjacent ally ... must plausibly cover at least half your body": asked, not assumed."""
    combat, table, mid = _fight(tmp_path, [*STEALERS, "TAL_SCOUNDREL_BOB_AND_WEAVE"], ally=True)
    _result, prompts = S.play(table, mid, S.candidate(table, mid, "BOB AND WEAVE"))
    assert _labels(prompts[0]) == {ALLY: "Ally"}, "which adjacent ally is the anchor"
    willing = _menu_prompt(prompts, "bob_and_weave_willing")
    assert set(_labels(willing)) == {"accept", "refuse"} and "Ally" in willing["reactor"], \
        "the ally itself is asked whether it agrees"
    covers = _menu_prompt(prompts, "bob_and_weave_covers")
    assert set(_labels(covers)) == {"yes", "no"} and "half" in covers["trigger"], \
        "and whether it really can cover half the user's body"
    filed = [row for row in S.engine(combat, mid).state.actors[THIEF].conditions.values()
             if row.condition_id == scoundrel_riders.ANCHOR]
    assert filed and filed[0].data["anchor"] == ALLY, "the answered anchor is what was filed"


def test_steal_equipment_offers_only_a_worn_thing(tmp_path):
    """Finding 4: the menu is the printed eligibility, not everything the target happens to carry."""
    _combat, table, mid = _fight(tmp_path, [*STEALERS, "TAL_SCOUNDREL_STEAL_EQUIPMENT"], victim_kit=S.ARMORED)
    _result, prompts = S.play(table, mid, S.candidate(table, mid, EQUIPMENT, target=VICTIM))
    prompt = _menu_prompt(prompts, "steal_objects")
    offered = _labels(prompt)
    assert any(ARMOR_KEY in option for option in offered), "a suit of worn armor is what this talent prints"
    assert all(ARMOR_KEY in option or option == scoundrel_riders.NOTHING for option in offered), \
        f"nothing unworn is on offer, and this talent never plants one of the thief's own objects: {sorted(offered)}"
    assert prompt["choice"]["maximum"] == 1, "Steal Equipment prints one worn item"
    assert "plant" not in prompt["trigger"].lower(), f"the question does not offer planting: {prompt['trigger']}"


def test_steal_equipment_prints_one_worn_item_even_with_cleaned_out(tmp_path):
    """\"attempt to remove one worn item\": Cleaned Out's second slot is Steal's, not this talent's."""
    _combat, table, mid = _fight(tmp_path, [*STEALERS, "TAL_SCOUNDREL_STEAL_EQUIPMENT",
                                          "TAL_SCOUNDREL_CLEANED_OUT"], victim_kit=S.ARMORED)
    _result, prompts = S.play(table, mid, S.candidate(table, mid, EQUIPMENT, target=VICTIM))
    prompt = _menu_prompt(prompts, "steal_objects")
    assert prompt["choice"]["maximum"] == 1, "one worn item, and no second slot from Cleaned Out"
    assert all(not str(row["id"]).startswith("plant:") for row in prompt["choice"]["options"]), \
        "and this talent never plants"
    assert scoundrel_riders.NOTHING in _labels(prompt), "taking nothing is always on offer"


def test_taking_nothing_at_the_table_takes_nothing_and_disarms_nobody(tmp_path):
    """\"Take nothing\", and declining, are answers: no object moves and the default disarm does not happen."""
    for answer, label in (("nothing", "take-nothing"), ("decline", "decline")):
        combat, table, mid = _fight(_case(tmp_path, label), STEALERS, victim_kit=S.ARMORED)
        answer = None if answer == "decline" else answer
        result, prompts = S.play(table, mid, S.candidate(table, mid, "STEAL", target=VICTIM), answer=answer)
        assert result["status"] == "COMMITTED", f"{label}: the check is still made; it is what the action is"
        assert _menu_prompt(prompts, "steal_objects"), f"{label}: the question was really put and answered"
        engine = S.engine(combat, mid)
        assert S.records(engine, PACK_KEY) == [], f"{label}: nothing changed hands"
        assert [row.condition_id for row in engine.state.actors[VICTIM].conditions.values()] == [], \
            f"{label}: and nothing was disarmed, which is what the table's own default would have done"


def test_plain_steal_does_not_offer_a_complete_suit_of_worn_armor(tmp_path):
    """"Master Thief does not make ... a complete suit of worn armor ordinarily accessible.\""""
    _combat, table, mid = _fight(tmp_path, STEALERS, victim_kit=S.ARMORED)
    _result, prompts = S.play(table, mid, S.candidate(table, mid, "STEAL", target=VICTIM))
    offered = _labels(_menu_prompt(prompts, "steal_objects"))
    assert not any(ARMOR_KEY in option for option in offered), "an ordinary Steal cannot reach worn armor"
    assert any("weapon.qiang" in option for option in offered), "but what the target holds is on offer"


def test_master_thief_does_not_reach_a_worn_suit_of_armor_at_the_table_either(tmp_path):
    """The talent's own printed line limits what Steal can reach, so owning it changes nothing about the menu."""
    _combat, table, mid = _fight(tmp_path, [*STEALERS, "TAL_SCOUNDREL_MASTER_THIEF"], victim_kit=S.ARMORED)
    _result, prompts = S.play(table, mid, S.candidate(table, mid, "STEAL", target=VICTIM))
    offered = _labels(_menu_prompt(prompts, "steal_objects"))
    assert not any(ARMOR_KEY in option for option in offered), \
        "\"Master Thief does not make ... a complete suit of worn armor ordinarily accessible\""
    assert any("weapon.qiang" in option for option in offered), "the rest of what it wears is still on offer"


def _plant_answer(tiny):
    """Answer the object menu with a planting, and the printed Tiny question with ``tiny``."""
    def reply(prompt):
        source = str(prompt["context"]["reaction_source_id"])
        if source.endswith("steal_objects"):
            return f"plant:{PACK_KEY}"
        if source.endswith("steal_tiny"):
            return tiny
        return None
    return reply


def test_planting_asks_the_printed_tiny_question_and_honours_the_answer(tmp_path):
    """"plant one Tiny object in an accessible location on the target": the size is asked, and it is enforced."""
    for tiny, planted, label in (("yes", True, "tiny"), ("no", False, "not-tiny")):
        combat, table, mid = _fight(_case(tmp_path, label), STEALERS, victim_kit=S.ARMORED)
        result, prompts = S.play(table, mid, S.candidate(table, mid, "STEAL", target=VICTIM),
                                answer=_plant_answer(tiny))
        assert result["status"] == "COMMITTED"
        asked = _menu_prompt(prompts, "steal_tiny")
        assert "Tiny" in asked["trigger"] and asked["reactor"] == "Thief" and asked["affected"] == "Victim", \
            f"{label}: the fighter is asked, in plain words, about the object and the creature"
        records = S.records(S.engine(combat, mid), PACK_KEY)
        assert bool(records) is planted, \
            f"{label}: the object {'is' if planted else 'is not'} planted, so {records}"


def test_a_planted_object_survives_a_commit_and_a_reload_as_one_record(tmp_path):
    """Checklist 7: the planted object keeps its own identity and its single record across a saved fight."""
    combat, table, mid = _fight(tmp_path, STEALERS, victim_kit=S.ARMORED)
    taken = S.play(table, mid, S.candidate(table, mid, "STEAL", target=VICTIM), answer=_plant_answer("yes"))
    assert taken[0]["status"] == "COMMITTED", "the printed check was made and answered"
    before = S.records(S.engine(combat, mid), PACK_KEY)
    assert len(before) == 1, f"one record per object: {before}"
    filed, data = before[0]
    assert filed == THIEF and data["held_by"] == VICTIM, \
        "the record stays on the creature whose bundle lists the object, and says who has it"
    assert data["owner"] == THIEF and data["item_name"], "and carries the object's own identity"
    assert all(isinstance(value, (str, int)) for value in data.values()), \
        f"only strings and integers go into a saved fight: {sorted(data)}"

    reloaded = S.engine(combat, mid)  # a fresh session, replayed from what the table committed
    assert S.records(reloaded, PACK_KEY) == before, "the same single record comes back after a reload"
    assert any(row.get("key") == PACK_KEY for row in
               scoundrel_riders.possessions(reloaded, reloaded.state.actors[VICTIM])), \
        "and the victim really holds it"
    assert combat.replay(mid)["status"] == "PASS", "the saved fight replays"


def test_cleaned_out_offers_exactly_two_objects(tmp_path):
    _combat, table, mid = _fight(tmp_path, [*STEALERS, "TAL_SCOUNDREL_CLEANED_OUT"], victim_kit=S.ARMORED)
    _result, prompts = S.play(table, mid, S.candidate(table, mid, "STEAL", target=VICTIM))
    assert _menu_prompt(prompts, "steal_objects")["choice"]["maximum"] == 2, \
        "\"up to two accessible objects instead of one\""


def test_an_ai_scoundrel_answers_its_own_menu_and_the_action_resolves(tmp_path):
    """Checklist 9: an AI actor decides by itself; only a player is asked."""
    from tests.r1i_service_support import force_ai_candidate

    combat, table, mid = _fight(tmp_path, STEALERS)  # a player's menu, so the printed Steal can be named
    steal = S.candidate(table, mid, "STEAL", target=VICTIM)
    force_ai_candidate(combat, mid, THIEF, steal)  # and then the AI's own controller plays exactly that
    engine = S.engine(combat, mid)
    check_point = len(engine.events)
    response = table.auto_step(mid, table.state(mid)["last_sequence"])
    assert response["status"] != "REACTION_REQUIRED", \
        f"the AI fighter answered its own question by itself: {response.get('reaction')}"
    engine = S.engine(combat, mid)
    rolled = [event for event in engine.events[check_point:] if event.event_type == "CHECK_ROLLED"]
    assert [event for event in rolled if event.payload["skill"] == "Sleight of Hand"], \
        "and the printed Scoundrel Check ran anyway"


def test_a_stolen_object_survives_a_commit_and_a_reload(tmp_path):
    """Checklist 7: what the table hands over is replayed from the saved fight, not held in memory."""
    combat, table, mid = _fight(tmp_path, STEALERS)
    taken = S.play(table, mid, S.candidate(table, mid, "STEAL", target=VICTIM), answer=f"take:{PACK_KEY}")
    assert taken[0]["status"] == "COMMITTED", "the printed check was made and answered"
    before = S.engine(combat, mid)
    record = S.held_by(before.state.actors[VICTIM], PACK_KEY)
    assert record, "the victim's pack is recorded as gone"
    data = record[0].data
    assert data["held_by"] == THIEF and data["hand"], "it says who has it and in which hand"
    assert all(isinstance(value, (str, int)) for value in data.values()), \
        f"only strings and integers go into a saved fight: {sorted(data)}"

    reloaded = S.engine(combat, mid)  # a fresh session, replayed from what the table committed
    after = S.held_by(reloaded.state.actors[VICTIM], PACK_KEY)
    assert [row.data for row in after] == [data], "the same record comes back after a reload"
    assert any(row["key"] == PACK_KEY for row in
               scoundrel_riders.possessions(reloaded, reloaded.state.actors[THIEF])), \
        "and it is the thief's current possession again"
    assert combat.replay(mid)["status"] == "PASS", "the saved fight replays"


def test_the_square_a_set_down_object_landed_in_survives_a_commit_and_a_reload(tmp_path):
    combat, table, mid = _fight(tmp_path, STEALERS)
    _result, prompts = S.play(table, mid, S.candidate(table, mid, "STEAL", target=VICTIM), answer=f"fall:{PACK_KEY}")
    spot = next(prompt for prompt in prompts if str(prompt["context"]["reaction_source_id"]).endswith("steal_spot"))
    assert spot["choice"]["options"], "the square was chosen from real squares"
    record = S.held_by(S.engine(combat, mid).state.actors[VICTIM], PACK_KEY)
    assert record and record[0].data.get("dropped_at"), \
        f"the printed check succeeded, so the object fell into the square that was chosen: {record}"
    before = record[0].data["dropped_at"]
    assert all(isinstance(value, int) for value in before.values()), f"the square is two integers: {before}"
    after = S.held_by(S.engine(combat, mid).state.actors[VICTIM], PACK_KEY)[0].data["dropped_at"]
    assert after == before, "and it is the same square after a reload"


def _own(engine, who, key, owner_id):
    """Whether this creature's own current possession list holds the copy whose identity is ``owner_id``'s."""
    return scoundrel_riders.object_id(owner_id, key) in {
        str(row.get("object") or "") for row in scoundrel_riders.possessions(engine, engine.state.actors[who])}


# One seed per case on which both printed Scoundrel Checks succeed, found by running the case and reading its fight log
# (a check that fails takes nothing, so these cases need one that does not).
KNOWN_GOOD_SEEDS = {"twins": "B", "handover": "A", "legacy": "A"}


def _two_stolen_packs(tmp_path, label, *, answer_rival):
    """One real fight on this case's known-good seed: the thief takes the Victim's pack, then plays again on the Rival.

    A failed Scoundrel Check takes nothing -- that is the printed rule, and it is not what these two cases are about --
    so each names a seed on which both printed checks succeed, found by running the case and reading its fight log, and
    fails when that seed stops working. It does not skip: a Steal that stopped moving objects would otherwise turn both
    regressions into a green run that asserted nothing.
    """
    attempt = KNOWN_GOOD_SEEDS[label]
    seed = f"AUTO11R2F1-{label}-{attempt}"
    combat, table, mid = _fight(_case(tmp_path, f"{label}-{attempt}"), STEALERS, rival=True, seed=seed)
    start = {who: _carried(S.engine(combat, mid), who) for who in (THIEF, VICTIM, RIVAL)}
    first = S.play(table, mid, S.candidate(table, mid, "STEAL", target=VICTIM),
                   answer=f"take:{scoundrel_riders.object_id(VICTIM, PACK_KEY)}")
    assert first[0]["status"] == "COMMITTED", "the printed check was made and answered"
    after_first = S.records(S.engine(combat, mid), PACK_KEY)
    assert after_first, f"{label}: the first printed check succeeds on {seed}, so the pack changes hands here"
    S.to_thief(table, mid, end_thief=True)
    second, prompts = S.play(table, mid, S.candidate(table, mid, "STEAL", target=RIVAL), answer=answer_rival)
    assert second["status"] == "COMMITTED", "and the thief plays again on the Rival"
    assert S.checks_succeeded(S.engine(combat, mid), 2), \
        f"{label}: both printed checks succeed on {seed}, and this case needs both to have moved something"
    return combat, table, mid, after_first, prompts, start


def test_two_identical_objects_keep_their_own_records_and_identities_through_the_whole_table(tmp_path):
    """The finding: a second identical object must never take the first one's record.

    Thief, Victim and Rival all carry the same Explorer's Pack, so the fight holds three copies of one item. Taking
    the Rival's pack must not touch the pack the thief already took: each object keeps its own name, its own owner
    and its own record, and the menu that chose it says which copy is which -- before and after a commit and a reload.
    The loads and the hands move with the objects, or the separation would mean nothing to the players carrying them.
    """
    combat, _table, mid, after_first, prompts, start = _two_stolen_packs(
        tmp_path, "twins", answer_rival=f"fall:{scoundrel_riders.object_id(RIVAL, PACK_KEY)}")
    assert len(after_first) == 1 and after_first[0][0] == VICTIM and after_first[0][1]["owner"] == VICTIM, \
        f"the pack that came from the Victim is recorded as the Victim's own: {after_first}"
    assert _own(S.engine(combat, mid), THIEF, PACK_KEY, VICTIM), "and the thief really holds that copy"

    offered = _menu_prompt(prompts, "steal_objects")["choice"]["options"]
    packs = [row for row in offered if PACK_KEY in str(row["id"])]
    assert len(packs) == 5, f"three copies of one pack are in reach, so five separate choices including reposition: {sorted(row['id'] for row in offered)}"
    assert len({row["label"] for row in packs}) == 5, \
        f"and a player can tell every one of them apart: {sorted(row['label'] for row in packs)}"
    for kind, owner in (("take", RIVAL), ("fall", RIVAL), ("reposition", RIVAL), ("plant", THIEF), ("plant", VICTIM)):
        assert sum(1 for row in packs
                   if str(row["id"]) == f"{kind}:{scoundrel_riders.object_id(owner, PACK_KEY)}") == 1, \
            f"{kind} is on offer once for the copy belonging to {owner}: {sorted(row['id'] for row in packs)}"

    engine = S.engine(combat, mid)
    records = S.records(engine, PACK_KEY)
    assert len(records) == 2, f"two independent objects, one record each: {records}"
    filed = {who: dict(data) for who, data in records}
    assert filed[RIVAL]["owner"] == RIVAL and filed[RIVAL]["dropped_at"], \
        f"the Rival's copy is the Rival's own, lying where it was set down: {filed[RIVAL]}"
    assert filed[VICTIM]["owner"] == VICTIM and filed[VICTIM]["held_by"] == THIEF and filed[VICTIM]["hand"], \
        f"and the pack the thief took is untouched, still in the hand it went into: {filed[VICTIM]}"
    assert filed[VICTIM]["object_id"] == scoundrel_riders.object_id(VICTIM, PACK_KEY) \
        and filed[RIVAL]["object_id"] == scoundrel_riders.object_id(RIVAL, PACK_KEY), \
        f"each object is named by whose bundle lists it: {[data.get('object_id') for data in filed.values()]}"
    assert _own(engine, THIEF, PACK_KEY, VICTIM) and _own(engine, THIEF, PACK_KEY, THIEF), \
        "so the thief is carrying both its own pack and the one it took"
    assert all(isinstance(value, (str, int)) for data in filed.values()
               for name, value in data.items() if name != "dropped_at"), \
        f"only strings and integers go into a saved fight: {sorted(filed[RIVAL])}"
    assert all(isinstance(value, int) for value in filed[RIVAL]["dropped_at"].values()), \
        f"and a square is two integers: {filed[RIVAL]['dropped_at']}"

    # what the three fighters are actually bearing and holding now, which is where a mixed-up object would show:
    pack = _pack_pounds(engine, RIVAL)
    assert _carried(engine, THIEF)[0] == pytest.approx(start[THIEF][0] + pack), \
        f"the thief bears the one pack it took ({start[THIEF][0]} -> {_carried(engine, THIEF)[0]})"
    assert _carried(engine, VICTIM)[0] == pytest.approx(start[VICTIM][0] - pack), "and the victim does not bear it"
    assert _carried(engine, RIVAL)[0] == pytest.approx(start[RIVAL][0] - pack), \
        "the Rival's copy lies in the square it fell into, off the Rival's back"
    assert filed[VICTIM]["hand"] in _hands(engine, THIEF) and filed[VICTIM]["hand"] not in _carried(engine, THIEF)[1], \
        f"\"take the object into a free hand\" is a hand, and it is not free any more: {filed[VICTIM]['hand']}"
    assert len(_carried(engine, THIEF)[1]) == len(_hands(engine, THIEF)) - 1, \
        f"so the thief has one free hand fewer, not two: {_carried(engine, THIEF)[1]}"

    reloaded = S.engine(combat, mid)  # a fresh session, replayed from what the table committed
    assert S.records(reloaded, PACK_KEY) == records, "and both records come back after a reload, as they were"
    assert _own(reloaded, THIEF, PACK_KEY, VICTIM) and _own(reloaded, THIEF, PACK_KEY, THIEF), \
        "each creature's possession list still names its own copy"
    for who in (THIEF, VICTIM, RIVAL):
        assert _carried(reloaded, who) == _carried(engine, who), \
            f"{who}'s load and free hands come back after a reload exactly as the fight left them"
    assert combat.replay(mid)["status"] == "PASS", "the saved fight replays"


def test_one_object_keeps_one_record_and_its_identity_through_three_handovers_at_the_table(tmp_path):
    """The other half: once an object is identified, every later handover moves THAT record and nothing else.

    The thief's own pack travels Thief -> the Rival's hands -> back into the Thief's hand, while the pack it
    took from the Victim stands untouched beside it. Each is one object, so each is one record, filed on the
    creature whose bundle lists it, with the same identity on both sides of a commit and a reload.
    """
    def plant_own(prompt):
        return (f"plant:{scoundrel_riders.object_id(THIEF, PACK_KEY)}"
                if str(prompt["context"]["reaction_source_id"]).endswith("steal_objects") else "yes")

    combat, table, mid, after_first, _prompts, start = _two_stolen_packs(tmp_path, "handover", answer_rival=plant_own)
    stolen = [dict(data) for who, data in after_first if who == VICTIM]
    assert len(stolen) == 1 and stolen[0]["object_id"] == scoundrel_riders.object_id(VICTIM, PACK_KEY), \
        f"the pack taken from the Victim carries the Victim's own identity: {after_first}"
    planted = [dict(data) for who, data in S.records(S.engine(combat, mid), PACK_KEY)
               if who == THIEF and (data or {}).get("held_by") == RIVAL]
    assert len(planted) == 1, f"and the thief's own pack is planted in the Rival's hands: {S.records(S.engine(combat, mid), PACK_KEY)}"
    assert planted[0]["object_id"] == scoundrel_riders.object_id(THIEF, PACK_KEY) and planted[0]["owner"] == THIEF, \
        f"that planted object is the thief's own, by identity and not by name: {planted}"
    assert [dict(data) for who, data in S.records(S.engine(combat, mid), PACK_KEY) if who == VICTIM] == stolen, \
        "and the pack taken from the Victim is exactly as it was, untouched by the planting"

    # two transfers so far, and the weights moved with them: the thief's own pack now rides on the Rival, the pack the
    # thief took rides on the thief, and neither creature carries both.
    planted_engine = S.engine(combat, mid)
    pack = _pack_pounds(planted_engine, RIVAL)
    assert _carried(planted_engine, THIEF)[0] == pytest.approx(start[THIEF][0]), \
        f"the thief no longer bears its own pack, and bears the one it took instead: {_carried(planted_engine, THIEF)[0]}"
    assert _carried(planted_engine, RIVAL)[0] == pytest.approx(start[RIVAL][0] + pack), \
        "and the Rival bears its own pack plus the one planted in its hands"
    assert _carried(planted_engine, VICTIM)[0] == pytest.approx(start[VICTIM][0] - pack), \
        "the victim still bears nothing"
    assert stolen[0]["hand"] not in _carried(planted_engine, THIEF)[1], \
        "the hand the taken pack went into is still not free, and the planting freed none"

    S.to_thief(table, mid, end_thief=True)
    retaken, _ = S.play(table, mid, S.candidate(table, mid, "STEAL", target=RIVAL),
                        answer=f"take:{scoundrel_riders.object_id(THIEF, PACK_KEY)}")
    assert retaken["status"] == "COMMITTED", "and the thief takes that same planted object back"
    engine = S.engine(combat, mid)
    records = S.records(engine, PACK_KEY)
    assert records == after_first, \
        f"after three handovers only the pack that came from the Victim still has a record: {records}"
    assert _own(engine, THIEF, PACK_KEY, THIEF) and _own(engine, THIEF, PACK_KEY, VICTIM), \
        "the planted object came back into the thief's own hands, where it needs no record"
    assert not _own(engine, RIVAL, PACK_KEY, THIEF), "and the Rival really handed it back"
    assert _carried(engine, THIEF)[0] == pytest.approx(start[THIEF][0] + pack), \
        "so the thief bears both of its own packs again, the second one being the one it took"
    assert _carried(engine, RIVAL)[0] == pytest.approx(start[RIVAL][0]), "and the Rival is back to its own pack"
    assert _carried(engine, VICTIM)[0] == pytest.approx(0.0), "and the victim is still carrying nothing"
    assert len(_carried(engine, THIEF)[1]) == len(_hands(engine, THIEF)) - 1, \
        f"one free hand fewer: the taken pack still occupies the hand it went into: {_carried(engine, THIEF)[1]}"

    reloaded = S.engine(combat, mid)  # a fresh session, replayed from what the table committed
    assert S.records(reloaded, PACK_KEY) == records, "the same record comes back after a reload"
    assert _own(reloaded, THIEF, PACK_KEY, THIEF) and _own(reloaded, THIEF, PACK_KEY, VICTIM), \
        "and each object is still the thief's own possession, named by whose bundle lists it"
    for who in (THIEF, VICTIM, RIVAL):
        assert _carried(reloaded, who) == _carried(engine, who), \
            f"{who}'s load and free hands come back after a reload exactly as the fight left them"
    assert combat.replay(mid)["status"] == "PASS", "the saved fight replays"


def test_a_record_saved_before_objects_were_named_is_still_its_own_creature_s_object(tmp_path):
    """The nine historical saves: a record written before ``object_id`` existed keeps the object it was filed for.

    The table's own Drop writes exactly that shape -- ``item_key``, ``item_name`` and the square, with no name of its
    own -- so the thief drops its pack, then steals the Rival's identical pack. The dropped record must not be taken
    over by an object the thief never carried, the new record must be the Rival's own, and both must come back
    unchanged from the saved fight.
    """
    combat, table, mid = _fight(tmp_path, STEALERS, rival=True, seed=f"AUTO11R2F1-legacy-{KNOWN_GOOD_SEEDS['legacy']}")
    dropped = S.play(table, mid, S.candidate(table, mid, "Drop Explorer's Pack"))
    assert dropped[0]["status"] == "COMMITTED"
    legacy = S.records(S.engine(combat, mid), PACK_KEY)
    assert len(legacy) == 1 and legacy[0][0] == THIEF and "object_id" not in legacy[0][1], \
        f"the table's own Drop records the pack without naming it, which is the older shape: {legacy}"

    S.to_thief(table, mid, end_thief=True)
    stolen, _prompts = S.play(table, mid, S.candidate(table, mid, "STEAL", target=RIVAL),
                              answer=f"take:{scoundrel_riders.object_id(RIVAL, PACK_KEY)}")
    assert stolen["status"] == "COMMITTED", "and the thief steals the Rival's identical pack"
    engine = S.engine(combat, mid)
    assert S.checks_succeeded(engine, 1), "the printed check succeeded, or nothing changed hands"
    records = S.records(engine, PACK_KEY)
    filed = {who: dict(data) for who, data in records}
    assert set(filed) == {THIEF, RIVAL}, f"one record per object, not one record for two of the same thing: {records}"
    assert "object_id" not in filed[THIEF], \
        f"the older record is untouched, still the thief's own dropped pack: {filed[THIEF]}"
    assert filed[THIEF]["dropped_at"], "and still lying where it was dropped"
    assert filed[RIVAL]["object_id"] == scoundrel_riders.object_id(RIVAL, PACK_KEY) \
        and filed[RIVAL]["held_by"] == THIEF and filed[RIVAL]["hand"], \
        f"while the Rival's own copy is the one that gained a record and went into the thief's hand: {filed[RIVAL]}"
    assert _own(engine, THIEF, PACK_KEY, RIVAL) and not _own(engine, THIEF, PACK_KEY, THIEF), \
        "so the thief is carrying the Rival's pack and its own is on the ground, where it was dropped"

    reloaded = S.engine(combat, mid)  # a fresh session, replayed from what the table committed
    assert S.records(reloaded, PACK_KEY) == records, "both records come back after a reload, exactly as they were"
    assert _own(reloaded, THIEF, PACK_KEY, RIVAL) and not _own(reloaded, THIEF, PACK_KEY, THIEF), \
        "and the older record is still the thief's own object, not the Rival's"
    assert combat.replay(mid)["status"] == "PASS", "the saved fight replays"


def test_a_fighter_without_the_talents_is_never_asked(tmp_path):
    combat, table, mid = _fight(tmp_path, ["TAL_SCOUNDREL_DIRTY_TRICK"])
    labels = [group["label"] for group in table.state(mid)["menu"]["actions"]]
    assert EQUIPMENT not in labels, "Steal Equipment is a talent: without it, no such button"
    assert not any("Quick Thievery" in label for label in labels), "nor a Quick Thievery Bonus Action"
    assert "BOB AND WEAVE" not in labels, "nor Bob and Weave"
    engine = S.engine(combat, mid)
    assert not any((row.parameters or {}).get("steal_equipment")
                   for row in engine.action_catalog.values() if row.owner_id == THIEF), \
        "and nothing publishes the talent's action for a fighter who does not own it"