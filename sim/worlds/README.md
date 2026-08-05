# sim/worlds

Gazebo world files (.world / .sdf) for each scenario class.

```
worlds/
  workbench_v0.world     default tabletop, single arm, one camera
  workbench_v0_dual.sdf  dual camera (future)
  inspection_station.sdf flat inspection table, overhead camera (future)
```

World version is pinned in each scenario manifest (`world_version` field).
Changing a world file requires bumping the version string and re-freezing
affected scenarios.
