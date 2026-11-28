#!/usr/bin/env python3
"""Apply the final Bible terminology to tracked, unsealed Factory wording.

Run from any directory: apply_aspect_terms.py REPO --pairs changed_lines.txt.
The input is the certified abf7e98c398e -> c8981da6a877 line-pair file.
This pass leaves the archive and CAT1 file kinds for the authority round.
After regenerating typed authority, use --rebind-cards OLD_RULES_TEXT to carry
reviewed cards across the terminology-only change, then rebuild player text.
Code is changed only at reviewed literal anchors in apply_aspect_terms_roles.tsv.
Decisions must trace a display read; runtime values never follow wording by default.
A SHA-256 token in any tracked APP file pins the matching file's bytes, regardless of literal roles.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import csv
from copy import deepcopy
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import lru_cache
from hashlib import file_digest
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tokenize

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.aspect_term_values import json_values
from tools.aspect_terms import TERMS, _SPHERE, _is_shape, aspect_terms
from tools.rebind_aspect_bible import line_pairs, text_sha, write_reviews


_POLICY = Path(__file__).with_suffix(".json")
_CODE_ROLES = Path(__file__).with_name("apply_aspect_terms_roles.tsv")
_SHA256 = re.compile(rb"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", re.I)
_MARK = re.compile(r"^[ \t]*(?:(?:#{1,6}|[-+*]|\d+[.)])[ \t]+)?")
_TERM = re.compile(r"sphere|aspect|way of", re.I)
_ID_KEY = re.compile(r"(?:^|_)(?:id|ids|key|keys|sha256|hash|path|paths|filename|kind|tag|tags|enum|schema)(?:_|$)")
_CERTIFIED_WORDS = re.compile(r"[\w'-]+")
_ASPECT_NAMES = {
    name.casefold() for key in ("names", "aliases_other_spellings_to_short_name", "short_lists")
    for name in TERMS[key]
}
_ASPECT_LIST_HEADING = re.compile(r"legal (?:spheres?|aspects?):", re.I)
_MARKDOWN_BULLET = re.compile(r"^([ \t]*)[-+*][ \t]+")
_JSON_TEXT = frozenset({
    "sphere_name", "description", "full_description", "short_description", "one_line_description", "summary",
    "text", "tooltip", "title", "label", "display_name", "player_text", "source_markdown",
    "body", "why", "notes", "note", "full_exact_source_text", "rule_text", "rules_text", "effect_text",
    "printed_text", "published_text", "intro", "headline", "caption", "help", "message",
})
_JS_TAG = re.compile(r"<!--[\s\S]*?-->|<(?:[^>'\"]|\"[^\"]*\"|'[^']*')*>")
_HTML_LABEL = re.compile(r'''(\b(?:aria-label|title|placeholder|alt)\s*=\s*)(["'])(.*?)\2''', re.S)


def _track(root):
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    return [Path(item) for item in raw.decode().split("\0") if item]


def _pin_manifests(root, paths):
    """Index SHA-256 tokens across tracked APP files, including deferred or stale pin sources."""
    pins = defaultdict(list)
    for path in paths:
        name = path.relative_to(root).as_posix()
        if name.startswith("APP/"):
            for digest in {match.lower() for match in _SHA256.findall(path.read_bytes())}:
                pins[digest].append(name)
    return pins


def _pinned_files(paths, pins):
    if not pins:
        return {}
    pinned = {}
    for path in paths:
        with path.open("rb") as source:
            digest = file_digest(source, "sha256").hexdigest().encode("ascii")
        if digest in pins:
            pinned[path] = sorted(pins[digest])
    return pinned


def _split_line(value):
    line = value.rstrip("\r\n")
    return line, value[len(line):]


def _bare_aspect_name(line):
    return _MARK.sub("", line).strip(" \t*_`.;").casefold() in _ASPECT_NAMES


def _certified(path):
    variants = defaultdict(set)
    new_lines = set()
    for _, old, new in line_pairs(path):
        variants[old].add(new)
        new_lines.add(new)
        short_old, short_new = (_MARK.sub("", line) for line in (old, new))
        if short_old != short_new:
            variants[short_old].add(short_new)
            new_lines.add(short_new)
    # A short heading can be used in several senses. Do not select a
    # replacement arbitrarily or treat today's certified print as old text.
    ambiguous = {old: sorted(items) for old, items in variants.items() if len(items) != 1}
    return {
        old: next(iter(items)) for old, items in variants.items()
        if len(items) == 1 and old not in new_lines
    }, new_lines, ambiguous


class Wording:
    def __init__(self, pairs):
        self.pairs, self.new_lines, self.ambiguous = _certified(pairs)
        self.bare_pairs = {old for old in self.pairs if _bare_aspect_name(old)}
        self.counts = defaultdict(Counter)
        self.samples = defaultdict(list)
        self.residual_fragments = set()
        self.shape_uses = set()
        self._old_phrases = defaultdict(set)
        for line in self.pairs:
            words = [m[0].casefold() for m in _CERTIFIED_WORDS.finditer(line)]
            for i in range(len(words) - 7):
                self._old_phrases[tuple(words[i:i + 8])].add(line)
        self._bare_words = re.compile(
            r"(?<![\w./])(?:" + "|".join(re.escape(name) for name in
                sorted(TERMS["short_lists"], key=len, reverse=True)) + r")(?![\w/]|\.\w)",
        )

    def count(self, path, metric, where=None):
        self.counts[path][metric] += 1
        if where is not None and len(self.samples[metric]) < 20:
            self.samples[metric].append((path, where))

    @lru_cache(maxsize=8192)
    def rename(self, old, *, singleton=False, aspect_label=False):
        pieces = []
        pairs_found = 0
        legal_indent = None
        for part in old.splitlines(keepends=True):
            line, eol = _split_line(part)
            bullet = _MARKDOWN_BULLET.match(line)
            heading = _MARK.sub("", line).strip(" \t*")
            if _ASPECT_LIST_HEADING.fullmatch(heading):
                legal_indent = bullet.end() if bullet else 0
            elif not bullet or (legal_indent is not None and len(bullet[1]) < legal_indent):
                legal_indent = None
            in_aspect_context = aspect_label or (legal_indent is not None and bullet is not None)
            if line in self.pairs and (line not in self.bare_pairs or in_aspect_context):
                line = self.pairs[line]
                pairs_found += 1
            pieces.append(line + eol)
        exact = "".join(pieces)
        new = _wording(exact) if singleton or any(ch.isspace() for ch in exact) else exact
        return new, pairs_found

    def text(self, path, old, where, *, singleton=False, aspect_label=False, context=None):
        if not old:
            return old
        authored = old
        for previous, current in (context or {}).items():
            authored = authored.replace(previous, current)
        if authored != old:
            self.count(path, "old_sense_aspect_decisions", where)
        new, applied = self.rename(authored, singleton=singleton, aspect_label=aspect_label)
        if applied:
            self.count(path, "values_with_old_whole_line")
            self.counts[path]["whole_lines_replaced"] += applied
        if new != old:
            self.count(path, "values_changed")
            self.counts[path]["lines_changed"] += sum(
                left != right for left, right in zip(old.splitlines(), new.splitlines(), strict=True)
            )
        for line in new.splitlines():
            if line in self.new_lines:
                self.count(path, "new_whole_lines")
            if line in self.pairs:
                self.count(path, "remaining_old_whole_lines", where)
            if self._bare_words.search(line) and not _TERM.search(line) and line not in self.new_lines:
                self.count(path, "possible_bare_legacy_name_lines", where)
            for match in _SPHERE.finditer(line):
                if _is_shape(line, *match.span()):
                    self.count(path, "shape_terms_kept", where)
                    self.shape_uses.add((path, str(where), line))
            if new != old or line not in self.new_lines:
                words = [m[0].casefold() for m in _CERTIFIED_WORDS.finditer(line)]
                for i in range(len(words) - 7):
                    for pair in self._old_phrases.get(tuple(words[i:i+8]), ()):
                        if self.pairs[pair] not in new and pair not in new:
                            self.residual_fragments.add((path, str(where), pair))
        return new


@lru_cache(maxsize=8192)
def _wording(text):
    return aspect_terms(text)


def _patch(source, edits):
    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]
    return source


def _offsets(source):
    starts = [0, *(match.end() for match in re.finditer("\n", source))]
    return lambda pos: starts[pos[0] - 1] + pos[1]


@dataclass(frozen=True)
class CodeRole:
    # line is an audit coordinate in the pre-apply source. The exact anchor
    # and column locate the same literal even when a merge moves that line.
    line: int
    column: int
    anchor: str
    old: str
    new: str
    decision: str
    read: str


def _load_code_roles(path):
    by_file = defaultdict(list)
    with path.open(encoding="utf-8") as source:
        header = next(source).rstrip("\n").split("\t")
        for row in source:
            fields = dict(zip(header, row.rstrip("\n").split("\t"), strict=True))
            role = CodeRole(
                int(fields["line"]), int(fields["column"]), json.loads(fields["anchor"]),
                json.loads(fields["old"]), json.loads(fields["new"]), fields["decision"], fields["read"],
            )
            if role.decision not in {"keep", "change"} or not role.read:
                raise ValueError(f"Incomplete code wording decision: {fields['file']}:{role.line}")
            by_file[fields["file"]].append(role)
    return by_file


def _code_edits(source, roles):
    """Exact preimages only. Unreviewed and drifted literals are not renamed."""
    by_anchor = defaultdict(list)
    keep = {(row.anchor, row.column, row.old) for row in roles if row.decision == "keep"}
    for row in roles:
        if row.decision == "change":
            if (row.anchor, row.column, row.old) in keep:
                raise ValueError(f"Conflicting code wording decisions at line {row.line}")
            by_anchor[row.anchor].append(row)
    offset = 0
    edits = set()
    for line in source.split("\n"):
        for row in by_anchor.get(line.removesuffix("\r"), ()):
            start = offset + row.column
            if source.startswith(row.old, start):
                edits.add((start, start + len(row.old), row.new))
        offset += len(line) + 1
    return edits


def _python(source, roles):
    edits = _code_edits(source, roles)
    if not edits:
        return source

    # The AST proposes string positions, not permissions. E.g. a comparison
    # could be dispatch against a stored value, or a local display-name join.
    # Only the decision row knows whether its producer/reader changes with it.
    offset = _offsets(source)
    lines = source.split("\n")

    def pos(line, byte_col):
        return offset((line, len(lines[line - 1].encode()[:byte_col].decode())))

    literals = {
        (pos(node.lineno, node.col_offset), pos(node.end_lineno, node.end_col_offset))
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant) and isinstance(node.value, str))
    }
    candidates = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        token_kind = tokenize.tok_name[token.type]
        if token_kind not in {"COMMENT", "STRING", "FSTRING_MIDDLE"}:
            continue
        start, end = offset(token.start), offset(token.end)
        if token_kind == "COMMENT" or any(left <= start and end <= right for left, right in literals):
            candidates.add((start, end))
    result = _patch(source, [edit for edit in edits if edit[:2] in candidates])
    ast.parse(result)
    return result


def _javascript(source, roles):
    # The JavaScript decisions were traced by hand. No inferred roles.
    return _patch(source, _code_edits(source, roles))


def _html(source, transform, settings):
    singletons = settings.get("singletons", ())

    def label(value, start):
        return transform(value, source.count("\n", 0, start) + 1, singleton=value.strip() in singletons)

    parts, last = [], 0
    for tag in _JS_TAG.finditer(source):
        parts.append(label(source[last:tag.start()], last))
        parts.append(_HTML_LABEL.sub(lambda m: m[1] + m[2] + label(m[3], tag.start()) + m[2], tag[0]))
        last = tag.end()
    parts.append(label(source[last:], last))
    return "".join(parts)


def _csv(source, transform, settings):
    # Preserve dialect details by changing only the spans of actual cells.
    token = re.compile(r'''("(?:[^"]|"")*"|[^,\r\n]*)(,|\r\n|\n|\r|$)''')
    edits, headers = [], []
    column, row = 0, 1
    for match in token.finditer(source):
        cell, separator = match.groups()
        if not (cell or separator):
            continue
        value = next(csv.reader([cell]))[0] if cell else ""
        if row == 1:
            headers.append(value.casefold())
        elif column < len(headers) and not _ID_KEY.search(headers[column]):
            updated = transform(value, f"{row}:{headers[column]}")
            if updated != value:
                replacement = '"' + updated.replace('"', '""') + '"' if cell.startswith('"') or ',' in updated else updated
                edits.append((*match.span(1), replacement))
        column += 1
        if separator not in {",", ""}:
            row, column = row + 1, 0
    return _patch(source, edits)


def _json(source, transform, settings):
    def update(value, key, offset):
        field = next((part for part in reversed(key) if isinstance(part, str)), "")
        if _ID_KEY.search(field) or field not in _JSON_TEXT:
            return value
        if field in {"display_name", "sphere_name"} and settings.get("aspect_names"):
            value = TERMS["short_lists"].get(value, value)
        aspect_label = field == "sphere_name" or (field == "display_name" and settings.get("aspect_names"))
        return transform(value, ".".join(map(str, key)), aspect_label=bool(aspect_label))
    return json_values(source, update)


def _source_rows(raw=False):
    from tools import typed_mechanics_helpers as typed

    return {row["id"]: row for row in (typed._gather_sources() if raw else typed.sources())}


def _rebind_owner_edits(before_raw, after_raw, pinned):
    from factory_authoring.owner_text_edits import apply_edit
    from tools import typed_mechanics_helpers as typed

    path = typed.OWNER_TEXT_EDITS
    prepared, left = {}, []
    for key, edit in typed.owner_text_edits().items():
        if key not in before_raw or key not in after_raw:
            continue
        old, new = before_raw[key]["text"], after_raw[key]["text"]
        if old == new:
            continue
        if new != aspect_terms(old):
            left.append(key)
            continue
        candidate = deepcopy(edit)
        for pair in candidate.get("replace", ()):
            for field in ("old", "new"):
                pair[field] = aspect_terms(pair[field])
        if "remove" in candidate:
            candidate["remove"] = [aspect_terms(line) for line in candidate["remove"]]
        old_typing, old_edited, old_problems = apply_edit(old, edit)
        new_typing, new_edited, new_problems = apply_edit(new, candidate)
        if old_problems or new_problems or new_edited != aspect_terms(old_edited) or new_typing != aspect_terms(old_typing):
            left.append(key)
            continue
        if candidate.get("typing_carried_from_text_sha256") == text_sha(old_typing):
            candidate["typing_carried_from_text_sha256"] = text_sha(new_typing)
        if edit != candidate:
            prepared[key] = candidate

    if path in pinned:
        return [], sorted(set(left) | prepared.keys())

    _write_owner_edits(path, prepared)
    return sorted(prepared), sorted(left)


def _write_owner_edits(path, prepared):
    if not prepared:
        return

    def update(value, key, _offset):
        if len(key) >= 3 and key[0] == "records" and key[1] in prepared:
            result = prepared[key[1]]
            for piece in key[2:]:
                result = result[piece]
            return result
        return value

    source = path.read_bytes().decode("utf-8")
    updated = json_values(source, update)
    if updated != source:
        path.write_bytes(updated.encode("utf-8"))


def _rename_display_values(value):
    if isinstance(value, str):
        return aspect_terms(value)
    if isinstance(value, list):
        return [_rename_display_values(item) for item in value]
    if isinstance(value, dict):
        return {key: _rename_display_values(item) for key, item in value.items()}
    return value


def _prepare_card_rebinds(before_rules, after_rules, edits):
    """Carry a review only if both old bindings match and both texts retain their meaning."""
    from factory_authoring.player_rules import build_player_text, card_sha

    def clarified(key, rules, edit):
        return build_player_text({key: rules}, {key: edit})["records"][key]

    prepared = {}
    for key, edit in edits.items():
        if "player_card" not in edit:
            continue
        card = edit["player_card"]
        new = after_rules.get(key)
        if new is None:
            raise ValueError(f"{key}: reviewed card is missing its regenerated rules")
        if (card["rules_sha256"] == card_sha(new)
                and card["source_sha256"] == card_sha(clarified(key, new, edit))):
            continue

        old = before_rules.get(key)
        if old is None or card["rules_sha256"] != card_sha(old):
            raise ValueError(f"{key}: reviewed card did not bind the previous rules")
        if new != aspect_terms(old):
            raise ValueError(f"{key}: printed rules changed beyond the Aspect terminology")
        old_clarified = clarified(key, old, edit)
        if card["source_sha256"] != card_sha(old_clarified):
            raise ValueError(f"{key}: reviewed card did not bind the previous clarified text")

        candidate = deepcopy(edit)
        for field in ("player_text", "player_replace"):
            if field in candidate:
                candidate[field] = _rename_display_values(candidate[field])
        new_clarified = clarified(key, new, candidate)
        if new_clarified != aspect_terms(old_clarified):
            raise ValueError(f"{key}: clarified text changed beyond the Aspect terminology")
        rebound = candidate["player_card"]
        for field in ("summary", "groups", "facts", "choice_names"):
            if field in rebound:
                rebound[field] = _rename_display_values(rebound[field])
        rebound["rules_sha256"] = card_sha(new)
        rebound["source_sha256"] = card_sha(new_clarified)
        prepared[key] = candidate
    return prepared


def _rebind_cards(root, old_rules, *, write):
    from tools import typed_mechanics_helpers as typed

    path = typed.OWNER_TEXT_EDITS

    def read_json(path):
        return json.loads(path.read_text(encoding="utf-8"))

    prepared = _prepare_card_rebinds(
        read_json(old_rules), read_json(path.with_name("rules_text.json")), typed.owner_text_edits(),
    )
    if prepared and write:
        tracked = (root / rel for rel in _track(root))
        pins = _pin_manifests(root, (file for file in tracked if not file.is_symlink() and file.is_file()))
        if pinned := _pinned_files((path,), pins):
            raise ValueError(f"{path.name} is pinned by {', '.join(pinned[path])}")
        _write_owner_edits(path, prepared)
    return {"cards_rebound": sorted(prepared)}


def _rebind(before, before_raw, pinned):
    from tools import typed_mechanics_helpers as typed

    owner_rebound, owner_left = _rebind_owner_edits(before_raw, _source_rows(raw=True), pinned)
    after = _source_rows()
    bindings, left = {}, []
    finals = typed.load_finals()
    for key, row in before.items():
        current = after.get(key)
        if not current or row.get("bible") or current.get("bible"):
            continue
        old = row.get("typing_text", row["text"])
        new = current.get("typing_text", current["text"])
        if old == new:
            continue
        if finals.get(key, {}).get("text_sha256") != text_sha(old):
            continue
        if new == aspect_terms(old):
            bindings[key] = text_sha(old), text_sha(new)
        else:
            left.append(key)
    kept = write_reviews(bindings, aspect_terms, pinned_paths=pinned) if bindings else set()
    return {
        "rebound": sorted(bindings.keys() - kept), "left": sorted(set(left) | kept),
        "owner_rebound": owner_rebound, "owner_left": owner_left,
    }


def _classify(path, policy):
    name = path.as_posix()
    for kind, patterns in policy["defer"].items():
        if any(fnmatchcase(name, pattern) for pattern in patterns):
            return kind
    return None


def apply(root, pairs, *, write):
    policy = json.loads(_POLICY.read_text(encoding="utf-8"))
    wording = Wording(pairs)
    code_roles = _load_code_roles(_CODE_ROLES)
    changes = defaultdict(Counter)
    deferred = defaultdict(list)
    pending = []
    root = root.resolve()
    tracked = _track(root)
    files = {
        path: root / path for path in tracked
        if not (root / path).is_symlink() and (root / path).is_file()
    }
    pins = _pin_manifests(root, files.values())
    pinned = _pinned_files(files.values(), pins)
    for path in tracked:
        file = files.get(path)
        if file in pinned:
            continue
        name = path.as_posix()
        if kind := _classify(path, policy):
            deferred[kind].append(name)
            continue
        suffix = path.suffix.casefold()
        if file is None or suffix not in {".py", ".js", ".mjs", ".cjs", ".html", ".json", ".jsonl", ".csv", ".md", ".txt"}:
            continue
        data = file.read_bytes()
        try:
            source = data.decode("utf-8")
        except UnicodeDecodeError:
            deferred["non-UTF-8"].append(name)
            continue
        settings = policy["options"].get(name, {})
        transform = lambda value, where, **kw: wording.text(name, value, where, context=settings.get("context"), **kw)
        if suffix in {".json", ".jsonl"}:
            # Treat accepted snapshots and standalone release registries as
            # opaque; their own input hash/commitment verifies their values.
            if re.search(r'"(?:record_hash|registry_commitment_sha256|seal_sha256|snapshot_sha256)"\s*:', source):
                deferred["committed data"].append(name)
                continue
            updated = _json(source, transform, settings)
        elif suffix == ".py":
            updated = _python(source, code_roles.get(name, ()))
        elif suffix in {".js", ".mjs", ".cjs"}:
            updated = _javascript(source, code_roles.get(name, ()))
        elif suffix == ".html":
            updated = _html(source, transform, settings)
        elif suffix == ".csv":
            updated = _csv(source, transform, settings)
        else:
            # Give the terminology function whole blocks (notably the legal
            # Aspect headings and bulleted choices) with their exact newlines.
            updated = transform(source, "document")
        if updated != source:
            changes[suffix]["files"] += 1
            if suffix in {".py", ".js", ".mjs", ".cjs"}:
                changes[suffix]["lines"] += sum(
                    old != new for old, new in zip(source.splitlines(), updated.splitlines(), strict=True)
                )
            else:
                changes[suffix]["lines"] += wording.counts[name]["lines_changed"]
            if write:
                pending.append((file, data, updated.encode("utf-8")))

    rebind = {"rebound": [], "left": [], "owner_rebound": [], "owner_left": []}
    if pending:
        from tools import typed_mechanics_helpers as typed
        from tools.rebind_aspect_bible import review_paths

        before = _source_rows()
        before_raw = _source_rows(raw=True)
        rebind_paths = (*review_paths(), typed.OWNER_TEXT_EDITS)
        pinned.update(_pinned_files((path for path in rebind_paths if path.relative_to(root) not in files), pins))
        rebind_inputs = {path: path.read_bytes() for path in rebind_paths if path not in pinned}
        try:
            for file, _old, updated in pending:
                file.write_bytes(updated)
            rebind = _rebind(before, before_raw, pinned)
        except Exception:
            for file, old, _updated in pending:
                file.write_bytes(old)
            for file, old in rebind_inputs.items():
                if file.read_bytes() != old:
                    file.write_bytes(old)
            raise
    return {
        "changes_by_kind": changes, "by_file": dict(wording.counts), "deferred": deferred,
        "kept_as_history": {path.relative_to(root).as_posix(): manifests for path, manifests in pinned.items()},
        "unambiguous_pairs": len(wording.pairs), "ambiguous_old_lines": wording.ambiguous,
        "samples": dict(wording.samples), "factory_rebind": rebind,
        "partial_old_line_matches": sorted(wording.residual_fragments),
        "shape_uses": sorted(wording.shape_uses),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pairs", type=Path)
    mode.add_argument("--rebind-cards", type=Path, metavar="OLD_RULES_TEXT")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if (root / "APP").resolve() != Path(__file__).resolve().parents[1]:
        parser.error("run the script from the same checkout it applies")
    if args.rebind_cards:
        try:
            report = _rebind_cards(root, args.rebind_cards, write=not args.dry_run)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        report = apply(root, args.pairs, write=not args.dry_run)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
