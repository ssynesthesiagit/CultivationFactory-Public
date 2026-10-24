from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from app.core import FoundryError, sha256_json
from character_creation import compiler_selection_authority as authority
from character_creation import method_corpus_release as release
from factory_authoring import final_character_materializer as materializer
from factory_authoring import final_compiler_release
from test_compiler_selection_authority import pinned_authority


def base_corpus():
    path = materializer.FINAL_CHARACTER_DEFAULT_CORPUS
    if not str(path).startswith('/var/tmp/'):
        # These tests publish release files into the state root, so they run
        # only against an explicit scratch copy, never the owner's live root.
        pytest.skip(
            'Release-owning test: set CULTIVATION_FACTORY_STATE_ROOT to a scratch copy of the '
            'Factory state root under /var/tmp (vendor/ with factory_adapter.json pointing at it).'
        )
    assert sha256(path.read_bytes()).hexdigest() == release.BASE_CORPUS_SHA256
    return path


def test_exact_complete_source_and_additive_reproducible_release():
    base = base_corpus().read_bytes()
    first = release.derive_corpus_bytes(base)
    assert first == release.derive_corpus_bytes(base)
    assert sha256(first).hexdigest() == release.CORPUS_SHA256
    with zipfile.ZipFile(BytesIO(base)) as original, zipfile.ZipFile(BytesIO(first)) as new:
        assert set(new.namelist()) == set(original.namelist()) | {release.SOURCE_MEMBER}
        for name in original.namelist():
            if name != release.MANIFEST_MEMBER:
                assert new.read(name) == original.read(name)
        manifest = json.loads(new.read(release.MANIFEST_MEMBER))
        assert manifest['method_corpus_release'] == release.provenance()
        assert sha256(new.read(release.MANIFEST_MEMBER)).hexdigest() == release.MANIFEST_SHA256
        assert manifest['active_packet_sources'] == json.loads(original.read(release.MANIFEST_MEMBER))['active_packet_sources'] + [release.SOURCE_MEMBER]
        assert new.read(release.SOURCE_MEMBER) == release.verified_source()


def test_all_102_methods_have_real_compiler_source(pinned_authority):
    assert pinned_authority['schema'] == authority.RELEASED_COMPILER_SELECTION_AUTHORITY_SCHEMA
    assert pinned_authority['method_corpus_release'] == release.binding()
    assert pinned_authority['method_choice']['compiler_backed_ids'] == [f'METHOD-{i:03}' for i in range(1, 103)]
    for number in range(81, 103):
        row = pinned_authority['method_choice']['records'][f'METHOD-{number:03}']
        assert row['source_path'] == release.SOURCE_MEMBER
        assert row['source_file_sha256'] == release.SOURCE_SHA256
        assert row['corpus_sha256'] == release.CORPUS_SHA256
        assert row['source_text'].startswith(f'## METHOD-{number:03} — ')


@pytest.mark.parametrize('paths,expected', [
    ({'BODY_REFINING','QI_CULTIVATION'}, {'METHOD-081','METHOD-082','METHOD-085'}),
    ({'BODY_REFINING','SPIRIT_AWAKENING'}, {'METHOD-083','METHOD-085','METHOD-087'}),
    ({'QI_CULTIVATION','SPIRIT_AWAKENING'}, {'METHOD-084','METHOD-085'}),
    ({'BODY_REFINING','QI_CULTIVATION','SPIRIT_AWAKENING'}, {'METHOD-085'}),
])
def test_every_multi_path_combination_is_compiler_backed(paths, expected, pinned_authority):
    rows = json.loads(release.REGISTRY_PATH.read_text())['methods']
    compatible = {r['method_id'] for r in rows if paths <= {g['path_id'] for g in r['explicit_ap_grants'] if g.get('grants_attainment_points')}}
    assert compatible == expected
    assert compatible <= set(pinned_authority['method_choice']['compiler_backed_ids'])


@pytest.mark.parametrize('field', ['corpus_sha256','source_sha256','parent_corpus_sha256','manifest_sha256','active_source_index_sha256'])
def test_rehashed_release_binding_tampering_fails(field, pinned_authority):
    forged = deepcopy(pinned_authority)
    forged['method_corpus_release'][field] = '0' * 64
    forged['authority_sha256'] = sha256_json({k:v for k,v in forged.items() if k != 'authority_sha256'})
    with pytest.raises(FoundryError):
        authority.verify_compiler_selection_authority(forged)


