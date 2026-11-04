//! A byte-exact subset of Rich 15.0.0 (owned by P2-A).
//!
//! Python allegro-buddy prints everything through Rich; bab must emit the SAME bytes,
//! including ANSI SGR sequences, wrapping, padding and trailing whitespace. Reference source:
//! `rich==15.0.0` (install it into a private venv under /srv/public/plainer to read it; the
//! compat harness pins the same version). When this doc and Rich disagree, Rich wins.
//!
//! # Pipeline (as in Rich)
//!
//! renderable (`Text`, `Table`, `str` with markup) --render(console, options)--> lines of
//! [`segment::Segment`]s (text + optional [`style::Style`]) --> the console joins them,
//! rendering each styled segment as `ESC[<sgr>m<text>ESC[0m` (Rich `Style.render`; no SGR
//! when the console has no colour system), appends `"\n"` per line and writes (or captures).
//!
//! # Pieces
//!
//! * [`style`]: `Style` (attributes + colours), Rich's style-definition parser, SGR codes.
//! * [`segment`]: `Segment`, line splitting/cropping helpers (Rich `Segment`).
//! * [`cells`]: terminal cell width of strings (Rich `cell_len` / `set_cell_size`, via
//!   unicode-width with Rich's table semantics; verify ambiguous chars like `ⓘ`, `·`, `…`, `→`, `≤`).
//! * [`text`]: `Text` with spans (Rich `Text`): append/assemble/join, wrap, render.
//! * [`markup`]: Rich console markup (`[bold red]..[/]`) -> `Text`, used for plain `str`
//!   printed via `Console.print(str)` and `str` table cells (Rich `render_str`).
//! * [`highlight`]: Rich `ReprHighlighter` (numbers, ipv6-looking clock times, paths, ...),
//!   applied to plain `str` printed with `Console.print(str)` (highlight=True by default) but
//!   NOT to `Text` objects and NOT to table cells (Table(highlight=False)).
//! * [`table`]: `Table` (Rich `Table` with `box.SIMPLE`, `show_edge=False`, `pad_edge=False`
//!   as used by `core.render_table`) and `Table::grid` (as used by `ab info`'s "You" block),
//!   including Rich's column width algorithm (`_calculate_column_widths`, collapse/ratio
//!   reduce, wrapping, `…` overflow).
//! * [`console`]: `Console` (stdout/stderr singletons, width, colour detection, print,
//!   capture for `--watch`, clear, status spinner).
//!
//! # The `Renderable` trait
//!
//! Anything printable implements [`Renderable`]. Rendering never writes; the console does.

pub mod cells;
pub mod console;
pub mod highlight;
pub mod markup;
pub mod segment;
pub mod style;
pub mod table;
pub mod text;

pub use console::{Console, stderr, stdout};
pub use segment::Segment;
pub use style::Style;
pub use table::{Cell, Column, Justify, Table};
pub use text::{Text, TextPart};

/// Rich `ConsoleOptions` subset needed by bab's renderables.
#[derive(Debug, Clone, PartialEq)]
pub struct RenderOptions {
    /// Maximum width in cells for this render (`options.max_width`).
    pub max_width: usize,
    /// Justification override (`options.justify`), `None` = renderable's own/default.
    pub justify: Option<Justify>,
    /// Overflow override (`options.overflow`), `None` = renderable's own (`fold` default).
    pub overflow: Option<text::Overflow>,
    /// `options.no_wrap`.
    pub no_wrap: bool,
    /// `options.markup` (for `str` renderables).
    pub markup: bool,
    /// `options.highlight` (for `str` renderables).
    pub highlight: bool,
    /// `options.is_terminal` (some renderables, e.g. status, behave differently).
    pub is_terminal: bool,
}

/// Rich `Measurement`: minimum and maximum width (cells) a renderable needs.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Measurement {
    pub minimum: usize,
    pub maximum: usize,
}

/// Something the console can print (Rich `__rich_console__` + `__rich_measure__`).
pub trait Renderable {
    /// Render to lines of segments (no trailing newline segments; the console adds `\n`).
    /// Mirrors `Console.render_lines(renderable, options, pad=False)` semantics for
    /// top-level printing; tables pad their cells themselves.
    fn render_lines(&self, console: &Console, options: &RenderOptions) -> Vec<Vec<Segment>>;

    /// Rich `__rich_measure__` (used by tables to size columns).
    fn measure(&self, console: &Console, options: &RenderOptions) -> Measurement;
}
