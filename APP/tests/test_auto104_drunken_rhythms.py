"""AUTO104: Drunken Style's printed Rhythms resolve at the table (the Broken-Rhythm Strike maneuver, Slapstick Escape,
Staggering Shove, The Floor Betrays You, Lucky-Looking Miss and Laughing Feint).

Every case commits through TabletopService and is read back from a fresh CombatService reload, so a change that only compiles
is not counted: the printed effect has to have happened in fight state. Outcomes are pinned in the compiled bundle (a weapon
attack's to-hit and a Drunken Style save's DC) rather than by scripting dice, so a multi-question cast stays deterministic.
"""
import pytest
from types import SimpleNamespace

from combat.ext import dazed_restriction
from combat.ext.drunken_style import (BROKEN, DAZED, FEINT, FEINT_ALLY, FEINT_BAD_READ, FEINT_DEADLINE, FEINT_NO_OA,
                                      FLOOR, LUCKY, LUCKY_AIM, MARK, SLAPSTICK, STAGGERING)
from tests.auto_worker1_support import LEFT, OTHER, RIGHT, act, fight, reload, resolve, triple_fight
from tests.h1_support import ROOT, script, sheet
from tests.hunt15_support import turn

FOCUS = "resource:core.martial_focus"
ADJACENT = {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}}
SPEND_FOCUS = {"type": "spend_resource", "resource_id": FOCUS, "flat": 1, "applies_to": "self"}
STRIKE = "Broken-Rhythm Strike: Bi Shou (Dagger)"


LONG_MARK = {"type": "mark", "mark": MARK, "applies_to": "target", "duration": {"kind": "minutes", "amount": 1}}


def _pin_weapon(hit=True, only=None):
    """Pin every weapon attack this bundle's character makes, so its attack roll is decided by the pinned to-hit alone."""
    def edit(bundle):
        if only and bundle.get("actor_id") != only:
            return
        for action in bundle["action_catalog"]:
            typed = (action.get("parameters") or {}).get("typed") or {}
            if typed.get("weapon") and any(row.get("type") == "attack" for row in typed.get("effects") or []):
                typed.setdefault("numbers", {})["attack_bonus"] = 100 if hit else -100
    return edit


def _pin_shove(save_dc):
    """Pin the Unarmed Strike Shove option's own save DC in the compiled bundle."""
    def edit(bundle):
        for action in bundle["action_catalog"]:
            typed = (action.get("parameters") or {}).get("typed") or {}
            if str(typed.get("unarmed_option") or "").startswith("shove"):
                typed.setdefault("numbers", {})["save_dc"] = save_dc
    return edit


def _pin(*, hit=True, save_dc=None, only=None):
    """Pin the Broken-Rhythm Strike maneuver's own to-hit (and its Drunken Style save DC) in the compiled bundle."""
    def edit(bundle):
        if only and bundle.get("actor_id") != only:
            return
        for action in bundle["action_catalog"]:
            typed = (action.get("parameters") or {}).get("typed") or {}
            if ".broken_rhythm" in str(action.get("source_definition_id") or "") or typed.get("maneuver") == "broken_rhythm":
                numbers = typed.setdefault("numbers", {})
                numbers["attack_bonus"] = 100 if hit else -100
                if save_dc is not None:
                    numbers["save_dc"] = save_dc
    return edit


def _reach_pins(*, only=None, reach=None):
    """Give that creature's own weapon attacks a printed reach. Only the ActionDefinition's reach moves: a melee weapon
    keeps an empty typed range, which is what still makes it a melee attack."""
    def edit(bundle):
        if only and bundle.get("actor_id") != only:
            return
        for action in bundle["action_catalog"]:
            if action.get("owner_id") != bundle["actor_id"]:
                continue
            typed = (action.get("parameters") or {}).get("typed") or {}
            if typed.get("weapon") and any(row.get("type") == "attack" for row in typed.get("effects") or []):
                action["range_ft"] = reach
    return edit


def _labels(table, mid):
    return [group["label"] for group in table.state(mid)["menu"]["actions"]]


def _cast(table, mid, label, picks=None, **kwargs):
    return resolve(lambda reply: act(table, mid, label, reply, **kwargs), picks)


def _use_modifier(table, mid, name):
    """Turn a "changes Broken-Rhythm Strike" talent on for that ability and choose its effect, through the table's own
    attack-modifier settings (the two settings a printed talent offers: on/off, then the effect on a hit)."""
    _cast(table, mid, f"{name}: {name}")
    effect_setting = next(label for label in _labels(table, mid)
                          if label.startswith(f"{name}: ") and label != f"{name}: {name}"
                          and "Ask me when it hits" not in label)
    _cast(table, mid, effect_setting)


def _off_rhythm(actor, owner=LEFT):
    """Whether ``actor`` bears the Off-Rhythm mark ``owner`` placed."""
    from combat.typed_executor import mark_condition_id

    return any(row.condition_id == mark_condition_id(MARK, owner) for row in actor.conditions.values())


PRONE = "condition:typed.prone"


def _miss(combat, table, mid, label, picks=None, **kwargs):
    """Cast ``label`` with every die this engine rolls scripted to 1, so the attack always misses by at most 5 and the
    printed "Miss by 5 or Less" branch runs. The table re-executes the action for each answer, so each one is scripted."""
    def send(reply):
        script(combat._load_session(mid).engine, [1])
        return act(table, mid, label, reply, **kwargs)
    return resolve(send, picks)


def _step(combat, table, mid, label, key, name, before, **kwargs):
    """Cast ``label`` and, when the printed step is offered, answer with one of its own legal destinations: the first
    option that is not the creature's current cell."""
    def send(reply):
        script(combat._load_session(mid).engine, [1])
        return act(table, mid, label, reply, **kwargs)
    answers, prompts = [], []
    for _ in range(12):
        result = send(answers)
        if result["status"] != "REACTION_REQUIRED":
            assert result["status"] == "COMMITTED", result
            return result, prompts
        prompt = result["reaction"]
        prompts.append(prompt)
        options = [o["id"] for o in (prompt.get("choice") or {}).get("options", [])]
        here = f"cell:{before.x},{before.y}"
        chosen = [next((o for o in options if o != here), options[0])] if prompt["context"]["reaction_source_id"] == key \
            else options[:1]
        answers.append({**prompt["context"], "selection": "USE" if chosen or not prompt.get("choice") else "DECLINE",
                        "option_ids": chosen})
    raise AssertionError("too many choices")


def _reminders(combat, mid):
    return [e.payload.get("rider") for e in combat._load_session(mid).engine.events if e.event_type == "GM_RIDER"]


# ------------------------------------------------------------------------------------------------ the maneuver
def test_broken_rhythm_strike_is_built_from_weapons_and_its_printed_talents_reach_it(tmp_path):
    """The root cause this lane found: Broken-Rhythm Strike was built from the compile_actions hook, which the compiler's
    modifier pass runs before, so every talent printing "with Broken-Rhythm Strike" reported "no matching ability"."""
    combat, table, mid = fight(tmp_path, [BROKEN, FLOOR])
    report = {row["id"]: row for row in (combat._load_session(mid).engine.typed_bundle_documents[0].get("modifiers") or [])}
    assert report[FLOOR]["status"] == "applied", report[FLOOR]
    assert STRIKE in _labels(table, mid)


def test_broken_rhythm_strike_marks_the_target_off_rhythm_on_a_hit(tmp_path):
    combat, table, mid = fight(tmp_path, [BROKEN], bundle_edit=_pin(hit=True), positions=ADJACENT)
    _cast(table, mid, STRIKE, target_id=RIGHT)
    assert _off_rhythm(reload(combat, mid).state.actors[RIGHT]), "Hit: the target becomes Off-Rhythm from you"


