#!/usr/bin/env python3
"""Reproduce supplied-PSE / Gabriel small-signature execution comparisons.

Requires Python 3.10+, Cargo/Rust 1.95.0 and a linker. First compilation may
need network access for locked third-party crates. Outputs are synthetic.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, statistics, subprocess, time, zipfile
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parents[1]


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def execute(cmd, cwd, env, prefix, timeout=900):
    started = time.perf_counter()
    with prefix.with_suffix(".stdout").open("wb") as out, prefix.with_suffix(".stderr").open("wb") as err:
        cp = subprocess.run(cmd, cwd=cwd, env=env, stdout=out, stderr=err, timeout=timeout)
    write_json(prefix.with_suffix(".command.json"), {"command": cmd, "cwd": str(cwd), "returncode": cp.returncode, "elapsed_seconds": time.perf_counter()-started})
    if cp.returncode:
        raise RuntimeError(f"Command failed; inspect {prefix}.stderr")
    return prefix.with_suffix(".stdout").read_bytes()


def measure(suite, original, fork, out, env):
    out.mkdir()
    protocol = {"suite": suite, "external_pairs": 3, "within_harness_repetitions": 5,
                "orders": [["original", "fork"], ["fork", "original"], ["original", "fork"]],
                "metric": "paired ratio of per-process median observation throughput",
                "latency_unit": "batch tick, not single observation",
                "linux_cpu_and_rss_counters": "unavailable zeros in inherited harness",
                "semantics": "synthetic in-memory engine only, no Gabriel durable owner or financial predictor",
                "golden": "focused: directly serialized state snapshots and crystals; stock: state hashes and trace metadata"}
    write_json(out/"protocol.json", protocol)
    binaries={"original": original, "fork": fork}
    goldens={variant:execute([str(binary), "golden"], out, env, out/("golden_"+variant)) for variant,binary in binaries.items()}
    same = goldens["original"] == goldens["fork"]
    write_json(out/"golden_comparison.json", {"bytes_identical":same, "bytes":{v:len(x) for v,x in goldens.items()},"sha256":{v:hashlib.sha256(x).hexdigest() for v,x in goldens.items()}})
    if not same:
        raise RuntimeError("Reference/fork golden mismatch; timing halted")
    records=[]
    for pair, order in enumerate(protocol["orders"]):
        for variant in order:
            raw=execute([str(binaries[variant])], out, env, out/f"pair_{pair}_{variant}", timeout=240)
            records.append({"pair":pair,"variant":variant,"raw":json.loads(raw)})
            print(f"{suite}: pair {pair+1}/3 {variant} complete", flush=True)
    keys=sorted({(m["mode"],m["entities"],m["ticks"]) for r in records for m in r["raw"]["measurements"]})
    summary=[]
    for key in keys:
        pairs=[]
        for pair in range(3):
            rates={}
            for variant in binaries:
                run=next(r for r in records if r["pair"]==pair and r["variant"]==variant)
                rows=[m for m in run["raw"]["measurements"] if (m["mode"],m["entities"],m["ticks"])==key]
                rates[variant]=statistics.median(m["obs_per_s"] for m in rows)
            pairs.append({"pair":pair,"median_rates":rates,"ratio":rates["fork"]/rates["original"]})
        summary.append({"mode":key[0],"entities":key[1],"ticks":key[2],"pairs":pairs,"median_paired_ratio":statistics.median(p["ratio"] for p in pairs)})
    write_json(out/"results.json", {"runs":records,"summary":summary})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New output directory (must not exist)")
    args=parser.parse_args()
    work=args.output.resolve();work.mkdir(parents=True,exist_ok=False)
    archive=HERE/"pse-standalone-supplied.zip"
    assert hashlib.sha256(archive.read_bytes()).hexdigest()=="30d4a6aeab6c6509c0cc31fcf5b4be4fd3f95aec745127aa848c8ce37b7299ca"
    with zipfile.ZipFile(archive) as z:
        for entry in z.infolist():
            parts=PurePosixPath(entry.filename)
            if parts.is_absolute() or ".." in parts.parts or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Unsafe archive path/link")
        z.extractall(work/"reference")
    sources={"original":work/"reference/pse", "fork":NATIVE}
    env=os.environ.copy();env["RUSTUP_TOOLCHAIN"]="1.95.0"
    compiler=execute(["rustc","--version","--verbose"],work,env,work/"compiler")
    if not compiler.startswith(b"rustc 1.95.0 "):
        raise RuntimeError("This protocol requires Rust 1.95.0")
    stock={};focused={}
    for variant,source in sources.items():
        env["CARGO_TARGET_DIR"]=str(work/("target_"+variant))
        prefix=work/("stock_build_"+variant)
        execute(["cargo","bench","--locked","--bench","engine","--no-run"],source,env,prefix)
        text=prefix.with_suffix(".stderr").read_text()
        match=re.findall(r"Executable benches/engine.rs \(([^)]+)\)", text)
        if not match: raise RuntimeError("Cannot locate compiled stock benchmark")
        stock[variant]=Path(match[-1])
        project=work/("focused_"+variant);(project/"src").mkdir(parents=True)
        shutil.copy2(HERE/"focused_harness.rs",project/"src/main.rs")
        shutil.copy2(HERE/("focused_"+variant+".lock"),project/"Cargo.lock")
        manifest=f'[package]\nname="pse-focused-{variant}"\nversion="0.1.0"\nedition="2021"\n\n[workspace]\n\n[dependencies]\n'
        for dep in ["pse-core","pse-graph","pse-types"]:
            manifest+=dep+'={path='+json.dumps(str(source/"crates"/dep))+'}\n'
        manifest+='serde_json="1"\n\n[profile.release]\nopt-level=3\nlto="thin"\ncodegen-units=1\ndebug=true\nstrip="none"\noverflow-checks=false\npanic="unwind"\n'
        (project/"Cargo.toml").write_text(manifest)
        execute(["cargo","build","--locked","--release"],project,env,work/("focused_build_"+variant))
        focused[variant]=work/("target_"+variant)/"release"/("pse-focused-"+variant+(".exe" if os.name=="nt" else ""))
    # All compilation is finished before wall-clock measurements begin.
    measure("stock",stock["original"],stock["fork"],work/"stock",env)
    measure("focused",focused["original"],focused["fork"],work/"focused",env)


if __name__ == "__main__":
    main()
