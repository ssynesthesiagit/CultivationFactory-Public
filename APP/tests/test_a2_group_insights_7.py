"""Insights 7: Restorative Circulation through sealed CombatService fights and reload.

Wounding and healing both commit through real table actions, so the engine itself
offers the general ``healing_offered_bonus_from`` seam; nothing patches a live
engine. The owner sheet is sealed into the bundle before the fight and every
assertion reads a cold-reloaded saved fight.

The printed trigger is "a Qi-powered feature", so the synthetic healing action is
a Qi sphere feature; the non-Qi regression heals through an action without one.
"""
from combat import typed_executor as te
from combat.ext import insights7 as i7
from combat.ext import life_state
from tests.auto_worker1_support import ALLY, LEFT, RIGHT, act, fight as service_fight, reload, resolve, turn

HEAL = {"type": "healing", "applies_to": "target", "flat": 10}
WOUND = {"type": "damage", "applies_to": "target", "flat": 400, "damage_types": ["force"]}
LETHAL = {"type": "damage", "applies_to": "target", "flat": 1000, "damage_types": ["force"]}
# One printed heal (10) plus the fixture's Proficiency Bonus (4): the wound that leaves the recipient
# exactly one full activation of healing below maximum Hit Points.
NEAR_FULL = {"type": "damage", "applies_to": "target", "flat": 14, "damage_types": ["force"]}
CHOICE = i7.CHOICE


def fight(tmp_path, cl=15, sphere="tianxia.sphere.qiweaving", owner=LEFT, **kwargs):
    """A fight whose healing action is a Qi-powered feature and whose owner holds the Insight."""
    def insight_fields(doc, aid):
        fields = doc["spheres_and_talents"]
        fields["cultivation_insight_record_ids"] = [i7.FEATURE]
        fields["learned_talent_record_ids"] = []
    return service_fight(tmp_path, [], cl=cl, sheet_edit=insight_fields, prepare_sphere=sphere,
                         cause_target="ANY_CREATURE", prepare_target="ANY_CREATURE", **kwargs)


def owner_heals(combat, table, mid, target, before, picks=None, actor=LEFT):
    """The owner's own table action heals ``target``; the Insight may add to it."""
    turn(table, mid, actor)
    resolve(lambda answers: act(table, mid, "Prepare", answers, target_id=target), picks)
    return reload(combat, mid).state.actors[target].current_hp - before


def opponent_wounds(combat, table, mid, target):
    """A real opposing table action wounds ``target``, so the owner can heal a wound."""
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, "Cause", a, target_id=target))
    return reload(combat, mid).state.actors[target].current_hp


def test_healing_an_ally_adds_the_proficiency_bonus(tmp_path):
    combat, table, mid = fight(tmp_path, prepare=[HEAL], cause=[WOUND], ally=True)
    engine = reload(combat, mid)
    assert engine.state.current_actor_id == LEFT
    assert i7.row_of(engine, LEFT, i7.BLOCK, "healing_bonus") is not None
    pb = engine.state.actors[LEFT].proficiency_bonus
    wounded = opponent_wounds(combat, table, mid, ALLY)
    assert wounded < engine.state.actors[ALLY].maximum_hp
    gained = owner_heals(combat, table, mid, ALLY, wounded)
    assert gained == 10 + pb


def test_the_bonus_is_available_again_on_a_later_turn(tmp_path):
    combat, table, mid = fight(tmp_path, prepare=[HEAL], cause=[WOUND], ally=True)
    engine = reload(combat, mid)
    pb = engine.state.actors[LEFT].proficiency_bonus
    wounded = opponent_wounds(combat, table, mid, ALLY)
    turn(table, mid, LEFT)
    resolve(lambda a: act(table, mid, "Prepare", a, target_id=ALLY))
    first = reload(combat, mid).state.actors[ALLY].current_hp
    assert first == wounded + 10 + pb
    # The once-per-turn allowance is not consumed for the rest of the scene.
    wounded = opponent_wounds(combat, table, mid, ALLY)
    assert owner_heals(combat, table, mid, ALLY, wounded) == 10 + pb


