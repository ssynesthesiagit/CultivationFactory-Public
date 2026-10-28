"""Persisted table admission and reactions: owned sight exceptions and missing dependencies.

Test-only setup actions create concealment/marks through ordinary table commits.
A primary-action adapter gives the printed Dawnlit Rebuke Mark identity an
explicit sight requirement, exercising the general contract through the table.
A reaction adapter gives that same printed Mark identity a "when you take
damage" trigger, so the shared sight and dependency reaction contract is
exercised through real table commits, consent prompts, payments and reloads.
"""
import pytest

from combat import ext
from tests import hunt28_support as support
from tests.hunt28_support import OWNER, ALLY, FOE, act, fixture, options, reload, send

SCRIPTURE = 'tianxia.talent.radiance.dawnmark_scripture'
WITNESS = 'RADIANCE_TAL_DAWNLIT_REBUKE'
STRIKE = 'Unseen bearer strikes'


def prepared_table(tmp_path, monkeypatch, *, scripture=True, marker=OWNER, dependency=None, target_kind='HOSTILE_ENTITY',
                   reaction=None):
    compile_character = support.compile_character

    def compile_setup(*args, **kwargs):
        bundle = compile_character(*args, **kwargs)
        actor = kwargs['actor_id']
        if actor == OWNER:
            aid = 'action:test.sight_mark'
            bundle['actor_template']['action_ids'].append(aid)
            bundle['action_catalog'].append({
                'source_definition_id': aid, 'display_name': 'Sight-qualified Mark talent', 'owner_id': actor,
                'economy': 'ACTION', 'resolution_kind': 'TYPED', 'target_kind': target_kind, 'range_ft': 120,
                'costs': [['resource:core.qi', 2]],
                'parameters': {'typed': {'source': WITNESS, 'requires_seen_target': True,
                    'effects': [{'type': 'spend_mark', 'mark': 'Smoke Trace', 'applies_to': 'target'}],
                    'numbers': {}, 'duration': {'kind': 'instant'}}}})
        if actor == marker:
            aid = 'action:test.prepare_unseen_mark'
            bundle['actor_template']['action_ids'].append(aid)
            bundle['action_catalog'].append({
                'source_definition_id': aid, 'display_name': 'Prepare unseen marked target', 'owner_id': actor,
                'economy': 'NONE', 'resolution_kind': 'TYPED', 'target_kind': 'HOSTILE_ENTITY', 'range_ft': 60,
                'parameters': {'typed': {'effects': [
                    {'type': 'mark', 'mark': name, 'applies_to': 'target',
                     'duration': {'kind': 'until_end_of_your_next_turn'}} for name in ('Dawnmark', 'Smoke Trace')
                ] + [{'type': 'condition', 'condition': 'invisible', 'applies_to': 'target',
                      'duration': {'kind': 'until_end_of_your_next_turn'}}],
                    'numbers': {}, 'duration': {'kind': 'instant'}}}})
        if actor == OWNER and dependency is not None:
            aid = 'action:test.dependent'
            bundle['actor_template']['action_ids'].append(aid)
            bundle['action_catalog'].append({
                'source_definition_id': aid, 'display_name': 'Dependent maneuver', 'owner_id': actor,
                'economy': 'ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'SELF',
                'costs': [['resource:core.qi', 2]],
                'parameters': {'typed': {'requires_compiled_actions': dependency,
                    'effects': [{'type': 'temp_hp', 'flat': 3, 'formula': 'none', 'applies_to': 'self'}],
                    'numbers': {}, 'duration': {'kind': 'instant'}}}})
        if reaction is not None:
            if actor == OWNER:
                # A reaction adapter mirroring the primary-action adapter above: the printed
                # Dawnlit Rebuke Mark identity answers "when you take damage", keeping its real
                # Dawnmark-on-the-damager requirement, its real 1 Qi cost and its real printed
                # damage, so the general sight and dependency reaction contract runs through a
                # real table commit rather than a direct helper call.
                for row in bundle['typed_reactions']:
                    if row.get('feature_id') == WITNESS:
                        row.update({'kind': 'damaged', 'requires_sight': True, **reaction})
            if actor == FOE:
                # The marked, unseen bearer strikes the owner: the reaction's printed trigger.
                aid = 'action:test.unseen_strike'
                bundle['actor_template']['action_ids'].append(aid)
                bundle['action_catalog'].append({
                    'source_definition_id': aid, 'display_name': STRIKE, 'owner_id': actor,
                    'economy': 'ACTION', 'resolution_kind': 'TYPED', 'target_kind': 'HOSTILE_ENTITY', 'range_ft': 60,
                    'parameters': {'typed': {'effects': [
                        {'type': 'damage', 'applies_to': 'target', 'damage_types': ['FORCE'], 'flat': 6}],
                        'numbers': {}, 'duration': {'kind': 'instant'}}}})
        return bundle

    # Replace only this fixture's compiler reference; never patch engine methods.
    monkeypatch.setattr(support, 'compile_character', compile_setup)
    combat, table, mid = fixture(tmp_path, [WITNESS, *([SCRIPTURE] if scripture else [])])
    return combat, table, mid


