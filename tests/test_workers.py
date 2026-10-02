"""WP05: containment helpers, registry, worktrees, backends and supervisor crash windows (AT08 host parts, AT12, AT13, AT24 parts)."""
import hashlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from gabriel_agent.contracts import GabrielError, Code, loads, canonical
from gabriel_agent.contracts.rules import approval_digest
from gabriel_agent.tools import ToolRegistry, fingerprint_of, fs
from gabriel_agent.workers import (RunSpec, TrustedLocalBackend, LinuxNamespaceBackend, Worktree, Supervisor, SupervisorCrash,
                                   backend_for)

from .fake_targets import IdempotentTarget, NonIdempotentTarget, fake_registry
from .harness import World, tool, usage, sha


# ---------------------------------------------------------------- filesystem containment

def test_contained_root_rejects_escapes_and_symlinks(tmp_path):
    root = tmp_path / "root"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.txt").write_text("a")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    os.symlink(outside, root / "src" / "link.txt")
    os.symlink(tmp_path, root / "escape")
    with fs.ContainedRoot(str(root)) as c:
        assert c.read("src/a.txt") == b"a"
        for bad in ("/etc/passwd", "../outside.txt", "src/../../outside.txt", "src//a.txt", "", "src/./a.txt"):
            with pytest.raises(GabrielError) as info:
                c.read(bad)
            assert info.value.code is Code.POLICY_DENIED, bad
        with pytest.raises(GabrielError):
            c.read("src/link.txt")          # symlink leaf
        with pytest.raises(GabrielError):
            c.read("escape/outside.txt")    # symlink directory component
        with pytest.raises(GabrielError):
            c.write("escape/new.txt", b"x")
        with pytest.raises(GabrielError):
            c.write("src/link.txt", b"x")
        assert outside.read_text() == "secret"
        c.write("src/deep/new.txt", b"new")
        assert c.read("src/deep/new.txt") == b"new" and c.exists("src/deep/new.txt")
        manifest = c.manifest()
        assert manifest["src/link.txt"]["kind"] == "symlink" and manifest["escape"]["kind"] == "symlink"
        assert manifest["src/a.txt"]["sha256"] == hashlib.sha256(b"a").hexdigest()
        c.delete("src/deep/new.txt")
        assert not c.exists("src/deep/new.txt")
    assert fs.path_in_scope("src/a.txt", ["src/"]) and not fs.path_in_scope("tests/a.txt", ["src"])
    assert fs.path_in_scope("anything", [""])


# ---------------------------------------------------------------- registry

def test_registry_fingerprints_and_visible_catalog():
    registry = fake_registry(IdempotentTarget(), NonIdempotentTarget())
    catalog = registry.catalog()
    assert set(catalog["tools"]) == {"fixture.read", "fixture.write", "fixture.external", "fixture.keyed"}
    assert all(registry.verify_loaded().values())
    descriptor, impl = registry.tool("fixture.write")
    assert descriptor["implementation_fingerprint"] == fingerprint_of(impl)
    assert fingerprint_of(impl) != fingerprint_of(registry.tool("fixture.read")[1])
    grant = {"grant_id": "g", "tool_ids": ["fixture.read"], "effect_classes": ["read"]}
    visible = registry.visible_catalog(grant)
    assert [t["tool_id"] for t in visible["tools"]] == ["fixture.read"]
    with pytest.raises(GabrielError):
        registry.tool("tool.unknown")
    with pytest.raises(GabrielError):
        registry.register_tool(tool("fixture.read", "read"), impl)
    record = registry.catalog_record("c")
    assert record["schema"] == "gabriel.catalog/1" and len(record["tools"]) == 4


# ---------------------------------------------------------------- worktrees

