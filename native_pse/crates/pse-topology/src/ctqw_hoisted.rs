//! Call-local reuse of CTQW mode phases.
//!
//! This changes evaluation multiplicity, not the ordered arithmetic for any
//! source/destination pair. Bitwise equality assumes repeatable scalar sin/cos
//! and arithmetic results for identical input bits in the chosen build. Rust's
//! portable API does not guarantee trigonometric repeatability or NaN payloads.
//! The reference function remains the default and the executable oracle.

use pse_fmath::Fmath;
use crate::{ctqw_propagate_reference, CtqwResult, SpectralDecomposition, TopologyConfig};

// Sufficient bounds, deliberately broader than ordinary graph spectra and
// narrower than all finite f64 inputs. Values are exact binary powers.
const COMPONENT_BOUND: f64 = f64::from_bits((1023_u64 + 128) << 52);
const PHASE_INPUT_BOUND: f64 = f64::from_bits((1023_u64 + 250) << 52);
const NONZERO_TIME_MIN: f64 = f64::from_bits((1023_u64 - 250) << 52);

/// Conservative domain for reusing intermediate values without exceptional
/// floating-point arithmetic. Repeated NaN operations can select different
/// payload/sign operands after compilation even with the same algebraic order.
/// Such cases run the exact executable reference body instead.
///
/// On usize <= 64-bit targets, scan steps are < 2^64. For nonzero admitted T,
/// |dt| >= 2^-315 and |t| <= 2|T|, hence reciprocals and phases stay finite:
/// |lambda*t| <= 2^501. With |sin|, |cos| <= 2, component bounds and rounding
/// give each product < 2^259. Rank <= 2^32 and k*2^-53 <= 2^-21 give each
/// accumulated amplitude < 2^293 and the final probability < 2^588.
/// At most n^2 < 2^128 finite scan times enter the mean, so its sum is below
/// 2^380. These loose margins avoid edge-of-range reasoning. T = +/-0 is
/// admitted explicitly; zero scan steps delegate to the reference.
///
/// Only consumed eigenvalues and eigenvector rows/columns are checked. Ragged
/// or missing eigenvector entries retain the reference zero fallback.
fn finite_hoist_domain(spectral: &SpectralDecomposition, config: &TopologyConfig, n: usize) -> bool {
    let k = spectral.truncation_rank;
    if usize::BITS > 64
        || (k as u128) > (1_u128 << 32)
        || k > spectral.eigenvalues.len()
        || config.ctqw_time_steps == 0
        || !config.ctqw_threshold.is_finite()
    {
        return false;
    }
    let time = config.ctqw_time_max;
    if !time.is_finite()
        || time.abs() > PHASE_INPUT_BOUND
        || (time != 0.0 && time.abs() < NONZERO_TIME_MIN)
    {
        return false;
    }
    spectral.eigenvalues.iter().take(k).all(|lambda| {
        lambda.is_finite() && lambda.abs() <= PHASE_INPUT_BOUND
    }) && spectral.eigenvectors.iter().take(k).all(|row| {
        row.iter().take(n).all(|u| u.is_finite() && u.abs() <= COMPONENT_BOUND)
    })
}

