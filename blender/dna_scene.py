"""
Procedural "mechanical DNA" scene for the hero fly-through.

Run headless with the `bpy` module (Blender 5.x as a Python package):

    python blender/dna_scene.py --out renders/frames --res 1920x1080 --samples 96

Builds one mesh (helix backbones, rungs, hubs, glowing rings), lights it,
animates the camera through the four website states and renders linear
RGBA EXR frames. `blender/post.py` then adds the background gradient, bloom
and tone mapping, and `blender/encode.sh` turns the frames into web clips.
"""

import argparse
import math
import os
import random
import sys

import bpy
from mathutils import Matrix, Vector

# --------------------------------------------------------------------------
# Helix parameters (scene units: helix radius = 1, axis along +X)
# --------------------------------------------------------------------------
R = 1.0            # helix radius (centre of the backbone tube)
PITCH = 16.0       # length of one full turn (stylised, long pitch)
STEP = PITCH / 12  # distance between base pairs (12 rungs per turn)
PHI0 = math.radians(-76)  # rung 0 chord is vertical (z) at y = R*cos(76deg)
PHASE = math.radians(152)   # angular offset of strand B (minor/major groove)
X_MIN, X_MAX = -26.0, 26.0
TUBE_R = 0.115     # backbone radius
N_AROUND = 40      # tube resolution

rng = random.Random(7)


# --------------------------------------------------------------------------
# Mesh accumulator: every part goes into one mesh with material indices
# --------------------------------------------------------------------------
class MeshBuilder:
    def __init__(self):
        self.verts = []
        self.faces = []
        self.mats = []
        self.uvs = []  # flattened per loop

    def add_grid(self, rings, mat, uv_rows, closed=True):
        """rings: list of rings (each a list of Vector, same length).
        uv_rows: list of u values per ring. v runs 0..1 around."""
        n = len(rings[0])
        base = len(self.verts)
        for ring in rings:
            self.verts.extend(ring)
        cols = n if closed else n - 1
        for i in range(len(rings) - 1):
            for j in range(cols):
                j2 = (j + 1) % n
                a = base + i * n + j
                b = base + i * n + j2
                c = base + (i + 1) * n + j2
                d = base + (i + 1) * n + j
                self.faces.append((a, b, c, d))
                self.mats.append(mat)
                v0 = j / n
                v1 = (j + 1) / n
                u0 = uv_rows[i]
                u1 = uv_rows[i + 1]
                self.uvs.extend([(u0, v0), (u0, v1), (u1, v1), (u1, v0)])

    def add_fan(self, ring, center, mat, flip=False):
        base = len(self.verts)
        self.verts.extend(ring)
        self.verts.append(center)
        c = base + len(ring)
        n = len(ring)
        for j in range(n):
            a = base + j
            b = base + (j + 1) % n
            f = (a, c, b) if flip else (a, b, c)
            self.faces.append(f)
            self.mats.append(mat)
            self.uvs.extend([(0.5, 0.5)] * 3)

    def build(self, name, materials):
        me = bpy.data.meshes.new(name)
        me.from_pydata([tuple(v) for v in self.verts], [], self.faces)
        me.polygons.foreach_set("material_index", self.mats)
        me.polygons.foreach_set("use_smooth", [True] * len(self.faces))
        uv = me.uv_layers.new(name="UVMap")
        flat = [c for uvp in self.uvs for c in uvp]
        uv.data.foreach_set("uv", flat)
        for m in materials:
            me.materials.append(m)
        me.validate()
        me.update()
        ob = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(ob)
        return ob


def frame_from(axis):
    axis = axis.normalized()
    up = Vector((0, 0, 1)) if abs(axis.z) < 0.9 else Vector((1, 0, 0))
    x = axis.cross(up).normalized()
    y = axis.cross(x).normalized()
    return x, y, axis


def lathe(mb, origin, axis, strips, mat_of_strip, n=32, twist=0.0):
    """Surface of revolution. strips: list of (mat, [(z, r), ...]).
    Each strip has its own vertices -> hard edge between strips."""
    x, y, z = frame_from(axis)
    for mat, prof in strips:
        rings = []
        us = []
        acc = 0.0
        for k, (pz, pr) in enumerate(prof):
            if k:
                acc += math.hypot(pz - prof[k - 1][0], pr - prof[k - 1][1])
            us.append(acc)
            ring = []
            for j in range(n):
                a = 2 * math.pi * j / n + twist
                ring.append(origin + z * pz + (x * math.cos(a) + y * math.sin(a)) * max(pr, 1e-4))
            rings.append(ring)
        mb.add_grid(rings, mat, us)


