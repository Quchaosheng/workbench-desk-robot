# ADR-0001: P0 is a fixed tabletop single-arm simulator

## Status

Accepted for v0.1.

## Decision

Use Ubuntu 24.04, ROS 2 Jazzy and Gazebo Harmonic. P0 demonstrates one active arm moving a known red block into a tray. Mobile base, dual active arms, physical hardware and open-vocabulary perception are out of scope.

## Consequence

The team can prove planning, state, action, verification, recovery and replay in one month. Expansion requires a new ADR after the deterministic baseline passes.
