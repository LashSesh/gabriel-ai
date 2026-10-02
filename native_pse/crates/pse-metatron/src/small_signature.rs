//! Exact execution shortcut for the engine's binary undirected graphs, n <= 7.
//!
//! This preserves the legacy padded S7 signature, including its limitations.
//! It is not a new graph equivalence relation or a scientific validation rule.

use std::sync::OnceLock;

use pse_types::MetatronTopologySignature;

use crate::bitgraph::{bits_to_adjacency, edge_to_bit, permute_bits, S7BitCache};
use crate::embed::embed;
use crate::error::{ScanError, ScanResult};
use crate::ingest::InputGraph;
use crate::platonic::classify_platonic;
use crate::scan::hash_canonical_matrix;
use crate::spectrum::compute_spectrum;

fn cache() -> &'static S7BitCache {
    static CACHE: OnceLock<S7BitCache> = OnceLock::new();
    CACHE.get_or_init(S7BitCache::new)
}

// The legacy canonical form minimizes the entire row-major matrix, whereas
// bitgraph::canonical_bits minimizes a column-major packed integer. These are
// different conventions. The first differing matrix entry is in the upper
// triangle; encode its row-major order with the first entry most significant.
fn row_major_key(bits: u32) -> u32 {
    let mut key = 0;
    for i in 0..7 {
        for j in (i + 1)..7 {
            key = (key << 1) | ((bits >> edge_to_bit(i, j)) & 1);
        }
    }
    key
}

fn legacy_orbit(bits: u32, permutations: &S7BitCache) -> (u32, usize, usize) {
    let mut best_key = u32::MAX;
    let mut best_bits = 0;
    let mut stabilizer = 0;
    for table in &permutations.tables {
        let transformed = permute_bits(bits, table);
        if transformed == bits {
            stabilizer += 1;
        }
        let key = row_major_key(transformed);
        if key < best_key {
            best_key = key;
            best_bits = transformed;
        }
    }
    // The cache contains every member of S7 exactly once. The stabilizer of
    // every graph contains the identity; orbit-stabilizer gives the quotient.
    (best_bits, permutations.len() / stabilizer, stabilizer)
}

