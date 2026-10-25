# ADR 0002: Qdrant with bge-m3 dense + sparse vectors, fused by RRF, then a cross-encoder

- Status: accepted
- Date: 2026-10-25

## Context

Engineering questions mix semantic phrasing ("how hot may the coolant get") with exact tokens
that dense embeddings blur: part numbers (EP-02), requirement IDs (REQ-A-0019), parameter
names, German compounds (Kühlmittelaustrittstemperatur). The corpus is German and English.

## Decision

- **Vector store: Qdrant.** Named dense and sparse vectors in one collection, payload indexes
  for filters (system, document type, version, access groups), int8 scalar quantisation,
  server-side fusion through the Query API. It is also the store named in the job posting.
- **Embeddings: BAAI/bge-m3.** One forward pass gives a 1024-d dense vector and sparse lexical
  weights, multilingual, 8k context. Hybrid search needs no second model.
- **Fusion: reciprocal rank fusion** of the dense top 50 and sparse top 50.
- **Reranker: bge-reranker-v2-m3** (multilingual cross-encoder) keeps the best 8. Its score is
  also the "not found" signal: below a calibrated threshold the system refuses instead of
  guessing.

## Consequences

- Baseline on the 60-question golden set: recall@5 0.95+, MRR about 0.89 (see README).
- Rerank scores are calibrated per model; changing the reranker means recalibrating
  `rerank_threshold` (`fcrag eval` records each question's top score for this).
- A near-synonym can defeat the threshold: "warranty period" scores 0.64 against "design
  lifetime". Retrieval cannot catch this; the prompt tells the model to say what the
  documents do and do not state.
