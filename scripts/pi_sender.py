"""
scripts/pi_sender.py
Integrated Pi Sender Pipeline.
Processes target frames via CircleDetection, encrypts/signs payloads,
and transmits them over TCP (or Radio) to the Ground Station.
"""

import os
import sys
import time
import json
import socket
import hashlib
import logging
import argparse
from pathlib import Path
from typing import List

import cv2

# =====================================================================
# 1. ENVIRONMENT & MODULE RESOLUTION
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
    from ImageSecurity import crypto_transport
except ImportError as e:
    logging.critical(f"[CRITICAL] Module import failed: {e}")
    sys.exit(1)

# Default Pipeline Paths
INPUT_IMAGES_DIR = PROJECT_ROOT / "CircleDetection" / "test_images"
STAGED_CROPS_DIR = PROJECT_ROOT / "staged_crops"
IMG_EXTENSIONS = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tif", "*.tiff", "*.webp")

# RADIO INTEGRATION HOOK 1: Import radio driver module here later
# Example:
# from radio_transceiver import RadioDriver
# radio = RadioDriver(port="/dev/ttyS0", baudrate=9600)


# =====================================================================
# 2. VISION PIPELINE INTEGRATION
# =====================================================================

def process_and_crop_image(image_path: Path, output_dir: Path) -> str | None:
    """Processes candidate image through red ring detection and stages lossless crop."""
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
    
    # Save target crop as lossless PNG
    cv2.imwrite(str(out_path), crop, [int(cv2.IMWRITE_PNG_COMPRESSION), 1])
    
    logging.info(f"[TARGET MATCH] Staged target: {out_path.name} (Score: {ring['score']:.2f})")
    return str(out_path)


# =====================================================================
# 3. SECURITY & TRANSMISSION PIPELINE INTEGRATION
# =====================================================================

def secure_and_transmit_batch(staged_files: List[str], receiver_host: str, receiver_port: int):
    """Encrypts, signs, and transmits staged targets over network/RF transport layer."""
    logging.info("[SECURITY] Generating Key Infrastructure for transmission batch...")

    # Key Infrastructure Setup
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

    pub_bytes = public_key.public_bytes_raw()

    for file_path in staged_files:
        filename = os.path.basename(file_path)
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

        # Structured Transport Package
        payload_package = {
            "filename": filename,
            "source_md5": source_md5,
            "public_key_hex": pub_bytes.hex(),
            "aes_key_hex": aes_key.hex(),
            "nonce_hex": pkg["nonce"].hex(),
            "signature_hex": pkg["signature"].hex(),
            "ciphertext_hex": pkg["ciphertext"].hex()
        }

        # Convert payload dictionary to JSON string
        json_payload = json.dumps(payload_package)

        # =====================================================================
        # RADIO INTEGRATION HOOK 2: TRANSMISSION TRANSPORT LAYER
        # =====================================================================
        # CURRENT IMPLEMENTATION: Standard Local/Network TCP Socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_sock:
                client_sock.settimeout(5.0)
                client_sock.connect((receiver_host, receiver_port))
                client_sock.sendall(json_payload.encode("utf-8"))
            logging.info(f"[TRANSMISSION SUCCESS] Sent {filename} to {receiver_host}:{receiver_port}")
        except Exception as e:
            logging.error(f"[TRANSMISSION FAILED] Unable to reach {receiver_host}:{receiver_port} - {e}")

        # FUTURE RADIO IMPLEMENTATION: Replace TCP socket block above with teammate's radio driver function:
        # Example:
        # try:
        #     radio.transmit_packet(json_payload)
        #     logging.info(f"[RADIO SUCCESS] Transmitted {filename} over radio link.")
        # except Exception as e:
        #     logging.error(f"[RADIO FAILED] Transmission failed: {e}")
        # =====================================================================

        time.sleep(0.2)


# =====================================================================
# 4. ENTRY POINT
# =====================================================================

def main():
    parser = argparse.ArgumentParser(description="Pi Sender Edge Daemon")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Target Receiver IP address")
    parser.add_argument("--port", type=int, default=65432, help="Target Receiver TCP port")
    parser.add_argument("--input", type=str, default=str(INPUT_IMAGES_DIR), help="Path to input images directory")
    args = parser.parse_args()

    input_path = Path(args.input)
    logging.info(f"[STARTUP] Running Pi Sender -> Target: {args.host}:{args.port}")

    if not input_path.exists():
        logging.error(f"[ERROR] Specified input path does not exist: {input_path}")
        return

    image_files = []
    for ext in IMG_EXTENSIONS:
        image_files.extend(input_path.glob(ext))

    staged_crops = []
    for img_path in sorted(image_files):
        cropped = process_and_crop_image(img_path, STAGED_CROPS_DIR)
        if cropped:
            staged_crops.append(cropped)

    if not staged_crops:
        logging.info("[SYSTEM] No valid target red rings found for processing.")
        return

    secure_and_transmit_batch(staged_crops, args.host, args.port)


if __name__ == "__main__":
    main()