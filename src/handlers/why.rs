//! `bab why [JOBID] [--nodes] [--fix [auto|mem|cpus|gpus]] [-y]`, plus `queue_hints` used
//! by `bab q`. Port of `handlers/why.py`. Owned by P3-E.
//!
//! Notes:
//! * `--fix` confirmation: `hooks::interactive()` replaces `sys.stdin.isatty()`;
//!   `click.confirm('Apply?', default=False)` is `cli::prompt::confirm`.
//! * `_apply_fix` ends with a bare `raise SystemExit(1)` when the re-read does not match:
//!   return `Err(AbError::Exit(1))` (nothing printed by that line itself).
//! * `_start_text` uses `datetime.fromtimestamp(planned_start)` (local time):
//!   `core::timefmt::local_iso_from_epoch`.

use crate::core::jobs::JobRecord;
use crate::error::Result;
use crate::fit::{MemLimits, NodeCapacity};
use std::collections::{BTreeSet, HashMap};

/// `--fix` choice.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FixChoice {
    Auto,
    Mem,
    Cpus,
    Gpus,
}

/// `Inputs`: job records, node capacities, partition memory limits.
pub type Inputs = (Vec<JobRecord>, Vec<NodeCapacity>, MemLimits);

/// `load_inputs(strict=, job_id=)`: `load_job_records`, `load_nodes`, `load_partitions`
/// (independent read-only queries; may run concurrently).
pub fn load_inputs(strict: bool, job_id: Option<&str>) -> Result<Inputs> {
    todo!()
}

/// `queue_hints(job_ids)` -> (raw job id -> hint, error text). Never fails: any error
/// becomes `Some("<ExceptionType>: <message>")` like Python's
/// `f'{type(exc).__name__}: {exc}'` (only reachable for unexpected record shapes; mirror
/// what can happen with malformed JSON fields, e.g. `TypeError`/`ValueError`).
pub fn queue_hints(job_ids: &BTreeSet<String>) -> (HashMap<String, String>, Option<String>) {
    todo!()
}

/// `cmd_why(jobid=, show_nodes=, fix=, assume_yes=)`.
pub fn cmd_why(
    jobid: Option<&str>,
    show_nodes: bool,
    fix: Option<FixChoice>,
    assume_yes: bool,
) -> Result<()> {
    todo!()
}
