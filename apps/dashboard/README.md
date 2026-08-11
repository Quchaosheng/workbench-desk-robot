# Dashboard (Owner: Interaction)

Read-only task status, evidence, and replay UI for Workbench-1.

```bash
python -m workbench_backend.server --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080`. A run can be deep-linked with `?run=<run_id>`; the parcel fixture uses `?run=dashboard-parcel--parcel-intake-003`. The backend serves committed fixture runs by default and can be pointed at any directory of ordered `.jsonl` event streams with `--data-dir`.

Parcel runs include a read-only decision table that shows the observed label and
condition, the policy-derived destination, and whether the actual placement
matches that decision.

The HTTP boundary deliberately implements `GET` only. `POST`, `PUT`, `PATCH`, and `DELETE` return `405 read_only`; there is no ROS, MCU, motion, or emergency-stop publisher in this application.

Vendored UI dependency: Lucide `0.468.0`, ISC license in `vendor/LUCIDE-LICENSE.txt`.

The dashboard follows a two-tab keyboard model: `Left`/`Right` (or `Up`/`Down`) changes views, while `Home` and `End` jump to the first or last view. Filters and run selection expose pressed state, replay exposes playback and position state, and the active mobile run scrolls into view. Nonessential motion is suppressed when the operating system requests reduced motion.
