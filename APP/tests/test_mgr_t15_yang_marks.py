"""MGR-T15 Yang marks (1D1): the five source records' intact clauses, through real fights.

Each test fails on the code before this round: marks kept a producer's expression regardless of
willingness, a willing bearer had no way to end its own Kindled Mark, Completing Flame Mantle's
linked mark and Complete Force damage-type rider did nothing, Life Refuses Closure protected a
creature that was killed outright, Dawn's Kindled Mark never expired and its Prone target stayed
down, and Ten-Thousand Motions Become Noon applied no start-of-turn mark, no movement light and
no maximum response die.
"""
import pytest

from combat import typed_reactions
from combat.ext.yang_sun_marks import EXCEPTION, DIM_LIGHT, completion_allows, consume_completion
from combat.ext.yang_recovery import ROUND
from combat.posture import prone_conditions
from combat.typed_executor import CONDITION_PREFIX, bears_mark, block_mark
from combat.ext import states
from tests.worker2_support import (ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn)


def _context(engine, actor, target):
    marker = engine.state.actors[actor] if isinstance(actor, str) else actor
    ctx = states.context(engine, marker, "test:mark", [target], {})
    ctx.effect_source = "TAL_YANG_APPLYING_A_RISING_MARK#kindle_the_rising"
    return ctx


def _kindled_ids(actor, owner=OWNER):
    return [c.condition_id for c in actor.conditions.values()
            if c.condition_id.startswith(CONDITION_PREFIX + "mark.kindled_mark." + owner)]


def _overkindled_ids(actor, owner=OWNER):
    return [c.condition_id for c in actor.conditions.values()
            if c.condition_id.startswith(CONDITION_PREFIX + "mark.overkindled_mark." + owner)]


def _hit(engine, who, damage=30):
    # Numeric probes use Auto reactions, not an unanswered manual table intent
    # left over from fixture turn setup. Include the real packet-query boundary.
    from combat import pending_damage

    previous = engine._active_intent
    engine._active_intent = None
    try:
        with pending_damage.scope(engine, who, damage, "SLASHING", "action:test.attack", FOE):
            pending_damage.prepare(engine, damage, None)
            return typed_reactions.on_damage(engine, who, damage, 0,
                                             source_definition_id="action:test.attack", source_actor_id=FOE)
    finally:
        engine._active_intent = previous


def _move_candidate(combat, mid, destination):
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates()
            if c.display_name.startswith("Move to ") and c.destination
            and (c.destination.x, c.destination.y) == destination]
    assert rows, f"no move to {destination}"
    return rows[0]


DAGGER = {"items": [{"item_id": "tianxia.mortal.weapon.bi_shou", "name": "Bi Shou (Dagger)", "quantity": 1}]}


# ---------------------------------------------------------------- Kindled / Overkindled expression
def test_rising_mark_expression_follows_the_bearers_willingness(tmp_path):
    # "A Rising Mark on you, a willing creature ... is a Kindled Mark. ... on an unwilling
    # creature ... is an Overkindled Mark." A neutral placement is resolved by the bearer; an owning
    # record that already names an expression keeps it (Kindle the Wounded Breath heals a chosen foe
    # and prints a Kindled Mark for it).
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_COMPLETING_FLAME_MANTLE"])
    engine = combat._load_session(mid).engine
    ally, foe = engine.state.actors[ALLY], engine.state.actors[FOE]
    block_mark(_context(engine, OWNER, ally), {"type": "mark", "mark": "Rising Mark", "applies_to": "target"})
    assert _kindled_ids(ally) and not _overkindled_ids(ally)
    block_mark(_context(engine, OWNER, foe), {"type": "mark", "mark": "Rising Mark", "applies_to": "target"})
    assert _overkindled_ids(foe) and not _kindled_ids(foe)
    block_mark(_context(engine, OWNER, engine.state.actors[OWNER]),
               {"type": "mark", "mark": "Rising Mark", "applies_to": "target"})
    me = engine.state.actors[OWNER]
    assert _kindled_ids(me) and not _overkindled_ids(me)
    block_mark(_context(engine, OWNER, foe), {"type": "mark", "mark": "Kindled Mark", "applies_to": "target"})
    assert _kindled_ids(foe)  # a named Kindled Mark is not reclassified


