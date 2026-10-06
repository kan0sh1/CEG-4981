"""
radio_driver.py
Transport Layer for LilyGO T3-S3 (SX1280) LoRa Transceivers over Serial.
Handles chunking, framing, CRC32 checksums, and RF transmission delays.
"""

import time
import zlib
import logging
import serial

class RadioTransport:
    def __init__(self, port: str = "/dev/ttyACM0", baudrate: int = 115200, chunk_size: int = 120):
        """
        :param port: Serial port ('/dev/ttyACM0' on Pi; 'COM3' or similar on Windows PC)
        :param baudrate: Must match main.cpp Serial.begin (115200)
        :param chunk_size: 120 bytes max to prevent exceeding SX1280 252-byte FIFO limit
        """
        self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=2.0)
        self.chunk_size = chunk_size
        logging.info(f"[RADIO INITIALIZED] Bound to {port} @ {baudrate} baud")

    def send_payload(self, json_payload_str: str):
        """Chunks, frames, and transmits a serialized JSON payload over RF."""
        raw_bytes = json_payload_str.encode('utf-8')
        total_len = len(raw_bytes)
        total_chunks = (total_len + self.chunk_size - 1) // self.chunk_size

        # Compute entire payload CRC32
        payload_crc = zlib.crc32(raw_bytes)

        logging.info(f"[RADIO TX] Sending {total_len} bytes in {total_chunks} chunks (CRC: {hex(payload_crc)})")

        # 1. Start-of-Frame (SOF) Marker: <SOF|total_chunks|payload_crc>
        sof_marker = f"<SOF|{total_chunks}|{payload_crc}>\n".encode('utf-8')
        self.ser.write(sof_marker)
        time.sleep(0.2)

        # 2. Transmit Individual Chunks
        for idx in range(total_chunks):
            chunk = raw_bytes[idx * self.chunk_size : (idx + 1) * self.chunk_size]
            chunk_crc = zlib.crc32(chunk)
            
            # Format: <PKT|index|chunk_crc|DATA_HEX>
            packet_str = f"<PKT|{idx}|{chunk_crc}|{chunk.hex()}>\n"
            self.ser.write(packet_str.encode('utf-8'))
            
            # Pacing delay to allow SX1280 time to finish transmitting over RF
            time.sleep(0.25)

        # 3. End-of-Frame (EOF) Marker
        time.sleep(0.2)
        self.ser.write(b"<EOF>\n")
        logging.info("[RADIO TX] Transmission complete.")

    def receive_payload(self) -> str | None:
        """Blocks until a full payload frame is reassembled and CRC verified."""
        buffer = {}
        total_expected_chunks = None
        expected_payload_crc = None
        in_frame = False

        logging.info("[RADIO RX] Listening for incoming RF payload...")

        while True:
            try:
                line_bytes = self.ser.readline()
                if not line_bytes:
                    continue

                line = line_bytes.decode('utf-8', errors='ignore').strip()

                # Parse Start-of-Frame
                if line.startswith("<SOF|"):
                    parts = line.rstrip(">").split("|")
                    if len(parts) == 3:
                        total_expected_chunks = int(parts[1])
                        expected_payload_crc = int(parts[2])
                        buffer.clear()
                        in_frame = True
                        logging.info(f"[RADIO RX] Frame start detected! Expecting {total_expected_chunks} chunks.")
                    continue

                # Parse Data Packet
                if in_frame and line.startswith("<PKT|"):
                    parts = line.rstrip(">").split("|")
                    if len(parts) == 4:
                        idx = int(parts[1])
                        recv_crc = int(parts[2])
                        chunk_data = bytes.fromhex(parts[3])

                        # Verify packet CRC32
                        if zlib.crc32(chunk_data) == recv_crc:
                            buffer[idx] = chunk_data
                            logging.info(f"[RADIO RX] Chunk {idx + 1}/{total_expected_chunks} verified.")
                        else:
                            logging.error(f"[RADIO RX ERROR] Corrupted chunk at index {idx}! CRC mismatch.")

                # Parse End-of-Frame
                if in_frame and line.startswith("<EOF>"):
                    logging.info("[RADIO RX] EOF received. Reassembling payload...")

                    if len(buffer) != total_expected_chunks:
                        logging.error(f"[RADIO RX ERROR] Packet loss detected! Got {len(buffer)}/{total_expected_chunks} chunks.")
                        return None

                    reassembled_bytes = bytearray()
                    for idx in range(total_expected_chunks):
                        reassembled_bytes.extend(buffer[idx])

                    # Verify full payload CRC32
                    if zlib.crc32(reassembled_bytes) == expected_payload_crc:
                        logging.info("[RADIO RX SUCCESS] Payload integrity verified!")
                        return reassembled_bytes.decode('utf-8')
                    else:
                        logging.error("[RADIO RX ERROR] Payload CRC failed! Data corrupted.")
                        return None

            except Exception as e:
                logging.error(f"[RADIO RX EXCEPTION] Error: {e}")