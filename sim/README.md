# Simulation

Perception owns scenarios; Integration owns world assets. The repository currently
contains deterministic scenario manifests and a bounded runner control surface,
but it does **not** contain a complete Gazebo world, perception bridge, or grasp
adapter yet. Scripted event logs are pipeline fixtures, never hardware or Gazebo
evidence.

## Operator entry points

Run these from the repository root:

```bash
python tools/scripts/sim_cli.py doctor
python tools/scripts/sim_cli.py list
python tools/scripts/sim_cli.py run normal-001 --runner scripted --output-dir runs/sim
python tools/scripts/sim_cli.py run --all --runner gazebo
```

`doctor` only diagnoses dependencies. `list` validates every manifest and shows
the deterministic materialized-scene hash. `sim_cli run` publishes an atomic run
artifact containing the source manifest, materialized scene, event log (when one
exists), stdout/stderr, metadata, and checksums.

The default Gazebo runner requires a configured, tokenized command in
`WORKBENCH_GAZEBO_COMMAND` or an explicit `--command` argument. A missing
adapter is `NOT_EXECUTED` with a non-zero exit code. A scripted run is always
labelled `SCRIPTED_FIXTURE` and `release_eligible: false`.

## Reproducibility boundary

The same manifest and seed produce the same materialized scene and scene hash.
That guarantee does not extend to Gazebo event ordering, physics timing, sensor
noise, or hardware behavior. Raw runner logs and metadata are retained so those
differences remain inspectable.

## Ownership boundary

Do not modify robot control logic to make scenarios easier. A future real-world
runner must apply the manifest seed, world version, fault type, reset isolation,
and timeout, then emit the existing validated event-log contract. It must not
promote a fixture or a missing dependency to a passing regression.
