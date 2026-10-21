"""ROLLREASON1F16R2 finding 1: a nested same-actor, same-reason check keeps its receipts to itself.

Synthetic engine only (no saved fight, no live server, public-CI safe). A nested check
starts from a copy of the outer frame; if the receipt list were shared, a receipt added
inside the nested check would still show on the outer roll's hover and feed after the
nested check ended.
"""
from types import SimpleNamespace

from combat.gate2_engine import Gate2Engine
from combat.roll_reasons import remember


def _receipt(effect, kind):
    return {'kind': kind, 'effect': effect, 'owner': 'Test', 'why': f'{effect} applies'}


def test_inner_check_receipt_does_not_appear_on_outer_frame():
    engine = SimpleNamespace(_d20_scopes=())
    outer_context = {'kind': 'check', 'actor_id': 'ally', 'reason': 'CHECK:test.roll', 'source_id': 'test.roll'}
    inner_context = dict(outer_context)

    with Gate2Engine.d20_scope(engine, outer_context):
        remember(engine, [_receipt('Outer Advantage', 'advantage')])
        outer_frame = engine._d20_scopes[-1]
        with Gate2Engine.d20_scope(engine, inner_context):
            remember(engine, [_receipt('Inner Disadvantage', 'disadvantage')])
            # The inner check sees the outer receipt it inherited, plus its own.
            assert [r['effect'] for r in engine._d20_scopes[-1]['mode_sources']] == [
                'Outer Advantage', 'Inner Disadvantage']
        # After the nested check ends, the outer roll lists only its own receipt.
        assert [r['effect'] for r in outer_frame['mode_sources']] == ['Outer Advantage']
        assert [r['effect'] for r in engine._d20_scopes[-1]['mode_sources']] == ['Outer Advantage']
