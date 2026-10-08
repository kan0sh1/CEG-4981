import serial
import base64
import time

SERIAL_PORT = "/dev/ttyACM0"  # Update to match your port (e.g., 'COM3' on Windows)
BAUD_RATE = 115200
IMAGE_PATH = "test_image.png"  # Path to your test image
CHUNK_SIZE = 200               # Safe chunk size in bytes for SX1280 FIFO

def send_image():
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=2)
    time.sleep(2)  # Wait for serial connection to stabilize

    # Read image and convert to Base64
    with open(IMAGE_PATH, "rb") as f:
        raw_bytes = f.read()
    
    b64_data = base64.b64encode(raw_bytes).decode("utf-8")
    total_chunks = (len(b64_data) + CHUNK_SIZE - 1) // CHUNK_SIZE

    print(f"[+] Sending '{IMAGE_PATH}' ({len(raw_bytes)} bytes, {total_chunks} chunks)...")

    # Send START marker
    ser.write(f"START:{total_chunks}\n".encode("utf-8"))
    time.sleep(0.15)

    # Send Base64 chunks
    for i in range(total_chunks):
        chunk = b64_data[i * CHUNK_SIZE : (i + 1) * CHUNK_SIZE]
        ser.write(f"{chunk}\n".encode("utf-8"))
        print(f" -> Sent chunk {i+1}/{total_chunks}")
        time.sleep(0.12)  # Small delay to give RadioLib time to transmit frame

    # Send END marker
    ser.write(b"END\n")
    print("[+] Transmission complete!")
    ser.close()

if __name__ == "__main__":
    send_image()