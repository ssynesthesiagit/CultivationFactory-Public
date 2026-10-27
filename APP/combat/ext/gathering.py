"""Harvesting and Gathering in the journey: Gathering Checks, Harvest Lots, Read the Sign, Seal the Essence.

The printed sphere is a field and downtime craft, not a combat action, so it runs in the journey beside Thread and
Alchemy. Source of truth is the printed text (authority/typed_mechanics/rules_text.json); the numbers and the talents
that refine each procedure are data in combat/rules/gathering.json, read by feature id, never by an ability name here.

* Source: the GM admits a ``harvest_source`` -- a material source plus a ``harvest`` block (Harvest DC, rarity,
  category, hazard, facts, ...). "This sphere does not create Lots from nothing": every Lot is taken from one.
* ``clean_harvest``: Gathering Check (d20 + Proficiency Bonus + key ability modifier, the sheet's ``key_mod``) against
  the Harvest DC; the printed margin table decides the Lots, their quality, the benefits, the hazard. A method
  (Jade Knife, Sovereign Clean Cut, Root-Left-Alive, Source-Sparing, Quick Field Harvest) is a named row of the rules
  data that refines the table; gates (beast cores) name the talent a source needs.
* ``read_the_sign`` reveals up to three of the source's facts (one incomplete fact on a failure) and may be recorded in
  the Field Ledger, whose recorded sites give Advantage on the first check there.
* ``seal_essence`` seals up to Proficiency Bonus + key modifier Lots (minimum 1); the stable duration follows the
  character's Cultivation Level.

Shared helpers used: material_ledger (sources, holdings, take; the journey's single locked atomic commit). Consumers of
this module: the journey command/option/admission hooks below only. Every roll is a DeterministicRollAuthority roll
whose counter is saved, so cold replay repeats it. Hidden facts (DC, hazard, facts) stay in the shared source row,
which material_ledger's journey_view never sends to a player.
"""
from __future__ import annotations

from itertools import combinations

import json
from pathlib import Path

from . import hook
from . import material_ledger as ledger
from ..journey import integer, require

RULES_PATH = Path(__file__).resolve().parents[1] / "rules" / "gathering.json"
_CACHE: dict = {}
CP = {"qi": "resource:core.qi", "stamina": "resource:core.stamina", "resonance": "resource:core.resonance"}
HARVEST_KEYS = {"dc", "rarity", "category", "hazard", "facts", "sign_dc", "perfect", "living", "destructive", "prepared"}
TIERS = ("nat1", "fail_gt5", "fail_le5", "success", "plus5", "plus10")


def rules() -> dict:
    mtime = RULES_PATH.stat().st_mtime_ns
    if _CACHE.get("mtime") != mtime:
        _CACHE.update(mtime=mtime, data=json.loads(RULES_PATH.read_text(encoding="utf-8")))
    return _CACHE["data"]


def tier_of(natural: int, total: int, dc: int) -> str:
    """The printed margin table: a natural 1 is its own row; otherwise success/failure by 5 and by 10."""
    if natural == 1:
        return "nat1"
    margin = total - dc
    return ("plus10" if margin >= 10 else "plus5" if margin >= 5 else "success" if margin >= 0
            else "fail_le5" if margin >= -5 else "fail_gt5")


def _has(session, aid, feature) -> bool:
    return ledger.owned(session, aid, feature)


def _numbers(session, aid) -> dict:
    return ledger.numbers(session, aid)


def _learning(session, aid) -> dict:
    return session.state["actors"][aid].setdefault("gathering_learning", {})


def _fits(row: dict, harvest: dict) -> bool:
    return (not row.get("rarities") or harvest["rarity"] in row["rarities"]) \
        and (not row.get("categories") or harvest["category"] in row["categories"])


def _validated(block) -> dict:
    data = rules()
    require(isinstance(block, dict) and {"dc", "rarity", "category"} <= set(block) <= HARVEST_KEYS,
            "Record the Harvest DC, rarity and category of the source (and only the typed harvest fields).")
    require(integer(block["dc"], 1) and block["rarity"] in data["rarities"] and block["category"] in data["categories"],
            "Choose a whole Harvest DC, a known rarity and a known category.")
    facts = block.get("facts", [])
    require(isinstance(facts, list) and len(facts) <= 12 and all(isinstance(f, str) and 0 < len(f) <= 400 for f in facts),
            "Record the source's facts as short text lines.")
    require(isinstance(block.get("hazard", ""), str) and len(block.get("hazard", "")) <= 400, "Record the hazard as text.")
    require(block.get("sign_dc") is None or integer(block["sign_dc"], 1), "Record the Read the Sign DC as a whole number.")
    for flag in ("perfect", "living", "destructive", "prepared"):
        require(type(block.get(flag, False)) is bool, f"Record {flag} as true or false.")
    return {"hazard": "", "facts": [], "sign_dc": None, "perfect": False, "living": False, "destructive": False,
            "prepared": False, **block, "yield_reduced": False}


