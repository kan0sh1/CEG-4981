import os

# USB Token 
STORED_TOKEN = "REBELS_ACCESS_KEY"

# Second factor: PIN/password
STORED_PIN = "1234"
#temporary auth, subject to change

# absolute path to token.txt
TOKEN_PATH = os.path.join(os.path.dirname(__file__), "token.txt")

def check_usb_token(file_path=TOKEN_PATH):


# check if USB token file exists
    if not os.path.exists(file_path):
        message = ("USB token file not found.")
        return message, False

# open and read token.txt, stripping surrounding whitespace
    try:
        with open(file_path, "r") as file:
            usb_token = file.read().strip()

# compare file content against stored authorization key
        if usb_token == STORED_TOKEN:
            message = ("USB token verified.")
            return message, True
        else:
            message = ("Invalid USB token.")
            return message, False

# handles unexpected read errors
    except Exception:
        message = ("Unable to read USB token.")
        return message, False

#check pin

def check_pin(pin):
    if pin == STORED_PIN:
        message = ("PIN verified.")
        return message, True
    else:
        message = ("Invalid PIN.")
        return message, False


# authenticate()