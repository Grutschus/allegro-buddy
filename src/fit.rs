//! Match a pending job's request against the free capacity of each node. Port of
//! `fit.py` (pure: callers load Slurm data and pass it in). Owned by P2-C; port
//! `tests/test_fit.py` (on `main`) as unit tests.
//!
//! Requests come from `scontrol --json show job` records ([`JobRecord`]); memory/CPUs
//! from the per-unit fields (`memory_per_tres`, `memory_per_cpu`, `cpus_per_tres`), not
//! `tres_req_str` (stale after `scontrol update`).
//!
//! Python's `Counter.most_common()` order (count desc, ties in first-seen order) matters
//! for `Diagnosis::skipped`; `Counter` iteration (first-seen) for `skip_summary(short)`.

use crate::core::jobs::JobRecord;
use crate::core::nodes::Node;
use crate::core::partitions::Partition;
use std::collections::{BTreeSet, HashMap};

/// `Dim`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Dim {
    Gpus,
    Cpus,
    Mem,
}

impl Dim {
    /// `'gpus'` / `'cpus'` / `'mem'`.
    pub fn as_str(self) -> &'static str {
        match self {
            Dim::Gpus => "gpus",
            Dim::Cpus => "cpus",
            Dim::Mem => "mem",
        }
    }
}

/// `MemMode`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum MemMode {
    Node,
    Cpu,
    Gpu,
}

pub const DIMS: [Dim; 3] = [Dim::Gpus, Dim::Cpus, Dim::Mem];
/// Ties in "which resource binds" go to the scarcest first.
pub const BOTTLENECK_ORDER: [Dim; 3] = [Dim::Gpus, Dim::Mem, Dim::Cpus];
/// `HINT_REASONS`.
pub const HINT_REASONS: [&str; 2] = ["Resources", "Priority"];
pub const MAX_SLOTS: usize = 5;
pub const UNLIMITED_THRESHOLD: i64 = 1 << 62;

pub const SKIP_DOWN: &str = "down or drained";
pub const SKIP_FEATURE: &str = "missing feature";
pub const SKIP_GPU: &str = "no matching GPU";
pub const SKIP_EXCLUDED: &str = "excluded";
pub const SKIP_NOT_REQUESTED: &str = "not in requested nodes";
pub const SKIP_OUTSIDE_RESERVATION: &str = "outside its reservation";
pub const RESERVATION_PREFIX: &str = "reservation ";

/// `DIM_LABELS`.
pub fn dim_label(dim: Dim) -> &'static str {
    match dim {
        Dim::Gpus => "GPU",
        Dim::Cpus => "CPU",
        Dim::Mem => "mem",
    }
}

/// `Amount`: GPUs, CPUs and memory (MB) on one node.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default)]
pub struct Amount {
    pub gpus: i64,
    pub cpus: i64,
    pub mem: i64,
}

impl Amount {
    pub fn get(&self, dim: Dim) -> i64 {
        match dim {
            Dim::Gpus => self.gpus,
            Dim::Cpus => self.cpus,
            Dim::Mem => self.mem,
        }
    }

    pub fn covers(&self, need: &Amount) -> bool {
        DIMS.iter().all(|&d| self.get(d) >= need.get(d))
    }

    pub fn short_of(&self, need: &Amount) -> Vec<Dim> {
        DIMS.iter()
            .copied()
            .filter(|&d| self.get(d) < need.get(d))
            .collect()
    }
}

/// `NodeCapacity`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeCapacity {
    pub name: String,
    /// Upper-cased state.
    pub state: String,
    pub partitions: BTreeSet<String>,
    pub features: BTreeSet<String>,
    pub reservation: String,
    pub cpus_total: i64,
    pub cpus_free: i64,
    pub mem_total: i64,
    pub mem_free: i64,
    /// Sorted by type.
    pub gpus_total: Vec<(String, i64)>,
    pub gpus_free: Vec<(String, i64)>,
}

impl NodeCapacity {
    /// `NodeCapacity.from_node(node)`.
    pub fn from_node(node: &Node) -> NodeCapacity {
        todo!()
    }

