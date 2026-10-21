"""Regressions for the Sol seam review's three blocking True Reflection and Paper defects.

Each check fails on the pre-fix branch:
- Warning Rustle moved the warned ally for free and picked the farthest cell itself.
- Burst Pattern ignored the recorded save ability and always used DEX.
- Fixate the Original applied an unscoped Disadvantage (and never fired at all).

Synthetic fixtures only; no private data.
"""
from dataclasses import dataclass
from types import SimpleNamespace

from combat.ext.true_reflection import SOURCE as MIRROR_SOURCE

from tests.worker2_support import ALLY, OWNER, fixture

PAPER = 'tianxia.subpath.qi.paper_cultivator.feature.'
FAMILIAR_SOURCE = PAPER + 'folded_familiar'


@dataclass
class _ECtx:
    """A plain dataclass so the handlers' dataclasses.replace() works on it."""
    engine: object
    actor: object
    target: object
    targets: list
    intent: object
    typed: dict
    source: str
    numbers: dict
    action: object


def _intent(actor_id):
    return SimpleNamespace(actor_id=actor_id, decision_id='review-decision', state_version=0,
                           intent_id='review-intent', candidate_id='review-candidate', target_ids=(),
                           reaction_decisions=(), destination=None, option_ids=())


def _respond_by_choice(engine, answers):
    """Answer each exact choice id; unanswered questions return no decision (the fallback)."""
    from combat.gate2_runtime_models import ReactionDecision
    engine._gate4_reaction_cache = {}
    seen = {}

    def respond(_engine, checkpoint, reactor_id, choice_id, *, context=None):
        seen[choice_id] = dict(context or {})
        option = answers.get(choice_id)
        if option is None:
            return None
        return ReactionDecision(checkpoint=checkpoint, reactor_id=reactor_id,
                                reaction_source_id=choice_id, selection='USE', option_ids=(option,))

    engine._reaction_decision = respond
    return seen


def _asset_actor(owner, group, name, x):
    from combat.gate2_runtime_models import Position
    return owner.model_copy(update={
        'entity_id': f'summon:{group}-review', 'display_name': name,
        'team_id': owner.team_id, 'owner_id': owner.entity_id, 'primary_combatant': False,
        'active': True, 'size_category': 'Tiny',
        'position': Position(x=x, y=owner.position.y, z=owner.position.z),
        'summon': {'owner': owner.entity_id, 'group': group,
                   'source': FAMILIAR_SOURCE, 'arrives': 'action', 'size': 'tiny'}})


# --- Finding 1: Warning Rustle spends the ally's grant and lets the player choose

def test_warning_rustle_charges_the_allys_grant_and_uses_the_players_destination(tmp_path):
    from combat import granted_movement
    from combat.ext import paper_actors
    from combat.ext.needle import checkpoint_id

    combat, table, mid = fixture(tmp_path, [], owner_features=[FAMILIAR_SOURCE], cl=18,
        battlefield_transform=lambda arena: arena.update(terrain_regions=[]))
    engine = combat._load_session(mid).engine
    owner = engine.state.actors[OWNER]
    ally = engine.state.actors[ALLY]
    ally.position = owner.position.model_copy(update={'x': owner.position.x + 5})
    ally_start = ally.position
    hound = _asset_actor(owner, 'paper_familiar_hound', 'Paper Hound', x=owner.position.x + 10)
    engine.state.actors[hound.entity_id] = hound

    intent = _intent(hound.entity_id)
    engine._active_intent = intent
    offered = granted_movement.candidates(engine, ally, paper_actors.RUSTLE_FT, intent, FAMILIAR_SOURCE)
    assert len(offered) >= 2, 'the test needs more than one legal 5-foot destination'
    # The player picks a non-default destination: the cheapest legal cell is the preferred fallback,
    # so choosing a different, costlier one proves the choice is really taken.
    ranked = sorted(offered.values(), key=lambda c: (int(c.movement_cost_ft or 0), c.candidate_id))
    picked = next(c for c in reversed(ranked) if c.movement_cost_ft > ranked[0].movement_cost_ft)

    seen = _respond_by_choice(engine, {
        'choice:needle.paper_warning_rustle_ally': ally.entity_id,
        'choice:needle.paper_warning_rustle_effect': 'move',
        'choice:needle.paper_warning_rustle_move': picked.candidate_id,
    })

    paper_actors.warning_rustle(_ECtx(engine, hound, ally, [ally], intent, {}, FAMILIAR_SOURCE, {}, None),
                                {'type': 'paper_warning_rustle'})

    # The player's chosen destination is the one the ally reached, not the farthest cell.
    assert 'choice:needle.paper_warning_rustle_move' in seen, 'the destination was never offered'
    assert ally.position == picked.destination
    assert ally.position != ranked[0].destination
    # The grant was spent: the receipt carries a real, nonzero charge, not a free teleport.
    receipts = [e for e in engine.events
                if e.event_type == 'MOVEMENT_COMMITTED' and e.actor_id == ally.entity_id]
    assert receipts, 'the move must leave a movement receipt'
    charged = receipts[-1].payload.get('granted_cost_ft')
    assert charged == picked.movement_cost_ft
    assert charged > 0
    assert receipts[-1].payload.get('forced') is not True


