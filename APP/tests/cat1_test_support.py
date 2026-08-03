from __future__ import annotations
import hashlib, json, os, unicodedata
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CAT=ROOT/"catalog_authority/cat1"; DATA=CAT/"data"
def load(name): return json.loads((DATA/name).read_text(encoding="utf-8"))
def cbytes(o): return (json.dumps(o,sort_keys=True,ensure_ascii=False,separators=(",",":"))+"\n").encode()
def sha(p):
 h=hashlib.sha256()
 with p.open("rb") as f:
  for b in iter(lambda:f.read(1024*1024),b""): h.update(b)
 return h.hexdigest()
def fold(s): return unicodedata.normalize("NFKC",s).casefold()
def record_ok(r): return hashlib.sha256(cbytes({k:v for k,v in r.items() if k!="record_commitment_sha256"})).hexdigest()==r["record_commitment_sha256"]
def registry_ok(o): return hashlib.sha256(cbytes({k:v for k,v in o.items() if k!="registry_commitment_sha256"})).hexdigest()==o["registry_commitment_sha256"]
