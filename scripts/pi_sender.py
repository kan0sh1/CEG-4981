"""
pi_sender.py
USB Scanner, OpenCV Red Ring Detector/Cropper, Cryptographic Staging, and RF Transmitter.
"""

import os
import sys
import time
import glob
import math
import logging
from pathlib import Path
from typing import List, Tuple, Optional

import cv2
import numpy as np

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Pipeline Configuration
USB_MOUNT_DIR = "/media/usb"
STAGING_CROP_DIR = "./staged_crops"
IMG_EXTENSIONS = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tif", "*.tiff", "*.webp")


# =====================================================================
# 1. RED RING DETECTION & CROPPING UTILITIES (From red_ring.py)
# =====================================================================

def circularity(area: float, perimeter: float) -> float:
    """Calculates contour circularity metric (4 * pi * Area / Perimeter^2)."""
    if perimeter <= 1e-9:
        return 0.0
    return float(4.0 * math.pi * area / (perimeter * perimeter))


def detect_and_crop_red_ring(
    image_path: str,
    output_dir: str,
    s_min: int = 80,
    v_min: int = 80,
    min_outer_area: float = 800.0,
    min_inner_area: float = 200.0,
    circ_outer: float = 0.75,
    circ_inner: float = 0.70,
    center_tol_ratio: float = 0.12,
    outer_scale: float = 0.89
) -> Optional[str]:
    """
    Reads an image from disk, detects a red ring using HSV masking + contour hierarchy,
    crops the ring feature with anti-aliased circular blending, saves lossless PNG to
    output_dir, and returns the path to the cropped file (or None if no match).
    """
    bgr = cv2.imread(image_path)
    if bgr is None:
        return None

    # Step A: Dual-range HSV Red Masking
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    lower1 = np.array([0, s_min, v_min], dtype=np.uint8)
    upper1 = np.array([10, 255, 255], dtype=np.uint8)
    lower2 = np.array([170, s_min, v_min], dtype=np.uint8)
    upper2 = np.array([180, 255, 255], dtype=np.uint8)

    mask1 = cv2.inRange(hsv, lower1, upper1)
    mask2 = cv2.inRange(hsv, lower2, upper2)
    mask = cv2.bitwise_or(mask1, mask2)

    # Step B: Morphological Cleaning (Open removes noise, Close connects ring gaps)
    ker_o = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    ker_c = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, ker_o, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, ker_c, iterations=2)

    # Step C: Contour Hierarchy Tree Evaluation
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None or len(contours) == 0:
        return None

    hierarchy = hierarchy[0]  # Shape: (N, 4) -> [next, prev, child, parent]
    best_ring = None

    for i, cnt_outer in enumerate(contours):
        child_idx = int(hierarchy[i][2])
        if child_idx < 0:
            continue  # Must have an inner child (hole) to form a ring

        area_o = float(cv2.contourArea(cnt_outer))
        if area_o < min_outer_area:
            continue

        per_o = float(cv2.arcLength(cnt_outer, True))
        c_outer = circularity(area_o, per_o)
        if c_outer < circ_outer:
            continue

        cnt_inner = contours[child_idx]
        area_i = float(cv2.contourArea(cnt_inner))
        if area_i < min_inner_area:
            continue

        per_i = float(cv2.arcLength(cnt_inner, True))
        c_inner = circularity(area_i, per_i)
        if c_inner < circ_inner:
            continue

        (cx_o, cy_o), r_o = cv2.minEnclosingCircle(cnt_outer)
        (cx_i, cy_i), r_i = cv2.minEnclosingCircle(cnt_inner)

        if r_i <= 1 or r_o <= 1 or r_i >= r_o:
            continue

        # Centers must align within threshold
        dist = math.hypot(cx_o - cx_i, cy_o - cy_i)
        if dist > (center_tol_ratio * r_o):
            continue

        # Score calculation matching red_ring.py
        score = (2.0 * c_outer + 2.0 * c_inner) + 0.002 * area_o + 0.001 * area_i
        if best_ring is None or score > best_ring["score"]:
            best_ring = {
                "center_o": (cx_o, cy_o),
                "center_i": (cx_i, cy_i),
                "r_outer": r_o,
                "score": score
            }

    if best_ring is None:
        return None

    # Step D: Crop including ring boundary
    h, w = bgr.shape[:2]
    cx, cy = best_ring["center_o"]
    r = max(1.0, best_ring["r_outer"] * outer_scale)

    x1 = int(round(cx - r))
    y1 = int(round(cy - r))
    x2 = int(round(cx + r))
    y2 = int(round(cy + r))

    x1c, y1c = max(0, x1), max(0, y1)
    x2c, y2c = min(w, x2), min(h, y2)

    crop = bgr[y1c:y2c, x1c:x2c].copy()
    if crop.size == 0:
        return None

    # Step E: 4x Anti-aliased Circular Alpha Masking
    ch, cw = crop.shape[:2]
    ss = 4
    mask_hi = np.zeros((ch * ss, cw * ss), dtype=np.uint8)
    ccx = int(round((cx - x1c) * ss))
    ccy = int(round((cy - y1c) * ss))
    rr = int(round(min(r, min(cw, ch) / 2.0) * ss))
    cv2.circle(mask_hi, (ccx, ccy), rr, 255, thickness=-1, lineType=cv2.LINE_AA)
    
    crop_mask = cv2.resize(mask_hi, (cw, ch), interpolation=cv2.INTER_AREA)
    mask_f = (crop_mask.astype(np.float32) / 255.0)[:, :, None]
    crop = (crop.astype(np.float32) * mask_f).astype(np.uint8)

    # Step F: Stage Lossless Crop PNG
    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    out_path = os.path.join(output_dir, f"crop_{base_name}.png")
    
    cv2.imwrite(out_path, crop, [int(cv2.IMWRITE_PNG_COMPRESSION), 1])
    logging.info(f"[VISION MATCH] Red ring detected (score={best_ring['score']:.2f}) -> Staged: {out_path}")
    return out_path


