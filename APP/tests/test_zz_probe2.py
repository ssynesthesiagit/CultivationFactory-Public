"""TEMPORARY diagnostic for MAINREDKARMA1 (dropped before submission)."""
import hashlib
import json
import re
from pathlib import Path

EXPECTED = '2bb7888d'


def test_probe_reading_key():
    root = Path(__file__).resolve().parents[1]
    mechanics = json.loads((root / 'authority' / 'Tianxia_Typed_Mechanics_Authority_R1.json').read_text())['mechanics']
    mechanic = mechanics['tianxia.talent.karma.return_the_sting']
    trigger = str((mechanic.get('activation') or {}).get('trigger') or '')
    entry_id = str(mechanic.get('mechanic_id'))
    rows = json.loads('{}')
    import combat.reaction_triggers as rt
    reading_rows = rt._reading_rows()
    row = reading_rows.get((entry_id, hashlib.sha256(trigger.encode()).hexdigest()))
    row_sha = next((sha for (ident, sha) in reading_rows if ident == entry_id), None)
    digest = hashlib.sha256(trigger.encode()).hexdigest()
    extra = '' if row is not None else ' ' + re.sub(r'\W', '_', trigger[20:48])
    mark = 'I%d S%d %s|%s L%d%s' % (
        int(entry_id in {ident for (ident, _sha) in reading_rows}),
        1 if digest.startswith(EXPECTED) else 0,
        digest[:6], (row_sha or '-')[:6], len(trigger), extra)
    assert mark == 'want'
