//! Source-conditioned queries on a frozen, labelled engine graph.
//!
//! The graph producer uses `(W + W^T)/2`, ignores self-loops, and includes
//! inactive vertices. The snapshot is an explicit model observation; its
//! intensities are not outcome probabilities or calibrated confidence values.

use pse_fmath::Fmath;
use pse_graph::PersistentGraph;
use pse_types::{content_address_raw, Hash256, VertexId};
use std::collections::{BTreeMap, BTreeSet};

pub use pse_topology::conditioned_walk::{BackendChoice, Complex, WalkBackend, WalkError};
pub use pse_topology::SparseLaplacian;
use pse_topology::conditioned_walk::{ConditionedWalkPlan, PreparedState};

/// Explicit resource contract before the dense representation is constructed.
pub const MAX_CONDITIONED_VERTICES: usize = 512;

#[derive(Debug, thiserror::Error)]
pub enum ConditionedError {
    #[error("engine is faulted; reset and replay before taking a snapshot")]
    Faulted,
    #[error("conditioned graph has {actual} vertices; maximum is {maximum}")]
    GraphBudget { actual: usize, maximum: usize },
    #[error("graph vertex identifiers and index map are inconsistent")]
    InvalidVertexMap,
    #[error("graph contains a negative or nonfinite directed edge weight")]
    InvalidSourceWeight,
    #[error("a normalized readout requires a nonzero initial state")]
    ZeroSource,
    #[error("unknown snapshot vertex {0}")]
    UnknownVertex(VertexId),
    #[error("duplicate vertex {0} in source or target selection")]
    DuplicateVertex(VertexId),
    #[error(transparent)]
    Walk(#[from] WalkError),
}

/// The represented positive Laplacian, its vertex order and engine tick.
/// Identity covers these values, not the engine's entire state or provenance.
pub struct ConditionedSnapshot {
    tick: u64,
    vertices: Vec<VertexId>,
    indices: BTreeMap<VertexId, usize>,
    identity: Hash256,
    laplacian: SparseLaplacian,
    plan: ConditionedWalkPlan,
}

/// A caller source bound to one immutable graph snapshot.
pub struct PreparedConditionedState<'a> {
    snapshot: &'a ConditionedSnapshot,
    prepared: PreparedState<'a>,
    source_scale: f64,
    scaled_norm: f64,
    normalized_initial: Vec<Complex<f64>>,
    normalized_norm: f64,
}

/// Selection of the scalar-region execution path.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RegionChoice { Auto, StateReadout }

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RegionBackend { CompleteGraph, StateReadout }

enum RegionData {
    CompleteGraph { cosine: f64, sine: f64, frequency: f64, initial_mass: f64 },
    StateReadout,
}

/// A fixed target set and source; the complete-graph path needs constant work
/// per scalar query after setup. This does not materialize the full state.
pub struct PreparedRegion<'a> {
    source: &'a PreparedConditionedState<'a>,
    indices: Vec<usize>,
    data: RegionData,
}

/// Full normalized readout; positions follow `snapshot.vertex_ids()`.
/// Intensities divide by the initial normalized norm, never the evolved norm.
/// `norm_ratio` therefore exposes numerical drift without clamping.
pub struct ConditionedReadout {
    pub amplitudes: Vec<Complex<f64>>,
    pub normalized_intensities: Vec<f64>,
    pub norm_ratio: f64,
}

