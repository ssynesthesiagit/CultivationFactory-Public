"""AUTO10 (round 25) + AUTO10f1 review fixes: the Talismans sphere's printed effects the engine now resolves itself.

Every test is a real compiled character in a real fight. The table tests go through the menu, commit and a
reload from disk (which also asserts the replay); the falling and damage tests drive the engine's own fall
and attack code so the printed numbers are read off committed events.

AUTO10f1 changed what the review found wrong: the printed array's placement is the table's again (no
destructive partial automation), Remote Activation asks the talisman's actual holder and keeps the formula's own
reach, Recall needs a talisman that really is out in the world and names its actual holder, Elemental Talisman
only pays its printed Proficiency Bonus for a paid craft and only on one damage roll, and Read the Script
reveals exactly the fact or facts the fighter asked for.
"""
import json

import pytest

from combat import falling
from combat.ext.talisman_scribe import NO as SCRIBE_NOT_MINE
from combat.ext.talismans import CRAFTED_ELEMENT, CRAFTING_PAID, ELEMENT, FEATHERFALL_CONDITION, PREPARED, SCRIPT_FACTS
from tests.h1_support import ALLY, FOE, ME, duel, give, ready, script, use
from tests.hunt12_support import ME as TABLE_ME, FOE as TABLE_FOE, candidate, fight, hit_dice, reload, send
from tests.test_lock2_persistence import act

ALLY_TABLE = "actor:factory.auto10f1-ally"
PREPARED_LIMIT = PREPARED
PURIFYING = "tianxia.talent.talismans.purifying_talisman"
FEATHERFALL = "tianxia.talent.talismans.featherfall_talisman"
RECALL = "tianxia.talent.talismans.talisman_recall"
RECALL_CHOICE = "talismans_out_in_the_world"
WORLD = "condition:typed.talisman_recall"
ELEMENTAL = "tianxia.talent.talismans.elemental_talisman"
REMOTE = "tianxia.talent.talismans.remote_activation"
SERVITOR = "tianxia.talent.talismans.living_scripture_servitor"
SPIRIT = "tianxia.talent.talismans.talisman_spirit"
EMBER = "tianxia.talent.talismans.ember_talisman"
HEALING = "tianxia.talent.talismans.healing_talisman"
DEMON_TAG = "tianxia.talent.talismans.demon_subduing_tag"
SCRIPT = "TALISMANS_BASE_READ_THE_SCRIPT"
SCRIPT_NAME = "Read the Script"
SEAL_EYE = "tianxia.talent.talismans.seal_breaker_s_eye"
ARRAY = "tianxia.talent.talismans.talisman_array"
TAGS = "tianxia.talent.talismans.ten_thousand_tags_obey"
BOMB = "tianxia.talent.talismans.talisman_bomb"
POISONED = "condition:typed.poisoned"
STAMINA = "resource:core.stamina"
ARRAY_NAME = "Set up a Talisman Array"
BOMB_NAME = "Talisman Bomb"
TAGS_KEEP = "resource:named.tags_obey_kept"   # the once-per-long-rest benefit a deferred array must not spend
TOGGLE = "Elemental Talisman: choose a damage type"
# The hostile creature for a formula that must see its target: 25 feet from the fighter, 25 feet from the ally beside
# it, and in clear sight of the fighter through the pillar arena's open lane.
SEEN_FOE = (8, 6)


def answer(prompt, option_id):
    return {**prompt["context"], "selection": "USE", "option_ids": [option_id]}


def options(prompt):
    return {row["id"]: row["label"] for row in prompt["choice"]["options"]}


def pick(prompt, needle):
    """The offered option whose label contains ``needle``."""
    offered = options(prompt)
    if "cultivation points" in needle:
        assert all(" CP" not in label for label in offered.values())
    return next(key for key, label in offered.items() if needle in label)


def riders(engine, contains=None):
    """The GM-only lines the fight log shows."""
    lines = [str((event.payload or {}).get("rider") or "") for event in engine.events if event.event_type == "GM_RIDER"]
    return [line for line in lines if contains is None or contains in line]


def notes(engine, contains=None):
    """The plain log lines the fight shows the players."""
    lines = [str((event.payload or {}).get("log") or "") for event in engine.events
             if event.event_type == "PASSIVE_TRIGGERED"]
    return [line for line in lines if contains is None or contains in line]


def packets(engine, target_id):
    return [event for event in engine.events
            if event.event_type == "DAMAGE_COMMITTED" and target_id in (event.target_ids or ())]


def dice_of(engine, suffix):
    return [event for event in engine.events if event.event_type == "DAMAGE_ROLLED"
            and str(event.source_definition_id).endswith(suffix)]


def saves(engine, suffix):
    return [event for event in engine.events if event.event_type == "SAVE_ROLLED"
            and str((event.payload or {}).get("reason") or "").endswith(suffix)]


def intent_for(engine, actor_id=ME, target_id=""):
    from combat.gate2_runtime_models import ActionIntent

    return ActionIntent(intent_id="auto10", decision_id="auto10", candidate_id="auto10",
                        state_version=engine.state.state_version, actor_id=actor_id,
                        target_ids=(target_id,) if target_id else ())


def next_turn(table, mid):
    assert act(table, mid, "end")["status"] == "COMMITTED"
    while table.state(mid)["menu"]["actor_id"] != TABLE_ME:
        assert act(table, mid, "end")["status"] == "COMMITTED"


def chooser(combat, mid, *, prefix=None, name=None, target=None):
    """The fighter's menu button by name (prefix or exact) and, when the button has one, its target."""
    def matches(candidate_row):
        label = str(candidate_row.display_name)
        if name is not None and label != name:
            return False
        if prefix is not None and not label.startswith(prefix):
            return False
        if target is not None and tuple(candidate_row.target_ids or ()) != (target,):
            return False
        return candidate_row.actor_id == TABLE_ME

    return next(row for row in combat._load_session(mid).engine.legal_candidates() if matches(row))


