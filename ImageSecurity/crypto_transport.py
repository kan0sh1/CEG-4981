import hashlib
import struct
import time
from Crypto.Cipher import AES
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.exceptions import InvalidSignature

CHUNK_SIZE = 512  # Optimal payload size for Sub-GHz RF modules

# =====================================================================
# 1. APPLICATION LAYER: SIGNING & INTEGRITY (Ed25519 + MD5)
# =====================================================================

def prepare_signed_file(file_path: str, private_key: ed25519.Ed25519PrivateKey) -> tuple[bytes, str]:
    """
    Reads image, calculates MD5, signs (MD5 + Raw Image) via Ed25519.
    Returns: (Signed Payload Bytes, Original MD5 Hex)
    """
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    # MD5 Checksum (Req 40)
    md5_hex = hashlib.md5(file_bytes).hexdigest()
    md5_bytes = md5_hex.encode('utf-8')  # 32 bytes

    # Ed25519 Signature over (MD5 + File)
    signature = private_key.sign(md5_bytes + file_bytes)  # 64 bytes

    # Unencrypted Signed Payload: [MD5 (32B)] + [Signature (64B)] + [Raw File]
    signed_payload = md5_bytes + signature + file_bytes
    return signed_payload, md5_hex


def verify_and_save_file(signed_payload: bytes, public_key: ed25519.Ed25519PublicKey, output_path: str) -> tuple[bool, str]:
    """
    Verifies Ed25519 signature and MD5 hash after full file reassembly (Req 110).
    """
    if len(signed_payload) < 96:
        return False, "Payload too short"

    md5_hex = signed_payload[:32].decode('utf-8')
    signature = signed_payload[32:96]
    file_bytes = signed_payload[96:]

    # 1. Verify Ed25519 Signature
    try:
        public_key.verify(signature, md5_hex.encode('utf-8') + file_bytes)
    except InvalidSignature:
        return False, "Ed25519 Signature Verification Failed! Potential Spoofing."

    # 2. Verify MD5 Integrity
    computed_md5 = hashlib.md5(file_bytes).hexdigest()
    if computed_md5 != md5_hex:
        return False, f"MD5 Mismatch! Computed: {computed_md5}, Expected: {md5_hex}"

    # 3. Save to disk
    with open(output_path, "wb") as f:
        f.write(file_bytes)

    return True, md5_hex


# =====================================================================
# 2. TRANSPORT LAYER: ENCRYPTION & CHUNKING (AES-256-GCM)
# =====================================================================

def encrypt_and_chunk(signed_payload: bytes, file_id: int, symmetric_key: bytes) -> list[bytes]:
    """
    Splits signed payload into chunks and encrypts each chunk using AES-256-GCM.
    """
    chunks = [signed_payload[i:i + CHUNK_SIZE] for i in range(0, len(signed_payload), CHUNK_SIZE)]
    total_chunks = len(chunks)
    packets = []

    for chunk_id, chunk_data in enumerate(chunks):
        cipher = AES.new(symmetric_key, AES.MODE_GCM)
        ciphertext, auth_tag = cipher.encrypt_and_digest(chunk_data)

        # Header: FileID (2B), ChunkID (2B), TotalChunks (2B)
        header = struct.pack(">HHH", file_id, chunk_id, total_chunks)
        
        # Frame: Header (6B) + Nonce (12B) + AuthTag (16B) + Ciphertext
        packet = header + cipher.nonce + auth_tag + ciphertext
        packets.append(packet)

    return packets


def decrypt_chunk(packet: bytes, symmetric_key: bytes) -> tuple[int, int, int, bytes | None]:
    """
    Decrypts an incoming RF packet and verifies AES-GCM Auth Tag.
    Returns: (file_id, chunk_id, total_chunks, decrypted_data)
    """
    if len(packet) < 36:  # 6B Header + 12B Nonce + 16B Tag = 36B Minimum
        return None, None, None, None

    header = packet[:6]
    file_id, chunk_id, total_chunks = struct.unpack(">HHH", header)

    nonce = packet[6:18]
    auth_tag = packet[18:34]
    ciphertext = packet[34:]

    cipher = AES.new(symmetric_key, AES.MODE_GCM, nonce=nonce)
    try:
        # Decrypts and checks AES-GCM Auth Tag for packet-level integrity
        decrypted_chunk = cipher.decrypt_and_verify(ciphertext, auth_tag)
        return file_id, chunk_id, total_chunks, decrypted_chunk
    except ValueError:
        # RF Corruption detected!
        return file_id, chunk_id, total_chunks, None


# =====================================================================
# 3. TRANSMISSION PROTOCOL: ACK/NACK RETRANSMISSION LOOP (Req 120)
# =====================================================================