impl ConditionedSnapshot {
    pub(crate) fn from_graph(
        graph: &PersistentGraph,
        tick: u64,
        choice: BackendChoice,
    ) -> Result<Self, ConditionedError> {
        let n = graph.graph.node_count();
        if n > MAX_CONDITIONED_VERTICES {
            return Err(ConditionedError::GraphBudget {
                actual: n, maximum: MAX_CONDITIONED_VERTICES,
            });
        }
        if graph.id_map.len() != n {
            return Err(ConditionedError::InvalidVertexMap);
        }
        let mut vertices = Vec::with_capacity(n);
        let mut indices = BTreeMap::new();
        for (dense_index, node_index) in graph.graph.node_indices().enumerate() {
            let vertex = graph.graph[node_index].id;
            if graph.id_map.get(&vertex) != Some(&node_index)
                || indices.insert(vertex, dense_index).is_some()
            {
                return Err(ConditionedError::InvalidVertexMap);
            }
            vertices.push(vertex);
        }
        // Reject upstream defects before compute_laplacian could clip them.
        if graph.graph.raw_edges().iter().any(|edge| {
            !edge.weight.weight.is_finite() || edge.weight.weight < 0.0
        }) {
            return Err(ConditionedError::InvalidSourceWeight);
        }
        let laplacian = pse_topology::compute_laplacian(graph);
        let plan = ConditionedWalkPlan::new(&laplacian, choice)?;
        let mut identity_bytes = b"gabriel/conditioned-snapshot/v1;exp(-itL);L=D-A\0".to_vec();
        identity_bytes.extend_from_slice(&tick.to_le_bytes());
        identity_bytes.extend_from_slice(&(n as u64).to_le_bytes());
        for (&vertex, &degree) in vertices.iter().zip(&laplacian.degree) {
            identity_bytes.extend_from_slice(&vertex.to_le_bytes());
            identity_bytes.extend_from_slice(&degree.to_bits().to_le_bytes());
        }
        let mut edges = laplacian.adjacency.clone();
        edges.sort_by_key(|&(i, j, _)| (i, j));
        identity_bytes.extend_from_slice(&(edges.len() as u64).to_le_bytes());
        for (i, j, weight) in edges {
            identity_bytes.extend_from_slice(&(i as u64).to_le_bytes());
            identity_bytes.extend_from_slice(&(j as u64).to_le_bytes());
            identity_bytes.extend_from_slice(&weight.to_bits().to_le_bytes());
        }
        Ok(Self {
            tick, vertices, indices, identity: content_address_raw(&identity_bytes),
            laplacian, plan,
        })
    }

    pub fn tick(&self) -> u64 { self.tick }
    pub fn vertex_ids(&self) -> &[VertexId] { &self.vertices }
    pub fn identity(&self) -> &Hash256 { &self.identity }
    pub fn laplacian(&self) -> &SparseLaplacian { &self.laplacian }
    pub fn backend(&self) -> WalkBackend { self.plan.backend() }

    /// Dense source in exactly `vertex_ids()` order, stably normalized before
    /// evolution. Unlike the lower-level arbitrary-norm walk, this observer
    /// rejects zero and returns normalized amplitudes. The normalization first
    /// divides by the largest real/imaginary component, so subnormal and near-
    /// maximum finite nonzero sources do not underflow/overflow the norm.
    pub fn prepare_state(
        &self,
        initial: &[Complex<f64>],
    ) -> Result<PreparedConditionedState<'_>, ConditionedError> {
        if initial.len() != self.vertices.len() {
            return Err(WalkError::DimensionMismatch {
                expected: self.vertices.len(), actual: initial.len(),
            }.into());
        }
        for (vertex, value) in initial.iter().enumerate() {
            if !value.re.is_finite() || !value.im.is_finite() {
                return Err(WalkError::NonFiniteState { vertex }.into());
            }
        }
        let source_scale = initial.iter().fold(0.0_f64, |scale, x| {
            scale.max(x.re.abs()).max(x.im.abs())
        });
        if source_scale == 0.0 {
            return Err(ConditionedError::ZeroSource);
        }
        let scaled_initial: Vec<_> = initial.iter().map(|x| {
            Complex::new(x.re / source_scale, x.im / source_scale)
        }).collect();
        let scaled_norm: f64 = scaled_initial.iter().map(|x| x.norm_sqr()).sum();
        if !scaled_norm.is_finite() || scaled_norm <= 0.0 {
            return Err(WalkError::NumericalOverflow.into());
        }
        let norm = scaled_norm.sqrt();
        let normalized_initial: Vec<_> = scaled_initial.iter().map(|x| *x / norm).collect();
        let normalized_norm = normalized_initial.iter().map(|x| x.norm_sqr()).sum();
        let prepared = self.plan.prepare_state(&normalized_initial)?;
        Ok(PreparedConditionedState {
            snapshot: self, prepared, source_scale, scaled_norm,
            normalized_initial, normalized_norm,
        })
    }

    /// Labelled source; each snapshot vertex must occur exactly once.
    /// Input order may differ from the snapshot order; absent values are not zero-filled.
    pub fn prepare_named_state(
        &self,
        initial: &[(VertexId, Complex<f64>)],
    ) -> Result<PreparedConditionedState<'_>, ConditionedError> {
        let mut seen = BTreeSet::new();
        let mut ordered = vec![Complex::new(0.0, 0.0); self.vertices.len()];
        for &(vertex, amplitude) in initial {
            let &index = self.indices.get(&vertex)
                .ok_or(ConditionedError::UnknownVertex(vertex))?;
            if !seen.insert(vertex) {
                return Err(ConditionedError::DuplicateVertex(vertex));
            }
            ordered[index] = amplitude;
        }
        if initial.len() != self.vertices.len() {
            return Err(WalkError::DimensionMismatch {
                expected: self.vertices.len(), actual: initial.len(),
            }.into());
        }
        self.prepare_state(&ordered)
    }
}

