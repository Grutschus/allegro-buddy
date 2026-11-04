//! Differential test of `bab::render` against rich==15.0.0.
//!
//! `tests/render/cases.json` (written by `tools/render/make_cases.py`) describes console
//! operations; `tests/render/expected.json` holds what real Rich printed for them (written by
//! `tools/render/rich_ref.py`). This test replays every case with bab's renderer and demands
//! byte equality with the committed expectations. With `BAB_RICH_PY=/path/to/python` (a venv
//! with rich==15.0.0) it also re-runs the Python reference live and compares against that;
//! add `BAB_RICH_REGEN=1` to rewrite `expected.json`. `BAB_RENDER_DUMP=file` writes bab's
//! output (same JSON shape) for inspection.

use bab::render::console::{ColorChoice, ConsoleConfig};
use bab::render::style::ColorSystem;
use bab::render::table::{Cell, Column, Table};
use bab::render::text::{Justify, Overflow, Text, TextPart};
use bab::render::theme::style;
use bab::render::{BoxStyle, Console, Padding, PrintOptions, Renderable, VerticalAlign};
use serde_json::{Map, Value};
use std::collections::BTreeMap;
use std::path::Path;
use std::rc::Rc;

fn justify(v: &Value) -> Justify {
    match v.as_str().unwrap() {
        "default" => Justify::Default,
        "left" => Justify::Left,
        "center" => Justify::Center,
        "right" => Justify::Right,
        "full" => Justify::Full,
        other => panic!("justify {other}"),
    }
}

fn overflow(v: &Value) -> Overflow {
    match v.as_str().unwrap() {
        "fold" => Overflow::Fold,
        "crop" => Overflow::Crop,
        "ellipsis" => Overflow::Ellipsis,
        "ignore" => Overflow::Ignore,
        other => panic!("overflow {other}"),
    }
}

fn text_part(v: &Value) -> TextPart {
    match v {
        Value::String(s) => TextPart::Plain(s.clone()),
        Value::Array(a) => TextPart::Styled(a[0].as_str().unwrap().to_owned(), style(a[1].as_str().unwrap())),
        _ => TextPart::Text(build_text(v)),
    }
}

fn build_text(spec: &Value) -> Text {
    match spec["type"].as_str().unwrap() {
        "text" => {
            let base = style(spec.get("style").and_then(Value::as_str).unwrap_or(""));
            let mut text = match spec.get("plain") {
                Some(plain) => Text::with_style(plain.as_str().unwrap(), base),
                None => {
                    let parts = spec.get("parts").and_then(Value::as_array).cloned().unwrap_or_default();
                    let mut t = Text::assemble(parts.iter().map(text_part));
                    t.style = base;
                    t
                }
            };
            if let Some(v) = spec.get("justify") {
                text.justify = Some(justify(v));
            }
            if let Some(v) = spec.get("overflow") {
                text.overflow = Some(overflow(v));
            }
            if let Some(v) = spec.get("no_wrap") {
                text.no_wrap = v.as_bool();
            }
            if let Some(v) = spec.get("end") {
                text.end = v.as_str().unwrap().to_owned();
            }
            for s in spec.get("stylize").and_then(Value::as_array).into_iter().flatten() {
                let s = s.as_array().unwrap();
                text.stylize(style(s[0].as_str().unwrap()), s[1].as_i64().unwrap() as isize, s[2].as_i64().map(|e| e as isize));
            }
            for a in spec.get("append").and_then(Value::as_array).into_iter().flatten() {
                let a = a.as_array().unwrap();
                text.append(a[0].as_str().unwrap(), a[1].as_str());
            }
            text
        }
        "join" => {
            let items: Vec<Text> = spec["items"].as_array().unwrap().iter().map(build_text).collect();
            build_text(&spec["sep"]).join(items)
        }
        other => panic!("not a text: {other}"),
    }
}

fn cell(v: &Value) -> Cell {
    match v {
        Value::String(s) => Cell::Str(s.clone()),
        _ => match v["type"].as_str().unwrap() {
            "text" | "join" => Cell::Text(build_text(v)),
            _ => Cell::Renderable(build(v)),
        },
    }
}

struct OwnedPadding {
    inner: Rc<dyn Renderable>,
    pad: (usize, usize, usize, usize),
    expand: bool,
}

impl OwnedPadding {
    fn padding(&self) -> Padding<'_> {
        let mut p = Padding::new(self.inner.as_ref(), self.pad);
        p.expand = self.expand;
        p
    }
}

impl Renderable for OwnedPadding {
    fn render(&self, console: &Console, options: &bab::render::RenderOptions) -> Vec<bab::render::Segment> {
        self.padding().render(console, options)
    }
    fn measure(&self, console: &Console, options: &bab::render::RenderOptions) -> bab::render::Measurement {
        self.padding().measure(console, options)
    }
}