def test_a_second_activation_in_the_same_turn_gains_nothing(tmp_path):
    """Once during each of your turns: a second Qi-powered heal in that same turn is plain healing."""
    again = {"effects": [HEAL], "target_kind": "ANY_CREATURE", "sphere": "tianxia.sphere.qiweaving"}
    combat, table, mid = fight(tmp_path, prepare=[HEAL], cause=[WOUND], ally=True, extra_actions=[("Again", again)])
    engine = reload(combat, mid)
    pb = engine.state.actors[LEFT].proficiency_bonus
    wounded = opponent_wounds(combat, table, mid, ALLY)
    turn(table, mid, LEFT)
    resolve(lambda a: act(table, mid, "Prepare", a, target_id=ALLY), {CHOICE: [ALLY]})
    first = reload(combat, mid).state.actors[ALLY].current_hp
    assert first == wounded + 10 + pb
    # Still LEFT's own turn: the printed allowance is spent, so the second heal is the printed 10 and no more.
    resolve(lambda a: act(table, mid, "Again", a, target_id=ALLY))
    assert reload(combat, mid).state.actors[ALLY].current_hp == first + 10


def test_a_non_qi_feature_gains_no_bonus(tmp_path):
    """The printed trigger is a Qi-powered feature: an ordinary feature's heal is untouched."""
    combat, table, mid = fight(tmp_path, prepare=[HEAL], cause=[WOUND], ally=True, sphere=None)
    engine = reload(combat, mid)
    assert i7.row_of(engine, LEFT, i7.BLOCK, "healing_bonus") is not None
    wounded = opponent_wounds(combat, table, mid, ALLY)
    assert owner_heals(combat, table, mid, ALLY, wounded) == 10


def test_a_non_owner_healing_gains_no_bonus(tmp_path):
    """The bonus belongs to the healer: the Insight never rides another creature's Qi-powered heal."""
    def right_only(doc, aid):
        fields = doc["spheres_and_talents"]
        fields["cultivation_insight_record_ids"] = [i7.FEATURE] if aid == RIGHT else []
        fields["learned_talent_record_ids"] = []
    combat, table, mid = service_fight(tmp_path, [], cl=15, sheet_edit=right_only, prepare_sphere="tianxia.sphere.qiweaving",
                                       prepare=[HEAL], cause=[WOUND], ally=True,
                                       cause_target="ANY_CREATURE", prepare_target="ANY_CREATURE")
    engine = reload(combat, mid)
    pb = engine.state.actors[LEFT].proficiency_bonus
    assert i7.row_of(engine, LEFT, i7.BLOCK, "healing_bonus") is None
    # LEFT is the acting Qi-powered healer but holds no Insight, so LEFT's heal is the printed 10.
    wounded = opponent_wounds(combat, table, mid, ALLY)
    assert owner_heals(combat, table, mid, ALLY, wounded) == 10
    assert pb > 0


def test_a_character_without_the_insight_keeps_the_printed_healing(tmp_path):
    combat, table, mid = service_fight(tmp_path, [], prepare=[HEAL], cause=[WOUND], ally=True,
                                       cause_target="ANY_CREATURE", prepare_target="ANY_CREATURE")
    engine = reload(combat, mid)
    assert i7.row_of(engine, LEFT, i7.BLOCK, "healing_bonus") is None
    wounded = opponent_wounds(combat, table, mid, ALLY)
    assert owner_heals(combat, table, mid, ALLY, wounded) == 10


def test_a_full_health_recipient_gains_temporary_hit_points_instead(tmp_path):
    combat, table, mid = fight(tmp_path, prepare=[HEAL], cause=[WOUND], ally=True)
    engine = reload(combat, mid)
    pb = engine.state.actors[LEFT].proficiency_bonus
    full = engine.state.actors[ALLY].maximum_hp
    # Heal an ally that is already at full health: no wound is needed for the fallback.
    turn(table, mid, LEFT)
    resolve(lambda a: act(table, mid, "Prepare", a, target_id=ALLY))
    ally = reload(combat, mid).state.actors[ALLY]
    assert ally.current_hp == full  # the increase never overflows past full health
    assert ally.temporary_hp == pb