@hook("journey_admission")
def admit_source(session, aid, kind, payload, reason):
    """A harvest source is a material source whose typed ``harvest`` block says how it is harvested."""
    if kind != "harvest_source":
        return None
    require(isinstance(payload, dict) and "harvest" in payload, "Record the harvest block of the source.")
    block = _validated(payload["harvest"])
    rest = {key: value for key, value in payload.items() if key != "harvest"}
    require(rest.get("kind") == "raw_material" and rest.get("unit") == "lot", "A harvest source holds raw material counted in lots.")
    ledger.admit(session, aid, "material_source", rest, reason)
    ledger.sources(session)[rest["id"]]["harvest"] = block
    return True


def _cp_resource(session, aid) -> str:
    return CP[str(_numbers(session, aid).get("primary", "qi")).lower()]


def _spend(session, aid, amount: int) -> None:
    resource = _cp_resource(session, aid)
    actor = session.state["actors"][aid]
    require(actor["resources"].get(resource, 0) >= amount, f"This needs {amount} Cultivation Point(s) you do not have.")
    actor["resources"][resource] -= amount
    session.emit("HARVEST_PAID", aid, resource_id=resource, amount=amount)


def _roll(session, aid, kind: str, bonus: int, mode: str):
    from ..gate2_rolls import DeterministicRollAuthority

    actor = session.state["actors"][aid]
    roller = DeterministicRollAuthority(session.state["journey_id"] + ":gathering")
    store = actor.setdefault("material_preparation", {})
    roller.counter = store.get("gathering_roll_counter", 0)
    roll = roller.d20(modifier=bonus, actor_id=aid, reason="CHECK:Gathering:" + kind, mode=mode)
    store["gathering_roll_counter"] = roller.counter
    return roll


def _check_parts(session, aid, kind: str, harvest: dict, source_id: str, *, disadvantage: bool = False):
    """(bonus, mode, sites_used): the sheet's modifier, the highest non-stacking bonus per group, Advantage sources."""
    data = rules()
    numbers = _numbers(session, aid)
    bonus = int(numbers.get("pb", 0)) + int(numbers.get("key_mod", 0))
    groups: dict[str, int] = {}
    for feature, row in data["check_bonus"].items():
        if kind in row["checks"] and _has(session, aid, feature):
            if row.get("requires_harvest_tools"):
                tools = ledger.holdings(session, aid).values()
                if not any(tool.get("kind") == "harvest_tool" and tool.get("quantity", 0) > 0 for tool in tools):
                    continue
            groups[row["group"]] = max(groups.get(row["group"], 0), int(row["value"]))
    bonus += sum(groups.values())
    advantages = []
    for feature, row in data["advantage"].items():
        if kind in row["checks"] and _fits(row, harvest) and _has(session, aid, feature):
            advantages.append(feature)
    learning = _learning(session, aid)
    site = learning.get("sites", {}).get(source_id)
    if site is not None and learning.get("last_source") not in (None, source_id):
        site["used"] = 0
    learning["last_source"] = source_id
    if site is not None and not site["used"] and kind in data["ledger"]["advantage_checks"]:
        advantages.append("field_ledger")
    mode = "NORMAL" if bool(advantages) == disadvantage else ("ADVANTAGE" if advantages else "DISADVANTAGE")
    return bonus, mode, "field_ledger" in advantages


def _source(session, aid, source_id):
    source = ledger.sources(session).get(source_id)
    require(source is not None and "harvest" in source and aid in source["known_to"]
            and (not source.get("exclusive_to") or source["exclusive_to"] == aid),
            "Choose a harvest source you actually know.")
    require(not session.state["actors"][aid]["incapacitated"], "An incapacitated creature cannot gather.")
    return source


