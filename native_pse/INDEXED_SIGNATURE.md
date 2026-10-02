# Exhaustively verified finite orbit index

The tables encode the existing zero-padded seven-slot S7 graph action. Every
binary undirected graph is a 21-bit word, with edge (i,j), i<j, at bit
`j*(j-1)/2+i`. Minimum selection uses the upper triangle in row-major order,
with the first entry most significant, preserving the legacy matrix convention.

All files use little-endian integers:

| File | Meaning | Bytes |
|---|---|---:|
| s7_classes.bin | One u16 class ID for each of 2^21 words | 4,194,304 |
| s7_metadata.bin | 1,044 rows of four u32: representative, canonical edge word, orbit cardinality, stabilizer order | 16,704 |
| s7_witnesses.bin | One packed forward vertex permutation for each graph, three bits per image coordinate | 8,388,608 |

The first two files supply runtime lookup. The third supplies offline witnesses.
Witnesses prohibit merging distinct orbits. Closure under the six adjacent
transpositions prohibits splitting an orbit. Nonempty fibers are therefore
exactly orbits. The matrix-action checker independently verifies every witness,
closure condition, class minimum and cardinality. It does not share the
generator's edge-action tables.

```bash
python native_pse/tools/reproduce_graph_index.py --output /path/to/new-directory
```

This command was actually executed with g++ and C++17. It compiles the two
standalone programs, regenerates the files twice, checks identical bytes against
the delivered data, rejects fourteen damaged certificates and accepts a different
valid witness for the empty graph. The execution record and hashes are in
`benchmark-results/indexed/results/verification_report.json`.

## Native integration and exact-input reuse

The optional `indexed-signature` feature is now compiled and executed with
Rust 1.95.0. `memoized-signature` implies it and adds a 256-slot thread-local
cache of complete signatures. Root, pse-core and pse-metatron expose the features;
packed evaluation remains the default. Enabling both selects memoized execution.

Every call validates the original matrix before lookup. Cache identity is the
pair (n, labelled edge bits), never an orbit class or canonical hash. Only whole
matrices consisting of exact +0.0 and 1.0 encodings are cached. Any -0.0 bypasses
the cache and executes indexed evaluation. Full key comparison, independent
owned copies and unchanged miss computation preserve outputs under a fixed
floating-point environment. Reset and statistics functions are public in
`pse_metatron::memoized_signature`. Fresh engines on one thread share its cache;
256 bounds entries per thread, not measured process memory.

The complete workspace test execution passes 449 tests, with one documentation
test ignored and the known historical fixture explicitly filtered. The unfiltered
command still fails that preserved fixture. The metatron package includes three
index tests and eight cache tests. Source review confirms the original spectral,
embedding, subgraph and packed-signature files are unchanged. No inherited
model defect or historical portability problem is claimed repaired.

The release profile disables LTO after local ThinLTO builds produced undefined
symbols. All three new benchmark variants use no LTO and matched settings.
The cause of the ThinLTO failures is not established. The successful full
workspace verification used retained debug information and no symbol stripping:

```bash
CARGO_PROFILE_RELEASE_DEBUG=true CARGO_PROFILE_RELEASE_STRIP=none \
  cargo test --manifest-path native_pse/Cargo.toml --locked --release \
  --jobs 1 --workspace --all-features \
  -- --skip full_state_matches_original_golden_fixture
python native_pse/benchmark-results/indexed_engine/reproduce.py \
  --output /absolute/path/to/new-results-directory
python reproduction/report_native_indexed_results.py
```

The full default benchmark wrapper was actually executed, including three
locked builds and exact output gates. Five alternating pairs give warm whole-
engine indexed/packed throughput ratios 1.662, 1.320 and 1.177 for repeated
complete graphs with 3, 5 and 7 sources. Warm memoized/indexed ratios are 1.243,
1.075 and 1.014. Eight-source controls bypass the signature. First-call and
collision controls expose cache initialization/miss costs; a cache-hit kernel
factor is not an engine-wide gain. See `benchmark-results/indexed_engine/` for
frozen inputs, protocol, individual measurements, ranges and commands.

The compiled input tables match the offline certificate hashes before and
after measurement. This binds the shipped bytes to the certificate; the runtime
does not re-run that certificate on each lookup. Historical dense-to-packed
ratios are a separate experiment and are not multiplied by the new ratios.
