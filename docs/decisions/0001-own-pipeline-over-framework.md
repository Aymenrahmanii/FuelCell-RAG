# ADR 0001: Build the RAG pipeline as own code, use libraries per component

- Status: accepted
- Date: 2026-10-25

## Context

LangChain and LlamaIndex offer complete RAG pipelines. They speed up a first demo, but they hide
the steps this project needs to measure and change one at a time: chunking, hybrid fusion,
reranking thresholds, citation validation. Each step also has to emit its own trace span and be
switchable by config for the ablation runs.

## Decision

Write the pipeline as small, typed Python functions of our own: one module per stage, a shared
`Element` / `Chunk` schema, and a `Parser` protocol for file types. Use libraries for single
components only: Docling for PDF layout, qdrant-client, bge-m3 and bge-reranker, LiteLLM for
provider access, Ragas for metrics.

## Consequences

- Every stage is unit-testable, traceable and swappable by config, which the evaluation harness
  needs.
- More code to maintain than a framework pipeline. It stays manageable because each stage is
  a thin wrapper around a library.
- No framework lock-in when swapping the hosted LLM for an on-premise model.
