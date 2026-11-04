//! Rich `Console` subset: the two process-wide consoles and everything they do.
//! Owned by P2-A.
//!
//! Python has `CONSOLE = Console()` and `ERROR_CONSOLE = Console(stderr=True)` in core.py;
//! here they are [`stdout()`] and [`stderr()`] (lazily created, `Sync`, interior mutability).
//!
//! # Detection (Rich 15.0.0 `Console.__init__`, `is_terminal`, `size`, `_detect_color_system`)
//!
//! Replicate exactly, per console (stdout vs stderr file):
//! * `is_terminal`: `FORCE_COLOR` (non-empty? check Rich 15) forces True; `TTY_COMPATIBLE`
//!   (`1`/`0`, Rich 14+) overrides; else `isatty(fd)`. `is_dumb_terminal`: `TERM` in
//!   (`dumb`, `unknown`). `is_interactive` (Rich 14+, `TTY_INTERACTIVE`) for the spinner.
//! * colour system: `None` when not a terminal or dumb; else `COLORTERM` in
//!   (`truecolor`, `24bit`) -> TrueColor; `TERM` ends with `-256color` -> EightBit,
//!   `-16color` -> Standard; else Standard. `NO_COLOR` (non-empty) strips colours, keeps
//!   attributes. Also check `FORCE_COLOR` + `NO_COLOR` interplay and Rich's `JUPYTER`/
//!   Windows branches (ignore those).
//! * width: `COLUMNS` (digits) wins, even when piped; else the terminal size from the
//!   first of stdin/stdout/stderr that has one (Rich tries all three fds!); else 80.
//!   Dumb terminal -> 80. Height similarly (`LINES`, 25). Width is re-read every time
//!   (`Console.width` property) unless Rich caches it: check.
//!
//! # Printing (`Console.print(*objects, style=None, width=None)`)
//!
//! Renders with `options.max_width = min(width, console.width)`, joins segments (each
//! styled segment -> `Style.render`, colour stripped for NO_COLOR, nothing for no colour
//! system), one `"\n"` after each line, then writes and flushes (or appends to the capture
//! buffer). `print()` with no objects writes `"\n"`. A `str` object goes through
//! `render_str(markup=True, highlight=True)` (see [`super::markup`], [`super::highlight`])
//! and `style=` is the base style.
//!
//! # Capture (`with CONSOLE.capture() as c:` in `run_watched`)
//!
//! While capturing, output is rendered exactly as it would be printed (same colour
//! system / width) but appended to a buffer; [`Console::end_capture`] returns it. Nested
//! captures are not needed. Both consoles are captured independently.
//!
//! # Clear and status
//!
//! * [`Console::clear`]: Rich `clear(home=True)`: when `is_terminal`, writes `ESC[2J` + `ESC[H`
//!   (Rich `Control.clear()`, `Control.home()`); nothing otherwise.
//! * [`Console::status`]: `Console.status(text)` with spinner `dots`, transient: only
//!   animates when the console is interactive (terminal, not dumb); writes nothing
//!   otherwise. Rendering per refresh (12.5/s? Rich Live default refresh_per_second=12.5),
//!   hides the cursor while active, and clears its line(s) on stop. Implement with a
//!   background thread and `Status::update` / `Drop`. Must not interleave with other output
//!   (Rich redirects stdout through Live while active: prints during status go above it).

use super::style::{ColorSystem, Style};
use super::text::Text;
use super::{RenderOptions, Renderable};
use std::sync::Mutex;

/// The stdout console (Python `core.CONSOLE`).
pub fn stdout() -> &'static Console {
    todo!()
}

/// The stderr console (Python `core.ERROR_CONSOLE`).
pub fn stderr() -> &'static Console {
    todo!()
}

/// Which stream a console writes to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Stream {
    Stdout,
    Stderr,
}

/// Per-console mutable state.
#[derive(Debug, Default)]
struct ConsoleState {
    /// `Some(buffer)` while capturing.
    capture: Option<String>,
}

/// A Rich console bound to stdout or stderr.
#[derive(Debug)]
pub struct Console {
    stream: Stream,
    state: Mutex<ConsoleState>,
}

/// Extra arguments of `Console.print`.
#[derive(Debug, Clone, Copy, Default, PartialEq)]
pub struct PrintOptions {
    /// `width=`: capped at the console width.
    pub width: Option<usize>,
    /// `style=`: base style for the printed objects.
    pub style: Option<Style>,
}

impl Console {
    pub fn stream(&self) -> Stream {
        self.stream
    }

    /// `Console.width`.
    pub fn width(&self) -> usize {
        todo!()
    }

    /// `Console.is_terminal`.
    pub fn is_terminal(&self) -> bool {
        todo!()
    }

    /// `Console.is_interactive` (spinner).
    pub fn is_interactive(&self) -> bool {
        todo!()
    }

    /// `Console.color_system` (`None` = no colour).
    pub fn color_system(&self) -> Option<ColorSystem> {
        todo!()
    }

    /// `NO_COLOR` in effect.
    pub fn no_color(&self) -> bool {
        todo!()
    }

    /// Default render options for this console (`Console.options`).
    pub fn options(&self) -> RenderOptions {
        todo!()
    }

    /// `print(renderable)`.
    pub fn print(&self, renderable: &dyn Renderable) {
        self.print_with(renderable, PrintOptions::default())
    }

    /// `print(renderable, width=..., style=...)`.
    pub fn print_with(&self, renderable: &dyn Renderable, options: PrintOptions) {
        todo!()
    }

    /// `print(some_str, style=...)`: markup + ReprHighlighter, `style` as base style.
    pub fn print_str(&self, s: &str, style: Option<&str>) {
        todo!()
    }

    /// `print()`: an empty line.
    pub fn newline(&self) {
        todo!()
    }

    /// Write already-rendered bytes (or append to the capture buffer). Used by `run_watched`
    /// to replay captured frames (`sys.stdout.write(capture.get())`).
    pub fn write_raw(&self, s: &str) {
        todo!()
    }

    /// Start capturing (`Console.begin_capture`).
    pub fn begin_capture(&self) {
        todo!()
    }

    /// Stop capturing and return what was printed meanwhile (`Console.end_capture`).
    pub fn end_capture(&self) -> String {
        todo!()
    }

    /// `Console.clear()` (only on a terminal).
    pub fn clear(&self) {
        todo!()
    }

    /// `Console.status(text)`: transient spinner while the returned guard lives.
    pub fn status(&'static self, text: Text) -> Status {
        todo!()
    }
}

/// A running `Console.status` spinner; stops (and erases itself) on drop.
#[derive(Debug)]
pub struct Status {
    console: &'static Console,
}

impl Status {
    /// `status.update(text)`.
    pub fn update(&self, text: Text) {
        todo!()
    }
}

impl Drop for Status {
    fn drop(&mut self) {
        // P2-A: stop the spinner thread and erase the transient line.
    }
}