def test_a_willing_bearer_ends_its_kindled_mark_without_an_action(tmp_path):
    # "A willing creature may end your Rising Mark on itself at any time, no Action required."
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_COMPLETING_FLAME_MANTLE"])
    settle(table, mid, candidate(combat, mid, "Kindle the Rising", target=ALLY).candidate_id)
    assert _kindled_ids(reload(tmp_path, mid).state.actors[ALLY])
    turn(table, mid, ALLY)
    engine = combat._load_session(mid).engine
    action_available = engine.state.actors[ALLY].action_available
    ending = candidate(combat, mid, "End a Kindled Mark on yourself")
    settle(table, mid, ending.candidate_id)
    engine = reload(tmp_path, mid)
    assert not _kindled_ids(engine.state.actors[ALLY])
    assert engine.state.actors[ALLY].action_available == action_available


@pytest.mark.parametrize("answer", ["accept", "refuse"])
def test_neutral_rising_mark_recipient_consent_survives_table_reload(tmp_path, answer):
    from combat.canonical import canonical_sha256
    from combat.ext.yang_sun_marks import offer_cancel

    def neutral_kindle(bundles):
        # Synthetic neutral producer: exercise mark_apply through a sealed table action.
        bundle = bundles[0]
        action = next(a for a in bundle["action_catalog"]
                      if a["source_definition_id"].endswith(KINDLE))
        marks = [e for e in action["parameters"]["typed"]["effects"] if e.get("type") == "mark"]
        assert marks
        for row in marks:
            row["mark"] = "Rising Mark"
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, mid = fixture(tmp_path, [KINDLE], named=True, bundle_transform=neutral_kindle)
    from tests.worker2_support import act

    kindle = candidate(combat, mid, "Kindle the Rising", target=ALLY).candidate_id
    pending = act(table, mid, kindle)
    assert pending["status"] == "REACTION_REQUIRED"
    assert pending["reaction"]["context"]["reaction_source_id"] == "choice:willing.consent"
    assert pending["reaction"]["context"]["reactor_id"] == ALLY
    waiting = reload(tmp_path, mid).state.actors[ALLY]
    assert not _kindled_ids(waiting) and not _overkindled_ids(waiting)
    prompts = settle(table, mid, kindle, picks={"choice:willing.consent": answer})
    consent = [p for p in prompts if p["context"]["reaction_source_id"] == "choice:willing.consent"]
    assert consent and consent[0]["context"]["reactor_id"] == ALLY
    prompt = consent[0]["moment"]
    assert all(name in prompt for name in ("Wren", "Tobin", "Kindle the Rising"))
    engine = reload(tmp_path, mid)
    ally = engine.state.actors[ALLY]
    assert bool(_kindled_ids(ally)) is (answer == "accept")
    assert bool(_overkindled_ids(ally)) is (answer == "refuse")
    assert bool(offer_cancel(engine, ally)) is (answer == "accept")
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    assert any(c.display_name == "End a Kindled Mark on yourself"
               for c in engine.legal_candidates()) is (answer == "accept")


# ---------------------------------------------------------------- Completing Flame Mantle
def test_mantle_self_kindle_also_marks_one_willing_creature_within_ten_feet(tmp_path):
    # "when you use Kindle the Rising on yourself, you may also apply a Kindled Mark to one
    # willing creature within 10 feet" -- while the Mantle is active.
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_COMPLETING_FLAME_MANTLE"], positions={
        OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 9, "y": 9}})
    settle(table, mid, candidate(combat, mid, "Completing Flame Mantle").candidate_id)
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    prompts = settle(table, mid, candidate(combat, mid, "Kindle the Rising", target=OWNER).candidate_id,
                    picks={"choice:needle.mantle_link": ALLY})
    assert any(p["context"]["reaction_source_id"] == "choice:needle.mantle_link" for p in prompts)
    engine = reload(tmp_path, mid)
    assert _kindled_ids(engine.state.actors[OWNER]) and _kindled_ids(engine.state.actors[ALLY])