def test_the_floor_betrays_you_dazes_on_a_failed_save(tmp_path):
    combat, table, mid = fight(tmp_path, [BROKEN, FLOOR], bundle_edit=_pin(hit=True, save_dc=40))
    _use_modifier(table, mid, "The Floor Betrays You")
    _, prompts = _cast(table, mid, STRIKE, target_id=RIGHT)
    assert not [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.drunken_floor_betrayed"]
    target = reload(combat, mid).state.actors[RIGHT]
    assert dazed_restriction.holds(target), "Failed Save: Prone and Dazed"
    assert any(row.condition_id == PRONE for row in target.conditions.values())
    assert not target.reaction_available, "Dazed: cannot take Reactions"
    assert not _reminders(combat, mid)


def test_the_floor_betrays_you_asks_prone_or_dazed_on_a_successful_save(tmp_path):
    combat, table, mid = fight(tmp_path, [BROKEN, FLOOR], bundle_edit=_pin(hit=True, save_dc=2))
    _use_modifier(table, mid, "The Floor Betrays You")
    _, prompts = _cast(table, mid, STRIKE, {"choice:needle.drunken_floor_betrayed": ["dazed"]}, target_id=RIGHT)
    asked = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.drunken_floor_betrayed"]
    assert asked, "Successful Save: the target is Prone, or it is Dazed, your choice"
    assert {o["id"] for o in asked[0]["choice"]["options"]} == {"prone", "dazed"}
    assert "Dazed" in str(asked[0]), "the prompt says what Dazed does"
    assert dazed_restriction.holds(reload(combat, mid).state.actors[RIGHT])
    assert not _reminders(combat, mid)


def test_the_floor_betrays_you_is_inert_without_the_talent(tmp_path):
    combat, table, mid = fight(tmp_path, [BROKEN], bundle_edit=_pin(hit=True), positions=ADJACENT)
    _cast(table, mid, STRIKE, target_id=RIGHT)
    assert not dazed_restriction.holds(reload(combat, mid).state.actors[RIGHT])


# ------------------------------------------------------------------------------------------------ Slapstick Escape
def test_slapstick_escape_asks_five_feet_after_a_melee_miss(tmp_path):
    """Printed: "When a creature misses you with a melee attack, you may move 5 feet without provoking Opportunity Attacks
    from that creature.\""""
    combat, table, mid = fight(tmp_path, [SLAPSTICK], right_talents=[BROKEN], positions=ADJACENT)
    before = reload(combat, mid).state.actors[LEFT].position
    turn(table, mid, RIGHT)
    _, prompts = _step(combat, table, mid, STRIKE, "choice:needle.drunken_slapstick_step", "Slapstick Escape",
                       before, target_id=LEFT)
    assert any("5 feet" in str(prompt) for prompt in prompts), [str(p) for p in prompts]
    after = reload(combat, mid).state.actors[LEFT].position
    assert (after.x, after.y) != (before.x, before.y)
    assert combat._load_session(mid).engine.grid.distance_ft(before, after) <= 5
    assert not _reminders(combat, mid)


def test_slapstick_escape_asks_ten_feet_against_an_off_rhythm_attacker(tmp_path):
    """Printed: "If the attacker was Off-Rhythm from you, you may move 10 feet instead\""""
    def edits(bundle):
        _pin(hit=True, only=LEFT)(bundle)
        _pin(hit=False, only=RIGHT)(bundle)

    combat, table, mid = fight(tmp_path, [BROKEN, SLAPSTICK], right_talents=[BROKEN], bundle_edit=edits,
                               positions=ADJACENT)
    _cast(table, mid, STRIKE, target_id=RIGHT)  # the hit that makes the attacker Off-Rhythm from the defender
    assert _off_rhythm(reload(combat, mid).state.actors[RIGHT])
    before = reload(combat, mid).state.actors[LEFT].position
    turn(table, mid, RIGHT)
    _, prompts = _step(combat, table, mid, STRIKE, "choice:needle.drunken_slapstick_step", "Slapstick Escape",
                       before, target_id=LEFT)
    assert any("10 feet" in str(prompt) for prompt in prompts), [str(p) for p in prompts]
    after = reload(combat, mid).state.actors[LEFT].position
    assert (after.x, after.y) != (before.x, before.y)
    assert combat._load_session(mid).engine.grid.distance_ft(before, after) <= 10


def test_slapstick_escape_is_inert_without_the_talent(tmp_path):
    combat, table, mid = fight(tmp_path, [], right_talents=[BROKEN], positions=ADJACENT)
    before = reload(combat, mid).state.actors[LEFT].position
    turn(table, mid, RIGHT)
    _, prompts = _miss(combat, table, mid, STRIKE, target_id=LEFT)
    assert not any("slapstick" in str(prompt) for prompt in prompts)
    assert reload(combat, mid).state.actors[LEFT].position == before


# ------------------------------------------------------------------------------------------------ Staggering Shove
@pytest.mark.parametrize("rhythm", [False, True])
def test_staggering_shove_disadvantages_only_an_off_rhythm_shove_save(tmp_path, rhythm):
    """Printed: "the target has Disadvantage on its saving throw" -- only the Shove option, only an Off-Rhythm creature."""
    combat, table, mid = fight(tmp_path, [STAGGERING], bundle_edit=_pin(hit=True, save_dc=40), positions=ADJACENT,
                               prepare=[LONG_MARK] if rhythm else [])
    if rhythm:
        _cast(table, mid, "Prepare")
        assert _off_rhythm(reload(combat, mid).state.actors[RIGHT])
        turn(table, mid, RIGHT)
        turn(table, mid, LEFT)
    _cast(table, mid, "Shove: Prone", target_id=RIGHT)
    rolls = [r for r in reload(combat, mid).rolls if r.actor_id == RIGHT and "shove" in r.reason]
    assert rolls, [r.reason for r in reload(combat, mid).rolls]
    assert ("DISADVANTAGE" in str(rolls[-1].mode)) is rhythm, (rolls[-1].mode, rhythm)


def _save_outcome(combat, mid, subject):
    """The real result of ``subject``'s last saving throw, read from the committed SAVE_ROLLED event."""
    events = [e for e in combat._load_session(mid).engine.events
              if e.event_type == "SAVE_ROLLED" and e.actor_id == subject]
    assert events, "the Shove's saving throw was rolled"
    return bool((events[-1].payload or {}).get("success"))


def test_staggering_shove_steps_five_feet_only_when_the_target_fails_the_shove_save(tmp_path):
    """"If the Shove succeeds, you may also move 5 feet": a Shove lands exactly when the target's Strength save FAILS.
    The step is offered on that outcome and withheld when the target resists the push."""
    combat, table, mid = fight(tmp_path, [STAGGERING], bundle_edit=_pin_shove(40), positions=ADJACENT, prepare=[LONG_MARK])
    _cast(table, mid, "Prepare")
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    before = reload(combat, mid).state.actors[LEFT].position
    _, prompts = _step(combat, table, mid, "Shove: Prone", "choice:needle.drunken_staggering_step", "Staggering Shove",
                       before, target_id=RIGHT)
    assert not _save_outcome(combat, mid, RIGHT), "the pinned DC makes the target fail its Strength save"
    assert any("Staggering Shove" in str(prompt) for prompt in prompts), [str(p) for p in prompts]
    after = reload(combat, mid).state.actors[LEFT].position
    assert (after.x, after.y) != (before.x, before.y), "the printed five-foot step was taken"
    assert combat._load_session(mid).engine.grid.distance_ft(before, after) <= 5


def test_staggering_shove_steps_nothing_when_the_target_resists_the_shove(tmp_path):
    """The save succeeding means the Shove did NOT succeed, so no free step is offered even from a failed save."""
    combat, table, mid = fight(tmp_path, [STAGGERING], bundle_edit=_pin_shove(2), positions=ADJACENT, prepare=[LONG_MARK])
    _cast(table, mid, "Prepare")
    turn(table, mid, RIGHT)
    turn(table, mid, LEFT)
    before = reload(combat, mid).state.actors[LEFT].position
    _, prompts = _cast(table, mid, "Shove: Prone", target_id=RIGHT)
    assert _save_outcome(combat, mid, RIGHT), "the pinned DC lets the target resist the Shove"
    assert not any("Staggering Shove" in str(prompt) for prompt in prompts), \
        "a resisted Shove is not a successful Shove: " + str([p for p in prompts if "Staggering" in str(p)])
    assert reload(combat, mid).state.actors[LEFT].position == before


# ------------------------------------------------------------------------------------------------ Lucky-Looking Miss
def test_lucky_looking_miss_regains_focus_when_the_false_opening_is_created(tmp_path):
    combat, table, mid = fight(tmp_path, [BROKEN, LUCKY], positions=ADJACENT, prepare=[SPEND_FOCUS], prepare_target="SELF")
    _cast(table, mid, "Prepare")
    assert reload(combat, mid).state.actors[LEFT].resources[FOCUS] == 0
    _miss(combat, table, mid, STRIKE, {"choice:needle.drunken_false_opening": ["open"]}, target_id=RIGHT)
    after = reload(combat, mid)
    assert after.state.actors[LEFT].resources[FOCUS] == 1, "Martial Focus is restored the moment the opening is created"
    assert not any(row.condition_id == LUCKY_AIM for row in after.state.actors[LEFT].conditions.values()), \
        "no Advantage yet: the opening's creature has not attacked"


def test_lucky_looking_miss_grants_advantage_after_the_opening_creature_misses(tmp_path):
    combat, table, mid = fight(tmp_path, [BROKEN, LUCKY], bundle_edit=_pin_weapon(hit=False, only=RIGHT), positions=ADJACENT)
    _miss(combat, table, mid, STRIKE, {"choice:needle.drunken_false_opening": ["open"]}, target_id=RIGHT)
    turn(table, mid, RIGHT)
    # the opening's creature answers with the attack that misses it
    resolve(lambda reply: act(table, mid, "Bi Shou (Dagger) attack", reply, target_id=LEFT))
    held = [row for row in reload(combat, mid).state.actors[LEFT].conditions.values() if row.condition_id == LUCKY_AIM]
    assert held and held[0].data.get("target_id") == RIGHT, \
        [row.condition_id for row in reload(combat, mid).state.actors[LEFT].conditions.values()]


def test_lucky_looking_miss_is_inert_without_the_talent(tmp_path):
    combat, table, mid = fight(tmp_path, [BROKEN], positions=ADJACENT, prepare=[SPEND_FOCUS], prepare_target="SELF")
    _cast(table, mid, "Prepare")
    _miss(combat, table, mid, STRIKE, {"choice:needle.drunken_false_opening": ["open"]}, target_id=RIGHT)
    after = reload(combat, mid)
    assert after.state.actors[LEFT].resources[FOCUS] == 0
    assert not any(row.condition_id == LUCKY_AIM for row in after.state.actors[LEFT].conditions.values())


# ------------------------------------------------------------------------------------------------ Laughing Feint
def _feinted(combat, mid, condition_id, subject=RIGHT):
    return [row for row in reload(combat, mid).state.actors[subject].conditions.values()
            if row.condition_id == condition_id]


def _feint(combat, table, mid, option, **kwargs):
    """Left lands the Broken-Rhythm Strike that makes ``Visitor`` Off-Rhythm and answers Laughing Feint with ``option``."""
    _, prompts = _cast(table, mid, STRIKE, {"choice:needle.drunken_feint": [option]}, target_id=RIGHT, **kwargs)
    asked = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.drunken_feint"]
    assert asked, "Laughing Feint is asked on the mark placement"
    return asked[0]


def test_laughing_feint_asks_which_result_lands_when_a_creature_becomes_off_rhythm(tmp_path):
    combat, table, mid = fight(tmp_path, [BROKEN, FEINT], bundle_edit=_pin(hit=True), positions=ADJACENT)
    asked = _feint(combat, table, mid, "bad_read")
    assert {o["id"] for o in asked["choice"]["options"]} == {"no_oa", "ally_advantage", "bad_read"}
    for option in asked["choice"]["options"]:
        assert "Opportunity Attacks" in option["label"] or "Advantage" in option["label"] or "Perception" in option["label"]
    for option in asked["choice"]["options"]:
        if option["id"] in ("ally_advantage", "bad_read"):
            assert "start of your next turn" in option["label"], \
                f"the printed deadline is missing from {option['id']}: {option['label']}"


def test_laughing_feint_stops_opportunity_attacks_until_the_start_of_your_next_turn(tmp_path):
    """"it cannot make Opportunity Attacks against you until the start of your next turn" -- a real condition, on the
    feinted creature, and the engine's own Opportunity Attack gate then refuses that one attacker."""
    from combat import ext

    combat, table, mid = fight(tmp_path, [BROKEN, FEINT], bundle_edit=_pin(hit=True), positions=ADJACENT)
    _feint(combat, table, mid, "no_oa")
    held = _feinted(combat, mid, FEINT_NO_OA)
    assert held, [r.condition_id for r in reload(combat, mid).state.actors[RIGHT].conditions.values()]
    assert held[0].data.get("owner") == LEFT
    assert held[0].expires_on == FEINT_DEADLINE, "the printed deadline is the start of the owner's next turn"
    engine = combat._load_session(mid).engine
    assert ext.run("opportunity_allowed", engine, reload(combat, mid).state.actors[RIGHT], reload(combat, mid).state.actors[LEFT]) == [False], \
        "the feinted creature cannot answer the owner's movement with an Opportunity Attack"


def test_laughing_feint_leaves_other_creatures_free_to_make_opportunity_attacks(tmp_path):
    """The bar is against "you" only: a different creature's Opportunity Attack is untouched."""
    from combat import ext

    combat, table, mid = fight(tmp_path, [BROKEN, FEINT], bundle_edit=_pin(hit=True), positions=ADJACENT)
    _feint(combat, table, mid, "no_oa")
    engine = combat._load_session(mid).engine
    state = reload(combat, mid).state.actors
    assert ext.run("opportunity_allowed", engine, state[RIGHT], state[LEFT]) == [False]
    assert False not in ext.run("opportunity_allowed", engine, state[LEFT], state[RIGHT])


def test_laughing_feint_gives_another_creatures_next_attroll_advantage_and_spends_it(tmp_path):
    """"the next attack roll against it by a creature other than you has Advantage" -- offered to an ally's attack, never
    to the owner's own attack, and spent by that roll whether it hit or missed."""
    combat, table, mid = triple_fight(tmp_path, [BROKEN, FEINT], third_ally=True, bundle_edit=_pin(hit=True, only=LEFT))
    _feint(combat, table, mid, "ally_advantage")
    held = _feinted(combat, mid, FEINT_ALLY)
    assert held, [r.condition_id for r in reload(combat, mid).state.actors[RIGHT].conditions.values()]
    assert held[0].expires_on == FEINT_DEADLINE
    turn(table, mid, OTHER)
    _, prompts = resolve(lambda reply: act(table, mid, "Bi Shou (Dagger) attack", reply, target_id=RIGHT))
    roll = next((r for r in reload(combat, mid).rolls if r.actor_id == OTHER and "attack" in str(r.reason).lower()), None)
    assert roll is not None, [r.reason for r in reload(combat, mid).rolls]
    assert "ADVANTAGE" in str(roll.mode), f"an ally's next attack roll against it has Advantage, not {roll.mode}"
    assert not _feinted(combat, mid, FEINT_ALLY), "the printed roll spends the benefit"


def _free_attack_action(bundle, actor_id, label, attack_bonus=100):
    """Give ``actor_id`` one economy-free weapon attack, so a test can measure a second attack roll inside a single
    turn -- inside the printed deadline, where an expiry sweep cannot be mistaken for a consumption.

    ``attack_bonus`` is the to-hit the typed resolver actually reads, so a caller can make the roll land or miss for
    real; the sheet's own technique bonus is not what this attack uses.
    """
    if bundle.get("actor_id") != actor_id:
        return
    action_id = f"action:test.auto104.free_attack.{actor_id}"
    bundle["actor_template"]["action_ids"].append(action_id)
    bundle["action_catalog"].append({
        "source_definition_id": action_id, "display_name": label, "owner_id": actor_id,
        "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "HOSTILE_ENTITY",
        "range_ft": 5, "costs": [],
        "parameters": {"typed": {"effects": [{"type": "attack", "applies_to": "target",
                                              "damage": {"count": 1, "sides": 4}, "evidence": "a weapon attack"}],
                                 "numbers": {"attack_bonus": attack_bonus}, "duration": {"kind": "instant"}, "riders": []}}})


def test_laughing_feint_never_gives_its_own_owner_advantage(tmp_path):
    """"by a creature other than you" -- the owner's own attack roll is neither helped nor spent.

    Both rolls are made in the turn the Feint was placed, before the printed deadline, so this is about who the benefit
    is for and not about the condition having expired.
    """
    combat, table, mid = fight(tmp_path, [BROKEN, FEINT], positions=ADJACENT, bundle_edit=lambda b: (
        _free_attack_action(b, LEFT, "A second swing"), _pin(hit=True)(b))[0])
    _feint(combat, table, mid, "ally_advantage")
    assert _feinted(combat, mid, FEINT_ALLY), "the chosen result really is placed on the feinted creature"
    mark = len(reload(combat, mid).rolls)
    _cast(table, mid, "A second swing", target_id=RIGHT)
    fresh = [r for r in reload(combat, mid).rolls[mark:] if r.actor_id == LEFT and "attack" in str(r.reason).lower()]
    assert fresh, [r.reason for r in reload(combat, mid).rolls]
    assert "ADVANTAGE" not in str(fresh[0].mode), "the owner does not benefit from its own talent"
    assert _feinted(combat, mid, FEINT_ALLY), \
        "an attack roll the owner was never given Advantage for must not spend the ally's benefit either"
    assert reload(combat, mid).state.actors[LEFT].turns_started == 1, "still inside the printed deadline"


FOURTH = "actor:factory.h15-fourth"
FOUR_SQUARE = {LEFT: {"x": 3, "y": 5}, RIGHT: {"x": 4, "y": 6}, OTHER: {"x": 3, "y": 6}, FOURTH: {"x": 4, "y": 5}}


def four_fight(tmp_path, *, left_talents=(), other_talents=(), fourth_hit=True, match_seed="auto104",
               bundle_edit=None, positions=None):
    """``triple_fight`` plus a fourth creature at ``FOURTH``, so two Feint owners and one unrelated attacker can face the
    same feinted creature. All four squares are adjacent to it, so every printed weapon attack is in reach. ``positions``
    overrides the squares for the cases that need a creature somewhere the enemy cannot see it."""
    import json
    import zipfile

    from combat.canonical import canonical_sha256
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from tests.test_carry import KIT

    owned = {LEFT: list(left_talents), RIGHT: [], OTHER: list(other_talents), FOURTH: []}
    labels = {LEFT: "Keeper", RIGHT: "Visitor", OTHER: "Second keeper", FOURTH: "Third keeper"}
    bundles = []
    for aid, mids in owned.items():
        doc = sheet(mids, cl=15, dc=100, kit={"starting_kit": KIT}, score=14)
        doc.setdefault("spheres_and_talents", {})["sphere_record_ids"] = []
        doc["spheres_and_talents"]["automatic_sphere_component_record_ids"] = []
        stats = doc["ability_scores_and_statistics"]
        stats["technique_attack_bonus"] = -100 if aid == FOURTH and not fourth_hit else 100
        stats["primary_resource"]["maximum"] = 100
        stats["hit_points"]["maximum"] = 1000
        stats["armor_class"]["base_value"] = 1
        doc["identity"]["display_name"] = labels[aid]
        folder = tmp_path / "portable_characters" / aid.removeprefix("actor:factory.")
        folder.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(folder / "current.zip", "w") as archive:
            archive.writestr("Tianxia_Owner_Character_Sheet_v1.json", json.dumps(doc))
        bundle = compile_character(doc, actor_id=aid, reaction_plan={"ask": True})
        if bundle_edit is not None:
            bundle_edit(bundle)
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)
        bundles.append(bundle)
    combat = CombatService(ROOT, tmp_path)
    mid = combat._finish_factory_match(
        bundles, [LEFT, RIGHT, OTHER, FOURTH],
        {LEFT: "team:factory", RIGHT: "team:opponents", OTHER: "team:factory", FOURTH: "team:factory"},
        positions or FOUR_SQUARE, combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [LEFT, OTHER, FOURTH], [RIGHT],
        control_modes={a: "MANUAL" for a in (LEFT, RIGHT, OTHER, FOURTH)}, match_seed=match_seed,
        display_name="AUTO104 four-creature regression", maximum_rounds=10)["match_id"]
    table = TabletopService(combat, tmp_path)
    turn(table, mid, LEFT)
    return combat, table, mid