def prepare(combat, table, mid, marker=OWNER):
    while table.state(mid)['menu']['actor_id'] != marker:
        assert act(table, mid, table.state(mid)['menu']['end_turn'])['status'] == 'COMMITTED'
    option = next(o for o in options(table, mid, 'Prepare unseen marked target') if o['target_ids'] == [FOE])
    assert act(table, mid, option['candidate_id'])['status'] == 'COMMITTED'
    reload(combat, mid)
    support.owner_turn(table, mid)


def drive(combat, table, mid, cid, *, actor, auto=False, use=True):
    """Drive one candidate to a commit, answering every Ask-me question the table raises.

    Returns the typed reaction prompts answered. The Dawnmark Scripture flare is a turn-start
    choice rather than the reaction under test, so it is always declined: the bearer keeps the
    Reaction the reaction test is about.
    """
    prompts, answers = [], []
    for _ in range(6):
        result = send(combat, table, mid, cid, auto, answers, actor=actor)
        if result['status'] == 'COMMITTED':
            return prompts
        prompt = result['reaction']
        wanted = str(prompt['context'].get('reaction_source_id') or '').startswith('reaction:typed.')
        if wanted:
            prompts.append(prompt)
        # A paid reaction with nothing to choose between is a plain USE/DECLINE; the turn-start
        # flare question carries its own options but is declined here either way.
        take = wanted and use
        answers.append({**prompt['context'], 'selection': 'USE' if take else 'DECLINE',
                        'option_ids': [o['id'] for o in (prompt.get('choice') or {}).get('options') or []] if take else []})
    raise AssertionError('the decision never committed')


def advance_to(combat, table, mid, actor_id):
    """End turns until the named creature is the one holding priority."""
    for _ in range(10):
        state = table.state(mid)
        if state['menu']['actor_id'] == actor_id:
            return
        drive(combat, table, mid, state['menu']['end_turn'], actor=state['menu']['actor_id'])
    raise AssertionError(f'{actor_id} turn not reached')


def bearers_strike(combat, table, mid, *, auto=False, decline=False):
    """The marked, unseen bearer strikes the owner; return the owner's Ask-me reaction prompts.

    Mirrors tests/test_hunt29_flare.py: the owner is manual, so a paid reaction of hers pauses the
    table and is answered through the ordinary decision answers, whether the striking creature's own
    turn is manual or driven by the AI.
    """
    cid = next(o['candidate_id'] for o in options(table, mid, STRIKE) if o['target_ids'] == [OWNER])
    return drive(combat, table, mid, cid, actor=FOE, auto=auto, use=not decline)


def answered(engine):
    """The owner's paid reaction was paid for and its printed damage reached the unseen bearer."""
    owner, bearer = engine.state.actors[OWNER], engine.state.actors[FOE]
    return owner.resources['resource:core.qi'] == 29 and bearer.current_hp < bearer.maximum_hp