impl PreparedConditionedState<'_> {
    pub fn snapshot(&self) -> &ConditionedSnapshot { self.snapshot }
    /// Original maximum component magnitude; never multiply these metadata
    /// blindly when the original norm is outside binary64's representable range.
    pub fn source_scale(&self) -> f64 { self.source_scale }
    pub fn scaled_source_squared_norm(&self) -> f64 { self.scaled_norm }

    pub fn state_at(&self, time: f64) -> Result<Vec<Complex<f64>>, ConditionedError> {
        Ok(self.prepared.state_at(time)?)
    }

    pub fn readout_at(&self, time: f64) -> Result<ConditionedReadout, ConditionedError> {
        let amplitudes = self.state_at(time)?;
        let mut normalized_intensities = Vec::with_capacity(amplitudes.len());
        let mut norm_ratio = 0.0;
        for x in &amplitudes {
            let intensity = x.norm_sqr() / self.normalized_norm;
            if !intensity.is_finite() {
                return Err(WalkError::NumericalOverflow.into());
            }
            normalized_intensities.push(intensity);
            norm_ratio += intensity;
        }
        if !norm_ratio.is_finite() {
            return Err(WalkError::NumericalOverflow.into());
        }
        Ok(ConditionedReadout { amplitudes, normalized_intensities, norm_ratio })
    }

    /// Validate a fixed region once. Auto uses the two-subspace scalar formula
    /// only for a graph recognized by the unchanged complete-graph plan.
    pub fn prepare_region(
        &self,
        targets: &[VertexId],
        choice: RegionChoice,
    ) -> Result<PreparedRegion<'_>, ConditionedError> {
        let mut indices = BTreeSet::new();
        for &vertex in targets {
            let &index = self.snapshot.indices.get(&vertex)
                .ok_or(ConditionedError::UnknownVertex(vertex))?;
            if !indices.insert(index) {
                return Err(ConditionedError::DuplicateVertex(vertex));
            }
        }
        let indices: Vec<_> = indices.into_iter().collect();
        let data = if choice == RegionChoice::Auto
            && self.snapshot.backend() == WalkBackend::CompleteGraph
        {
            let n = self.normalized_initial.len();
            let mean = self.normalized_initial.iter().copied()
                .fold(Complex::new(0.0, 0.0), |a, b| a + b) / n as f64;
            let mut constant = indices.len() as f64 * mean.norm_sqr();
            let mut cross = Complex::new(0.0, 0.0);
            let mut initial_mass = 0.0;
            for &i in &indices {
                let residual = self.normalized_initial[i] - mean;
                constant += residual.norm_sqr();
                cross += mean.conj() * residual;
                initial_mass += self.normalized_initial[i].norm_sqr() / self.normalized_norm;
            }
            let weight = self.snapshot.laplacian.adjacency.first()
                .map(|edge| edge.2).unwrap_or(0.0);
            let cosine = 2.0 * cross.re / self.normalized_norm;
            let sine = 2.0 * cross.im / self.normalized_norm;
            constant /= self.normalized_norm;
            let frequency = n as f64 * weight;
            if ![constant, cosine, sine, frequency, initial_mass].iter().all(|x| x.is_finite()) {
                return Err(WalkError::NumericalOverflow.into());
            }
            RegionData::CompleteGraph { cosine, sine, frequency, initial_mass }
        } else {
            RegionData::StateReadout
        };
        Ok(PreparedRegion { source: self, indices, data })
    }

    /// Region mass divided by the initial norm. Empty regions have zero mass.
    /// Repeated or unknown labels are errors; target order does not affect the sum.
    /// Binary64 rounding can produce a value slightly outside the ideal [0,1].
    pub fn target_mass_at(
        &self,
        time: f64,
        targets: &[VertexId],
    ) -> Result<f64, ConditionedError> {
        let mut indices = BTreeSet::new();
        for &vertex in targets {
            let &index = self.snapshot.indices.get(&vertex)
                .ok_or(ConditionedError::UnknownVertex(vertex))?;
            if !indices.insert(index) {
                return Err(ConditionedError::DuplicateVertex(vertex));
            }
        }
        let readout = self.readout_at(time)?;
        let mass: f64 = indices.iter().map(|&i| readout.normalized_intensities[i]).sum();
        if !mass.is_finite() {
            return Err(WalkError::NumericalOverflow.into());
        }
        Ok(mass)
    }
}


