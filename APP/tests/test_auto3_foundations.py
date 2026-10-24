"""Foundation automation lane AUTO3: the printed Path/Foundation features that reached the most fielded fighters.

Scope: Foundation features (Path, Subpath, Tradition and Foundation features -- the typed mechanics with no Sphere,
the "?" row of docs/plans/TYPED_MECHANICS_COVERAGE_R1.md).

Choice tests execute compiled actions in the engine. Scaling, resistance, damage-soak
and potency tests inspect compiled fields only; service persistence is covered separately
in test_sph_foundations_r1.py.
"""

from __future__ import annotations

from pathlib import Path

from combat.gate2_runtime_content import AN
from combat.gate4_controller import LocalDeterministicController
from combat.gate4_context import build_reaction_context
from combat.gate4_models import ReactionDecision
from combat.gate4_policy import PolicyLibrary

from tests.h1_support import ME, duel, give, script, use

ROOT = Path(__file__).resolve().parents[1]

TEMPERED = "tianxia.path.body_refining.feature.tempered_response"
CULTIVATED = "tianxia.path.qi_cultivation.feature.cultivated_response"
BLAST = "Scouring Destructive Blast"  # the sparring foe's printed DEX saving throw, DC 14

#: the printed Discipline -> saving throw, in the owner's own words, for both printed Defensive Disciplines.
TEMPERED_FRAMES = [("Rooted Frame", "STR"), ("Flowing Frame", "DEX"), ("Enduring Frame", "CON")]
CULTIVATED_FRAMES = [("Reflexive Circulation", "DEX"), ("Calculated Circulation", "INT"),
                     ("Imperious Circulation", "CHA")]


def _table(feature: str, *, primary="Stamina"):
    """ME owns ``feature`` (the Defensive Discipline); the printed sparring foe stands next to ME and uses its
    printed Dexterity save-forcing attack. ``answer`` is the printed Discipline the fighter picks, or None to let
    the local AI controller choose for itself."""
    engine = duel([feature], primary=primary, cl=10, seed="AUTO3")
    give(engine, ME, **{("stamina" if primary == "Stamina" else "qi"): 10})
    policies = PolicyLibrary(ROOT)
    controller = LocalDeterministicController()

    def react(request):
        policy, _ = policies.for_actor(request["reactor_id"])
        choice = controller.choose_reaction(build_reaction_context(engine, policy, request))
        return choice.decision, choice.record.model_dump(mode="json")

    engine.set_reaction_provider(react)
    foe = engine.state.actors[AN]
    engine.state.current_slot_index = engine.state.initiative_order.index(AN)
    engine.state.current_actor_id = AN
    engine._system_start_turn()
    foe.action_available = True
    return engine, []


def _blast(engine, *, attack=20, face=10):
    """The foe attacks ME with its printed save-forcing attack: ME's Dexterity save is 10 + 2 = 12 against DC 14,
    so the printed "add your Proficiency Bonus, turning the failure into a success" is exactly what decides it."""
    script(engine, [attack] + [face] * 10)
    return use(engine, BLAST, target=ME, actor_id=AN)


def _saves(events):
    return [event.payload for event in events if event.event_type == "SAVE_ROLLED"]


def test_a_body_refiner_keeps_every_printed_defensive_discipline_on_their_row():
    """feature_blocks.json narrowed a choose_one save_rescue row to the weakest listed save at compile time, which
    decided the fighter's own printed choice for them. Every printed option now stays on the row."""
    engine, _asked = _table(TEMPERED)
    row = next(row for row in engine.typed_reaction_rows[ME] if row.get("feature_id") == TEMPERED)
    assert row["block"] == "save_rescue" and row["choose_one"] is True
    assert sorted(row["choices"]) == sorted(code for _name, code in TEMPERED_FRAMES)


# --------------------------------------------------------------------------- retained rider text and compiled fields
# The table used to hand the owner each of these printed lines as "not applied automatically" (factory_compiler._gm_lines
# -> combat/decision_text.py "Some printed effects are recorded for the GM"). Compiled-field checks below are not runtime proof.
TEMPERED_CULTIVATED_GM_LINES_BEFORE = 12  # each feature surfaced twelve of them at the table
BODY_TEMPERING, EXTRA_ATTACK, STAMINA_GUARD = (
    "tianxia.path.body_refining.feature.body_tempering",
    "tianxia.path.body_refining.feature.extra_attack",
    "tianxia.path.body_refining.feature.stamina_guard",
)
NASCENT_SOUL = "tianxia.path.qi_cultivation.feature.nascent_soul"
POTENCY = "tianxia.path.qi_cultivation.feature.qi_technique_potency"


