"""Public synthetic release fixtures: no original books, live stores or pin patches."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import zipfile

import pytest

from app.core import FoundryError
from character_creation import release_descriptor as releases
from tools.build_method_foundation_release import rebuild_descriptor, write_descriptor


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _issue(root, data):
    path = root / "release.json"
    digest = write_descriptor(path, data, root / "release_trust.py")
    trust = releases.TrustRoot(root, path, digest)
    return releases.load_descriptor(trust)


@pytest.fixture
def fixture_release(tmp_path):
    root = tmp_path / "application"
    root.mkdir()
    data = releases.thaw(releases.DESCRIPTOR.data)
    methods = [{"method_id": f"METHOD-{n:03}", "name": f"Method {n:03}",
                "explicit_ap_grants": [], "rule": f"Synthetic method rule {n}."}
               for n in range(1, 103)]
    foundations = [{"foundation_id": f"FOUNDATION_{n:02}", "display_name": f"Foundation {n}",
                    "catalog_number": n, "authority_class": "ORTHODOX", "selectable": True,
                    "tournament_legal": True, "stage": "Foundation Establishment",
                    "rule": f"Synthetic foundation rule {n}.", "source": {}}
                   for n in range(1, 31)]
    for key in ("methods", "foundations"):
        data["releases"][key]["source_path"] = f"sources/{key}.md"
        data["releases"][key]["registry_path"] = f"registry/{key}.json"
    (root / "sources").mkdir()
    method_text = "\n".join(f'## {r["method_id"]} — {r["name"]}\n\n```json\n{json.dumps(r)}\n```\n' for r in methods)
    (root / "sources/methods.md").write_text(method_text)
    (root / "sources/foundations.md").write_text(
        "\n".join(f"# {n}. Foundation {n}\n\nSynthetic section {n}.\n" for n in range(1, 63)))
    _write_json(root / "registry/methods.json", {"methods": methods})
    _write_json(root / "registry/foundations.json", {
        "schema": "Tianxia.FoundationCatalogRuntime.v0.4C", "orthodox": foundations,
        "theoretical_chakra": [{"foundation_id": f"CHAKRA_{n}"} for n in range(32)]})
    legacy = data["legacy_method_member"]
    foundation_member = "Synthetic/SOURCE_EXCERPT_Foundations.md"
    manifest = {"active_packet_sources": [legacy, foundation_member], "subject_authority": []}
    base = releases.write_corpus({
        data["manifest_member"]: json.dumps(manifest).encode(),
        legacy: "".join(f'## {n}. Method {n:03}\n' for n in range(1, 81)).encode(),
        foundation_member: "".join(f"# Foundation {n}\n" for n in range(1, 10)).encode(),
    })
    data["releases"]["base"]["corpus_sha256"] = sha256(base).hexdigest()
    data["compiler"]["corpus_sha256"] = sha256(base).hexdigest()
    base_path = root / "base.zip"
    base_path.write_bytes(base)
    descriptor = _issue(root, rebuild_descriptor(root, data, base))
    return root, base_path, descriptor


def _published(fixture_release, key="foundations"):
    root, base, descriptor = fixture_release
    spec = releases.select_release(key=key, descriptor=descriptor)
    path, view = releases.ensure_release(spec, root / "vendor", base)
    return path, view


@pytest.mark.parametrize("key,method_count,foundation_count", [
    ("base", 80, 9), ("methods", 102, 9), ("foundations", 102, 30),
])
def test_verified_view_preserves_complete_inventory_and_exact_source_bindings(fixture_release, key, method_count, foundation_count):
    path, view = _published(fixture_release, key)
    spec = view.release
    assert len(view.projected["method_choice"]["compiler_backed_ids"]) == method_count
    assert len(view.projected["foundation_choice"]["compiler_backed_ids"]) == foundation_count
    assert releases.thaw(view.projected["projection"]) == releases.thaw(spec.data["projection"])
    for slot in ("method_choice", "foundation_choice"):
        for row in view.projected[slot]["records"].values():
            if row["selectable"]:
                assert row["source_file_sha256"] == spec.data["members"][row["source_path"]]
                assert row["source_excerpt_sha256"] == sha256(row["source_text"].encode()).hexdigest()
    assert path.read_bytes() == view.corpus_bytes
    with pytest.raises(TypeError):
        view.projected["method_choice"]["records"]["METHOD-001"]["selectable"] = False
    with pytest.raises(FrozenInstanceError):
        view.corpus_bytes = b"forged"
    root, base, descriptor = fixture_release
    assert releases.select_release(schema=spec.data["schema"], corpus_sha256=spec.data["corpus_sha256"],
        corpus_path=path, vendor_dir=root / "vendor", base_corpus=base, descriptor=descriptor) == spec
    with pytest.raises(FoundryError):
        releases.select_release(schema=spec.data["schema"], corpus_sha256="0" * 64, descriptor=descriptor)


def test_one_section_edit_one_rebuild_no_handwritten_python_digest_edits(fixture_release):
    root, base, descriptor = fixture_release
    _, before = _published(fixture_release)
    python_before = (root / "release_trust.py").read_bytes()
    source = root / "sources/foundations.md"
    source.write_text(source.read_text().replace("Synthetic section 1.", "Changed synthetic section 1."))
    with pytest.raises(FoundryError):
        releases.verify_release(before.release, before.corpus_bytes)
    # ONE release-authoring operation regenerates registry source commitments,
    # descriptor and its out-of-band commitment; no Python literal is hand-edited.
    rebuilt = rebuild_descriptor(root, releases.thaw(descriptor.data), base.read_bytes())
    updated = _issue(root, rebuilt)
    _, after = _published((root, base, updated))
    assert (root / "release_trust.py").read_bytes() != python_before  # generated, not handwritten
    assert updated.release("methods").data == descriptor.release("methods").data
    assert updated.release("base").data == descriptor.release("base").data
    assert before.release.data["records"] == after.release.data["records"]
    prefix = before.release.data["member_prefix"]
    changed_sections = {p for p in before.members if p.startswith(prefix) and before.members[p] != after.members[p]}
    assert changed_sections == {prefix + "FOUNDATION_01.md"}
    for slot in ("method_choice", "foundation_choice"):
        for identity, old in before.projected[slot]["records"].items():
            new = after.record(slot, identity)
            # Every evidence row commits to the whole release corpus identity.
            # No unrelated excerpt, record binding, cost, rule or diagnostic changes.
            assert new["corpus_sha256"] != old["corpus_sha256"]
            for field in old:
                if field == "source_file_sha256" and slot == "foundation_choice" and identity == "FOUNDATION_01":
                    assert new[field] != old[field]
                elif field != "corpus_sha256":
                    assert new[field] == old[field], (identity, field)
    assert before.projected["method_choice"]["compiler_backed_ids"] == after.projected["method_choice"]["compiler_backed_ids"]
    assert before.projected["foundation_choice"]["compiler_backed_ids"] == after.projected["foundation_choice"]["compiler_backed_ids"]


@pytest.mark.parametrize("target", ["source", "registry", "parent", "member", "manifest", "descriptor"])
def test_bit_flips_are_rejected_without_overwriting_evidence(fixture_release, target):
    root, base, descriptor = fixture_release
    path, view = _published(fixture_release)
    if target in {"source", "registry", "parent", "descriptor"}:
        victim = {"source": root / "sources/foundations.md", "registry": root / "registry/foundations.json",
                  "parent": base, "descriptor": root / "release.json"}[target]
        victim.write_bytes(victim.read_bytes() + b"x")
        if target == "descriptor":
            with pytest.raises(FoundryError):
                releases.load_descriptor(descriptor.trust)
            return
    else:
        members = dict(view.members)
        member = (view.release.descriptor.data["manifest_member"] if target == "manifest"
                  else view.release.data["member_prefix"] + "FOUNDATION_01.md")
        members[member] += b"x"
        path.write_bytes(releases.write_corpus(members))
    evidence = path.read_bytes()
    with pytest.raises(FoundryError):
        releases.ensure_release(view.release, root / "vendor", base)
    assert path.read_bytes() == evidence


def test_self_consistent_unsigned_replacement_and_wrong_trust_root_fail(fixture_release, tmp_path):
    root, base, descriptor = fixture_release
    changed = root / "sources/foundations.md"
    changed.write_text(changed.read_text().replace("Synthetic section 1.", "Unsigned replacement."))
    forged = rebuild_descriptor(root, releases.thaw(descriptor.data), base.read_bytes())
    _write_json(root / "release.json", forged)
    with pytest.raises(FoundryError):
        releases.load_descriptor(descriptor.trust)
    foreign = tmp_path / "foreign.json"
    _write_json(foreign, {"format": 1, "releases": {}})
    with pytest.raises(FoundryError):
        releases.load_descriptor(releases.TrustRoot(root, foreign, descriptor.trust.descriptor_sha256))


@pytest.mark.parametrize("field", ["source_path", "registry_path", "source_member"])
@pytest.mark.parametrize("path", ["../escape", "/absolute", "safe/../../escape", "safe\\escape"])
def test_even_authenticated_descriptors_reject_traversal(fixture_release, field, path):
    root, _, descriptor = fixture_release
    bad = releases.thaw(descriptor.data)
    bad["releases"]["methods"][field] = path
    with pytest.raises(FoundryError):
        _issue(root, bad)


@pytest.mark.parametrize("target", ["source", "registry", "release", "parent", "directory"])
def test_symlinks_are_rejected_including_cached_release_inputs(fixture_release, tmp_path, target):
    root, base, descriptor = fixture_release
    path, view = _published(fixture_release)
    if target == "directory":
        directory = root / "sources"
        outside = tmp_path / "moved-sources"
        directory.rename(outside)
        directory.symlink_to(outside, target_is_directory=True)
    else:
        victim = {"source": root / "sources/foundations.md", "registry": root / "registry/foundations.json",
                  "release": path, "parent": base}[target]
        outside = tmp_path / "preserved"
        victim.rename(outside)
        victim.symlink_to(outside)
    with pytest.raises(FoundryError):
        releases.ensure_release(view.release, root / "vendor", base)


@pytest.mark.parametrize("tamper", ["record", "projection", "member"])
def test_rehashed_record_or_projection_commitments_cannot_disagree_with_sources(fixture_release, tamper):
    root, _, descriptor = fixture_release
    path, view = _published(fixture_release)
    bad = releases.thaw(descriptor.data)
    row = bad["releases"]["foundations"]
    if tamper == "record":
        row["records"]["FOUNDATION_01"] = "0" * 64
    elif tamper == "projection":
        row["projection"]["foundation_records_sha256"] = "0" * 64
    else:
        row["members"][row["member_prefix"] + "FOUNDATION_01.md"] = "0" * 64
    # Even a legitimately committed descriptor must agree with source records.
    issued = _issue(root, bad)
    with pytest.raises(FoundryError):
        releases.verify_release(issued.release("foundations"), path.read_bytes())


def test_corpus_path_traversal_and_symlink_members_are_rejected(fixture_release):
    _, _, descriptor = fixture_release
    for name in ("../escape.md", "/absolute.md"):
        with pytest.raises(FoundryError):
            releases.zip_members(releases.write_corpus({name: b"unsafe"}))
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        info = zipfile.ZipInfo("link")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        archive.writestr(info, "outside")
    with pytest.raises(FoundryError):
        releases.zip_members(stream.getvalue())


def test_baseline_public_release_identities_are_unchanged():
    # A public, digest-only snapshot: no protected book text or history reads.
    expected = json.loads((Path(__file__).parent / "fixtures/method_foundation_baseline_bindings.json").read_bytes())
    for key, fields in expected.items():
        row = releases.thaw(releases.select_release(key=key).data)
        assert {name: row[name] for name in fields} == fields


def test_cached_parsing_never_skips_same_size_same_mtime_tampering(fixture_release):
    root, _, _ = fixture_release
    _, view = _published(fixture_release)
    source = root / "sources/foundations.md"
    stat = source.stat()
    source.write_bytes(source.read_bytes().replace(b"Synthetic section 1.", b"Tampering section 1."))
    import os
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert source.stat().st_size == stat.st_size
    with pytest.raises(FoundryError):
        releases.verify_release(view.release, view.corpus_bytes)


def test_materialization_selector_preserves_the_existing_supported_releases(fixture_release):
    root, base, descriptor = fixture_release
    assert releases.select_release(descriptor=descriptor, consumer="materialization").key == "methods"
    for key in ("base", "methods"):
        spec = descriptor.release(key)
        assert releases.select_release(descriptor=descriptor, consumer="materialization",
            corpus_path=spec.path(root / "vendor", base), vendor_dir=root / "vendor", base_corpus=base).key == key
    with pytest.raises(FoundryError):
        releases.select_release(descriptor=descriptor, consumer="materialization",
            corpus_sha256=descriptor.release("foundations").data["corpus_sha256"])
