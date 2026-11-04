//! Jobs: details, JSON records, history, pending jobs, dev jobs, job output files.
//! Owned by P2-C. Each function names its Python original.

use super::Record;
use crate::error::Result;
use chrono::NaiveDateTime;
use std::path::PathBuf;

/// One `scontrol --json show job` record (`jobs[i]`), used by `fit` and `why`.
pub type JobRecord = serde_json::Value;

/// `USER_JOB_DETAIL_LIMIT`: past this many jobs one full listing beats per-job calls.
pub const USER_JOB_DETAIL_LIMIT: usize = 20;
/// `SQUEUE_PENDING_HEADERS`.
pub const SQUEUE_PENDING_HEADERS: [&str; 5] = ["JobID", "Name", "Partition", "TimeLimit", "Reason"];

/// `display_job_id(job)`: `ArrayJobId_ArrayTaskId` for array tasks, else `JobId`.
pub fn display_job_id(job: &Record) -> String {
    todo!()
}

/// `parse_job_detail_line(line)`: props + `NodeBlocks` (everything after the first
/// ` Nodes=`) for per-node lookups.
pub fn parse_job_detail_line(line: &str) -> Record {
    todo!()
}

/// `job_on_node(job, node)`: that node's `Nodes=... CPU_IDs=... Mem=... GRES=...` block.
pub fn job_on_node(job: &Record, node: &str) -> Record {
    todo!()
}

/// `job_gres_on_node(job, node)`: the block's `GRES`, or the job's `GRES` without blocks.
pub fn job_gres_on_node(job: &Record, node: &str) -> String {
    todo!()
}

/// `load_job_details(job_id)`: `scontrol --oneliner --details show job [id]`, checked only
/// without an id; failure with an id -> `[]`.
pub fn load_job_details(job_id: Option<&str>) -> Result<Vec<Record>> {
    todo!()
}

/// `get_job_detail(job_id)`: first record or None.
pub fn get_job_detail(job_id: &str) -> Result<Option<Record>> {
    todo!()
}

/// `get_user_jobs(user, name=name)`: `squeue -h --user=U --format=%F [--name=N]` (checked),
/// unique base ids in order; more than [`USER_JOB_DETAIL_LIMIT`] -> one full
/// `load_job_details(None)` filtered by user/name, else `load_job_details(id)` per id
/// (sequential in Python; these are read-only and may run via `slurm::parallel`, keeping
/// the order of results).
pub fn get_user_jobs(user: Option<&str>, name: Option<&str>) -> Result<Vec<Record>> {
    todo!()
}

/// `load_running_jobs()`: all job details in [`super::RUNNING_STATES`].
pub fn load_running_jobs() -> Result<Vec<Record>> {
    todo!()
}

/// `load_job_records(job_id, strict=strict)`: `scontrol --json show job [id]`; checked
/// only when strict and no id; non-zero -> `[]`; bad JSON -> strict:
/// `die("this needs a Slurm whose `scontrol --json show job` works", exit_code=2)`, else `[]`.
pub fn load_job_records(job_id: Option<&str>, strict: bool) -> Result<Vec<JobRecord>> {
    todo!()
}

/// `load_user_pending_jobs(user)`: `squeue -h --state=PD --user=U --format=%i|%j|%P|%l|%R`
/// (unchecked; failure -> `[]`) with [`SQUEUE_PENDING_HEADERS`].
pub fn load_user_pending_jobs(user: Option<&str>) -> Result<Vec<Record>> {
    todo!()
}

/// Time deltas in seconds (`timedelta.total_seconds()`; None when unknown).
pub type Etas = Vec<Option<f64>>;

/// `get_user_job_etas(user, now=now)`: (pending start deltas, running end deltas).
/// Consumers truncate with `int()`.
pub fn get_user_job_etas(user: Option<&str>, now: NaiveDateTime) -> Result<(Etas, Etas)> {
    todo!()
}

/// `load_job_history(user, strict=strict, since=since)`: sacct over a bounded window,
/// normalized (`JobId`, `StateToken`, `HistorySource`), newest first, unique by JobId.
/// Error message adds the `SLURM_CONF` tip for `host:localhost:6819`.
pub fn load_job_history(user: Option<&str>, strict: bool, since: &str) -> Result<Vec<Record>> {
    todo!()
}

/// `get_user_job_history(user, finished_only=..., strict=..., since=...)`: without dev jobs.
pub fn get_user_job_history(
    user: Option<&str>,
    finished_only: bool,
    strict: bool,
    since: &str,
) -> Result<Vec<Record>> {
    todo!()
}

/// `job_history_completion_ids(incomplete, user)` (2-day window, never fails).
pub fn job_history_completion_ids(incomplete: &str, user: Option<&str>) -> Vec<String> {
    todo!()
}

/// `resolve_slurm_output_path(template, job_id, raw_id=, name=, user=)`: `%J %j %A %a %x
/// %u %%` with zero-pad widths; unknown patterns kept; then `os.path.expandvars` and
/// `expanduser`. None for nullish templates.
pub fn resolve_slurm_output_path(
    template: &str,
    job_id: &str,
    raw_id: &str,
    name: &str,
    user: &str,
) -> Option<PathBuf> {
    todo!()
}

/// Which output stream (`OutputStream`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OutputStream {
    Stdout,
    Stderr,
}

impl OutputStream {
    /// `"stdout"` / `"stderr"` as used in messages.
    pub fn as_str(self) -> &'static str {
        match self {
            OutputStream::Stdout => "stdout",
            OutputStream::Stderr => "stderr",
        }
    }
}

/// `resolve_job_output_path(job_id, stream=, user=)`: scontrol detail, else the sacct
/// fallback; None when unknown or owned by someone else.
pub fn resolve_job_output_path(
    job_id: &str,
    stream: OutputStream,
    user: Option<&str>,
) -> Result<Option<PathBuf>> {
    todo!()
}

/// `read_log_tail(path, max_lines=)`: last N lines (UTF-8, errors replaced; 0 = all);
/// OSError -> `die("could not read {path}: {exc}")` with Python's `str(OSError)` format
/// (`[Errno 13] Permission denied: '/path'`).
pub fn read_log_tail(path: &std::path::Path, max_lines: usize) -> Result<String> {
    todo!()
}

/// `get_job_output(job_id, stream=, tail_lines=, user=)` -> (path, text), with the
/// Python die() messages for unresolvable/missing/non-file paths.
pub fn get_job_output(
    job_id: &str,
    stream: OutputStream,
    tail_lines: usize,
    user: Option<&str>,
) -> Result<(PathBuf, String)> {
    todo!()
}

/// `find_dev_jobs(user, job_id=)`: active (not COMPLETING) `ab-dev` jobs, RUNNING first,
/// newest SubmitTime first.
pub fn find_dev_jobs(user: Option<&str>, job_id: Option<&str>) -> Result<Vec<Record>> {
    todo!()
}
