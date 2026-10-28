from cat1_test_support import *
def test_repeated_extraction_is_identical(tmp_path):
 import zipfile
 z=tmp_path/"overlay.zip"
 with zipfile.ZipFile(z,"w",compression=zipfile.ZIP_DEFLATED) as f:
  for p in sorted(ROOT.rglob("*")):
   if p.is_file(): f.write(p,p.relative_to(ROOT).as_posix())
 roots=[]
 for n in ("a","b"):
  d=tmp_path/n; d.mkdir()
  with zipfile.ZipFile(z) as f: f.extractall(d)
  roots.append(d)
 def digest(d):
  h=hashlib.sha256()
  for p in sorted(d.rglob("*")):
   if p.is_file(): h.update(p.relative_to(d).as_posix().encode()+b"\0"+p.read_bytes())
  return h.hexdigest()
 assert digest(roots[0])==digest(roots[1])