def _mark_action(bundle, actor_id, label):
    """Give ``actor_id`` one economy-free action that only lays the Off-Rhythm Mark on its target.

    A second Feint owner has to be able to place its own Feint *without* attacking: an attack roll against the target is
    itself "the next attack roll against it by a creature other than you", so it would spend the first owner's benefit
    (correctly, but not what the overlapping case is measuring).
    """
    if bundle.get("actor_id") != actor_id:
        return
    action_id = f"action:test.auto104.mark.{actor_id}"
    bundle["actor_template"]["action_ids"].append(action_id)
    bundle["action_catalog"].append({
        "source_definition_id": action_id, "display_name": label, "owner_id": actor_id,
        "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "HOSTILE_ENTITY",
        "range_ft": 60, "costs": [],
        "parameters": {"typed": {"effects": [LONG_MARK], "numbers": {}, "duration": {"kind": "instant"}, "riders": []}}})


@pytest.mark.parametrize("fourth_hit", [True, False], ids=["hit", "miss"])
def test_overlapping_laughing_feints_both_spend_their_advantage_on_one_attack_roll(tmp_path, fourth_hit):
    """Two owners Feint the same creature, so one third creature's attack roll is the next eligible roll for *both*.

    Advantage does not stack with itself, so that single roll spends both instances. Only the first was spent before,
    and the survivor then wrongly gave that attacker Advantage on its following attack roll as well.

    The attack roll's own to-hit is pinned on the action the attacker actually casts -- the typed resolver reads the
    action's numbers, not the sheet's technique bonus -- and the outcome is asserted against the target's hit points, so
    the "miss" case really misses and a broken ``after_miss`` cannot pass by making the same roll in both cases.
    """
    combat, table, mid = four_fight(tmp_path, left_talents=[BROKEN, FEINT], other_talents=[BROKEN, FEINT],
                                    match_seed="s3", bundle_edit=lambda b: (
                                        _mark_action(b, OTHER, "Weave the off-rhythm"),
                                        _free_attack_action(b, FOURTH, "Swing at the feinted creature",
                                                            attack_bonus=100 if fourth_hit else -100),
                                        _pin(hit=True, only=LEFT)(b))[2])
    _feint(combat, table, mid, "ally_advantage")             # LEFT feints RIGHT
    turn(table, mid, OTHER)
    _cast(table, mid, "Weave the off-rhythm", {"choice:needle.drunken_feint": ["ally_advantage"]}, target_id=RIGHT)
    _turn_to(table, mid, FOURTH)
    owners = sorted(row.source_actor_id for row in _ally_bearers(reload(combat, mid).state.actors[RIGHT]))
    assert owners == sorted([LEFT, OTHER]), \
        f"both owners really hold an overlapping instance when the attacker acts: {owners}"
    before = reload(combat, mid).state.actors[RIGHT].current_hp
    _cast(table, mid, "Swing at the feinted creature", target_id=RIGHT)
    dealt = before - reload(combat, mid).state.actors[RIGHT].current_hp
    assert (dealt > 0) is fourth_hit, \
        f"the {'hit' if fourth_hit else 'miss'} case must actually {'hit' if fourth_hit else 'miss'}: dealt {dealt}"
    roll = _roll_for(combat, mid, FOURTH, "attack")
    assert roll is not None, [r.reason for r in reload(combat, mid).rolls]
    assert "ADVANTAGE" in str(roll.mode), f"an unrelated attacker gets the printed Advantage, not {roll.mode}"
    assert not _feinted(combat, mid, FEINT_ALLY), \
        "both instances are spent by that one roll, so neither can help the next one"
    mark = len(reload(combat, mid).rolls)
    _cast(table, mid, "Swing at the feinted creature", target_id=RIGHT)
    second = next((r for r in reload(combat, mid).rolls[mark:] if r.actor_id == FOURTH and "attack" in str(r.reason).lower()), None)
    assert second is not None, [r.reason for r in reload(combat, mid).rolls]
    assert "ADVANTAGE" not in str(second.mode), \
        f"the benefit was for one roll only, not {second.mode}"


