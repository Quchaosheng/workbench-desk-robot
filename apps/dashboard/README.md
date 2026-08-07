# Dashboard (Owner: Interaction)

Read-only task status, evidence, and replay UI for Workbench-1.

```bash
python -m workbench_backend.server --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080`. The backend serves committed fixture runs by default and can be pointed at any directory of ordered `.jsonl` event streams with `--data-dir`.

The HTTP boundary deliberately implements `GET` only. `POST`, `PUT`, `PATCH`, and `DELETE` return `405 read_only`; there is no ROS, MCU, motion, or emergency-stop publisher in this application.

Vendored UI dependency: Lucide `0.468.0`, ISC license in `vendor/LUCIDE-LICENSE.txt`.
