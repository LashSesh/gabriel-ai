# Conditioned Engine task benchmark

This is a complete, bounded, read-only graph diagnostic task. Each measured
sample starts a new public `pse::Engine`, ingests every frozen batch, snapshots
its current graph, prepares a named source and fixed target region, and returns
the region's normalized intensity and a fixed-deadband action at every requested
time. All three consumers solve exactly that scalar task. The last variant
uses a compiled three-coefficient regional formula on recognized cliques;
noncliques retain full-state evaluation. The full source and full graph are
available, so there is no observation-acquisition or forecasting claim.

The frozen `protocol.json` defines eight source-generated graphs, three query
counts, three execution variants, pairing/order, source/target identities,
normalization, tolerances and decision policy. Query j uses
`query_times[j % 16] + (j // 16)/4096`; all 256 times are distinct. An exact
same-time cache cannot eliminate repeated work within a task. `golden` records
257 primary frames (zero plus every requested time), all graph data,
complete states and diagnostic controls. `measure` records scalar responses,
actions and all timing spans. No future labels or simulated outcome labels
enter this task. Time is the specified mathematical walk parameter, not a
market horizon or an authenticated event timestamp.

The declared configuration suppresses crystal commits using the existing
`min_crystal_tick` gate. Graph ingestion, embeddings, carrier state and metrics
still execute. Thus a measured total gain concerns this **integrated observer
task**, not default crystallization, financial forecasting, or the complete
Gabriel deployment. The fixed region consumer explicitly avoids requiring a
full returned field when only a scalar is needed.

## Execute

A Rust 1.95.0 toolchain, cached Cargo dependencies and Python 3.10+ are required.
Run native correctness checks before measurement, and do not run other builds
or CPU-heavy workloads concurrently. Use a new output directory each time:

```bash
python3 reproduce.py --pilot-only --output /absolute/path/to/new-pilot
python3 reproduce.py --output /absolute/path/to/new-measurements
```

A preserved earlier duration-only pilot used repeated cycles of 16 times.
The distinct-time protocol was fixed before final paired measurements, and
that earlier pilot is excluded from all reported statistics.

The pilot reports only a duration estimate; it is excluded from final paired
statistics. The runner pins no-LTO release settings, one codegen unit and one
build job, captures every command and both streams, preserves source guards and
binary identity, and verifies a complete reopened command index after the final
command. A failed run retains its streams and `complete: false`. Portable
reconstruction does not require the original executable to be distributed.

Returned scalar response vectors survive the measured interval so every output
can be checked afterward. Their construction is timed; subsequent serialization
and destruction are excluded. Engine, snapshot, source and region destruction
are included in the total interval. Input byte generation, process launch and
JSON/disk transport are excluded. A separate persistent-owner comparison is
needed to measure those boundary costs.

The zero-time, uniform-source, basis-source, real-zero-mean and permutation
controls expose representational limits. Complete-graph time sampling has at
most three independent intensity time functions for a fixed complex source,
and at most two for a real source. More samples do not create independent
information. The action deadband is a policy, not an outward-rounded proof.
