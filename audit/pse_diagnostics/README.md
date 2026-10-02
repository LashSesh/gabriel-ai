# Executed diagnostic counterexamples

Run from this directory with Rust 1.95.0:

```sh
cargo run --locked --release
```

The supplied output was executed against the unchanged uploaded PSE on Linux. The delivered dependency paths point to the included optional Gabriel PSE fork. The relevant graph, topology and scale source files are unchanged in that fork; its small-signature optimization does not repair either diagnostic failure. `Cargo.lock` records the actual dependency resolution. The expected analytic gap of the 32-node complete graph with symmetrized edge weights 1/2 is 16. The partial routine reports 0 after obtaining only the eigenvalue near 16; the full decomposition returns a gap near 16. The second case requests at most two clusters but produces four. These are inherited correctness limitations, not claims that the diagnostics pass.