def torus(mb, center, axis, major, minor, mat, n_major=48, n_minor=12):
    x, y, z = frame_from(axis)
    rings = []
    us = []
    for i in range(n_major + 1):
        a = 2 * math.pi * i / n_major
        d = x * math.cos(a) + y * math.sin(a)
        ring = []
        for j in range(n_minor):
            b = 2 * math.pi * j / n_minor
            ring.append(center + d * (major + minor * math.cos(b)) + z * (minor * math.sin(b)))
        rings.append(ring)
        us.append(i / n_major)
    mb.add_grid(rings, mat, us)


# --------------------------------------------------------------------------
# Helix geometry helpers
# --------------------------------------------------------------------------
def strand_angle(x, strand):
    return 2 * math.pi * x / PITCH + PHI0 + (PHASE if strand else 0.0)


def strand_point(x, strand, radius=R):
    a = strand_angle(x, strand)
    return Vector((x, radius * math.cos(a), radius * math.sin(a)))


def strand_tangent(x, strand):
    a = strand_angle(x, strand)
    w = 2 * math.pi / PITCH
    return Vector((1.0, -R * w * math.sin(a), R * w * math.cos(a))).normalized()


def strand_inward(x, strand):
    a = strand_angle(x, strand)
    return Vector((0.0, -math.cos(a), -math.sin(a)))


def backbone_segment(mb, strand, x0, x1, mat, radius=TUBE_R, round_len=0.07):
    """Sweep a tube along the helix between x0 and x1 with domed ends.
    v = 0 faces the helix axis (so circuit patterns sit on the inner side)."""
    length_x = x1 - x0
    # dense sampling with extra rings near the ends for the dome
    ts = []
    dome = [0.0, 0.08, 0.2, 0.36, 0.55, 0.75, 1.0]
    rx = round_len / 1.0  # x-distance approx equal to arc distance * cos
    for d in dome:
        ts.append(x0 + rx * d)
    k = max(8, int(length_x * 26))
    for i in range(1, k):
        ts.append(x0 + rx + (length_x - 2 * rx) * i / k)
    for d in reversed(dome):
        ts.append(x1 - rx * d)
    rings, us = [], []
    acc = 0.0
    prev = None
    for idx, t in enumerate(ts):
        p = strand_point(t, strand)
        if prev is not None:
            acc += (p - prev).length
        prev = p
        tan = strand_tangent(t, strand)
        inw = strand_inward(t, strand)
        inw = (inw - tan * inw.dot(tan)).normalized()
        bi = tan.cross(inw)
        # dome profile
        dist = min(t - x0, x1 - t)
        if dist < rx:
            q = dist / rx
            r = radius * math.sqrt(max(0.0, 1 - (1 - q) ** 2))
            r = max(r, radius * 0.02)
        else:
            r = radius
        ring = []
        for j in range(N_AROUND):
            a = 2 * math.pi * j / N_AROUND
            ring.append(p + (inw * math.cos(a) + bi * math.sin(a)) * r)
        rings.append(ring)
        us.append(acc)
    mb.add_grid(rings, mat, us)
    # close the tiny dome tips
    mb.add_fan(rings[0], strand_point(ts[0], strand), mat, flip=True)
    mb.add_fan(rings[-1], strand_point(ts[-1], strand), mat)


# --------------------------------------------------------------------------
# Materials
# --------------------------------------------------------------------------
def principled(name, base, metallic=0.0, rough=0.4, coat=0.0, coat_rough=0.05,
               transmission=0.0, ior=1.45, spec_tint=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*base, 1)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Coat Weight"].default_value = coat
    bsdf.inputs["Coat Roughness"].default_value = coat_rough
    bsdf.inputs["Transmission Weight"].default_value = transmission
    bsdf.inputs["IOR"].default_value = ior
    if spec_tint:
        bsdf.inputs["Specular Tint"].default_value = (*spec_tint, 1)
    return m


PULSE_NODES = ("PulseX", "PulseW", "PulseGain")


