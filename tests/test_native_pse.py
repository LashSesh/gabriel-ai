"""ADR-18: the native PSE graph engine as a contained numerical worker (graph.snapshot,
graph.region_mass, graph.window_reachability): independent references, direct/hosted
equivalence, complete bindings and honest verdicts. Nothing here grants the native code a claim
it has not earned: the references are scipy, a closed-form harmonic model and a reconstruction
of the declared construction rule."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from gabriel_agent.adapters import analytical, native_graph
from gabriel_agent.agent import TaskRunner, Workspace, export_task
from gabriel_agent.contracts.codec import loads
from gabriel_agent.domains.numerical import pack as numerical
from gabriel_agent.evaluation.fixtures import graph_walk as gw
from gabriel_agent.workers import TrustedLocalBackend
from gabriel_agent.workers.isolation import RunSpec

CONTAINMENT = os.environ.get("GABRIEL_CONTAINMENT_TESTS") == "1"
NATIVE = native_graph.available()
BIN = native_graph.binaries() if NATIVE else {}
needs_native = pytest.mark.skipif(not NATIVE, reason="native PSE executables not built: cargo build --locked --release --example engine_observer "
                                                     "--example engine_snapshot --manifest-path native_pse/Cargo.toml")
HISTORIES = (gw.BATCHES, gw.CLIQUE_BATCHES, [[3], [1, 3]], [[9, 2], [4], [2, 0]], [[7, 3, 5]], [[5]], [[0, 1], [1, 2], [2, 3], [3, 0], [0, 2]])


def scripted(script):
    return {"kind": "scripted", "script": script, "provider_id": "scripted-domains"}


def run_task(ws, spec, **extras):
    created = ws.create_task(spec)
    return created, TaskRunner(ws, created["task_id"], extras=extras).run()


def raw(dataset):
    return gw.text(dataset).encode("utf8")


def job_result(ws, created):
    node = ws.owner.projection(created["run_id"])["nodes"].get("run-job")
    return loads(ws.store.get(node["outputs"]["job_result"])) if node and "job_result" in node["outputs"] else None


# ------------------------------------------------------------------ independent references

@needs_native
def test_reference_model_reproduces_native_snapshot_identities_and_laplacians():
    for batches in HISTORIES:
        result = native_graph.run_job("graph.snapshot", {}, raw(gw.batches_dataset(batches)), BIN)
        assert result["verdict"] == "computed", result
        snapshot, engine = result["output"]["snapshot"], result["output"]["engine"]
        assert snapshot["identity"] == gw.reference_identity(batches)
        assert [v["entity"] for v in snapshot["vertices"]] == gw.vertex_order(batches)
        assert engine["ticks"] == len(batches) and engine["observations"] == sum(map(len, batches)) and engine["commits"] == 0 and not engine["faulted"]
        assert result["output"]["model"] == native_graph.MODEL and result["output"]["profile"] == native_graph.PROFILE_ID
        # the exact export (engine_snapshot) represents the same Laplacian as the reconstruction, bit for bit
        order, laplacian = gw.reference_laplacian(batches)
        source = [(entity, 1.0 if index == 0 else 0.0, 0.0) for index, entity in enumerate(order)]
        exported = native_graph.run_job("graph.window_reachability", {}, raw(gw.window_dataset(batches=batches, source=source, targets=[order[-1]])), BIN)
        assert exported["verdict"] == "computed" and exported["output"]["certificates"] is None, exported
        represented = exported["output"]["represented"]
        assert represented["identity"] == snapshot["identity"] and represented["entities"] == order
        assert [[native_graph.number(x) for x in row] for row in represented["laplacian_bits"]] == laplacian


def test_the_two_independent_references_agree():
    pytest.importorskip("scipy")
    for batches in HISTORIES:
        order = gw.vertex_order(batches)
        source = [(entity, 1.0 if index == 0 else 0.3, -0.2 * index) for index, entity in enumerate(order)]
        times = [0.0, 0.3, 1.0, 2.5, 7.0]
        stdlib = gw.reference_masses(batches, source, order[-1:], times, method="stdlib")
        scipy = gw.reference_masses(batches, source, order[-1:], times, method="scipy")
        assert max(abs(a - b) for a, b in zip(stdlib, scipy)) <= 1e-12, batches
        assert all(0.0 <= m <= 1.0 + 1e-12 for m in stdlib)


@needs_native
def test_region_mass_matches_the_scipy_reference_on_every_backend():
    pytest.importorskip("scipy")
    rows = gw.reference_mass_rows()
    assert max(abs(m - s) for (_, m, _), s in zip(rows, gw.reference_masses(gw.BATCHES, gw.SOURCE, gw.TARGETS, gw.TIMES, method="scipy"))) <= 1e-12
    outputs = {}
    for backend in native_graph.BACKENDS:
        result = native_graph.run_job("graph.region_mass", {}, raw(gw.query_dataset(backend=backend)), BIN)
        assert result["verdict"] == "computed", result
        values = result["output"]["values"]
        assert [v["time_bits"] for v in values] == [t for t, _, _ in rows]
        masses = [native_graph.number(v["mass_bits"]) for v in values]
        assert all(0.0 <= m <= 1.0 for m in masses)
        assert max(abs(m - m_ref) for m, (_, m_ref, _) in zip(masses, rows)) <= 1e-12
        assert [v["decision"] for v in values] == [d for _, _, d in rows]
        assert result["output"]["backend"] == backend and result["diagnostics"]["engine"]["commits"] == 0
        assert set(result["diagnostics"]["timings"]) == {"identity_validation_us", "native_process_us", "wire_bytes"}
        outputs[backend] = masses
    for a in outputs:
        for b in outputs:
            assert max(abs(x - y) for x, y in zip(outputs[a], outputs[b])) <= 1e-12
    # the decision rule is re-checked by the adapter: a mass just inside the deadband is ambiguous
    ambiguous = native_graph.run_job("graph.region_mass", {}, raw(gw.query_dataset(times=[2.0], threshold=rows[3][1], deadband=1e-6)), BIN)
    assert ambiguous["output"]["values"][0]["decision"] == "ambiguous"


@needs_native
def test_window_certificates_follow_the_closed_form_reference_and_declare_their_scope():
    pytest.importorskip("flint")
    stage_one = native_graph.run_job("graph.window_reachability", {}, gw.WINDOW_TEXT.encode("utf8"), BIN)
    assert stage_one["verdict"] == "computed" and stage_one["output"]["stage"] == "snapshot"
    certified = native_graph.certify(stage_one["output"])
    assert certified["statuses"] == gw.reference_window_statuses() == ["excluded", "reachable"]
    for certificate in certified["certificates"]:
        assert certificate["schema"] == "gabriel-clique-window-certificate/v1" and certificate["status"] in ("reachable", "excluded")
        assert certificate["evidence"]["method"] in ("endpoint_maximum", "rational_point", "critical_point", "stationary_exact", "global_amplitude_exact")
    assert certified["arithmetic"]["source_sha256"] == hashlib.sha256(Path(native_graph.__file__).with_name("window_certificate.py").read_bytes()).hexdigest()
    # the opposite outcome on the same first window at a lower threshold, again matching the reference
    lower = native_graph.run_job("graph.window_reachability", {}, raw(gw.window_dataset(threshold=0.1)), BIN)
    assert native_graph.certify(lower["output"])["statuses"] == gw.reference_window_statuses(threshold=0.1) == ["reachable", "reachable"]
    # a history outside the exact clique profile is declared out of scope, never guessed
    mixed = native_graph.run_job("graph.window_reachability", {}, gw.WINDOW_MIXED_TEXT.encode("utf8"), BIN)
    assert mixed["verdict"] == "computed"
    certified_mixed = native_graph.certify(mixed["output"])
    assert certified_mixed["statuses"] == ["out_of_scope", "out_of_scope"]
    assert "uniform clique" in certified_mixed["certificates"][0]["reason"]
    with pytest.raises(ValueError):
        gw.harmonic_coefficients(gw.BATCHES, gw.SOURCE, gw.TARGETS)


# ------------------------------------------------------------------ AT16 for the native worker: direct/hosted equivalence and scope

@needs_native
def test_direct_and_hosted_native_worker_agree_and_unsupported_inputs_abstain(tmp_path):
    direct = native_graph.run_job("graph.region_mass", {}, gw.QUERY_TEXT.encode("utf8"), BIN)
    assert direct["verdict"] == "computed"
    work = tmp_path / "work"
    (work / "data").mkdir(parents=True)
    (work / "data" / "query.json").write_text(gw.QUERY_TEXT)
    (work / ".gabriel_worker" / "bin").mkdir(parents=True)
    (work / ".gabriel_worker" / "native_worker.py").write_bytes(Path(native_graph.__file__).read_bytes())
    binaries = {}
    for name, entry in BIN.items():
        target = work / ".gabriel_worker" / "bin" / name
        target.write_bytes(Path(entry["path"]).read_bytes())
        target.chmod(0o755)
        binaries[name] = {"path": ".gabriel_worker/bin/" + name, "sha256": entry["sha256"]}
    (work / ".gabriel_worker" / "job.json").write_text(json.dumps({"operation": "graph.region_mass", "parameters": {}, "input_path": "data/query.json",
                                                                   "output_path": "out/mass.json", "result_path": ".gabriel_worker/result.json",
                                                                   "binaries": binaries, "max_input_bytes": native_graph.MAX_INPUT_BYTES}))
    witness = TrustedLocalBackend().run(RunSpec(argv=["python3", ".gabriel_worker/native_worker.py", ".gabriel_worker/job.json"], worktree=str(work),
                                                timeout_ms=60000, max_output_bytes=1 << 20, marker="t-native-hosted"))
    assert witness.exit_code == 0, witness.stderr.captured
    hosted = json.loads((work / ".gabriel_worker" / "result.json").read_text())
    assert hosted["verdict"] == "computed" and hosted["operation"] == "graph.region_mass"
    assert (work / "out" / "mass.json").read_bytes() == native_graph.dumps(direct["output"])
    assert hosted["output_sha256"] == hashlib.sha256(native_graph.dumps(direct["output"])).hexdigest()
    assert hosted["worker_build"] == numerical.worker_build("graph.region_mass") == native_graph.worker_build(BIN)
    assert hosted["input_sha256"] == hashlib.sha256(gw.QUERY_TEXT.encode("utf8")).hexdigest() and hosted["worker_us"] >= 0
    # the worker records the interpreter it ran under (the backend's python3), the job the host's: both are retained
    assert set(hosted["numerical_environment"]) == set(native_graph.numerical_environment()) and hosted["numerical_environment"]["float_model"] == "ieee754-binary64"
    # unsupported inputs abstain or reject; none is a success and none is a transport failure
    assert native_graph.run_job("graph.region_mass", {}, gw.BATCHES_TEXT.encode("utf8"), BIN)["verdict"] == "out_of_scope"
    assert native_graph.run_job("graph.snapshot", {}, gw.QUERY_TEXT.encode("utf8"), BIN)["verdict"] == "out_of_scope"
    assert native_graph.run_job("graph.region_mass", {"backend": "spectral_full"}, gw.QUERY_TEXT.encode("utf8"), BIN)["verdict"] == "invalid_input"
    assert native_graph.run_job("graph.snapshot", {}, b'{"kind": "series", "units": "degC", "values": []}', BIN)["verdict"] == "out_of_scope"
    assert native_graph.run_job("graph.snapshot", {}, b'{"kind": "graph", "vertices": 3, "edges": [[0, 1]]}', BIN)["verdict"] == "out_of_scope"
    assert native_graph.run_job("graph.snapshot", {}, b"\x00\xff", BIN)["verdict"] == "invalid_input"
    assert native_graph.run_job("graph.walk", {}, gw.QUERY_TEXT.encode("utf8"), BIN)["verdict"] == "invalid_input"
    too_many = raw(gw.batches_dataset([list(range(65))]))
    assert native_graph.run_job("graph.snapshot", {}, too_many, BIN)["verdict"] == "invalid_input"
    reversed_window = raw(gw.window_dataset(windows=[(2.0, 1.0)]))
    assert native_graph.run_job("graph.window_reachability", {}, reversed_window, BIN)["verdict"] == "invalid_input"
    zero_source = raw(gw.query_dataset(source=[(e, 0.0, 0.0) for e, _, _ in gw.SOURCE]))
    assert native_graph.run_job("graph.region_mass", {}, zero_source, BIN)["verdict"] == "invalid_input"
    assert native_graph.run_job("graph.snapshot", {}, gw.BATCHES_TEXT.encode("utf8"), {})["verdict"] == "unknown"
    # the standard-library worker keeps its own scope: a native dataset is out of scope for it
    assert analytical.run_job("graph.small_signature", {}, gw.QUERY_TEXT.encode("utf8"))["verdict"] == "out_of_scope"


@needs_native
def test_native_identity_and_contract_violations_are_rejected():
    observer = BIN["engine_observer"]
    tampered = {"engine_observer": {"path": observer["path"], "sha256": "0" * 64}}
    result = native_graph.run_job("graph.snapshot", {}, gw.BATCHES_TEXT.encode("utf8"), tampered)
    assert result["verdict"] == "invalid_input" and "identity mismatch" in result["diagnostics"]["reason"]
    job = {"schema": native_graph.OBSERVER_SCHEMA, "backend": "auto_region", "batches": gw.BATCHES,
           "queries": [{"source": gw.source_entries(), "targets": gw.TARGETS, "times_bits": [gw.bits(t) for t in gw.TIMES],
                        "threshold_bits": gw.bits(gw.THRESHOLD), "deadband_bits": gw.bits(gw.DEADBAND)}]}
    response = native_graph.invoke(observer["path"], observer["sha256"], job)
    native_graph.validate_observer_response(response, job)
    for mutate, message in [(lambda r: r["engine"].update(commits=1), "crystal"), (lambda r: r["engine"].update(faulted=True), "faulted"),
                            (lambda r: r["snapshot"].update(model="exp(-itL);L=D-A"), "model"),
                            (lambda r: r["query_results"][0]["values"][3].update(decision="below"), "decision"),
                            (lambda r: r["query_results"][0]["values"][0].update(mass_bits=gw.bits(1.5)), "outside"),
                            (lambda r: r.update(backend="spectral_full"), "contract")]:
        broken = json.loads(json.dumps(response))
        mutate(broken)
        with pytest.raises(ValueError, match=message):
            native_graph.validate_observer_response(broken, job)
    snapshot_binary = BIN["engine_snapshot"]
    exported = native_graph.invoke(snapshot_binary["path"], snapshot_binary["sha256"], {"schema": native_graph.SNAPSHOT_SCHEMA, "batches": gw.BATCHES})
    native_graph.laplacian_for_certificate(exported, gw.BATCHES)
    for mutate, message in [(lambda r: r["snapshot"].update(identity="0" * 64), "identity"),
                            (lambda r: r["snapshot"]["adjacency"][0].update(weight_bits=gw.bits(0.25)), "asymmetric"),
                            (lambda r: r["snapshot"]["vertices"][0].update(entity=9), "sensor vertex"),
                            (lambda r: r["engine"].update(commits=2), "committed")]:
        broken = json.loads(json.dumps(exported))
        mutate(broken)
        with pytest.raises(ValueError, match=message):
            native_graph.laplacian_for_certificate(broken, gw.BATCHES)
    with pytest.raises(ValueError, match="history"):
        native_graph.laplacian_for_certificate(exported, gw.CLIQUE_BATCHES)


def test_worker_build_and_cache_key_bind_the_native_executables():
    assert set(numerical.OPERATIONS) == set(analytical.OPERATIONS) | set(native_graph.OPERATIONS)
    assert all(numerical.is_native(op) for op in native_graph.OPERATIONS) and not numerical.is_native("graph.small_signature")
    assert numerical.worker_build() == hashlib.sha256(Path(analytical.__file__).read_bytes()).hexdigest()
    bound = {"engine_observer": {"sha256": "a" * 64}, "engine_snapshot": {"sha256": "b" * 64}}
    build = native_graph.worker_build(bound)
    assert build != numerical.worker_build()
    assert build != native_graph.worker_build({"engine_observer": {"sha256": "a" * 64}})  # a missing executable is a different build
    assert build != native_graph.worker_build(dict(bound, engine_snapshot={"sha256": "c" * 64}))
    if NATIVE:
        assert numerical.worker_build("graph.snapshot") == native_graph.worker_build(BIN) != build
    env = native_graph.numerical_environment()
    assert set(env) == {"python", "platform", "float_model"}
    digest = hashlib.sha256(gw.QUERY_TEXT.encode("utf8")).hexdigest()
    key = numerical.cache_key(digest, "graph.region_mass", {}, build, env)
    assert key != numerical.cache_key(digest, "graph.small_signature", {}, build, env)       # the profile differs
    assert key != numerical.cache_key(digest, "graph.region_mass", {}, native_graph.worker_build(dict(bound, engine_observer={"sha256": "d" * 64})), env)
    assert key != numerical.cache_key(digest, "graph.region_mass", {}, build, dict(env, python="0.0"))
    assert key != numerical.cache_key(hashlib.sha256(b"x").hexdigest(), "graph.region_mass", {}, build, env)


def test_native_datasets_are_described_without_computation():
    for relative, content in gw.TEXTS.items():
        description = native_graph.describe(content.encode("utf8"))
        assert description["format"] == "json" and description["kind"] in native_graph.KINDS and description["problems"] == [], relative
        assert analytical.describe(content.encode("utf8"))["kind"] == "unknown"  # the pack falls through to the native description
    bad = native_graph.describe(raw(gw.query_dataset(threshold=2.0)))
    assert bad["kind"] == "graph_query" and any("threshold" in p for p in bad["problems"])
    unknown = native_graph.describe(raw(dict(gw.query_dataset(), extra=1)))
    assert any("unknown fields" in p for p in unknown["problems"])
    assert native_graph.describe(b"[]")["kind"] == "unknown" and native_graph.describe(b"\xff")["format"] == "unsupported"


# ------------------------------------------------------------------ through the owner

@needs_native
def test_native_tasks_run_through_the_core_with_honest_verdicts(tmp_path):
    pytest.importorskip("flint")
    repo = tmp_path / "repo"
    base = gw.build_repo(repo)
    ws = Workspace.create(tmp_path / "ws", backend="trusted_local", allow_trusted_local=True)
    try:
        for operation in ("graph.snapshot", "graph.region_mass", "graph.window_reachability"):
            oracle = gw.write_oracle(tmp_path / ("oracle_%s.json" % operation), operation)
            created, summary = run_task(ws, gw.task_spec(repo, base, oracle, scripted(gw.script(operation)), operation))
            assert summary["state"] == "succeeded", (operation, summary["log"])
            outcomes = {a["check_id"]: a["outcome"] for a in summary["assessments"] if a["eligible"]}
            assert outcomes["reference"] == "passed" and outcomes["scope"] == "passed", operation
            result = job_result(ws, created)
            assert result["verdict"] == "computed" and result["status"] == "completed" and result["worker_build"] == native_graph.worker_build(BIN)
            job = loads(ws.store.get(result["job_ref"]))
            assert job["profile_id"] == native_graph.PROFILE_ID and job["parameters"] == {}
            written = json.loads((Path(created["worktree"]) / gw.OUTPUTS[operation]).read_text())
            assert written["profile"] == native_graph.PROFILE_ID and hashlib.sha256((Path(created["worktree"]) / gw.OUTPUTS[operation]).read_bytes()).hexdigest() == result["output_sha256"]
            if operation == "graph.window_reachability":
                assert written["stage"] == "certified" and written["statuses"] == gw.reference_window_statuses()
                diagnostics = json.loads(ws.store.get(result["diagnostics_ref"]).decode("utf8"))
                assert diagnostics["stage_two"]["status"] == "computed" and diagnostics["stage_two"]["elapsed_us"] >= 0 and diagnostics["stage_one_us"] >= 0
            assert not (Path(created["worktree"]) / ".gabriel_worker").exists()
            manifest = export_task(ws, created["task_id"], tmp_path / ("delivery-" + operation))
            assert manifest["run_state"] == "succeeded"
        # retained domain verdicts: the run fails, nothing claims success, no output is left behind
        oracle = gw.write_oracle(tmp_path / "oracle_mass.json", "graph.region_mass")
        for variant, verdict in (("window_mixed", "out_of_scope"), ("wrong_input_kind", "out_of_scope"), ("stdlib_on_native", "out_of_scope")):
            created, summary = run_task(ws, gw.task_spec(repo, base, oracle, scripted(gw.script(variant)), "graph.region_mass", max_plan_versions=1, max_repairs=0))
            assert summary["state"] == "failed", variant
            result = job_result(ws, created)
            assert result["verdict"] == verdict and result["output_ref"] is None and result["output_sha256"] is None, variant
            assert not (Path(created["worktree"]) / "out").exists() or not any((Path(created["worktree"]) / "out").iterdir()), variant
            if variant == "window_mixed":
                diagnostics = json.loads(ws.store.get(result["diagnostics_ref"]).decode("utf8"))
                assert diagnostics["stage_two"]["statuses"] == ["out_of_scope", "out_of_scope"]  # the certificates are retained as evidence
        # a parameter on a native operation is rejected before any execution
        created, summary = run_task(ws, gw.task_spec(repo, base, oracle, scripted(gw.script("with_parameters")), "graph.region_mass", max_plan_versions=1, max_repairs=0))
        assert summary["state"] == "failed" and job_result(ws, created) is None
        assert ws.owner.replay()["status"] == "passed"
    finally:
        ws.close()


@pytest.mark.containment
@pytest.mark.skipif(not CONTAINMENT, reason="set GABRIEL_CONTAINMENT_TESTS=1 to run the native worker inside the namespace jail")
@needs_native
def test_native_worker_runs_inside_the_namespace_jail(tmp_path):
    pytest.importorskip("flint")
    repo = tmp_path / "repo"
    base = gw.build_repo(repo)
    ws = Workspace.create(tmp_path / "ws", backend="linux_namespace")
    try:
        for operation in ("graph.region_mass", "graph.window_reachability"):
            oracle = gw.write_oracle(tmp_path / ("oracle_%s.json" % operation), operation)
            created, summary = run_task(ws, gw.task_spec(repo, base, oracle, scripted(gw.script(operation)), operation))
            assert summary["state"] == "succeeded", (operation, summary["log"])
            result = job_result(ws, created)
            assert result["containment"] is True and result["backend_kind"] == "linux_namespace" and result["verdict"] == "computed"
            assert not (Path(created["worktree"]) / ".gabriel_worker").exists()
        # the specified readout and its detections inside the jail (ADR-19)
        from gabriel_agent.evaluation.fixtures import graph_readout as gr
        repo_stream = tmp_path / "repo-stream"
        base_stream = gr.build_repo(repo_stream)
        for operation in ("graph.state_readout", "graph.detections"):
            oracle = gr.write_oracle(tmp_path / ("oracle_stream_%s.json" % operation), operation)
            created, summary = run_task(ws, gr.task_spec(repo_stream, base_stream, oracle, scripted(gr.script(operation)), operation))
            assert summary["state"] == "succeeded", (operation, summary["log"])
            result = job_result(ws, created)
            assert result["containment"] is True and result["verdict"] == "computed"
        assert ws.owner.replay()["status"] == "passed"
    finally:
        ws.close()


# ------------------------------------------------------------------ cross-implementation signature check

S7_CLASSES = Path(analytical.__file__).resolve().parents[3] / "native_pse" / "crates" / "pse-metatron" / "data" / "s7_classes.bin"


def s7_word(edges) -> int:
    """The inherited 21-bit edge word: edge (i, j), i < j, at bit j*(j-1)/2 + i (INDEXED_SIGNATURE.md)."""
    word = 0
    for a, b in edges:
        i, j = min(a, b), max(a, b)
        word |= 1 << (j * (j - 1) // 2 + i)
    return word


@pytest.mark.skipif(not S7_CLASSES.is_file(), reason="native S7 orbit index not present")
def test_small_signature_partition_agrees_with_the_native_s7_orbit_index():
    """The standard-library canonical adjacency (graph.small_signature) and the native engine's
    exhaustively verified S7 orbit index must induce the same isomorphism classes; the native
    index, padded to seven slots, cannot see the vertex count (the inherited collision)."""
    import itertools
    import random
    classes = S7_CLASSES.read_bytes()
    assert len(classes) == 2 * (1 << 21)

    def native_class(edges) -> int:
        word = s7_word(edges)
        return classes[2 * word] | (classes[2 * word + 1] << 8)

    def check(n, graphs):
        by_stdlib, by_native = {}, {}
        for edges in graphs:
            stdlib = analytical.canonical_adjacency(n, edges)
            native = native_class(edges)
            assert by_stdlib.setdefault(stdlib, native) == native, (n, edges)   # same stdlib class -> same native orbit
            assert by_native.setdefault(native, stdlib) == stdlib, (n, edges)   # same native orbit -> same stdlib class
        return len(by_stdlib)

    for n in (1, 2, 3, 4, 5):
        pairs = list(itertools.combinations(range(n), 2))
        graphs = [[list(pairs[k]) for k in range(len(pairs)) if mask >> k & 1] for mask in range(1 << len(pairs))]
        assert check(n, graphs) == {1: 1, 2: 2, 3: 4, 4: 11, 5: 34}[n]       # the known numbers of graphs up to isomorphism
    rng = random.Random(7)
    for n in (6, 7):
        pairs = list(itertools.combinations(range(n), 2))
        graphs = []
        for _ in range(48):
            mask = rng.getrandbits(len(pairs))
            edges = [list(pairs[k]) for k in range(len(pairs)) if mask >> k & 1]
            graphs.append(edges)
            permutation = list(range(n))
            rng.shuffle(permutation)
            graphs.append(sorted([sorted([permutation[a], permutation[b]]) for a, b in edges]))  # an isomorphic copy
        check(n, graphs)
    # the inherited defect: the native word has no vertex count, so a graph and the same graph with an
    # isolated vertex share an orbit while the retained signature keeps them apart
    assert native_class([[0, 1]]) == native_class([[0, 1]])
    small = analytical.run_job("graph.small_signature", {}, json.dumps({"kind": "graph", "vertices": 3, "edges": [[0, 1]]}).encode(), )
    larger = analytical.run_job("graph.small_signature", {}, json.dumps({"kind": "graph", "vertices": 4, "edges": [[0, 1]]}).encode())
    assert small["output"]["signature"] != larger["output"]["signature"]
    assert small["diagnostics"]["legacy_padded_signature"] == larger["diagnostics"]["legacy_padded_signature"]


# ------------------------------------------------------------------ the graph tier of the corpus

def test_graph_tier_is_sound_and_frozen_protocols_keep_their_digests():
    from gabriel_agent.evaluation import corpus, corpus_domains as cd
    report = cd.check_all("graph")
    assert len(report) == 10 and all(item["sound"] for item in report), [(i["task_id"], i["controls"]) for i in report if not i["sound"]]
    assert {item["family"] for item in report} == {"graph-snapshot", "graph-mass", "graph-window", "graph-readout", "graph-detections"}
    assert all(task.domain == "numerical" and task.tier == "graph" for task in cd.GRAPH_TASKS)
    # adding the tier changes no digest a protocol was frozen with (pilot 1 predates the recorded corpus amendment, ADR-16)
    for name in ("protocol5", "pilot2"):
        path = Path(__file__).resolve().parents[1] / "evidence" / "wp14" / (name + ".frozen.json")
        if path.is_file():
            protocol = json.loads(path.read_text())
            assert protocol["corpus_digest"] == corpus.corpus_digest(protocol["tiers"]), name
    assert corpus.corpus_digest(["graph"]) != corpus.corpus_digest(["numerical"])


@needs_native
def test_a_hit_on_the_complete_job_key_reissues_the_retained_result_and_witness(tmp_path):
    pytest.importorskip("flint")
    repo = tmp_path / "repo"
    base = gw.build_repo(repo)
    ws = Workspace.create(tmp_path / "ws", backend="trusted_local", allow_trusted_local=True)
    try:
        oracle = gw.write_oracle(tmp_path / "oracle.json", "graph.window_reachability")
        spec = gw.task_spec(repo, base, oracle, scripted(gw.script("graph.window_reachability")), "graph.window_reachability")
        first_created, first = run_task(ws, spec)
        second_created, second = run_task(ws, spec)
        assert first["state"] == second["state"] == "succeeded", (first["log"], second["log"])
        one, two = job_result(ws, first_created), job_result(ws, second_created)
        assert one["cache"] == {"key": two["cache"]["key"], "hit": False} and two["cache"]["hit"] is True
        assert two["output_sha256"] == one["output_sha256"] and two["witness_ref"] == one["witness_ref"] and two["diagnostics_ref"] == one["diagnostics_ref"]
        node = ws.owner.projection(second_created["run_id"])["nodes"]["run-job"]
        assert set(node["outputs"]) >= {"job_result", "witness"}
        assert (Path(second_created["worktree"]) / gw.OUTPUTS["graph.window_reachability"]).read_bytes() == (Path(first_created["worktree"]) / gw.OUTPUTS["graph.window_reachability"]).read_bytes()
        outcomes = {a["check_id"]: a["outcome"] for a in second["assessments"] if a["eligible"]}
        assert outcomes["reference"] == "passed"
        assert ws.owner.replay()["status"] == "passed"
    finally:
        ws.close()


# ------------------------------------------------------------------ ADR-19: the specified state readout and its detections

from gabriel_agent.evaluation.fixtures import graph_readout as gr  # noqa: E402


def readout_cases():
    import random
    rng = random.Random(19)
    cases = [("fixture", gr.STREAM, gr.profile()), ("nonadaptive", gr.STREAM, gr.profile(adaptive_carrier=False)), ("one_carrier", gr.STREAM, gr.profile(carriers=1)),
             ("thirteen", gr.STREAM, gr.profile(carriers=13, lam=0.25, mu_r=0.1, eta_r=2.0)), ("sixtyfour", gr.STREAM, gr.profile(carriers=64))]
    for index in range(6):
        stream = []
        for _ in range(rng.randint(3, 30)):
            entities = sorted(rng.sample(range(16), rng.randint(1, 8)))
            stream.append([(e, rng.uniform(0, 2 * 3.141592653589793), rng.random()) for e in entities])
        cases.append(("random_%d" % index, stream, gr.profile(carriers=rng.choice([2, 3, 4, 7, 16, 33]), adaptive_carrier=rng.random() < 0.7,
                                                            lam=rng.choice([0.1, 0.5]), mu_r=rng.choice([0.3, 1.0]), eta_r=rng.choice([1.0, 3.0]),
                                                            thresholds={k: rng.choice([0.3, 0.5, 0.7]) for k in "dqrgjpnk"})))
    return cases


@needs_native
def test_state_readout_matches_the_standard_library_reference():
    for name, stream, prof in readout_cases():
        result = native_graph.run_job("graph.state_readout", {}, raw(gr.stream_dataset(stream, prof)), BIN)
        assert result["verdict"] == "computed", (name, result)
        output = result["output"]
        assert output["kind"] == "state_readout" and output["arithmetic"] == "pure-rust-libm" and output["engine"]["commits"] == 0 and result["rows"] == len(stream)
        steps = gr.decode_readout(output)
        deviation = gr.compare_readout(steps, stream, gr.decoded_profile(prof))
        assert deviation <= 1e-12, (name, deviation)
        # the specification's finding: r, p and n are constants under the profile and k is lambda_c * q
        norm = gr.decoded_profile(prof)["normalization"]
        for step in steps:
            assert step["metrics"]["r"] == 1.0 and step["metrics"]["p"] == 1.0
            assert abs(step["metrics"]["n"] - gr.math.exp(-norm["lambda_seam"] * step["carrier"]["delta_phi"])) <= 1e-15
            assert abs(step["metrics"]["k"] - norm["lambda_c"] * step["metrics"]["q"]) <= 1e-15
        # the identity covers batches, profile and every step
        assert output["identity"] == hashlib.sha256(native_graph.canonical({"batches": output["ticks"] and gr.stream_dataset(stream, prof)["batches"], "profile": prof, "ticks": output["ticks"]})).hexdigest()


@needs_native
def test_detections_follow_the_declared_schedule_and_carry_complete_identities():
    stream, prof = gr.STREAM, gr.profile()
    readout = native_graph.run_job("graph.state_readout", {}, raw(gr.stream_dataset(stream, prof)), BIN)
    steps = gr.decode_readout(readout["output"])
    for schedule in ({"min_tick": 1, "cooldown": 1}, {"min_tick": 0, "cooldown": 0}, {"min_tick": 2, "cooldown": 5}, gr.no_detection_schedule()):
        result = native_graph.run_job("graph.detections", {}, raw(gr.detection_dataset(stream, prof, schedule)), BIN)
        assert result["verdict"] == "computed", result
        found = result["output"]["detections"]
        assert [d["tick"] for d in found] == gr.reference_detection_ticks(steps, schedule), schedule
        assert result["rows"] == len(found) and result["output"]["readout_identity"] == readout["output"]["identity"]
        for detection in found:
            body = {k: v for k, v in detection.items() if k != "identity"}
            assert detection["identity"] == hashlib.sha256(native_graph.canonical(body)).hexdigest()
            assert set(body) == {"readout_identity", "tick", "vertices", "metrics", "thresholds", "schedule"}
    assert native_graph.run_job("graph.detections", {}, raw(gr.detection_dataset(stream, prof, gr.no_detection_schedule())), BIN)["output"]["detections"] == []
    # a changed threshold changes the admitted set and every identity
    lower = native_graph.run_job("graph.detections", {}, raw(gr.detection_dataset(stream, gr.profile(thresholds={k: 0.0 for k in "dqrgjpnk"}), {"min_tick": 0, "cooldown": 0})), BIN)
    assert [d["tick"] for d in lower["output"]["detections"]] == [1, 2, 3, 4]
    identities = {d["identity"] for d in lower["output"]["detections"]}
    assert len(identities) == 4 and not identities & {d["identity"] for d in result["output"]["detections"]}


@needs_native
def test_readout_contract_violations_and_undeclared_inputs_are_rejected():
    job = {"schema": native_graph.READOUT_SCHEMA, "batches": gr.stream_dataset()["batches"], "profile": gr.profile()}
    binary = BIN["engine_readout"]
    response = native_graph.invoke(binary["path"], binary["sha256"], job)
    native_graph.validate_readout_response(response, job)
    for mutate, message in [(lambda r: r.update(arithmetic="platform-libm"), "arithmetic"), (lambda r: r["engine"].update(commits=1), "committed"),
                            (lambda r: r["engine"].update(faulted=True), "faulted"), (lambda r: r["ticks"][1]["metrics"].update(d=native_graph.bits(0.99)), "identity"),
                            (lambda r: r["ticks"][0].update(kairos=not r["ticks"][0]["kairos"]), "gate verdict"), (lambda r: r["ticks"][0].update(vertices=[9]), "vertex order"),
                            (lambda r: r["ticks"][0]["carrier"].update(index=7), "outside"), (lambda r: r.update(identity="0" * 64), "identity")]:
        broken = json.loads(json.dumps(response))
        mutate(broken)
        with pytest.raises(ValueError, match=message):
            native_graph.validate_readout_response(broken, job)
    assert native_graph.run_job("graph.state_readout", {}, raw(gr.stream_dataset([[(0, 7.0, 0.5)]])), BIN)["verdict"] == "invalid_input"
    assert native_graph.run_job("graph.state_readout", {}, raw(gr.stream_dataset(prof=gr.profile(carriers=0))), BIN)["verdict"] == "invalid_input"
    assert native_graph.run_job("graph.state_readout", {}, raw(gr.stream_dataset([[(0, 0.0, 1.5)]])), BIN)["verdict"] == "invalid_input"
    assert native_graph.run_job("graph.state_readout", {}, raw(dict(gr.stream_dataset(), schedule=gr.SCHEDULE)), BIN)["verdict"] == "invalid_input"
    assert native_graph.run_job("graph.detections", {}, raw(gr.stream_dataset()), BIN)["verdict"] == "out_of_scope"
    assert native_graph.run_job("graph.state_readout", {}, gw.BATCHES_TEXT.encode("utf8"), BIN)["verdict"] == "out_of_scope"
    assert native_graph.run_job("graph.detections", {}, raw(gr.detection_dataset(schedule={"min_tick": 1000, "cooldown": 0})), BIN)["verdict"] == "invalid_input"
    assert native_graph.run_job("graph.state_readout", {"carriers": 2}, raw(gr.stream_dataset()), BIN)["verdict"] == "invalid_input"
    for relative, content in gr.TEXTS.items():
        description = native_graph.describe(content.encode("utf8"))
        assert description["kind"] in ("observation_stream", "detection_query"), relative
        assert bool(description["problems"]) == (relative == "data/stream_bad.json"), relative


@needs_native
def test_readout_and_detection_tasks_run_through_the_core(tmp_path):
    repo = tmp_path / "repo"
    base = gr.build_repo(repo)
    ws = Workspace.create(tmp_path / "ws", backend="trusted_local", allow_trusted_local=True)
    try:
        for operation, kwargs in (("graph.state_readout", {}), ("graph.detections", {})):
            oracle = gr.write_oracle(tmp_path / ("oracle_%s.json" % operation), operation, **kwargs)
            created, summary = run_task(ws, gr.task_spec(repo, base, oracle, scripted(gr.script(operation)), operation))
            assert summary["state"] == "succeeded", (operation, summary["log"])
            outcomes = {a["check_id"]: a["outcome"] for a in summary["assessments"] if a["eligible"]}
            assert outcomes["reference"] == "passed" and outcomes["scope"] == "passed", operation
            result = job_result(ws, created)
            assert result["verdict"] == "computed" and result["worker_build"] == native_graph.worker_build(BIN)
            assert not (Path(created["worktree"]) / ".gabriel_worker").exists()
        oracle = gr.write_oracle(tmp_path / "oracle_none.json", "graph.detections", schedule=gr.no_detection_schedule())
        created, summary = run_task(ws, gr.task_spec(repo, base, oracle, scripted(gr.script("detections_none")), "graph.detections"))
        assert summary["state"] == "succeeded", summary["log"]
        written = json.loads((Path(created["worktree"]) / gr.OUTPUTS["graph.detections"]).read_text())
        assert written["detections"] == [] and job_result(ws, created)["rows"] == 0  # an empty admitted set is a computed result
        oracle = gr.write_oracle(tmp_path / "oracle_v.json", "graph.state_readout")
        for variant, verdict in (("bad_profile", "invalid_input"), ("wrong_input_kind", "out_of_scope")):
            created, summary = run_task(ws, gr.task_spec(repo, base, oracle, scripted(gr.script(variant)), "graph.state_readout", max_plan_versions=1, max_repairs=0))
            assert summary["state"] == "failed", variant
            result = job_result(ws, created)
            assert result["verdict"] == verdict and result["output_ref"] is None, variant
        assert ws.owner.replay()["status"] == "passed"
    finally:
        ws.close()


def test_graph_tier_readout_and_detection_families_are_sound():
    from gabriel_agent.evaluation import corpus_domains as cd
    report = cd.check_all("graph")
    assert {item["family"] for item in report} == {"graph-snapshot", "graph-mass", "graph-window", "graph-readout", "graph-detections"}
    assert len(report) == 10 and all(item["sound"] for item in report), [(i["task_id"], i["controls"]) for i in report if not i["sound"]]
