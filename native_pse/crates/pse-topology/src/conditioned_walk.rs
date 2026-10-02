//! Opt-in full-state evolution `exp(-i t L) psi` for a fixed real Laplacian.
//!
//! This API does not replace the legacy all-pairs CTQW statistic. The clique
//! backend uses its two spectral subspaces; the general backend retains all
//! eigenpairs. Neither backend normalizes input or output states.

use crate::SparseLaplacian;
use nalgebra::{DMatrix, SymmetricEigen};
pub use nalgebra::Complex;
use std::error::Error;
use std::fmt;

/// Explicit selection also permits comparisons against the same full-spectrum
/// implementation, without changing graph validation or matrix construction.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BackendChoice {
    Auto,
    Spectral,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum WalkBackend {
    CompleteGraph,
    Spectral,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum WalkError {
    EmptyGraph,
    DimensionMismatch { expected: usize, actual: usize },
    DimensionOverflow,
    AllocationFailed,
    InvalidDegree { vertex: usize },
    InvalidEdge { from: usize, to: usize },
    DuplicateEdge { from: usize, to: usize },
    AsymmetricEdge { from: usize, to: usize },
    InconsistentDegree { vertex: usize },
    NonFiniteState { vertex: usize },
    NonFiniteTime,
    NumericalOverflow,
    EigensolverFailed,
}

impl fmt::Display for WalkError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "conditioned CTQW: {self:?}")
    }
}

impl Error for WalkError {}

enum PlanData {
    Clique { constant_eigenvalue: f64, orthogonal_eigenvalue: f64 },
    Spectral { eigenvalues: Vec<f64>, eigenvectors: DMatrix<f64> },
}

/// An immutable validated graph and its complete evolution representation.
/// Construction costs O(n²+E) before any O(n³) eigendecomposition. Auto's
/// complete-graph recognition is exact, never based on a tolerance.
pub struct ConditionedWalkPlan {
    n: usize,
    data: PlanData,
}

enum PreparedData {
    Clique { mean: Complex<f64> },
    Spectral { overlaps: Vec<Complex<f64>> },
}

/// The original state and state-specific overlaps, borrowing a fixed plan.
/// This separation makes repeated time queries independent of state setup.
pub struct PreparedState<'a> {
    plan: &'a ConditionedWalkPlan,
    initial: Vec<Complex<f64>>,
    data: PreparedData,
}

fn finite_complex(value: Complex<f64>) -> bool {
    value.re.is_finite() && value.im.is_finite()
}

impl ConditionedWalkPlan {
    /// Validate and own a representation of `L = D - A`.
    ///
    /// Each off-diagonal ordered pair may occur at most once. Every supplied
    /// entry needs its exactly equal reverse (including explicit zero entries).
    /// Weights must be finite and nonnegative. Degrees must equal the finite
    /// left-to-right sum of weights in increasing neighbour-index order.
    pub fn new(graph: &SparseLaplacian, choice: BackendChoice) -> Result<Self, WalkError> {
        let n = graph.n;
        if n == 0 {
            return Err(WalkError::EmptyGraph);
        }
        if graph.degree.len() != n {
            return Err(WalkError::DimensionMismatch { expected: n, actual: graph.degree.len() });
        }
        let size = n.checked_mul(n).ok_or(WalkError::DimensionOverflow)?;
        let mut cells = Vec::new();
        cells.try_reserve_exact(size).map_err(|_| WalkError::AllocationFailed)?;
        // NaN means "not supplied"; actual NaN weights are rejected below.
        cells.resize(size, f64::NAN);
        for (i, &degree) in graph.degree.iter().enumerate() {
            if !degree.is_finite() || degree < 0.0 {
                return Err(WalkError::InvalidDegree { vertex: i });
            }
            cells[i * n + i] = degree;
        }
        for &(i, j, weight) in &graph.adjacency {
            if i >= n || j >= n || i == j || !weight.is_finite() || weight < 0.0 {
                return Err(WalkError::InvalidEdge { from: i, to: j });
            }
            let cell = &mut cells[j * n + i];
            if !cell.is_nan() {
                return Err(WalkError::DuplicateEdge { from: i, to: j });
            }
            *cell = -weight;
        }
        for i in 0..n {
            let mut degree = 0.0;
            for j in 0..n {
                if i == j {
                    continue;
                }
                let forward = cells[j * n + i];
                let reverse = cells[i * n + j];
                if forward.is_nan() != reverse.is_nan()
                    || (!forward.is_nan() && forward != reverse)
                {
                    return Err(WalkError::AsymmetricEdge { from: i, to: j });
                }
                if !forward.is_nan() {
                    degree -= forward;
                }
            }
            if !degree.is_finite() {
                return Err(WalkError::NumericalOverflow);
            }
            if degree != graph.degree[i] {
                return Err(WalkError::InconsistentDegree { vertex: i });
            }
        }
        for value in &mut cells {
            if value.is_nan() {
                *value = 0.0;
            }
        }

        if choice == BackendChoice::Auto {
            let weight = if n == 1 { 0.0 } else { -cells[n] };
            let degree = graph.degree[0];
            let exact_uniform = (0..n).all(|i| {
                graph.degree[i] == degree
                    && (0..n).all(|j| i == j || cells[j * n + i] == -weight)
            });
            // A repeated sum can differ from a single rounded product. Such a
            // graph remains valid but deliberately takes the spectral path.
            if exact_uniform && degree == (n - 1) as f64 * weight {
                // The represented diagonal is a rounded f64 number. Retain its
                // tiny constant-space eigenvalue instead of silently replacing
                // the actual stored matrix by an ideal row-sum-zero matrix.
                let constant_eigenvalue = (-((n - 1) as f64)).mul_add(weight, degree);
                let orthogonal_eigenvalue = degree + weight;
                if !constant_eigenvalue.is_finite() || !orthogonal_eigenvalue.is_finite() {
                    return Err(WalkError::NumericalOverflow);
                }
                return Ok(Self {
                    n,
                    data: PlanData::Clique { constant_eigenvalue, orthogonal_eigenvalue },
                });
            }
        }

        let matrix = DMatrix::from_vec(n, n, cells);
        let max_iterations = n.saturating_mul(128).max(1024);
        let decomposition = SymmetricEigen::try_new(matrix, f64::EPSILON, max_iterations)
            .ok_or(WalkError::EigensolverFailed)?;
        if !decomposition.eigenvalues.iter().all(|x| x.is_finite())
            || !decomposition.eigenvectors.iter().all(|x| x.is_finite())
        {
            return Err(WalkError::NumericalOverflow);
        }
        Ok(Self {
            n,
            data: PlanData::Spectral {
                eigenvalues: decomposition.eigenvalues.as_slice().to_vec(),
                eigenvectors: decomposition.eigenvectors,
            },
        })
    }

