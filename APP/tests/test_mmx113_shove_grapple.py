"""MMX113: the 2024 Unarmed Strike options Grapple / Shove -- and the Drunken Style stance row.

Part 1 (HUNT111 #1, reported SEVERE as "Shove and Grapple roll an attack and deal weapon
damage"). Owner text and the compiler's own docstring (factory_compiler._unarmed_options):
"Grapple and Shove replace one attack of the Attack action; the target makes a Strength or
Dexterity save against 8 + Strength + PB." So a fighter with N attacks may still make N - 1
attacks alongside the maneuver -- the maneuver itself makes no attack and no damage. These
tests pin both halves at the table: a one-attack fighter's press is a save and nothing else,
and a fighter with Extra Attack makes exactly the one remaining attack the rules allow, with
the button saying so. Together they fail on a shove that invents an attack and on a "fix"
that strips the attack the rules keep.

Part 2 (HUNT111 #2): TAL_DRUNKEN_STYLE_EMPTY_CUP_STANCE was typed with the opposite of its
printed text -- the parser read "squeezing does not impose Disadvantage" as disadvantage on
your Drunken Style attack rolls, and "creatures Off-Rhythm from you do not gain Advantage" as
that advantage. A defensive stance became a self-inflicted debuff.

MMX113f1 review fixes: the correction must not cost the row its machine-readable
eligibility (Martial Focus, no heavy armor) or its printed standing sentence. Both are
asserted below at the data layer; the standing benefit is deliberately NOT asserted as
running, because the stance is a passive row the compiler skips.
"""
import json
import re
from pathlib import Path

import pytest

from tests.hunt12_support import FOE, ME, candidate, fight, hit_dice, reload, send

ROOT = Path(__file__).resolve().parents[1]
OPTIONS = ("Shove: Prone", "Shove: Push 5 ft", "Grapple")
EXTRA_ATTACK = "tianxia.path.body_refining.feature.extra_attack"
EMPTY_CUP = "TAL_DRUNKEN_STYLE_EMPTY_CUP_STANCE"


def _attack_rows(typed):
    return sum(int(e.get("count") or 1) for e in (typed.get("effects") or [])
               if isinstance(e, dict) and e.get("type") == "attack")


def press(tmp_path, monkeypatch, label, *, mids=(), save_roll=20):
    """One press of ``label`` in a real table fight, with the dice scripted."""
    combat, table, mid = fight(tmp_path, mids=mids)
    hit_dice(monkeypatch, save_roll=save_roll)
    chosen = candidate(combat, mid, lambda c: c.display_name == label and tuple(c.target_ids) == (FOE,))
    before = reload(tmp_path, mid).state.actors[FOE].current_hp
    assert send(combat, table, mid, chosen)["status"] == "COMMITTED"
    engine = reload(tmp_path, mid)
    action = engine.action_catalog[chosen.source_definition_id]
    # The button text the table actually shows. Imported here, not at module scope: importing
    # a plug-in module early registers its button_description hook before combat.ext loads
    # the rest, which changes which description wins for OTHER tests in the same session.
    from combat.tabletop import engine_button_description
    # The save is rolled by the TARGET (that is whose chance it is), so filter saves on the
    # target while attacks and damage are the fighter's own.
    action_events = [e for e in engine.events if e.source_definition_id == chosen.source_definition_id]
    mine = [e for e in action_events if e.actor_id == ME]
    # How many attacks the plain Attack action gives this fighter, best row (the number a
    # Shove or Grapple replaces one of).
    basic = [_attack_rows((a.parameters or {}).get("typed") or {})
             for a in engine.action_catalog.values()
             if a.owner_id == ME and str(a.economy.value if hasattr(a.economy, "value") else a.economy) == "ACTION"
             and ".unarmed." not in a.source_definition_id]
    return {
        "action": action,
        "help": engine_button_description(action.model_dump(mode="json")) or "",
        "declared_attacks": _attack_rows((action.parameters or {}).get("typed") or {}),
        "attack_action_attacks": max(basic, default=1),
        "attacks": [e for e in mine if e.event_type == "ATTACK_ROLLED"],
        "damage": [e for e in mine if e.event_type == "DAMAGE_COMMITTED" and FOE in e.target_ids],
        "saves": [e for e in engine.events if e.event_type == "SAVE_ROLLED"
                  and (e.actor_id == FOE or FOE in e.target_ids)],
        "hp_before": before,
        "hp_after": engine.state.actors[FOE].current_hp,
        "action_available": engine.state.actors[ME].action_available,
        "conditions": sorted(c.condition_id for c in engine.state.actors[FOE].conditions.values()),
    }


# --- part 1: the maneuver is a saving throw, and only the replaced attack goes away -------

