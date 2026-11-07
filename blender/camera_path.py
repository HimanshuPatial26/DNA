"""
Camera choreography shared by the renderer and the website.

States (website sections):
  hero  - wide diagonal view of the helix            (frame 0 and FRAME_COUNT-1)
  s2    - close-up along the helix, rung in focus    ("How will DNA testing change you?")
  s3    - macro of a glowing rung connector          ("What part of the world ...")

Transitions are rendered as one continuous loop:
  hero -> s2 -> s3 -> (pull out, horizontal) -> hero
"""

import math

FPS = 30

# --- poses ---------------------------------------------------------------
# loc / target in scene units, roll in degrees, lens in mm.
POSES = {
    "hero": dict(loc=(4.3, -10.7, 1.9), target=(0.6, 0.0, 0.0), roll=50.0, lens=38.0, fstop=2.8,
                 shift=(0.01, -0.01)),
    "s2": dict(loc=(-2.1, -1.0, -1.45), target=(0.9, 0.55, 0.55), roll=-105.0, lens=26.0, fstop=0.3,
               focus_point=(0.0, 0.242, 0.0), shift=(0.08, 0.04)),
    "s3": dict(loc=(-0.85, 0.0, 0.22), target=(0.0, 0.242, 0.0), roll=-95.0, lens=38.0, fstop=1.1,
               shift=(0.11, 0.04)),
    "wide": dict(loc=(3.0, -9.0, -1.5), target=(0.5, 0.0, 0.0), roll=17.0, lens=30.0, fstop=2.8),
}

# --- transitions -----------------------------------------------------------
# (from, to, frames, waypoints[list of (loc, target)])
SEGMENTS = [
    ("hero", "s2", 40, [((1.2, -7.0, -1.2), (0.6, 0.2, 0.2))]),
    ("s2", "s3", 36, [((-1.75, -0.55, -0.55), (0.0, 0.3, 0.1))]),
    ("s3", "wide", 34, [((-1.6, -1.9, 0.0), (0.2, 0.2, 0.0))]),
    ("wide", "hero", 30, []),
]

# Website markers (frame index where each state is reached)
MARKS = {"hero": 0}
_f = 0
for _a, _b, _n, _w in SEGMENTS:
    _f += _n
    MARKS.setdefault(_b, _f)
MARKS["hero_end"] = _f
FRAME_COUNT = _f + 1


def _lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def _catmull(p0, p1, p2, p3, t):
    t2, t3 = t * t, t * t * t
    return tuple(
        0.5 * ((2 * b) + (-a + c) * t + (2 * a - 5 * b + 4 * c - d) * t2 + (-a + 3 * b - 3 * c + d) * t3)
        for a, b, c, d in zip(p0, p1, p2, p3)
    )


def _spline(points, t):
    """Centripetal-ish Catmull-Rom through points, t in [0,1]."""
    n = len(points)
    if n == 2:
        return _lerp(points[0], points[1], t)
    seg = min(int(t * (n - 1)), n - 2)
    lt = t * (n - 1) - seg
    p1, p2 = points[seg], points[seg + 1]
    p0 = points[seg - 1] if seg > 0 else _lerp(p1, p2, -1.0)
    p3 = points[seg + 2] if seg + 2 < n else _lerp(p1, p2, 2.0)
    return _catmull(p0, p1, p2, p3, lt)


def ease_in_out(t, power=3.2):
    """Strong ease in/out: slow start, fast middle, long soft landing."""
    if t < 0.42:
        return 0.42 * (t / 0.42) ** power
    u = (1 - t) / 0.58
    return 1 - 0.58 * u ** (power * 0.9)


def _focus_point(p):
    return p.get("focus_point", p["target"])


