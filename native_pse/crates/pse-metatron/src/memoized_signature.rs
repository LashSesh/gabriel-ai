//! Optional bounded cache of complete indexed signatures for exact inputs.
//!
//! The key is `(n, labelled upper-triangle edge bits)`, never an isomorphism
//! class. After ordinary validation, only matrices containing the exact
//! binary64 encodings of `+0.0` and `1.0` are cached. In particular, any `-0.0`
//! anywhere in a matrix bypasses the cache and uses the indexed calculation.
//!
//! Each thread retains at most [`CACHE_CAPACITY`] entries. Independent engine
//! instances on the same thread share these entries; a new engine does not
//! imply a cold cache. Hits return owned clones. Eviction and the diagnostic
//! counters do not affect signature values. This is an execution cache, not
//! a new graph equivalence rule or a proof about spectral arithmetic. Exact
//! reuse assumes the thread's floating-point environment remains unchanged.

use std::cell::RefCell;

use pse_types::MetatronTopologySignature;

use crate::bitgraph::edge_to_bit;
use crate::error::ScanResult;
use crate::indexed_signature::{compute_validated_indexed_signature, validate_signature_input};
use crate::ingest::InputGraph;

/// Maximum number of full signatures retained per thread.
pub const CACHE_CAPACITY: usize = 256;

/// Diagnostics for the current thread only, since its last cache reset.
///
/// A miss is a validated, cache-eligible input absent from its assigned slot.
/// A bypass is a validated input containing a binary64 encoding other than
/// exact `+0.0` or `1.0` (currently only `-0.0` passes ordinary validation).
/// Invalid inputs change no counters. Counters saturate at `usize::MAX`.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct ThreadCacheStats {
    pub hits: usize,
    pub misses: usize,
    pub bypasses: usize,
    /// Insertions replacing a different key in the same slot.
    pub evictions: usize,
    /// Currently occupied slots, at most [`CACHE_CAPACITY`].
    pub entries: usize,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct Key {
    n: u8,
    bits: u32,
}

impl Key {
    fn from_exact_input(input: &InputGraph) -> Option<Self> {
        // Inspect the whole matrix, including the diagonal and lower half.
        // Numerical comparisons alone would accidentally admit signed zero.
        if input.adjacency.iter().flatten().any(|value| {
            let bits = value.to_bits();
            bits != 0.0f64.to_bits() && bits != 1.0f64.to_bits()
        }) {
            return None;
        }
        let mut bits = 0;
        for i in 0..input.n {
            for j in (i + 1)..input.n {
                if input.adjacency[i][j] == 1.0 {
                    bits |= 1 << edge_to_bit(i, j);
                }
            }
        }
        Some(Self { n: input.n as u8, bits })
    }

    fn slot(self) -> usize {
        let word = self.bits | ((self.n as u32) << 21);
        let mixed = word.wrapping_mul(0x9e37_79b1);
        ((mixed ^ (mixed >> 16)) as usize) & (CACHE_CAPACITY - 1)
    }
}

struct Entry {
    key: Key,
    signature: MetatronTopologySignature,
}

struct ThreadCache {
    slots: [Option<Entry>; CACHE_CAPACITY],
    stats: ThreadCacheStats,
}

impl Default for ThreadCache {
    fn default() -> Self {
        Self {
            slots: std::array::from_fn(|_| None),
            stats: ThreadCacheStats::default(),
        }
    }
}

thread_local! {
    static CACHE: RefCell<ThreadCache> = RefCell::new(ThreadCache::default());
}

/// Discard this thread's entries and reset all its diagnostic counters.
///
/// Useful for reproducible measurements. Other threads are unaffected, and
/// clearing this cache does not change signature results.
pub fn clear_thread_cache() {
    CACHE.with(|cache| *cache.borrow_mut() = ThreadCache::default());
}

/// Read this thread's cache counters and occupied-slot count.
pub fn thread_cache_stats() -> ThreadCacheStats {
    CACHE.with(|cache| cache.borrow().stats)
}

