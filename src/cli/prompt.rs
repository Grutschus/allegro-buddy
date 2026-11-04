//! `click.confirm`. Owned by P2-B.
//!
//! `click.confirm('Apply?', default=False)` prints `Apply? [y/N]: ` (click's prompt
//! suffix; via click.echo to stdout, no newline), reads a line from stdin:
//! `y`/`yes` -> true, `n`/`no` -> false, empty -> default, anything else ->
//! `Error: invalid input` and ask again; EOF or Ctrl-C -> `click.Abort` (click echoes a
//! newline first) -> `Err(AbError::Abort)`.

use crate::error::Result;

/// `click.confirm(text, default=default)`.
pub fn confirm(text: &str, default: bool) -> Result<bool> {
    todo!()
}