def _turn_to(table, mid, actor_id, limit=8):
    """``hunt15_support.turn`` advances at most three turns, which is not enough to reach anyone in a four-creature fight."""
    for _ in range(limit):
        if table.state(mid)["menu"]["actor_id"] == actor_id:
            return
        assert act(table, mid, "end")["status"] == "COMMITTED"
    raise AssertionError(f"could not reach {actor_id} within {limit} turns")


def _ally_bearers(target):
    return [row for row in target.conditions.values() if row.condition_id == FEINT_ALLY]


def test_laughing_feint_disadvantages_the_next_perception_or_insight_check(tmp_path):
    """"it has Disadvantage on its next Wisdom (Perception) or Wisdom (Insight) check" -- carried as the engine's own
    check_mode rule, which is the resolver every check in the game actually goes through."""
    from combat.typed_executor import check_mode, check_modes

    combat, table, mid = fight(tmp_path, [BROKEN, FEINT], bundle_edit=_pin(hit=True), positions=ADJACENT)
    _feint(combat, table, mid, "bad_read")
    held = _feinted(combat, mid, FEINT_BAD_READ)
    assert held, [r.condition_id for r in reload(combat, mid).state.actors[RIGHT].conditions.values()]
    assert held[0].expires_on == FEINT_DEADLINE
    assert (held[0].data.get("rule") or {}).get("check_mode") == {"Perception": "DISADVANTAGE", "Insight": "DISADVANTAGE"}
    engine = combat._load_session(mid).engine
    actor = reload(combat, mid).state.actors[RIGHT]
    # the full resolver, not one hook in isolation: this is the call the opposed-check resolver makes for each participant
    for skill in ("Perception", "Insight"):
        assert check_modes(actor, "WIS", skill, engine=engine) == {"DISADVANTAGE"}, skill
        assert check_mode(actor, "WIS", skill, engine=engine) == "DISADVANTAGE", skill
    assert check_modes(actor, "INT", "Investigation", engine=engine) == set(), "no other check is touched"
    assert check_modes(actor, "WIS", "Arcana", engine=engine) == set(), "only the two printed Wisdom skills"


def _roll_for(combat, mid, actor_id, part):
    return next((r for r in reload(combat, mid).rolls if r.actor_id == actor_id and part in str(r.reason).lower()), None)


