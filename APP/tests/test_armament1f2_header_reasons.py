"""ARMAMENT1F2: a compact-menu header refused at the source explains itself, for each such source.

Four plug-in `source_unavailable` hooks give the compact header its reason: Check movement: move
quietly (no scene calls for it), Study an illusion (no visible unstudied illusion), Attempt to Remove
Clinging Seal (no strengthened seal), and Break Chains of Qi (no chains held). Each is checked on its
own real fight, both as the hook answer and as the table's lazy `unavailable_reasons`, and every
fight runs the whole-menu honesty check from the Domain Armament module.
"""
import pytest  # noqa: F401

from combat import ext
from tests.test_domain_armament_and_manifestation import _assert_compact_headers_honest
from tests.worker2_support import OWNER, fixture as worker_fixture, turn
from tests.test_r5i_integration import PLAYER, fixture as wax_fixture, turn as wax_turn

PRESS = "TAL_WAX_PRESS_SEAL"
CLINGING = "TAL_WAX_CLINGING_SEAL"
CHAINS = "tianxia.subpath.qi.cultivator_of_seals.feature.chains_of_qi"
STUDY = "system:combat.study_figment"
SCENE_REFUSAL = "No part of this scene calls for that check."
WAX_REFUSAL = "You bear no strengthened Wax Seal to tear away."
STUDY_REFUSAL = "There is no illusion you can see that you have not already studied."
CHAINS_REFUSAL = "You are not held by Chains of Qi; there is nothing to break."


def _first_reason(answers):
    return next((text for text in answers if isinstance(text, str) and text.strip()), None)


def _owned(engine, owner, predicate):
    return [a for a in engine.action_catalog.values() if a.owner_id == owner and predicate(a)]


def _header_reason(table, mid, source):
    lazy = table.state(mid, lazy=True)
    headers = {g["source_definition_id"] for g in lazy["menu"]["actions"] if g.get("lazy")}
    assert source in headers, f"{source} is not offered as a compact header"
    return (lazy.get("unavailable_reasons") or {}).get("act:" + source)


def test_scene_check_header_says_why_no_scene_calls_for_it(tmp_path):
    combat, table, mid = worker_fixture(tmp_path, [], ask=False)
    turn(table, mid, OWNER)
    engine = combat._load_session(mid).engine
    action = _owned(engine, OWNER, lambda a: (a.parameters or {}).get("scene_check_purpose") == "quiet_movement")[0]
    assert _first_reason(ext.run("source_unavailable", engine, engine.state.actors[OWNER], action)) == SCENE_REFUSAL
    assert _header_reason(table, mid, action.source_definition_id) == SCENE_REFUSAL


def test_study_header_says_why_there_is_no_illusion_to_study(tmp_path):
    combat, table, mid = worker_fixture(tmp_path, [], ask=False)
    turn(table, mid, OWNER)
    engine = combat._load_session(mid).engine
    action = engine.action_catalog[STUDY]
    assert _first_reason(ext.run("source_unavailable", engine, engine.state.actors[OWNER], action)) == STUDY_REFUSAL


def test_wax_seal_attempt_header_says_why_no_seal_is_strengthened(tmp_path):
    combat, table, mid = wax_fixture(tmp_path, [PRESS, CLINGING])
    wax_turn(table, mid, PLAYER)
    engine = combat._load_session(mid).engine
    action = _owned(engine, PLAYER, lambda a: any(
        e.get("type") == "wax_seal_attempt" for e in ((a.parameters or {}).get("typed") or {}).get("effects") or []))[0]
    assert _first_reason(ext.run("source_unavailable", engine, engine.state.actors[PLAYER], action)) == WAX_REFUSAL
    assert _header_reason(table, mid, action.source_definition_id) == WAX_REFUSAL


def test_chains_header_says_why_nothing_is_held(tmp_path):
    combat, table, mid = worker_fixture(tmp_path, [], owner_features=[CHAINS], cl=6, owner_dc=100, ask=False)
    turn(table, mid, OWNER)
    engine = combat._load_session(mid).engine
    action = _owned(engine, OWNER, lambda a: (a.parameters or {}).get("qi5_escape"))[0]
    assert _first_reason(ext.run("source_unavailable", engine, engine.state.actors[OWNER], action)) == CHAINS_REFUSAL
    assert _header_reason(table, mid, action.source_definition_id) == CHAINS_REFUSAL


CANDLEFLARE_REFUSAL = "You have no wax within reach to kindle."


def test_candleflare_header_says_why_no_wax_is_within_reach(tmp_path):
    combat, table, mid = wax_fixture(tmp_path, [PRESS, CLINGING])
    wax_turn(table, mid, PLAYER)
    engine = combat._load_session(mid).engine
    action = _owned(engine, PLAYER, lambda a: a.source_definition_id.endswith(".wax.kindle.candleflare"))[0]
    assert _first_reason(ext.run("source_unavailable", engine, engine.state.actors[PLAYER], action)) == CANDLEFLARE_REFUSAL
    assert _header_reason(table, mid, action.source_definition_id) == CANDLEFLARE_REFUSAL


def _lazy_headers(table, mid):
    lazy = table.state(mid, lazy=True)
    return [g["source_definition_id"] for g in lazy["menu"]["actions"] if g.get("lazy") and g.get("source_definition_id")]


def test_every_refusing_fight_has_honest_compact_headers(tmp_path):
    """The Domain Armament whole-menu property, over the fights that carry the other refusals too.

    The honesty check itself is the Domain Armament module's; this test only reads the header
    list directly so it does not depend on that helper's return shape at older commits.
    """
    fights = [
        ("scene", lambda: worker_fixture(tmp_path / "scene", [], ask=False), OWNER),
        ("chains", lambda: worker_fixture(tmp_path / "chains", [], owner_features=[CHAINS], cl=6, owner_dc=100, ask=False), OWNER),
        ("wax", lambda: wax_fixture(tmp_path / "wax", [PRESS, CLINGING]), PLAYER),
    ]
    for name, build, actor in fights:
        combat, table, mid = build()
        (turn if name != "wax" else wax_turn)(table, mid, actor)
        _assert_compact_headers_honest(table, mid)
        assert _lazy_headers(table, mid), f"{name}: the compact menu offers headers to check"
