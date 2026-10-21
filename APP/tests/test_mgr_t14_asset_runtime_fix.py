"""Regressions for the asset actor runtime review findings.

Each check fails on the pre-fix branch: the Paper actions were deliberately
unpublished, Warning Rustle resolved no effect, Folded Familiar had no creation
size, Mirror Strike lost the triggering damage type, and True Reflection stopped
at manifestation.  Table-level where the defect showed (creation, commit and
cold reload), catalogue level only where the defect was a missing compiled row.
"""
import json

import pytest

from combat.factory_compiler import compile_character
from combat.ext.paper_actors import FAMILIAR_SIZES
from combat.ext.true_reflection import PATTERNS
from tests.h1_support import sheet
from tests.worker2_support import ALLY, FOE, OWNER, candidate, fixture, reload, settle

PAPER = 'tianxia.subpath.qi.paper_cultivator.feature.'
MIRROR = 'tianxia.subpath.qi.mirror_cultivator.feature.true_reflection'


def _labels(bundle, group):
    body = next(c for c in bundle['summons'] if c['summon']['group'] == group)
    return {a['display_name'] for a in body.get('action_catalog', [])}


# --- F2: the required Paper actions are published, not removed ---------------

@pytest.mark.parametrize('feature,group,expected', [
    ('folded_familiar', 'paper_familiar_crane', 'Crane View'),
    ('folded_familiar', 'paper_familiar_fox', 'Ink Trail'),
    ('folded_familiar', 'paper_familiar_turtle', 'Folded Shelter'),
    ('paper_dragon', 'paper_dragon', 'Carry a willing creature')])
def test_required_paper_actions_stay_reachable(feature, group, expected):
    """Checklist 15: hiding an unimplemented button is not delivering the record."""
    doc = sheet([], cl=18)
    doc.setdefault('path_and_subpath', {})['path_feature_record_ids'] = [PAPER + feature]
    bundle = compile_character(doc, actor_id=OWNER)
    assert expected in _labels(bundle, group)


def test_paper_exchange_redirects_attack_to_clone_and_dismisses_afterward(tmp_path):
    from combat.ext import paper_actors

    combat, table, mid = fixture(tmp_path, [], owner_features=[PAPER + 'paper_clone'], cl=18,
        battlefield_transform=lambda arena: arena.update(terrain_regions=[]))
    engine = combat._load_session(mid).engine
    owner = engine.state.actors[OWNER]
    clone = _asset_actor(owner, 'paper-clone-test', 'Paper Clone', x=owner.position.x + 5)
    clone.summon.update(source=PAPER + 'paper_clone', group='paper_clone')
    engine.state.actors[clone.entity_id] = clone
    engine.state.actors['enemy'] = owner.model_copy(update={
        'entity_id': 'enemy', 'team_id': 'enemy-team', 'summon': None})
    engine._typed_pending_attack = {'attacker': 'enemy', 'target': owner.entity_id}

    owner_cell, clone_cell = owner.position, clone.position
    paper_actors.paper_exchange(_Ctx(engine, owner, owner), {'type': 'paper_exchange'})

    assert owner.position == clone_cell
    assert clone.position == owner_cell
    assert paper_actors.redirect_paper_exchange(engine, engine.state.actors['enemy'], owner, None) is clone
    assert clone.active, 'the Clone remains until the redirected attack resolves'
    paper_actors.finish_paper_exchange(_Ctx(engine, clone, owner), clone, True, {'type': 'attack'})
    assert not clone.active


def test_paper_exchange_destroys_clone_when_no_attack_is_pending(tmp_path):
    from combat.ext import paper_actors

    combat, table, mid = fixture(tmp_path, [], owner_features=[PAPER + 'paper_clone'], cl=18,
        battlefield_transform=lambda arena: arena.update(terrain_regions=[]))
    engine = combat._load_session(mid).engine
    owner = engine.state.actors[OWNER]
    clone = _asset_actor(owner, 'paper-clone-test', 'Paper Clone', x=owner.position.x + 5)
    clone.summon.update(source=PAPER + 'paper_clone', group='paper_clone')
    engine.state.actors[clone.entity_id] = clone

    paper_actors.paper_exchange(_Ctx(engine, owner, owner), {'type': 'paper_exchange'})

    assert owner.position == clone.position
    assert not clone.active