def make_repo(path: Path) -> str:
    path.mkdir(parents=True)
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@invalid", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@invalid")
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True, env=env)
    (path / "src").mkdir()
    (path / "src" / "mod.py").write_text("def f():\n    return 1\n")
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True, env=env)
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def test_worktree_pin_manifest_and_patch(tmp_path):
    repo = tmp_path / "repo"
    base = make_repo(repo)
    wt = Worktree.create(repo, base, tmp_path / "wt" / "run-01")
    assert wt.head() == base
    manifest = wt.manifest()
    assert "src/mod.py" in manifest and ".git" not in manifest
    (wt.path / "src" / "mod.py").write_text("def f():\n    return 2\n")
    (wt.path / "src" / "new.py").write_text("x = 1\n")
    assert wt.changed_paths() == ["src/mod.py", "src/new.py"]
    patch = wt.patch().decode()
    assert "+    return 2" in patch and "new.py" in patch
    assert (repo / "src" / "mod.py").read_text() == "def f():\n    return 1\n"  # user tree untouched
    with pytest.raises(GabrielError):
        Worktree.create(repo, base[:7], tmp_path / "wt" / "short")
    with pytest.raises(GabrielError):
        Worktree.create(repo, base, tmp_path / "wt" / "run-01")
    wt.remove()
    assert not wt.path.exists()


# ---------------------------------------------------------------- trusted_local backend

def test_trusted_local_capture_timeout_and_descendant_report(tmp_path):
    backend = TrustedLocalBackend()
    probe = backend.probe()
    assert probe["available"] and probe["containment"] is False
    with pytest.raises(GabrielError):
        backend_for("trusted_local")  # explicit opt-in required
    marker = "gabriel-marker-" + os.urandom(4).hex()
    witness = backend.run(RunSpec(argv=[sys.executable, "-c", "import os,sys; sys.stdout.write('x'*5000); print(os.environ.get('SECRET_TOKEN','none'), file=sys.stderr)"],
                                  worktree=str(tmp_path), max_output_bytes=1000, marker=marker, env={"SECRET_TOKEN": "visible-only-if-allowlisted"}))
    assert witness.exit_code == 0 and witness.stdout.truncated and witness.stdout.total_bytes == 5000
    assert len(witness.stdout.captured) == 1000
    assert witness.stdout.full_sha256 == hashlib.sha256(b"x" * 5000).hexdigest()
    assert witness.stderr.captured.strip() == b"visible-only-if-allowlisted"
    assert witness.descendants_cleaned is True and witness.network == "unrestricted_host"
    os.environ["GABRIEL_TEST_LEAK"] = "leaked"
    try:
        witness = backend.run(RunSpec(argv=[sys.executable, "-c", "import os;print(os.environ.get('GABRIEL_TEST_LEAK','scrubbed'))"], worktree=str(tmp_path)))
    finally:
        del os.environ["GABRIEL_TEST_LEAK"]
    assert witness.stdout.captured.strip() == b"scrubbed"  # ambient environment is not inherited
    started = time.monotonic()
    witness = backend.run(RunSpec(argv=["sleep", "30"], worktree=str(tmp_path), timeout_ms=300))
    assert witness.timed_out and witness.signal == 9 and time.monotonic() - started < 10
    witness = backend.run(RunSpec(argv=["/nonexistent/binary"], worktree=str(tmp_path)))
    assert witness.start_failure and witness.exit_code is None
    # a daemonized descendant survives in trusted_local mode and the witness says so
    marker = "gabriel-marker-" + os.urandom(4).hex()
    witness = backend.run(RunSpec(argv=["sh", "-c", "sleep 20 >/dev/null 2>&1 & echo started"], worktree=str(tmp_path), marker=marker))
    try:
        assert witness.exit_code == 0 and witness.descendants_cleaned is False
    finally:
        subprocess.run(["pkill", "-9", "-f", "sleep 20"], check=False)
    record = witness.to_record({"sha256": "0" * 64, "bytes": 0, "media_type": "text/plain"}, {"sha256": "0" * 64, "bytes": 0, "media_type": "text/plain"})
    from gabriel_agent.contracts import validate
    validate(record, "run-witness")


