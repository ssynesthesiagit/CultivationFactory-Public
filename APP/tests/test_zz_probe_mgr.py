"""TEMPORARY diagnostic probe (not committed)."""
import pytest
import combat.typed_executor as te
from combat import ext as ext_mod
import tests.test_mgr_t15_close_whirlpool_prison as T

LOG = []

def _short(x):
    return repr(x)[:120]


def test_probe_healing(tmp_path, monkeypatch):
    orig_block = te.BLOCKS['healing_reduction']
    def block(ctx, effect):
        LOG.append('BLOCK ' + _short((effect.get('applies_to'), effect.get('duration'), effect.get('expires_on'))))
        subs = te._default_subject(ctx, effect, harmful=True)
        LOG.append('SUBS ' + _short([s.entity_id for s in subs]) + ' tg=' + _short([s.entity_id for s in ctx.targets]))
        return orig_block(ctx, effect)
    monkeypatch.setitem(te.BLOCKS, 'healing_reduction', block)
    orig_exp = te.effect_expiry
    def exp(ctx, effect, subject, **kw):
        r = orig_exp(ctx, effect, subject, **kw)
        LOG.append('EXP ' + _short((effect.get('duration'), r, kw.get('fallback'))))
        return r
    monkeypatch.setattr(te, 'effect_expiry', exp)
    try:
        T.test_native_failed_start_pressure_choice_and_action_escape(tmp_path, monkeypatch, 'healing', 'MANUAL')
        res = 'PASSED'
    except AssertionError as e:
        res = 'ASSERT ' + str(e)[:150]
    except Exception as e:
        res = 'EXC ' + type(e).__name__ + ' ' + str(e)[:200]
    pytest.fail('TRACE2 ' + ' ## '.join(LOG) + ' ### ' + res)
