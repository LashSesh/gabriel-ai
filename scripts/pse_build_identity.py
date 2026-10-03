#!/usr/bin/env python3
"""Record the build identity of the native PSE executables: toolchain, lockfile digest, digest of
the bound source set (manifests, examples, crate sources), executable digests and the arithmetic
profile. Usage: .venv/bin/python scripts/pse_build_identity.py --output evidence/pse/build_identity.json
The executables must have been built with
  cargo build --locked --release --manifest-path native_pse/Cargo.toml --example engine_observer --example engine_snapshot --example engine_readout
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from gabriel_agent.adapters import native_graph  # noqa: E402

SHIPPED = {"engine_observer": "629b13f23fad4a4e8142eb7345e5bb2ca36dce508fb364758d76050d096300b1"}  # the inherited Linux binary, for comparison only


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bound_sources() -> dict:
    native = ROOT / "native_pse"
    files = [native / "Cargo.toml", native / "Cargo.lock"] + sorted(native.glob("examples/*.rs")) + sorted(native.glob("src/**/*.rs")) + \
        sorted(native.glob("crates/*/Cargo.toml")) + sorted(native.glob("crates/*/src/**/*.rs"))
    return {str(p.relative_to(ROOT)): sha(p) for p in files if p.is_file()}


def locked_version(name: str) -> str:
    lines = (ROOT / "native_pse" / "Cargo.lock").read_text().splitlines()
    for index, line in enumerate(lines):
        if line.strip() == 'name = "%s"' % name and index + 1 < len(lines) and lines[index + 1].startswith("version = "):
            return name + " " + lines[index + 1].split('"')[1]
    return name + " (not locked)"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    binaries = native_graph.binaries()
    if set(binaries) != set(native_graph.BINARIES):
        print("executables missing: " + ", ".join(sorted(set(native_graph.BINARIES) - set(binaries))), file=sys.stderr)
        return 2
    sources = bound_sources()
    record = {"schema": "gabriel.evidence.pse-build/2", "platform": platform.platform(), "machine": platform.machine(),
              "toolchain": {"cargo": subprocess.check_output(["cargo", "--version"], text=True).strip(), "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip()},
              "command": "cargo build --locked --release --manifest-path native_pse/Cargo.toml --example engine_observer --example engine_snapshot --example engine_readout",
              "arithmetic_profile": native_graph.ARITHMETIC, "libm_crate": locked_version("libm"),
              "cargo_lock_sha256": sha(ROOT / "native_pse" / "Cargo.lock"), "bound_source_files": len(sources),
              "bound_source_set_sha256": hashlib.sha256(json.dumps(sources, sort_keys=True).encode("ascii")).hexdigest(),
              "executables": {name: {"sha256": entry["sha256"], "bytes": entry["bytes"]} for name, entry in sorted(binaries.items())},
              "worker_build": native_graph.worker_build(binaries), "shipped_for_comparison": SHIPPED}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    print(json.dumps({k: record[k] for k in ("arithmetic_profile", "executables", "bound_source_files", "bound_source_set_sha256")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
