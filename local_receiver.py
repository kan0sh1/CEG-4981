# # """
# # local_receiver.py
# # Ground Station Receiver Service.
# # Receives incoming payloads over TCP (or Radio), authenticates Ed25519 signatures
# # and MD5 hashes, decrypts AES-GCM payloads, and displays verification windows.
# # """

# # import os
# # import sys
# # import socket
# # import json
# # import math
# # import hashlib
# # import argparse
# # import logging
# # from pathlib import Path

# # import cv2
# # import numpy as np
# # from cryptography.hazmat.primitives.asymmetric import ed25519
# # from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# # # Logging Setup
# # logging.basicConfig(
# #     level=logging.INFO,
# #     format="%(asctime)s [%(levelname)s] %(message)s",
# #     handlers=[logging.StreamHandler(sys.stdout)]
# # )

# # DECRYPTED_DIR = Path("./decrypted_outputs")
# # DECRYPTED_DIR.mkdir(exist_ok=True)

# # # RADIO INTEGRATION HOOK 1: Import teammate's radio driver module here later
# # # Example:
# # # from radio_transceiver import RadioDriver
# # # radio = RadioDriver(port="/dev/ttyUSB0", baudrate=9600)


# # # =====================================================================
# # # 1. SECURITY & VERIFICATION ROUTINES
# # # =====================================================================

# # def verify_and_decrypt(package: dict) -> tuple[bool, bool, bytes | None]:
# #     """
# #     Decrypts payload using AES-256-GCM and verifies both the 
# #     Ed25519 digital signature and the source MD5 checksum.
# #     """
# #     ciphertext = bytes.fromhex(package["ciphertext_hex"])
# #     nonce = bytes.fromhex(package["nonce_hex"])
# #     signature = bytes.fromhex(package["signature_hex"])
# #     aes_key = bytes.fromhex(package["aes_key_hex"])
# #     pub_bytes = bytes.fromhex(package["public_key_hex"])
# #     expected_md5 = package["source_md5"]

# #     # 1. AES-256-GCM Decryption
# #     try:
# #         aesgcm = AESGCM(aes_key)
# #         decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
# #     except Exception as e:
# #         logging.error(f"[DECRYPT ERROR] AES-GCM failure: {e}")
# #         return False, False, None

# #     # 2. Ed25519 Digital Signature Verification
# #     try:
# #         public_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
# #         public_key.verify(signature, decrypted_bytes)
# #         sig_valid = True
# #     except Exception:
# #         sig_valid = False

# #     # 3. MD5 Checksum Verification
# #     computed_md5 = hashlib.md5(decrypted_bytes).hexdigest()
# #     md5_valid = (computed_md5.lower() == expected_md5.lower())

# #     return sig_valid, md5_valid, decrypted_bytes


# # def render_preview(ciphertext_hex: str, decrypted_bytes: bytes, filename: str):
# #     """Generates dual-pane GUI window: Ciphertext Noise vs. Decrypted Target."""
# #     raw_cipher = bytes.fromhex(ciphertext_hex)
# #     side = int(math.floor(math.sqrt(len(raw_cipher))))
# #     noise_matrix = np.frombuffer(raw_cipher[:side * side], dtype=np.uint8).reshape((side, side))
# #     noise_img = cv2.resize(noise_matrix, (350, 350), interpolation=cv2.INTER_NEAREST)
# #     noise_bgr = cv2.cvtColor(noise_img, cv2.COLOR_GRAY2BGR)

# #     nparr = np.frombuffer(decrypted_bytes, np.uint8)
# #     decrypted_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
# #     if decrypted_img is None:
# #         return

# #     decrypted_resized = cv2.resize(decrypted_img, (350, 350))
# #     combined_view = np.hstack((noise_bgr, decrypted_resized))

# #     cv2.putText(combined_view, "1. Encrypted Static", (10, 25), 
# #                 cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
# #     cv2.putText(combined_view, "2. Decrypted Target", (360, 25), 
# #                 cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

# #     window_title = f"Ground Station Verification: {filename}"
# #     cv2.imshow(window_title, combined_view)
# #     cv2.waitKey(0)  # Press any key on window to proceed
# #     cv2.destroyWindow(window_title)