/// Compute the same complete CTQW result while sharing cos/sin values between
/// ordered vertex pairs. No cross-call state or approximation is introduced.
#[allow(clippy::needless_range_loop)]
pub fn ctqw_propagate_hoisted(spectral: &SpectralDecomposition, config: &TopologyConfig) -> CtqwResult {
    let n = spectral.eigenvectors.first().map(|v| v.len()).unwrap_or(0);
    if n == 0 {
        return CtqwResult {
            transfer_probabilities: vec![],
            propagation_speeds: vec![],
            mean_propagation_time: 0.0,
        };
    }

    let k = spectral.truncation_rank;
    if !finite_hoist_domain(spectral, config, n) {
        return ctqw_propagate_reference(spectral, config);
    }
    let dt = config.ctqw_time_max / config.ctqw_time_steps as f64;
    let threshold = config.ctqw_threshold;

    // t_star[j][k] = first time p_{jk}(t) >= threshold
    let mut t_star = vec![vec![f64::INFINITY; n]; n];
    // p at t=0: p_{jj}(0) = 1, p_{jk}(0) = 0 for j != k
    for j in 0..n {
        t_star[j][j] = 0.0;
    }

    // Reuse only mode/time-dependent values. Products and accumulation below
    // retain the reference evaluation order for every ordered vertex pair.
    let mut cos_phase = vec![0.0f64; k];
    let mut sin_phase = vec![0.0f64; k];

    // Scan through time steps
    for step in 1..=config.ctqw_time_steps {
        let t = step as f64 * dt;
        // A singleton, or a previously resolved threshold scan, has no
        // pending pair. Generate phases only at the first pending pair.
        let mut phases_ready = false;
        // For each source j, compute transfer probabilities to all targets
        for j in 0..n {
            for dest in 0..n {
                if t_star[j][dest].is_finite() {
                    continue;
                }
                if !phases_ready {
                    for m in 0..k {
                        let phase = -spectral.eigenvalues[m] * t;
                        cos_phase[m] = phase.dcos();
                        sin_phase[m] = phase.dsin();
                    }
                    phases_ready = true;
                }
                // alpha_{j,dest}(t) = sum_m exp(-i*lambda_m*t) * u_m[j] * u_m[dest]
                // |alpha|^2 = (Re^2 + Im^2)
                let mut re = 0.0f64;
                let mut im = 0.0f64;
                for m in 0..k {
                    let u_mj =
                        if m < spectral.eigenvectors.len() && j < spectral.eigenvectors[m].len() {
                            spectral.eigenvectors[m][j]
                        } else {
                            0.0
                        };
                    let u_md = if m < spectral.eigenvectors.len()
                        && dest < spectral.eigenvectors[m].len()
                    {
                        spectral.eigenvectors[m][dest]
                    } else {
                        0.0
                    };
                    re += cos_phase[m] * u_mj * u_md;
                    im += sin_phase[m] * u_mj * u_md;
                }
                let prob = re * re + im * im;
                if prob >= threshold {
                    t_star[j][dest] = t;
                }
            }
        }
    }

    // Transfer probabilities at t_max (for reporting)
    let t_max = config.ctqw_time_max;
    // The last scan time need not have identical bits to t_max. Recompute.
    for m in 0..k {
        let phase = -spectral.eigenvalues[m] * t_max;
        cos_phase[m] = phase.dcos();
        sin_phase[m] = phase.dsin();
    }
    let mut transfer_probabilities = vec![vec![0.0f64; n]; n];
    for j in 0..n {
        for dest in 0..n {
            let mut re = 0.0f64;
            let mut im = 0.0f64;
            for m in 0..k {
                let u_mj = if m < spectral.eigenvectors.len() && j < spectral.eigenvectors[m].len()
                {
                    spectral.eigenvectors[m][j]
                } else {
                    0.0
                };
                let u_md =
                    if m < spectral.eigenvectors.len() && dest < spectral.eigenvectors[m].len() {
                        spectral.eigenvectors[m][dest]
                    } else {
                        0.0
                    };
                re += cos_phase[m] * u_mj * u_md;
                im += sin_phase[m] * u_mj * u_md;
            }
            transfer_probabilities[j][dest] = re * re + im * im;
        }
    }

    // Propagation speeds (set to 0 when t_star is infinite or same vertex)
    let propagation_speeds: Vec<Vec<f64>> = t_star
        .iter()
        .enumerate()
        .map(|(j, row)| {
            row.iter()
                .enumerate()
                .map(|(dest, &ts)| {
                    if j == dest || ts == 0.0 || ts.is_infinite() {
                        0.0
                    } else {
                        // distance = 1 (simplified: no actual shortest-path distance)
                        1.0 / ts
                    }
                })
                .collect()
        })
        .collect();

    // Mean propagation time: average of finite t_star values (excluding diagonal)
    let finite_times: Vec<f64> = t_star
        .iter()
        .enumerate()
        .flat_map(|(j, row)| {
            row.iter()
                .enumerate()
                .filter(move |&(dest, _)| dest != j)
                .map(|(_, &ts)| ts)
        })
        .filter(|ts| ts.is_finite())
        .collect();
    let mean_propagation_time = if finite_times.is_empty() {
        config.ctqw_time_max
    } else {
        finite_times.iter().sum::<f64>() / finite_times.len() as f64
    };

    CtqwResult {
        transfer_probabilities,
        propagation_speeds,
        mean_propagation_time,
    }
}

#[cfg(test)]
mod domain_tests {
    use super::*;

    #[test]
    fn finite_domain_bounds_are_conservative_and_explicit() {
        let mut spectral = SpectralDecomposition {
            eigenvalues: vec![0.0, PHASE_INPUT_BOUND],
            eigenvectors: vec![vec![COMPONENT_BOUND, -COMPONENT_BOUND], vec![0.0, 1.0]],
            spectral_gap: 0.0, cheeger_estimate: 0.0,
            fiedler_vector: Vec::new(), truncation_rank: 2,
        };
        let mut cfg = TopologyConfig::default();
        for time in [0.0, -0.0, NONZERO_TIME_MIN, -NONZERO_TIME_MIN, PHASE_INPUT_BOUND, -PHASE_INPUT_BOUND] {
            cfg.ctqw_time_max = time;
            assert!(finite_hoist_domain(&spectral, &cfg, 2));
        }
        for time in [NONZERO_TIME_MIN.next_down(), PHASE_INPUT_BOUND.next_up(), f64::NAN, f64::INFINITY] {
            cfg.ctqw_time_max = time;
            assert!(!finite_hoist_domain(&spectral, &cfg, 2));
        }
        cfg.ctqw_time_max = 1.0;
        spectral.eigenvectors[0][0] = COMPONENT_BOUND.next_up();
        assert!(!finite_hoist_domain(&spectral, &cfg, 2));
        spectral.eigenvectors[0][0] = 1.0;
        spectral.eigenvalues[1] = PHASE_INPUT_BOUND.next_up();
        assert!(!finite_hoist_domain(&spectral, &cfg, 2));
        spectral.eigenvalues[1] = 1.0;
        cfg.ctqw_time_steps = 0;
        assert!(!finite_hoist_domain(&spectral, &cfg, 2));
    }
}
