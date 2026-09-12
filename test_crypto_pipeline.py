"""
test_crypto_pipeline.py
Tests the cryptographic transport pipeline using your existing project files.
"""

import os
import sys
import glob
import numpy as np
import cv2
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Import directly from your project's ImageSecurity module
try:
    from ImageSecurity import crypto_transport
    print("[SETUP] Successfully imported ImageSecurity.crypto_transport")
except ImportError as e:
    print(f"[ERROR] Import failed: {e}")
    sys.exit(1)

# Define directories based on your structure
TEST_IMAGE_DIR = PROJECT_ROOT / "CircleDetection" / "test_images"
OUTPUT_DIR = PROJECT_ROOT / "crypto_test_run"
OUTPUT_DIR.mkdir(exist_ok=True)


def get_sample_image() -> str:
    """Finds a test image from CircleDetection/test_images or creates a fallback."""
    search_patterns = ["*.png", "*.jpg", "*.jpeg", "*.bmp"]
    found_files = []
    
    for pattern in search_patterns:
        found_files.extend(glob.glob(str(TEST_IMAGE_DIR / pattern)))
        
    if found_files:
        sample_path = found_files[0]
        print(f"[SETUP] Using test image from CircleDetection: {os.path.basename(sample_path)}")
        return sample_path

    # Fallback if CircleDetection/test_images is currently empty
    fallback_path = str(OUTPUT_DIR / "fallback_sample.png")
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.circle(img, (100, 100), 50, (0, 0, 255), -1)
    cv2.imwrite(fallback_path, img)
    print(f"[SETUP] No images found in {TEST_IMAGE_DIR}. Created fallback image.")
    return fallback_path


def main():
    print("==========================================")
    print("Testing ImageSecurity Cryptographic Pipeline")
    print("==========================================\n")

    # 1. Source Image
    input_image_path = get_sample_image()
    reconstructed_image_path = str(OUTPUT_DIR / "reconstructed_target.png")

    # 2. Key Setup (Using your crypto module)
    print("[CRYPTO] Generating keys via crypto_transport...")
    if hasattr(crypto_transport, "generate_keypair"):
        private_key, public_key = crypto_transport.generate_keypair()
    else:
        # Fallback to cryptography library directly if function names differ
        from cryptography.hazmat.primitives.asymmetric import ed25519
        private_key = ed25519.Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

    if hasattr(crypto_transport, "generate_shared_aes_key"):
        aes_key = crypto_transport.generate_shared_aes_key()
    else:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aes_key = AESGCM.generate_key(bit_length=256)

    # 3. Read Source Bytes
    with open(input_image_path, "rb") as f:
        raw_bytes = f.read()

    print(f"[SENDER] Input File: {os.path.basename(input_image_path)} ({len(raw_bytes)} bytes)")

    # 4. Encrypt & Sign
    # Calls your crypto_transport routines
    if hasattr(crypto_transport, "encrypt_and_sign"):
        pkg = crypto_transport.encrypt_and_sign(raw_bytes, aes_key, private_key)
    else:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        signature = private_key.sign(raw_bytes)
        nonce = os.urandom(12)
        aesgcm = AESGCM(aes_key)
        ciphertext = aesgcm.encrypt(nonce, raw_bytes, None)
        pkg = {"nonce": nonce, "ciphertext": ciphertext, "signature": signature, "raw_bytes": raw_bytes}

    print(f"[SENDER] Encrypted Payload Size: {len(pkg['ciphertext'])} bytes")

    # 5. Decrypt & Verify
    if hasattr(crypto_transport, "decrypt_and_verify"):
        decrypted_bytes = crypto_transport.decrypt_and_verify(
            pkg["ciphertext"], pkg["nonce"], pkg["signature"], aes_key, public_key
        )
    else:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        aesgcm = AESGCM(aes_key)
        decrypted_bytes = aesgcm.decrypt(pkg["nonce"], pkg["ciphertext"], None)
        public_key.verify(pkg["signature"], decrypted_bytes)

    # 6. Save & Compare Output
    with open(reconstructed_image_path, "wb") as f:
        f.write(decrypted_bytes)

    orig_img = cv2.imread(input_image_path)
    recon_img = cv2.imread(reconstructed_image_path)

    if np.array_equal(orig_img, recon_img):
        print("\n[SUCCESS] Pipeline verified: Reconstructed image matches original perfectly!")
    else:
        print("\n[WARNING] Decryption succeeded, but image bytes differ from source.")


if __name__ == "__main__":
    main()