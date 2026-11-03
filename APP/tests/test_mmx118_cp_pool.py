"""MMX118: a fighter whose Path pool is not Qi can use the printed "Qi Storage Talisman" button.

HUNT112 #1 (P1, round-24 LIVE 42e43e14): the printed button raised
``ValueError: unknown resource`` for 7 of 9 M-Z characters. ``combat/ext/talismans.py`` recorded the
CP pool at build time from ``factory_compiler.RESOURCE_IDS`` keyed on ``info["primary"]`` -- but the
``compile_action`` hook is called with an ``info`` that has no ``primary`` (factory_compiler.py:2362),
so the lookup was always the fallback ``resource:core.qi``. Any character without a Qi pool then
gained a pool it does not have and ``gate2_engine._gain_resource`` (gate2_engine.py:2951) raised,
taking the whole table down mid-turn.

The printed rule (Qi Storage Talisman, Prereq CL 5+): "A creature holding the talisman may activate
it to regain CP equal to the amount stored, up to its normal maximum." CP is this game's Path pool
(``typed_executor.CP_POOLS``), so a Stamina or Resonance fighter regains that pool.
"""
from combat.canonical import canonical_sha256
from combat.ext.talismans import PREPARED
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_lock2_persistence import act

ME, FOE = "actor:factory.mmx118-talisman", "actor:factory.mmx118-talisman-foe"
STAMINA = "resource:core.stamina"
RESONANCE = "resource:core.resonance"
TALISMAN = "tianxia.talent.talismans.qi_storage_talisman"


def _sealed(document, pool, initial):
    """Build a bundle whose Path pool starts at ``initial`` (a synthetic fight setup)."""
    bundle = compile_character(document, actor_id=ME, reaction_plan={"ask": True})
    for resource in bundle["actor_template"]["resources"]:
        if resource["resource_id"] == pool:
            resource["initial"] = initial
    unsigned = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    bundle["bundle_sha256"] = canonical_sha256(unsigned)
    return bundle


def _prepared_count(**kw):
    """One stored charge is offered per prepared talisman (the character knows its own limit)."""
    bundle = compile_character(sheet([TALISMAN], cl=10, **kw), actor_id=ME)
    return next(row["maximum"] for row in bundle["actor_template"]["resources"]
                if row["resource_id"] == PREPARED)


def _fight(tmp_path, *, primary="Stamina", pool=STAMINA, charges=None, start=0):
    mine = sheet([TALISMAN], cl=10, primary=primary)
    bundle = _sealed(mine, pool, start)
    foe = sheet([], cl=10, primary=primary)
    combat = CombatService(ROOT, tmp_path)
    if charges is not None:
        bundle = combat._with_prefight(bundle, {ME: ["setup-choice:qi_storage_charges:" + ",".join(map(str, charges))]})
    opponent = compile_character(foe, actor_id=FOE)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        [bundle, opponent], [ME, FOE], {ME: "team:factory", FOE: "team:opponents"},
        {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [FOE],
        control_modes={ME: "MANUAL", FOE: "MANUAL"}, match_seed="MMX118-TALISMAN",
        display_name="MMX118 Qi Storage pool regression", maximum_rounds=20)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != ME:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid


def _reloaded(combat, mid):
    return combat._load_session(mid).engine.state


def _offered(combat, mid):
    return [row for row in combat._load_session(mid).engine.legal_candidates()
            if row.display_name == "Qi Storage Talisman"]


def test_printed_button_restores_the_paths_own_cp_pool_for_a_stamina_fighter(tmp_path):
    """The regression: this press raised ValueError("unknown resource") before the fix."""
    charges = [2] + [0] * (_prepared_count(primary="Stamina") - 1)
    combat, table, mid = _fight(tmp_path, charges=charges, start=5)
    before = _reloaded(combat, mid)
    assert STAMINA in before.actors[ME].resources
    assert "resource:core.qi" not in before.actors[ME].resources
    assert _offered(combat, mid), "the printed button must be offered"
    assert send_talisman(table, mid, combat) == "COMMITTED"
    after = _reloaded(combat, mid)
    assert after.actors[ME].resources[STAMINA] == 7  # the recorded 2 CP, not the 4 PB legacy guess
    assert after.actors[ME].resources[PREPARED] == before.actors[ME].resources[PREPARED] - 1
    assert combat.verify(mid)["status"] == "PASS"


def test_resonance_fighter_also_uses_its_own_pool(tmp_path):
    combat, table, mid = _fight(tmp_path, primary="Resonance", pool=RESONANCE,
                                charges=[1] + [0] * (_prepared_count(primary="Resonance") - 1), start=0)
    assert "resource:core.qi" not in _reloaded(combat, mid).actors[ME].resources
    assert send_talisman(table, mid, combat) == "COMMITTED"
    assert _reloaded(combat, mid).actors[ME].resources[RESONANCE] == 1
    assert combat.verify(mid)["status"] == "PASS"


def test_a_fighter_with_no_cp_pool_is_cleanly_refused_never_crashed(tmp_path):
    """No CP-backed pool: nothing to restore, so the button is not offered and nothing raises."""
    combat, table, mid = _fight(tmp_path, charges=[2] + [0] * (_prepared_count() - 1), start=5)
    # One loaded engine: _load_session re-reads from disk, so the stripped pools must be read
    # back off the same object whose candidates are asked.
    engine = combat._load_session(mid).engine
    actor = engine.state.actors[ME]
    for pool in ("resource:core.qi", STAMINA, RESONANCE):
        actor.resources.pop(pool, None)
        actor.resource_maximums.pop(pool, None)
    offered = [row for row in engine.legal_candidates() if row.display_name == "Qi Storage Talisman"]
    assert not offered, "a fighter with no Path pool must not be offered a CP restore"
    assert combat.verify(mid)["status"] == "PASS"


def send_talisman(table, mid, combat):
    menu = table.state(mid)["menu"]
    chosen = next(option["candidate_id"] for group in menu["actions"]
                  for option in group["options"] if option["label"] == "Qi Storage Talisman")
    return table.act(mid, chosen, menu["decision_id"], menu["state_version"], 0, [])["status"]
