#!/usr/bin/env python3
"""Compile an HF05ZVK-R1F Character_Master_Ledger into HF05ZUI-R2K surfaces."""
from __future__ import annotations
import argparse, hashlib, importlib.util, io, json, re, shutil, sys, zipfile
from pathlib import Path
from typing import Any

SCHEMA = "HF05ZVK-R1F"
PRODUCER_RELEASE = "HF05ZVK-R1H"
COMPILER_VERSION = "HF05ZVK-R1H.Compiler.Phase2I.v2-rulebook"
# v2 follows docs/rules/TIANXIA_RULES_AS_WRITTEN.md: Q01 CL1 free-Sphere talent,
# no Sphere-count cap (RAW-078), RAW-015 CP minimum, CL20 Immortal Realm (Q15),
# and no output-quality floors (those belong to the generating controller).
TARGET = "HF05ZUI-R2K"
TARGET_PATCH = "HF05ZUI-R2K.3"
ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
ACTION_FIELDS = ("timing", "cost", "range", "target", "roll_save_check", "effect", "failure", "duration", "limit", "counterplay")
BUCKETS = {"action", "bonus_action", "reaction", "passive", "procedure"}
BUILD_MODES = {"production", "acceptance_fixture"}
ALLOCATION_CHANNELS = {
    "background", "background_sphere", "background_talent", "origin", "level_1_sphere",
    "free_level", "new_sphere", "new_sphere_bonus", "trained_choice", "method", "foundation",
    "manual", "training_source", "forged", "immortal_art", "equipment", "feature", "emergency_seed", "item", "event"
}
GRANT_TYPES = {
    "background", "origin_insight", "sphere", "talent", "method", "foundation",
    "recorded_art", "training_source", "forged_technique", "immortal_art", "equipment", "item", "feature", "emergency_seed", "event"
}
TRAINED_CHANNELS = {"new_sphere", "trained_choice", "manual"}
ZERO_COST_CHANNELS = ALLOCATION_CHANNELS - TRAINED_CHANNELS
SPHERE_DIVERSITY_DEFAULT = {1:2,2:3,3:4,4:4,5:5,6:5,7:6,8:6,9:7,10:8,11:8,12:9,13:9,14:10,15:11,16:11,17:12,18:12,19:13,20:14}
SPHERE_DIVERSITY_EXCEPTIONAL = {cl: value + 2 for cl, value in SPHERE_DIVERSITY_DEFAULT.items()}
PRODUCTION_CANONICAL_NAME_TYPES = {"background", "origin_insight", "sphere", "talent", "method", "foundation", "recorded_art", "immortal_art", "feature"}
CANONICAL_SELECTION_AUTHORITIES = {"tianxia_rules", "user_directive"}
POINT_BUY_COST = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
REALM_RANK = {"Mortal": 1, "Foundation": 2, "Core Formation": 3, "Nascent Soul": 4, "Immortal": 5}
BASE_FORMS = {
    "Strike": (1, 1), "Projection": (1, 1), "Movement": (1, 1),
    "Burst": (2, 2), "Cone": (2, 2), "Line": (2, 2), "Ward": (2, 2),
    "Aura": (3, 3), "Zone": (3, 3), "Counter": (3, 3), "Ritual": (None, 1),
}
ADVANCED_AUGMENTS = {
    "Major Condition": ("Foundation", 2, 2), "Persistent Zone": ("Foundation", 2, 2),
    "Ignore Resistance": ("Core Formation", 2, 2), "Reaction Activation": ("Core Formation", 2, 2),
    "Bonus-Action Activation": ("Core Formation", 2, 3), "Severe Hindrance": ("Core Formation", 2, 2),
    "Domain Effect": ("Nascent Soul", 3, 3), "Conceptual Effect": ("Nascent Soul", 3, 4),
}
CANONICAL_DRAWBACK_REDUCTIONS = {
    "Concentration": 1, "Preparation": 1, "Long Invocation": 1, "Self-Damage": 1,
    "Restricted Environment": 1, "Material Focus": 1, "Once per Short Rest": 1,
    "Once per Long Rest": 2, "Exhausting": 2, "Backlash": 1,
}
PATH_RULES = {
    "Body Refining": {"resource": "Stamina", "hit_die": "d12", "die_size": 12, "fixed_average": 7},
    "Qi Cultivation": {"resource": "Qi", "hit_die": "d8", "die_size": 8, "fixed_average": 5},
    "Spirit Awakening": {"resource": "Resonance", "hit_die": "d8", "die_size": 8, "fixed_average": 5},
}
BANNED = re.compile(r"\b(tbd|todo|unknown|not recorded|not itemized|placeholder|unnamed|as appropriate|resolve as appropriate|generic effect)\b", re.I)

class BuildError(ValueError): pass

def load(path: Path) -> dict[str, Any]:
    try: data=json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e: raise BuildError(f"MISSING_FILE:{path}") from e
    except json.JSONDecodeError as e: raise BuildError(f"INVALID_JSON:{path}:{e.msg}") from e
    if not isinstance(data, dict): raise BuildError(f"ROOT_OBJECT_REQUIRED:{path}")
    return data

