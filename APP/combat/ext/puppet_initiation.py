"""Puppet Initiation's acquisition and one completed-rest basic vessel.

Uses the public learning contract reviewed at 4d78beec and the native Journey
rest clock. Vessel combat behavior stays in vessel.py. No receipt or item is
created by compiling, importing, reopening, or starting an encounter.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from . import hook
from .. import table_advance
from ..ability_checks import proficiency_rank
from ..tabletop import TabletopError

SPHERE = "tianxia.sphere.puppetry"
SOURCE = "PUPPETRY_BASE_PUPPET_INITIATION"
SHA = "b025dc6491bfa7c75876bd601a3be185e7cb5bf3e7bbf14e14314fe3750fefb8"
TOOLS = ("Woodcarver’s Tools", "Weaver’s Tools", "Smith’s Tools", "Tinker’s Tools", "Calligrapher’s Supplies")
SKILL = "Sleight of Hand"
FORMS = ("bludgeoning", "piercing", "slashing")


def sequence(value):
    return json.loads(value) if isinstance(value, str) else value or []


def normalize(value):
    return str(value).replace("’", "'").casefold()


def prior_proficiency(sheet, selected):
    """Explicit proficiency ranks, never a guessed numeric skill bonus."""
    stats = sheet.get("ability_scores_and_statistics") or {}
    if selected == SKILL:
        row = next((r for r in sequence(stats.get("skills")) if r.get("skill") == SKILL), None)
        if row is not None and proficiency_rank(row) is None:
            raise TabletopError("LEARNING_PROFICIENCY_UNKNOWN", "Puppet Initiation needs your recorded Sleight of Hand proficiency rank; a numeric bonus alone is not evidence.", 422)
        return bool(row and (proficiency_rank(row) or 0) >= 1)
    tools = list(sequence(stats.get("tool_proficiencies")))
    for row in (sheet.get("background_and_origin") or {}).values():
        if isinstance(row, dict):
            tools.extend(row.get("tool_proficiencies") or [])
            tools.extend(row.get("tool_expertise") or [])
            if row.get("selected_tool") and row.get("result") in ("proficiency", "proficient", "expertise"):
                tools.append(row["selected_tool"])
    return normalize(selected) in {normalize(t) for t in tools}


def talent_options(sheet, talents, prior=()):
    """Use the native prerequisite evaluator, including unknown gates."""
    have = table_advance.known(sheet)
    have["spheres"].add(SPHERE)
    have["talents"].update(table_advance.base_ability_index().get(SPHERE, []))
    have["talents"].update(prior)
    return [{"id": r["canonical_talent_id"], "name": r["display_name"]} for r in talents
            if r.get("owning_canonical_sphere_id") == SPHERE
            and r.get("canonical_talent_id") not in have["talents"]
            and not r.get("background_only") and not r.get("automatic_grant")
            and table_advance.talent_status(r, have)["legal"]]


@hook("learning_choices")
def choices(sheet, sphere_id, talents, draft=None):
    if sphere_id != SPHERE:
        return None
    draft = draft or {}
    out = [{"id": "proficiency", "label": "Puppet Initiation: choose one tool or Sleight of Hand proficiency",
            "options": [{"id": n, "name": n} for n in (*TOOLS, SKILL)]},
           {"id": "free", "label": "New Sphere: choose its normal free first Puppetry talent",
            "options": talent_options(sheet, talents)}]
    selected = draft.get("proficiency")
    if selected in (*TOOLS, SKILL) and prior_proficiency(sheet, selected):
        prior = [draft["free"]] if draft.get("free") in {r["id"] for r in out[1]["options"]} else []
        out.append({"id": "bonus", "label": "Puppet Initiation: already proficient; choose one eligible bonus Puppetry talent (free)",
                    "options": talent_options(sheet, talents, prior)})
    return out


@hook("learning_receipt")
def receipt(sheet, kind, record_id, selected, talents):
    if kind != "sphere" or record_id != SPHERE:
        return None
    if SPHERE in table_advance.known(sheet)["spheres"]:
        raise TabletopError("LEARNING_ALREADY_KNOWN", "Puppetry is already known; Puppet Initiation is granted only once.", 409)
    offered = choices(sheet, SPHERE, talents, selected)
    if set(selected) != {r["id"] for r in offered}:
        raise TabletopError("LEARNING_CHOICES_REQUIRED", "Choose each Puppet Initiation benefit, including the bonus talent when already proficient.", 422)
    for row in offered:
        if selected[row["id"]] not in {o["id"] for o in row["options"]}:
            raise TabletopError("LEARNING_CHOICE_INVALID", row["label"] + ": that choice is not eligible.", 422)
    learned = [selected[k] for k in ("free", "bonus") if k in selected]
    if len(set(learned)) != len(learned):
        raise TabletopError("LEARNING_DUPLICATE_TALENT", "Choose distinct talents for the first and bonus talent.", 422)
    text = json.loads((Path(__file__).resolve().parents[2] / "authority/typed_mechanics/rules_text.json").read_text())[SOURCE]
    if hashlib.sha256(text.encode()).hexdigest() != SHA:
        raise TabletopError("LEARNING_SOURCE_CHANGED", "Puppet Initiation's source changed; review its acquisition rules first.", 409)
    return {"source": SOURCE, "source_sha256": SHA, "sphere_id": SPHERE, "choices": dict(selected),
            "talents": learned, "slot_cost": 0, "conditional_bonus_earned": int("bonus" in selected)}


@hook("learning_projection")
def project(sheet, advancement):
    receipts = [r for a in advancement["spheres"] if a.get("id") == SPHERE
                for r in a.get("learning_receipts", []) if r.get("source") == SOURCE and r.get("source_sha256") == SHA]
    if not receipts:
        return sheet
    out = copy.deepcopy(sheet)
    stats = out["ability_scores_and_statistics"]
    learned = out.setdefault("spheres_and_talents", {}).setdefault("learned_talent_record_ids", [])
    for r in receipts:
        learned.extend(t for t in r["talents"] if t not in learned)
        pick = r["choices"]["proficiency"]
        if pick == SKILL:
            skills = sequence(stats.get("skills"))
            existing = next((s for s in skills if s.get("skill") == SKILL), None)
            if not existing or (proficiency_rank(existing) or 0) < 1:
                dex = next((int(a["modifier"]) for a in sequence(stats.get("abilities")) if a["ability"] == "DEX"), 0)
                bonus = int((existing or {}).get("bonus", dex)) + int(out["identity"]["proficiency_bonus"])
                skills = [s for s in skills if s.get("skill") != SKILL]
                skills.append({"skill": SKILL, "bonus": bonus, "proficiency_multiplier": 1, "proficiency": "proficient"})
                stats["skills"] = skills
        else:
            tools = list(sequence(stats.get("tool_proficiencies")))
            if normalize(pick) not in {normalize(t) for t in tools}:
                tools.append(pick)
            stats["tool_proficiencies"] = tools
    out["puppet_initiation"] = {"source": SOURCE, "source_sha256": SHA}
    return out


@hook("compile_bundle")
def bundle(document, info):
    initiation = info["owner_sheet"].get("puppet_initiation")
    if initiation and SPHERE in table_advance.known(info["owner_sheet"])["spheres"]:
        document = copy.deepcopy(document)
        document["puppet_initiation"] = copy.deepcopy(initiation)
    return document


@hook("journey_options")
def rest_options(session, actor_id):
    actor = session.state["actors"][actor_id]
    if (not actor["bundle"].get("puppet_initiation") or actor["rest_preparations"].get(SOURCE)
            or actor["incapacitated"] or session.state["phase"] != "travel"):
        return None
    return [{"id": "puppet_rest:" + form, "kind": "puppet_initiation_rest", "payload": {"form": form},
             "label": f"Puppet Initiation: create your one basic {form} puppet vessel during an eight-hour Long Rest (no CP cost)."}
            for form in FORMS]


@hook("journey_command")
def rest_command(session, actor_id, kind, payload):
    if kind != "puppet_initiation_rest":
        return None
    from ..journey import require
    require(any(o["payload"] == payload for o in rest_options(session, actor_id) or []),
            "Choose an available Puppet Initiation Long Rest preparation.")
    session.state["actors"][actor_id]["puppet_rest_form"] = payload["form"]
    session.command(actor_id, "long_rest", {})
    return True


@hook("journey_rest")
def complete_rest(session, actor_id):
    actor = session.state["actors"][actor_id]
    form = actor.pop("puppet_rest_form", None)
    if form not in FORMS or not actor["bundle"].get("puppet_initiation") or actor["rest_preparations"].get(SOURCE):
        return
    identity = "puppet:" + hashlib.sha256((session.state["journey_id"] + ":" + actor_id + ":" + SOURCE).encode()).hexdigest()[:24]
    actor["rest_preparations"][SOURCE] = {"item_instance_id": identity, "owner_id": actor_id, "source_id": SOURCE,
        "source_sha256": SHA, "name": "Basic puppet vessel", "form": form,
        "completed_rest": actor["long_rests"], "completed_seconds": session.state["seconds"], "state_revision": 0, "lineage": "rest-" + identity}
    actor["bundle"]["puppet_initiation"]["vessel"] = copy.deepcopy(actor["rest_preparations"][SOURCE])
    # The journey's already-sealed action definitions are its native combat
    # entry source. Carry the same physical item there, without re-acquisition.
    for action in actor["bundle"].get("action_catalog", []):
        params = action.get("parameters") or {}
        if params.get("vessel_kit"):
            params["vessel_initiation"] = copy.deepcopy(actor["bundle"]["puppet_initiation"])
    carrying = actor["bundle"].setdefault("carrying", {})
    carrying.setdefault("items", []).append({"key": identity, "item_id": SOURCE,
        "name": "Basic puppet vessel", "quantity": 1, "weight_lb": "0", "kind": "item", "worn": False})
    # Match the native inventory's unknown-weight representation, rather than
    # inventing a mass absent from Puppet Initiation's printed creation rule.
    carrying.setdefault("unweighed", []).append("Basic puppet vessel")
    session.emit("PUPPET_VESSEL_CREATED", actor_id, item_instance_id=identity, source_id=SOURCE,
                 text=f"{actor['name']} finishes creating one basic {form} puppet vessel during the Long Rest.")


@hook("journey_persistent_fields")
def persistent():
    # The completed-rest product is durable actor state: it must survive journey save and reload,
    # or a later encounter or journey loses the one-item guard and the owner-sheet projection.
    return ("rest_preparations",)


@hook("owner_sheet_projection")
def prepared_sheet(sheet, service, project_id):
    if not sheet.get("puppet_initiation") or SPHERE not in table_advance.known(sheet)["spheres"]:
        return sheet
    actor_id = "actor:factory." + project_id
    prepared = service.journeys.actor_preparations(actor_id).get(SOURCE)
    if not prepared or prepared.get("owner_id") != actor_id or prepared.get("source_sha256") != SHA:
        return sheet
    out = copy.deepcopy(sheet)
    out["puppet_initiation"]["vessel"] = prepared
    # Source-created equipment is an actual carried instance. Its item_id is
    # the printed creating source, not a guessed ItemBook classification;
    # no unpublished price, weight, or construction benefit is invented.
    equipment = out.setdefault("equipment", [])
    kit = next((r["starting_kit"] for r in equipment if isinstance(r, dict) and r.get("starting_kit")), None)
    if kit is None:
        kit = {"items": []}
        equipment.append({"starting_kit": kit})
    items = kit.setdefault("items", [])
    if not any(r.get("combat_item_key") == prepared["item_instance_id"] for r in items):
        items.append({"item_id": SOURCE, "source_component_id": SOURCE, "name": "Basic puppet vessel",
                      "quantity": 1, "combat_item_key": prepared["item_instance_id"]})
    return out


@hook("committed_products")
def persist_item_state(service, engine):
    """Synchronize only actual source-created items, after journal commit.

    A new fight/recompile cannot restore a broken item or heal its damage.
    Preview/pause/replay never call this service seam.

    The prepared item carries a state revision that advances every time its
    vessel changes (Raise, move, damage, dismissal, breakage). Only a strictly
    newer revision of the same item may replace the durable completed-rest
    product, so a stale parallel encounter that still holds an older snapshot
    cannot resurrect a broken vessel, undo damage, or move the item back when
    it commits an unrelated action.
    """
    from .vessel import PREPARED_ITEM
    for actor in engine.state.actors.values():
        saved = next((dict(c.data) for c in actor.conditions.values() if c.condition_id == PREPARED_ITEM
                      and c.data.get("source_id") == SOURCE and c.data.get("owner_id") == actor.entity_id), None)
        if not saved:
            continue
        prior = service.journeys.actor_preparations(actor.entity_id).get(SOURCE)
        if (prior and saved.get("item_instance_id") == prior.get("item_instance_id") and saved != prior
                and int(saved.get("state_revision") or 0) > int(prior.get("state_revision") or 0)):
            # The encounter's ancestry is its own chain of lineages (one action can fire several
            # lifecycle events). The store accepts it only when the durable lineage is in that chain,
            # checked under the lock; a fresh read of the durable lineage cannot stand in for it.
            product = {k: v for k, v in saved.items() if k != "ancestry"}
            service.journeys.update_preparation(actor.entity_id, SOURCE, product,
                ancestry=str(saved.get("ancestry") or "").split(","))
