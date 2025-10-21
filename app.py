import os
import uuid
import base64
import requests
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from flasgger import Swagger
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.exceptions import InvalidSignature

from supabase import create_client, Client
from datetime import datetime
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from functools import wraps

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL").strip()
AUTH_TOKEN = os.getenv("AUTH_TOKEN").strip()
POS_ID = os.getenv("POS_ID").strip()
IUTE_PUBLIC_KEY_URL = f"{API_BASE_URL}/public-key/dev-ALB-public-key.pem"

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


CLOUD_RUN_SERVICE_URL = "https://iute-integration-service-341272241059.europe-west8.run.app"
google_request = google_requests.Request()

def token_required(f):
    """Decorator to ensure a valid Google OIDC ID token is present."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return jsonify({"error": "Authorization header is missing"}), 401
        
        parts = auth_header.split()
        if parts[0].lower() != "bearer" or len(parts) != 2:
            return jsonify({"error": "Invalid Authorization header format. Expected 'Bearer <token>'"}), 401
            
        token = parts[1]
        
        try:
            id_info = id_token.verify_oauth2_token(
                token, google_request, audience=CLOUD_RUN_SERVICE_URL
            )
            
        except ValueError as e:
            app.logger.error(f"Token verification failed: {e}")
            return jsonify({"error": "Invalid or expired token"}), 401
            
        return f(*args, **kwargs)
    return decorated_function


app = Flask(__name__)

template = {
    "swagger": "2.0",
    "info": {
        "title": "POS to Iute Integration API",
        "description": "API service to act as a bridge between the POS system and the Iute payment gateway, with database persistence.",
        "version": "1.5.0"
    },
    "host": "iute-integration-service-341272241059.europe-west8.run.app",
    "basePath": "/",
    "schemes": ["https"],
}
swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": 'apispec_1',
            "route": '/apispec_1.json',
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/apidocs/"
}
swagger = Swagger(app, template=template, config=swagger_config)


if __name__ != '__main__':
    handler = RotatingFileHandler('app.log', maxBytes=100000, backupCount=5)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


@app.route("/")
def health_check():
    """Provides a simple health check endpoint."""
    return "<h1>The Iute Integration Server is running.</h1><p>API documentation is available at /apidocs</p>"


def verify_iute_signature(body, signature_header, timestamp_header):
    """Verifies the webhook signature from Iute using their public key."""
    if not all([body, signature_header, timestamp_header]):
        app.logger.error("Signature verification failed: Missing headers or body.")
        return False
    try:
        response = requests.get(IUTE_PUBLIC_KEY_URL, timeout=10)
        response.raise_for_status()
        public_key_pem = response.content

        public_key = load_pem_public_key(public_key_pem, backend=default_backend())
        signature = base64.b64decode(signature_header)
        message = body + timestamp_header.encode('utf-8')

        public_key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())

        app.logger.info("Signature verification successful!")
        return True
    except InvalidSignature:
        app.logger.error("Signature verification failed: Invalid signature!")
        return False
    except Exception as e:
        app.logger.error(f"An error occurred during signature verification: {e}")
        return False

def db_update_order_status(order_id: str, status: str, reason: str = None):
    """
    Updates the status of an order in the Supabase database.
    This function handles all status updates to ensure consistency.
    """
    try:
        update_data = {"status": status}
        if reason:
            update_data["cancellation_reason"] = reason
        
        supabase.table("orders").update(update_data).eq("order_id", order_id).execute()
        app.logger.info(f"Database status for Order ID {order_id} updated to {status}.")
        return True
    except Exception as e:
        app.logger.error(f"Failed to update database for Order ID {order_id}: {e}")
        return False


@app.route('/create_or_update_payment', methods=['POST'])
@token_required
def create_or_update_payment():
    """
    Create or Update an Iute Payment Request.
    (Full Swagger documentation is parsed from this docstring)
    ---
    tags:
      - Payments
    parameters:
      - name: body
        in: body
        required: true
        schema:
          id: PaymentData
          type: object
          required:
            - totalAmount
            - myiutePhone
            - currency
            - merchant
          properties:
            myiutePhone:
              type: string
              description: "Mandatory. The customer's phone number in international format."
            orderId:
              type: string
              description: "(Optional) Provide an existing orderId to update an order. If omitted, a new order will be created."
            totalAmount:
              type: number
              format: float
              description: "Mandatory. The total amount of the transaction."
            currency:
              type: string
              description: "Mandatory. The 3-letter ISO currency code."
              enum: ["EUR", "ALL", "MDL", "MKD"]
            merchant:
              type: object
              required:
                - salesmanIdentifier
              properties:
                salesmanIdentifier:
                  type: string
                  description: "Mandatory. The unique identifier for the cashier."
                userConfirmationUrl:
                  type: string
                  description: "(Optional) Merchant webhook confirmation URL."
                userCancelUrl:
                  type: string
                  description: "(Optional) Merchant webhook cancel URL."
            shippingAmount:
              type: number
              format: float
              description: "(Optional) Order shipping amount. Must be positive."
            subtotal:
              type: number
              format: float
              description: "(Optional) Order subtotal amount. Must be positive."
            taxAmount:
              type: number
              format: float
              description: "(Optional) Order tax amount. Must be positive."
            userPin:
              type: string
              description: "(Optional) Customer IDPN / PIN number. This is NOT stored in the database."
            birthday:
              type: string
              description: "(Optional) Customer birthday in dd.MM.yyyy format."
              example: "31.12.1990"
            gender:
              type: string
              description: "(Optional) Customer gender."
              enum: ["MALE", "FEMALE"]
            shipping:
              type: object
              description: "(Optional) Customer shipping information and address object."
            billing:
              type: object
              description: "(Optional) Customer billing information and address object."
            items:
              type: array
              description: "(Optional) Shopping cart items."
              items:
                type: object
                properties:
                  id:
                    type: string
                    description: "Product ID."
                  displayName:
                    type: string
                    description: "Product name."
                  sku:
                    type: string
                    description: "Product SKU."
                  unitPrice:
                    type: number
                    format: float
                    description: "Single unit price."
                  qty:
                    type: integer
                    description: "Quantity."
                  itemImageUrl:
                    type: string
                    description: "HTTP address of the product image."
                  itemUrl:
                    type: string
                    description: "HTTP address of the product page."
            discounts:
              type: object
              description: "(Optional) Free format key-value model about discounts."
            metadata:
              type: object
              description: "(Optional) Free format key-value model about metadata."
    responses:
      200:
        description: Payment request created/updated successfully.
      400:
        description: Bad Request. Required fields are missing or a field has an invalid value.
      500:
        description: Internal Server Error. Failed to communicate with Iute API.
      502:
        description: "Bad Gateway. The request was successfully sent to the Iute API, but the upstream service rejected it with an error."
    """
    data = request.get_json()

    if not data:
        return jsonify({"error": "Request body must be a valid JSON."}), 400

    missing_fields = []
    if 'totalAmount' not in data: missing_fields.append('totalAmount')
    if 'myiutePhone' not in data: missing_fields.append('myiutePhone')
    if 'currency' not in data: missing_fields.append('currency')
    if 'merchant' not in data or 'salesmanIdentifier' not in data.get('merchant', {}):
        missing_fields.append('merchant.salesmanIdentifier')

    if missing_fields:
        error_msg = f"Request body must include all required fields: {', '.join(missing_fields)}"
        return jsonify({"error": error_msg}), 400
    
    orderId = data.get('orderId', str(uuid.uuid4()))
    
    payload = data.copy()
    payload['orderId'] = orderId
    payload['merchant']['posIdentifier'] = POS_ID
    
    api_url = f"{API_BASE_URL}/api/v1/physical-api-partners/order"
    headers = { "Authorization": AUTH_TOKEN, "Content-Type": "application/json" }

    app.logger.info(f"Sending Create/Update Order request to Iute for Order ID: {orderId}")

    try:

        response = requests.post(api_url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        iute_response_data = response.json()
        app.logger.info(f"Iute Response for {orderId}: {iute_response_data}")

        try:
            birthday_str = data.get("birthday")
            birthday_db_format = None
            if birthday_str:
                try: 
                    birthday_db_format = datetime.strptime(birthday_str, "%d.%m.%Y").strftime("%Y-%m-%d")
                except ValueError:
                    app.logger.warning(f"Invalid birthday format for order {orderId}. Storing as NULL.")

            order_data_to_save = {
                "order_id": orderId,
                "status": "PENDING",
                "total_amount": data.get("totalAmount"),
                "currency": data.get("currency"),
                "subtotal": data.get("subtotal"),
                "shipping_amount": data.get("shippingAmount"),
                "tax_amount": data.get("taxAmount"),
                "customer_phone": data.get("myiutePhone"),
                "birthday": birthday_db_format,
                "gender": data.get("gender"),
                "salesman_identifier": data.get("merchant", {}).get("salesmanIdentifier"),
                "user_confirmation_url": data.get("merchant", {}).get("userConfirmationUrl"),
                "user_cancel_url": data.get("merchant", {}).get("userCancelUrl"),
                "shipping_info": data.get("shipping"),
                "billing_info": data.get("billing"),
                "items": data.get("items", []),
                "discounts": data.get("discounts"),
                "metadata": data.get("metadata"),
                "iute_response": iute_response_data
            }
            
            supabase.table("orders").upsert(order_data_to_save).execute()
            app.logger.info(f"Order {orderId} with its items upserted to the database.")

        except Exception as db_error:
            app.logger.error(f"DATABASE ERROR for order {orderId}: {db_error}")

        return jsonify({
            "status": "success", "message": "Payment request sent successfully.",
            "orderId": orderId, "iute_response": iute_response_data
        }), 200

    except requests.exceptions.RequestException as e:
        app.logger.error(f"ERROR calling Iute API: {e}")
        if e.response is not None:
            return jsonify({ "error": "Iute API rejected the request.", "iute_status_code": e.response.status_code, "iute_response": e.response.json() if 'application/json' in e.response.headers.get('content-type', '') else e.response.text }), 502
        return jsonify({"error": "Failed to communicate with Iute API"}), 500
    

@app.route('/payment_status/<string:order_id>', methods=['GET'])
@token_required
def check_order_status(order_id):
    """
    Check Order Status.
    ---
    tags:
      - Payments
    ... (rest of your swagger spec from the prompt) ...
    """
    app.logger.info(f"Checking status for Order ID: {order_id}")

    api_url = f"{API_BASE_URL}/api/v1/physical-api-partners/orders/{order_id}/status?orderId={order_id}"
    headers = { "Authorization": AUTH_TOKEN }

    try:
        response = requests.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        status_data = response.json()
        app.logger.info(f"Status for Order ID {order_id}: {status_data}")


        if status_data.get("status"):
            db_update_order_status(order_id, status_data["status"])

        return jsonify(status_data), 200

    except requests.exceptions.RequestException as e:
        app.logger.error(f"ERROR calling Iute status API for Order ID {order_id}: {e}")
        if e.response is not None:
            if e.response.status_code == 404:
                return jsonify({"error": f"Order with ID '{order_id}' not found."}), 404
            try: iute_json_response = e.response.json()
            except ValueError: iute_json_response = e.response.text
            return jsonify({ "error": "Upstream Iute API returned an error.", "iute_status_code": e.response.status_code, "iute_response": iute_json_response }), 502
        return jsonify({"error": "Failed to communicate with Iute API"}), 500


@app.route('/iute/confirmation', methods=['POST'])
def iute_confirmation_webhook():
    """
    Iute Payment Confirmation Webhook.
    ---
    tags:
      - Webhooks
    ... (rest of your swagger spec from the prompt) ...
    """
    app.logger.info("Received a request on /iute/confirmation...")
    if not verify_iute_signature(request.get_data(), request.headers.get('x-iute-signature'), request.headers.get('x-iute-timestamp')):
        return jsonify({"status": "error", "message": "Invalid signature"}), 400

    data = request.get_json()
    order_id = data.get('orderId')
    app.logger.info(f"PAYMENT CONFIRMED for Order ID: {order_id}")


    if order_id:
        db_update_order_status(order_id, "CONFIRMED")
    
    return jsonify({"status": "received"}), 200


@app.route('/iute/cancellation', methods=['POST'])
def iute_cancellation_webhook():
    """
    Iute Payment Cancellation Webhook.
    ---
    tags:
      - Webhooks
    ... (rest of your swagger spec from the prompt) ...
    """
    app.logger.info("Received a request on /iute/cancellation...")
    if not verify_iute_signature(request.get_data(), request.headers.get('x-iute-signature'), request.headers.get('x-iute-timestamp')):
        return jsonify({"status": "error", "message": "Invalid signature"}), 400
        
    data = request.get_json()
    order_id = data.get('orderId')
    reason = data.get('description')
    app.logger.warning(f"PAYMENT CANCELLED for Order ID: {order_id}. Reason: {reason}")


    if order_id:
        db_update_order_status(order_id, "CANCELLED", reason)

    return jsonify({"status": "received"}), 200