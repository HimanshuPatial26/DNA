# DNA — landing page

A full-screen, three-section landing page for a DNA-testing product, built around a
photoreal mechanical DNA helix rendered in **Blender (Cycles)**. Each scroll moves
the camera through the helix to the next shot while the copy slides out and in
through masked line reveals.

| Section | Copy | Shot |
| --- | --- | --- |
| 1 | *Find out what your DNA says about you and your family.* + **Watch video** | wide diagonal helix |
| 2 | *How will DNA testing change you?* | close-up along the helix, shallow focus |
| 3 | *What part of the world do your ancestors come from?* | macro of a glowing base-pair connector |

Scrolling past section 3 loops back to section 1 with a pull-out move, as in the reference.

## Run it

It's a static site with no build step:

```bash
python3 -m http.server 8080
```

Then open <http://localhost:8080>. Any static host works (Vercel, Netlify, GitHub Pages, S3).

**Navigation:** mouse wheel or trackpad, arrow keys, PageUp and PageDown, swipe on touch devices, the
pager on the right edge, or the **menu** overlay. **Watch video** plays the whole fly-through.

## How it works

```
index.html               markup for the header, three panels, menu and video modal
assets/css/style.css     layout, typography, masked line reveals, responsive rules
assets/js/main.js        clip playback, section state machine, input handling
assets/video/            t1..t3 (forward) + t1r..t3r (reversed) camera moves, film (full loop)
                         every clip is in two formats: .mp4 (H.264) and .webm (VP9)
assets/img/              section stills (first frame shown before any clip plays)
assets/fonts/            Lexend (SIL OFL), a free geometric sans close to the reference type
blender/                 everything needed to regenerate the 3D renders
```

* The helix is a pre-rendered camera loop (`hero → s2 → s3 → wide → hero`).
  It is cut at the section marks into short clips, and each clip also has a reversed copy.
  Going forward plays `tN` and going back plays `tNr`. Each clip ends on the exact frame
  where the next one starts, so swapping clips is seamless.
* Clips are fetched as blobs after first paint, so later moves start instantly.
  If a clip is not ready yet, or the visitor prefers reduced motion, the page
  cross-fades between section stills instead.
* While a section is idle, a slow CSS drift and a light mouse parallax keep the frame moving.

## Re-rendering the 3D (Blender)

The scene is fully procedural Python with no `.blend` file to maintain. It runs on
Blender 5.x installed as the `bpy` Python module:

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install bpy OpenEXR opencv-python-headless numpy

# 1. render linear RGBA EXR frames with Cycles (141 frames)
python blender/dna_scene.py --out renders/frames --res 1600x900 --samples 48

# 2. background gradient + bloom + filmic tone map  ->  PNG
python blender/post.py renders/frames renders/post

# 3. cut into web clips + stills (needs ffmpeg with libx264 + libvpx-vp9)
python blender/encode.py renders/post assets
```

* `blender/dna_scene.py`: builds the helix procedurally. It makes swept backbone tubes with
  machined grooves and cyan "data-lane" circuitry, T-junction hubs, rungs with glass
  tips and concentric glowing lenses, and floating rings. It also sets up the lights,
  depth of field and motion blur.
* `blender/camera_path.py`: camera poses for each section and the eased spline
  moves between them. The website's clip boundaries come from `MARKS`.
* `blender/preview.py`: fast low-res look-dev renders of named poses or frames.

On a 4-core CPU a full render takes about 70 minutes (roughly 30 s per frame). To change a shot, edit
`POSES` or `SEGMENTS` in `camera_path.py` and re-run the three steps.
