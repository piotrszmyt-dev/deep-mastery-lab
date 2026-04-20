# Styling Map — Styling_Template.css

---

## Palette

> **Architectural rule:** Tier 2 contains only `var(--tier1-token)` semantic mappings (e.g. `--btn-pri-bg: var(--color-accent)`). Any variable with a concrete value (`0px`, a gradient, a raw color) lives in Tier 1. If a component's variables don't map to a shared palette role — like progress bar shape and pattern — they belong in Tier 1 directly, with no Tier 2 layer.

### Tier 1 — Primitives `:root`
*Only these values change per theme. Populated below with **E-INKed** as the reference.*

```css
:root {

  /* ── ACCENT ─────────────────────────────────────────────────
     The single "personality" color of the theme.
     accent-text: the color of text placed ON top of accent bg.  */
  --color-accent:       #5C8A8A;
  --color-accent-light: #6FA0A0;   /* hover */
  --color-accent-dark:  #4A7070;   /* pressed / active */
  --color-accent-text:  #1A1A1A;   /* text ON accent backgrounds */

  /* ── NEUTRAL SURFACE SCALE ───────────────────────────────────
     Dark themes: 0 = darkest (bg), 900 = lightest (strong text).
     Light themes: invert — 0 = white, 900 = near-black.         */
  --color-neutral-0:   #121212;    /* page background */
  --color-neutral-50:  #1A1A1A;    /* surface: cards, panels, sidebar */
  --color-neutral-100: #1A1A1A;    /* inset: text field normal bg */
  --color-neutral-200: #2A2A2A;    /* raised: hover surfaces */
  --color-neutral-300: #404040;    /* borders, dividers, scrollbars */
  --color-neutral-400: #696969;    /* disabled text and icons */
  --color-neutral-500: #B0B0B0;    /* muted / secondary text */
  --color-neutral-700: #E0E0E0;    /* standard readable text */
  --color-neutral-900: #E0E0E0;    /* strongest text (same in E-INKed) */

  /* ── ERROR ───────────────────────────────────────────────────
     Single-use: answer-wrong card border.                       */
  --color-error:        #8C5656;

  /* ── TYPOGRAPHY ──────────────────────────────────────────────*/
  --font-sans: sans-serif;
  --font-mono: 'Courier New', monospace;

  /* ── RADII ───────────────────────────────────────────────────
     Shape personality. Boxy themes: sm=md=4px. Rounded: 8–16px. */
  --radius-sm:   4px;
  --radius-md:   4px;
  --radius-lg:   5px;
  --radius-xl:   8px;
  --radius-pill: 9999px;

  /* ── SHADOWS ─────────────────────────────────────────────────
     Depth personality.
     E-INKed: crisp flat offset (2px 2px, no blur).
     Soft themes: diffuse (0 4px 12px rgba(...)).
     Glow themes: colored spread (0 0 12px rgba(accent, 0.4)).    */
  --shadow-sm:    1px 1px 0px rgba(0,0,0,0.15);
  --shadow-md:    2px 2px 0px rgba(0,0,0,0.15);
  --shadow-lg:    0 10px 25px rgba(0,0,0,0.15);
  --shadow-xl:    0 20px 50px rgba(0,0,0,0.15);
  --shadow-focus: 0 0 0 2px var(--color-neutral-0), 0 0 0 4px var(--color-neutral-300);
  --shadow-glow:  none;   /* override with accent glow for neon/bioluminescent themes */

  /* ── BUTTON GRADIENT ─────────────────────────────────────────
     Controls shading on primary button face.
     Flat: set both to var(--color-accent).
     Shaded: start = lighter, end = darker (top-to-bottom depth).  */
  --btn-gradient-start: var(--color-accent);
  --btn-gradient-end:   var(--color-accent);

  /* ── TEXTURE ─────────────────────────────────────────────────
     Optional surface pattern for cards / generator window.
     Set to an SVG data: URL for paper/noise; none = clean flat.  */
  --texture-surface: none;

}
```

### Semantic Role Map
*Which Tier 1 token covers each UI role — for quick reasoning when building themes.*

| Role | Token | Used by |
|---|---|---|
| Page background | `--color-neutral-0` | main area, tab active, text field bg, console |
| Cards / panels / sidebar | `--color-neutral-50` | lesson card, welcome card, generator, popovers, dropdowns, answer cards |
| Hover surfaces | `--color-neutral-200` | tab hover bg, expander hover |
| All borders & dividers | `--color-neutral-300` | every border, separator, scrollbar thumb |
| Disabled text / icons | `--color-neutral-400` | disabled states, inactive sidebar items |
| Muted / secondary text | `--color-neutral-500` | body text, labels, sidebar normal, icons |
| Standard text | `--color-neutral-700` | primary readable text, hover text, metric values |
| Text on accent | `--color-accent-text` | button text, key-hint text, selected item text, correct-answer card |
| Primary action | `--color-accent` | primary button, progress fill, focus borders, active lesson, answer letter, key-hint bg, tab ring, all accent icons |
| Accent pressed | `--color-accent-dark` | primary button `:active`, dropdown selected `:hover` |
| Error border | `--color-error` | answer-card user-wrong only |

---

## Element Map