@pytest.mark.parametrize("label", OPTIONS)
def test_shove_and_grapple_roll_no_attack_and_deal_no_damage(tmp_path, monkeypatch, label):
    """A one-attack fighter's press is the save and its outcome -- no attack roll, no damage."""
    out = press(tmp_path, monkeypatch, label)
    assert out["saves"], f"{label} never asked the target for a saving throw"
    assert out["attacks"] == [], f"{label} rolled an attack: {[e.payload for e in out['attacks']]}"
    assert out["damage"] == [], f"{label} dealt damage: {[e.payload for e in out['damage']]}"
    assert out["hp_after"] == out["hp_before"], (
        f"{label} moved the target from {out['hp_before']} to {out['hp_after']} hit points")


@pytest.mark.parametrize("label", OPTIONS)
def test_shove_and_grapple_surviving_save_leaves_the_target_alone(tmp_path, monkeypatch, label):
    """A successful save: nothing is applied, and the maneuver still costs the Attack action."""
    out = press(tmp_path, monkeypatch, label, save_roll=20)
    assert out["saves"], f"{label} never asked the target for a saving throw"
    assert not [c for c in out["conditions"] if "prone" in c or "grappled" in c]
    assert out["hp_after"] == out["hp_before"]
    assert out["action_available"] is False, "a successful save must not refund the Attack action after reload"


def test_shove_on_prone_applies_only_the_prone(tmp_path, monkeypatch):
    """The failed save's outcome is the printed one: knocked Prone, nothing else."""
    out = press(tmp_path, monkeypatch, "Shove: Prone", save_roll=1)
    assert "condition:typed.prone" in out["conditions"], out["conditions"]


def test_shove_keeps_exactly_the_attacks_the_rules_allow(tmp_path, monkeypatch):
    """With Extra Attack, a Shove replaces ONE attack: the others are still made.

    This is the attack HUNT111 read as an invented extra. It is the remaining attack of the
    Attack action, so it must stay -- and the button must say the player is making it.
    """
    out = press(tmp_path, monkeypatch, "Shove: Prone", mids=(EXTRA_ATTACK,), save_roll=1)
    allowed = out["attack_action_attacks"] - 1
    assert allowed > 0, "this fighter owns Extra Attack, so the Attack action has attacks to replace"
    assert out["declared_attacks"] == allowed, (
        f"a Shove must replace one attack: the action offers {out['declared_attacks']} of "
        f"{out['attack_action_attacks']}")
    assert len(out["attacks"]) == allowed, (
        f"expected the {allowed} remaining Attack-action attacks, rolled {len(out['attacks'])}: "
        f"{[e.payload for e in out['attacks']]}")
    assert f"{allowed} remaining unarmed attack" in out["help"], out["help"]
    assert "Armor Class" in out["help"], out["help"]


def test_shove_button_says_a_one_attack_fighter_makes_no_attack(tmp_path, monkeypatch):
    """Newcomer-readable disclosure: with nothing left to strike with, say the press is a save."""
    out = press(tmp_path, monkeypatch, "Shove: Prone")
    assert out["attack_action_attacks"] == 1, out["attack_action_attacks"]
    assert out["declared_attacks"] == 0
    assert "remaining unarmed attack" not in out["help"], out["help"]
    assert "save" in out["help"], out["help"]
    assert "DC" in out["help"], out["help"]


# --- part 2: the Drunken Style stance row applies what its printed text negates -----------

def _authority():
    return json.loads((ROOT / "authority/Tianxia_Typed_Mechanics_Authority_R1.json").read_bytes())


def _printed():
    return json.loads((ROOT / "authority/typed_mechanics/rules_text.json").read_bytes())


def test_empty_cup_stance_applies_nothing_its_printed_text_negates():
    """The two negated benefits stay printed rules, not automated penalties."""
    row = _authority()["mechanics"][EMPTY_CUP]
    granted = [e for e in row["effects"] if e.get("type") in ("advantage", "disadvantage")]
    assert granted == [], f"{EMPTY_CUP} still applies {granted}"
    text = " ".join(row["riders"]).lower()
    assert "does not impose disadvantage" in text, row["riders"]
    assert "do not gain advantage" in text, row["riders"]


def test_empty_cup_stance_keeps_its_structured_eligibility_gate():
    """The stance's prerequisite must survive the correction as machine-readable data.

    A review replaces the whole model-v2 activation unless it supplies one of its own
    (build_typed_mechanics_authority.merge), so without an explicit activation the trigger
    silently became null and the only surviving record of "Martial Focus, no heavy armor"
    was prose. A future consumer could then hand out the benefits without either.

    Asserted at both layers: the reviews.json INPUT, so a rebuild cannot quietly drop the
    gate, and the generated authority, so a builder change that ignores it is caught too.
    """
    review = json.loads((ROOT / "authority/typed_mechanics/reviews.json").read_bytes())[EMPTY_CUP]
    for label, activation in (("reviews.json", review.get("activation")),
                              ("generated authority", _authority()["mechanics"][EMPTY_CUP]["activation"])):
        trigger = (activation or {}).get("trigger") or ""
        assert trigger == "While you are holding Martial Focus and not wearing heavy armor", (
            f"{label} changed the printed eligibility gate: {activation!r}")


