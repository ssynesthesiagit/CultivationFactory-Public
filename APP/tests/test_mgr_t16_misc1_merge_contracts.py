"""Integrated compiler/menu contracts behind the misc-1 review failures."""
from combat import ext
from combat.ext.empirical_evidence import FLAG
from tests.test_mgr_t16_misc1_evidence import fight
from tests.worker2_support import ALLY, FOE, OWNER, reload


def test_integrated_evidence_catalog_reaches_the_native_menu_after_reload(tmp_path):
    combat, table, mid = fight(tmp_path)
    engine = reload(tmp_path, mid)
    actor = engine.state.actors[OWNER]
    actions = [a for a in engine.action_catalog.values()
               if a.owner_id == OWNER and a.parameters.get(FLAG)]
    assert actions, 'Every owned native Analyze route needs its evidence adapter'
    obj = engine.state.objects['object:map.600']
    assert obj.component['source_profiles']['empirical_tracker']['age_seconds'] == 0
    from combat.ext.eye_common import has
    assert has(engine, OWNER, 'empirical_tracker'), 'Public fixtures must retain the owned Approach marker'
    from combat.gate2_engine import Gate2Engine
    # Diagnose the native targeting pass separately from extension admission.
    native = [c for a in actions for c in Gate2Engine._action_candidates(engine, actor, a)]
    from combat.ext.empirical_evidence import evidence_targets
    from combat.primary_intents import allows_primary
    import json
    assert native, json.dumps({
        'action_available': actor.action_available,
        'focus': actor.resources.get('resource:core.martial_focus'),
        'owned': has(engine, OWNER, 'empirical_tracker'),
        'targets': evidence_targets(engine, actor, actions[0]),
        'sight': engine._line_of_sight_actor_to_cell(actor, obj.position),
        'distance': engine._effect_distance_to_cell(actor, obj.position),
        'actions': [(a.economy.value, a.range_ft, allows_primary(a)) for a in actions],
    }, sort_keys=True)
    vetoes = {c.source_definition_id: ext.vetoing_hooks(
        'candidate_allowed', engine, actor, c, engine.action_catalog[c.source_definition_id])
        for c in native}
    assert not any(vetoes.values()), vetoes
    assert any(c.source_definition_id in vetoes for c in engine.legal_candidates())


def test_field_deafness_is_a_continuous_grant_for_initial_and_later_members(tmp_path):
    from tests.test_mgr_t16_misc1_silence import fight as field_fight, move

    combat, table, mid = field_fight(tmp_path)

    def grants(who):
        actor = reload(tmp_path, mid).state.actors[who]
        return [c for c in actor.conditions.values()
                if c.condition_id == 'condition:typed.zone_effect'
                and (c.data.get('rule') or {}).get('cant_hear')]

    assert grants(OWNER), 'Starting members need the continuous Deafened grant'
    assert not grants(ALLY)
    move(combat, table, mid, ALLY, (7, 6))
    assert grants(ALLY), 'Entering after casting must grant Deafened after cold reload'
    move(combat, table, mid, ALLY, (8, 6))
    assert not grants(ALLY), 'Leaving must remove the field-owned Deafened grant'
    assert grants(OWNER), 'Another creature leaving must not remove the owner grant'
    # The ally occupies the direct route; approach on one turn, then enter
    # around it on the next without exceeding the foe's movement allowance.
    move(combat, table, mid, FOE, (9, 6))
    move(combat, table, mid, FOE, (7, 6))
    assert grants(FOE), 'Hostile creatures receive the same continuous deafness'
    engine = reload(tmp_path, mid)
    saves = [e.actor_id for e in engine.events if e.event_type == 'SAVE_ROLLED']
    assert FOE in saves, 'Hostile entry must still resolve the additional save'
    assert ALLY not in saves and OWNER not in saves, (
        'Continuous deafness affects everyone; the additional entry save remains hostile-only')
