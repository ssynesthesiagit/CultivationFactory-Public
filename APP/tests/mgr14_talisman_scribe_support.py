"""TALISMANS_BASE_TALISMAN_SCRIBE sheet and table helpers shared by its two regression files.

``tests.test_mgr_t14_talisman_scribe`` keeps the Print/Play clauses and ``tests.test_mgr_t14_talisman_scribe_auto``
keeps the automatic-controller cases; both drive the same real table fight, so the builders live here once. Nothing
here reads repository history: the fight is built from the current authority through ``tests.h1_support.sheet``.
"""
from combat import table_advance
from combat.ext import talisman_scribe
from tests.h1_support import ROOT, sheet
from tests.hunt12_support import ME as TABLE_ME
from tests.test_lock2_persistence import act

SCRIBE = talisman_scribe.SCRIBE
SPHERE = "tianxia.sphere.talismans"
SCRIPT = "TALISMANS_BASE_READ_THE_SCRIPT"
SCRIPT_NAME = "Read the Script"
PURIFYING = "tianxia.talent.talismans.purifying_talisman"
YES = talisman_scribe.YES
ALLY_TABLE = "actor:factory.mgr14-talisman-scribe-ally"


def _unacquired():
    """A Purifying Talisman fighter whose sheet has learned no Sphere, so it owns no base ability at all.

    ``sheet`` fills ``automatic_sphere_component_record_ids`` from the ids it is handed, so the list is
    emptied here: this fighter reaches every Talismans base row only by learning the Sphere at the table.
    """
    base = sheet([PURIFYING], cl=18, dc=10, primary="Stamina")
    block = base["spheres_and_talents"]
    base["spheres_and_talents"] = {"sphere_record_ids": [], "learned_talent_record_ids": [],
                                   "automatic_sphere_component_record_ids": []}
    assert PURIFYING in block["learned_talent_record_ids"], "the fighter keeps the talent it actually took"
    return base


def _learned_talismans():
    """The unacquired sheet with the Talismans sphere learned at the table -- no Talisman Scribe id typed in."""
    return table_advance.apply(_unacquired(), {"spheres": [{"id": SPHERE}]})


def _table(tmp_path, learner, *, seed="MGR14SCRIBE", ally_sheet=None):
    """A real table fight over the given sheet: the scribe and an ally beside it."""
    from combat.factory_compiler import compile_character
    from combat.gate5_service import CombatService
    from combat.tabletop_service import TabletopService

    mine = compile_character(learner, actor_id=TABLE_ME, reaction_plan={"ask": True})
    ally = compile_character(_unacquired() if ally_sheet is None else ally_sheet, actor_id=ALLY_TABLE)
    combat = CombatService(ROOT, tmp_path)
    table = TabletopService(combat, tmp_path)
    mid = combat._finish_factory_match(
        [mine, ally], [TABLE_ME, ALLY_TABLE],
        {TABLE_ME: "team:factory", ALLY_TABLE: "team:factory"},
        {TABLE_ME: {"x": 3, "y": 6}, ALLY_TABLE: {"x": 3, "y": 7}},
        combat.factory_arenas(include_retired=True)["battlefield:factory_pillar_arena"],
        [TABLE_ME, ALLY_TABLE], [],
        control_modes={TABLE_ME: "MANUAL", ALLY_TABLE: "MANUAL"},
        match_seed=seed, display_name=f"MGR-T14 Talisman Scribe regression {seed}",
        maximum_rounds=20)["match_id"]
    while table.state(mid)["menu"]["actor_id"] != TABLE_ME:
        assert act(table, mid, "end")["status"] == "COMMITTED"
    return combat, table, mid


def _script_check(engine):
    """The real Read the Script Intelligence check this fight recorded."""
    return [event for event in engine.events
            if event.event_type == "CHECK_ROLLED" and str(event.source_definition_id).endswith(SCRIPT)]
