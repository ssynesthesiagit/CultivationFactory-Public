from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "Tianxia.CAT3.CanonicalCatalogAuthority.v1"
COMPILER_VERSION = "CAT3-P1R-R2-R1.0"
FACTORY_RELATIVE_PATH = Path("BundledContent") / "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2.zip"
FACTORY_SHA256 = "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385"
COMPENDIUM_SUFFIX = "09_RULES/Source_Text/Tianxia_Sphere_Compendium_Latest_R0I_85Spheres.md"
COMPENDIUM_PATH = "09_RULES/Source_Text/Tianxia_Sphere_Compendium_Latest_R0I_85Spheres.md"
COMPENDIUM_SHA256 = "67f67275889467d43605debaa0c05dc5ddde9ba079222819aabea27c66167775"
SOURCE_PACK = "Tianxia_Factory_HF05ZVK_R1H_Phase2I_HF2"
SOURCE_VERSION = "HF05ZVK-R1H Phase 2I HF2 / Canon Corpus P2A"
EXPECTED_SPHERES = 85
REALM_ENTRY_CL = {"Mortal": 1, "Foundation": 5, "Core Formation": 10, "Nascent Soul": 15, "Immortal": 20}
NONCANONICAL_LABELS = {
    "Chains / Meridian": ("content_family_label", "Chains"),
    "Chakra Imbuement": ("generated_coverage_grouping", "Imbuement"),
    "Chakra Universal": ("generated_coverage_grouping", None),
    "Drain": ("route_label", None),
    "Fencing": ("alias", "The Piercing Needle"),
    "Harvesting-Gathering": ("alias", "Harvesting Gathering"),
    "Phasing": ("route_label", None),
    "Predator": ("route_label", None),
    "Pressure Points / Meridian": ("content_family_label", "Pressure Points"),
    "Universal": ("generated_coverage_grouping", None),
    "Universal C09": ("generated_coverage_grouping", None),
    "Universal Martial": ("generated_coverage_grouping", None),
    "Vitality": ("route_label", None),
}

# Generic authored section grammar. These are semantic section families, not a
# six-record blacklist. Descendants of blocker sections are never selectable.
STRUCTURAL_EXACT = {
    "cultivation insights", "path synergies", "sphere synergies", "automation notes",
    "path expression", "path expression notes", "character sheet notes", "player notes",
    "weapon catalogue", "weapon catalog", "weapon profiles", "axe profiles",
    "armor traditions", "source traditions", "axe traditions", "legal weapon profiles",
    "optional mechanical insights", "training", "realm evolutions", "realm progression",
    "domain talents", "realm evolution talents", "base sphere abilities", "sphere boundaries",
    "sphere boundary", "sphere sentence", "talent tags", "rules baseline",
    "player facing rules", "strategic project seeds", "forged technique examples",
    "realm feature", "nascent soul form", "domain", "limitations", "limitation",
    "benefit", "benefits", "drawback", "drawbacks", "failed save", "successful save",
    "failed initial save", "successful initial save", "object barrier or effect",
    "creature", "allies", "enemies", "you", "you and allies",
}
STRUCTURAL_CONTAINS = (
    "drawbacks and variant", "optional cultivation variant", "cultivation variants", "secret inheritance",
    "variant scriptures", "path synerg", "sphere synerg", "cultivation insight",
    "automation note", "acquisition guidance", "talent acquisition", "training rules",
    "save dc", "key ability", "realm feature", "realm evolution", "realm progression",
    "weapon catalogue", "weapon catalog", "character sheet note", "path expression note",
    "formation anchors", "source limitations", "player notes", "cross-sphere notes",
    "crafting results", "refinement results", "infection effects", "maintaining fate effects",
    "objects cover and targeting", "barrier domain", "barriers domains",
)
STRUCTURAL_PREFIXES = (
    "you and allies", "allies", "enemies when", "creature make", "object or barrier deal",
    "object barrier or effect", "failed save", "successful save", "benefits", "benefit",
)
ACCESS_FIELD_RE = re.compile(
    r"(?i)^(?:classification|talent\s+type|access(?:\s+category)?|inheritance\s+type)\s*:\s*(.+?)\s*$"
)
PREREQUISITE_LABEL_RE = re.compile(r"(?i)^(?:prerequisites?|requirements?|requires?|available\s+at)$")
# Authored fields are tokenized before prerequisite extraction. Several source
# rows append a following field without a newline (and sometimes without
# whitespace, e.g. ``CL 5+Augment - 1 CP``).
STRUCTURED_FIELD_LABELS = (
    "Compatible Proposition", "Prerequisites", "Prerequisite", "Requirements", "Requirement",
    "Available at", "Action Type", "Use Limit", "Saving Throw", "Attack Roll", "Cultivation Cost",
    "Activation Cost", "Augment", "Requires", "Trigger", "Target", "Targets", "Cost", "Range",
    "Area", "Duration", "Effect", "Frequency", "Special", "Limit", "Upkeep", "Recovery",
)
STRUCTURED_FIELD_RE = re.compile(
    r"(?i)(?<![a-z0-9])(?P<label>" + "|".join(
        re.escape(label).replace(r"\ ", r"\s+") for label in sorted(STRUCTURED_FIELD_LABELS, key=len, reverse=True)
    ) + r")\s*(?P<separator>:|[-–—])\s*"
)
REALM_RE = re.compile(r"(?i)\b(Mortal|Foundation|Core\s+Formation|Nascent\s+Soul|Immortal)\s+Realm\b")
CL_RE = re.compile(r"(?i)\bCL\s*(\d+)\s*(?:\+|or\s+(?:higher|above)|and\s+(?:higher|above))?")


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def normalize(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value).replace("’", "'").replace("‘", "'")
    return re.sub(r"[^a-z0-9]+", " ", folded.casefold()).strip()


def slug(value: str) -> str:
    return normalize(value).replace(" ", "_")


def realm_for_cl(minimum_cl: int) -> str:
    if minimum_cl >= 20:
        return "Immortal"
    if minimum_cl >= 15:
        return "Nascent Soul"
    if minimum_cl >= 10:
        return "Core Formation"
    if minimum_cl >= 5:
        return "Foundation"
    return "Mortal"


def committed(record: dict[str, Any]) -> dict[str, Any]:
    payload = {key: value for key, value in record.items() if key != "record_commitment_sha256"}
    return {**payload, "record_commitment_sha256": sha256_bytes(canonical_bytes(payload))}


@dataclass(frozen=True)
class SourceToken:
    index: int
    source_line: int
    source_column: int
    text: str


@dataclass(frozen=True)
class Heading:
    token_index: int
    line: int
    column: int
    level: int
    title: str
    raw_text: str
    inline_body: str = ""


@dataclass(frozen=True)
class Candidate:
    sphere_name: str
    sphere_heading: Heading
    heading: Heading
    section_heading: Heading
    realm: str
    default_minimum_cl: int
    acquisition_route: str
    access_category: str


def tokenize_source(lines: list[str]) -> list[SourceToken]:
    """Split appended Markdown headings into real logical source boundaries."""
    tokens: list[SourceToken] = []
    for line_number, line in enumerate(lines, 1):
        starts = [0]
        # A Markdown heading marker after prose is a new logical token. Require
        # whitespace before the marker to avoid splitting ordinary hash text.
        starts.extend(match.end() for match in re.finditer(r"(?<=\S)\s+(?=#{1,6}\s)", line))
        starts = sorted(set(starts))
        for offset, start in enumerate(starts):
            end = starts[offset + 1] if offset + 1 < len(starts) else len(line)
            text = line[start:end].strip()
            if text:
                leading = len(line[start:end]) - len(line[start:end].lstrip())
                tokens.append(SourceToken(len(tokens), line_number, start + leading + 1, text))
    return tokens


def _structured_field_segments(text: str) -> list[tuple[str, str, int, int]]:
    """Return exact field segments without crossing a following field."""
    matches = list(STRUCTURED_FIELD_RE.finditer(text))
    if not matches:
        # A separator-less ``Requires X`` field is historical authored syntax,
        # but lowercase prose such as ``require mission reports`` is not a
        # field boundary and must not become an acquisition prerequisite.
        legacy = re.match(r"^\s*(?P<label>Requires?)\s+(?P<body>.+)$", text)
        if legacy is None:
            legacy = re.match(r"(?i)^\s*(?P<label>Available\s+at)\s+(?P<body>.+)$", text)
        if legacy:
            return [(legacy.group("label"), legacy.group("body").strip(), legacy.start("label"), len(text))]
        return []
    rows: list[tuple[str, str, int, int]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end].strip().strip("-–— ")
        rows.append((match.group("label"), body, match.start(), end))
    return rows


def _split_heading_title_and_body(raw_title: str) -> tuple[str, str]:
    title = raw_title.strip()
    package_root = re.match(r"(?i)^(.+?\bPackage)\s+([A-Z][\s\S]+)$", title)
    if package_root:
        return package_root.group(1).strip(), package_root.group(2).strip()
    # Exact structural roots often have explanatory prose appended on the same
    # physical line. Stop at the authored section label.
    structural_root = re.match(
        r"(?i)^(.+?\b(?:TALENTS|VARIANTS|SCRIPTURES|SYNERGIES|INSIGHTS|NOTES|CATALOGUE|CATALOG|TRADITIONS))\s+([A-Z][\s\S]+)$",
        title,
    )
    if structural_root and normalize(structural_root.group(1)) != normalize(title):
        return structural_root.group(1).strip(), structural_root.group(2).strip()
    # Some source rows place the complete effect after the heading name using
    # the same dash glyph normally used for tags.  A lowercase continuation is
    # prose, not a tag list, and belongs in the Talent description.
    dash_body = re.match(r"^(.+?)\s+[-–—]\s+(.+)$", title)
    if dash_body:
        continuation = dash_body.group(2).strip()
        prose_continuation = continuation[:1].islower() or (
            continuation.endswith((".", "!", "?")) and len(continuation.split()) >= 4
        )
        if prose_continuation:
            return dash_body.group(1).strip(), continuation

    # Preserve tags in the heading while separating obvious prose or explicit
    # prerequisite fields authored on the same line.
    marker = re.search(
        r"\s+(?=(?:Prerequisites?|Requirements?|Requires?|Available\s+at|Use|While|When|You|This|The|An?|If|Once|After|Before|Choose|Gain|Make|Spend)\b)",
        title,
        re.I,
    )
    if marker and re.search(r"\s[-–—]\s", title[: marker.start()]):
        return title[: marker.start()].strip(), title[marker.end() :].strip()
    quote = re.search(r"\s+[“\"]", title)
    if quote:
        return title[: quote.start()].strip(), title[quote.start() :].strip()
    return title, ""


