//! `bab info`, `bab free`, `bab queue`/`q`, `bab node` (and hidden `gpualloc`).
//! Port of `handlers/resources.py`. Owned by P3-D.
//!
//! Notes:
//! * `MAX_WIDTH = 100`: the "You" grid and the "Nodes with free GPUs" packing never get
//!   wider than `min(console.width, 100)`.
//! * `cmd_queue` asks [`super::why::queue_hints`] for bottleneck hints of pending jobs
//!   whose reason is in `fit::HINT_REASONS`.
//! * `--watch` is handled by `cli::watch::run_watched` around these functions; they must
//!   not print outside the consoles.
//! * Python issues several independent read-only queries per command (e.g. info: nodes,
//!   partitions, sacctmgr, squeue, reservations); these may run concurrently via
//!   `core::slurm::parallel` as long as output order and error order stay Python's.

use crate::error::Result;

/// Never wider than this: long lists wrap rather than span a wide terminal.
pub const MAX_WIDTH: usize = 100;

/// `--kind` of `bab free`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Kind {
    Gpu,
    Cpu,
}

/// `guess_node(args_node)`: the argument, this host (full or short hostname via
/// `hooks::hostname`) if it is a node, the node of your running dev job, or of your
/// first running GPU job; else `die("could not guess the node; name it: bab node <node>")`.
pub fn guess_node(node: Option<&str>) -> Result<String> {
    todo!()
}

/// `cmd_info(all_partitions=...)`.
pub fn cmd_info(all_partitions: bool) -> Result<()> {
    todo!()
}

/// `cmd_queue(all_users=, user=, partition=)`.
pub fn cmd_queue(all_users: bool, user: Option<&str>, partition: Option<&str>) -> Result<()> {
    todo!()
}

/// `cmd_free(kind=, show_nodes=, partition_filter=, gpu_type=)`; `gpu_type` is already
/// canonical (cli's `_normalize_gpu_type` callback).
pub fn cmd_free(
    kind: Kind,
    show_nodes: bool,
    partition_filter: Option<&str>,
    gpu_type: Option<&str>,
) -> Result<()> {
    todo!()
}

/// `cmd_node(node=)` (also `gpualloc`).
pub fn cmd_node(node: Option<&str>) -> Result<()> {
    todo!()
}
