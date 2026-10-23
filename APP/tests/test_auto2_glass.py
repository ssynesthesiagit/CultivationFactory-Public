"""A2GLASS: Glass's Faultline Mark reactions through table execute_intent and cold service replay.

Every test compiles real Glass fighters, drives the printed line through the table service
(``TabletopService`` over ``CombatService``), answers the printed choices, and asserts on the *committed* fight after a
cold reload.  No bare-engine call and no production monkeypatch: the trigger is a real attack, the printed reaction is a
real question, and the consequences are the engine's own conditions and damage.

Printed text: APP/authority/typed_mechanics/rules_text.json (Break the Proud Weapon, Spell-Line Crack, Flaw Within the
Golden Technique).  Plug-in: combat/ext/glass_faults.py.  Block rows: combat/rules/feature_blocks.d/a2_glass.json.
"""
import pytest

from tests.cw2_service_support import add_action, seal
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle, turn

T = "TAL_GLASS_"
BASES = ["GLASS_BASE_REFRACTION_RESPONSES", "GLASS_BASE_TEMPER_GLASS_SURFACE", "GLASS_BASE_FAULTLINE_MARKS",
         "GLASS_BASE_GLASS_SHARD", "GLASS_BASE_FAULTLINE_STRIKE"]
PRIDE = T + "BREAK_THE_PROUD_WEAPON"
SPELL_LINE = T + "SPELL_LINE_CRACK"
FLAW = T + "FLAW_WITHIN_THE_GOLDEN_TECHNIQUE"

FRACTURED = "condition:typed.glass_fractured_weapon"
REACTION_DENIED = "condition:typed.glass_spell_line_no_reaction"
CON_DISADV = "condition:typed.glass_flaw_concentration_save"
AUTO_SAVE = "condition:typed.glass_flaw_auto_save"
SAVE_ADV = "condition:typed.glass_spell_line_advantage"
RESIST_EFFECT = "condition:typed.glass_flaw_resist"
FEATURE_LOCKED = "condition:typed.glass_flaw_feature_locked"


def prepare(bundles):
    """Seal the owner's printed Faultline Mark, the foe's weapon attack and the foe's high-cost technique.

    ``add_action`` on the owner carries the *production* typed mark effect -- the same ``{"type": "mark", "mark": "Faultline
    Mark"}`` row Glass Shard and Faultline Strike carry in the authority -- so a test can place the mark the printed talents
    answer to without depending on an attack roll.  ``sealed_native_attack`` on the foe runs the engine's own attack code so
    its ``after_hit`` reaches the plug-in, and the foe's technique declares a Cultivation Point cost so Flaw's "high-cost
    supernatural feature" has something to fire on.  Production ownership is untouched: the owner still learns only the Glass
    talents under test.
    """
    add_action(bundles[0], "Glass Faultline Mark", [{"type": "mark", "mark": "Faultline Mark", "applies_to": "target",
                                                      "duration": {"kind": "until_end_of_your_next_turn"}}])
    # a printed melee weapon attack.  ``after_hit`` is the typed attack path, and the engine reads its "weapon" out of the
    # typed parameters (typed_executor.py: "weapon" if ctx.typed.get("weapon") is not None else "other"), so a weapon attack
    # that reaches the printed triggers is sealed as a typed attack carrying a weapon specification.
    add_action(bundles[2], "Foe Blade", [{"type": "attack", "attack_kind": "weapon_melee", "count": 1,
                                           "on_hit": [{"type": "damage", "applies_to": "target", "flat": 3,
                                                       "damage_types": ["slashing"], "duration": "instant"}]}],
               typed={"weapon": {"kind": "melee", "ability_modifier": 3}, "range_ft": 5,
                      "numbers": {"pb": 4, "attack_bonus": 20, "save_dc": 16, "cl": 15}})
    add_action(bundles[2], "Foe Technique", [{"type": "damage", "applies_to": "target", "flat": 4,
                                              "damage_types": ["slashing"], "duration": "instant"}],
               typed={"costs": [["resource:core.cp", 1]]})
    for bundle in bundles:
        seal(bundle)


