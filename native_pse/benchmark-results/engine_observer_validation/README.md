# Executed native observer validation

`first_native_observer` is the initial three unit/eight integration-test run.
`workspace_observer` is the complete release/all-feature workspace run, with
`full_state_matches_original_golden_fixture` explicitly filtered. It passed
492 tests; one documentation test remained ignored, one fixture filtered.
`historical_fixture` ran that fixture alone in the correct package and failed
with exit 101. The fixture was not changed.

Each command has its original captured stdout/stderr, byte counts, SHA-256
and declared environment. These are executed checks, not timing benchmarks.
The source-conditioned low-level kernel is unchanged; the new observer owns
its explicit stable source normalization and regional readout.
