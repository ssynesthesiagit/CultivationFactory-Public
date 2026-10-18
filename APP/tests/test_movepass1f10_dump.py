"""MOVEPASS1F10 evidence dump (NOT COMMITTED): writes the six stock captures for base and head to a fixed evidence dir."""
import hashlib, json, subprocess, sys
from pathlib import Path
import pytest
from tests.replay_base import replay_base_or_skip
from tests.test_save_reload_equivalence import STOCK_SEEDS, _bytes_of

APP = Path(__file__).resolve().parents[1]
OUT = Path('/var/tmp/auto-audit/fix/MOVEPASS1F10-evidence/stock')


@pytest.mark.parametrize('seed', STOCK_SEEDS)
def test_dump_stock_captures(tmp_path, seed):
    import os
    base = replay_base_or_skip()
    OUT.mkdir(parents=True, exist_ok=True)
    for arm in ('base', 'head'):
        command = [sys.executable, '-m', 'tests.wall_height_stock_capture', str(tmp_path / arm), seed]
        if arm == 'base':
            command.append(base)
        result = subprocess.run(command, cwd=APP, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
                                text=True, capture_output=True, timeout=600)
        assert result.returncode == 0, result.stdout[-1500:] + result.stderr[-4000:]
        capture = json.loads(result.stdout.splitlines()[-1])
        (OUT / f'{seed}-{arm}.json').write_bytes(_bytes_of(capture).encode())
    print('DUMPED', seed, base)
