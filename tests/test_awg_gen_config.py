import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "awg-gen-config"
FIXTURE = ROOT / "tests" / "fixtures" / "awg0.conf"


def load_module():
    name = "awg_gen_config_under_test"
    loader = importlib.machinery.SourceFileLoader(name, str(SCRIPT))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loader.exec_module(module)
    return module


awg = load_module()


def sample_generated():
    return awg.Generated(
        mtu=1280,
        intensity="medium",
        router_mode=False,
        extreme=False,
        jc=5,
        jmin=210,
        jmax=850,
        s1=40,
        s2=51,
        s3=33,
        s4=16,
        h1="200000000-200020000",
        h2="1300000000-1300020000",
        h3="2500000000-2500020000",
        h4="3700000000-3700020000",
        i1="<r 101><t>",
        i2="<r 102><t>",
        i3="<r 103><t>",
        i4="<r 104><t>",
        i5="<r 105><t>",
        header_protection_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        content_padding_addition="",
        rekey_after_time="108-130",
        rekey_timeout="5-7",
        reject_after_time="180-201",
        keepalive_timeout="10-14",
        max_handshake_attempts="14-19",
        random_trailers=True,
        disable_cookies=False,
        profile="quic_initial",
        mimic_all=False,
    )


class CliTests(unittest.TestCase):
    def test_version(self):
        p = subprocess.run([str(SCRIPT), "--version"], check=True, capture_output=True, text=True)
        self.assertEqual(p.stdout.strip(), "awg-gen-config 0.1.9")

    def test_builtin_self_test(self):
        p = subprocess.run([str(SCRIPT), "--self-test"], check=True, capture_output=True, text=True)
        self.assertIn("self-test: OK", p.stdout)

    def test_help_exposes_output_mode(self):
        p = subprocess.run([str(SCRIPT), "--help"], check=True, capture_output=True, text=True)
        self.assertIn("-o FILE", p.stdout)
        self.assertIn("--output FILE", p.stdout)


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.original = FIXTURE.read_text(encoding="utf-8")
        self.generated = sample_generated()

    def test_i1_i5_are_rendered_as_comments(self):
        block = awg.render_generated_block(self.generated)
        self.assertIn("# profile=quic_initial; intensity=medium", block)
        self.assertNotIn("path-mtu", block)
        self.assertNotIn("outer-ipv", block)
        for i in range(1, 6):
            self.assertIn(f"# I{i} = <r {100 + i}><t>", block)
            self.assertNotRegex(block, rf"(?m)^I{i}\s*=")
        self.assertNotRegex(block, r"(?m)^MTU\s*=")

    def test_merge_does_not_add_mtu_when_source_has_none(self):
        block = awg.render_generated_block(self.generated)
        merged = awg.merge_config(self.original, block)

        self.assertNotRegex(merged, r"(?m)^\s*MTU\s*=")

    def test_merge_preserves_existing_server_mtu(self):
        original = self.original.replace("ListenPort = 39697\n", "ListenPort = 39697\nMTU = 1376\n", 1)
        block = awg.render_generated_block(self.generated)
        merged = awg.merge_config(original, block)

        self.assertEqual(merged.count("MTU ="), 1)
        self.assertIn("MTU = 1376", merged)
        self.assertNotIn("MTU = 1280", merged)

    def test_cps_mtu_is_passed_to_packet_padding(self):
        options = awg.CpsOptions(
            mtu=576,
            intensity="medium",
            host="example.com",
            use_tag_c=False,
            use_tag_t=True,
            use_tag_r=True,
            use_tag_rc=True,
            use_tag_rd=True,
            use_browser_fp=False,
            browser_profile="chrome",
            mimic_all=False,
        )
        real_calc_padding = awg.calc_padding
        calls = []

        def capture_padding(*args, **kwargs):
            mtu = kwargs["mtu"] if "mtu" in kwargs else args[4]
            padding = real_calc_padding(*args, **kwargs)
            calls.append((mtu, args[0], args[1], padding))
            return padding

        with mock.patch.object(awg, "calc_padding", side_effect=capture_padding):
            awg.mk_quic_initial(options)

        self.assertTrue(calls)
        self.assertEqual({call[0] for call in calls}, {576})
        for mtu, header_size, extra_size, padding in calls:
            self.assertLessEqual(header_size + extra_size + padding, mtu)

    def test_junk_ranges_are_architect_ranges_independent_of_mtu(self):
        expected = {
            "low": (64, 256, 256, 512),
            "medium": (128, 512, 512, 1024),
            "high": (256, 768, 768, 1280),
        }
        for intensity, (jmin_lo, jmin_hi, jmax_lo, jmax_hi) in expected.items():
            with mock.patch.object(awg, "rnd", side_effect=[jmin_lo, jmax_lo]) as draw:
                jc, jmin, jmax = awg.generate_junk(intensity, 0, False, False)

            self.assertEqual(jc, 0)
            self.assertEqual(jmin, jmin_lo)
            self.assertEqual(jmax, jmax_lo)
            self.assertEqual(draw.call_args_list, [mock.call(jmin_lo, jmin_hi), mock.call(jmax_lo, jmax_hi)])
            self.assertGreater(jmax, jmin + 64)

        with mock.patch.object(awg, "rnd", side_effect=[256, 256, 256]) as draw:
            _, jmin, jmax = awg.generate_junk("low", 0, False, False)

        self.assertEqual(draw.call_args_list, [mock.call(64, 256), mock.call(256, 512), mock.call(64, 256)])
        self.assertEqual(jmin, 256)
        self.assertEqual(jmax, 256 + 64 + 256)
        self.assertGreater(jmax, 512)
        self.assertGreater(jmax, jmin + 64)

        for intensity, (jmin_lo, jmin_hi, jmax_lo, _) in expected.items():
            for _ in range(100):
                _, jmin, jmax = awg.generate_junk(intensity, 5, False, False)
                self.assertGreaterEqual(jmin, jmin_lo)
                self.assertLessEqual(jmin, jmin_hi)
                self.assertGreaterEqual(jmax, jmax_lo)
                self.assertGreater(jmax, jmin + 64)

        with mock.patch.object(awg, "rnd", side_effect=[-1, 16, 96]) as draw:
            jc, jmin, jmax = awg.generate_junk("medium", 5, True, False)

        self.assertEqual(draw.call_args_list, [mock.call(-1, 1), mock.call(16, 31), mock.call(96, 128)])
        self.assertLessEqual(jc, 3)
        self.assertGreaterEqual(jmin, 16)
        self.assertLessEqual(jmin, 31)
        self.assertGreaterEqual(jmax, 96)
        self.assertLessEqual(jmax, 128)
        self.assertGreater(jmax, jmin + 64)

    def test_router_extreme_zero_junk_keeps_nonzero_jc(self):
        with mock.patch.object(awg, "rnd", side_effect=[6, 16, 96]) as draw:
            jc, jmin, jmax = awg.generate_junk("medium", 0, True, True)

        self.assertEqual(draw.call_args_list, [mock.call(1, 8), mock.call(16, 31), mock.call(96, 128)])
        self.assertEqual(jc, 3)
        self.assertGreaterEqual(jmin, 16)
        self.assertLessEqual(jmin, 31)
        self.assertGreaterEqual(jmax, 96)
        self.assertLessEqual(jmax, 128)

    def test_router_non_extreme_zero_junk_stays_zero(self):
        with mock.patch.object(awg, "rnd", side_effect=[16, 96]):
            jc, jmin, jmax = awg.generate_junk("medium", 0, True, False)

        self.assertEqual(jc, 0)
        self.assertGreaterEqual(jmin, 16)
        self.assertLessEqual(jmin, 31)
        self.assertGreaterEqual(jmax, 96)
        self.assertLessEqual(jmax, 128)

    def test_interactive_has_one_architect_mtu_question(self):
        int_prompts = []
        choice_prompts = []
        bool_prompts = []
        text_prompts = []
        captured = {}

        def fake_ask_int(prompt, default, low, high):
            int_prompts.append(prompt)
            return default

        def fake_ask_choice(prompt, options, default):
            choice_prompts.append(prompt)
            return options[default][0]

        def fake_ask_bool(prompt, default):
            bool_prompts.append(prompt)
            return default

        def fake_ask(prompt, default=""):
            text_prompts.append(prompt)
            return default

        def fake_generate_cps(profile, options, router_mode):
            captured["options"] = options
            return "i1", "i2", "i3", "i4", "i5", profile

        with mock.patch.object(awg, "ask_int", side_effect=fake_ask_int), \
             mock.patch.object(awg, "ask_choice", side_effect=fake_ask_choice), \
             mock.patch.object(awg, "ask_bool", side_effect=fake_ask_bool), \
             mock.patch.object(awg, "ask", side_effect=fake_ask), \
             mock.patch.object(awg, "generate_cps", side_effect=fake_generate_cps):
            generated = awg.generate_interactive()

        prompts = int_prompts + choice_prompts + bool_prompts + text_prompts
        self.assertEqual(int_prompts.count("MTU"), 1)
        self.assertNotIn("Outer/path MTU", prompts)
        self.assertNotIn("Outer IP header to budget for:", prompts)
        self.assertFalse(any("safe tunnel" in prompt.lower() for prompt in prompts))
        self.assertFalse(any("safe jmax" in prompt.lower() for prompt in prompts))
        self.assertEqual(captured["options"].mtu, 1500)
        self.assertEqual(generated.mtu, 1500)

    def test_summary_uses_simple_generator_mtu_label(self):
        with mock.patch("builtins.print") as printer:
            awg.print_summary(self.generated)

        lines = [call.args[0] for call in printer.call_args_list]
        self.assertIn("  MTU used for CPS generation: 1280", lines)
        self.assertFalse(any("path MTU" in line for line in lines))
        self.assertFalse(any("safe bound" in line for line in lines))

    def test_merge_preserves_mtu_from_legacy_generated_block(self):
        legacy_block = awg.render_generated_block(self.generated).replace(
            awg.BEGIN_MARKER, f"{awg.BEGIN_MARKER}\nMTU = 1376", 1
        )
        original = self.original.replace("ListenPort = 39697\n", f"ListenPort = 39697\n{legacy_block}\n", 1)
        block = awg.render_generated_block(self.generated)
        merged = awg.merge_config(original, block)

        self.assertEqual(merged.count("MTU ="), 1)
        self.assertIn("MTU = 1376", merged)
        self.assertNotIn("MTU = 1280", merged)

    def test_merge_preserves_server_identity_and_peers(self):
        block = awg.render_generated_block(self.generated)
        merged = awg.merge_config(self.original, block)

        self.assertIn("PrivateKey = server-private-key", merged)
        self.assertIn("Address = 10.8.1.0/24", merged)
        self.assertIn("ListenPort = 39697", merged)

        old_peer_tail = self.original[self.original.index("[Peer]"):].strip()
        new_peer_tail = merged[merged.index("[Peer]"):].strip()
        self.assertEqual(new_peer_tail, old_peer_tail)

        self.assertNotIn("Jmin = 396", merged)
        self.assertNotIn("# I1 = <r 10>", merged)
        self.assertIn("# I1 = <r 101><t>", merged)
        self.assertEqual(merged.count("[Peer]"), 2)

    def test_generate_sizes_respects_awg3_constraints(self):
        for _ in range(2000):
            s1, s2, s3, s4 = awg.generate_sizes(False, False, True)
            self.assertGreaterEqual(min(s1, s2, s3, s4), 12)
            self.assertLessEqual(s4, 32)
            self.assertNotEqual(s2, s1 + 56)
            self.assertNotEqual(s3, s1 + 84)
            self.assertNotEqual(s3, s2 + 28)

    def test_local_output_is_0600(self):
        if os.name == "nt":
            self.skipTest("POSIX permissions test")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "export.conf"
            awg.write_local_output(str(path), b"secret\n")
            self.assertEqual(path.read_bytes(), b"secret\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_output_mode_never_calls_container_write_restart_or_backup(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "candidate.conf"
            with mock.patch.object(awg, "read_container_file", return_value=self.original.encode()), \
                 mock.patch.object(awg, "generate_interactive", return_value=self.generated), \
                 mock.patch.object(awg, "print_summary"), \
                 mock.patch.object(awg, "copy_bytes_to_container", side_effect=AssertionError("container write called")), \
                 mock.patch.object(awg, "restart_container", side_effect=AssertionError("restart called")), \
                 mock.patch.object(awg, "create_backup", side_effect=AssertionError("backup called")), \
                 mock.patch.object(awg, "preflight_in_container", side_effect=AssertionError("container preflight called")):
                awg.output_config("dummy-container", "/opt/amnezia/awg/awg0.conf", str(target))

            exported = target.read_text(encoding="utf-8")
            self.assertIn("PrivateKey = server-private-key", exported)
            self.assertIn("# I1 = <r 101><t>", exported)
            self.assertNotRegex(exported, r"(?m)^\s*MTU\s*=")
            self.assertEqual(exported[exported.index("[Peer]"):].strip(), self.original[self.original.index("[Peer]"):].strip())


if __name__ == "__main__":
    unittest.main()
