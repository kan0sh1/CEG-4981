import os
from cryptography.hazmat.primitives.asymmetric import ed25519

os.makedirs("keys", exist_ok=True)

# Generate Ed25519 Keypair
private_key = ed25519.Ed25519PrivateKey.generate()
public_key = private_key.public_key()

with open("keys/pi_ed25519_private.pem", "wb") as f:
    f.write(private_key.private_bytes_raw())

with open("keys/rebel_server_public.pem", "wb") as f:
    f.write(public_key.public_bytes_raw())

# Generate Random 256-bit AES Symmetric Key
symmetric_key = os.urandom(32)
with open("keys/symmetric.key", "wb") as f:
    f.write(symmetric_key)

print("[SUCCESS] Local test keys generated in /keys/ directory.")