// `ab`: thin entry point. Everything lives in the library crate (`allegro_buddy::cli::main`);
// this is the ONLY place that calls `std::process::exit`. The aliases in src/bin/
// `include!` this file (so plain comments here: an inner doc comment can't be included).

fn main() {
    let argv: Vec<std::ffi::OsString> = std::env::args_os().collect();
    std::process::exit(allegro_buddy::cli::main(argv));
}
