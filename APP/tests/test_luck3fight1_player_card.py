"""Public-safe integrity checks for Heaven's Luck's player text and combat record.

Owner-authored prose is redacted in public exports, so the assertions below
name the stable record ID, the typed feature block, a numeric source digest
and short mechanics fragments (a few words each) instead of quoting whole
sentences of owner wording.
"""
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
AUTH = APP / 'authority' / 'typed_mechanics'
KEY = 'insight.legacy-heavens-luck'
TEXT_SHA256 = 'af7829836135663aa7e829d375bbb8dee3a6cf56bc004ebaa6a022a5bf73279e'


def test_heavens_luck_player_text_and_combat_record_share_typed_identity():
    player_text = json.loads((AUTH / 'player_text.json').read_text())['records']
    # The path is written from the app directory down: the export's static
    # dependency scan resolves a literal path, and the bare file name is
    # ambiguous (the same name is also a reviewed authority record).
    feature_blocks = json.loads(
        (APP / 'combat/rules/feature_blocks.d/a2_insights_five.json').read_text())['features']

    assert KEY in player_text
    assert isinstance(player_text[KEY], str)
    text = player_text[KEY]
    # The combat limit: three rerolls of a saving throw or attack roll per fight,
    # and all three uses come back at the start of the next fight.
    assert 'Three times during each fight' in text
    assert 'saving throw or attack roll' in text
    assert 'All three uses return' in text
    assert 'start of each fight' in text
    # The distinct out-of-combat allowance is once between Full Cultivation
    # Sessions and applies only to Cultivation Checks; it is stated after the
    # fight limit, so it is never read as a fourth fight use.
    assert 'Once between Full Cultivation Sessions' in text
    assert 'Cultivation Check' in text
    assert text.index('Once between Full Cultivation Sessions') > text.index(
        'Three times during each fight')
    # Exactly two reroll allowances: one per fight and one between sessions.
    assert text.count('reroll the die') == 2
    # The old wording that put a Cultivation Check under the fight limit is gone.
    assert 'Cultivation Check, saving throw, or attack roll' not in text
    assert KEY in feature_blocks
    assert feature_blocks[KEY]['block'] == 'insights_five'
    assert feature_blocks[KEY]['text_sha256'] == TEXT_SHA256
    # Preserve the distinct combat limit and its reset timing; the public export
    # carries this short mechanics text even though owner-authored prose is redacted.
    outcome = feature_blocks[KEY]['outcome']
    assert 'Up to three times each fight' in outcome
    assert 'saving throw' in outcome
    assert 'start of each fight' in outcome