fn build(spec: &Value) -> Rc<dyn Renderable> {
    match spec["type"].as_str().unwrap() {
        "text" | "join" => Rc::new(build_text(spec)),
        "padding" => {
            let pad: Vec<usize> = spec["pad"].as_array().unwrap().iter().map(|v| v.as_u64().unwrap() as usize).collect();
            let inner: Rc<dyn Renderable> = match &spec["renderable"] {
                Value::String(s) => Rc::new(cell(&Value::String(s.clone()))),
                v => build(v),
            };
            Rc::new(OwnedPadding {
                inner,
                pad: Padding::unpack(&pad),
                expand: spec.get("expand").and_then(Value::as_bool).unwrap_or(true),
            })
        }
        "table" => Rc::new(build_table(spec)),
        other => panic!("unknown renderable {other}"),
    }
}

fn opt_str<'a>(m: &'a Map<String, Value>, k: &str) -> Option<&'a str> {
    m.get(k).and_then(Value::as_str)
}

fn build_table(spec: &Value) -> Table {
    let mut table = if spec.get("simple").and_then(Value::as_bool) == Some(true) {
        Table::simple(spec.get("title").and_then(Value::as_str))
    } else if let Some(grid) = spec.get("grid") {
        let g: Vec<usize> = grid.as_array().unwrap().iter().map(|v| v.as_u64().unwrap() as usize).collect();
        Table::grid(g[0], g[1])
    } else {
        Table::new()
    };
    for (key, value) in spec.get("options").and_then(Value::as_object).cloned().unwrap_or_default() {
        match key.as_str() {
            "box" => table.box_style = value.as_str().map(|n| BoxStyle::named(n).unwrap()),
            "title" => table.title = Some(cell(&value)),
            "caption" => table.caption = Some(cell(&value)),
            "show_lines" => table.show_lines = value.as_bool().unwrap(),
            "show_header" => table.show_header = value.as_bool().unwrap(),
            "show_footer" => table.show_footer = value.as_bool().unwrap(),
            "show_edge" => table.show_edge = value.as_bool().unwrap(),
            "pad_edge" => table.pad_edge = value.as_bool().unwrap(),
            "expand" => table.expand = value.as_bool().unwrap(),
            "highlight" => table.highlight = value.as_bool().unwrap(),
            "collapse_padding" => table.collapse_padding = value.as_bool().unwrap(),
            "leading" => table.leading = value.as_u64().unwrap() as usize,
            "width" => table.width = value.as_u64().map(|v| v as usize),
            "min_width" => table.min_width = value.as_u64().map(|v| v as usize),
            "border_style" => table.border_style = style(value.as_str().unwrap()),
            "row_styles" => table.row_styles = value.as_array().unwrap().iter().map(|s| style(s.as_str().unwrap())).collect(),
            "padding" => {
                let p: Vec<usize> = value.as_array().unwrap().iter().map(|v| v.as_u64().unwrap() as usize).collect();
                table.padding = Padding::unpack(&p);
            }
            other => panic!("table option {other}"),
        }
    }
    for c in spec.get("columns").and_then(Value::as_array).into_iter().flatten() {
        let m = c.as_object().unwrap();
        let mut column = Column {
            header: m.get("header").map_or(Cell::Str(String::new()), cell),
            footer: m.get("footer").map_or(Cell::Str(String::new()), cell),
            ..Column::default()
        };
        if let Some(s) = opt_str(m, "style") {
            column.style = style(s);
        }
        if let Some(s) = opt_str(m, "header_style") {
            column.header_style = style(s);
        }
        if let Some(v) = m.get("justify") {
            column.justify = justify(v);
        }
        if let Some(v) = m.get("overflow") {
            column.overflow = overflow(v);
        }
        if let Some(v) = opt_str(m, "vertical") {
            column.vertical = match v {
                "top" => VerticalAlign::Top,
                "middle" => VerticalAlign::Middle,
                _ => VerticalAlign::Bottom,
            };
        }
        column.no_wrap = m.get("no_wrap").and_then(Value::as_bool).unwrap_or(false);
        column.ratio = m.get("ratio").and_then(Value::as_u64).map(|v| v as usize);
        column.width = m.get("width").and_then(Value::as_u64).map(|v| v as usize);
        column.min_width = m.get("min_width").and_then(Value::as_u64).map(|v| v as usize);
        column.max_width = m.get("max_width").and_then(Value::as_u64).map(|v| v as usize);
        column.highlight = Some(m.get("highlight").and_then(Value::as_bool).unwrap_or(table.highlight));
        table.add_column_spec(column);
    }
    for r in spec.get("rows").and_then(Value::as_array).into_iter().flatten() {
        let cells = r["cells"].as_array().unwrap().iter().map(cell).collect();
        let row_style = r.get("style").and_then(Value::as_str).map(style);
        let end_section = r.get("end_section").and_then(Value::as_bool).unwrap_or(false);
        table.add_row_styled(cells, row_style, end_section);
    }
    table
}