def press(combat, table, mid, steps=(), *, prefix=None, name=None, target=None):
    """Take a button, answering each prompt in turn.

    Each step answers one prompt: the option with that exact id when the prompt offers it (a creature's entity id, ""
    for the caster's own hand), otherwise the option whose label holds the text.  A prompt with no step left takes
    its first option.  Returns the prompts, so a test can read what was offered.
    """
    chosen = chooser(combat, mid, prefix=prefix, name=name, target=target)
    answers, prompts = [], []
    response = send(combat, table, mid, chosen, answers)
    while response["status"] == "REACTION_REQUIRED":
        prompt = response["reaction"]
        prompts.append(prompt)
        offered = options(prompt)
        if len(answers) < len(steps):
            wanted = steps[len(answers)]
            option = wanted if wanted in offered else pick(prompt, wanted)
        else:
            option = next(iter(offered))
        answers.append(answer(prompt, option))
        response = send(combat, table, mid, chosen, answers)
    assert response["status"] == "COMMITTED", response
    return prompts


def three(tmp_path, mids, *, outside=None, foe_mids=(), dc=10, cl=18, foe_at=(12, 6)):
    """A table fight: the fighter, one allied creature beside it and one hostile creature, optionally with the
    fighter's fight setup declaring how many crafted talismans are out in the world (Talisman Recall's ledger).

    ``foe_at`` places the hostile creature.  The pillar arena hides some cells from the fighter, so a formula that
    needs to see its target asks for a cell it can see (the default is 45 feet away and out of the Touch reach of a
    talisman in an enemy's hands).
    """
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.h1_support import ROOT, sheet

    mine = compile_character(sheet(list(mids), cl=cl, dc=dc, primary="Stamina", score=18),
                             actor_id=TABLE_ME, reaction_plan={"ask": True})
    ally = compile_character(sheet(list(mids)[:1], cl=cl, primary="Stamina"), actor_id=ALLY_TABLE)
    foe = compile_character(sheet(list(foe_mids), cl=cl, primary="Stamina"), actor_id=TABLE_FOE)
    combat = CombatService(ROOT, tmp_path)
    if outside is not None:
        mine = combat._with_prefight(mine, {TABLE_ME: [f"setup-choice:{RECALL_CHOICE}:{outside}"]})
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        [mine, ally, foe], [TABLE_ME, ALLY_TABLE, TABLE_FOE],
        {TABLE_ME: "team:factory", ALLY_TABLE: "team:factory", TABLE_FOE: "team:opponents"},
        {TABLE_ME: {"x": 3, "y": 6}, ALLY_TABLE: {"x": 3, "y": 7}, TABLE_FOE: {"x": foe_at[0], "y": foe_at[1]}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [TABLE_ME, ALLY_TABLE], [TABLE_FOE],
        control_modes={TABLE_ME: "MANUAL", ALLY_TABLE: "MANUAL", TABLE_FOE: "MANUAL"},
        match_seed="AUTO10F1", display_name="AUTO10f1 regression", maximum_rounds=20)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != TABLE_ME:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid


def names(engine):
    return {key: actor.display_name for key, actor in engine.state.actors.items()}


def prepared(engine, actor_id=TABLE_ME):
    return int(engine.state.actors[actor_id].resources.get(PREPARED, 0))


def limit(engine, actor_id=TABLE_ME):
    return int(engine.state.actors[actor_id].resource_maximums.get(PREPARED_LIMIT, 0))


def outside(engine, actor_id=TABLE_ME):
    """How many crafted talismans the fighter's fight setup declared out in the world."""
    for row in engine.state.actors[actor_id].conditions.values():
        if row.condition_id == WORLD:
            return int((row.data or {}).get("outside") or 0)
    return 0


def menu(engine):
    return {str(row.display_name) for row in engine.legal_candidates()}


def learned(engine, actor_id=TABLE_ME):
    """The damage types this fighter's Elemental Talisman learnings let them craft with, as the fight stores them."""
    for row in engine.state.actors[actor_id].conditions.values():
        if row.condition_id == ELEMENT:
            data = row.data or {}
            names = [str(name) for name in data.get("elements") or []]
            names += [str(data["element"])] if data.get("element") else []
            return set(names)
    return set()


def pill(engine, actor_id=TABLE_ME):
    """The Elemental Talisman pill the fight shows the player."""
    return next((str((row.data or {}).get("label") or "") for row in engine.state.actors[actor_id].conditions.values()
                 if row.condition_id == ELEMENT), "")


def elemental_prompts(prompts):
    """The questions Elemental Talisman asked, by the moment that put them."""
    return [str(prompt.get("moment") or "") for prompt in prompts if prompt.get("reaction") == "Elemental Talisman"]


# ------------------------------------------------------------------------------ Purifying Talisman: "End one minor poison"
def test_purifying_talisman_ends_a_poison(tmp_path):
    combat, table, mid = fight(tmp_path, [PURIFYING])
    engine = combat._load_session(mid).engine
    engine._apply_condition(engine.state.actors[TABLE_ME], POISONED, "test:swamp", TABLE_FOE, expires_on=None)
    chosen = candidate(combat, mid, lambda c: str(c.source_definition_id).endswith(PURIFYING))
    assert send(combat, table, mid, chosen)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    assert not engine._has_condition(engine.state.actors[TABLE_ME], POISONED), \
        "the printed 'End one minor poison' did not happen"
    assert riders(engine, "contamination of things and surroundings"), \
        "the parts of the printed line the table does not track stay, worded as narration"


# ------------------------------------------------------------------------------ Talisman Recall: only a talisman that is really out there
def test_talisman_recall_is_not_offered_when_no_talisman_is_out_there(tmp_path):
    """"Choose one talisman you crafted": consuming a talisman leaves nothing behind that could be recalled."""
    combat, table, mid = three(tmp_path, [PURIFYING, RECALL])
    press(combat, table, mid, prefix="Purifying Talisman", target=TABLE_ME)
    engine = reload(tmp_path, mid)
    assert prepared(engine) == limit(engine) - 1, "the formula must have used up one prepared talisman"
    assert "Talisman Recall" not in menu(engine), \
        "with no talisman in the world Recall would conjure one: the button must not be on the menu"
    assert outside(engine) == 0, "consuming a talisman must not leave one out in the world"