# --- F3: Warning Rustle is a working Reaction, not an inert Action ----------

def test_warning_rustle_is_a_perception_triggered_reaction():
    doc = sheet([], cl=18)
    doc.setdefault('path_and_subpath', {})['path_feature_record_ids'] = [PAPER + 'folded_familiar']
    bundle = compile_character(doc, actor_id=OWNER)
    hound = next(c for c in bundle['summons'] if c['summon']['group'] == 'paper_familiar_hound')
    row = next((r for r in hound['typed_reactions'] if r.get('name') == 'Warning Rustle'), None)
    assert row is not None, "Warning Rustle must be the Hound's printed Reaction"
    assert row['kind'] == 'enters_range'
    assert row['range_ft'] == 10
    assert row['effects'] == [{'type': 'paper_warning_rustle'}]
    # It is a Reaction, so it must not also be a command-menu Action.
    assert 'Warning Rustle' not in {a['display_name'] for a in hound['action_catalog']}


def test_warning_rustle_actually_warns_an_adjacent_ally(tmp_path):
    """The defect: the option was an Action with no hound branch, so commanding
    it consumed the Hound's action and resolved nothing. It must now warn a real
    adjacent ally, and that ally's chosen outcome must land on the table."""
    from combat.ext import paper_actors
    from combat.ext.needle import checkpoint_id

    combat, table, mid = fixture(tmp_path, [], owner_features=[PAPER + 'folded_familiar'], cl=18,
        battlefield_transform=lambda arena: arena.update(terrain_regions=[]))
    engine = combat._load_session(mid).engine
    owner = engine.state.actors[OWNER]
    ally = engine.state.actors[ALLY]
    ally_start = owner.position.model_copy(update={'x': owner.position.x + 5})
    ally.position = ally_start
    hound = _asset_actor(owner, 'paper_familiar_hound', 'Paper Hound', x=owner.position.x + 10)
    engine.state.actors[hound.entity_id] = hound
    before_hp = ally.current_hp

    _answer(engine, checkpoint_id(engine, 'warning_rustle_ally', hound.entity_id),
            owner.entity_id, 'choice:needle.paper_warning_rustle_ally', ally.entity_id)
    _answer(engine, checkpoint_id(engine, 'warning_rustle_choice', hound.entity_id),
            ally.entity_id, 'choice:needle.paper_warning_rustle_effect', 'move')

    paper_actors.warning_rustle(_Ctx(engine, hound, ally), {'type': 'paper_warning_rustle'})

    # The warned ally must actually have moved: the pre-fix handler had no hound
    # branch at all and resolved nothing.
    assert ally.position != ally_start


class _Ctx:
    """The minimal effect context the plug-in's own handlers read."""

    def __init__(self, engine, actor, target):
        self.engine = engine
        self.actor = actor
        self.target = target
        self.targets = [target] if target is not None else []
        self.intent = None
        self.typed = {}
        self.source = PAPER + 'folded_familiar'
        self.numbers = {}
        self.action = None

    def rider(self, text):  # pragma: no cover - the handlers under test do not ride
        raise AssertionError('unexpected rider: ' + text)


# --- F5: the printed Tiny or Small creation choice --------------------------

class _Intent:
    """The minimal stand-in ``ask`` needs: a non-None active intent."""

    def __init__(self, actor_id):
        self.actor_id = actor_id
        self.reaction_decisions = ()


