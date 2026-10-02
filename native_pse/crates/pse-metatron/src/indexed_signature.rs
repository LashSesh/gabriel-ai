//! Optional checked-table candidate; Rust integration tests must be run before activation.
use pse_types::MetatronTopologySignature;

use crate::bitgraph::{bits_to_adjacency, edge_to_bit};
use crate::embed::embed;
use crate::error::{ScanError, ScanResult};
use crate::ingest::InputGraph;
use crate::platonic::classify_platonic;
use crate::scan::hash_canonical_matrix;
use crate::spectrum::compute_spectrum;

const CLASSES: &[u8; 4194304] = include_bytes!("../data/s7_classes.bin");
const METADATA: &[u8; 16704] = include_bytes!("../data/s7_metadata.bin");
pub const INDEX_BYTES: usize = CLASSES.len() + METADATA.len();

pub fn indexed_orbit(bits: u32) -> Option<(u32, usize, usize)> {
    if bits >= 1 << 21 { return None; }
    let offset = bits as usize * 2;
    let class = u16::from_le_bytes([CLASSES[offset], CLASSES[offset + 1]]) as usize;
    let row = class * 16;
    let word = |at| u32::from_le_bytes(METADATA[at..at+4].try_into().unwrap());
    Some((word(row+4), word(row+8) as usize, word(row+12) as usize))
}

pub fn compute_indexed_signature(adjacency: Vec<Vec<f64>>) -> ScanResult<MetatronTopologySignature> {
    compute_validated_indexed_signature(validate_signature_input(adjacency)?)
}

// The optional memoizer shares the original validation and size-check order.
// Call this before considering any cached result.
pub(crate) fn validate_signature_input(adjacency: Vec<Vec<f64>>) -> ScanResult<InputGraph> {
    let input = InputGraph::from_adjacency(adjacency)?;
    if input.n > 7 {
        return Err(ScanError::TooManyNodes { n: input.n });
    }
    Ok(input)
}

// Only accepts an input returned by validate_signature_input. Keeping the
// calculation here preserves the original routines and arithmetic order.
pub(crate) fn compute_validated_indexed_signature(
    input: InputGraph,
) -> ScanResult<MetatronTopologySignature> {
    let mut bits = 0;
    for i in 0..input.n {
        for j in (i + 1)..input.n {
            if input.adjacency[i][j] == 1.0 {
                bits |= 1 << edge_to_bit(i, j);
            }
        }
    }
    let (canonical_bits, orbit_size, stabilizer_order) = indexed_orbit(bits).expect("validated 21-bit input");
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
    use crate::small_signature::compute_small_signature;
    #[test]
    fn all_labelled_graphs_through_five_vertices() {
        for n in 1..=5 {
            for bits in 0..(1u32 << (n*(n-1)/2)) {
                let a = bits_to_adjacency(bits, n);
                assert_eq!(pse_types::canonical_bytes(&compute_indexed_signature(a.clone()).unwrap()),
                           pse_types::canonical_bytes(&compute_small_signature(a).unwrap()));
            }
        }
    }
    #[test]
    fn sampled_larger_graphs() {
        let mut seed=2026092613u64;
        for n in [6,7] { for _ in 0..64 {
            seed^=seed<<13; seed^=seed>>7; seed^=seed<<17;
            let bits=seed as u32 & ((1u32 << (n*(n-1)/2))-1);
            let a=bits_to_adjacency(bits,n);
            assert_eq!(pse_types::canonical_bytes(&compute_indexed_signature(a.clone()).unwrap()),
                       pse_types::canonical_bytes(&compute_small_signature(a).unwrap()));
        }}
    }
    #[test]
    fn boundaries() {
        assert_eq!(indexed_orbit(0),Some((0,1,5040)));
        assert_eq!(indexed_orbit((1<<21)-1),Some(((1<<21)-1,1,5040)));
        assert_eq!(indexed_orbit(1<<21),None);
        for a in [vec![],vec![vec![0.0;8];8],vec![vec![1.0]],
                  vec![vec![0.0,0.5],vec![0.5,0.0]]] {
            assert!(compute_indexed_signature(a).is_err());
        }
    }
}
