"""Family field collections; legacy singular aliases remain the newest field.

One Hearth is maintained. Each paid Pavilion or once-per-scene Welcome retains
its own actual activation, center, recipients and clocks. Source-owned callers
mutate these documents only during native committed transactions.
"""


def pavilions(camp):
    return camp.get('pavilions', [camp['pavilion']] if camp.get('pavilion') else [])


def welcomes(family):
    return family.get('welcomes', [family['welcome']] if family.get('welcome') else [])


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
