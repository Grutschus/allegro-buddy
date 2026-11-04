//! Rich `Table` (Rich 15.0.0 `rich/table.py`, `rich/box.py`). Owned by P2-A.
//!
//! # Configurations bab uses
//!
//! 1. [`Table::simple`] == `core.render_table`'s table:
//!    `Table(title=title, title_style="bold", box=box.SIMPLE, show_edge=False,
//!    pad_edge=False, header_style="bold")`, columns via `add_column(header, justify=...)`,
//!    rows via `add_row(*cells, end_section=...)`, printed with
//!    `CONSOLE.print(table, width=width)` (width = `min(width, console.width)`).
//!    Rich details that matter: title centred over the table width in `title_style`
//!    (`Text` justify center, then the line padded? check), header row bold, the SIMPLE
//!    box's head row separator `─` spanning all columns incl. padding, an `end_section`
//!    row followed by an empty separator line (SIMPLE's `row` line is blank: rendered as
//!    spaces), padding (0, 1) between columns with `pad_edge=False` dropping the outer
//!    padding, `collapse_padding=False`, cell `justify` (left/right/center), `expand=False`,
//!    and Rich's width algorithm when the table is wider than `max_width`
//!    (`_calculate_column_widths`: measure each column (min = longest word, max = longest
//!    line), shrink wrapable columns via `_collapse_widths` + `ratio_reduce`, then wrap the
//!    cells; non-wrapable overflow -> `…` with `overflow="ellipsis"`? check per column).
//!    Trailing spaces: Rich pads every cell to the column width, so lines carry trailing
//!    spaces (e.g. `"all           7/8       0/4"` lines are padded to table width).
//! 2. [`Table::grid`] == `Table.grid(padding=(0, 2))` in `resources._render_you`: no box,
//!    no header, no edge padding, `collapse_padding=True`; first column
//!    `add_column(style="dim", no_wrap=True)`, second column wraps with a hanging indent
//!    (continuation lines start at the column). Printed with
//!    `CONSOLE.print(grid, width=min(CONSOLE.width, 100))`.
//!
//! Cells are [`Cell`]s: `Text` renders as is; `Str` goes through markup (Rich renders a
//! `str` cell with `console.render_str(cell, markup=True, highlight=False)`; verify the
//! highlight flag against Rich 15's Table, which passes `highlight=self.highlight`).
//!
//! rich-click help (P2-B) may need more box styles/panels; add them here or in a sibling
//! module (`render::panel`) as needed.

use super::style::Style;
use super::text::Text;
use super::{Measurement, RenderOptions, Renderable, Segment};

/// Rich `JustifyMethod`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default)]
pub enum Justify {
    #[default]
    Default,
    Left,
    Center,
    Right,
    Full,
}

/// Box drawing style (Rich `rich.box`). Add more if rich-click help needs them.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum BoxStyle {
    /// `box.SIMPLE`.
    Simple,
}

/// A table cell: a styled `Text`, or a `str` that Rich renders with markup.
#[derive(Debug, Clone, PartialEq)]
pub enum Cell {
    Text(Text),
    Str(String),
}

impl From<Text> for Cell {
    fn from(t: Text) -> Cell {
        Cell::Text(t)
    }
}

impl From<&str> for Cell {
    fn from(s: &str) -> Cell {
        Cell::Str(s.to_owned())
    }
}

impl From<String> for Cell {
    fn from(s: String) -> Cell {
        Cell::Str(s)
    }
}

/// Rich `Column` subset.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Column {
    pub header: String,
    pub justify: Justify,
    /// Column style (applied under the cell contents), e.g. `dim` in the grid.
    pub style: Style,
    pub no_wrap: bool,
}

/// One row: cells plus Rich's `end_section` flag.
#[derive(Debug, Clone, PartialEq)]
pub struct Row {
    pub cells: Vec<Cell>,
    pub end_section: bool,
}

/// Rich `Table` subset (see module docs).
#[derive(Debug, Clone, PartialEq)]
pub struct Table {
    pub title: Option<String>,
    pub title_style: Style,
    pub box_style: Option<BoxStyle>,
    pub show_header: bool,
    pub header_style: Style,
    pub show_edge: bool,
    pub pad_edge: bool,
    /// (top, right, bottom, left) as Rich normalizes `padding`.
    pub padding: (usize, usize, usize, usize),
    pub collapse_padding: bool,
    pub expand: bool,
    pub columns: Vec<Column>,
    pub rows: Vec<Row>,
}

impl Table {
    /// The `core.render_table` configuration (SIMPLE box, bold title/header, no edges).
    pub fn simple(title: Option<&str>) -> Table {
        todo!()
    }

    /// `Table.grid(padding=(vertical, horizontal))`.
    pub fn grid(vertical: usize, horizontal: usize) -> Table {
        todo!()
    }

    /// `add_column(header, justify=justify)`.
    pub fn add_column(&mut self, header: &str, justify: Justify) -> &mut Table {
        todo!()
    }

    /// `add_column(**full spec)`, e.g. the grid's `style="dim", no_wrap=True` column.
    pub fn add_column_spec(&mut self, column: Column) -> &mut Table {
        todo!()
    }

    /// `add_row(*cells, end_section=end_section)`.
    pub fn add_row(&mut self, cells: Vec<Cell>, end_section: bool) -> &mut Table {
        todo!()
    }
}

impl Renderable for Table {
    fn render_lines(&self, console: &super::Console, options: &RenderOptions) -> Vec<Vec<Segment>> {
        todo!()
    }

    fn measure(&self, console: &super::Console, options: &RenderOptions) -> Measurement {
        todo!()
    }
}
