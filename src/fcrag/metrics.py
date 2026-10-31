"""Prometheus metrics in the text exposition format, without a client library.

Counters and histograms live in this process; gauges that describe shared state (documents per
status, ingestion queue length) are read when /metrics is scraped, so every API replica reports
the same value. Only counts and timings are exposed: no question, answer or document text.
"""

import threading
from collections.abc import Callable, Iterable

Labels = tuple[tuple[str, str], ...]

LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 6.0, 10.0, 20.0, 60.0)
"""Seconds. 6 s is the plan's end-to-end p95 target."""


def _labels(labels: Labels, extra: str = "") -> str:
    parts = [f'{k}="{_escape(v)}"' for k, v in labels]
    if extra:
        parts.append(extra)
    return "{" + ",".join(parts) + "}" if parts else ""


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(value)


class Counter:
    def __init__(self, name: str, help_text: str) -> None:
        self.name, self.help = name, help_text
        self._values: dict[Labels, float] = {}
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def value(self, **labels: str) -> float:
        return self._values.get(tuple(sorted(labels.items())), 0.0)

    def render(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} counter"
        with self._lock:
            items = sorted(self._values.items())
        for labels, value in items:
            yield f"{self.name}{_labels(labels)} {_number(value)}"


class Histogram:
    def __init__(
        self, name: str, help_text: str, buckets: tuple[float, ...] = LATENCY_BUCKETS
    ) -> None:
        self.name, self.help, self.buckets = name, help_text, buckets
        self._counts: dict[Labels, list[int]] = {}
        self._sums: dict[Labels, float] = {}
        self._lock = threading.Lock()

    def observe(self, value: float, **labels: str) -> None:
        key = tuple(sorted(labels.items()))
        with self._lock:
            counts = self._counts.setdefault(key, [0] * (len(self.buckets) + 1))
            for i, bound in enumerate(self.buckets):
                if value <= bound:
                    counts[i] += 1
            counts[-1] += 1  # +Inf
            self._sums[key] = self._sums.get(key, 0.0) + value

    def render(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} histogram"
        with self._lock:
            items = sorted((k, list(v), self._sums[k]) for k, v in self._counts.items())
        for labels, counts, total in items:
            for bound, count in zip((*self.buckets, float("inf")), counts, strict=True):
                le = "+Inf" if bound == float("inf") else _number(bound)
                yield f"{self.name}_bucket{_labels(labels, f'le="{le}"')} {count}"
            yield f"{self.name}_sum{_labels(labels)} {_number(total)}"
            yield f"{self.name}_count{_labels(labels)} {counts[-1]}"


class Gauge:
    """Read at scrape time from ``read``, which returns (labels, value) pairs."""

    def __init__(
        self, name: str, help_text: str, read: Callable[[], list[tuple[dict[str, str], float]]]
    ) -> None:
        self.name, self.help, self.read = name, help_text, read

    def render(self) -> Iterable[str]:
        try:
            samples = self.read()
        except Exception:
            return  # an unreachable database or queue must not break the whole scrape
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} gauge"
        for labels, value in samples:
            yield f"{self.name}{_labels(tuple(sorted(labels.items())))} {_number(value)}"


HTTP_REQUESTS = Counter(
    "fcrag_http_requests_total", "API requests by route template, method and status code."
)
HTTP_LATENCY = Histogram("fcrag_http_request_duration_seconds", "API request duration by route.")
ANSWERS = Counter("fcrag_answers_total", "Answers by outcome: found (sources) or not_found.")
STAGE_LATENCY = Histogram(
    "fcrag_answer_stage_seconds", "Answer pipeline time per stage (rewrite, embed, ... generate)."
)
LLM_CALLS = Counter(
    "fcrag_llm_calls_total", "LLM calls by model and outcome: ok, retry, fallback, failed."
)
RESPONSE_CACHE = Counter(
    "fcrag_response_cache_total", "Response cache lookups by result: hit or miss."
)
_REGISTRY: list[Counter | Histogram | Gauge] = [
    HTTP_REQUESTS, HTTP_LATENCY, ANSWERS, STAGE_LATENCY, LLM_CALLS, RESPONSE_CACHE,
]  # fmt: skip


def register(metric: Counter | Histogram | Gauge) -> None:
    if all(m.name != metric.name for m in _REGISTRY):
        _REGISTRY.append(metric)


def render() -> str:
    return "\n".join(line for metric in _REGISTRY for line in metric.render()) + "\n"