def pulse_factor(nt, scale=1.0):
    """Socket = 1 + gain * scale * exp(-((world_x - PulseX) / PulseW)^2).

    The idle loops sweep PulseX along the helix; with PulseGain = 0 (the
    default, used by every transition frame) the factor is exactly 1."""
    N, L = nt.nodes, nt.links

    def value(name, v):
        n = N.get(name) or N.new("ShaderNodeValue")
        n.name = n.label = name
        n.outputs[0].default_value = v
        return n.outputs[0]

    def op(kind, a, b=None, vb=None):
        n = N.new("ShaderNodeMath")
        n.operation = kind
        L.new(a, n.inputs[0])
        if b is not None:
            L.new(b, n.inputs[1])
        elif vb is not None:
            n.inputs[1].default_value = vb
        return n.outputs[0]

    geo = N.new("ShaderNodeNewGeometry")
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(geo.outputs["Position"], sep.inputs[0])
    d = op("DIVIDE", op("SUBTRACT", sep.outputs["X"], value("PulseX", -1000.0)), value("PulseW", 2.0))
    e = op("EXPONENT", op("MULTIPLY", op("MULTIPLY", d, d), vb=-1.0))
    g = op("MULTIPLY", value("PulseGain", 0.0), vb=scale)
    return op("ADD", op("MULTIPLY", e, g), vb=1.0)


def emission(name, color, strength):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (*color, 1)
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = "MULTIPLY"
    mul.inputs[0].default_value = strength
    nt.links.new(pulse_factor(nt), mul.inputs[1])
    nt.links.new(mul.outputs[0], em.inputs["Strength"])
    nt.links.new(em.outputs[0], out.inputs[0])
    return m


def set_pulse(x, width, gain):
    for m in bpy.data.materials:
        if not m.node_tree:
            continue
        for name, v in zip(PULSE_NODES, (x, width, gain)):
            n = m.node_tree.nodes.get(name)
            if n:
                n.outputs[0].default_value = v


