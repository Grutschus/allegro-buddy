//! Rich `RegexHighlighter` / `ReprHighlighter` (rich/highlighter.py).
//!
//! `Console.print("some str")` highlights by default (Console(highlight=True)): numbers,
//! quoted strings, paths, URLs, UUIDs, ipv4/ipv6/eui48 ... get `repr.*` styles from Rich's
//! default theme. Table cells are not highlighted (Table(highlight=False)). The patterns
//! below are Rich 15's, verbatim except for escaping `[`/`]` inside character classes
//! (Rust regex syntax); `fancy_regex` provides the lookbehinds.

use super::text::Text;
use super::theme::Theme;
use fancy_regex::Regex;
use std::sync::LazyLock;

/// Rich `RegexHighlighter`: each regex adds `base_style + group name` spans, in order.
#[derive(Debug, Clone)]
pub struct RegexHighlighter {
    pub highlights: Vec<Regex>,
    pub base_style: String,
}

impl RegexHighlighter {
    /// Compile `patterns` (Python `re` syntax that `fancy_regex` understands).
    pub fn new(base_style: &str, patterns: &[&str]) -> Result<RegexHighlighter, fancy_regex::Error> {
        Ok(RegexHighlighter {
            highlights: patterns.iter().map(|p| Regex::new(p)).collect::<Result<_, _>>()?,
            base_style: base_style.to_owned(),
        })
    }

    /// Rich `RegexHighlighter.highlight(text)` (in place).
    pub fn highlight(&self, text: &mut Text, theme: &Theme) {
        for re in &self.highlights {
            text.highlight_regex(re, &self.base_style, theme);
        }
    }
}

static REPR: LazyLock<RegexHighlighter> = LazyLock::new(|| {
    let combined = [
        r"(?P<ipv4>[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3})",
        r"(?P<ipv6>([A-Fa-f0-9]{1,4}::?){1,7}[A-Fa-f0-9]{1,4})",
        r"(?P<eui64>(?:[0-9A-Fa-f]{1,2}-){7}[0-9A-Fa-f]{1,2}|(?:[0-9A-Fa-f]{1,2}:){7}[0-9A-Fa-f]{1,2}|(?:[0-9A-Fa-f]{4}\.){3}[0-9A-Fa-f]{4})",
        r"(?P<eui48>(?:[0-9A-Fa-f]{1,2}-){5}[0-9A-Fa-f]{1,2}|(?:[0-9A-Fa-f]{1,2}:){5}[0-9A-Fa-f]{1,2}|(?:[0-9A-Fa-f]{4}\.){2}[0-9A-Fa-f]{4})",
        r"(?P<uuid>[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})",
        r"(?P<call>[\w.]*?)\(",
        r"\b(?P<bool_true>True)\b|\b(?P<bool_false>False)\b|\b(?P<none>None)\b",
        r"(?P<ellipsis>\.\.\.)",
        r"(?P<number_complex>(?<!\w)(?:\-?[0-9]+\.?[0-9]*(?:e[-+]?\d+?)?)(?:[-+](?:[0-9]+\.?[0-9]*(?:e[-+]?\d+)?))?j)",
        r"(?P<number>(?<!\w)\-?[0-9]+\.?[0-9]*(e[-+]?\d+?)?\b|0x[0-9a-fA-F]*)",
        r"(?P<path>\B(/[-\w._+]+)*\/)(?P<filename>[-\w._+]*)?",
        r#"(?<![\\\w])(?P<str>b?'''.*?(?<!\\)'''|b?'.*?(?<!\\)'|b?""".*?(?<!\\)"""|b?".*?(?<!\\)")"#,
        r"(?P<url>(file|https|http|ws|wss)://[-0-9a-zA-Z$_+!`(),.?/;:&=%#~@]*)",
    ]
    .join("|");
    RegexHighlighter::new(
        "repr.",
        &[
            r"(?P<tag_start><)(?P<tag_name>[-\w.:|]*)(?P<tag_contents>[\w\W]*)(?P<tag_end>>)",
            r#"(?P<attrib_name>[\w_]{1,50})=(?P<attrib_value>"?[\w_]+"?)?"#,
            r"(?P<brace>[\]\[{}()])",
            &combined,
        ],
    )
    .expect("ReprHighlighter patterns")
});

/// Rich `ReprHighlighter`.
pub fn repr_highlighter() -> &'static RegexHighlighter {
    &REPR
}

/// Apply `ReprHighlighter` to `text` in place (Rich `Highlighter.__call__` -> `highlight`).
pub fn highlight_repr(text: &mut Text) {
    REPR.highlight(text, &Theme::default());
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::render::style::Style;

    fn styled(s: &str) -> Vec<(String, Style)> {
        let mut t = Text::new(s);
        highlight_repr(&mut t);
        t.spans()
            .iter()
            .map(|sp| (s.chars().skip(sp.start).take(sp.end - sp.start).collect(), sp.style))
            .collect()
    }

    #[test]
    fn numbers_and_clock() {
        let number = Style::of("bold cyan not italic");
        let spans = styled("Canceled 123, 456_7.");
        assert_eq!(spans[0], ("123".to_owned(), number));
        let spans = styled("every 10s · 12:34:56 · Ctrl-C to quit");
        assert!(spans.iter().any(|(s, _)| s == "12:34:56"));
        assert!(!spans.iter().any(|(s, _)| s == "10"));
    }

    #[test]
    fn strings_and_paths() {
        let spans = styled("see '/tmp/x.txt' now");
        assert!(spans.iter().any(|(s, _)| s == "'/tmp/x.txt'"));
        assert_eq!(spans.len(), 1);
    }
}