def test_talisman_recall_needs_the_declared_talisman_and_brings_it_back(tmp_path):
    combat, table, mid = three(tmp_path, [PURIFYING, RECALL], outside=2)
    engine = combat._load_session(mid).engine
    press(combat, table, mid, prefix="Purifying Talisman", target=TABLE_ME)
    engine = reload(tmp_path, mid)
    assert "Talisman Recall" in menu(engine), "a declared talisman in the world is something to recall"
    next_turn(table, mid)
    prompts = press(combat, table, mid, name="Talisman Recall", steps=[""])
    engine = reload(tmp_path, mid)
    assert prepared(engine) == limit(engine), "a talisman that flies to your hand is a prepared talisman again"
    assert outside(engine) == 1, "the recalled talisman is no longer out in the world"
    assert notes(engine, "flies to"), "the printed result must be readable"
    assert any("lying unattended" in label for label in options(prompts[0]).values()), \
        "'If unattended, it flies to your hand'"
    assert any("Strength saving throw" in label for label in options(prompts[0]).values()), \
        "'If held or worn by another creature, that creature makes a Strength saving throw'"


def test_talisman_recall_lets_a_successful_save_keep_the_talisman_where_it_is(tmp_path, monkeypatch):
    combat, table, mid = three(tmp_path, [PURIFYING, RECALL], outside=1)
    press(combat, table, mid, prefix="Purifying Talisman", target=TABLE_ME)
    engine = reload(tmp_path, mid)
    before = prepared(engine)
    next_turn(table, mid)
    hit_dice(monkeypatch, save_roll=20)  # the holder's printed Strength saving throw succeeds
    prompts = press(combat, table, mid, name="Talisman Recall", steps=[TABLE_FOE])
    engine = reload(tmp_path, mid)
    assert prepared(engine) == before, "a saved talisman is not recalled"
    assert outside(engine) == 1, "'On a success, it remains where it is': the talisman is still out there"
    assert [event for event in saves(engine, ":STR") if event.actor_id == TABLE_FOE], \
        "the holder the fighter named, not the first creature on the field, makes the printed Strength saving throw"
    assert notes(engine, "stays where it is"), "the printed result must be readable"
    assert TABLE_FOE in options(prompts[0]), "the printed holder may be any creature"


def test_talisman_recall_asks_the_actual_holder_including_an_ally(tmp_path, monkeypatch):
    """The printed holder may be any creature: an ally wearing it answers the printed Strength saving throw."""
    combat, table, mid = three(tmp_path, [PURIFYING, RECALL], outside=1)
    press(combat, table, mid, prefix="Purifying Talisman", target=TABLE_ME)  # room for a recalled talisman
    next_turn(table, mid)
    hit_dice(monkeypatch, save_roll=1)  # the ally's Strength saving throw fails
    prompts = press(combat, table, mid, name="Talisman Recall", steps=[ALLY_TABLE])
    engine = reload(tmp_path, mid)
    assert ALLY_TABLE in options(prompts[0]), "an allied creature holding the talisman must be on the menu"
    assert [event for event in saves(engine, ":STR") if event.actor_id == ALLY_TABLE], \
        "the allied holder, not an enemy, must answer the printed Strength saving throw"
    assert prepared(engine) == limit(engine), "'On a failed save, the talisman returns to you'"


def test_talisman_recall_is_offered_at_full_prepared_capacity_without_exceeding_the_limit(tmp_path, monkeypatch):
    """"it flies to your hand or a legal space within your reach" is bringing the talisman back, not readying it.

    The printed Prepared Talisman Limit is the only thing that makes a talisman ready to use, so at the limit the recall
    still happens -- the talisman leaves the world and reaches the fighter's hand -- and waits there for the printed
    "Ready a talisman" instead of the limit being exceeded. Before the fix the button was not on the menu at all.
    """
    combat, table, mid = three(tmp_path, [PURIFYING, RECALL], outside=1)
    engine = reload(tmp_path, mid)
    assert prepared(engine) == limit(engine) and outside(engine) == 1, \
        "this case needs a fighter at the printed limit with a talisman out in the world"
    assert "Talisman Recall" in menu(engine), \
        "bringing a talisman back is not readying it, so the limit must not take the button off the menu"
    next_turn(table, mid)
    hit_dice(monkeypatch, save_roll=1)
    prompts = press(combat, table, mid, name="Talisman Recall", steps=[TABLE_FOE])
    engine = reload(tmp_path, mid)
    assert outside(engine) == 0, "the recalled talisman is no longer out in the world"
    assert prepared(engine) == limit(engine), \
        "'Your Prepared Talisman Limit ... only a limited number are immediately prepared': the limit is not exceeded"
    assert engine.state.actors[TABLE_ME].resource_maximums[PREPARED_LIMIT] == limit(engine), \
        "recalling a talisman may not raise the printed limit"
    assert [event for event in saves(engine, ":STR") if event.actor_id == TABLE_FOE], \
        "the holder the fighter named makes the printed Strength saving throw at the limit too"
    assert notes(engine, "Ready a talisman"), \
        "a talisman that arrived with no room under the limit must say how to ready it"
    assert any("lying unattended" in label for label in options(prompts[0]).values()), \
        "'If unattended, it flies to your hand'"


# ------------------------------------------------------------------------------ Read the Script: the fact(s) the fighter asked for
def read_the_script(tmp_path, mids, needles=()):
    combat, table, mid = three(tmp_path, mids)
    engine = combat._load_session(mid).engine
    assert any(str(row.source_definition_id).endswith(SCRIPT) for row in engine.action_catalog.values()), \
        "Read the Script must be a real action"
    # Talisman Scribe (one of the Sphere's automatic base abilities, so every fighter built by ``sheet`` owns it)
    # prints "Advantage on checks to identify a talisman formula you personally know". That boundary is asked between
    # the Difficulty Class question and the fact question (MGR-T14-ling-base-talisman-scribe-1); these cases answer
    # that the writing is NOT a formula the fighter personally know, so the check still rolls normally and the
    # printed facts asserted below are unchanged.
    prompts = press(combat, table, mid, name=SCRIPT_NAME,
                    steps=["Arcana", "worn or smudged", SCRIBE_NOT_MINE, *needles])
    return reload(tmp_path, mid), prompts


FACT_QUESTION = ": read "   # distinguishes the printed fact questions from other Read the Script questions