    pub fn dimension(&self) -> usize {
        self.n
    }

    pub fn backend(&self) -> WalkBackend {
        match self.data {
            PlanData::Clique { .. } => WalkBackend::CompleteGraph,
            PlanData::Spectral { .. } => WalkBackend::Spectral,
        }
    }

    /// Cache overlaps once; no state normalization is performed. Intermediate
    /// arithmetic overflow is an error even if later cancellation could make
    /// the exact mathematical answer finite.
    pub fn prepare_state(&self, initial: &[Complex<f64>]) -> Result<PreparedState<'_>, WalkError> {
        if initial.len() != self.n {
            return Err(WalkError::DimensionMismatch { expected: self.n, actual: initial.len() });
        }
        for (i, &value) in initial.iter().enumerate() {
            if !finite_complex(value) {
                return Err(WalkError::NonFiniteState { vertex: i });
            }
        }
        let data = match &self.data {
            PlanData::Clique { .. } => {
                // Scale first to avoid overflowing the sum of finite entries.
                let divisor = self.n as f64;
                let mean = initial.iter().fold(Complex::new(0.0, 0.0), |sum, &x| sum + x / divisor);
                if !finite_complex(mean) {
                    return Err(WalkError::NumericalOverflow);
                }
                PreparedData::Clique { mean }
            }
            PlanData::Spectral { eigenvectors, .. } => {
                let mut overlaps = Vec::with_capacity(self.n);
                for column in 0..self.n {
                    let mut overlap = Complex::new(0.0, 0.0);
                    for row in 0..self.n {
                        overlap += initial[row] * eigenvectors[(row, column)];
                    }
                    if !finite_complex(overlap) {
                        return Err(WalkError::NumericalOverflow);
                    }
                    overlaps.push(overlap);
                }
                PreparedData::Spectral { overlaps }
            }
        };
        Ok(PreparedState { plan: self, initial: initial.to_vec(), data })
    }
}

fn phase(eigenvalue: f64, time: f64) -> Result<Complex<f64>, WalkError> {
    let angle = -time * eigenvalue;
    if !angle.is_finite() {
        return Err(WalkError::NumericalOverflow);
    }
    let (sin, cos) = angle.sin_cos();
    if !sin.is_finite() || !cos.is_finite() {
        return Err(WalkError::NumericalOverflow);
    }
    Ok(Complex::new(cos, sin))
}

impl PreparedState<'_> {
    /// Return the complete complex state at finite dimensionless time `t`.
    /// Positive L uses the sign convention `exp(-i t L)`; negative times are
    /// supported. At t=0 the original finite state is returned bit for bit.
    pub fn state_at(&self, time: f64) -> Result<Vec<Complex<f64>>, WalkError> {
        if !time.is_finite() {
            return Err(WalkError::NonFiniteTime);
        }
        if time == 0.0 {
            return Ok(self.initial.clone());
        }
        let state = match (&self.plan.data, &self.data) {
            (PlanData::Clique { constant_eigenvalue, orthogonal_eigenvalue }, PreparedData::Clique { mean }) => {
                let constant = phase(*constant_eigenvalue, time)?;
                let orthogonal = phase(*orthogonal_eigenvalue, time)?;
                if *constant_eigenvalue == 0.0 && *orthogonal_eigenvalue == 0.0 {
                    return Ok(self.initial.clone());
                }
                self.initial.iter().map(|&x| constant * *mean + orthogonal * (x - *mean)).collect()
            }
            (PlanData::Spectral { eigenvalues, eigenvectors }, PreparedData::Spectral { overlaps }) => {
                let mut result = vec![Complex::new(0.0, 0.0); self.plan.n];
                for column in 0..self.plan.n {
                    let coefficient = phase(eigenvalues[column], time)? * overlaps[column];
                    for row in 0..self.plan.n {
                        result[row] += coefficient * eigenvectors[(row, column)];
                    }
                }
                result
            }
            _ => unreachable!("prepared state is private and paired with its borrowed plan"),
        };
        if !state.iter().copied().all(finite_complex) {
            return Err(WalkError::NumericalOverflow);
        }
        Ok(state)
    }
}

#[cfg(test)]
#[path = "conditioned_walk_tests.rs"]
mod tests;
