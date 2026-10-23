"""Runtime packaging uses pinned generated JSON, not build-only sidecars."""
from factory_authoring import body_refining_variants as br


def test_runtime_pin_does_not_require_the_builder_sidecar(tmp_path, monkeypatch):
    target = tmp_path / "authority.json"
    target.write_bytes(br.AUTHORITY.read_bytes())
    monkeypatch.setattr(br, "AUTHORITY", target)
    br.access.cache_clear()
    try:
        assert br.access()["schema"] == "TianxiaBodyRefiningVariants.v1"
        assert br.access()["counts"]["canonical_versions"] == 72
        assert not target.with_suffix(".sha256").exists()
    finally:
        br.access.cache_clear()