def asked_fact(prompt):
    """The printed fact the fact question offered under the answered option."""
    answered = pick(prompt, FACT_QUESTION)  # the printed fact questions read "Read the Script: read <fact>"
    return next(fact for fact in SCRIPT_FACTS if options(prompt)[answered].endswith(fact))


def test_read_the_script_rolls_an_intelligence_check_and_learns_the_fact_it_asked_for(tmp_path):
    engine, prompts = read_the_script(tmp_path, [PURIFYING])
    checks = [event for event in engine.events
              if event.event_type == "CHECK_ROLLED" and str(event.source_definition_id).endswith(SCRIPT)]
    assert len(checks) == 1, "the printed Intelligence check must be rolled"
    assert checks[0].payload["dc"] == 10 and checks[0].payload["skill"] == "Arcana"
    margin = int(checks[0].payload["actor"]["total"]) - int(checks[0].payload["dc"])
    assert margin >= 0, "this case needs a successful check; the seeded fight must supply one"
    learned = [line for line in notes(engine, "learns") if "learns nothing" not in line]
    assert learned, "a successful check must reveal a fact"
    # The questions that offered a printed fact, in the order asked. Other printed questions may precede them
    # (the Talismans Fighter's choice of proficiency, the Difficulty Class, Talisman Scribe's knowledge boundary),
    # so this reads the fact questions themselves rather than counting prompt positions.
    fact_prompts = [prompt for prompt in prompts
                    if any(FACT_QUESTION in label for label in options(prompt).values())]
    first = asked_fact(fact_prompts[0])
    if margin >= 5:
        assert len(fact_prompts) == 2, "'Success by 5 or more reveals an additional fact': exactly one more question"
        second = asked_fact(fact_prompts[1])
        assert second != first, "the additional fact must be a different one"
        assert learned[0].endswith(f"two facts: {first}; {second}."), learned
    else:
        assert len(fact_prompts) == 1, "'On a success, learn one': exactly one question and one fact"
        assert learned[0].endswith(f"one fact: {first}."), learned
    assert riders(engine, "what this writing shows about"), \
        "what the writing shows about the fact asked for is the table's to state, so it rides a GM rider"


def test_read_the_script_reveals_no_fact_when_the_check_fails(tmp_path, monkeypatch):
    from combat.gate2_rolls import DeterministicRollAuthority

    monkeypatch.setattr(DeterministicRollAuthority, "_die", lambda self, sides: (2, 0))
    combat, table, mid = three(tmp_path, [PURIFYING])
    press(combat, table, mid, name=SCRIPT_NAME, steps=["Arcana", "worn or smudged"])
    engine = reload(tmp_path, mid)
    assert notes(engine, "learns nothing"), "a failed check reveals nothing"
    assert not [line for line in notes(engine) if "one fact" in line or "two facts" in line], \
        "no fact may be revealed by a failed check"
    assert not riders(engine, "what this writing shows about"), \
        "a failed check reveals no fact, so it leaves the table nothing to state"


def test_read_the_script_honours_advantage_from_seal_bakers_eye(tmp_path):
    engine, _ = read_the_script(tmp_path, [PURIFYING, SEAL_EYE])
    checks = [event for event in engine.events
              if event.event_type == "CHECK_ROLLED" and str(event.source_definition_id).endswith(SCRIPT)]
    assert checks and checks[0].payload["actor"]["mode"] == "ADVANTAGE", \
        "Seal Breaker's Eye prints Advantage on Read the Script checks"


# ------------------------------------------------------------------------------ Featherfall Talisman
def launch(engine, victim, steps=4, roll=6):
    script(engine, [roll] * 20)
    victim.maximum_hp = victim.current_hp = 200
    falling.displace(engine, victim, steps, "test:launch")


def test_featherfall_talisman_spends_a_talisman_and_the_fall_is_safe():
    engine = duel([FEATHERFALL], ally_mids=[], primary="Stamina", cl=15)
    me, ally = engine.state.actors[ME], engine.state.actors[ALLY]
    engine._active_intent = intent_for(engine, ME, ALLY)
    before = me.resources.get(PREPARED, 0)
    assert before >= 1, "a talisman fighter starts with prepared talismans"
    launch(engine, ally)
    assert engine._has_condition(ally, FEATHERFALL_CONDITION), "the safe descent was not recorded"
    assert ally.current_hp == 200, "the printed 'takes no falling damage' did not happen"
    assert not engine._has_condition(ally, "condition:typed.prone"), "a safe descent lands upright"
    assert me.resources.get(PREPARED, 0) == before - 1, "'Consumed: yes' did not use a talisman"
    resolved = [event for event in engine.events if event.event_type == "REACTION_RESOLVED" and event.actor_id == ME]
    assert resolved and str(resolved[-1].source_definition_id).endswith(FEATHERFALL), "the Reaction was not spent"


def test_featherfall_talisman_never_spends_a_second_talisman_or_reaches_past_thirty_feet():
    engine = duel([FEATHERFALL], ally_mids=[], primary="Stamina", cl=15)
    me, ally, foe = engine.state.actors[ME], engine.state.actors[ALLY], engine.state.actors[FOE]
    engine._active_intent = intent_for(engine, ME, ALLY)
    before = me.resources.get(PREPARED, 0)
    # Already descending safely: no second talisman is spent for the same fall.
    engine._apply_condition(ally, FEATHERFALL_CONDITION, FEATHERFALL, ME, expires_on=None,
                            data={"fall_speed_ft": 30, "fall_damage_immune": 1, "fall_lands_upright": 1})
    launch(engine, ally)
    assert me.resources.get(PREPARED, 0) == before, "a protected creature must not cost another talisman"
    # Out of range: the printed talisman cannot reach, so the fall still hurts.
    foe.position = foe.position.model_copy(update={"x": foe.position.x + 60, "z": 4})
    script(engine, [6] * 20)
    foe.maximum_hp = foe.current_hp = 200
    falling.settle(engine)
    assert foe.current_hp < 200, "beyond 30 feet the printed talisman cannot help"
    assert me.resources.get(PREPARED, 0) == before