def test_mantle_zone_keeps_its_printed_light_and_grappler_damage(tmp_path):
    # "you emit bright light in a 10-foot radius and dim light for an additional 10 feet";
    # "a creature that starts its turn Grappling you takes Fire or Radiant damage equal to
    # your Proficiency Bonus + your Key Ability modifier"; the Mantle "does not count as sunlight".
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet

    bundle = compile_character(sheet(["TAL_YANG_COMPLETING_FLAME_MANTLE"], cl=15), actor_id=OWNER)
    # Kindle/Force augments also end in the Mantle id. Inspect its OWN action.
    row = next(a for a in bundle["action_catalog"]
               if a["parameters"].get("typed", {}).get("source") == "TAL_YANG_COMPLETING_FLAME_MANTLE")
    spec = row["parameters"]["typed"]["zone_spec"]
    assert spec["visual"]["light"]["radius_ft"] == 10 and spec["visual"]["light"]["level"] == "bright"
    assert spec["profile"].get("grappling_owner") == 1
    trigger = spec["triggers"][0]
    assert trigger["on"] == ["grappler_start"]
    damage = trigger["effects"][0]
    assert damage["damage_types"] == ["fire", "radiant"]
    assert damage["formula"] == "key_ability_modifier"
    assert damage["dice"]["bonus_formula"] == "pb"
    assert spec["visual"].get("sunlight") is None  # illumination is not tracked; the Mantle is not sunlight


def test_mantle_wraps_complete_force_damage_only_for_its_owner(tmp_path):
    # "once per turn when you spend a Kindled Mark with Complete Force, the bonus damage may be
    # Fire, Radiant, or Force damage instead."
    from combat.factory_compiler import compile_character
    from tests.h1_support import sheet

    with_mantle = compile_character(sheet(["TAL_YANG_COMPLETING_FLAME_MANTLE"], cl=15), actor_id=OWNER)
    row = next(r for r in with_mantle["typed_reactions"] if r["feature_id"] == "TAL_YANG_KINDLED_RESPONSES#complete_force")
    assert [e.get("type") for e in row["effects"] if e.get("type", "").startswith("yang_completion")] == ["yang_completion_damage"]
    without = compile_character(sheet(["TAL_YANG_APPLYING_A_RISING_MARK#kindle_the_rising"], cl=15), actor_id=OWNER)
    plain = next(r for r in without["typed_reactions"] if r["feature_id"] == "TAL_YANG_KINDLED_RESPONSES#complete_force")
    assert not any(str(e.get("type", "")).startswith("yang_completion") for e in plain["effects"])


# ---------------------------------------------------------------- Life Refuses Closure
def test_life_refuses_closure_cannot_hold_a_creature_killed_outright(tmp_path):
    # Trigger: "would be reduced to 0 Hit Points but not killed outright". Leftover damage past
    # current + maximum HP is instant death, so 1 Hit Point is not a possible outcome.
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_LIFE_REFUSES_CLOSURE"], ask=False)
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    ally.current_hp = 5
    from combat import pending_damage

    with pending_damage.scope(engine, ally, 100, "SLASHING", "action:test.attack", FOE):
        assert _hit(engine, ally, 100) == 100
    assert not _kindled_ids(ally)
    assert not prone_conditions(ally)


def test_life_refuses_closure_records_the_first_damage_exception(tmp_path):
    # "the first time it deals damage, it may spend its Kindled Mark with Complete Force without
    # counting against your once-per-round limit"; a Life mark is Force-only, never Aim.
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_LIFE_REFUSES_CLOSURE"], ask=False)
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    ally.current_hp = 5
    assert _hit(engine, ally) == 4
    held = [c for c in ally.conditions.values() if c.condition_id == EXCEPTION]
    assert held and held[0].data["source"] == "TAL_YANG_LIFE_REFUSES_CLOSURE"
    assert held[0].data["kind"] == "first_damage"
    assert completion_allows(engine, OWNER, ally, "force")
    assert not completion_allows(engine, OWNER, ally, "aim")
    assert consume_completion(engine, OWNER, ally, "force")
    assert not completion_allows(engine, OWNER, ally, "force")


def test_life_refuses_closure_long_rest_limit_is_per_creature(tmp_path):
    # "Use Limit: Once per Long Rest per creature": a second use on the same ally is refused even
    # after the Reaction comes back; another creature still has its own use.
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_LIFE_REFUSES_CLOSURE"], ask=False)
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    ally.current_hp = 5
    assert _hit(engine, ally) == 4
    engine.state.actors[OWNER].reaction_available = True
    assert _hit(engine, ally) == 30