def test_a_recipient_reaching_full_health_gains_temporary_hit_points(tmp_path):
    """"If the target is already at maximum Hit Points after the healing": wounded to full is the fallback."""
    combat, table, mid = fight(tmp_path, prepare=[HEAL], cause=[NEAR_FULL], ally=True)
    engine = reload(combat, mid)
    pb = engine.state.actors[LEFT].proficiency_bonus
    ally = reload(combat, mid).state.actors[ALLY]
    # Wound the ally by exactly one printed heal (10) plus the Proficiency Bonus, so this activation's
    # increased healing lands it on maximum Hit Points.
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, "Cause", a, target_id=ALLY))
    wounded = reload(combat, mid).state.actors[ALLY].current_hp
    assert wounded == ally.maximum_hp - 10 - pb, wounded
    gained = owner_heals(combat, table, mid, ALLY, wounded)
    landed = reload(combat, mid).state.actors[ALLY]
    assert landed.current_hp == ally.maximum_hp  # the increase never overflows past full health
    assert gained == 10 + pb
    # The printed fallback is resolved after the healing, so the recipient at maximum gains Temporary HP.
    assert landed.temporary_hp == pb, (landed.temporary_hp, pb)


def test_cl12_doubles_the_bonus_for_a_chosen_target_at_zero_hit_points(tmp_path):
    combat, table, mid = fight(tmp_path, cl=15, prepare=[HEAL], cause=[LETHAL], ally=True)
    engine = reload(combat, mid)
    pb = engine.state.actors[LEFT].proficiency_bonus
    assert opponent_wounds(combat, table, mid, ALLY) == 0
    turn(table, mid, LEFT)
    resolve(lambda a: act(table, mid, "Prepare", a, target_id=ALLY))
    engine = reload(combat, mid)
    assert engine.state.actors[ALLY].current_hp == 10 + 2 * pb
    # A target brought back from 0 is below full, so the Temporary HP fallback does not apply.
    assert engine.state.actors[ALLY].temporary_hp == 0


def test_a_manual_owner_may_decline_and_keep_the_allowance(tmp_path):
    """Declining the printed choice spends nothing: a later activation still has it."""
    combat, table, mid = fight(tmp_path, prepare=[HEAL], cause=[WOUND], ally=True)
    engine = reload(combat, mid)
    pb = engine.state.actors[LEFT].proficiency_bonus
    wounded = opponent_wounds(combat, table, mid, ALLY)
    assert owner_heals(combat, table, mid, ALLY, wounded, picks={CHOICE: []}) == 10


def test_a_manual_owner_may_choose_an_enemy_recipient(tmp_path):
    """The printed text says "choose one recipient" with no side restriction; a player may choose an enemy."""
    combat, table, mid = fight(tmp_path, prepare=[HEAL], cause=[WOUND])
    engine = reload(combat, mid)
    pb = engine.state.actors[LEFT].proficiency_bonus
    wounded = opponent_wounds(combat, table, mid, RIGHT)
    assert owner_heals(combat, table, mid, RIGHT, wounded, picks={CHOICE: [RIGHT]}) == 10 + pb