# ------------------------------------------------------------------------------ Elemental Talisman: damage type, crafting payment, one roll
def toggle(tmp_path, mids, needles):
    """Take the free "Elemental Talisman: choose a damage type" button, answering with the named damage types."""
    combat, table, mid = three(tmp_path, mids)
    prompts = press(combat, table, mid, name=TOGGLE, steps=list(needles))
    return combat, table, mid, prompts, reload(tmp_path, mid)


def test_elemental_talisman_offers_every_damage_type_not_yet_chosen(tmp_path):
    """"Choose Acid, Cold, Fire, Lightning, or Thunder": the menu is the printed five, not the first one or two.

    One learning allows one damage type, and the print names which five it may be.  Before the fix the menu was cut
    down to the number of learnings left, so this fighter could only ever pick Acid.
    """
    combat, table, mid = three(tmp_path, [EMBER, ELEMENTAL])
    try:
        prompts = press(combat, table, mid, name=TOGGLE, steps=["Thunder"])
    except StopIteration as exc:  # the printed damage type was never on the menu to answer with
        raise AssertionError(
            "'Choose Acid, Cold, Fire, Lightning, or Thunder': the menu is the printed five and Thunder is one of them"
        ) from exc
    offered = options(prompts[0])
    engine = reload(tmp_path, mid)
    assert set(offered) == {"acid", "cold", "fire", "lightning", "thunder"}, \
        f"one learning of Elemental Talisman may choose any of the printed five damage types, not {list(offered)}"
    assert learned(engine) == {"thunder"}, learned(engine)
    assert any("craft talismans that deal Thunder damage" in label for label in offered.values()), \
        "what the choice buys must be readable"
    assert TOGGLE not in menu(engine), "the printed damage type is chosen; the toggle has nothing left to offer"


def test_elemental_talisman_offers_fire_and_thunder_with_only_two_learnings(tmp_path):
    """Two learnings used to limit the menu to Acid and Cold, so Fire and Thunder could never be chosen at all.

    "You may learn this talent multiple times, choosing a different damage type each time" constrains the choices to
    be different from one another; it says nothing about which of the printed five they may be.
    """
    combat, table, mid, prompts, engine = toggle(tmp_path, [EMBER, ELEMENTAL, ELEMENTAL], ["Acid"])
    assert {"fire", "thunder"} <= set(options(prompts[0])), \
        f"two learnings may reach any of the printed five damage types, not {list(options(prompts[0]))}"
    next_turn(table, mid)
    press(combat, table, mid, name=TOGGLE, steps=["Thunder"])
    engine = reload(tmp_path, mid)
    assert learned(engine) == {"acid", "thunder"}, \
        "'choosing a different damage type each time' adds a damage type; the first one must survive"
    assert pill(engine) == "Elemental Talisman: Acid, Thunder", \
        f"the pill must show every damage type this fighter may craft with: {pill(engine)!r}"
    assert notes(engine, "Thunder damage"), "the second learning's damage type must be readable"
    assert TOGGLE not in menu(engine), "'a different damage type each time': every learning has its own damage type"


def test_elemental_talisman_still_offers_a_type_for_each_learning_left(tmp_path):
    """Each learning takes one damage type of its own, and the menu drops what that learning has already taken.

    Three learnings, three presses: after the first choice the four unchosen types are what is left to offer, the
    button stays on the menu while a learning has no damage type of its own yet, and it leaves once all three have
    one -- even though two of the printed five were never chosen.
    """
    combat, table, mid, prompts, engine = toggle(tmp_path, [EMBER, ELEMENTAL, ELEMENTAL, ELEMENTAL], ["Fire"])
    assert set(options(prompts[0])) == {"acid", "cold", "fire", "lightning", "thunder"}, \
        f"nothing has been chosen yet, so the whole printed list is on offer: {list(options(prompts[0]))}"
    assert TOGGLE in menu(engine), "two learnings of Elemental Talisman still have no damage type of their own"
    next_turn(table, mid)
    prompts = press(combat, table, mid, name=TOGGLE, steps=["Lightning"])
    assert set(options(prompts[0])) == {"acid", "cold", "lightning", "thunder"}, \
        "'a different damage type each time': the type already chosen (Fire) is not offered again"
    assert TOGGLE in menu(reload(tmp_path, mid)), "the third learning still has no damage type of its own"
    next_turn(table, mid)
    press(combat, table, mid, name=TOGGLE, steps=["Thunder"])
    engine = reload(tmp_path, mid)
    assert learned(engine) == {"fire", "lightning", "thunder"}, learned(engine)
    assert TOGGLE not in menu(engine), "every learning of Elemental Talisman has a damage type of its own"


def test_elemental_talisman_reuses_a_learned_damage_type_for_each_talisman(tmp_path, monkeypatch):
    """"Choose ... when you craft a compatible Attack formula": the damage type belongs to the talisman, not the fighter.

    Two learnings, so the fighter has chosen Acid and Cold; each Ember Talisman they activate names the damage type it
    was crafted for, and the talismans may differ even though the formula is the same -- and a third talisman crafted
    for the first type again may be crafted for it again, because choosing a type never uses it up.  Before the fix the
    type was one fighter-wide setting, the last one chosen won, and every strike dealt the same damage.
    """
    combat, table, mid = three(tmp_path, [EMBER, ELEMENTAL, ELEMENTAL], foe_at=SEEN_FOE)
    engine = combat._load_session(mid).engine
    foe = engine.state.actors[TABLE_FOE]
    foe.armor_class = 10
    foe.maximum_hp = foe.current_hp = 1000
    press(combat, table, mid, name=TOGGLE, steps=["Acid"])
    next_turn(table, mid)
    press(combat, table, mid, name=TOGGLE, steps=["Cold"])
    assert learned(reload(tmp_path, mid)) == {"acid", "cold"}
    hit_dice(monkeypatch)
    struck = []
    for crafted in ("Acid", "Cold", "Acid"):
        next_turn(table, mid)
        give(combat._load_session(mid).engine, TABLE_ME, stamina=30)
        try:
            prompts = press(combat, table, mid, name="Ember Talisman", target=TABLE_FOE, steps=[crafted, "1 cultivation points (your Path resource) or more"])
        except StopIteration as exc:  # the talisman's own damage type was never put to the player
            raise AssertionError(
                f"Elemental Talisman never asked which damage type this talisman was crafted for ({crafted}): "
                f"'Choose Acid, Cold, Fire, Lightning, or Thunder when you craft a compatible Attack formula'") from exc
        assert any("which damage type did you choose for this talisman" in question.lower()
                   for question in elemental_prompts(prompts)), \
            "the damage type of the talisman being activated is a player-owned choice"
        engine = reload(tmp_path, mid)
        dealt = packets(engine, TABLE_FOE)
        struck.append(str(dealt[-1].payload.get("damage_type")) if dealt else "nothing")
    assert struck == ["ACID", "COLD", "ACID"], \
        f"each talisman deals the damage type it was crafted for, and a learned type is offered again for a later " \
        f"talisman: {struck}"
    assert learned(engine) == {"acid", "cold"}, "crafting with a damage type must not use it up"
    assert TOGGLE not in menu(engine), "'a different damage type each time' allows no further choice"