    /// Backfill has set the node aside (`PLANNED` in state).
    pub fn planned(&self) -> bool {
        self.state.contains("PLANNED")
    }

    /// GPUs of one canonical type (all for None), free or total.
    pub fn gpus(&self, kind: Option<&str>, free: bool) -> i64 {
        todo!()
    }
}

/// `JobRequest` (see `fit.py` for every field's meaning).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct JobRequest {
    pub job_id: String,
    pub display_id: String,
    pub update_id: String,
    pub user: String,
    pub state: String,
    pub reason: String,
    pub partitions: Vec<String>,
    pub node_count: i64,
    pub gpus: i64,
    pub gpu_type: Option<String>,
    pub gpu_kind: Option<String>,
    pub cpus: i64,
    pub cpus_per_gpu: Option<i64>,
    pub min_cpus: i64,
    pub mem_mode: MemMode,
    pub mem_value: i64,
    pub tres_per_node: String,
    pub gpus_per_job: bool,
    /// Alternatives of required features; `Some(vec![])` = no constraint, `None` = an
    /// expression fit does not evaluate.
    pub features: Option<Vec<BTreeSet<String>>>,
    pub excluded: BTreeSet<String>,
    pub required: BTreeSet<String>,
    pub reservation: String,
    pub exclusive: bool,
    pub het: bool,
    pub pending_tasks: i64,
    pub planned_nodes: String,
    pub planned_start: Option<i64>,
}

impl JobRequest {
    /// `JobRequest.from_record(record)`.
    pub fn from_record(record: &JobRecord) -> JobRequest {
        todo!()
    }

    /// `--mem=0`: all of a node's memory.
    pub fn whole_node_mem(&self) -> bool {
        self.mem_mode == MemMode::Node && self.mem_value == 0
    }

    pub fn mem_for(&self, gpus: i64, cpus: i64) -> i64 {
        todo!()
    }

    /// The per-node request before node-specific adjustments.
    pub fn amount(&self) -> Amount {
        todo!()
    }

    pub fn need_on(&self, node: &NodeCapacity, mem_per_cpu_limit: Option<i64>) -> Amount {
        todo!()
    }

    pub fn free_on(&self, node: &NodeCapacity) -> Amount {
        todo!()
    }

    pub fn total_on(&self, node: &NodeCapacity) -> Amount {
        todo!()
    }

    pub fn knob_value(&self, knob: Dim) -> i64 {
        todo!()
    }

    pub fn with_knob(&self, knob: Dim, value: i64) -> JobRequest {
        todo!()
    }

    /// `--mem` / `--mem-per-cpu` / `--mem-per-gpu` / `--cpus-per-gpu` / `CPUs` / `GPUs`.
    pub fn knob_flag(&self, knob: Dim) -> &'static str {
        todo!()
    }

    /// The in-place `scontrol update` for a knob, if any.
    pub fn update_command(&self, knob: Dim, value: i64) -> Option<Vec<String>> {
        todo!()
    }
}

/// `NodeFit`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NodeFit {
    pub node: NodeCapacity,
    pub need: Amount,
    pub free: Amount,
    pub total: Amount,
    pub limit: Option<i64>,
}

impl NodeFit {
    pub fn short(&self) -> Vec<Dim> {
        self.free.short_of(&self.need)
    }

    pub fn fits(&self) -> bool {
        self.free.covers(&self.need)
    }

    pub fn holds(&self) -> bool {
        self.total.covers(&self.need)
    }
}

/// `Fix`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Fix {
    pub knob: Dim,
    pub old: i64,
    pub new: i64,
    pub request: JobRequest,
    pub nodes: Vec<String>,
    pub command: Option<Vec<String>>,
}

impl Fix {
    /// `(old - new) / old`.
    pub fn cut(&self) -> f64 {
        (self.old - self.new) as f64 / self.old as f64
    }
}

/// `Slot`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Slot {
    pub free: Amount,
    pub nodes: Vec<String>,
}