def test_laughing_feint_bad_read_is_spent_by_the_feinted_creatures_own_wisdom_check(tmp_path):
    """The bad read names a check the *creature* makes, so its own Wisdom (Insight) check spends it.

    Before this the consumption read only the initiating actor's CHECK_ROLLED payload, so a feinted creature that
    checked kept the penalty and its next check was disadvantaged again.
    """
    combat, table, mid = fight(tmp_path, [BROKEN, FEINT], positions=ADJACENT, bundle_edit=lambda b: (
        _contest_action(b, RIGHT, "Read the room", ability="WIS", skill="Insight"), _pin(hit=True)(b))[0])
    _feint(combat, table, mid, "bad_read")
    assert _feinted(combat, mid, FEINT_BAD_READ)
    turn(table, mid, RIGHT)
    _cast(table, mid, "Read the room", target_id=LEFT)
    roll = _roll_for(combat, mid, RIGHT, "check:")
    assert roll is not None, [r.reason for r in reload(combat, mid).rolls]
    assert "DISADVANTAGE" in str(roll.mode), f"the named check is disadvantaged, not {roll.mode}"
    assert not _feinted(combat, mid, FEINT_BAD_READ), "the check it names spends it"
    assert reload(combat, mid).state.actors[LEFT].turns_started == 1, \
        "the printed deadline is still running: the check spent the penalty, the clock did not"


def _contest_action(bundle, actor_id, label, *, ability, skill, on_the_defender=False):
    """Give ``actor_id`` one economy-free action that runs a real opposed check through ``ext.contests``.

    ``on_the_defender`` puts the WIS check on the creature being attacked, which is the case the old consumption could
    not see: the CHECK_ROLLED payload names only the initiating actor's check and files the defender's under "target".
    Both sides are checks here: a saving throw on the *initiating* side is an unrelated pre-existing crash in
    ``typed_executor.resolve_opposed_check`` (``choice`` is only bound on the defender-save branch), reported separately
    rather than relied on here.
    """
    if bundle.get("actor_id") != actor_id:
        return
    action_id = f"action:test.auto104.contest.{actor_id}.{label.replace(' ', '_').lower()}"
    actor_check = {"ability": "STR", "skill": "Athletics"} if on_the_defender else {"ability": ability, "skill": skill}
    target_check = {"ability": ability, "skill": skill} if on_the_defender else {"ability": "STR", "skill": "Athletics"}
    bundle["actor_template"]["action_ids"].append(action_id)
    bundle["action_catalog"].append({
        "source_definition_id": action_id, "display_name": label, "owner_id": actor_id,
        "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "HOSTILE_ENTITY",
        "range_ft": 60, "costs": [],
        "parameters": {"typed": {"effects": [{"type": "contest_against", "applies_to": "target",
                                              "actor_check": actor_check, "target_check": target_check,
                                              "evidence": "an opposed check"}],
                                 "numbers": {"save_dc": 10}, "duration": {"kind": "instant"}, "riders": []}}})


def test_laughing_feint_bad_read_is_spent_when_the_feinted_creature_defends_an_opposed_check(tmp_path):
    """In an opposed check each creature is told its mode before either die is drawn, so the feinted defender's own
    Wisdom check is a qualifying roll and must spend the bad read -- not left hanging for later checks."""
    def edits(bundle):
        _contest_action(bundle, LEFT, "Read the creature", ability="WIS", skill="Perception", on_the_defender=True)

    combat, table, mid = fight(tmp_path, [BROKEN, FEINT], bundle_edit=lambda b: (edits(b), _pin(hit=True)(b))[0],
                               positions=ADJACENT)
    _feint(combat, table, mid, "bad_read")
    assert _feinted(combat, mid, FEINT_BAD_READ)
    _cast(table, mid, "Read the creature", target_id=RIGHT)
    roll = _roll_for(combat, mid, RIGHT, "check:")
    assert roll is not None, [r.reason for r in reload(combat, mid).rolls]
    assert "DISADVANTAGE" in str(roll.mode), \
        f"the defender's own WIS (Perception) check is the named one, not {roll.mode}"
    assert not _feinted(combat, mid, FEINT_BAD_READ), "the defender's qualifying roll spends it"
    assert reload(combat, mid).state.actors[LEFT].turns_started == 1, \
        "the printed deadline is still running, so the roll spent the penalty rather than the clock"


def _free_search_action(bundle, actor_id, label, bonus=4):
    """Give ``actor_id`` one economy-free Search, so a second qualifying check can be made *inside* the printed deadline.

    It runs the same typed effect the compiler's own printed Search runs (``{"type": "search"}`` -> ``block_search`` ->
    ``combat/stealth.py``), and records its check the same way, so it is the same code path -- it just does not spend the
    Action, which is what lets the second check happen before the clock, instead of a whole round later.
    """
    if bundle.get("actor_id") != actor_id:
        return
    action_id = f"action:test.auto104.free_search.{actor_id}"
    bundle["actor_template"]["action_ids"].append(action_id)
    bundle["action_catalog"].append({
        "source_definition_id": action_id, "display_name": label, "owner_id": actor_id,
        "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "SELF",
        "range_ft": 0, "costs": [],
        "parameters": {"typed": {"effects": [{"type": "search", "bonus": bonus}], "numbers": {},
                                 "duration": {"kind": "instant"}, "riders": []}}})


def _pin_hide(bonus=100, only=None):
    """Pin the Hide action's own Stealth bonus, so a creature out of its enemy's sight really does end up hiding."""
    def edit(bundle):
        if only and bundle.get("actor_id") != only:
            return
        for action in bundle["action_catalog"]:
            params = action.get("parameters") or {}
            if str(params.get("stealth") or "") != "hide":
                continue
            for effect in (params.get("typed") or {}).get("effects") or []:
                if isinstance(effect, dict) and effect.get("type") == "hide":
                    effect["bonus"] = bonus
    return edit


def test_laughing_feint_bad_read_is_spent_by_the_printed_search_check(tmp_path):
    """The single-check path, on a real printed action: the feinted creature's own Search -- a Wisdom (Perception) check --
    spends the bad read, and only that check does.

    Every other regression here drives an opposed check, which is charged by the ``opposed_check_resolved`` hook and never
    reaches the ``CHECK_ROLLED`` consumption this covers. Search is the table's own printed action, built by the compiler
    for every character (combat/factory_compiler.py); it is offered only while an enemy is hiding, which is what the ally
    out of the Visitor's sight is there to provide. Its check is recorded as the bare ``check="Perception"`` skill key.
    This covers persistence on that existing path; the Analyze regression below discriminates descriptive labels.

    Both searches commit through TabletopService and are read back from a fresh reload, so the consumption has to have
    survived the fight state rather than merely run in memory.
    """
    squares = {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 4, "y": 6}, OTHER: {"x": 7, "y": 1}, FOURTH: {"x": 4, "y": 5}}
    combat, table, mid = four_fight(tmp_path, left_talents=[BROKEN, FEINT], positions=squares, bundle_edit=lambda b: (
        _free_search_action(b, RIGHT, "Look around again"), _pin_hide(only=OTHER)(b), _pin(hit=True, only=LEFT)(b))[2])
    _feint(combat, table, mid, "bad_read")
    assert _feinted(combat, mid, FEINT_BAD_READ)

    turn(table, mid, OTHER)
    _cast(table, mid, "Hide")                      # a real enemy is now hiding, which is what makes Search legal
    _turn_to(table, mid, RIGHT)
    assert "Search" in _labels(table, mid), "the feinted creature is offered its printed Search"
    _cast(table, mid, "Search")
    roll = _roll_for(combat, mid, RIGHT, "check:")
    assert roll is not None, [r.reason for r in reload(combat, mid).rolls]
    assert "DISADVANTAGE" in str(roll.mode), \
        f"the Search's own Wisdom (Perception) check is the one the bad read names, not {roll.mode}"
    assert reload(combat, mid).state.actors[LEFT].turns_started == 1, \
        "the printed deadline is still running, so the roll spent the penalty rather than the clock"
    assert not _feinted(combat, mid, FEINT_BAD_READ), \
        "that check spends the bad read -- read back after a reload, so the removal really persisted"

    # One use only, still inside the deadline: the very next Search is the next qualifying check and is not helped.
    assert reload(combat, mid).state.actors[LEFT].turns_started == 1, "still before the deadline, so this proves use"
    mark = len(reload(combat, mid).rolls)
    _cast(table, mid, "Look around again")
    second = next((r for r in reload(combat, mid).rolls[mark:] if r.actor_id == RIGHT and "check:" in str(r.reason).lower()), None)
    assert second is not None, [r.reason for r in reload(combat, mid).rolls]
    assert "DISADVANTAGE" not in str(second.mode), f"only the next check was named by the bad read, not {second.mode}"


