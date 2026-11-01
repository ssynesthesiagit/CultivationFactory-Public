#!/usr/bin/env python3
"""Rebuild the single Method/Foundation descriptor from accepted source inputs.

This is a release-authoring operation, not a runtime trust-on-first-use path.
Review descriptor + generated release_trust.py together. The original base
corpus and compiler trust identities remain fixed; source/registry/member/
record/projection commitments are derived, never copied into consumers.
Foundation registry source locators are regenerated from the accepted book;
its gameplay fields are not rewritten.
"""
from __future__ import annotations

from hashlib import sha256
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from character_creation import release_descriptor as releases


def rebuild_descriptor(app_root, template, base):
    data = json.loads(json.dumps(template))
    trust = releases.TrustRoot(Path(app_root), Path(app_root) / "release.json", "")
    for key in ("methods", "foundations"):
        row = data["releases"][key]
        raw = releases.relative_path(app_root, row["source_path"]).read_bytes()
        row["source_sha256"] = sha256(raw).hexdigest()
        registry_path = releases.relative_path(app_root, row["registry_path"])
        if key == "foundations":
            registry = json.loads(registry_path.read_bytes())
            text = raw.decode()
            headings = list(re.finditer(r"^# (\d+)\. (.+)$", text, re.M))
            if len(headings) != 62 or len(registry["orthodox"]) != 30:
                raise releases.invalid("The complete playable Foundation source inventory changed.", kind=key)
            changed = False
            for number, record in enumerate(registry["orthodox"], 1):
                heading, following = headings[number - 1:number + 1]
                if heading.group(1) != str(number) or heading.group(2) != record["display_name"]:
                    raise releases.invalid("A Foundation heading does not match its stable record.", kind=key)
                section = (text[heading.start():following.start()].rstrip() + "\n").encode()
                source = {**record["source"], "artifact_sha256": row["source_sha256"],
                          "section_sha256": sha256(section).hexdigest(), "section_number": number}
                changed |= source != record["source"]
                record["source"] = source
            if changed:
                registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n")
        row["registry_sha256"] = sha256(registry_path.read_bytes()).hexdigest()
    descriptor = releases.Descriptor(trust, releases.freeze(data))
    sources = {k: releases.verified_sources(descriptor.release(k)) for k in ("methods", "foundations")}
    if sha256(base).hexdigest() != data["releases"]["base"]["corpus_sha256"]:
        raise releases.invalid("The release builder requires the authenticated base corpus.")
    payload = base
    for key in ("base", "methods", "foundations"):
        descriptor = releases.Descriptor(trust, releases.freeze(data))
        release = descriptor.release(key)
        if key != "base":
            payload = releases.derive_corpus_bytes(release, payload)
        row = data["releases"][key]
        row["corpus_sha256"] = sha256(payload).hexdigest()
        release = releases.Descriptor(trust, releases.freeze(data)).release(key)
        projected = releases.project(release, payload,
            list(releases.thaw(sources["methods"]["records"]).values()),
            list(releases.thaw(sources["foundations"]["records"]).values()))
        row["manifest_sha256"] = projected["source_authority"]["manifest_sha256"]
        row["active_source_index_sha256"] = projected["source_authority"]["active_source_index_sha256"]
        row["projection"] = projected["projection"]
        row["members"] = {name: sha256(value).hexdigest() for name, value in releases.zip_members(payload).items()}
        if key != "base":
            row["records"] = releases.record_commitments(sources[key]["records"])
    return data


def write_descriptor(path, data, trust_module):
    encoded = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()
    Path(path).write_bytes(encoded)
    digest = sha256(encoded).hexdigest()
    Path(trust_module).write_text(
        '"""Generated descriptor commitment; rebuild with tools/build_method_foundation_release.py."""\n'
        + f'DESCRIPTOR_SHA256 = "{digest}"\n')
    return digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--base-corpus", type=Path, required=True)
    args = parser.parse_args()
    path = args.app_root / "character_creation/method_foundation_release.json"
    template = json.loads(path.read_bytes())
    data = rebuild_descriptor(args.app_root, template, args.base_corpus.read_bytes())
    digest = write_descriptor(path, data, path.with_name("release_trust.py"))
    print(f"Method/Foundation descriptor rebuilt: {digest}")


if __name__ == "__main__":
    main()
