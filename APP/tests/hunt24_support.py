"""Public synthetic bundles and real persisted tables for hunt 24 regressions."""
from combat.canonical import canonical_sha256
from combat.factory_compiler import compile_character
from combat.gate5_service import CombatService
from combat.tabletop_service import TabletopService
from tests.h1_support import ROOT, sheet

A, D, F = 'actor:factory.h24-attacker', 'actor:factory.h24-defender', 'actor:factory.h24-foe'


def finish_direct_setup(engine):
    """Direct-engine fixtures must finish new initiative tasks before ordinary play."""
    from combat.gate2_runtime_models import ActionIntent
    if engine.state.setup_tasks:
        candidate = engine.legal_candidates()[0]
        engine.execute_intent(ActionIntent(intent_id='test:initiative-setup', decision_id=candidate.decision_id,
            candidate_id=candidate.candidate_id, state_version=candidate.state_version, actor_id=candidate.actor_id))


def table_fight(tmp_path, talents=(), *, primary='Qi', prepare=None, foes=1, ally=False, enemy_out_of_range=False):
    bundles = []
    for aid in [A, D, *([F] if foes == 2 else [])]:
        document = sheet(list(talents) if aid == D else [], cl=15, primary=primary)
        document['identity']['display_name'] = {A:'Attacker', D:'Defender', F:'Second foe'}[aid]
        bundle = compile_character(document, actor_id=aid, reaction_plan={'mode':'ask', 'ask':aid == D})
        if prepare:
            prepare(bundle)
            bundle.pop('bundle_sha256', None)
            bundle['bundle_sha256'] = canonical_sha256(bundle)
        bundles.append(bundle)
    svc = CombatService(ROOT, tmp_path)
    ids = [b['actor_id'] for b in bundles]
    mid = svc._finish_factory_match(bundles, ids, {aid:'d' if aid == D or (ally and aid == F) else 'a' for aid in ids},
        {A:{'x':18 if enemy_out_of_range else 3,'y':6}, D:{'x':4,'y':6}, **({F:{'x':4,'y':5}} if foes == 2 else {})},
        svc.factory_arenas(include_retired=True)['battlefield:factory_pillar_arena'], [D], [A],
        control_modes={aid:'MANUAL' for aid in ids}, match_seed='HUNT24',
        display_name='Hunt 24 regression', maximum_rounds=4)['match_id']
    return svc, TabletopService(svc, tmp_path), mid