def _answer(engine, checkpoint, reactor_id, choice_id, option):
    """Make the engine's own decision transport answer one exact question.

    ``ask`` returns its preferred fallback whenever nobody answers, so a test that
    only calls the handler would silently take the default and prove nothing.
    Returns the captured prompt context so a caller can inspect the offered menu.
    """
    from combat.gate2_runtime_models import ReactionDecision
    if getattr(engine, '_gate4_reaction_cache', None) is None:
        engine._gate4_reaction_cache = {}
    if getattr(engine, '_active_intent', None) is None:
        # ask() returns its fallback before consulting any transport when there is
        # no active intent; this stub only has to be present and answerable.
        engine._active_intent = _Intent(reactor_id)
    seen = {}
    decision = ReactionDecision(checkpoint=checkpoint, reactor_id=reactor_id,
                                reaction_source_id=choice_id, selection='USE',
                                option_ids=(option,))

    def respond(_engine, cp, reactor, rid, *, context=None):
        if rid == choice_id:
            seen.update(context or {})
        return decision

    engine._reaction_decision = respond
    return seen


@pytest.mark.parametrize('picked,expected', [('small', 'Small'), ('tiny', 'Tiny')])
def test_folded_familiar_creation_size_is_chosen_and_survives_reload(tmp_path, picked, expected):
    """The defect: every form was compiled size='tiny', so the printed Small
    choice could never be taken. The decision is asked once per actual creation,
    stored as a string and read by the native size/footprint authority."""
    from combat.ext import paper_actors
    from combat.ext.needle import checkpoint_id

    combat, table, mid = fixture(tmp_path, [], owner_features=[PAPER + 'folded_familiar'], cl=18,
        battlefield_transform=lambda arena: arena.update(terrain_regions=[]))
    engine = combat._load_session(mid).engine
    owner = engine.state.actors[OWNER]
    creature = _asset_actor(owner, 'paper_familiar_crane', 'Paper Crane', x=owner.position.x + 5)
    engine.state.actors[creature.entity_id] = creature
    _answer(engine, checkpoint_id(engine, 'folded_familiar_size', creature.entity_id),
            owner.entity_id, 'choice:needle.paper_familiar_size', picked)

    paper_actors.choose_familiar_size(engine, owner, creature, PAPER + 'folded_familiar')

    assert creature.summon['familiar_size'] == picked
    assert creature.summon['size'] == picked
    assert creature.size_category == expected
    # Integers and strings only: this value travels through ActorState.summon.
    assert isinstance(creature.summon['familiar_size'], str)
    # The occupied-square footprint is the native authority for that size.
    assert engine.actor_footprints[creature.entity_id] is not None


def test_folded_familiar_size_choice_is_actually_offered(tmp_path):
    """The printed decision must offer both legal sizes, not only the fallback."""
    from combat.ext import paper_actors
    from combat.ext.needle import checkpoint_id

    combat, table, mid = fixture(tmp_path, [], owner_features=[PAPER + 'folded_familiar'], cl=18,
        battlefield_transform=lambda arena: arena.update(terrain_regions=[]))
    engine = combat._load_session(mid).engine
    owner = engine.state.actors[OWNER]
    creature = _asset_actor(owner, 'paper_familiar_crane', 'Paper Crane', x=owner.position.x + 5)
    engine.state.actors[creature.entity_id] = creature
    intent = _answer(engine, checkpoint_id(engine, 'folded_familiar_size', creature.entity_id),
                     owner.entity_id, 'choice:needle.paper_familiar_size', 'small')
    seen = intent
    paper_actors.choose_familiar_size(engine, owner, creature, PAPER + 'folded_familiar')
    assert sorted(seen['needle_options']) == ['small', 'tiny']
    assert 'size' in seen.get('prompt', '').lower()


def _asset_actor(owner, group, name, x):
    """A real ActorState cloned from a live fighter, so every derived field the
    engine reads (hit points, footprint, conditions) is genuinely present."""
    from combat.gate2_runtime_models import Position
    return owner.model_copy(update={
        'entity_id': f'summon:{group}-test', 'display_name': name,
        'team_id': owner.team_id, 'owner_id': owner.entity_id, 'primary_combatant': False,
        'active': True, 'size_category': 'Tiny',
        'position': Position(x=x, y=owner.position.y, z=owner.position.z),
        'summon': {'owner': owner.entity_id, 'group': group,
                   'source': PAPER + 'folded_familiar', 'arrives': 'action', 'size': 'tiny'}})