# =====================================================================
# 2. USB SCANNER INTERFACE
# =====================================================================

def scan_usb_for_plans(usb_dir: str) -> List[str]:
    """
    Scans USB directory for raw images, runs embedded red ring vision detection,
    crops matched targets, and returns staged file paths for crypto/RF pipeline.
    """
    logging.info(f"[USB] Scanning mount path: {usb_dir}...")
    if not os.path.exists(usb_dir):
        logging.warning(f"[USB] Mount directory {usb_dir} not accessible.")
        return []

    all_files = []
    for ext in IMG_EXTENSIONS:
        all_files.extend(glob.glob(os.path.join(usb_dir, "**", ext), recursive=True))

    logging.info(f"[VISION] Processing {len(all_files)} raw candidate image(s)...")
    staged_crops = []

    for file_path in all_files:
        cropped_path = detect_and_crop_red_ring(file_path, STAGING_CROP_DIR)
        if cropped_path:
            staged_crops.append(cropped_path)
        else:
            logging.debug(f"[VISION SKIP] No target ring feature in: {os.path.basename(file_path)}")

    staged_crops.sort()
    logging.info(f"[USB] Staged {len(staged_crops)} cropped plan(s) for exfiltration.")
    return staged_crops


# =====================================================================
# 3. TRANSMISSION PIPELINE STUBS
# =====================================================================

def prepare_signed_file(file_path: str) -> dict:
    """Computes file hash, Ed25519 signature, and encrypts into transport payload."""
    logging.info(f"[CRYPTO] Signing and encrypting target: {os.path.basename(file_path)}")
    return {"path": file_path, "status": "READY"}


def process_file_batch(staged_files: List[str]):
    """Iterates through prepared target files and transmits over RF interface."""
    for file_path in staged_files:
        payload = prepare_signed_file(file_path)
        logging.info(f"[RF] Transmitting payload for {os.path.basename(payload['path'])}...")
        time.sleep(0.5)  # Simulate packet chunk transmission


# =====================================================================
# 4. ENTRY POINT
# =====================================================================

def main():
    logging.info("==========================================")
    logging.info("Starting Pi Sender Daemon (Red Ring Mode)")
    logging.info("==========================================")

    target_crops = scan_usb_for_plans(USB_MOUNT_DIR)
    if not target_crops:
        logging.info("[SYSTEM] No valid target red ring plans found on USB drive. Exiting.")
        return

    process_file_batch(target_crops)
    logging.info("[SYSTEM] Execution batch complete.")


if __name__ == "__main__":
    main()