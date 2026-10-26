"""MMX118f1: a saved catalog written by the predecessor still loads, and still pays the right pool.

The predecessor recorded the CP pool on the compiled action itself
(``replacement.parameters["qi_storage_resource"] = RESOURCE_IDS.get(info.get("primary") or "qi")``,
``combat/ext/talismans.py:136`` at 42e43e14). Because ``compile_action`` is handed an info dict with no
``primary``, that line wrote the constant ``resource:core.qi`` into *every* character's catalog, and a
fighter without a Qi pool crashed on press. The fix stops recording a guess, so the question this file
answers is what happens to the fights already saved with that guess in them:

* a fighter whose saved catalog names a pool they really have keeps paying into **that** pool, so an
  already-played Qi fight is not silently re-pointed somewhere else; and
* a fighter whose saved catalog names a pool they do **not** have is the exact shape of the pre-fix
  crash, and must now restore their own Path pool instead of taking the table down.

The recorded parameter is put on the compiled bundle exactly as the predecessor's ``compile_qi_storage``
wrote it, then the bundle is re-sealed with ``canonical_sha256`` -- the same synthetic-fight technique
``tests/test_hunt48_qi_storage_talisman.py`` uses for its pool initial value. These are synthetic fights
built in a pytest tmp_path; no owner data is read or written.
"""
from __future__ import annotations

import pytest

from combat.canonical import canonical_sha256
from combat.ext.cp_pools import QI, RESONANCE, STAMINA
from combat.ext.talismans import PREPARED
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet
from tests.test_lock2_persistence import act

ME, FOE = "actor:factory.mmx118f1-catalog", "actor:factory.mmx118f1-catalog-foe"
TALISMAN = "tianxia.talent.talismans.qi_storage_talisman"
OLD_RECORDED = QI  # what the predecessor wrote for every character, whatever their Path pool was


def _bundle(document, *, recorded: str | None, initial: int = 0):
    """Compile a character, then stamp on the pool the predecessor's catalog recorded.

    ``recorded=None`` is a catalog written by the current compiler (no guess recorded at all).
    """
    bundle = compile_character(document, actor_id=ME, reaction_plan={"ask": False})
    for action in bundle["action_catalog"]:
        if str(action.get("source_definition_id") or "").endswith(TALISMAN) and recorded:
            action["parameters"]["qi_storage_resource"] = recorded
    for resource in bundle["actor_template"]["resources"]:
        if resource["resource_id"] in (QI, STAMINA, RESONANCE):
            resource["initial"] = initial
    unsigned = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    bundle["bundle_sha256"] = canonical_sha256(unsigned)
    return bundle


def _charges(bundle) -> list[int]:
    prepared = next(row["maximum"] for row in bundle["actor_template"]["resources"]
                    if row["resource_id"] == PREPARED)
    return [2] + [0] * (prepared - 1)


def _fight(tmp_path, *, primary: str, recorded: str | None, initial: int = 0):
    mine = sheet([TALISMAN], cl=10, primary=primary)
    bundle = _bundle(mine, recorded=recorded, initial=initial)
    combat = CombatService(ROOT, tmp_path)
    bundle = combat._with_prefight(bundle, {ME: ["setup-choice:qi_storage_charges:" + ",".join(map(str, _charges(bundle)))]})
    opponent = compile_character(sheet([], cl=10, primary=primary), actor_id=FOE)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        [bundle, opponent], [ME, FOE], {ME: "team:factory", FOE: "team:opponents"},
        {ME: {"x": 3, "y": 6}, FOE: {"x": 4, "y": 6}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"], [ME], [FOE],
        control_modes={ME: "MANUAL", FOE: "MANUAL"}, match_seed="MMX118F1-CATALOG",
        display_name="MMX118f1 saved catalog", maximum_rounds=20)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != ME:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid


def _activate(table, mid) -> str:
    menu = table.state(mid)["menu"]
    chosen = next(option["candidate_id"] for group in menu["actions"]
                  for option in group["options"] if option["label"] == "Qi Storage Talisman")
    return table.act(mid, chosen, menu["decision_id"], menu["state_version"], 0, [])["status"]


def test_a_qi_fight_whose_saved_catalog_records_qi_keeps_paying_qi(tmp_path):
    """The common predecessor save: a Qi fighter's catalog named Qi, and must still restore Qi."""
    combat, table, mid = _fight(tmp_path, primary="Qi", recorded=OLD_RECORDED, initial=0)
    engine = combat._load_session(mid).engine
    assert engine.action_catalog[[key for key in engine.action_catalog
                                  if key.endswith(TALISMAN)][0]].parameters.get("qi_storage_resource") == QI
    assert _activate(table, mid) == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid).engine.state  # commit + reload
    assert reloaded.actors[ME].resources[QI] == 2
    # The formula is "Consumed: yes": one prepared talisman is spent, the rest are untouched.
    assert reloaded.actors[ME].resources[PREPARED] == engine.state.actors[ME].resources[PREPARED] - 1
    assert combat.verify(mid)["status"] == "PASS"


def test_a_stamina_fight_saved_with_the_old_qi_record_does_not_crash_it(tmp_path):
    """The pre-fix crash, as a saved fight: the catalog names Qi, the fighter has Stamina.

    Before the fix this raised ``ValueError("unknown resource")`` inside ``gate2_engine._gain_resource``
    and came back as ``COMBAT_AI_INTENT_INVALID``; the button took the table down. Now the recorded pool
    is ignored unless the fighter really has it, and the restore lands in their own Path pool.
    """
    combat, table, mid = _fight(tmp_path, primary="Stamina", recorded=OLD_RECORDED, initial=0)
    state = CombatService(ROOT, tmp_path)._load_session(mid).engine.state
    assert QI not in state.actors[ME].resources, "this control only means something for a fighter without Qi"
    assert STAMINA in state.actors[ME].resources
    assert _activate(table, mid) == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid).engine.state  # commit + reload
    assert reloaded.actors[ME].resources[STAMINA] == 2, "the stored CP belongs in the fighter's own pool"
    assert QI not in reloaded.actors[ME].resources, "the restore must not invent a Qi pool"
    assert combat.verify(mid)["status"] == "PASS"


@pytest.mark.parametrize("primary, pool", [("Resonance", RESONANCE), ("Stamina", STAMINA)])
def test_a_current_catalog_records_no_guess_at_all(tmp_path, primary, pool):
    """Today's compiler records nothing, so the pool is decided at use time and never persisted."""
    combat, table, mid = _fight(tmp_path, primary=primary, recorded=None, initial=0)
    engine = combat._load_session(mid).engine
    row = engine.action_catalog[[key for key in engine.action_catalog if key.endswith(TALISMAN)][0]]
    assert "qi_storage_resource" not in row.parameters
    assert _activate(table, mid) == "COMMITTED"
    reloaded = CombatService(ROOT, tmp_path)._load_session(mid).engine.state  # commit + reload
    assert reloaded.actors[ME].resources[pool] == 2
    assert combat.verify(mid)["status"] == "PASS"
