//! Reservations. Mirrors `core.load_reservations`, `active_reservations`,
//! `recent_active_reservations`, `upcoming_reservations`,
//! `reservation_blocked_pending_jobs`, `reserved_nodes_map`, `user_can_use_reservation`.
//! Owned by P2-C.

use super::Record;
use crate::error::Result;
use chrono::NaiveDateTime;
use std::collections::{BTreeSet, HashMap};

/// Active reservations older than this (by StartTime) are not displayed.
pub const RESERVATION_MAX_ACTIVE_DISPLAY_AGE_DAYS: i64 = 30;

/// `load_reservations()`: `scontrol --oneliner show reservation` (unchecked; failure ->
/// `[]`), lines containing `ReservationName=`.
pub fn load_reservations() -> Result<Vec<Record>> {
    todo!()
}

/// `active_reservations(reservations)`: `State` upper == `ACTIVE`.
pub fn active_reservations(reservations: &[Record]) -> Vec<Record> {
    todo!()
}

/// `recent_active_reservations(reservations, now=now)`.
pub fn recent_active_reservations(reservations: &[Record], now: NaiveDateTime) -> Vec<Record> {
    todo!()
}

/// `upcoming_reservations(reservations, now=now)`: INACTIVE and starting in the future.
pub fn upcoming_reservations(reservations: &[Record], now: NaiveDateTime) -> Vec<Record> {
    todo!()
}

/// `reservation_blocked_pending_jobs(resvs, pending_jobs)`.
pub fn reservation_blocked_pending_jobs(resvs: &[Record], pending_jobs: &[Record]) -> Vec<Record> {
    todo!()
}

/// `reserved_nodes_map(reservations)`: node -> reservation name (later reservations win).
pub fn reserved_nodes_map(reservations: &[Record]) -> HashMap<String, String> {
    todo!()
}

/// `user_can_use_reservation(reservation, user, groups)`.
pub fn user_can_use_reservation(
    reservation: &Record,
    user: &str,
    groups: &BTreeSet<String>,
) -> bool {
    todo!()
}
