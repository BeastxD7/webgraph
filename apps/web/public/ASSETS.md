# Bundled assets

Everything in this directory is third-party content with its own licence, separate from the
project's MIT licence. Anything added here must be recorded below before it is committed.

## `earth/` — the landing hero's Earth (NASA, public domain)

NASA imagery is not copyrighted and may be used without permission; NASA asks to be credited,
which the hero does at the frame's edge ("Earth imagery: NASA"). Each file is a downsample
of the original (macOS `sips`, JPEG), kept small so the hero's textures total ~1.4 MB.

| file | source | original |
|---|---|---|
| `day-2k.jpg`, `day-512.jpg` | Blue Marble Next Generation with topography and bathymetry, December 2004, NASA Earth Observatory (Reto Stöckli, NASA GSFC) — <https://visibleearth.nasa.gov/images/73909> | `world.topo.bathy.200412.3x5400x2700.jpg` |
| `night-2k.jpg`, `night-512.jpg` | Black Marble 2016, NASA Earth Observatory (Joshua Stevens; NASA GSFC, Miguel Román) — <https://visibleearth.nasa.gov/images/144898> | `BlackMarble_2016_01deg.jpg` |
| `clouds-2k.jpg`, `clouds-512.jpg` | Blue Marble cloud cover (combined), NASA Goddard Space Flight Center — <https://visibleearth.nasa.gov/images/57747> | `cloud_combined_2048.jpg` |
| `spec-1k.jpg` | An ocean mask derived here from `day-2k.jpg` (where blue dominates), for the sun's glint; no separate source | — |
| `still-1440-light.jpg`, `still-1440-dark.jpg` | The hero's resting frame in each theme (day, and the sunrise), rendered from the textures above by the hero's own WebGL code (`tools/render_hero_still.py`); what the page shows before JavaScript | — |

The previous hero photograph (*The Palouse from Steptoe Butte*, Caleb Riston, CC BY 4.0) was
removed with the landing redesign, together with the footer credit it required.

## Brand

| file | what | source |
|---|---|---|
| `logo/mark.svg` | The mark: the constellation w -- five nodes, four edges, its brightest star a four-point star at the top right -- white on the accent tile; 24-unit grid | drawn in-house (`docs/design/logo-explorations-2.svg`, `logo-refinement-2.svg`, `logo-refinement-3.svg`) |
| `favicon.svg`, `app/icon.svg` | The mark's 16 px form: the star drawn as a larger dot, because its arms merge at that size; otherwise identical | in-house |
| `logo/mark-mono.svg` | The glyph alone on `currentColor`, for one-colour uses | in-house |
| `logo/lockup.svg` | Mark + "webgraph"; the wordmark is Manrope 700 as `<text>`, so a machine without Manrope falls back to the system sans -- the site itself sets it in `<Wordmark>` | in-house |
| `logo/icon-32.png`, `icon-180.png`, `icon-512.png`, `app/apple-icon.png` | The mark rasterised (headless Chromium) | in-house |
| `logo/og.png`, `app/opengraph-image.png` | 1200×630: the mark and wordmark over `earth/still-1440-dark.jpg` | in-house; the Earth as above |


## Technology marks (Simple Icons, CC0-1.0)

The mark beside a detected technology's name -- in the Site Report's Stack section, the crawl's
"Technology detected" panel and its pipeline row, and a page run's framework chips -- is a
Simple Icons path (`simple-icons` 16.31.0 on npm, CC0-1.0, <https://simpleicons.org>), drawn
inline at 14 px in one colour from our own tokens. Nothing is copied into this directory: the
102 marks we use are named imports in `lib/tech-icons.ts` and ship as one deferred chunk.
Simple Icons' own `DISCLAIMER.md` applies: the set is CC0, the marks are not. Marks are
trademarks of their owners, shown to identify the detected technology, and a technology
whose mark is not in the set (or whose owner withdrew it -- Amazon, Microsoft, Adobe,
LinkedIn) gets a neutral cube outline drawn in-house, never a neighbouring brand's mark.
