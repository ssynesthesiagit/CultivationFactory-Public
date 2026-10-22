"""Family field collections; legacy singular aliases remain the newest field.

One Hearth is maintained. Each paid Pavilion or once-per-scene Welcome retains
its own actual activation, center, recipients and clocks. Source-owned callers
mutate these documents only during native committed transactions.

Shared helpers: qi_hearthfire_camp and qi_hearthfire_persistence import
pavilions, welcomes, keep_pavilions, keep_welcomes and hearth_identity. These
are the public shared API for the family field documents; siblings never touch
their internals.
"""


def pavilions(camp):
    return camp.get('pavilions', [camp['pavilion']] if camp.get('pavilion') else [])


def welcomes(family):
    return family.get('welcomes', [family['welcome']] if family.get('welcome') else [])


def hearth_identity(camp):
    """Camp/persistence consumers share the exact scene and Asset receipt.

    Object IDs alone are reused by real items and across encounters. Retaining
    the complete empowerment also distinguishes a replacement by the same owner.
    """
    from copy import deepcopy
    from ..asset_anchor_runtime import KEY
    obj=camp.get('native_object') or {}
    receipt=(obj.get('component') or {}).get(KEY)
    if receipt and obj.get('object_id') and camp.get('scene'):
        return {'scene':camp['scene'],'object_id':obj['object_id'],'empowerment':deepcopy(receipt)}


def welcome_uses_camp(welcome,camp):
    """A Hearth-centered field depends on its original, authenticated source."""
    identity=hearth_identity(camp)
    return bool(identity and welcome.get('center')=='hearth' and welcome.get('hearth_source')==identity)


def keep(document,singular,plural,rows):
    if rows:
        document[singular]=rows[-1]
        if len(rows)>1:document[plural]=rows
        else:document.pop(plural,None)
    else:
        document.pop(singular,None);document.pop(plural,None)


def keep_pavilions(camp,rows):
    keep(camp,'pavilion','pavilions',rows)


def keep_welcomes(family,rows):
    keep(family,'welcome','welcomes',rows)
