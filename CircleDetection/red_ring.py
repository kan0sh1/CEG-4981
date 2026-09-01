"""
Red Ring Detector + Crop Inside Content (Laptop Test Script)
python red_ring_cropper.py --input ./test_images --output ./out --top 10 --debug --min_outer_area 800 --min_inner_area 200
What it does:
- Reads all images from an input folder
- Detects a RED RING (donut) deterministically using HSV mask + contour hierarchy
- Crops the CONTENT INCLUDING the RING ITSELF (outer boundary)
- Saves cropped results + optional debug overlays
- Picks up to top N matches (default 10) by score

Requirements:
  pip install opencv-python numpy

Run examples:
  python red_ring_cropper.py --input ./test_images --output ./out --top 10 --debug
  python red_ring_cropper.py --input ./test_images --output ./out --inner_scale 0.98
"""

import argparse
import math
import os
from pathlib import Path
from typing import List, Tuple, Optional

import cv2
import numpy as np


IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def list_images(folder: Path) -> List[Path]:
    files = []
    for p in sorted(folder.rglob("*")):
        if p.is_file() and p.suffix.lower() in IMG_EXTS:
            files.append(p)
    return files


def circularity(area: float, perimeter: float) -> float:
    if perimeter <= 1e-9:
        return 0.0
    return float(4.0 * math.pi * area / (perimeter * perimeter))


def make_red_mask_hsv(bgr: np.ndarray,
                      s_min: int = 80,
                      v_min: int = 80,
                      h_low_1: int = 0,
                      h_high_1: int = 10,
                      h_low_2: int = 170,
                      h_high_2: int = 180) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

    lower1 = np.array([h_low_1, s_min, v_min], dtype=np.uint8)
    upper1 = np.array([h_high_1, 255, 255], dtype=np.uint8)

    lower2 = np.array([h_low_2, s_min, v_min], dtype=np.uint8)
    upper2 = np.array([h_high_2, 255, 255], dtype=np.uint8)

    mask1 = cv2.inRange(hsv, lower1, upper1)
    mask2 = cv2.inRange(hsv, lower2, upper2)
    mask = cv2.bitwise_or(mask1, mask2)

    return mask


def clean_mask(mask: np.ndarray, k_open: int = 3, k_close: int = 7) -> np.ndarray:
    # Opening removes small specks; closing fills small gaps in the ring.
    if k_open > 0:
        ker_o = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_open, k_open))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, ker_o, iterations=1)
    if k_close > 0:
        ker_c = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_close, k_close))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, ker_c, iterations=2)
    return mask


def contour_center_radius(cnt: np.ndarray) -> Tuple[Tuple[float, float], float]:
    # Use minEnclosingCircle as a robust estimate of circle center/radius
    (cx, cy), r = cv2.minEnclosingCircle(cnt)
    return (float(cx), float(cy)), float(r)


