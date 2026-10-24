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


def test_proficiency_limitation_remains_visible():
    from tests.test_auto3_foundations import _gm_lines

    assert any("does not stack" in line and "proficiency" in line for line in _gm_lines(TEMPERED))


def test_additional_discipline_limitation_remains_visible():
    from tests.test_auto3_foundations import _gm_lines, NASCENT_SOUL

    assert any("not asked for yet" in line for line in _gm_lines(NASCENT_SOUL))


    # Scripture Prison itself prevents Reactions on a successful save; final
    # availability cannot distinguish the response's action cost in this fixture.


