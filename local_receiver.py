"""
local_receiver.py
Ground Station Receiver Service.
Receives incoming payloads over TCP (or Radio), authenticates Ed25519 signatures
and MD5 hashes, decrypts AES-GCM payloads, and displays verification windows.
"""

import os
import sys
import socket
import json
import math
import hashlib
import argparse
import logging
from pathlib import Path

import cv2
import numpy as np
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Logging Setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

DECRYPTED_DIR = Path("./decrypted_outputs")
DECRYPTED_DIR.mkdir(exist_ok=True)

# RADIO INTEGRATION HOOK 1: Import teammate's radio driver module here later
# Example:
# from radio_transceiver import RadioDriver
# radio = RadioDriver(port="/dev/ttyUSB0", baudrate=9600)


# =====================================================================
# 1. SECURITY & VERIFICATION ROUTINES
# =====================================================================

def verify_and_decrypt(package: dict) -> tuple[bool, bool, bytes | None]:
    """
    Decrypts payload using AES-256-GCM and verifies both the 
    Ed25519 digital signature and the source MD5 checksum.
    """
    ciphertext = bytes.fromhex(package["ciphertext_hex"])
    nonce = bytes.fromhex(package["nonce_hex"])
    signature = bytes.fromhex(package["signature_hex"])
    aes_key = bytes.fromhex(package["aes_key_hex"])
    pub_bytes = bytes.fromhex(package["public_key_hex"])
    expected_md5 = package["source_md5"]

    # 1. AES-256-GCM Decryption
    try:
        aesgcm = AESGCM(aes_key)
        decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    except Exception as e:
        logging.error(f"[DECRYPT ERROR] AES-GCM failure: {e}")
        return False, False, None

    # 2. Ed25519 Digital Signature Verification
    try:
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
        public_key.verify(signature, decrypted_bytes)
        sig_valid = True
    except Exception:
        sig_valid = False

    # 3. MD5 Checksum Verification
    computed_md5 = hashlib.md5(decrypted_bytes).hexdigest()
    md5_valid = (computed_md5.lower() == expected_md5.lower())

    return sig_valid, md5_valid, decrypted_bytes


def render_preview(ciphertext_hex: str, decrypted_bytes: bytes, filename: str):
    """Generates dual-pane GUI window: Ciphertext Noise vs. Decrypted Target."""
    raw_cipher = bytes.fromhex(ciphertext_hex)
    side = int(math.floor(math.sqrt(len(raw_cipher))))
    noise_matrix = np.frombuffer(raw_cipher[:side * side], dtype=np.uint8).reshape((side, side))
    noise_img = cv2.resize(noise_matrix, (350, 350), interpolation=cv2.INTER_NEAREST)
    noise_bgr = cv2.cvtColor(noise_img, cv2.COLOR_GRAY2BGR)

    nparr = np.frombuffer(decrypted_bytes, np.uint8)
    decrypted_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if decrypted_img is None:
        return

    decrypted_resized = cv2.resize(decrypted_img, (350, 350))
    combined_view = np.hstack((noise_bgr, decrypted_resized))

    cv2.putText(combined_view, "1. Encrypted Static", (10, 25), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    cv2.putText(combined_view, "2. Decrypted Target", (360, 25), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    window_title = f"Ground Station Verification: {filename}"
    cv2.imshow(window_title, combined_view)
    cv2.waitKey(0)  # Press any key on window to proceed
    cv2.destroyWindow(window_title)


# =====================================================================
# 2. RECEIVER SERVER & LISTENER LOOP
# =====================================================================

def start_receiver(host: str, port: int, enable_gui: bool):
    """Listens for incoming transport packages over network socket or radio driver."""
    logging.info(f"[SERVER START] Ground Station listening on {host}:{port}...")

    # =====================================================================
    # RADIO INTEGRATION HOOK 2: RECEIVER LISTENER LOOP
    # =====================================================================
    # CURRENT IMPLEMENTATION: TCP Socket Listener Loop
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((host, port))
        server_sock.listen()

        payload_count = 0

        while True:
            try:
                conn, addr = server_sock.accept()
                with conn:
                    payload_count += 1
                    data = b""
                    while True:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        data += chunk

                    if not data:
                        continue

                    # Parse JSON package string
                    package = json.loads(data.decode("utf-8"))
                    filename = package["filename"]

                    # Execute verification & decryption pipeline
                    sig_valid, md5_valid, decrypted_bytes = verify_and_decrypt(package)

                    logging.info(
                        f"[PAYLOAD #{payload_count}] Received from {addr[0]} - "
                        f"File: {filename} | Ed25519: {'PASS' if sig_valid else 'FAIL'} | "
                        f"MD5: {'PASS' if md5_valid else 'FAIL'}"
                    )

                    if sig_valid and md5_valid and decrypted_bytes:
                        out_path = DECRYPTED_DIR / f"verified_{filename}"
                        with open(out_path, "wb") as f:
                            f.write(decrypted_bytes)
                        logging.info(f" -> Stored authenticated payload at {out_path}")

                        if enable_gui and ("DISPLAY" in os.environ or sys.platform == "win32"):
                            render_preview(package["ciphertext_hex"], decrypted_bytes, filename)
                    else:
                        logging.warning(f" -> [REJECTED] Payload integrity verification failed for {filename}")

            except KeyboardInterrupt:
                logging.info("\n[SHUTDOWN] Terminating Ground Station service.")
                break
            except Exception as e:
                logging.error(f"[ERROR] Processing exception: {e}")

    # FUTURE RADIO IMPLEMENTATION: Replace TCP socket listener block above with radio read loop:
    # Example:
    # payload_count = 0
    # while True:
    #     raw_json_data = radio.listen_for_packet()  # Blocks until teammate's driver receives & reassembles packet
    #     package = json.loads(raw_json_data)
    #     sig_valid, md5_valid, decrypted_bytes = verify_and_decrypt(package)
    #     ... [Keep verification & display logic] ...
    # =====================================================================


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ground Station Receiver Service")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Binding interface (0.0.0.0 for all interfaces)")
    parser.add_argument("--port", type=int, default=65432, help="TCP Listening Port")
    parser.add_argument("--no-gui", action="store_true", help="Disable OpenCV preview windows for headless servers")
    args = parser.parse_args()

    start_receiver(args.host, args.port, enable_gui=not args.no_gui)