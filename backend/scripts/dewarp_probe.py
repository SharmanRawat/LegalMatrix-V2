"""Offline probe: does cylindrical dewarp (unroll a curved bottle face flat)
help the CPU OCR read what run24 failed on? Fit the curve from CACHED token
box geometry (no extra OCR to find it), remap the crop flat, re-OCR ONLY the
reprojected region, then compare token yield against the plain-photo draw.

Frozen-cache honest: never calls the audit's merge, never touches the pipe
cache, never re-draws anything outside the two probe crops. Report-only."""
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

CACHE = "/tmp/pipeline_audit_pipe_cache.json"
IMAGES = "/home/sharman_rawat/LegalMatrix-V2/new_images"


def cached_tokens(path):
    key = None
    full = str(Path(IMAGES) / path)
    for k in json.load(open(CACHE)):
        if k.split("|")[1] == full:
            key = k
            break
    if not key:
        return None, []
    return key, json.load(open(CACHE))[key].get("tokens", [])


def unroll_fit(tokens, shape):
    """Fit the label's curved baseline from token anchors: tokens' vertical
    centres should sit on a near-parabola across the image width (curved can).
    Return (y_fit_for_x, x_overlap) so we can remap."""
    pts = []
    for t in tokens:
        box = t.get("box")
        if not box or box[2] - box[0] < 20:  # too-small OCR noise, not stat
            continue
        x = (box[0] + box[2]) / 2
        y = (box[1] + box[3]) / 2
        w = box[2] - box[0]
        pts.append((x, y, w))
    if len(pts) < 8:
        return None
    xs = np.array([p[0] for p in pts], dtype=np.float64)
    ys = np.array([p[1] for p in pts], dtype=np.float64)
    # Wide tokens (statutory lines) dominate; quadratic y(x) captures the arc.
    A = np.polynomial.polynomial.polyfit(xs, ys, 2)
    return A


def dewarp(path, out_path):
    key, toks = cached_tokens(path)
    img = cv2.imread(str(Path(IMAGES) / path))
    if img is None:
        return None, f"no image: {path}"
    fit = unroll_fit(toks, img.shape)
    if fit is None:
        return None, f"too few anchors ({path}) — cannot fit curve"
    h, w = img.shape[:2]
    xs = np.arange(w, dtype=np.float32)
    curve = np.polynomial.polynomial.polyval(xs, fit)  # y(x) arc
    # Straighten: shift each column so its arc returns to a common baseline,
    # clipping columns where the arc takes us off the valid glyph area.
    y_max = h - 1
    shift = (curve - np.nanmedian(curve)).astype(np.float32)
    nudge = np.clip(shift, -0.4 * h, 0.4 * h)
    map_y, map_x = np.meshgrid(np.arange(h, dtype=np.float32), xs, indexing="ij")
    map_y = map_y + nudge[None, :]
    flat = cv2.remap(img, map_x, map_y.astype(np.float32), cv2.INTER_CUBIC,
                     borderMode=cv2.BORDER_REPLICATE)
    cv2.imwrite(out_path, flat)
    return flat, f"unrolled {path}: {len(toks)} anchors, polydeg=2"


def main():
    targets = [
        "product4_front.jpg",  # BRUT round can — statutory block curved
        "product2_back.jpg",   # Parachute round bottle — banned glyph block
        "product5_front.jpg",  # WishCare — curved tube
        "product1_front.jpg",  # flat box (control: should NOT move)
        "product3_front.jpg",  # DAVIDOFF can (curved too)
    ]
    for t in targets:
        out = "/tmp/dewarp_" + t.replace(".jpg", ".png")
        _, msg = dewarp(t, out)
        print(msg)
    print("-> rendered flat candidates; next: re-OCR them & diff vs cached")


if __name__ == "__main__":
    main()
