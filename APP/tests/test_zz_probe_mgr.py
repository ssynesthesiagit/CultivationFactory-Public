"""TEMPORARY diagnostic probe (not committed)."""
import traceback
import pytest
import combat.typed_executor as te
from combat.ext import needle
from combat import ext as ext_mod
import tests.test_mgr_t15_close_whirlpool_prison as T

TRACE = '/var/tmp/mgr-t15-probe/trace.txt'

def _log(*row):
    with open(TRACE, 'a') as f:
        f.write(repr(row)[:700] + '\n')


def test_probe_healing(tmp_path, monkeypatch):
    open(TRACE, 'w').close()
    orig_ask = needle.ask
    def ask(engine, intent, checkpoint, chooser, choice_id, options, **kw):
        r = orig_ask(engine, intent, checkpoint, chooser, choice_id, options, **kw)
        if 'drowning' in str(choice_id):
            _log('ASK', choice_id, list(options), 'RETURN', r)
        return r
    monkeypatch.setattr(needle, 'ask', ask)
    orig_run = te._run_effects_in_chain
    def chain(ctx, effects):
        for e in effects:
            if isinstance(e, dict) and e.get('type') in ('healing_reduction', 'condition', 'reaction_denied', 'disadvantage'):
                _log('CHAIN', e.get('type'), e.get('applies_to'), e.get('evidence', '')[:40], 'elig_pre=', 'deferred' if e.get('deferred') else '')
        return orig_run(ctx, effects)
    monkeypatch.setattr(te, '_run_effects_in_chain', chain)
    orig_allowed = ext_mod.run_strict
    def strict(name, *a, **k):
        r = orig_allowed(name, *a, **k)
        if name == 'effect_allowed' and a and isinstance(a[1] if len(a) > 1 else None, dict) and a[1].get('type') == 'healing_reduction':
            _log('ALLOWED', r)
        return r
    monkeypatch.setattr(ext_mod, 'run_strict', strict)
    try:
        T.test_native_failed_start_pressure_choice_and_action_escape(tmp_path, monkeypatch, 'healing', 'MANUAL')
        res = 'PASSED'
    except AssertionError as e:
        res = 'ASSERT ' + str(e)
    except Exception:
        res = 'EXC ' + traceback.format_exc()[-800:]
    _log('RESULT', res)
    pytest.fail('see /var/tmp/mgr-t15-probe/trace.txt: ' + res[:200])