def test_namespace_backend_probe_is_non_mutating():
    probe = LinuxNamespaceBackend().probe()
    assert probe["backend"] == "linux_namespace" and probe["checks"]["jail_selftest"] == "not_executed"
    assert isinstance(probe["available"], bool)


@pytest.mark.containment
def test_namespace_jail_isolation_selftest(tmp_path):
    """Privileged: creates namespaces, mounts a tmpfs root and pivots into it."""
    backend = LinuxNamespaceBackend()
    probe = backend.probe(selftest=True)
    assert probe["available"], probe
    (tmp_path / "wt").mkdir()
    (tmp_path / "wt" / "hello.txt").write_text("hi")
    (tmp_path / "secret.txt").write_text("host secret")
    marker = "gabriel-marker-" + os.urandom(4).hex()
    code = ("import os, socket, sys\n"
            "print('cwd', os.getcwd()); print('files', sorted(os.listdir('.')))\n"
            "print('home_visible', os.path.exists('/home'), 'root_visible', os.path.exists('/root'), 'secret', os.path.exists('/secret.txt'))\n"
            "print('caps', open('/proc/self/status').read().split('CapEff:')[1].split()[0])\n"
            "s = socket.socket()\n"
            "try:\n    s.settimeout(2); s.connect(('1.1.1.1', 443)); print('net ok')\nexcept Exception as e:\n    print('net blocked', type(e).__name__)\n"
            "try:\n    open('/usr/bin/zzz', 'w'); print('usr writable')\nexcept Exception as e:\n    print('usr readonly', type(e).__name__)\n"
            "open('written.txt', 'w').write('from jail')\n"
            "os.system('sleep 30 >/dev/null 2>&1 &')\n"
            "print('pid', os.getpid())\n")
    witness = backend.run(RunSpec(argv=["/usr/bin/python3", "-c", code], worktree=str(tmp_path / "wt"), marker=marker, timeout_ms=30000))
    out = witness.stdout.captured.decode()
    assert witness.exit_code == 0, (out, witness.stderr.captured.decode())
    assert "cwd /work" in out and "home_visible False" in out and "secret False" in out
    assert "caps 0000000000000000" in out and "net blocked" in out and "usr readonly" in out
    assert (tmp_path / "wt" / "written.txt").read_text() == "from jail"
    assert witness.descendants_cleaned is True
    witness = backend.run(RunSpec(argv=["sleep", "30"], worktree=str(tmp_path / "wt"), timeout_ms=500, marker=marker))
    assert witness.timed_out and witness.descendants_cleaned is True


# ---------------------------------------------------------------- supervisor crash windows

def build(tmp_path, crash_after_io=None):
    idem, non = IdempotentTarget(), NonIdempotentTarget()
    registry = fake_registry(idem, non, crash_after_io)
    w = World(tmp_path, catalog=registry.catalog())
    w.admit(); w.start()
    plan = w.plan_record([w.node("observe", "fixture.read", outputs=("snapshot",)),
                          w.node("write", "fixture.write", depends_on=["observe"], check_ids=["oracle", "output-valid"], retry_class="reconcile_before_retry"),
                          w.node("keyed", "fixture.keyed", depends_on=["observe"], retry_class="target_idempotent_retry"),
                          w.node("external", "fixture.external", depends_on=["observe"], retry_class="never")])
    w.accept_plan(plan)
    sup = Supervisor(w.owner, w.store, registry, w.cred)
    return w, registry, sup, idem, non


def verify_node(w, node_id):
    """Submit the structural assessments that a completed node needs to become verified."""
    projection = w.owner.projection("run-01")
    state = projection["nodes"][node_id]
    node = next(n for n in projection["plan"]["nodes"] if n["node_id"] == node_id)
    snapshot = projection["run_meta"]["observed_snapshot_ref"]
    for check_id in node["check_ids"]:
        verifier = "owner.output_valid" if check_id == "output-valid" else "fixture.oracle"
        w.assess(check_id, [snapshot, state["result_ref"]], verifier=verifier)


