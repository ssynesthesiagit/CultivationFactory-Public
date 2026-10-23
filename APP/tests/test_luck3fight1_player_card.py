"""Public-safe integrity checks for Heaven's Luck's player text and combat record.

Owner-authored prose is redacted in public exports. Keep assertions to stable
record IDs, output structure, and numeric source digests.
"""
import json
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
AUTH = APP / 'authority' / 'typed_mechanics'
KEY = 'insight.legacy-heavens-luck'
TEXT_SHA256 = 'af7829836135663aa7e829d375bbb8dee3a6cf56bc004ebaa6a022a5bf73279e'


def test_heavens_luck_player_text_and_combat_record_share_typed_identity():
    player_text = json.loads((AUTH / 'player_text.json').read_text())['records']
    feature_blocks = json.loads((APP / 'combat' / 'rules' / 'feature_blocks.d' /
                                 'a2_insights_five.json').read_text())['features']

    assert KEY in player_text
    assert isinstance(player_text[KEY], str)
    # The distinct out-of-combat allowance is once between Full Cultivation
    # Sessions and applies only to Cultivation Checks; don't regress to a
    # three-per-fight or generic roll allowance.
    assert player_text[KEY].endswith(
        'Once between Full Cultivation Sessions, when you make a Cultivation Check, '
        'you may reroll the die.\n\nYou must use the new result.'
    )
    assert KEY in feature_blocks
    assert feature_blocks[KEY]['block'] == 'insights_five'
    assert feature_blocks[KEY]['text_sha256'] == TEXT_SHA256
    # Preserve the distinct combat limit and its reset timing; the public export
    # carries this short mechanics text even though owner-authored prose is redacted.
    assert feature_blocks[KEY]['outcome'] == (
        'Up to three times each fight, reroll your attack roll or saving throw '
        'and use the new result. All three uses return at the start of each fight'
    )
