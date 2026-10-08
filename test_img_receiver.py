import serial
import base64

SERIAL_PORT = "/dev/ttyACM1"  # Update to match receiving port
BAUD_RATE = 115200
OUTPUT_PATH = "received_image.png"

def receive_image():
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=None)
    print(f"[*] Listening on {SERIAL_PORT} for incoming image transmission...")

    b64_chunks = []
    receiving = False

    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line:
            continue

        if line.startswith("START:"):
            total_expected = line.split(":")[1]
            print(f"[+] Incoming image transfer detected! Expected chunks: {total_expected}")
            b64_chunks = []
            receiving = True

        elif line == "END" and receiving:
            print("[+] All chunks received! Reconstructing image...")
            full_b64 = "".join(b64_chunks)
            
            try:
                img_data = base64.b64decode(full_b64)
                with open(OUTPUT_PATH, "wb") as f:
                    f.write(img_data)
                print(f"[SUCCESS] Image successfully saved as '{OUTPUT_PATH}'!")
            except Exception as e:
                print(f"[ERROR] Failed to decode image: {e}")
            
            receiving = False

        elif receiving:
            b64_chunks.append(line)
            print(f" -> Received chunk {len(b64_chunks)}")

if __name__ == "__main__":
    receive_image()