@pytest.mark.parametrize("first_skill", ["Perception", "Investigation"])
def test_laughing_feint_bad_read_analyze_selected_skill_commits_and_reloads(tmp_path, first_skill):
    """Analyze's real skill choice and actual-skill CHECK_ROLLED payload spend only a qualifying bad read.

    The fixture removes only Analyze's Action/Focus cost so repeated checks fit before the Feint owner's next turn;
    Persistent Analysis supplies the printed per-target attempt allowance. The compiled effect, skill prompt, check
    mode, event dispatch, commit and cold reload all use the production paths.
    """
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService
    from combat.ext.mind_hidden_eye import BASE_ID

    def edits(bundle):
        _pin(hit=True, only=LEFT)(bundle)
        if bundle.get("actor_id") == RIGHT:
            for action in bundle["action_catalog"]:
                if action["display_name"] == "Analyze":
                    action["economy"] = "NONE"
                    action["costs"] = []

    combat, table, mid = fight(tmp_path, [BROKEN, FEINT], positions=ADJACENT, bundle_edit=edits,
                               right_talents=[BASE_ID, "TAL_THE_HIDDEN_EYE_PERSISTENT_ANALYSIS"])
    _feint(combat, table, mid, "bad_read")
    held = _feinted(combat, mid, FEINT_BAD_READ)
    assert len(held) == 1 and held[0].expires_on == FEINT_DEADLINE
    instance_id = held[0].instance_id
    turn(table, mid, RIGHT)

    # Investigation leaves the penalty live; the event identifies the actual selected skill.
    # In both cases two qualifying checks follow, the last without the already-consumed Disadvantage.
    skills = [first_skill, "Perception"] + (["Perception"] if first_skill == "Investigation" else [])
    spent = False
    for skill in skills:
        before = reload(combat, mid)
        event_count, roll_count = len(before.events), len(before.rolls)
        result, prompts = _cast(table, mid, "Analyze", {"choice:needle.eye_approach": [skill]}, target_id=LEFT)
        assert result["status"] == "COMMITTED"
        choices = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:needle.eye_approach"]
        assert len(choices) == 1
        assert {o["id"] for o in choices[0]["choice"]["options"]} == {"Perception", "Investigation"}

        # Check persisted state, then make the next request through entirely new service instances.
        loaded = reload(combat, mid)
        checks = [e for e in loaded.events[event_count:] if e.event_type == "CHECK_ROLLED" and e.actor_id == RIGHT]
        assert len(checks) == 1
        event = checks[0]
        assert event.target_ids == (LEFT,)
        assert event.payload["skill"] == skill
        assert event.payload["actor"]["reason"] == f"CHECK:analyze:{skill.lower()}"
        rolls = [r for r in loaded.rolls[roll_count:] if r.actor_id == RIGHT and r.reason.startswith("CHECK:analyze:")]
        assert len(rolls) == 1 and rolls[0].reason == event.payload["actor"]["reason"]
        disadvantaged = skill == "Perception" and not spent
        assert str(rolls[0].mode).split(".")[-1] == ("DISADVANTAGE" if disadvantaged else "NORMAL")
        spent = spent or skill == "Perception"
        remaining = [c for c in loaded.state.actors[RIGHT].conditions.values() if c.condition_id == FEINT_BAD_READ]
        if spent:
            assert not remaining, "the qualifying Analyze must persistently consume the bad read"
        else:
            assert len(remaining) == 1 and remaining[0].instance_id == instance_id
            assert remaining[0].expires_on == FEINT_DEADLINE
        assert loaded.state.current_actor_id == RIGHT
        assert loaded.state.actors[LEFT].turns_started == 1, "consumption happened before the owner's deadline"
        combat = CombatService(ROOT, tmp_path)
        table = TabletopService(combat, tmp_path)


@pytest.mark.parametrize("payload,expected", [
    ({"check": "Perception"}, True),                                            # Search, a trap notice, a lantern sweep
    ({"skill": "Perception"}, True),                                            # Invisible Blade Current
    ({"skill": "Wisdom (Insight)"}, True),                                       # Break the Glass
    ({"check": "WIS (Perception)"}, True),
    ({"skill": "Intelligence (Arcana)"}, False), ({"skill": "Cultivation Check"}, False),   # Break the Glass's other checks
    ({"check": "Stealth"}, False), ({"skill": "Air Check"}, False),              # Hide; Arrow-Turning Breath
    ({"skill": "Perceptive"}, False),                                            # a label that merely contains the letters
    ({"skill": "Intelligence (Investigation) or Wisdom (Perception), Analyze",    # Analyze keeps the best of several rolls
      "actor": {"reason": "CHECK:analyze:perception"}}, True),
    ({"skill": "Intelligence (Investigation) or Wisdom (Perception), Analyze",
      "actor": {"reason": "CHECK:analyze:investigation"}}, False),
    ({"skill": "Intelligence (Investigation) or Wisdom (Perception), Analyze",
      "actor": {"reason": "CHECK:analyze:survival"}}, False),                    # Empirical Tracker's option, not in the label
    ({"skill": "Intelligence (Investigation) or Wisdom (Perception), Analyze",
      "actor": {"reason": "CHECK:analyze:medicine"}}, False),                    # Physical Examination's option
], ids=["search", "invisible-blade", "break-glass-insight", "wis-perception", "arcana", "cultivation", "hide",
        "air-check", "substring", "analyze-perception", "analyze-investigation", "analyze-survival", "analyze-medicine"])
def test_the_bad_read_is_spent_by_exactly_the_checks_a_producer_names(payload, expected):
    """Every ``CHECK_ROLLED`` producer names its check in prose, not as a bare skill key, and the bad read must be spent by
    exactly those.

    The shapes are lifted from the producers themselves -- combat/stealth.py (Search), combat/ext/trap.py,
    combat/ext/riders14_awareness.py and combat/ext/air_currents.py (Perception), combat/ext/well_of_hours.py (Break the
    Glass) and combat/ext/mind_hidden_eye.py (Analyze, whose label lists the options and whose reason names the one that
    was kept). Matching the event's string exactly silently stopped recognising the prose ones at once: a feinted creature
    that Insight-checked kept its Disadvantage, and it disadvantaged every later check until the deadline ran out.

    This drives the real ``event`` hook, so it fails against the source that made the mistake for that reason rather than
    because a helper was missing.
    """
    from combat.ext.drunken_style import laughing_feint_bad_read_spent

    actor = SimpleNamespace(entity_id=RIGHT, conditions={"b1": SimpleNamespace(
        condition_id=FEINT_BAD_READ, instance_id="b1", source_actor_id=LEFT, source_definition_id="broken-rhythm")})
    engine = SimpleNamespace(state=SimpleNamespace(actors={RIGHT: actor}), _append_event=lambda *a, **k: None)
    payload = {**payload, "actor": {"natural_result": 12, **payload.get("actor", {})}}
    laughing_feint_bad_read_spent(engine, "CHECK_ROLLED", {"actor_id": RIGHT, "payload": payload})
    assert (FEINT_BAD_READ not in {row.condition_id for row in actor.conditions.values()}) is expected, payload


def test_laughing_feint_bad_read_serves_only_one_qualifying_check(tmp_path):
    """One use of the condition: the first named check is disadvantaged, the very next one is not."""
    def edits(bundle):
        _contest_action(bundle, RIGHT, "Read the room", ability="WIS", skill="Insight")

    combat, table, mid = fight(tmp_path, [BROKEN, FEINT], bundle_edit=lambda b: (edits(b), _pin(hit=True)(b))[0],
                               positions=ADJACENT)
    _feint(combat, table, mid, "bad_read")
    turn(table, mid, RIGHT)
    _cast(table, mid, "Read the room", target_id=LEFT)
    first = _roll_for(combat, mid, RIGHT, "check:")
    assert "DISADVANTAGE" in str(first.mode), f"the first named check is disadvantaged, not {first.mode}"
    assert not _feinted(combat, mid, FEINT_BAD_READ), "that check spends it"
    mark = len(reload(combat, mid).rolls)
    _cast(table, mid, "Read the room", target_id=LEFT)  # economy-free, so still inside the printed deadline
    assert reload(combat, mid).state.actors[LEFT].turns_started == 1, "still before the deadline, so this proves use"
    second = next(r for r in reload(combat, mid).rolls[mark:] if r.actor_id == RIGHT and "check:" in str(r.reason).lower())
    assert "DISADVANTAGE" not in str(second.mode), f"only the next check was named, not {second.mode}"


