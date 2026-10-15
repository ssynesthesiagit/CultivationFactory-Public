"""Public native subpath learning and progression, shared by source providers.

Uses the existing table advancement journal. Source providers own access and
progression, while the host requires a unique source, stable printed IDs and
canonical rule hashes. No provider means no acquisition or automatic grant.
"""
from .ext import run_strict
from .journey import require


def specification(source, sheet):
    replies=run_strict('subpath_acquisition',source,sheet)
    require(len(replies)==1,'This Subpath has no unique native acquisition provider.')
    row=replies[0]
    require(isinstance(row,dict) and set(row)=={'name','legal','reasons','features'}
            and type(row['legal']) is bool and isinstance(row['reasons'],list)
            and all(isinstance(f,dict) and set(f)=={'id','minimum_cl','text_sha256'}
                    and type(f['minimum_cl']) is int and f['minimum_cl']>=1 for f in row['features']),
            'The Subpath provider must supply documented access and source-backed progression.')
    import hashlib
    from .ext.qiweaving_common import rules_text
    printed=rules_text()
    require(all(f['id'] in printed and hashlib.sha256(printed[f['id']].encode()).hexdigest()==f['text_sha256']
                for f in row['features']),'Subpath progression does not match its controlling printed source.')
    return row


def project(sheet, acquisitions):
    from copy import deepcopy
    if not acquisitions:return sheet
    out=deepcopy(sheet);paths=out.setdefault('path_and_subpath',{})
    held=paths.setdefault('path_feature_record_ids',[])
    cl=int(out['identity']['cultivation_level'])
    for acquisition in acquisitions:
        spec=specification(acquisition['id'],sheet)
        # A recorded GM override is explicit provenance, never inferred access.
        if not spec['legal'] and not acquisition.get('gm'):continue
        for feature in spec['features']:
            if cl>=feature['minimum_cl'] and feature['id'] not in held:held.append(feature['id'])
    return out
