---
name: FuelCell-RAG
description: A drawing sheet for answers. Claims carry item balloons that match a numbered parts list of sources, with revision state in redline.
colors:
  navy: "#14263f"
  navy-hover: "#1d3556"
  rail-ink: "#e3eaf3"
  rail-dim: "#9db0c6"
  desk: "#edf0ee"
  sheet: "#ffffff"
  sheet-alt: "#f6f8f9"
  ink: "#1a1d21"
  graphite: "#4a5560"
  faint: "#66717c"
  hair: "#cfd4d9"
  hair-strong: "#8d97a1"
  blue: "#1f4e8c"
  blue-hover: "#173d70"
  blue-tint: "#e5edf7"
  red: "#b42d1c"
  red-tint: "#fbebe8"
  green: "#1b724a"
  green-tint: "#e2f2ea"
typography:
  headline:
    fontFamily: "Barlow Semi Condensed, Barlow, system-ui, sans-serif"
    fontSize: "1.5rem"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "0.005em"
  title:
    fontFamily: "Barlow Semi Condensed, Barlow, system-ui, sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: 1.5
  body:
    fontFamily: "Barlow, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.97rem"
    fontWeight: 400
    lineHeight: 1.5
  body-small:
    fontFamily: "Barlow, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Barlow Semi Condensed, Barlow, system-ui, sans-serif"
    fontSize: "0.78rem"
    fontWeight: 500
    letterSpacing: "0.06em"
  data:
    fontFamily: "JetBrains Mono, ui-monospace, Cascadia Mono, Consolas, monospace"
    fontSize: "0.78rem"
    fontWeight: 400
rounded:
  sheet: "2px"
  control: "3px"
  balloon: "999px"
spacing:
  s1: "4px"
  s2: "8px"
  s3: "12px"
  s4: "16px"
  s5: "24px"
  s6: "32px"
  s7: "48px"
components:
  button-primary:
    backgroundColor: "{colors.navy}"
    textColor: "{colors.sheet}"
    rounded: "{rounded.control}"
    height: "36px"
    padding: "0 14px"
  button-primary-hover:
    backgroundColor: "{colors.navy-hover}"
  button-default:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "36px"
    padding: "0 14px"
  button-default-hover:
    backgroundColor: "{colors.sheet-alt}"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.blue}"
    rounded: "{rounded.control}"
    height: "36px"
  chip:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "30px"
    padding: "0 11px"
  chip-selected:
    backgroundColor: "{colors.blue-tint}"
    textColor: "{colors.blue}"
  input:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    height: "36px"
    padding: "0 10px"
  sheet:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sheet}"
    padding: "16px"
  balloon:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.blue}"
    rounded: "{rounded.balloon}"
    height: "1.5em"
  balloon-active:
    backgroundColor: "{colors.blue}"
    textColor: "{colors.sheet}"
  nav-item:
    textColor: "{colors.rail-ink}"
    height: "40px"
    padding: "0 12px"
  nav-item-current:
    backgroundColor: "{colors.desk}"
    textColor: "{colors.navy}"
---

# Design System: FuelCell-RAG

## Overview

**Creative North Star: "The Drawing Sheet"**

Every answer is treated as an engineering drawing sheet: a white sheet on a pale desk, ruled with hairlines, annotated rather than decorated. Claims in the prose carry item balloons, which are numbered circles, and each balloon points to a row in a parts-list register of sources. A title block under the answer records how it was made. Provenance is the visual subject; the interface exists to make a claim traceable from balloon to parts-list row to page preview.

Density is calm and technical. Surfaces are flat, bordered by 1px hairlines, and square-cornered (2-3px). A deep navy rail anchors the left edge like a drawing-office cabinet. Colour is reserved for state: blue means selection and citation, green means current, red means superseded or conflicting. Nothing else is coloured. State is never colour alone; it always pairs with a shape (circle, triangle, square) or a strike.

The system refuses the chat-over-documents default: no message bubbles, no avatars, no gradient send button. The question is a tinted rectangle; the answer is a sheet.

**Key Characteristics:**
- White sheets on a pale grey-green desk, separated by hairlines rather than shadows.
- Navy rail with the current page "cut out" in desk colour so it reads as continuous with the page.
- Item balloons as the single signature mark, matched one-to-one to parts-list rows.
- Revision triangles and redline strike-through carry version state.
- Three faces: Barlow for reading, Barlow Semi Condensed for drawing-style labels and headings, JetBrains Mono for IDs, scores and values.
- Tabular numerals everywhere (set on body).

## Colors

A cold, restrained drafting palette: navy structure, neutral grey-white paper, and exactly three state hues.

