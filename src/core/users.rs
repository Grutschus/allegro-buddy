//! Who is running bab. Mirrors `core.current_user`, `core.current_groups`,
//! `core.user_accounts`. Owned by P2-C.

use super::Record;
use crate::error::Result;
use std::collections::BTreeSet;

/// `current_user()` = `getpass.getuser()` via [`crate::hooks::user`].
pub fn current_user() -> &'static str {
    crate::hooks::user()
}

/// `current_groups()` via [`crate::hooks::groups`].
pub fn current_groups() -> &'static BTreeSet<String> {
    crate::hooks::groups()
}

/// `user_accounts(user)`: `sacctmgr -nP show user <user> withassoc [cluster=<name>]
/// format=DefaultAccount,Account,QOS`, unchecked, rows with keys `DefaultAccount`,
/// `Account`, `QOS`. The cluster name comes from `settings::slurm_cluster_name()` (cached
/// file / `scontrol show config`).
pub fn user_accounts(user: &str) -> Result<Vec<Record>> {
    todo!()
}