def test_life_exception_pays_complete_force_once(tmp_path):
    from combat.typed_executor import run_effects
    from combat.ext.yang_sun_marks import LIFE

    combat, table, mid = fixture(tmp_path, [LIFE], ask=False)
    engine = combat._load_session(mid).engine
    ally, foe = engine.state.actors[ALLY], engine.state.actors[FOE]
    run_effects(_context(engine, OWNER, ally), [
        {"type": "mark", "mark": "Kindled Mark", "applies_to": "target"},
        {"type": "yang_completion_exception", "source": LIFE, "applies_to": "ally"},
    ])
    ctx = _context(engine, ALLY, foe)
    run_effects(ctx, [{"type": "damage", "flat": 1, "applies_to": "target"}])
    assert not bears_mark(ally, OWNER, "Kindled Mark")
    assert not completion_allows(engine, OWNER, ally, "force")
    assert engine.state.actors[OWNER].turn_flags.get(ROUND) is None
    from combat.ext.yang_sun_marks import FORCE
    bonuses = lambda: [e for e in engine.events if e.event_type == "DAMAGE_COMMITTED"
                       and e.source_definition_id == FORCE]
    assert len(bonuses()) == 1 and bonuses()[0].payload["hp_damage"] > 0
    run_effects(_context(engine, ALLY, foe), [{"type": "damage", "flat": 1, "applies_to": "target"}])
    assert len(bonuses()) == 1  # a later occurrence cannot spend this exception again


# ---------------------------------------------------------------- Dawn Commands the Fallen Breath
def test_dawn_stands_the_target_and_times_its_mark(tmp_path):
    # "The target drops to 1 Hit Point instead of dying and gains a Kindled Mark that lasts for
    # 1 minute. It may immediately stand if Prone."
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_DAWN_COMMANDS_THE_FALLEN_BREATH"], ask=False)
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    ally.current_hp = 5
    engine._apply_condition(ally, CONDITION_PREFIX + "prone", "test:prone", FOE, expires_on="UNTIL_REMOVED")
    assert prone_conditions(ally)
    assert _hit(engine, ally) == 4
    assert not prone_conditions(ally)
    mark = [c for c in ally.conditions.values() if c.condition_id in _kindled_ids(ally)]
    from combat.typed_executor import clock_expiry
    # "lasts for 1 minute": the standard clock duration (rules duration_rounds), not the fight,
    # derived from the printed unit instead of hardcoding the standard's round count.
    assert mark and mark[0].expires_on == clock_expiry(engine, "minutes", 1)
    assert any(c.condition_id == EXCEPTION and c.data["kind"] == "first_hit_or_save" for c in ally.conditions.values())


@pytest.mark.parametrize("accept", [True, False])
@pytest.mark.parametrize("round_used", [False])
def test_complete_aim_pays_only_after_acceptance(tmp_path, monkeypatch, accept, round_used):
    # Drive _aim itself, not pay_complete_aim_slot: the free normal slot stays
    # unpaid until acceptance, and Dawn's held exception is not used pre-roll.
    # Occupied-slot behavior is covered by the real miss regression in occurrences.
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_DAWN_COMMANDS_THE_FALLEN_BREATH"])
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    from combat.ext import yang_recovery
    from combat.ext.yang_sun_marks import DAWN
    from combat.typed_executor import run_effects

    # Dawn's death-trigger dispatch is covered above; install its real benefit
    # here so this regression isolates the choice/payment ordering in _aim.
    run_effects(_context(engine, OWNER, ally), [
        {"type": "mark", "mark": "Kindled Mark", "applies_to": "target"},
        {"type": "yang_completion_exception", "source": DAWN, "applies_to": "ally"},
    ])
    owner = engine.state.actors[OWNER]
    before_slot = engine.state.round_number if round_used else None
    if round_used:
        owner.turn_flags[ROUND] = before_slot
    choices = []

    def answer(*args, **kwargs):
        # At the actual _aim choice boundary, no payment is allowed yet.
        choices.append(kwargs["choice_id"])
        assert owner.turn_flags.get(ROUND) == before_slot
        assert completion_allows(engine, OWNER, ally, "aim")
        assert bears_mark(ally, OWNER, "Kindled Mark")
        return "use" if accept else None

    monkeypatch.setattr(yang_recovery.family, "choose", answer)
    bonus = yang_recovery._aim(_context(engine, ALLY, engine.state.actors[FOE]), ally,
                              target=engine.state.actors[FOE])
    assert choices == ["choice:needle.yang_aim_attack"]
    assert bool(bonus) is accept
    assert completion_allows(engine, OWNER, ally, "aim") is not (accept and round_used)
    assert bears_mark(ally, OWNER, "Kindled Mark") is not accept
    assert owner.turn_flags.get(ROUND) == (engine.state.round_number if accept else before_slot)