def backbone_material(name, circuit):
    """Dark navy metal with fine machined grooves; optional cyan circuitry on
    the inner face (UV v≈0) made of dashed data lanes plus a perforated band."""
    m = principled(name, (0.040, 0.055, 0.10), metallic=0.8, rough=0.4, coat=0.7, coat_rough=0.06)
    nt = m.node_tree
    N = nt.nodes
    L = nt.links
    bsdf = N.get("Principled BSDF")

    uv = N.new("ShaderNodeUVMap")
    sep = N.new("ShaderNodeSeparateXYZ")
    L.new(uv.outputs["UV"], sep.inputs[0])

    def math_node(op, a=None, b=None, va=None, vb=None, clamp=False):
        n = N.new("ShaderNodeMath")
        n.operation = op
        n.use_clamp = clamp
        if a is not None:
            L.new(a, n.inputs[0])
        elif va is not None:
            n.inputs[0].default_value = va
        if b is not None:
            L.new(b, n.inputs[1])
        elif vb is not None:
            n.inputs[1].default_value = vb
        return n.outputs[0]

    u = sep.outputs["X"]   # arc length along the tube (scene units)
    v = sep.outputs["Y"]   # 0..1 around, 0 = inner side

    # fine circumferential machining grooves -> bump
    groove = math_node("SINE", math_node("MULTIPLY", u, vb=2 * math.pi * 55))
    groove = math_node("MULTIPLY", groove, vb=0.5)
    bump = N.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.04
    bump.inputs["Distance"].default_value = 0.002
    L.new(groove, bump.inputs["Height"])
    L.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    if not circuit:
        return m

    # distance from the inner line, wrapped (v in 0..1)
    vc = math_node("SUBTRACT", math_node("FRACT", math_node("ADD", v, vb=0.5)), vb=0.5)
    vabs = math_node("ABSOLUTE", vc)
    # data lanes: 7 thin lanes around the inner side
    lanes = math_node("MULTIPLY", vc, vb=46.0)
    lane_id = math_node("FLOOR", lanes)
    lane_f = math_node("FRACT", lanes)
    lane_mask = math_node("MULTIPLY",
                          math_node("GREATER_THAN", lane_f, vb=0.32),
                          math_node("LESS_THAN", lane_f, vb=0.68))
    # dashes along u: per-lane random on/off using white noise
    dash_u = math_node("MULTIPLY", u, vb=9.0)
    dash_cell = math_node("FLOOR", math_node("ADD", dash_u, math_node("MULTIPLY", lane_id, vb=0.37)))
    comb = N.new("ShaderNodeCombineXYZ")
    L.new(dash_cell, comb.inputs[0])
    L.new(lane_id, comb.inputs[1])
    wn = N.new("ShaderNodeTexWhiteNoise")
    wn.noise_dimensions = "3D"
    L.new(comb.outputs[0], wn.inputs["Vector"])
    on = math_node("GREATER_THAN", wn.outputs["Value"], vb=0.45)
    dash_f = math_node("FRACT", math_node("ADD", dash_u, math_node("MULTIPLY", lane_id, vb=0.37)))
    gap = math_node("LESS_THAN", dash_f, vb=0.82)
    dash = math_node("MULTIPLY", math_node("MULTIPLY", on, gap), lane_mask)
    inner = math_node("LESS_THAN", vabs, vb=0.085)
    lanes_on = math_node("MULTIPLY", dash, inner)

    # perforated band next to the lanes: grid of small dots (bump only)
    band = math_node("MULTIPLY",
                     math_node("GREATER_THAN", vabs, vb=0.10),
                     math_node("LESS_THAN", vabs, vb=0.21))
    du = math_node("SUBTRACT", math_node("FRACT", math_node("MULTIPLY", u, vb=60.0)), vb=0.5)
    dv = math_node("SUBTRACT", math_node("FRACT", math_node("MULTIPLY", v, vb=110.0)), vb=0.5)
    dd = math_node("ADD", math_node("MULTIPLY", du, du), math_node("MULTIPLY", dv, dv))
    dots = math_node("MULTIPLY", math_node("LESS_THAN", dd, vb=0.09), band)
    h2 = math_node("SUBTRACT", groove, math_node("MULTIPLY", dots, vb=1.5))
    L.new(h2, bump.inputs["Height"], verify_limits=False)

    # emission
    col = N.new("ShaderNodeMix")
    col.data_type = "RGBA"
    col.inputs[6].default_value = (0.02, 0.25, 1.0, 1)
    col.inputs[7].default_value = (0.10, 0.60, 1.0, 1)
    wn2 = N.new("ShaderNodeTexWhiteNoise")
    wn2.noise_dimensions = "3D"
    L.new(comb.outputs[0], wn2.inputs["Vector"])
    L.new(wn2.outputs["Value"], col.inputs[0])
    L.new(col.outputs[2], bsdf.inputs["Emission Color"])
    L.new(math_node("MULTIPLY", math_node("MULTIPLY", lanes_on, vb=5.0), pulse_factor(nt, 1.5)),
           bsdf.inputs["Emission Strength"])
    # lanes are recessed glass strips: darker, smoother base
    rough = math_node("ADD", math_node("MULTIPLY", lanes_on, vb=-0.3), vb=0.4)
    L.new(rough, bsdf.inputs["Roughness"])
    return m


