"""Value-only JSON edits for the Aspect wording migration."""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher

_TOKEN = re.compile(r'"(?:[^"\\]+|\\.)*"|[{}\[\]:,]|[^\s{}\[\]:,"]+')
_ESCAPE = re.compile(r'\\u[dD][89a-bA-B][0-9a-fA-F]{2}\\u[dD][c-fC-F][0-9a-fA-F]{2}|\\u[0-9a-fA-F]{4}|\\.|[^\\]', re.S)


def _edit_string(raw, before, after):
    """Preserve the original spelling of all equal spans, including escapes."""
    chars = list(_ESCAPE.finditer(raw, 1, len(raw) - 1))
    if len(chars) != len(before):
        raise ValueError(f"Cannot align escaped string: {raw[:80]!r}")
    offsets = [match.start() for match in chars] + [len(raw) - 1]
    ascii_escapes = bool(re.search(r'\\u[0-9a-fA-F]{4}', raw)) and raw.isascii()
    # Find a shared prefix/suffix first; avoid a quadratic comparison of long
    # repeated rule text when only a small part of a value changed.
    start = 0
    while start < min(len(before), len(after)) and before[start] == after[start]:
        start += 1
    end = 0
    while end < min(len(before), len(after)) - start and before[-1-end] == after[-1-end]:
        end += 1
    left, right = before[start:len(before)-end], after[start:len(after)-end]
    out = [raw[:offsets[start]]]
    for tag, a, b, c, d in SequenceMatcher(None, left, right).get_opcodes():
        if tag == "equal":
            out.append(raw[offsets[start+a]:offsets[start+b]])
        else:
            out.append(json.dumps(right[c:d], ensure_ascii=ascii_escapes)[1:-1])
    return "".join(out) + raw[offsets[len(before)-end]:]


def json_values(source, transform):
    """Call transform(value, tuple_of_keys_and_indexes, offset) on JSON(L) strings.

    The lexical traversal never serializes a container or edits a key. Each
    document is processed independently, including consecutive JSONL records.
    """
    tokens = iter(_TOKEN.finditer(source))
    cursor = 0
    pieces = []

    def walk(token, path):
        nonlocal cursor
        value = token[0]
        if value == "{":
            for key in tokens:
                if key[0] == "}":
                    return
                if key[0] == ",":
                    continue
                if next(tokens)[0] != ":":
                    raise ValueError(f"Missing JSON field separator at offset {key.end()}")
                walk(next(tokens), (*path, json.loads(key[0])))
        elif value == "[":
            index = 0
            for item in tokens:
                if item[0] == "]":
                    return
                if item[0] != ",":
                    walk(item, (*path, index))
                    index += 1
        elif value.startswith('"'):
            old = json.loads(value)
            new = transform(old, path, token.start())
            if new != old:
                pieces.extend((source[cursor:token.start()], _edit_string(value, old, new)))
                cursor = token.end()

    for token in tokens:
        walk(token, ())
    return "".join(pieces) + source[cursor:]
