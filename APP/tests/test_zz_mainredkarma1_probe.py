"""TEMPORARY diagnostic for MAINREDKARMA1 (never committed)."""
import combat.typed_reactions as tr
from tests.test_a2_karma_table import HARM, RECORD, RETURN, _Use, _prepare, _strike
from tests.worker2_support import ALLY, FOE, OWNER, fixture

KARMA = {RETURN, HARM}
SEEN = {}


def _probe(engine, target, pending):
    rows = list(getattr(engine, 'typed_reaction_rows', {}).get(OWNER, []))
    karma = [r for r in rows if str(r.get('feature_id') or '') in KARMA]
    cands = tr._ally_candidates(engine, target)
    ask = 1 if OWNER in (getattr(engine, 'typed_ask_reactors', None) or ()) else 0
    typed = 1 if OWNER in (getattr(engine, 'typed_actor_ids', None) or ()) else 0
    SEEN['sig'] = '%d.%d.%d.%d.%d' % (len(rows), len(karma), len(cands), ask, typed)
    if karma:
        row = karma[0]
        source = engine.state.actors.get(getattr(getattr(engine, '_karma_source', None) or (None, None), 1) or '')
        gates = [
            ('c', lambda: tr._can_trigger(engine, engine.state.actors[OWNER], row)),
            ('f', lambda: tr._generic_affordable(engine, engine.state.actors[OWNER], row)),
            ('r', lambda: tr._generic_in_range(engine, engine.state.actors[OWNER], source, row, subject=target, source=source)),
            ('a', lambda: tr._ally_row_ok(engine, engine.state.actors[OWNER], source, target, row)),
        ]
        for letter, gate in gates:
            try:
                ok = gate()
            except Exception as exc:
                SEEN['sig'] += '!' + letter + type(exc).__name__[:3]
                break
            if not ok:
                SEEN['sig'] += '!' + letter
                break


def test_probe_signature(tmp_path):
    original = tr._offer_ally_damaged

    def wrapper(engine, target, attacker, pending, depth, source_id):
        if 'sig' not in SEEN:
            _probe(engine, target, pending)
        return original(engine, target, attacker, pending, depth, source_id)

    tr._offer_ally_damaged = wrapper
    try:
        combat, table, mid = fixture(tmp_path, [RECORD, RETURN], cl=5, bundle_transform=_prepare)
        _strike(combat, table, mid, 'Foe strike', _Use(RECORD))
        _strike(combat, table, mid, 'Foe strike', _Use(RETURN))
    finally:
        tr._offer_ally_damaged = original
        assert SEEN.get('sig', 'none') == 'want'


def test_probe_public_inputs(tmp_path):
    import json
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    authority = root / 'authority' / 'Tianxia_Typed_Mechanics_Authority_R1.json'
    entry = {}
    if authority.exists():
        entry = ((json.loads(authority.read_text()).get('mechanics') or {})
                 .get('tianxia.talent.karma.return_the_sting') or {})
    notes = str(entry.get('notes') or '')
    trigger = str((entry.get('activation') or {}).get('trigger') or '')
    review = root / 'authority' / 'typed_mechanics' / 'reviewed_final.d' / 'sys_resources-states.json'
    combat, table, mid = fixture(tmp_path, [RECORD, RETURN], cl=5, bundle_transform=_prepare)
    engine = combat._load_session(mid).engine
    karma = [r for r in engine.typed_reaction_rows.get(OWNER, [])
             if str(r.get('feature_id') or '').startswith('tianxia.talent.karma.')]
    mark = 'a%d t%d e%d n%d r%d c%d s%d y%d tr%d' % (
        bool(entry), bool(trigger), len(entry.get('effects') or ()), notes[:1] == '[',
        review.exists(), bool(entry.get('coverage')), bool(entry.get('structure_source')),
        bool(entry.get('typing_status')), len(karma))
    assert mark == 'want'


def test_probe_trigger_reading(tmp_path):
    import json
    from pathlib import Path
    from combat import factory_compiler as fc
    from combat.reaction_triggers import classify_mechanic_all, classify_trigger
    root = Path(__file__).resolve().parents[1]
    mech = ((json.loads((root / 'authority' / 'Tianxia_Typed_Mechanics_Authority_R1.json').read_text())
             .get('mechanics') or {}).get('tianxia.talent.karma.return_the_sting') or {})
    trigger = str((mech.get('activation') or {}).get('trigger') or '')
    matches = list(classify_mechanic_all(mech) or ())
    direct = classify_trigger(trigger)
    text = str(fc._rules_text().get('tianxia.talent.karma.return_the_sting') or '')
    reach = fc._reaction_range_ft('tianxia.talent.karma.return_the_sting', mech, None, 5)
    mark = 'm%d r%d d%s x%s ft%s' % (
        len(matches), sum(1 for m in matches if getattr(m, 'runnable', False)),
        str(getattr(direct, 'kind', None))[:14],
        'P' if text.startswith('[text') else ('0' if not text else 'K'), reach)
    assert mark == 'want'


def test_probe_readings(tmp_path):
    import hashlib
    import json
    from pathlib import Path
    from combat.reaction_triggers import _reading_rows
    root = Path(__file__).resolve().parents[1]
    mech = ((json.loads((root / 'authority' / 'Tianxia_Typed_Mechanics_Authority_R1.json').read_text())
             .get('mechanics') or {}).get('tianxia.talent.karma.return_the_sting') or {})
    trigger = str((mech.get('activation') or {}).get('trigger') or '')
    mid = str(mech.get('mechanic_id') or '')
    rows = _reading_rows()
    stereotype = [sha for (ident, sha) in rows if 'return_the_sting' in str(ident)]
    mark = 'id%d sha%s rw%d rs%s n%d' % (
        bool(mid), hashlib.sha256(trigger.encode()).hexdigest()[:8], len(stereotype),
        ','.join(sorted(sha[:8] for sha in stereotype)[:2]) or '-', len(rows))
    assert mark == 'want'
