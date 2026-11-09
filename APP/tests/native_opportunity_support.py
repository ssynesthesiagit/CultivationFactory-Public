"""Shared native-opportunity table setup for LOCK13 and SOL114."""
from combat.factory_compiler import compile_character
from combat.gate2_runtime_content import AN, BAI
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, ME, sheet
from tests.test_hidden_targeting import turn

CM = "TAL_LIGHTNING_CHARGED_COUNTERMEASURE"


def fight(tmp_path, *, owned=True, two=False):
    doc = sheet([CM] if owned else [], cl=12, dc=30)
    doc['identity']['display_name'] = 'Watcher'
    bundle = compile_character(doc, actor_id=ME, reaction_plan={'ask': True})
    svc = CombatService(ROOT, tmp_path)
    positions = {ME: {'x': 4, 'y': 6}, AN: {'x': 5, 'y': 6}, BAI: {'x': 4, 'y': 7}}
    mid = svc.persistence.create_match(match_seed='LOCK13-NATIVE', typed_bundles=(bundle,),
        roster_setup={'primary_actor_ids': [ME, AN, BAI] if two else [ME, AN],
                      'team_by_actor': {ME: 'a', AN: 'b', BAI: 'b'},
                      'starting_positions': positions}).match_id
    for aid in ([ME, AN, BAI] if two else [ME, AN]):
        svc.set_controller_mode(mid, actor_id=aid, controller_mode='MANUAL')
    table = TabletopService(svc, tmp_path)
    turn(table, mid, ME)
    return svc, table, mid
