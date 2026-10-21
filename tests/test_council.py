"""[TESTS / council] Ballots, blackboard, member specs, every protocol, failures, parallelism."""
from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from hybrid_agent.backends import BackendUnavailable, CannedBackend
from hybrid_agent.core.config import Config
from hybrid_agent.council import (Blackboard, Council, CouncilError, MemberSpec, PROTOCOLS, parse_ballot,
                                  tally)


def cfg(**kw) -> Config:
    tmp = Path(tempfile.mkdtemp())
    return Config(backend="scripted", workspace=tmp / "ws", log_dir=tmp / "logs", **kw)


class Down(CannedBackend):
    def chat(self, *a, **k):
        raise BackendUnavailable("server down")


class Slow(CannedBackend):
    active = 0
    peak = 0
    lock = threading.Lock()

    def chat(self, *a, **k):
        with Slow.lock:
            Slow.active += 1
            Slow.peak = max(Slow.peak, Slow.active)
        time.sleep(0.15)
        with Slow.lock:
            Slow.active -= 1
        return super().chat(*a, **k)


class BallotTests(unittest.TestCase):
    def test_parse(self):
        b = parse_ballot("m", "Reasons...\nVOTE: **Option B**\nCONFIDENCE: 80%", ["Option A", "Option B"])
        self.assertEqual((b.choice, b.confidence), ("Option B", 0.8))
        self.assertEqual(parse_ballot("m", "vote: yes, definitely", ["Yes", "No"]).choice, "Yes")
        self.assertIsNone(parse_ballot("m", "no vote here", ["Yes"]).choice)
        self.assertEqual(parse_ballot("m", "VOTE: Yes\nCONFIDENCE: 7").confidence, 0.07)

    def test_tally_modes(self):
        ballots = [parse_ballot("a", "VOTE: A\nCONFIDENCE: 0.9", ["A", "B"]),
                   parse_ballot("b", "VOTE: B\nCONFIDENCE: 0.3", ["A", "B"]),
                   parse_ballot("c", "VOTE: B\nCONFIDENCE: 0.3", ["A", "B"]),
                   parse_ballot("d", "abstain", ["A", "B"])]
        self.assertEqual(tally(ballots, "majority").winner, "B")
        w = tally(ballots, "weighted")
        self.assertEqual(w.winner, "A")
        self.assertEqual(w.abstentions, ["d"])
        tie = tally(ballots[1:2] + [parse_ballot("x", "VOTE: A\nCONFIDENCE: 0.3", ["A", "B"])])
        self.assertTrue(tie.tie)
        self.assertIsNone(tie.winner)


class BlackboardTests(unittest.TestCase):
    def test_thread_safe_posting(self):
        board = Blackboard()
        threads = [threading.Thread(target=lambda i=i: [board.post(f"m{i}", "x") for _ in range(50)])
                   for i in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len(board), 400)
        self.assertEqual(sorted(e["id"] for e in board.entries()), list(range(1, 401)))
        self.assertIn("m3", board.render(last=400))


class MemberSpecTests(unittest.TestCase):
    def test_validation(self):
        self.assertEqual(MemberSpec.from_dict({"name": "a", "role": "skeptic"}).tool_profile(), "readonly")
        with self.assertRaises(ValueError):
            MemberSpec.from_dict({"name": "a", "role": "wizard"})
        with self.assertRaises(ValueError):
            MemberSpec.from_dict({"name": "a", "colour": "red"})
        with self.assertRaises(ValueError):
            Council([MemberSpec("a"), MemberSpec("a")], cfg())

    def test_members_get_role_tools_plus_board(self):
        c = Council.from_config(None, cfg())
        skeptic = c.members["skeptic"].agent.tools
        self.assertIn("board_post", skeptic)
        self.assertNotIn("run_shell", skeptic)            # read-only role
        self.assertIn("run_shell", c.members["engineer"].agent.tools)
        self.assertEqual(c.chair, "chair")
        self.assertNotIn("chair", c.participants)


class ProtocolTests(unittest.TestCase):
    def test_every_protocol_runs(self):
        c = Council.from_config(None, cfg())
        for name in PROTOCOLS:
            r = c.deliberate("Should we do X?", protocol=name, rounds=2)
            self.assertTrue(r.final_answer, name)
            self.assertTrue(r.contributions, name)
            self.assertTrue(r.to_markdown().startswith(f"# Council session: {name}"))

    def test_roundtable_uses_tools_and_board(self):
        r = Council.from_config(None, cfg()).deliberate("Q?", protocol="roundtable")
        kinds = [(c.member, c.kind) for c in r.contributions]
        self.assertIn(("chair", "synthesis"), kinds)
        self.assertEqual(sum(1 for _, k in kinds if k == "opening"), 3)
        self.assertTrue(any(e["topic"] == "status" for e in r.board), "members should post via board_post")

    def test_debate_stops_early_on_consensus(self):
        r = Council.from_config(None, cfg()).deliberate("Q?", protocol="debate", rounds=4, options=["Only"])
        self.assertTrue(r.tally["consensus"])
        self.assertFalse([c for c in r.contributions if c.kind == "rebuttal"])

    def test_vote_proposes_options_when_missing(self):
        r = Council.from_config(None, cfg()).deliberate("Q?", protocol="vote")
        self.assertEqual(r.options, ["Option A", "Option B"])
        self.assertIsNotNone(r.tally)

    def test_failed_member_sits_out(self):
        specs = [MemberSpec("chair", "chair"), MemberSpec("ok", "researcher"),
                 MemberSpec("broken", "skeptic", backend=Down("broken"))]
        r = Council(specs, cfg()).deliberate("Q?", protocol="roundtable")
        errs = [c for c in r.contributions if c.error]
        self.assertEqual([c.member for c in errs], ["broken"])
        self.assertTrue(r.final_answer)

    def test_all_members_down_raises(self):
        specs = [MemberSpec("chair", "chair"), MemberSpec("x", backend=Down("x"))]
        with self.assertRaises(CouncilError):
            Council(specs, cfg()).deliberate("Q?")

    def test_chair_failure_falls_back_to_positions(self):
        specs = [MemberSpec("chair", "chair", backend=Down("chair")), MemberSpec("a"), MemberSpec("b")]
        r = Council(specs, cfg()).deliberate("Q?")
        self.assertIn("could not synthesise", r.final_answer)

    def test_parallel_workers(self):
        Slow.peak = 0
        specs = [MemberSpec("chair", "chair", backend=Slow("chair"))] + \
                [MemberSpec(f"m{i}", backend=Slow(f"m{i}")) for i in range(3)]
        start = time.monotonic()
        Council(specs, cfg(), workers=3).deliberate("Q?", protocol="roundtable")
        self.assertGreaterEqual(Slow.peak, 2)
        self.assertLess(time.monotonic() - start, 3)

    def test_config_file_and_save(self):
        data = {"protocol": "debate", "rounds": 1, "chair": "boss",
                "members": [{"name": "boss", "role": "chair"}, {"name": "x", "role": "analyst", "weight": 2}]}
        c = Council.from_config(data, cfg())
        self.assertEqual(c.chair, "boss")
        r = c.deliberate("Q?")
        self.assertEqual(r.protocol, "debate")
        path = r.save(Path(tempfile.mkdtemp()))
        self.assertTrue(path.exists() and path.with_suffix(".json").exists())

    def test_example_config_is_valid(self):
        root = Path(__file__).resolve().parent.parent
        for f in (root / "examples").glob("*.json"):
            Council.from_config(f, cfg())


if __name__ == "__main__":
    unittest.main()
