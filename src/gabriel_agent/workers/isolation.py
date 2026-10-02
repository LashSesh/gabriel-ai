"""Worker isolation backends.

``linux_namespace`` is the supported containment backend: user, mount, PID,
network, IPC and UTS namespaces, a tmpfs root with read-only system binds,
``pivot_root``, capability drop with ``no_new_privs``, resource limits,
no network, and SIGKILL of the whole PID namespace on timeout or cancel.

``trusted_local`` is an explicitly separate mode: a plain subprocess in a
new session with resource limits and a scrubbed environment. It is not
containment and is refused for untrusted execution unless the workspace
opts in. Output capture retains a bounded prefix, the total byte count and
a digest over the full stream so truncation is visible, never hidden.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import resource
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..contracts.errors import Code, GabrielError
import re as _re


def _ident(*parts) -> str:
    """Join parts into an ASCII identifier (letters, digits, '.', '_', ':', '-')."""
    text = ":".join(str(p) for p in parts)
    text = _re.sub(r"[^A-Za-z0-9._:-]", "-", text)
    return text[:128] if text and text[0].isalnum() else ("x" + text)[:128]

ENV_ALLOWLIST_DEFAULT = ("LANG", "LC_ALL", "TZ")
BASE_ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8"}


@dataclass
class RunSpec:
    argv: list
    worktree: str                      # host path of the writable working tree
    cwd: str = "."                     # relative to the worktree
    timeout_ms: int = 60000
    max_output_bytes: int = 1 << 20
    env: dict = field(default_factory=dict)      # extra allowlisted variables (values are data, never secrets)
    rlimit_cpu_s: int = 300
    rlimit_as_bytes: int = 2 << 30
    rlimit_fsize_bytes: int = 256 << 20
    rlimit_nofile: int = 256
    ro_binds: list = field(default_factory=list)  # extra host directories visible read-only (namespace backend)
    marker: str = ""                   # unique token placed in the environment for descendant detection


@dataclass
class Stream:
    captured: bytes
    total_bytes: int
    full_sha256: str
    truncated: bool
    capture_limit_bytes: int


@dataclass
class RunWitness:
    argv: list
    cwd: str
    exit_code: int | None
    signal: int | None
    timed_out: bool
    duration_ms: int
    backend_kind: str
    backend_identity: str
    stdout: Stream
    stderr: Stream
    env_allowlist: list
    network: str
    descendants_cleaned: bool | None
    rlimits: list
    start_failure: str | None = None

    def to_record(self, stdout_ref: dict, stderr_ref: dict) -> dict:
        def stream(s, ref):
            return {"captured_ref": ref, "total_bytes": s.total_bytes, "full_sha256": s.full_sha256,
                    "truncated": s.truncated, "capture_limit_bytes": s.capture_limit_bytes}
        return {"schema": "gabriel.run-witness/1", "argv": list(self.argv), "cwd": self.cwd, "exit_code": self.exit_code,
                "signal": self.signal, "timed_out": self.timed_out, "duration_ms": self.duration_ms,
                "backend_identity": self.backend_identity, "backend_kind": self.backend_kind,
                "stdout": stream(self.stdout, stdout_ref), "stderr": stream(self.stderr, stderr_ref),
                "env_allowlist": list(self.env_allowlist), "network": self.network,
                "descendants_cleaned": self.descendants_cleaned, "rlimits": list(self.rlimits),
                "start_failure": self.start_failure}


class _Reader(threading.Thread):
    """Drain a pipe completely: bounded prefix retained, full stream digested."""

    def __init__(self, stream, limit):
        super().__init__(daemon=True)
        self.stream, self.limit = stream, limit
        self.chunks, self.total, self.digest = [], 0, hashlib.sha256()
        self.kept = 0
        self.start()

    def run(self):
        try:
            while True:
                chunk = self.stream.read(65536)
                if not chunk:
                    break
                self.digest.update(chunk)
                self.total += len(chunk)
                if self.kept < self.limit:
                    take = chunk[:self.limit - self.kept]
                    self.chunks.append(take)
                    self.kept += len(take)
        finally:
            self.stream.close()

    def result(self) -> Stream:
        self.join()
        return Stream(b"".join(self.chunks), self.total, self.digest.hexdigest(), self.total > self.limit, self.limit)


def _rlimit_list(spec: RunSpec):
    return ["cpu=%ds" % spec.rlimit_cpu_s, "as=%d" % spec.rlimit_as_bytes, "fsize=%d" % spec.rlimit_fsize_bytes,
            "nofile=%d" % spec.rlimit_nofile]


def _scrubbed_env(spec: RunSpec) -> tuple[dict, list]:
    env = dict(BASE_ENV)
    allow = []
    for key in ENV_ALLOWLIST_DEFAULT:
        if key in os.environ:
            env[key] = os.environ[key]
            allow.append(key)
    for key, value in spec.env.items():
        if not key.isidentifier() or not isinstance(value, str) or not value.isascii():
            raise GabrielError(Code.POLICY_DENIED, "worker environment entries must be ASCII identifiers/values", obj=key)
        env[key] = value
        allow.append(key)
    if spec.marker:
        env["GABRIEL_WORKER_MARKER"] = spec.marker
    return env, sorted(set(allow))


def descendants_alive(marker: str) -> bool:
    """Scan /proc for any process still carrying the marker in its environment or cmdline."""
    if not marker:
        return False
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        for name in ("environ", "cmdline"):
            try:
                data = Path("/proc", pid, name).read_bytes()
            except OSError:
                continue
            if marker.encode() in data:
                return True
    return False


class TrustedLocalBackend:
    """Explicitly separate trusted-local mode: supervision, not containment."""
    kind = "trusted_local"

    def identity(self) -> str:
        return _ident("trusted_local", "python-" + platform.python_version(), platform.machine())

    def probe(self) -> dict:
        return {"backend": self.kind, "available": True, "containment": False,
                "reasons": ["plain subprocess in a new session; no filesystem, network or credential boundary"],
                "checks": {"python": sys.executable}}

    def run(self, spec: RunSpec) -> RunWitness:
        env, allow = _scrubbed_env(spec)
        cwd = os.path.join(spec.worktree, spec.cwd)

        def limits():
            resource.setrlimit(resource.RLIMIT_CPU, (spec.rlimit_cpu_s, spec.rlimit_cpu_s))
            resource.setrlimit(resource.RLIMIT_AS, (spec.rlimit_as_bytes, spec.rlimit_as_bytes))
            resource.setrlimit(resource.RLIMIT_FSIZE, (spec.rlimit_fsize_bytes, spec.rlimit_fsize_bytes))
            resource.setrlimit(resource.RLIMIT_NOFILE, (spec.rlimit_nofile, spec.rlimit_nofile))
        started = time.monotonic()
        try:
            proc = subprocess.Popen(spec.argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, start_new_session=True, preexec_fn=limits)
        except OSError as exc:
            empty = Stream(b"", 0, hashlib.sha256(b"").hexdigest(), False, spec.max_output_bytes)
            return RunWitness(spec.argv, spec.cwd, None, None, False, 0, self.kind, self.identity(), empty, empty, allow,
                              "unrestricted_host", None, _rlimit_list(spec), start_failure=str(exc)[:500])
        out, err = _Reader(proc.stdout, spec.max_output_bytes), _Reader(proc.stderr, spec.max_output_bytes)
        timed_out = False
        try:
            proc.wait(timeout=spec.timeout_ms / 1000)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        duration = int((time.monotonic() - started) * 1000)
        code = proc.returncode
        exit_code, sig = (code, None) if code >= 0 else (None, -code)
        cleaned = None if not spec.marker else not descendants_alive(spec.marker)
        return RunWitness(spec.argv, spec.cwd, exit_code, sig, timed_out, duration, self.kind, self.identity(),
                          out.result(), err.result(), allow, "unrestricted_host", cleaned, _rlimit_list(spec))


class LinuxNamespaceBackend:
    """Supported containment: unshare(1) namespaces plus the in-namespace init in jail_init."""
    kind = "linux_namespace"
    UNSHARE_FLAGS = ["--user", "--map-root-user", "--mount", "--pid", "--fork", "--kill-child=SIGKILL",
                     "--net", "--ipc", "--uts", "--propagation", "private"]

    def __init__(self, unshare="unshare", python=None):
        self.unshare = unshare
        self.python = python or sys.executable

    def identity(self) -> str:
        return _ident("linux_namespace", platform.release(), platform.machine(), "python-" + platform.python_version())

    def probe(self, selftest: bool = False) -> dict:
        """Non-mutating availability probe. ``selftest`` additionally runs a jailed
        process (mounts, pivot_root, capability drop) and is only done on request."""
        checks, reasons = {}, []
        checks["platform"] = sys.platform
        if sys.platform != "linux":
            reasons.append("Linux kernel namespaces are required")
        for tool in (self.unshare, "setpriv"):
            path = shutil.which(tool)
            checks[tool] = path
            if path is None:
                reasons.append("missing util-linux tool: " + tool)
        try:
            proc = subprocess.run([self.unshare] + self.UNSHARE_FLAGS + ["--", "true"], capture_output=True, text=True, timeout=20)
            checks["unshare_namespaces"] = proc.returncode == 0
            if proc.returncode != 0:
                reasons.append("cannot create user/mount/pid/net/ipc/uts namespaces: " + proc.stderr.strip()[:300])
        except (OSError, subprocess.SubprocessError) as exc:
            checks["unshare_namespaces"] = False
            reasons.append("unshare probe failed: " + str(exc)[:200])
        checks["jail_selftest"] = "not_executed"
        if selftest and not reasons:
            witness = self.run(RunSpec(argv=["/usr/bin/env", "python3", "-c", "import os,socket\nprint('pid', os.getpid())\n"
                                             "s=socket.socket()\ntry:\n  s.settimeout(1); s.connect(('127.0.0.1', 9))\n  print('net ok')\nexcept Exception as e:\n  print('net blocked', type(e).__name__)"],
                                       worktree=str(Path.cwd()), timeout_ms=30000, max_output_bytes=4096))
            checks["jail_selftest"] = {"exit_code": witness.exit_code, "stdout": witness.stdout.captured.decode("utf8", "replace")[:300],
                                       "start_failure": witness.start_failure}
            if witness.exit_code != 0 or b"net blocked" not in witness.stdout.captured:
                reasons.append("jail self-test did not confirm isolation")
        return {"backend": self.kind, "available": not reasons, "containment": not reasons, "reasons": reasons,
                "checks": checks, "identity": self.identity()}

    def run(self, spec: RunSpec) -> RunWitness:
        env, allow = _scrubbed_env(spec)
        config = {"argv": spec.argv, "worktree": os.path.realpath(spec.worktree), "cwd": spec.cwd, "env": env,
                  "rlimits": {"cpu": spec.rlimit_cpu_s, "as": spec.rlimit_as_bytes, "fsize": spec.rlimit_fsize_bytes,
                              "nofile": spec.rlimit_nofile},
                  "ro_binds": [os.path.realpath(p) for p in spec.ro_binds], "hostname": "gabriel-worker"}
        src_root = str(Path(__file__).resolve().parents[2])
        launcher_env = dict(os.environ, PYTHONPATH=src_root, PYTHONDONTWRITEBYTECODE="1")
        argv = [self.unshare] + self.UNSHARE_FLAGS + ["--", self.python, "-m", "gabriel_agent.workers.jail_init"]
        started = time.monotonic()
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    env=launcher_env, start_new_session=True)
        except OSError as exc:
            empty = Stream(b"", 0, hashlib.sha256(b"").hexdigest(), False, spec.max_output_bytes)
            return RunWitness(spec.argv, spec.cwd, None, None, False, 0, self.kind, self.identity(), empty, empty, allow,
                              "none", None, _rlimit_list(spec), start_failure=str(exc)[:500])
        proc.stdin.write(json.dumps(config).encode("utf8"))
        proc.stdin.close()
        out, err = _Reader(proc.stdout, spec.max_output_bytes), _Reader(proc.stderr, spec.max_output_bytes)
        timed_out = False
        try:
            proc.wait(timeout=spec.timeout_ms / 1000)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                os.killpg(proc.pid, signal.SIGKILL)  # kills unshare; --kill-child kills the PID-namespace init
            except ProcessLookupError:
                pass
            proc.wait()
        duration = int((time.monotonic() - started) * 1000)
        code = proc.returncode
        exit_code, sig = (code, None) if code >= 0 else (None, -code)
        stderr = err.result()
        start_failure = None
        if exit_code == 124 and b"GABRIEL_JAIL_SETUP_FAILED" in stderr.captured:
            start_failure = stderr.captured.decode("utf8", "replace")[-500:]
        cleaned = not descendants_alive(spec.marker) if spec.marker else None
        return RunWitness(spec.argv, spec.cwd, exit_code, sig, timed_out, duration, self.kind, self.identity(),
                          out.result(), stderr, allow, "none", cleaned, _rlimit_list(spec), start_failure=start_failure)


def backend_for(name: str, allow_trusted_local: bool = False):
    if name == "linux_namespace":
        return LinuxNamespaceBackend()
    if name == "trusted_local":
        if not allow_trusted_local:
            raise GabrielError(Code.POLICY_DENIED, "trusted_local execution requires the explicit workspace opt-in allow_trusted_local")
        return TrustedLocalBackend()
    raise GabrielError(Code.UNSUPPORTED, "unknown containment backend " + name)


def probe_backends() -> dict:
    return {"linux_namespace": LinuxNamespaceBackend().probe(), "trusted_local": TrustedLocalBackend().probe()}