def dump(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

def htext(text: str) -> str: return hashlib.sha256(text.encode("utf-8")).hexdigest()


ABILITY_ALIASES={"strength":"STR","str":"STR","dexterity":"DEX","dex":"DEX","constitution":"CON","con":"CON","intelligence":"INT","int":"INT","wisdom":"WIS","wis":"WIS","charisma":"CHA","cha":"CHA"}
def parse_ability_adjustments(value):
    out={a:0 for a in ABILITIES}
    if isinstance(value,dict):
        for k,v in value.items():
            ab=ABILITY_ALIASES.get(str(k).strip().lower())
            if ab and isinstance(v,int): out[ab]+=v
        return out
    for amount,ability in re.findall(r"([+-]\s*\d+)\s*(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma|STR|DEX|CON|INT|WIS|CHA)\b",str(value or ""),re.I):
        out[ABILITY_ALIASES[ability.lower()]]+=int(amount.replace(" ",""))
    return out

def ability_timeline(ledger):
    stats=obj(ledger.get("core_stats"),"core_stats"); ag=obj(stats.get("ability_generation"),"core_stats.ability_generation")
    base=obj(ag.get("base_scores"),"ability_generation.base_scores"); bg=obj(ag.get("background_adjustments",{}),"ability_generation.background_adjustments"); species=obj(ag.get("species_adjustments",{}),"ability_generation.species_adjustments"); other=obj(ag.get("other_adjustments",{}),"ability_generation.other_adjustments")
    current={ab:int(base.get(ab,0))+int(bg.get(ab,0) or 0)+int(species.get(ab,0) or 0) for ab in ABILITIES}
    totals={ab:0 for ab in ABILITIES}; by_level={}
    for row in arr(obj(ledger.get("advancement"),"advancement").get("levels"),"advancement.levels"):
        rcl=row.get("cl"); delta={ab:0 for ab in ABILITIES}
        for a in arr(row.get("allocations"),f"level.{rcl}.allocations"):
            structured=a.get("ability_score_adjustments")
            parsed=parse_ability_adjustments(structured if isinstance(structured,dict) else a.get("name"))
            if any(parsed.values()) and a.get("channel")!="event": raise BuildError(f"ABILITY_ADJUSTMENT_MUST_USE_EVENT_CHANNEL:CL{rcl}:{a.get('allocation_id')}")
            for ab,val in parsed.items(): delta[ab]+=val; totals[ab]+=val
        for ab,val in delta.items(): current[ab]+=val
        by_level[rcl]={"scores":dict(current),"mods":{ab:(current[ab]-10)//2 for ab in ABILITIES},"deltas":delta}
    declared={ab:int(other.get(ab,0) or 0) for ab in ABILITIES}
    if totals!=declared: raise BuildError(f"ABILITY_TIMELINE_EVENT_TOTAL_MISMATCH:{totals}!={declared}")
    if by_level and by_level[max(by_level)]["scores"]!=stats.get("ability_scores"): raise BuildError(f"ABILITY_TIMELINE_FINAL_MISMATCH:{by_level[max(by_level)]['scores']}!={stats.get('ability_scores')}")
    return by_level
def hfile(path: Path) -> str:
    d=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(131072), b""): d.update(b)
    return d.hexdigest()

def req(v: Any, label: str):
    if v is None or v=="" or v==[] or v=={}: raise BuildError(f"MISSING_REQUIRED:{label}")
    if isinstance(v,str) and BANNED.search(v): raise BuildError(f"BANNED_PLACEHOLDER:{label}:{v}")
    return v

def text(v: Any, label: str) -> str:
    req(v,label)
    if not isinstance(v,str): raise BuildError(f"TEXT_REQUIRED:{label}")
    return v.strip()

def arr(v: Any, label: str) -> list[Any]:
    if v is None: return []
    if not isinstance(v,list): raise BuildError(f"LIST_REQUIRED:{label}")
    return v

def obj(v: Any, label: str) -> dict[str,Any]:
    if not isinstance(v,dict): raise BuildError(f"OBJECT_REQUIRED:{label}")
    return v

def none_state(v: Any) -> bool:
    return isinstance(v,dict) and v.get("status") in {"none_acquired","not_applicable","not_selected_for_this_build","unavailable_until_later_cl"} and isinstance(v.get("reason"),str) and bool(v["reason"].strip())

def assert_clean(v: Any, label="root"):
    if isinstance(v,str):
        if BANNED.search(v): raise BuildError(f"BANNED_PLACEHOLDER:{label}:{v}")
    elif isinstance(v,list):
        for i,x in enumerate(v): assert_clean(x,f"{label}[{i}]")
    elif isinstance(v,dict):
        for k,x in v.items(): assert_clean(x,f"{label}.{k}")

def item_integration_module():
    path=Path(__file__).resolve().parents[1]/"06_VALIDATORS"/"validate_item_integration_p2e.py"
    spec=importlib.util.spec_from_file_location("hf05zvk_item_integration",path)
    if not spec or not spec.loader: raise BuildError("ITEM_INTEGRATION_VALIDATOR_LOAD_FAILED")
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def universal_coverage_module():
    path=Path(__file__).resolve().parents[1]/"06_VALIDATORS"/"validate_selected_rule_execution_coverage.py"
    spec=importlib.util.spec_from_file_location("hf05zvk_universal_coverage",path)
    if not spec or not spec.loader: raise BuildError("UNIVERSAL_COVERAGE_VALIDATOR_LOAD_FAILED")
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

def realm_for_cl(cl:int)->str:
    if 1<=cl<=4: return "Mortal"
    if 5<=cl<=9: return "Foundation"
    if 10<=cl<=14: return "Core Formation"
    if 15<=cl<=19: return "Nascent Soul"
    if cl==20: return "Immortal"  # Q15: CL20 is the Immortal Realm
    raise BuildError(f"CL_OUT_OF_RANGE:{cl}")

def pb_for_cl(cl:int)->int:
    return 2 if cl<=4 else 3 if cl<=8 else 4 if cl<=12 else 5 if cl<=16 else 6

def complexity_limit(cl:int)->int:
    return 2 if cl<=4 else 4 if cl<=9 else 6 if cl<=14 else 8 if cl<=19 else 10

def all_zip_text(corpus: Path)->dict[str,str]:
    if not corpus.is_file(): raise BuildError(f"RULES_CORPUS_MISSING:{corpus}")
    out={}
    def walk(z:zipfile.ZipFile,prefix="",depth=0):
        for info in z.infolist():
            if info.is_dir(): continue
            data=z.read(info.filename); name=(prefix+info.filename).replace("\\","/")
            if info.filename.lower().endswith((".md",".txt")):
                try: out[name]=data.decode("utf-8")
                except UnicodeDecodeError: pass
            elif depth<2 and info.filename.lower().endswith(".zip"):
                try:
                    with zipfile.ZipFile(io.BytesIO(data)) as nz: walk(nz,name+"::",depth+1)
                except zipfile.BadZipFile: pass
    try:
        with zipfile.ZipFile(corpus) as z: walk(z)
    except zipfile.BadZipFile as e: raise BuildError(f"RULES_CORPUS_INVALID:{corpus}") from e
    return out

def corpus_authority_manifest(corpus:Path)->dict[str,Any]:
    try:
        with zipfile.ZipFile(corpus) as z:
            raw=z.read("_CANON_AUTHORITY_MANIFEST.json")
        manifest=json.loads(raw.decode("utf-8"))
    except KeyError as e: raise BuildError("RULES_CORPUS_AUTHORITY_MANIFEST_MISSING") from e
    except Exception as e: raise BuildError(f"RULES_CORPUS_AUTHORITY_MANIFEST_INVALID:{e}") from e
    if manifest.get("schema_version")!="HF05ZVK-R1F.CanonAuthorityManifest.P2A.v1":
        raise BuildError(f"RULES_CORPUS_AUTHORITY_SCHEMA_INVALID:{manifest.get('schema_version')}")
    active=manifest.get("active_packet_sources")
    if not isinstance(active,list) or not active: raise BuildError("RULES_CORPUS_ACTIVE_SOURCES_EMPTY")
    return manifest

def corpus_text_for_paths(corpus:Path, paths:set[str])->dict[str,str]:
    out:dict[str,str]={}
    try:
        with zipfile.ZipFile(corpus) as root_zip:
            for path in sorted(paths):
                parts=path.split("::")
                try:
                    data=root_zip.read(parts[0])
                    for nested_name in parts[1:]:
                        with zipfile.ZipFile(io.BytesIO(data)) as nested_zip:
                            data=nested_zip.read(nested_name)
                    out[path]=data.decode("utf-8")
                except (KeyError, zipfile.BadZipFile, UnicodeDecodeError):
                    continue
    except zipfile.BadZipFile as e:
        raise BuildError(f"RULES_CORPUS_INVALID:{corpus}") from e
    return out

def verify_packets(registry:dict[str,Any], corpus:Path)->dict[str,dict[str,Any]]:
    packets=arr(registry.get("packets"),"rules_packets.packets")
    if not packets: raise BuildError("RULES_PACKET_REGISTRY_EMPTY")
    authority_manifest=corpus_authority_manifest(corpus); active=set(authority_manifest["active_packet_sources"]); index={}
    requested={str(p.get("source_path","")).replace("\\","/") for p in packets if isinstance(p,dict) and p.get("authority")=="tianxia_rules"}
    source=corpus_text_for_paths(corpus,requested)
    for p in packets:
        p=obj(p,"rules_packet")
        pid=text(p.get("packet_id"),"rules_packet.packet_id")
        if pid in index: raise BuildError(f"DUPLICATE_RULES_PACKET:{pid}")
        authority=text(p.get("authority"),f"packet.{pid}.authority")
        text(p.get("name"),f"packet.{pid}.name")
        excerpt=text(p.get("source_text"),f"packet.{pid}.source_text")
        if p.get("source_text_sha256")!=htext(excerpt): raise BuildError(f"RULES_PACKET_HASH_MISMATCH:{pid}")
        if authority=="tianxia_rules":
            path=text(p.get("source_path"),f"packet.{pid}.source_path").replace("\\","/")
            if path not in active: raise BuildError(f"RULES_PACKET_SOURCE_NOT_ACTIVE:{pid}:{path}")
            matches=[source[path]] if path in source else []
            if not matches: raise BuildError(f"RULES_PACKET_SOURCE_NOT_FOUND:{pid}:{path}")
            if not any(excerpt in body for body in matches): raise BuildError(f"RULES_PACKET_EXCERPT_NOT_FOUND:{pid}")
        elif authority not in {"original_design","inspiration_source","user_directive"}:
            raise BuildError(f"RULES_PACKET_AUTHORITY_INVALID:{pid}:{authority}")
        index[pid]=p
    return index

def ensure_packet_refs(rows:list[dict[str,Any]], packets:dict[str,dict[str,Any]], label:str, optional=False):
    for i,row in enumerate(rows):
        refs=row.get("source_packet_ids") or ([row.get("source_packet_id")] if row.get("source_packet_id") else [])
        if not refs and not optional: raise BuildError(f"SOURCE_PACKET_REF_REQUIRED:{label}[{i}]")
        for r in refs:
            if r not in packets: raise BuildError(f"UNKNOWN_SOURCE_PACKET:{label}[{i}]:{r}")


def packet_refs(row:dict[str,Any]) -> list[str]:
    refs=row.get("source_packet_ids") or ([row.get("source_packet_id")] if row.get("source_packet_id") else [])
    return [str(x) for x in refs if str(x).strip()]


def require_canonical_authority(row:dict[str,Any], packets:dict[str,dict[str,Any]], label:str, build_mode:str):
    if build_mode == "acceptance_fixture":
        return
    refs=packet_refs(row)
    authorities={packets[r].get("authority") for r in refs if r in packets}
    if not (authorities & CANONICAL_SELECTION_AUTHORITIES):
        raise BuildError(f"CANONICAL_RULE_AUTHORITY_REQUIRED:{label}:{sorted(authorities)}")
    if "inspiration_source" in authorities and not (authorities & CANONICAL_SELECTION_AUTHORITIES):
        raise BuildError(f"INSPIRATION_CANNOT_AUTHORIZE_MECHANICS:{label}")



def normalized_name(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def packet_text_haystack(packet: dict[str, Any]) -> str:
    return " ".join(str(packet.get(k, "")) for k in ("name", "source_section", "source_text", "mechanical_interpretation", "notes"))


def require_named_canonical_selection(row: dict[str, Any], packets: dict[str, dict[str, Any]], label: str, build_mode: str):
    """Prevent a broad rules excerpt from being used to authorize an invented catalog selection."""
    if build_mode == "acceptance_fixture":
        return
    refs = packet_refs(row)
    canonical = [packets[r] for r in refs if r in packets and packets[r].get("authority") == "tianxia_rules"]
    if not canonical:
        # Explicit user directives may authorize custom content. The generated
        # item remains visibly custom rather than masquerading as catalog canon.
        if any(packets[r].get("authority") == "user_directive" for r in refs if r in packets):
            if row.get("custom_design") is not True:
                raise BuildError(f"USER_DIRECTIVE_CUSTOM_DESIGN_FLAG_REQUIRED:{label}")
            return
        raise BuildError(f"CANONICAL_RULE_AUTHORITY_REQUIRED:{label}")
    target = normalized_name(row.get("name") or row.get("technique_name"))
    if not target:
        raise BuildError(f"CANONICAL_SELECTION_NAME_REQUIRED:{label}")
    if not any(target in normalized_name(packet_text_haystack(packet)) for packet in canonical):
        raise BuildError(f"CANONICAL_SELECTION_NAME_NOT_IN_SOURCE_PACKET:{label}:{row.get('name') or row.get('technique_name')}")


def validate_training_record(record: Any, *, label: str, kind: str, current_pb: int, ability_modifiers: dict[str, int], expected_dc: int):
    record = obj(record, label)
    if record.get("kind") != kind:
        raise BuildError(f"TRAINING_KIND_MISMATCH:{label}:{record.get('kind')}!={kind}")
    ability = text(record.get("ability"), f"{label}.ability")
    if ability not in {"INT", "WIS"}:
        raise BuildError(f"TRAINING_ABILITY_INVALID:{label}:{ability}")
    if record.get("ability_modifier") != ability_modifiers[ability]:
        raise BuildError(f"TRAINING_ABILITY_MODIFIER_MISMATCH:{label}")
    if record.get("proficiency_bonus") != current_pb:
        raise BuildError(f"TRAINING_PB_MISMATCH:{label}")
    d6 = record.get("time_d6_roll")
    if not isinstance(d6, int) or not 1 <= d6 <= 6:
        raise BuildError(f"TRAINING_TIME_D6_INVALID:{label}:{d6}")
    expected_days = max(2, d6 + current_pb - ability_modifiers[ability])
    if record.get("training_days") != expected_days:
        raise BuildError(f"TRAINING_TIME_MISMATCH:{label}:{record.get('training_days')}!={expected_days}")
    if record.get("dc_total") != expected_dc:
        raise BuildError(f"TRAINING_DC_MISMATCH:{label}:{record.get('dc_total')}!={expected_dc}")
    if not isinstance(record.get("check_total"), int) or record["check_total"] < expected_dc:
        raise BuildError(f"TRAINING_CHECK_NOT_SUCCESSFUL:{label}:{record.get('check_total')}<{expected_dc}")
    if record.get("result") != "learned":
        raise BuildError(f"TRAINING_RESULT_INVALID:{label}:{record.get('result')}")
    text(record.get("source_description"), f"{label}.source_description")

def checkpoint_hash(levels:list[dict[str,Any]], upto:int) -> str:
    # Seal the complete allocation record, including training history and CL1
    # overlap metadata. Earlier versions hashed only display fields, allowing a
    # training roll or adjudication detail to drift without changing the state
    # checkpoint.
    cumulative=[]
    for row in levels[:upto]:
        for a in row.get("allocations",[]):
            sealed=json.loads(json.dumps(a, ensure_ascii=False, sort_keys=True))
            if isinstance(sealed.get("source_packet_ids"), list):
                sealed["source_packet_ids"]=sorted(str(x) for x in sealed["source_packet_ids"])
            cumulative.append(sealed)
    row=levels[upto-1]
    payload={
        "cl":row.get("cl"), "realm":row.get("realm"), "pb":row.get("pb"),
        "hp_max":row.get("hp",{}).get("max_after_level"),
        "resource_name":row.get("resource",{}).get("name"),
        "resource_max":row.get("resource",{}).get("max_after_level"),
        "cumulative_allocations":cumulative
    }
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()


def validate_point_buy(stats:dict[str,Any], scores:dict[str,Any], background:dict[str,Any]|None=None, packets:dict[str,dict[str,Any]]|None=None, build_mode:str="production"):
    generation=obj(stats.get("ability_generation"),"core_stats.ability_generation")
    method=text(generation.get("method"),"core_stats.ability_generation.method")
    if method == "user_directive":
        refs=arr(generation.get("directive_source_packet_ids"),"core_stats.ability_generation.directive_source_packet_ids")
        if not refs: raise BuildError("ABILITY_USER_DIRECTIVE_PACKET_REQUIRED")
        if packets is None: raise BuildError("ABILITY_USER_DIRECTIVE_PACKET_REGISTRY_REQUIRED")
        for ref in refs:
            if ref not in packets: raise BuildError(f"ABILITY_USER_DIRECTIVE_PACKET_UNKNOWN:{ref}")
        if not any(packets[ref].get("authority")=="user_directive" for ref in refs): raise BuildError("ABILITY_USER_DIRECTIVE_AUTHORITY_REQUIRED")
        for ab in ABILITIES:
            if not isinstance(scores.get(ab),int): raise BuildError(f"ABILITY_SCORE_INTEGER_REQUIRED:{ab}")
        return
    if method != "27_point_buy":
        raise BuildError(f"ABILITY_GENERATION_METHOD_INVALID:{method}:USE_27_POINT_BUY_OR_EXPLICIT_USER_DIRECTIVE")
    base=obj(generation.get("base_scores"),"core_stats.ability_generation.base_scores")
    bg=obj(generation.get("background_adjustments",{}),"core_stats.ability_generation.background_adjustments")
    species=obj(generation.get("species_adjustments",{}),"core_stats.ability_generation.species_adjustments")
    other=obj(generation.get("other_adjustments",{}),"core_stats.ability_generation.other_adjustments")
    for m,label in ((base,"base_scores"),(bg,"background_adjustments"),(species,"species_adjustments"),(other,"other_adjustments")):
        for k,v in m.items():
            if k not in ABILITIES or not isinstance(v,int): raise BuildError(f"ABILITY_GENERATION_MAP_INVALID:{label}:{k}")
    if set(base)!=set(ABILITIES): raise BuildError("POINT_BUY_BASE_SCORES_INCOMPLETE")
    if any(v not in POINT_BUY_COST for v in base.values()): raise BuildError("POINT_BUY_SCORE_OUT_OF_RANGE")
    spent=sum(POINT_BUY_COST[v] for v in base.values())
    if spent!=27 or generation.get("points_spent")!=27: raise BuildError(f"POINT_BUY_TOTAL_MISMATCH:{spent}")
    computed={ab:base[ab]+bg.get(ab,0)+species.get(ab,0)+other.get(ab,0) for ab in ABILITIES}
    if computed!=scores: raise BuildError(f"FINAL_ABILITY_SCORE_RECONCILIATION_FAILED:{computed}!={scores}")
    bg_values=[v for v in bg.values() if v]
    if bg_values != [2]: raise BuildError(f"BACKGROUND_ABILITY_INCREASE_INVALID:{bg}:EXPECTED_ONE_PLUS_2")
    if background:
        allowed=set(background.get("ability_score_options",[]))
        if allowed and any(k not in allowed for k,v in bg.items() if v): raise BuildError(f"BACKGROUND_ABILITY_OPTION_ILLEGAL:{bg}:{sorted(allowed)}")

def validate_action(a:dict[str,Any], i:int, ids:set[str]):
    aid=text(a.get("action_id"),f"actions[{i}].action_id")
    if aid in ids: raise BuildError(f"DUPLICATE_ACTION_ID:{aid}")
    ids.add(aid); text(a.get("name"),f"actions[{i}].name")
    b=text(a.get("bucket"),f"actions[{i}].bucket")
    if b not in BUCKETS: raise BuildError(f"ACTION_BUCKET_INVALID:{aid}:{b}")
    if a.get("action_type")!=b: raise BuildError(f"ACTION_TYPE_ALIAS_MISMATCH:{aid}")
    for f in ACTION_FIELDS: text(a.get(f),f"action.{aid}.{f}")
    # Typed-card semantic lint. These phrases are valid mechanics in the
    # correct field, but are strong evidence of column displacement elsewhere.
    failure_norm=str(a.get("failure","")).strip().lower().rstrip(".")
    duration_norm=str(a.get("duration","")).strip().lower()
    limit_norm=str(a.get("limit","")).strip().lower()
    counterplay_norm=str(a.get("counterplay","")).strip().lower()
    if failure_norm in {"instantaneous","until the start of your next turn","until the end of your next turn"}:
        raise BuildError(f"ACTION_FIELD_DISPLACEMENT_FAILURE_LOOKS_DURATION:{aid}")
    if duration_norm.startswith(("once per round","once per turn","a number of times per")) or "not save proficiency" in duration_norm:
        raise BuildError(f"ACTION_FIELD_DISPLACEMENT_DURATION_LOOKS_LIMIT:{aid}")
    if counterplay_norm.startswith("no counterplay beyond") and any(x in limit_norm for x in ("force multiple","drain stamina","use a non-","avoid the area","break concentration")):
        raise BuildError(f"ACTION_FIELD_DISPLACEMENT_LIMIT_COUNTERPLAY_SWAPPED:{aid}")
    for field in ("source_spheres","source_talents","source_packet_ids","creates_states","consumes_states"):
        if field in a: arr(a[field],f"action.{aid}.{field}")
    for field in ("resource_costs","resource_gains","resource_requirements"):
        arr(a.get(field),f"action.{aid}.{field}")

def validate_exec(e:dict[str,Any], label:str):
    e=obj(e,label)
    for f in ACTION_FIELDS: text(e.get(f),f"{label}.{f}")

def validate_ledger(ledger:dict[str,Any], packets:dict[str,dict[str,Any]], *,
                    path_authority:Path|None=None)->dict[str,Any]:
    if ledger.get("schema_version")!=SCHEMA: raise BuildError(f"WRONG_SCHEMA:{ledger.get('schema_version')}")
    if ledger.get("status")!="COMMAND_4_EXECUTABLE_CHARACTER_COMPLETE": raise BuildError("MASTER_LEDGER_NOT_COMMAND_4_SEALED")
    build_mode=ledger.get("build_mode","production")
    if build_mode not in BUILD_MODES: raise BuildError(f"BUILD_MODE_INVALID:{build_mode}")
    char=obj(ledger.get("character"),"character")
    for f in ("character_id","name","title","concept","path","key_ability"): text(char.get(f),f"character.{f}")
    ensure_packet_refs([{"source_packet_ids":char.get("path_source_packet_ids",[])}],packets,"character.path")
    path_rule_row={"name":char.get("path"),"source_packet_ids":char.get("path_source_packet_ids",[])}
    require_canonical_authority(path_rule_row,packets,"character.path",build_mode)
    require_named_canonical_selection(path_rule_row,packets,"character.path",build_mode)
    cl=char.get("cl"); pb=char.get("pb")
    if not isinstance(cl,int): raise BuildError("CHARACTER_CL_INTEGER_REQUIRED")
    if char.get("realm")!=realm_for_cl(cl): raise BuildError(f"REALM_CL_MISMATCH:{char.get('realm')}:{cl}")
    if pb!=pb_for_cl(cl): raise BuildError(f"PB_CL_MISMATCH:{pb}:{cl}")
    path_rule=PATH_RULES.get(char.get("path"))
    if not path_rule: raise BuildError(f"PATH_INVALID:{char.get('path')}")
    index_root = path_authority or Path(__file__).resolve().parents[2] / "non_sphere_authority" / "authority"
    index_file = char["path"].lower().replace(" ", "_") + ".path_index.p2a.json"
    profile = load(index_root / index_file)["path_profile"]
    options = profile["key_ability"]["options"]
    if char.get("key_ability") not in {*options, *(name[:3].upper() for name in options)}:
        raise BuildError(f"PATH_KEY_ABILITY_ILLEGAL:{char.get('path')}:{char.get('key_ability')}")
    expected_path_features=arr(char.get("path_feature_ids_expected"),"character.path_feature_ids_expected")
    if not expected_path_features: raise BuildError("PATH_FEATURE_EXPECTATION_EMPTY")
    if len(expected_path_features)!=len(set(expected_path_features)): raise BuildError("PATH_FEATURE_EXPECTATION_DUPLICATE")
    stats=obj(ledger.get("core_stats"),"core_stats")
    scores=obj(stats.get("ability_scores"),"core_stats.ability_scores")
    mods=obj(stats.get("ability_modifiers"),"core_stats.ability_modifiers")
    saves=obj(stats.get("saving_throws"),"core_stats.saving_throws")
    for ab in ABILITIES:
        if not isinstance(scores.get(ab),int): raise BuildError(f"ABILITY_SCORE_INTEGER_REQUIRED:{ab}")
        expected=(scores[ab]-10)//2
        if mods.get(ab)!=expected: raise BuildError(f"ABILITY_MODIFIER_MISMATCH:{ab}")
        if not isinstance(saves.get(ab),int): raise BuildError(f"SAVE_INTEGER_REQUIRED:{ab}")
    for f in ("ac_active","hp_current","hp_max","technique_attack_bonus","save_dc","speed_ft","primary_resource_current","primary_resource_max"):
        if not isinstance(stats.get(f),int): raise BuildError(f"CORE_STAT_INTEGER_REQUIRED:{f}")
    if stats["hp_current"]<0 or stats["hp_max"]<1: raise BuildError("HP_VALUES_OUT_OF_RANGE")
    if stats["hp_current"]>stats["hp_max"]: raise BuildError("HP_CURRENT_EXCEEDS_MAX")
    if stats["primary_resource_current"]<0 or stats["primary_resource_max"]<0: raise BuildError("PRIMARY_RESOURCE_VALUES_OUT_OF_RANGE")
    if stats["primary_resource_current"]>stats["primary_resource_max"]: raise BuildError("PRIMARY_RESOURCE_CURRENT_EXCEEDS_MAX")
    if stats["speed_ft"]<=0: raise BuildError("SPEED_MUST_BE_POSITIVE")
    text(stats.get("primary_resource_name"),"core_stats.primary_resource_name")
    skills=obj(stats.get("skills",{}),"core_stats.skills")
    if any(not isinstance(v,int) for v in skills.values()): raise BuildError("SKILL_VALUES_MUST_BE_INTEGERS")
    proficient_skills=arr(stats.get("proficient_skills",[]),"core_stats.proficient_skills")
    if len(proficient_skills)!=len(set(proficient_skills)): raise BuildError("PROFICIENT_SKILLS_DUPLICATE")
    skill_ability_map=obj(stats.get("skill_ability_map"),"core_stats.skill_ability_map")
    skill_multipliers=obj(stats.get("skill_proficiency_multipliers"),"core_stats.skill_proficiency_multipliers")
    skill_adjustments=obj(stats.get("skill_adjustments"),"core_stats.skill_adjustments")
    if set(skills)!=(set(skill_ability_map)) or set(skills)!=(set(skill_multipliers)) or set(skills)!=(set(skill_adjustments)):
        raise BuildError("SKILL_CALCULATION_KEY_MISMATCH")
    if set(proficient_skills)!={name for name,m in skill_multipliers.items() if m>0}: raise BuildError("PROFICIENT_SKILL_LIST_MISMATCH")
    for name,value in skills.items():
        ability=skill_ability_map[name]
        if ability not in ABILITIES: raise BuildError(f"SKILL_ABILITY_INVALID:{name}:{ability}")
        multiplier=skill_multipliers[name]; adjustment=skill_adjustments[name]
        if multiplier not in {0,1,2}: raise BuildError(f"SKILL_PROFICIENCY_MULTIPLIER_INVALID:{name}:{multiplier}")
        if not isinstance(adjustment,int): raise BuildError(f"SKILL_ADJUSTMENT_INTEGER_REQUIRED:{name}")
        expected_skill=mods[ability]+pb*multiplier+adjustment
        if value!=expected_skill: raise BuildError(f"SKILL_RECONCILIATION_FAILED:{name}:{value}!={expected_skill}")
    skill_sources=obj(stats.get("skill_sources",{}),"core_stats.skill_sources")
    skill_packet_sources=obj(stats.get("skill_source_packet_ids",{}),"core_stats.skill_source_packet_ids")
    if set(skill_sources)!=set(skills): raise BuildError("SKILL_DISPLAY_SOURCE_KEY_MISMATCH")
    for name in skills:
        text(skill_sources.get(name),f"core_stats.skill_sources.{name}")
        if skill_multipliers[name]>0 or skill_adjustments[name]!=0:
            refs=skill_packet_sources.get(name,[])
            if not isinstance(refs,list) or not refs: raise BuildError(f"SKILL_SOURCE_PACKET_REQUIRED:{name}")
            for ref in refs:
                if ref not in packets: raise BuildError(f"SKILL_SOURCE_PACKET_UNKNOWN:{name}:{ref}")
    ac_generation=obj(stats.get("ac_generation"),"core_stats.ac_generation")
    ac_components=("base_ac","dexterity_modifier_applied","shield_adjustment","foundation_adjustment","method_adjustment","item_adjustment","other_adjustment")
    for field in ac_components:
        if not isinstance(ac_generation.get(field),int): raise BuildError(f"AC_COMPONENT_INTEGER_REQUIRED:{field}")
    ac_total=sum(ac_generation[field] for field in ac_components)
    if ac_generation.get("total")!=ac_total or stats["ac_active"]!=ac_total: raise BuildError(f"AC_RECONCILIATION_FAILED:{stats['ac_active']}!={ac_total}")
    arr(ac_generation.get("source_grant_ids",[]),"core_stats.ac_generation.source_grant_ids")
    speed_generation=obj(stats.get("speed_generation"),"core_stats.speed_generation")
    speed_components=("base_speed","path_adjustment","sphere_adjustment","foundation_adjustment","method_adjustment","equipment_adjustment","other_adjustment")
    for field in speed_components:
        if not isinstance(speed_generation.get(field),int): raise BuildError(f"SPEED_COMPONENT_INTEGER_REQUIRED:{field}")
    speed_total=sum(speed_generation[field] for field in speed_components)
    if speed_generation.get("total")!=speed_total or stats["speed_ft"]!=speed_total: raise BuildError(f"SPEED_RECONCILIATION_FAILED:{stats['speed_ft']}!={speed_total}")
    arr(speed_generation.get("source_grant_ids",[]),"core_stats.speed_generation.source_grant_ids")
    initiative_generation=obj(stats.get("initiative_generation"),"core_stats.initiative_generation")
    init_ability=text(initiative_generation.get("ability"),"core_stats.initiative_generation.ability")
    if init_ability not in ABILITIES: raise BuildError(f"INITIATIVE_ABILITY_INVALID:{init_ability}")
    init_mult=initiative_generation.get("proficiency_multiplier"); init_adjust=initiative_generation.get("adjustment")
    if init_mult not in {0,1,2}: raise BuildError(f"INITIATIVE_PROFICIENCY_MULTIPLIER_INVALID:{init_mult}")
    if not isinstance(init_adjust,int): raise BuildError("INITIATIVE_ADJUSTMENT_INTEGER_REQUIRED")
    init_total=mods[init_ability]+pb*init_mult+init_adjust
    if initiative_generation.get("total")!=init_total or stats.get("initiative_bonus")!=init_total: raise BuildError(f"INITIATIVE_RECONCILIATION_FAILED:{stats.get('initiative_bonus')}!={init_total}")
    arr(initiative_generation.get("source_grant_ids",[]),"core_stats.initiative_generation.source_grant_ids")
    save_adjust=obj(stats.get("saving_throw_adjustments",{}),"core_stats.saving_throw_adjustments")
    save_adjust_sources=obj(stats.get("saving_throw_adjustment_source_packet_ids",{}),"core_stats.saving_throw_adjustment_source_packet_ids")
    for ab in ABILITIES:
        if not isinstance(save_adjust.get(ab,0),int): raise BuildError(f"SAVE_ADJUSTMENT_INTEGER_REQUIRED:{ab}")
        if saves[ab] != mods[ab] + save_adjust.get(ab,0): raise BuildError(f"SAVE_RECONCILIATION_FAILED:{ab}:{saves[ab]}!={mods[ab]}+{save_adjust.get(ab,0)}")
        if save_adjust.get(ab,0) != 0:
            refs=save_adjust_sources.get(ab,[])
            if not isinstance(refs,list) or not refs: raise BuildError(f"SAVE_ADJUSTMENT_SOURCE_REQUIRED:{ab}")
            for ref in refs:
                if ref not in packets: raise BuildError(f"SAVE_ADJUSTMENT_SOURCE_UNKNOWN:{ab}:{ref}")
    key_map={"Strength":"STR","Dexterity":"DEX","Constitution":"CON","Intelligence":"INT","Wisdom":"WIS","Charisma":"CHA","STR":"STR","DEX":"DEX","CON":"CON","INT":"INT","WIS":"WIS","CHA":"CHA"}
    key_ab=key_map.get(char.get("key_ability"))
    if not key_ab: raise BuildError(f"KEY_ABILITY_INVALID:{char.get('key_ability')}")
    attack_adjust=stats.get("technique_attack_adjustment",0); dc_adjust=stats.get("save_dc_adjustment",0)
    if not isinstance(attack_adjust,int) or not isinstance(dc_adjust,int): raise BuildError("TECHNIQUE_SCALAR_ADJUSTMENT_INTEGER_REQUIRED")
    if stats["technique_attack_bonus"] != pb + mods[key_ab] + attack_adjust: raise BuildError("TECHNIQUE_ATTACK_BONUS_RECONCILIATION_FAILED")
    if stats["save_dc"] != 8 + pb + mods[key_ab] + dc_adjust: raise BuildError("SAVE_DC_RECONCILIATION_FAILED")
    scalar_sources=obj(stats.get("technique_scalar_source_packet_ids",{}),"core_stats.technique_scalar_source_packet_ids")
    for label,value in (("technique_attack_adjustment",attack_adjust),("save_dc_adjustment",dc_adjust)):
        if value != 0:
            refs=scalar_sources.get(label,[])
            if not isinstance(refs,list) or not refs: raise BuildError(f"TECHNIQUE_SCALAR_SOURCE_REQUIRED:{label}")
            for ref in refs:
                if ref not in packets: raise BuildError(f"TECHNIQUE_SCALAR_SOURCE_UNKNOWN:{label}:{ref}")
    if stats.get("primary_resource_name") != path_rule["resource"]: raise BuildError(f"PATH_RESOURCE_MISMATCH:{stats.get('primary_resource_name')}!={path_rule['resource']}")
    hp_generation=obj(stats.get("hp_generation"),"core_stats.hp_generation")
    if hp_generation.get("hit_die") != path_rule["hit_die"]: raise BuildError(f"PATH_HIT_DIE_MISMATCH:{hp_generation.get('hit_die')}!={path_rule['hit_die']}")
    hp_mode=text(hp_generation.get("mode"),"core_stats.hp_generation.mode")
    if hp_mode not in {"fixed_average","rolled"}: raise BuildError(f"HP_GENERATION_MODE_INVALID:{hp_mode}")

    advancement=obj(ledger.get("advancement"),"advancement"); levels=arr(advancement.get("levels"),"advancement.levels"); timeline=ability_timeline(ledger)
    if [x.get("cl") for x in levels] != list(range(1,cl+1)): raise BuildError("LEVEL_ROWS_MUST_COVER_CL1_TO_CURRENT")
    last_hp=0
    allocation_index={}
    allocations_by_cl={}
    for level_index,row in enumerate(levels,1):
        rcl=row["cl"]; level_mods=(timeline.get(rcl) or {}).get("mods",mods); key_mod=level_mods[key_ab]; con_mod=level_mods["CON"]
        if row.get("realm")!=realm_for_cl(rcl): raise BuildError(f"LEVEL_REALM_MISMATCH:{rcl}")
        if row.get("pb")!=pb_for_cl(rcl): raise BuildError(f"LEVEL_PB_MISMATCH:{rcl}")
        hp=obj(row.get("hp"),f"level.{rcl}.hp"); mx=hp.get("max_after_level")
        if not isinstance(mx,int): raise BuildError(f"LEVEL_HP_INTEGER_REQUIRED:{rcl}")
        for field in ("base_gain","constitution_delta","other_delta"):
            if not isinstance(hp.get(field),int): raise BuildError(f"LEVEL_HP_COMPONENT_INTEGER_REQUIRED:CL{rcl}:{field}")
        expected_base=path_rule["die_size"] if rcl==1 else path_rule["fixed_average"]
        if rcl==1 and hp["base_gain"]!=expected_base: raise BuildError(f"LEVEL1_HP_BASE_MISMATCH:{hp['base_gain']}!={expected_base}")
        if rcl>1 and hp_mode=="fixed_average" and hp["base_gain"]!=expected_base: raise BuildError(f"FIXED_HP_BASE_MISMATCH:CL{rcl}:{hp['base_gain']}!={expected_base}")
        if rcl>1 and hp_mode=="rolled" and not 1<=hp["base_gain"]<=path_rule["die_size"]: raise BuildError(f"ROLLED_HP_BASE_OUT_OF_RANGE:CL{rcl}:{hp['base_gain']}")
        if hp["constitution_delta"]!=con_mod: raise BuildError(f"LEVEL_HP_CONSTITUTION_MISMATCH:CL{rcl}:{hp['constitution_delta']}!={con_mod}")
        expected_hp=last_hp+hp["base_gain"]+hp["constitution_delta"]+hp["other_delta"]
        if mx!=expected_hp: raise BuildError(f"LEVEL_HP_MATH_MISMATCH:CL{rcl}:{mx}!={expected_hp}")
        if hp["other_delta"] != 0:
            hp_refs=packet_refs(hp)
            if not hp_refs: raise BuildError(f"LEVEL_HP_OTHER_DELTA_SOURCE_REQUIRED:CL{rcl}")
            for ref in hp_refs:
                if ref not in packets: raise BuildError(f"LEVEL_HP_OTHER_DELTA_SOURCE_UNKNOWN:CL{rcl}:{ref}")
        if mx<last_hp and not row.get("legal_max_hp_reduction_event"): raise BuildError(f"HP_NOT_MONOTONIC:{rcl}")
        last_hp=mx
        resource=obj(row.get("resource"),f"level.{rcl}.resource")
        for f in ("base_after_level","method_delta","foundation_delta","item_delta","max_after_level"):
            if not isinstance(resource.get(f),int): raise BuildError(f"LEVEL_RESOURCE_INTEGER_REQUIRED:CL{rcl}:{f}")
        # RAW-015: Qi and Resonance pools never fall below 2 x Path level.
        expected_base=max(0,rcl*key_mod) if path_rule["resource"]=="Stamina" else max(rcl*key_mod,2*rcl)
        if resource["base_after_level"]!=expected_base: raise BuildError(f"LEVEL_RESOURCE_BASE_MISMATCH:CL{rcl}:{resource['base_after_level']}!={expected_base}")
        # Explicit Source-Rule modifiers stack across the active Primary Method,
        # Foundation, and items. The one-Primary-Method rule prevents multiple
        # Method shapes from stacking; it does not suppress Foundation benefits.
        if resource["method_delta"] != 0:
            if none_state(ledger.get("method")):
                raise BuildError(f"PRIMARY_RESOURCE_METHOD_DELTA_WITHOUT_METHOD:CL{rcl}:{resource['method_delta']}")
            method_id=(ledger.get("method") or {}).get("method_id")
            if resource.get("method_source_grant_id") != method_id:
                raise BuildError(f"PRIMARY_RESOURCE_METHOD_SOURCE_MISMATCH:CL{rcl}:{resource.get('method_source_grant_id')}!={method_id}")
        if resource["foundation_delta"] != 0:
            if none_state(ledger.get("foundation")):
                raise BuildError(f"PRIMARY_RESOURCE_FOUNDATION_DELTA_WITHOUT_FOUNDATION:CL{rcl}:{resource['foundation_delta']}")
            foundation_id=(ledger.get("foundation") or {}).get("foundation_id")
            if resource.get("foundation_source_grant_id") != foundation_id:
                raise BuildError(f"PRIMARY_RESOURCE_FOUNDATION_SOURCE_MISMATCH:CL{rcl}:{resource.get('foundation_source_grant_id')}!={foundation_id}")
        if resource["item_delta"] != 0:
            item_sources=resource.get("item_source_grant_ids")
            if not isinstance(item_sources,list) or not item_sources:
                raise BuildError(f"PRIMARY_RESOURCE_ITEM_SOURCE_REQUIRED:CL{rcl}")
        expected_max=resource["base_after_level"]+resource["method_delta"]+resource["foundation_delta"]+resource["item_delta"]
        if resource["max_after_level"]!=expected_max: raise BuildError(f"LEVEL_RESOURCE_MATH_MISMATCH:CL{rcl}:{resource['max_after_level']}!={expected_max}")
        if resource.get("name")!=stats.get("primary_resource_name"): raise BuildError(f"LEVEL_RESOURCE_NAME_MISMATCH:CL{rcl}")
        allocations=arr(row.get("allocations"),f"level.{rcl}.allocations")
        allocations_by_cl[rcl]=allocations
        trained_cost=0
        for order,a in enumerate(allocations,1):
            a=obj(a,f"level.{rcl}.allocations[{order-1}]")
            aid=text(a.get("allocation_id"),f"level.{rcl}.allocation_id")
            if aid in allocation_index: raise BuildError(f"DUPLICATE_ALLOCATION_ID:{aid}")
            channel=text(a.get("channel"),f"level.{rcl}.channel")
            if channel not in ALLOCATION_CHANNELS: raise BuildError(f"ALLOCATION_CHANNEL_INVALID:{rcl}:{channel}")
            grant_type=text(a.get("grant_type"),f"level.{rcl}.grant_type")
            if grant_type not in GRANT_TYPES: raise BuildError(f"ALLOCATION_GRANT_TYPE_INVALID:{rcl}:{grant_type}")
            text(a.get("grant_id"),f"level.{rcl}.grant_id")
            text(a.get("name"),f"level.{rcl}.name")
            if not isinstance(a.get("slot_cost"),int) or a["slot_cost"]<0: raise BuildError(f"ALLOCATION_SLOT_COST_REQUIRED:{rcl}")
            if channel in TRAINED_CHANNELS:
                if a["slot_cost"]!=1: raise BuildError(f"TRAINED_ALLOCATION_SLOT_COST_INVALID:{rcl}:{aid}:{a['slot_cost']}")
                trained_cost+=a["slot_cost"]
            elif a["slot_cost"]!=0:
                raise BuildError(f"FREE_ALLOCATION_SLOT_COST_INVALID:{rcl}:{aid}:{a['slot_cost']}")
            refs=packet_refs(a)
            if not refs: raise BuildError(f"ALLOCATION_SOURCE_PACKET_REQUIRED:{rcl}:{aid}")
            for ref in refs:
                if ref not in packets: raise BuildError(f"ALLOCATION_UNKNOWN_PACKET:{rcl}:{ref}")
            allocation_index[aid]={**a,"cl":rcl,"order":order}
        if trained_cost>3: raise BuildError(f"TRAINED_CHOICE_BUDGET_EXCEEDED:CL{rcl}:{trained_cost}")
        expected_hash=checkpoint_hash(levels,level_index)
        if row.get("state_after_hash")!=expected_hash: raise BuildError(f"STATE_CHECKPOINT_HASH_MISMATCH:CL{rcl}")
    if levels[-1]["hp"]["max_after_level"]!=stats["hp_max"]: raise BuildError("FINAL_HP_DOES_NOT_MATCH_LEVEL_LEDGER")

    bo=obj(ledger.get("background_origin"),"background_origin")
    background=obj(bo.get("background"),"background_origin.background"); origin=obj(bo.get("origin_insight"),"background_origin.origin_insight")
    text(background.get("background_id"),"background.background_id"); text(background.get("allocation_id"),"background.allocation_id")
    for f in ("name","summary","grant_mode"):
        text(background.get(f),f"background.{f}")
    if background["grant_mode"] not in {"sphere_and_talent","compensation"}: raise BuildError(f"BACKGROUND_GRANT_MODE_INVALID:{background['grant_mode']}")
    if background["grant_mode"] == "sphere_and_talent":
        text(background.get("background_sphere"),"background.background_sphere")
        text(background.get("background_talent"),"background.background_talent")
    else:
        text(background.get("compensation"),"background.compensation")
    arr(background.get("ability_score_options",[]),"background.ability_score_options")
    if not arr(background.get("equipment"),"background.equipment"): raise BuildError("BACKGROUND_EQUIPMENT_EMPTY")
    text(origin.get("origin_insight_id"),"origin_insight.origin_insight_id"); text(origin.get("allocation_id"),"origin_insight.allocation_id")
    for f in ("name","benefit"):
        text(origin.get(f),f"origin_insight.{f}")
    arr(origin.get("restrictions",[]),"origin_insight.restrictions")
    ensure_packet_refs([background,origin],packets,"background_origin")
    require_canonical_authority(background,packets,"background",build_mode); require_canonical_authority(origin,packets,"origin_insight",build_mode)
    require_named_canonical_selection(background,packets,"background",build_mode); require_named_canonical_selection(origin,packets,"origin_insight",build_mode)
    for field in ("skill_proficiencies","tool_proficiencies","languages"):
        arr(background.get(field,[]),f"background.{field}")
    equipment_reconciliation=obj(background.get("equipment_reconciliation"),"background.equipment_reconciliation")
    for field in ("printed_items","ledger_equipment_ids","bundled_items","missing_items"):
        arr(equipment_reconciliation.get(field,[]),f"background.equipment_reconciliation.{field}")
    text(equipment_reconciliation.get("note"),"background.equipment_reconciliation.note")
    if equipment_reconciliation.get("missing_items"):
        raise BuildError(f"BACKGROUND_EQUIPMENT_UNRECONCILED:{equipment_reconciliation.get('missing_items')}")
    effect_records=arr(origin.get("effect_records"),"origin_insight.effect_records")
    if not effect_records: raise BuildError("ORIGIN_EFFECT_RECORDS_EMPTY")
    effect_ids=set()
    for j,effect_row in enumerate(effect_records):
        effect_row=obj(effect_row,f"origin_insight.effect_records[{j}]")
        eid=text(effect_row.get("effect_id"),f"origin_insight.effect_records[{j}].effect_id")
        if eid in effect_ids: raise BuildError(f"ORIGIN_EFFECT_ID_DUPLICATE:{eid}")
        effect_ids.add(eid)
        for field in ("effect_type","trigger","condition","effect","display_surface","source_claim_text"):
            text(effect_row.get(field),f"origin_insight.effect_records[{j}].{field}")
        refs=packet_refs(effect_row)
        if not refs: raise BuildError(f"ORIGIN_EFFECT_SOURCE_REQUIRED:{eid}")
        matched=False
        for ref in refs:
            if ref not in packets: raise BuildError(f"ORIGIN_EFFECT_SOURCE_UNKNOWN:{eid}:{ref}")
            if effect_row["source_claim_text"] in packets[ref].get("source_text",""): matched=True
        if not matched: raise BuildError(f"ORIGIN_EFFECT_CLAIM_NOT_EXACT_SOURCE_TEXT:{eid}")
    validate_point_buy(stats,scores,background,packets,build_mode)

    spheres=arr(ledger.get("spheres"),"spheres"); talents=arr(ledger.get("talents"),"talents"); features=arr(ledger.get("features",[]),"features")
    if not spheres: raise BuildError("SPHERES_EMPTY")
    sphere_ids=set(); sphere_names=set()
    for i,row in enumerate(spheres):
        row=obj(row,f"spheres[{i}]"); sid=text(row.get("sphere_id"),f"spheres[{i}].sphere_id"); name=text(row.get("name"),f"spheres[{i}].name")
        if sid in sphere_ids or name in sphere_names: raise BuildError(f"DUPLICATE_SPHERE:{sid}:{name}")
        sphere_ids.add(sid); sphere_names.add(name)
        text(row.get("allocation_id"),f"sphere.{sid}.allocation_id")
        gained=row.get("gained_at_cl")
        if not isinstance(gained,int) or not 1<=gained<=cl: raise BuildError(f"SPHERE_GAIN_CL_INVALID:{sid}:{gained}")
        acquisition=text(row.get("acquisition_type"),f"sphere.{sid}.acquisition_type")
        if acquisition not in {"background_sphere","level_1_sphere","new_sphere","feature"}: raise BuildError(f"SPHERE_ACQUISITION_TYPE_INVALID:{sid}:{acquisition}")
    talent_ids=set(); talent_names=set()
    for i,row in enumerate(talents):
        row=obj(row,f"talents[{i}]"); tid=text(row.get("talent_id"),f"talents[{i}].talent_id")
        if tid in talent_ids: raise BuildError(f"DUPLICATE_TALENT:{tid}")
        name=text(row.get("name"),f"talent.{tid}.name")
        if name in talent_names: raise BuildError(f"DUPLICATE_TALENT_NAME:{name}")
        talent_ids.add(tid); talent_names.add(name); sphere=text(row.get("sphere"),f"talent.{tid}.sphere")
        if sphere not in sphere_names: raise BuildError(f"TALENT_UNKNOWN_SPHERE:{tid}:{sphere}")
        gained=row.get("gained_at_cl")
        if not isinstance(gained,int) or not 1<=gained<=cl: raise BuildError(f"TALENT_GAIN_CL_INVALID:{tid}:{gained}")
        acquisition=text(row.get("acquisition_type"),f"talent.{tid}.acquisition_type")
        if acquisition not in {"background_talent","free_level","new_sphere_bonus","trained_choice","feature"}: raise BuildError(f"TALENT_ACQUISITION_TYPE_INVALID:{tid}:{acquisition}")
        text(row.get("allocation_id"),f"talent.{tid}.allocation_id"); text(row.get("mechanical_summary"),f"talent.{tid}.mechanical_summary")
    ensure_packet_refs(spheres,packets,"spheres"); ensure_packet_refs(talents,packets,"talents"); ensure_packet_refs(features,packets,"features",optional=True)
    for row in spheres:
        require_canonical_authority(row,packets,f"sphere.{row['sphere_id']}",build_mode)
        require_named_canonical_selection(row,packets,f"sphere.{row['sphere_id']}",build_mode)
    for row in talents:
        require_canonical_authority(row,packets,f"talent.{row['talent_id']}",build_mode)
        require_named_canonical_selection(row,packets,f"talent.{row['talent_id']}",build_mode)
    sphere_by_name_pre={row["name"]:row for row in spheres}
    for row in talents:
        sphere_row=sphere_by_name_pre[row["sphere"]]
        if sphere_row["gained_at_cl"]>row["gained_at_cl"]: raise BuildError(f"TALENT_BEFORE_SPHERE:{row['talent_id']}:{row['gained_at_cl']}<{sphere_row['gained_at_cl']}")
    feature_ids=set(); path_feature_ids=set()
    for i,row in enumerate(features):
        row=obj(row,f"features[{i}]"); fid=text(row.get("feature_id"),f"features[{i}].feature_id")
        if fid in feature_ids: raise BuildError(f"DUPLICATE_FEATURE_ID:{fid}")
        feature_ids.add(fid); text(row.get("allocation_id"),f"feature.{fid}.allocation_id"); text(row.get("name"),f"feature.{fid}.name")
        if not isinstance(row.get("gained_at_cl"),int) or not 1<=row["gained_at_cl"]<=cl: raise BuildError(f"FEATURE_GAIN_CL_INVALID:{fid}")
        text(row.get("mechanical_summary"),f"feature.{fid}.mechanical_summary")
        category=text(row.get("category"),f"feature.{fid}.category")
        if category=="path_feature": path_feature_ids.add(fid)
        require_canonical_authority(row,packets,f"feature.{fid}",build_mode)
        require_named_canonical_selection(row,packets,f"feature.{fid}",build_mode)
    if set(expected_path_features)!=path_feature_ids:
        raise BuildError(f"PATH_FEATURE_SET_MISMATCH:expected={sorted(expected_path_features)}:actual={sorted(path_feature_ids)}")

    method=ledger.get("method")
    if not none_state(method):
        method=obj(method,"method")
        for f in ("method_id","allocation_id","name","role","resource_name","resource_formula"):
            text(method.get(f),f"method.{f}")
        if not isinstance(method.get("gained_at_cl"),int) or not 1<=method["gained_at_cl"]<=cl: raise BuildError("METHOD_GAIN_CL_INVALID")
        if not arr(method.get("benefits"),"method.benefits"): raise BuildError("METHOD_BENEFITS_EMPTY")
        arr(method.get("drawbacks",[]),"method.drawbacks"); arr(method.get("mechanical_hooks",[]),"method.mechanical_hooks")
        if not arr(method.get("applied_math"),"method.applied_math"): raise BuildError("METHOD_APPLIED_MATH_EMPTY")
        stacking_statement=text(method.get("stacking_statement"),"method.stacking_statement")
        if re.search(r"(?:foundation.*(?:does not|do not|cannot).*stack|only method.*(?:resource|maximum))",stacking_statement,re.I):
            raise BuildError("METHOD_FOUNDATION_FALSE_NONSTACKING_RULE")
        for j,modifier in enumerate(arr(method.get("resource_modifiers",[]),"method.resource_modifiers")):
            modifier=obj(modifier,f"method.resource_modifiers[{j}]")
            text(modifier.get("resource_name"),f"method.resource_modifiers[{j}].resource_name")
            if not isinstance(modifier.get("amount"),int): raise BuildError(f"METHOD_RESOURCE_MODIFIER_AMOUNT_REQUIRED:{j}")
            if modifier.get("operation") not in {"add","subtract","set","multiply"}: raise BuildError(f"METHOD_RESOURCE_MODIFIER_OPERATION_INVALID:{j}")
            ensure_packet_refs([modifier],packets,f"method.resource_modifiers[{j}]")
        text(method.get("breakthrough_shape"),"method.breakthrough_shape")
        if not arr(method.get("foundation_compatibility"),"method.foundation_compatibility"): raise BuildError("METHOD_FOUNDATION_COMPATIBILITY_EMPTY")
        if not arr(method.get("incompatibilities"),"method.incompatibilities"): raise BuildError("METHOD_INCOMPATIBILITIES_EMPTY")
        ensure_packet_refs([method],packets,"method")
        require_canonical_authority(method,packets,"method",build_mode)
        require_named_canonical_selection(method,packets,"method",build_mode)
    foundation=ledger.get("foundation")
    if cl >= 5 and none_state(foundation):
        raise BuildError("FOUNDATION_REQUIRED_FOR_COMPLETE_CL5_PLUS_BUILD")
    if not none_state(foundation):
        foundation=obj(foundation,"foundation")
        for f in ("foundation_id","allocation_id","name","chosen_foundation","grade","stage"):
            text(foundation.get(f),f"foundation.{f}")
        if not isinstance(foundation.get("gained_at_cl"),int) or not 1<=foundation["gained_at_cl"]<=cl: raise BuildError("FOUNDATION_GAIN_CL_INVALID")
        if foundation["gained_at_cl"] < 5:
            exception=foundation.get("mortal_exception_source_packet_id")
            if not exception or exception not in packets: raise BuildError("FOUNDATION_BEFORE_CL5_REQUIRES_EXPLICIT_SOURCE")
        benefits=arr(foundation.get("benefits"),"foundation.benefits")
        if len(benefits)<3: raise BuildError(f"FOUNDATION_BENEFITS_INCOMPLETE:{len(benefits)}")
        resource=obj(foundation.get("foundation_resource"),"foundation.foundation_resource")
        for f in ("name","generation"): text(resource.get(f),f"foundation.resource.{f}")
        if not isinstance(resource.get("current"),int) or not isinstance(resource.get("max"),int) or resource["current"]<0 or resource["max"]<0 or resource["current"]>resource["max"]: raise BuildError("FOUNDATION_RESOURCE_INVALID")
        arr(foundation.get("actions",[]),"foundation.actions"); arr(foundation.get("burdens",[]),"foundation.burdens")
        stage_rows=arr(foundation.get("stage_benefit_map"),"foundation.stage_benefit_map")
        if not stage_rows: raise BuildError("FOUNDATION_STAGE_BENEFIT_MAP_EMPTY")
        available_benefits=[]
        for j,stage_row in enumerate(stage_rows):
            stage_row=obj(stage_row,f"foundation.stage_benefit_map[{j}]")
            text(stage_row.get("stage"),f"foundation.stage_benefit_map[{j}].stage")
            if not isinstance(stage_row.get("available"),bool): raise BuildError(f"FOUNDATION_STAGE_AVAILABILITY_BOOLEAN_REQUIRED:{j}")
            stage_benefits=arr(stage_row.get("benefits",[]),f"foundation.stage_benefit_map[{j}].benefits")
            ensure_packet_refs([stage_row],packets,f"foundation.stage_benefit_map[{j}]")
            if stage_row["available"]: available_benefits.extend(stage_benefits)
        for benefit in benefits:
            if benefit not in available_benefits: raise BuildError(f"FOUNDATION_BENEFIT_NOT_IN_AVAILABLE_STAGE_MAP:{benefit}")
        for j,modifier in enumerate(arr(foundation.get("primary_resource_modifiers",[]),"foundation.primary_resource_modifiers")):
            modifier=obj(modifier,f"foundation.primary_resource_modifiers[{j}]")
            text(modifier.get("resource_name"),f"foundation.primary_resource_modifiers[{j}].resource_name")
            if not isinstance(modifier.get("amount"),int): raise BuildError(f"FOUNDATION_RESOURCE_MODIFIER_AMOUNT_REQUIRED:{j}")
            if modifier.get("operation") not in {"add","subtract","set","multiply"}: raise BuildError(f"FOUNDATION_RESOURCE_MODIFIER_OPERATION_INVALID:{j}")
            if not isinstance(modifier.get("applies_from_cl"),int): raise BuildError(f"FOUNDATION_RESOURCE_MODIFIER_CL_REQUIRED:{j}")
            ensure_packet_refs([modifier],packets,f"foundation.primary_resource_modifiers[{j}]")
        lifecycle=obj(foundation.get("lifecycle_coverage"),"foundation.lifecycle_coverage")
        lifecycle_keys=("passive_chassis","resources","actions_reactions","states","burdens","hidden_injuries","strains","deviations","integration","repair","treatment","temptations","failure_consequences")
        for category in lifecycle_keys:
            row=obj(lifecycle.get(category),f"foundation.lifecycle_coverage.{category}")
            status=text(row.get("status"),f"foundation.lifecycle_coverage.{category}.status")
            if status not in {"present","none_in_source","not_yet_available","suppressed_by_specific_rule"}: raise BuildError(f"FOUNDATION_LIFECYCLE_STATUS_INVALID:{category}:{status}")
            entries=arr(row.get("entries",[]),f"foundation.lifecycle_coverage.{category}.entries")
            text(row.get("note"),f"foundation.lifecycle_coverage.{category}.note")
            refs=arr(row.get("source_packet_ids",[]),f"foundation.lifecycle_coverage.{category}.source_packet_ids")
            if status=="present" and not entries: raise BuildError(f"FOUNDATION_LIFECYCLE_PRESENT_WITHOUT_ENTRIES:{category}")
            if status in {"none_in_source","not_yet_available","suppressed_by_specific_rule"} and entries: raise BuildError(f"FOUNDATION_LIFECYCLE_EMPTY_STATUS_HAS_ENTRIES:{category}")
            if status in {"present","suppressed_by_specific_rule"} and not refs: raise BuildError(f"FOUNDATION_LIFECYCLE_SOURCE_REQUIRED:{category}")
            for ref in refs:
                if ref not in packets: raise BuildError(f"FOUNDATION_LIFECYCLE_SOURCE_UNKNOWN:{category}:{ref}")
        for j,row in enumerate(arr(foundation.get("suppressed_or_excluded_benefits",[]),"foundation.suppressed_or_excluded_benefits")):
            row=obj(row,f"foundation.suppressed_or_excluded_benefits[{j}]")
            text(row.get("benefit"),f"foundation.suppressed_or_excluded_benefits[{j}].benefit")
            text(row.get("reason"),f"foundation.suppressed_or_excluded_benefits[{j}].reason")
            ensure_packet_refs([row],packets,f"foundation.suppressed_or_excluded_benefits[{j}]")
        if not arr(foundation.get("fixed_scope"),"foundation.fixed_scope"): raise BuildError("FOUNDATION_FIXED_SCOPE_EMPTY")
        if not arr(foundation.get("ai_notes"),"foundation.ai_notes"): raise BuildError("FOUNDATION_AI_NOTES_EMPTY")
        ensure_packet_refs([foundation],packets,"foundation")
        require_canonical_authority(foundation,packets,"foundation",build_mode)
        require_named_canonical_selection(foundation,packets,"foundation",build_mode)

    training_sources=arr(ledger.get("training_sources",[]),"training_sources")
    if not training_sources: raise BuildError("MANUAL_LINEAGE_SOURCE_REQUIRED_FOR_COMPLETE_CHARACTER")
    training_source_ids=set()
    acceptable_source_types={"manual","jade_slip","mural","teacher","teacher_record","sect_lineage","inheritance","family_record","spirit_relation","battlefield_journal","journal","item_source","other"}
    for i,row in enumerate(training_sources):
        row=obj(row,f"training_sources[{i}]")
        sid=text(row.get("source_id"),f"training_sources[{i}].source_id")
        if sid in training_source_ids: raise BuildError(f"DUPLICATE_TRAINING_SOURCE:{sid}")
        training_source_ids.add(sid)
        text(row.get("allocation_id"),f"training_source.{sid}.allocation_id")
        text(row.get("name"),f"training_source.{sid}.name")
        source_type=text(row.get("type"),f"training_source.{sid}.type")
        if source_type not in acceptable_source_types: raise BuildError(f"TRAINING_SOURCE_TYPE_INVALID:{sid}:{source_type}")
        gained=row.get("gained_at_cl")
        if not isinstance(gained,int) or not 1<=gained<=cl: raise BuildError(f"TRAINING_SOURCE_GAIN_CL_INVALID:{sid}:{gained}")
        contents=obj(row.get("contents"),f"training_source.{sid}.contents")
        for field in ("recorded_arts","methods","warnings","recipes","theory","false_routes"):
            arr(contents.get(field,[]),f"training_source.{sid}.contents.{field}")
        arr(row.get("restrictions",[]),f"training_source.{sid}.restrictions")
        arr(row.get("risks",[]),f"training_source.{sid}.risks")
        arr(row.get("mechanics_granted",[]),f"training_source.{sid}.mechanics_granted")
        ensure_packet_refs([row],packets,f"training_source.{sid}")
        require_canonical_authority(row,packets,f"training_source.{sid}",build_mode)
        require_named_canonical_selection(row,packets,f"training_source.{sid}",build_mode)

    non_sphere_sources={"Foundation","Method","Path","Background","Origin Insight","Equipment","Recorded Art","Training Source","Forged Technique","System"}
    non_talent_grants={background.get("name"),origin.get("name")}
    if isinstance(method,dict): non_talent_grants.add(method.get("name"))
    if isinstance(foundation,dict): non_talent_grants.add(foundation.get("name"))
    non_talent_grants.update(x.get("name") for x in training_sources)
    non_talent_grants.discard(None)

    equipment=arr(ledger.get("equipment",[]),"equipment"); ensure_packet_refs(equipment,packets,"equipment",optional=True)
    equipment_ids=set()
    for i,row in enumerate(equipment):
        row=obj(row,f"equipment[{i}]"); eid=text(row.get("equipment_id"),f"equipment[{i}].equipment_id")
        if eid in equipment_ids: raise BuildError(f"DUPLICATE_EQUIPMENT_ID:{eid}")
        equipment_ids.add(eid); text(row.get("allocation_id"),f"equipment.{eid}.allocation_id"); text(row.get("name"),f"equipment.{eid}.name"); text(row.get("type"),f"equipment.{eid}.type")
        if not isinstance(row.get("gained_at_cl"),int) or not 1<=row["gained_at_cl"]<=cl: raise BuildError(f"EQUIPMENT_GAIN_CL_INVALID:{eid}")
        if not isinstance(row.get("equipped"),bool): raise BuildError(f"EQUIPMENT_EQUIPPED_BOOLEAN_REQUIRED:{eid}")
        require_canonical_authority(row,packets,f"equipment.{eid}",build_mode)

    resources=arr(ledger.get("resources",[]),"resources"); resource_ids=set(); resource_names=set()
    for i,row in enumerate(resources):
        row=obj(row,f"resources[{i}]"); rid=text(row.get("resource_id"),f"resources[{i}].resource_id"); name=text(row.get("name"),f"resources[{i}].name")
        if rid in resource_ids or name in resource_names: raise BuildError(f"DUPLICATE_RESOURCE:{rid}:{name}")
        resource_ids.add(rid); resource_names.add(name)
        if not isinstance(row.get("current"),int) or not isinstance(row.get("max"),int) or row["current"]<0 or row["max"]<0 or row["current"]>row["max"]: raise BuildError(f"RESOURCE_VALUE_INVALID:{rid}")
        text(row.get("formula"),f"resource.{rid}.formula"); text(row.get("recovery"),f"resource.{rid}.recovery")
        if not arr(row.get("source_grant_ids"),f"resource.{rid}.source_grant_ids"): raise BuildError(f"RESOURCE_SOURCE_GRANTS_EMPTY:{rid}")
    if stats["primary_resource_name"] not in resource_names: raise BuildError("PRIMARY_RESOURCE_NOT_IN_RESOURCE_LEDGER")
    primary=next(x for x in resources if x["name"]==stats["primary_resource_name"])
    if primary["current"]!=stats["primary_resource_current"] or primary["max"]!=stats["primary_resource_max"]: raise BuildError("PRIMARY_RESOURCE_LEDGER_MISMATCH")

    state_rows=arr(ledger.get("states",[]),"states"); state_ids=set()
    for i,row in enumerate(state_rows):
        row=obj(row,f"states[{i}]"); sid=text(row.get("state_id"),f"states[{i}].state_id")
        if sid in state_ids: raise BuildError(f"DUPLICATE_STATE_ID:{sid}")
        state_ids.add(sid)
        for f in ("name","created_by","duration","effect","end_condition","source"): text(row.get(f),f"state.{sid}.{f}")

    action_ids=set(); actions=arr(ledger.get("actions"),"actions")
    for i,a in enumerate(actions):
        a=obj(a,f"actions[{i}]"); validate_action(a,i,action_ids); ensure_packet_refs([a],packets,f"action.{a['action_id']}")
        require_canonical_authority(a,packets,f"action.{a['action_id']}",build_mode)
    # Output-quality floors (meaningful actions, Composites, Recorded Arts) are
    # the generating controller's responsibility, not character legality.
    meaningful=[a for a in actions if a.get("bucket")!="passive" and not a.get("basic_system_action")]
    for a in actions:
        aid=a["action_id"]
        for sid in arr(a.get("creates_states",[]),f"action.{aid}.creates_states")+arr(a.get("consumes_states",[]),f"action.{aid}.consumes_states"):
            if sid not in state_ids: raise BuildError(f"ACTION_UNKNOWN_STATE:{aid}:{sid}")
        for sphere in arr(a.get("source_spheres",[]),f"action.{aid}.source_spheres"):
            if sphere not in sphere_names and sphere not in sphere_ids and sphere not in non_sphere_sources: raise BuildError(f"ACTION_UNKNOWN_SPHERE:{aid}:{sphere}")
        for tid in arr(a.get("source_talents",[]),f"action.{aid}.source_talents"):
            if tid not in talent_ids and tid not in talent_names and tid not in non_talent_grants: raise BuildError(f"ACTION_UNKNOWN_TALENT:{aid}:{tid}")
        for cost_index,cost in enumerate(arr(a.get("resource_costs"),f"action.{aid}.resource_costs")):
            cost=obj(cost,f"action.{aid}.resource_costs[{cost_index}]")
            rid=text(cost.get("resource_id"),f"action.{aid}.resource_costs[{cost_index}].resource_id")
            if rid not in resource_ids: raise BuildError(f"ACTION_RESOURCE_COST_UNKNOWN:{aid}:{rid}")
            if not isinstance(cost.get("amount"),int) or cost["amount"]<0: raise BuildError(f"ACTION_RESOURCE_COST_INVALID:{aid}:{rid}")
            maximum=cost.get("maximum_amount",cost["amount"])
            if not isinstance(maximum,int) or maximum<cost["amount"]: raise BuildError(f"ACTION_RESOURCE_COST_RANGE_INVALID:{aid}:{rid}:{cost['amount']}..{maximum}")
            if maximum>cost["amount"] and cost.get("selection_required") is not True: raise BuildError(f"ACTION_VARIABLE_RESOURCE_COST_SELECTION_REQUIRED:{aid}:{rid}")
            text(cost.get("timing"),f"action.{aid}.resource_costs[{cost_index}].timing")
            text(cost.get("condition"),f"action.{aid}.resource_costs[{cost_index}].condition")
            if cost["amount"]>0:
                resource_row=next(x for x in resources if x["resource_id"]==rid)
                cost_display=str(a.get("cost","")).lower()
                if str(cost["amount"]) not in cost_display or resource_row["name"].lower() not in cost_display:
                    refs=arr(a.get("cost_display_override_source_packet_ids",[]),f"action.{aid}.cost_display_override_source_packet_ids")
                    if not refs: raise BuildError(f"ACTION_COST_DISPLAY_MISMATCH:{aid}:{cost['amount']} {resource_row['name']}!={a.get('cost')}")
                    for ref in refs:
                        if ref not in packets: raise BuildError(f"ACTION_COST_DISPLAY_OVERRIDE_SOURCE_UNKNOWN:{aid}:{ref}")
        cost_text=str(a.get("cost", ""))
        variable_match=re.search(r"\bspend\s+(\d+)\s*[–—-]\s*(\d+)\s+([A-Za-z][A-Za-z -]*?)(?:[.;,]|$)",cost_text,re.I)
        if variable_match:
            low,high=int(variable_match.group(1)),int(variable_match.group(2)); resource_name=variable_match.group(3).strip().lower()
            matches=[]
            for cost in arr(a.get("resource_costs"),f"action.{aid}.resource_costs"):
                if not isinstance(cost,dict): continue
                row=next((x for x in resources if x.get("resource_id")==cost.get("resource_id")),None)
                if row and row.get("name","").lower() in resource_name:
                    matches.append(cost)
            if not matches: raise BuildError(f"ACTION_VARIABLE_RESOURCE_COST_NOT_TYPED:{aid}:{low}-{high}:{resource_name}")
            if not any(x.get("amount")==low and x.get("maximum_amount")==high and x.get("selection_required") is True for x in matches):
                raise BuildError(f"ACTION_VARIABLE_RESOURCE_COST_RANGE_MISMATCH:{aid}:{low}-{high}")
        roll_text=str(a.get("roll_save_check",""))
        dc_numbers=[int(x) for x in re.findall(r"\bDC\s*(\d+)\b",roll_text,re.I)]
        if dc_numbers and any(x!=stats["save_dc"] for x in dc_numbers):
            refs=arr(a.get("roll_override_source_packet_ids",[]),f"action.{aid}.roll_override_source_packet_ids")
            if not refs: raise BuildError(f"ACTION_SAVE_DC_DISPLAY_MISMATCH:{aid}:{dc_numbers}!={stats['save_dc']}")
            for ref in refs:
                if ref not in packets: raise BuildError(f"ACTION_ROLL_OVERRIDE_SOURCE_UNKNOWN:{aid}:{ref}")
        attack_match=re.search(r"technique attack\s*([+-]\d+)",roll_text,re.I)
        if attack_match and int(attack_match.group(1))!=stats["technique_attack_bonus"]:
            refs=arr(a.get("roll_override_source_packet_ids",[]),f"action.{aid}.roll_override_source_packet_ids")
            if not refs: raise BuildError(f"ACTION_ATTACK_DISPLAY_MISMATCH:{aid}:{attack_match.group(1)}!={stats['technique_attack_bonus']}")
            for ref in refs:
                if ref not in packets: raise BuildError(f"ACTION_ROLL_OVERRIDE_SOURCE_UNKNOWN:{aid}:{ref}")
        for gain_index,gain in enumerate(arr(a.get("resource_gains"),f"action.{aid}.resource_gains")):
            gain=obj(gain,f"action.{aid}.resource_gains[{gain_index}]")
            rid=text(gain.get("resource_id"),f"action.{aid}.resource_gains[{gain_index}].resource_id")
            if rid not in resource_ids: raise BuildError(f"ACTION_RESOURCE_GAIN_UNKNOWN:{aid}:{rid}")
            if not isinstance(gain.get("amount"),int) or gain["amount"]<=0: raise BuildError(f"ACTION_RESOURCE_GAIN_INVALID:{aid}:{rid}")
            text(gain.get("trigger"),f"action.{aid}.resource_gains[{gain_index}].trigger")
            text(gain.get("cap_behavior"),f"action.{aid}.resource_gains[{gain_index}].cap_behavior")
        for req_index,requirement in enumerate(arr(a.get("resource_requirements"),f"action.{aid}.resource_requirements")):
            requirement=obj(requirement,f"action.{aid}.resource_requirements[{req_index}]")
            rid=text(requirement.get("resource_id"),f"action.{aid}.resource_requirements[{req_index}].resource_id")
            if rid not in resource_ids: raise BuildError(f"ACTION_RESOURCE_REQUIREMENT_UNKNOWN:{aid}:{rid}")
            if not isinstance(requirement.get("minimum"),int) or requirement["minimum"]<0: raise BuildError(f"ACTION_RESOURCE_REQUIREMENT_INVALID:{aid}:{rid}")
            text(requirement.get("condition"),f"action.{aid}.resource_requirements[{req_index}].condition")
    for row in state_rows:
        if row["created_by"] not in action_ids: raise BuildError(f"STATE_CREATOR_NOT_EXPORTED:{row['state_id']}:{row['created_by']}")
        producers=sorted(a["action_id"] for a in actions if row["state_id"] in arr(a.get("creates_states",[]),f"action.{a['action_id']}.creates_states"))
        if row["created_by"] not in producers: raise BuildError(f"STATE_PRIMARY_CREATOR_DOES_NOT_CREATE_STATE:{row['state_id']}:{row['created_by']}")

    def validate_execution_coverage(rows, expected_rows, id_field, label):
        rows=arr(rows,label); expected={r[id_field]:r for r in expected_rows}; seen=set()
        active_classes={"standalone_action","alternate_attack","bonus_action","reaction","triggered_passive","noncombat_procedure","subsumed_expression"}
        for i,row in enumerate(rows):
            row=obj(row,f"{label}[{i}]"); sid=text(row.get("source_id"),f"{label}[{i}].source_id")
            if sid in seen: raise BuildError(f"EXECUTION_COVERAGE_DUPLICATE:{label}:{sid}")
            seen.add(sid)
            if sid not in expected: raise BuildError(f"EXECUTION_COVERAGE_UNKNOWN_SOURCE:{label}:{sid}")
            if row.get("source_name")!=expected[sid].get("name"): raise BuildError(f"EXECUTION_COVERAGE_NAME_MISMATCH:{label}:{sid}")
            classification=text(row.get("classification"),f"{label}[{i}].classification")
            if classification not in {"standalone_action","alternate_attack","bonus_action","reaction","triggered_passive","action_modifier","state_modifier","noncombat_procedure","pure_passive_stat","subsumed_expression"}: raise BuildError(f"EXECUTION_COVERAGE_CLASS_INVALID:{label}:{sid}:{classification}")
            actions_for=arr(row.get("action_ids",[]),f"{label}[{i}].action_ids")
            targets=arr(row.get("target_action_ids",[]),f"{label}[{i}].target_action_ids")
            states_for=arr(row.get("state_ids",[]),f"{label}[{i}].state_ids")
            stats_for=arr(row.get("stat_targets",[]),f"{label}[{i}].stat_targets")
            text(row.get("display_surface"),f"{label}[{i}].display_surface"); text(row.get("coverage_note"),f"{label}[{i}].coverage_note")
            ensure_packet_refs([row],packets,f"{label}.{sid}")
            for aid in actions_for+targets:
                if aid not in action_ids: raise BuildError(f"EXECUTION_COVERAGE_ACTION_UNRESOLVED:{label}:{sid}:{aid}")
            for stid in states_for:
                if stid not in state_ids: raise BuildError(f"EXECUTION_COVERAGE_STATE_UNRESOLVED:{label}:{sid}:{stid}")
            if classification in active_classes and not actions_for: raise BuildError(f"EXECUTION_COVERAGE_ACTION_REQUIRED:{label}:{sid}:{classification}")
            if classification=="action_modifier":
                if not targets: raise BuildError(f"EXECUTION_COVERAGE_TARGET_ACTION_REQUIRED:{label}:{sid}")
                for aid in targets:
                    action=next(a for a in actions if a["action_id"]==aid)
                    refs=set(action.get("source_talents",[]))|set(action.get("source_spheres",[]))|set(action.get("applied_talent_ids",[]))|set(action.get("applied_sphere_ids",[]))
                    if sid not in refs and expected[sid].get("name") not in refs: raise BuildError(f"EXECUTION_MODIFIER_NOT_ATTACHED_TO_ACTION:{label}:{sid}:{aid}")
            if classification=="state_modifier" and not states_for: raise BuildError(f"EXECUTION_COVERAGE_STATE_REQUIRED:{label}:{sid}")
            if classification=="pure_passive_stat" and not stats_for: raise BuildError(f"EXECUTION_COVERAGE_STAT_TARGET_REQUIRED:{label}:{sid}")
        missing=set(expected)-seen
        if missing: raise BuildError(f"EXECUTION_COVERAGE_MISSING:{label}:{sorted(missing)}")
    manuals=arr(ledger.get("recorded_arts",[]),"recorded_arts")
    for i,m in enumerate(manuals):
        mid=text(m.get("manual_technique_id"),f"recorded_arts[{i}].manual_technique_id")
        text(m.get("allocation_id"),f"manual.{mid}.allocation_id")
        roles=arr(m.get("tactical_roles",[]),f"manual.{mid}.tactical_roles")
        if not roles: raise BuildError(f"RECORDED_ART_TACTICAL_ROLE_REQUIRED:{mid}")
        for f in ("manual_name","technique_name","reproduced_package","training_dc_expression","does_not_grant"):
            text(m.get(f),f"manual.{mid}.{f}")
        training_source_id=text(m.get("training_source_id"),f"manual.{mid}.training_source_id")
        source_record=next((x for x in training_sources if x["source_id"]==training_source_id),None)
        if not source_record: raise BuildError(f"MANUAL_TRAINING_SOURCE_UNRESOLVED:{mid}:{training_source_id}")
        if mid not in source_record.get("contents",{}).get("recorded_arts",[]): raise BuildError(f"MANUAL_NOT_LISTED_IN_TRAINING_SOURCE:{mid}:{training_source_id}")
        if not isinstance(m.get("manual_difficulty"),int) or m["manual_difficulty"]<0: raise BuildError(f"MANUAL_DIFFICULTY_INTEGER_REQUIRED:{mid}")
        if not isinstance(m.get("training_dc"),int): raise BuildError(f"MANUAL_TRAINING_DC_INTEGER_REQUIRED:{mid}")
        linked=text(m.get("linked_action_id"),f"manual.{mid}.linked_action_id")
        if linked not in action_ids: raise BuildError(f"MANUAL_ACTION_NOT_EXPORTED:{mid}:{linked}")
        validate_exec(m.get("execution"),f"manual.{mid}.execution")
        linked_action=next(a for a in actions if a["action_id"]==linked)
        if linked_action.get("recorded_art_id")!=mid: raise BuildError(f"MANUAL_ACTION_RECORDED_ART_LINK_MISMATCH:{mid}:{linked}")
        for field in ACTION_FIELDS:
            if linked_action.get(field)!=m["execution"].get(field): raise BuildError(f"MANUAL_EXECUTION_ACTION_MISMATCH:{mid}:{field}")
        ensure_packet_refs([m],packets,f"manual.{mid}")
        require_canonical_authority(m,packets,f"manual.{mid}",build_mode)
        require_named_canonical_selection({**m,"name":m.get("technique_name")},packets,f"manual.{mid}",build_mode)
        expression_kind=text(m.get("expression_kind"),f"manual.{mid}.expression_kind")
        if expression_kind not in {"single_sphere_expression","source_authored_lineage_expression","preserved_forged_expression"}:
            raise BuildError(f"RECORDED_ART_EXPRESSION_KIND_INVALID:{mid}:{expression_kind}")
        source_sphere_rows=arr(m.get("source_spheres",[]),f"manual.{mid}.source_spheres")
        if expression_kind=="single_sphere_expression":
            if len(source_sphere_rows)!=1: raise BuildError(f"RECORDED_ART_SINGLE_SPHERE_REQUIRED:{mid}:{len(source_sphere_rows)}")
            if m.get("preserved_forged_expression") is not None: raise BuildError(f"RECORDED_ART_SINGLE_SPHERE_CANNOT_CARRY_PRESERVED_FORGED:{mid}")
        if expression_kind=="source_authored_lineage_expression":
            if m.get("custom_design") is not False: raise BuildError(f"RECORDED_ART_LINEAGE_EXPRESSION_CANNOT_BE_CUSTOM_DESIGN:{mid}")
            if len(source_sphere_rows)<2: raise BuildError(f"RECORDED_ART_LINEAGE_EXPRESSION_REQUIRES_MULTI_SPHERE_SOURCE:{mid}")
            if m.get("preserved_forged_expression") is not None: raise BuildError(f"RECORDED_ART_LINEAGE_EXPRESSION_CANNOT_CARRY_PRESERVED_FORGED:{mid}")
        if expression_kind=="preserved_forged_expression" and m.get("preserved_forged_expression") is None:
            raise BuildError(f"RECORDED_ART_PRESERVED_FORGED_RECORD_REQUIRED:{mid}")
        if m.get("custom_design") is True and len(source_sphere_rows)>1 and expression_kind!="preserved_forged_expression":
            raise BuildError(f"CUSTOM_RECORDED_ART_MULTI_SPHERE_REQUIRES_PRESERVED_FORGED_EXPRESSION:{mid}")
        preserved=m.get("preserved_forged_expression")
        if preserved is not None:
            preserved=obj(preserved,f"manual.{mid}.preserved_forged_expression")
            pid=text(preserved.get("expression_id"),f"manual.{mid}.preserved.expression_id")
            if preserved.get("status")!="preserved_recorded_art_expression": raise BuildError(f"PRESERVED_FORGED_STATUS_INVALID:{pid}")
            if preserved.get("source_recorded_art_id")!=mid: raise BuildError(f"PRESERVED_FORGED_RECORDED_ART_LINK_MISMATCH:{pid}:{mid}")
            if preserved.get("linked_action_id")!=linked: raise BuildError(f"PRESERVED_FORGED_ACTION_LINK_MISMATCH:{pid}:{linked}")
            text(preserved.get("name"),f"preserved.{pid}.name"); text(preserved.get("base_form"),f"preserved.{pid}.base_form")
            primary_sphere_name=text(preserved.get("primary_sphere"),f"preserved.{pid}.primary_sphere")
            secondary_sphere_names=arr(preserved.get("secondary_spheres",[]),f"preserved.{pid}.secondary_spheres")
            if len(secondary_sphere_names)!=len(set(secondary_sphere_names)): raise BuildError(f"PRESERVED_FORGED_SECONDARY_SPHERE_DUPLICATE:{pid}")
            for sphere_name in [primary_sphere_name,*secondary_sphere_names]:
                sphere=sphere_by_name_pre.get(sphere_name)
                if not sphere or sphere["gained_at_cl"]>m.get("gained_at_cl",cl): raise BuildError(f"PRESERVED_FORGED_SPHERE_NOT_KNOWN:{pid}:{sphere_name}")
            components=arr(preserved.get("component_grant_ids"),f"preserved.{pid}.component_grant_ids")
            if not components: raise BuildError(f"PRESERVED_FORGED_COMPONENTS_EMPTY:{pid}")
            for ref in components:
                if ref not in talent_ids and ref not in talent_names and ref not in sphere_ids and ref not in sphere_names: raise BuildError(f"PRESERVED_FORGED_COMPONENT_UNRESOLVED:{pid}:{ref}")
            if not isinstance(preserved.get("complexity"),int) or preserved["complexity"]<1: raise BuildError(f"PRESERVED_FORGED_COMPLEXITY_INVALID:{pid}")
            if not isinstance(preserved.get("cp_cost"),int) or preserved["cp_cost"]<1: raise BuildError(f"PRESERVED_FORGED_CP_COST_INVALID:{pid}")
            if preserved.get("counts_against_personal_forged_limit") is not False: raise BuildError(f"PRESERVED_FORGED_PERSONAL_SLOT_FLAG_INVALID:{pid}")
            if preserved.get("learned_as_personal_technique") is not False: raise BuildError(f"PRESERVED_FORGED_LEARNED_FLAG_INVALID:{pid}")
            if not isinstance(preserved.get("learnable_separately"),bool): raise BuildError(f"PRESERVED_FORGED_LEARNABLE_FLAG_REQUIRED:{pid}")
            validate_exec(preserved.get("execution"),f"preserved.{pid}.execution")
            for field in ACTION_FIELDS:
                if preserved["execution"].get(field)!=m["execution"].get(field): raise BuildError(f"PRESERVED_FORGED_MANUAL_EXECUTION_MISMATCH:{pid}:{field}")
            ensure_packet_refs([preserved],packets,f"preserved.{pid}")
            require_canonical_authority(preserved,packets,f"preserved.{pid}",build_mode)
    preserved_ids=[m.get("preserved_forged_expression",{}).get("expression_id") for m in manuals if m.get("preserved_forged_expression")]
    if len(preserved_ids)!=len(set(preserved_ids)): raise BuildError("DUPLICATE_PRESERVED_FORGED_EXPRESSION_ID")
    if not manuals and not none_state(ledger.get("recorded_arts_none_state")): raise BuildError("RECORDED_ART_EMPTY_REQUIRES_NONE_STATE")

    forged=arr(ledger.get("forged_techniques",[]),"forged_techniques")
    if not forged and not none_state(ledger.get("forged_techniques_none_state")): raise BuildError("FORGED_EMPTY_REQUIRES_NONE_STATE")
    if len(forged)>pb: raise BuildError(f"FORGED_TECHNIQUE_PB_LIMIT_EXCEEDED:{len(forged)}>{pb}")
    for i,f in enumerate(forged):
        fid=text(f.get("forged_id"),f"forged[{i}].forged_id"); aid=text(f.get("action_id"),f"forged.{fid}.action_id")
        if aid not in action_ids: raise BuildError(f"FORGED_ACTION_NOT_EXPORTED:{fid}:{aid}")
        forged_action=next(a for a in actions if a["action_id"]==aid)
        if forged_action.get("forged_id")!=fid: raise BuildError(f"FORGED_ACTION_IDENTITY_MISMATCH:{fid}:{aid}")
        learned=f.get("cl_learned")
        if not isinstance(learned,int) or not 1<=learned<=cl: raise BuildError(f"FORGED_CL_ILLEGAL:{fid}:{learned}")
        if learned<5:
            exception=f.get("mortal_exception_source_packet_id")
            if not exception or exception not in packets: raise BuildError(f"FORGED_MORTAL_EXCEPTION_SOURCE_REQUIRED:{fid}:{learned}")
        if f.get("realm")!=realm_for_cl(learned): raise BuildError(f"FORGED_REALM_CL_MISMATCH:{fid}:{f.get('realm')}:{learned}")
        status=text(f.get("status"),f"forged.{fid}.status")
        if status not in {"learned","signature","evolved"}: raise BuildError(f"FORGED_STATUS_INVALID:{fid}:{status}")
        base_form=text(f.get("base_form"),f"forged.{fid}.base_form")
        if base_form not in BASE_FORMS: raise BuildError(f"FORGED_BASE_FORM_INVALID:{fid}:{base_form}")
        base_complexity=f.get("base_complexity"); secondary_complexity=f.get("secondary_sphere_complexity_adjustment")
        base_cp=f.get("base_cp_cost"); secondary_cp=f.get("secondary_sphere_cp_adjustment")
        for label,value in (("base_complexity",base_complexity),("secondary_sphere_complexity_adjustment",secondary_complexity),("base_cp_cost",base_cp),("secondary_sphere_cp_adjustment",secondary_cp)):
            if not isinstance(value,int) or value<0: raise BuildError(f"FORGED_COST_COMPONENT_INVALID:{fid}:{label}:{value}")
        expected_base_cp, expected_base_complexity = BASE_FORMS[base_form]
        if base_complexity != expected_base_complexity: raise BuildError(f"FORGED_BASE_COMPLEXITY_MISMATCH:{fid}:{base_complexity}!={expected_base_complexity}")
        if expected_base_cp is None:
            if base_cp < 1: raise BuildError(f"FORGED_RITUAL_BASE_CP_INVALID:{fid}:{base_cp}")
        elif base_cp != expected_base_cp:
            raise BuildError(f"FORGED_BASE_CP_MISMATCH:{fid}:{base_cp}!={expected_base_cp}")
        comp=f.get("final_complexity")
        if not isinstance(comp,int) or comp<1 or comp>complexity_limit(learned): raise BuildError(f"FORGED_COMPLEXITY_ILLEGAL:{fid}:{comp}")
        secondaries=arr(f.get("secondary_spheres",[]),f"forged.{fid}.secondary_spheres")
        if len(secondaries)!=len(set(secondaries)): raise BuildError(f"FORGED_SECONDARY_SPHERE_DUPLICATE:{fid}")
        if f.get("primary_sphere") in secondaries: raise BuildError(f"FORGED_PRIMARY_REPEATED_AS_SECONDARY:{fid}")
        if secondary_complexity != len(secondaries): raise BuildError(f"FORGED_SECONDARY_COMPLEXITY_MISMATCH:{fid}:{secondary_complexity}!={len(secondaries)}")
        all_forged_spheres=[f.get("primary_sphere")]+secondaries
        for sphere_name in all_forged_spheres:
            sphere=sphere_by_name_pre.get(sphere_name)
            if not sphere or sphere["gained_at_cl"]>learned: raise BuildError(f"FORGED_SPHERE_NOT_KNOWN_AT_LEARNING:{fid}:{sphere_name}")
        sphere_count=len(all_forged_spheres)
        if f.get("forging_dc")!=10+comp+sphere_count: raise BuildError(f"FORGED_DC_MISMATCH:{fid}")
        component_actions=arr(f.get("component_action_ids",[]),f"forged.{fid}.component_action_ids")
        if not component_actions: raise BuildError(f"FORGED_COMPONENT_ACTIONS_EMPTY:{fid}")
        for ref in component_actions:
            if ref not in action_ids: raise BuildError(f"FORGED_COMPONENT_ACTION_UNRESOLVED:{fid}:{ref}")
        component_grants=arr(f.get("component_grant_ids",[]),f"forged.{fid}.component_grant_ids")
        if not component_grants: raise BuildError(f"FORGED_COMPONENT_GRANTS_EMPTY:{fid}")
        for ref in component_grants:
            if ref not in talent_ids and ref not in talent_names and ref not in sphere_ids and ref not in sphere_names: raise BuildError(f"FORGED_COMPONENT_GRANT_UNRESOLVED:{fid}:{ref}")
            row = next((x for x in talents if ref in {x.get("talent_id"),x.get("name")}), None) or next((x for x in spheres if ref in {x.get("sphere_id"),x.get("name")}), None)
            if row and row.get("gained_at_cl",99)>learned: raise BuildError(f"FORGED_COMPONENT_NOT_KNOWN_AT_LEARNING:{fid}:{ref}")
        total_reduction=0
        for drawback in arr(f.get("drawbacks",[]),f"forged.{fid}.drawbacks"):
            drawback=obj(drawback,f"forged.{fid}.drawback"); text(drawback.get("name"),f"forged.{fid}.drawback.name"); text(drawback.get("consequence"),f"forged.{fid}.drawback.consequence")
            reduction=drawback.get("cp_reduction")
            if not isinstance(reduction,int) or reduction<0: raise BuildError(f"FORGED_DRAWBACK_REDUCTION_INVALID:{fid}")
            canonical=CANONICAL_DRAWBACK_REDUCTIONS.get(drawback["name"])
            if canonical is None:
                refs=arr(drawback.get("exception_source_packet_ids",[]),f"forged.{fid}.drawback.exception_source_packet_ids")
                if not refs: raise BuildError(f"FORGED_CUSTOM_DRAWBACK_SOURCE_REQUIRED:{fid}:{drawback['name']}")
                for ref in refs:
                    if ref not in packets: raise BuildError(f"FORGED_CUSTOM_DRAWBACK_SOURCE_UNKNOWN:{fid}:{ref}")
            elif reduction!=canonical:
                raise BuildError(f"FORGED_DRAWBACK_REDUCTION_MISMATCH:{fid}:{drawback['name']}:{reduction}!={canonical}")
            total_reduction+=reduction
        if total_reduction>pb: raise BuildError(f"FORGED_DRAWBACK_REDUCTION_EXCEEDS_PB:{fid}:{total_reduction}>{pb}")
        augment_complexity=0; augment_cp=0
        for augment in arr(f.get("augments",[]),f"forged.{fid}.augments"):
            augment=obj(augment,f"forged.{fid}.augment"); text(augment.get("name"),f"forged.{fid}.augment.name")
            if not isinstance(augment.get("complexity"),int) or augment["complexity"]<0: raise BuildError(f"FORGED_AUGMENT_COMPLEXITY_INVALID:{fid}")
            if not isinstance(augment.get("additional_cp"),int) or augment["additional_cp"]<0: raise BuildError(f"FORGED_AUGMENT_CP_INVALID:{fid}")
            minimum_realm=text(augment.get("minimum_realm"),f"forged.{fid}.augment.minimum_realm")
            if minimum_realm not in REALM_RANK or REALM_RANK[f["realm"]]<REALM_RANK[minimum_realm]: raise BuildError(f"FORGED_AUGMENT_REALM_ILLEGAL:{fid}:{minimum_realm}")
            canonical=ADVANCED_AUGMENTS.get(augment["name"])
            if canonical:
                if (minimum_realm,augment["complexity"],augment["additional_cp"])!=canonical:
                    raise BuildError(f"FORGED_ADVANCED_AUGMENT_MISMATCH:{fid}:{augment['name']}")
            elif augment["complexity"]!=1 or augment["additional_cp"]!=1:
                refs=arr(augment.get("exception_source_packet_ids",[]),f"forged.{fid}.augment.exception_source_packet_ids")
                if not refs: raise BuildError(f"FORGED_NONSTANDARD_AUGMENT_SOURCE_REQUIRED:{fid}:{augment['name']}")
                for ref in refs:
                    if ref not in packets: raise BuildError(f"FORGED_NONSTANDARD_AUGMENT_SOURCE_UNKNOWN:{fid}:{ref}")
            augment_complexity+=augment["complexity"]; augment_cp+=augment["additional_cp"]
        expected_complexity=base_complexity+secondary_complexity+augment_complexity
        if comp!=expected_complexity: raise BuildError(f"FORGED_COMPLEXITY_RECONCILIATION_FAILED:{fid}:{comp}!={expected_complexity}")
        expected_cp=max(1,base_cp+secondary_cp+augment_cp-total_reduction)
        if f.get("final_cp_cost")!=expected_cp: raise BuildError(f"FORGED_CP_RECONCILIATION_FAILED:{fid}:{f.get('final_cp_cost')}!={expected_cp}")
        forged_primary_cost=sum(c.get("amount",0) for c in forged_action.get("resource_costs",[]) if c.get("resource_id")==primary["resource_id"])
        if forged_primary_cost!=expected_cp: raise BuildError(f"FORGED_ACTION_CP_COST_MISMATCH:{fid}:{forged_primary_cost}!={expected_cp}")
        text(f.get("cost_adjudication_note"),f"forged.{fid}.cost_adjudication_note")
        cost_refs=arr(f.get("cost_authority_packet_ids"),f"forged.{fid}.cost_authority_packet_ids")
        if not cost_refs: raise BuildError(f"FORGED_COST_AUTHORITY_REQUIRED:{fid}")
        for ref in cost_refs:
            if ref not in packets: raise BuildError(f"FORGED_COST_AUTHORITY_UNKNOWN:{fid}:{ref}")
        record=obj(f.get("forging_record"),f"forged.{fid}.forging_record")
        text(record.get("research_time"),f"forged.{fid}.forging_record.research_time")
        if not arr(record.get("materials"),f"forged.{fid}.forging_record.materials"): raise BuildError(f"FORGED_MATERIALS_EMPTY:{fid}")
        if record.get("check_dc")!=f.get("forging_dc"): raise BuildError(f"FORGED_RECORD_DC_MISMATCH:{fid}")
        if not isinstance(record.get("check_total"),int): raise BuildError(f"FORGED_CHECK_TOTAL_INTEGER_REQUIRED:{fid}")
        if record["check_total"] < record["check_dc"]: raise BuildError(f"FORGED_FINAL_CHECK_NOT_SUCCESSFUL:{fid}:{record['check_total']}<{record['check_dc']}")
        if record.get("result") not in {"success","failed_then_succeeded"}: raise BuildError(f"FORGED_RECORD_RESULT_INVALID:{fid}")
        if not isinstance(record.get("attempts"),int) or record["attempts"]<1: raise BuildError(f"FORGED_ATTEMPTS_INVALID:{fid}")
        validate_exec(f.get("execution"),f"forged.{fid}.execution")
        ensure_packet_refs([f],packets,f"forged.{fid}")
        require_canonical_authority(f,packets,f"forged.{fid}.rules",build_mode)
    seeds=arr(ledger.get("emergency_technique_seeds",[]),"emergency_technique_seeds")
    if not seeds and not none_state(ledger.get("emergency_technique_seeds_none_state")): raise BuildError("EMERGENCY_SEED_EMPTY_REQUIRES_NONE_STATE")
    seed_ids=set()
    for i,s in enumerate(seeds):
        sid=text(s.get("seed_id"),f"seed[{i}].seed_id")
        if sid in seed_ids: raise BuildError(f"DUPLICATE_EMERGENCY_SEED:{sid}")
        seed_ids.add(sid); text(s.get("allocation_id"),f"seed.{sid}.allocation_id"); text(s.get("name"),f"seed[{i}].name"); text(s.get("exact_expression"),f"seed[{i}].exact_expression")
        component_spheres=arr(s.get("component_spheres"),f"seed.{sid}.component_spheres")
        for sphere in component_spheres:
            if sphere not in sphere_names and sphere not in sphere_ids: raise BuildError(f"SEED_UNKNOWN_SPHERE:{sid}:{sphere}")
        created=s.get("created_at_cl")
        if not isinstance(created,int) or not 1<=created<=cl: raise BuildError(f"SEED_CL_INVALID:{sid}:{created}")
        text(s.get("event"),f"seed.{sid}.event"); text(s.get("later_study_benefit"),f"seed.{sid}.later_study_benefit")
        if not isinstance(s.get("converted_to_learned"),bool): raise BuildError(f"SEED_CONVERSION_BOOLEAN_REQUIRED:{sid}")
        if s.get("converted_to_learned") and s.get("learned_forged_id") not in {x.get("forged_id") for x in forged}: raise BuildError(f"SEED_LEARNED_LINK_UNRESOLVED:{sid}")

    immortal_arts=arr(ledger.get("immortal_arts",[]),"immortal_arts")
    if not immortal_arts and not none_state(ledger.get("immortal_arts_none_state")):
        raise BuildError("IMMORTAL_ART_EMPTY_REQUIRES_NONE_STATE")
    immortal_ids=set()
    for i,art in enumerate(immortal_arts):
        art=obj(art,f"immortal_arts[{i}]"); iid=text(art.get("immortal_art_id"),f"immortal_arts[{i}].immortal_art_id")
        if iid in immortal_ids: raise BuildError(f"DUPLICATE_IMMORTAL_ART_ID:{iid}")
        immortal_ids.add(iid)
        for field in ("name","dao_aspect","status","evolution_state"): text(art.get(field),f"immortal_art.{iid}.{field}")
        text(art.get("allocation_id"),f"immortal_art.{iid}.allocation_id")
        if not isinstance(art.get("gained_at_cl"),int) or not 1<=art["gained_at_cl"]<=cl: raise BuildError(f"IMMORTAL_ART_GAIN_CL_INVALID:{iid}")
        aids=arr(art.get("action_ids"),f"immortal_art.{iid}.action_ids")
        if not aids: raise BuildError(f"IMMORTAL_ART_ACTION_REQUIRED:{iid}")
        for aid in aids:
            if aid not in action_ids: raise BuildError(f"IMMORTAL_ART_ACTION_UNRESOLVED:{iid}:{aid}")
            ia_action=next(a for a in actions if a["action_id"]==aid)
            if ia_action.get("classification")!="immortal_art": raise BuildError(f"IMMORTAL_ART_ACTION_CLASSIFICATION_INVALID:{iid}:{aid}:{ia_action.get('classification')}")
            if ia_action.get("immortal_art_id")!=iid: raise BuildError(f"IMMORTAL_ART_ACTION_PARENT_LINK_MISMATCH:{iid}:{aid}:{ia_action.get('immortal_art_id')}")
        if not arr(art.get("limitations"),f"immortal_art.{iid}.limitations"): raise BuildError(f"IMMORTAL_ART_LIMITATIONS_REQUIRED:{iid}")
        if not arr(art.get("behavior_hooks"),f"immortal_art.{iid}.behavior_hooks"): raise BuildError(f"IMMORTAL_ART_BEHAVIOR_HOOKS_REQUIRED:{iid}")
        text(art.get("execution_summary"),f"immortal_art.{iid}.execution_summary")
        text(art.get("acquisition_record"),f"immortal_art.{iid}.acquisition_record")
        ensure_packet_refs([art],packets,f"immortal_art.{iid}")
        require_canonical_authority(art,packets,f"immortal_art.{iid}",build_mode)

    # Event-sourced acquisition reconciliation. Every permanent character grant
    # must resolve to exactly one allocation event at the level it was gained.
    grant_registry={}
    def register_grant(grant_type:str, grant_id:str, name:str, gained_at_cl:int, allocation_id:str, row:dict[str,Any], expected_channel:str):
        key=(grant_type,grant_id)
        if key in grant_registry: raise BuildError(f"DUPLICATE_GRANT_REGISTRY:{grant_type}:{grant_id}")
        grant_registry[key]={"name":name,"gained_at_cl":gained_at_cl,"allocation_id":allocation_id,"row":row,"expected_channel":expected_channel}
    register_grant("background",background["background_id"],background["name"],1,background["allocation_id"],background,"background")
    register_grant("origin_insight",origin["origin_insight_id"],origin["name"],1,origin["allocation_id"],origin,"origin")
    for row in spheres: register_grant("sphere",row["sphere_id"],row["name"],row["gained_at_cl"],row["allocation_id"],row,row["acquisition_type"])
    for row in talents: register_grant("talent",row["talent_id"],row["name"],row["gained_at_cl"],row["allocation_id"],row,row["acquisition_type"])
    for row in features: register_grant("feature",row["feature_id"],row["name"],row["gained_at_cl"],row["allocation_id"],row,"feature")
    if not none_state(method): register_grant("method",method["method_id"],method["name"],method["gained_at_cl"],method["allocation_id"],method,"method")
    if not none_state(foundation): register_grant("foundation",foundation["foundation_id"],foundation["name"],foundation["gained_at_cl"],foundation["allocation_id"],foundation,"foundation")
    for row in equipment: register_grant("equipment",row["equipment_id"],row["name"],row["gained_at_cl"],row["allocation_id"],row,"equipment")
    # Item Book R1 instances are event-sourced permanent grants distinct from legacy equipment rows.
    equipment_r2=obj(ledger.get("equipment_ledger_r2",{}),"equipment_ledger_r2")
    item_cov_by_instance={r.get("instance_id"):r for r in arr(obj(ledger.get("item_execution_coverage",{}),"item_execution_coverage").get("items",[]),"item_execution_coverage.items") if isinstance(r,dict)}
    item_catalog_rows={r.get("item_id"):r for r in load(Path(__file__).resolve().parents[1]/"09_RULES"/"Items"/"ItemCatalog_R2.json").get("items",[])} if equipment_r2.get("item_instances") else {}
    for inst in arr(equipment_r2.get("item_instances",[]),"equipment_ledger_r2.item_instances"):
        iid=text(inst.get("instance_id"),"item_instance.instance_id");cov=item_cov_by_instance.get(iid)
        if not cov: raise BuildError(f"ITEM_COVERAGE_ROW_MISSING:{iid}")
        definition=inst.get("definition_snapshot") or item_catalog_rows.get(inst.get("item_id")) or {}
        iname=text(definition.get("name"),f"item_instance.{iid}.name")
        register_grant("item",iid,iname,cov.get("gained_at_cl"),cov.get("allocation_id"),cov,"item")
    for row in training_sources: register_grant("training_source",row["source_id"],row["name"],row["gained_at_cl"],row["allocation_id"],row,"training_source")
    for row in manuals: register_grant("recorded_art",row["manual_technique_id"],row["technique_name"],row["gained_at_cl"],row["allocation_id"],row,"manual")
    for row in forged: register_grant("forged_technique",row["forged_id"],row["name"],row["cl_learned"],row["allocation_id"],row,"forged")
    for row in seeds: register_grant("emergency_seed",row["seed_id"],row["name"],row["created_at_cl"],row["allocation_id"],row,"emergency_seed")
    for row in immortal_arts: register_grant("immortal_art",row["immortal_art_id"],row["name"],row["gained_at_cl"],row["allocation_id"],row,"immortal_art")

    known_grant_ids={grant_id for (_grant_type,grant_id) in grant_registry}
    for resource in resources:
        for grant_id in resource.get("source_grant_ids",[]):
            if grant_id not in known_grant_ids: raise BuildError(f"RESOURCE_SOURCE_GRANT_UNRESOLVED:{resource['resource_id']}:{grant_id}")
    for block_name in ("ac_generation","speed_generation","initiative_generation"):
        for grant_id in arr(stats.get(block_name,{}).get("source_grant_ids",[]),f"core_stats.{block_name}.source_grant_ids"):
            if grant_id not in known_grant_ids: raise BuildError(f"SCALAR_SOURCE_GRANT_UNRESOLVED:{block_name}:{grant_id}")
    base_equipment_id=stats.get("ac_generation",{}).get("base_source_equipment_id")
    if base_equipment_id:
        equipment_by_id={row["equipment_id"]:row for row in equipment}
        source_equipment=equipment_by_id.get(base_equipment_id)
        if not source_equipment: raise BuildError(f"AC_BASE_EQUIPMENT_UNRESOLVED:{base_equipment_id}")
        if source_equipment.get("equipped") is False: raise BuildError(f"AC_BASE_EQUIPMENT_NOT_EQUIPPED:{base_equipment_id}")
        if source_equipment.get("ac_contribution")!=stats["ac_generation"]["base_ac"]: raise BuildError(f"AC_BASE_EQUIPMENT_VALUE_MISMATCH:{base_equipment_id}")

    seen_grants=set()
    for allocation_id,a in allocation_index.items():
        key=(a["grant_type"],a["grant_id"])
        if a["grant_type"]=="event": continue
        if key not in grant_registry: raise BuildError(f"ALLOCATION_GRANT_UNRESOLVED:{allocation_id}:{a['grant_type']}:{a['grant_id']}")
        if key in seen_grants: raise BuildError(f"GRANT_ALLOCATED_MORE_THAN_ONCE:{a['grant_type']}:{a['grant_id']}")
        seen_grants.add(key)
        g=grant_registry[key]
        if g["allocation_id"]!=allocation_id: raise BuildError(f"GRANT_ALLOCATION_ID_MISMATCH:{a['grant_id']}:{g['allocation_id']}!={allocation_id}")
        if g["gained_at_cl"]!=a["cl"]: raise BuildError(f"GRANT_LEVEL_MISMATCH:{a['grant_id']}:{g['gained_at_cl']}!={a['cl']}")
        if g["name"]!=a["name"]: raise BuildError(f"GRANT_NAME_MISMATCH:{a['grant_id']}:{g['name']}!={a['name']}")
        if g["expected_channel"]!=a["channel"]: raise BuildError(f"GRANT_CHANNEL_MISMATCH:{a['grant_id']}:{g['expected_channel']}!={a['channel']}")
        if not (set(packet_refs(g["row"])) & set(packet_refs(a))): raise BuildError(f"GRANT_ALLOCATION_SOURCE_MISMATCH:{a['grant_id']}")
    missing=[f"{gt}:{gid}" for (gt,gid),g in grant_registry.items() if (gt,gid) not in seen_grants]
    if missing: raise BuildError(f"UNALLOCATED_CHARACTER_GRANTS:{','.join(sorted(missing))}")

    sphere_by_id={x["sphere_id"]:x for x in spheres}; sphere_by_name={x["name"]:x for x in spheres}
    talent_by_id={x["talent_id"]:x for x in talents}
    manual_by_id={x["manual_technique_id"]:x for x in manuals}
    known_sphere_ids:set[str]=set()
    known_talent_ids:set[str]=set()
    for rcl in range(1,cl+1):
        rows=allocations_by_cl[rcl]
        free=[x for x in rows if x["channel"]=="free_level" and x["grant_type"]=="talent"]
        if len(free)!=1: raise BuildError(f"FREE_LEVEL_TALENT_COUNT_INVALID:CL{rcl}:{len(free)}")
        talent=talent_by_id.get(free[0]["grant_id"])
        if not talent: raise BuildError(f"FREE_LEVEL_TALENT_UNRESOLVED:CL{rcl}")
        sphere=sphere_by_name.get(talent["sphere"])
        if not sphere: raise BuildError(f"FREE_LEVEL_TALENT_SPHERE_UNRESOLVED:CL{rcl}:{talent['sphere']}")
        if rcl==1:
            level1=[x for x in rows if x["channel"]=="level_1_sphere"]
            if len(level1)!=1: raise BuildError(f"LEVEL_1_SPHERE_COUNT_INVALID:{len(level1)}")
            entry=level1[0]
            if entry["grant_type"]=="sphere":
                level1_sphere_id=entry["grant_id"]
            elif entry["grant_type"]=="event":
                level1_sphere_id=text(entry.get("overlap_sphere_id"),"level_1_sphere.overlap_sphere_id")
                text(entry.get("overlap_note"),"level_1_sphere.overlap_note")
                if entry.get("contribution_talent_id")!=free[0]["grant_id"]: raise BuildError("CL1_OVERLAP_CONTRIBUTION_TALENT_MISMATCH")
            else:
                raise BuildError(f"LEVEL_1_SPHERE_GRANT_TYPE_INVALID:{entry['grant_type']}")
            if level1_sphere_id!=sphere["sphere_id"]: raise BuildError("CL1_LEVEL_TALENT_NOT_FROM_LEVEL_1_SPHERE")
        elif sphere["gained_at_cl"]>=rcl:
            raise BuildError(f"FREE_LEVEL_TALENT_SPHERE_NOT_PREVIOUSLY_KNOWN:CL{rcl}:{sphere['sphere_id']}")
        for a in [x for x in rows if x["channel"]=="new_sphere"]:
            new_sphere=sphere_by_id.get(a["grant_id"])
            if not new_sphere: raise BuildError(f"NEW_SPHERE_ALLOCATION_UNRESOLVED:CL{rcl}:{a['grant_id']}")
            bonuses=[x for x in rows if x["channel"]=="new_sphere_bonus" and x["grant_type"]=="talent" and talent_by_id.get(x["grant_id"],{}).get("sphere")==new_sphere["name"]]
            if len(bonuses)!=1: raise BuildError(f"NEW_SPHERE_BONUS_TALENT_COUNT_INVALID:CL{rcl}:{new_sphere['sphere_id']}:{len(bonuses)}")
        # Q01: the CL1 free Sphere grants its first talent like any newly
        # gained Sphere, separately from the CL1 level talent.
        level1_bonus_spheres={
            sphere_by_id.get(x["grant_id"] if x["grant_type"]=="sphere" else x.get("overlap_sphere_id"),{}).get("name")
            for x in rows if x["channel"]=="level_1_sphere"
        }
        level1_bonus_count=0
        for bonus in [x for x in rows if x["channel"]=="new_sphere_bonus" and x["grant_type"]=="talent"]:
            talent=talent_by_id.get(bonus["grant_id"],{})
            matching=[x for x in rows if x["channel"]=="new_sphere" and x["grant_type"]=="sphere" and sphere_by_id.get(x["grant_id"],{}).get("name")==talent.get("sphere")]
            if len(matching)==1: continue
            if not matching and talent.get("sphere") in level1_bonus_spheres:
                level1_bonus_count+=1
                continue
            raise BuildError(f"ORPHAN_NEW_SPHERE_BONUS_TALENT:CL{rcl}:{bonus['grant_id']}")
        if level1_bonus_count>1: raise BuildError(f"LEVEL_1_SPHERE_BONUS_TALENT_COUNT_INVALID:CL{rcl}:{level1_bonus_count}")
        for trained in [x for x in rows if x["channel"]=="trained_choice" and x["grant_type"]=="talent"]:
            talent=talent_by_id.get(trained["grant_id"],{})
            sphere=sphere_by_name.get(talent.get("sphere"))
            if not sphere or sphere["gained_at_cl"]>rcl: raise BuildError(f"TRAINED_TALENT_SPHERE_NOT_KNOWN:CL{rcl}:{trained['grant_id']}")

        # Validate the actual training history in allocation order.  This is
        # intentionally separate from free grants, which require no check.
        prior_manual_count_this_cl=0
        for a in rows:
            channel=a["channel"]
            if channel=="new_sphere":
                prior_count=len(known_sphere_ids)
                record=obj(a.get("training_record"),f"allocation.{a['allocation_id']}.training_record")
                d4=record.get("dc_d4_roll")
                if not isinstance(d4,int) or not 1<=d4<=4: raise BuildError(f"NEW_SPHERE_DC_D4_INVALID:{a['allocation_id']}:{d4}")
                if record.get("prior_different_spheres_known")!=prior_count: raise BuildError(f"NEW_SPHERE_PRIOR_COUNT_MISMATCH:{a['allocation_id']}:{record.get('prior_different_spheres_known')}!={prior_count}")
                validate_training_record(record,label=f"allocation.{a['allocation_id']}.training_record",kind="new_sphere",current_pb=pb_for_cl(rcl),ability_modifiers=(timeline.get(rcl) or {}).get("mods",mods),expected_dc=10+d4+prior_count)
            elif channel=="trained_choice" and a["grant_type"]=="talent":
                talent_row=talent_by_id[a["grant_id"]]
                prior_talent_count=sum(1 for tid in known_talent_ids if talent_by_id[tid]["sphere"]==talent_row["sphere"])
                record=obj(a.get("training_record"),f"allocation.{a['allocation_id']}.training_record")
                if record.get("prior_talents_known_in_sphere")!=prior_talent_count: raise BuildError(f"KNOWN_SPHERE_TALENT_PRIOR_COUNT_MISMATCH:{a['allocation_id']}:{record.get('prior_talents_known_in_sphere')}!={prior_talent_count}")
                validate_training_record(record,label=f"allocation.{a['allocation_id']}.training_record",kind="known_sphere_talent",current_pb=pb_for_cl(rcl),ability_modifiers=(timeline.get(rcl) or {}).get("mods",mods),expected_dc=10+prior_talent_count)
            elif channel=="manual" and a["grant_type"]=="recorded_art":
                manual_row=manual_by_id.get(a["grant_id"])
                if not manual_row: raise BuildError(f"RECORDED_ART_ALLOCATION_UNRESOLVED:CL{rcl}:{a['grant_id']}")
                record=obj(a.get("training_record"),f"allocation.{a['allocation_id']}.training_record")
                if record.get("manual_difficulty")!=manual_row["manual_difficulty"]: raise BuildError(f"RECORDED_ART_DIFFICULTY_MISMATCH:{a['allocation_id']}")
                if record.get("prior_recorded_arts_learned_this_cl")!=prior_manual_count_this_cl: raise BuildError(f"RECORDED_ART_PRIOR_COUNT_MISMATCH:{a['allocation_id']}")
                expected_manual_dc=10+manual_row["manual_difficulty"]+2*prior_manual_count_this_cl
                validate_training_record(record,label=f"allocation.{a['allocation_id']}.training_record",kind="recorded_art",current_pb=pb_for_cl(rcl),ability_modifiers=(timeline.get(rcl) or {}).get("mods",mods),expected_dc=expected_manual_dc)
                if manual_row.get("training_dc")!=expected_manual_dc: raise BuildError(f"RECORDED_ART_TRAINING_DC_MISMATCH:{a['grant_id']}:{manual_row.get('training_dc')}!={expected_manual_dc}")
                prior_manual_count_this_cl+=1
            if a["grant_type"]=="sphere": known_sphere_ids.add(a["grant_id"])
            elif a["grant_type"]=="talent": known_talent_ids.add(a["grant_id"])

        # RAW-078: no Sphere-count cap; three trained choices per CL bound growth.
    if background["grant_mode"]=="sphere_and_talent":
        cl1=allocations_by_cl[1]
        bgs=[x for x in cl1 if x["channel"]=="background_sphere" and x["grant_type"]=="sphere"]
        bgt=[x for x in cl1 if x["channel"]=="background_talent" and x["grant_type"]=="talent"]
        if len(bgs)!=1 or sphere_by_id[bgs[0]["grant_id"]]["name"]!=background["background_sphere"]: raise BuildError("BACKGROUND_SPHERE_ALLOCATION_MISMATCH")
        if len(bgt)!=1 or talent_by_id[bgt[0]["grant_id"]]["name"]!=background["background_talent"]: raise BuildError("BACKGROUND_TALENT_ALLOCATION_MISMATCH")
        bg_sphere=sphere_by_id[bgs[0]["grant_id"]]; bg_talent=talent_by_id[bgt[0]["grant_id"]]
        if bg_talent["sphere"]!=bg_sphere["name"]: raise BuildError("BACKGROUND_TALENT_NOT_FROM_BACKGROUND_SPHERE")
        level1=[x for x in cl1 if x["channel"]=="level_1_sphere"]
        if len(level1)!=1: raise BuildError(f"LEVEL_1_SPHERE_COUNT_INVALID:{len(level1)}")
        entry=level1[0]
        if entry["grant_type"]=="event":
            if entry.get("overlap_sphere_id")!=bgs[0]["grant_id"]: raise BuildError("CL1_OVERLAP_BACKGROUND_SPHERE_MISMATCH")
            if entry.get("overlap_background_sphere_allocation_id")!=bgs[0]["allocation_id"]: raise BuildError("CL1_OVERLAP_BACKGROUND_ALLOCATION_MISMATCH")
            free=[x for x in cl1 if x["channel"]=="free_level" and x["grant_type"]=="talent"]
            if len(free)!=1 or entry.get("contribution_talent_id")!=free[0]["grant_id"]: raise BuildError("CL1_OVERLAP_FREE_TALENT_MISMATCH")
            if free[0]["grant_id"]==bgt[0]["grant_id"]: raise BuildError("CL1_OVERLAP_DUPLICATE_TALENT")
        elif entry["grant_type"]=="sphere" and entry["grant_id"]==bgs[0]["grant_id"]:
            raise BuildError("CL1_OVERLAP_MUST_USE_RECONCILIATION_EVENT")
    # Final resource and event-sourced state must agree with the visible block.
    if levels[-1]["resource"]["max_after_level"]!=stats["primary_resource_max"]: raise BuildError("FINAL_RESOURCE_DOES_NOT_MATCH_LEVEL_LEDGER")

    deviations=arr(ledger.get("blueprint_deviations",[]),"blueprint_deviations")
    deviation_fields=set()
    for i,row in enumerate(deviations):
        row=obj(row,f"blueprint_deviations[{i}]")
        field=text(row.get("field"),f"blueprint_deviations[{i}].field")
        if field in deviation_fields: raise BuildError(f"BLUEPRINT_DEVIATION_DUPLICATE_FIELD:{field}")
        deviation_fields.add(field)
        text(row.get("reason"),f"blueprint_deviations[{i}].reason")
        if row.get("approved") is not True: raise BuildError(f"BLUEPRINT_DEVIATION_NOT_APPROVED:{field}")

    dao_i_ching=obj(ledger.get("dao_i_ching"),"dao_i_ching"); dao=obj(dao_i_ching.get("dao"),"dao_i_ching.dao"); iching=obj(dao_i_ching.get("i_ching"),"dao_i_ching.i_ching")
    for f in ("dao_phrase","combat_doctrine","resource_policy","reaction_policy","ai_turn_prompt"):
        text(dao.get(f),f"dao.{f}")
    for f in ("preferred_engagements","avoidance_rules","risk_thresholds","target_selection_logic","failure_recovery","forbidden_behaviors"):
        arr(dao.get(f),f"dao.{f}")
    if not isinstance(iching.get("enabled"),bool): raise BuildError("I_CHING_ENABLED_BOOLEAN_REQUIRED")
    for f in ("reading_name","hexagram_or_trigram","natural_tendency","testing_tendency","combat_state_interpretation","low_resource_shift","gm_generation_instruction"):
        text(iching.get(f),f"i_ching.{f}")
    arr(iching.get("shift_triggers"),"i_ching.shift_triggers")

    behavior=obj(ledger.get("ai_behavior"),"ai_behavior")
    text(behavior.get("profile_id"),"ai_behavior.profile_id"); text(behavior.get("retreat_policy"),"ai_behavior.retreat_policy")
    for aid in arr(behavior.get("action_refs"),"ai_behavior.action_refs"):
        if aid not in action_ids: raise BuildError(f"AI_BEHAVIOR_ACTION_UNRESOLVED:{aid}")
    if not arr(behavior.get("turn_procedure"),"ai_behavior.turn_procedure"): raise BuildError("AI_BEHAVIOR_TURN_PROCEDURE_EMPTY")
    coverage_mod=universal_coverage_module()
    coverage_issues=coverage_mod.validate_ledger(ledger,"complete")
    if coverage_issues: raise BuildError(coverage_issues[0])
    item_issues=item_integration_module().validate_ledger(ledger,"complete")
    if item_issues: raise BuildError(item_issues[0])
    assert_clean(ledger)
    return {"cl":cl,"pb":pb,"action_ids":sorted(action_ids),"meaningful_count":len(meaningful)}

def action_surface(a:dict[str,Any])->dict[str,Any]:
    return {
      **a,
      "display_name":a["name"], "economy":a["bucket"],
      "roll_or_save":a["roll_save_check"], "success_effect":a["effect"],
      "failure_or_limit":a["failure"],
      "display_card":{
        "action_id":a["action_id"],"action_name":a["name"],"economy":a["bucket"],
        "timing":a["timing"],"cost":a["cost"],"range":a["range"],"target":a["target"],
        "roll_save_check":a["roll_save_check"],"success_effect":a["effect"],"failure_limit":a["failure"],
        "duration":a["duration"],"limit":a["limit"],"counterplay":a["counterplay"]
      }
    }

def level_row(r:dict[str,Any], cultivation_insights:list[dict[str,Any]]|None=None)->dict[str,Any]:
    by={}
    for a in r.get("allocations",[]): by.setdefault(a["channel"],[]).append(a)
    names=lambda ch:[x.get("name") or x.get("selection_name") or x.get("allocation_id") for x in by.get(ch,[])]
    trained_cost=sum(a.get("slot_cost",0) for a in r.get("allocations",[]))
    background_grants=names("background")+names("background_sphere")+names("background_talent")
    advancement_events=[]
    advancement_choices=[]
    for event in by.get("event",[]):
        adjustments=parse_ability_adjustments(event.get("ability_score_adjustments") if isinstance(event.get("ability_score_adjustments"),dict) else event.get("name"))
        adjustments={ability:amount for ability,amount in adjustments.items() if amount}
        row={
          "allocation_id":event.get("allocation_id"),"grant_id":event.get("grant_id"),"name":event.get("name"),
          "event_type":"ability_score_improvement" if adjustments else "advancement_event",
          "ability_score_adjustments":adjustments,"source_packet_ids":event.get("source_packet_ids",[])
        }
        advancement_events.append(row)
        if adjustments or re.search(r"ability score|cultivation insight|\bASI\b",str(event.get("name","")),re.I): advancement_choices.append(row)
    for insight in cultivation_insights or []:
        if insight.get("gained_at_cl")!=r.get("cl"): continue
        channel=str(insight.get("acquisition_channel","")).lower()
        if "level" not in channel: continue
        row={
          "allocation_id":insight.get("allocation_id"),"grant_id":insight.get("insight_id") or insight.get("canonical_insight_id"),
          "name":insight.get("name"),"event_type":"cultivation_insight","ability_score_adjustments":insight.get("ability_score_adjustments",{}),
          "source_packet_ids":insight.get("source_packet_ids",[])
        }
        if not any(x.get("grant_id")==row.get("grant_id") for x in advancement_choices): advancement_choices.append(row)
    return {
      "cl":r["cl"],"CL":r["cl"],"realm":r["realm"],"pb":r["pb"],"PB":r["pb"],
      "hp_gain":r["hp"].get("base_gain",0)+r["hp"].get("constitution_delta",0)+r["hp"].get("other_delta",0),"hp_total":r["hp"]["max_after_level"],"max_hp_after_level":r["hp"]["max_after_level"],
      "resource_max_after_level":r["resource"]["max_after_level"],
      "background_grants":background_grants,"background_sphere":"; ".join(names("background_sphere")),"background_talent":"; ".join(names("background_talent")),
      "level_1_sphere":"; ".join(names("level_1_sphere")),"origin_insight":"; ".join(names("origin")),
      "free_level_talent":"; ".join(names("free_level")),"new_spheres_gained":names("new_sphere"),
      "new_sphere_bonus_talents":names("new_sphere_bonus"),"trained_choices":names("new_sphere")+names("trained_choice"),
      "trained_choices_used":trained_cost,"trained_choice_limit":3,
      "path_features":names("feature"),"equipment_gained":names("equipment"),
      "method_event":"; ".join(names("method")),"foundation_event":"; ".join(names("foundation")),
      "advancement_events":advancement_events,"advancement_choices":advancement_choices,
      "asi_or_insight_choice":"; ".join(str(x.get("name") or x.get("grant_id") or "") for x in advancement_choices if x.get("name") or x.get("grant_id")),
      "training_sources":names("training_source"),"manuals_or_recorded_arts":names("manual"),"forged_techniques":names("forged"),"emergency_technique_seeds":names("emergency_seed"),
      "validation_notes":["sealed state checkpoint",r["state_after_hash"]]
    }

def compact_forged(f:dict[str,Any])->dict[str,Any]:
    e=f["execution"]
    return {**f,"name":f["name"],"timing":e["timing"],"cost":e["cost"],"range":e["range"],"target":e["target"],"roll_save_check":e["roll_save_check"],"effect":e["effect"],"failure":e["failure"],"duration":e["duration"],"limit":e["limit"],"counterplay":e["counterplay"],"complexity":f["final_complexity"],"cp_cost":f["final_cp_cost"]}

def source_label(row:dict[str,Any], prefix:str="Rules packet") -> str:
    refs=[str(x) for x in row.get("source_packet_ids",[]) if str(x).strip()]
    cl=row.get("gained_at_cl", row.get("gained_at_CL"))
    parts=[]
    if isinstance(cl,int): parts.append(f"CL {cl}")
    if refs: parts.append(f"{prefix}{'s' if len(refs)>1 else ''}: {', '.join(refs)}")
    return " · ".join(parts) or "Character Master Ledger"

def method_surfaces(method:dict[str,Any], stats:dict[str,Any]) -> tuple[dict[str,Any],dict[str,Any]]:
    if none_state(method): return method, method
    mechanical=list(method.get("benefits",[]))+list(method.get("mechanical_hooks",[]))
    resource_object={
      "name":method["resource_name"], "formula":method["resource_formula"],
      "effect":f"Sets and governs the character's {method['resource_name']} progression; secondary counters remain separate unless explicitly stated.",
      "applied_to":method["resource_name"], "final_primary_resource_max":stats["primary_resource_max"]
    }
    common={**method,"method_name":method["name"],"status":"Active primary method","source":"Character_Master_Ledger.json / " + source_label(method),
            "mechanical_effects":mechanical,"applied_math":method["applied_math"],
            "stacking_statement":method.get("stacking_statement"),"resource_modifiers":method.get("resource_modifiers",[]),
            "breakthrough_shape":method["breakthrough_shape"],"foundation_compatibility":method["foundation_compatibility"],
            "incompatibilities":method["incompatibilities"]}
    file_surface={**common,"resource_shape":resource_object,"foundation_shape":{"foundation_compatibility":method["foundation_compatibility"]},"active_method":method,"primary_method":True}
    model_surface={**common,"resource_shape":f"{method['resource_name']} · {method['resource_formula']}"}
    return file_surface, model_surface

def foundation_surface(foundation:dict[str,Any]) -> dict[str,Any]:
    if none_state(foundation): return foundation
    r=foundation["foundation_resource"]
    counter=f"{r['name']} {r['current']}/{r['max']} · {r['generation']}"
    lifecycle=foundation.get("lifecycle_coverage",{})
    return {**foundation,"status_stage":foundation["stage"],"source":"Character_Master_Ledger.json / " + source_label(foundation),
            "passive_chassis":foundation["benefits"],"stage_benefit_map":foundation.get("stage_benefit_map",{}),
            "primary_resource_modifiers":foundation.get("primary_resource_modifiers",[]),"resources_counters":[counter],
            "actions_riders":foundation.get("actions",[]),"fixed_scope":foundation["fixed_scope"],
            "lifecycle_coverage":lifecycle,"burdens_strains_deviations":foundation.get("burdens",[]),
            "suppressed_or_excluded_benefits":foundation.get("suppressed_or_excluded_benefits",[]),"ai_notes":foundation["ai_notes"]}

def background_origin_surface(bo:dict[str,Any]) -> dict[str,Any]:
    b={**bo["background"],"source":"Character_Master_Ledger.json / " + source_label(bo["background"]),
       "skill_proficiencies":bo["background"].get("skill_proficiencies",[]),"tool_proficiencies":bo["background"].get("tool_proficiencies",[]),
       "languages":bo["background"].get("languages",[]),"equipment_reconciliation":bo["background"].get("equipment_reconciliation",{})}
    o={**bo["origin_insight"],"source":"Character_Master_Ledger.json / " + source_label(bo["origin_insight"]),
       "effect_records":bo["origin_insight"].get("effect_records",[]),
       "counts_against_background":False,"counts_against_level_talent":False,"counts_against_trained_choices":False}
    return {"background":b,"origin_insight":o}

def semantic_validator_module():
    path=Path(__file__).resolve().parents[1]/"06_VALIDATORS"/"validate_semantic_requirements.py"
    spec=importlib.util.spec_from_file_location("hf05zvk_r1f_semantic",path)
    if not spec or not spec.loader: raise BuildError(f"SEMANTIC_VALIDATOR_IMPORT_FAILED:{path}")
    mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

def compile_surfaces(L:dict[str,Any], packet_registry:dict[str,Any], semantic_report:dict[str,Any])->dict[str,Any]:
    c=L["character"]; s=L["core_stats"]; levels=[level_row(x,L.get("cultivation_insights",[])) for x in L["advancement"]["levels"]]
    actions=[action_surface(x) for x in L["actions"]]
    action_map={a["action_id"]:a for a in actions}
    compiled_states=[]
    for state in L.get("states",[]):
        producers=sorted(a.get("action_id") for a in actions if state.get("state_id") in arr(a.get("creates_states",[]),"compile_state_producers"))
        compiled_states.append({**state,"created_by_ids":producers})
    training_sources=[{**x,"source":source_label(x)} for x in L.get("training_sources",[])]
    manuals=[]
    preserved=[]
    for m in L.get("recorded_arts",[]):
        e=m["execution"]
        manuals.append({**m,"name":m["technique_name"],"source_spheres":m.get("source_spheres",[]),"source_talents":m.get("source_talents",[]),"linked_action":m.get("linked_action_id"),"linked_action_detail":action_map[m["linked_action_id"]],"training_dc":m["training_dc"],"source":source_label(m),**e})
        if m.get("preserved_forged_expression"):
            pfx=m["preserved_forged_expression"]
            preserved.append({**pfx,"allocation_id":m["allocation_id"],"recorded_art_name":m["technique_name"],"manual_name":m["manual_name"],"source":source_label(pfx),**pfx["execution"]})
    forged=[compact_forged(x) for x in L.get("forged_techniques",[])]
    immortal_arts=[]
    for art in L.get("immortal_arts",[]):
        details=[action_map[aid] for aid in art.get("action_ids",[]) if aid in action_map]
        immortal_arts.append({**art,"linked_action_details":details,"execution_cards":[a.get("display_card",a) for a in details],"action_count":len(details)})
    none=L.get("forged_techniques_none_state") or {"status":"none_acquired","reason":"No learned Forged Techniques were selected for this character."}
    bo=background_origin_surface(L["background_origin"])
    method_file,method_model=method_surfaces(L["method"],s)
    foundation=foundation_surface(L["foundation"])
    dao=L["dao_i_ching"]
    dao_file={**dao,**dao.get("dao",{}),"source":"Character_Master_Ledger.json"}
    coverage_mod=universal_coverage_module()
    sphere_projection=coverage_mod.project_legacy(L,"sphere")
    talent_projection=coverage_mod.project_legacy(L,"talent")
    sphere_coverage={x["source_id"]:x for x in sphere_projection}
    talent_coverage={x["source_id"]:x for x in talent_projection}
    spheres=[{**x,"display_name":x["name"],"source":source_label(x),"execution_coverage":sphere_coverage.get(x["sphere_id"],{})} for x in L["spheres"]]
    talents=[{**x,"display_name":x["name"],"talent_name":x["name"],"canonical_talent_name":x["name"],"effect":x["mechanical_summary"],
              "source":source_label(x),"source_type":x["acquisition_type"],"gained_at_CL":x["gained_at_cl"],"execution_coverage":talent_coverage.get(x["talent_id"],{})} for x in L["talents"]]
    identity={"character_id":c["character_id"],"display_name":c["name"],"name":c["name"],"title":c["title"],"concept_summary":c["concept"],"species":c.get("species","Human"),"path":c["path"],"realm":c["realm"],"CL":c["cl"],"PB":c["pb"],"key_ability":c["key_ability"]}
    ability_rows=[{"ability":ab,"score":s["ability_scores"][ab],"modifier":s["ability_modifiers"][ab],"save":s["saving_throws"][ab]} for ab in ABILITIES]
    skill_rows=[{"name":k,"bonus":v,"proficient":k in s.get("proficient_skills",[]),"source":s.get("skill_sources",{}).get(k,"")} for k,v in s.get("skills",{}).items()]
    core={"ac":{"current":s["ac_active"],"base":s.get("ac_base",s["ac_active"]),"math":s.get("ac_math",[])},"hp":{"current":s["hp_current"],"max":s["hp_max"],"formula":s.get("hp_formula","")},"speed_ft":s["speed_ft"],"initiative":s.get("initiative_bonus",0),"attack_bonus":s["technique_attack_bonus"],"save_dc":s["save_dc"],"primary_resource":{"name":s["primary_resource_name"],"current":s["primary_resource_current"],"max":s["primary_resource_max"],"formula":s.get("primary_resource_formula","")},"ability_scores":ability_rows,"skills":skill_rows,"senses":L.get("senses",[]),"defenses":L.get("defenses",{})}
    spheres_talents={"spheres":spheres,"talents":talents,"features":L.get("features",[])}
    equipment_r2=L.get("equipment_ledger_r2")
    item_exec=L.get("item_execution_coverage",{})
    item_cards=[]
    if isinstance(equipment_r2,dict):
        try:
            item_projection=load(Path(__file__).resolve().parents[1]/"09_RULES"/"Items"/"ItemGMProjection_R2.json")
            cards={x.get("item_id"):x for x in item_projection.get("items",[])}
            for inst in equipment_r2.get("item_instances",[]):
                card=dict(cards.get(inst.get("item_id"),{})); card["instance_id"]=inst.get("instance_id"); card["runtime_state"]={"attunement_state":inst.get("attunement_state"),"equipped_state":inst.get("equipped_state"),"runtime_charge_pools":inst.get("runtime_charge_pools"),"storage_contents":inst.get("storage_contents"),"item_spirit_state":inst.get("item_spirit_state"),"growth_state":inst.get("growth_state"),"durability":inst.get("durability")}
                item_cards.append(card)
        except Exception:
            item_cards=[]
    ers={"equipment":L.get("equipment",[]),"resources":L.get("resources",[]),"states":compiled_states,"equipment_ledger_r2":equipment_r2,"item_cards":item_cards,"item_execution_coverage":item_exec}
    diagnostics=[{"severity":"info","code":"HF05ZVK_CANONICAL_PROJECTION_COMPLETE","message":"All authoritative tabs were compiled from Character_Master_Ledger.json into consumer-ready shapes.","source":COMPILER_VERSION,"tab":"diagnostics"}]
    for sem_issue in semantic_report.get("issues",[]):
        diagnostics.append({"severity":"error" if sem_issue.get("severity") in {"critical","high"} else "warning","code":sem_issue.get("code"),"message":sem_issue.get("message"),"source":"Semantic_Validation_Report.json","tab":"diagnostics","semantic_severity":sem_issue.get("severity"),"source_id":sem_issue.get("source_id")})
    model={"schema":"Tianxia_GM_Character_View_Model_v2","schema_version":"Tianxia_GM_Character_View_Model_v2","patch":TARGET_PATCH,"producer_release":PRODUCER_RELEASE,"compiler_version":COMPILER_VERSION,"consumer_family":TARGET,"identity":identity,"core_stats":core,"leveling_ledger":levels,"background_origin":bo,"spheres_talents":spheres_talents ,"actions":actions,"forged_techniques":forged,"forged_techniques_none_state":none,"preserved_forged_expressions":preserved,"emergency_technique_seeds":L.get("emergency_technique_seeds",[]),"immortal_arts":immortal_arts,"immortal_arts_none_state":L.get("immortal_arts_none_state"),"training_sources":training_sources,"martial_manuals":manuals,"foundation":foundation,"method":method_model,"dao_i_ching":dao,"equipment_resources_states":ers,"diagnostics":diagnostics,"semantic_validation":semantic_report,"signature_loadout":semantic_report.get("signature_loadout",L.get("signature_loadout",L.get("semantic_contract",{}).get("signature_loadout",[]))),"validation":{"verdict":"PASS_HF05ZVK_R1F_COMPILED_MODEL" if semantic_report.get("release_ready") else "FAIL_HF05ZVK_R1F_SEMANTIC_VALIDATION","error_count":sum(1 for x in diagnostics if x.get("severity")=="error"),"warning_count":sum(1 for x in diagnostics if x.get("severity")=="warning")}}
    import_surface={"schema_version":SCHEMA,"producer_release":PRODUCER_RELEASE,"compiler_version":COMPILER_VERSION,"gm_screen_family":TARGET,"gm_screen_target":TARGET_PATCH,"character":{**identity,"cl":c["cl"],"pb":c["pb"]},"name":c["name"],"path":c["path"],"realm":c["realm"],"CL":c["cl"],"PB":c["pb"],"ac_active":s["ac_active"],"hp_current":s["hp_current"],"hp_max":s["hp_max"],"technique_attack_bonus":s["technique_attack_bonus"],"save_dc":s["save_dc"],"pb":c["pb"],"speed_ft":s["speed_ft"],"primary_resource_name":s["primary_resource_name"],"primary_resource_current":s["primary_resource_current"],"primary_resource_max":s["primary_resource_max"],"ability_scores":s["ability_scores"],"ability_modifiers":s["ability_modifiers"],"saving_throws":s["saving_throws"],"skills":s.get("skills",{}),"background":bo["background"],"origin_insight":bo["origin_insight"],"spheres":spheres,"talents":talents,"features":L.get("features",[]) ,"actions":actions,"martial_manuals":manuals,"forged_techniques":forged,"forged_techniques_none_state":none,"preserved_forged_expressions":preserved,"emergency_technique_seeds":L.get("emergency_technique_seeds",[]),"immortal_arts":immortal_arts,"immortal_arts_none_state":L.get("immortal_arts_none_state"),"training_sources":training_sources,"method":method_model,"active_method":method_model,"active_primary_method":method_model,"foundation":foundation,"dao_i_ching":dao,"equipment":L.get("equipment",[]),"resources":L.get("resources",[]),"states":compiled_states,"leveling_ledger_rows":levels,"semantic_validation":semantic_report,"signature_loadout":semantic_report.get("signature_loadout",L.get("signature_loadout",L.get("semantic_contract",{}).get("signature_loadout",[])))}
    rows=[]
    for x in spheres: rows.append({"row_kind":"sphere","id":x["sphere_id"],"name":x["name"],"source":x["source"]})
    for x in talents: rows.append({"row_kind":"talent","id":x["talent_id"],"name":x["name"],"sphere":x["sphere"],"effect":x["mechanical_summary"],"source":x["source"]})
    for x in actions: rows.append({"row_kind":"action",**x})
    for x in training_sources: rows.append({"row_kind":"training_source",**x})
    for x in manuals: rows.append({"row_kind":"recorded_art",**x})
    for x in forged: rows.append({"row_kind":"forged_technique",**x})
    for x in preserved: rows.append({"row_kind":"preserved_forged_expression",**x})
    for x in L.get("emergency_technique_seeds",[]): rows.append({"row_kind":"emergency_technique_seed",**x})
    for x in immortal_arts: rows.append({"row_kind":"immortal_art",**x})
    tabs=[("overview-core-stats","Overview / Core Stats"),("leveling-ledger","Leveling Ledger"),("background-origin","Background & Origin"),("paths-subpaths","Paths & Subpaths"),("spheres-talents","Spheres & Talents"),("insights","Insights"),("actions","Actions"),("forged-techniques","Forged Techniques"),("martial-manuals-recorded-arts","Martial Manuals / Recorded Arts"),("immortal-arts","Immortal Arts"),("foundation","Foundation"),("method","Method"),("companions-spirits","Companions, Spirits & Beasts"),("equipment","Equipment"),("resources-states-suppression","Resources, States & Suppression"),("dao-i-ching","Dao & I Ching"),("diagnostics","Diagnostics")]
    manifest={"schema_version":SCHEMA,"producer_release":PRODUCER_RELEASE,"compiler_version":COMPILER_VERSION,"consumer_family":TARGET,"target":TARGET_PATCH,"required_tabs":[{"tab_id":x,"label":y,"always_visible":True} for x,y in tabs],"expected_counts":{"level_rows":len(levels),"spheres":len(spheres),"talents":len(talents),"actions":len(actions),"training_sources":len(training_sources),"recorded_arts":len(manuals),"forged_techniques":len(forged),"preserved_forged_expressions":len(preserved),"emergency_technique_seeds":len(L.get("emergency_technique_seeds",[])),"immortal_arts":len(immortal_arts),"equipment":len(L.get("equipment",[])),"states":len(compiled_states),"companions":len(L.get("companions",[])),"path_feature_groups":len(L.get("feature_coverage_manifest",{}).get("path_feature_coverage",[])),"subpath_feature_groups":len(L.get("feature_coverage_manifest",{}).get("subpath_feature_coverage",[])),"insight_coverage":len(L.get("feature_coverage_manifest",{}).get("insight_coverage",[])),"item_instances":len((L.get("equipment_ledger_r2") or {}).get("item_instances",[])),"item_coverage":len((L.get("item_execution_coverage") or {}).get("items",[]))},"source_of_truth":"Character_Master_Ledger.json"}
    source_map={
      "overview-core-stats":["Character_Import_Surface.json","Canonical_Stats_Resource_Block.json"],"leveling-ledger":["Leveling_Ledger.json"],
      "background-origin":["Background_Origin_Ledger.json","Origin_Insight_Ledger.json"],"paths-subpaths":["Path_Feature_Coverage.json","Subpath_Feature_Coverage.json","Feature_Coverage_Manifest.json","Character_Master_Ledger.json"],"spheres-talents":["Selected_Spheres.json","Talent_Source_Ledger.json"],"insights":["Insight_Execution_Coverage.json","Selected_Rule_Execution_Coverage.json","Character_Master_Ledger.json"],
      "actions":["Complete_Action_Surface.json"],"forged-techniques":["Forged_Techniques.json","Preserved_Forged_Expressions.json","Emergency_Technique_Seeds.json"],
      "martial-manuals-recorded-arts":["Manual_Lineage_Record.json","Martial_Arts_and_Manuals.json"],"immortal-arts":["Immortal_Arts.json"],"foundation":["Foundation_Detail_Ledger.json"],"method":["Cultivation_Method_Profile.json"],"companions-spirits":["Companion_Execution_Coverage.json","Complete_Action_Surface.json","Character_Master_Ledger.json"],"equipment":["Equipment_Ledger.json","Equipment_Ledger_Legacy.json","Item_Execution_Coverage.json","Selected_Item_GM_Projection.json"],"resources-states-suppression":["Character_Import_Surface.json","State_Effect_Registry.json","Source_CL_and_Realm_Suppression.json","Modifier_Ledger.json","Procedure_Ledger.json","Passive_Statistic_Ledger.json","Permission_Record_Ledger.json"],
      "dao-i-ching":["Dao_IChing_Combat_Profile.json","AI_Combat_Behavior_Profile.json"],
      "diagnostics":["Selected_Rule_Execution_Coverage.json","Feature_Coverage_Manifest.json","Semantic_Validation_Report.json","Build_Reconciliation.json","GM_Screen_Tab_Expectation_Manifest.json","PACKAGE_MANIFEST.json"]}
    v1={"schema_version":"Tianxia_GM_Character_Model_v1","metadata":{"schema_version":SCHEMA,"factory":SCHEMA,"producer_release":PRODUCER_RELEASE,"compiler_version":COMPILER_VERSION,"consumer":TARGET,"consumer_patch":TARGET_PATCH},"identity":identity,"stats":import_surface,"background_origin":bo,"spheres_talents":spheres_talents ,"actions":actions,"forged_techniques":forged,"preserved_forged_expressions":preserved,"emergency_technique_seeds":L.get("emergency_technique_seeds",[]),"immortal_arts":immortal_arts,"immortal_arts_none_state":L.get("immortal_arts_none_state"),"training_sources":training_sources,"martial_manuals":manuals,"foundation":foundation,"method":method_model,"dao_i_ching":dao,"equipment_resources_states":ers,"semantic_validation":semantic_report,"signature_loadout":semantic_report.get("signature_loadout",L.get("signature_loadout",L.get("semantic_contract",{}).get("signature_loadout",[])))}
    ai_generation_profile={
      "schema_version":SCHEMA,"character_id":c["character_id"],"build_mode":L.get("build_mode"),"path":c["path"],
      "ability_generation":s.get("ability_generation"),"primary_resource":{"name":s["primary_resource_name"],"formula":s.get("primary_resource_formula"),"max":s["primary_resource_max"]},
      "background_grants":bo["background"],"cl1_free_sphere_and_talent":{
        "sphere_allocations":[a for a in L["advancement"]["levels"][0]["allocations"] if a.get("channel")=="level_1_sphere"],
        "talent_allocations":[a for a in L["advancement"]["levels"][0]["allocations"] if a.get("channel")=="free_level"]},
      "sphere_acquisition_ledger":spheres,"talent_source_ledger":talents,"manual_lineage_sources":training_sources,
      "trained_choice_ledger":[{"cl":row["cl"],**a} for row in L["advancement"]["levels"] for a in row["allocations"] if a.get("slot_cost")==1],
      "level_talent_ledger":[{"cl":row["cl"],**a} for row in L["advancement"]["levels"] for a in row["allocations"] if a.get("channel")=="free_level"],
      "sphere_diversity_by_cl":[{"cl":row["cl"],"known_spheres":sum(1 for x in spheres if x["gained_at_cl"]<=row["cl"]),"default_max":SPHERE_DIVERSITY_DEFAULT[row["cl"]],"exceptional_max":SPHERE_DIVERSITY_EXCEPTIONAL[row["cl"]],"override":row.get("sphere_diversity_override")} for row in L["advancement"]["levels"]],
      "method_boundary":method_model,"foundation_boundary":foundation,"forged_technique_count":len(forged),"forged_technique_limit":c["pb"],
      "gm_screen_executable_buckets":sorted(BUCKETS),"source_of_truth":"Character_Master_Ledger.json"}
    return {
      "Character_Master_Ledger.json":L,"Rules_Selection_Packets.json":packet_registry,"Semantic_Validation_Report.json":semantic_report,"Signature_Loadout.json":{"schema":"HF05ZVK-R1F.SignatureLoadout.v1","character_id":c["character_id"],"actions":semantic_report.get("signature_loadout",L.get("signature_loadout",L.get("semantic_contract",{}).get("signature_loadout",[])))},"Tianxia_GM_Character_Model_v1.json":v1,"Tianxia_GM_Character_View_Model_v2.json":model,
      "Character_Import_Surface.json":import_surface,"Normalized_Sheet.json":import_surface,"Canonical_Stats_Resource_Block.json":s,"Leveling_Ledger.json":{"schema_version":SCHEMA,"level_rows":levels,"levels":levels},
      "Background_Origin_Ledger.json":bo,"Origin_Insight_Ledger.json":bo["origin_insight"],"Cultivation_Method_Profile.json":method_file,"Foundation_Detail_Ledger.json":foundation,
      "Dao_IChing_Combat_Profile.json":dao_file,"Selected_Spheres.json":{"spheres":spheres,"execution_coverage":sphere_projection},"Talent_Source_Ledger.json":{"talents":talents,"execution_coverage":talent_projection},
      "Sphere_Execution_Coverage.json":{"schema_version":SCHEMA,"coverage":sphere_projection,"generated_from":"Selected_Rule_Execution_Coverage.json"},"Talent_Execution_Coverage.json":{"schema_version":SCHEMA,"coverage":talent_projection,"generated_from":"Selected_Rule_Execution_Coverage.json"},"Selected_Rule_Execution_Coverage.json":{"schema_version":SCHEMA,"coverage_version":L.get("execution_coverage_version"),"coverage":L.get("selected_rule_execution_coverage",[])},"Feature_Coverage_Manifest.json":L.get("feature_coverage_manifest",{}),"Path_Feature_Coverage.json":{"schema_version":SCHEMA,"coverage":L.get("feature_coverage_manifest",{}).get("path_feature_coverage",[])},"Subpath_Feature_Coverage.json":{"schema_version":SCHEMA,"coverage":L.get("feature_coverage_manifest",{}).get("subpath_feature_coverage",[])},"Insight_Execution_Coverage.json":{"schema_version":SCHEMA,"coverage":L.get("feature_coverage_manifest",{}).get("insight_coverage",[])},"Companion_Execution_Coverage.json":{"schema_version":SCHEMA,"companion_sheet_version":L.get("companion_sheet_version","HF05ZVK-R1F.CompanionSheet.P2F.v1"),"coverage":L.get("feature_coverage_manifest",{}).get("companion_coverage",[]),"companions":L.get("companions",[])},"Source_CL_and_Realm_Suppression.json":L.get("source_cl_realm_suppression_export",{}),"Modifier_Ledger.json":{"modifiers":L.get("modifiers",[])},"Procedure_Ledger.json":{"procedures":L.get("procedures",[])},"Passive_Statistic_Ledger.json":{"passive_statistics":L.get("passive_statistics",[])},"Permission_Record_Ledger.json":{"permission_records":L.get("permission_records",[])},"Equipment_Ledger.json":L.get("equipment_ledger_r2",{"schema_version":"Tianxia_Equipment_Ledger_v2_1","record_type":"equipment_ledger","character_id":c["character_id"],"catalog_version":"tianxia.item_catalog.final_audit_r1","item_instances":[],"derived_equipment_summary":{"attunement_slots_used":0,"attunement_slots_max":4,"equipped_weapon_instance_ids":[],"equipped_armor_instance_id":None,"equipped_shield_instance_id":None,"active_item_action_ids":[],"active_item_reaction_ids":[],"ac_contributions":[],"attack_contributions":[],"speed_contributions":[],"active_set_resonances":[]},"validation":{"verdict":"PASS_EMPTY_EQUIPMENT_LEDGER","errors":[],"warnings":[]},"source_map":{}}),"Equipment_Ledger_Legacy.json":{"equipment":L.get("equipment",[])},"Item_Execution_Coverage.json":L.get("item_execution_coverage",{"schema_version":"HF05ZVK-R1F.ItemExecutionCoverage.P2E.v1","character_id":c["character_id"],"catalog_version":"tianxia.item_catalog.final_audit_r1","items":[]}),"Selected_Item_GM_Projection.json":{"schema_version":"Tianxia_Item_GMScreen_Selected_Projection_P2E","items":item_cards},
      "State_Effect_Registry.json":{"states":compiled_states},"Complete_Action_Surface.json":{"schema_version":SCHEMA,"actions":actions},
      "Manual_Lineage_Record.json":{"schema_version":SCHEMA,"training_sources":training_sources},
      "Martial_Arts_and_Manuals.json":{"schema_version":SCHEMA,"training_sources":training_sources,"recorded_arts":manuals,"manuals":manuals,"preserved_forged_expressions":preserved,"none_state":L.get("recorded_arts_none_state")},
      "Forged_Techniques.json":{"schema_version":SCHEMA,"forged_techniques":forged,"learned_forged_techniques":forged,"preserved_forged_expressions":preserved,"none_state":none},
      "Preserved_Forged_Expressions.json":{"schema_version":SCHEMA,"preserved_forged_expressions":preserved},
      "Emergency_Technique_Seeds.json":{"schema_version":SCHEMA,"emergency_technique_seeds":L.get("emergency_technique_seeds",[]),"none_state":L.get("emergency_technique_seeds_none_state")},
      "Immortal_Arts.json":{"schema_version":SCHEMA,"immortal_arts":immortal_arts,"none_state":L.get("immortal_arts_none_state")},
      "AI_Character_Generation_Profile.json":ai_generation_profile,"AI_Combat_Behavior_Profile.json":L["ai_behavior"],"GM_Screen_Display_Rows.json":{"schema_version":SCHEMA,"rows":rows},
      "GM_Screen_Projection_Rows.json":{"schema_version":SCHEMA,"rows":rows,"source":"HF05ZVK deterministic compiler"},"GM_Screen_Tab_Expectation_Manifest.json":manifest,
      "GM_Screen_Source_Map_Expectation.json":{"source_of_truth":"Character_Master_Ledger.json","producer_release":PRODUCER_RELEASE,"consumer":TARGET,"consumer_patch":TARGET_PATCH,"tab_sources":source_map},
      "Build_Reconciliation.json":{"schema_version":SCHEMA,"status":"COMMAND_5_GM_SCREEN_CANDIDATE_READY","counts":manifest["expected_counts"],"action_ids":[a["action_id"] for a in actions],
         "rules_packet_ids":sorted(p["packet_id"] for p in packet_registry.get("packets",[])),"all_derived_from_master_ledger":True,"manual_derived_file_edits_allowed":False,
         "semantic_validation":{"verdict":semantic_report.get("verdict"),"release_ready":semantic_report.get("release_ready"),"ledger_sha256":semantic_report.get("ledger_sha256"),"counts":semantic_report.get("counts")},"projection_contract":{"method":"consumer-ready-stacking-preserved","foundation":"full-lifecycle-consumer-ready","background_origin":"complete-grant-and-effect-records","talent_execution":"complete-action-modifier-passive-routing","dao_i_ching":"nested-and-flat-compatible","level_rows":"full CL1-current","immortal_arts":"embedded-executable-action-packets-or-explicit-none-state","items":"Item Book R1 R2 Equipment Ledger plus universal execution coverage; legacy projection retained separately"}}
    }

def write_build(out:Path, surfaces:dict[str,Any]):
    if out.exists(): shutil.rmtree(out)
    out.mkdir(parents=True)
    for name,data in surfaces.items(): dump(out/name,data)
    files=[]
    for p in sorted(out.iterdir()):
        if p.is_file(): files.append({"path":p.name,"sha256":hfile(p),"bytes":p.stat().st_size})
    dump(out/"PACKAGE_MANIFEST.json",{"schema_version":SCHEMA,"producer_release":PRODUCER_RELEASE,"compiler_version":COMPILER_VERSION,"consumer":TARGET,"consumer_patch":TARGET_PATCH,"files":files})
    lines=[f"{hfile(p)}  {p.name}" for p in sorted(out.iterdir()) if p.is_file() and p.name!="SHA256SUMS.txt"]
    (out/"SHA256SUMS.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")

def main(argv=None)->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--ledger",type=Path,required=True); ap.add_argument("--rules-packets",type=Path,required=True); ap.add_argument("--corpus","--needed",dest="corpus",type=Path,required=True); ap.add_argument("--output",type=Path,required=True); ap.add_argument("--path-authority",type=Path)
    a=ap.parse_args(argv)
    try:
        ledger=load(a.ledger); registry=load(a.rules_packets); packets=verify_packets(registry,a.corpus); summary=validate_ledger(ledger,packets,path_authority=a.path_authority)
        semantic=semantic_validator_module().run(ledger,registry)
        if not semantic.get("release_ready"):
            raise BuildError("SEMANTIC_VALIDATION_FAILED:"+json.dumps(semantic.get("counts",{}),sort_keys=True))
        surfaces=compile_surfaces(ledger,registry,semantic); write_build(a.output,surfaces)
        print(json.dumps({"verdict":"PASS_HF05ZVK_R1F_COMPILE","output":str(a.output),"summary":summary,"semantic":semantic,"files":len(surfaces)+2},indent=2)); return 0
    except BuildError as e:
        print(json.dumps({"verdict":"FAIL_HF05ZVK_R1F_COMPILE","blocker":str(e)},indent=2)); return 2
if __name__=="__main__": raise SystemExit(main())