@pytest.mark.parametrize("accept", [True, False])
def test_dawn_exception_is_not_spent_when_complete_aim_takes_the_free_round_slot(tmp_path, accept):
    # Actual attack -> _aim -> player response, not the payment helper.
    from combat.canonical import canonical_sha256
    from combat.ext.yang_sun_marks import DAWN

    def dawn_benefit(bundles):
        # Seal a synthetic setup action carrying Dawn's real benefit effects, so
        # setup itself commits instead of mutating a disposable service session.
        bundle = bundles[0]
        action = next(a for a in bundle["action_catalog"]
                      if a["source_definition_id"].endswith(KINDLE))
        action["parameters"]["typed"]["effects"].append(
            {"type": "yang_completion_exception", "source": DAWN, "applies_to": "ally"})
        bundle.pop("bundle_sha256", None)
        bundle["bundle_sha256"] = canonical_sha256(bundle)

    combat, table, mid = fixture(
        tmp_path, [DAWN], bundle_transform=dawn_benefit,
        ally_kit={"starting_kit": DAGGER}, named=True,
        positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 5, "y": 6}})
    settle(table, mid, candidate(combat, mid, "Kindle the Rising", target=ALLY).candidate_id)
    assert completion_allows(reload(tmp_path, mid), OWNER, reload(tmp_path, mid).state.actors[ALLY], "aim")
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    assert engine.state.actors[OWNER].turn_flags.get(ROUND) != engine.state.round_number
    assert completion_allows(engine, OWNER, engine.state.actors[ALLY], "aim"), "Dawn exception missing before attack"
    from tests.worker2_support import act

    attack = candidate(combat, mid, "Bi Shou (Dagger) attack", target=FOE).candidate_id
    pending = act(table, mid, attack)
    assert pending["status"] == "REACTION_REQUIRED"
    assert pending["reaction"]["context"]["reaction_source_id"] == "choice:needle.yang_aim_attack"
    waiting = reload(tmp_path, mid)
    assert waiting.state.actors[OWNER].turn_flags.get(ROUND) != waiting.state.round_number
    assert completion_allows(waiting, OWNER, waiting.state.actors[ALLY], "aim")
    assert bears_mark(waiting.state.actors[ALLY], OWNER, "Kindled Mark")
    prompts = settle(
        table, mid, attack,
        picks={"choice:needle.yang_aim_attack": "use" if accept else None,
               "choice:needle.completion_force": None})
    assert any(p["context"]["reaction_source_id"] == "choice:needle.yang_aim_attack" for p in prompts), "Complete Aim was not offered"
    engine = reload(tmp_path, mid)
    owner, ally = engine.state.actors[OWNER], engine.state.actors[ALLY]
    assert (owner.turn_flags.get(ROUND) == engine.state.round_number) is accept
    # Accepting ordinary Aim spends the mark before the hit; declining it leaves
    # the first hit to consume Dawn\'s exception, even if that response is declined too.
    assert completion_allows(engine, OWNER, ally, "aim") is accept
    assert bears_mark(ally, OWNER, "Kindled Mark") is not accept
    aim_rolls = [e for e in engine.events if e.event_type == "CHECK_ROLLED"
                 and str(e.source_definition_id).endswith("#complete_aim")]
    assert bool(aim_rolls) is accept


# ---------------------------------------------------------------- Kindle the Rising in one engine (review 1)
KINDLE = 'TAL_YANG_APPLYING_A_RISING_MARK#kindle_the_rising'


def test_two_kindle_owners_share_one_engine_and_each_keeps_its_own_end_button(tmp_path):
    # The end-button id must be per owner: a fixed id collided (TYPED_ACTION_ID_COLLISION) when two
    # Kindle the Rising bundles were registered in the same engine.
    from combat.ext import yang_sun_marks as sun

    combat, table, mid = fixture(tmp_path, [KINDLE], ally_talents=[KINDLE])
    engine = combat._load_session(mid).engine
    ids = {str(a.source_definition_id) for a in engine.action_catalog.values()
           if str(a.source_definition_id).startswith(sun.CANCEL)}
    assert ids == {sun.cancel_id(OWNER), sun.cancel_id(ALLY)}
    block_mark(_context(engine, OWNER, engine.state.actors[ALLY]), {"type": "mark", "mark": "Kindled Mark", "applies_to": "target"})
    block_mark(_context(engine, ALLY, engine.state.actors[FOE]), {"type": "mark", "mark": "Kindled Mark", "applies_to": "target"})
    assert sun.offer_cancel(engine, engine.state.actors[ALLY]) == [sun.cancel_id(OWNER)]
    assert sun.offer_cancel(engine, engine.state.actors[FOE]) == [sun.cancel_id(ALLY)]


