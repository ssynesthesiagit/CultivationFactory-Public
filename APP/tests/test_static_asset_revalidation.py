"""Conditional reads validate the actual stamped deployment bytes."""
import os
from pathlib import Path

import pytest

from app.static_build import BUILD_HEADER, StaticBuild


@pytest.fixture
def assets(tmp_path):
    folder = tmp_path / "static/tabletop"
    folder.mkdir(parents=True)
    (folder / "tabletop.html").write_text('<script src="/static/tabletop/main.js"></script>')
    (folder / "main.js").write_text('import "./child.js"; const value = "first";\n')
    (folder / "child.js").write_text('export const value = 1;\n')
    return tmp_path, StaticBuild(tmp_path, nonce="fixed-test-build")


@pytest.mark.parametrize("form", ["weak", "strong", "list", "star"])
def test_matching_validator_reuses_stamped_bytes(assets, form):
    _, build = assets
    initial = build.response_for("/static/tabletop/main.js")
    assert initial.status_code == 200
    assert f"?v={build.build}".encode() in initial.body
    etag = initial.headers["etag"]
    condition = {"weak": etag, "strong": etag.removeprefix("W/"),
                 "list": f'"unrelated,opaque", {etag}', "star": "*"}[form]
    cached = build.response_for("/static/tabletop/main.js", if_none_match=condition)
    assert cached.status_code == 304
    assert cached.body == b""
    assert "content-length" not in cached.headers
    for key in ("etag", "cache-control", "vary", BUILD_HEADER):
        assert cached.headers[key] == initial.headers[key]


def test_replaced_source_invalidates_validator_even_with_same_size_and_mtime(assets):
    root, build = assets
    url = "/static/tabletop/main.js"
    old = build.response_for(url)
    path = root / "static/tabletop/main.js"
    before = path.stat()
    replacement = path.with_suffix(".new")
    replacement.write_bytes(path.read_bytes().replace(b"first", b"later"))
    os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
    replacement.replace(path)
    changed = build.response_for(url, if_none_match=old.headers["etag"])
    assert changed.status_code == 200
    assert changed.headers["etag"] != old.headers["etag"]
    assert b'later' in changed.body


def test_new_process_build_invalidates_prior_validator(assets):
    root, old_build = assets
    prior = old_build.response_for("/tabletop")
    new_build = StaticBuild(root, nonce="different-process")
    current = new_build.response_for("/tabletop", if_none_match=prior.headers["etag"])
    assert current.status_code == 200
    assert current.headers["etag"] != prior.headers["etag"]
    assert f"?v={new_build.build}".encode() in current.body


def test_head_and_mutation_preconditions(assets):
    _, build = assets
    url = "/static/tabletop/main.js"
    initial = build.response_for(url)
    head = build.response_for(url, method="HEAD")
    assert head.status_code == 200 and head.body == b""
    assert int(head.headers["content-length"]) == len(initial.body)
    assert build.response_for(url, method="HEAD", if_none_match=initial.headers["etag"]).status_code == 304
    assert build.response_for(url, method="POST", if_none_match=initial.headers["etag"]).status_code == 412


@pytest.mark.parametrize("form", ["unquoted", "malformed", "quoted_comma", "adjacent", "space_only"])
def test_nonmatching_or_malformed_validator_does_not_suppress_body(assets, form):
    _, build = assets
    url = "/static/tabletop/main.js"
    initial = build.response_for(url)
    tag = initial.headers["etag"].removeprefix("W/")
    condition = {"unquoted": tag.strip('"'), "malformed": f'garbage {tag}',
                 "quoted_comma": f'"prefix,{tag[1:-1]}"', "adjacent": f'"other"{tag}',
                 "space_only": f'"other" {tag}'}[form]
    current = build.response_for(url, if_none_match=condition)
    assert current.status_code == 200
    assert current.body == initial.body


def test_conditional_requests_do_not_expand_static_path_scope(assets):
    root, build = assets
    (root / "private.js").write_text("private")
    assert build.response_for("/static/tabletop/../../private.js", if_none_match="*") is None
    assert build.response_for("/static/tabletop/missing.js", if_none_match="*") is None