def parse_heading(token: SourceToken) -> Heading | None:
    match = re.match(r"^(#{1,6})\s+(.+?)\s*$", token.text)
    if not match:
        return None
    title, inline_body = _split_heading_title_and_body(match.group(2).strip())
    return Heading(
        token_index=token.index,
        line=token.source_line,
        column=token.source_column,
        level=len(match.group(1)),
        title=title,
        raw_text=token.text,
        inline_body=inline_body,
    )


def realm_from_heading(title: str) -> str | None:
    folded = title.casefold()
    if "talent" not in folded:
        return None
    for realm in ("Core Formation", "Nascent Soul", "Foundation", "Immortal", "Mortal"):
        if realm.casefold() in folded:
            return realm
    return None


def is_realm_talent_heading(title: str) -> bool:
    return realm_from_heading(title) is not None


def structural_role(title: str) -> str:
    folded = normalize(title)
    has_tag_separator = bool(re.search(r"\s[-–—]\s", title))
    if any(folded.startswith(normalize(prefix)) for prefix in STRUCTURAL_PREFIXES):
        return "blocker"
    if folded in STRUCTURAL_EXACT:
        return "blocker"
    if (folded.startswith("secret ") and "inheritance" in folded) or (
        folded.startswith("optional ") and "variant" in folded
    ):
        return "blocker"
    if any(token in folded for token in STRUCTURAL_CONTAINS):
        # Tagged actual Talents such as "Court ... - Domain" remain candidates;
        # untagged section/domain headings remain structure.
        if not has_tag_separator or any(token in folded for token in ("realm feature", "realm evolution talents")):
            return "blocker"
    if (not has_tag_separator and re.search(r"(?i)\btalents\s*$", title)) or folded in {
        "domain", "realm evolutions", "nascent soul form",
    }:
        return "category"
    if re.fullmatch(r"(?:foundation|core formation|nascent soul|immortal) realm evolution", folded):
        return "blocker"
    return "candidate"


_LEGACY_BROAD_USE_CUE_RE = re.compile(
    r"(?i)\b(?:you\s+(?:are|must|cannot|can|have|wear|wield|use)|"
    r"target|creature|object|surface|wall|cliff|structure|ammunition|"
    r"remains|corpse|workpiece|weapon|armor|shield|item|tool|"
    r"while|when|during|after|before|not\s+exhausted|unused|enough|"
    r"wielding|proficien(?:t|cy)|action|reaction|"
    r"bound|grappled|restrained|tethered|bonded\s+companion|adjacent|within\s+range)\b"
)


def _explicit_prerequisite_use_semantics(body: str) -> str | None:
    """Return an exact use-only basis for a mislabeled authored prerequisite.

    The source corpus contains three narrow cases where an authored
    ``Prerequisite`` field includes execution authority. These exceptions are
    recognized by complete clause semantics, never by generic body words.
    """
    folded = normalize(body)
    if folded == "the target is bound grappled restrained or attached to one of your tethers":
        return "exact_target_state_prerequisite"
    if folded == "discovery of the target s true name":
        return "exact_true_name_discovery_subclause"
    if folded.startswith("at the start of your turn while wielding an approved spear weapon choose one posture"):
        return "exact_timing_and_wielding_subclause"
    return None


def _requirement_scope(label: str, body: str) -> str:
    """Separate acquisition authority from state/use requirements.

    An authenticated ``Prerequisite``/``Prerequisites`` field is acquisition
    authority by default. Generic words in its body cannot erase that label.
    Separately tokenized ``Requirement``/``Requires`` fields may be use-scoped
    when their exact semantics describe actor, target, equipment, timing, or
    execution state. Three narrow source-authenticated prerequisite exceptions
    are handled by complete-clause semantics above.
    """
    folded_label = normalize(label)
    if "prerequisite" in folded_label:
        return "use_condition" if _explicit_prerequisite_use_semantics(body) else "acquisition"
    if folded_label.startswith("available at"):
        return "acquisition"
    if folded_label in {"requirement", "requirements", "require", "requires"}:
        return "use_condition" if _LEGACY_BROAD_USE_CUE_RE.search(body) else "acquisition"
    return "acquisition"


def _partition_requirement_field(label: str, body: str) -> list[dict[str, str]]:
    """Partition the two mixed explicit prerequisite fields at exact boundaries.

    Returned ``source_text`` values are exact contiguous source substrings. No
    general prose splitter is used; ambiguous authority remains fail-closed.
    """
    folded_label = normalize(label)
    if "prerequisite" not in folded_label:
        return [{"body": body, "source_text": body, "scope": _requirement_scope(label, body), "scope_basis": "field_semantics"}]

    true_name = re.fullmatch(
        r"(?is)(?P<acquisition>CL\s*17\+\s*,\s*Immortal\s+Scripture\s*,)\s*and\s*"
        r"(?P<execution>discovery\s+of\s+the\s+target[’']s\s+True\s+Name\.)",
        body.strip(),
    )
    if true_name:
        acquisition_source = true_name.group("acquisition")
        acquisition_body = acquisition_source.rstrip(" ,")
        execution_source = "and " + true_name.group("execution")
        execution_body = true_name.group("execution").rstrip(".")
        return [
            {"body": acquisition_body, "source_text": acquisition_source, "scope": "acquisition", "scope_basis": "explicit_prerequisite_label"},
            {"body": execution_body, "source_text": execution_source, "scope": "use_condition", "scope_basis": "exact_true_name_discovery_subclause"},
        ]

    spear = re.fullmatch(
        r"(?is)(?P<acquisition>CL\s*5\+\s+Form\s+a\s+stable\s+Spear\s+Heart\.)\s*"
        r"(?P<execution>At\s+the\s+start\s+of\s+your\s+turn\s+while\s+wielding\s+an\s+approved\s+Spear\s+weapon,\s+choose\s+one\s+posture\s+until\s+the\s+start\s+of\s+your\s+next\s+turn\.)",
        body.strip(),
    )
    if spear:
        return [
            {"body": "CL 5+, Spear Heart", "source_text": spear.group("acquisition"), "scope": "acquisition", "scope_basis": "explicit_prerequisite_label"},
            {"body": spear.group("execution").rstrip("."), "source_text": spear.group("execution"), "scope": "use_condition", "scope_basis": "exact_timing_and_wielding_subclause"},
        ]

    basis = _explicit_prerequisite_use_semantics(body)
    return [{"body": body, "source_text": body, "scope": "use_condition" if basis else "acquisition", "scope_basis": basis or "explicit_prerequisite_label"}]


def talent_name_and_tags(title: str) -> tuple[str, list[str]]:
    parts = re.split(r"\s+[-–—]\s+", title, maxsplit=1)
    name = parts[0].strip()
    if len(parts) == 1:
        return name, []
    tag_text = parts[1].strip()
    tags = [part.strip() for part in tag_text.split(",") if part.strip()]
    return name, tags


def source_block(tokens: list[SourceToken], headings: list[Heading], heading: Heading) -> tuple[str, str, int, int, list[SourceToken]]:
    end_token = len(tokens)
    for following in headings:
        if following.token_index <= heading.token_index:
            continue
        if following.level <= heading.level:
            end_token = following.token_index
            break
    block_tokens = tokens[heading.token_index:end_token]
    exact = "\n".join(token.text for token in block_tokens).rstrip()
    description_parts: list[str] = []
    if heading.inline_body:
        description_parts.append(heading.inline_body)
    heading_by_token = {row.token_index: row for row in headings}
    for token in block_tokens[1:]:
        nested = heading_by_token.get(token.index)
        if nested:
            # Nested effect/target/save/result structure remains readable, but
            # Markdown heading markers are not allowed to leak into the runtime
            # description projection.
            description_parts.append(nested.title)
            if nested.inline_body:
                description_parts.append(nested.inline_body)
        else:
            description_parts.append(token.text)
    description = "\n".join(description_parts).strip()
    end_line = block_tokens[-1].source_line if block_tokens else heading.line
    end_column = (block_tokens[-1].source_column + len(block_tokens[-1].text) - 1) if block_tokens else heading.column
    return exact, description, end_line, end_column, block_tokens


def parse_realm_candidates(tokens: list[SourceToken], headings: list[Heading], spheres: list[Heading]) -> list[Candidate]:
    output: list[Candidate] = []
    for sphere_index, sphere_heading in enumerate(spheres):
        sphere_name = sphere_heading.title.removeprefix("Sphere of ").strip()
        sphere_end = spheres[sphere_index + 1].token_index if sphere_index + 1 < len(spheres) else len(tokens)
        local = [heading for heading in headings if sphere_heading.token_index < heading.token_index < sphere_end]
        roots = [(index, heading) for index, heading in enumerate(local) if is_realm_talent_heading(heading.title)]
        selected: dict[int, Candidate] = {}
        for root_index, root in roots:
            realm = realm_from_heading(root.title)
            assert realm is not None
            boundary_token = sphere_end
            # Any sibling/ancestor heading closes the realm section. This is the
            # central structural fix that prevents later notes/traditions from
            # leaking into the last realm's Talent output.
            for following in local[root_index + 1 :]:
                if following.level < root.level or (
                    following.level == root.level
                    and (is_realm_talent_heading(following.title) or structural_role(following.title) != "candidate")
                ):
                    boundary_token = following.token_index
                    break
            stack: list[tuple[int, str]] = []
            for child in local[root_index + 1 :]:
                if child.token_index >= boundary_token:
                    break
                while stack and stack[-1][0] >= child.level:
                    stack.pop()
                parent_role = stack[-1][1] if stack else "root"
                role = structural_role(child.title)
                if child.level == root.level:
                    parent_role = "root"
                if parent_role in {"candidate", "blocker"}:
                    role = "blocker"
                if role == "candidate":
                    selected[child.token_index] = Candidate(
                        sphere_name=sphere_name,
                        sphere_heading=sphere_heading,
                        heading=child,
                        section_heading=root,
                        realm=realm,
                        default_minimum_cl=REALM_ENTRY_CL[realm],
                        acquisition_route="ordinary-sphere-talent",
                        access_category="Open",
                    )
                stack.append((child.level, role))
        output.extend(selected.values())
    return output


