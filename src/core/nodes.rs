//! Nodes: loading, the per-process node facts cache, GPU partition detection and per-node
//! free capacity. Mirrors `core.load_nodes`, `nodes_from_json`, `node_from_props`,
//! `remember_nodes`, `node_facts`, `is_gpu_partition`, `node_is_*`, `node_free`,
//! `node_gpu_type_counts`, `infer_node_gpu_type`. Owned by P2-C.
//!
//! # Node facts cache (plan amendment 6)
//!
//! Python keeps `_NODE_FACTS`, overwritten by EVERY `load_nodes()` call
//! (`remember_nodes`), and lazily filled by `node_facts()` (which calls
//! `load_nodes(strict=False)` if nothing was loaded yet). Styling helpers
//! (`partition_text`, `node_text`) and `is_gpu_partition(detect=False)` only read what is
//! loaded and never call Slurm. Here: a process-wide `RwLock<Option<Arc<NodeFacts>>>`;
//! [`remember_nodes`] replaces it, [`loaded_node_facts`] reads without loading,
//! [`node_facts`] loads on first use. `load_nodes` itself is NOT cached: Python calls Slurm
//! again on every `load_nodes()` and the call log must match.

use super::Record;
use super::gpu::GpuCounts;
use crate::error::Result;
use std::collections::BTreeSet;
use std::sync::Arc;

/// One node, in the shape `nodes_from_json` returns (all values strings, like Python).
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct Node {
    /// `NodeName`
    pub name: String,
    /// `State`, e.g. `MIXED+PLANNED` (JSON state list joined by `+`).
    pub state: String,
    /// `CPUTot`
    pub cpu_tot: String,
    /// `CPUAlloc`
    pub cpu_alloc: String,
    /// `RealMemory` (MB)
    pub real_memory: String,
    /// `AllocMem` (MB)
    pub alloc_mem: String,
    /// `Gres` (`(null)` when empty)
    pub gres: String,
    /// `GresUsed`
    pub gres_used: String,
    /// `Partitions`, comma-separated
    pub partitions: String,
    /// `ActiveFeatures`, comma-separated
    pub active_features: String,
    /// `Features`, comma-separated
    pub features: String,
    /// `Reservation`
    pub reservation: String,
    /// `SpecMem` (MB)
    pub spec_mem: String,
}

impl Node {
    /// `node.get(key)` by the Python dict key (`"NodeName"`, `"Gres"`, ...); None if unknown.
    pub fn get(&self, key: &str) -> Option<&str> {
        Some(match key {
            "NodeName" => &self.name,
            "State" => &self.state,
            "CPUTot" => &self.cpu_tot,
            "CPUAlloc" => &self.cpu_alloc,
            "RealMemory" => &self.real_memory,
            "AllocMem" => &self.alloc_mem,
            "Gres" => &self.gres,
            "GresUsed" => &self.gres_used,
            "Partitions" => &self.partitions,
            "ActiveFeatures" => &self.active_features,
            "Features" => &self.features,
            "Reservation" => &self.reservation,
            "SpecMem" => &self.spec_mem,
            _ => return None,
        })
    }

    /// Partition names (empty items skipped), in order.
    pub fn partition_list(&self) -> impl Iterator<Item = &str> {
        self.partitions.split(',').filter(|p| !p.is_empty())
    }
}

/// `NodeFacts`.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct NodeFacts {
    pub names: BTreeSet<String>,
    pub gpu_nodes: BTreeSet<String>,
    pub gpu_partitions: BTreeSet<String>,
}

/// `load_nodes(strict=strict)`: `scontrol --json show nodes` (unchecked); if that fails or
/// its JSON is unusable, fall back to `scontrol --oneliner show node` (checked iff
/// `strict`). Always calls [`remember_nodes`].
pub fn load_nodes(strict: bool) -> Result<Vec<Node>> {
    todo!()
}

/// `nodes_from_json(stdout)`; Err for invalid JSON / wrong shape (Python ValueError /
/// AttributeError -> fallback). Handles Slurm 22.05 string `state` + `state_flags`.
pub fn nodes_from_json(stdout: &str) -> std::result::Result<Vec<Node>, String> {
    todo!()
}

/// `node_from_props(props)` for the oneliner fallback.
pub fn node_from_props(props: &Record) -> Node {
    todo!()
}

/// `remember_nodes(nodes)`: replace the facts cache.
pub fn remember_nodes(nodes: &[Node]) {
    todo!()
}

/// The facts of the last `load_nodes`, without calling Slurm (`_NODE_FACTS`).
pub fn loaded_node_facts() -> Option<Arc<NodeFacts>> {
    todo!()
}

/// `node_facts()`: loads nodes (`strict=False`, which cannot fail) if none were loaded yet.
pub fn node_facts() -> Arc<NodeFacts> {
    todo!()
}

/// `is_gpu_partition(name, detect=detect)`: `[cluster] gpu-partitions` if configured,
/// else whether a loaded node with GPUs is in it; `detect=true` may load nodes
/// (via [`node_facts`]).
pub fn is_gpu_partition(name: &str, detect: bool) -> bool {
    todo!()
}

/// `node_is_usable(node)`: no [`super::BAD_NODE_FLAGS`] substring in the upper-cased state.
pub fn node_is_usable(node: &Node) -> bool {
    todo!()
}

/// `node_is_idle(node)`: `IDLE` in state.
pub fn node_is_idle(node: &Node) -> bool {
    todo!()
}

/// `node_is_mixed(node)`: `MIXED` in state.
pub fn node_is_mixed(node: &Node) -> bool {
    todo!()
}

/// `infer_node_gpu_type(node)`: from ActiveFeatures, AvailableFeatures (never set in our
/// node shape, always None), Features.
pub fn infer_node_gpu_type(node: &Node) -> Option<String> {
    todo!()
}

/// `node_gpu_type_counts(node)`: `Gres` counts, generic GPUs re-typed by features.
pub fn node_gpu_type_counts(node: &Node) -> GpuCounts {
    todo!()
}

/// `NodeFree`.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct NodeFree {
    pub cpu_total: i64,
    pub cpu_free: i64,
    pub mem_total_mb: i64,
    pub mem_free_mb: i64,
    pub gpu_total_by_type: GpuCounts,
    pub gpu_free_by_type: GpuCounts,
}

/// `node_free(node)`: the one place the free-capacity math lives.
pub fn node_free(node: &Node) -> NodeFree {
    todo!()
}