def test_elemental_talisman_asks_nothing_of_a_talisman_that_makes_no_attack(tmp_path):
    """"when you craft a compatible Attack formula": a talisman that makes no attack gets neither printed question."""
    combat, table, mid = three(tmp_path, [HEALING, ELEMENTAL])
    press(combat, table, mid, name=TOGGLE, steps=["Acid"])
    next_turn(table, mid)
    prompts = press(combat, table, mid, prefix="Healing Talisman", target=ALLY_TABLE)
    engine = reload(tmp_path, mid)
    assert not elemental_prompts(prompts), \
        "a Healing Talisman has no damage roll and no crafted damage type; Elemental Talisman has nothing to ask"
    assert learned(engine) == {"acid"}, "what the fighter may craft with is untouched by a talisman that makes no attack"


def ember_strike(monkeypatch, tmp_path, mids, *, element="Acid", crafting="1 cultivation points (your Path resource) or more", crafted=None):
    """An Ember Talisman strike at the table, with the printed crafting questions answered.

    One learning of Elemental Talisman leaves one damage type chosen, and a fighter with a single learned damage type
    is not asked which one it is, so only the crafting payment is answered here.
    """
    combat, table, mid = three(tmp_path, mids, foe_at=SEEN_FOE)
    engine = combat._load_session(mid).engine
    engine.state.actors[TABLE_FOE].armor_class = 10  # the scripted d20 hits
    give(engine, TABLE_ME, stamina=30)
    steps = []
    if element:
        press(combat, table, mid, name=TOGGLE, steps=[element])
        next_turn(table, mid)
        if crafted:
            steps.append(crafted)
    hit_dice(monkeypatch)
    press(combat, table, mid, name="Ember Talisman", target=TABLE_FOE, steps=[*steps, crafting])
    return reload(tmp_path, mid)


def printed_dice(engine):
    rolled = dice_of(engine, EMBER)
    return sum(int(die) for die in rolled[-1].payload["dice"])


def test_elemental_talisman_adds_the_proficiency_bonus_only_for_a_paid_craft(tmp_path, monkeypatch):
    engine = ember_strike(monkeypatch, tmp_path, [EMBER, ELEMENTAL])
    dealt = packets(engine, TABLE_FOE)
    assert dealt, "the Talisman Attack dealt no damage"
    assert {str(packet.payload.get("damage_type")) for packet in dealt} == {"ACID"}, \
        "the printed damage type was not applied"
    pb = engine.state.actors[TABLE_ME].proficiency_bonus
    assert int(dealt[-1].payload["reduced_to"]) == printed_dice(engine) + pb, \
        "'When you spend at least 1 CP while crafting the talisman, add your Proficiency Bonus to one damage roll'"


def test_elemental_talisman_without_the_crafting_payment_deals_no_bonus(tmp_path, monkeypatch):
    engine = ember_strike(monkeypatch, tmp_path, [EMBER, ELEMENTAL], crafting="no cultivation points (your Path resource)")
    dealt = packets(engine, TABLE_FOE)
    assert int(dealt[-1].payload["reduced_to"]) == printed_dice(engine), \
        "a talisman crafted without spending CP gains no Proficiency Bonus"


def test_elemental_talisman_is_inert_for_a_fighter_who_has_not_chosen_an_element(tmp_path, monkeypatch):
    engine = ember_strike(monkeypatch, tmp_path, [EMBER, ELEMENTAL], element=None)
    dealt = packets(engine, TABLE_FOE)
    assert {str(packet.payload.get("damage_type")) for packet in dealt} == {"FIRE"}, \
        "before an element is chosen the formula keeps its own printed type"
    assert int(dealt[-1].payload["reduced_to"]) == printed_dice(engine), \
        "no element chosen means the formula is not one of this fighter's Elemental Talismans"


def test_elemental_talisman_leaves_another_fighter_untouched(tmp_path, monkeypatch):
    """A fighter without the talent keeps their Talisman Attack's own type and damage."""
    engine = ember_strike(monkeypatch, tmp_path, [EMBER], element=None)
    dealt = packets(engine, TABLE_FOE)
    assert {str(packet.payload.get("damage_type")) for packet in dealt} == {"FIRE"}
    assert int(dealt[-1].payload["reduced_to"]) == printed_dice(engine)
    assert not any(row.condition_id == ELEMENT for row in engine.state.actors[TABLE_ME].conditions.values())
    assert TOGGLE not in menu(engine), "the toggle belongs to the talent's owner alone"


