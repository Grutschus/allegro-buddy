//! `--watch`: Python `run_watched`. Owned by P2-B.
//!
//! ```text
//! interval None -> render() once, errors propagate.
//! loop:
//!   capture stdout console AND stderr console; run render(); an Err(AbError::Exit(_))
//!     (die / SystemExit) is swallowed after its message was captured;
//!     Err(Interrupted) ends the loop -> Ok(()) (exit 0); other errors propagate.
//!   stdout console .clear()                       (ESC[2J ESC[H on a terminal only)
//!   stdout console .print_str(f"every {interval:g}s · {time.strftime('%H:%M:%S')} · Ctrl-C to quit", style="dim")
//!                                                 (a plain str: markup + highlighting!)
//!   write captured stderr to stderr, flush; write captured stdout to stdout, flush
//!   signals::sleep(interval)  (Ctrl-C -> Ok(()))
//! ```
//! The clock comes from `hooks::now()`; `{interval:g}` from `pyfmt::format_g`.

use crate::error::Result;

/// `run_watched(render, interval)`.
pub fn run_watched(render: &mut dyn FnMut() -> Result<()>, interval: Option<f64>) -> Result<()> {
    todo!()
}