# # # =====================================================================
# # # 2. RECEIVER SERVER & LISTENER LOOP
# # # =====================================================================

# # def start_receiver(host: str, port: int, enable_gui: bool):
# #     """Listens for incoming transport packages over network socket or radio driver."""
# #     logging.info(f"[SERVER START] Ground Station listening on {host}:{port}...")

# #     # =====================================================================
# #     # RADIO INTEGRATION HOOK 2: RECEIVER LISTENER LOOP
# #     # =====================================================================
# #     # CURRENT IMPLEMENTATION: TCP Socket Listener Loop
# #     with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
# #         server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
# #         server_sock.bind((host, port))
# #         server_sock.listen()

# #         payload_count = 0

# #         while True:
# #             try:
# #                 conn, addr = server_sock.accept()
# #                 with conn:
# #                     payload_count += 1
# #                     data = b""
# #                     while True:
# #                         chunk = conn.recv(4096)
# #                         if not chunk:
# #                             break
# #                         data += chunk

# #                     if not data:
# #                         continue

# #                     # Parse JSON package string
# #                     package = json.loads(data.decode("utf-8"))
# #                     filename = package["filename"]

# #                     # Execute verification & decryption pipeline
# #                     sig_valid, md5_valid, decrypted_bytes = verify_and_decrypt(package)

# #                     logging.info(
# #                         f"[PAYLOAD #{payload_count}] Received from {addr[0]} - "
# #                         f"File: {filename} | Ed25519: {'PASS' if sig_valid else 'FAIL'} | "
# #                         f"MD5: {'PASS' if md5_valid else 'FAIL'}"
# #                     )

# #                     if sig_valid and md5_valid and decrypted_bytes:
# #                         out_path = DECRYPTED_DIR / f"verified_{filename}"
# #                         with open(out_path, "wb") as f:
# #                             f.write(decrypted_bytes)
# #                         logging.info(f" -> Stored authenticated payload at {out_path}")

# #                         if enable_gui and ("DISPLAY" in os.environ or sys.platform == "win32"):
# #                             render_preview(package["ciphertext_hex"], decrypted_bytes, filename)
# #                     else:
# #                         logging.warning(f" -> [REJECTED] Payload integrity verification failed for {filename}")

# #             except KeyboardInterrupt:
# #                 logging.info("\n[SHUTDOWN] Terminating Ground Station service.")
# #                 break
# #             except Exception as e:
# #                 logging.error(f"[ERROR] Processing exception: {e}")

# #     # FUTURE RADIO IMPLEMENTATION: Replace TCP socket listener block above with radio read loop:
# #     # Example:
# #     # payload_count = 0
# #     # while True:
# #     #     raw_json_data = radio.listen_for_packet()  # Blocks until teammate's driver receives & reassembles packet
# #     #     package = json.loads(raw_json_data)
# #     #     sig_valid, md5_valid, decrypted_bytes = verify_and_decrypt(package)
# #     #     ... [Keep verification & display logic] ...
# #     # =====================================================================


# # if __name__ == "__main__":
# #     parser = argparse.ArgumentParser(description="Ground Station Receiver Service")
# #     parser.add_argument("--host", type=str, default="0.0.0.0", help="Binding interface (0.0.0.0 for all interfaces)")
# #     parser.add_argument("--port", type=int, default=65432, help="TCP Listening Port")
# #     parser.add_argument("--no-gui", action="store_true", help="Disable OpenCV preview windows for headless servers")
# #     args = parser.parse_args()

# #     start_receiver(args.host, args.port, enable_gui=not args.no_gui)

# """
# local_receiver.py
# Ground Station Receiver Service.
# Receives incoming payloads over LilyGO T3-S3 SX1280 Radio Transceiver,
# authenticates Ed25519 signatures and MD5 hashes, decrypts AES-GCM payloads,
# and displays verification windows.
# """

# import os
# import sys
# import json
# import math
# import hashlib
# import argparse
# import logging
# from pathlib import Path

# import cv2
# import numpy as np
# from cryptography.hazmat.primitives.asymmetric import ed25519
# from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# # Import custom radio driver transport layer
# from radio_driver import RadioTransport

# # Logging Setup
# logging.basicConfig(
#     level=logging.INFO,
#     format="%(asctime)s [%(levelname)s] %(message)s",
#     handlers=[logging.StreamHandler(sys.stdout)]
# )

