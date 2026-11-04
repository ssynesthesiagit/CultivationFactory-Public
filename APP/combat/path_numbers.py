"""Owning-Path numeric projection for native source compilers and explicit multi-Path sheets.

path_numbers(sheet, base, modifiers, path_id, *, default_key=None,
             require_effective_cl=False) returns a copy of sealed numbers.
Only a matching explicit Path row overrides CL/key; absence preserves legacy
numbers. It grants no feature, invents no Path choice, and changes no runtime
state. Cai Clan and Lantern Keeper share this projection.

numbers_for_compile(info, path_id) projects the compiled numbers a source's
own printed chassis uses when the sheet records that Path as its own row:
the row's effective CL (a suppressed Path borrows no other Path's chassis),
its key ability's modifier from the sheet's ability rows, and the Proficiency
Bonus, attack bonus and save DC those give.

A single-Path sheet without explicit rows keeps its ordinary compiled numbers,
so nothing changes for it. Both "compile_passives" and "compile_action" may
call this: their info mapping carries owner_sheet, numbers and the sheet's
ability rows. Two rows for one Path, or a non-integer effective CL, is a
malformed sheet rather than a silent fallback.
"""
from __future__ import annotations

from copy import deepcopy

PATH = "tianxia.path.qi_cultivation"


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


def numbers_for_compile(info, path_id=PATH):
    """The owning Path's own numbers, or the compiled numbers when it has no row."""
    numbers = dict(info["numbers"])
    sheet = info.get("owner_sheet") or {}
    rows = (sheet.get("path_and_subpath") or {}).get("paths") or []
    matches = [row for row in rows if isinstance(row, dict) and row.get("path_id") == path_id]
    if not matches:
        return numbers
    if len(matches) != 1 or type(matches[0].get("effective_cl")) is not int:
        raise ValueError("An explicit owning Path requires one integer effective CL profile")
    path = matches[0]
    cl = path["effective_cl"]
    if not 0 <= cl <= 20:
        raise ValueError("The owning Path effective CL must be from 0 through 20")
    numbers["cl"] = cl
    numbers["pb"] = int(path.get("proficiency_bonus") or (2 + max(0, cl - 1) // 4))
    key = str(path.get("key_ability") or "").upper()[:3]
    abilities = (sheet.get("ability_scores_and_statistics") or {}).get("abilities") or []
    ability = next((row for row in abilities if str(row.get("ability") or "").upper()[:3] == key), None)
    if ability is not None:
        numbers["key_mod"] = int(ability["modifier"]) if "modifier" in ability else (int(ability["score"]) - 10) // 2
        numbers["attack_bonus"] = numbers["pb"] + numbers["key_mod"]
        numbers["save_dc"] = 8 + numbers["attack_bonus"]
    return numbers
