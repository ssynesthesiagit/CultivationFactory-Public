"""Whole-clause regressions for the base row SABERS_BASE_SABER_LINE_METHOD (MGR-T14-ling-base-saber-method-1).

Printed rules (authority riders, rules_text sha256 4e726f2f...): Passive / Self / Cost None; "Choose one qualifying
saber-profile weapon ..."; "You gain proficiency with that weapon if you do not already have it."; "You may use
Sabers talents with qualifying saber-profile weapons. If a weapon is ambiguous, the GM decides ...".

Producers under test (all pre-existing and generic -- this lane only verifies them):
  acquisition      combat/table_advance.apply learns the sphere and grants the row as an automatic component.
  build grant      combat/rules/weapon_specials.json proficiency.grants[row] {group: "saber", choose: 1} read by
                    combat/factory_compiler._weapon_proficiency: one carried, not-already-proficient saber-profile
                    weapon gains the proficiency bonus (the sheet does not record the pick, so it is the first
                    qualifying carried weapon, treasure first -- documented in weapon_specials.json's own note).
  talent use       combat/ext/wenxue_sabers.py attach_saber_weapon delivers a Sabers talent with the actor's own
                    saber-profile weapon action; combat/ext/sabers_riders.py saber_bound_reach seals one selectable
                    expression per qualifying carried saber (the player picks the expression; the AI picks from its
                    own candidates); combat/ext/weapon_required.py withholds the talent entirely while the fighter
                    carries no qualifying saber-profile weapon.
  GM ambiguity     the three printed riders stay in authority/typed_mechanics/player_text.json (sheet/tooltips) and
                    the saber-profile membership itself is the owner-editable groups list in weapon_specials.json.

Every test here fails if its producer stops delivering: no test injects metadata into the compiled bundle.
"""

import json
from pathlib import Path

from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN
from combat.gate2_runtime_models import ActionIntent
from combat.gate4_engine import Gate4ControllerEngine

ROOT = Path(__file__).resolve().parents[1]
ME = "actor:factory.mgr_t14_saber_method"
MECH = "SABERS_BASE_SABER_LINE_METHOD"
SPHERE = "tianxia.sphere.sabers"
DAO = "tianxia.mortal.weapon.dao"
DUAN = "tianxia.mortal.weapon.duan_dao"
QIANG = "tianxia.mortal.weapon.qiang"

