"""
Quick look-dev previews: render named poses or timeline frames at low res.

    python blender/preview.py --out /tmp/prev --res 640x360 --samples 24 hero s2 s3 wide 18 50
"""

import argparse
import importlib
import math
import os
import sys

import bpy
from mathutils import Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import camera_path  # noqa: E402
import dna_scene  # noqa: E402


def place(cam, st):
    loc = Vector(st["loc"])
    tgt = Vector(st["target"])
    q = (tgt - loc).normalized().to_track_quat("-Z", "Z")
    cam.matrix_world = Matrix.Translation(loc) @ q.to_matrix().to_4x4() @ Matrix.Rotation(math.radians(st["roll"]), 4, "Z")
    cam.data.lens = st["lens"]
    cam.data.shift_x, cam.data.shift_y = st.get("shift", (0, 0))
    cam.data.dof.focus_distance = st["focus"]
    cam.data.dof.aperture_fstop = st["fstop"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--res", default="640x360")
    ap.add_argument("--samples", type=int, default=24)
    ap.add_argument("items", nargs="+")
    a = ap.parse_args()
    importlib.reload(camera_path)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    w, h = (int(v) for v in a.res.split("x"))
    dna_scene.setup_render((w, h), a.samples, False)
    dna_scene.setup_world()
    dna_scene.setup_lights()
    dna_scene.build_dna()
    cam = dna_scene.setup_camera()
    os.makedirs(a.out, exist_ok=True)
    import json
    for it in a.items:
        if it.startswith("{"):
            p = json.loads(it)
            label = p.pop("name")
            st = dict(p)
            st["focus"] = camera_path._dist(p["loc"], p.get("focus_point", p["target"]))
        elif it in camera_path.POSES:
            label = it
            p = camera_path.POSES[it]
            st = dict(p)
            st["focus"] = camera_path._dist(p["loc"], camera_path._focus_point(p))
        else:
            label = it
            st = camera_path.camera_state(int(it))
        place(cam, st)
        bpy.context.scene.render.filepath = os.path.join(a.out, f"{label}.exr")
        bpy.ops.render.render(write_still=True)
        print("done", it, flush=True)


if __name__ == "__main__":
    main()