# DECRYPTED_DIR = Path("./decrypted_outputs")
# DECRYPTED_DIR.mkdir(exist_ok=True)


# # =====================================================================
# # 1. SECURITY & VERIFICATION ROUTINES
# # =====================================================================

# def verify_and_decrypt(package: dict) -> tuple[bool, bool, bytes | None]:
#     """
#     Decrypts payload using AES-256-GCM and verifies both the 
#     Ed25519 digital signature and the source MD5 checksum.
#     """
#     ciphertext = bytes.fromhex(package["ciphertext_hex"])
#     nonce = bytes.fromhex(package["nonce_hex"])
#     signature = bytes.fromhex(package["signature_hex"])
#     aes_key = bytes.fromhex(package["aes_key_hex"])
#     pub_bytes = bytes.fromhex(package["public_key_hex"])
#     expected_md5 = package["source_md5"]

#     # 1. AES-256-GCM Decryption
#     try:
#         aesgcm = AESGCM(aes_key)
#         decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
#     except Exception as e:
#         logging.error(f"[DECRYPT ERROR] AES-GCM failure: {e}")
#         return False, False, None

#     # 2. Ed25519 Digital Signature Verification
#     try:
#         public_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
#         public_key.verify(signature, decrypted_bytes)
#         sig_valid = True
#     except Exception:
#         sig_valid = False

#     # 3. MD5 Checksum Verification
#     computed_md5 = hashlib.md5(decrypted_bytes).hexdigest()
#     md5_valid = (computed_md5.lower() == expected_md5.lower())

#     return sig_valid, md5_valid, decrypted_bytes


# def render_preview(ciphertext_hex: str, decrypted_bytes: bytes, filename: str):
#     """Generates dual-pane GUI window: Ciphertext Noise vs. Decrypted Target."""
#     raw_cipher = bytes.fromhex(ciphertext_hex)
#     side = int(math.floor(math.sqrt(len(raw_cipher))))
#     noise_matrix = np.frombuffer(raw_cipher[:side * side], dtype=np.uint8).reshape((side, side))
#     noise_img = cv2.resize(noise_matrix, (350, 350), interpolation=cv2.INTER_NEAREST)
#     noise_bgr = cv2.cvtColor(noise_img, cv2.COLOR_GRAY2BGR)

#     nparr = np.frombuffer(decrypted_bytes, np.uint8)
#     decrypted_img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
#     if decrypted_img is None:
#         return

#     decrypted_resized = cv2.resize(decrypted_img, (350, 350))
#     combined_view = np.hstack((noise_bgr, decrypted_resized))

#     cv2.putText(combined_view, "1. Encrypted Static", (10, 25), 
#                 cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
#     cv2.putText(combined_view, "2. Decrypted Target", (360, 25), 
#                 cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

#     window_title = f"Ground Station Verification: {filename}"
#     cv2.imshow(window_title, combined_view)
#     cv2.waitKey(0)  # Press any key on window to proceed
#     cv2.destroyWindow(window_title)


# # =====================================================================
# # 2. RECEIVER SERVER & LISTENER LOOP
# # =====================================================================

# def start_receiver(serial_port: str, baudrate: int, enable_gui: bool):
#     """Listens for incoming transport packages over LilyGO T3-S3 SX1280 radio driver."""
#     logging.info(f"[SERVER START] Ground Station listening on serial port {serial_port} @ {baudrate} baud...")

#     try:
#         radio = RadioTransport(port=serial_port, baudrate=baudrate)
#     except Exception as e:
#         logging.error(f"[RADIO ERROR] Failed to initialize serial port {serial_port}: {e}")
#         return

#     payload_count = 0

#     while True:
#         try:
#             # Block until radio driver reassembles and verifies a complete payload frame
#             raw_json_data = radio.receive_payload()
#             if not raw_json_data:
#                 logging.warning("[RADIO REJECT] Frame dropped due to packet loss or CRC failure.")
#                 continue

#             payload_count += 1

#             # Parse JSON package string
#             package = json.loads(raw_json_data)
#             filename = package["filename"]

#             # Execute verification & decryption pipeline
#             sig_valid, md5_valid, decrypted_bytes = verify_and_decrypt(package)