def resolved(engine):
    return [e for e in engine.events if e.event_type == 'REACTION_RESOLVED' and e.source_definition_id == WITNESS]


@pytest.mark.parametrize('auto', [False, True])
@pytest.mark.parametrize('target_kind', ['HOSTILE_ENTITY', 'ANY_CREATURE'])
def test_owner_targeting_rule_blocks_unseen_mark_talent_after_table_reload(tmp_path, monkeypatch, auto, target_kind):
    combat, table, mid = prepared_table(tmp_path, monkeypatch, target_kind=target_kind)
    prepare(combat, table, mid)
    from combat.target_knowledge import can_see
    engine = reload(combat, mid)
    assert not can_see(engine, engine.state.actors[OWNER], engine.state.actors[FOE])
    choices = [o for o in options(table, mid, 'Sight-qualified Mark talent') if o['target_ids'] == [FOE]]
    # SOL132's targeting override requires sight for creature effects even when
    # older ability-specific targeting allowed a known Mark without sight.
    assert not choices
    if auto:
        from combat.gate4_context import build_decision_context
        policy, _ = combat.policies.for_actor(OWNER)
        assert not any(c.source_definition_id == 'action:test.sight_mark' and FOE in c.target_ids
                       for c in build_decision_context(engine, policy, for_ai=True).legal_candidates)
    from combat.typed_executor import bears_mark
    loaded = reload(combat, mid)
    assert bears_mark(loaded.state.actors[FOE], OWNER, 'Smoke Trace')
    assert loaded.state.actors[OWNER].resources['resource:core.qi'] == 30


@pytest.mark.parametrize('scripture,marker', [(False, OWNER), (True, ALLY)])
def test_unseen_target_requires_scripture_and_casters_own_marks(tmp_path, monkeypatch, scripture, marker):
    combat, table, mid = prepared_table(tmp_path, monkeypatch, scripture=scripture, marker=marker)
    prepare(combat, table, mid, marker)
    assert not options(table, mid, 'Sight-qualified Mark talent')
    assert reload(combat, mid).state.actors[OWNER].resources['resource:core.qi'] == 30


@pytest.mark.parametrize('failure', ['unknown_direction', 'stale_direction', 'beyond_sixty_feet', 'barrier', 'non_mark'])
def test_scripture_preserves_direction_range_barrier_and_talent_category(failure, tmp_path, monkeypatch):
    combat, table, mid = prepared_table(tmp_path, monkeypatch)
    prepare(combat, table, mid)
    engine = reload(combat, mid)
    owner, target = engine.state.actors[OWNER], engine.state.actors[FOE]
    action = next(a for a in engine.action_catalog.values() if a.display_name == 'Sight-qualified Mark talent')
    from combat.target_knowledge import sight_bypassed
    assert sight_bypassed(engine, owner, target, action)
    if failure == 'unknown_direction':
        engine.state.observations.clear()
    elif failure == 'stale_direction':
        target.position = target.position.model_copy(update={'x': 5})
    elif failure == 'beyond_sixty_feet':
        target.position = target.position.model_copy(update={'x': 20})
    elif failure == 'barrier':
        target.position = target.position.model_copy(update={'x': 6})
        engine.state.observations[owner.team_id][target.entity_id] = target.position
        assert sight_bypassed(engine, owner, target, action)
        engine.grid.blocked.add((4, 6))
    else:
        action = action.model_copy(update={'parameters': {'typed': {'source': 'RADIANCE_BASE_STRIKE'}}})
    assert not sight_bypassed(engine, owner, target, action)


