//! Prints what bab resolves as the current user and groups (getpass.getuser /
//! getgroups + getgrgid_r via NSS), one group per line, sorted. Compare with Python's
//! `allegro_buddy.core.current_groups()` on a real cluster: `bench/live/nss_check.sh`.

fn main() {
    println!("user {}", bab::core::users::current_user());
    for group in bab::core::users::current_groups() {
        println!("group {group}");
    }
}