def test_a_manual_owner_can_choose_a_later_recipient_in_an_area_heal(tmp_path):
    """The activation-wide choice follows its recipient, not the first subject processed by an area effect."""
    area_heal = {"effects": [{"type": "healing", "applies_to": "allies_in_area", "flat": 10}],
                 "target_kind": "ANY_CREATURE", "sphere": "tianxia.sphere.qiweaving",
                 "area": {"shape": "sphere", "size_ft": 10}}
    combat, table, mid = fight(tmp_path, ally=True, extra_witness=True, witness_team="team:factory",
                               witness_position={"x": 4, "y": 5},
                               extra_actions=[("Area Heal", area_heal)])
    pb = reload(combat, mid).state.actors[LEFT].proficiency_bonus
    turn(table, mid, LEFT)
    result, prompts = resolve(lambda answers: act(table, mid, "Area Heal", answers, target_id=RIGHT), {CHOICE: [ALLY]})
    assert result["status"] == "COMMITTED", result
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == CHOICE)
    assert {option["id"] for option in prompt["choice"]["options"]} == {
        LEFT, ALLY, "actor:factory.auto111-witness"}
    landed = reload(combat, mid).state.actors
    assert landed[ALLY].temporary_hp == pb
    assert landed[LEFT].temporary_hp == 0


def test_later_wounded_area_recipient_gets_the_bonus_once_and_prompt_names_action(tmp_path):
    """A selected later target receives HP; the earlier target gets only the printed heal."""
    area_heal = {"effects": [{"type": "healing", "applies_to": "allies_in_area", "flat": 10}],
                 "target_kind": "SELF", "sphere": "tianxia.sphere.qiweaving",
                 "area": {"shape": "sphere", "size_ft": 10, "centered_on_self": True}}
    chosen = LEFT
    combat, table, mid = fight(tmp_path, cause=[WOUND], ally=True,
                               extra_witness=True, witness_team="team:factory",
                               witness_position={"x": 2, "y": 5},
                               extra_actions=[("Area Mend", area_heal)])
    pb = reload(combat, mid).state.actors[LEFT].proficiency_bonus
    turn(table, mid, RIGHT)
    resolve(lambda a: act(table, mid, "Cause", a, target_id=chosen))
    wounded = reload(combat, mid).state.actors[chosen].current_hp
    turn(table, mid, LEFT)
    result, _ = resolve(lambda answers: act(table, mid, "Area Mend", answers), {CHOICE: [chosen]})
    assert result["status"] == "COMMITTED", result
    landed = reload(combat, mid).state.actors
    assert landed[chosen].current_hp == min(landed[chosen].maximum_hp, wounded + 10 + pb)
    assert landed[ALLY].temporary_hp == 0


def test_choice_prompt_names_the_healing_action_and_explains_alternatives(tmp_path):
    area_heal = {"effects": [{"type": "healing", "applies_to": "allies_in_area", "flat": 10}],
                 "target_kind": "SELF", "sphere": "tianxia.sphere.qiweaving",
                 "area": {"shape": "sphere", "size_ft": 10, "centered_on_self": True}}
    combat, table, mid = fight(tmp_path, ally=True, extra_actions=[("Area Mend", area_heal)])
    turn(table, mid, LEFT)
    result, prompts = resolve(lambda answers: act(table, mid, "Area Mend", answers), {CHOICE: [LEFT]})
    assert result["status"] == "COMMITTED", result
    prompt = next(p for p in prompts if p["context"]["reaction_source_id"] == CHOICE)
    assert prompt["action"] == "Area Mend"
    assert "during Area Mend" in prompt["moment"]
    assert "full health" in prompt["moment"] and "twice your Proficiency Bonus" in prompt["moment"]


def test_explicit_qi_resource_cost_qualifies_without_qiweaving_sphere(tmp_path):
    """Feature provenance can identify Qi power from its actual cost when sphere_id is null."""
    combat, table, mid = fight(tmp_path, prepare=[HEAL], cause=[WOUND], ally=True, sphere=None,
                               prepare_costs=[("resource:core.qi", 1)])
    engine = reload(combat, mid)
    pb = engine.state.actors[LEFT].proficiency_bonus
    wounded = opponent_wounds(combat, table, mid, ALLY)
    assert owner_heals(combat, table, mid, ALLY, wounded) == 10 + pb


