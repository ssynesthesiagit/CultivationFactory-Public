"""Public recorded-material classifier for Water object consumers.

Only water_second_pass.cutting_object_hit calls it today, with its exact printed
material set. A future Pressure Lance implementation may reuse it under its own
policy; this helper grants no erosion benefit, changes no packets, and records
no success. Arguments: RuntimeObjectState and an iterable of exact material
names. Returns bool; attendance, magical/artifact status and unlisted materials
are ineligible. Missing material is inert. No name/kind inference or broad
'stone' substitution.
"""


def unattended_mundane_material(obj, materials):
    component = obj.component or {}
    if not obj.unattended or component.get('artifact') or component.get('magical'):
        return False
    material = str(component.get('material') or '').lower().replace('_', ' ').replace('-', ' ')
    return material in materials
