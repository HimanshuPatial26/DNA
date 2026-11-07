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

Scrolling past section 3 loops back to section 1 with a pull-out move.

---

## Quick start

Everything is already rendered and committed. The site is plain HTML, CSS and JS with
**no build step and no dependencies**.

```bash
git clone https://github.com/HimanshuPatial26/DNA.git
cd DNA
npm start            # or: node server.mjs
```

Open **http://localhost:8080**. Set a different port with `PORT=3000 npm start`.

The only requirement is Node.js 18 or newer. If you don't have Node, Python also works
(`python3 -m http.server 8080`). Python's server can't stream video byte ranges,
though, so use `npm start` when testing in Safari.

> Opening `index.html` straight from disk (`file://`) mostly works in Chrome, but
> browsers restrict fonts and `fetch` on `file://` URLs. Use a local server.

### Controls

| Action | Input |
| --- | --- |
| next / previous section | mouse wheel or trackpad · ↓ / ↑ · PageDown / PageUp · Space · swipe up/down |
| jump to a section | pager dots on the right edge · **menu** overlay · logo (back to start) |
| watch the full fly-through | **Watch video** on the first section |
| close menu or video | **Esc** |

---

## Deploy

It's a static folder, so upload the repository root anywhere:

* **Vercel:** import the repo, set the framework preset to **Other**, leave the build command
  empty and set the output directory to `.`. Or run `npx vercel` from the folder.
* **Netlify:** drag the folder into the Netlify dashboard, or connect the repo with no build command.
* **GitHub Pages:** go to *Settings → Pages*, choose *Deploy from a branch*, then this branch and `/ (root)`.

The `blender/`, `server.mjs` and `package.json` files are only for development. They are
harmless to deploy.

---

## Project structure

```
index.html               markup: header, three panels, pager, menu, video modal
assets/
  css/style.css          layout, typography, masked line reveals, responsive rules
  js/main.js             clip playback, section state machine, wheel/key/touch input
  video/                 t1..t3 forward + t1r..t3r reversed camera moves, idle0..2 loops, film
                         each in .mp4 (H.264) and .webm (VP9); the browser picks one
  img/                   hero.jpg / s2.jpg / s3.jpg section stills, favicon.svg
  fonts/                 Lexend (SIL Open Font License, see OFL.txt)
blender/                 procedural 3D scene + render / post / encode pipeline
server.mjs               zero-dependency dev server with HTTP Range support
package.json             `npm start`
```

### How the page works

* The helix is one pre-rendered camera loop (`hero → s2 → s3 → wide → hero`). It is
  cut at the section marks into short clips, and each clip also has a reversed copy.
  Going forward plays `tN` and going back plays `tNr`. Each clip ends on the exact frame
  where the next one starts, so swapping clips is seamless and the loop has no seam.
* Clips are fetched as blobs right after first paint (about 3.5 MB WebM or 5.5 MB MP4 in
  total), so moves start instantly. If a clip isn't ready, or the visitor prefers
  reduced motion, the page cross-fades between section stills instead.
* One trackpad swipe moves exactly one section: the momentum tail is ignored until
  the gesture ends.
* While a section rests, a seamless 5-second **idle loop** plays (`idle0..2`). The camera
  floats on a small ellipse and an energy pulse sweeps along the helix, lighting up the
  rings and circuitry. Each loop starts and ends exactly on the section's pose; short
  crossfades blend it with the camera moves. A light mouse parallax adds depth.
* Editing the copy: change the text in `index.html`. Each `<span class="line">` is one
  masked line on desktop. On phones the lines re-wrap automatically.

---

## Re-rendering the 3D (optional)

You only need this to change the 3D shots. The scene is fully procedural Python with no
`.blend` file to maintain. It uses Blender 5.2 installed as the `bpy` Python module, so
you don't need a separate Blender install.

**Requirements:** Python **3.13** and ffmpeg built with libx264 and libvpx-vp9.

```bash
python3.13 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r blender/requirements.txt

# 1. render linear RGBA EXR frames with Cycles (141 frames)
python blender/dna_scene.py --out renders/frames --res 1600x900 --samples 48

# 1b. render the three idle loops (225 frames at 15 fps, blended to 30 fps later)
python blender/dna_scene.py --out renders/idle --res 1600x900 --samples 48 --idle all

# 2. background gradient + bloom + filmic tone map  ->  PNG
python blender/post.py renders/frames renders/post
for s in hero s2 s3; do python blender/post.py renders/idle/idle_$s renders/post-idle/idle_$s; done

# 3. cut into web clips + stills (overwrites assets/video and assets/img)
python blender/encode.py renders/post assets --idle renders/post-idle
```

On a 4-core CPU step 1 takes about 70 minutes and step 1b about 1¾ hours (roughly 30 s per
frame); a GPU is much faster. Use `encode.py --skip-transitions` to re-encode only the loops.
`renders/` is git-ignored. Re-running step 1 skips frames that already exist, so
delete `renders/frames` after changing the scene.

| File | Purpose |
| --- | --- |
| `blender/dna_scene.py` | Builds the helix: swept backbone tubes with machined grooves and cyan "data-lane" circuitry, T-junction hubs, rungs with glass tips and concentric glowing lenses, and floating rings. Also sets up the lights, depth of field and motion blur. |
| `blender/camera_path.py` | Camera pose per section (`POSES`), the eased spline moves between them (`SEGMENTS`) and the idle-loop drift and energy pulse (`IDLE`). The site's clip boundaries come from `MARKS`. |
| `blender/preview.py` | Fast low-res look-dev renders: `python blender/preview.py --out /tmp/prev hero s2 s3 wide`. |
| `blender/post.py` | Background gradient, bloom, vignette and tone mapping. |
| `blender/encode.py` | Encodes forward/reversed clips, the full film and the stills. |

To change a shot, edit `POSES` in `camera_path.py`, preview it, then run the three steps.

---

## Credits

* Typeface: [Lexend](https://github.com/googlefonts/lexend), SIL Open Font License 1.1 (`assets/fonts/OFL.txt`).
* 3D: procedural geometry and materials in this repository, rendered with Blender Cycles.
