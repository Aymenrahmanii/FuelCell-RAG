"""Load test: concurrent users asking golden-set questions against a running API.

    uvx locust -f tests/load/locustfile.py --host http://localhost:8000 \\
        --users 10 --spawn-rate 2 --run-time 5m --headless --csv eval/runs/load

``/search`` measures retrieval alone (no LLM, no cost). With LOAD_ANSWERS=1, ``/ask/stream`` adds
two timings of its own: "time to first token" and "full answer" (until the ``done`` event). The
request row Locust records for ``/ask/stream`` itself only covers the response headers, which a
streamed answer sends at once, so it is not the answer time. Answers replayed from the response
cache are reported as "full answer (cached)"; start the API with FCRAG_RESPONSE_CACHE_TTL_S=0 to
measure every answer computed. Set FCRAG_API_KEY if the API requires a key.
"""

import json
import os
import random
import time
from pathlib import Path

from locust import HttpUser, between, events, task

GOLDEN = Path(__file__).resolve().parents[2] / "eval" / "golden_set.jsonl"
QUESTIONS = [json.loads(line)["question"] for line in GOLDEN.open(encoding="utf-8") if line.strip()]
HEADERS = {"X-API-Key": os.environ["FCRAG_API_KEY"]} if os.environ.get("FCRAG_API_KEY") else {}
ANSWERS = os.environ.get("LOAD_ANSWERS", "0") == "1"
"""Set LOAD_ANSWERS=1 to include LLM answers (costs tokens)."""


class Engineer(HttpUser):
    wait_time = between(2, 6)

    @task(3)
    def search(self) -> None:
        self.client.post(
            "/search", json={"question": random.choice(QUESTIONS)}, headers=HEADERS, name="/search"
        )

    @task(1)
    def ask(self) -> None:
        if not ANSWERS:
            return
        start = time.perf_counter()
        first_token = None
        cached, failed = False, False
        with self.client.post(
            "/ask/stream",
            json={"question": random.choice(QUESTIONS)},
            headers=HEADERS,
            stream=True,
            name="/ask/stream",
            catch_response=True,
        ) as response:
            for line in response.iter_lines():
                is_token = line.startswith(b"data: ") and b'"type": "token"' in line
                if is_token and first_token is None:
                    first_token = (time.perf_counter() - start) * 1000
                if b'"type": "done"' in line:
                    cached = b'"cached": true' in line
                if b'"type": "error"' in line:
                    failed = True
                    response.failure(line.decode(errors="replace"))
        total = (time.perf_counter() - start) * 1000
        if failed:
            return
        if first_token is not None and not cached:
            _record("time to first token", first_token)
        _record("full answer (cached)" if cached else "full answer", total)


def _record(name: str, ms: float) -> None:
    events.request.fire(
        request_type="SSE", name=name, response_time=ms, response_length=0, exception=None,
        context={},
    )  # fmt: skip
