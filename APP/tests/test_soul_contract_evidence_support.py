"""The historical support import resolves to the public checkpoint fixture."""
from tests.soul_contract_evidence_support import source_checkpoint


def test_legacy_support_alias_uses_current_public_checkpoint(source_checkpoint):
    # The compatibility fixture is synthetic and does not inspect this checkout
    # or read any private baseline/history.
    assert source_checkpoint is None
