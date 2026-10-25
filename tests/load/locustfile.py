"""Load test: concurrent users asking golden-set questions against a running API.

    uvx locust -f tests/load/locustfile.py --host http://localhost:8000 \\
        --users 10 --spawn-rate 2 --run-time 5m --headless --csv eval/runs/load

``/search`` measures retrieval alone (no LLM, no cost); ``/ask/stream`` measures the full answer,
including time to the first streamed token. Set FCRAG_API_KEY if the API requires a key.
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
                if b'"type": "error"' in line:
                    response.failure(line.decode(errors="replace"))
            if first_token is not None:
                events.request.fire(
                    request_type="SSE", name="time to first token", response_time=first_token,
                    response_length=0, exception=None, context={},
                )  # fmt: skip
