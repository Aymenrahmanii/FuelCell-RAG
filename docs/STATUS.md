# Project status (2026-11-01)

Where FuelCell-RAG stands against its 12-week plan ("FuelCell-RAG: Production-Level Project
Plan"), and what is left. Numbers come from the answer-v5 run
`2026-11-01-2214-answer-v5-corpus196` (196 documents) unless noted; the README has the full results table.

## v1.0 success criteria

| Target | Plan | Now | Status |
|---|---|---|---|
| Retrieval recall@5 | ≥ 0.85 | 0.921 (MRR 0.877), unchanged from 83 to 196 documents | met |
| Parameter lookup accuracy | ≥ 85 % | 92.7 % value accuracy | met |
| Citation correctness | ≥ 90 % | 95.6 % precision, 0 invalid | met |
| Correct "not in the documents" | ≥ 90 % | 7 of 7, 1 false refusal of 63 | met |
| Answer faithfulness | ≥ 0.90 | 0.918 judge (77 claims); earlier run: 0.932 blind second-opinion labels / 0.890 judge | met; labels not repeated for this run |
| Prompt-injection resistance | planted attacks | 3 of 3, also with the note forced in as source 1 | met |
| p95 end-to-end latency, 10 users | < 6 s | retrieval 2.7 s p95 (single user); answers 4.8 s p95 earlier | **open**: load test ready, not yet run |
| Corpus | ≥ 300 docs, 5 types | 196 (146 public + 50 generated), all 5 types | **open**: 104 short; OSTI unreachable from this network, DOE records added as a source |
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
2. **Corpus to 300+** (196 now): `discover_corpus.py` found 85 arXiv papers and 34 DOE Hydrogen
   Program records (5 were duplicates of existing ones and were dropped); OSTI and arXiv beyond
   page 1 time out on the developer's network (WinError 10060). Run discovery from another
   network, or add sources (DOE annual progress reports, Annual Merit Review proceedings), then
   `download_corpus.py --manifest data/sources.discovered.yaml`, `fcrag ingest`, commit the
   manifest and lock file, and re-run the eval. Beware: chunk ids come from file content, so two
   manifest entries with the same file overwrite each other in the index.
3. **Cross-lingual retrieval**: implemented behind `FCRAG_CROSS_LINGUAL` (off). Fixes text-11 in
   retrieval (rank 10 to 1, recall@5 0.937) at a cost in MRR and p95; the answer eval with the
   flag on is not run. Decide whether to enable it by default.
4. **Remaining faithfulness errors** (7 of 75 claims): comparisons citing only one side,
   facts from uncited sources, "latest" backed only by superseded versions, part descriptions not
   in the cited STEP tree. Candidate prompt rules exist for each; re-measure after any change.
5. **Release**: push a test tag (`v0.1.0-rc1`) to exercise `release.yml` once.
6. **Developer deliverables**: demo video, write-up, CV line.

## Open known issues

- CI eval gate takes 30-50 min (runner speed varies); limit 90 min.
- One gate parameter question ranks 6-10 (recall@5 0.975 on the gate set; threshold 0.80).
- The Docker API image runs on CPU; use `uv run fcrag serve` locally for GPU latency figures.
