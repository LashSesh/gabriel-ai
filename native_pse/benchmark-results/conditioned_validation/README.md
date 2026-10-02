# Native validation in the conditioned-walk phase

`final_workspace.*` is the actually executed complete release workspace test with all features and the one explicitly named inherited fixture excluded: 481 passed, one doc test ignored, one fixture filtered.

`historical_fixture.*` records an initial targeted command against `pse-core`; it selected **zero tests**, because the fixture belongs to the root `pse` package. It is retained as an unsuccessful test-selection attempt, not a fixture pass. `historical_fixture_actual.*` records the corrected command selecting that root package and the exact historical test. Read that command result for its outcome.

All commands use Rust 1.95.0, one build job, the release no-LTO profile, retained debug info and no symbol stripping. Raw stdout/stderr and their SHA256 values are supplied. These logs are correctness checks, not performance samples.
