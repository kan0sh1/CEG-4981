#!/usr/bin/env python3
"""
server_receiver.py - Rebel Server Execution Daemon
Project: Exfiltrate & Disseminate Challenge

Handles:
  1. Sub-GHz RF packet reception & decryption (AES-256-GCM)
  2. ACK/NACK handshake transmission
  3. Stale buffer garbage collection for timed-out/failed transfers
  4. Payload parsing (MD5 verification + Ed25519 signature check)
  5. Storing verified plan images to the web application directory
"""

import os
import sys
import time
import struct
import hashlib
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.exceptions import InvalidSignature

# Import custom crypto and transport module
from crypto_transport import RFReceiver

# =====================================================================
# CONFIGURATION & CONSTANTS
# =====================================================================
KEY_DIR = "./keys"                                # Path to crypto keys
PUBLIC_KEY_PATH = os.path.join(KEY_DIR, "pi_ed25519_public.pem")
SYMMETRIC_KEY_PATH = os.path.join(KEY_DIR, "symmetric.key")

# Output directory served by the local web application (Obi-Wan interface)
OUTPUT_DIR = "./web_app/static/plans"
LISTEN_TIMEOUT_PER_FILE = 60.0                     # Max time (s) to wait for a single file

# =====================================================================
# HARDWARE DRIVER MOCK / INTERFACE
# =====================================================================
class SubGHzRadioDriver:
    """
    Wrapper interface for the Rebel Server Sub-GHz RF transceiver module.
    Replace send() and receive() with your physical driver calls.
    """
    def __init__(self):
        print("[HARDWARE] Sub-GHz Transceiver Receiver Initialized.")

    def send(self, data: bytes):
        # TODO: Replace with physical RF transmit call (e.g., sending ACK/NACK packets)
        pass

    def receive(self) -> bytes | None:
        # TODO: Replace with physical RF receive call
        # Returns raw encrypted byte packet if received, else None
        return None

# =====================================================================
# CRYPTO KEY LOADING & VERIFICATION
# =====================================================================
def load_server_keys() -> tuple[ed25519.Ed25519PublicKey, bytes]:
    """Loads the Pi's Ed25519 Public Key and shared AES-256 Symmetric Key."""
    if not os.path.exists(PUBLIC_KEY_PATH) or not os.path.exists(SYMMETRIC_KEY_PATH):
        print(f"[CRITICAL ERROR] Missing keys in {KEY_DIR}/!")
        print("Ensure pi_ed25519_public.pem and symmetric.key exist.")
        sys.exit(1)

    with open(PUBLIC_KEY_PATH, "rb") as f:
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(f.read())

    with open(SYMMETRIC_KEY_PATH, "rb") as f:
        symmetric_key = f.read()

    return public_key, symmetric_key


def unpack_and_verify_payload(signed_payload: bytes, public_key: ed25519.Ed25519PublicKey) -> tuple[bool, bytes | None]:
    """
    Parses the reassembled signed payload:
    Structure: [ Signature (64B) | MD5 Hex (32B) | Raw Image Bytes ]
    
    1. Verifies Ed25519 Signature against Public Key
    2. Validates MD5 hash matches extracted raw image data
    """
    SIGNATURE_SIZE = 64
    MD5_HEX_SIZE = 32

    if len(signed_payload) <= (SIGNATURE_SIZE + MD5_HEX_SIZE):
        print("[VERIFY ERROR] Payload too short to contain valid headers.")
        return False, None

    # Unpack binary layout
    signature = signed_payload[:SIGNATURE_SIZE]
    md5_expected = signed_payload[SIGNATURE_SIZE:SIGNATURE_SIZE + MD5_HEX_SIZE].decode('ascii')
    raw_image_data = signed_payload[SIGNATURE_SIZE + MD5_HEX_SIZE:]

    # 1. Verify Ed25519 Digital Signature over (MD5 + Raw Image Data)
    signed_content = signed_payload[SIGNATURE_SIZE:]
    try:
        public_key.verify(signature, signed_content)
        print("[VERIFY] Ed25519 Signature VALID. Origin confirmed from Raspberry Pi.")
    except InvalidSignature:
        print("[SECURITY ERROR] Ed25519 Signature INVALID! Potential unauthorized or tampered payload.")
        return False, None

    # 2. Verify Integrity via MD5 Checksum
    md5_actual = hashlib.md5(raw_image_data).hexdigest()
    if md5_actual != md5_expected:
        print(f"[INTEGRITY ERROR] MD5 Mismatch! Expected: {md5_expected}, Calculated: {md5_actual}")
        return False, None

    print("[VERIFY] MD5 Checksum VALID. Image payload integrity intact.")
    return True, raw_image_data

# =====================================================================
# MAIN SERVER LISTENING LOOP
# =====================================================================
def main():
    print("\n[SYSTEM] Starting Rebel Server Receiver Daemon...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. Load Cryptographic Credentials
    public_key, symmetric_key = load_server_keys()

    # 2. Initialize Hardware & Receiver Class
    rf_hardware = SubGHzRadioDriver()
    receiver = RFReceiver(
        rf_hardware_driver=rf_hardware, 
        symmetric_key=symmetric_key, 
        public_key=public_key
    )

    expected_file_id = 1
    total_received_count = 0

    print(f"[SYSTEM] Listening for incoming Sub-GHz transmissions... (Output Dir: {OUTPUT_DIR})")

    try:
        while True:
            print(f"\n[LISTENING] Waiting for File ID #{expected_file_id}...")
            
            # Listen for reassembled payload from RFReceiver
            signed_payload = receiver.receive_file(
                expected_file_id=expected_file_id, 
                timeout=LISTEN_TIMEOUT_PER_FILE
            )

            if signed_payload:
                # Payload received; perform signature and hash verification
                is_valid, image_bytes = unpack_and_verify_payload(signed_payload, public_key)
                
                if is_valid and image_bytes:
                    # Save verified image file to web server directory
                    output_filename = f"plan_exfiltrated_{expected_file_id:02d}.png"
                    output_path = os.path.join(OUTPUT_DIR, output_filename)
                    
                    with open(output_path, "wb") as f:
                        f.write(image_bytes)
                        
                    print(f"[SAVED] Successfully wrote verified file to: {output_path}")
                    total_received_count += 1
                    expected_file_id += 1
                else:
                    print(f"[REJECTED] Security/Integrity check failed for File ID #{expected_file_id}.")
            else:
                # Timeout occurred; perform garbage collection check and remain listening
                receiver.cleanup_stale_buffers(max_idle_time=0.0)

    except KeyboardInterrupt:
        print("\n[SYSTEM] Receiver daemon stopped by operator.")
        print(f"[SUMMARY] Total verified files processed and saved: {total_received_count}")

if __name__ == "__main__":
    main()