def _method(session, aid, name, source):
    data = rules()["methods"]
    require(name in data, "Choose a printed harvest method.")
    method, harvest = data[name], source["harvest"]
    if method.get("requires"):
        require(_has(session, aid, method["requires"]), "You have not learned that method.")
    require(not method.get("rarities") or harvest["rarity"] in method["rarities"], "That method does not fit this rarity.")
    require(not method.get("categories") or harvest["category"] in method["categories"], "That method does not fit this material.")
    require(not method.get("living_only") or harvest["living"], "That method works on a living source.")
    return method


def _gate(session, aid, harvest):
    for row in rules()["gates"]:
        if _fits(row, harvest):
            require(_has(session, aid, row["requires"]), "Harvesting this needs a talent you have not learned.")


def _quality(base: str, tier: str, method: dict) -> str:
    """The Lot quality a method's rows give for a tier (the base table's quality when it names none)."""
    over = method.get("tiers", {})
    if tier == "fail_le5":
        return over.get("fail_le5", base)
    if tier in ("plus5", "plus10") and "plus5" in over:
        return over["plus5"]
    return over.get("success", base)


def _manual_benefit_sets(session, aid, harvest, source, method):
    """All printed margin-benefit choices, for the human journey menu."""
    available = []
    if source["remaining"] > 1:
        available.append("extra_lot")
    if not method.get("spares_source"):
        available.append("spare_source")
    if len(_learning(session, aid).get("facts", {}).get(source["id"], [])) < len(harvest["facts"]):
        available.append("extra_fact")
    if harvest["hazard"]:
        available.append("avoid_hazard")
    available.append("pure")
    return [list(pick) for count in (1, 2) for pick in combinations(available, count)]


def _auto_benefits(session, aid, harvest, source, count, spared_by_method) -> list[str]:
    left = source["remaining"]
    picks = []
    if session.state["actors"][aid]["control_mode"] != "LOCAL_AUTO":
        return picks
    for benefit in rules()["benefits"]:
        if len(picks) == count:
            break
        if benefit == "extra_lot" and left < 2:
            continue
        if benefit == "spare_source" and spared_by_method:
            continue
        if benefit == "extra_fact" and len(_learning(session, aid).get("facts", {}).get(source["id"], [])) >= len(harvest["facts"]):
            continue
        picks.append(benefit)
    return picks


@hook("journey_command")
def command(session, aid, kind, payload):
    if kind == "clean_harvest":
        return _clean_harvest(session, aid, payload)
    if kind == "read_the_sign":
        return _read_the_sign(session, aid, payload)
    if kind == "seal_essence":
        return _seal(session, aid, payload)
    return None


def _clean_harvest(session, aid, payload):
    data = rules()
    require(_has(session, aid, data["base"]["clean_harvest"]), "Only a Harvesting and Gathering character can Clean Harvest.")
    require(set(payload) <= {"source", "method", "benefits", "pay_cp", "save_source", "on_fail", "perfect", "extra_lot"} and "source" in payload,
            "Choose a source, and optionally a method, benefits and its printed choices.")
    source = _source(session, aid, payload["source"])
    harvest = source["harvest"]
    require(source["remaining"] > 0, "That source has no material left.")
    _gate(session, aid, harvest)
    name = payload.get("method", "standard")
    method = _method(session, aid, name, source)
    # Quick Field Harvest: Disadvantage unless 1 CP is paid or the source is already prepared, exposed, dead or stabilized.
    quick_disadvantage = bool(method.get("disadvantage_unless")) and not harvest["prepared"] and not payload.get("pay_cp")
    if method.get("pay_cp"):
        _spend(session, aid, method["pay_cp"])
    elif method.get("disadvantage_unless") and payload.get("pay_cp") and not harvest["prepared"]:
        _spend(session, aid, method["disadvantage_unless"]["pay_cp"])
        quick_disadvantage = False
    dc = harvest["dc"] + int(method.get("dc_delta", 0))
    bonus, mode, used_site = _check_parts(session, aid, "clean_harvest", harvest, source["id"], disadvantage=quick_disadvantage)
    roll = _roll(session, aid, "clean_harvest", bonus, mode)
    if used_site:
        _learning(session, aid)["sites"][source["id"]]["used"] = 1
    tier = tier_of(roll.natural_result, roll.total, dc)
    seconds = method.get("seconds_by_rarity", {}).get(harvest["rarity"], data["seconds"]["clean_harvest"])
    session.emit("HARVEST_CHECK", aid, source_id=source["id"], method=name, dc=dc, tier=tier, mode=mode,
                 roll=roll.model_dump(mode="json"))
    qualities = _lots_for(session, aid, source, harvest, method, tier, payload)
    if tier == "nat1" or (tier == "fail_gt5" and not qualities.get("saved") and not qualities.get("spared")):
        source["remaining"] -= 1
    taken = 0
    for quality in qualities["lots"]:
        if source["remaining"] <= 0:
            break
        row = ledger.take(session, aid, source["id"], 1)
        row["lot"] = {"quality": quality, "rarity": harvest["rarity"], "category": harvest["category"], "sealed": 0}
        taken += 1
    if qualities["lots"] and not qualities["spared"]:
        harvest["yield_reduced"] = True
    if tier == "nat1" and harvest["hazard"]:
        session.emit("HARVEST_HAZARD", aid, source_id=source["id"], hazard=harvest["hazard"])
    session.emit("HARVEST_RESOLVED", aid, source_id=source["id"], tier=tier, lots=qualities["lots"][:taken],
                 benefits=qualities["benefits"], source_survives=int(qualities["spared"]), hazard_avoided=int("avoid_hazard" in qualities["benefits"]))
    session.tick(seconds)
    return True