def test_overkindled_replaces_a_kindled_mark_from_the_same_owner(tmp_path):
    # A Kindled and an Overkindled Mark are one Rising Mark family: a neutral Rising Mark on an
    # unwilling creature that already holds the owner's Kindled Mark leaves exactly one, Overkindled.
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_COMPLETING_FLAME_MANTLE"])
    engine = combat._load_session(mid).engine
    foe = engine.state.actors[FOE]
    block_mark(_context(engine, OWNER, foe), {"type": "mark", "mark": "Kindled Mark", "applies_to": "target"})
    assert _kindled_ids(foe)
    block_mark(_context(engine, OWNER, foe), {"type": "mark", "mark": "Rising Mark", "applies_to": "target"})
    assert _overkindled_ids(foe) and not _kindled_ids(foe)
    assert len([c for c in foe.conditions.values() if c.condition_id.startswith(CONDITION_PREFIX + "mark.")]) == 1


# ---------------------------------------------------------------- Ten-Thousand Motions Become Noon
def _cast_noon(table, combat, mid, at):
    engine = combat._load_session(mid).engine
    rows = [c for c in engine.legal_candidates()
            if c.display_name.startswith("Ten-Thousand Motions Become Noon")
            and c.destination and (c.destination.x, c.destination.y) == at]
    assert rows, f"Ten-Thousand Motions Become Noon cannot be centred on {at}"
    settle(table, mid, rows[0].candidate_id)


def test_noon_ally_start_of_turn_may_gain_a_kindled_mark(tmp_path):
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_TEN_THOUSAND_MOTIONS_BECOME_NOON"],
                                positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 9, "y": 9}})
    _cast_noon(table, combat, mid, (3, 6))
    turn(table, mid, ALLY)
    engine = reload(tmp_path, mid)
    assert _kindled_ids(engine.state.actors[ALLY])


def test_noon_concealed_enemy_gains_an_overkindled_mark(tmp_path):
    # "enemies that start their turn Hidden, Invisible, heavily obscured, or under an illusion
    # gain one Overkindled Mark." The same turn_start_choice checkpoint is proven in the ally
    # test; this one sets the Hidden condition directly because no table action sets a condition.
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_TEN_THOUSAND_MOTIONS_BECOME_NOON"],
                                positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 8}, FOE: {"x": 5, "y": 6}})
    _cast_noon(table, combat, mid, (3, 6))
    from combat import ext, stealth

    engine = combat._load_session(mid).engine
    foe = engine.state.actors[FOE]
    engine._apply_condition(foe, stealth.HIDDEN, "test:hidden", FOE, expires_on="UNTIL_REMOVED")
    ext.run_strict("turn_start_choice", engine, foe)
    assert _overkindled_ids(foe)


def test_noon_twenty_feet_of_movement_emits_dim_light(tmp_path):
    # "when any creature in the area moves at least 20 feet during its turn, it emits dim light
    # until the start of its next turn."
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_TEN_THOUSAND_MOTIONS_BECOME_NOON"],
                                positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 4, "y": 6}, FOE: {"x": 9, "y": 9}})
    _cast_noon(table, combat, mid, (3, 6))
    turn(table, mid, ALLY)
    settle(table, mid, _move_candidate(combat, mid, (2, 6)).candidate_id)
    settle(table, mid, _move_candidate(combat, mid, (4, 6)).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(c.condition_id == DIM_LIGHT for c in engine.state.actors[ALLY].conditions.values())


def test_noon_spent_rising_mark_gives_complete_aim_its_maximum_die(tmp_path):
    # "when you spend a Rising Mark in the area, increase one die rolled by the response to its
    # maximum result." CL 15 -> Complete Aim's die is 1d6, so the recorded die is 6.
    combat, table, mid = fixture(tmp_path, ["TAL_YANG_TEN_THOUSAND_MOTIONS_BECOME_NOON"], cl=15,
                                 owner_kit={"starting_kit": DAGGER},
                                 positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 2, "y": 8}, FOE: {"x": 4, "y": 6}})
    _cast_noon(table, combat, mid, (3, 6))
    turn(table, mid, ALLY)
    turn(table, mid, OWNER)
    settle(table, mid, candidate(combat, mid, "Kindle the Rising", target=OWNER).candidate_id)
    settle(table, mid, candidate(combat, mid, "Bi Shou (Dagger) attack", target=FOE).candidate_id,
            picks={"choice:needle.yang_aim_attack": "use"})
    engine = reload(tmp_path, mid)
    aim = next(r for r in engine.events
               if r.event_type == "CHECK_ROLLED" and str(r.source_definition_id).endswith("#complete_aim"))
    assert aim.payload["dice"] == [6] and aim.payload["total"] == 6


