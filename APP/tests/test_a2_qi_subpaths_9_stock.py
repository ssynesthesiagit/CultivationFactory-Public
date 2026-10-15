"""Six complete stock AI captures using separate registered base/head worktrees."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest
from tests.test_save_reload_equivalence import STOCK_SEEDS,_bytes_of,_first_difference

HEAD=Path(__file__).resolve().parents[1]
BASE=HEAD.parent.with_name(HEAD.parent.name+'-base')/'APP'
pytestmark=pytest.mark.skipif(not BASE.exists(), reason='Create a registered sibling <worktree>-base at ded5fcaa for the lane capture.')
EVIDENCE=Path('/var/tmp/auto-audit/fix/A2GQISUB9r3-evidence/stock')


@pytest.mark.parametrize('seed',STOCK_SEEDS)
def test_qi_subpaths_stock_identity(tmp_path,seed):
    captures=[]
    for label,app in [('base',BASE),('head',HEAD)]:
        run=subprocess.run([sys.executable,'-m','tests.wall_height_stock_capture',str(tmp_path/label),seed],
            cwd=app,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},text=True,capture_output=True,timeout=600)
        assert run.returncode==0,run.stdout[-1500:]+run.stderr[-4000:]
        captures.append(json.loads(run.stdout.splitlines()[-1]))
    encoded=[_bytes_of(c).encode() for c in captures]
    result={'seed':seed,'base':'ded5fcaa','identical':encoded[0]==encoded[1],
        'base_sha256':hashlib.sha256(encoded[0]).hexdigest(),'head_sha256':hashlib.sha256(encoded[1]).hexdigest(),
        'steps':captures[1]['steps'],'first_difference':_first_difference(*captures)}
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    (EVIDENCE/(seed+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    for label,raw in zip(['base','head'],encoded):
        with gzip.open(EVIDENCE/(seed+'.'+label+'.json.gz'),'wb') as f:f.write(raw)
    assert captures[0]['state']['terminal_result'] and captures[1]['state']['terminal_result']
    assert result['identical'],result