BASE_SHEET = {
    "identity": {"proficiency_bonus": 4, "cultivation_level": 10, "path": "Spirit Awakening", "key_ability": "WIS"},
    "ability_scores_and_statistics": {
        "abilities": [{"ability": a, "score": 14, "modifier": 2} for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")],
        "primary_resource": {"name": "Resonance", "maximum": 30}, "armor_class": {"base_value": 14},
        "hit_points": {"maximum": 60}, "speed": {"walking_ft": 30},
        "technique_save_dc": 16, "technique_attack_bonus": 8,
    },
}


def _bundle(items, *, owned=True, talents=(), paths=(), wielded=False):
    kit = [{"starting_kit": {"items": [{"item_id": item, **({"wielded": True} if wielded else {})} for item in items]}}]
    sheet = {**BASE_SHEET, "equipment": kit,
             "path_and_subpath": {"path_record_ids": list(paths), "path_feature_record_ids": []},
             "spheres_and_talents": {"sphere_record_ids": [SPHERE],
                                     "automatic_sphere_component_record_ids": [MECH] if owned else [],
                                     "learned_talent_record_ids": list(talents)}}
    return compile_character(sheet, actor_id=ME)


def _bonus(bundle, short):
    for row in bundle["action_catalog"]:
        if ".weapon." in row["source_definition_id"] and row["source_definition_id"].endswith("." + short):
            return row["parameters"]["typed"]["numbers"]["attack_bonus"]
    raise AssertionError(f"no weapon action for {short}")


def _engine(bundle, foe_at=(4, 6)):
    engine = Gate4ControllerEngine(ROOT, match_seed="MGR_T14_SABER", typed_bundles=(bundle,),
                                   roster_setup={"primary_actor_ids": [ME, AN],
                                                 "team_by_actor": {ME: "team:a", AN: "team:b"},
                                                 "starting_positions": {ME: {"x": 3, "y": 6},
                                                                        AN: {"x": foe_at[0], "y": foe_at[1]}}})
    engine.state.current_slot_index = engine.state.actors and engine.state.initiative_order.index(ME)
    engine.state.current_actor_id = ME
    engine._system_start_turn()
    foe = engine.state.actors[AN]
    foe.maximum_hp = foe.current_hp = 2000
    foe.armor_class = -50
    return engine


def _cast(engine, name):
    candidate = next(c for c in engine.legal_candidates() if c.display_name == name)
    engine.execute_intent(ActionIntent(intent_id=f"i{name}", decision_id=candidate.decision_id,
                                       candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                                       actor_id=ME, target_ids=candidate.target_ids or (AN,)))
    return candidate


def _damage_rolls(engine):
    return [r.expression.removesuffix("+0") for r in engine.rolls if r.reason.startswith("DAMAGE:")]


def test_acquisition_grants_the_row_when_the_sphere_is_learned():
    """The real source acquisition path: learning Sabers grants the row, before any compile."""
    from combat import table_advance
    sheet = {"spheres_and_talents": {"sphere_record_ids": [], "automatic_sphere_component_record_ids": [],
                                     "learned_talent_record_ids": []}}
    block = table_advance.apply(sheet, {"spheres": [{"id": SPHERE}], "talents": [], "forged": [], "manuals": []})
    got = block["spheres_and_talents"]["automatic_sphere_component_record_ids"]
    assert SPHERE in block["spheres_and_talents"]["sphere_record_ids"] and MECH in got


def test_choose_grants_proficiency_to_exactly_one_carried_saber():
    """"Choose one qualifying saber-profile weapon": with two carried sabers exactly one gains the PB."""
    both = _bundle([DAO, DUAN])
    bonuses = {_bonus(both, "dao"), _bonus(both, "duan_dao")}
    assert len(bonuses) == 2, f"choose: 1 must pick exactly one of two carried sabers, got {_bonus(both, 'dao')}/{_bonus(both, 'duan_dao')}"
    assert max(bonuses) - min(bonuses) == 4  # the pick gains PB4; the other keeps STR only


def test_choose_only_applies_when_the_row_is_owned():
    """Wrong-owner control: same sheet, row stripped -> no proficiency pick."""
    assert _bonus(_bundle([DAO, DUAN], owned=False), "dao") == _bonus(_bundle([DUAN, DAO], owned=False), "duan_dao")
    assert _bonus(_bundle([DAO]), "dao") == _bonus(_bundle([DAO], owned=False), "dao") + 4


def test_non_saber_weapons_never_gain_from_the_row():
    """Boundary: a spear-profile weapon is untouched by the Sabers grant."""
    assert _bonus(_bundle([QIANG]), "qiang") == _bonus(_bundle([QIANG], owned=False), "qiang")


def test_choose_skips_a_weapon_the_character_already_has():
    """"if you do not already have it": a Path that trains martial weapons already covers the pick."""
    trained = _bundle([DAO], paths=("tianxia.path.body_refining",))
    untrained = _bundle([DAO], paths=("tianxia.path.body_refining",), owned=False)
    assert _bonus(trained, "dao") == _bonus(untrained, "dao")  # already proficient: the row changes nothing


def test_sabers_talent_delivers_its_weapon_damage_with_the_row_owned():
    """Table level: Forward Cut ("Make one saber attack ... normal weapon damage") delivers the carried dao's dice."""
    engine = _engine(_bundle([DAO], talents=["tianxia.talent.sabers.forward_cut"]))
    _cast(engine, "Forward Cut")
    rolls = _damage_rolls(engine)
    assert rolls and any("d10" in roll for roll in rolls), rolls  # the carried dao's versatile 1d10 weapon damage reached the table


def test_sabers_talent_is_not_offered_without_a_qualifying_saber():
    """Boundary: only a spear carried -> combat/ext/weapon_required.py withholds the talent (it strikes with a
    saber-profile weapon; "is not offered while the fighter has no such weapon"), so no saber weapon damage can fire."""
    engine = _engine(_bundle([QIANG], talents=["tianxia.talent.sabers.forward_cut"]))
    names = [c.display_name for c in engine.legal_candidates()]
    assert "Forward Cut" not in names, names


def test_one_selectable_expression_is_sealed_per_qualifying_saber():
    """"You may use Sabers talents with qualifying saber-profile weapons" (plural): Circle-Cleaving Saber seals one
    player-selectable expression per qualifying carried saber, and withholds the talent when none is carried."""
    # combat/starting_loadout.py draws only the ranked primary unless the sheet asks for both, so the
    # two-saber choice is declared here: this test is about the sealed expressions, not the loadout.
    sealed = _bundle([DAO, DUAN], talents=["tianxia.talent.sabers.circle_cleaving_saber"], wielded=True)
    actions = sealed["action_catalog"]
    base, = [a for a in actions if a["display_name"] == "Circle-Cleaving Saber"]
    alternate, = [a for a in actions
                  if a["source_definition_id"] == base["source_definition_id"] + ".saber_2"]
    dao, = [a for a in actions if a["source_definition_id"].endswith(".weapon.dao")]
    duan, = [a for a in actions if a["source_definition_id"].endswith(".weapon.duan_dao")]
    assert alternate["display_name"] == f"Circle-Cleaving Saber (with {duan['display_name']})"
    for expression, weapon in ((base, dao), (alternate, duan)):
        assert expression["parameters"]["range_from_action"] == weapon["source_definition_id"]
        assert expression["parameters"]["typed"]["saber_weapon_source"] == weapon["source_definition_id"]
        assert expression["parameters"]["typed"]["weapon_source_id"] == weapon["source_definition_id"]

    # Test each weapon with the other stowed: the dao's compiled versatile
    # expression may need the second hand to attack, even though it rests in one.
    # Carrying both weapons does not imply both expressions are simultaneously usable.
    expression_ids = {base["source_definition_id"], alternate["source_definition_id"]}
    for stowed, remaining in ((dao, alternate), (duan, base)):
        engine = _engine(sealed)
        remaining_weapon = duan if remaining is alternate else dao
        for index, weapon in enumerate((stowed, remaining_weapon)):
            stow, = [a for a in engine.action_catalog.values()
                     if a.owner_id == ME
                     and a.parameters.get("equipment_grip", {}).get("weapon") == weapon["source_definition_id"]
                     and a.parameters["equipment_grip"]["held"] == 0]
            candidate = next(c for c in engine.legal_candidates()
                             if c.source_definition_id == stow.source_definition_id)
            engine.execute_intent(ActionIntent(intent_id=f"stow-saber-{index}", decision_id=candidate.decision_id,
                candidate_id=candidate.candidate_id, state_version=candidate.state_version,
                actor_id=ME, target_ids=candidate.target_ids))
            offered = {c.source_definition_id for c in engine.legal_candidates()}
            expected = {remaining["source_definition_id"]} if index == 0 else set()
            assert expression_ids & offered == expected, (expected, expression_ids & offered)
    none = _bundle([QIANG], talents=["tianxia.talent.sabers.circle_cleaving_saber"])
    flagged = [a for a in none["action_catalog"] if (a["parameters"] or {}).get("sabers_requires_weapon")]
    assert flagged, "no qualifying saber -> the talent has no physical expression"
    engine = _engine(none)
    assert not any(c.display_name.startswith("Circle-Cleaving Saber") for c in engine.legal_candidates())


def test_the_full_printed_row_stays_typed_and_reaches_the_player_text():
    """Pin all four printed clauses in both documents, including the remaining riders."""
    from combat.factory_compiler import TYPED_AUTHORITY

    record = json.loads(TYPED_AUTHORITY.read_text(encoding="utf-8"))["mechanics"][MECH]
    assert record["activation"]["economy"] == "passive" and record["header_economy"] is True  # "Passive / Self"
    assert record["range"] == {"kind": "self", "feet": 0}
    assert record["cost"] == []                                                               # "Cost: None"
    assert record["coverage"] == "RIDERS_ONLY" and len(record["riders"]) == 3                  # choice, grant, permission + GM
    specials = json.loads((ROOT / "combat/rules/weapon_specials.json").read_text(encoding="utf-8"))["proficiency"]
    assert specials["grants"][MECH]["group"] == "saber" and specials["grants"][MECH]["choose"] == 1
    assert {"dao", "duan_dao"} <= set(specials["groups"]["saber"])
    rules = json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_text(encoding="utf-8"))
    player = json.loads((ROOT / "authority/typed_mechanics/player_text.json").read_text(encoding="utf-8"))["records"]
    from tests.prose_fingerprints import assert_prose_fingerprint

    assert_prose_fingerprint("printed:" + MECH, rules[MECH])
    assert_prose_fingerprint("player:" + MECH, player[MECH])
    assert_prose_fingerprint("riders:" + MECH, record["riders"])