def parse_named_talent_section(
    *, tokens: list[SourceToken], headings: list[Heading], spheres: list[Heading],
    section_title: str, realm: str, acquisition_route: str,
) -> list[Candidate]:
    output: list[Candidate] = []
    for sphere_index, sphere_heading in enumerate(spheres):
        sphere_end = spheres[sphere_index + 1].token_index if sphere_index + 1 < len(spheres) else len(tokens)
        local = [heading for heading in headings if sphere_heading.token_index < heading.token_index < sphere_end]
        for index, root in enumerate(local):
            if normalize(root.title) != normalize(section_title):
                continue
            boundary = sphere_end
            for following in local[index + 1 :]:
                if following.level <= root.level:
                    boundary = following.token_index
                    break
            stack: list[tuple[int, str]] = []
            for child in local[index + 1 :]:
                if child.token_index >= boundary:
                    break
                while stack and stack[-1][0] >= child.level:
                    stack.pop()
                parent_role = stack[-1][1] if stack else "root"
                role = structural_role(child.title)
                if parent_role in {"candidate", "blocker"}:
                    role = "blocker"
                if role == "candidate":
                    output.append(Candidate(
                        sphere_name=sphere_heading.title.removeprefix("Sphere of ").strip(),
                        sphere_heading=sphere_heading,
                        heading=child,
                        section_heading=root,
                        realm=realm,
                        default_minimum_cl=REALM_ENTRY_CL[realm],
                        acquisition_route=acquisition_route,
                        access_category="Open",
                    ))
                stack.append((child.level, role))
    return output


def secret_root_name(title: str) -> str | None:
    match = re.match(r"(?i)^secret\b.*?\binheritances?\b\s*[:–—-]\s*(.+?)\s*$", title)
    if not match:
        return None
    suffix = match.group(1).strip()
    if re.fullmatch(r"(?i)(?:CL\s*\d+\s*(?:\+|or\s+higher)?|(?:Mortal|Foundation|Core\s+Formation|Nascent\s+Soul|Immortal)\s+Realm)", suffix):
        return None
    return suffix


def explicit_minimum_cl(*values: str) -> int | None:
    minimums: list[int] = []
    for value in values:
        minimums.extend(int(match.group(1)) for match in CL_RE.finditer(value))
        for match in REALM_RE.finditer(value):
            key = re.sub(r"\s+", " ", match.group(1)).title()
            if key == "Core Formation":
                realm = key
            elif key == "Nascent Soul":
                realm = key
            else:
                realm = key
            minimums.append(REALM_ENTRY_CL[realm])
    return max(minimums) if minimums else None


def parse_secret_candidates(tokens: list[SourceToken], headings: list[Heading], spheres: list[Heading]) -> list[Candidate]:
    output: list[Candidate] = []
    for sphere_index, sphere_heading in enumerate(spheres):
        sphere_name = sphere_heading.title.removeprefix("Sphere of ").strip()
        sphere_end = spheres[sphere_index + 1].token_index if sphere_index + 1 < len(spheres) else len(tokens)
        local = [heading for heading in headings if sphere_heading.token_index < heading.token_index < sphere_end]
        roots: list[tuple[int, Heading]] = []
        for index, heading in enumerate(local):
            if not re.match(r"(?i)^secret\b.*\binheritances?\b", heading.title):
                continue
            if any(root.token_index < heading.token_index and root.level < heading.level for _, root in roots):
                continue
            roots.append((index, heading))
        for root_index, root in roots:
            root_minimum = explicit_minimum_cl(root.title) or REALM_ENTRY_CL["Nascent Soul"]
            root_realm = realm_for_cl(root_minimum)
            named = secret_root_name(root.title)
            if named:
                synthetic = replace(root, title=named)
                output.append(Candidate(
                    sphere_name=sphere_name, sphere_heading=sphere_heading, heading=synthetic,
                    section_heading=root, realm=root_realm, default_minimum_cl=root_minimum,
                    acquisition_route="secret-inheritance", access_category="Secret Inheritance",
                ))
                continue
            boundary = sphere_end
            for following in local[root_index + 1 :]:
                if following.level <= root.level:
                    boundary = following.token_index
                    break
            stack: list[tuple[int, str]] = []
            direct_children: list[Heading] = []
            for child in local[root_index + 1 :]:
                if child.token_index >= boundary:
                    break
                while stack and stack[-1][0] >= child.level:
                    stack.pop()
                parent_role = stack[-1][1] if stack else "root"
                role = structural_role(child.title)
                if parent_role in {"candidate", "blocker"}:
                    role = "blocker"
                if parent_role == "root" and role == "candidate":
                    direct_children.append(child)
                stack.append((child.level, role))
            plural_root = bool(re.search(r"(?i)\binheritances\b", root.title))
            selected = [child for child in direct_children if normalize(child.title) != "inheritance limits"] if plural_root else direct_children[:1]
            for child in selected:
                child_name = secret_root_name(child.title)
                if child_name:
                    child = replace(child, title=child_name)
                child_minimum = explicit_minimum_cl(child.title, child.inline_body, root.title) or root_minimum
                output.append(Candidate(
                    sphere_name=sphere_name, sphere_heading=sphere_heading, heading=child,
                    section_heading=root, realm=realm_for_cl(child_minimum), default_minimum_cl=child_minimum,
                    acquisition_route="secret-inheritance", access_category="Secret Inheritance",
                ))
    return output


def read_authority(source_root: Path) -> tuple[bytes, list[str]]:
    factory = source_root / FACTORY_RELATIVE_PATH
    if sha256_file(factory) != FACTORY_SHA256:
        raise ValueError("Authenticated embedded authority archive hash mismatch")
    with zipfile.ZipFile(factory) as archive:
        matches = [name for name in archive.namelist() if name.endswith(COMPENDIUM_SUFFIX)]
        if len(matches) != 1:
            raise ValueError(f"Expected one exact compendium, found {len(matches)}")
        payload = archive.read(matches[0])
    if sha256_bytes(payload) != COMPENDIUM_SHA256:
        raise ValueError("Authenticated compendium hash mismatch")
    return payload, payload.decode("utf-8").splitlines()


def load_prior(source_root: Path, name: str) -> dict[str, Any]:
    return json.loads((source_root / "catalog_authority" / "cat1" / "data" / name).read_text(encoding="utf-8"))


def source_provenance(line: int, column: int, section: str, *, exact_text: str | None = None) -> dict[str, Any]:
    result = {
        "source_pack": SOURCE_PACK,
        "source_version": SOURCE_VERSION,
        "source_path": COMPENDIUM_PATH,
        "source_file_sha256": COMPENDIUM_SHA256,
        "source_authority_sha256": FACTORY_SHA256,
        "source_anchor": f"line:{line}:column:{column}",
        "source_line": line,
        "source_column": column,
        "source_section": section,
    }
    if exact_text is not None:
        result["source_context_sha256"] = sha256_bytes(exact_text.encode("utf-8"))
    return result


def candidate_key(candidate: Candidate) -> tuple[str, str]:
    display_name, _ = talent_name_and_tags(candidate.heading.title)
    return normalize(candidate.sphere_name), normalize(display_name)


def choose_preserved_id(rows: list[dict[str, Any]], display_name: str) -> dict[str, Any]:
    expected_suffix = slug(display_name).upper()
    return sorted(rows, key=lambda row: (
        not str(row["canonical_talent_id"]).upper().endswith(expected_suffix),
        -len(str(row["canonical_talent_id"])), str(row["canonical_talent_id"]),
    ))[0]


def _load_entity_indexes(source_root: Path) -> dict[str, dict[str, list[dict[str, Any]]]]:
    indexes: dict[str, dict[str, list[dict[str, Any]]]] = {}

    def add(kind: str, name: str, target_id: str, aliases: Iterable[str] = (), **metadata: Any) -> None:
        for label in [name, *aliases]:
            key = normalize(label)
            if not key:
                continue
            indexes.setdefault(kind, {}).setdefault(key, []).append({"target_id": target_id, "display_name": name, **metadata})

    paths = json.loads((source_root / "non_sphere_authority" / "authority" / "Tianxia_Path_Index_Master_P2A.json").read_text(encoding="utf-8"))
    for row in paths["paths"]:
        add("path", row["display_name"], row["canonical_id"], [row["display_name"] + " Path"])
    subpaths = json.loads((source_root / "non_sphere_authority" / "authority" / "Tianxia_Subpath_Tradition_Index_Master_P2B.json").read_text(encoding="utf-8"))
    for row in subpaths["entries"]:
        add("subpath_or_tradition", row["display_name"], row["canonical_id"], row.get("aliases") or [])
    methods = json.loads((source_root / "non_sphere_authority" / "authority" / "Tianxia_Methods_Typed_Registry_v0_6.json").read_text(encoding="utf-8"))
    for row in methods["methods"]:
        add("method", row["name"], row["method_id"])
    foundations = json.loads((source_root / "non_sphere_authority" / "authority" / "Foundation_Runtime_Authority_v0_4C.json").read_text(encoding="utf-8"))
    for row in [*foundations["orthodox"], *foundations["theoretical_chakra"]]:
        add("foundation_or_feature", row["display_name"], row["foundation_id"])
        for feature in row.get("feature_labels") or []:
            add("foundation_or_feature", feature, row["foundation_id"])
    return indexes