# --------------------------------------------------------------------------
# Build the helix
# --------------------------------------------------------------------------
def build_dna():
    mats = {
        "bb": backbone_material("Backbone", False),
        "bb_c": backbone_material("BackboneCircuit", True),
        "metal": principled("DarkMetal", (0.045, 0.055, 0.075), metallic=0.92, rough=0.24, coat=0.5),
        "chrome": principled("Chrome", (0.22, 0.25, 0.30), metallic=1.0, rough=0.18),
        "glass": principled("Glass", (0.55, 0.65, 0.78), metallic=0.0, rough=0.06, transmission=1.0, ior=1.45),
        "orange": emission("GlowOrange", (1.0, 0.36, 0.035), 5.0),
        "core": emission("GlowCore", (1.0, 0.50, 0.11), 4.5),
        "blue": emission("GlowBlue", (0.08, 0.45, 1.0), 6.0),
        "tube": principled("RungTube", (0.05, 0.06, 0.08), metallic=0.85, rough=0.2, coat=0.8, coat_rough=0.03),
    }
    order = list(mats.keys())
    M = {k: i for i, k in enumerate(order)}
    mb = MeshBuilder()

    xs = []
    x = math.ceil(X_MIN / STEP) * STEP
    while x <= X_MAX + 1e-6:
        xs.append(round(x, 4))
        x += STEP

    hub_half = 0.10
    seg_gap = 0.012
    for strand in (0, 1):
        # backbone segments between hubs; some segments span two steps
        i = 0
        while i < len(xs) - 1:
            span = 2 if rng.random() < 0.25 and i < len(xs) - 2 else 1
            x0 = xs[i] + hub_half + seg_gap
            x1 = xs[i + span] - hub_half - seg_gap
            mat = M["bb_c"] if rng.random() < 0.38 else M["bb"]
            if strand == 0 and -4.5 < xs[i] < 1.0:
                mat = M["bb_c"]  # circuitry close to the S2/S3 camera
            if span == 2:
                # hide the skipped hub inside a long segment
                pass
            backbone_segment(mb, strand, x0, x1, mat)
            i += span

        for xi in xs:
            p = strand_point(xi, strand)
            tan = strand_tangent(xi, strand)
            # hub collar around the backbone
            lathe(mb, p, tan, [
                (M["metal"], [(-hub_half, TUBE_R * 0.92), (-hub_half, TUBE_R * 1.10)]),
                (M["metal"], [(-hub_half, TUBE_R * 1.10), (-hub_half + 0.012, TUBE_R * 1.16), (hub_half - 0.012, TUBE_R * 1.16), (hub_half, TUBE_R * 1.10)]),
                (M["metal"], [(hub_half, TUBE_R * 1.10), (hub_half, TUBE_R * 0.92)]),
            ], None, n=N_AROUND)
            # thin glowing bands at the collar edges (not on every hub)
            if rng.random() < 0.55:
                torus(mb, p + tan * (hub_half + 0.004), tan, TUBE_R * 1.04, 0.0075, M["orange"], n_major=48, n_minor=8)
            if rng.random() < 0.3:
                torus(mb, p - tan * (hub_half + 0.004), tan, TUBE_R * 1.04, 0.0075, M["orange"], n_major=48, n_minor=8)

    # rungs
    for idx, xi in enumerate(xs):
        a = strand_point(xi, 0)
        b = strand_point(xi, 1)
        chord = b - a
        L_ = chord.length
        d = chord.normalized()
        half = L_ / 2
        for side, (o, dirv) in enumerate(((a, d), (b, -d))):
            f = lambda t: t * half  # noqa: E731  (fraction of half-length)
            parts = [
                # T-stub out of the hub
                (M["metal"], [(0.0, 0.066), (f(0.30), 0.066)]),
                (M["metal"], [(f(0.30), 0.066), (f(0.30), 0.074)]),
                # collar
                (M["metal"], [(f(0.30), 0.074), (f(0.31), 0.078), (f(0.40), 0.078), (f(0.41), 0.074)]),
                (M["metal"], [(f(0.41), 0.074), (f(0.41), 0.046)]),
                # dark glossy tube
                (M["tube"], [(f(0.41), 0.046), (f(0.70), 0.046)]),
                (M["chrome"], [(f(0.70), 0.046), (f(0.705), 0.052), (f(0.74), 0.052), (f(0.74), 0.034)]),
                # dark inner core inside the glass sleeve
                (M["metal"], [(f(0.74), 0.032), (f(0.86), 0.032), (f(0.86), 0.0)]),
                # glass sleeve, closed at the tip
                (M["glass"], [(f(0.74), 0.052), (f(0.74), 0.058), (f(0.90), 0.058), (f(0.90), 0.0)]),
            ]
            lathe(mb, o, dirv, parts, None, n=32)
            # glowing ring inside the sleeve + concentric "lens" rings at the tip
            torus(mb, o + dirv * f(0.79), dirv, 0.043, 0.0035, M["orange"], n_major=36, n_minor=8)
            for rr, mat in ((0.044, "orange"), (0.031, "core"), (0.018, "core")):
                torus(mb, o + dirv * f(0.885), dirv, rr, 0.0032, M[mat], n_major=36, n_minor=8)
            lathe(mb, o, dirv, [(M["core"], [(f(0.884), 0.0), (f(0.884), 0.007), (f(0.888), 0.007), (f(0.888), 0.0)])], None, n=12)
            # collar ring + outer tip ring
            torus(mb, o + dirv * f(0.41), dirv, 0.064, 0.006, M["orange"], n_major=36, n_minor=8)
            torus(mb, o + dirv * f(0.902), dirv, 0.057, 0.0055, M["orange"], n_major=40, n_minor=8)
            if side == 0:
                # floating rings hovering in the gap
                torus(mb, o + dirv * f(0.952), dirv, 0.062, 0.0065, M["core"], n_major=40, n_minor=8)
                torus(mb, o + dirv * f(0.968), dirv, 0.050, 0.0035, M["orange"], n_major=40, n_minor=8)
            if idx % 3 == side:
                # mid-tube glowing band
                torus(mb, o + dirv * f(0.56), dirv, 0.049, 0.0045, M["orange"], n_major=36, n_minor=8)

    ob = mb.build("DNA", [mats[k] for k in order])
    return ob


