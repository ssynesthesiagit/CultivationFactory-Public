import hashlib,json,os,subprocess,sys
from pathlib import Path
import pytest
APP=Path(__file__).resolve().parents[1]
BASELINE=os.environ.get('A2GTRA2_STOCK_BASELINE_APP')
pytestmark=pytest.mark.skipif(os.environ.get('A2GTRA2_RUN_STOCK_CAPTURES')!='1' or not BASELINE,
                              reason='opt-in stock capture check; set A2GTRA2_RUN_STOCK_CAPTURES=1 and A2GTRA2_STOCK_BASELINE_APP')
@pytest.mark.parametrize('seed',['LOCK5-A','LOCK5-B','LOCK5-C','GATE4-TEST','GATE4-AN-1','GATE4-LEE'])
def test_stock_capture(tmp_path,seed):
 captures=[]
 for label in ['base','head']:
  args=[sys.executable,'-m','tests.flightsight_capture',str(tmp_path/label),seed]
  root=Path(BASELINE) if label=='base' else APP
  r=subprocess.run(args,cwd=root,capture_output=True,text=True,timeout=900)
  assert r.returncode==0,r.stderr[-3000:]
  captures.append(json.loads(r.stdout.splitlines()[-1]))
 encoded=[json.dumps(c,sort_keys=True,separators=(',',':')).encode() for c in captures]
 report={'seed':seed,'base':'6b893779','identical':encoded[0]==encoded[1],
         'base_sha256':hashlib.sha256(encoded[0]).hexdigest(),'head_sha256':hashlib.sha256(encoded[1]).hexdigest()}
 (tmp_path/(seed+'.json')).write_text(json.dumps(report,indent=2)+'\n')
 assert report['identical'],report
