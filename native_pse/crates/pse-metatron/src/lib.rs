#![allow(
    clippy::needless_range_loop,
    clippy::type_complexity,
    clippy::manual_range_contains,
    clippy::large_enum_variant,
    clippy::manual_rem_euclid,
    clippy::unnecessary_cast,
    clippy::new_without_default
)]
//! Canonical graph signatures, phase geometry and optional pattern catalogs.
//! Derived from metatron-scan (Sebastian Klemm, MIT); research reporting and
//! file-export utilities are outside the engine boundary.

pub mod bitgraph;
pub mod bitgraph_n;
pub mod catalog;
pub mod complement;
pub mod embed;
pub mod error;
pub mod geometry;
pub mod group;
pub mod ingest;
pub mod orbit;
pub mod phase_layout;
pub mod platonic;
pub mod properties;
pub mod scan;
pub mod signature;
pub mod small_signature;
pub mod spectrum;
pub mod stabilizer;

pub use bitgraph::{fast_orbit, S7BitCache};
pub use catalog::{
    build_catalog, build_catalog_for_n, build_catalog_orderly, find_in_catalog, oeis_a000055,
    oeis_a000088, oeis_a000171, oeis_a001349, oeis_a003400, oeis_a005470, oeis_a005840,
    oeis_a033995, CatalogEntry, CatalogStats, PeriodicTable,
};
pub use error::{ScanError, ScanResult};
pub use ingest::InputGraph;
pub use phase_layout::metatron_phase_layout;
pub use platonic::{classify_platonic, PlatonicClass};
pub use properties::{compute_properties, GraphProperties};
pub use scan::{scan, scan_with_cache, S7Cache, ScanReport};
pub use signature::{compute_signature, compute_signature_with_cache, signature_from_scan_report};
pub use spectrum::compute_spectrum;

#[cfg(feature = "indexed-signature")]
pub mod indexed_signature;

#[cfg(feature = "memoized-signature")]
pub mod memoized_signature;
