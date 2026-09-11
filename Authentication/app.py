import os
from flask import Flask, request, jsonify, send_from_directory
from authentication import check_usb_token, check_pin

# absolute file path construct to project root by stepping up one level from current file's directory
# absolute path to frontend folder
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..')) 
WEBSITE_DIR = os.path.join(BASE_DIR, 'Website')

# Flask App initialization
app = Flask(__name__, static_folder=WEBSITE_DIR, static_url_path='')


# Initial load up on index.html with the public video
@app.route('/')
def server_index():
    return send_from_directory(WEBSITE_DIR, 'index.html')

# API endpoint for handling POST login
@app.route('/api/login', methods=['POST'])
def api_authenticate():
    data = request.get_json() or {}
    entered_pin = data.get('pin', '')

# Verify presence and valid USB token file
    token_msg, token_valid = check_usb_token()
    if not token_valid:
        # return unauthorized on fails
        return jsonify({"authenticated": False, "message": token_msg}), 401 
    
    # verify submitted PIN against stored pin
    pin_msg, pin_valid = check_pin(entered_pin)
    if not pin_valid:
        # return unauthorized if pin check fails
        return jsonify({"authenticated": False, "message": pin_msg}), 401
    
    # return success
    return jsonify({
        "authenticated": True,
        "message": "Access Granted. Secret Video commensing",
        "video_id": "zGwszApFEcY"
    }), 200



if __name__ == '__main__':
    print("\n===== REBEL ACCESS SYSTEM =====")
    app.run(debug=True)