/// Compute a complete indexed signature, reusing an exact input when present.
///
/// Original input validation and the `n <= 7` check run before every lookup.
/// Misses and signed-zero bypasses use the unchanged indexed computation.
pub fn compute_memoized_signature(
    adjacency: Vec<Vec<f64>>,
) -> ScanResult<MetatronTopologySignature> {
    let input = validate_signature_input(adjacency)?;
    let Some(key) = Key::from_exact_input(&input) else {
        CACHE.with(|cache| {
            let mut cache = cache.borrow_mut();
            cache.stats.bypasses = cache.stats.bypasses.saturating_add(1);
        });
        return compute_validated_indexed_signature(input);
    };

    let hit = CACHE.with(|cache| {
        let mut cache = cache.borrow_mut();
        let signature = cache.slots[key.slot()]
            .as_ref()
            .filter(|entry| entry.key == key)
            .map(|entry| entry.signature.clone());
        if signature.is_some() {
            cache.stats.hits = cache.stats.hits.saturating_add(1);
        } else {
            cache.stats.misses = cache.stats.misses.saturating_add(1);
        }
        signature
    });
    if let Some(signature) = hit {
        return Ok(signature);
    }

    // No RefCell borrow is held while the signature is being calculated.
    let signature = compute_validated_indexed_signature(input)?;
    CACHE.with(|cache| {
        let mut cache = cache.borrow_mut();
        if cache.slots[key.slot()].is_some() {
            cache.stats.evictions = cache.stats.evictions.saturating_add(1);
        } else {
            cache.stats.entries += 1;
        }
        cache.slots[key.slot()] = Some(Entry { key, signature: signature.clone() });
    });
    Ok(signature)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::bitgraph::{bits_to_adjacency, mask_for_n};
    use crate::indexed_signature::compute_indexed_signature;

    fn assert_exact(actual: &MetatronTopologySignature, expected: &MetatronTopologySignature) {
        // Serialization checks every field, but may normalize signed zero;
        // compare every binary64 field separately as well.
        assert_eq!(pse_types::canonical_bytes(actual), pse_types::canonical_bytes(expected));
        assert_eq!(
            actual.spectrum.iter().map(|value| value.to_bits()).collect::<Vec<_>>(),
            expected.spectrum.iter().map(|value| value.to_bits()).collect::<Vec<_>>(),
        );
        assert_eq!(actual.spectral_radius.to_bits(), expected.spectral_radius.to_bits());
        assert_eq!(actual.algebraic_connectivity.to_bits(), expected.algebraic_connectivity.to_bits());
        assert_eq!(actual.graph_energy.to_bits(), expected.graph_energy.to_bits());
    }

    #[test]
    fn sampled_inputs_and_immediate_repeats_match_complete_indexed_signatures() {
        clear_thread_cache();
        let mut seed = 2026092617u64;
        for n in 1..=7 {
            for sample in 0..64 {
                seed ^= seed << 13;
                seed ^= seed >> 7;
                seed ^= seed << 17;
                let bits = match sample {
                    0 => 0,
                    1 => mask_for_n(n),
                    _ => seed as u32 & mask_for_n(n),
                };
                let adjacency = bits_to_adjacency(bits, n);
                let expected = compute_indexed_signature(adjacency.clone()).unwrap();
                assert_exact(&compute_memoized_signature(adjacency.clone()).unwrap(), &expected);
                let before_repeat = thread_cache_stats();
                assert_exact(&compute_memoized_signature(adjacency).unwrap(), &expected);
                let after_repeat = thread_cache_stats();
                assert_eq!(after_repeat.hits, before_repeat.hits + 1);
                assert_eq!(after_repeat.misses, before_repeat.misses);
            }
        }
    }

    #[test]
    fn graph_size_and_labelled_input_are_part_of_identity() {
        clear_thread_cache();
        for n in 1..=7 {
            let adjacency = bits_to_adjacency(0, n);
            let expected = compute_indexed_signature(adjacency.clone()).unwrap();
            assert_exact(&compute_memoized_signature(adjacency).unwrap(), &expected);
        }
        assert_eq!(thread_cache_stats().misses, 7);
        assert_eq!(thread_cache_stats().hits, 0);

        clear_thread_cache();
        // These are isomorphic but have different labelled adjacency words.
        for bits in [1, 2] {
            let adjacency = bits_to_adjacency(bits, 7);
            let expected = compute_indexed_signature(adjacency.clone()).unwrap();
            assert_exact(&compute_memoized_signature(adjacency).unwrap(), &expected);
        }
        assert_eq!(thread_cache_stats().misses, 2);
        assert_eq!(thread_cache_stats().hits, 0);
    }

    #[test]
    fn validation_precedes_lookup_and_preserves_error_details() {
        clear_thread_cache();
        compute_memoized_signature(vec![vec![0.0; 2]; 2]).unwrap();
        let before = thread_cache_stats();
        let mut invalid_eight = vec![vec![0.0; 8]; 8];
        invalid_eight[7].pop();
        let invalid = vec![
            vec![],
            vec![vec![0.0; 8]; 8],
            vec![vec![0.0; 9]; 9],
            invalid_eight,
            vec![vec![0.0, 0.0], vec![0.0]],
            vec![vec![0.0, 0.0], vec![1.0, 0.0]],
            vec![vec![0.0, 0.0], vec![0.0, 1.0]],
            vec![vec![0.0, 0.5], vec![0.5, 0.0]],
            vec![vec![0.0, 0.0], vec![f64::NAN, 0.0]],
            vec![vec![0.0, f64::INFINITY], vec![f64::INFINITY, 0.0]],
            vec![vec![0.0, f64::NEG_INFINITY], vec![f64::NEG_INFINITY, 0.0]],
        ];
        for adjacency in invalid {
            let expected = compute_indexed_signature(adjacency.clone()).unwrap_err();
            let actual = compute_memoized_signature(adjacency).unwrap_err();
            assert_eq!(format!("{actual:?}"), format!("{expected:?}"));
            assert_eq!(thread_cache_stats(), before);
        }
    }

    #[test]
    fn negative_zero_in_any_matrix_part_bypasses_even_a_warm_cache() {
        clear_thread_cache();
        let positive = vec![vec![0.0; 2]; 2];
        let expected_positive = compute_indexed_signature(positive.clone()).unwrap();
        assert_exact(&compute_memoized_signature(positive.clone()).unwrap(), &expected_positive);
        for (i, j) in [(0, 0), (0, 1), (1, 0), (1, 1)] {
            let mut adjacency = positive.clone();
            adjacency[i][j] = -0.0;
            let expected = compute_indexed_signature(adjacency.clone()).unwrap();
            for _ in 0..2 {
                let before = thread_cache_stats();
                assert_exact(&compute_memoized_signature(adjacency.clone()).unwrap(), &expected);
                assert_eq!(thread_cache_stats(), ThreadCacheStats {
                    bypasses: before.bypasses + 1,
                    ..before
                });
            }
        }
        assert_exact(&compute_memoized_signature(positive).unwrap(), &expected_positive);
        assert_eq!(thread_cache_stats(), ThreadCacheStats {
            hits: 1, misses: 1, bypasses: 8, evictions: 0, entries: 1,
        });
    }

    #[test]
    fn colliding_keys_evict_without_returning_the_other_signature() {
        clear_thread_cache();
        let first = Key { n: 7, bits: 0 };
        let second = (1..=mask_for_n(7))
            .map(|bits| Key { n: 7, bits })
            .find(|key| key.slot() == first.slot())
            .expect("more keys than slots");
        for key in [first, second, first, first] {
            let adjacency = bits_to_adjacency(key.bits, key.n as usize);
            let expected = compute_indexed_signature(adjacency.clone()).unwrap();
            assert_exact(&compute_memoized_signature(adjacency).unwrap(), &expected);
        }
        assert_eq!(thread_cache_stats(), ThreadCacheStats {
            hits: 1, misses: 3, bypasses: 0, evictions: 2, entries: 1,
        });
    }

    #[test]
    fn returned_values_cannot_mutate_cached_entries() {
        clear_thread_cache();
        let adjacency = bits_to_adjacency(13, 5);
        let expected = compute_indexed_signature(adjacency.clone()).unwrap();
        for _ in 0..2 {
            // First mutates a miss result, then a hit result.
            let mut owned = compute_memoized_signature(adjacency.clone()).unwrap();
            assert_exact(&owned, &expected);
            owned.canonical_hash.clear();
            owned.spectrum.clear();
            owned.n = 99;
            owned.graph_energy = f64::NAN;
        }
        assert_exact(&compute_memoized_signature(adjacency).unwrap(), &expected);
        assert_eq!(thread_cache_stats().hits, 2);
    }

    #[test]
    fn cache_entries_and_resets_are_thread_local() {
        clear_thread_cache();
        let adjacency = bits_to_adjacency(7, 3);
        let parent_signature = compute_memoized_signature(adjacency.clone()).unwrap();
        let parent_stats = thread_cache_stats();
        let child_signature = std::thread::spawn(move || {
            assert_eq!(thread_cache_stats(), ThreadCacheStats::default());
            let signature = compute_memoized_signature(adjacency.clone()).unwrap();
            assert_eq!(thread_cache_stats().misses, 1);
            assert_exact(&compute_memoized_signature(adjacency).unwrap(), &signature);
            assert_eq!(thread_cache_stats().hits, 1);
            clear_thread_cache();
            assert_eq!(thread_cache_stats(), ThreadCacheStats::default());
            signature
        }).join().unwrap();
        assert_exact(&child_signature, &parent_signature);
        assert_eq!(thread_cache_stats(), parent_stats);
        assert_exact(&compute_memoized_signature(bits_to_adjacency(7, 3)).unwrap(), &parent_signature);
        assert_eq!(thread_cache_stats().hits, 1);
    }

    #[test]
    fn more_than_capacity_unique_inputs_remain_bounded_and_clearable() {
        clear_thread_cache();
        let total = CACHE_CAPACITY * 4;
        for bits in 0..total as u32 {
            let adjacency = bits_to_adjacency(bits, 7);
            let expected = compute_indexed_signature(adjacency.clone()).unwrap();
            assert_exact(&compute_memoized_signature(adjacency).unwrap(), &expected);
            assert!(thread_cache_stats().entries <= CACHE_CAPACITY);
        }
        let stats = thread_cache_stats();
        assert_eq!(stats.hits, 0);
        assert_eq!(stats.misses, total);
        assert!(stats.evictions >= total - CACHE_CAPACITY);
        assert_eq!(stats.entries + stats.evictions, total);
        clear_thread_cache();
        assert_eq!(thread_cache_stats(), ThreadCacheStats::default());
        compute_memoized_signature(bits_to_adjacency(0, 7)).unwrap();
        assert_eq!(thread_cache_stats().misses, 1);
    }
}
