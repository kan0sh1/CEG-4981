import getpass
import os

# USB Token 
STORED_TOKEN = "REBELS_ACCESS_KEY"

# Second factor: PIN/password
STORED_PIN = "1234"
#temporary auth, subject to change

def check_usb_token():
    print("Insert USB drive and select the token file.")
    # Check token

    file_path = input("Enter the path to token.txt: ")

    if not os.path.exists(file_path):
        print("USB token file not found.")
        return False

    try:
        with open(file_path, "r") as file:
            usb_token = file.read().strip()

        if usb_token == STORED_TOKEN:
            print("USB token verified.")
            return True
        else:
            print("Invalid USB token.")
            return False

    except Exception:
        print("Unable to read USB token.")
        return False

#check pin

def check_pin():
    pin = getpass.getpass("Enter your PIN: ")

    if pin == STORED_PIN:
        print("PIN verified.")
        return True
    else:
        print("Invalid PIN.")
        return False

# Confirm
def authenticate():
    print("\n===== REBEL ACCESS SYSTEM =====")

    # Factor 1: USB token
    if not check_usb_token():
        print("\nACCESS DENIED")
        return False

    # Factor 2: PIN
    if not check_pin():
        print("\nACCESS DENIED")
        return False

    print("\nACCESS GRANTED")
    print("Secret video may now be accessed.")

    return True


authenticate()