def test_elemental_talisman_bonus_reaches_one_damage_roll_of_the_talisman():
    """"add your Proficiency Bonus to one damage roll the talisman makes": a second roll of the same activation is plain.

    No printed talisman Attack formula rolls damage twice, so this is the row itself: two damage rows of one activation
    through the shipped hook, and the second must come back empty.
    """
    from types import SimpleNamespace

    from combat.ext import talismans

    engine = duel([EMBER, ELEMENTAL], primary="Stamina", cl=10)
    me = engine.state.actors[ME]
    engine.__dict__[CRAFTING_PAID] = True
    engine.__dict__[CRAFTED_ELEMENT] = "cold"
    engine._apply_condition(me, ELEMENT, ELEMENTAL, ME, expires_on="UNTIL_REMOVED", data={"elements": ["cold"]})
    action = next(row for row in engine.action_catalog.values() if str(row.source_definition_id).endswith(EMBER))
    ctx = SimpleNamespace(engine=engine, actor=me, action=action, typed={"effects": [{"type": "attack"}]},
                          damage_cache={}, weapon_damage_dice=False)
    first = talismans.elemental_proficiency_bonus(ctx, {"type": "damage"}, ["fire"])
    second = talismans.elemental_proficiency_bonus(ctx, {"type": "damage"}, ["fire"])
    assert first == me.proficiency_bonus, "the first damage roll of the talisman gains the printed Proficiency Bonus"
    assert second is None, "'one damage roll the talisman makes': a second roll of the same activation gains nothing"
    # Without a damage type chosen for this very talisman there is nothing to pay the printed bonus on.
    engine.__dict__.pop(CRAFTED_ELEMENT)
    engine.__dict__[CRAFTING_PAID] = True
    assert talismans.elemental_proficiency_bonus(ctx, {"type": "damage"}, ["fire"]) is None, \
        "'When you spend at least 1 CP while crafting the talisman' is not enough on its own"


# ------------------------------------------------------------------------------ Remote Activation: the talisman's holder, not its target
def test_remote_activation_reaches_sixty_feet_but_keeps_the_formulas_own_reach(tmp_path):
    combat, table, mid = fight(tmp_path, [PURIFYING, REMOTE])
    engine = combat._load_session(mid).engine
    purifying = next(row for row in engine.action_catalog.values() if str(row.source_definition_id).endswith(PURIFYING))
    assert purifying.range_ft == 60, "a Touch formula must be reachable at 60 feet for an owner of Remote Activation"
    assert (purifying.parameters or {}).get("remote_range_ft") == 5, \
        "'as if you were holding it' keeps the formula's own printed reach"


def test_remote_activation_asks_the_actual_holder_not_the_formula_target(tmp_path, monkeypatch):
    combat, table, mid = three(tmp_path, [PURIFYING, REMOTE, DEMON_TAG], foe_at=SEEN_FOE)
    before = prepared(combat._load_session(mid).engine)
    hit_dice(monkeypatch, save_roll=20)
    prompts = press(combat, table, mid, name="Demon-Subduing Tag", steps=[ALLY_TABLE, "refuses"])
    engine = reload(tmp_path, mid)
    offered = options(prompts[0])
    assert ALLY_TABLE in offered and TABLE_FOE in offered, \
        "every creature within 60 feet may hold the talisman, allies and enemies alike"
    assert any("your own hand" in label for label in offered.values()), \
        "'as if you were holding it' also covers the talisman in the caster's own hand"
    assert [event for event in saves(engine, ":WIS") if event.actor_id == ALLY_TABLE], \
        "the holder answers the printed Wisdom save, not the caster and not the formula's target"
    assert prepared(engine) == before, "'your remote activation fails but the talisman is not consumed'"
    assert notes(engine, "not used"), "the refusal must be readable"
    assert not engine._has_condition(engine.state.actors[TABLE_FOE], "condition:typed.restrained"), \
        "a saved activation must not resolve the formula"


def test_remote_activation_a_failed_save_does_not_stop_it(tmp_path, monkeypatch):
    combat, table, mid = three(tmp_path, [PURIFYING, REMOTE, DEMON_TAG], foe_at=SEEN_FOE)
    before = prepared(combat._load_session(mid).engine)
    hit_dice(monkeypatch, save_roll=2)
    press(combat, table, mid, name="Demon-Subduing Tag", steps=[ALLY_TABLE, "refuses"])
    engine = reload(tmp_path, mid)
    assert prepared(engine) == before - 1, "a holder that fails its Wisdom save cannot stop the activation"
    assert engine._has_condition(engine.state.actors[TABLE_FOE], "condition:typed.restrained"), \
        "a failed Charisma saving throw must still restrain the formula's own target"


def test_remote_activation_keeps_the_formulas_own_reach_from_the_talisman(tmp_path, monkeypatch):
    """"as if you were holding it": a Touch formula reaches 5 feet from the talisman, not 60 feet from the caster."""
    combat, table, mid = three(tmp_path, [PURIFYING, REMOTE], foe_at=SEEN_FOE)
    engine = combat._load_session(mid).engine
    before = prepared(engine)
    # A visible holder is offered by the printed perception gate. Its talisman
    # remains well beyond Touch reach of the ally the formula is aimed at.
    press(combat, table, mid, name="Purifying Talisman", target=ALLY_TABLE, steps=[TABLE_FOE])
    engine = reload(tmp_path, mid)
    assert prepared(engine) == before, "a target beyond the formula's own reach of the talisman is not affected"
    assert notes(engine, "reaches 5 feet from the talisman"), "the printed refusal must be readable"


def test_remote_activation_resolves_when_the_formula_reaches_the_target_from_the_talisman(tmp_path, monkeypatch):
    combat, table, mid = three(tmp_path, [PURIFYING, REMOTE])
    engine = combat._load_session(mid).engine
    engine._apply_condition(engine.state.actors[ALLY_TABLE], POISONED, "test:swamp", TABLE_FOE, expires_on=None)
    press(combat, table, mid, name="Purifying Talisman", target=ALLY_TABLE, steps=[""])
    engine = reload(tmp_path, mid)
    assert not engine._has_condition(engine.state.actors[ALLY_TABLE], POISONED), \
        "the printed 'End one minor poison' must happen when the talisman can reach the target"
    assert notes(engine, "own hand") or not notes(engine, "reaches"), "no printed refusal for a reachable target"


