"""
Cut the post-processed frame sequence into the web clips used by the site.

    python blender/encode.py renders/post assets

Produces
  assets/video/t1.mp4  hero -> s2      t1r.mp4  s2 -> hero
  assets/video/t2.mp4  s2   -> s3      t2r.mp4  s3 -> s2
  assets/video/t3.mp4  s3   -> hero    t3r.mp4  hero -> s3
  assets/video/film.mp4  the whole loop with holds (for "Watch video")
  (every clip is written as .mp4/H.264 and .webm/VP9)
  assets/img/hero.jpg, s2.jpg, s3.jpg  section stills / posters
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from camera_path import FPS, MARKS  # noqa: E402

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


def encode_seq(frames, out, fps=FPS):
    """Encode to <out>.mp4 (H.264, Safari) and <out>.webm (VP9, Chrome/Firefox)."""
    base = out[:-4] if out.endswith(".mp4") else out
    with tempfile.TemporaryDirectory() as tmp:
        for i, src in enumerate(frames):
            os.symlink(os.path.abspath(src), os.path.join(tmp, f"{i:05d}.png"))
        pattern = os.path.join(tmp, "%05d.png")
        run(["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-i", pattern, *X264, base + ".mp4"])
        run(["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-i", pattern, *VP9, base + ".webm"])


def main():
    src, assets = sys.argv[1], sys.argv[2]
    vdir = os.path.join(assets, "video")
    idir = os.path.join(assets, "img")
    os.makedirs(vdir, exist_ok=True)
    os.makedirs(idir, exist_ok=True)

    def frame(i):
        return os.path.join(src, f"f_{i:04d}.png")

    marks = [MARKS["hero"], MARKS["s2"], MARKS["s3"], MARKS["hero_end"]]
    names = ["t1", "t2", "t3"]
    for k, name in enumerate(names):
        a, b = marks[k], marks[k + 1]
        seq = [frame(i) for i in range(a, b + 1)]
        encode_seq(seq, os.path.join(vdir, f"{name}.mp4"))
        encode_seq(list(reversed(seq)), os.path.join(vdir, f"{name}r.mp4"))

    # film: hold each state, then move on (loops seamlessly)
    hold = int(FPS * 1.6)
    film = []
    for k in range(3):
        film += [frame(marks[k])] * hold
        film += [frame(i) for i in range(marks[k] + 1, marks[k + 1])]
    encode_seq(film, os.path.join(vdir, "film.mp4"))

    for name, i in (("hero", marks[0]), ("s2", marks[1]), ("s3", marks[2])):
        run(["ffmpeg", "-v", "error", "-y", "-i", frame(i), "-q:v", "3", os.path.join(idir, f"{name}.jpg")])


if __name__ == "__main__":
    main()