def distance(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return float(math.hypot(a[0] - b[0], a[1] - b[1]))


def detect_best_ring(mask: np.ndarray,
                     min_outer_area: float,
                     min_inner_area: float,
                     circ_thresh_outer: float,
                     circ_thresh_inner: float,
                     center_tol_ratio: float,
                     max_candidates: int = 200) -> Optional[dict]:
    """
    Find best "ring" candidate: outer contour with inner child contour (hole).
    Returns dict with:
      - outer_cnt, inner_cnt
      - center (cx, cy)
      - r_outer, r_inner
      - score
    """

    contours, hierarchy = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None or len(contours) == 0:
        return None

    hierarchy = hierarchy[0]  # shape: (N, 4) => [next, prev, child, parent]
    best = None
    checked = 0

    for i, cnt_outer in enumerate(contours):
        if checked >= max_candidates:
            break
        child_idx = int(hierarchy[i][2])
        if child_idx < 0:
            continue  # not a ring (no hole)

        area_o = float(cv2.contourArea(cnt_outer))
        if area_o < min_outer_area:
            continue

        per_o = float(cv2.arcLength(cnt_outer, True))
        circ_o = circularity(area_o, per_o)
        if circ_o < circ_thresh_outer:
            continue

        # Evaluate the child contour as the "inner hole"
        cnt_inner = contours[child_idx]
        area_i = float(cv2.contourArea(cnt_inner))
        if area_i < min_inner_area:
            continue

        per_i = float(cv2.arcLength(cnt_inner, True))
        circ_i = circularity(area_i, per_i)
        if circ_i < circ_thresh_inner:
            continue

        center_o, r_o = contour_center_radius(cnt_outer)
        center_i, r_i = contour_center_radius(cnt_inner)

        # Ring sanity checks
        if r_i <= 1 or r_o <= 1:
            continue
        if r_i >= r_o:
            continue

        # Centers should be close (inner hole roughly centered in outer ring)
        tol = center_tol_ratio * r_o
        if distance(center_o, center_i) > tol:
            continue

        # Score: prefer roundness + larger ring + clear hole
        # You can tune weights if needed.
        score = (2.0 * circ_o + 2.0 * circ_i) + 0.002 * area_o + 0.001 * area_i

        checked += 1

        if best is None or score > best["score"]:
            best = {
                "outer_cnt": cnt_outer,
                "inner_cnt": cnt_inner,
                "center": center_i,   # use inner center for crop
                "center_o": center_o,
                "r_outer": r_o,
                "r_inner": r_i,
                "circ_o": circ_o,
                "circ_i": circ_i,
                "area_o": area_o,
                "area_i": area_i,
                "score": float(score),
            }

    return best


def crop_including_ring(bgr: np.ndarray,
                        center: Tuple[float, float],
                        r_outer: float,
                        outer_scale: float = 1.05,
                        circular_mask: bool = True) -> np.ndarray:
    """
    Crop a square around the OUTER edge of the ring, so the red ring itself
    is visible in the output (not just the content inside the hole).
    outer_scale > 1.0 adds a small margin outside the ring so it isn't clipped.
    """
    h, w = bgr.shape[:2]
    cx, cy = center
    r = max(1.0, r_outer * outer_scale)

    x1 = int(round(cx - r))
    y1 = int(round(cy - r))
    x2 = int(round(cx + r))
    y2 = int(round(cy + r))

    # Clamp to image bounds
    x1c, y1c = max(0, x1), max(0, y1)
    x2c, y2c = min(w, x2), min(h, y2)

    crop = bgr[y1c:y2c, x1c:x2c].copy()
    if crop.size == 0:
        return crop

    if circular_mask:
        ch, cw = crop.shape[:2]

        # Anti-aliased mask: draw the circle at 4x resolution, then downsample
        # with area interpolation. This gives a smooth, non-jagged edge instead
        # of the hard stair-stepped edge a directly-drawn mask produces.
        ss = 4
        mask_hi = np.zeros((ch * ss, cw * ss), dtype=np.uint8)
        ccx = int(round((cx - x1c) * ss))
        ccy = int(round((cy - y1c) * ss))
        rr = int(round(min(r, min(cw, ch) / 2.0) * ss))
        cv2.circle(mask_hi, (ccx, ccy), rr, 255, thickness=-1, lineType=cv2.LINE_AA)
        mask = cv2.resize(mask_hi, (cw, ch), interpolation=cv2.INTER_AREA)

        # Blend using the soft mask (values 0-255) instead of a hard bitwise AND,
        # so edge pixels fade smoothly into black rather than cutting sharply.
        mask_f = (mask.astype(np.float32) / 255.0)[:, :, None]
        crop = (crop.astype(np.float32) * mask_f).astype(np.uint8)

    return crop


def upscale_crop(crop: np.ndarray, factor: float) -> np.ndarray:
    """Upscale using Lanczos interpolation for the sharpest possible result
    when the source crop resolution is limited."""
    if factor is None or factor <= 1.0 or crop.size == 0:
        return crop
    h, w = crop.shape[:2]
    new_w = max(1, int(round(w * factor)))
    new_h = max(1, int(round(h * factor)))
    return cv2.resize(crop, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)


def draw_debug(bgr: np.ndarray, ring: dict) -> np.ndarray:
    dbg = bgr.copy()
    cx, cy = ring["center"]
    r_o = ring["r_outer"]
    r_i = ring["r_inner"]

    # Draw contours
    cv2.drawContours(dbg, [ring["outer_cnt"]], -1, (0, 255, 0), 2)
    cv2.drawContours(dbg, [ring["inner_cnt"]], -1, (255, 0, 0), 2)

    # Draw circles (estimated)
    cv2.circle(dbg, (int(round(cx)), int(round(cy))), int(round(r_i)), (255, 255, 0), 2)
    cv2.circle(dbg, (int(round(cx)), int(round(cy))), int(round(r_o)), (0, 255, 255), 2)

    label = f"score={ring['score']:.2f} circO={ring['circ_o']:.2f} circI={ring['circ_i']:.2f}"
    cv2.putText(dbg, label, (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
    return dbg


def main():
    # ------------------------------------------------------------------
    # HARDCODED DEFAULTS
    # These match the settings that were tuned and confirmed to work well.
    # Running the script with NO arguments at all uses these values, so
    # it can be launched with a single command/button (or later, a
    # systemd service / cron job / folder-watcher on a Raspberry Pi).
    # Every value can still be overridden via CLI flags if needed.
    # ------------------------------------------------------------------
    DEFAULT_INPUT = "./test_images"
    DEFAULT_OUTPUT = "./out"
    DEFAULT_TOP = 10
    DEFAULT_DEBUG = False
    DEFAULT_MIN_OUTER_AREA = 800.0
    DEFAULT_MIN_INNER_AREA = 200.0
    DEFAULT_OUTER_SCALE = 0.89
    DEFAULT_PNG = True

    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=DEFAULT_INPUT, help="Folder containing test images")
    ap.add_argument("--output", default=DEFAULT_OUTPUT, help="Output folder for cropped results")
    ap.add_argument("--top", type=int, default=DEFAULT_TOP, help="How many best matches to keep")
    ap.add_argument("--debug", action="store_true", default=DEFAULT_DEBUG, help="Save debug overlays + masks")
    ap.add_argument("--no_debug", action="store_true", help="Disable debug overlays even though it's on by default")
    ap.add_argument("--no_circular_mask", action="store_true", help="Do not mask crop to circle")
    ap.add_argument("--outer_scale", type=float, default=DEFAULT_OUTER_SCALE,
                    help="Crop radius scale relative to OUTER ring radius (>1.0 adds margin so ring isn't clipped)")
    ap.add_argument("--inner_scale", type=float, default=0.98,
                    help="(Deprecated, kept for backward compat) Previously used for inner-only crop")
    ap.add_argument("--png", action="store_true", default=DEFAULT_PNG, help="Save crops as lossless PNG instead of JPEG")
    ap.add_argument("--no_png", action="store_true", help="Use JPEG instead of PNG even though PNG is on by default")
    ap.add_argument("--jpeg_quality", type=int, default=100, help="JPEG quality 0-100 (ignored if --png)")
    ap.add_argument("--upscale", type=float, default=1.0,
                    help="Upscale factor applied to final crop using Lanczos interpolation, "
                         "e.g. 2.0 doubles resolution. Use only if source images are low-res.")
    # HSV red tuning
    ap.add_argument("--s_min", type=int, default=80)
    ap.add_argument("--v_min", type=int, default=80)
    # Ring filtering
    ap.add_argument("--min_outer_area", type=float, default=DEFAULT_MIN_OUTER_AREA)
    ap.add_argument("--min_inner_area", type=float, default=DEFAULT_MIN_INNER_AREA)
    ap.add_argument("--circ_outer", type=float, default=0.75)
    ap.add_argument("--circ_inner", type=float, default=0.70)
    ap.add_argument("--center_tol_ratio", type=float, default=0.12, help="allowed center offset as fraction of outer radius")
    args = ap.parse_args()

    # Since --debug and --png now default to True (hardcoded), the only way
    # to turn them off is via the explicit opt-out flags below.
    if args.no_debug:
        args.debug = False
    if args.no_png:
        args.png = False

    in_dir = Path(args.input)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.debug:
        (out_dir / "debug").mkdir(exist_ok=True)
        (out_dir / "mask").mkdir(exist_ok=True)

    images = list_images(in_dir)
    if not images:
        print(f"No images found in: {in_dir}")
        return

    print(f"Found {len(images)} image file(s) in: {in_dir.resolve()}")

    results = []  # (score, path, crop, debug_img, mask)
    no_ring_count = 0
    unreadable_count = 0

    for i, p in enumerate(images, start=1):
        bgr = cv2.imread(str(p))
        if bgr is None:
            print(f"  [{i}/{len(images)}] Skip unreadable: {p.name}")
            unreadable_count += 1
            continue

        mask = make_red_mask_hsv(bgr, s_min=args.s_min, v_min=args.v_min)
        mask = clean_mask(mask, k_open=3, k_close=7)

        ring = detect_best_ring(
            mask=mask,
            min_outer_area=args.min_outer_area,
            min_inner_area=args.min_inner_area,
            circ_thresh_outer=args.circ_outer,
            circ_thresh_inner=args.circ_inner,
            center_tol_ratio=args.center_tol_ratio,
        )

        if ring is None:
            print(f"  [{i}/{len(images)}] No ring detected: {p.name}")
            no_ring_count += 1
            continue

        print(f"  [{i}/{len(images)}] Ring detected: {p.name} (score={ring['score']:.2f})")

        # Use the OUTER center/radius so the crop includes the ring itself.
        crop = crop_including_ring(
            bgr=bgr,
            center=ring.get("center_o", ring["center"]),
            r_outer=ring["r_outer"],
            outer_scale=args.outer_scale,
            circular_mask=(not args.no_circular_mask),
        )
        if crop is None or crop.size == 0:
            continue

        crop = upscale_crop(crop, args.upscale)

        dbg = draw_debug(bgr, ring) if args.debug else None
        results.append((ring["score"], p, crop, dbg, mask))

    print(f"\n--- Processing summary ---")
    print(f"Total image files found:   {len(images)}")
    print(f"Unreadable/corrupt:        {unreadable_count}")
    print(f"No ring detected:          {no_ring_count}")
    print(f"Rings detected:            {len(results)}")

    if not results:
        print("\nNo red rings detected with current thresholds.")
        print("Try adjusting: --s_min, --v_min, --min_outer_area, --circ_outer, --center_tol_ratio")
        return

    # Keep top N by score
    results.sort(key=lambda x: x[0], reverse=True)
    kept = results[: max(1, args.top)]
    print(f"Keeping top {len(kept)} of {len(results)} detected (--top {args.top})\n")
    results = kept

    # Save outputs
    for idx, (score, p, crop, dbg, mask) in enumerate(results, start=1):
        base = p.stem
        ext = ".png" if args.png else ".jpg"
        crop_name = f"{idx:02d}_{base}_crop{ext}"
        crop_path = out_dir / crop_name

        if args.png:
            # PNG is lossless, compression level 0-9 (0 = fastest/largest, no quality loss either way)
            cv2.imwrite(str(crop_path), crop, [int(cv2.IMWRITE_PNG_COMPRESSION), 1])
        else:
            q = max(0, min(100, args.jpeg_quality))
            cv2.imwrite(str(crop_path), crop, [int(cv2.IMWRITE_JPEG_QUALITY), q])

        if args.debug and dbg is not None:
            dbg_path = out_dir / "debug" / f"{idx:02d}_{base}_debug.jpg"
            msk_path = out_dir / "mask" / f"{idx:02d}_{base}_mask.png"
            cv2.imwrite(str(dbg_path), dbg)
            cv2.imwrite(str(msk_path), mask)

        print(f"[{idx:02d}] score={score:.2f}  ->  {crop_path.name}")

    print(f"\nSaved {len(results)} cropped results to: {out_dir.resolve()}")
    if args.debug:
        print(f"Debug overlays: { (out_dir / 'debug').resolve() }")
        print(f"Masks:         { (out_dir / 'mask').resolve() }")


if __name__ == "__main__":
    main()