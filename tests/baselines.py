"""
Versioned simulator baselines (Phase 20).

Replaces the implicit "seed=42 must always equal X events forever"
invariant with an explicit dict.  When the simulator's semantics change
in a way that shifts event counts on purpose, bump SIMULATOR_VERSION in
``core.runs`` and add a new entry here keyed by that version.

Tests should prefer **behavioral invariants** (no double-assignment,
no NaN economics, completion-rate ordering between scenarios) over
exact event counts.  The exact-count assertions that remain are pinned
to ``CURRENT_VERSION`` so a future bump is a one-line update.
"""

from __future__ import annotations

from core.runs import SIMULATOR_VERSION


# {simulator_version: {seed: {n_drones, n_trips, expected_events_written}}}
SIMULATOR_BASELINES: dict[str, dict[int, dict]] = {
    # Phase 14 introduced distance-driven coordinate generation.
    "phase14": {
        42: {"n_drones": 3, "n_trips": 10, "events_written": 156},
    },
    # Phase 15 added run lineage columns + simulation_runs metadata, but did
    # not change event counts.
    "phase15": {
        42: {"n_drones": 3, "n_trips": 10, "events_written": 156},
    },
    # Phase 20 removed simulator-time economics + hybrid decision writes.
    # Event emission itself is unchanged, so the count survives.
    "phase20": {
        42: {"n_drones": 3, "n_trips": 10, "events_written": 156},
    },
    # Phase 21 adds per-ping telemetry RNG draws + an obstacle_warning
    # event type + an onboard remaining-range emergency-return trigger.
    # These shift the seeded sequence; the count drops because the new
    # emergency path can interrupt leg 2 mid-flight.
    "phase21": {
        42: {"n_drones": 3, "n_trips": 10, "events_written": 149},
    },
}


CURRENT_VERSION = SIMULATOR_VERSION


def expected_events(seed: int, version: str = CURRENT_VERSION) -> int:
    """Return the pinned event count for (version, seed), or raise KeyError.

    Test code uses this so a deliberate count change becomes a single
    SIMULATOR_BASELINES edit rather than a sweep through assert sites.
    """
    return SIMULATOR_BASELINES[version][seed]["events_written"]