def _add_structural_authority_indexes(
    source_root: Path, indexes: dict[str, dict[str, list[dict[str, Any]]]], *,
    headings: list[Heading], spheres: list[Heading], candidate_tokens: set[int],
) -> None:
    """Index exact source-backed structure without promoting it to Talents."""
    def add(name: str, target_id: str, *, sphere_name: str | None = None, source_line: int | None = None) -> None:
        key = normalize(name)
        if not key:
            return
        row = {"target_id": target_id, "display_name": name, "sphere_name": sphere_name, "source_line": source_line}
        bucket = indexes.setdefault("structural_authority", {}).setdefault(key, [])
        if any(
            normalize(existing["display_name"]) == normalize(name)
            and normalize(existing.get("sphere_name") or "") == normalize(sphere_name or "")
            for existing in bucket
        ):
            return
        if not any(existing["target_id"] == target_id for existing in bucket):
            bucket.append(row)

    legacy = json.loads((source_root / "catalog" / "sphere_talent_authority_v1.json").read_text(encoding="utf-8"))
    for row in legacy["records"].values():
        if not row.get("selectable_talent"):
            add(row["display_name"], row["record_id"], sphere_name=row.get("sphere_name"))

    for sphere_index, sphere in enumerate(spheres):
        sphere_name = sphere.title.removeprefix("Sphere of ").strip()
        end = spheres[sphere_index + 1].token_index if sphere_index + 1 < len(spheres) else 10**9
        for heading in headings:
            if not (sphere.token_index < heading.token_index < end) or heading.token_index in candidate_tokens:
                continue
            name, _ = talent_name_and_tags(heading.title)
            aliases: list[tuple[str, bool, str | None]] = [(name, False, None)]
            base = re.match(r"(?i)^BASE\s+ABILITY\s+\d+\s*:\s*(.+)$", name)
            if base:
                feature = base.group(1).strip()
                aliases.append((
                    feature,
                    True,
                    f"tianxia.structural.feature.{slug(feature)}",
                ))
            if normalize(name).endswith(" talents"):
                aliases.append((re.sub(r"(?i)\s+TALENTS\s*$", "", name).strip(), False, None))
                realm_category = re.match(
                    r"(?i)^(?:MORTAL|FOUNDATION|CORE\s+FORMATION|NASCENT\s+SOUL|IMMORTAL)\s+REALM\s+(.+?)\s+TALENTS$",
                    name,
                )
                if realm_category:
                    category = realm_category.group(1).strip()
                    aliases.append((
                        category,
                        True,
                        f"tianxia.structural.{slug(sphere_name)}.talent_category.{slug(category)}",
                    ))
            if normalize(name) == "extra attack and multiattack":
                aliases.extend([("Extra Attack", False, None), ("Multiattack", False, None)])
            for alias, explicit_single_word_alias, target_override in aliases:
                if len(normalize(alias).split()) < 2 and not explicit_single_word_alias:
                    continue
                add(
                    alias,
                    target_override or f"tianxia.structural.{slug(sphere_name)}.{slug(alias)}",
                    sphere_name=sphere_name,
                    source_line=heading.line,
                )
    # This authenticated structural heading defines two distinct feature names.
    # Preserve both exact names even though the combined heading sits outside
    # the selectable-Talent set.
    for heading in headings:
        if normalize(heading.title) == "extra attack and multiattack":
            for alias in ("Extra Attack", "Multiattack"):
                add(
                    alias,
                    f"tianxia.structural.feature.{slug(alias)}",
                    source_line=heading.line,
                )


def _extract_prerequisite_clauses(block_tokens: list[SourceToken], heading: Heading, sphere_name: str) -> list[dict[str, Any]]:
    clauses: list[dict[str, Any]] = []
    scan: list[tuple[str, int, int]] = [(heading.inline_body, heading.line, heading.column)] if heading.inline_body else []
    scan.extend((token.text, token.source_line, token.source_column) for token in block_tokens[1:])
    seen: set[tuple[int, int, str]] = set()
    for text, line, column in scan:
        plain = re.sub(r"[*_`]", "", text).strip()
        for raw_label, body, start, end in _structured_field_segments(plain):
            label = re.sub(r"\s+", " ", raw_label.strip()).title()
            if not PREREQUISITE_LABEL_RE.fullmatch(label):
                continue
            if not normalize(body) or normalize(body) in {"higher", "above"}:
                continue
            key = (line, column + start, body)
            if key in seen:
                continue
            seen.add(key)
            field_raw_text = plain[start:end].strip()
            field_id = f"field:{line}:{column + start}:{sha256_bytes(field_raw_text.encode('utf-8'))[:12]}"
            search_at = start
            for partition_index, partition in enumerate(_partition_requirement_field(label, body), 1):
                source_text = partition["source_text"]
                source_start = plain.find(source_text, search_at, end)
                if source_start < 0:
                    raise ValueError(f"Partitioned prerequisite source text was not found: {source_text!r}")
                search_at = source_start + len(source_text)
                raw_text = source_text
                if partition_index == 1:
                    label_prefix = plain[start:source_start]
                    raw_text = (label_prefix + source_text).strip()
                partition_body = partition["body"]
                clause_id = f"clause:{line}:{column + source_start}:{sha256_bytes(partition_body.encode('utf-8'))[:12]}"
                clauses.append({
                    "clause_id": clause_id,
                    "source_field_id": field_id,
                    "source_field_raw_text": field_raw_text,
                    "source_field_label": label,
                    "source_field_partition": partition_index,
                    "label": label,
                    "scope": partition["scope"],
                    "scope_basis": partition["scope_basis"],
                    "raw_text": raw_text,
                    "body": partition_body,
                    "source_provenance": source_provenance(
                        line, column + source_start, f"Sphere of {sphere_name}", exact_text=raw_text,
                    ),
                })
    return clauses


def _phrase_occurs(normalized_body: str, phrase: str) -> bool:
    return f" {phrase} " in f" {normalized_body} "


def _exact_reference_occurs(raw_text: str, normalized_body: str, phrase: str) -> bool:
    if not _phrase_occurs(normalized_body, phrase):
        return False
    words = phrase.split()
    if len(words) != 1:
        exact = r"[\s'’\-–—]+".join(re.escape(word) for word in words)
        return re.search(rf"(?i)(?<!\w){exact}(?!\w)", raw_text) is not None
    # A one-word stable name embedded in a hyphenated compound (for example
    # ``world-root pact``) is not an authored reference to the Talent ``Root``.
    return re.search(rf"(?i)(?<![\w-]){re.escape(phrase)}(?![\w-])", raw_text) is not None


def _exact_named_reference_occurs(raw_text: str, normalized_body: str, phrase: str, display_name: str) -> bool:
    """Allow comma separators only for an authority name that contains them."""
    if _exact_reference_occurs(raw_text, normalized_body, phrase):
        return True
    if "," not in display_name or not _phrase_occurs(normalized_body, phrase):
        return False
    words = phrase.split()
    exact = r"[\s,'’\-–—]+".join(re.escape(word) for word in words)
    return re.search(rf"(?i)(?<!\w){exact}(?!\w)", raw_text) is not None


def _consume_phrase(normalized_body: str, phrase: str) -> str:
    return (" " + normalized_body + " ").replace(" " + phrase + " ", " ", 1).strip()


