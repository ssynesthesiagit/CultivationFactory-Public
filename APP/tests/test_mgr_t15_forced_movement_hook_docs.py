"""Public contract regression for the shared forced-movement consent hook."""
from pathlib import Path


def test_forced_movement_consent_hook_contract_is_documented():
    from combat import ext

    contract = Path(ext.__file__).read_text()
    assert 'forced_movement_consent(engine, actor, distance_ft, source, intent) -> bool | None' in contract
    assert 'False refuses it, and None abstains.' in contract
    assert 'No provider changes ordinary forced' in contract
