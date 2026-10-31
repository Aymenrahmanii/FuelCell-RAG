"""Prometheus text format: counters, cumulative histogram buckets, scrape-time gauges."""

from fcrag.metrics import Counter, Gauge, Histogram


def test_counter_and_label_escaping() -> None:
    c = Counter("t_requests_total", "Requests.")
    c.inc(path="/ask", status="200")
    c.inc(2, path="/ask", status="200")
    c.inc(path='a"b\\c', status="500")
    lines = list(c.render())
    assert lines[:2] == ["# HELP t_requests_total Requests.", "# TYPE t_requests_total counter"]
    assert 't_requests_total{path="/ask",status="200"} 3' in lines
    assert 't_requests_total{path="a\\"b\\\\c",status="500"} 1' in lines


def test_histogram_buckets_are_cumulative() -> None:
    h = Histogram("t_seconds", "Latency.", buckets=(0.1, 1.0))
    for value in (0.05, 0.5, 5.0):
        h.observe(value, stage="rerank")
    lines = list(h.render())
    assert 't_seconds_bucket{stage="rerank",le="0.1"} 1' in lines
    assert 't_seconds_bucket{stage="rerank",le="1"} 2' in lines
    assert 't_seconds_bucket{stage="rerank",le="+Inf"} 3' in lines
    assert 't_seconds_count{stage="rerank"} 3' in lines
    assert 't_seconds_sum{stage="rerank"} 5.55' in lines


def test_a_failing_gauge_is_left_out() -> None:
    ok = Gauge("t_docs", "Docs.", lambda: [({"status": "indexed"}, 3.0)])
    assert list(ok.render())[-1] == 't_docs{status="indexed"} 3'

    def down() -> list[tuple[dict[str, str], float]]:
        raise ConnectionError("database down")

    assert list(Gauge("t_down", "Down.", down).render()) == []
