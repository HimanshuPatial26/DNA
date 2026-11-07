"""
Cut the post-processed frames into the web clips used by the site.

    python blender/encode.py renders/post assets --idle renders/post-idle

Produces (every clip as .mp4/H.264 for Safari and .webm/VP9 for Chrome/Firefox)
  assets/video/t1  hero -> s2      t1r  s2 -> hero
  assets/video/t2  s2   -> s3      t2r  s3 -> s2
  assets/video/t3  s3   -> hero    t3r  hero -> s3
  assets/video/idle0..idle2  seamless idle loops for hero / s2 / s3
  assets/video/film  the whole journey with idle holds (for "Watch video")
  assets/img/hero.jpg, s2.jpg, s3.jpg  section stills / posters

--idle points at the post-processed idle renders (idle_<state>/f_####.png),
which are rendered at IDLE_FPS and blended up to FPS here.
--skip-transitions re-encodes only the idle loops and the film.
"""

import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from camera_path import FPS, IDLE_FPS, IDLE_FRAMES, IDLE_STATES, MARKS  # noqa: E402

X264 = [
    "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-tune", "film",
    "-x264-params", "aq-mode=3:aq-strength=0.9",
    "-pix_fmt", "yuv420p", "-profile:v", "high", "-movflags", "+faststart", "-an",
]
VP9 = [
    "-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0", "-deadline", "good", "-cpu-used", "1",
    "-row-mt", "1", "-pix_fmt", "yuv420p", "-an",
]


def run(cmd):
    print(" ".join(cmd))
    subprocess.run(cmd, check=True)


def link_seq(frames, tmp):
    for i, src in enumerate(frames):
        os.symlink(os.path.abspath(src), os.path.join(tmp, f"{i:05d}.png"))
    return os.path.join(tmp, "%05d.png")


def encode_seq(frames, base, fps=FPS):
    """Encode a list of PNG frames to <base>.mp4 and <base>.webm."""
    with tempfile.TemporaryDirectory() as tmp:
        pattern = link_seq(frames, tmp)
        run(["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-i", pattern, *X264, base + ".mp4"])
        run(["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-i", pattern, *VP9, base + ".webm"])


def upsample_loop(frames, out_dir):
    """Blend an IDLE_FPS loop up to FPS. The first frame is appended so the
    blend wraps around, then cut so the clip loops with no seam."""
    n_out = len(frames) * FPS // IDLE_FPS
    os.makedirs(out_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        pattern = link_seq(frames + frames[:1], tmp)
        run([
            "ffmpeg", "-v", "error", "-y", "-framerate", str(IDLE_FPS), "-i", pattern,
            "-vf", f"framerate=fps={FPS}:interp_start=0:interp_end=255",
            "-frames:v", str(n_out), os.path.join(out_dir, "%05d.png"),
        ])
    return [os.path.join(out_dir, f"{i + 1:05d}.png") for i in range(n_out)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="post-processed transition frames (f_####.png)")
    ap.add_argument("assets", help="site assets directory")
    ap.add_argument("--idle", default="", help="post-processed idle loops root (idle_<state>/)")
    ap.add_argument("--skip-transitions", action="store_true")
    args = ap.parse_args()

    vdir = os.path.join(args.assets, "video")
    idir = os.path.join(args.assets, "img")
    os.makedirs(vdir, exist_ok=True)
    os.makedirs(idir, exist_ok=True)

    def frame(i):
        return os.path.join(args.src, f"f_{i:04d}.png")

    marks = [MARKS["hero"], MARKS["s2"], MARKS["s3"], MARKS["hero_end"]]

    if not args.skip_transitions:
        for k, name in enumerate(["t1", "t2", "t3"]):
            seq = [frame(i) for i in range(marks[k], marks[k + 1] + 1)]
            encode_seq(seq, os.path.join(vdir, name))
            encode_seq(list(reversed(seq)), os.path.join(vdir, name + "r"))
        for name, i in (("hero", marks[0]), ("s2", marks[1]), ("s3", marks[2])):
            run(["ffmpeg", "-v", "error", "-y", "-i", frame(i), "-q:v", "3", os.path.join(idir, f"{name}.jpg")])

    with tempfile.TemporaryDirectory() as work:
        holds = []
        for k, state in enumerate(IDLE_STATES):
            src = os.path.join(args.idle, f"idle_{state}") if args.idle else ""
            if src and os.path.isdir(src):
                frames = [os.path.join(src, f"f_{i:04d}.png") for i in range(IDLE_FRAMES)]
                loop = upsample_loop(frames, os.path.join(work, state))
                encode_seq(loop, os.path.join(vdir, f"idle{k}"))
                holds.append(loop)
            else:
                holds.append([frame(marks[k])] * int(FPS * 1.6))  # static hold fallback

        # film: idle hold, then the move to the next section (loops seamlessly)
        film = []
        for k in range(3):
            film += holds[k]
            film += [frame(i) for i in range(marks[k], marks[k + 1])]
        encode_seq(film, os.path.join(vdir, "film"))


if __name__ == "__main__":
    main()
