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

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL").strip()
AUTH_TOKEN = os.getenv("AUTH_TOKEN").strip()
POS_ID = os.getenv("POS_ID").strip()

IUTE_PUBLIC_KEY_URL = f"{API_BASE_URL}/public-key/dev-ALB-public-key.pem"

app = Flask(__name__)

template = {
    "swagger": "2.0",
    "info": {
        "title": "POS to Iute Integration API",
        "description": "API service to act as a bridge between the POS system and the Iute payment gateway.",
        "version": "1.4.0"
    },
    "host": "iute-integration-service-341272241059.europe-west8.run.app",
    "basePath": "/",
    "schemes": [
        "https"
    ],
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
    return "<h1>The Iute Integration Server is running.</h1><p>API documentation is available at /apidocs</p>"


def verify_iute_signature(body, signature_header, timestamp_header):
    try:
        response = requests.get(IUTE_PUBLIC_KEY_URL)
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


@app.route('/create_or_update_payment', methods=['POST'])
def create_or_update_payment():
    """
    Create or Update an Iute Payment Request
    This endpoint creates a new transaction or updates an existing one in the Iute system.

    -To create a new order, omit the `orderId` field.
      Continue to fill all other required fields.

    -To update an existing order, provide the `orderId` of the order to be updated.
      You can update the `amount`, `customerPhone`, `salesmanIdentifier`, and `currency` fields or other optional fields.
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
            - amount
            - customerPhone
            - salesmanIdentifier
            - currency
          properties:
            orderId:
              type: string
              description: "(Optional) Provide an existing orderId to update an order. If omitted, a new order will be created."
            amount:
              type: number
              format: float
              description: "Mandatory. The total amount of the transaction."
            customerPhone:
              type: string
              description: "Mandatory. The customer's phone number in international format."
            salesmanIdentifier:
              type: string
              description: "Mandatory. The unique identifier for the cashier."
            currency:
              type: string
              description: "Mandatory. The 3-letter ISO currency code."
              enum: ["EUR", "ALL", "MDL", "MKD"]
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
              description: "(Optional) Customer IDPN / PIN number."
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
    """
    data = request.get_json()
    
    required_fields = ['amount', 'customerPhone', 'salesmanIdentifier', 'currency']
    if not data or not all(field in data for field in required_fields):
        error_msg = f"Request body must include all required fields: {', '.join(required_fields)}"
        app.logger.warning(f"Bad request received: {error_msg} - Data: {data}")
        return jsonify({"error": error_msg}), 400

    currency = data['currency']
    if not isinstance(currency, str) or currency.upper() not in {"EUR", "ALL", "MDL", "MKD"}:
        error_msg = f"Invalid currency provided: '{currency}'. Supported currencies are: EUR, ALL, MDL, MKD"
        app.logger.warning(f"Bad request received: {error_msg}")
        return jsonify({"error": error_msg}), 400

    order_id = data.get('orderId', str(uuid.uuid4()))
    total_amount = data['amount']
    customer_phone = data['customerPhone']
    salesman = data['salesmanIdentifier']

    api_url = f"{API_BASE_URL}/api/v1/physical-api-partners/order"
    
    headers = { "Authorization": AUTH_TOKEN, "Content-Type": "application/json" }
  
    payload = {
        "myiutePhone": customer_phone,
        "orderId": order_id,
        "totalAmount": total_amount,
        "currency": currency.upper(),
        "merchant": {
            "posIdentifier": POS_ID,
            "salesmanIdentifier": salesman,
            "userConfirmationUrl": data.get("userConfirmationUrl"),
            "userCancelUrl": data.get("userCancelUrl")
        },
        "shippingAmount": data.get("shippingAmount"),
        "subtotal": data.get("subtotal"),
        "taxAmount": data.get("taxAmount"),
        "userPin": data.get("userPin"),
        "birthday": data.get("birthday"),
        "gender": data.get("gender"),
        "shipping": data.get("shipping"),
        "billing": data.get("billing"),
        "items": data.get("items"),
        "discounts": data.get("discounts"),
        "metadata": data.get("metadata")
    }

    app.logger.info(f"Sending Create/Update Order request to Iute for Order ID: {order_id}")
    app.logger.info(f"Payload: {payload}")

    try:
        response = requests.post(api_url, headers=headers, json=payload)
        response.raise_for_status()
        
        iute_response_data = response.json()
        app.logger.info(f"Iute Response: {iute_response_data}")

        return jsonify({
            "status": "success",
            "message": "Payment request sent successfully. Waiting for customer to approve in MyIute app.",
            "orderId": order_id,
            "iute_response": iute_response_data
        }), 200

    except requests.exceptions.RequestException as e:
        app.logger.error(f"ERROR calling Iute API: {e}")
        if e.response is not None:
            app.logger.error(f"Response Body: {e.response.text}")
        return jsonify({"error": "Failed to communicate with Iute API"}), 500

@app.route('/payment_status/<string:order_id>', methods=['GET'])
def check_order_status(order_id):
    """
    Check Order Status
    Retrieves the current status of a specific order from the Iute system.
    It requires the `orderId` as a path parameter.
    ---
    tags:
      - Payments
    parameters:
      - name: order_id
        in: path
        type: string
        required: true
        description: The unique ID of the order to check.
    responses:
      200:
        description: Status retrieved successfully.
        schema:
          type: object
          properties:
            orderId:
              type: string
            status:
              type: string
              example: "PAID"
      404:
        description: The requested orderId was not found in the Iute system.
      500:
        description: Internal Server Error. Failed to communicate with Iute API.
    """
    app.logger.info(f"Checking status for Order ID: {order_id}")

    api_url = f"{API_BASE_URL}/api/v1/physical-api-partners/orders/{order_id}/order-status"
    headers = { "Authorization": AUTH_TOKEN }

    try:
        response = requests.get(api_url, headers=headers)
        response.raise_for_status()

        status_data = response.json()
        app.logger.info(f"Status for Order ID {order_id}: {status_data}")
        return jsonify(status_data), 200

    except requests.exceptions.RequestException as e:
        app.logger.error(f"ERROR calling Iute status API for Order ID {order_id}: {e}")
        if e.response is not None:
            app.logger.error(f"Response Body: {e.response.text}")
            if e.response.status_code == 404:
                return jsonify({"error": f"Order with ID '{order_id}' not found."}), 404
        return jsonify({"error": "Failed to communicate with Iute API"}), 500


@app.route('/iute/confirmation', methods=['POST'])
def iute_confirmation_webhook():
    """
    Iute Payment Confirmation Webhook
    This endpoint is called by Iute's servers when a payment is successfully completed. **DO NOT CALL MANUALLY.**
    ---
    tags:
      - Webhooks
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
    responses:
      200:
        description: Webhook received and acknowledged.
      400:
        description: Webhook request was malformed or had an invalid signature.
    """
    app.logger.info("Received a request on /iute/confirmation...")
    signature = request.headers.get('x-iute-signature')
    timestamp = request.headers.get('x-iute-timestamp')
    raw_body = request.get_data()
    if not signature or not timestamp:
        app.logger.warning("Confirmation request missing signature headers.")
        return jsonify({"error": "Missing signature headers"}), 400
    if not verify_iute_signature(raw_body, signature, timestamp):
        app.logger.warning("Confirmation request had an invalid signature.")
        return jsonify({"status": "error", "message": "Invalid signature"}), 400
    data = request.get_json()
    order_id = data.get('orderId')
    app.logger.info(f"PAYMENT CONFIRMED for Order ID: {order_id}")
    return jsonify({"status": "received"}), 200


@app.route('/iute/cancellation', methods=['POST'])
def iute_cancellation_webhook():
    """
    Iute Payment Cancellation Webhook
    This endpoint is called by Iute's servers when a payment is cancelled or rejected. **DO NOT CALL MANUALLY.**
    ---
    tags:
      - Webhooks
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
    responses:
      200:
        description: Webhook received and acknowledged.
      400:
        description: Webhook request was malformed or had an invalid signature.
    """
    app.logger.info("Received a request on /iute/cancellation...")
    signature = request.headers.get('x-iute-signature')
    timestamp = request.headers.get('x-iute-timestamp')
    raw_body = request.get_data()
    if not signature or not timestamp:
        app.logger.warning("Cancellation request missing signature headers.")
        return jsonify({"error": "Missing signature headers"}), 400
    if not verify_iute_signature(raw_body, signature, timestamp):
        app.logger.warning("Cancellation request had an invalid signature.")
        return jsonify({"status": "error", "message": "Invalid signature"}), 400
    data = request.get_json()
    order_id = data.get('orderId')
    reason = data.get('description')
    app.logger.warning(f"PAYMENT CANCELLED for Order ID: {order_id}. Reason: {reason}")
    return jsonify({"status": "received"}), 200