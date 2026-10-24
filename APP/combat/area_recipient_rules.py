"""Catalogue-backed martial classification and owner area recipient rulings.

Used by area_recipients for compilation, old bundles, reactions and previews.
Names never classify abilities: sphere ids resolve through catalogue metadata.
The sealed tradition indexes have no primary sphere; only exclusively martial
synergies/leans establish a martial tradition. Mixed/unknown lists stay unknown.
"""
import json
import re
import zipfile
from functools import lru_cache
from pathlib import Path
from .read_queries import file_snapshot

APP = Path(__file__).resolve().parents[1]
OVERRIDES = APP / "combat/rules/area_recipient_overrides.json"


@lru_cache(maxsize=1)
def martial_catalogue():
    """Return sphere metadata, aliases and unambiguously martial feature ids."""
    catalogue = json.loads((APP / "catalog_authority/cat3/generated/catalog_authority.v1.json").read_text())
    spheres, aliases = {}, {}
    for row in catalogue["spheres"]:
        header = row["full_exact_source_text"].split("###", 1)[0]
        match = re.search(r"(?im)^Sphere Type:\s*(.+)$", header)
        sphere_type = match.group(1) if match else ""
        sid = row["canonical_sphere_id"]
        # Power Sphere with Martial Expressions (Sound) is still a power
        # sphere; explicit Martial / Hybrid Martial type declarations qualify.
        martial = bool(re.match(r"(?:Hybrid\s+)?Martial\b", sphere_type, re.I))
        spheres[sid] = {"name": row["display_name"], "sphere_type": sphere_type, "martial": martial}
        for name in [row["display_name"], *row.get("aliases", [])]:
            aliases[name.casefold()] = sid
            aliases["tianxia.sphere." + re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")] = sid
    features, uncertain = set(), {}
    # Legacy forged bundles omit sphere but retain their primary talent id.
    # Resolve that id through catalogue membership, never through its name.
    for row in catalogue["talents"]:
        if spheres.get(row["owning_canonical_sphere_id"], {}).get("martial"):
            features.add(row["canonical_talent_id"])
    for row in catalogue["automatic_base_abilities"]:
        if spheres.get(row["mapped_canonical_sphere_id"], {}).get("martial"):
            features.update(value for key in ("candidate_record_id", "runtime_component_id")
                            if (value := row.get(key)))
    for row in catalogue["automatic_base_ability_aliases"]:
        if row["canonical_component_id"] in features:
            features.add(row["legacy_id"])
    with zipfile.ZipFile(APP / "BundledContent/Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip") as archive:
        for name in archive.namelist():
            if not name.endswith("_subpath_tradition_index.p2b.json"):
                continue
            for row in json.loads(archive.read(name))["entries"]:
                identity = row["identity"]
                linked = identity.get("sphere_synergies", identity.get("sphere_lean", []))
                exclusively_martial = bool(linked) and all(
                    spheres.get(aliases.get(s.casefold()), {}).get("martial") for s in linked)
                for feature in row["feature_progression"]:
                    fid = feature["canonical_id"]
                    if exclusively_martial:
                        features.add(fid)
                    else:
                        uncertain[fid] = linked
    return spheres, aliases, frozenset(features), uncertain


def is_martial(typed):
    """Resolve typed sphere/primary Forge sphere, or indexed tradition feature."""
    spheres, aliases, features, _ = martial_catalogue()
    sid = typed.get("sphere", typed.get("sphere_id"))
    sid = aliases.get(str(sid).casefold(), sid)
    return bool(spheres.get(sid, {}).get("martial") or
                ability_source(typed) in features or typed.get("forged_from") in features)


def ability_source(typed):
    """Typed actions use source strings; authority mechanics use source objects."""
    source = typed.get("source")
    return source if isinstance(source, str) else typed.get("mechanic_id")


@lru_cache(maxsize=1)
def _read_overrides(path, mtime_ns, size):
    data = json.loads(Path(path).read_text())
    for row in data["abilities"].values():
        if row["recipients"] not in {"enemies", "everyone"} or not row.get("reason"):
            raise ValueError("Area recipient overrides need enemies/everyone and a reason")
    return data["abilities"]


def recipient_override(typed):
    """Current owner ruling; edits apply to future actions, including old fights.

    The tiny file is parsed only on change. No character/fight state is stored.
    """
    entries = file_snapshot(('area_recipient_overrides', OVERRIDES), _current_overrides)
    source = ability_source(typed)
    return entries.get(source)


def _current_overrides():
    stat = OVERRIDES.stat()
    return _read_overrides(str(OVERRIDES), stat.st_mtime_ns, stat.st_size)
