"""SHAREOFF1 proof on the base tree e5cf295e36: the old monkeypatch leaves sharing layers live.

Temporary file; not committed. Each test asserts that NO sharing layer returns a stored value
during the run that the old test called its "cold" run.
"""
from combat import ext, read_queries, senses, target_knowledge
from tests.test_ai_flight_options import FLYER, GROUND, flyer_fight


def _old_patches(monkeypatch):
    """The four monkeypatches test_aispeed2_shared_queries used to claim every layer was off."""
    monkeypatch.setattr(read_queries, "enumeration_cache", lambda engine: None)
    monkeypatch.setattr(read_queries, "memo", lambda engine, key, compute: compute())
    monkeypatch.setattr(read_queries, "invariant_query",
                        lambda engine, key, compute, refs=(): compute())
    monkeypatch.setattr(read_queries, "shared_query",
                        lambda engine, key, compute, refs=(): compute())


def test_old_monkeypatch_leaves_ext_enumeration_cache_live(tmp_path, monkeypatch):
    combat, _, mid, _ = flyer_fight(tmp_path)
    engine = combat._load_session(mid).engine
    _old_patches(monkeypatch)
    with read_queries.candidate_pass(engine):
        assert read_queries.enumeration_cache(engine) is None
        # combat/ext/__init__.py binds the real function at import time.
        assert ext.enumeration_cache(engine) is None, \
            "ext's import-time enumeration_cache still returns a live cache"


def test_old_monkeypatch_leaves_memo_stored_value(tmp_path, monkeypatch):
    combat, _, mid, _ = flyer_fight(tmp_path)
    engine = combat._load_session(mid).engine
    viewer = engine.state.actors[FLYER]
    target = engine.state.actors[GROUND]
    calls = []
    real = senses.perceives

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(senses, "perceives", spy)
    _old_patches(monkeypatch)
    with read_queries.read_frame(engine):
        target_knowledge.can_see(engine, viewer, target)
        target_knowledge.can_see(engine, viewer, target)
    assert len(calls) == 2, (
        f"can_see computed {len(calls)} time(s) for two calls: "
        "target_knowledge's import-time memo still returned a stored value")
