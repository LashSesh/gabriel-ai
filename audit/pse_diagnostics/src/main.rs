use pse_graph::PersistentGraph;
use pse_topology::{compute_laplacian,spectral_decompose};
use pse_scale::spectral_bisection_cluster;
use std::collections::BTreeSet;
fn main() {
 let mut g=PersistentGraph::new();
 for i in 0..32u64 {for j in (i+1)..32u64 {g.upsert_edge(i,j,0.0);}}
 let lap=compute_laplacian(&g);
 let partial=spectral_decompose(&lap,2);
 let full=spectral_decompose(&lap,32);
 let values:Vec<f64>=(0..8).map(|x| x as f64).collect();
 let ids:Vec<u64>=(0..8).collect();
 let labels=spectral_bisection_cluster(&values,&ids,0.01,1,2);
 let count=labels.values().copied().collect::<BTreeSet<_>>().len();
 println!("{}",serde_json::to_string_pretty(&serde_json::json!({"complete_graph_vertices":32,"directed_single_orientation_edges":496,"symmetric_weight":0.5,"analytic_spectrum":[0.0,16.0],"partial_k":2,"partial":partial,"full_k":32,"full_spectral_gap":full.spectral_gap,"full_eigenvalues":full.eigenvalues,"cluster_requested_max":2,"cluster_count":count,"cluster_labels":labels})).unwrap());
}
