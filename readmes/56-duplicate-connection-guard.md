# Duplicate Connection Guard — 2026-07-15

## Problem

When connecting stations to traffic circles in the grid generator, both ends of a
station could occasionally connect to the same traffic circle. This creates duplicate
edges in the network graph — double-counted capacity, inflated distances, and
potential routing anomalies.

The root cause: when a single station sits between two traffic circles and the block
spacing is small (<= 1.05 mi), the grid generator's position loop treats the station
as both the first and last element. Both the `pi == 0` and `pi == len(positions) - 1`
conditions fire, connecting both CPs to adjacent traffic circles. In edge cases this
results in both CPs of one station connecting to the same traffic circle.

## Fix

Added a guard at the top of `connect_cps()` in `engine/structures.py` (line 552).
Before creating any connection, the function now checks whether the two structures
are already connected via any existing CP pair. If they are, it returns `[]` silently.

**What changed:** 8 lines added to `connect_cps()`. No other files modified.

**Risk:** Zero. The guard only fires when a duplicate structure-to-structure link is
attempted. All existing valid connections are unaffected. Every caller already handles
an empty return (most ignore the return value).

## Verification

- Build a network with closely-spaced stations near traffic circles
- Confirm each traffic circle connects to each station at most once
- Confirm all existing networks load and simulate without change

**Action assigned to Alice — confirm by 2026-07-22.**