def test_laughing_feint_is_inert_without_the_talent(tmp_path):
    combat, table, mid = fight(tmp_path, [BROKEN], bundle_edit=_pin(hit=True), positions=ADJACENT)
    _, prompts = _cast(table, mid, STRIKE, target_id=RIGHT)
    assert not any("Laughing Feint" in str(prompt) for prompt in prompts)
    for condition_id in (FEINT_NO_OA, FEINT_ALLY, FEINT_BAD_READ):
        assert not _feinted(combat, mid, condition_id), condition_id


# ------------------------------------------------------------------------------------------------ the shared Daze rule
def test_daze_is_inert_for_a_creature_that_is_not_dazed(tmp_path):
    combat, table, mid = triple_fight(tmp_path, [BROKEN])
    for creature in reload(combat, mid).state.actors.values():
        assert not dazed_restriction.holds(creature)


def test_a_daze_condition_id_is_one_of_the_shared_printed_dazes():
    assert DAZED in dazed_restriction.IDS


# ------------------------------------------------------------------------------------------------ Slapstick: melee and reach
def test_slapstick_escape_answers_a_reach_weapon_miss_from_ten_feet(tmp_path):
    """Printed: "misses you with a melee attack" says nothing about five feet. A polearm is a melee attack at 10 feet, so
    the step is offered there; the old hard-coded five-foot guess refused it."""
    reach_positions = {LEFT: {"x": 3, "y": 6}, RIGHT: {"x": 5, "y": 6}}
    combat, table, mid = fight(tmp_path, [SLAPSTICK], right_talents=[BROKEN], positions=reach_positions,
                               bundle_edit=_reach_pins(only=RIGHT, reach=10))
    assert combat._load_session(mid).engine.grid.distance_ft(
        reload(combat, mid).state.actors[LEFT].position, reload(combat, mid).state.actors[RIGHT].position) == 10
    before = reload(combat, mid).state.actors[LEFT].position
    turn(table, mid, RIGHT)
    _, prompts = _step(combat, table, mid, STRIKE, "choice:needle.drunken_slapstick_step", "Slapstick Escape",
                       before, target_id=LEFT)
    assert any("5 feet" in str(prompt) for prompt in prompts), \
        "a reach weapon's melee miss still answers: " + str([p for p in prompts if "slapstick" in str(p).lower()])
    after = reload(combat, mid).state.actors[LEFT].position
    assert (after.x, after.y) != (before.x, before.y)
    assert combat._load_session(mid).engine.grid.distance_ft(before, after) <= 5


def test_slapstick_escape_never_answers_a_thrown_attack_from_an_adjacent_cell(tmp_path):
    """A thrown weapon is a ranged attack however close the thrower stands, so its miss is not "a melee attack" and
    grants no step. The compiler's own "Bi Shou (Dagger) thrown" variant is used, so nothing is renamed here."""
    combat, table, mid = fight(tmp_path, [SLAPSTICK], right_talents=[BROKEN], positions=ADJACENT)
    before = reload(combat, mid).state.actors[LEFT].position
    turn(table, mid, RIGHT)
    _, prompts = _miss(combat, table, mid, "Bi Shou (Dagger) thrown", target_id=LEFT)
    assert not any("Slapstick" in str(prompt) for prompt in prompts), \
        "a thrown attack is not a melee attack: " + str([p for p in prompts if "slapstick" in str(p).lower()])
    assert reload(combat, mid).state.actors[LEFT].position == before


# ------------------------------------------------------------------------------------------------ Lucky-Looking Miss is spent by the roll
def test_lucky_looking_miss_spends_its_advantage_when_the_next_attack_roll_misses(tmp_path):
    """"you gain Advantage on the next attack roll you make against it": the printed benefit is for the roll, so a
    whiff spends it exactly as a hit does. Before this it survived the miss and was still live for the next attack."""
    combat, table, mid = fight(tmp_path, [BROKEN, LUCKY], bundle_edit=_pin_weapon(hit=False, only=RIGHT), positions=ADJACENT)
    _miss(combat, table, mid, STRIKE, {"choice:needle.drunken_false_opening": ["open"]}, target_id=RIGHT)
    turn(table, mid, RIGHT)
    resolve(lambda reply: act(table, mid, "Bi Shou (Dagger) attack", reply, target_id=LEFT))  # the opening's miss
    assert _feinted(combat, mid, LUCKY_AIM, LEFT), "the opening's miss grants the Advantage"
    turn(table, mid, LEFT)
    _miss(combat, table, mid, STRIKE, target_id=RIGHT)
    assert not _feinted(combat, mid, LUCKY_AIM, LEFT), \
        "the attack roll it was for has been made, and it missed: the benefit is spent"


# ------------------------------------------------------------------------------------------------ two casters, two Dazes
def _daze_action(bundle, actor_id, label):
    """Give ``actor_id`` one 'Daze' action so this test can place a real printed Daze through the shared helper.

    Two such actions can be given one actor: they are economy-free, so a caster can place its own Daze twice inside a
    single turn, which is the only way its second Daze is a *refresh* of a still-running instance rather than a new one.
    """
    action_id = f"action:test.auto104.daze.{actor_id}.{label.replace(' ', '_').lower()}"
    bundle["actor_template"]["action_ids"].append(action_id)
    bundle["action_catalog"].append({
        "source_definition_id": action_id, "display_name": label, "owner_id": actor_id,
        "economy": "NONE", "resolution_kind": "TYPED", "target_kind": "HOSTILE_ENTITY",
        "range_ft": 60, "costs": [],
        "parameters": {"typed": {"effects": [{"type": "drunken_dazed", "applies_to": "target",
                                              "evidence": "Failed Save: The target is Prone and Dazed"}],
                                 "numbers": {}, "duration": {"kind": "instant"}, "riders": []}}})


def test_two_casters_each_keep_their_own_daze_and_its_deadline(tmp_path):
    """One caster's Daze must not delete another caster's still-running Daze: the creature stays restricted until the
    last of them expires. Before this the shared helper cleared every printed Daze, so the longer one was lost and the
    creature recovered early."""
    def edits(bundle):
        if bundle.get("actor_id") in (LEFT, OTHER):
            _daze_action(bundle, bundle["actor_id"], "Daze a creature")

    combat, table, mid = triple_fight(tmp_path, [FLOOR], third_ally=True, bundle_edit=edits)
    _cast(table, mid, "Daze a creature", target_id=RIGHT)
    assert dazed_restriction.holds(reload(combat, mid).state.actors[RIGHT])
    turn(table, mid, OTHER)
    _cast(table, mid, "Daze a creature", target_id=RIGHT)
    target = reload(combat, mid).state.actors[RIGHT]
    bearers = {(row.condition_id, row.source_actor_id) for row in target.conditions.values() if row.condition_id in dazed_restriction.IDS}
    assert bearers == {(DAZED, LEFT), (DAZED, OTHER)}, \
        "both casters' Dazes survive, each with its own deadline: " + str(sorted(bearers))
    assert dazed_restriction.holds(target)
    assert not target.reaction_available, "Dazed: cannot take Reactions"


def test_a_refreshed_daze_keeps_another_casters_still_running_daze(tmp_path):
    """The A/B/A sequence the review found: A Dazes, B Dazes, A refreshes its own -- and B's Daze must survive.

    ``apply`` picked out A's own instance and then handed the *condition id* to the engine's ``_remove_condition``,
    which deletes every instance carrying that id, so A's refresh silently ended B's Daze and threw away its later
    deadline. Each instance is now removed by its own id.
    """
    def edits(bundle):
        if bundle.get("actor_id") in (LEFT, OTHER):
            _daze_action(bundle, bundle["actor_id"], "Daze a creature")
        if bundle.get("actor_id") == LEFT:
            _daze_action(bundle, LEFT, "Daze again")

    combat, table, mid = triple_fight(tmp_path, [FLOOR], third_ally=True, bundle_edit=edits)
    turn(table, mid, OTHER)
    _cast(table, mid, "Daze a creature", target_id=RIGHT)
    other_first = _daze_bearers(reload(combat, mid).state.actors[RIGHT])
    turn(table, mid, LEFT)
    _cast(table, mid, "Daze a creature", target_id=RIGHT)  # A's first Daze
    _cast(table, mid, "Daze again", target_id=RIGHT)      # A refreshes it, same turn, economy-free
    target = reload(combat, mid).state.actors[RIGHT]
    bearers = _daze_bearers(target)
    assert other_first, "the first caster's Daze really was placed"
    assert (DAZED, OTHER) in bearers, \
        f"A's refresh must not delete another caster's Daze: {sorted(bearers)}"
    assert bearers.count((DAZED, LEFT)) == 1, \
        f"A's own Daze is replaced, not stacked: {sorted(bearers)}"
    assert dazed_restriction.holds(target), "Dazed: no Reactions, and an Action or a Bonus Action, not both"
    assert not target.reaction_available, "Dazed: cannot take Reactions"


