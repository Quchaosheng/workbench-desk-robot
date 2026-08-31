# OmniLink integration

This is an optional HTTP adapter to a separately hosted [OmniLink AI](https://github.com/vivekmaru/omnilink-ai) instance.
It adds knowledge search, RAG questions, and one-way export of Workbench run summaries.

## Quick start

```python
from integrations.omnilink import OmniLinkClient, RunSummaryExporter

client = OmniLinkClient("http://127.0.0.1:3000")
results = client.search("gripper calibration")
answer = client.ask("Which calibration notes mention the gripper?")
RunSummaryExporter(client, "http://127.0.0.1:8080").export(run_summary)
```

Keep OmniLink in its own process/container and database. The adapter never sends raw event streams,
`TaskGraph`, `SemanticAction`, action results, camera data, or safety state. OmniLink being unavailable
must not block Workbench's offline/control paths; catch `OmniLinkError` at optional call sites.

Before deployment, bind OmniLink to a private interface, put authentication/TLS/rate limiting in front
of it, allowlist outbound URLs, pin the OmniLink commit/image digest, and review its license and Gemini
data handling policy.
