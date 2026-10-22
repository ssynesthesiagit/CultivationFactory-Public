"""TEMPORARY diagnostic probe (not committed)."""
import pytest
import combat.typed_executor as te
import tests.test_mgr_t15_close_whirlpool_prison as T

LOG = []

def _mods(actors):
    out = []
    for aid, a in actors.items():
        for m in a.modifiers.values():
            if m.target_field == 'healing_reduction':
                out.append((aid[-8:], m.source_definition_id[-24:], m.expires_on, m.value))
    return repr(out)[:400]


def test_probe_healing(tmp_path, monkeypatch):
    orig_mod = te._modifier
    def mod(ctx, effect, field_name, value, **kw):
        r = orig_mod(ctx, effect, field_name, value, **kw)
        if field_name == 'healing_reduction':
            LOG.append('MOD ' + _mods(ctx.engine.state.actors) + ' ctxsrc=' + repr(ctx.source)[-30:])
        return r
    monkeypatch.setattr(te, '_modifier', mod)
    orig_cold = T.cold
    def cold(tp, mid):
        r = orig_cold(tp, mid)
        LOG.append('POST_COLD ' + _mods(r[2].state.actors))
        return r
    monkeypatch.setattr(T, 'cold', cold)
    try:
        T.test_native_failed_start_pressure_choice_and_action_escape(tmp_path, monkeypatch, 'healing', 'MANUAL')
        res = 'PASSED'
    except AssertionError as e:
        res = 'ASSERT ' + str(e)[:150]
    except Exception as e:
        res = 'EXC ' + type(e).__name__ + ' ' + str(e)[:200]
    pytest.fail('TRACE4 ' + ' ## '.join(LOG) + ' ### ' + res)
