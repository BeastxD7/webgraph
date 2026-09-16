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
