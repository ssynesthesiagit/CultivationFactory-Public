from character_creation.production_release import CharacterProductionReleaseAdapter


def test_stable_production_authority_uses_factory_hash_not_isolated_copy_paths():
    common = {
        "factory_zip_hash": "4daf167cf634f27efef4dd2f1c8700bb4b7037cc6234c32be1af90aea5916385",
        "factory_version": "HF05ZVK-R1H",
        "health": "READY",
    }
    manual = {
        **common,
        "copied_factory_zip": r"F:\fixture\manual\vendor\packages\factory.zip",
        "original_factory_zip": r"F:\source\BundledContent\factory.zip",
    }
    standard = {
        **common,
        "copied_factory_zip": r"F:\fixture\standard\vendor\packages\factory.zip",
        "original_factory_zip": r"G:\clean-source\BundledContent\factory.zip",
    }

    stable_manual = CharacterProductionReleaseAdapter._stable(manual)
    stable_standard = CharacterProductionReleaseAdapter._stable(standard)

    assert stable_manual == stable_standard == common
    assert CharacterProductionReleaseAdapter._stable(
        {**standard, "factory_zip_hash": "different-authority"}
    ) != stable_manual