# --- Finding 2: Burst Pattern uses the recorded save ability

def test_burst_pattern_uses_the_recorded_save_ability(monkeypatch):
    from combat import typed_executor
    from combat.ext import true_reflection

    calls = []
    monkeypatch.setattr(typed_executor, 'run_effects', lambda ctx, effects: calls.append(effects))
    actor = SimpleNamespace(entity_id='doppel', display_name='True Doppelganger', position=(0, 0, 0),
        turns_started=0, summon={'source': MIRROR_SOURCE, 'echoed_pattern': 'Burst Pattern',
                                 'pattern_damage_type': 'FIRE', 'pattern_save': 'WIS'})
    victim = SimpleNamespace(entity_id='victim', display_name='Victim', active=True, position=(1, 0, 0))
    engine = SimpleNamespace(state=SimpleNamespace(actors={'victim': victim}),
        grid=SimpleNamespace(distance_ft=lambda a, b: 5), _append_event=lambda *a, **k: None)
    ctx = _ECtx(engine, actor, victim, [victim], None, {}, MIRROR_SOURCE, {}, None)

    true_reflection.use_pattern(ctx, {})

    assert calls, 'Burst Pattern must resolve a save against the victim'
    assert calls[0][0]['type'] == 'save'
    assert calls[0][0]['ability'] == 'WIS', 'the recorded save must reach the save, not a DEX default'
    assert 'pattern_save' not in actor.summon, 'the recorded Pattern is erased after use'


# --- Finding 3: Fixate the Original is scoped to its Doppelganger

def _fixation_engine():
    original = SimpleNamespace(entity_id='original', active=True, turns_started=0, conditions={}, summon=None)
    doppel = SimpleNamespace(entity_id='doppel', active=True,
                             summon={'source': MIRROR_SOURCE, 'original_actor': 'original'})
    other = SimpleNamespace(entity_id='other', active=True, summon=None)

    class Engine:
        def __init__(self):
            self.state = SimpleNamespace(actors={'original': original, 'doppel': doppel, 'other': other})
            self.modifiers = []

        def _add_modifier(self, target, source_id, field, operation, value, applies_to, *,
                          expires_on, source_actor_id=None, **kwargs):
            self.modifiers.append({'target': target.entity_id, 'field': field, 'value': value,
                                   'applies_to': applies_to, 'source': source_id})

        def _remove_condition(self, *args, **kwargs):
            pass

    return Engine()


def test_fixation_disadvantage_is_scoped_to_the_doppelganger_only():
    from combat.ext import true_reflection

    engine = _fixation_engine()
    # The original creature has just completed an attack against an unrelated creature.
    true_reflection.fixate_original(engine, SimpleNamespace(attacker_id='original', target_id='other'), None)

    assert len(engine.modifiers) == 1, 'the original gets exactly one fixation modifier'
    mod = engine.modifiers[0]
    assert mod['target'] == 'original'
    assert mod['field'] == 'attack_mode_vs', 'Disadvantage must be scoped to one target, not the next attack'
    assert mod['value'] == 'DISADVANTAGE:doppel'


def test_fixation_never_penalizes_an_unrelated_attacker():
    from combat.ext import true_reflection

    engine = _fixation_engine()
    true_reflection.fixate_original(engine, SimpleNamespace(attacker_id='other', target_id='original'), None)
    assert engine.modifiers == []
