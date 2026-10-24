"""Optional, local semantic advice for the character builder.

The frozen choice envelope remains the authority. Embeddings only order advice;
they never grant a choice or bypass its prerequisites. Network/cache failures
return no advice, preserving the original builder. Requests store integer scores
and record IDs, never vectors or mutable model state. Coverage uses acquisitions
and resolved equipment, never priority lists or descriptive promises.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Mapping, Sequence
from urllib.request import Request, urlopen

from factory_authoring.owner_text import without_owner_exclusions

APP_ROOT = Path(__file__).resolve().parents[1]
DIMENSIONS = 768
CACHE_VERSION = "embeddinggemma-2-search-v1"
SLOT_CATEGORIES = {
    "path_choice": "path", "method_choice": "method",
    "subpath_choice": "subpath", "foundation_choice": "foundation",
    "background_choice": "background", "background_sphere_choice": "sphere",
    "sphere_priorities": "sphere", "background_talent_choice": "talent",
    "advancement_skeleton": "talent", "insight_priorities": "insight",
    "origin_insight_choice": "insight", "item_priorities": "treasure",
}


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Record:
    id: str
    category: str
    name: str
    text: str
    aliases: tuple[str, ...] = ()
    source_sha256: str = ""

    @property
    def document(self) -> str:
        return f"title: {self.name or 'none'} | text: {self.text}"


def records_from_request(request: Mapping[str, Any]) -> list[Record]:
    """Index every frozen selectable row, plus mundane/treasure kit choices.

    Path/Subpath/Foundation feature rows nested in the envelope are included.
    Advice about kit catalog entries still requires the normal budget/kit checks.
    Raw files and vectors are never copied into a provider prompt.
    """
    from factory_authoring.starting_kits import gear_name_forms

    records: dict[tuple[str, str], Record] = {}

    def visit(value: Any, category: str) -> None:
        if isinstance(value, Mapping):
            if value.get("selectable") is False:
                return
            rid = next((value[k] for k in ("choice_id", "canonical_sphere_id", "canonical_talent_id",
                "canonical_insight_id", "record_id", "item_id", "consumable_id", "wondrous_id",
                "material_id", "enchantment_id", "enhancement_id", "treasure_id", "feature_id",
                "canonical_id", "path_id", "subpath_id", "foundation_id", "method_id", "id")
                if isinstance(value.get(k), str)), None)
            name = value.get("name") or value.get("display_name")
            # A mundane catalog item stays equipment even when the same row
            # also occurs in the builder's item-priority slot.
            if rid and rid.startswith("tianxia.mortal."):
                category = "equipment"
            if rid and isinstance(name, str) and value.get("selectable") is not False:
                text = next((value[k] for k in ("description", "player_rules_text", "full_exact_source_text",
                    "full_rules_text", "full_description", "text", "property_text", "effect", "semantic_cue")
                    if isinstance(value.get(k), str) and value[k]), "")
                if not text:
                    text = "; ".join(f"{k.replace('_', ' ')}: {value[k]}" for k in
                        ("damage", "properties", "weapon_family", "armor_class", "activation", "tianxia_forms")
                        if value.get(k))
                aliases = tuple(a for a in value.get("aliases", []) if isinstance(a, str))
                # Printed catalog names include both pinyin and English in
                # parentheses, e.g. Liu Xing Chui (Meteor Hammer).
                # Gear uses the owner's slash aliases/plurals too, so "chain
                # whip" wins before the overlapping utility "chain" and "whip".
                aliases = tuple(dict.fromkeys((*aliases, *(
                    part.strip() for part in re.split(r"[()]", name) if part.strip()
                ), *(sorted(gear_name_forms(name)) if category == "equipment" else ()))))
                records.setdefault((category, rid), Record(rid, category, name, " ".join(text.split())[:900],
                                                          aliases, _hash(value)))
            for key, child in value.items():
                if isinstance(child, (Mapping, list, tuple)):
                    if rid and category not in {"path", "subpath", "foundation", "feature"}:
                        continue
                    if isinstance(child, Mapping) and (child.get("name") or child.get("display_name")):
                        child = {"id": key, **child}
                    visit(child, "feature" if category in {"path", "subpath", "foundation"} and rid else category)
        elif isinstance(value, (list, tuple)):
            for child in value:
                visit(child, category)

    for source in (request.get("delegated_choice_envelope") or {},
                   (request.get("stage1_prompt") or {}).get("envelope") or {}, request):
        for slot, rows in (source.get("choices_by_slot") or {}).items():
            visit(rows, SLOT_CATEGORIES.get(slot, "feature"))
        for key in ("creation_training_contract", "path_progression_choices"):
            visit(source.get(key), "feature")
    for filename, category, keys in (
        ("Tianxia_Mundane_Equipment_Catalog_R1.json", "equipment", ("items",)),
        ("Tianxia_Treasure_Catalog_Authority_R1.json", "treasure", ("wondrous", "consumables")),
        ("Tianxia_Treasure_Weapon_Authority_R1.json", "treasure", ("materials", "enchantments")),
        ("Tianxia_Treasure_Armor_Authority_R1.json", "treasure", ("materials", "enhancements")),
    ):
        data = json.loads((APP_ROOT / "authority" / filename).read_text())
        for key in keys:
            visit(data[key], category)
    # One vector per record ID. Prefer the frozen selectable
    # row over a second occurrence of the same ID in an equipment catalog.
    unique: dict[str, Record] = {}
    for row in records.values():
        unique.setdefault(row.id, row)
    return sorted(unique.values(), key=lambda row: (row.category, row.id))


def _vector(raw: Any) -> list[float]:
    if not isinstance(raw, list) or len(raw) != DIMENSIONS:
        raise ValueError("Embedding dimensions do not match the local index")
    if any(isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x) for x in raw):
        raise ValueError("Invalid embedding vector")
    norm = math.sqrt(sum(x * x for x in raw))
    if norm < 1e-12 or not math.isfinite(norm):
        raise ValueError("Empty embedding vector")
    return [x / norm for x in raw]


class EmbeddingClient:
    def __init__(self, endpoint: str = "http://127.0.0.1:11448", *, timeout: float = 3.0):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        request = Request(self.endpoint + "/v1/embeddings",
                          data=json.dumps({"input": list(texts)}).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=self.timeout) as response:
            data = json.load(response)["data"]
        if not isinstance(data, list) or len(data) != len(texts):
            raise ValueError("Incomplete embedding batch")
        by_index = {row["index"]: row["embedding"] for row in data}
        if set(by_index) != set(range(len(texts))):
            raise ValueError("Invalid embedding batch indices")
        return [_vector(by_index[i]) for i in range(len(texts))]


class ConceptIndex:
    """Content-addressed disk cache; changed records alone are re-embedded.

    Concurrent builds use atomic replacement. A racing cache write can lose
    reuse opportunities but cannot corrupt a reader or change any authority.
    The inventory hash covers every category/ID/printed-text/alias projection.
    Change CACHE_VERSION when changing model weights or search prefixes.
    """
    def __init__(self, records: Sequence[Record], cache_path: Path, client: EmbeddingClient,
                 *, batch_size: int = 32, budget_seconds: float = 30):
        self.records = list(records)
        self.cache_path, self.client = Path(cache_path), client
        self.batch_size, self.budget_seconds = batch_size, budget_seconds
        self.vectors: dict[str, list[float]] = {}
        self.keys = {r.id: _hash([CACHE_VERSION, client.endpoint, r.document, r.source_sha256]) for r in records}

    def build(self) -> None:
        namespace = _hash([CACHE_VERSION, self.client.endpoint, DIMENSIONS])
        cached: dict[str, list[float]] = {}
        try:
            data = json.loads(self.cache_path.read_text())
            if isinstance(data, dict) and data.get("namespace") == namespace and isinstance(data.get("vectors"), dict):
                cached = data["vectors"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        for row in self.records:
            key = self.keys[row.id]
            if key in cached:
                try:
                    cached[key] = self.vectors[row.id] = _vector(cached[key])
                except (ValueError, TypeError):
                    cached.pop(key, None)
        missing = list({self.keys[r.id]: r for r in self.records if r.id not in self.vectors}.values())
        started = time.monotonic()
        changed = False
        try:
            for offset in range(0, len(missing), self.batch_size):
                if time.monotonic() - started > self.budget_seconds:
                    raise TimeoutError("Optional embedding index warm-up budget exceeded")
                batch = missing[offset:offset + self.batch_size]
                vectors = self.client.embed([r.document for r in batch])
                for row, vector in zip(batch, vectors):
                    cached[self.keys[row.id]] = vector
                changed = True
        finally:
            if changed:
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                scratch = None
                try:
                    with tempfile.NamedTemporaryFile(mode="w", dir=self.cache_path.parent,
                                                     prefix=".concept-index-", delete=False) as out:
                        scratch = Path(out.name)
                        active_keys = set(self.keys.values())
                        json.dump({"namespace": namespace,
                                   "inventory_sha256": _hash([r.__dict__ for r in self.records]),
                                   "vectors": {k: v for k, v in cached.items() if k in active_keys}}, out)
                    os.replace(scratch, self.cache_path)
                finally:
                    if scratch is not None:
                        scratch.unlink(missing_ok=True)
        self.vectors = {r.id: cached[self.keys[r.id]] for r in self.records}

    def rank(self, query_vector: list[float], category: str | None = None) -> list[dict[str, Any]]:
        scores = []
        for row in self.records:
            if category and row.category != category:
                continue
            score = round(1000 * sum(a * b for a, b in zip(query_vector, self.vectors[row.id])))
            scores.append({"id": row.id, "name": row.name, "category": row.category, "score_milli": score})
        return sorted(scores, key=lambda r: (-r["score_milli"], r["id"]))


def owner_brief(request: Mapping[str, Any]) -> str:
    """Use sealed owner text; generated identity text cannot add requirements."""
    from character_creation.creative_controller.linear_prompt import owner_locked_descriptive_fields
    locked = owner_locked_descriptive_fields(request, request.get("delegated_choice_envelope") or {})
    concept = locked.get("concept") or request.get("concept") or request.get("brief") or ""
    title = locked.get("owner_descriptive_fields.identity.title") or request.get("title") or ""
    return " ".join(str(v) for v in (concept, title) if v).strip()[:4000]


_STOP = set("a an the and or with using uses use wielding wield who is of in on from to by for as plus cultivation cultivator style character named lord master".split())


def _affirmative_text(brief: str) -> str:
    """Conservatively omit exclusions and unresolved alternatives from intent.

    The full brief still ranks advice. Only affirmative, unambiguous phrases
    may assert an owner requirement; this is not a natural-language parser.
    Negation ends at a sentence boundary or an explicit new positive clause.
    Commas alone do not end it: excluded lists may contain commas. An
    alternative clause is omitted as a whole, including comma-separated lists,
    rather than choosing any of its members for players.
    """
    text = without_owner_exclusions(brief).casefold()
    return ";".join(
        "" if re.search(r"\bor\b|/", clause) else clause
        for clause in re.split(r"[;.!?\n+]|\bbut\b", text)
    )


def concept_phrases(brief: str, records: Sequence[Record]) -> list[tuple[str, str | None]]:
    """Extract catalog noun phrases first, longest aliases before contained ones.

    Remaining concrete phrases are delimited by conjunctions, verbs and
    punctuation. This small deterministic extractor needs no second model.
    Unknown ideas may receive advice but never become invented catalog IDs.
    """
    text = _affirmative_text(brief)
    spans: list[tuple[int, int, str, str]] = []
    for row in records:
        if row.category not in {"sphere", "equipment", "path", "subpath", "foundation", "talent", "insight"}:
            continue
        for name in (row.name, *row.aliases):
            if len(name) < 3:
                continue
            for match in re.finditer(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)", text):
                spans.append((match.start(), match.end(), match.group(), row.id))
    selected: list[tuple[int, int, str, str]] = []
    for span in sorted(spans, key=lambda s: (-(s[1] - s[0]), s[0], s[3])):
        if not any(span[0] < other[1] and other[0] < span[1] for other in selected):
            selected.append(span)
    remaining = list(text)
    for start, end, _, _ in selected:
        remaining[start:end] = ";" * (end - start)
    phrases = [(s[2], s[3]) for s in sorted(selected)]
    chunks = re.split(r"[^\w '-]+|\b(?:" + "|".join(sorted(_STOP)) + r")\b", "".join(remaining))
    phrases.extend((" ".join(chunk.split()), None) for chunk in chunks
                   if 2 <= len(chunk.strip()) <= 80 and len(chunk.split()) <= 5)
    return list(dict.fromkeys(phrases))[:24]


GEAR_NOUNS = frozenset(
    "weapon weapons hammer maul blade staff bow crossbow arrow arrows dagger knife whip armor armour "
    "mail gear club mace flail lance glaive halberd pike torch".split()
)
ELEMENT_FAMILY_CATEGORIES = ("sphere", "path", "subpath")


def semantic_candidates(ranked: Sequence[Mapping[str, Any]], phrase: str) -> list[Mapping[str, Any]]:
    """Keep only the category a phrase plausibly names, preserving rank order.

    A phrase containing a gear noun (weapon, hammer, torch...) names equipment.
    Any other unnamed phrase names an element/style family (Sphere, Path or
    Subpath). Talents and Insights are never semantic suggestions, and gear is
    never suggested for an element word such as fire or lava.
    """
    words = set(re.findall(r"\w+", phrase.casefold()))
    allowed = {"equipment"} if words & GEAR_NOUNS else set(ELEMENT_FAMILY_CATEGORIES)
    return [r for r in ranked if r["category"] in allowed]


def guidance(index: ConceptIndex, brief: str, *, per_category: int = 5,
             threshold_milli: int = 600, margin_milli: int = 30) -> dict[str, Any]:
    """Suggest a semantic top match at cosine >= .60 and lead >= .03.

    Lead-measured search-prefix/document-prefix scores put lava→Magma at .681
    (.047 ahead of Ash). Relative separation accepts it without treating a
    crowded neighborhood as owner intent. Each unnamed phrase is compared only
    within the category it plausibly names (see semantic_candidates), so an
    unrelated weapon cannot outscore an element. Semantic matches are advice
    only; exact affirmative catalog mentions alone become coverage requirements.
    """
    phrases = concept_phrases(brief, index.records)
    queries = [brief, *(phrase for phrase, _ in phrases)]
    vectors = index.client.embed([f"task: search result | query: {q}" for q in queries])
    shortlist = {category: index.rank(vectors[0], category)[:per_category]
                 for category in sorted({r.category for r in index.records})}
    requirements = []
    suggestions = []
    for (phrase, exact_id), vector in zip(phrases, vectors[1:]):
        # Unnamed element/style concepts must choose a broad family before a
        # specific Talent. A passing mention in a Talent is not an acquisition.
        candidates = index.rank(vector)
        if exact_id:
            best = next(r for r in candidates if r["id"] == exact_id)
        else:
            candidates = semantic_candidates(candidates, phrase)
            if not candidates:
                continue
            best = candidates[0]
            if best["score_milli"] < threshold_milli or (len(candidates) > 1 and
                    best["score_milli"] - candidates[1]["score_milli"] < margin_milli):
                continue
        target = requirements if exact_id else suggestions
        target.append({**best, "phrase": phrase, "match": "owner_named" if exact_id else "semantic"})
    return {"schema": "TianxiaFoundry.ConceptGuidance.v1", "shortlist": shortlist,
            "requirements": requirements, "suggestions": suggestions,
            "threshold_milli": threshold_milli, "margin_milli": margin_milli}


def freeze_concept_guidance(request: Mapping[str, Any], *, cache_path: Path | None = None) -> dict[str, Any]:
    """Best-effort advice; disable with TIANXIA_CONCEPT_EMBEDDINGS=0.

    A cold index has a 30-second warm-up budget; completed batches survive for
    the next build. Cache location and local endpoint can be configured using
    TIANXIA_CONCEPT_CACHE and TIANXIA_EMBEDDING_ENDPOINT. No service is started.
    """
    if os.environ.get("TIANXIA_CONCEPT_EMBEDDINGS", "1").lower() in {"0", "false", "off"}:
        return {}
    brief = owner_brief(request)
    if not brief:
        return {}
    try:
        index = ConceptIndex(records_from_request(request),
            Path(os.environ.get("TIANXIA_CONCEPT_CACHE", str(cache_path or APP_ROOT / "runtime_data/cache/concept_embeddings.json"))),
            EmbeddingClient(os.environ.get("TIANXIA_EMBEDDING_ENDPOINT", "http://127.0.0.1:11448")))
        index.build()
        return guidance(index, brief)
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def recommendation_scores(request: Mapping[str, Any]) -> dict[str, int]:
    advice = request.get("concept_guidance") or {}
    scores = {r["id"]: r["score_milli"] for rows in advice.get("shortlist", {}).values() for r in rows}
    for row in (*advice.get("suggestions", []), *advice.get("requirements", [])):
        scores[row["id"]] = 2000  # Concept-specific advice orders, never pins.
    return scores


def prompt_guidance(request: Mapping[str, Any]) -> str:
    advice = request.get("concept_guidance") or {}
    if not advice:
        return ""
    lines = ["Most relevant to the owner's concept (guidance only; the full legal choices remain authoritative):"]
    for category, rows in advice["shortlist"].items():
        lines.append(f"{category.title()}: " + "; ".join(r["name"] for r in rows[:3]))
    suggestions = [*advice.get("suggestions", []), *(
        r for r in advice.get("requirements", []) if r.get("match") == "semantic")]
    if suggestions:
        lines.append("Likely relevant (advice only; keep all legal player choices): "
                     + "; ".join(f"{r['phrase']} → {r['name']}" for r in suggestions))
    requirements = [r for r in advice.get("requirements", []) if r.get("match") == "owner_named"]
    if requirements:
        lines.append("Honor these concrete concepts through actual acquisitions/equipment when legal and affordable: "
                     + "; ".join(f"{r['phrase']} → {r['name']}" for r in requirements))
    return "\n".join(lines)


def coverage_warnings(request: Mapping[str, Any], acquired_ids: Sequence[str],
                      resolved_equipment: Any = None) -> list[str]:
    """Return plain review warnings for concepts absent from the actual build.

    When owner-gear policy is present, it alone checks weapon/armor/shield
    phrases, including ambiguous aliases and guaranteed-budget omissions.
    Concept indexing can pick a different catalog variant for the same noun
    (Staff versus Qi Focus (Staff)); that must not add a second requirement.
    Other equipment and non-gear concepts still need acquisition coverage.
    """
    selected = set(acquired_ids)
    owner_gear_policy = any(request.get(key) for key in (
        "owner_gear_requirements", "owner_gear_preferences", "owner_gear_warnings",
    ))

    def owner_gear_handles(row: Mapping[str, Any]) -> bool:
        if not owner_gear_policy or row.get("category") != "equipment":
            return False
        from factory_authoring.starting_kits import owner_named_gear

        gear = owner_named_gear(row.get("phrase"))
        return bool(gear["items"] or gear["warnings"])

    def equipment_ids(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if key in {"item_id", "chassis_id", "material_id", "enchantment_id", "enhancement_id", "treasure_id",
                           "wondrous_id", "consumable_id"} and isinstance(child, str):
                    selected.add(child)
                elif key in {"enchantment_ids", "enhancement_ids", "wondrous_ids", "consumable_ids"} and isinstance(child, list):
                    selected.update(x for x in child if isinstance(x, str))
                elif isinstance(child, (Mapping, list, tuple)):
                    equipment_ids(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                equipment_ids(child)

    equipment_ids(resolved_equipment)
    return [f"Your concept asks for {row['phrase']}. The finished build does not include {row['name']}. "
            "Review this choice: its prerequisites, available selections, or equipment budget may prevent adding it."
            for row in (request.get("concept_guidance") or {}).get("requirements", [])
            if row.get("match") == "owner_named" and row["id"] not in selected
            and not owner_gear_handles(row)]