# --------------------------------------------------------------------------
# World, lights, render settings
# --------------------------------------------------------------------------
def setup_world():
    w = bpy.data.worlds.new("World")
    bpy.context.scene.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    bg.inputs["Color"].default_value = (0.006, 0.016, 0.04, 1)
    bg.inputs["Strength"].default_value = 1.0


def area_light(name, loc, target, color, energy, size):
    ld = bpy.data.lights.new(name, "AREA")
    ld.shape = "DISK"
    ld.size = size
    ld.color = color
    ld.energy = energy
    ob = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    direction = Vector(target) - Vector(loc)
    ob.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return ob


def setup_lights():
    # cool top light -> blue-grey sheen on the upper edges of the tubes
    area_light("Top", (0, -2, 9), (0, 0, 0), (0.42, 0.55, 1.0), 1500, 14)
    # strong blue rim from behind
    area_light("Rim", (4, 12, 3), (0, 0, 0), (0.2, 0.45, 1.0), 1800, 10)
    # faint warm kicker from below (reflected glow)
    area_light("Warm", (-6, -6, -7), (0, 0, 0), (1.0, 0.45, 0.15), 250, 8)
    # soft front fill so the dark metal isn't pure black
    area_light("Fill", (-4, -14, 2), (0, 0, 0), (0.4, 0.55, 0.9), 250, 12)


def setup_render(res, samples, motion_blur):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    cy = sc.cycles
    cy.device = "CPU"
    cy.samples = samples
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.015
    cy.use_denoising = True
    cy.denoiser = "OPENIMAGEDENOISE"
    cy.max_bounces = 8
    cy.glossy_bounces = 4
    cy.transmission_bounces = 8
    cy.diffuse_bounces = 2
    cy.sample_clamp_indirect = 6.0
    cy.blur_glossy = 0.8
    cy.caustics_reflective = False
    cy.caustics_refractive = False
    w, h = res
    sc.render.resolution_x = w
    sc.render.resolution_y = h
    sc.render.resolution_percentage = 100
    sc.render.film_transparent = True
    sc.render.use_motion_blur = motion_blur
    sc.render.motion_blur_shutter = 0.5
    sc.render.image_settings.file_format = "OPEN_EXR"
    sc.render.image_settings.color_depth = "16"
    sc.render.image_settings.exr_codec = "ZIP"
    sc.render.image_settings.color_mode = "RGBA"
    sc.view_settings.view_transform = "Standard"
    sc.render.fps = 30
    sc.render.threads_mode = "AUTO"
    sc.render.use_persistent_data = True


# --------------------------------------------------------------------------
# Camera
# --------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from camera_path import FRAME_COUNT, IDLE_FRAMES, IDLE_STATES, camera_state, idle_state  # noqa: E402


def setup_camera():
    cd = bpy.data.cameras.new("Cam")
    cam = bpy.data.objects.new("Cam", cd)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    cd.sensor_width = 36
    cd.dof.use_dof = True
    cd.clip_start = 0.01
    cd.clip_end = 200
    return cam


