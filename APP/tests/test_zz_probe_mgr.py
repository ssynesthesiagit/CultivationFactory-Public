"""TEMPORARY diagnostic probe (not committed)."""
import pathlib, traceback
import pytest
import combat.typed_executor as te
import tests.test_mgr_t15_close_whirlpool_prison as T


def test_probe_healing(tmp_path, monkeypatch):
    log = []
    orig_mod = te._modifier
    def mod(ctx, *a, **k):
        r = orig_mod(ctx, *a, **k)
        blob = repr(a) + repr(k)
        if 'healing' in blob:
            log.append(('MOD', blob[:400], 'ret=' + repr(type(r).__name__)))
        return r
    monkeypatch.setattr(te, '_modifier', mod)
    orig_bh = te.BLOCKS['healing_reduction']
    def bh(ctx, effect):
        log.append(('BLOCK', repr(effect)[:300], 'target=' + str(getattr(ctx.target, 'entity_id', None)),
                    'targets=' + str([t.entity_id for t in ctx.targets])))
        orig_bh(ctx, effect)
        log.append(('BLOCK_DONE',))
    monkeypatch.setitem(te.BLOCKS, 'healing_reduction', bh)
    try:
        T.test_native_failed_start_pressure_choice_and_action_escape(tmp_path, monkeypatch, 'healing', 'MANUAL')
        res = 'INNER PASSED'
    except AssertionError as e:
        res = 'INNER ASSERT ' + str(e)
    except Exception:
        res = 'INNER EXC ' + traceback.format_exc()
    pytest.fail(res + '\n' + '\n'.join(map(str, log)))