def crash_at(stage_name):
    def hook(stage):
        if stage == stage_name:
            raise SupervisorCrash(stage)
    return hook


def test_supervisor_dispatch_happy_path_and_receipt_retry(tmp_path):
    w, registry, sup, idem, non = build(tmp_path)
    intent, _ = w.issue("observe")
    result, receipt = sup.dispatch(intent, {})
    assert receipt["event_kind"] == "ResultAccepted" and result["status"] == "completed"
    projection = w.owner.projection("run-01")
    assert projection["nodes"]["observe"]["status"] == "completed" and projection["run_meta"]["observed_snapshot_ref"] is not None
    assert sup.port_calls == 1
    # the owner's exact-retry semantics hold for the supervisor's own command ids
    again = w.owner.submit(w.command("accept_result", loads(w.store.get(projection["attempts"][intent["attempt_id"]]["result_ref"])),
                                     "task-01", "run-01", 4, command_id="result-" + intent["attempt_id"]), credential=w.cred)
    assert canonical(again) == canonical(receipt)


def test_crash_before_marker_abandons_lease_without_io(tmp_path):
    w, registry, sup, idem, non = build(tmp_path)
    i0, _ = w.issue("observe"); sup.dispatch(i0, {}); verify_node(w, "observe")
    sup.hooks = {"before_marker": crash_at("before_marker")}
    intent, _ = w.issue("write")
    with pytest.raises(SupervisorCrash):
        sup.dispatch(intent, {"value": "v1"})
    assert idem.calls == []
    attempt = w.owner.projection("run-01")["attempts"][intent["attempt_id"]]
    assert attempt["status"] == "issued"
    sup.hooks = {}
    actions = sup.recover("run-01")
    assert actions == [{"attempt_id": intent["attempt_id"], "action": "lease_abandoned_before_marker"}]
    projection = w.owner.projection("run-01")
    assert projection["nodes"]["write"]["status"] == "pending" and projection["ledger"]["reserved"]["tool_attempts"] == 0
    intent2, _ = w.issue("write")
    sup.dispatch(intent2, {"value": "v1"})
    assert idem.calls == [("apply", intent2["idempotency_key"])]


def test_crash_after_marker_before_io_reconciles_by_status(tmp_path):
    w, registry, sup, idem, non = build(tmp_path)
    i0, _ = w.issue("observe"); sup.dispatch(i0, {}); verify_node(w, "observe")
    sup.hooks = {"after_marker": crash_at("after_marker")}
    intent, _ = w.issue("keyed", target="provider-01")
    with pytest.raises(SupervisorCrash):
        sup.dispatch(intent, {"value": "v1"})
    assert idem.calls == []
    assert w.owner.projection("run-01")["attempts"][intent["attempt_id"]]["status"] == "marked"
    sup.hooks = {}
    actions = sup.recover("run-01")
    assert actions[0]["action"] == "marked_without_result_recorded_unknown"
    assert actions[1]["outcome"] == "confirmed_not_executed" and actions[1]["method"] == "target_status_by_key"
    projection = w.owner.projection("run-01")
    assert projection["run"]["unresolved_effect_ids"] == [] and projection["nodes"]["keyed"]["status"] == "pending"
    assert idem.calls == [("status", intent["idempotency_key"])]  # no blind re-execution
    intent2, _ = w.issue("keyed", target="provider-01")
    sup.dispatch(intent2, {"value": "v1"})
    assert len(idem.log) == 1


