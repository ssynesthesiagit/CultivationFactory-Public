"""Review regressions for phone activation discovery and base-family identity."""
import subprocess

from combat.ext.setting_choices import is_setting_action
from tests.test_option_composition import draft_fight
from tests.hunt12_support import ME


def test_phone_draft_enabled_and_aliased_activations():
    result = subprocess.run(
        ['node', '--test', '--test-isolation=none', 'tests/mobile_option_reachability.test.mjs'],
        text=True, capture_output=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_family_metadata_distinguishes_real_activations_from_free_settings(draft_fight):
    combat, table, mid, _payload = draft_fight
    engine = combat._load_session(mid).engine
    choices = [row for family in table.state(mid)['shapes'][ME] for row in family['choices']]
    activations = [row for row in choices if row['activation']]
    assert any(row['button_id'].endswith('blossom.cultivate_bloom') for row in activations)
    assert any(not row['activation'] for row in choices)
    for row in choices:
        action = engine.action_catalog[row['button_id'].removeprefix('act:')]
        assert row['activation'] == (not is_setting_action(action))