### 1. BUTTON — PRIMARY
- default: `bg, border, text, shadow, radius`
- hover: `bg, border-color, shadow`
- active: `bg, border-color, shadow`
- focus: `bg, focus-ring (inner + outer)`
- disabled: `bg, border, text`

### 2. BUTTON — SECONDARY
- default: `bg(transparent), border, text, shadow, radius`
- hover: `bg, border-color, shadow`
- active: `bg, border-color, shadow`
- focus: `bg, focus-ring`
- disabled: `bg, border, text`

### 3. PROGRESS BAR
- track: `bg, height, radius`
- fill: `bg (accent), shadow`

### 4. WELCOME CARD
- container: `bg, border, shadow, radius`
- title: `color, font`
- title icon: `color`
- subtitle: `color, opacity`
- divider: `border-color`

### 5. SIDEBAR
- container: `bg, text`
- collapse btn: `color (default / hover), bg-hover`
- title: `color, size, weight, shadow`
- title icon: `color, shadow`
- separator: `bg-color`
- expander closed: `bg, text`
- expander hover: `bg, text`
- expander open: `bg, text, radius, shadow`
- subconcept header: `color (disabled/label style)`
- subconcept normal: `color, bg`
- subconcept hover: `color`
- active item: `bg, text (normal)`
- active item hover: `bg, text`

### 6. MAIN AREA
- background: `bg, text`
- expand sidebar btn: `color (default / hover)`

### 7. LESSON CARD
- lesson title: `color, font, weight`
- card window: `bg, border, radius, shadow, texture`
- strong text: `color, weight`
- headers: `color, font, letter-spacing, weight`
- italic text: `color`
- table header: `color, border, bg`
- table data: `color, border`
- scrollbar: `thumb-color`

### 8. QUIZ / TEST
- question text: `color, opacity`
- answer card: `bg, border(transparent), radius`
- answer card hover: `border-color`
- answer letter (A B C D): `color (accent)`
- key-hint badge: `bg, color, border, radius, shadow`
- keyboard legend: `color, font`

### 9. FEEDBACK
- metric box: `bg, border, radius, shadow`
- metric box hover: `border-color`
- metric box passed: `border-color, shadow, color (accent)`
- metric box failed: `border-color (muted)`
- metric icon: `size, opacity`
- metric label: `color, size, uppercase, letter-spacing`
- metric value: `color, size, weight`
- expander normal: `border-bottom`
- expander hover: `bg, color, padding`
- expander open: `bg, color (accent)`
- answer-card base: `radius, font-size, border(transparent)`
- answer user-wrong: `bg, border (dotted + error color), text`
- answer user-correct: `bg, border (accent), text`
- answer correct-key: `bg (accent solid), border, text (inverted)`
- answer label: `opacity, size, uppercase`
- explanation box: `bg, border-left, radius, text, line-height`

### 10. GENERATOR WINDOW
- card container: `bg, border, border-top (accent), shadow, radius`
- card header: `color, font`
- card divider: `border-color`
- header icon: `color (accent)`
- input icon: `color (muted)`
- warning box: `color, striped-border (bg trick)`
- stat box: `bg, border, radius`
- stat-item border: `border-left`
- stat label: `color, size, uppercase`
- stat value: `color, weight, size`
- stat value accent: `color (accent)`
- spinner icon: `color`
- console: `bg (deeper), border, radius, font (mono)`
- console step: `border-bottom (dotted)`
- console icon: `color (accent)`
- console title: `color, weight`
- console message: `color, size, border-left`
- completion header: `color`
- completion icon: `color (accent), size`

### 11. STREAMLIT METRIC WIDGET
- container: `bg, border, radius, shadow`
- hover: `border-color (accent), shadow`
- label: `color, size, uppercase, letter-spacing`
- value: `color, size, weight`
- delta: `bg, color, radius`

### 12. UI ELEMENTS

#### Tabs
- inactive: `bg, color, radius`
- inactive hover: `bg`
- active: `bg (inset/deeper), color, shadow (accent ring)`
- border line: `hidden`

#### File Dropzone
- container: `bg, border (dotted), radius`
- text: `color`
- button: `bg, color, border, radius`
- icon: `color`

#### Popover
- container: `bg, shadow, border, radius`
- text: `color`

#### Dropdown Menu
- closed: `bg (inset), border, radius, text`
- open: `bg, border (accent), text (accent)`
- hover: `bg, border (text-color), text`
- item normal: `color`
- item selected: `bg (accent), text (inverted)`
- item selected hover: `bg (accent-dark)`
- scrollbar: `thumb-color`

#### Text Fields
- normal: `bg (inset), border, text, radius`
- hover: `bg, border (text-color)`
- focus: `bg, border (accent)`
- scrollbar: `thumb-color`
- number step btns: `bg, disabled-icon-color`
- tooltip icon: `stroke-color`
- field labels: `color, size, opacity`

### 13. MASTERY / SRS TREE
- module header: `color (accent), size, weight`
- concept group: `color (primary text), size, weight`
- lesson row: `color (muted text), weight`
- disabled items: `color (border-gray), opacity`

# Root Design: 

### Pallete:

Main sections
- Main Background 

- "sidebar_background", "sidebar_