def _daze_bearers(target):
    return [(row.condition_id, row.source_actor_id) for row in target.conditions.values()
            if row.condition_id in dazed_restriction.IDS]


def test_each_daze_still_ends_at_its_own_casters_next_turn(tmp_path):
    """The deadlines really are per caster: a creature is Dazed while *any* of its printed Dazes is still running, and
    only the last one to end lifts the restriction.

    Turn order is not assumed -- the test walks the fight forward and checks the invariant at every step, so whichever
    caster goes first, its own deadline is the one that ends first and the other's Daze still holds the creature.
    """
    def edits(bundle):
        if bundle.get("actor_id") in (LEFT, OTHER):
            _daze_action(bundle, bundle["actor_id"], "Daze a creature")

    combat, table, mid = triple_fight(tmp_path, [FLOOR], third_ally=True, bundle_edit=edits)
    turn(table, mid, OTHER)
    _cast(table, mid, "Daze a creature", target_id=RIGHT)
    turn(table, mid, LEFT)
    _cast(table, mid, "Daze a creature", target_id=RIGHT)
    assert sorted(_daze_bearers(reload(combat, mid).state.actors[RIGHT])) == sorted([(DAZED, LEFT), (DAZED, OTHER)])

    seen_partial, seen_free = False, False
    for _ in range(8):  # two full rounds is enough for both "until the start of your next turn" deadlines
        for creature in (LEFT, OTHER, RIGHT):
            if table.state(mid)["menu"]["actor_id"] != creature:
                turn(table, mid, creature)
        bearers = _daze_bearers(reload(combat, mid).state.actors[RIGHT])
        held = dazed_restriction.holds(reload(combat, mid).state.actors[RIGHT])
        assert held == bool(bearers), \
            f"Dazed exactly while a printed Daze remains: bearers={sorted(bearers)} holds={held}"
        seen_partial = seen_partial or len(bearers) == 1
        seen_free = seen_free or not bearers
        if seen_partial and seen_free:
            break
    assert seen_partial, "one caster's Daze ends while the other's is still running"
    assert seen_free, "the last Daze to end lifts the restriction"


def _daze_then_turn_to(table, mid, target_id=RIGHT):
    """Two casters Daze ``target_id`` with the real printed Daze, then hand the target its own turn with the Daze live."""
    _cast(table, mid, "Daze a creature", target_id=target_id)
    turn(table, mid, OTHER)
    _cast(table, mid, "Daze a creature", target_id=target_id)
    _turn_to(table, mid, target_id)


def _dazed_pair_fight(tmp_path):
    def edits(bundle):
        if bundle.get("actor_id") in (LEFT, OTHER):
            _daze_action(bundle, bundle["actor_id"], "Daze a creature")
    return four_fight(tmp_path, left_talents=[FLOOR], bundle_edit=edits)


def _menu_options_in_economy(engine, table, mid, economy):
    """Every option the acting creature's menu currently offers whose real action definition costs ``economy``.

    Matched exactly -- against the action definition the menu group names, which is the engine's own compiled economy,
    rather than by string suffix on a label. ``endswith("ACTION")`` would also match BONUS_ACTION, so a caller asking for
    an Action could silently be handed a Bonus Action and assert the wrong half of the printed rule.
    """
    out = set()
    for group in table.state(mid)["menu"]["actions"]:
        action = engine.action_catalog.get(group.get("source_definition_id"))
        if action is not None and getattr(getattr(action, "economy", None), "value", action.economy) == economy:
            out.add(group["label"])
    return sorted(out)


@pytest.mark.parametrize("spend_first,refused_label", [
    ("Unarmed Strike", None),        # Action first: the Bonus Action is what Daze refuses afterwards
], ids=["action-then-bonus"])
def test_a_dazed_creature_cannot_take_a_bonus_action_after_it_has_taken_its_action(tmp_path, spend_first, refused_label):
    """Printed Daze: "it may take either an Action or a Bonus Action on its turn, not both".

    Spent through the table, not by poking availability flags: the creature really takes its Action, TabletopService
    commits, and the state is read back from a fresh reload. While the Daze is live both economies are on offer -- so a
    menu that simply refuses everything cannot pass this -- and once the Action is spent the Bonus Action is gone, which
    is the Daze's doing and not the engine's ordinary "your action is used" rule (which leaves the Bonus Action alone).
    """
    combat, table, mid = _dazed_pair_fight(tmp_path)
    _daze_then_turn_to(table, mid)
    _cast(table, mid, "Drop Bi Shou (Dagger)")   # economy-free, so it costs neither; it makes the printed Bonus Action real
    engine = combat._load_session(mid).engine
    assert _menu_options_in_economy(engine, table, mid, "BONUS_ACTION"), \
        "a Bonus Action is on offer while the Daze is live"
    assert _menu_options_in_economy(engine, table, mid, "ACTION"), \
        "an Action is on offer while the Daze is live"

    _cast(table, mid, spend_first, target_id=LEFT)
    assert reload(combat, mid).state.actors[RIGHT].action_available is False, "the Action really was spent, and persisted"
    assert reload(combat, mid).state.actors[RIGHT].bonus_action_available is True, \
        "the Bonus Action economy itself is untouched: it is the Daze that refuses it"
    assert not _menu_options_in_economy(combat._load_session(mid).engine, table, mid, "BONUS_ACTION"), \
        "having taken its Action, a Dazed creature may not also take a Bonus Action"


def test_a_dazed_creature_cannot_take_an_action_after_it_has_taken_its_bonus_action(tmp_path):
    """The other half of the printed rule, through the table and a reload.

    The creature spends its Bonus Action on the printed "Pick up" -- which needs its dagger on the ground, so the
    economy-free Drop goes first -- and its Actions are then gone. Before the Bonus Action is spent they are not, so this
    is the Daze and not the ordinary per-economy bookkeeping.
    """
    combat, table, mid = _dazed_pair_fight(tmp_path)
    _daze_then_turn_to(table, mid)
    assert "Unarmed Strike" in _labels(table, mid), "an Action is on offer while the Daze is live"
    _cast(table, mid, "Drop Bi Shou (Dagger)")
    assert "Pick up Bi Shou (Dagger)" in _labels(table, mid), "the printed Bonus Action is now on offer"

    _cast(table, mid, "Pick up Bi Shou (Dagger)")
    assert reload(combat, mid).state.actors[RIGHT].bonus_action_available is False, \
        "the Bonus Action really was spent, and persisted"
    assert reload(combat, mid).state.actors[RIGHT].action_available is True, \
        "the Action economy itself is untouched: it is the Daze that refuses it"
    assert "Unarmed Strike" not in _labels(table, mid), \
        "having taken its Bonus Action, a Dazed creature may not also take an Action"


def test_a_second_caster_does_not_stack_the_action_or_bonus_restriction(tmp_path):
    """Two Dazes still deny one Action or one Bonus Action, not a doubled restriction. The printed half of the rule is
    exercised on real Action and Bonus Action definitions, selected by exact economy."""
    from combat import ext

    def edits(bundle):
        if bundle.get("actor_id") in (LEFT, OTHER):
            _daze_action(bundle, bundle["actor_id"], "Daze a creature")

    combat, table, mid = four_fight(tmp_path, left_talents=[FLOOR], bundle_edit=edits)
    _cast(table, mid, "Daze a creature", target_id=RIGHT)
    turn(table, mid, OTHER)
    _cast(table, mid, "Daze a creature", target_id=RIGHT)
    engine = combat._load_session(mid).engine
    target = reload(combat, mid).state.actors[RIGHT]
    assert dazed_restriction.holds(target)
    assert ext.run("reaction_allowed", engine, target, target) == [False], "Dazed: cannot take Reactions"

    # "may take either an Action or a Bonus Action on its turn, not both": with both economies still available neither is
    # what Daze refuses. These are the engine's own real action definitions, wrapped in a real candidate of the kind the
    # table offers -- matched on the exact economy, so asking for an Action can never hand back a Bonus Action.
    from combat.gate2_runtime_models import CandidateKind, LegalCandidate

    def candidate(economy):
        action = next((a for a in engine.action_catalog.values() if a.owner_id == RIGHT
                       and getattr(getattr(a, "economy", None), "value", a.economy) == economy), None)
        assert action is not None, f"no printed {economy} for the Dazed creature to be refused"
        return LegalCandidate(candidate_id="test", decision_id="test", state_version=1, kind=CandidateKind.ACTION,
                              actor_id=RIGHT, source_definition_id=action.source_definition_id,
                              display_name=action.display_name), action

    target.action_available, target.bonus_action_available = True, True
    for economy in ("ACTION", "BONUS_ACTION"):
        allowed, action = candidate(economy)
        assert dazed_restriction.dazed_one_action(engine, target, allowed, action) is None, \
            f"while both economies are still available the {economy} is not what Daze refuses"
