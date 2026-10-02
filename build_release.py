"""Build and verify the public manuscript/reproduction distribution."""
from pathlib import Path
import hashlib
import shutil
import zipfile

ROOT = Path(__file__).resolve().parent
NAMES = ["main.tex", "references.bib", "main.bbl", "README.md", "REFERENCES.tsv",
         "requirements.txt", "build_release.py", "RUNTIME_PROVENANCE.md", "development_report.tex"]


def public_file(path):
    if path.parent.name in {"gabriel_runtime", "audit"}:
        return path.suffix in {".py", ".md", ".json", ".log", ".zip", ".txt", ".tex"}
    if path.parent.name == "reproduction":
        return path.suffix in {".py", ".md"} and path.name != "check_source_schema.py"
    if path.parent.name == "results":
        if path.name in {"build.log", "quality_check.json", "corpus_inventory.json"}:
            return False
        if any(term in path.name for term in
               ("_build.log", "release_check", "release_review", "source_inventory", "source_audit")):
            return False
        return path.suffix in {".csv", ".npz", ".json", ".tex", ".log", ".sha256"}
    if path.parent.name == "figures":
        return path.suffix in {".pdf", ".png"}
    if path.parent.name == "data":
        return path.suffix in {".ts", ".json", ".md", ".csv", ".zip"}
    return False


pdf_bytes = (ROOT / "main.pdf").read_bytes()
if not pdf_bytes.startswith(b"%PDF-") or not pdf_bytes.rstrip().endswith(b"%%EOF"):
    raise RuntimeError("Missing or incomplete compiled manuscript PDF")

files = [ROOT / name for name in NAMES]
for sub in ("reproduction", "figures", "results", "data", "gabriel_runtime", "audit"):
    files.extend(p for p in (ROOT / sub).iterdir() if p.is_file() and public_file(p))
# Retain the supplied reference, optional Rust sources and explicit measured replay binary.
# Exclude target directories and other compiler build products.
files.append(ROOT / "audit" / "pse-standalone.zip")
for sub in ("native_pse", "audit/pse_diagnostics", "audit/pse_execution", "audit/engine_observer_independent", "results/window_reachability_study", "results/epoch_owner_study", "results/epoch_batch"):
    directory = ROOT / sub
    if directory.is_dir():
        files.extend(p for p in directory.rglob("*") if p.is_file()
                     and not any(part in {"target", "__pycache__", ".git"} for part in p.relative_to(directory).parts)
                     and (p.suffix in {".rs", ".md", ".toml", ".lock", ".json", ".log", ".csv", ".txt", ".py", ".stdout", ".stderr", ".zip", ".bin", ".cpp"}
                          or p.name == "LICENSE"
                          or (p.suffix == ".sqlite" and "graph_observer_owner" in p.parts)))
files = sorted(set(files), key=lambda p: p.relative_to(ROOT).as_posix())
for path in files:
    if not path.is_file() or (path.stat().st_size == 0 and path.suffix not in {".log", ".stdout", ".stderr"}):
        raise RuntimeError(f"Missing or empty file: {path}")
    if path.suffix == ".npz":
        with zipfile.ZipFile(path) as container:
            if container.testzip() is not None:
                raise RuntimeError(f"Corrupt NPZ container: {path}")
manifest = ROOT / "SHA256SUMS.txt"
manifest.write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " +
                            p.relative_to(ROOT).as_posix() + "\n" for p in files))
archive = ROOT.parent / "Gabriel_Research_Project.zip"
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
    for path in files + [manifest]:
        bundle.write(path, "Gabriel/" + path.relative_to(ROOT).as_posix())
with zipfile.ZipFile(archive) as bundle:
    if bundle.testzip() is not None:
        raise RuntimeError("ZIP integrity check failed")
    for path in files:
        if bundle.read("Gabriel/" + path.relative_to(ROOT).as_posix()) != path.read_bytes():
            raise RuntimeError(f"Packaged bytes differ: {path}")
shutil.copy2(ROOT / "main.pdf", ROOT.parent / "Gabriel.pdf")
print("FILES", len(files) + 1, "ZIP_BYTES", archive.stat().st_size)