def _lots_for(session, aid, source, harvest, method, tier, payload) -> dict:
    """The printed outcome of one tier: Lot qualities, chosen benefits, whether the source survives."""
    data = rules()
    out = {"lots": [], "benefits": [], "spared": bool(method.get("spares_source")), "saved": False}
    if tier == "nat1":
        return out
    if tier == "fail_gt5":
        if method.get("fail_gt5_may_save_source") and payload.get("save_source"):
            out.update(saved=True, spared=True)
        elif method.get("fail_choice"):
            choice = payload.get("on_fail", "no_lot")
            require(choice in method["fail_choice"], "Choose gaining no Lot or harming the source.")
            out["spared"] = choice == "no_lot"
        return out
    if tier == "fail_le5":
        if method.get("fail_choice"):
            choice = payload.get("on_fail", "no_lot")
            require(choice in method["fail_choice"], "Choose gaining no Lot or harming the source.")
            out["spared"] = choice == "no_lot"
            if choice == "no_lot":
                return out
        out["lots"] = [_quality("bruised", "fail_le5", method)]
        if method.get("lots_delta"):
            out["lots"] = out["lots"][:max(0, len(out["lots"]) + method["lots_delta"])]
        return out
    base = "normal"
    sovereign_beast = harvest["category"] in ("beast_core", "beast_remains") and harvest["rarity"] in ("very_rare", "legendary") \
        and _has(session, aid, "tianxia.talent.harvesting_gathering.sovereign_beast_dressing")
    if sovereign_beast and tier in ("plus5", "plus10"):
        base = "pure"
    perfect = tier == "plus10" and harvest["perfect"] and payload.get("perfect", True)
    wanted = 0 if perfect else (1 if tier == "plus5" else 2 if tier == "plus10" else 0)
    benefits = payload.get("benefits")
    if benefits is None:
        benefits = _auto_benefits(session, aid, harvest, source, wanted, out["spared"])
    require(isinstance(benefits, list) and len(set(benefits)) == len(benefits)
            and all(b in data["benefits"] for b in benefits), "Choose distinct printed benefits.")
    # The menu commits the check and selected priorities together. Higher-margin choices
    # are resolved from that same selection without rolling the harvest twice.
    benefits = benefits[:wanted]
    lots = ["perfect"] if perfect else [_quality(base, tier, method)]
    for benefit in benefits:
        if benefit == "extra_lot":
            require(source["remaining"] > len(lots), "The source does not have enough material for another Lot.")
            lots.append("normal")
        elif benefit == "pure":
            lots[0] = "pure" if lots[0] in ("bruised", "normal") else lots[0]
        elif benefit == "spare_source":
            out["spared"] = True
        elif benefit == "extra_fact":
            _reveal(session, aid, source, 1)
    out["benefits"] = list(benefits)
    for feature, row in data["extra_lot_at_plus5"].items():
        if tier in ("plus5", "plus10") and _fits(row, harvest) and _has(session, aid, feature) and payload.get("extra_lot", True) \
                and source["remaining"] > len(lots):
            lots.append("normal")
            out["benefits"].append("extra_lot:" + feature)
    if method.get("plus5_pure_lot") and tier in ("plus5", "plus10") and source["remaining"] > len(lots):
        lots.append("pure")
    for feature, row in data["survives_at_plus5"].items():
        if tier in ("plus5", "plus10") and _fits(row, harvest) and _has(session, aid, feature) and not harvest["destructive"]:
            out["spared"] = True
    if method.get("lots_delta"):
        lots = lots[:max(0, len(lots) + method["lots_delta"])]
    out["lots"] = lots
    return out


