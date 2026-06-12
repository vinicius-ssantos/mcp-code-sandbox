from __future__ import annotations

from prometheus_client import Counter, Histogram

executions_total = Counter(
    "sandbox_executions_total",
    "Total sandbox executions",
    ["language", "status"],
)

execution_duration_seconds = Histogram(
    "sandbox_execution_duration_seconds",
    "Sandbox execution duration in seconds",
    ["language"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0],
)

output_bytes_total = Counter(
    "sandbox_output_bytes_total",
    "Total bytes returned in sandbox output streams",
    ["language", "stream"],
)