# ------------------------------------------------------------------------------ Talisman Bomb: "6 CP plus consumed talismans"
def test_talisman_bomb_costs_its_printed_cp_and_consumes_its_talismans(tmp_path):
    combat, table, mid = fight(tmp_path, [PURIFYING, BOMB])
    engine = combat._load_session(mid).engine
    me = engine.state.actors[TABLE_ME]
    before, cp = me.resources.get(PREPARED, 0), me.resources.get(STAMINA, 0)
    assert before >= 2 and cp >= 6, "the printed bomb needs prepared talismans and 6 CP"
    prompts = press(combat, table, mid, prefix=BOMB_NAME, steps=["in the bomb"])
    engine = reload(tmp_path, mid)
    me = engine.state.actors[TABLE_ME]
    assert me.resources.get(STAMINA, 0) == cp - 6, "'Cost: 6 CP plus consumed talismans': the CP was not paid"
    assert me.resources.get(PREPARED, 0) == before - me.proficiency_bonus, \
        "'Bundle up to your Proficiency Bonus compatible talismans' must spend the most the printed limit allows"
    assert notes(engine, "Bomb bundles"), "what the bomb was made of must be readable"
    assert riders(engine, "Focused Bomb"), "the printed mode the table chooses stays worded as it is printed"
    labels = list(options(prompts[0]).values())
    assert all("improve" not in label for label in labels), \
        f"a bundle option must not promise an improvement the engine does not make: {labels}"


def test_talisman_bomb_is_offered_only_while_a_talisman_is_prepared(tmp_path):
    combat, table, mid = fight(tmp_path, [PURIFYING, BOMB])
    engine = combat._load_session(mid).engine
    engine.state.actors[TABLE_ME].resources[PREPARED] = 0
    assert not [c for c in engine.legal_candidates() if str(c.display_name).startswith(BOMB_NAME)], \
        "a bomb with no talisman to bundle must not be on the menu"


# ------------------------------------------------------------------------------ Talisman Array and Ten Thousand Tags Obey: the table's to place
def test_talisman_array_and_tags_obey_stay_the_table_s_to_place(tmp_path):
    """The printed array resolves "when one activates" inside it, which the engine cannot detect.

    So no button spends prepared talismans into an array the engine would never resolve, remove or refund, and the
    printed lines stay visible to the table instead of being claimed as automated.
    """
    from combat.factory_compiler import TYPED_AUTHORITY

    combat, table, mid = fight(tmp_path, [PURIFYING, ARRAY, TAGS])
    engine = combat._load_session(mid).engine
    before = prepared(engine)
    assert ARRAY_NAME not in menu(engine), \
        "an action that spends prepared talismans with no way to resolve, remove or recover them must not be offered"
    assert not [c for c in engine.action_catalog.values() if ARRAY_NAME in str(c.display_name)]
    assert prepared(engine) == before, "no array setup may spend prepared talismans"
    assert TAGS_KEEP not in engine.state.actors[TABLE_ME].resources, \
        "a once-per-long-rest benefit for a deferred array must not be spent at setup"
    record = json.loads(TYPED_AUTHORITY.read_bytes())["mechanics"]
    for key, printed in ((ARRAY, "Setup Time: 1 minute"), (ARRAY, "3 CP plus the talismans used"),
                         (ARRAY, "Reinforced Effect"), (ARRAY, "Layered Array"),
                         (ARRAY, "not a full Formation"),
                         (TAGS, "twice your Proficiency Bonus"), (TAGS, "prevent that talisman from being consumed")):
        lines = [str(row) for row in record[key].get("riders") or []]
        assert any(printed in line for line in lines), f"{key} lost the printed line {printed!r}: {lines}"


# ------------------------------------------------------------------------------ Living Scripture Servitor
@pytest.mark.parametrize("servitor,expected", [(True, 2), (False, 1)])
def test_living_scripture_servitor_doubles_the_spirit_and_keeps_it_ten_minutes(servitor, expected):
    from tests.h1_support import bundle

    document = bundle([SPIRIT] + ([SERVITOR] if servitor else []), primary="Stamina", cl=15)
    spirits = [row for row in document["summons"]
               if row["actor_template"]["display_name"] == "Talisman Spirit"]
    assert spirits, "the Talisman Spirit is not compiled"
    pb = int(document["actor_template"]["proficiency_bonus"])
    assert spirits[0]["actor_template"]["maximum_hp"] == expected * 5 * pb, spirits[0]["actor_template"]["maximum_hp"]
    action = next(row for row in document["action_catalog"] if str(row["source_definition_id"]).endswith(SPIRIT))
    duration = (action["parameters"].get("typed") or {}).get("duration") or {}
    assert (duration.get("kind"), duration.get("amount")) == (("minutes", 10) if servitor else ("minutes", 1)), duration


def test_living_scripture_servitor_spirit_survives_a_table_commit_and_reload(tmp_path):
    """"hit points become 10 x your Proficiency Bonus; duration becomes 10 minutes" at the table, not only in the catalog."""
    combat, table, mid = fight(tmp_path, [SPIRIT, SERVITOR])
    engine = combat._load_session(mid).engine
    pb = engine.state.actors[TABLE_ME].proficiency_bonus
    assert not [actor for actor in engine.state.actors.values()
                if (actor.summon or {}).get("status") == "present"], "no spirit is out yet"
    chosen = candidate(combat, mid, lambda c: str(c.source_definition_id).endswith(SPIRIT))
    assert send(combat, table, mid, chosen)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    spirits = [actor for actor in engine.state.actors.values()
               if (actor.summon or {}).get("group") == "talisman_spirit" and (actor.summon or {}).get("status") == "present"]
    assert spirits, [actor.summon for actor in engine.state.actors.values() if actor.summon]
    spirit = spirits[0]
    assert spirit.maximum_hp == 10 * pb, spirit.maximum_hp
    assert spirit.summon["duration_rounds"] == 10, spirit.summon
    assert spirit.summon["duration_text"] == "10 minutes", spirit.summon
    clocks = [str(row.expires_on) for row in spirit.conditions.values()]
    assert any("START_OF_SLOT_AT" in row for row in clocks), \
        f"the spirit's printed ten-minute lifetime must be a slot clock, not only compiled: {clocks}"

# ------------------------------------------------------------------------------ item 12: what this lane must NOT move
def test_an_unowned_ai_fight_matches_the_pre_lane_capture(tmp_path):
    """Compare every persisted event against the merged mainline, not an obsolete digest.

    Independent subprocesses load exact base sources and the working candidate.
    Mainline changes are present in both arms; a lane-only behavior leak still fails.
    """
    from tests.replay_base import replay_base_or_skip
    from tests.talisman_unowned_capture import compare

    compare(tmp_path, replay_base_or_skip())
