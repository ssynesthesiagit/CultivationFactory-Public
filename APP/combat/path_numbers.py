"""Explicit owning-Path numeric projection for native source compilers.

path_numbers(sheet, base, modifiers, path_id, *, default_key=None,
             require_effective_cl=False) returns a copy of sealed numbers.
Only a matching explicit Path row overrides CL/key; absence preserves legacy
numbers. It grants no feature, invents no Path choice, and changes no runtime
state. Cai Clan and Lantern Keeper share this projection.
"""
from copy import deepcopy


def path_numbers(sheet,base,modifiers,path_id,*,default_key=None,require_effective_cl=False):
    result=deepcopy(base)
    rows=(sheet.get('path_and_subpath') or {}).get('paths') or []
    row=next((r for r in rows if isinstance(r,dict) and r.get('path_id')==path_id),None)
    if row is None:return result
    if require_effective_cl or 'effective_cl' in row:
        value=row['effective_cl']
        if type(value) is not int or value<1:raise ValueError('The owning Path effective CL must be a positive integer.')
        result['cl']=value
    key=row.get('key_ability') or default_key
    if key is not None:
        key=str(key).upper()[:3]
        if key not in modifiers:raise ValueError('Record the owning Path’s actual key ability modifier.')
        result['key_mod']=int(modifiers[key])
        result['attack_bonus']=int(result['pb'])+result['key_mod']
        result['save_dc']=8+result['attack_bonus']
    return result
