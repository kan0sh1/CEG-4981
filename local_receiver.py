"""
local_receiver.py
Simulates an RF ground station / server receiving raw encrypted payloads.
Renders raw ciphertext as a grayscale noise matrix before decryption.
"""

import socket
import json
import math
from pathlib import Path

import cv2
import numpy as np

HOST = "127.0.0.1"  # Localhost
PORT = 65432        # Local TCP port
RECEIVED_DIR = Path("./received_encrypted_payloads")
RECEIVED_DIR.mkdir(exist_ok=True)


def display_ciphertext_noise(ciphertext_hex: str, filename: str):
    """
    Converts raw ciphertext bytes into a square grayscale matrix 
    and displays it as high-entropy static (pure visual noise).
    """
    raw_bytes = bytes.fromhex(ciphertext_hex)
    total_bytes = len(raw_bytes)

    if total_bytes == 0:
        return

    # Calculate dimensions for a square matrix
    side = int(math.floor(math.sqrt(total_bytes)))
    usable_bytes = side * side

    # Reshape byte array into a 2D image matrix
    byte_array = np.frombuffer(raw_bytes[:usable_bytes], dtype=np.uint8)
    noise_matrix = byte_array.reshape((side, side))

    # Scale window up for visibility
    display_img = cv2.resize(noise_matrix, (400, 400), interpolation=cv2.INTER_NEAREST)

    # Render window
    window_title = f"Pre-Decryption Ciphertext Stream: {filename}"
    cv2.imshow(window_title, display_img)
    print(f" [VISUALIZER] Displaying raw encrypted static window ({side}x{side} grid). Press any key on image to continue...")
    
    cv2.waitKey(0)
    cv2.destroyWindow(window_title)


def start_receiver():
    print("==========================================")
    print("      Local RF/TCP Encrypted Receiver     ")
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

                # Parse transport package header
                package = json.loads(data.decode("utf-8"))
                filename = package.get("filename", f"payload_{payload_count}.bin")
                ciphertext_hex = package.get("ciphertext_hex", "")
                signature_hex = package.get("signature_hex", "")
                nonce_hex = package.get("nonce_hex", "")

                print(f"\n[RECEIVED PAYLOAD #{payload_count}] Source File: {filename}")
                print(f" ├── Encrypted Size: {len(ciphertext_hex) // 2} bytes")
                print(f" ├── Nonce (Hex):    {nonce_hex[:16]}...")
                print(f" ├── Ed25519 Sig:    {signature_hex[:24]}...")
                print(f" └── Ciphertext Preview (HEX): {ciphertext_hex[:40]}...")

                # Save raw metadata & ciphertext (NO DECRYPTION)
                out_path = RECEIVED_DIR / f"encrypted_{filename}.json"
                with open(out_path, "w") as f:
                    json.dump(package, f, indent=2)

                print(f" [SAVED] Raw encrypted package saved to: {out_path}")

                # Display the raw encrypted noise window
                display_ciphertext_noise(ciphertext_hex, filename)


if __name__ == "__main__":
    start_receiver()