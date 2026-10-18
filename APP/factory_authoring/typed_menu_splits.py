"""Choose-one menu splits (owner 2026-09-26, 2026-09-28; no model logs named here, so tests may import it)."""
from __future__ import annotations

import copy
import re

from factory_authoring.typed_mechanics_merge import _coverage


_DELIVERY_TYPES = {"attack", "save", "half_damage", "spend_resource"}


def split_reaction_menu(mechanic: dict, row: dict, text: str) -> None:
    """A reaction's printed "Choose one" menu as one option each (owner 2026-09-26, step 14): the reaction row
    runs its common effects plus the one option picked (combat/factory_compiler.py _generic_reaction) instead of
    every option at once. The options came up short of the earlier typing in about half the reactions (Flowing
    Response lost its AC bonus), so an earlier-typed top-level effect no option accounts for is kept as common,
    and a reaction whose unaccounted effect sits inside an effect the options also cover is left whole."""
    import copy

    from factory_authoring.typed_mechanics import apply_cl_scaling
    from factory_authoring.typed_structure import (_all, _substantive, build_options, drop_cost_restatement, fix_misread_effects,
                                                   graft_options, has_choose_one_menu, mandatory_core, option_area)

    if not has_choose_one_menu(text):
        return
    common, options = build_options(row.get("common_effects") or [], row["options"], text)
    if len(options) < 2:
        return
    prior = mechanic["effects"]
    core = mandatory_core(prior, options)
    if _substantive(core):
        common, options = core, graft_options(core, options, text)
    kinds = lambda effects: {r.get("type") for r in _all(effects) if isinstance(r, dict)} - _DELIVERY_TYPES  # noqa: E731
    covered = kinds(common).union(*(kinds(option["effects"]) for option in options))
    carried = [r for r in prior if isinstance(r, dict) and kinds([r]) - covered]
    if any(kinds([r]) & covered for r in carried):
        return
    # The earlier typing sometimes lists one printed line twice (Staff of One's "Gain +1 AC").
    carried = [r for index, r in enumerate(carried)
               if not r.get("evidence") or (r.get("type"), r.get("evidence")) not in {(c.get("type"), c.get("evidence")) for c in carried[:index]}]
    tidy = lambda effects: fix_misread_effects(drop_cost_restatement(effects, mechanic.get("cost")), adds_to_technique=False)  # noqa: E731
    # As for actions, each option is the whole tree that runs when it is picked (build_options/graft_options put
    # the common part in it); the kept earlier-typed effects go into every option too.
    mechanic["effects"] = tidy([*common, *copy.deepcopy(carried)])
    mechanic["options"] = [{**option, "effects": tidy([*option["effects"], *copy.deepcopy(carried)])} for option in options]
    for tree in [mechanic, *mechanic["options"]]:  # the printed CL table again (audit F4)
        apply_cl_scaling(tree, text)
    for option in mechanic["options"]:
        area = option_area(option, mechanic)
        if area:
            option["area"] = area
    mechanic["coverage"] = _coverage(mechanic["effects"] or [1], mechanic["riders"])


def split_branch_menu_record(mechanic: dict, row: dict, text: str) -> None:
    """A "Choose one" menu printed inside one save or attack outcome ("Failed Save: Choose one: ...") as one option each (fight
    audit 2026-09-28; Court of the Ninth Grave applied Speed -10 and "cannot take Reactions" together). ``has_choose_one_menu``
    leaves that menu to nobody, so no split above ever ran on it and the typing put every bullet in the one outcome. Each option is
    the whole tree that runs when it is picked, as for the top-level menus, with only its own bullet in the menu's place
    (factory_authoring/typed_structure.py split_branch_menu). Left as typed: a record the options proposals or the earlier typing
    give nothing to hang the choice on."""
    from factory_authoring.typed_mechanics import apply_cl_scaling
    from factory_authoring.typed_structure import (branch_menu, drop_cost_restatement, fix_misread_effects, has_choose_one_menu,
                                                   mark_deferred, option_area, split_branch_menu)

    menu = branch_menu(text)
    if menu is None or has_choose_one_menu(text):
        return
    split = split_branch_menu(mechanic["effects"], row, text, menu, mechanic.get("riders"))
    if split is None:
        return
    usable_now = mechanic["activation"].get("economy") in ("action", "bonus_action")
    tidy = lambda effects: fix_misread_effects((mark_deferred if usable_now else list)(  # noqa: E731
        drop_cost_restatement(effects, mechanic.get("cost"))), adds_to_technique=False)
    mechanic["effects"] = tidy(split["effects"])
    mechanic["options"] = [{"label": option["label"], "effects": tidy(option["effects"]), "riders": option["riders"]} for option in split["options"]]
    mechanic["riders"] = split["riders"]
    for tree in [mechanic, *mechanic["options"]]:  # the printed CL table again (audit F4)
        apply_cl_scaling(tree, text)
    for option in mechanic["options"]:
        area = option_area(option, mechanic)
        if area:
            option["area"] = area
    mechanic["coverage"] = _coverage(mechanic["effects"] or [1], mechanic["riders"])


# Deafened (2024, owner 2026-09-26): an effect whose targets must hear the user ("one creature that can hear you").
