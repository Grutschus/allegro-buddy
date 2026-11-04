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

use crate::error::{AbError, Result};
use crate::render::console;
use std::time::Duration;

/// `run_watched(render, interval)`.
pub fn run_watched(render: &mut dyn FnMut() -> Result<()>, interval: Option<f64>) -> Result<()> {
    let Some(interval) = interval else {
        return render();
    };
    let (out, err) = (console::stdout(), console::stderr());
    loop {
        out.begin_capture();
        err.begin_capture();
        let result = render();
        let errors = err.end_capture();
        let captured = out.end_capture();
        match result {
            Ok(()) | Err(AbError::Exit(_)) => {}
            Err(AbError::Interrupted) => return Ok(()),
            Err(other) => return Err(other),
        }
        if crate::signals::check().is_err() {
            return Ok(());
        }
        out.clear();
        let now = crate::hooks::now().format("%H:%M:%S");
        out.print_str(
            &format!(
                "every {}s · {now} · Ctrl-C to quit",
                crate::pyfmt::format_g(interval)
            ),
            Some("dim"),
        );
        err.write_raw(&errors);
        out.write_raw(&captured);
        match crate::signals::sleep(sleep_duration(interval)) {
            Ok(()) => {}
            Err(_) => return Ok(()),
        }
    }
}

/// `time.sleep(interval)` for any float the FloatRange accepts (inf/nan included).
fn sleep_duration(interval: f64) -> Duration {
    Duration::try_from_secs_f64(interval).unwrap_or(Duration::MAX)
}
