"""Release metadata for a G1 build (WP12).

Binds the source commit, package source identities, the dependency lock of
the tested environment, supported platform/backend, schema registry and
catalog identities and the executed acceptance evidence. It never relabels a
specification check as product acceptance: extension gates (G2/G3) are
listed as not established.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

from .. import __version__
from ..contracts.codec import canonical
from ..contracts.schemas import registry_digest
from ..state.reducer import reducer_identity


def _git(root, *args):
    try:
        return subprocess.check_output(["git", "-C", str(root)] + list(args), text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, OSError):
        return None


def _pip_freeze(python: str) -> list:
    try:
        out = subprocess.check_output([python, "-m", "pip", "freeze", "--exclude-editable"], text=True, stderr=subprocess.DEVNULL)
        return sorted(line.strip() for line in out.splitlines() if line.strip())
    except (subprocess.CalledProcessError, OSError):
        try:
            out = subprocess.check_output(["uv", "pip", "freeze", "--python", python], text=True, stderr=subprocess.DEVNULL)
            return sorted(line.strip() for line in out.splitlines() if line.strip() and not line.startswith("-e"))
        except (subprocess.CalledProcessError, OSError):
            return []


def _license_status(root: Path) -> dict:
    candidates = [p for p in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING") if (root / p).is_file()]
    native = [str(p.relative_to(root)) for p in (root / "native_pse").glob("LICENSE*")] if (root / "native_pse").is_dir() else []
    declared = None
    try:
        import tomllib
        declared = tomllib.loads((root / "pyproject.toml").read_text()).get("project", {}).get("license", {}).get("text")
    except (OSError, ValueError, AttributeError):
        declared = None
    return {"root_license_files": candidates, "subdirectory_license_files": native, "declared": declared,
            "status": "resolved" if candidates and declared and not str(declared).startswith("LicenseRef-") else "unresolved",
            "note": "The root license governs the original software and manuscript materials; bundled external datasets keep their own "
                    "attribution and terms (data/ATTRIBUTION.md), and a subdirectory license covers only its subtree."}


def release_manifest(root: Path, *, evidence: dict | None = None, python: str = sys.executable, catalog_digest: str | None = None,
                     doctor: dict | None = None) -> dict:
    root = Path(root)
    sources = {}
    for path in sorted((root / "src").rglob("*")):
        if path.is_file() and path.suffix in (".py", ".json"):
            sources[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    package_identity = hashlib.sha256(canonical(sources)).hexdigest()
    manifest = {
        "schema": "gabriel.release-manifest/1",
        "version": __version__,
        "created_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source_commit": _git(root, "rev-parse", "HEAD"),
        "source_branch": _git(root, "rev-parse", "--abbrev-ref", "HEAD"),
        "source_dirty": bool(_git(root, "status", "--porcelain")),
        "package_source_identity": package_identity,
        "package_source_files": len(sources),
        "schema_registry_digest": registry_digest(),
        "reducer_identity": reducer_identity(),
        "catalog_digest": catalog_digest,
        "dependency_lock": _pip_freeze(python),
        "python": platform.python_version(),
        "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "supported_backends": {"linux_namespace": "supported containment backend; requires Linux user namespaces, util-linux unshare and setpriv; "
                                                  "verified by gabriel doctor --selftest on the release host",
                               "trusted_local": "explicitly separate trusted mode without containment; opt-in only"},
        "doctor": doctor,
        "license": _license_status(root),
        "acceptance_evidence": evidence or {},
        "gates": {"G0": "holds: inherited runtime checks rerun (evidence/wp01)",
                  "G1": "established on the release host for one provider and fifteen synthetic repository-repair tasks in five families "
                        "(evidence/live, evidence/wp11, evidence/wp12); advantage gate (AT17) executed under three frozen protocols and not passed",
                  "G2": "established on the release host for the three fixture task families: repository repair, source-grounded document "
                        "amendment and numerical transformation run through one owner/scheduler/policy build with registered domain observers "
                        "and independent oracles (AT23, evidence/wp10/at23); memory and analytical adapters per AT14-AT16 and AT25 (tests); the native "
                        "PSE graph engine integrated as a contained analytical worker with independent references and separate measurements "
                        "(ADR-18, evidence/pse); "
                        "advantage gate (AT17) executed on the document and numerical families under protocol 5 (evidence/wp14) and not passed; "
                        "the associative memory layer (ADR-20) executed under protocol 6b (evidence/wp15): the engine's walk over verified co-citations "
                        "carried the required source in every needed run including the held-out family (10/10 against 0/10 for the provenance view) "
                        "and cost two of six unneeded runs (the declared harm bound of one was exceeded); under protocol 7 (ADR-21) carried sources "
                        "say in the prompt why they are there, which kept every needed outcome, brought the unneeded family to the provenance view's "
                        "level against the unlabeled control, and made the associative view the document pack's default as declared; since ADR-23 "
                        "the history is projected onto the retrieval's own candidates (a withdrawn or unauthorized source erodes from it, "
                        "evidence/wp16) and every retained retrieval manifest recomputes from the chain at its own frontier and access policy revision",
                  "G3": "established in the blueprint's scoped sense (ADR-22, evidence/wp15): on the association distribution, with the document "
                        "pack's declared progress channels, a readout trained on 48 retained decisions of the system's own runs met the declared "
                        "held-out criterion on two unseen topics (equal verified success, 2836 against 5425 mean tokens, no false completion), its "
                        "held-out decision loss was 0.045 against the rule's 6.91, and the memory's promotion rule admitted it; it ships pinned as "
                        "the document pack's default routing policy with its provenance; it learned one legible fact (stop when the unmet claim's "
                        "expected source was not retrieved), can only stop a repair earlier than the rule, and stopped one recoverable repair on a "
                        "seen task; protocol 4 on the hard tier (evidence/wp13) had trained no readout and rejected the episodic ablation; under "
                        "protocol 10 (ADR-24, evidence/wp17) the same route ran on the numerical pack with its own declared channels: the readout met "
                        "the held-out criterion (equal verified success, 1329 against 2357 tokens, decision loss 0.109 against 3.45 on decisions of "
                        "both classes) and the memory's promotion rule declined it (held-out support 4 against 4 refutations), so the numerical pack "
                        "keeps the rule-based default"},
        "known_issues": ([] if _license_status(root)["status"] == "resolved" else ["root license unresolved"]) +
                        ["a catalog, registry or reducer change needs an explicit migration (gabriel migrate: backup, equivalence replay, recorded epoch); "
                         "journals created before catalog records existed migrate only when the running code reproduces them",
                         "single-host, single-user deployment only",
                         "the native PSE executables are built from source per host (cargo); without them native graph operations are refused at "
                         "proposal time, and without python-flint window certificates are unknown (never success)",
                         "the native engine's arithmetic is platform-independent by construction (pure-Rust libm, ADR-19) but was executed on this "
                         "platform only; the engine's crystal and consensus paths remain quarantined and the state readout is a specified model "
                         "quantity, not a measurement",
                         "advantage over a simple verification loop not shown; the evaluation corpus is saturated for gpt-4.1-mini",
                         "the associative view (ADR-20, the document pack's default since ADR-21) carries sources that verified runs cited together "
                         "into a budgeted prompt whether or not the task needs them; the prompt says why each is there, which under protocol 7 kept "
                         "gpt-4.1-mini from stating the forbidden figure (6/6 first attempts without the reason, 0/6 with it) but cost two repairs on "
                         "one needed task; two providers of one vendor (gpt-4.1-mini, gpt-5-mini; protocol 9), one presentation; the lexical seeds "
                         "are tie-broken by observation id; the history erodes by declared withdrawal and authorization only (ADR-23), never by time, "
                         "and a withdrawal declared by one task is re-admitted by a later task that declares the source available",
                         "the document pack's default routing policy is a readout promoted on one constructed distribution with one provider "
                         "(ADR-22) and transferred with fixed weights to a second provider of the same vendor (protocol 9); it can only stop a "
                         "repair earlier than the rule, it abstains where its declared channels are missing, and it stopped one recoverable "
                         "repair on a seen task under gpt-4.1-mini; a task that pins rule-based-v1 explicitly opts out",
                         "the numerical pack declares progress channels (ADR-24) but ships no readout: its protocol 10 candidate met the held-out "
                         "criterion and the memory's promotion rule declined it on a held-out composition half of which is hopeless by construction; "
                         "a numerical task runs the rule-based policy, and a readout bound to its layout abstains at a failed node before any "
                         "reference verification ran"],
    }
    return manifest


def write_release_manifest(root: Path, path: Path, **kw) -> dict:
    manifest = release_manifest(root, **kw)
    Path(path).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
