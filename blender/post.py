"""
Post-process linear RGBA EXR renders into final sRGB PNG frames:
  - composite over the navy screen-space background gradient
  - multi-scale bloom from the HDR highlights (glowing rings / circuitry)
  - filmic tone mapping, vignette, light dithering grain

    python blender/post.py renders/frames renders/post
"""

import os
import sys

import cv2
import numpy as np
import OpenEXR


def srgb_to_linear(c):
    c = np.asarray(c, dtype=np.float32) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055)


_bg_cache = {}


def background(h, w):
    key = (h, w)
    if key in _bg_cache:
        return _bg_cache[key]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    nx = xx / w
    ny = yy / h
    # soft lighter navy pool slightly below centre, darker corners
    d = np.sqrt(((nx - 0.42) / 0.75) ** 2 + ((ny - 0.62) / 0.8) ** 2)
    t = np.clip(d, 0, 1) ** 1.3
    centre = srgb_to_linear([8, 27, 54])
    edge = srgb_to_linear([2, 12, 28])
    bg = centre[None, None, :] * (1 - t[..., None]) + edge[None, None, :] * t[..., None]
    # cool haze at top-left
    d2 = np.sqrt(((nx - 0.15) / 0.5) ** 2 + ((ny - 0.05) / 0.45) ** 2)
    bg += srgb_to_linear([4, 16, 36])[None, None, :] * np.clip(1 - d2, 0, 1)[..., None] ** 2 * 0.6
    _bg_cache[key] = bg.astype(np.float32)
    return _bg_cache[key]


def bloom(img, h):
    lum = img.max(axis=2)
    # soft knee threshold
    knee = np.clip((lum - 0.8) / 3.0, 0, 1) ** 2
    bright = img * knee[..., None]
    out = np.zeros_like(img)
    scale = h / 1080.0
    for sigma, wgt in ((3, 0.22), (9, 0.18), (24, 0.12), (60, 0.08), (140, 0.05)):
        s = sigma * scale
        small = bright
        f = 1
        # blur on downsampled copies for the wide radii (fast)
        while s / f > 12 and min(small.shape[:2]) > 64:
            small = cv2.resize(small, (small.shape[1] // 2, small.shape[0] // 2), interpolation=cv2.INTER_AREA)
            f *= 2
        b = cv2.GaussianBlur(small, (0, 0), s / f)
        if f > 1:
            b = cv2.resize(b, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR)
        out += b * wgt
    return out


def aces(x):
    a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
    return np.clip((x * (a * x + b)) / (x * (c * x + d) + e), 0, 1)


def process(src, dst, exposure=1.0, seed=0):
    with OpenEXR.File(src) as f:
        im = f.channels()["RGBA"].pixels.astype(np.float32)
    rgb = np.ascontiguousarray(im[..., :3])
    alpha = im[..., 3]
    h, w = alpha.shape
    bg = background(h, w)
    comp = rgb + bg * (1 - np.clip(alpha, 0, 1))[..., None]
    comp = comp + bloom(comp, h)
    # vignette
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    v = 1 - 0.35 * (((xx / w - 0.5) / 0.7) ** 2 + ((yy / h - 0.5) / 0.7) ** 2)
    comp *= np.clip(v, 0.55, 1)[..., None]
    # tone map: keep the darks linear-ish, roll off highlights
    mapped = aces(comp * exposure)
    # aces lifts saturation of glows nicely but crushes darks -> blend in
    lin_dark = comp * exposure
    k = np.clip(lin_dark / 0.08, 0, 1)
    mapped = lin_dark * (1 - k) + mapped * k
    out = linear_to_srgb(mapped)
    rng = np.random.default_rng(seed)
    out = out * 255 + rng.uniform(-0.6, 0.6, size=out.shape)
    out = np.clip(out + 0.5, 0, 255).astype(np.uint8)
    cv2.imwrite(dst, out[..., ::-1])


def main():
    src_dir, dst_dir = sys.argv[1], sys.argv[2]
    os.makedirs(dst_dir, exist_ok=True)
    names = sorted(n for n in os.listdir(src_dir) if n.endswith(".exr"))
    for i, n in enumerate(names):
        dst = os.path.join(dst_dir, n.replace(".exr", ".png"))
        src = os.path.join(src_dir, n)
        if os.path.exists(dst) and os.path.getmtime(dst) > os.path.getmtime(src):
            continue
        process(src, dst, seed=i)
    print(f"processed {len(names)} frames")


if __name__ == "__main__":
    main()
