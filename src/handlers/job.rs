//! `bab job history` and `bab job output`. Port of `handlers/job.py`. Owned by P3-F.

use crate::error::Result;

/// `cmd_job_history(limit=)` (0 or negative: all).
pub fn cmd_job_history(limit: i64) -> Result<()> {
    todo!()
}

/// `cmd_job_output(jobid=, stderr=)`.
pub fn cmd_job_output(jobid: &str, stderr: bool) -> Result<()> {
    todo!()
}
