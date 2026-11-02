# Demo video script (about 3 minutes)

Every question below was answered correctly in the evaluation run
`2026-11-01-2214-answer-v5-corpus196` (value and citations checked against the generator's
truth). Answers are written by an LLM, so wording differs slightly on each take.

## Before recording (15 min)

1. Close games and anything using the GPU. Check with `nvidia-smi`: under 2 GB used.
2. Use the GPU API, not the Docker one (the Docker image runs on CPU):
   ```bash
   docker compose stop api
   uv run fcrag serve                              # API on :8000 with the GPU
   ```
   The UI container on :8501 talks to :8000, so it works unchanged. Otherwise run
   `uv run streamlit run src/fcrag/ui/chat.py`.
3. Confirm the `.env` has a working `GROQ_API_KEY`. Do not show `.env` on screen.
4. **Warm up**: ask one throwaway question first. The first request loads the models and takes
   30 s or more.
5. **Rehearse every question once.** Answers are cached for 24 h, so the recorded take replays
   instantly and is marked "cached". If you prefer to show live generation, start the API with
   `FCRAG_RESPONSE_CACHE_TTL_S=0`. Groq's free tier allows 8,000 tokens per minute, so leave
   10 s between questions; two long answers in a row can stall for 20 s or more.
6. Screen: browser at 125 % zoom, window 1920×1080, notifications off.

## Script

**0:00 Opening (15 s).** Chat page.
> "FuelCell-RAG answers engineering questions over fuel cell datasheets, requirements, CAD
> assemblies and public reports, in German and English, and every claim cites its source."

**0:15 Parameter lookup with a citation (30 s).**
Ask: *What is the maximum air mass flow of the System A air compressor?*
Expected: **100 g/s**. Click a citation to open the source and show the page or table cell.
> "Answers cite a page, table cell, requirement ID or CAD part. This one comes from the
> parameter sheet."

**0:45 German question, versions (30 s).**
Ask: *Welche Auslegungslebensdauer gilt aktuell für System B?*
Expected: **25 000 h**, with the source labelled latest or superseded.
> "The documents contain several versions. The answer uses the current one and the source panel
> labels which is latest and which is superseded."

**1:15 Requirements and CAD (30 s).**
Ask: *Which requirements refine REQ-A-0001?* then *How many tie rods hold the System C stack
together?*
Expected: REQ-A-0013 and REQ-A-0012; four tie rods (part TR-01).
> "Requirement links and the STEP assembly tree are searchable too."

**1:45 It says when it does not know (20 s).**
Ask: *What is the warranty period of System A?* (or *Which supplier manufactures the air
compressor of System B?*)
Expected: a refusal ("I could not find this in the documents", or the sources give a design
lifetime but no warranty).
> "A calibrated relevance threshold stops it from guessing. It refuses 6 of 7 unanswerable
> questions at the retrieval stage and 7 of 7 after the answer step."

**2:05 Comparison and the requirement checker (25 s).** Open "Parameter comparison": all three
systems are selected by default; add or keep "rated net power" under Parameters (expected 80, 300
and 100 kW for A, B and C). Then open "Requirement checker": the box is pre-filled with *The fuel
cell stack shall not exceed a maximum coolant outlet temperature of 90 °C.* with System B
selected. Click **Check** and show the result (conflict, consistent or unknown, with the
document value it was compared to). I did not run these two pages while writing this script:
try both once before recording and cut the step if the result is unclear.

**2:30 Evaluation (25 s).** Open the evaluation page. Show the run, recall per category, and the
failing questions with reasons.
> "A 70-question golden set with exact gold sources, 25 in German. Recall@5 0.94, 93 % value
> accuracy, 96 % citation precision, faithfulness 0.92 by an independent judge. The failures
> are listed here, not hidden."

**2:55 Close (10 s).**
> "Code, evaluation and CI gate are on GitHub: Aymenrahmanii/FuelCell-RAG."

## If something goes wrong

- A question times out: wait 60 s for Groq's per-minute window, cut and retake.
- An answer is wrong or worded differently from the expected one: do not edit it, rerun. The
  evaluation shows these answers were correct, but the wording is not fixed.
- Do not use these questions, they are known failures: *Wie ... Wirkungsgrade ... foliengelagerten
  Verdichter-Expanders* (text-11, German question about an English slide deck), and the
  three-system comparison cross-sys-06.

## Numbers you can say (all measured, 196-document corpus unless noted)

| Claim | Value |
|---|---|
| Retrieval recall@5 / MRR | 0.921 / 0.877 (0.937 / 0.882 at 254 documents with the new defaults) |
| Value accuracy | 92.7 % |
| Citation precision | 95.6 %, 0 invalid citations |
| Correct "not in the documents" | 7 of 7, 1 false refusal of 63 |
| Faithfulness (LLM judge) | 0.918 |
| Prompt-injection resistance | 3 of 3, also with the note forced in as source 1 |
| Retrieval under 10 users | p95 4.9 s on the laptop GPU |
