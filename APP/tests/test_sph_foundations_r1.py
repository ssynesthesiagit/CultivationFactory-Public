"""Defensive Discipline ownership and lifetime through real table commits/reloads."""
import pytest

from combat.canonical import canonical_sha256
from combat.gate2_rolls import DeterministicRollAuthority
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, ME, FOE, bundle
from tests.r1i_service_support import force_ai_candidate
from tests.test_auto3_foundations import TEMPERED, CULTIVATED

BLAST = "Scripture Prison"


def fixture(tmp_path, monkeypatch, *, feature=TEMPERED, primary="Stamina"):
    def die(roller, sides):
        counter = roller.counter
        roller.counter += 1
        return min(10, sides), counter

    monkeypatch.setattr(DeterministicRollAuthority, "_die", die)
    defender = bundle([feature], primary=primary)
    defender["actor_template"].update(display_name="Defender", initiative_bonus=-1000, maximum_hp=500)
    defender.pop("bundle_sha256", None)
    defender["bundle_sha256"] = canonical_sha256(defender)
    attacker = bundle(["tianxia.talent.ink.scripture_prison"], actor_id=FOE, dc=14)
    attacker["actor_template"].update(display_name="Ink caster", initiative_bonus=1000, maximum_hp=500)
    attacker.pop("bundle_sha256", None)
    attacker["bundle_sha256"] = canonical_sha256(attacker)
    combat = CombatService(ROOT, tmp_path)
    session = combat.persistence.create_match(match_seed="SPH-foundations-r1", typed_bundles=(defender, attacker),
        roster_setup={"primary_actor_ids": [ME, FOE], "team_by_actor": {ME: "team:a", FOE: "team:b"},
                      "starting_positions": {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}}})
    mid = session.match_id
    combat._read_metadata(mid, session)
    for actor in (ME, FOE):
        combat.set_controller_mode(mid, actor_id=actor, controller_mode="MANUAL")
    table = TabletopService(combat, tmp_path)
    assert table.state(mid)["menu"]["actor_id"] == FOE
    assert not any(row.get("ask") for row in session.engine.typed_reaction_rows[ME])
    return combat, table, mid


def reload(tmp_path, mid):
    combat = CombatService(ROOT, tmp_path)
    session = combat._load_session(mid)
    assert session.mechanical.replay()["status"] == "PASS"
    return combat, TabletopService(combat, tmp_path), session.engine


def act(combat, table, mid, cid, answers=(), *, auto=False):
    if auto:
        return table.auto_step(mid, 0, list(answers))
    menu = table.state(mid)["menu"]
    return table.act(mid, cid, menu["decision_id"], menu["state_version"], 0, list(answers))


# Body Refining's choices and proficiency restriction are now enforced by the table;
# Qi Cultivation's remaining build-pick riders still need to be visible.
def test_additional_discipline_choice_is_described_as_a_build_pick():
    from tests.test_auto3_foundations import _gm_lines, NASCENT_SOUL

    for feature in (TEMPERED, CULTIVATED, NASCENT_SOUL):
        lines = _gm_lines(feature)
        assert not any("not asked for yet" in line or "first time it matters" in line for line in lines)
        if feature != TEMPERED:
            assert any("recorded on your character sheet" in line for line in lines)

    from combat.typed_reactions import rules as block_rules
    block = block_rules()["features"][TEMPERED]
    assert block["choose_one"]
    assert "tianxia.path.body_refining.feature.indomitable_body" in block["pick_sources"]


def test_proficiency_limitation_is_enforced_not_a_gm_rider():
    from combat.typed_reactions import rules as block_rules
    from tests.test_auto3_foundations import _gm_lines

    assert block_rules()["features"][TEMPERED]["unless_proficient"] is True
    assert not any("does not stack" in line and "proficiency" in line for line in _gm_lines(TEMPERED))