/// `Diagnosis`.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Diagnosis {
    pub request: JobRequest,
    pub rows: Vec<NodeFit>,
    /// `Counter.most_common()` of skip reasons.
    pub skipped: Vec<(String, i64)>,
    pub fixes: Vec<Fix>,
    pub slots: Vec<Slot>,
}

impl Diagnosis {
    pub fn fits(&self) -> Vec<String> {
        todo!()
    }

    pub fn fits_now(&self) -> bool {
        todo!()
    }

    pub fn never_fits(&self) -> bool {
        todo!()
    }

    pub fn unavailable(&self) -> Vec<(String, i64)> {
        todo!()
    }

    pub fn planned(&self) -> BTreeSet<String> {
        todo!()
    }

    pub fn dims(&self) -> Vec<Dim> {
        todo!()
    }

    pub fn short_count(&self, dim: Dim) -> i64 {
        todo!()
    }

    pub fn best_free(&self, dim: Dim) -> i64 {
        todo!()
    }

    pub fn max_total(&self, dim: Dim) -> i64 {
        todo!()
    }

    pub fn bottleneck(&self) -> Dim {
        todo!()
    }

    pub fn fix_for(&self, knob: Dim) -> Option<&Fix> {
        self.fixes.iter().find(|f| f.knob == knob)
    }

    /// In-place fixes first, then non-GPU, then the smallest cut (first wins ties, like
    /// Python `min`).
    pub fn lead_fix(&self) -> Option<&Fix> {
        todo!()
    }
}

/// Partition -> `MaxMemPerCPU` (None = no limit).
pub type MemLimits = HashMap<String, Option<i64>>;

/// `mem_to_mb("40G")` -> 40960 (ceil; unparseable 0).
pub fn mem_to_mb(token: &str) -> i64 {
    todo!()
}

/// `format_mem(mb)`: `40G` or `1536M`.
pub fn format_mem(mb: i64) -> String {
    todo!()
}

/// `round_down_mb(mb)`.
pub fn round_down_mb(mb: i64) -> i64 {
    if mb >= 1024 { mb / 1024 * 1024 } else { mb }
}

/// `count_array_tasks(spec)`.
pub fn count_array_tasks(spec: &str) -> i64 {
    todo!()
}

/// `mem_per_cpu_limits(partitions)`.
pub fn mem_per_cpu_limits(partitions: &[Partition]) -> MemLimits {
    todo!()
}

/// `find_record(records, jobid)`: by id, else array match (pending first).
pub fn find_record<'a>(records: &'a [JobRecord], jobid: &str) -> Option<&'a JobRecord> {
    todo!()
}

/// `skip_reason(request, node)`.
pub fn skip_reason(request: &JobRequest, node: &NodeCapacity) -> Option<String> {
    todo!()
}

/// `diagnose(request, nodes, mem_per_cpu_limits)`.
pub fn diagnose(request: &JobRequest, nodes: &[NodeCapacity], limits: &MemLimits) -> Diagnosis {
    todo!()
}

/// `join_names(names, limit)`: `gpu110 +2`.
pub fn join_names(names: &[String], limit: usize) -> String {
    todo!()
}

/// `format_free(dim, value)`.
pub fn format_free(dim: Dim, value: i64) -> String {
    todo!()
}

/// `format_need(dim, value)`.
pub fn format_need(dim: Dim, value: i64) -> String {
    todo!()
}

/// `skip_summary(skipped, short=)`.
pub fn skip_summary(skipped: &[(String, i64)], short: bool) -> String {
    todo!()
}

/// `never_fits_reason(diagnosis)`.
pub fn never_fits_reason(diagnosis: &Diagnosis) -> String {
    todo!()
}

/// `fix_phrase(fix)`.
pub fn fix_phrase(fix: &Fix) -> String {
    todo!()
}

/// `queue_hint(diagnosis)`: the `Node/Reason` cell of `bab q`.
pub fn queue_hint(diagnosis: &Diagnosis) -> String {
    todo!()
}
