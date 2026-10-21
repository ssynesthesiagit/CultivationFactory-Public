"""Public recorded-material classifier for Water object consumers.

water_second_pass.cutting_object_hit passes its exact printed material set.
Pressure Lance may reuse the classifier with its separately owned policy; this
helper grants no erosion benefit, changes no packets, and records no success.
Arguments: RuntimeObjectState and an iterable of exact material names. Returns
bool; attendance, magical/artifact status and unlisted materials are ineligible.
Missing material is inert. No name/kind inference or broad 'stone' substitution.
"""


def unattended_mundane_material(obj, materials):
    component = obj.component or {}
    if not obj.unattended or component.get('artifact') or component.get('magical'):
        return False
    material = str(component.get('material') or '').lower().replace('_', ' ').replace('-', ' ')
    return material in materials