def _dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def camera_state(frame):
    f = frame
    for a, b, n, way in SEGMENTS:
        if f <= n:
            A, B = POSES[a], POSES[b]
            t = ease_in_out(f / n)
            locs = [A["loc"]] + [w[0] for w in way] + [B["loc"]]
            tgts = [A["target"]] + [w[1] for w in way] + [B["target"]]
            loc = _spline(locs, t)
            tgt = _spline(tgts, t)
            fpA, fpB = _focus_point(A), _focus_point(B)
            fp = _lerp(fpA, fpB, t)
            # depth of field opens up only near the end of a move
            fs = math.exp(math.log(A["fstop"]) + (math.log(B["fstop"]) - math.log(A["fstop"])) * t)
            return dict(
                loc=loc,
                target=tgt,
                shift=_lerp(A.get("shift", (0, 0)), B.get("shift", (0, 0)), t),
                roll=A["roll"] + (B["roll"] - A["roll"]) * t,
                lens=A["lens"] + (B["lens"] - A["lens"]) * t,
                focus=max(0.05, _dist(loc, fp)),
                fstop=fs,
            )
        f -= n
    p = POSES["hero"]
    return dict(loc=p["loc"], target=p["target"], shift=p.get("shift", (0, 0)), roll=p["roll"], lens=p["lens"],
                focus=_dist(p["loc"], _focus_point(p)), fstop=p["fstop"])


# --- idle loops ------------------------------------------------------------
# While a section is on screen the site plays a short seamless loop: the camera
# floats on a small ellipse around its pose and an energy pulse sweeps along the
# helix. Every loop starts and ends exactly on the section's pose (t = 0 / 1).
IDLE_FPS = 15                 # rendered rate; blended up to FPS when encoding
IDLE_FRAMES = 75              # 5 s loop
IDLE = {
    # amp: (right, up) half-size of the camera ellipse in scene units
    # roll: degrees; pulse: x range the pulse centre sweeps, width, strength
    "hero": dict(amp=(0.42, 0.26), roll=0.7, pulse=(-14.0, 14.0), width=3.0, gain=1.6),
    "s2": dict(amp=(0.07, 0.045), roll=1.0, pulse=(-6.0, 12.0), width=2.0, gain=1.6),
    "s3": dict(amp=(0.022, 0.015), roll=1.2, pulse=(-5.0, 5.0), width=1.5, gain=1.4),
}
IDLE_STATES = ["hero", "s2", "s3"]


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _norm(a):
    n = math.sqrt(sum(x * x for x in a)) or 1.0
    return tuple(x / n for x in a)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def idle_state(name, t):
    """Camera + pulse for idle loop `name` at loop phase t in [0, 1)."""
    p = POSES[name]
    cfg = IDLE[name]
    fwd = _norm(_sub(p["target"], p["loc"]))
    right = _norm(_cross(fwd, (0.0, 0.0, 1.0)))
    up = _cross(right, fwd)
    a = 2 * math.pi * t
    ox = cfg["amp"][0] * math.sin(a)
    oy = cfg["amp"][1] * (1 - math.cos(a))
    off = tuple(r * ox + u * oy for r, u in zip(right, up))
    loc = tuple(l + o for l, o in zip(p["loc"], off))
    tgt = tuple(g + 0.25 * o for g, o in zip(p["target"], off))
    x0, x1 = cfg["pulse"]
    return dict(
        loc=loc,
        target=tgt,
        shift=p.get("shift", (0, 0)),
        roll=p["roll"] + cfg["roll"] * math.sin(a),
        lens=p["lens"],
        focus=max(0.05, _dist(loc, _focus_point(p))),
        fstop=p["fstop"],
        # energy pulse: fades in/out with the loop so t = 0 matches the pose frame
        pulse_x=x0 + (x1 - x0) * t,
        pulse_w=cfg["width"],
        pulse_gain=cfg["gain"] * math.sin(math.pi * t) ** 2,
    )


if __name__ == "__main__":
    import json
    print(json.dumps({"marks": MARKS, "frames": FRAME_COUNT, "fps": FPS,
                      "idle": {"states": IDLE_STATES, "frames": IDLE_FRAMES, "fps": IDLE_FPS}}))