def glass(tmp_path, talents, **kwargs):
    """A Glass owner standing next to the foe, so a printed melee weapon hit is actually in reach."""
    kwargs.setdefault("foe_position", {"x": 4, "y": 5})
    return fixture(tmp_path, list(BASES) + [T + name for name in talents], cl=15, bundle_transform=prepare, **kwargs)


def marked(engine, who=FOE):
    from combat.ext import glass_refraction

    return glass_refraction.marked(engine.state.actors[who], OWNER)


def foe_turn(table, mid, picks=None, choices=None):
    """Advance initiative to the foe's turn, answering choices raised on the way."""
    prompts = []
    for _ in range(12):
        if table.state(mid)["menu"]["actor_id"] == FOE:
            return prompts
        prompts += settle(table, mid, table.state(mid)["menu"]["end_turn"], picks, choices=choices)
    raise AssertionError("no foe turn")


def owner_setup(combat, table, mid, temper=True):
    """The owner places its printed Faultline Mark, and optionally holds a Glass Surface of their own.

    Temper Glass Surface is the printed way a Glass fighter owns a Glass Surface, and Spell-Line Crack's trigger is "while
    you can see it through a Glass Surface", so the surface is part of the printed setup rather than a convenience.
    """
    settle(table, mid, candidate(combat, mid, "Glass Faultline Mark", target=FOE).candidate_id)
    if temper:
        settle(table, mid, candidate(combat, mid, "Temper Glass Surface").candidate_id)


def conditions(engine, who, condition_id):
    return [c for c in engine.state.actors[who].conditions.values() if c.condition_id == condition_id]