#             logging.info(
#                 f"[PAYLOAD #{payload_count}] Received over Radio - "
#                 f"File: {filename} | Ed25519: {'PASS' if sig_valid else 'FAIL'} | "
#                 f"MD5: {'PASS' if md5_valid else 'FAIL'}"
#             )

#             if sig_valid and md5_valid and decrypted_bytes:
#                 out_path = DECRYPTED_DIR / f"verified_{filename}"
#                 with open(out_path, "wb") as f:
#                     f.write(decrypted_bytes)
#                 logging.info(f" -> Stored authenticated payload at {out_path}")

#                 if enable_gui and ("DISPLAY" in os.environ or sys.platform == "win32"):
#                     render_preview(package["ciphertext_hex"], decrypted_bytes, filename)
#             else:
#                 logging.warning(f" -> [REJECTED] Payload integrity verification failed for {filename}")

#         except KeyboardInterrupt:
#             logging.info("\n[SHUTDOWN] Terminating Ground Station service.")
#             break
#         except Exception as e:
#             logging.error(f"[ERROR] Processing exception: {e}")


# if __name__ == "__main__":
#     parser = argparse.ArgumentParser(description="Ground Station Receiver Service with LoRa Transceiver")
#     parser.add_argument("--port", type=str, default="COM3", help="Serial port connected to LilyGO T3-S3 (e.g., COM3 or /dev/ttyACM0)")
#     parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate (must match main.cpp 115200)")
#     parser.add_argument("--no-gui", action="store_true", help="Disable OpenCV preview windows for headless servers")
#     args = parser.parse_args()

#     start_receiver(serial_port=args.port, baudrate=args.baud, enable_gui=not args.no_gui)

"""
test_crypto_pipeline.py
Local integration test for vision cropping and cryptographic payload generation.
Simulates the entire pipeline locally without needing connected SX1280 radio hardware.
"""

import os
import sys
import glob
import json
import hashlib
import numpy as np
import cv2
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import Vision and Security modules
try:
    from CircleDetection.red_ring import (
        make_red_mask_hsv,
        clean_mask,
        detect_best_ring,
        crop_including_ring
    )
    from ImageSecurity import crypto_transport
    print("[SETUP] Successfully imported CircleDetection and ImageSecurity modules.")
except ImportError as e:
    print(f"[ERROR] Import failed: {e}")
    sys.exit(1)

# Define directories
TEST_IMAGE_DIR = PROJECT_ROOT / "CircleDetection" / "test_images"
OUTPUT_DIR = PROJECT_ROOT / "crypto_test_run"
OUTPUT_DIR.mkdir(exist_ok=True)


def get_sample_image() -> str:
    """Finds a test image from CircleDetection/test_images or creates a synthetic fallback."""
    search_patterns = ["*.png", "*.jpg", "*.jpeg", "*.bmp"]
    found_files = []
    
    for pattern in search_patterns:
        found_files.extend(glob.glob(str(TEST_IMAGE_DIR / pattern)))
        
    if found_files:
        sample_path = found_files[0]
        print(f"[SETUP] Using test image: {os.path.basename(sample_path)}")
        return sample_path

    # Fallback synthetic image generation
    fallback_path = str(OUTPUT_DIR / "fallback_sample.png")
    img = np.zeros((300, 300, 3), dtype=np.uint8)
    cv2.circle(img, (150, 150), 60, (0, 0, 255), 15)  # Draw synthetic red ring
    cv2.imwrite(fallback_path, img)
    print(f"[SETUP] No test images in {TEST_IMAGE_DIR}. Created synthetic target image.")
    return fallback_path


