import pathlib, sys
import pytest
import tests.test_mgr_t15_close_whirlpool_prison as T


def test_probe(tmp_path, monkeypatch):
    seen = []
    orig_cold = T.cold
    def cold(tmp_path_, mid):
        combat, table, engine = orig_cold(tmp_path_, mid)
        foe = engine.state.actors[T.FOE]
        seen.append('MODS ' + repr([(m.target_field, m.value, getattr(m, 'expires_on', None), m.source_definition_id) for m in foe.modifiers.values()]))
        seen.append('CONDS ' + repr([c.condition_id for c in foe.conditions.values()]))
        seen.append('ROUND ' + repr((engine.state.current_actor_id, foe.current_hp, foe.maximum_hp)))
        return combat, table, engine
    monkeypatch.setattr(T, 'cold', cold)
    try:
        T.test_native_failed_start_pressure_choice_and_action_escape(tmp_path, monkeypatch, 'healing', 'MANUAL')
    except AssertionError as e:
        seen.append('ASSERT ' + str(e))
    assert False, '\n'.join(seen)