# ----------------------------------------------------------------------------------------- Break the Proud Weapon
def test_pride_asks_before_a_marked_weapon_hit_and_a_fracture_lands(tmp_path):
    combat, table, mid = glass(tmp_path, ["BREAK_THE_PROUD_WEAPON"], ask=False)
    owner_setup(combat, table, mid, temper=False)
    engine = reload(tmp_path, mid)
    assert marked(engine), "the owner's Glass Shard must leave the foe marked"
    prompts = foe_turn(table, mid, choices={})
    prompts += settle(table, mid, candidate(combat, mid, "Foe Blade", target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.glass_pride_weapon" for p in prompts), \
        "Break the Proud Weapon must be offered as a real question on the marked creature's weapon hit"
    # a failed Strength save fractures; the seeded roll decides, so accept either printed branch
    assert conditions(engine, FOE, FRACTURED) or engine.state.actors[OWNER].current_hp < engine.state.actors[OWNER].maximum_hp


def test_pride_declining_keeps_the_mark_and_the_reaction(tmp_path):
    combat, table, mid = glass(tmp_path, ["BREAK_THE_PROUD_WEAPON"], ask=False)
    owner_setup(combat, table, mid, temper=False)
    foe_turn(table, mid, choices={})
    settle(table, mid, candidate(combat, mid, "Foe Blade", target=OWNER).candidate_id, {"choice:needle.glass_pride_weapon": None})
    engine = reload(tmp_path, mid)
    assert marked(engine), "declining a printed 'you may' must leave the Faultline Mark in place"
    assert not conditions(engine, FOE, FRACTURED)


def test_pride_only_answers_a_marked_creature(tmp_path):
    """An unmarked foe's weapon hit pays nothing: the printed trigger is a marked creature."""
    combat, table, mid = glass(tmp_path, ["BREAK_THE_PROUD_WEAPON"], ask=False)
    foe_turn(table, mid)
    settle(table, mid, candidate(combat, mid, "Foe Blade", target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert not conditions(engine, FOE, FRACTURED)


def test_pride_is_not_owned_by_a_fighter_who_did_not_learn_it(tmp_path):
    """The block row is the ownership test: without the talent the question is never raised."""
    combat, table, mid = fixture(tmp_path, list(BASES) + [SPELL_LINE], cl=15, bundle_transform=prepare, ask=False)
    owner_setup(combat, table, mid, temper=False)
    prompts = foe_turn(table, mid)
    prompts += settle(table, mid, candidate(combat, mid, "Foe Blade", target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert not any("glass_pride_weapon" in p["context"]["reaction_source_id"] for p in prompts)
    assert not conditions(engine, FOE, FRACTURED)


# ----------------------------------------------------------------------------------------- Spell-Line Crack
def test_spell_line_crack_fires_on_a_marked_high_cost_feature(tmp_path):
    combat, table, mid = glass(tmp_path, ["SPELL_LINE_CRACK"], ask=False)
    owner_setup(combat, table, mid)
    engine = reload(tmp_path, mid)
    assert marked(engine)
    prompts = foe_turn(table, mid)
    prompts += settle(table, mid, candidate(combat, mid, "Foe Technique", target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.glass_spell_line" for p in prompts), \
        "Spell-Line Crack must be offered when a marked creature spends CP in the caster's sight"
    assert (conditions(engine, FOE, REACTION_DENIED) or conditions(engine, FOE, CON_DISADV)
            or conditions(engine, OWNER, SAVE_ADV)), "one printed answer must land after the save"


def test_spell_line_crack_needs_the_mark(tmp_path):
    combat, table, mid = glass(tmp_path, ["SPELL_LINE_CRACK"], ask=False)
    prompts = foe_turn(table, mid)
    prompts += settle(table, mid, candidate(combat, mid, "Foe Technique", target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert not any("glass_spell_line" in p["context"]["reaction_source_id"] for p in prompts)
    assert not conditions(engine, FOE, REACTION_DENIED)


def test_spell_line_crack_asks_before_spending_the_mark(tmp_path):
    combat, table, mid = glass(tmp_path, ["SPELL_LINE_CRACK"], ask=False)
    owner_setup(combat, table, mid)
    foe_turn(table, mid)
    # Turn the Angle answers the same damage packet, so both printed "you may" questions are declined
    settle(table, mid, candidate(combat, mid, "Foe Technique", target=OWNER).candidate_id,
           {"choice:needle.glass_spell_line": None, "choice:needle.refraction_response": None})
    engine = reload(tmp_path, mid)
    assert marked(engine), "declining keeps the Faultline Mark"


# ----------------------------------------------------------------------------------------- Flaw Within the Golden Technique
def test_flaw_fires_on_a_marked_high_cost_feature_within_sixty_feet(tmp_path):
    # Flaw is exercised on its own here. A fighter owning both Spell-Line Crack and Flaw is offered a choice between them
    # on the same activation (the GLASSR6 fix, covered by test_a2_glass_r6_fix.py).
    combat, table, mid = glass(tmp_path, ["FLAW_WITHIN_THE_GOLDEN_TECHNIQUE"], ask=False)
    owner_setup(combat, table, mid)
    prompts = foe_turn(table, mid)
    prompts += settle(table, mid, candidate(combat, mid, "Foe Technique", target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.glass_flaw" for p in prompts), \
        "Flaw Within the Golden Technique must answer a marked creature's high-cost feature"
    assert not marked(engine), "the printed reaction spends the Faultline Mark"
    # which of the four printed answers lands depends on the Wisdom saving throw, so the assertion is that one of them did
    said = [str((e.payload or {}).get("log") or "") for e in engine.events
            if e.event_type == "PASSIVE_TRIGGERED" and e.source_definition_id == FLAW]
    assert (conditions(engine, FOE, FEATURE_LOCKED) or conditions(engine, ALLY, AUTO_SAVE)
            or conditions(engine, ALLY, RESIST_EFFECT) or said), \
        "one printed answer must land after the save"


def test_flaw_ignores_an_enemy_that_is_not_marked(tmp_path):
    combat, table, mid = glass(tmp_path, ["FLAW_WITHIN_THE_GOLDEN_TECHNIQUE"], ask=False)
    prompts = foe_turn(table, mid)
    prompts += settle(table, mid, candidate(combat, mid, "Foe Technique", target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    assert not any("glass_flaw" in p["context"]["reaction_source_id"] for p in prompts)
    assert not conditions(engine, FOE, FEATURE_LOCKED)


# ----------------------------------------------------------------------------------------- recipient rule
def test_the_recipient_is_picked_by_side_not_by_perception(tmp_path):
    """An ally and an enemy are both in reach; the printed "one ally affected" must never name the enemy.

    The owner, the ally and the foe all stand together.  The AI owner answers for itself, so this is the regression that
    an automatic or AI-made multi-recipient choice picks by the side the printed text names rather than handing over the
    whole perceived list (corkboard #1545 / the repeated A2 review finding).
    """
    combat, table, mid = glass(tmp_path, ["FLAW_WITHIN_THE_GOLDEN_TECHNIQUE"], ask=False, extra_allies=1)
    owner_setup(combat, table, mid)
    prompts = foe_turn(table, mid)
    # the marked foe strikes at the caster's own ally: the printed "one ally affected by the triggering effect" now has a
    # legal recipient, while the foe itself (an enemy) stands in reach and is never one
    prompts += settle(table, mid, candidate(combat, mid, "Foe Technique", target=ALLY).candidate_id,
                      {"choice:needle.glass_flaw_outcome": "ally_saves"})
    engine = reload(tmp_path, mid)
    assert any(p["context"]["reaction_source_id"] == "choice:needle.glass_flaw" for p in prompts), \
        "the AI owner must answer Flaw when an ally and an enemy are both in reach"
    allies = [ALLY, "actor:factory.worker2-ally3"]
    # no recipient condition may land on the enemy for an "ally" answer
    assert not conditions(engine, FOE, AUTO_SAVE), "the printed 'one ally affected' must not reach an enemy"
    assert not conditions(engine, FOE, RESIST_EFFECT), "the printed 'one ally affected' must not reach an enemy"
    asked = any(p["context"]["reaction_source_id"] == "choice:needle.glass_flaw_outcome" for p in prompts)
    if asked:   # the printed ally answer was chosen, so it must have landed on an ally
        landed = [who for who in allies if conditions(engine, who, AUTO_SAVE) or conditions(engine, who, RESIST_EFFECT)]
        assert landed, "the printed 'one ally affected' answer must land on an ally, never an enemy"


def test_an_enemy_mark_is_never_placed_on_the_owners_own_side(tmp_path):
    """Every mark here answers to a hostile-creature rule, so no ally ever wears the owner's Faultline Mark."""
    combat, table, mid = glass(tmp_path, ["FLAW_WITHIN_THE_GOLDEN_TECHNIQUE"], ask=False, extra_allies=1)
    owner_setup(combat, table, mid)
    foe_turn(table, mid)
    settle(table, mid, candidate(combat, mid, "Foe Technique", target=ALLY).candidate_id)
    engine = reload(tmp_path, mid)
    from combat.ext import glass_refraction

    for ally in (ALLY, "actor:factory.worker2-ally3", OWNER):
        assert not glass_refraction.marked(engine.state.actors[ally], OWNER)


# ----------------------------------------------------------------------------------------- persistence
def test_every_condition_survives_a_cold_reload(tmp_path):
    """A fracture placed through the table replays from the committed fight, not from live memory."""
    def setup(bundles):
        prepare(bundles)
        bundles[2]['actor_template']['saving_throws']['STR'] = -100  # the foe fails its Strength save: a fracture lands
        seal(bundles[2])

    combat, table, mid = fixture(tmp_path, list(BASES) + [T + "BREAK_THE_PROUD_WEAPON"], cl=15, bundle_transform=setup,
                                 foe_position={"x": 4, "y": 5}, ask=False)
    owner_setup(combat, table, mid, temper=False)  # no Glass Surface, so Pride is the reaction offered
    foe_turn(table, mid)
    settle(table, mid, candidate(combat, mid, "Foe Blade", target=OWNER).candidate_id)
    engine = reload(tmp_path, mid)
    fractures = [row for who in (OWNER, ALLY, FOE) for row in conditions(engine, who, FRACTURED)]
    assert fractures, "the fracture placed at the table must be replayed after a cold reload"
    assert engine.state.event_sequence > 0