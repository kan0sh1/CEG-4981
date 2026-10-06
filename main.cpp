/*
  LilyGO T3-S3 SX1280PA - Transparent Serial-to-LoRa Bridge
  Bridges USB Serial (Pi/PC) <-> SX1280 2.4GHz RF Transceiver.
*/

#include <RadioLib.h>
#include <Arduino.h>

// Board Pin Definitions for LilyGO T3-S3 SX1280PA
#define RADIO_SCLK_PIN      5
#define RADIO_MISO_PIN      3
#define RADIO_MOSI_PIN      6
#define RADIO_CS_PIN        7
#define BOARD_LED           37
#define RADIO_RST_PIN       8
#define RADIO_DIO1_PIN      9     // SX1280 DIO1
#define RADIO_BUSY_PIN      36    // SX1280 BUSY
#define RADIO_RX_PIN        21    // RF Switch RX
#define RADIO_TX_PIN        10    // RF Switch TX

#define CONFIG_RADIO_FREQ          2400.0
#define CONFIG_RADIO_OUTPUT_POWER  3      // CRITICAL: Max 3dBm for PA version to avoid hardware damage!

SX1280 radio = new Module(RADIO_CS_PIN, RADIO_DIO1_PIN, RADIO_RST_PIN, RADIO_BUSY_PIN);

// Flags for non-blocking interrupt handling
volatile bool rfOperationDone = false;
bool isTransmitting = false;

// Serial RX Buffer
String inputBuffer = "";

void setRfFlag(void) {
    rfOperationDone = true;
}

void setup() {
    // Standard Baud Rate matching Python serial settings
    Serial.begin(115200);
    
    pinMode(BOARD_LED, OUTPUT);
    digitalWrite(BOARD_LED, LOW);

    SPI.begin(RADIO_SCLK_PIN, RADIO_MISO_PIN, RADIO_MOSI_PIN);

    // Initialize Radio
    int state = radio.begin(CONFIG_RADIO_FREQ);
    if (state != RADIOLIB_ERR_NONE) {
        while (true) {
            // Signal hardware error with fast LED blinking
            digitalWrite(BOARD_LED, !digitalRead(BOARD_LED));
            delay(100);
        }
    }

    // Set output power & RF switch configuration
    radio.setOutputPower(CONFIG_RADIO_OUTPUT_POWER);
    radio.setRfSwitchPins(RADIO_RX_PIN, RADIO_TX_PIN);

    // Set interrupt callback
    radio.setDio1Action(setRfFlag);

    // Default state: Start listening for incoming RF data
    radio.startReceive();
}

void loop() {
    // =========================================================================
    // 1. INCOMING FROM AIR (RF -> SERIAL TO PYTHON)
    // =========================================================================
    if (rfOperationDone) {
        rfOperationDone = false;

        if (isTransmitting) {
            // Finished transmitting packet over RF, toggle LED & revert to RX mode
            digitalWrite(BOARD_LED, LOW);
            isTransmitting = false;
            radio.startReceive();
        } else {
            // Received packet over RF
            String receivedPayload;
            int state = radio.readData(receivedPayload);

            if (state == RADIOLIB_ERR_NONE && receivedPayload.length() > 0) {
                // Pulse LED on receive
                digitalWrite(BOARD_LED, HIGH);
                
                // Print raw line to USB Serial for Python to process
                Serial.println(receivedPayload);
                
                digitalWrite(BOARD_LED, LOW);
            }

            // Immediately restart listening
            radio.startReceive();
        }
    }

    // =========================================================================
    // 2. OUTGOING FROM PYTHON (SERIAL TO AIR)
    // =========================================================================
    while (Serial.available() > 0) {
        char c = Serial.read();
        
        if (c == '\n') {
            inputBuffer.trim();
            if (inputBuffer.length() > 0) {
                // Wait if an RF operation is currently active
                while (isTransmitting) { delay(1); }

                digitalWrite(BOARD_LED, HIGH);
                isTransmitting = true;
                
                // Transmit line over RF
                radio.startTransmit(inputBuffer);
            }
            inputBuffer = "";
        } else if (c != '\r') {
            inputBuffer += c;
        }
    }
}