def _reveal(session, aid, source, count: int) -> list[str]:
    facts = source["harvest"]["facts"]
    known = _learning(session, aid).setdefault("facts", {}).setdefault(source["id"], [])
    new = facts[len(known):len(known) + count]
    known.extend(new)
    return new


def _read_the_sign(session, aid, payload):
    data = rules()
    require(_has(session, aid, data["base"]["read_the_sign"]), "Only a Harvesting and Gathering character can Read the Sign.")
    require(set(payload) <= {"source", "record", "replace"} and "source" in payload, "Choose a source to read.")
    source = _source(session, aid, payload["source"])
    harvest = source["harvest"]
    require(harvest["sign_dc"] is not None, "The GM has not set a Read the Sign DC for this source.")
    bonus, mode, used_site = _check_parts(session, aid, "read_the_sign", harvest, source["id"])
    roll = _roll(session, aid, "read_the_sign", bonus, mode)
    if used_site:
        _learning(session, aid)["sites"][source["id"]]["used"] = 1
    natural = roll.natural_result
    success = roll.total >= harvest["sign_dc"]
    if success:
        learned = _reveal(session, aid, source, 3)
    else:
        learned = []
        if len(_learning(session, aid).setdefault("facts", {}).get(source["id"], [])) < len(harvest["facts"]):
            incomplete = _learning(session, aid).setdefault("incomplete_facts", {}).setdefault(source["id"], [])
            facts = harvest["facts"]
            clue = facts[len(_learning(session, aid).setdefault("facts", {}).get(source["id"], []))]
            incomplete.append(clue[:max(1, len(clue) // 2)].rstrip() + "…")
    mishap = (not success) and roll.total <= harvest["sign_dc"] - 5
    session.emit("HARVEST_SIGN", aid, source_id=source["id"], dc=harvest["sign_dc"], success=int(success), learned=len(learned),
                 incomplete=int(not success), mishap=int(mishap), natural=natural, roll=roll.model_dump(mode="json"))
    if success and payload.get("record", False) and _has(session, aid, data["ledger"]["feature"]):
        _record_site(session, aid, source["id"], payload.get("replace"))
    session.tick(data["seconds"]["read_the_sign"])
    return True


def _site_cap(session, aid) -> int:
    numbers, ledger_rules = _numbers(session, aid), rules()["ledger"]
    cap = ledger_rules["base_sites"] + int(numbers.get("pb", 0)) + int(numbers.get("key_mod", 0))
    return cap * max([1, *(factor for feature, factor in ledger_rules["multipliers"].items() if _has(session, aid, feature))])


def _record_site(session, aid, source_id, replace):
    sites = _learning(session, aid).setdefault("sites", {})
    if source_id in sites:
        return
    if len(sites) >= _site_cap(session, aid):
        require(replace in sites, "Your Field Ledger is full; name a recorded site to replace.")
        del sites[replace]
    # The first visit earns no advantage; a later examination marks a return visit.
    sites[source_id] = {"recorded_at": session.state["seconds"], "used": 1}
    session.emit("HARVEST_SITE_RECORDED", aid, source_id=source_id)


def _applies(session, aid, lot, table, choice) -> bool:
    """Whether any owned feature of a rules table covers this Lot (and the printed choice it needs, if any)."""
    return any(_fits(spec, lot) and _has(session, aid, feature) and (not spec.get("choice") or spec["choice"] == choice)
               for feature, spec in table.items())


def seal_seconds_for(cl: int, factor: int = 1):
    """Stable duration in seconds for a Cultivation Level (None: indefinite)."""
    days = [d for lo, d in rules()["seal_days_by_cl"] if cl >= lo][-1]
    return None if days == 0 else days * 86400 * factor


def _seal(session, aid, payload):
    data = rules()
    require(_has(session, aid, data["base"]["seal"]), "Only a Harvesting and Gathering character can Seal the Essence.")
    require(set(payload) <= {"lots", "choice", "lot_choices", "repair_bruise"} and isinstance(payload.get("lots"), list) and payload["lots"]
            and len(set(payload["lots"])) == len(payload["lots"]), "Choose distinct Lots to seal.")
    numbers = _numbers(session, aid)
    cap = max(1, int(numbers.get("pb", 0)) + int(numbers.get("key_mod", 0)))
    rows = []
    for key in payload["lots"]:
        row = ledger.holdings(session, aid).get(key)
        require(row is not None and row.get("lot") and not row["lot"]["sealed"] and row["quantity"] > 0,
                "Choose your own unsealed harvested Lots.")
        rows.append(row)
    weight = 0
    for row in rows:
        weight += 1
    require(weight <= cap, f"You can seal at most {cap} Lots at a time.")
    choices = payload.get("lot_choices", {})
    require(isinstance(choices, dict) and set(choices) <= set(payload["lots"]), "Choose sealing options only for Lots being sealed.")
    choice = payload.get("choice")
    cl = int(numbers.get("cl", 1))
    fixed = 0
    for key, row in zip(payload["lots"], rows):
        lot = row["lot"]
        lot_choice = choices.get(key, choice)
        span = None if _applies(session, aid, lot, data["seal"]["indefinite"], lot_choice) \
            else seal_seconds_for(cl, 2 if _applies(session, aid, lot, data["seal"]["double_duration"], lot_choice) else 1)
        lot["sealed"] = 1
        lot["stable_until"] = None if span is None else session.state["seconds"] + span
        for flag in ("masked", "scent_hidden", "warded"):
            lot[flag] = int(_applies(session, aid, lot, {f: s for f, s in data["seal"]["masks"].items() if s["flag"] == flag}, lot_choice))
        lot["alchemist_mark"] = int(_applies(session, aid, lot, data["seal"]["alchemist_mark"], lot_choice))
        for feature, spec in data["seal"]["bruise_fix"].items():
            allowed = [r for lo, r in spec["rarities_by_cl"] if cl >= lo][-1]
            if _has(session, aid, feature) and payload.get("repair_bruise", False) and fixed < spec["per_seal"] and lot["quality"] == spec["from"] and lot["rarity"] in allowed:
                lot["quality"], fixed = spec["to"], fixed + 1
    session.emit("HARVEST_SEALED", aid, lots=sorted(payload["lots"]), choice=choice or "")
    session.tick(data["seconds"]["seal"])
    return True


@hook("journey_options")
def options(session, aid):
    actor = session.state["actors"][aid]
    data = rules()
    if session.state["phase"] != "travel" or actor["incapacitated"]:
        return None
    rows = []
    auto = int(actor["control_mode"] == "LOCAL_AUTO")
    if _has(session, aid, data["base"]["clean_harvest"]):
        for sid, source in sorted(ledger.sources(session).items()):
            harvest = source.get("harvest")
            if not harvest or aid not in source["known_to"] or source["remaining"] <= 0 \
                    or (source.get("exclusive_to") and source["exclusive_to"] != aid):
                continue
            for name in data["methods"]:
                try:
                    _gate(session, aid, harvest)
                    method = _method(session, aid, name, source)
                except ValueError:
                    continue
                if method.get("pay_cp") and actor["resources"].get(_cp_resource(session, aid), 0) < method["pay_cp"]:
                    continue
                payload = {"source": sid, "method": name}
                cost = method.get("pay_cp", 0)
                duration = method.get("seconds_by_rarity", {}).get(harvest["rarity"], data["seconds"]["clean_harvest"])
                cost_text = f"; costs {cost} Cultivation Point(s)" if cost else ""
                if method.get("disadvantage_unless") and not harvest["prepared"]:
                    cost_text += "; no cost, but the check has Disadvantage"
                rows.append({"id": f"harvest:{sid}:{name}", "kind": "clean_harvest", "auto_select": auto, "payload": payload,
                             "label": f"{method['label']} at {source['name']}: Gathering Check against Harvest DC; {duration} seconds{cost_text}."})
                if not auto:
                    for picks in _manual_benefit_sets(session, aid, harvest, source, method):
                        automatic_extra = any(_fits(spec, harvest) and _has(session, aid, feature)
                                              for feature, spec in data["extra_lot_at_plus5"].items())
                        variants = []
                        can_pay = name == "quick" and not harvest["prepared"] and actor["resources"].get(_cp_resource(session, aid), 0) >= 1
                        for pay in ([False, True] if can_pay else [False]):
                            for include_extra in ([True, False] if automatic_extra else [True]):
                                selected = {**payload, "perfect": False, "benefits": picks}
                                if pay:
                                    selected["pay_cp"] = True
                                if not include_extra:
                                    selected["extra_lot"] = False
                                variants.append(selected)
                        for selected in variants:
                            if name == "sovereign_cut":
                                selected["save_source"] = True
                            suffix = ":paid" if selected.get("pay_cp") else ""
                            rows.append({"id": f"harvest:{sid}:{name}:benefits:{','.join(picks)}{suffix}", "kind": "clean_harvest",
                                         "auto_select": 0, "payload": selected,
                                         "label": f"{method['label']} at {source['name']}; if the check succeeds by 5 or more, choose {' and '.join(p.replace('_', ' ') for p in picks)}" + ("; preserve the source on a failure greater than 5." if selected.get("save_source") else "") + ("; decline the automatic extra Lot." if selected.get("extra_lot") is False else "") + ("; pay 1 Cultivation Point to avoid Disadvantage." if selected.get("pay_cp") else ".")})
                    if harvest["perfect"]:
                        available = [p for p in _manual_benefit_sets(session, aid, harvest, source, method) if len(p) == 2]
                        for picks in available:
                            for paid in ([False, True] if name == "quick" and not harvest["prepared"] and actor["resources"].get(_cp_resource(session, aid), 0) >= 1 else [False]):
                                selected = {**payload, "perfect": False, "benefits": picks}
                                if paid:
                                    selected["pay_cp"] = True
                                suffix = ":paid" if paid else ""
                                rows.append({"id": f"harvest:{sid}:{name}:two-benefits:{','.join(picks)}{suffix}", "kind": "clean_harvest", "auto_select": 0,
                                             "payload": selected,
                                             "label": f"{method['label']} at {source['name']}; if the check succeeds by 10 or more, choose {' and '.join(picks)} instead of a Perfect Lot" + ("; pay 1 Cultivation Point to avoid Disadvantage." if paid else ".")})
                if name == "quick" and not harvest["prepared"] and actor["resources"].get(_cp_resource(session, aid), 0) >= 1:
                    paid = {**payload, "pay_cp": True}
                    rows.append({"id": f"harvest:{sid}:{name}:pay", "kind": "clean_harvest", "auto_select": auto, "payload": paid,
                                 "label": f"{method['label']} at {source['name']} without Disadvantage; 1 Cultivation Point, {duration} seconds."})
                if name == "sovereign_cut":
                    preserved = {**payload, "save_source": True}
                    rows.append({"id": f"harvest:{sid}:{name}:preserve", "kind": "clean_harvest", "auto_select": auto, "payload": preserved,
                                 "label": f"{method['label']} at {source['name']}; preserve the source on a failure greater than 5."})
                if method.get("fail_choice"):
                    for choice in method["fail_choice"]:
                        chosen = {**payload, "on_fail": choice}
                        rows.append({"id": f"harvest:{sid}:{name}:failure:{choice}", "kind": "clean_harvest", "auto_select": auto, "payload": chosen,
                                     "label": f"{method['label']} at {source['name']}; on a failure, {choice.replace('_', ' ')}."})
            if _has(session, aid, data["base"]["read_the_sign"]) and harvest["sign_dc"] is not None:
                sites = _learning(session, aid).get("sites", {})
                auto_record = bool(auto and _has(session, aid, data["ledger"]["feature"]))
                replacement = sorted(sites)[0] if auto_record and sid not in sites and len(sites) >= _site_cap(session, aid) else None
                payload = {"source": sid, "record": auto_record}
                if replacement:
                    payload["replace"] = replacement
                rows.append({"id": f"sign:{sid}", "kind": "read_the_sign", "auto_select": auto, "payload": payload,
                             "label": f"Read the Sign at {source['name']}: a Gathering Check, ten minutes."})
                if _has(session, aid, data["ledger"]["feature"]):
                    choices = [None] if sid in sites or len(sites) < _site_cap(session, aid) else sorted(sites)
                    for replacement in choices:
                        recorded = {"source": sid, "record": True}
                        suffix = "record" if replacement is None else "replace:" + replacement
                        if replacement is not None:
                            recorded["replace"] = replacement
                        rows.append({"id": f"sign:{sid}:{suffix}", "kind": "read_the_sign", "auto_select": 0,
                                     "payload": recorded,
                                     "label": f"Read the Sign at {source['name']} and record it in your Field Ledger" +
                                              (f", replacing {ledger.sources(session).get(replacement, {}).get('name', 'a recorded site')}." if replacement else ".")})
    if _has(session, aid, data["base"]["seal"]):
        lots = [key for key, row in sorted(ledger.holdings(session, aid).items()) if row.get("lot") and not row["lot"]["sealed"]]
        if lots:
            cap = max(1, int(_numbers(session, aid).get("pb", 0)) + int(_numbers(session, aid).get("key_mod", 0)))
            auto_payload = {"lots": lots[:cap]}
            if auto:
                auto_payload["repair_bruise"] = True
                lot_choices = {}
                for key in auto_payload["lots"]:
                    lot = ledger.holdings(session, aid)[key]["lot"]
                    for choice in ("double", "hide", "mark"):
                        if _applies(session, aid, lot, data["seal"]["double_duration"], choice) or \
                                _applies(session, aid, lot, data["seal"]["masks"], choice) or \
                                _applies(session, aid, lot, data["seal"]["alchemist_mark"], choice):
                            lot_choices[key] = choice
                            break
                if lot_choices:
                    auto_payload["lot_choices"] = lot_choices
            rows.append({"id": "seal:all", "kind": "seal_essence", "auto_select": auto, "payload": auto_payload,
                         "label": f"Seal the Essence of your harvested Lots (ten minutes; up to {cap} at a time)."})
            if not auto:
                for key in lots:
                    lot = ledger.holdings(session, aid)[key]["lot"]
                    choices = [None]
                    for choice in ("double", "hide", "mark"):
                        if _applies(session, aid, lot, data["seal"]["double_duration"], choice) or \
                                _applies(session, aid, lot, data["seal"]["masks"], choice) or \
                                _applies(session, aid, lot, data["seal"]["alchemist_mark"], choice):
                            choices.append(choice)
                    cl = int(_numbers(session, aid).get("cl", 1))
                    repair_available = lot["quality"] == "bruised" and any(
                        _has(session, aid, feature) and lot["rarity"] in [r for level, rarities in spec["rarities_by_cl"] if cl >= level][-1]
                        for feature, spec in data["seal"]["bruise_fix"].items())
                    if repair_available:
                        rows.append({"id": f"seal:{key}:repair", "kind": "seal_essence", "auto_select": 0,
                                     "payload": {"lots": [key], "repair_bruise": True},
                                     "label": f"Seal {row['name']}; improve one eligible Bruised Lot. Takes ten minutes."})
                    for choice in choices:
                        payload = {"lots": [key]}
                        if choice:
                            payload["choice"] = choice
                        rows.append({"id": f"seal:{key}:{choice or 'normal'}", "kind": "seal_essence", "auto_select": 0,
                                     "payload": payload,
                                     "label": f"Seal {row['name']} for ten minutes" + ({"double": "; double its stable time.", "hide": "; hide its scent.", "mark": "; mark it for later appraisal."}.get(choice, "."))})
                for count in range(2, min(cap, len(lots)) + 1):
                    for batch in combinations(lots, count):
                        choices_for_batch = [None]
                        for choice in ("double", "hide", "mark"):
                            if all(_applies(session, aid, lot_row, data["seal"]["double_duration"], choice)
                                   or _applies(session, aid, lot_row, data["seal"]["masks"], choice)
                                   or _applies(session, aid, lot_row, data["seal"]["alchemist_mark"], choice) for lot_row in batch_rows):
                                choices_for_batch.append(choice)
                        for choice in choices_for_batch:
                            payload = {"lots": list(batch)}
                            if choice:
                                payload["choice"] = choice
                            rows.append({"id": "seal:batch:" + (choice or "normal") + ":" + ",".join(batch), "kind": "seal_essence", "auto_select": 0,
                                         "payload": payload,
                                         "label": f"Seal {count} selected harvested Lots together; takes ten minutes" + ({"double": "; double their stable time.", "hide": "; hide their scent.", "mark": "; mark them for later appraisal."}.get(choice, "."))})
    return rows
