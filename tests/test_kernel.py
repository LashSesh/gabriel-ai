"""Kernel invariants (AT20, AT21 representation parts), ported from the executed blueprint reference and extended."""
from dataclasses import FrozenInstanceError
import hashlib
import unittest

from gabriel_agent.kernel import (Artifact, assess_goal, candidate, check_evidence, gate_decision, goal, snapshot, select_candidate, complete, progress_vector)
from gabriel_agent.contracts.codec import MAX_INT, canonical, loads as _loads
from gabriel_agent.contracts import CodecError


def parse_envelope(raw):
    try:
        return _loads(raw)
    except CodecError as exc:
        raise ValueError(str(exc))
#


def identity(value):
    return hashlib.sha256(value.encode("ascii")).hexdigest()


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.profile = identity("registered-test-profile-v1")
        self.oracle = identity("registered-test-oracle-v1")
        self.policy = identity("registered-test-policy-v1")
        self.blob = Artifact("document content: \u00fc".encode("utf8"))
        self.params = Artifact(canonical({"tolerance_hex": "0x1.0p-20"}))
        self.g = goal("software", self.profile, self.params.ref(),
                      {"a": self.oracle, "b": self.oracle})
        self.s = snapshot("software", self.profile, {"input": self.blob.ref()}, 7)

    def evidence(self, key="a", **changes):
        args = dict(goal_id=self.g.id, obligation=key, snapshot_id=self.s.id,
                    oracle=self.oracle, profile=self.profile, outcome="passed",
                    scope="supported", execution="observed", result=self.blob.ref())
        args.update(changes)
        return check_evidence(**args)

    def assess(self, records=None, **changes):
        args = dict(goal_spec=self.g, current_snapshot=self.s,
                    evidence=records if records is not None else
                    [self.evidence("a"), self.evidence("b")])
        args.update(changes)
        return assess_goal(**args).json()

    def proposal(self, kind="modify", **changes):
        args = dict(goal_id=self.g.id, snapshot_id=self.s.id,
                    action_kind=kind, target=self.blob.ref(), payload=self.params.ref())
        args.update(changes)
        return candidate(**args)

    def gate(self, c, decision="permit", **changes):
        args = dict(candidate_id=c.id, goal_id=self.g.id, snapshot_id=self.s.id,
                    policy=self.policy, decision=decision)
        args.update(changes)
        return gate_decision(**args)

    def select(self, candidates, gates, ranks):
        return select_candidate(candidates, gates, ranks, self.g, self.s, self.policy)

    def test_three_domain_labels_share_only_representation(self):
        for domain in ("software", "documents", "numeric"):
            with self.subTest(domain=domain):
                g = goal(domain, self.profile, self.params.ref(), {"requirement": self.oracle})
                s = snapshot(domain, self.profile, {"input": self.blob.ref()}, 7)
                e = check_evidence(g.id, "requirement", s.id, self.oracle,
                                   self.profile, "passed", "supported", "observed", self.blob.ref())
                self.assertTrue(assess_goal(g, s, [e]).json()["satisfied"])
                c = candidate(g.id, s.id, "transform", self.blob.ref(), self.params.ref())
                d = gate_decision(c.id, g.id, s.id, self.policy, "permit")
                self.assertEqual(select_candidate([c], [d], {c.id: 0}, g, s, self.policy), c)

    def test_all_mandatory_obligations_required(self):
        self.assertTrue(self.assess()["satisfied"])
        a = self.assess([self.evidence("a")])
        self.assertEqual(a["outcome"], "not_run")
        self.assertFalse(a["satisfied"])

    def test_zero_priority_or_quantized_distance_cannot_complete(self):
        # Even a proposed routing record saying zero deficit/weight is irrelevant.
        for routing in ({"weight": 0, "distance_raw": 0},
                        {"weight": MAX_INT, "distance_raw": 0}):
            routing_blob = Artifact(canonical(routing))
            c = self.proposal(payload=routing_blob.ref())
            self.assertEqual(self.select([c], [self.gate(c)], {c.id: 0}), c)
            self.assertFalse(self.assess([self.evidence("a")])["satisfied"])

    def test_missing_or_wrong_oracle_is_invalid(self):
        for oracle in (None, identity("unregistered")):
            with self.subTest(oracle=oracle):
                a = self.assess([self.evidence("a", oracle=oracle), self.evidence("b")])
                self.assertEqual(a["scope"], "invalid")
                self.assertFalse(a["satisfied"])

    def test_stale_snapshot_invalidates_prior_pass(self):
        later = snapshot("software", self.profile, {"input": self.blob.ref()}, 8)
        a = self.assess(current_snapshot=later)
        self.assertEqual(a["scope"], "invalid")
        self.assertFalse(a["satisfied"])

    def test_dry_run_and_synthetic_pass_are_not_observed_passes(self):
        for execution in ("dry_run", "synthetic"):
            a = self.assess([self.evidence("a", execution=execution), self.evidence("b")])
            self.assertEqual(a["outcome"], "not_run")
            self.assertFalse(a["satisfied"])

    def test_wrong_domain_or_profile_cannot_borrow_evidence(self):
        for s in (snapshot("documents", self.profile, {}, 7),
                  snapshot("software", identity("other-profile"), {}, 7)):
            self.assertFalse(self.assess(current_snapshot=s)["satisfied"])
        a = self.assess([self.evidence("a", profile=identity("wrong")), self.evidence("b")])
        self.assertEqual(a["scope"], "invalid")

    def test_duplicate_evidence_does_not_increase_support(self):
        a = self.assess([self.evidence("a"), self.evidence("a"), self.evidence("b")])
        self.assertEqual(a["scope"], "invalid")
        self.assertIn("duplicate_evidence:a", a["issues"])
        self.assertFalse(a["satisfied"])

    def test_assessment_identity_binds_passed_receipts_not_just_verdict(self):
        a, b = self.evidence("a"), self.evidence("b")
        changed = self.evidence("a", result=Artifact(b"different oracle output").ref())
        first = assess_goal(self.g, self.s, [a, b])
        repeated = assess_goal(self.g, self.s, [a, b])
        reversed_order = assess_goal(self.g, self.s, [b, a])
        different_result = assess_goal(self.g, self.s, [changed, b])
        self.assertTrue(first.json()["satisfied"])
        self.assertTrue(different_result.json()["satisfied"])
        self.assertEqual(first.id, repeated.id)
        self.assertEqual(first.id, reversed_order.id)
        self.assertNotEqual(first.id, different_result.id)
        self.assertEqual(first.json()["evidence_ids"], sorted([a.id, b.id]))

    def test_assessment_identity_retains_rejected_and_duplicate_inputs(self):
        a, b = self.evidence("a"), self.evidence("b")
        foreign = self.evidence("unknown")
        batch = [foreign, a, a, b]
        assessed = assess_goal(self.g, self.s, batch)
        self.assertFalse(assessed.json()["satisfied"])
        self.assertEqual(assessed.json()["evidence_ids"],
                         sorted([foreign.id, a.id, a.id, b.id]))
        self.assertEqual(assessed.id, assess_goal(self.g, self.s, list(reversed(batch))).id)
        self.assertNotEqual(assessed.id, assess_goal(self.g, self.s, [foreign, a, b]).id)

    def test_unknown_obligation_is_invalid(self):
        a = self.assess([self.evidence("a"), self.evidence("b"), self.evidence("unknown")])
        self.assertEqual(a["scope"], "invalid")
        self.assertFalse(a["satisfied"])

    def test_supported_failures_and_nondecisions_are_distinct(self):
        for outcome in ("failed", "inconclusive", "not_run"):
            a = self.assess([self.evidence("a", outcome=outcome), self.evidence("b")])
            self.assertEqual(a["outcome"], outcome)
            self.assertEqual(a["scope"], "supported")
            self.assertFalse(a["satisfied"])

    def test_scope_does_not_turn_invalid_pass_into_success(self):
        for scope in ("out_of_scope", "invalid"):
            a = self.assess([self.evidence("a", scope=scope), self.evidence("b")])
            self.assertEqual(a["scope"], scope)
            self.assertFalse(a["satisfied"])

    def test_proposed_snapshot_never_becomes_observed_by_hashing(self):
        proposed = snapshot("software", self.profile, {"input": self.blob.ref()}, 7, "proposed")
        self.assertNotEqual(self.s.id, proposed.id)
        records = [self.evidence(k, snapshot_id=proposed.id) for k in ("a", "b")]
        self.assertFalse(self.assess(records, current_snapshot=proposed)["satisfied"])
        c = self.proposal(proposed_state=proposed.id)
        self.assertEqual(self.select([c], [self.gate(c)], {c.id: 5}), c)
        self.assertEqual(self.s.json()["state"], "observed")
        self.assertEqual(self.s.json()["inputs"], {"input": self.blob.ref()})

    def test_rejected_high_rank_never_selected(self):
        good, bad = self.proposal("modify"), self.proposal("delete")
        got = self.select([bad, good], [self.gate(bad, "reject"), self.gate(good)],
                          {bad.id: MAX_INT, good.id: -7})
        self.assertEqual(got, good)

    def test_missing_gate_or_inconclusive_gate_gives_no_candidate(self):
        c = self.proposal()
        for receipts in ([], [self.gate(c, "inconclusive")], [self.gate(c, "reject")]):
            self.assertIsNone(self.select([c], receipts, {c.id: MAX_INT}))

    def test_stale_gate_or_wrong_policy_does_not_authorize(self):
        c = self.proposal()
        for receipt in (self.gate(c, snapshot_id=identity("stale")),
                        self.gate(c, policy=identity("other-policy"))):
            self.assertIsNone(self.select([c], [receipt], {c.id: 1}))

    def test_all_semantic_candidate_fields_bind_identity(self):
        base = self.proposal()
        variants = [self.proposal("delete"), self.proposal("create"),
                    self.proposal(snapshot_id=identity("other-snapshot")),
                    self.proposal(goal_id=identity("other-goal")),
                    self.proposal(payload=Artifact(b"other").ref()),
                    self.proposal(target=Artifact(b"other").ref()),
                    self.proposal(proposed_state=identity("proposed"))]
        self.assertEqual(len({base.id, *(x.id for x in variants)}), len(variants) + 1)

    def test_ranking_ties_use_stable_identifier(self):
        a, b = self.proposal("modify"), self.proposal("delete")
        receipts = [self.gate(a), self.gate(b)]
        expected = min((a, b), key=lambda x: x.id)
        for order in ([a, b], [b, a]):
            self.assertEqual(self.select(order, receipts, {a.id: 0, b.id: 0}), expected)

    def test_duplicates_unknown_gate_and_noninteger_rank_rejected(self):
        a, b = self.proposal("modify"), self.proposal("delete")
        for candidates, receipts, ranks in (
            ([a, a], [self.gate(a)], {a.id: 0}),
            ([a], [self.gate(a), self.gate(a)], {a.id: 0}),
            ([a], [self.gate(b)], {a.id: 0}),
            ([a], [], {a.id: 0, b.id: 0}),
            ([a], [], {a.id: True}), ([a], [], {a.id: 0.0})):
            with self.assertRaises(ValueError):
                self.select(candidates, receipts, ranks)

    def test_artifact_immutability_and_hash_copy(self):
        with self.assertRaises(FrozenInstanceError):
            self.g.raw = b"changed"
        copy = self.g.json()
        copy["obligations"].clear()
        self.assertEqual(len(self.g.json()["obligations"]), 2)
        self.assertEqual(self.blob.ref()["sha256"], hashlib.sha256(self.blob.raw).hexdigest())

    def test_canonical_encoder_strictness(self):
        self.assertEqual(canonical({"b": 1, "a": False}), b'{"a":false,"b":1}')
        self.assertNotEqual(canonical({"a": True}), canonical({"a": 1}))
        for bad in (1.0, float("nan"), MAX_INT + 1, "\u00fc", {1: "x"}, (1,)):
            with self.assertRaises(ValueError):
                canonical(bad)
        for raw in (b'{"a":1,"a":2}', b'{"a":1.0}', b'{"a":"\\u00fc"}'):
            with self.assertRaises(ValueError):
                parse_envelope(raw)

    def test_empty_goal_and_boolean_frontier_are_rejected(self):
        with self.assertRaises(ValueError):
            goal("software", self.profile, self.params.ref(), {})
        with self.assertRaises(ValueError):
            snapshot("software", self.profile, {}, True)


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)


class CompletionTests(ContractTests):
    def test_completion_requires_assessment_artifacts_and_effects(self):
        a = assess_goal(self.g, self.s, [self.evidence("a"), self.evidence("b")])
        self.assertTrue(complete(a, True, True))
        self.assertFalse(complete(a, False, True))
        self.assertFalse(complete(a, True, False))
        partial = assess_goal(self.g, self.s, [self.evidence("a")])
        self.assertFalse(complete(partial, True, True))
        with self.assertRaises(ValueError):
            complete(a, 1, True)

    def test_progress_vector_is_diagnostic_only(self):
        a = assess_goal(self.g, self.s, [self.evidence("a", outcome="failed")])
        self.assertEqual(progress_vector(a), {"passed": 0, "failed": 1, "inconclusive": 0, "not_run": 1, "issues": 0})
        self.assertFalse(a.json()["satisfied"])

    def test_kernel_contract_identity_differs_from_reference(self):
        self.assertEqual(self.g.json()["contract"], "gabriel.kernel/1")