def key_camera(cam, frames):
    sc = bpy.context.scene
    sc.frame_start = 0
    sc.frame_end = FRAME_COUNT - 1
    for f in frames:
        st = camera_state(f)
        loc = Vector(st["loc"])
        tgt = Vector(st["target"])
        fwd = (tgt - loc).normalized()
        q = fwd.to_track_quat("-Z", "Z")
        roll = Matrix.Rotation(math.radians(st["roll"]), 4, "Z")
        mat = Matrix.Translation(loc) @ q.to_matrix().to_4x4() @ roll
        cam.matrix_world = mat
        cam.keyframe_insert("location", frame=f)
        cam.rotation_mode = "XYZ"
        cam.keyframe_insert("rotation_euler", frame=f)
        cam.data.lens = st["lens"]
        cam.data.keyframe_insert("lens", frame=f)
        cam.data.shift_x, cam.data.shift_y = st["shift"]
        cam.data.keyframe_insert("shift_x", frame=f)
        cam.data.keyframe_insert("shift_y", frame=f)
        cam.data.dof.focus_distance = st["focus"]
        cam.data.dof.keyframe_insert("focus_distance", frame=f)
        cam.data.dof.aperture_fstop = st["fstop"]
        cam.data.dof.keyframe_insert("aperture_fstop", frame=f)
    # make interpolation linear (we key every frame)
    for ob in (cam, cam.data):
        ad = ob.animation_data
        if ad and ad.action:
            for layer in getattr(ad.action, "layers", []):
                for strip in layer.strips:
                    for bag in strip.channelbags:
                        for fc in bag.fcurves:
                            for kp in fc.keyframe_points:
                                kp.interpolation = "LINEAR"
            for fc in getattr(ad.action, "fcurves", []) or []:
                for kp in fc.keyframe_points:
                    kp.interpolation = "LINEAR"
    # unwrap euler discontinuities
    return cam


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="renders/frames")
    ap.add_argument("--res", default="1920x1080")
    ap.add_argument("--samples", type=int, default=96)
    ap.add_argument("--frames", default="all", help="'all', 'a-b', or comma list")
    ap.add_argument("--no-mblur", action="store_true")
    ap.add_argument("--save-blend", default="")
    ap.add_argument("--idle", default="", help="render idle loops instead: 'all' or e.g. 'hero,s3'")
    args = ap.parse_args(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])

    bpy.ops.wm.read_factory_settings(use_empty=True)
    w, h = (int(v) for v in args.res.split("x"))
    setup_render((w, h), args.samples, not args.no_mblur)
    setup_world()
    setup_lights()
    build_dna()
    cam = setup_camera()
    key_camera(cam, range(FRAME_COUNT))

    if args.save_blend:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(args.save_blend))

    if args.idle:
        render_idle(cam, args)
        return

    if args.frames == "all":
        frames = list(range(FRAME_COUNT))
    elif "-" in args.frames:
        a, b = (int(v) for v in args.frames.split("-"))
        frames = list(range(a, b + 1))
    else:
        frames = [int(v) for v in args.frames.split(",")]

    os.makedirs(args.out, exist_ok=True)
    sc = bpy.context.scene
    for f in frames:
        path = os.path.join(os.path.abspath(args.out), f"f_{f:04d}.exr")
        if os.path.exists(path):
            continue
        sc.frame_set(f)
        sc.render.filepath = path
        bpy.ops.render.render(write_still=True)
        print(f"rendered {f}", flush=True)


def place_camera(cam, st):
    loc = Vector(st["loc"])
    q = (Vector(st["target"]) - loc).normalized().to_track_quat("-Z", "Z")
    cam.animation_data_clear()
    cam.data.animation_data_clear()
    cam.matrix_world = Matrix.Translation(loc) @ q.to_matrix().to_4x4() @ Matrix.Rotation(math.radians(st["roll"]), 4, "Z")
    cam.data.lens = st["lens"]
    cam.data.shift_x, cam.data.shift_y = st.get("shift", (0, 0))
    cam.data.dof.focus_distance = st["focus"]
    cam.data.dof.aperture_fstop = st["fstop"]


def render_idle(cam, args):
    """Seamless idle loops: <out>/idle_<state>/f_0000.exr ... (IDLE_FRAMES each)."""
    sc = bpy.context.scene
    sc.render.use_motion_blur = False  # the drift is far too slow to need it
    states = IDLE_STATES if args.idle == "all" else args.idle.split(",")
    for name in states:
        out = os.path.join(os.path.abspath(args.out), f"idle_{name}")
        os.makedirs(out, exist_ok=True)
        for i in range(IDLE_FRAMES):
            path = os.path.join(out, f"f_{i:04d}.exr")
            if os.path.exists(path):
                continue
            st = idle_state(name, i / IDLE_FRAMES)
            place_camera(cam, st)
            set_pulse(st["pulse_x"], st["pulse_w"], st["pulse_gain"])
            sc.render.filepath = path
            bpy.ops.render.render(write_still=True)
            print(f"rendered idle {name} {i}", flush=True)


if __name__ == "__main__":
    main()