def test_both_printed_familiar_sizes_are_legal():
    assert set(FAMILIAR_SIZES) == {'tiny', 'small'}


# --- F4: Mirror Strike keeps the triggering packet's damage type ------------

def test_mirror_strike_offers_the_triggering_packet_damage_type():
    from combat.ext import true_reflection
    from combat.gate2_runtime_models import ActorState

    class Ctx:
        actor = ActorState.model_construct(entity_id='x', summon={
            'source': true_reflection.SOURCE, 'trigger_damage_type': 'FIRE'})

    assert true_reflection.strike_damage_types(Ctx(), ['FORCE', 'PSYCHIC']) == [
        'FORCE', 'PSYCHIC', 'FIRE']


def test_mirror_strike_does_not_invent_a_damage_type():
    from combat.ext import true_reflection
    from combat.gate2_runtime_models import ActorState

    for recorded in (None, 'UNTYPED', 'FORCE'):
        class Ctx:
            actor = ActorState.model_construct(entity_id='x', summon={
                'source': true_reflection.SOURCE, 'trigger_damage_type': recorded})

        assert true_reflection.strike_damage_types(Ctx(), ['FORCE', 'PSYCHIC']) is None


# --- F1: the assigned True Reflection mechanics -----------------------------

def test_doppelganger_publishes_guard_pattern_and_intercession():
    doc = sheet([], cl=18)
    doc.setdefault('path_and_subpath', {})['path_feature_record_ids'] = [MIRROR]
    bundle = compile_character(doc, actor_id=OWNER)
    labels = _labels(bundle, 'true_doppelganger')
    assert {'Guard', 'Use Echoed Pattern'} <= labels
    body = next(c for c in bundle['summons'] if c['summon']['group'] == 'true_doppelganger')
    row = next((r for r in body['typed_reactions']
                if r.get('name') == 'Mirrored Intercession'), None)
    assert row is not None and row['kind'] == 'ally_hit' and row['range_ft'] == 10


def test_echoed_pattern_is_only_offered_when_one_was_recorded():
    doc = sheet([], cl=18)
    doc.setdefault('path_and_subpath', {})['path_feature_record_ids'] = [MIRROR]
    bundle = compile_character(doc, actor_id=OWNER)
    assert 'Use Echoed Pattern' in _labels(bundle, 'true_doppelganger')


def test_the_six_printed_patterns_are_the_only_recordable_ones():
    assert PATTERNS == ('Assault Pattern', 'Burst Pattern', 'Restraint Pattern',
                        'Shelter Pattern', 'Passage Pattern', 'Restoration Pattern')


def test_missing_intercession_attacker_does_not_penalize_an_unrelated_enemy():
    from combat.ext import true_reflection
    from combat.gate2_runtime_models import ActorState

    unrelated = ActorState.model_construct(entity_id='unrelated', active=True, team_id='enemy')
    doppelganger = ActorState.model_construct(entity_id='doppel', team_id='ally', summon={
        'source': true_reflection.SOURCE})
    class Engine:
        def __init__(self):
            self.state = type('State', (), {'actors': {'unrelated': unrelated}})()
            self.modifiers = []
        def _add_modifier(self, *args, **kwargs):
            self.modifiers.append((args, kwargs))
    class Ctx:
        actor = doppelganger
        engine = Engine()

    true_reflection.mirrored_intercession(Ctx(), {})
    assert Ctx.engine.modifiers == []


def test_unrecorded_pattern_is_inert_and_a_used_pattern_is_erased():
    """A Pattern is used once during the activation, then erased."""
    from combat.ext import true_reflection
    from combat.gate2_runtime_models import ActorState

    class Ctx:
        actor = ActorState.model_construct(entity_id='x', summon={})
        target = None

    true_reflection.use_pattern(Ctx(), {})
    assert 'echoed_pattern' not in Ctx.actor.summon


# --- F6: the stock replay wrapper actually runs -----------------------------