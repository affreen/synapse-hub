"""
Unit tests for backend/ai_explainer.py's pure logic (JSON parsing, dotenv
loading, enable/disable detection). These do NOT call the real Claude API —
that would require a live key and network access, and wouldn't be
deterministic for CI. server.py's fallback-to-offline-templates behavior
means the app degrades gracefully if the real API is unreachable, which is
what actually matters for correctness; that's exercised manually (see
README's testing section) rather than in this offline unit suite.
"""

import os
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "backend"))

import ai_explainer  # noqa: E402


class TestExtractJson(unittest.TestCase):
    def test_plain_json(self):
        result = ai_explainer._extract_json('{"packets": ["a", "b"]}')
        self.assertEqual(result, {"packets": ["a", "b"]})

    def test_json_wrapped_in_fence(self):
        text = '```json\n{"packets": ["a"]}\n```'
        result = ai_explainer._extract_json(text)
        self.assertEqual(result, {"packets": ["a"]})

    def test_json_wrapped_in_bare_fence(self):
        text = '```\n{"explanation": "hello"}\n```'
        result = ai_explainer._extract_json(text)
        self.assertEqual(result, {"explanation": "hello"})

    def test_invalid_json_raises(self):
        with self.assertRaises(Exception):
            ai_explainer._extract_json("not json at all")


class TestPacketFacts(unittest.TestCase):
    def test_tcp_packet_facts(self):
        pkt = {
            "number": 5,
            "length": 60,
            "summary": {"protocol": "HTTP", "src": "10.0.0.1", "dst": "10.0.0.2"},
            "layers": {
                "tcp": {"src_port": 51000, "dst_port": 80, "flags_set": ["SYN"], "seq": 1, "ack": 0},
            },
        }
        facts = ai_explainer._packet_facts(pkt)
        self.assertEqual(facts["protocol"], "HTTP")
        self.assertEqual(facts["tcp"]["dst_port"], 80)
        self.assertEqual(facts["tcp"]["flags"], ["SYN"])

    def test_arp_packet_facts(self):
        pkt = {
            "number": 1, "length": 42,
            "summary": {"protocol": "ARP", "src": "10.0.0.1", "dst": "10.0.0.2"},
            "layers": {"arp": {"opcode": "Request", "sender_ip": "10.0.0.1",
                                "target_ip": "10.0.0.2", "sender_mac": "aa:bb:cc:dd:ee:ff"}},
        }
        facts = ai_explainer._packet_facts(pkt)
        self.assertEqual(facts["arp"]["opcode"], "Request")


class TestIsEnabled(unittest.TestCase):
    def setUp(self):
        self._orig = os.environ.pop("ANTHROPIC_API_KEY", None)
        ai_explainer._dotenv_loaded = True  # skip real .env lookup during this test

    def tearDown(self):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        if self._orig is not None:
            os.environ["ANTHROPIC_API_KEY"] = self._orig
        ai_explainer._dotenv_loaded = False

    def test_disabled_when_no_key(self):
        self.assertFalse(ai_explainer.is_enabled())

    def test_enabled_when_key_set(self):
        os.environ["ANTHROPIC_API_KEY"] = "sk-test-fake-key"
        self.assertTrue(ai_explainer.is_enabled())


class TestDotenvLoading(unittest.TestCase):
    def test_loads_key_from_dotenv_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dotenv_path = os.path.join(tmp, ".env")
            with open(dotenv_path, "w") as f:
                f.write("ANTHROPIC_API_KEY=sk-from-dotenv\n")

            # Point the loader at our temp project root by monkeypatching
            # the module-level path logic via a direct call with the same
            # shape it uses internally.
            os.environ.pop("ANTHROPIC_API_KEY", None)
            ai_explainer._dotenv_loaded = False
            original_file = ai_explainer.__file__
            try:
                ai_explainer.__file__ = os.path.join(tmp, "backend", "ai_explainer.py")
                ai_explainer._load_dotenv()
                self.assertEqual(os.environ.get("ANTHROPIC_API_KEY"), "sk-from-dotenv")
            finally:
                ai_explainer.__file__ = original_file
                os.environ.pop("ANTHROPIC_API_KEY", None)
                ai_explainer._dotenv_loaded = False


if __name__ == "__main__":
    unittest.main()