def test_heaven_returning_nine_needles_real_qi_cost_triggers_the_insight(tmp_path):
    """The actual sphere-less subpath feature carries its printed 8 Qi cost to the healing rider."""
    feature = "tianxia.subpath.qi.meridian_physician.feature.heaven_returning_nine_needles"

    def add_insight_and_feature(doc, aid):
        if aid != LEFT:
            return
        fields = doc["spheres_and_talents"]
        fields["cultivation_insight_record_ids"] = [i7.FEATURE]
        fields["learned_talent_record_ids"] = []
        doc["path_and_subpath"] = {"path_feature_record_ids": [feature]}

    combat, table, mid = service_fight(tmp_path, [], cl=18, sheet_edit=add_insight_and_feature,
                                       cause=[WOUND], cause_target="ANY_CREATURE", ally=True)
    engine = reload(combat, mid)
    needle = next(action for action in engine.action_catalog.values()
                  if action.owner_id == LEFT and "Heaven-Returning Nine Needles" in action.display_name)
    assert ("resource:core.qi", 8) in needle.costs
    pb = engine.state.actors[LEFT].proficiency_bonus
    assert opponent_wounds(combat, table, mid, ALLY) < engine.state.actors[ALLY].maximum_hp
    turn(table, mid, LEFT)
    result, _ = resolve(lambda answers: act(table, mid, needle.display_name, answers, target_id=ALLY),
                        {CHOICE: [ALLY]})
    assert result["status"] == "COMMITTED", result
    healed = reload(combat, mid).state.actors[ALLY]
    assert healed.current_hp == healed.maximum_hp
    assert healed.temporary_hp == pb

DENY = {'type': 'condition', 'condition': 'restorative_denial_probe', 'applies_to': 'target', 'condition_data': {'rule': {'healing_denied': True}}, 'expires_on': 'UNTIL_REMOVED'}
# Ordinary healing never reaches a dead creature (only a soul-return talent does), so the probe here is the
# engine's own lingering-soul condition rather than 0 Hit Points: a creature at 0 Hit Points is still dying
# and remains a legal recipient (see the dying-enemy case below).
DEAD = {'type': 'condition', 'condition': 'soul_lingering', 'applies_to': 'target', 'expires_on': 'UNTIL_REMOVED'}


def test_a_dead_later_area_recipient_is_filtered_from_the_menu(tmp_path):
    """The dead-recipient exclusion the denial filter shares: a lingering soul is never offered."""
    area_heal = {"effects": [{"type": "healing", "applies_to": "allies_in_area", "flat": 10}],
                 "target_kind": "SELF", "sphere": "tianxia.sphere.qiweaving",
                 "area": {"shape": "sphere", "size_ft": 10, "centered_on_self": True}}
    combat, table, mid = fight(tmp_path, cause=[WOUND, DEAD], ally=True,
                               extra_actions=[("Area Heal", area_heal)])
    wounded = opponent_wounds(combat, table, mid, ALLY)
    engine = reload(combat, mid)
    assert life_state.is_dead(engine.state.actors[ALLY]), "fixture must leave a lingering soul, not a dying creature"
    turn(table, mid, LEFT)
    result, prompts = resolve(lambda a: act(table, mid, "Area Heal", a), {CHOICE: [LEFT]})
    assert result["status"] == "COMMITTED", result
    offered = [o["id"] for p in prompts for o in (p.get("choice") or {}).get("options", [])]
    assert ALLY not in offered
    assert LEFT in offered
    engine = reload(combat, mid)
    assert engine.state.actors[ALLY].current_hp == wounded
    assert engine.state.actors[LEFT].turn_flags.get(i7.USED) == 1
    assert engine.state.actors[LEFT].temporary_hp == engine.state.actors[LEFT].proficiency_bonus


