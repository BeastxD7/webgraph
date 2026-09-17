# Theme study — is green the right palette under the Earth hero?

(The contact sheets and per-view shots this refers to were produced in the theme-study session and attached to PR #TBD; the tokens that came out of it are in `apps/web/app/globals.css` §1.)

Date 2026-09-17. Branch `theme-study`. Evidence: `control.png`, `atmosphere.png`, `sunrise.png`,
`ink.png` (one contact sheet per candidate: the same eight views, light and dark, with the
candidate's swatches and its contrast table), `seam.png` (the hero frame's bottom over each
candidate's ground, both themes), and the per-view shots under `shots/<palette>-<theme>-<view>.png`.
Every shot is the production build of main with the candidate's tokens injected over the live
ones -- the same markup, only the `--*` values change -- so what differs between sheets is the
palette and nothing else.

## The tension

The hero is astronomical: black space, the atmosphere's cold blue at the limb, a warm flare, a
white serif; by day a blue-grey sky and blue water. Below it the site was botanical: an ink-green
accent, warm bone paper, a ruled grid. Two brands meeting at one seam. The green also did two
jobs at once -- it was the accent (links, buttons, focus) *and* the semantic "measured", so a
verified value and a hyperlink shared a colour.

## Colours sampled from the hero (the source for the candidates)

| where | hex |
|---|---|
| space, dark frame, top-left | `#020202` (frame ground `#05070c`) |
| atmosphere glow at the limb, dark, away from the sun (x 450, y 600-620) | `#3b4e76` → `#5b78a2` → `#708eb4` → `#86a4c6` |
| the limb line itself | `#f8fbff` |
| the flare's halo edge (dark, right of the sun) | `#a5a29b` / `#d5d3d1` -- nearly white; its hue is the shader's `(1.0, 0.85, 0.65)` |
| day sky, top → near the limb (light frame, x 60) | `#808fa2` → `#a2aeba` → `#c1c8d0` |
| day water | `#6a7c94` / `#768fac` |

## Candidates

**Control (green, as shipped).** Bone `#f6f7f4`, ink `#0f1a14`, leaf `#3f8527` / `#326a20`; dark
`#0e1310` with `#7fc063`. What it does well: warm, readable, the green chips on the report are
unambiguous. Where it fails: the seam. In dark the ground is a green-black next to the frame's
blue-black, with a green blob from the backdrop glowing beside space (`seam.png`, second cell);
in light the warm bone meets the frame's cool blue-grey sky. And accent = good.

**Atmosphere.** Accent from the limb (`#3568a3` fill / `#2b5a91` text; dark `#7ea9dc` / `#93bbea`),
cool paper `#f4f6f9` from the sky family, dark ground `#080c14` -- the hero's space lifted one
step, ink a navy-black `#0f1624`. Green stays as `good` (measured), the flare's amber is `warn`,
oxide red is `bad`: the report keeps three distinct state hues and none of them is the accent.
The grid becomes a graticule (96 px majors, 24 px minors). What it does well: the seam agrees in
both themes (`seam.png`, third and fourth cells: the day sky flows into the cool paper; the
navy ground continues space), the How-it-reads panel reads like a diagram on drafting paper,
"measured" green now means only measured. Risk: blue is the default web. Mitigations that are
visible on the sheet: the blue is a deep, desaturated limb blue, not a UI blue; the serif and
the amber edge of the panel frame carry the character; the grid is a graticule.

**Sunrise.** Neutral ink/paper with the flare's amber as the accent (`#a86412` / `#8f5409`; dark
`#f0b45f`), `warn` pushed to burnt orange, `bad` to a cool crimson so red is not the accent.
What it does well: distinctive and warm, the dark theme is handsome. Where it fails: the
recall bar and the citation anchors in amber read as caution (`shots/sunrise-light-how.png`,
the bar under 1.000); to keep three states distinct the flags had to become three warm hues
side by side (amber accent, orange warn, crimson bad), which is exactly the muddle a report UI
cannot afford; and in light the warm paper sits against the cool day sky -- the weakest seam
of the three.

**Ink.** Near-monochrome: ink, paper, graphite; colour only as state. Accent = ink, links = ink
underlined. What it does well: the most editorial; dark is the closest to linear.app/vercel.com
and to the hero's white-on-black (`shots/ink-dark-how.png`). Where it fails: the product pages
go grey -- the "Available" chips, the active nav, the docs' primary all lose their colour
(`shots/ink-light-products.png`), so the "does it feel dead" test fails on `/products` and
`/watch`; links without colour need an underline everywhere or they vanish, which the docs
theme does not give them.

## Contrast (computed; softs composited on the ground)

The site's own floors are stricter than the brief's 4.5 / 3: `muted` ≥ 7:1 (the Backdrop
comment calls it "the AAA floor with no headroom"), `faint` ≥ 4.2:1 large-only. Every candidate
clears them; Atmosphere's `muted` is 7.2 / 8.7, its `faint` 4.4 / 5.5.

## control
| check | light | dark |
|---|---:|---:|
| ink/ground | 16.6 | 15.6 |
| muted/ground | 7.2 | 8.2 |
| faint/ground | 4.2 | 5.0 |
| accent-ink/ground | 6.1 | 10.1 |
| accent-ink/surface | 6.5 | 9.4 |
| text on accent fill | 4.6 | 8.6 |
| good/ground | 6.1 | 10.1 |
| warn/ground | 5.5 | 9.4 |
| bad/ground | 6.6 | 7.8 |
| good/good-soft | 5.6 | 7.8 |
| warn/warn-soft | 5.0 | 7.3 |
| bad/bad-soft | 5.8 | 6.3 |

## atmosphere
| check | light | dark |
|---|---:|---:|
| ink/ground | 16.7 | 16.2 |
| muted/ground | 7.2 | 8.7 |
| faint/ground | 4.4 | 5.5 |
| accent-ink/ground | 6.5 | 9.8 |
| accent-ink/surface | 7.1 | 9.2 |
| text on accent fill | 5.7 | 8.0 |
| good/ground | 5.7 | 9.8 |
| warn/ground | 5.6 | 10.3 |
| bad/ground | 6.1 | 8.2 |
| good/good-soft | 5.2 | 7.9 |
| warn/warn-soft | 5.2 | 8.1 |
| bad/bad-soft | 5.4 | 6.8 |

## sunrise
| check | light | dark |
|---|---:|---:|
| ink/ground | 16.6 | 16.6 |
| muted/ground | 7.6 | 8.3 |
| faint/ground | 4.4 | 5.0 |
| accent-ink/ground | 5.6 | 11.5 |
| accent-ink/surface | 6.1 | 10.8 |
| text on accent fill | 4.7 | 10.7 |
| good/ground | 5.7 | 9.9 |
| warn/ground | 5.1 | 8.6 |
| bad/ground | 6.1 | 8.3 |
| good/good-soft | 5.2 | 7.9 |
| warn/warn-soft | 4.5 | 7.0 |
| bad/bad-soft | 5.3 | 6.8 |

## ink
| check | light | dark |
|---|---:|---:|
| ink/ground | 17.3 | 16.9 |
| muted/ground | 8.0 | 8.4 |
| faint/ground | 4.5 | 5.0 |
| accent-ink/ground | 17.3 | 19.8 |
| accent-ink/surface | 18.8 | 18.6 |
| text on accent fill | 18.8 | 16.9 |
| good/ground | 5.7 | 9.9 |
| warn/ground | 5.5 | 9.9 |
| bad/ground | 6.7 | 8.2 |
| good/good-soft | 5.2 | 8.0 |
| warn/warn-soft | 5.0 | 8.0 |
| bad/bad-soft | 5.9 | 6.8 |


## What the product needs

- A report UI with good / warn / bad states that are three hues, none of them the accent
  (Atmosphere and Ink satisfy this; Control and Sunrise do not).
- A docs site that is quiet: a single restrained accent for links and the active item
  (Atmosphere's deep blue; Ink has none, so links must be underlined).
- Marketing pages that carry the hero down the page: cool paper by day, space by night
  (Atmosphere only).
- Charts (`RankChart`) whose self bar and labels use the accent and the ink (all four work; the
  legacy `leaf-*` aliases map onto the accent).

## Against the references

llamaindex.ai and landing.ai use one accent on neutral paper with the illustration carrying the
character; linear.app and vercel.com are Ink with one accent used sparingly. Atmosphere is the
first pattern with the hero as the illustration; Ink is the second without the accent. None of
the four references uses green as a primary.

## Pick

**Atmosphere**, with two conditions carried into the tokens: `good` stays green and is never the
accent; the frame keeps a 1 px hairline (`box-shadow: 0 0 0 1px var(--rule)`) so its rounded
edge survives on the near-space dark ground. Applied site-wide as the token values in
`globals.css` §1/§1b, the docs bridge (`docs.css`, its dark block now on the tokens), the light
hero's `--scene-*` ink, `themeColor`, and the graticule. Sunrise's amber survives as `warn` and in
the hero's flare; Ink's discipline survives as the rule that colour means state.
