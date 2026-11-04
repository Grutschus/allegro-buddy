//! Partitions: loading, access, ordering, per-partition stats, dev partition choice.
//! Mirrors `core.load_partitions`, `partition_allowed`, `sort_partitions`,
//! `get_accessible_partitions`, `choose_partition`, `PartitionStats`, `_summarize`,
//! `summarize_partitions`, `summarize_selected_partitions`. Owned by P2-C.

use super::Record;
use super::gpu::GpuCounts;
use super::nodes::Node;
use crate::error::Result;
use std::collections::{BTreeSet, HashMap};

/// A partition: the `scontrol --oneliner show partition` record (`PartitionName`,
/// `MaxTime`, `AllowGroups`, `DenyGroups`, `Default`, `MaxMemPerCPU`, ...).
pub type Partition = Record;

/// `load_partitions(strict=strict)`: `scontrol --oneliner show partition` (checked iff
/// strict); on failure (unchecked) `[]`.
pub fn load_partitions(strict: bool) -> Result<Vec<Partition>> {
    todo!()
}

/// `partition_allowed(partition, groups)` (DenyGroups first, then AllowGroups; `ALL`
/// and nullish mean everyone).
pub fn partition_allowed(partition: &Partition, groups: &BTreeSet<String>) -> bool {
    todo!()
}

/// `sort_partitions(partitions)`: GPU partitions first, families (`gpu-a100`,
/// `gpu-a100:test`) together, shortest family MaxTime first, then family name, MaxTime,
/// name. MaxTime None/0 counts as infinity (`parse_slurm_time(...) or inf`). Uses
/// `is_gpu_partition(name)` with detection (may load nodes, like Python).
pub fn sort_partitions(partitions: Vec<Partition>) -> Vec<Partition> {
    todo!()
}

/// `get_accessible_partitions(include_all=...)`: load (strict), filter by group access
/// unless `include_all`, sort.
pub fn get_accessible_partitions(include_all: bool) -> Result<Vec<Partition>> {
    todo!()
}

/// `choose_partition(partition_name, gpu_count, cpus, time_limit)` for `dev start`:
/// resolves `auto` to the `Default=YES` partition, validates access and MaxTime; every
/// failure is a `die()` with Python's exact message.
pub fn choose_partition(partition_name: &str, time_limit: &str) -> Result<String> {
    todo!()
}

/// `PartitionStats`.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct PartitionStats {
    pub nodes: i64,
    pub idle_nodes: i64,
    pub cpu_total: i64,
    pub cpu_free: i64,
    pub mem_total_gb: i64,
    pub mem_free_gb: i64,
    pub gpu_total: i64,
    pub gpu_free: i64,
    pub gpu_usable: i64,
    pub gpu_total_by_type: GpuCounts,
    pub gpu_free_by_type: GpuCounts,
    pub gpu_usable_by_type: GpuCounts,
}

/// `summarize_partitions(names, nodes=nodes)`: stats per partition name (every name
/// present, even without nodes). Memory per node is `round(mb / 1024)` (half to even)
/// BEFORE summing, like Python.
pub fn summarize_partitions(names: &[String], nodes: &[Node]) -> HashMap<String, PartitionStats> {
    todo!()
}

/// `summarize_selected_partitions(partition_names, nodes=nodes)`: one merged bucket
/// (each node counted once); empty set -> empty stats.
pub fn summarize_selected_partitions(names: &BTreeSet<String>, nodes: &[Node]) -> PartitionStats {
    todo!()
}