def legacy_snapshot(released):
    old = deepcopy(released)
    old['schema'] = authority.COMPILER_SELECTION_AUTHORITY_SCHEMA
    del old['method_corpus_release']
    with zipfile.ZipFile(base_corpus()) as corpus:
        raw = corpus.read(release.MANIFEST_MEMBER)
        active = set(json.loads(raw)['active_packet_sources'])
        index = [{'source_path':p,'source_file_sha256':sha256(authority._read_source(corpus,p)[0]).hexdigest()} for p in sorted(active)]
        old['source_authority'] = {'manifest_sha256':sha256(raw).hexdigest(),'active_source_index':index,'active_source_index_sha256':sha256_json(index)}
        for slot, extractor in [('method_choice',authority._method_excerpt),('foundation_choice',authority._foundation_excerpt)]:
            records = {key:authority._evidence(choice_id=key,canonical_name=row['canonical_name'],source=extractor(corpus,row['canonical_name'],active),corpus=old['factory']) for key,row in old[slot]['records'].items()}
            old[slot] = {'records':records,'compiler_backed_ids':sorted(key for key,row in records.items() if row['selectable'])}
    old['projection'] = {
        'method_records_sha256':sha256_json(old['method_choice']['records']),
        'foundation_records_sha256':sha256_json(old['foundation_choice']['records']),
        'compiler_backed_method_ids_sha256':sha256_json(old['method_choice']['compiler_backed_ids']),
        'compiler_backed_foundation_ids_sha256':sha256_json(old['foundation_choice']['compiler_backed_ids']),
    }
    old['authority_sha256'] = sha256_json({k:v for k,v in old.items() if k != 'authority_sha256'})
    return old


def test_legacy_snapshot_remains_valid_but_cannot_promote_new_methods(pinned_authority):
    old = legacy_snapshot(pinned_authority)
    assert authority.verify_compiler_selection_authority(old) == old
    assert 'METHOD-083' not in old['method_choice']['compiler_backed_ids']
    stripped = deepcopy(pinned_authority)
    stripped['schema'] = authority.COMPILER_SELECTION_AUTHORITY_SCHEMA
    del stripped['method_corpus_release']
    stripped['authority_sha256'] = sha256_json({k:v for k,v in stripped.items() if k != 'authority_sha256'})
    with pytest.raises(FoundryError):
        authority.verify_compiler_selection_authority(stripped)


def test_corrupt_and_symlink_cache_are_rejected_without_overwrite(tmp_path):
    vendor = tmp_path / 'vendor'
    target = release.release_path(vendor)
    target.parent.mkdir(parents=True)
    target.write_bytes(b'corrupt')
    with pytest.raises(FoundryError):
        release.ensure_release(vendor, base_corpus())
    assert target.read_bytes() == b'corrupt'
    target.unlink()
    outside = tmp_path / 'outside'
    outside.write_bytes(b'preserve')
    target.symlink_to(outside)
    with pytest.raises(FoundryError):
        release.ensure_release(vendor, base_corpus())
    assert outside.read_bytes() == b'preserve'


def test_source_and_parent_tampering_are_rejected(tmp_path, monkeypatch):
    with pytest.raises(FoundryError):
        release.derive_corpus_bytes(base_corpus().read_bytes() + b'x')
    altered = tmp_path / 'source.md'
    altered.write_bytes(release.SOURCE_PATH.read_bytes() + b'x')
    monkeypatch.setattr(release, 'SOURCE_PATH', altered)
    with pytest.raises(FoundryError):
        release.derive_corpus_bytes(base_corpus().read_bytes())


