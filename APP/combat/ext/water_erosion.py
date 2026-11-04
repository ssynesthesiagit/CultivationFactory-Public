"""Heaven-Falling Tsunami's Scouring Erosion, granted only by the GM's per-object decision.

Printed: "Scouring Erosion requires GM permission for a qualified unattended mundane material; no automatic Resistance
bypass or doubled damage is granted." The source's own erosion text lets the GM allow either an ordinary Resistance bypass
or double damage, so the table offers exactly those two answers, plus decline. Each struck qualifying object asks the GM
separately (gm_adjudication, including automatic turns; an unanswered legacy engine declines). Qualifying means: unattended, mundane
(not magical or an artifact), and of a mundane material. The answer is returned to combat/ext/objects.technique_used, which applies it
through object_rules.work_out: "bypass" ignores Resistance to the technique's Bludgeoning damage only; "double" doubles once.
"""
from . import hook

# Printed mundane erodible materials: Cutting Current's rope, cloth, paper, ash, salt, mud, clay, soft stone, plus the
# ordinary mundane materials the object table already carries. Mundane barriers qualify through their material too.
MUNDANE = frozenset({'cloth', 'paper', 'rope', 'ash', 'salt', 'mud', 'clay', 'packed_earth', 'soft_stone', 'crystal', 'glass', 'ice', 'wood', 'bone', 'stone', 'iron', 'steel'})
BYPASS, DOUBLE = 'bypass', 'double'


def qualifies(obj):
    component = obj.component or {}
    material = str(component.get('material') or '').lower().replace(' ', '_')
    return (bool(obj.unattended) and not obj.destroyed and not component.get('magical')
            and not component.get('artifact') and material in MUNDANE)


@hook('compile_actions')
def tsunami_gm_preview(info):
    """Both owned Tsunami shapes must ask the GM even without manual reactors."""
    source = 'TAL_WATER_HEAVEN_FALLING_TSUNAMI'
    if source not in info['owned_ids']:
        return None
    for action in info['actions']:
        typed = (action.parameters or {}).get('typed') or {}
        if typed.get('source') == source:
            typed['gm_adjudication'] = True
    return None


@hook('technique_object_modifiers')
def scouring_erosion_permission(ctx, obj, row):
    """The GM's answer for one struck object: "bypass", "double", or None (declined or not offered)."""
    if not row.get('scouring_erosion') or not qualifies(obj):
        return None
    from .needle import ask, checkpoint_id, CHOICE
    component = obj.component or {}
    name = component.get('name') or f"{component.get('kind') or getattr(obj, 'kind', None) or 'unattended object'} made of {component.get('material') or 'mundane material'}"
    picked = ask(ctx.engine, ctx.intent, checkpoint_id(ctx.engine, 'scouring_erosion', ctx.source, obj.object_id),
        ctx.actor, CHOICE + 'scouring_erosion', [BYPASS, DOUBLE], name='Scouring Erosion', automatic=False,
        allow_decline=True, default='decline', gm_adjudication=True,
        labels={BYPASS: 'Scouring Erosion: ignore ordinary Resistance to Bludgeoning', DOUBLE: 'Scouring Erosion: double damage'},
        prompt=f'GM: may {ctx.action.display_name} erode {name}? An unattended mundane {(obj.component or {}).get("material")} '
               'object. Choose the printed benefit the GM allows, or decline.')
    return picked[0] if picked else None
