"""Saved combat loadout compilation shared by fight creation and preparation.

Preparation must use the same physical inventory, grants and choices as a new
fight; neither surface can silently substitute the original creation kit.
"""
from .factory_compiler import compile_character
from .tabletop import ButtonStore, TabletopError
from factory_authoring.owner_items import OwnerItemStore


def compile_saved_character(service, project_id, *, held_weapons=None):
    try:
        saved = ButtonStore(service.userdata_root / "tabletop_buttons").get(project_id)
    except TabletopError:
        saved = {}
    return compile_character(
        service._factory_owner_sheet(project_id), actor_id="actor:factory." + project_id,
        owner_items=OwnerItemStore(service.userdata_root / "owner_items").items(project_id),
        powering=saved.get("powering") or {}, reaction_plan=saved.get("reactions") or None,
        granted_spheres=saved.get("granted_spheres") or None, summon_plan=saved.get("summons") or None,
        left_behind=saved.get("left_behind") or None,
        attuned=saved.get("attuned") if isinstance(saved.get("attuned"), list) else None,
        held_weapons=held_weapons)
