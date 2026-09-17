"""
scripts/pi_sender.py
Integrates CircleDetection/red_ring.py and ImageSecurity/crypto_transport.py
into an end-to-end processing and transmission pipeline.
"""

import os
import sys
import time
import json
import socket
import hashlib
import logging
from pathlib import Path
from typing import List

import cv2

# =====================================================================
# 1. ENVIRONMENT & IMPORT RESOLUTION
# =====================================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

try:
    from CircleDetection.red_ring import (
        make_red_mask_hsv,
        clean_mask,
        detect_best_ring,
        crop_including_ring
    )
    logging.info("[SETUP] Successfully imported CircleDetection.red_ring")
except ImportError as e:
    logging.error(f"[ERROR] Failed importing red_ring module: {e}")
    sys.exit(1)

try:
    from ImageSecurity import crypto_transport
    logging.info("[SETUP] Successfully imported ImageSecurity.crypto_transport")
except ImportError as e:
    logging.error(f"[ERROR] Failed importing crypto_transport module: {e}")
    sys.exit(1)

INPUT_IMAGES_DIR = PROJECT_ROOT / "CircleDetection" / "test_images"
STAGED_CROPS_DIR = PROJECT_ROOT / "staged_crops"
IMG_EXTENSIONS = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tif", "*.tiff", "*.webp")

RECEIVER_HOST = "127.0.0.1"
RECEIVER_PORT = 65432


# =====================================================================
# 2. VISION PIPELINE INTEGRATION
# =====================================================================

def process_and_crop_image(image_path: Path, output_dir: Path) -> str | None:
    bgr = cv2.imread(str(image_path))
    if bgr is None:
        logging.warning(f"[VISION SKIP] Unreadable image file: {image_path.name}")
        return None

    mask = make_red_mask_hsv(bgr, s_min=80, v_min=80)
    mask = clean_mask(mask, k_open=3, k_close=7)

    ring = detect_best_ring(
        mask=mask,
        min_outer_area=800.0,
        min_inner_area=200.0,
        circ_thresh_outer=0.75,
        circ_thresh_inner=0.70,
        center_tol_ratio=0.12
    )

    if ring is None:
        logging.debug(f"[VISION SKIP] No red ring target found in: {image_path.name}")
        return None

    crop = crop_including_ring(
        bgr=bgr,
        center=ring.get("center_o", ring["center"]),
        r_outer=ring["r_outer"],
        outer_scale=0.89,
        circular_mask=True
    )

    if crop is None or crop.size == 0:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"crop_{image_path.stem}.png"

    cv2.imwrite(str(out_path), crop, [int(cv2.IMWRITE_PNG_COMPRESSION), 1])
    logging.info(
        f"[VISION MATCH] Target detected in {image_path.name} "
        f"(score={ring['score']:.2f}) -> Staged: {out_path.name}"
    )
    return str(out_path)


def scan_and_stage_targets(input_dir: Path) -> List[str]:
    logging.info(f"[PIPELINE] Scanning input path: {input_dir}")
    if not input_dir.exists():
        logging.error(f"[ERROR] Input directory {input_dir} does not exist.")
        return []

    image_files = []
    for ext in IMG_EXTENSIONS:
        image_files.extend(input_dir.glob(ext))

    logging.info(f"[PIPELINE] Found {len(image_files)} source candidate(s)...")
    staged_crops = []

    for img_path in sorted(image_files):
        cropped_file = process_and_crop_image(img_path, STAGED_CROPS_DIR)
        if cropped_file:
            staged_crops.append(cropped_file)

    return staged_crops


# =====================================================================
# 3. SECURITY & TRANSMISSION PIPELINE INTEGRATION
# =====================================================================

def secure_and_transmit_batch(staged_files: List[str]):
    logging.info("\n------------------------------------------")
    logging.info("Initializing Cryptographic Key Infrastructure")
    logging.info("------------------------------------------")

    # Generate keypair and AES key
    if hasattr(crypto_transport, "generate_keypair"):
        private_key, public_key = crypto_transport.generate_keypair()
    else:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

    if hasattr(crypto_transport, "generate_shared_aes_key"):
        aes_key = crypto_transport.generate_shared_aes_key()
    else:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aes_key = AESGCM.generate_key(bit_length=256)

    # Export key materials for offline verification on local receiver
    pub_bytes = public_key.public_bytes_raw()
    
    for file_path in staged_files:
        filename = os.path.basename(file_path)
        logging.info(f"\n[SECURITY] Encrypting & Signing target: {filename}")
        
        with open(file_path, "rb") as f:
            raw_bytes = f.read()

        # Compute source MD5 checksum prior to encryption
        source_md5 = hashlib.md5(raw_bytes).hexdigest()

        # Encrypt & Sign routines
        if hasattr(crypto_transport, "encrypt_and_sign"):
            pkg = crypto_transport.encrypt_and_sign(raw_bytes, aes_key, private_key)
        else:
            signature = private_key.sign(raw_bytes)
            nonce = os.urandom(12)
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            aesgcm = AESGCM(aes_key)
            ciphertext = aesgcm.encrypt(nonce, raw_bytes, None)
            pkg = {"nonce": nonce, "ciphertext": ciphertext, "signature": signature}

        # Hex-encode binary payloads + attach key materials & MD5
        payload_package = {
            "filename": filename,
            "source_md5": source_md5,
            "public_key_hex": pub_bytes.hex(),
            "aes_key_hex": aes_key.hex(),
            "nonce_hex": pkg["nonce"].hex(),
            "signature_hex": pkg["signature"].hex(),
            "ciphertext_hex": pkg["ciphertext"].hex()
        }

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_sock:
                client_sock.connect((RECEIVER_HOST, RECEIVER_PORT))
                client_sock.sendall(json.dumps(payload_package).encode("utf-8"))
            logging.info(f"[TRANSMISSION SUCCESS] Payload sent for {filename} (MD5: {source_md5})")
        except ConnectionRefusedError:
            logging.error(
                f"[TRANSMISSION ERROR] Connection refused on {RECEIVER_HOST}:{RECEIVER_PORT}. "
                "Ensure local_receiver.py is running in Terminal 1."
            )

        time.sleep(0.2)

    logging.info("\n[PIPELINE] Batch processing and transmission completed successfully.")


def main():
    logging.info("==========================================")
    logging.info("Starting Integrated Pi Sender Daemon")
    logging.info("==========================================\n")

    staged_targets = scan_and_stage_targets(INPUT_IMAGES_DIR)

    if not staged_targets:
        logging.info("[SYSTEM] No target red rings detected in input set. Terminating execution.")
        return

    secure_and_transmit_batch(staged_targets)


if __name__ == "__main__":
    main()