def test_a_healing_prohibited_later_area_recipient_is_filtered_and_allowance_is_spent(tmp_path):
    """An earlier eligible subject must not let a later prohibited creature enter the menu."""
    area_heal = {"effects": [{"type": "healing", "applies_to": "allies_in_area", "flat": 10}],
                 "target_kind": "SELF", "sphere": "tianxia.sphere.qiweaving",
                 "area": {"shape": "sphere", "size_ft": 10, "centered_on_self": True}}
    combat, table, mid = fight(tmp_path, cause=[WOUND, DENY], ally=True,
                               extra_actions=[("Area Heal", area_heal)])
    wounded = opponent_wounds(combat, table, mid, ALLY)
    engine = reload(combat, mid)
    assert any(row.get("healing_denied") for row in te.condition_rules(engine.state.actors[ALLY]))
    turn(table, mid, LEFT)
    result, prompts = resolve(lambda a: act(table, mid, "Area Heal", a), {CHOICE: [LEFT]})
    assert result["status"] == "COMMITTED", result
    offered = [o["id"] for p in prompts for o in (p.get("choice") or {}).get("options", [])]
    assert ALLY not in offered
    assert LEFT in offered
    engine = reload(combat, mid)
    assert engine.state.actors[ALLY].current_hp == wounded
    assert engine.state.actors[LEFT].turn_flags.get(i7.USED) == 1
    assert engine.state.actors[LEFT].temporary_hp == engine.state.actors[LEFT].proficiency_bonus


def test_a_full_health_fallback_grants_proficiency_bonus_not_the_cl12_double(tmp_path):
    """A CL12+ heal from 0 to full uses the ordinary PB Temporary HP fallback."""
    max_heal = {"type": "healing", "applies_to": "target", "flat": 1000}
    combat, table, mid = fight(tmp_path, cl=12, prepare=[max_heal], cause=[LETHAL], ally=True)
    engine = reload(combat, mid)
    pb = engine.state.actors[LEFT].proficiency_bonus
    assert opponent_wounds(combat, table, mid, ALLY) == 0
    healed = owner_heals(combat, table, mid, ALLY, 0)
    engine = reload(combat, mid)
    assert engine.state.actors[ALLY].current_hp == engine.state.actors[ALLY].maximum_hp
    assert engine.state.actors[ALLY].temporary_hp == pb


def test_declining_then_choosing_in_the_same_turn_keeps_the_allowance(tmp_path):
    again = {"effects": [HEAL], "target_kind": "ANY_CREATURE", "sphere": "tianxia.sphere.qiweaving"}
    combat, table, mid = fight(tmp_path, prepare=[HEAL], cause=[WOUND], ally=True,
                               extra_actions=[("Again", again)])
    pb = reload(combat, mid).state.actors[LEFT].proficiency_bonus
    wounded = opponent_wounds(combat, table, mid, ALLY)
    turn(table, mid, LEFT)
    resolve(lambda a: act(table, mid, "Prepare", a, target_id=ALLY), {CHOICE: []})
    after_decline = reload(combat, mid)
    assert after_decline.state.actors[LEFT].turn_flags.get(i7.USED) is None
    hp_after_decline = after_decline.state.actors[ALLY].current_hp
    assert hp_after_decline == wounded + 10
    resolve(lambda a: act(table, mid, "Again", a, target_id=ALLY), {CHOICE: [ALLY]})
    after_choice = reload(combat, mid)
    assert after_choice.state.actors[ALLY].current_hp == hp_after_decline + 10 + pb
    assert after_choice.state.actors[LEFT].turn_flags.get(i7.USED) == 1


def test_a_manual_owner_may_choose_a_dying_enemy_recipient(tmp_path):
    """The printed text permits any recipient; a dying enemy is a legal manual choice, which takes the CL12 double at 0 HP."""
    combat, table, mid = fight(tmp_path, cl=12, prepare=[HEAL], cause=[LETHAL])
    engine = reload(combat, mid)
    pb = engine.state.actors[LEFT].proficiency_bonus
    assert opponent_wounds(combat, table, mid, RIGHT) == 0
    turn(table, mid, LEFT)
    resolve(lambda a: act(table, mid, "Prepare", a, target_id=RIGHT), {CHOICE: [RIGHT]})
    engine = reload(combat, mid)
    assert engine.state.actors[RIGHT].current_hp == 10 + 2 * pb
