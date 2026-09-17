"""
pi_sender.py
Integrates CircleDetection/red_ring.py and ImageSecurity/crypto_transport.py
into an end-to-end processing pipeline for Raspberry Pi / local execution.
"""

import os
import sys
import glob
import time
import logging
import socket
import json
from pathlib import Path
from typing import List

import cv2

# Ensure project root is on Python's search path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# 1. Import module routines directly from project folders
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

# Pipeline Paths & Defaults
INPUT_IMAGES_DIR = PROJECT_ROOT / "CircleDetection" / "test_images"
STAGED_CROPS_DIR = PROJECT_ROOT / "staged_crops"
IMG_EXTENSIONS = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.tif", "*.tiff", "*.webp")

RECEIVER_HOST = "127.0.0.1"
RECEIVER_PORT = 65432  # Must match local_receiver.py port

# =====================================================================
# 2. VISION PIPELINE INTEGRATION
# =====================================================================

def process_and_crop_image(image_path: Path, output_dir: Path) -> str | None:
    """
    Passes raw image through red_ring.py detection pipeline.
    Saves antialiased crop to output_dir if a ring is matched.
    """
    bgr = cv2.imread(str(image_path))
    if bgr is None:
        logging.warning(f"[VISION SKIP] Unreadable image file: {image_path.name}")
        return None

    # Run red_ring detection routines
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

    # Crop including outer boundary with anti-aliasing
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

    # Save as lossless PNG
    cv2.imwrite(str(out_path), crop, [int(cv2.IMWRITE_PNG_COMPRESSION), 1])
    logging.info(f"[VISION MATCH] Target detected in {image_path.name} (score={ring['score']:.2f}) -> Staged: {out_path.name}")
    return str(out_path)


def scan_and_stage_targets(input_dir: Path) -> List[str]:
    """Scans directory and runs vision processing on all candidate images."""
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
    """
    Encrypts/signs each staged image via ImageSecurity and transmits 
    the raw hex payload via local TCP socket without local decryption.
    """
    logging.info("\n------------------------------------------")
    logging.info("Initializing Cryptographic Key Infrastructure")
    logging.info("------------------------------------------")

    # Key generation wrappers
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

    for file_path in staged_files:
        filename = os.path.basename(file_path)
        logging.info(f"\n[SECURITY] Encrypting & Signing target: {filename}")
        
        with open(file_path, "rb") as f:
            raw_bytes = f.read()

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

        # Hex-encode binary payloads for JSON transport
        payload_package = {
            "filename": filename,
            "nonce_hex": pkg["nonce"].hex(),
            "signature_hex": pkg["signature"].hex(),
            "ciphertext_hex": pkg["ciphertext"].hex()
        }

        # Transmit over localhost socket to local_receiver.py
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_sock:
                client_sock.connect((RECEIVER_HOST, RECEIVER_PORT))
                client_sock.sendall(json.dumps(payload_package).encode("utf-8"))
            logging.info(f"[TRANSMISSION SUCCESS] Encrypted payload sent to receiver for {filename}")
        except ConnectionRefusedError:
            logging.error(
                f"[TRANSMISSION ERROR] Connection refused on {RECEIVER_HOST}:{RECEIVER_PORT}. "
                "Ensure local_receiver.py is running in Terminal 1."
            )

        time.sleep(0.2)

    logging.info("\n[PIPELINE] Batch processing and transmission completed successfully.")

# def secure_and_transmit_batch(staged_files: List[str]):
    """
    Loads keypairs, signs/encrypts each staged image via ImageSecurity,
    and handles simulated RF payload transmission.
    """
    logging.info("\n------------------------------------------")
    logging.info("Initializing Cryptographic Key Infrastructure")
    logging.info("------------------------------------------")

    # Generate or load active keys using crypto_transport
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

    for file_path in staged_files:
        logging.info(f"\n[SECURITY] Processing target: {os.path.basename(file_path)}")
        
        with open(file_path, "rb") as f:
            raw_bytes = f.read()

        # Call crypto_transport routines
        if hasattr(crypto_transport, "encrypt_and_sign"):
            pkg = crypto_transport.encrypt_and_sign(raw_bytes, aes_key, private_key)
        else:
            # Fallback wrapper
            signature = private_key.sign(raw_bytes)
            nonce = os.urandom(12)
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            aesgcm = AESGCM(aes_key)
            ciphertext = aesgcm.encrypt(nonce, raw_bytes, None)
            pkg = {"nonce": nonce, "ciphertext": ciphertext, "signature": signature}

        logging.info(f"[SECURITY] Payload Encrypted ({len(pkg['ciphertext'])} bytes) & Signed with Ed25519.")
        
        # Simulate RF transmission step
        logging.info(f"[RF TRANSPORT] Transmitting payload packets for {os.path.basename(file_path)}...")
        time.sleep(0.3)

    logging.info("\n[PIPELINE] Batch processing and transmission completed successfully.")


# =====================================================================
# 4. ENTRY POINT
# =====================================================================

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