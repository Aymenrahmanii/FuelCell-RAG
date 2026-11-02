---
version: 1
slug: "src-fcrag-web-index-html"
primary_target: "src/fcrag/web/index.html"
related_targets: []
---

# Surface brief: FuelCell-RAG web app (src/fcrag/web)

Scope and mode: Operate. A five-screen web app (chat, documents, parameter comparison, requirement checker, evaluation) served as static files by the FastAPI app at /app. Replaces the Streamlit UI once all five screens are covered.

Audience, job, constraints: engineers who need a traceable answer fast, and a hiring team who must see a real, measured system within a minute. No build step, no new Python packages, vanilla JS modules, self-hosted fonts. Works with and without the X-API-Key header. German and English content. Real API data only; no mocked numbers.

Chosen direction: Drawing Sheet (pick card). The world lends type (DIN-style technical grotesque), palette (drafting navy rail, pale desk, white sheets, hairlines, drafting blue, redline red, approved green), density, and one signature move: drawing-sheet item balloons. Citations render as numbered balloons that match the numbered parts-list rows of the source register, and the title block records the answer's metadata. It never supplies the layout or the controls: navigation is a rail, controls are standard buttons, tabs, inputs, selects and sortable tables.

Memorable moment: a cited answer where every [S1] balloon lights its row in the parts list and a superseded source is struck in redline.

Unresolved: dark theme (not built); mobile layout is read-only friendly rather than a full redesign.

## Direction contract

THESIS: The app is a drawing sheet for answers: claims carry item balloons, sources form a numbered parts list with revision state, and a title block records how the answer was made. It refuses the chat-over-documents default of bubbles, avatars and a gradient send button.

OWN-WORLD: Deep drafting-navy rail (#14263F), pale grey-green desk (#EDF0EE), white sheets with 1px hairlines (#C9CED3), ink #1A1D21, graphite #5E6872, drafting blue #1F4E8C for selection and links, redline #C4301F for superseded and conflicts, approved green #1D7A4E for current and consistent. Barlow for text, Barlow Semi Condensed for labels, JetBrains Mono for IDs and values. Circular item balloons, triangle revision marks, title blocks with ruled cells. Recognisable with all content removed by the balloons, the ruled title block and the navy rail.

STORY: A visitor understands that every claim is traceable (balloon to parts-list row to page preview), believes it because failures and superseded versions are shown in redline, and acts by asking, opening a source, or checking the evaluation page.

FIRST VIEWPORT: Navy rail left (240px) with the product name and five screens. Main sheet: a running head naming the scope (systems, document types, latest only) above the thread. Empty state shows three verified example questions and the corpus size. Composer fixed at the bottom of the sheet. After an answer, the source register opens at the right (about 380px) as a parts list with balloon numbers, revision triangles and scores; the title block sits under the answer with model, timings, prompt version and cache state.

FORM: Drawing Sheet, the IMPECCABLE'S PICK candidate from the roll (seed 63b4ff03, kind pick), built on the assigned index 6 list.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
