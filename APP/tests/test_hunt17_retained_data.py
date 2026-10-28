"""Isolate retained-data bookkeeping inside real table transactions, without core patches.

Test-only actions prepare each existing plug-in state in one transaction and
exercise its production hook in a later transaction. Fresh loading checks the
event journal rather than the original in-memory engine.
"""
import pytest

from combat import ext, typed_executor
from combat.canonical import canonical_sha256
from combat.ext import blood_riders, hunger_riders, karma_riders, suppressed_effects
from combat.gate2_runtime_models import ActionDefinition, EconomyKind
from combat.gate5_service import CombatService
from tests.r1i_service_support import ROOT, OWNER, FOE, fixture, candidate, force_ai_candidate


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('case', ['mantle_hit', 'three_course', 'trial_harm', 'writ_harm', 'trial_heal', 'merit_heal', 'burn', 'restore'])
def test_retained_bookkeeping_reloads_without_new_applications(tmp_path, monkeypatch, auto, case):
    cid = {'mantle_hit': hunger_riders.MANTLE, 'trial_harm': karma_riders.TRIAL,
           'writ_harm': karma_riders.WRIT, 'trial_heal': karma_riders.TRIAL,
           'merit_heal': karma_riders.MERIT, 'burn': 'condition:typed.test_burn',
           'three_course': hunger_riders.MANTLE, 'restore': 'condition:typed.invisible'}[case]
    def prepare(ctx, effect):
        if 'heal' in case:
            ctx.engine._commit_damage(ctx.engine.state.actors[FOE], 5, 'FORCE', 'test:prepare', OWNER, None, reaction_depth=1)
        data = {'benefits': ['Beast Strength'], 'used': [], 'pb': 4, 'key': 2} if case in ('mantle_hit', 'three_course') else (
            {'burn': 1, 'burn_dice': '3d8', 'type': 'NECROTIC'} if case == 'burn' else {'amount': 6, 'pb': 4})
        ctx.engine._apply_condition(ctx.actor, cid, 'test:retained-source', OWNER,
                                   expires_on='UNTIL_REMOVED', data=data)
    def trigger(ctx, effect):
        if case == 'mantle_hit':
            hunger_riders.mantle_hit(ctx, ctx.engine.state.actors[FOE], 'weapon')
        elif case == 'restore':
            condition = next(c for c in ctx.actor.conditions.values() if c.condition_id == cid)
            document = condition.model_dump(mode='json')
            clock = suppressed_effects.lifetime(ctx.engine, ctx.actor, condition)
            ctx.engine._remove_condition(ctx.actor, cid, ctx.source)
            suppressed_effects.restore(ctx.engine, ctx.actor, document, clock)
        elif case.endswith('harm'):
            ctx.engine._commit_damage(ctx.engine.state.actors[FOE], 1, 'FORCE', ctx.source, OWNER, None, reaction_depth=1)
        elif case.endswith('heal'):
            ctx.target = ctx.engine.state.actors[FOE]
            ctx.targets = [ctx.target]
            typed_executor.block_healing(ctx, {'type': 'healing', 'applies_to': 'target', 'flat': 1})
        else:
            blood_riders.reroll_burns(ctx.engine, ctx.actor)
    ext.effects()
    monkeypatch.setitem(ext._EFFECTS, 'test_retained_prepare', prepare)
    monkeypatch.setitem(ext._EFFECTS, 'test_retained_trigger', trigger)
    def actions(bundles):
        owner = bundles[0]
        if case == 'three_course':
            # Three-Course Battle Body answers only for an actor that owns its own Hunger row (hunger_riders._three_course
            # returns early without it), and this fixture compiles no talents, so the row is added to the bundle here and
            # the trigger action carries the talent as its typed source -- the production technique_used hook then does
            # the work in a later transaction, exactly as the case describes. Without the row the trigger changed nothing
            # and this case asserted a bookkeeping pass that never happened (red since AUTO14, ee26e61c).
            owner['typed_passives'].append({'feature_id': hunger_riders.H + 'three_course_battle_body',
                                            'block': 'lane9_hunger', 'kind': 'three_course', 'pb': 4, 'key_mod': 2,
                                            'name': 'Three-Course Battle Body'})
        for name, effect in [('Prepare retained state', 'test_retained_prepare'), ('Trigger retained state', 'test_retained_trigger')]:
            owner['action_catalog'].append(ActionDefinition(
                source_definition_id='action:test.' + effect, display_name=name, owner_id=OWNER,
                economy=EconomyKind.NONE, resolution_kind='TYPED', target_kind='SELF',
parameters={'typed': {'effects': [{'type': effect}], 'numbers': {}, 'riders': [],
                                          # Only the trigger action carries the talent: the prepare action must stay
                                          # offered while no Mantle is up, which is itself the printed rule.
                                          **({'source': hunger_riders.H + 'three_course_battle_body'}
                                             if case == 'three_course' and effect == 'test_retained_trigger' else {})}}
            ).model_dump(mode='json'))
            owner['actor_template']['action_ids'] = [*owner['actor_template']['action_ids'], 'action:test.' + effect]
        owner.pop('bundle_sha256', None)
        owner['bundle_sha256'] = canonical_sha256(owner)
    combat, table, mid, send, commit = fixture(tmp_path, [], bundle_transform=actions)
    commit(candidate(table, mid, 'Prepare retained state'))
    before = CombatService(ROOT, tmp_path)._load_session(mid)
    key, held = next((k, c.model_dump(mode='json')) for k, c in before.engine.state.actors[OWNER].conditions.items()
                     if c.condition_id == cid)
    sequence = before.engine.state.event_sequence
    action = candidate(table, mid, 'Trigger retained state')
    if auto:
        force_ai_candidate(combat, mid, OWNER, action)
        assert send(action, auto=True)['status'] == 'COMMITTED'
    else:
        commit(action)
    loaded = CombatService(ROOT, tmp_path)._load_session(mid)
    assert loaded.mechanical.replay()['status'] == 'PASS'
    updated = loaded.engine.state.actors[OWNER].conditions[key]
    assert (updated.data == held['data']) if case == 'restore' else (updated.data != held['data'])
    assert updated.expires_on == held['expires_on']
    events = [e for e in loaded.engine.events if e.sequence > sequence
              and e.event_type == 'CONDITION_APPLIED' and e.payload.get('instance_id') == key]
    assert len(events) == 1 and events[0].payload.get('retained_instance_update') == 1
