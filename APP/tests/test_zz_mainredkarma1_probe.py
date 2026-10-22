"""TEMPORARY diagnostic for MAINREDKARMA1 (never committed): log every generic-reaction gate the three Karma
reflection rows pass through, so the CI summary line names the gate that refuses them."""
import combat.typed_reactions as tr
from tests.test_a2_karma_table import GRACE_REPAID, HARM, RECORD, RETURN, _Use, _prepare, _strike
from tests.cw2_service_support import add_action, seal
from tests.worker2_support import ALLY, FOE, OWNER, fixture

KARMA = {
    'return_the_sting': RETURN,
    'harm_returned': HARM,
    'grace_repaid': GRACE_REPAID,
}
LOG = []


def _karma_row(args):
    for arg in args:
        if isinstance(arg, dict):
            feature = str(arg.get('feature_id') or '')
            for name, full in KARMA.items():
                if feature == full:
                    return name, arg
    return None, None


def _patch(name, label=None, extra=None):
    original = getattr(tr, name)

    def wrapper(*args, **kwargs):
        result = original(*args, **kwargs)
        if name == '_offer_ally_damaged':
            LOG.append('offer=%s/%s' % (args[1].entity_id.split(':')[-1], args[3]))
            return result
        what, row = _karma_row(args)
        if what is not None:
            LOG.append('%s[%s]=%s' % (label or name, what, result))
            if extra is not None:
                extra(args, row)
        return result

    setattr(tr, name, wrapper)


def _mark_detail(args, row):
    from combat.typed_executor import bears_mark

    reactor, other = args[0], args[1]
    mark = row.get('requires_mark')
    LOG.append('  bears(%s,%s)=%s mark_on=%s' % (
        getattr(other, 'entity_id', None), mark,
        bears_mark(other, reactor.entity_id, mark) if other is not None else 'no-subject', row.get('mark_on')))
    holder = reactor.turn_flags.get('_probe_conditions')
    LOG.append('  subject_conditions=%s' % (sorted(getattr(other, 'conditions', {}) or ()),))


def _setup():
    LOG.clear()
    for name, label, extra in (
            ('_offer_ally_damaged', None, None),
            ('_ally_row_ok', 'ally_row_ok', None),
            ('_can_trigger', 'can_trigger', None),
            ('_generic_affordable', 'affordable', None),
            ('_generic_in_range', 'in_range', None),
            ('_generic_mark_ok', 'mark_ok', _mark_detail),
            ('_consent', 'consent', None),
            ('_spend_generic', 'spend', None)):
        _patch(name, label, extra)


def _report():
    return ' '.join(LOG) or 'nothing'


def test_probe_return_the_sting(tmp_path):
    _setup()
    try:
        combat, table, mid = fixture(tmp_path, [RECORD, RETURN], cl=5, bundle_transform=_prepare)
        _strike(combat, table, mid, 'Foe strike', _Use(RECORD))
        _strike(combat, table, mid, 'Foe strike', _Use(RETURN))
    finally:
        assert _report() == 'clean'


def test_probe_harm_returned(tmp_path):
    _setup()
    try:
        combat, table, mid = fixture(tmp_path, [RECORD, HARM], cl=5,
                                     bundle_transform=lambda bs: _prepare(bs, heavy=20))
        _strike(combat, table, mid, 'Foe strike', _Use(RECORD))
        _strike(combat, table, mid, 'Foe strike', _Use(RECORD))
        _strike(combat, table, mid, 'Foe heavy', _Use(HARM))
    finally:
        assert _report() == 'clean'


def test_probe_grace_repaid(tmp_path):
    def prepare(bundles):
        _prepare(bundles, heavy=20)
        add_action(bundles[1], 'Ally mend', [{'type': 'healing', 'applies_to': 'target', 'flat': 5}],
                   target='ANY_CREATURE')
        seal(bundles[1])

    _setup()
    try:
        combat, table, mid = fixture(tmp_path, [RECORD, GRACE_REPAID], cl=5, bundle_transform=prepare)
        _strike(combat, table, mid, 'Foe strike', _Use(RECORD), target=OWNER)
        from tests.worker2_support import candidate, settle, turn
        turn(table, mid, OWNER)
        turn(table, mid, ALLY)
        settle(table, mid, candidate(combat, mid, 'Ally mend', target=OWNER).candidate_id, _Use(RECORD))
        turn(table, mid, FOE)
        _strike(combat, table, mid, 'Foe heavy', _Use(GRACE_REPAID), target=ALLY)
    finally:
        assert _report() == 'clean'
