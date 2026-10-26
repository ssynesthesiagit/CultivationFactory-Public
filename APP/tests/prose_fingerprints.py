"""Content pins used by the path, Needle and Saber regressions.

Each pin accepts only the reviewed owner text or its deterministic public-export
variant (public_test_prose.transform). Hashes avoid shipping quoted rule prose.
Unlike presence/count checks, these reject any removed, substituted or misplaced
clause. Intentional rule edits must re-review and update both pins, not derive
expected values from the documents under test.
"""
import hashlib
import json

FINGERPRINTS = {
    "printed:tianxia.path.body_refining.feature.tempered_response": [
        "2ac1fb61d75eaf2ef85b3e2eef0b6678783308a224dbf6a301f22c3160199393",
        "82884782df93e3268477a4f9d1e4a2f0f15bd427e1cb2e8241114e38e919e7f1"
    ],
    "printed:tianxia.path.body_refining.feature.indomitable_body": [
        "64370a02ef29f49d877cf38867a014dd15cb83390b747a6a9280444d1111c9cb",
        "65e60c0c6e3d8c2318bdeea740ffa822c4fa351f88c27a071feb2bf1b1e0ecc4"
    ],
    "printed:tianxia.path.body_refining.feature.meridian_reinforcement": [
        "455d14649fcc04eca54186afc8d35d3d52495c963cf5df2784cd65c081571a6e",
        "80a7cf6f0cb19f83ee2f6d112457ede36e1bff9506ec3fccca7d3208e122274f"
    ],
    "printed:tianxia.path.body_refining.feature.extra_attack": [
        "563061da2b2b27459cdd6b84929f9c28d920adda865310115050da9fabcd4c88",
        "6438b4482fcbef59e90855df7dd165f188ede55c383cd9fc254a7778f14738d9"
    ],
    "riders:tianxia.subpath.body.hundred_hand_battle_mandala.feature.thousand_hand_incarnation": [
        "412f8d47ff121f3923386fd4ec7ce6aa03e4713d55c051801d1a506030179d5d",
        "70b7c5979f95d82ac4ce3059c94b3b336bec918014f698d8fad9e6eefe22d3cb"
    ],
    "riders:TAL_FENCING_VACUUM_CUT": [
        "5f77f1ef992b95b2e0df3267880737e49eb95a1d0aa8e204e9e6db985b0c2ec4",
        "86e17f466263aeb999dadffb7aa6fc5641c70d4dcc91015f5db0900ad18b2cd8"
    ],
    "riders:TAL_FENCING_SOVEREIGN_NEEDLE_INCARNATION": [
        "5c2f382ec897cad49fe24d22886326c41b66b465292550a49a0e45a856afab52",
        "d4daf1dfcc03fa60fd5114e358fddee4e4d080da93034e38ca0aea33e086539b"
    ],
    "riders:SABERS_BASE_SABER_LINE_METHOD": [
        "5f526205d123986c20b81fecfd19161e31132b5961aa93202054d98916d98726",
        "7ad67e021742f61a230643bc96c70c9bee482e0c5db7bfb3e8d1e144bf568538"
    ],
    "printed:SABERS_BASE_SABER_LINE_METHOD": [
        "dc77158d2159e68842592084ee5d433d2cc0e777f854b528a802c240aabb2afe",
        "eb96e731976cd566e0bb271d5083993b3120231cd1f204193b2055249dba8a3e"
    ],
    "player:SABERS_BASE_SABER_LINE_METHOD": [
        "2b69c50b4853e583cde6e2f7062a3bd72077adb37177fef838a6d2df8bcf9a99",
        "ee144911b5a3a39b1681777fdf187cd9ce93cc17bc99b208c0bdd3ef186ce401"
    ],
    "covers:tianxia.path.body_refining.feature.tempered_response": [
        "c1c9abc5e7a78ab4effdccf9a209da96c0423d77c9a2db02b2cbb3fc916076c8"
    ],
    "covers:tianxia.path.body_refining.feature.indomitable_body": [
        "91bc2335b4e482fc8d945dcab09c8efbc1e69c903acf2b147d33bead0e2bc931"
    ],
    "covers:tianxia.path.body_refining.feature.meridian_reinforcement": [
        "7f6d06bf6512c001a502323c3bc8435115654c282cd3c9b3dbaf2f071f6df03d"
    ],
    "covers:tianxia.path.body_refining.feature.extra_attack": [
        "a7efcaed3bfe526f3b246e26be49412adb9bfe87e65e1b8011272eac4fbc086e"
    ]
}

def assert_prose_fingerprint(label, value):
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    actual = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert actual in FINGERPRINTS[label], (label, "clause content changed", actual)
