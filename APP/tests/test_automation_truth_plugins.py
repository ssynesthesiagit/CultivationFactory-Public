"""Source-index tests: declarations must never turn into execution claims."""

from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from dataclasses import asdict
from pathlib import Path

from tools.automation_truth_plugins import build_plugin_index


class PluginSourceIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="automation-truth-test-", dir=Path(__file__).resolve().parents[2])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.extension_dir = self.root / "APP" / "combat" / "ext"
        self.extension_dir.mkdir(parents=True)

    def source(self, name, code):
        path = self.extension_dir / name
        path.write_text(textwrap.dedent(code).lstrip(), encoding="utf-8")
        return path

    def test_comments_docstrings_and_uncalled_helpers_do_not_prove_ownership(self):
        self.source("example.py", '''
            """COMMENT_ONLY is automated."""
            from . import hook
            # COMMENT_ONLY belongs to this plug-in.
            def unused():
                return "UNUSED_HELPER"
            @hook("speed")
            def speed(engine, actor):
                """COMMENT_ONLY and DOCSTRING_ONLY are implemented here."""
                return None
        ''')
        index = build_plugin_index(self.root, ["COMMENT_ONLY", "DOCSTRING_ONLY", "UNUSED_HELPER"])
        self.assertEqual(index.mechanic_claims, {})
        self.assertEqual(index.hooks["speed"][0]["status"], "REGISTERED_HANDLER")

    def test_empty_or_missing_authority_ids_are_ignored(self):
        self.source("example.py", '''
            from . import hook
            @hook("speed")
            def speed(engine, actor):
                return actor.settings.get("", " ")
        ''')
        index = build_plugin_index(self.root, ["", " ", None])
        self.assertEqual(index.mechanic_claims, {})

    def test_exact_id_through_called_helper_is_explicitly_unverified(self):
        self.source("example.py", '''
            from . import hook
            OWNED = "EXACT_ID"
            def owns(actor):
                return OWNED in actor.features
            @hook("speed")
            def speed(engine, actor):
                if owns(actor):
                    return 5
                return None
            @hook("armor_class")
            def armor(engine, actor):
                return None
            raise RuntimeError("The index must not import plug-ins")
        ''')
        index = build_plugin_index(self.root, ["EXACT_ID"])
        claims = index.claims_for("EXACT_ID")
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["hook"], "speed")
        self.assertEqual(claims[0]["status"], "UNVERIFIED_REFERENCE")
        self.assertIn("APP/combat/ext/example.py:2", claims[0]["evidence"])
        self.assertIn("APP/combat/ext/example.py:7", claims[0]["evidence"])

    def test_effect_and_block_registrations_and_dispatch_sites(self):
        self.source("example.py", '''
            from . import hook as register_hook, effect as register_effect
            FIRST, SECOND = "first_block", "second_block"
            BLOCKS = {FIRST, SECOND}
            @register_hook("compile_block")
            def compile(block, spec, row, numbers):
                if block not in BLOCKS:
                    return None
                return [row]
            @register_effect("example_effect")
            def execute(ctx, effect):
                return None
        ''')
        (self.extension_dir.parent / "consumer.py").write_text(
            'from . import ext as extension\n'
            'def compile_one(block):\n'
            '    return extension.run("compile_block", block)\n', encoding="utf-8")
        index = build_plugin_index(self.root)
        self.assertEqual(sorted(index.blocks), ["first_block", "second_block"])
        self.assertEqual(index.blocks["first_block"][0]["status"], "REGISTERED_BLOCK_GUARD")
        self.assertEqual(index.effects["example_effect"][0]["function"], "execute")
        self.assertEqual(index.hook_dispatches["compile_block"][0]["evidence"], ["APP/combat/consumer.py:3"])
        self.assertEqual(index.unresolved_block_compilers, [])

    def test_dynamic_blocks_remain_unresolved(self):
        self.source("example.py", '''
            from . import hook
            @hook("compile_block")
            def compile(block, spec, row, numbers):
                return registered_compilers[block](spec)
        ''')
        index = build_plugin_index(self.root)
        self.assertEqual(index.blocks, {})
        self.assertEqual(index.unresolved_block_compilers[0]["status"], "UNKNOWN_BLOCK_DISPATCH")

    def test_cross_module_block_consumer_has_only_unverified_evidence(self):
        self.source("compiler.py", '''
            from . import hook
            @hook("compile_block")
            def compile(block, spec, row, numbers):
                return [row] if block == "owned_marker" else None
        ''')
        self.source("consumer.py", '''
            from . import hook
            BLOCK = "owned_marker"
            @hook("speed")
            def speed(engine, actor):
                return next((row["amount"] for row in engine.rows if row["block"] == BLOCK), None)
        ''')
        index = build_plugin_index(self.root)
        consumer = index.block_consumers["owned_marker"][0]
        self.assertEqual(consumer["status"], "UNVERIFIED_BLOCK_REFERENCE")
        self.assertEqual(consumer["module"], "combat.ext.consumer")
        self.assertEqual(len(index.claims_for("arbitrary", block_names=["owned_marker"])), 2)

    def test_literal_concatenated_ids_and_conditional_gm_sites(self):
        self.source("example.py", '''
            from . import hook
            PREFIX = "tianxia."
            @hook("event")
            def event(engine, actor):
                if PREFIX + "example" not in actor.features:
                    return
                engine._append_event("GM_RIDER", "source", payload={"rider": "Apply the remaining clause by hand."})
                actor.rider(f"Runtime name: {actor.name}")
        ''')
        index = build_plugin_index(self.root, ["tianxia.example"])
        references = [record for record in index.claims_for("tianxia.example") if record["category"] == "plugin_id_reference"]
        self.assertEqual(len(references), 1)
        self.assertEqual(len(index.gm_emissions), 2)
        static = next(record for record in index.gm_emissions if record["emission_kind"] == "event")
        dynamic = next(record for record in index.gm_emissions if record["emission_kind"] == "context_method")
        self.assertEqual(static["template"], "Apply the remaining clause by hand.")
        self.assertEqual(static["hooks"], ["event"])
        self.assertIsNone(dynamic["template"])
        self.assertEqual(dynamic["template_status"], "UNKNOWN_DYNAMIC_TEMPLATE")
        self.assertEqual(dynamic["status"], "POSSIBLE_GM_EMISSION_SITE")
        mapped = [record for record in index.claims_for("tianxia.example") if record["category"] == "plugin_gm_emission"]
        self.assertTrue(all(record["applicability"] == "UNKNOWN_MODULE_ASSOCIATION" for record in mapped))

    def test_factory_alias_is_never_invented(self):
        self.source("example.py", '''
            from . import hook
            @hook("speed")
            def speed(engine, actor):
                return "ABILITY" in actor.features
        ''')
        index = build_plugin_index(self.root, ["factory:ABILITY", "ABILITY"])
        self.assertEqual(index.claims_for("factory:ABILITY"), [])
        claim = index.claims_for("factory:ABILITY", ability_id="ABILITY")[0]
        self.assertEqual(claim["matched_id"], "ABILITY")
        self.assertEqual(claim["authority_mechanic_id"], "factory:ABILITY")
        self.assertEqual(claim["status"], "UNVERIFIED_REFERENCE")

    def test_deterministic_and_independent_return_values(self):
        self.source("example.py", '''
            from . import hook
            @hook("speed")
            def speed(engine, actor):
                return "EXACT_ID" in actor.features
        ''')
        one = build_plugin_index(self.root, ["EXACT_ID"])
        two = build_plugin_index(self.root, ["EXACT_ID"])
        self.assertEqual(json.dumps(asdict(one), sort_keys=True), json.dumps(asdict(two), sort_keys=True))
        claims = one.claims_for("EXACT_ID")
        claims[0]["evidence"].append("mutated")
        self.assertNotIn("mutated", one.claims_for("EXACT_ID")[0]["evidence"])

    def test_unreadable_source_is_explicit_unknown(self):
        self.source("broken.py", "def broken(:\n")
        index = build_plugin_index(self.root)
        self.assertEqual(index.diagnostics[0]["status"], "UNKNOWN")
        self.assertEqual(index.diagnostics[0]["evidence"], ["APP/combat/ext/broken.py:1"])


if __name__ == "__main__":
    unittest.main()