impl PreparedRegion<'_> {
    pub fn backend(&self) -> RegionBackend {
        match self.data {
            RegionData::CompleteGraph { .. } => RegionBackend::CompleteGraph,
            RegionData::StateReadout => RegionBackend::StateReadout,
        }
    }

    pub fn mass_at(&self, time: f64) -> Result<f64, ConditionedError> {
        if !time.is_finite() { return Err(WalkError::NonFiniteTime.into()); }
        let mass = match self.data {
            RegionData::CompleteGraph { cosine, sine, frequency, initial_mass } => {
                if time == 0.0 || frequency == 0.0 {
                    return Ok(initial_mass);
                }
                let phase = frequency * time;
                if !phase.is_finite() { return Err(WalkError::NumericalOverflow.into()); }
                // Anchor at the independently accumulated initial mass and use
                // cos(theta)-1=-2 sin(theta/2)^2 to avoid near-zero cancellation.
                let half_sine = (phase * 0.5).dsin();
                initial_mass - 2.0 * cosine * half_sine * half_sine + sine * phase.dsin()
            }
            RegionData::StateReadout => {
                let readout = self.source.readout_at(time)?;
                self.indices.iter().map(|&i| readout.normalized_intensities[i]).sum()
            }
        };
        if !mass.is_finite() { return Err(WalkError::NumericalOverflow.into()); }
        Ok(mass)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn malformed_vertex_maps_are_rejected_before_projection() {
        let mut graph = PersistentGraph::new();
        graph.upsert_vertex(5, 0.0);
        graph.id_map.clear();
        assert!(matches!(ConditionedSnapshot::from_graph(&graph, 1, BackendChoice::Auto),
            Err(ConditionedError::InvalidVertexMap)));
        graph.upsert_vertex(5, 0.0);
        assert!(matches!(ConditionedSnapshot::from_graph(&graph, 1, BackendChoice::Auto),
            Err(ConditionedError::InvalidVertexMap)));
    }

    #[test]
    fn invalid_raw_weights_are_not_hidden_by_projection() {
        for weight in [-1.0, f64::NAN, f64::INFINITY] {
            let mut graph = PersistentGraph::new();
            graph.upsert_edge(5, 9, 0.0);
            graph.graph.edge_weights_mut().next().unwrap().weight = weight;
            assert!(matches!(ConditionedSnapshot::from_graph(&graph, 1, BackendChoice::Auto),
                Err(ConditionedError::InvalidSourceWeight)));
        }
    }

    #[test]
    fn vertex_budget_is_checked_before_dense_allocation() {
        let mut graph = PersistentGraph::new();
        for i in 0..=MAX_CONDITIONED_VERTICES { graph.upsert_vertex(i as u64, 0.0); }
        assert!(matches!(ConditionedSnapshot::from_graph(&graph, 1, BackendChoice::Auto),
            Err(ConditionedError::GraphBudget { .. })));
    }
}
