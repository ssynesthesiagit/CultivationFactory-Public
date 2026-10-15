"""Integrated compiler/menu contracts behind the misc-1 review failures."""
from combat import ext
from combat.ext.empirical_evidence import FLAG
from tests.test_mgr_t16_misc1_evidence import fight
from tests.worker2_support import OWNER, reload


def test_integrated_evidence_catalog_reaches_the_native_menu_after_reload(tmp_path):
    combat, table, mid = fight(tmp_path)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    actions = [a for a in engine.action_catalog.values()
               if a.owner_id == OWNER and a.parameters.get(FLAG)]
    assert actions, 'Every owned native Analyze route needs its evidence adapter'
    obj = engine.state.objects['object:map.600']
    assert obj.component['source_profiles']['empirical_tracker']['age_seconds'] == 0
    from combat.gate2_engine import Gate2Engine
    # Diagnose the native targeting pass separately from extension admission.
    native = [c for a in actions for c in Gate2Engine._action_candidates(engine, actor, a)]
    assert native, {'actions': [a.model_dump(mode='json') for a in actions],
                    'object': obj.model_dump(mode='json'),
                    'profiles': engine.typed_passive_rows[OWNER]}
    vetoes = {c.source_definition_id: ext.vetoing_hooks(
        'candidate_allowed', engine, actor, c, engine.action_catalog[c.source_definition_id])
        for c in native}
    assert not any(vetoes.values()), vetoes
    assert any(c.source_definition_id in vetoes for c in engine.legal_candidates())