def _compile_prerequisites(
    *, clauses: list[dict[str, Any]], minimum_cl: int, sphere_id: str, sphere_name: str,
    talent_id: str, talent_tags: list[str], talent_source_line: int,
    entity_indexes: dict[str, dict[str, list[dict[str, Any]]]],
    talent_indexes: dict[str, dict[str, list[dict[str, Any]]]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, bool, str | None]:
    predicates: list[dict[str, Any]] = [
        {
            "predicate_id": f"implicit:{talent_id}:minimum_cl",
            "clause_id": None, "alternative_id": None, "scope": "acquisition",
            "kind": "minimum_cl", "value": minimum_cl, "resolution_status": "resolved",
            "source_basis": "strictest explicit numeric/realm constraint or exact authored realm-section entry CL",
        },
        {
            "predicate_id": f"implicit:{talent_id}:owning_sphere",
            "clause_id": None, "alternative_id": None, "scope": "acquisition",
            "kind": "owning_sphere", "target_id": sphere_id, "display_name": sphere_name,
            "resolution_status": "resolved", "source_basis": "exact Sphere section containment",
        },
    ]
    compiled_clauses: list[dict[str, Any]] = []
    unresolved_acquisition: list[str] = []
    unresolved_use: list[str] = []
    all_indexes = {**entity_indexes, "talent": talent_indexes.get(normalize(sphere_name), {})}
    global_talents = talent_indexes.get("*", {})

    for clause in clauses:
        # Preserve authored alternatives. Every alternative is all-of; the clause
        # is any-of. This is deterministic and fail-closed for ambiguous text.
        branch_texts = [part.strip() for part in re.split(r"(?i)\s+or\s+(?!higher\b|above\b)", clause["body"]) if part.strip()]
        if not branch_texts:
            branch_texts = [clause["body"]]
        alternative_rows: list[dict[str, Any]] = []
        for branch_index, branch in enumerate(branch_texts, 1):
            alternative_id = f"{clause['clause_id']}:alt:{branch_index}"
            normalized = normalize(branch)
            matched_spans: list[tuple[int, int]] = []
            branch_predicates: list[str] = []

            def add_predicate(kind: str, *, target_id: str | None = None, display_name: str | None = None, value: Any = None, exact: str, status: str = "resolved", reason: str | None = None) -> None:
                pred_id = f"predicate:{sha256_bytes((alternative_id + '|' + kind + '|' + exact + '|' + str(target_id or value)).encode('utf-8'))[:20]}"
                row: dict[str, Any] = {
                    "predicate_id": pred_id, "clause_id": clause["clause_id"], "alternative_id": alternative_id,
                    "scope": clause["scope"], "kind": kind, "resolution_status": status,
                    "raw_text": exact, "source_provenance": clause["source_provenance"],
                }
                if target_id is not None:
                    row["target_id"] = target_id
                if display_name is not None:
                    row["display_name"] = display_name
                if value is not None:
                    row["value"] = value
                if reason:
                    row["owner_reason"] = reason
                predicates.append(row)
                branch_predicates.append(pred_id)

            for match in CL_RE.finditer(branch):
                add_predicate("minimum_cl", value=int(match.group(1)), exact=match.group(0))
                matched_spans.append(match.span())
            for match in REALM_RE.finditer(branch):
                realm = re.sub(r"\s+", " ", match.group(1)).title()
                add_predicate("realm", value=realm, exact=match.group(0))
                matched_spans.append(match.span())

            # Typed counts over an exact authored same-Sphere Talent tag are
            # acquisition authority, not an unresolved text fragment.
            same_sphere_rows = {
                row["target_id"]: row
                for rows in talent_indexes.get(normalize(sphere_name), {}).values()
                for row in rows
            }
            exact_tags = {
                normalize(tag): tag
                for row in same_sphere_rows.values()
                for tag in row.get("tags") or []
                if normalize(tag)
            }
            count_words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
            for match in re.finditer(
                r"(?i)\b(?:at\s+least\s+)?(?P<count>one|two|three|four|five|\d+)\s+(?P<tag>[A-Za-z][A-Za-z '\-–—]+?)\s+talents?\b",
                branch,
            ):
                tag_key = normalize(match.group("tag"))
                if tag_key not in exact_tags:
                    continue
                raw_count = match.group("count").casefold()
                minimum = count_words.get(raw_count, int(raw_count) if raw_count.isdigit() else 0)
                display_tag = exact_tags[tag_key]
                add_predicate(
                    "talent_tag_count", target_id=f"tag:{slug(display_tag)}",
                    display_name=display_tag, value=minimum, exact=match.group(0),
                )
                normalized = _consume_phrase(normalized, normalize(match.group(0)))

            # Exact Talent names are authoritative before any generic Sphere or
            # other catalog alias may consume a word from the name. Same-Sphere
            # exact names win; only a globally unique exact name is a fallback.
            longer_exact_authority = {
                phrase
                for kind, index in entity_indexes.items()
                if kind != "sphere"
                for phrase in index
                if _exact_reference_occurs(branch, normalized, phrase)
            }
            explicit_sphere_names = {
                phrase
                for phrase in entity_indexes.get("sphere", {})
                if _phrase_occurs(normalized, phrase + " sphere")
                or _phrase_occurs(normalized, "sphere of " + phrase)
            }
            talent_candidates: list[tuple[str, dict[str, Any]]] = []
            candidate_phrases = set(all_indexes.get("talent", {})).union(global_talents)
            for phrase in candidate_phrases:
                indexed_rows = [
                    *all_indexes.get("talent", {}).get(phrase, []),
                    *global_talents.get(phrase, []),
                ]
                if not any(
                    _exact_named_reference_occurs(branch, normalized, phrase, row["display_name"])
                    for row in indexed_rows
                ):
                    continue
                if any(
                    longer != phrase and len(longer) > len(phrase) and _phrase_occurs(longer, phrase)
                    for longer in longer_exact_authority.union(explicit_sphere_names)
                ):
                    continue
                same = {
                    row["target_id"]: row for row in all_indexes.get("talent", {}).get(phrase, [])
                    if row["target_id"] != talent_id
                    and _exact_named_reference_occurs(branch, normalized, phrase, row["display_name"])
                }
                global_unique = {
                    row["target_id"]: row for row in global_talents.get(phrase, [])
                    if row["target_id"] != talent_id
                    and _exact_named_reference_occurs(branch, normalized, phrase, row["display_name"])
                }
                target: dict[str, Any] | None = next(iter(same.values())) if len(same) == 1 else None
                pool = same or global_unique
                if target is None and len(pool) > 1:
                    current_tags = {normalize(tag) for tag in talent_tags}
                    tagged = [
                        row for row in pool.values()
                        if current_tags.intersection(normalize(tag) for tag in row.get("tags") or [])
                    ]
                    if len(tagged) == 1:
                        target = tagged[0]
                    else:
                        preceding = [row for row in pool.values() if int(row.get("source_line") or 0) < talent_source_line]
                        if preceding:
                            nearest = sorted(preceding, key=lambda row: (-int(row.get("source_line") or 0), row["target_id"]))
                            if len(nearest) == 1 or nearest[0].get("source_line") != nearest[1].get("source_line"):
                                target = nearest[0]
                if target is None and len(global_unique) == 1:
                    target = next(iter(global_unique.values()))
                if target is not None:
                    talent_candidates.append((phrase, target))
            for phrase, target in sorted(talent_candidates, key=lambda item: (-len(item[0]), item[0])):
                if not _exact_named_reference_occurs(branch, normalized, phrase, target["display_name"]):
                    continue
                add_predicate("talent", target_id=target["target_id"], display_name=target["display_name"], exact=target["display_name"])
                normalized = _consume_phrase(normalized, phrase)

            # Longest exact non-Sphere authority names follow Talent names.
            index_kinds = ["path", "subpath_or_tradition", "method", "foundation_or_feature", "structural_authority"]
            for kind in index_kinds:
                for phrase in sorted(all_indexes.get(kind, {}), key=lambda item: (-len(item), item)):
                    if not _exact_reference_occurs(branch, normalized, phrase):
                        continue
                    matches = all_indexes[kind][phrase]
                    if kind == "structural_authority" and len(phrase.split()) == 1:
                        # A one-word structural name is safe only when it is the
                        # entire authored prerequisite after ordinary CL/realm
                        # syntax is removed.  This admits exact source-backed
                        # features such as ``Interpose`` while still rejecting
                        # incidental prose such as ``comparable source`` and
                        # hyphen compounds such as ``world-root pact``.
                        category_clause = normalize(REALM_RE.sub(" ", CL_RE.sub(" ", branch)))
                        category_clause = re.sub(
                            r"\b(?:and|or|the|a|an|to|of|with|access|must|have|has|requires|required|"
                            r"requirement|prerequisite|sphere|path|realm|talent|talents|one|any|either|"
                            r"higher|above|at|least)\b",
                            " ", category_clause,
                        )
                        category_clause = re.sub(r"\s+", " ", category_clause).strip()
                        if category_clause != phrase:
                            continue
                    if kind == "structural_authority":
                        explicit_feature = [
                            row for row in matches
                            if str(row.get("target_id") or "").startswith("tianxia.structural.feature.")
                        ]
                        if explicit_feature:
                            matches = explicit_feature
                    unique = {row["target_id"]: row for row in matches}
                    same_sphere = {
                        row["target_id"]: row for row in matches
                        if not row.get("sphere_name") or normalize(row["sphere_name"]) == normalize(sphere_name)
                    }
                    target = next(iter(same_sphere.values())) if len(same_sphere) == 1 else (next(iter(unique.values())) if len(unique) == 1 else None)
                    if target is not None:
                        add_predicate(kind, target_id=target["target_id"], display_name=target["display_name"], exact=target["display_name"])
                        normalized = _consume_phrase(normalized, phrase)

            # Generic Sphere aliases are deliberately last.
            for phrase in sorted(entity_indexes.get("sphere", {}), key=lambda item: (-len(item), item)):
                sphere_phrase = phrase + " sphere"
                sphere_of_phrase = "sphere of " + phrase
                if _phrase_occurs(normalized, sphere_phrase) or _phrase_occurs(normalized, sphere_of_phrase):
                    matches = entity_indexes["sphere"][phrase]
                    if len({row["target_id"] for row in matches}) == 1:
                        target = matches[0]
                        add_predicate("sphere", target_id=target["target_id"], display_name=target["display_name"], exact=target["display_name"])
                        normalized = _consume_phrase(normalized, sphere_phrase)
                        normalized = _consume_phrase(normalized, sphere_of_phrase)

            # Remove numeric/realm tokens and ordinary connective language before
            # determining whether authored authority remains unresolved.
            residual = CL_RE.sub(" ", branch)
            residual = REALM_RE.sub(" ", residual)
            for predicate_id in branch_predicates:
                row = next(item for item in predicates if item["predicate_id"] == predicate_id)
                exact = row.get("raw_text") or row.get("display_name") or ""
                if exact:
                    residual = re.sub(re.escape(exact), " ", residual, flags=re.I)
            # Use the already-consumed normalized branch for the resolution
            # decision. Raw-text removal is retained only for owner-readable
            # evidence; it cannot reintroduce punctuation fragments.
            normalized_residual = CL_RE.sub(" ", normalized)
            normalized_residual = REALM_RE.sub(" ", normalized_residual)
            normalized_residual = re.sub(
                r"\b(?:and|or|the|a|an|to|of|with|access|must|have|has|requires|required|requirement|prerequisite|sphere|path|realm|talent|one|any|either|higher|above|at|least)\b",
                " ", normalized_residual,
            )
            normalized_residual = re.sub(r"\s+", " ", normalized_residual).strip()

            provenance_terms = re.findall(
                r"(?i)\b(?:teacher|master|scripture|inheritance|revelation|permission|gm|story|sect|manual|lineage|bloodline|authority|initiation)\b",
                residual,
            )
            equipment_terms = re.findall(
                r"(?i)\b(?:supplies|cauldron|weapon|armor|shield|tool|instrument|item|talisman|forge|workshop|material|equipment)\b",
                residual,
            )
            if provenance_terms:
                add_predicate(
                    "acquisition_provenance", value=sorted({normalize(term) for term in provenance_terms}), exact=branch,
                    reason="Exact teacher/scripture/inheritance/story provenance must be recorded.",
                )
                normalized_residual = ""
            elif equipment_terms:
                add_predicate(
                    "equipment_or_use_condition", value=branch, exact=branch,
                    reason="The exact authored equipment or use condition must be evidenced when relevant.",
                )
                normalized_residual = ""

            if normalized_residual:
                reason = f"Unresolved exact authority phrase: {normalized_residual}"
                add_predicate("unresolved", value=normalized_residual, exact=branch, status="unresolved", reason=reason)
                (unresolved_acquisition if clause["scope"] == "acquisition" else unresolved_use).append(reason)
            alternative_rows.append({
                "alternative_id": alternative_id,
                "operator": "all_of",
                "raw_text": branch,
                "predicate_ids": branch_predicates,
            })
        compiled_clauses.append({
            **clause,
            "operator": "any_of",
            "alternatives": alternative_rows,
            "resolution_status": "unresolved" if any(
                next(pred for pred in predicates if pred["predicate_id"] == pid)["resolution_status"] == "unresolved"
                for alt in alternative_rows for pid in alt["predicate_ids"]
            ) else "resolved",
        })

    if unresolved_acquisition:
        status = "UNRESOLVED_FAIL_CLOSED"
        safe = False
        unresolved_reason = "; ".join(sorted(set(unresolved_acquisition)))
    elif unresolved_use:
        status = "TYPED_ACQUISITION_USE_CONDITION_UNRESOLVED"
        safe = True
        unresolved_reason = "; ".join(sorted(set(unresolved_use)))
    else:
        status = "TYPED"
        safe = True
        unresolved_reason = None
    return predicates, compiled_clauses, status, safe, unresolved_reason


def _secret_child_options(candidate: Candidate, headings: list[Heading]) -> list[dict[str, Any]]:
    """Project sibling result modes as child choices of one singular inheritance."""
    if candidate.acquisition_route != "secret-inheritance":
        return []
    if re.search(r"(?i)\binheritances\b", candidate.section_heading.title):
        return []
    rows: list[dict[str, Any]] = []
    for heading in headings:
        if heading.token_index <= candidate.heading.token_index:
            continue
        if heading.level < candidate.heading.level:
            break
        if heading.level != candidate.heading.level:
            continue
        if normalize(heading.title) == "inheritance limits":
            break
        rows.append({
            "choice_id": f"{slug(candidate.heading.title)}.{slug(heading.title)}",
            "display_name": heading.title,
            "source_provenance": source_provenance(
                heading.line,
                heading.column,
                f"Sphere of {candidate.sphere_name}",
                exact_text=heading.raw_text,
            ),
        })
    return rows


def _explicit_access_category(candidate: Candidate, tags: list[str], block_tokens: list[SourceToken]) -> tuple[str, list[dict[str, Any]]]:
    category = candidate.access_category
    evidence: list[dict[str, Any]] = []
    explicit_values: list[tuple[str, int, int]] = []
    for tag in tags:
        folded = normalize(tag)
        if folded in {"forbidden", "forbidden legacy", "restricted", "secret", "secret inheritance"}:
            explicit_values.append((tag, candidate.heading.line, candidate.heading.column))
    for token in block_tokens:
        plain = re.sub(r"[*_`]", "", token.text).strip()
        match = ACCESS_FIELD_RE.match(plain)
        if match:
            explicit_values.append((match.group(1), token.source_line, token.source_column))
        elif normalize(plain) in {"forbidden", "forbidden legacy", "restricted", "secret", "secret inheritance"}:
            explicit_values.append((plain, token.source_line, token.source_column))
    for value, line, column in explicit_values:
        folded = normalize(value)
        if "forbidden" in folded:
            category = "Forbidden Legacy"
        elif "secret" in folded or "inheritance" in folded:
            category = "Secret Inheritance"
        elif "restricted" in folded:
            category = "Restricted"
        evidence.append({"value": value, "source_provenance": source_provenance(line, column, f"Sphere of {candidate.sphere_name}", exact_text=value)})
    if category != "Open" and not evidence:
        evidence.append({
            "value": candidate.section_heading.title,
            "source_provenance": source_provenance(candidate.section_heading.line, candidate.section_heading.column, f"Sphere of {candidate.sphere_name}", exact_text=candidate.section_heading.raw_text),
        })
    return category, evidence


def _migration_evidence(*, sphere: str, display_name: str, source_provenance_row: dict[str, Any], exact_text: str, record_commitment: str | None = None) -> dict[str, Any]:
    evidence = {
        "source_pack": SOURCE_PACK,
        "source_path": COMPENDIUM_PATH,
        "source_file_sha256": COMPENDIUM_SHA256,
        "source_authority_sha256": FACTORY_SHA256,
        "source_anchor": source_provenance_row["source_anchor"],
        "source_context_sha256": sha256_bytes(exact_text.encode("utf-8")),
        "owning_sphere": sphere,
        "display_name": display_name,
    }
    if record_commitment:
        evidence["canonical_record_commitment_sha256"] = record_commitment
    return evidence


def build(source_root: Path, output_root: Path) -> dict[str, Any]:
    _, physical_lines = read_authority(source_root)
    tokens = tokenize_source(physical_lines)
    headings = [heading for token in tokens if (heading := parse_heading(token))]
    spheres = [heading for heading in headings if heading.level == 1 and heading.title.startswith("Sphere of ")]
    if len(spheres) != EXPECTED_SPHERES:
        raise ValueError(f"Expected 85 exact Sphere sections, found {len(spheres)}")
    sphere_names = [heading.title.removeprefix("Sphere of ").strip() for heading in spheres]
    if len(set(sphere_names)) != EXPECTED_SPHERES:
        raise ValueError("Duplicate canonical Sphere headings")

    candidates = parse_realm_candidates(tokens, headings, spheres)
    candidates.extend(parse_named_talent_section(tokens=tokens, headings=headings, spheres=spheres, section_title="BASIC SHADOW TALENTS", realm="Mortal", acquisition_route="ordinary-sphere-talent"))
    candidates.extend(parse_named_talent_section(tokens=tokens, headings=headings, spheres=spheres, section_title="SCRIPT-SEALED MECHANIST TALENTS", realm="Mortal", acquisition_route="variant-specific-talent"))
    candidates.extend(parse_secret_candidates(tokens, headings, spheres))
    unique_candidates = {(row.sphere_name, row.heading.token_index): row for row in candidates}
    candidates = sorted(unique_candidates.values(), key=lambda row: (row.sphere_heading.token_index, row.heading.token_index))

    old_talents = load_prior(source_root, "canonical_talents.v1.json")["records"]
    old_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in old_talents:
        old_sphere = "The Piercing Needle" if row.get("legacy_source_sphere_label") == "Fencing" else row["owning_canonical_sphere_name"]
        old_by_key[(normalize(old_sphere), normalize(row["display_name"]))].append(row)

    sphere_ids = {name: f"tianxia.sphere.{slug(name)}" for name in sphere_names}
    entity_indexes = _load_entity_indexes(source_root)
    entity_indexes["sphere"] = {}
    for name, sphere_id in sphere_ids.items():
        labels = [name]
        if name.casefold().startswith("the "):
            labels.append(name[4:])
        for label in labels:
            entity_indexes["sphere"].setdefault(normalize(label), []).append({"target_id": sphere_id, "display_name": name})
    for row in load_prior(source_root, "sphere_aliases_and_labels.v1.json")["records"]:
        if row.get("canonical_sphere_id") in sphere_ids.values():
            entity_indexes["sphere"].setdefault(normalize(row["label"]), []).append({
                "target_id": row["canonical_sphere_id"],
                "display_name": row.get("canonical_display_name") or row["label"],
            })

    drafts: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    preserved_by_candidate: dict[int, list[dict[str, Any]]] = {}
    for candidate in candidates:
        display_name, tags = talent_name_and_tags(candidate.heading.title)
        exact_text, description, end_line, end_column, block_tokens = source_block(tokens, headings, candidate.heading)
        clauses = _extract_prerequisite_clauses(block_tokens, candidate.heading, candidate.sphere_name)
        explicit_text = "\n".join(dict.fromkeys(clause.get("source_field_raw_text", clause["raw_text"]) for clause in clauses))
        minimum_cl = explicit_minimum_cl(candidate.heading.title, candidate.heading.inline_body, explicit_text, candidate.section_heading.title)
        if minimum_cl is None:
            minimum_cl = candidate.default_minimum_cl
        preserved_rows = old_by_key.get(candidate_key(candidate), [])
        preserved = choose_preserved_id(preserved_rows, display_name) if preserved_rows else None
        talent_id = preserved["canonical_talent_id"] if preserved else f"tianxia.talent.{slug(candidate.sphere_name)}.{slug(display_name)}"
        if talent_id in used_ids:
            talent_id = f"{talent_id}.{slug(candidate.realm)}"
        if talent_id in used_ids:
            talent_id = f"{talent_id}.{sha256_bytes((candidate.heading.title + str(candidate.heading.token_index)).encode('utf-8'))[:10]}"
        if talent_id in used_ids:
            raise ValueError(f"Canonical Talent ID collision: {talent_id}")
        used_ids.add(talent_id)
        access_category, access_evidence = _explicit_access_category(candidate, tags, block_tokens)
        provenance = source_provenance(candidate.heading.line, candidate.heading.column, f"Sphere of {candidate.sphere_name}", exact_text=exact_text)
        drafts.append({
            "candidate": candidate, "canonical_talent_id": talent_id, "display_name": display_name,
            "tags": tags, "exact_text": exact_text, "description": description, "end_line": end_line,
            "end_column": end_column, "clauses": clauses, "minimum_cl": minimum_cl,
            "access_category": access_category, "access_evidence": access_evidence,
            "source_provenance": provenance, "preserved": preserved,
            "child_options": _secret_child_options(candidate, headings),
        })
        preserved_by_candidate[candidate.heading.token_index] = preserved_rows

    _add_structural_authority_indexes(
        source_root, entity_indexes, headings=headings, spheres=spheres,
        candidate_tokens={row.heading.token_index for row in candidates},
    )

    talent_indexes: dict[str, dict[str, list[dict[str, Any]]]] = {"*": {}}
    for draft in drafts:
        row = {
            "target_id": draft["canonical_talent_id"], "display_name": draft["display_name"],
            "tags": draft["tags"], "source_line": draft["source_provenance"]["source_line"],
            "sphere_name": draft["candidate"].sphere_name,
        }
        labels = [draft["display_name"]]
        if draft["display_name"].casefold().startswith("the "):
            labels.append(draft["display_name"][4:])
        if ":" in draft["display_name"]:
            prefix, suffix = (part.strip() for part in draft["display_name"].split(":", 1))
            labels.extend([prefix, suffix])
        if "domain" in normalize(draft["display_name"]):
            labels.extend(draft["tags"])
            labels.extend(f"{draft['display_name']} {tag}" for tag in draft["tags"])
        sphere_key = normalize(draft["candidate"].sphere_name)
        for label in labels:
            key = normalize(label)
            if not key:
                continue
            talent_indexes.setdefault(sphere_key, {}).setdefault(key, []).append(row)
            talent_indexes["*"].setdefault(key, []).append(row)

    talents: list[dict[str, Any]] = []
    migrations: list[dict[str, Any]] = []
    candidate_by_key: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for draft in drafts:
        candidate: Candidate = draft["candidate"]
        predicates, compiled_clauses, status, safe, unresolved_reason = _compile_prerequisites(
            clauses=draft["clauses"], minimum_cl=draft["minimum_cl"],
            sphere_id=sphere_ids[candidate.sphere_name], sphere_name=candidate.sphere_name,
            talent_id=draft["canonical_talent_id"], talent_tags=draft["tags"],
            talent_source_line=draft["source_provenance"]["source_line"],
            entity_indexes=entity_indexes, talent_indexes=talent_indexes,
        )
        if draft["access_category"] != "Open" and not any(
            row["kind"] == "acquisition_provenance" and row["scope"] == "acquisition"
            for row in predicates
        ):
            predicates.append({
                "predicate_id": f"implicit:{draft['canonical_talent_id']}:access_provenance",
                "clause_id": None, "alternative_id": None, "scope": "acquisition",
                "kind": "acquisition_provenance", "value": draft["access_category"],
                "resolution_status": "resolved",
                "owner_reason": f"{draft['access_category']} content requires exact acquisition provenance.",
                "source_basis": "authenticated access classification on the canonical Talent record",
            })
        aliases: list[str] = []
        record_payload = {
            "canonical_talent_id": draft["canonical_talent_id"],
            "display_name": draft["display_name"],
            "exact_heading": candidate.heading.raw_text,
            "owning_canonical_sphere_id": sphere_ids[candidate.sphere_name],
            "owning_canonical_sphere_name": candidate.sphere_name,
            "membership_kind": "exact-authored-sphere-membership",
            "minimum_cl": draft["minimum_cl"],
            "realm_band": realm_for_cl(draft["minimum_cl"]),
            "section_realm": candidate.realm,
            "tags": draft["tags"],
            "raw_prerequisite_text": "\n".join(dict.fromkeys(clause.get("source_field_raw_text", clause["raw_text"]) for clause in draft["clauses"])),
            "prerequisite_clauses": compiled_clauses,
            "typed_prerequisites": predicates,
            "prerequisite_evaluation_status": status,
            "creator_selectability_can_be_evaluated_safely": safe,
            "unresolved_reason": unresolved_reason,
            "access_category": draft["access_category"],
            "access_classification_evidence": draft["access_evidence"],
            "acquisition_provenance_required": draft["access_category"] != "Open" or any(p["kind"] == "acquisition_provenance" and p["scope"] == "acquisition" for p in predicates),
            "creator_access_semantics": "RECORD_PROVENANCE_ON_INITIAL_SELECTION; REQUIRE_EXACT_EVIDENCE_POST_CREATION",
            "acquisition_routes": [candidate.acquisition_route],
            "child_options": draft["child_options"],
            "ordinary_talent": candidate.acquisition_route == "ordinary-sphere-talent",
            "free_sphere_talent_eligible": candidate.acquisition_route == "ordinary-sphere-talent" and draft["access_category"] == "Open",
            "automatic_grant": False,
            "background_only": False,
            "full_exact_source_text": draft["exact_text"],
            "full_description": draft["description"],
            "source_text_end_line": draft["end_line"],
            "source_text_end_column": draft["end_column"],
            "source_provenance": draft["source_provenance"],
            "preserved_legacy_id": draft["canonical_talent_id"] if draft["preserved"] else None,
            "migration_aliases": aliases,
            "compiler_version": COMPILER_VERSION,
        }
        record = committed(record_payload)
        # Exact duplicate legacy IDs bind only after the canonical record has a
        # commitment, so migration evidence can identify the precise target.
        preserved_rows = preserved_by_candidate[candidate.heading.token_index]
        for duplicate in preserved_rows:
            duplicate_id = duplicate["canonical_talent_id"]
            if duplicate_id == record["canonical_talent_id"]:
                continue
            aliases.append(duplicate_id)
            migrations.append({
                "legacy_id": duplicate_id, "canonical_id": record["canonical_talent_id"],
                "record_type": "talent", "migration_kind": "EXACT_DUPLICATE_ALIAS",
                "evidence": _migration_evidence(
                    sphere=candidate.sphere_name, display_name=draft["display_name"],
                    source_provenance_row=draft["source_provenance"], exact_text=draft["exact_text"],
                    record_commitment=record["record_commitment_sha256"],
                ),
            })
        if aliases:
            record_payload["migration_aliases"] = sorted(aliases)
            record = committed(record_payload)
            # Refresh target commitment in those migration rows.
            for migration in migrations[-len(aliases):]:
                migration["evidence"]["canonical_record_commitment_sha256"] = record["record_commitment_sha256"]
        talents.append(record)
        candidate_by_key[(normalize(candidate.sphere_name), normalize(draft["display_name"]))].append(record)

    # Unmatched prior Talent IDs are retired as explicit non-selectable legacy
    # findings. They are never guessed onto a containing record.
    migrated_or_current = {row["canonical_talent_id"] for row in talents} | {row["legacy_id"] for row in migrations}
    retired_prior: list[dict[str, Any]] = []
    for prior in old_talents:
        prior_id = prior["canonical_talent_id"]
        if prior_id in migrated_or_current:
            continue
        retired_prior.append(committed({
            "record_id": prior_id,
            "display_name": prior["display_name"],
            "legacy_source_sphere_name": prior.get("owning_canonical_sphere_name") or prior.get("legacy_source_sphere_label"),
            "source_role": "retired_non_talent_or_unresolved_prior_projection",
            "source_role_reason": "CAT3-P1R structural parsing did not establish this prior projected ID as an authored selectable Talent; it remains review-compatible but non-selectable.",
            "source_citation": [prior.get("exact_source_anchor")],
            "source_path": COMPENDIUM_PATH,
            "source_hash": COMPENDIUM_SHA256,
            "source_anchor": prior.get("exact_source_anchor"),
        }))

    old_mixed = load_prior(source_root, "mixed_candidate_classification.v1.json")["records"]
    quarantined_prior = [row for row in old_mixed if row["cat1_classification"] == "AMBIGUOUS_REQUIRES_AUTHORITY_DECISION"]
    quarantine: list[dict[str, Any]] = []
    for row in quarantined_prior:
        sphere_name = {"Fencing": "The Piercing Needle", "Chains / Meridian": "Chains", "Pressure Points / Meridian": "Pressure Points"}.get(row.get("source_label") or "", row.get("source_label") or "")
        matches = candidate_by_key.get((normalize(sphere_name), normalize(row["display_name"])), [])
        # Exact resolution additionally requires a source-context anchor/hash. A
        # name-only match remains quarantined.
        context = row.get("source_context") or {}
        heading_lines = {
            int(hit["line"])
            for hit in (context.get("exact_name_heading_hits") or [])
            if isinstance(hit, dict) and str(hit.get("line") or "").isdigit()
        } if isinstance(context, dict) else set()
        exact_matches = [
            target for target in matches
            if target["source_provenance"]["source_line"] in heading_lines
        ]
        if len(exact_matches) == 1:
            target = exact_matches[0]
            alias = row["candidate_record_id"]
            payload = {key: value for key, value in target.items() if key != "record_commitment_sha256"}
            payload["migration_aliases"] = sorted(set(payload["migration_aliases"] + [alias]))
            refreshed = committed(payload)
            talents[talents.index(target)] = refreshed
            candidate_by_key[(normalize(sphere_name), normalize(row["display_name"]))] = [refreshed if item is target else item for item in matches]
            migrations.append({
                "legacy_id": alias, "canonical_id": refreshed["canonical_talent_id"], "record_type": "talent",
                "migration_kind": "EXACT_QUARANTINE_IDENTITY_RESOLUTION",
                "evidence": _migration_evidence(
                    sphere=sphere_name, display_name=row["display_name"],
                    source_provenance_row=refreshed["source_provenance"], exact_text=refreshed["full_exact_source_text"],
                    record_commitment=refreshed["record_commitment_sha256"],
                ),
            })
        else:
            quarantine.append(committed({
                "candidate_record_id": row["candidate_record_id"], "display_name": row["display_name"],
                "source_label": row.get("source_label"), "status": "QUARANTINED_EXACT_DECISION_REQUIRED",
                "reason": row.get("reason"), "source_context": row.get("source_context"),
                "resolution_attempt": "Exact source identity was not uniquely established; normalized display-name equality is insufficient.",
            }))

    memberships = [committed({
        "membership_id": f"membership:{row['canonical_talent_id']}:{row['owning_canonical_sphere_id']}",
        "canonical_talent_id": row["canonical_talent_id"], "canonical_sphere_id": row["owning_canonical_sphere_id"],
        "canonical_sphere_name": row["owning_canonical_sphere_name"], "edge_kind": row["membership_kind"],
        "source_provenance": row["source_provenance"],
    }) for row in talents]

    by_sphere = Counter(row["owning_canonical_sphere_name"] for row in talents)
    ordinary_by_sphere = Counter(row["owning_canonical_sphere_name"] for row in talents if row["ordinary_talent"])
    sphere_records: list[dict[str, Any]] = []
    for index, sphere_heading in enumerate(spheres):
        name = sphere_heading.title.removeprefix("Sphere of ").strip()
        end_token = spheres[index + 1].token_index if index + 1 < len(spheres) else len(tokens)
        exact_section = "\n".join(token.text for token in tokens[sphere_heading.token_index:end_token]).rstrip()
        aliases_for_sphere: list[str] = []
        if name == "The Piercing Needle":
            aliases_for_sphere.append("Fencing")
        if name == "Harvesting Gathering":
            aliases_for_sphere.extend(["Harvesting", "Harvesting-Gathering", "Harvesting and Gathering"])
        sphere_records.append(committed({
            "canonical_sphere_id": sphere_ids[name], "display_name": name, "aliases": aliases_for_sphere,
            "talent_count": by_sphere[name], "ordinary_talent_count": ordinary_by_sphere[name],
            "automatic_base_abilities": [], "full_exact_source_text": exact_section,
            "source_section_end_line": tokens[end_token - 1].source_line if end_token else sphere_heading.line,
            "source_provenance": source_provenance(sphere_heading.line, sphere_heading.column, f"Sphere of {name}", exact_text=exact_section),
            "compiler_version": COMPILER_VERSION,
        }))

    aliases = [committed({
        "label": label, "label_classification": classification,
        "canonical_sphere_id": sphere_ids.get(target) if target else None, "canonical_sphere_name": target,
        "owner_ruling": "Fencing is a legacy/content-family alias of The Piercing Needle." if label == "Fencing" else "Noncanonical label is classified without promotion to a Sphere.",
    }) for label, (classification, target) in sorted(NONCANONICAL_LABELS.items())]

    background_routes = load_prior(source_root, "background_origin_talent_routes.v1.json")["records"]
    raw_base_abilities = [row for row in old_mixed if row["cat1_classification"] == "BASE_SPHERE_ABILITY"]
    base_alias_source = "TAL_DARK_DARKNESS"
    base_alias_target = "DARK_BASE_DARKNESS"
    base_abilities: list[dict[str, Any]] = []
    for raw in raw_base_abilities:
        payload = {key: value for key, value in raw.items() if key != "record_commitment_sha256"}
        payload["source_row_id"] = raw["candidate_record_id"]
        payload["runtime_component_id"] = base_alias_target if raw["candidate_record_id"] == base_alias_source else raw["candidate_record_id"]
        payload["runtime_alias_of"] = base_alias_target if raw["candidate_record_id"] == base_alias_source else None
        base_abilities.append(committed(payload))
    base_aliases = [committed({
        "legacy_id": base_alias_source, "canonical_component_id": base_alias_target,
        "migration_kind": "AUTOMATIC_BASE_COMPONENT_ALIAS",
        "reason": "Both exact source rows identify the same Dark — Darkness automatic base component; source provenance is preserved while runtime/UI grant once.",
        "source_row_count_preserved": 2,
    })]
    migrations.append({
        "legacy_id": base_alias_source, "canonical_id": base_alias_target,
        "record_type": "automatic_base_component", "migration_kind": "AUTOMATIC_BASE_COMPONENT_ALIAS",
        "evidence": {"source_pack": SOURCE_PACK, "source_path": COMPENDIUM_PATH, "source_file_sha256": COMPENDIUM_SHA256, "owning_sphere": "Dark", "display_name": "Darkness"},
    })

    legacy_manifest = json.loads((source_root / "catalog" / "sphere_talent_authority_v1.json").read_text(encoding="utf-8"))
    legacy_non_talent_findings = [committed({
        "record_id": row["record_id"], "display_name": row["display_name"],
        "legacy_source_sphere_name": row["sphere_name"], "source_role": row["classification"],
        "source_role_reason": row["reason"], "source_citation": list(row.get("declared_source_refs") or []),
        "source_path": legacy_manifest["catalog_path"], "source_hash": legacy_manifest["catalog_sha256"],
        "source_anchor": f"record:{row['record_id']}",
    }) for row in sorted(legacy_manifest["records"].values(), key=lambda item: item["record_id"]) if not row.get("selectable_talent")]
    by_legacy_id = {row["record_id"]: row for row in legacy_non_talent_findings}
    for row in retired_prior:
        by_legacy_id.setdefault(row["record_id"], row)
    legacy_non_talent_findings = sorted(by_legacy_id.values(), key=lambda row: row["record_id"])

    unique_base_components = {row["runtime_component_id"] for row in base_abilities}
    counts = {
        "canonical_spheres": len(sphere_records), "canonical_talents": len(talents),
        "ordinary_talents": sum(row["ordinary_talent"] for row in talents),
        "restricted_or_secret_talents": sum(row["access_category"] != "Open" for row in talents),
        "memberships": len(memberships), "background_only_routes": len(background_routes),
        "automatic_base_ability_records": len(base_abilities),
        "automatic_base_ability_unique_components": len(unique_base_components),
        "automatic_base_ability_aliases": len(base_aliases),
        "migration_aliases": len(migrations), "quarantined_records": len(quarantine),
        "legacy_non_talent_compatibility_records": len(legacy_non_talent_findings),
        "unresolved_acquisition_talents": sum(not row["creator_selectability_can_be_evaluated_safely"] for row in talents),
        "inline_heading_boundaries_tokenized": sum(heading.column > 1 for heading in headings),
    }
    body: dict[str, Any] = {
        "schema": SCHEMA, "compiler_version": COMPILER_VERSION,
        "deterministic_serialization": "UTF-8 canonical JSON; sorted keys; compact separators; LF terminator",
        "source_authority": {"archive_path": FACTORY_RELATIVE_PATH.as_posix(), "archive_sha256": FACTORY_SHA256, "compendium_path": COMPENDIUM_PATH, "compendium_sha256": COMPENDIUM_SHA256},
        "counts": counts, "spheres": sphere_records, "talents": talents, "memberships": memberships,
        "sphere_aliases_and_noncanonical_labels": aliases, "automatic_base_abilities": base_abilities,
        "automatic_base_ability_aliases": base_aliases, "background_only_routes": background_routes,
        "stable_id_migrations": sorted(migrations, key=lambda row: (row.get("record_type", ""), row["legacy_id"])),
        "quarantined_decision_packets": sorted(quarantine, key=lambda row: row["candidate_record_id"]),
        "legacy_non_talent_findings": legacy_non_talent_findings,
    }
    body["registry_commitment_sha256"] = sha256_bytes(canonical_bytes(body))
    write_json(output_root / "catalog_authority.v1.json", body)

    write_json(output_root / "matrices" / "sphere_matrix.json", [{
        "canonical_sphere_id": row["canonical_sphere_id"], "display_name": row["display_name"],
        "ordinary_talent_count": row["ordinary_talent_count"], "total_talent_count": row["talent_count"],
        "source_line": row["source_provenance"]["source_line"],
    } for row in sphere_records])
    write_json(output_root / "matrices" / "talent_prerequisite_matrix.json", [{
        "canonical_talent_id": row["canonical_talent_id"], "display_name": row["display_name"],
        "sphere": row["owning_canonical_sphere_name"], "minimum_cl": row["minimum_cl"],
        "realm_band": row["realm_band"], "raw_prerequisite_text": row["raw_prerequisite_text"],
        "prerequisite_clauses": row["prerequisite_clauses"], "typed_prerequisites": row["typed_prerequisites"],
        "prerequisite_evaluation_status": row["prerequisite_evaluation_status"],
        "creator_selectability_can_be_evaluated_safely": row["creator_selectability_can_be_evaluated_safely"],
        "access_category": row["access_category"],
    } for row in talents])
    write_json(output_root / "matrices" / "stable_id_migration_ledger.json", body["stable_id_migrations"])
    write_json(output_root / "matrices" / "quarantine_disposition_matrix.json", body["quarantined_decision_packets"])
    write_json(output_root / "matrices" / "noncanonical_label_matrix.json", aliases)
    write_json(output_root / "matrices" / "automatic_base_component_matrix.json", {
        "source_rows": base_abilities, "runtime_aliases": base_aliases,
        "source_row_count": len(base_abilities), "unique_component_count": len(unique_base_components),
    })
    prior_coverage = json.loads((source_root / "catalog" / "sphere_talent_authority_v1.json").read_text(encoding="utf-8"))["sphere_coverage"]
    write_json(output_root / "matrices" / "sphere_restoration_matrix.json", [{
        "canonical_sphere_id": row["canonical_sphere_id"], "display_name": row["display_name"],
        "prior_selectable_talent_count": len(prior_coverage.get("Fencing" if row["display_name"] == "The Piercing Needle" else row["display_name"], {}).get("selectable_talent_ids") or []),
        "compiled_ordinary_talent_count": ordinary_by_sphere[row["display_name"]],
        "restored_from_prior_zero_membership": not bool(prior_coverage.get("Fencing" if row["display_name"] == "The Piercing Needle" else row["display_name"], {}).get("selectable_talent_ids") or []),
    } for row in sphere_records])
    write_json(output_root / "matrices" / "legacy_non_talent_compatibility_matrix.json", legacy_non_talent_findings)
    write_json(output_root / "compiler_run.json", {
        "schema": "Tianxia.CAT3.CompilerRun.v1", "compiler_version": COMPILER_VERSION,
        "source_archive_sha256": FACTORY_SHA256, "compendium_sha256": COMPENDIUM_SHA256,
        "counts": counts, "registry_commitment_sha256": body["registry_commitment_sha256"],
    })
    return body


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    result = build(Path(args.source_root).resolve(), Path(args.output_root).resolve())
    print(json.dumps({"result": "PASS", "counts": result["counts"], "registry_commitment_sha256": result["registry_commitment_sha256"], "output_root": str(Path(args.output_root).resolve())}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
