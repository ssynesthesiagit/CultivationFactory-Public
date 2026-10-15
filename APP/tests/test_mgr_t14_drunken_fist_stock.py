"""Six native replays compared to preserved exact-base full-capture hashes.

The public CI checkout lacks the private base Git object. These hashes were
computed from the full native captures at 8bd818c78df011c2b67145d8e33975468c3e6a75,
whose baseline/head byte equality and terminal results are retained in the lane's
stock evidence. Hash the same canonical capture; never skip a missing revision.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS, _bytes_of

BASE='8bd818c78df011c2b67145d8e33975468c3e6a75'
GOLDEN={
    'GATE4-AN-1':'93bdb2a5a856d1a7b5ffa0d5fefd6db357af0d1e9a7ef67181c4d22f78ae8e2c',
    'GATE4-LEE':'205c585659c53a8272e3cdec1f033b94fcd7219427dde37846b11b78d376afd6',
    'GATE4-TEST':'605839eed8bbd2b1d6827cd34b8f4f4ba1459c0a59d7947fc7a45ef2e9889e53',
    'LOCK5-A':'04ee289faa1ce9668a25ee23181c574d1a0a2a62c975c2e05d66881ae77bf2e9',
    'LOCK5-B':'152dbaa3de85325eea4d5ee24e5f3dcb910de15d081323e4c7012527aab9d670',
    'LOCK5-C':'55505283393d5aae4844de67c8f8a32362c161ae5a92b4500f3df1af5964d437',
}

@pytest.mark.parametrize('seed',STOCK_SEEDS)
def test_exact_base_stock(tmp_path,seed):
    app=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,'-m','tests.wall_height_stock_capture',str(tmp_path/'head'),seed],
        cwd=app,text=True,capture_output=True,timeout=600)
    assert result.returncode==0,result.stdout[-1500:]+result.stderr[-4000:]
    captured=json.loads(result.stdout.splitlines()[-1])
    encoded=_bytes_of(captured).encode()
    actual=hashlib.sha256(encoded).hexdigest()
    evidence=Path('/var/tmp/auto-audit/fix/MGR-T14-ling-reserve-drunken-fist-swaying-step-1-evidence/stock-final')
    evidence.mkdir(parents=True,exist_ok=True)
    (evidence/f'{seed}-head.json').write_bytes(encoded)
    (evidence/f'{seed}-comparison.json').write_text(json.dumps({'seed':seed,'base':BASE,
        'base_sha256':GOLDEN[seed],'head_sha256':actual,'identical':actual==GOLDEN[seed]},indent=2)+'\n')
    assert captured['state']['terminal_result']
    assert actual==GOLDEN[seed],{'base':BASE,'seed':seed,'expected':GOLDEN[seed],'actual':actual}