def test_crash_after_io_before_result_commit_idempotent_target(tmp_path):
    holder = {}

    def crash():
        raise SupervisorCrash("after_io_inside_tool")
    w, registry, sup, idem, non = build(tmp_path, crash_after_io=crash)
    i0, _ = w.issue("observe"); sup.dispatch(i0, {}); verify_node(w, "observe")
    intent, _ = w.issue("keyed", target="provider-01")
    # the tool raised after the target applied the effect: the supervisor records the attempt as failed/unknown
    result, receipt = sup.dispatch(intent, {"value": "v1"})
    assert result["status"] == "failed" and result["effect_outcome"] == "outcome_unknown"
    projection = w.owner.projection("run-01")
    assert projection["run"]["unresolved_effect_ids"] == [intent["intent_id"]]
    assert idem.log == {intent["idempotency_key"]: "v1"}
    action = sup.reconcile(intent)
    assert action["outcome"] == "confirmed_success"
    projection = w.owner.projection("run-01")
    assert projection["run"]["unresolved_effect_ids"] == [] and projection["nodes"]["keyed"]["status"] == "failed"
    assert projection["nodes"]["keyed"]["last_failure"] == "confirmed_success_without_result"
    assert idem.calls.count(("apply", intent["idempotency_key"])) == 1


def test_non_idempotent_unknown_outcome_never_retried_blindly(tmp_path):
    def crash():
        raise SupervisorCrash("after_io_inside_tool")
    w, registry, sup, idem, non = build(tmp_path, crash_after_io=crash)
    i0, _ = w.issue("observe"); sup.dispatch(i0, {}); verify_node(w, "observe")
    intent = w.intent_record("external", target="worktree-01")
    w.owner.register_approval(intent, w.cred)
    approved = dict(intent, approval_digest=approval_digest(intent))
    w.submit("issue_intent", approved)
    result, receipt = sup.dispatch(approved, {})
    assert result["effect_outcome"] == "outcome_unknown" and non.count == 1
    action = sup.reconcile(approved)
    assert action["outcome"] == "still_unknown" and action["method"] == "manual_review"
    projection = w.owner.projection("run-01")
    assert projection["run"]["unresolved_effect_ids"] == [approved["intent_id"]]
    assert projection["nodes"]["external"]["status"] == "failed"
    with pytest.raises(GabrielError):  # retry_class never: no second attempt can be issued
        w.issue("external", target="worktree-01")
    assert non.count == 1


def test_crash_after_result_commit_before_ack_is_idempotent_on_retry(tmp_path):
    w, registry, sup, idem, non = build(tmp_path)
    sup.hooks = {"after_result_commit": crash_at("after_result_commit")}
    intent, _ = w.issue("observe")
    with pytest.raises(SupervisorCrash):
        sup.dispatch(intent, {})
    projection = w.owner.projection("run-01")
    assert projection["attempts"][intent["attempt_id"]]["status"] == "completed"
    sup.hooks = {}
    assert sup.recover("run-01") == []  # nothing is possibly-executed: the result is committed
    assert sup.port_calls == 1


def test_late_result_after_lease_expiry_matches_prior_attempt(tmp_path):
    w, registry, sup, idem, non = build(tmp_path)
    i0, _ = w.issue("observe"); sup.dispatch(i0, {}); verify_node(w, "observe")
    intent, _ = w.issue("write")
    w.mark(intent)
    w.time[0] += 10_000_000
    assert [a["attempt_id"] for a in w.owner.expired_attempts()] == [intent["attempt_id"]]
    actions = sup.recover("run-01")
    assert actions[0]["action"] == "marked_without_result_recorded_unknown" and actions[1]["outcome"] == "confirmed_not_executed"
    # the late result from the old attempt arrives afterwards: matched, retained, never a new attempt
    late = w.result_record(intent)
    receipt = w.submit("accept_result", late)
    assert "audit fact" in " ".join(receipt["notes"])
    projection = w.owner.projection("run-01")
    assert len(projection["attempts"]) == 2 and projection["late_results"][0]["attempt_id"] == intent["attempt_id"]