### Primary
- **Drafting Navy** (`navy`, #14263f): the rail, primary buttons, the skip link. Hover lifts to `navy-hover`.
- **Citation Blue** (`blue`, #1f4e8c): balloons, links, focus rings, selected chips and rows, the live-answer sweep, evaluation bar fills. It means "selected or cited". `blue-tint` is the selected/question background; `blue-hover` is reserved for pressed link states.

### Secondary
- **Current Green** (`green`, #1b724a): current revision, ok marks, saved confirmation, positive delta. `green-tint` is defined for status fills.
- **Redline Red** (`red`, #b42d1c): superseded revisions, conflicts, failures, low scores, disagreement and the strike through superseded titles. `red-tint` fills error notices (text on it is a darker #7d1f13).

### Neutral
- **Pale Desk** (`desk`, #edf0ee): page background, and the current nav item.
- **Sheet White** (`sheet`, #ffffff) and **Sheet Alt** (`sheet-alt`, #f6f8f9): sheets and inset or header surfaces (table heads, code, expanded rows).
- **Ink** (`ink`, #1a1d21), **Graphite** (`graphite`, #4a5560), **Faint** (`faint`, #66717c): primary, secondary and tertiary text. Faint is the floor for any text on white.
- **Hairline** (`hair`, #cfd4d9) and **Strong Hairline** (`hair-strong`, #8d97a1): dividers and control borders respectively.
- **Rail Ink / Rail Dim** (`rail-ink`, `rail-dim`): text on navy.

### Named Rules
**The State-Only Colour Rule.** Blue, green and red appear only to encode selection, currency, or conflict. Decoration, emphasis and branding stay in navy and neutrals.

**The Shape-Plus-Colour Rule.** Every coloured state also changes shape: ok is a filled circle, superseded or failed is a triangle, warning is a small square, unknown is a hollow ring.

## Typography

**Display Font:** Barlow Semi Condensed (with Barlow, system-ui)
**Body Font:** Barlow (with system-ui, Segoe UI, sans-serif)
**Label/Mono Font:** JetBrains Mono (with ui-monospace, Cascadia Mono, Consolas)

**Character:** Barlow's highway-signage and drafting-label DNA, condensed for headings and field labels, set against a monospace for anything that is an identifier or measurement. Fonts are self-hosted woff2 (Barlow 400/400i/500/600, Semi Condensed 500/600, JetBrains Mono 400/500).

### Hierarchy
- **Headline** (600, 1.5rem, 1.1): page title in the top bar and the empty-state heading.
- **Title** (600, 1.125rem): sheet headers, dialog and error-state headings.
- **Body** (400, 0.97rem, 1.5): answers and general reading. Answer prose is capped at 74ch.
- **Body small** (400, 0.875rem): table cells, notes, metadata, controls.
- **Label** (500, 0.78rem, 0.06em tracking, uppercase, Semi Condensed): title-block cell captions and table column heads only.
- **Data** (JetBrains Mono, 0.74-0.86rem): document IDs, scores, values with units. Figures in summary cells use Semi Condensed 600 at 1.35rem.

### Named Rules
**The Mono-For-Identifiers Rule.** Anything a person might copy or compare (document ID, score, parameter value) is monospace; prose never is.

**The Caption-Not-Eyebrow Rule.** Uppercase condensed labels are cell captions inside a title block or table head, attached to the value they describe. They are never set above a heading as an introduction.

## Layout

A two-column shell: a fixed 232px navy rail (sticky, full height) and a fluid main column. The top bar is 76px (64px on mobile) with a hairline bottom rule; content padding is 24px vertical and 32px horizontal (16px on mobile), with 48px at the bottom. Spacing is a 4px base scale: 4, 8, 12, 16, 24, 32, 48.

The chat view is a two-column sheet layout: the thread (fluid) beside a 392px sticky source register. The composer is pinned to the bottom of the thread even on short threads. Other screens use full-width sheets, a 320px picker beside a fluid pane (`split`), and stacks with 16px gaps. Title-block cells sit in a hairline-divided row (`cells`), or an auto-fit wrap with 150px minimum.

Breakpoints: at 1180px the chat and split layouts collapse to a single column and the register becomes static; the empty register hides. At 860px the rail becomes a horizontal top strip with icon-only navigation, the composer anchors to the viewport bottom edge to edge, title-block cells stack, and summary figures go two-up. Wide tables scroll horizontally inside a wrapper (880px minimum) rather than overflowing the page; long lists are height-capped (320px) with sticky heads.

## Elevation & Depth

Flat by default. Depth comes from the white-on-desk tonal step plus 1px hairline borders. A single faint sheet shadow lifts sheets: `0 1px 0 rgb(20 38 63 / 0.05), 0 8px 18px -12px rgb(20 38 63 / 0.35)`; it is soft and tinted navy, not an offset block. Dialogs use `0 6px 14px -6px rgb(20 38 63 / 0.4)` over a navy 45% backdrop. Controls carry no shadow at all.

### Named Rules
**The Hairline-First Rule.** Separate regions with a 1px rule before reaching for a shadow; shadow is reserved for sheets and dialogs.

## Shapes

Square and ruled. Sheets are 2px radius, controls 3px, and nothing is a pill except the item balloon, which is a circle by definition (999px) because that is what a drawing balloon is. Status marks are 9px circles, 11px triangles or 1px-radius squares. The rail's current item is rounded only on its left side (3px) so it fuses with the page. Borders are 1px hairline; the balloon outline is 1.25px blue.

## Components

### Buttons
- **Shape:** 3px radius, 36px tall (30px small, 36px square icon), 14px horizontal padding, weight 500.
- **Primary:** Navy fill, white text, weight 600. One per context (send, run).
- **Default:** White fill, strong-hairline border, ink text; hover steps to Sheet Alt with a graphite border.
- **Quiet:** transparent, blue text; hover fills blue-tint. Toggle state (`aria-pressed`) is blue-tint fill, blue border and text.
- **Focus / disabled:** 2px blue outline at 2px offset (white on navy surfaces); disabled drops to 50% opacity. Transitions are 120ms ease-out.

### Chips
- 30px, 3px radius, white with strong-hairline border. Selected: blue-tint fill, blue border and text, weight 600. Used as filters and scope choices.

### Inputs / Fields
- 36px minimum, white, 1px strong-hairline border, 3px radius, 10px inline padding; hover darkens the border to graphite; focus is the global blue outline. The composer textarea has a transparent border inside its own sheet (44px minimum, 180px max).

### Sheets and Title Block
- White, 1px hairline border, 2px radius, the sheet shadow. A sheet head (12px 16px) carries a Title-size heading with a graphite note, ruled beneath. The title block is a row of `cells` under the answer: Label-style caption over a small-size value (monospace for IDs), cells divided by vertical hairlines.

### Navigation
- Navy rail, 40px items, icons as 1.6px-stroke line SVGs, label weight 500. Hover `navy-hover`; current item is Pale Desk with navy text, weight 600. The foot holds a health mark (circle ok, triangle down) and a quiet outlined button. On mobile the rail turns into a horizontal strip and labels hide.

### Item Balloon (signature)
- A 1.5em circle with a 1.25px blue outline, white fill, blue Semi Condensed 600 numerals, inline in prose. Hover or active fills solid blue with white text. Ranges (`group`) widen to a pill-shaped padding. A `ghost` balloon is dashed grey for an unresolved reference; `static` is non-interactive.

### Parts-List Register (signature)
- A sticky sheet of numbered rows (30px index column, title, side column with revision and score). A selected row is blue-tint, and rows referenced together get a 7% blue wash. Each row expands to show the excerpt in a bordered `pre` (max 260px) and a page preview image with a strong-hairline border. Rows enter with a top-down clip reveal staggered 45ms.

### Revision Marks
- Current: green triangle glyph plus revision text. Superseded: red, and the part title is struck through in a 1.5px red line over graphite text (the redline). Status dots in tables follow the shape rules.

### Tables
- 0.875rem, sticky Sheet Alt head with Label-style captions, 9px 12px cell padding, hairline row rules, subtle hover wash, sortable heads as buttons, numeric columns right-aligned. Expandable rows show a chevron drawn in CSS borders.

### Evaluation Bars
- A 12px track with quartile tick hairlines, a blue fill, and a red fill for low values; value to the right in graphite.

### Notices and Dialogs
- Notices are hairline-topped strips: `bad` on red-tint with dark red text, `info` on Sheet Alt. Dialogs are 420px max, 2px radius, 24px padding. The live-answer state is a 2px blue sweep along the top edge of the sheet.

## Do's and Don'ts

### Do:
- **Do** answer in a sheet: prose with inline balloons, a register of sources, then a title block of cells.
- **Do** match every balloon to a parts-list row, and show superseded versions with the red strike and a red triangle.
- **Do** pair every state colour with a shape or strike (blue selection, green current, red conflict).
- **Do** use hairlines (1px `hair` or `hair-strong`) to divide regions; keep radii at 2px (sheets) and 3px (controls).
- **Do** set IDs, scores and values in JetBrains Mono, and let long IDs wrap rather than overflow.
- **Do** keep table overflow inside a scroll wrapper and keep the composer pinned to the thread bottom.
- **Do** honour reduced motion; animations are limited to the live sweep, the row reveal and 120ms state transitions.

### Don't:
- **Don't** use chat bubbles, avatars, or a gradient or glowing send button.
- **Don't** introduce another accent hue; blue, green and red already cover selection, currency and conflict.
- **Don't** use colour alone to signal state.
- **Don't** round surfaces beyond 3px; the balloon is the only circle in the layout.
- **Don't** put uppercase condensed labels above headings as introductions; they are captions inside title-block cells and table heads.
- **Don't** use shadows to separate adjacent regions; use a hairline.

## Not Canonized

The optional title-block strip on every screen head was deliberately not built, so the title block belongs to answers (and comparable record sheets) only. Raw hexes outside the token set remain in the stylesheet (selection #c9dcf3, question border #c4d5ea, scrollbar greys, rail-foot health greens #5fc38f and #ff8a78, rail button border #3c5273, error text #7d1f13, row hover #f7f9fa, skeleton #e8ecef); they are one-off values, not part of the system.