@pytest.mark.parametrize('method_id', ['METHOD-083', 'METHOD-085', 'METHOD-087'])
def test_materializer_bridges_combined_path_methods_and_rejects_forgery(method_id):
    base = base_corpus()
    corpus = release.ensure_release(materializer.FINAL_CHARACTER_DEFAULT_STATE_ROOT / 'vendor', base)
    rows = json.loads(release.REGISTRY_PATH.read_text())['methods']
    row = next(r for r in rows if r['method_id'] == method_id)
    packet = {'record_id': method_id, 'display_name': row['name'], 'source_evidence': [{
        'source_path': materializer._PACKET_METHOD_SOURCE_PATH,
        'source_hash': release.REGISTRY_SHA256, 'source_anchor': f'method:{method_id}'}]}
    active, texts = materializer._corpus_active_texts(corpus)
    recognized, proof = materializer._bridge_modern_packet_source(packet, corpus=corpus, active=active, corpus_texts=texts)
    assert recognized and proof['source_path'] == release.SOURCE_MEMBER
    assert proof['source_file_sha256'] == release.SOURCE_SHA256
    assert proof['source_evidence_verified'] is True
    base_active, base_texts = materializer._corpus_active_texts(base)
    assert materializer._bridge_modern_packet_source(packet, corpus=base, active=base_active, corpus_texts=base_texts) == (True, None)
    for field, value in [('record_id', 'METHOD-002'), ('display_name', row['name'] + ' forged')]:
        forged = {**packet, field: value}
        assert materializer._bridge_modern_packet_source(forged, corpus=corpus, active=active, corpus_texts=texts) == (True, None)
    forged = deepcopy(packet)
    forged['source_evidence'][0]['source_hash'] = '0' * 64
    assert materializer._bridge_modern_packet_source(forged, corpus=corpus, active=active, corpus_texts=texts) == (True, None)


def test_materializer_requires_exact_release_location_and_hash(tmp_path):
    base = base_corpus()
    # The pinned production compiler is the derived v2 release; publish (or
    # re-verify) it in this scratch state root like the materializer does.
    materializer._final_compiler_release.ensure_release(materializer.FINAL_CHARACTER_DEFAULT_STATE_ROOT)
    corpus = release.ensure_release(materializer.FINAL_CHARACTER_DEFAULT_STATE_ROOT / 'vendor', base)
    materializer._assert_production_pins(materializer.FINAL_CHARACTER_DEFAULT_COMPILER, corpus)
    materializer._assert_production_pins(materializer.FINAL_CHARACTER_DEFAULT_COMPILER, base)
    substitute = tmp_path / 'same-bytes.zip'
    substitute.write_bytes(corpus.read_bytes())
    with pytest.raises(FoundryError):
        materializer._assert_production_pins(materializer.FINAL_CHARACTER_DEFAULT_COMPILER, substitute)


def test_real_unchanged_compiler_verifies_all_102_method_packets(tmp_path, pinned_authority):
    """Real subprocess packet acceptance; the base ledger remains a fixture."""
    base = base_corpus()
    corpus = release.ensure_release(materializer.FINAL_CHARACTER_DEFAULT_STATE_ROOT / 'vendor', base)
    root = base.parent.parent
    fixture = root / '08_FIXTURES/GOOD_Authoritative_CL13'
    registry = json.loads((fixture / 'Command_2/Rules_Selection_Packets.json').read_text())
    for key,row in pinned_authority['method_choice']['records'].items():
        excerpt = row['source_text'].strip()
        registry['packets'].append({'packet_id':f'RELEASE_{key}','name':row['canonical_name'],'authority':'tianxia_rules','source_path':row['source_path'],'source_text':excerpt,'source_text_sha256':sha256(excerpt.encode()).hexdigest()})
    packet_file = tmp_path / 'packets.json'
    packet_file.write_text(json.dumps(registry))
    compiler = root / authority.PINNED_COMPILER_RELATIVE_PATH
    assert sha256(compiler.read_bytes()).hexdigest() == authority.PINNED_COMPILER_SHA256
    result = subprocess.run([sys.executable,str(compiler),'--ledger',str(fixture / 'Character_Master_Ledger.json'),'--rules-packets',str(packet_file),'--corpus',str(corpus),'--output',str(tmp_path / 'compiled')],capture_output=True,text=True,timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / 'compiled/Complete_Action_Surface.json').is_file()
    # The same exact new packets must remain rejected by the legacy corpus.
    legacy = subprocess.run([sys.executable,str(compiler),'--ledger',str(fixture / 'Character_Master_Ledger.json'),'--rules-packets',str(packet_file),'--corpus',str(base),'--output',str(tmp_path / 'legacy')],capture_output=True,text=True,timeout=60)
    assert legacy.returncode != 0
    assert 'RULES_PACKET_SOURCE_NOT_ACTIVE' in legacy.stdout + legacy.stderr
