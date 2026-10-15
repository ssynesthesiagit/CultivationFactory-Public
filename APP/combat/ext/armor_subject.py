"""Public armor facts shared by Equipment armor and Helmet Discipline.

Given suits retain their owner-item UID across combat aliases and reindexing;
kit suits use their published inventory identity. Proficiency comes only from
the published owner-sheet armor list. Fitting never grants training.
"""
from . import hook

CATEGORIES = {"light", "medium", "heavy"}
HEAD_PROTECTION_KINDS = {"helmet", "mask", "armored hood", "equivalent"}


def categories_of(sheet):
    declared = (sheet.get("proficiencies") or {}).get("armor") or []
    if not isinstance(declared, list):
        raise ValueError("Armor proficiency must be a published list of categories")
    return {str(v).lower().removesuffix(" armor") for v in declared} & CATEGORIES


def item_record(item, kit, owner_items=()):
    """Resolve one inventory identity against its mundane/treasure authority."""
    from ..armour import catalog
    if item["key"] == "treasure_armor":
        return (kit.get("resolved_treasure_armor") or {}).get("chassis") or {}
    if item["key"].startswith("given."):
        index = int(item["key"].split(".")[1])
        return ((owner_items[index].get("record") or {}).get("chassis") or {})
    return catalog().get(item.get("item_id")) or {}


@hook("compile_bundle")
def armor_facts(bundle, info):
    from ..armour import catalog
    sheet = info["owner_sheet"]
    # The shared rest adapter uses the real published character, not a neutral
    # placeholder actor. This metadata grants no combat statistics or training.
    from ..factory_compiler import _scores
    scores = _scores(sheet.get("ability_scores_and_statistics") or {})
    template = bundle["actor_template"]
    bundle["preparation_abilities"] = {a.lower(): scores.get(a,
        template.get("dexterity_score", 10) if a == "DEX" else template.get("strength_score", 10) if a == "STR" else 10)
        for a in ("STR", "DEX", "CON", "INT", "WIS", "CHA")}
    proficient = categories_of(sheet)
    kit = info["kit"]
    treasures = {"treasure_armor": (kit.get("resolved_treasure_armor") or {}).get("chassis") or {}}
    treasures.update({f"given.{i}": (r.get("record") or {}).get("chassis") or {}
                      for i, r in enumerate(info["owner_items"])})
    item_uids = {f"given.{i}": r.get("item_uid", "") for i, r in enumerate(info["owner_items"])}
    # The equipped given suit is also exposed as treasure_armor by the compiler.
    # Both combat keys must resolve to the same physical suit, never the slot.
    equipped = next((r for r in info["owner_items"] if r.get("kind") == "armour" and r.get("equipped")), None)
    if equipped:
        item_uids["treasure_armor"] = equipped.get("item_uid", "")
    for item in (bundle.get("carrying") or {}).get("items") or []:
        source = treasures.get(item["key"]) or catalog().get(item.get("item_id")) or {}
        category = source.get("armor_category")
        if category in CATEGORIES:
            item.update(armor_category=category, armor_proficient=int(category in proficient),
                        armor_stealth=int(str(source.get("stealth") or "").lower() == "disadvantage"))
            if item["key"] in item_uids:
                item["item_uid"] = item_uids[item["key"]]
    # Use the compiler's effective ownership, including saved sphere grants.
    owned = list(info["owned_ids"])
    if "tianxia.sphere.equipment" in info["spheres"]:
        owned.append("EQUIPMENT_BASE_FITTED_ARMOR_DESIGNATION")
    bundle["armor_subject"] = {"proficiencies": sorted(proficient), "owned": sorted(set(owned)),
                               "armor_ease_count": owned.count("tianxia.talent.equipment.armor_ease"),
                               "fitted_key": "", "ready": 0}
    # A published suit profile may explicitly include head protection. An item
    # name, a lantern hood, or talent ownership cannot establish this fact.
    physical_keys = {i["key"] for i in bundle["carrying"]["items"] if i.get("armor_category")}
    for group in sheet.get("equipment") or []:
        profile = group.get("head_protection") or {}
        if profile.get("armor_key") in physical_keys and profile.get("kind") in HEAD_PROTECTION_KINDS:
            bundle["armor_subject"]["head_protection_key"] = profile["armor_key"]
            bundle["armor_subject"]["head_protection_kind"] = profile["kind"]
    return bundle


def bundle_of(engine, actor):
    return next((b for b in getattr(engine, "typed_bundle_documents", ()) or ()
                 if b.get("actor_id") == actor.entity_id), {})


def worn_item(bundle):
    return next((i for i in (bundle.get("carrying") or {}).get("items") or []
                 if i.get("worn") and i.get("armor_category")), None)


def armor_identity(item):
    """Durable suit identity for Equipment preparation and Helmet Discipline.

    An imported given suit without its UID cannot acquire durable preparation.
    Combat keys remain local addresses; ordinary kit identities are source keys.
    """
    return item.get("item_uid", "" if item["key"].startswith("given.") else item["key"])


def armor_key(bundle, identity, preferred=""):
    """Resolve a durable identity to a current key, preferring its worn alias."""
    items = [i for i in (bundle.get("carrying") or {}).get("items") or []
             if i.get("armor_category") and identity and armor_identity(i) == identity]
    return next((i["key"] for i in items if i.get("worn")),
                next((i["key"] for i in items if i["key"] == preferred), items[0]["key"] if items else ""))


