"""AUTOREL3f1: Brute's damage-bonus hook must be inert for characters that do not own it.

The reviewed Brute branch added ``combat.ext.rolled_conditions.explicit_ability_bonus`` on the
general ``damage_roll_bonus`` hook. That hook's documented contract passes ``row=None`` for the one
set of dice an ordinary attack sequence shares across its strikes ("effect is None for attack-sequence
dice", combat/ext/__init__.py), but the plug-in called ``row.get`` anyway. Every ordinary attack by a
character WITHOUT Brute therefore raised an AttributeError that was journaled as a ``GM_RIDER`` error
event. The per-fight suppression of that error is transient (``engine._ext_failures_logged``), so a
fight reopened from storage emitted the error a second time; the extra event shifts later candidate
ids and deterministic AI choices, and the reloaded fight diverges from the same fight played straight
through. These are service-level regressions for that defect.
"""
import json

import tests.test_attack_abilities as abilities
from combat.gate5_service import CombatService, FACTORY_ACTOR_PREFIX
from tests.cw2_service_support import seal
from tests.h1_support import ROOT
from tests.test_save_reload_equivalence import _bytes_of, _play
from tests.worker2_support import FOE, candidate, fixture, reload, settle

HOOK = "rolled_conditions.explicit_ability_bonus"

COURT = {"display_name": "Ability court", "width_squares": 10, "height_squares": 10,
         "starts": {"team1": [[3, 4]], "team2": [[4, 4]]}, "walls": []}


def _extension_errors(engine):
    """Journaled plug-in failures, the way a player would see them as a table rider."""
    return [event for event in engine.events
            if event.event_type == "GM_RIDER"
            and HOOK in json.dumps(event.payload or {}, sort_keys=True)]


def _rows(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _rows(child)
    elif isinstance(value, list):
        for child in value:
            yield from _rows(child)


def _rows_of(value):
    return list(_rows(value))


def test_an_ordinary_attack_records_no_extension_error_without_brute(tmp_path):
    """An Iron Fist fighter (no Brute) makes its ordinary typed strikes; none writes a plug-in error."""
    combat, table, match, actor, _foe = abilities.table_fixture(tmp_path, abilities.sheet())
    engine = combat._load_session(match).engine
    strike = next(c for c in engine.legal_candidates()
                  if "Iron Fist" in c.display_name and ".natural." in c.source_definition_id)
    result = abilities.commit_manual_with_iron_fist_choices(table, match, strike, 0)
    assert result["status"] == "COMMITTED", result
    cold = CombatService(ROOT, tmp_path)._load_session(match).engine
    assert not _extension_errors(cold), _extension_errors(cold)
    assert any(e.event_type == "ATTACK_ROLLED" and e.actor_id == actor for e in cold.events)


def _start_iron_fist_court(root):
    """A small all-AI court fight of two Iron Fist fighters, for the reload-equivalence harness.

    Both are glass cannons (AC 1, 8 HP) so the fight settles in a handful of committed steps.
    """
    sheets = {"ability": abilities.sheet(), "foe": abilities.sheet(training=False)}
    for sheet in sheets.values():
        sheet["ability_scores_and_statistics"]["armor_class"]["base_value"] = 1
        sheet["ability_scores_and_statistics"]["hit_points"]["maximum"] = 8
    for name, sheet in sheets.items():
        abilities.install(root, name, sheet)
    combat = CombatService(ROOT, root)
    combat.tabletop_maps.save(COURT)
    actor, foe = FACTORY_ACTOR_PREFIX + "ability", FACTORY_ACTOR_PREFIX + "foe"
    view = combat.create_factory_match(project_ids=["ability"], opponent_actor_ids=[foe],
                                       control_modes={actor: "LOCAL_AUTO", foe: "LOCAL_AUTO"},
                                       arena_id="battlefield:map.ability-court", match_seed="ABILITY-DEX")
    return combat._load_session(view["match_id"]), view["match_id"]


def test_a_typed_fight_reloaded_midway_is_the_same_game(tmp_path):
    """Cut an all-typed-attack fight in half and reopen it: one game, not two."""
    straight = tmp_path / "straight"
    reopened = tmp_path / "reopened"
    straight.mkdir()
    reopened.mkdir()
    arm_a = _play(straight, _start_iron_fist_court)
    arm_b = _play(reopened, _start_iron_fist_court, cut=3)
    assert arm_b["reloaded_at"] == 3
    assert arm_b["steps"] == arm_a["steps"], (arm_a["steps"], arm_b["steps"])
    for label in ("events", "rolls", "state"):
        from tests.replay_assertions import assert_replay_equal
        assert_replay_equal(_bytes_of(arm_a[label]), _bytes_of(arm_b[label]),
                            f"the reopened fight diverged on {label}")


def test_the_brute_owner_still_adds_its_ability_bonus(tmp_path):
    """The inertness fix must not disarm the owner: Brute's marked damage row keeps its STR modifier."""
    def prepare(bundles):
        owner = bundles[0]
        owner["actor_template"].update(strength_score=14, dexterity_score=14)
        for action in owner["action_catalog"]:
            typed = (action.get("parameters") or {}).get("typed") or {}
            if typed.get("source") != "TAL_BRUTE_THUNDEROUS_CLAP":
                continue
            for row in _rows_of(typed["effects"]):
                if row.get("type") == "damage":
                    row["dice"]["modifier"] = 0
                    row["damage_ability"] = "STR"
        seal(owner)
        seal(bundles[2])

    combat, table, mid = fixture(tmp_path, ["TAL_BRUTE_THUNDEROUS_CLAP"], cl=5,
                                 foe_position={"x": 4, "y": 5}, bundle_transform=prepare)
    hp = reload(tmp_path, mid).state.actors[FOE].current_hp
    settle(table, mid, candidate(combat, mid, "Thunderous Clap").candidate_id)
    cold = reload(tmp_path, mid)
    rolls = [r for r in cold.rolls if "DAMAGE" in r.reason and "d8" in r.expression]
    assert rolls, "the Brute owner's attack must roll damage"
    assert rolls[-1].modifier == 2, rolls[-1].modifier
    assert cold.state.actors[FOE].current_hp < hp