class RFSender:
    def __init__(self, rf_hardware_driver, symmetric_key: bytes):
        self.rf = rf_hardware_driver
        self.key = symmetric_key

    def send_file(self, file_id: int, signed_payload: bytes, timeout=2.0, max_retries=5) -> bool:
        packets = encrypt_and_chunk(signed_payload, file_id, self.key)
        total_chunks = len(packets)
        chunk_idx = 0

        while chunk_idx < total_chunks:
            packet = packets[chunk_idx]
            retries = 0
            ack_received = False

            while retries < max_retries and not ack_received:
                # Transmit packet over RF
                self.rf.send(packet)
                
                # Listen for ACK/NACK response from Rebel Server
                response = self.rf.receive_with_timeout(timeout)
                if response:
                    # Expect ACK structure: "ACK" (3B) + FileID (2B) + ChunkID (2B)
                    if len(response) == 7 and response[:3] == b"ACK":
                        res_file_id, res_chunk_id = struct.unpack(">HH", response[3:])
                        if res_file_id == file_id and res_chunk_id == chunk_idx:
                            ack_received = True
                            chunk_idx += 1  # Move to next chunk
                            break
                
                # If NACK or Timeout occurs, retry
                retries += 1
                time.sleep(0.05)

            if not ack_received:
                print(f"[ERR] Failed to transmit File {file_id}, Chunk {chunk_idx} after max retries.")
                return False

        return True


class RFReceiver:
    def __init__(self, rf_hardware_driver, symmetric_key: bytes, public_key: ed25519.Ed25519PublicKey):
        """
        :param rf_hardware_driver: Hardware interface object providing send() and receive()
        :param symmetric_key: 32-byte (256-bit) AES key for packet decryption
        :param public_key: Ed25519 Public Key for sender authenticity verification
        """
        self.rf = rf_hardware_driver
        self.key = symmetric_key
        self.public_key = public_key
        
        self.buffer = {}             # Stores incoming chunks: {file_id: {chunk_id: chunk_data}}
        self.buffer_timestamps = {}  # Tracks last activity per file_id for garbage collection

    def cleanup_stale_buffers(self, max_idle_time: float = 30.0):
        """
        Purges partially received files from memory if no new chunks have arrived 
        within the max_idle_time window. Prevents memory leaks on failed transmissions.
        """
        current_time = time.time()
        stale_ids = [
            file_id for file_id, last_active in self.buffer_timestamps.items()
            if current_time - last_active > max_idle_time
        ]
        
        for file_id in stale_ids:
            print(f"[CLEANUP] Discarding incomplete/corrupted buffer for File ID: {file_id}")
            if file_id in self.buffer:
                del self.buffer[file_id]
            if file_id in self.buffer_timestamps:
                del self.buffer_timestamps[file_id]

    def receive_file(self, expected_file_id: int, timeout: float = 60.0) -> bytes | None:
        """
        Listens for incoming RF packets for a specific file, sends ACK/NACK responses,
        and reassembles the complete payload upon receiving all chunks.
        
        Returns: Reassembled signed_payload bytes if successful, None on timeout/failure.
        """
        start_time = time.time()
        self.buffer[expected_file_id] = {}
        self.buffer_timestamps[expected_file_id] = time.time()

        while time.time() - start_time < timeout:
            # Perform periodic buffer maintenance on inactive transfers
            self.cleanup_stale_buffers()

            # Poll RF driver for incoming packet
            packet = self.rf.receive()
            if not packet:
                time.sleep(0.01)  # Yield CPU execution briefly
                continue

            # Decrypt packet and check AES-GCM Auth Tag
            file_id, chunk_id, total_chunks, chunk_data = decrypt_chunk(packet, self.key)

            # Ignore packets not belonging to the targeted file stream
            if file_id != expected_file_id or file_id is None:
                continue

            # Update activity timestamp for garbage collection tracking
            self.buffer_timestamps[file_id] = time.time()

            if chunk_data is not None:
                # 1. Valid Chunk: Store data & send ACK response
                self.buffer[file_id][chunk_id] = chunk_data
                ack_packet = b"ACK" + struct.pack(">HH", file_id, chunk_id)
                self.rf.send(ack_packet)

                # 2. Check if all file chunks have arrived
                if len(self.buffer[file_id]) == total_chunks:
                    print(f"[RECOVERED] All {total_chunks} chunks received for File ID: {file_id}")
                    
                    # Reassemble payload in ordinal sequence
                    full_payload = b"".join([self.buffer[file_id][i] for i in range(total_chunks)])
                    
                    # Flush buffer state for this completed file
                    del self.buffer[file_id]
                    del self.buffer_timestamps[file_id]
                    
                    return full_payload
            else:
                # 3. Corrupted Chunk (AES-GCM Auth Tag Mismatch): Return NACK
                print(f"[NACK] Corruption detected in File ID: {file_id}, Chunk ID: {chunk_id}")
                nack_packet = b"NAK" + struct.pack(">HH", file_id, chunk_id)
                self.rf.send(nack_packet)

        # Timeout reached before all chunks arrived
        print(f"[TIMEOUT] File ID {expected_file_id} failed to complete within {timeout} seconds.")
        self.cleanup_stale_buffers(max_idle_time=0.0)  # Force purge failed file state
        return None