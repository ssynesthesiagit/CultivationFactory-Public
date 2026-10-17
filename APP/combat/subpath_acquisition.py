"""Public native subpath learning and progression, shared by source providers.

Uses the existing table advancement journal. Source providers own access and
progression, while the host requires a unique source, stable printed IDs and
canonical rule hashes. No provider means no acquisition or automatic grant.
"""
from .ext import run_strict
from .journey import require


def selected_subpaths(sheet):
    """Actual canonical Subpath selections, not inferred feature ownership."""
    block=sheet.get('path_and_subpath') or {};out=set()
    def add(value):
        if isinstance(value,str) and value.startswith('tianxia.subpath.'):out.add(value)
        elif isinstance(value,dict):
            for key in ('subpath_id','subpath_record_id'):add(value.get(key))
        elif isinstance(value,(list,tuple)):
            for item in value:add(item)
    for key in ('subpath_record_ids','subpath_record_id','subpath_ids','subpath_id','subpaths','subpath'):
        add(block.get(key))
    rows=block.get('paths') or []
    if isinstance(rows,dict):rows=list(rows.values())
    for row in rows:add(row)
    return out


def specification(source, sheet):
    replies=run_strict('subpath_acquisition',source,sheet)
    require(len(replies)==1,'This Subpath has no unique native acquisition provider.')
    row=replies[0]
    require(isinstance(row,dict) and {'name','legal','reasons','features'} <= set(row)
            and not set(row)-{'name','legal','reasons','features','effective_cl'}
            and ('effective_cl' not in row or type(row['effective_cl']) is int and row['effective_cl']>=0)
            and type(row['legal']) is bool and isinstance(row['reasons'],list)
            and all(isinstance(f,dict) and set(f)=={'id','minimum_cl','text_sha256'}
                    and type(f['minimum_cl']) is int and f['minimum_cl']>=1 for f in row['features']),
            'The Subpath provider must supply documented access and source-backed progression.')
    import hashlib
    import re
    from .ext.qiweaving_common import rules_text
    printed=rules_text()
    require(len({f['id'] for f in row['features']})==len(row['features'])
            and all(f['id'].startswith(source+'.feature.') and f['id'] in printed
                and hashlib.sha256(printed[f['id']].encode()).hexdigest()==f['text_sha256']
                and (heading:=re.search(r'^#{2,6}\s+CL(\d+)\s*[-–—]',printed[f['id']],re.M)) is not None
                and int(heading.group(1))==f['minimum_cl'] for f in row['features']),
            'Subpath progression does not match its controlling printed source.')
    reasons=[]
    for policy in run_strict('subpath_acquisition_policy',source,sheet):
        require(isinstance(policy,dict) and set(policy)=={'allowed','reason'}
                and type(policy['allowed']) is bool and type(policy['reason']) is str and bool(policy['reason']),
                'A Subpath policy must state its allowed flag and printed restriction.')
        if not policy['allowed']:reasons.append(policy['reason'])
    if reasons:row={**row,'legal':False,'policy_blocked':True,'reasons':list(dict.fromkeys([*row['reasons'],*reasons]))}
    return row


def project(sheet, acquisitions):
    from copy import deepcopy
    if not acquisitions:return sheet
    out=deepcopy(sheet);paths=out.setdefault('path_and_subpath',{})
    held=paths.setdefault('path_feature_record_ids',[])
    cl=int(out['identity']['cultivation_level'])
    for acquisition in acquisitions:
        spec=specification(acquisition['id'],out)
        require('source_features' not in acquisition or acquisition['source_features']==spec['features'],
                'The learned Subpath source changed; re-admit its canonical progression before granting features.')
        # A recorded GM override is explicit provenance, never inferred access.
        if spec.get('policy_blocked') or (not spec['legal'] and not acquisition.get('gm')):continue
        selected=paths.setdefault('subpath_record_ids',[])
        if acquisition['id'] not in selected:selected.append(acquisition['id'])
        for feature in spec['features']:
            if min(cl,spec.get('effective_cl',cl))>=feature['minimum_cl'] and feature['id'] not in held:held.append(feature['id'])
    return out


def options(sheet, mechanics):
    """Source-backed table menu; unsupported schools never become grants."""
    sources = sorted({m['subpath_id'] for m in mechanics.values() if m.get('subpath_id')})
    out = []
    for source in sources:
        if not run_strict('subpath_acquisition', source, sheet):
            continue
        spec = specification(source, sheet)
        out.append({'id': source, 'name': spec['name'], 'legal': spec['legal'], 'reasons': spec['reasons'],
                    'features': spec['features']})
    return out
