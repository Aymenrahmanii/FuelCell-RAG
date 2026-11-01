# Project status (2026-11-01)

Where FuelCell-RAG stands against its 12-week plan ("FuelCell-RAG: Production-Level Project
Plan"), and what is left. Numbers come from the answer-v5 run `2026-11-01-1322-answer-v5`
unless noted; the README has the full results table.

## v1.0 success criteria

| Target | Plan | Now | Status |
|---|---|---|---|
| Retrieval recall@5 | ≥ 0.85 | 0.921 (MRR 0.877) | met |
| Parameter lookup accuracy | ≥ 85 % | 95.1 % value accuracy | met |
| Citation correctness | ≥ 90 % | 94.0 % precision, 0 invalid | met |
| Correct "not in the documents" | ≥ 90 % | 7 of 7, 1 false refusal of 63 | met |
| Answer faithfulness | ≥ 0.90 | 0.932 blind second-opinion labels / 0.890 judge (96 % agreement) | met on the labels, judge is the lower bound |
| Prompt-injection resistance | planted attacks | 3 of 3, also with the note forced in as source 1 | met |
| p95 end-to-end latency, 10 users | < 6 s | retrieval 2.7 s p95 (single user); answers 4.8 s p95 earlier | **open**: load test ready, not yet run |
| Corpus | ≥ 300 docs, 5 types | 83 (33 public + 50 generated), all 5 types | **open**: discovery script ready, not yet run |
| Parser test coverage | ≥ 80 % | drawing 90, Excel 93, requirements 94, STEP 98 % | met (PDF needs Docling installed) |

## Built (all merged to main)

- Ingestion: Docling PDFs with OCR, Excel parameter sheets, ReqIF/DOCX/CSV requirements, STEP
  assemblies (CadQuery in a child process, text fallback), drawings read by layout; two-phase
  pipeline, parameter extraction into Postgres, Redis/RQ worker, document registry.
- Retrieval: bge-m3 dense + sparse in Qdrant (RRF), bge-reranker-v2-m3, calibrated not-found
  threshold, system scoping, structured parameter routing, requirement chunks for trace questions.
- Generation: LiteLLM (Groq gpt-oss-120b, Gemini fallback, local model in restricted mode),
  answer prompt answer-v5, follow-up rewriting from chat history, citation normalisation and
  checks, response cache (Redis, keyed by question, filters, prompt, model and registry).
- Apps: chat, documents, parameter comparison, requirement checker, evaluation dashboard
  (Streamlit); FastAPI with API key and group stub (`X-User-Groups`, `X-User-Id`).
- Operations: Langfuse traces, Prometheus metrics and a Grafana dashboard (`--profile
  monitoring`), audit log with retention (`fcrag audit-prune`), pip-audit in CI, images to GHCR
  and a release on `v*` tags.
- Evaluation: 70-question golden set (25 German, 9 categories) with exact gold sources, CI gate,
  LLM judge with blind second-opinion calibration, prompt-injection test (as retrieved and
  forced), parser golden-file snapshots (22 inputs), load test.

## Next steps

1. **Load test** (on the developer's machine, GPU): API with `FCRAG_RESPONSE_CACHE_TTL_S=0` on
   :8001, then Locust 10 users × 5 min, retrieval only and with `LOAD_ANSWERS=1`
   (`tests/load/locustfile.py` has the commands). Record p95 of `/search`, "time to first
   token" and "full answer" in the README latency row. Expect answers under load to be capped by
   Groq's free tier (8,000 tokens/min); report that, or measure with a paid tier or local model.
2. **Corpus to 300+**: `scripts/discover_corpus.py --target 230`, review
   `data/sources.discovered.yaml`, `download_corpus.py --manifest data/sources.discovered.yaml`,
   `fcrag ingest`, commit the manifest and its lock file. First run on 2026-11-01 timed out on
   some queries (WinError 10060), probably OSTI blocking that network; if so, add the DOE
   Hydrogen Program library (hydrogen.energy.gov, reachable) as a discovery source. Then re-run
   the full eval to check that retrieval holds with 4× the documents.
3. **Cross-lingual retrieval**: German questions about English documents still fail (text-11,
   refused). Planned experiment: translate the query and retrieve with both.
4. **Remaining faithfulness errors** (7 of 75 claims): comparisons citing only one side,
   facts from uncited sources, "latest" backed only by superseded versions, part descriptions not
   in the cited STEP tree. Candidate prompt rules exist for each; re-measure after any change.
5. **Release**: push a test tag (`v0.1.0-rc1`) to exercise `release.yml` once.
6. **Developer deliverables**: demo video, write-up, CV line.

## Open known issues

- CI eval gate takes 30-50 min (runner speed varies); limit 90 min.
- One gate parameter question ranks 6-10 (recall@5 0.975 on the gate set; threshold 0.80).
- The Docker API image runs on CPU; use `uv run fcrag serve` locally for GPU latency figures.