/// Return the same complete signature as compute_signature_with_cache for
/// a binary undirected simple graph of 1..=7 vertices, using integer orbits.
/// The dense reference API remains available and unchanged.
pub fn compute_small_signature(adjacency: Vec<Vec<f64>>) -> ScanResult<MetatronTopologySignature> {
    let input = InputGraph::from_adjacency(adjacency)?;
    if input.n > 7 {
        return Err(ScanError::TooManyNodes { n: input.n });
    }
    let mut bits = 0;
    for i in 0..input.n {
        for j in (i + 1)..input.n {
            if input.adjacency[i][j] == 1.0 {
                bits |= 1 << edge_to_bit(i, j);
            }
        }
    }
    let (canonical_bits, orbit_size, stabilizer_order) = legacy_orbit(bits, cache());
    let canonical_graph = InputGraph {
        n: 7,
        adjacency: bits_to_adjacency(canonical_bits, 7),
        labels: None,
    };
    let canonical_hash = hash_canonical_matrix(&embed(&canonical_graph));

    // Keep these floating-point computations on the original embedding and
    // in the original routines. Computing them on a permuted canonical graph
    // would be mathematically equivalent but need not preserve binary64 bits.
    let embedded = embed(&input);
    let spectrum = compute_spectrum(&embedded, input.n);
    let platonic = classify_platonic(&embedded, input.n);
    let contains = |name: &str| {
        platonic.iter().any(|class| class.solid == name && class.is_subgraph)
    };
    Ok(MetatronTopologySignature {
        canonical_hash,
        n: input.n as u32,
        m: input.edge_count() as u32,
        orbit_size: orbit_size as u64,
        stabilizer_order: stabilizer_order as u64,
        spectrum: spectrum.eigenvalues,
        spectral_radius: spectrum.spectral_radius,
        algebraic_connectivity: spectrum.algebraic_connectivity,
        graph_energy: spectrum.graph_energy,
        spanning_tree_count: spectrum.spanning_tree_count,
        triangle_count: spectrum.triangle_count as u32,
        contains_tetrahedron: contains("tetrahedron"),
        contains_octahedron: contains("octahedron"),
        contains_cube: contains("cube"),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bitgraph::mask_for_n;
    use crate::signature::compute_signature_with_cache;
    use crate::S7Cache;

    // Independent direct indexed-matrix action, without the bit-permutation
    // table or integer canonical comparator used by the implementation.
    fn indexed_reference(bits: u32, permutations: &S7BitCache) -> (Vec<u8>, usize, usize) {
        let matrix = bits_to_adjacency(bits, 7);
        let mut images = std::collections::BTreeSet::new();
        let mut stabilizer = 0;
        let original: Vec<u8> = matrix.iter().flatten().map(|&v| v as u8).collect();
        for permutation in &permutations.perms {
            let mut image = Vec::with_capacity(49);
            for i in 0..7 {
                for j in 0..7 {
                    image.push(matrix[permutation[i] - 1][permutation[j] - 1] as u8);
                }
            }
            if image == original {
                stabilizer += 1;
            }
            images.insert(image);
        }
        (images.first().unwrap().clone(), images.len(), stabilizer)
    }

    #[test]
    fn every_simple_graph_through_five_vertices_matches_indexed_action() {
        let permutations = cache();
        for n in 1..=5 {
            for bits in 0..=mask_for_n(n) {
                let (canonical, orbit, stabilizer) = legacy_orbit(bits, permutations);
                let actual: Vec<u8> = bits_to_adjacency(canonical, 7)
                    .iter().flatten().map(|&v| v as u8).collect();
                let expected = indexed_reference(bits, permutations);
                assert_eq!((actual, orbit, stabilizer), expected, "n={n}, bits={bits}");
            }
        }
    }

    #[test]
    fn sampled_six_and_seven_vertex_graphs_match_indexed_action() {
        let permutations = cache();
        let mut seed = 20260926u64;
        for n in [6, 7] {
            for _ in 0..24 {
                seed ^= seed << 13;
                seed ^= seed >> 7;
                seed ^= seed << 17;
                let bits = seed as u32 & mask_for_n(n);
                let (canonical, orbit, stabilizer) = legacy_orbit(bits, permutations);
                let actual: Vec<u8> = bits_to_adjacency(canonical, 7)
                    .iter().flatten().map(|&v| v as u8).collect();
                assert_eq!((actual, orbit, stabilizer), indexed_reference(bits, permutations));
            }
        }
    }

    #[test]
    fn complete_signatures_equal_dense_reference_bytes() {
        let dense_cache = S7Cache::new();
        // Include empty, complete, disconnected, asymmetric-degree and
        // boundary-size graphs. No tolerance comparisons hide float changes.
        for (n, bits) in [(1,0), (2,1), (3,7), (4,13), (5,1023),
                         (6,0), (6,15517), (7,1), (7,1098753)] {
            let adjacency = bits_to_adjacency(bits, n);
            let expected = compute_signature_with_cache(adjacency.clone(), None, &dense_cache).unwrap();
            let actual = compute_small_signature(adjacency).unwrap();
            assert_eq!(pse_types::canonical_bytes(&actual), pse_types::canonical_bytes(&expected),
                       "n={n}, bits={bits}");
        }
    }

    #[test]
    fn rejects_invalid_or_out_of_scope_graphs() {
        for adjacency in [vec![], vec![vec![0.0; 8]; 8], vec![vec![1.0]],
                          vec![vec![0.0, 0.5], vec![0.5, 0.0]],
                          vec![vec![0.0, 1.0], vec![0.0, 0.0]]] {
            assert!(compute_small_signature(adjacency).is_err());
        }
    }

    #[test]
    fn inherited_padding_identity_limitation_is_explicit() {
        let one = compute_small_signature(vec![vec![0.0]]).unwrap();
        let two = compute_small_signature(vec![vec![0.0; 2]; 2]).unwrap();
        assert_eq!(one.canonical_hash, two.canonical_hash);
        assert_ne!(one.n, two.n);
    }
}
