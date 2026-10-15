"""Candidate query reuse preserves exact bindings and never crosses state reads."""
from combat import attack_provenance, directional_cover
from combat.gate2_runtime_models import Position
from tests.test_auto_tabik import _engine, ME, AN


def test_one_descriptor_build_per_observed_hostile_per_query(monkeypatch):
    engine, _ = _engine([])
    original = attack_provenance.ranged_attacks
    calls = []
    def counted(engine, actor):
        calls.append(actor.entity_id)
        return original(engine, actor)
    monkeypatch.setattr(attack_provenance, 'ranged_attacks', counted)
    before = engine.state.model_dump(mode='json')
    candidates = engine.legal_candidates()
    assert len([c for c in candidates if c.kind.value == 'MOVE']) > 10
    assert calls == [AN]
    assert engine.state.model_dump(mode='json') == before
    assert engine.legal_candidates() == candidates
    assert calls == [AN, AN]


def test_cached_candidates_match_uncached_after_equipment_and_catalogue_changes(monkeypatch):
    engine, _ = _engine([])
    actor = engine.state.actors[AN]
    uncached = directional_cover.tactical_cover
    for revision in range(3):
        if revision == 1:
            actor.action_ids = ()
        elif revision == 2:
            # A changed catalogue/action list must be read even without advancing
            # a state/event counter (e.g. a separate projection under construction).
            actor.action_ids = engine.state.actors[ME].action_ids
        optimized = [c.model_dump(mode='json') for c in engine.legal_candidates()]
        with monkeypatch.context() as patch:
            patch.setattr(directional_cover, 'tactical_cover',
                lambda e, a, t, p, attacks=None: uncached(e, a, t, p))
            ordinary = [c.model_dump(mode='json') for c in engine.legal_candidates()]
        assert optimized == ordinary


def test_tactical_rays_shared_but_each_attack_still_reaches_cover_hook(monkeypatch):
    from tests.test_lock_choices import install
    engine, _ = _engine([])
    actor, target = engine.state.actors[AN], engine.state.actors[ME]
    rays = directional_cover.sight_rays
    builds, observed = [], []
    def counted(*args, **kwargs):
        builds.append(1)
        return rays(*args, **kwargs)
    def cover(engine, attacker, target, context):
        observed.append(context['attack']['source_id'])
        return 5 if context['attack']['source_id'] == 'second' else 2
    monkeypatch.setattr(directional_cover, 'sight_rays', counted)
    install(monkeypatch, 'directional_cover', cover)
    attacks = [{'source_id': name, 'ranged': True, 'range_ft': 120} for name in ('first', 'second')]
    assert directional_cover.tactical_cover(engine, actor, target, Position(x=4, y=6), attacks) == 5
    assert builds == [1]
    assert observed == ['first', 'second']