@pytest.mark.parametrize('dependency', [['action:missing.tumble'], [], ['action:an_eui.strike']])
def test_missing_or_unowned_compiled_dependency_is_never_offered_or_charged_after_reload(tmp_path, monkeypatch, dependency):
    combat, table, mid = prepared_table(tmp_path, monkeypatch, dependency=dependency)
    assert not options(table, mid, 'Dependent maneuver')
    assert act(table, mid, options(table, mid, 'Dodge')[0]['candidate_id'])['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 30
    assert not any(e.event_type == 'RESOURCE_SPENT' for e in engine.events)


def test_available_owned_dependency_allows_payment_and_effect_after_reload(tmp_path, monkeypatch):
    combat, table, mid = prepared_table(tmp_path, monkeypatch, dependency=['action:test.prepare_unseen_mark'])
    choice = options(table, mid, 'Dependent maneuver')[0]
    assert act(table, mid, choice['candidate_id'])['status'] == 'COMMITTED'
    engine = reload(combat, mid)
    assert engine.state.actors[OWNER].resources['resource:core.qi'] == 28
    assert engine.state.actors[OWNER].temporary_hp == 3


def test_sight_qualified_mark_reaction_uses_same_owned_exception(tmp_path, monkeypatch):
    """Helper level: the shared sight reply on its own. The table-level path is covered below."""
    from combat.ext.reaction_sight import sight_allowed
    combat, table, mid = prepared_table(tmp_path, monkeypatch)
    prepare(combat, table, mid)
    engine = reload(combat, mid)
    owner, target = engine.state.actors[OWNER], engine.state.actors[FOE]
    row = {'feature_id': WITNESS, 'requires_sight': True}
    assert sight_allowed(engine, owner, target, row) is None
    assert sight_allowed(engine, engine.state.actors[ALLY], target, row) is False


def test_missing_reaction_dependency_helper_rejects_and_absent_metadata_stays_inert(tmp_path, monkeypatch):
    """Helper level: this row's readiness reply, and that no metadata means no gate.

    This says nothing about consent or spending: those happen inside the reaction machinery, which a
    direct helper call never reaches. That ordering is only observable through a real table, and is
    covered by the missing-dependency reaction test below.
    """
    from combat.ext.activation_requirements import reaction_ready
    combat, table, mid = prepared_table(tmp_path, monkeypatch)
    engine = reload(combat, mid)
    row = {'requires_compiled_actions': ['action:missing.tumble']}
    assert reaction_ready(engine, engine.state.actors[OWNER], engine.state.actors[FOE], row) is False
    assert reaction_ready(engine, engine.state.actors[OWNER], engine.state.actors[FOE], {}) is None


@pytest.mark.parametrize('strike_auto', [False, True])
def test_sight_qualified_mark_reaction_on_unseen_bearer_resolves_and_survives_reload(tmp_path, monkeypatch, strike_auto):
    """The owner's paid Mark reaction answers the unseen, Dawnmarked bearer's strike, manual Ask me."""
    combat, table, mid = prepared_table(tmp_path, monkeypatch, reaction={})
    prepare(combat, table, mid)
    advance_to(combat, table, mid, FOE)
    assert len(bearers_strike(combat, table, mid, auto=strike_auto)) == 1, \
        'The paid Mark reaction was never offered against the unseen bearer'
    engine = reload(combat, mid)
    assert answered(engine), 'The reaction must be paid for and its effect kept across a reload'
    assert resolved(engine)


@pytest.mark.parametrize('strike_auto', [False, True])
def test_sight_qualified_mark_reaction_is_never_offered_without_scripture(tmp_path, monkeypatch, strike_auto):
    """The negative: the same table without the owned sight exception, so no unseen reaction."""
    combat, table, mid = prepared_table(tmp_path, monkeypatch, scripture=False, reaction={})
    prepare(combat, table, mid)
    advance_to(combat, table, mid, FOE)
    assert bearers_strike(combat, table, mid, auto=strike_auto) == []
    engine = reload(combat, mid)
    assert not answered(engine)
    assert not resolved(engine)


@pytest.mark.parametrize('dependency', [['action:missing.tumble'], ['action:an_eui.strike']])
def test_missing_reaction_dependency_gives_no_prompt_payment_or_effect_after_reload(tmp_path, monkeypatch, dependency):
    """Sight is available, so only the missing/unowned dependency can refuse this paid reaction."""
    combat, table, mid = prepared_table(tmp_path, monkeypatch, reaction={'requires_compiled_actions': dependency})
    prepare(combat, table, mid)
    advance_to(combat, table, mid, FOE)
    assert bearers_strike(combat, table, mid) == [], 'A rejected reaction must never reach consent'
    engine = reload(combat, mid)
    assert not answered(engine)
    assert not resolved(engine)
    assert not any(e.event_type == 'RESOURCE_SPENT' and e.actor_id == OWNER for e in engine.events)


def test_available_owned_reaction_dependency_permits_prompt_payment_and_effect_after_reload(tmp_path, monkeypatch):
    """The same row with an owned, compiled dependency is offered, paid for and kept."""
    combat, table, mid = prepared_table(tmp_path, monkeypatch,
                                        reaction={'requires_compiled_actions': ['action:test.prepare_unseen_mark']})
    prepare(combat, table, mid)
    advance_to(combat, table, mid, FOE)
    assert len(bearers_strike(combat, table, mid)) == 1, 'An owned dependency must not refuse the reaction'
    engine = reload(combat, mid)
    assert answered(engine)
    assert resolved(engine)


def test_declined_mark_reaction_costs_nothing_after_reload(tmp_path, monkeypatch):
    """Ask me is a real choice: declining spends neither the Qi nor the Reaction."""
    combat, table, mid = prepared_table(tmp_path, monkeypatch, reaction={})
    prepare(combat, table, mid)
    advance_to(combat, table, mid, FOE)
    assert len(bearers_strike(combat, table, mid, decline=True)) == 1
    engine = reload(combat, mid)
    assert not answered(engine)
    assert not resolved(engine)
    assert engine.state.actors[OWNER].reaction_available
    assert not any(e.event_type == 'RESOURCE_SPENT' and e.actor_id == OWNER for e in engine.events)


def test_pre_spend_regression_exposes_unresolvable_choice_without_guard(tmp_path, monkeypatch):
    combat, table, mid = prepared_table(tmp_path, monkeypatch, dependency=['action:missing.tumble'])
    assert not options(table, mid, 'Dependent maneuver')
    callbacks = ext._HOOKS['candidate_allowed']
    monkeypatch.setitem(ext._HOOKS, 'candidate_allowed', [f for f in callbacks
        if f.__module__ != 'combat.ext.activation_requirements'])
    # A service may reuse a menu for the same state version. Registration
    # isolation needs a fresh service, not the already cached menu.
    table = support.TabletopService(support.CombatService(support.ROOT, combat.userdata_root), combat.userdata_root)
    assert options(table, mid, 'Dependent maneuver'), 'The old admission offered this unresolved paid use'


def test_owner_sight_requirement_is_independent_of_old_exception_hook(tmp_path, monkeypatch):
    combat, table, mid = prepared_table(tmp_path, monkeypatch)
    prepare(combat, table, mid)
    assert not options(table, mid, 'Sight-qualified Mark talent')
    monkeypatch.setitem(ext._HOOKS, 'target_sight_bypass', [])
    table = support.TabletopService(support.CombatService(support.ROOT, combat.userdata_root), combat.userdata_root)
    assert not options(table, mid, 'Sight-qualified Mark talent'), 'The old admission discarded the unseen Mark target'


def test_stock_saved_ai_continuation_remains_byte_identical_without_owned_metadata(monkeypatch):
    from tests.test_hunt32_inert_replay import _capture
    enabled = _capture()
    for point, callbacks in list(ext._HOOKS.items()):
        monkeypatch.setitem(ext._HOOKS, point, [f for f in callbacks if f.__module__ not in {
            'combat.ext.activation_requirements', 'combat.ext.radiance_dawnmark'}])
    assert _capture() == enabled