def proficient_worn(engine, actor):
    item = worn_item(bundle_of(engine, actor))
    return bool(item and item.get("armor_proficient") and not item.get("destroyed"))


def fitted_ready(engine, actor):
    bundle = bundle_of(engine, actor)
    item = worn_item(bundle)
    state = bundle.get("armor_subject") or {}
    return bool(item and item.get("armor_proficient") and not item.get("destroyed")
                and state.get("ready") and state.get("fitted_key") == item["key"])


@hook("equipment_check_mode")
def worn_armor_check(engine, actor, ability, skill):
    """General worn-item penalty; exemptions remove this source alone."""
    if ability != "DEX" or skill != "Stealth":
        return None
    from . import run_strict
    bundle = bundle_of(engine, actor)
    item = worn_item(bundle)
    if not item or not item.get("armor_stealth") or item.get("destroyed"):
        return None
    if any(run_strict("armor_penalty_exempt", bundle, "stealth", item)):
        return None
    return "DISADVANTAGE"


@hook("compile_actions")
def requested_armor_checks(info):
    """Actual table-requested checks, not a talent's invented ability or DC.

    equipment.armor_checks records request_id, purpose, item_key, ability, dc,
    economy and optional skill. A request is source-authored encounter context;
    it grants no success, training, repair, object HP or armor creation.
    """
    from ..factory_compiler import equipment_list
    from ..gate2_runtime_models import ActionDefinition, EconomyKind
    purposes = {"clean", "oil", "relace", "patch", "seal", "dry", "safely remove"}
    ability_names = {"STR": "Strength", "DEX": "Dexterity", "CON": "Constitution", "INT": "Intelligence", "WIS": "Wisdom", "CHA": "Charisma"}
    requests = [r for group in info["owner_sheet"].get("equipment") or [] for r in group.get("armor_checks") or []]
    if not requests:
        return None
    items = {i["key"]: i for i in equipment_list(info["owner_sheet"], info["owner_items"])["items"]}
    out, seen = [], set()
    for row in requests:
        if not isinstance(row, dict) or set(row) - {"request_id", "purpose", "item_key", "ability", "skill", "dc", "economy"}:
            raise ValueError("Armor check requires a source-authored check context")
        required = {"request_id", "purpose", "item_key", "ability", "dc", "economy"}
        if not required <= row.keys() or row["purpose"] not in purposes or row["ability"] not in {"STR", "DEX", "CON", "INT", "WIS", "CHA"} \
                or type(row["dc"]) is not int or row["dc"] < 1 or row["economy"] not in {"ACTION", "BONUS_ACTION"}:
            raise ValueError("Armor check requires its actual purpose, ability, positive DC and economy")
        rid = row["request_id"]
        if not isinstance(rid, str) or not rid or not all(c.isalnum() or c in "_-" for c in rid) or rid in seen:
            raise ValueError("Armor checks require distinct stable request identities")
        seen.add(rid)
        item = items.get(row["item_key"])
        if item is None or item_record(item, info["kit"], info["owner_items"]).get("armor_category") not in CATEGORIES:
            raise ValueError("Armor maintenance must name a source-qualified physical suit")
        label = f"{row['purpose'].capitalize()} {item['name']}"
        out.append(ActionDefinition(source_definition_id=f"action:typed.{info['short']}.armor_check.{rid}",
            display_name=label, owner_id=info["actor_id"], economy=EconomyKind(row["economy"]),
            resolution_kind="TYPED", target_kind="SELF", parameters={"expected_damage": 0,
                "armor_check": dict(row), "description": f"{label}: make the requested {ability_names[row['ability']]} "
                    f"{'('+row['skill']+') ' if row.get('skill') else ''}check against DC {row['dc']}. "
                    f"Costs one {'Action' if row['economy'] == 'ACTION' else 'Bonus Action'}. Field Maintenance gives "
                    "Advantage only with proficiency in this armor's category. This check creates or restores no armor or object Hit Points.",
                "typed": {"numbers": info["numbers"], "effects": [{"type": "armor_maintenance_check", **row}],
                          "riders": [], "duration": {"kind": "instant"}}}))
    return out


@hook("preparation_committed")
def armor_committed_health(service, engine):
    """Equipment preparation uses actual committed HP, regardless of talents.

    Shared by Sleep in Armor and Helmet Discipline rest eligibility. This is a
    rest input only; it neither heals combatants nor changes fight genesis HP.
    """
    from ..preparation import PreparationStore
    for bundle in getattr(engine, "typed_bundle_documents", ()) or ():
        if "EQUIPMENT_BASE_FITTED_ARMOR_DESIGNATION" not in (bundle.get("armor_subject") or {}).get("owned", []):
            continue
        actor = engine.state.actors[bundle["actor_id"]]
        store = PreparationStore(service.userdata_root)
        with store.lock(actor.entity_id):
            state = store.read(actor.entity_id)
            if state.get("combat_hp") == actor.current_hp and state.get("combat_hp_max") == actor.maximum_hp:
                continue
            state.update(combat_hp=actor.current_hp, combat_hp_max=actor.maximum_hp)
            state["revision"] += 1
            store.write(actor.entity_id, state)
