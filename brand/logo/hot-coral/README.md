# Halcyon · Hot Coral treatments

Three colour treatments of the approved Halcyon mark (the kingfisher "y" with its beak, in a rounded
tile) and wordmark, moved from the Lime Anchor colours onto the Hot Coral palette. The shapes are the
Lime Anchor vectors in `../lime-anchor/`, read and recoloured by `build.py`; nothing is redrawn.
Exploration only: `brand/assets/`, `site/` and `extension/` still carry Lime Anchor until the captain
chooses a treatment and the palette is ported.

## Palette

| Role | Hex | Use (captain, 2026-11-06) |
| --- | --- | --- |
| Signature, Hot Coral | `#F0446E` | logo, standout links, primary action, breaking-news tag |
| Secondary, Plum | `#5B1738` | strong headers, important titles, hover |
| Tech accent, Cyan | `#20C7D9` | tech icons, charts, interactive points |
| Surface / Surface dark | `#F7F9FC` / `#111827` | grounds |
| Ink / Muted / Border | `#101828` / `#667085` / `#E4E7EC` | text, secondary text, lines |

Mix 60 % light surface, 25 % ink or dark, 10 % coral, 5 % cyan. No small white text directly on coral.

## Treatments

| | Tile | Bird | Beak | Wordmark on Surface | Wordmark on Surface dark | Sheet |
| --- | --- | --- | --- | --- | --- | --- |
| **Coral Tile** (recommended) | coral | surface | plum | coral letters, plum beak | coral letters, surface beak | `contact-sheet-coral-tile.png` |
| Plum Tile | plum | surface | coral | plum letters, coral beak | surface letters, coral beak | `contact-sheet-plum-tile.png` |
| Ink Tile | ink | coral | cyan | ink letters, coral beak | coral letters, cyan beak | `contact-sheet-ink-tile.png` |
| Lime Anchor (current) | `#174A34` | `#F8FBF3` | `#D7FF2F` | `#2F6B00` letters | `#F8FBF3` letters | `contact-sheet-lime-anchor.png` |

Each sheet shows the mark at 512, 48 and 16 px (plus the 16 px raster at 8x), the Chrome Web Store
icon at 128 px, the full logo at 480 px and the 16 px icon in a light and a dark Chrome toolbar, on
Surface and on Surface dark. Contrast ratios for every pairing are in `contrast-checks.json`
(WCAG 2 relative luminance, same form as the Lime Anchor file).

### Why Coral Tile

- The captain gave coral the role "logo". Coral Tile is the one treatment where the mark *is* coral:
  a coral square reads as Halcyon in a browser tab, a light or dark toolbar and a home screen alike.
  Plum Tile sinks into dark grounds (1.37 : 1) and Ink Tile disappears on Surface dark (1.00 : 1),
  leaving only the bird.
- At 16 px the light bird on the coral field is the most legible of the three (see the 8x panels):
  a light figure on a saturated ground survives anti-aliasing better than a coral figure on ink.
- Mark and wordmark share one coral, so the identity holds with or without the tile.

What it sacrifices:

- Bird / tile contrast drops from 9.72 : 1 (Lime Anchor) to 3.46 : 1. That passes the WCAG
  non-text floor (3 : 1) and nothing more; the captain's own warning applies to the mark too.
- The plum beak on coral is 3.54 : 1, a quiet detail that reads at 48 px and vanishes below it.
  Lime Anchor's lime beak was the loudest part of the mark; here the beak is a nuance.
- The coral wordmark on Surface is 3.46 : 1: keep it at the kit's minimum of 160 px (its strokes are
  "large text" by any measure) and never set running text or small links in coral on light grounds.

Ink Tile is the fallback if the captain wants a quieter, more "tech" icon: it has the best in-tile
contrast (bird 4.87, beak 8.65) and is the only treatment that shows the cyan accent in the mark.

## Token mapping for the port

Same token names as `site/tokens.css`; only values change. Light block:

| Token | Lime Anchor | Hot Coral | Note |
| --- | --- | --- | --- |
| `--hue` | 130 | 258 | the greys follow the palette's blue-grey (`#667085`, `#E4E7EC` are ~258°) |
| `--brand-signature` | `#2F6B00` | `#F0446E` | links, primary action, focus ring |
| `--brand-secondary` | `#174A34` | `#5B1738` | headers, hover of the primary action |
| `--brand-lime` → `--brand-tech` | `#D7FF2F` | `#20C7D9` | tech icons, charts, interactive points; never text on light |
| `--brand-surface` | `#F8FBF3` | `#F7F9FC` | reading surface; text colour in dark mode |
| `--brand-ink` | `#142018` | `#101828` | text on light; dark-mode bar |
| `--brand-white` | `#FFFFFF` | `#FFFFFF` | |
| `--color-accent` | signature | signature `#F0446E` | 3.46 on Surface: standout links at ≥ 18.66 px bold or ≥ 24 px only |
| `--color-link` (new) | — | secondary `#5B1738` | inline text links on light, 12.26 on Surface |
| `--color-accent-hover` | secondary | secondary `#5B1738` | the captain's hover role |
| `--color-on-accent` | white | ink `#101828` | 4.87 on coral: AA for any size; white (3.65) only on buttons ≥ 18.66 px bold |
| `--color-ink-2` / `--color-ink-3` | gray-44 / gray-51 | `#667085` muted (4.72 on Surface) | secondary text |
| `--color-border` | gray-90 | `#E4E7EC` | |
| `--color-live` (breaking) | red-55 | `#F0446E` | the breaking-news tag: coral fill, ink text |

Dark block (`#111827` ground):

| Token | Lime Anchor | Hot Coral | Contrast |
| --- | --- | --- | --- |
| `--color-bar` / `--color-inset` | ink | `#111827` | |
| `--color-ink` | surface | `#F7F9FC` | 16.82 |
| `--color-accent` | lime | `#F0446E` | 4.86, AA for text at any size |
| `--color-accent-hover` | lime-hover | `#F4698A` (coral one step lighter, same hue) | 6.11 |
| `--color-on-accent` | ink | `#101828` | 4.87 on coral |
| `--color-tech` | — | `#20C7D9` | 8.64, charts and interactive points |
| `--color-ink-2` | gray-80 | `#98A2B3` | 6.89 |
| `--color-border` | deep-27 | `#1F2937` | |

Dark-mode pairs: surface letters on `#111827`; coral action with ink text; cyan for charts; mark on
dark keeps its coral tile (4.86 against the ground).

## Files

- `build.py` writes every SVG and PNG here from `../lime-anchor/`, the four contact sheets and
  `contrast-checks.json`. Run `python brand/logo/hot-coral/build.py` (headless Chrome + Pillow).
- `<treatment>/icons/halcyon-icon-primary.svg` + PNG 16, 32, 48, 128, 512; `favicons/favicon.svg`;
  `logos/halcyon-primary.svg` (light ground, transparent), `halcyon-dark.svg` (dark ground),
  `halcyon-on-surface.svg`, `halcyon-on-dark.svg`, `halcyon-mono-ink.svg`, `halcyon-mono-white.svg`,
  and the 640 px PNG of the two transparent wordmarks.
