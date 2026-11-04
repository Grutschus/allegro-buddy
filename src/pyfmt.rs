//! Python formatting helpers whose exact output shows up in user-facing messages.
//!
//! Owned by P2-C. All of these must match CPython 3.12 byte for byte.

/// `repr(s)` for a `str`: single quotes unless the string contains `'` and no `"`;
/// escapes `\\`, the chosen quote, `\n`, `\r`, `\t`, other non-printable characters as
/// `\xNN` / `\uNNNN` / `\UNNNNNNNN` (printable per `str.isprintable`).
/// Used by `{x!r}` in messages, e.g. `unknown --gpu-type 'foo'`.
pub fn repr_str(s: &str) -> String {
    todo!()
}

/// `repr(list_of_str)`: `['a', 'b']` (empty: `[]`). Used for `sorted(SECTIONS)` etc.
pub fn repr_list<S: AsRef<str>>(items: &[S]) -> String {
    todo!()
}

/// `shlex.quote(s)`: `''` for empty, `s` unchanged when it only has `[A-Za-z0-9_@%+=:,./-]`
/// (Python `\w` here is ASCII because of `re.ASCII`), else `'...'` with `'` -> `'"'"'`.
pub fn shlex_quote(s: &str) -> String {
    todo!()
}

/// `shlex.join(argv)`: `shlex_quote` each element, joined by single spaces.
pub fn shlex_join<S: AsRef<str>>(argv: &[S]) -> String {
    todo!()
}

/// `format(value, 'g')` / `f'{value:g}'`: 6 significant digits, no trailing zeros,
/// exponent form outside 1e-4..1e16 (`10.0` -> `10`, `2.5` -> `2.5`, `1e+20`).
pub fn format_g(value: f64) -> String {
    todo!()
}
