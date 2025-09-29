import os
import uuid
import time
import base64
import requests
from flask import Flask, request, jsonify

from dotenv import load_dotenv

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.exceptions import InvalidSignature


load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL")
AUTH_TOKEN = os.getenv("AUTH_TOKEN")
POS_ID = os.getenv("POS_ID")
TEST_CUSTOMER_PHONE = os.getenv("TEST_CUSTOMER_PHONE")
CURRENCY = os.getenv("CURRENCY")

IUTE_PUBLIC_KEY_URL = f"{API_BASE_URL}/public-key/dev-ALB-public-key.pem"


# SETUP
app = Flask(__name__)

# TEST ROUTE
@app.route("/")
def health_check():
    """A simple 'homepage' to show that the server is running."""
    return "<h1>The Iute Integration Server is running.</h1><p>This page is just a health check. The real endpoints are at /iute/confirmation and /iute/cancellation.</p>"



# SIGNATURE VERIFICATION 

def verify_iute_signature(body, signature_header, timestamp_header):
    try:
        response = requests.get(IUTE_PUBLIC_KEY_URL)
        response.raise_for_status() 
        public_key_pem = response.content
        
        public_key = load_pem_public_key(public_key_pem, backend=default_backend())
        signature = base64.b64decode(signature_header)
        message = body + timestamp_header.encode('utf-8')

        public_key.verify(
            signature,
            message,
            padding.PKCS1v15(),
            hashes.SHA256()
        )
        print("Signature verification successful!")
        return True
    except InvalidSignature:
        print("ERROR: Invalid signature!")
        return False
    except Exception as e:
        print(f"ERROR: An error occurred during signature verification: {e}")
        return False



# API ENDPOINT (to be called by POS)

@app.route('/create_iute_payment', methods=['POST'])
def create_iute_payment():
    data = request.get_json()
    if not data or 'amount' not in data:
        return jsonify({"error": "Missing 'amount' in request body"}), 400

    total_amount = data['amount']
    order_id = str(uuid.uuid4())

    api_url = f"{API_BASE_URL}/api/v1/physical-api-partners/order"
    
    headers = {
        "Authorization": AUTH_TOKEN,
        "Content-Type": "application/json"
    }

    payload = {
        "myiutePhone": TEST_CUSTOMER_PHONE,
        "orderId": order_id,
        "totalAmount": total_amount,
        "currency": CURRENCY,
        "merchant": {
            "posIdentifier": POS_ID,
            "salesmanIdentifier": "cashier-01" 
        }
    }

    print(f">>>Sending Create Order request to Iute for Order ID: {order_id}")
    print(f"Payload: {payload}")

    try:
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status()
        
        iute_response_data = response.json()
        print(f"+++Iute Response: {iute_response_data}")

        return jsonify({
            "status": "success",
            "message": "Payment initiated. Waiting for customer to approve in MyIute app.",
            "orderId": order_id,
            "iute_response": iute_response_data
        }), 200

    except requests.exceptions.RequestException as e:
        print(f"xxxERROR calling Iute API: {e}")
        if e.response:
            print(f"Response Body: {e.response.text}")
        return jsonify({"error": "Failed to communicate with Iute API"}), 500



# WEBHOOK ENDPOINTS

@app.route('/iute/confirmation', methods=['POST'])
def iute_confirmation_webhook():
    print("\nReceived a request on /iute/confirmation...")
    signature = request.headers.get('x-iute-signature')
    timestamp = request.headers.get('x-iute-timestamp')
    raw_body = request.get_data()
    if not signature or not timestamp:
        return jsonify({"error": "Missing signature headers"}), 400
    if not verify_iute_signature(raw_body, signature, timestamp):
        return jsonify({"status": "error", "message": "Invalid signature"}), 400
    data = request.get_json()
    order_id = data.get('orderId')
    print(f"+++PAYMENT CONFIRMED for Order ID: {order_id}")
    return jsonify({"status": "received"}), 200


@app.route('/iute/cancellation', methods=['POST'])
def iute_cancellation_webhook():
    print("\nReceived a request on /iute/cancellation...")
    signature = request.headers.get('x-iute-signature')
    timestamp = request.headers.get('x-iute-timestamp')
    raw_body = request.get_data()
    if not signature or not timestamp:
        return jsonify({"xxxerror": "Missing signature headers"}), 400
    if not verify_iute_signature(raw_body, signature, timestamp):
        return jsonify({"status": "error", "message": "Invalid signature"}), 400
    data = request.get_json()
    order_id = data.get('orderId')
    reason = data.get('description')
    print(f"XXX PAYMENT CANCELLED for Order ID: {order_id}. Reason: {reason}")
    return jsonify({"status": "received"}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)