def test_empty_cup_stance_standing_from_prone_is_typed_data_and_printed_text(tmp_path):
    """Keep the printed five-foot cost and prove standing charges it after reload."""
    row = _authority()["mechanics"][EMPTY_CUP]
    movement = [e for e in row["effects"]
                if e.get("type") == "movement" and e.get("condition") == "prone"]
    assert movement and movement[0].get("distance_ft") == 5, row["effects"]
    # The native stance now charges the printed five feet. Keep the source
    # contract and assert the actual capability, rather than a stale GM rider.
    assert "standing from Prone costs only 5 feet" in _printed()[EMPTY_CUP]
    from combat import posture
    from tests.auto_worker1_support import LEFT, act, fight, reload
    combat, table, mid = fight(tmp_path, [EMPTY_CUP], prepare_target='SELF',
        prepare=[{'type':'condition', 'condition':'prone', 'applies_to':'self', 'duration':'until_removed'}])
    assert act(table, mid, 'Prepare')['status'] == 'COMMITTED'
    engine = reload(combat, mid); actor = engine.state.actors[LEFT]
    assert posture.standing_cost(engine, actor) == 5
    before = actor.movement_remaining_ft
    assert act(table, mid, posture.SOURCE)['status'] == 'COMMITTED'
    actor = reload(combat, mid).state.actors[LEFT]
    assert not posture.prone_conditions(actor) and actor.movement_remaining_ft == before - 5


# A printed benefit the table negates, e.g. "does not impose Disadvantage on ...".
_NEGATED_BENEFIT = re.compile(
    r"\b(?:does not|do not|doesn'?t|don'?t|never|cannot|can'?t)\s+"
    r"(?:impose|imposes|gain|gains|have|has|give|gives|apply|applies|suffer|suffers)?\s*"
    r"(advantage|disadvantage)\b", re.IGNORECASE)

# The same parser defect elsewhere, found by MMX113's scan: each of these still grants the
# benefit its own printed text negates. They are NOT fixed here -- removing a penalty has no
# effect kind in the engine today (combat/attack_modes.py carries no DISADVANTAGE token), so
# each is a lock-round item, and each belongs to a Sphere this lane was not assigned. Listing
# them makes any NEW inversion fail this test, and keeps the backlog in the repo.
KNOWN_NEGATION_BACKLOG = {
    "TAL_DRUNKEN_STYLE_EMPTY_CUP_STANCE",  # fixed by MMX113
    "TAL_DRUNKEN_STYLE_THE_WORLD_SWINGS_WIDE",
    "TAL_DUAL_WIELDING_MIXED_DEFENSE",
    "TAL_SNIPER_FAR_SHOT",
    "TAL_SOUND_TEN_THOUSAND_ECHOES_FIELD",
    "TAL_THE_HIDDEN_EYE_EXPEDITED_CUNNING",
    "TAL_THE_HIDDEN_EYE_WIND_READER",
    "TAL_WEATHER_PRESSURE_CRACKING_SHROUD",
    "tianxia.subpath.qi.blood_moon_execution_saber_cultivator.feature.execution_threshold",
    "tianxia.subpath.qi.hidden_thunder_draw_saber_cultivator.feature.one_breath_duel",
    "tianxia.subpath.qi.star_piercing_greatbow_cultivator.feature.brace_the_heavens",
    "tianxia.subpath.qi.star_piercing_greatbow_cultivator.feature.fortress_piercing_shot",
    "tianxia.subpath.qi.storm_soul_cultivator.feature.lightning_reflexes",
    "tianxia.talent.equipment.breath_aligned_armor",
    "tianxia.talent.formations.harmonized_pulse",
    "tianxia.talent.stars.night_sight_meridian",
}


def test_no_typed_row_applies_an_inverted_advantage_beyond_the_known_backlog():
    authority, printed = _authority(), _printed()
    inverted = set()
    for mid, mechanic in authority["mechanics"].items():
        text = printed.get(mid) or ""
        if not _NEGATED_BENEFIT.search(text):
            continue
        for effect in mechanic.get("effects") or []:
            if isinstance(effect, dict) and effect.get("type") in ("advantage", "disadvantage"):
                inverted.add(mid)
    assert inverted <= KNOWN_NEGATION_BACKLOG, (
        f"new rows apply a benefit their printed text negates: {sorted(inverted - KNOWN_NEGATION_BACKLOG)}")
    assert EMPTY_CUP not in inverted
