"""Regression for the public-CI export credential screen (lead addendum 2026-10-21).

The public exporter (tools/public_test_export.py) refuses any published file that
contains a credential-shaped assignment such as `secret = '...'`, which kept every
test importing the soul-contract plug-in local-only. The plug-in must name its
ids without that shape. Synthetic: reads only the plug-in source text.
"""
import importlib
import re
from pathlib import Path

PLUGIN_NAME = 'combat.ext.mgr_reserve_soul_collateral_contract_cultivator_sign_in_living_qi'
PLUGIN_FILE = Path(__file__).resolve().parents[1] / 'combat' / 'ext' / 'mgr_reserve_soul_collateral_contract_cultivator_sign_in_living_qi.py'
CREDENTIAL_SHAPE = re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|password|secret)\s*[=:]\s*[\"'][^\"'\r\n]{8,}[\"']")


def test_soul_contract_plugin_has_no_credential_shaped_assignment():
    assert CREDENTIAL_SHAPE.search(PLUGIN_FILE.read_text()) is None


def test_soul_contract_ids_keep_their_values_under_role_names():
    mod = importlib.import_module(PLUGIN_NAME)
    assert mod.SECRET_CONDITION_ID == 'condition:typed.soul_contract_secret'
    assert mod.SHARE_SECRET_ACTION_ID == 'action:soul_contract.share_secret'
    assert not hasattr(mod, 'SECRET')
    assert not hasattr(mod, 'SHARE_SECRET')
