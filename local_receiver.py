"""
local_receiver.py
Offline verification & rendering ground station.
Validates Ed25519 signatures, AES-256-GCM decryption, MD5 hashes,
and displays pre-decryption noise next to decrypted images.
"""

import socket
import json
import math
import hashlib
from pathlib import Path

import cv2
import numpy as np
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HOST = "127.0.0.1"
PORT = 65432
DECRYPTED_DIR = Path("./decrypted_outputs")
DECRYPTED_DIR.mkdir(exist_ok=True)


def verify_and_decrypt(package: dict) -> tuple[bool, bool, bytes | None]:
    """
    1. Decrypts AES-256-GCM payload.
    2. Verifies Ed25519 digital signature on decrypted raw bytes.
    3. Checks MD5 checksum against original file hash.
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
        print(f" [DECRYPT FAIL] AES-GCM decryption failed: {e}")
        return False, False, None

    # 2. Ed25519 Signature Verification
    sig_valid = False
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


def display_pipeline_verification(ciphertext_hex: str, decrypted_bytes: bytes, filename: str):
    """Generates side-by-side visualization: Ciphertext Noise vs. Decrypted Crop."""
    # Build Noise Grid
    raw_cipher = bytes.fromhex(ciphertext_hex)
    side = int(math.floor(math.sqrt(len(raw_cipher))))
    noise_matrix = np.frombuffer(raw_cipher[:side * side], dtype=np.uint8).reshape((side, side))
    noise_img = cv2.resize(noise_matrix, (350, 350), interpolation=cv2.INTER_NEAREST)
    noise_bgr = cv2.cvtColor(noise_img, cv2.COLOR_GRAY2BGR)

    # Decode Decrypted Image
    nparr = np.frombuffer(decrypted_bytes, np.uint8)
    decrypted_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    decrypted_resized = cv2.resize(decrypted_img, (350, 350))

    # Stitch side-by-side
    combined_view = np.hstack((noise_bgr, decrypted_resized))

    # Add display labels
    cv2.putText(combined_view, "1. Encrypted Static", (10, 25), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    cv2.putText(combined_view, "2. Decrypted Target", (360, 25), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    window_title = f"Offline Verification Pipeline: {filename}"
    cv2.imshow(window_title, combined_view)
    print(" [VISUALIZER] Showing dual preview window. Press ANY KEY on image window to continue...")
    cv2.waitKey(0)
    cv2.destroyWindow(window_title)


def start_receiver():
    print("==========================================")
    print("  Offline Verification Ground Station     ")
    print("==========================================\n")
    print(f"[RECEIVER] Listening on {HOST}:{PORT}...")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.bind((HOST, PORT))
        server_sock.listen()

        payload_count = 0

        while True:
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

                package = json.loads(data.decode("utf-8"))
                filename = package["filename"]

                print(f"\n[PAYLOAD #{payload_count}] Incoming payload: {filename}")

                # Execute Verification Routines
                sig_valid, md5_valid, decrypted_bytes = verify_and_decrypt(package)

                sig_status = "PASS" if sig_valid else "FAIL"
                md5_status = "PASS" if md5_valid else "FAIL"

                print(f" ├── Ed25519 Signature Verification: [{sig_status}]")
                print(f" ├── MD5 Hash Verification:         [{md5_status}]")

                if sig_valid and md5_valid and decrypted_bytes:
                    out_path = DECRYPTED_DIR / f"verified_{filename}"
                    with open(out_path, "wb") as f:
                        f.write(decrypted_bytes)
                    print(f" └── [SUCCESS] Image authenticated & decrypted -> Saved to {out_path}")
                    
                    # Display Side-by-Side Verification
                    display_pipeline_verification(package["ciphertext_hex"], decrypted_bytes, filename)
                else:
                    print(" └── [SECURITY ALERT] Payload failed authentication or integrity checks!")


if __name__ == "__main__":
    start_receiver()