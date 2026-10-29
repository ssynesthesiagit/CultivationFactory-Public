from app.core import EXPECTED_FACTORY_HASH
from vendor_adapter.service import FactoryAdapter


def test_factory_version_and_hash_detection(factory_environment):
    status=factory_environment['adapter'].status()
    assert status['health']=='READY'
    assert status['factory_zip_hash']==EXPECTED_FACTORY_HASH


def test_copied_fixture_health_check(factory_environment):
    result=factory_environment['adapter'].health_check()
    assert result['verdict']=='PASS'
    assert result['details']['fixture_schema_validation']
    assert result['details']['original_factory_unchanged']


def test_vendor_logs_captured(factory_environment):
    if not factory_environment['adapter'].recent_runs():
        factory_environment['adapter'].health_check()
    run=factory_environment['adapter'].recent_runs()[0]
    assert run['stdout_path'] and run['stderr_path']
    assert run['command']


def test_original_factory_remains_unchanged(factory_environment):
    status=factory_environment['adapter'].status()
    assert status['health']=='READY'
    assert status['factory_zip_hash']==EXPECTED_FACTORY_HASH


def test_windows_transient_extraction_publish_is_retried_atomically(tmp_path, monkeypatch):
    import os

    staging = tmp_path / "factory.staging"
    destination = tmp_path / "factory"
    staging.mkdir()
    (staging / "FACTORY_MANIFEST.json").write_text("{}", encoding="utf-8")
    real_replace = os.replace
    calls = {"count": 0}

    def transient_replace(source, target):
        calls["count"] += 1
        if calls["count"] < 3:
            error = PermissionError(13, "transient Windows scanner lock")
            error.winerror = 5
            raise error
        return real_replace(source, target)

    monkeypatch.setattr("vendor_adapter.service.os.replace", transient_replace)
    FactoryAdapter._publish_extraction(staging, destination, attempts=3, delay_seconds=0)
    assert calls["count"] == 3
    assert destination.is_dir()
    assert not staging.exists()
