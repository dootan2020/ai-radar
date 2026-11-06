# Halcyon · Hot Coral treatments

Three colour treatments of the approved Halcyon mark (the kingfisher "y" with its beak, in a rounded
tile) and wordmark, moved from the Lime Anchor colours onto the Hot Coral palette. The shapes are the
Lime Anchor vectors in `../lime-anchor/`, read and recoloured by `build.py`; nothing is redrawn.

**The captain chose Coral Tile on 2026-11-06 (23:5x).** `build.py` writes it to `brand/logo/coral-tile/`, the
one kit `brand/publish_kit.py` publishes, and the site, the extension, the favicon, the Store art and the
share images are built from it. Plum Tile, Ink Tile and the retired Lime Anchor kit stay here in
`brand/logo-work/`, which is never published.

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

## Token mapping as shipped (`site/tokens.css`)

The proposal above became the following. Where it departs from the captain's notes or the first proposal,
the reason is in the last column. Contrast is WCAG 2 relative luminance.

Primitives: `--hue` 130 → 258; `--brand-signature` #2F6B00 → #F0446E; `--brand-secondary` #174A34 → #5B1738;
`--brand-lime` #D7FF2F → `--brand-tech` #20C7D9; `--brand-surface` #F8FBF3 → #F7F9FC; `--brand-ink` #142018 →
#101828; new `--brand-surface-dark` #111827, `--brand-card-dark` #1D2939, `--brand-muted` #667085,
`--brand-border` #E4E7EC; coral shades `--coral-text` #B82F55, `--coral-breaking` #B4234D, `--coral-wash`
#FFE4EA, `--coral-light` #F4698A; cyan shades `--cyan-text` #0B6F7A, `--cyan-wash` #E3F7F9. The green dark ramp
(`--deep-16…32`, hue 155) and `--red-55/70` are gone; `--deep-33/38` (hue 262) replace the dark fill and hairline.

Light:

| Role | Lime Anchor | Hot Coral | Contrast | Why |
| --- | --- | --- | --- | --- |
| `--color-canvas` | gray-95 | Surface #F7F9FC | | captain: 60 % light surface |
| `--color-surface` (card) | Surface | white | | captain: cards white |
| `--color-card-edge` (new) | — | Border #E4E7EC | | captain: light grey border |
| `--color-bar` | Surface | white | | |
| `--color-hair` | gray-90 | Border #E4E7EC | | |
| `--color-ink-2` | gray-44 | gray-44 (hue 258) | 7.7 on white | long supporting text a step darker than Muted |
| `--color-ink-3` | gray-51 | Muted #667085 | 4.97 white, 4.72 Surface | |
| `--color-heading` (new) | — | Plum #5B1738 | 12.26 | captain: Plum for strong headers, important titles |
| `--color-accent` (text) | Signature #2F6B00 | #B82F55 | 5.87 white, 5.57 Surface | coral #F0446E is 3.46: links, active tabs and coral words use the captain's own #B82F55 |
| `--color-accent-hover` | Secondary | Plum #5B1738 | 12.93 | captain: hover |
| `--color-accent-fill` (new) | — | Coral #F0446E | | primary button, header action, badges, story rule and bullets |
| `--color-on-accent` | white | Ink #101828 | 4.87 | captain: no small white text on coral |
| `--color-accent-fill-hover` / `--color-on-accent-hover` (new) | — | Plum / white | 12.93 | |
| `--color-live` / `--color-live-wash` | red-55 / red 10 % | #B4234D / #FFE4EA | 5.33 | captain: breaking tag |
| `--color-live-fill` (new) | — | #B4234D | 6.39 with white | a breaking badge on a picture |
| `--color-ok` / `--color-ok-wash` | green 145 | #0B6F7A / #E3F7F9 | 5.88 | a green "ready / up" read as leftover Lime Anchor; the palette's cyan, one step deeper for text |
| `--color-tech` (new) | — | Cyan #20C7D9 | | the unread dot, an interactive point |
| `--color-chart` (new) | — | #0B6F7A | 5.88 | chart points on light need 3 : 1; cyan is 2.05 |

Dark (`#111827` page):

| Role | Lime Anchor | Hot Coral | Contrast | Why |
| --- | --- | --- | --- | --- |
| `--color-canvas` / `--color-bar` / `--color-inset` | deep-16 / ink / ink | #111827 | | captain |
| `--color-surface` | deep-20 | #1D2939 | | captain: cards #1D2939 |
| `--color-fill` / `--color-hair` | deep-27 / deep-32 | deep-33 / deep-38 | | |
| `--color-card-edge` | — | transparent | | dark cards rise by lightness |
| `--color-ink` | Surface | Surface #F7F9FC | 13.94 on card | |
| `--color-accent` (text) | Lime | #F4698A | 5.06 on card | coral #F0446E is 4.03 on the card: coral kept, one step lighter for words |
| `--color-accent-hover` | lime-hover | #F4698A mixed 40 % toward Surface | | |
| `--color-accent-fill` / `--color-on-accent` | Lime / Ink | Coral / Ink | 4.87 | captain: coral kept as the accent |
| `--color-accent-fill-hover` | — | #F4698A with Ink | 6.11 | Plum would vanish on dark |
| `--color-live` | red-70 | #F4698A | 5.06 | |
| `--color-ok`, `--color-tech`, `--color-chart` | green 145 | Cyan #20C7D9 | 7.16 on card | |

Other placements: feed section titles, tile titles and the story headline use `--color-heading`;
the feed's `.btn` is the captain's secondary (coral outline, #B82F55 text) and `.btn.primary` the coral
fill; `theme-color` is white in light and #111827 in dark. Share images, covers and the Store promo are
rebuilt by `brand/build-assets.py` and `brand/export-png.py` with the same roles.

## Files

- `build.py` writes every SVG and PNG here (Coral Tile into `brand/logo/coral-tile/`) from `../lime-anchor/`, the four contact sheets and
  `contrast-checks.json`. Run `python brand/logo/hot-coral/build.py` (headless Chrome + Pillow).
- `<treatment>/icons/halcyon-icon-primary.svg` + PNG 16, 32, 48, 128, 512; `favicons/favicon.svg`;
  `logos/halcyon-primary.svg` (light ground, transparent), `halcyon-dark.svg` (dark ground),
  `halcyon-on-surface.svg`, `halcyon-on-dark.svg`, `halcyon-mono-ink.svg`, `halcyon-mono-white.svg`,
  and the 640 px PNG of the two transparent wordmarks.