def test_other_producers_neutral_rising_mark_is_not_a_yang_mark(tmp_path):
    combat, table, mid = fixture(tmp_path, [KINDLE])
    engine = combat._load_session(mid).engine
    ally = engine.state.actors[ALLY]
    ctx = _context(engine, OWNER, ally)
    ctx.effect_source = "TAL_OTHER_NEUTRAL_MARK"
    block_mark(ctx, {"type": "mark", "mark": "Rising Mark", "applies_to": "target"})
    assert bears_mark(ally, OWNER, "Rising Mark")
    assert not _kindled_ids(ally) and not _overkindled_ids(ally)


@pytest.mark.parametrize("response", ["complete_force", "complete_resolve", "overheat_force"])
@pytest.mark.parametrize("inside", [True, False])
def test_noon_maximizes_one_die_for_each_other_dice_response(tmp_path, response, inside):
    from combat.gate2_rolls import DeterministicRollAuthority
    from combat.gate2_runtime_models import DiceSpec
    from combat.typed_executor import run_effects

    combat, table, mid = fixture(tmp_path, ["TAL_YANG_TEN_THOUSAND_MOTIONS_BECOME_NOON"],
                                positions={OWNER: {"x": 3, "y": 6}, ALLY: {"x": 2, "y": 8},
                                           FOE: {"x": 4, "y": 6}})
    # Keep a real, committed zone and cold reload; exercise the same two amount
    # paths the accepted reactions dispatch (damage effects and save bonuses).
    _cast_noon(table, combat, mid, (3, 6))
    engine = reload(tmp_path, mid)
    owner, foe = engine.state.actors[OWNER], engine.state.actors[FOE]
    if not inside:
        owner.position = owner.position.model_copy(update={"x": 30, "y": 30})
    family = "OVERKINDLED" if response == "overheat_force" else "KINDLED"
    source = f"TAL_YANG_{family}_RESPONSES#{response}"
    # Synthetic printed CL-15 response amounts: public exports may redact the
    # prose used to classify reaction triggers. This test concerns the accepted
    # response's actual amount path, not that separate classification step.
    effect = {"type": "attack_modifier" if response == "complete_resolve" else "damage",
              "dice": {"count": 1 if response == "complete_resolve" else 3, "sides": 6},
              **({} if response == "complete_resolve" else {"formula": "key_ability_modifier"})}
    row = {"feature_id": source, "numbers": {"cl": 15, "key_mod": 2}, "effects": [effect]}
    spec = effect["dice"]
    while True:
        raw = DeterministicRollAuthority(seed=engine.roller.seed, counter=engine.roller.counter).roll(
            DiceSpec(count=spec["count"], sides=spec["sides"]), actor_id=OWNER, reason="expected")
        if raw.dice[0] < spec["sides"]:
            break
        engine.roller.counter = raw.counter_end  # never let a natural maximum hide a missing hook
    if response == "complete_resolve":
        amount = typed_reactions._generic_amount(engine, owner, row, effect)
    else:
        ctx = _context(engine, OWNER, foe)
        ctx.effect_source = source
        ctx.typed["numbers"] = row["numbers"]
        # Overheat normally resolves the attacker through its reaction context;
        # target it explicitly here without changing its damage or roll path.
        run_effects(ctx, [{**effect, "applies_to": "target"}])
        amount = engine.rolls[-1].total
    roll = engine.rolls[-1]
    expected = (spec["sides"], *raw.dice[1:]) if inside else raw.dice
    assert roll.dice == expected
    assert amount == sum(expected) + roll.modifier
    if spec["count"] > 1:
        assert roll.dice[1:] == raw.dice[1:]  # only one die, never maximize the pool