def main():
    print("==================================================")
    print(" Testing End-to-End Vision & Crypto Pipeline      ")
    print("==================================================\n")

    # 1. Vision Processing (Red Ring Detection & Crop)
    raw_image_path = get_sample_image()
    bgr = cv2.imread(raw_image_path)
    
    mask = make_red_mask_hsv(bgr, s_min=80, v_min=80)
    mask = clean_mask(mask, k_open=3, k_close=7)
    ring = detect_best_ring(mask=mask, min_outer_area=800.0, min_inner_area=200.0)

    if ring is not None:
        crop = crop_including_ring(
            bgr=bgr,
            center=ring.get("center_o", ring["center"]),
            r_outer=ring["r_outer"],
            outer_scale=0.89,
            circular_mask=True
        )
        crop_path = str(OUTPUT_DIR / "staged_crop.png")
        cv2.imwrite(crop_path, crop, [int(cv2.IMWRITE_PNG_COMPRESSION), 1])
        print(f"[VISION] Target detected and cropped -> {crop_path}")
        input_image_path = crop_path
    else:
        print("[VISION] No red ring detected. Testing directly on source image.")
        input_image_path = raw_image_path

    # 2. Key Generation & Setup
    print("[CRYPTO] Initializing key pairs and AES-256-GCM session key...")
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

    # 3. Encrypt Payload & Build JSON (Simulates pi_sender.py)
    with open(input_image_path, "rb") as f:
        raw_bytes = f.read()

    source_md5 = hashlib.md5(raw_bytes).hexdigest()

    if hasattr(crypto_transport, "encrypt_and_sign"):
        pkg = crypto_transport.encrypt_and_sign(raw_bytes, aes_key, private_key)
    else:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        signature = private_key.sign(raw_bytes)
        nonce = os.urandom(12)
        aesgcm = AESGCM(aes_key)
        ciphertext = aesgcm.encrypt(nonce, raw_bytes, None)
        pkg = {"nonce": nonce, "ciphertext": ciphertext, "signature": signature}

    payload_package = {
        "filename": os.path.basename(input_image_path),
        "source_md5": source_md5,
        "public_key_hex": pub_bytes.hex(),
        "aes_key_hex": aes_key.hex(),
        "nonce_hex": pkg["nonce"].hex(),
        "signature_hex": pkg["signature"].hex(),
        "ciphertext_hex": pkg["ciphertext"].hex()
    }

    json_payload_str = json.dumps(payload_package)
    print(f"[PI SENDER SIMULATION] Encrypted JSON Payload generated: {len(json_payload_str)} bytes")

    # =========================================================================
    # [OPTIONAL / MOCK SECTION] LOCAL LOOPBACK BYPASS
    # Everything below simulates local_receiver.py parsing and validating data.
    # When switching strictly to radio ops, this entire bottom section is replaced
    # by running:
    #    Pi: python3 scripts/pi_sender.py --port /dev/ttyACM0
    #    PC: python local_receiver.py --port COM3
    # =========================================================================

    print("\n----------------- Simulates Ground Station Receiver -----------------")
    received_package = json.loads(json_payload_str)

    # Decode HEX fields
    recv_ciphertext = bytes.fromhex(received_package["ciphertext_hex"])
    recv_nonce = bytes.fromhex(received_package["nonce_hex"])
    recv_sig = bytes.fromhex(received_package["signature_hex"])
    recv_aes_key = bytes.fromhex(received_package["aes_key_hex"])
    recv_pub_bytes = bytes.fromhex(received_package["public_key_hex"])

    # Decrypt
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.asymmetric import ed25519
    
    aesgcm = AESGCM(recv_aes_key)
    decrypted_bytes = aesgcm.decrypt(recv_nonce, recv_ciphertext, None)

    # Verify Ed25519 Signature
    pub_key_obj = ed25519.Ed25519PublicKey.from_public_bytes(recv_pub_bytes)
    pub_key_obj.verify(recv_sig, decrypted_bytes)
    print("[RECEIVER VERIFICATION] Ed25519 Signature: VALID")

    # Verify MD5
    computed_md5 = hashlib.md5(decrypted_bytes).hexdigest()
    if computed_md5.lower() == received_package["source_md5"].lower():
        print("[RECEIVER VERIFICATION] MD5 Checksum: MATCH")

    # Save Output
    reconstructed_path = str(OUTPUT_DIR / "reconstructed_target.png")
    with open(reconstructed_path, "wb") as f:
        f.write(decrypted_bytes)

    # Check Byte Equivalence
    if raw_bytes == decrypted_bytes:
        print("\n[SUCCESS] Pipeline Test PASSED! Reconstructed payload matches original image perfectly.")
    else:
        print("\n[FAIL] Payload mismatch after decryption.")

    # =========================================================================


if __name__ == "__main__":
    main()