def _mechanic(feature: str) -> dict:
    from combat.typed_numbers import authority_mechanics

    return authority_mechanics()[feature]


def _gm_lines(feature: str) -> list[str]:
    """Exactly the lines the table would show the owner for this feature."""
    row = _mechanic(feature)
    return _gm_lines_of(row)


def _gm_lines_of(row: dict) -> list[str]:
    from combat.factory_compiler import _gm_lines as shown

    return shown(row.get("riders"), row, row.get("effects") or [])


def test_the_table_no_longer_asks_the_owner_to_adjudicate_what_it_already_does():
    before = {"tempered_response": TEMPERED_CULTIVATED_GM_LINES_BEFORE,
              "cultivated_response": TEMPERED_CULTIVATED_GM_LINES_BEFORE,
              "body_tempering": 3, "extra_attack": 2, "stamina_guard": 6,
              "nascent_soul": 5, "qi_technique_potency": 3}
    now = {key.split(".")[-1]: len(_gm_lines(key)) for key in
           (TEMPERED, CULTIVATED, BODY_TEMPERING, EXTRA_ATTACK, STAMINA_GUARD, NASCENT_SOUL, POTENCY)}
    # Unproved execution claims and the proficiency restriction remain visible.
    assert now == {"tempered_response": 2, "cultivated_response": 1, "body_tempering": 3, "extra_attack": 2,
                   "stamina_guard": 6, "nascent_soul": 5, "qi_technique_potency": 2}


def test_extra_attack_scales_by_cultivation_level_as_printed():
    """"This increases to three attacks at CL11 and four attacks at CL17" is the block's own numbers_by_cl."""
    from tests.h1_support import bundle

    counts = {}
    for cl in (5, 11, 17):
        compiled = bundle([EXTRA_ATTACK], actor_id=ME, cl=cl)
        counts[cl] = next(row["attacks"] for row in compiled["typed_passives"] if row.get("block") == "extra_attack")
    assert counts == {5: 2, 11: 3, 17: 4}


def test_stamina_guard_reduces_by_a_ten_sided_die_for_each_point_up_to_the_proficiency_bonus():
    """"spend up to your Proficiency Bonus in Stamina ... Reduce the triggering damage by 1d10 per Stamina spent"."""
    from tests.h1_support import bundle

    compiled = bundle([STAMINA_GUARD], actor_id=ME, cl=10)
    row = next(row for row in compiled["typed_reactions"] if row.get("feature_id") == STAMINA_GUARD)
    assert row["block"] == "damage_soak"
    assert row["max_spend"] == 4 and row["die"] == 10  # the printed Proficiency Bonus and 1d10
    assert row["resource_id"] == "resource:core.stamina"


def test_body_tempering_resists_only_nonmagical_bludgeoning_piercing_and_slashing():
    """The compiled mundane_only flag expresses the restriction; its rider stays until runtime proof is supplied."""
    from tests.h1_support import bundle

    row = next(row for row in bundle([BODY_TEMPERING], actor_id=ME, cl=10)["typed_passives"]
               if row.get("block") == "resistance")
    assert sorted(row["damage_types"]) == ["BLUDGEONING", "PIERCING", "SLASHING"]
    assert row["mundane_only"] is True


def test_qi_technique_potency_adds_the_key_ability_modifier_to_a_qi_paid_damage_roll():
    from tests.h1_support import bundle

    row = next(row for row in bundle([POTENCY], actor_id=ME, cl=10)["typed_passives"]
               if row.get("block") == "technique_potency")
    assert row["bonus"] == "key_mod" and row["resource_id"] == "resource:core.qi"


def test_a_kept_gm_line_is_written_for_a_player_who_knows_only_basic_dnd():
    """Checklist 13: what is left must not carry internal ids, file names or "not automated"."""
    import re

    jargon = re.compile(r"not automated|combat/ext|combat/|typed_|gate[2345]|feature_blocks|"
                        r"the GM's|coordinator audit|\bGM\b(?!\s*(?:'s)?\s*(?:call|resolves))", re.I)
    for key in (TEMPERED, CULTIVATED, BODY_TEMPERING, EXTRA_ATTACK, STAMINA_GUARD, NASCENT_SOUL, POTENCY):
        for line in _gm_lines(key):
            assert not jargon.search(line), f"{key}: {line}"