fn print_options(kw: Option<&Value>) -> PrintOptions {
    let mut o = PrintOptions::default();
    let Some(kw) = kw.and_then(Value::as_object) else {
        return o;
    };
    for (key, value) in kw {
        match key.as_str() {
            "style" => o.style = Some(style(value.as_str().unwrap())),
            "width" => o.width = value.as_u64().map(|v| v as usize),
            "end" => o.end = value.as_str().unwrap().to_owned(),
            "soft_wrap" => o.soft_wrap = value.as_bool(),
            "highlight" => o.highlight = value.as_bool(),
            "markup" => o.markup = value.as_bool(),
            "emoji" => o.emoji = value.as_bool(),
            "no_wrap" => o.no_wrap = value.as_bool(),
            "overflow" => o.overflow = Some(overflow(value)),
            "crop" => o.crop = value.as_bool().unwrap(),
            other => panic!("print kw {other}"),
        }
    }
    o
}

fn run(case: &Value, variant: &Value) -> String {
    let color = match variant["color"].as_str().unwrap() {
        "none" => None,
        "standard" => Some(ColorSystem::Standard),
        "256" => Some(ColorSystem::EightBit),
        "truecolor" => Some(ColorSystem::TrueColor),
        other => panic!("color {other}"),
    };
    let console = Console::new(ConsoleConfig {
        stream: None,
        force_terminal: Some(true),
        color_system: ColorChoice::Fixed(color),
        width: Some(variant["width"].as_u64().unwrap() as usize),
        height: Some(25),
        no_color: Some(variant["no_color"].as_bool().unwrap()),
        env: Some(Default::default()),
        ..ConsoleConfig::default()
    });
    for op in case["ops"].as_array().unwrap() {
        if let Some(spec) = op.get("print") {
            let options = print_options(op.get("kw"));
            match spec {
                Value::String(s) => console.print_str_with(s, options),
                _ => console.print_with(build(spec).as_ref(), options),
            }
        } else if op.get("newline").is_some() {
            console.newline();
        } else if op.get("clear").is_some() {
            console.clear();
        } else {
            panic!("op {op}");
        }
    }
    console.take_output()
}

fn variant_name(case: &Value, variant: &Value) -> String {
    format!(
        "{}-w{}-{}{}",
        case["name"].as_str().unwrap(),
        variant["width"],
        variant["color"].as_str().unwrap(),
        if variant["no_color"].as_bool().unwrap() { "-nocolor" } else { "" }
    )
}

fn compare(label: &str, actual: &BTreeMap<String, String>, expected: &BTreeMap<String, String>) -> Vec<String> {
    let mut failures = Vec::new();
    for (name, want) in expected {
        let got = actual.get(name).map(String::as_str).unwrap_or("<missing>");
        if got != want {
            failures.push(format!("[{label}] {name}\n--- rich\n{want:?}\n--- bab\n{got:?}"));
        }
    }
    failures
}

#[test]
fn render_matches_rich() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let cases_path = root.join("tests/render/cases.json");
    let expected_path = root.join("tests/render/expected.json");
    let cases: Vec<Value> = serde_json::from_str(&std::fs::read_to_string(&cases_path).unwrap()).unwrap();
    let mut actual = BTreeMap::new();
    for case in &cases {
        for variant in case["variants"].as_array().unwrap() {
            actual.insert(variant_name(case, variant), run(case, variant));
        }
    }
    if let Ok(dump) = std::env::var("BAB_RENDER_DUMP") {
        std::fs::write(dump, serde_json::to_string_pretty(&actual).unwrap()).unwrap();
    }
    let mut failures = Vec::new();
    if let Ok(python) = std::env::var("BAB_RICH_PY") {
        let output = std::process::Command::new(python)
            .arg(root.join("tools/render/rich_ref.py"))
            .arg(&cases_path)
            .output()
            .expect("run BAB_RICH_PY");
        assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
        if std::env::var("BAB_RICH_REGEN").as_deref() == Ok("1") {
            std::fs::write(&expected_path, &output.stdout).unwrap();
        }
        let live: BTreeMap<String, String> = serde_json::from_slice(&output.stdout).unwrap();
        failures.extend(compare("live", &actual, &live));
    }
    let expected: BTreeMap<String, String> =
        serde_json::from_str(&std::fs::read_to_string(&expected_path).unwrap()).unwrap();
    assert_eq!(expected.len(), actual.len(), "expected.json is stale: regenerate it");
    failures.extend(compare("fixture", &actual, &expected));
    let count = failures.len();
    for failure in failures.iter().take(8) {
        eprintln!("{failure}\n");
    }
    assert!(failures.is_empty(), "{count} render mismatches");
}
