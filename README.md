# POS to Iute Integration API Service

## 1. Project Overview

This project is a Python Flask backend service that acts as a secure bridge between a POS system and the Iute payment gateway. It exposes a simple REST API to initiate payments and includes webhook endpoints to receive real-time status updates (confirmation/cancellation) from Iute's servers.

The service is designed to be deployed as a scalable, serverless container on Google Cloud Run.

### Key Features

*   **Create Payments:** A single endpoint (`/create_iute_payment`) for the POS to initiate a transaction.
*   **Secure Webhooks:** Endpoints (`/iute/confirmation`, `/iute/cancellation`) to securely receive callbacks from Iute.
*   **Signature Verification:** Automatically verifies incoming webhook requests to ensure they are authentic and untampered.
*   **API Documentation:** Interactive API documentation is automatically generated and available at the `/apidocs` endpoint, powered by Swagger/Flasgger.
*   **Production-Ready:** Implements best practices such as environment-based configuration, production-grade logging, and containerization for deployment.

---

## 2. Technology Stack

*   **Backend:** Python 3, Flask
*   **API Documentation:** Flasgger (Swagger UI)
*   **WSGI Server:** Gunicorn
*   **Deployment Platform:** Google Cloud Run, Google Cloud Build, Google Secret Manager
*   **Containerization:** Docker

---

## 3. Local Development Setup

Follow these steps to run the application on your local machine for development and testing.

### Prerequisites

*   Python 3.9+
*   A tool to make API requests (e.g., Postman)

### Step-by-Step Instructions

1.  **Clone the Repository:**
    ```bash
    git clone <your-repository-url>
    cd iute_integration
    ```

2.  **Create and Activate a Virtual Environment:**
    ```bash
    # For Windows
    python -m venv venv
    .\venv\Scripts\activate

    # For macOS/Linux
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install Dependencies:**
    Install all the required Python libraries from the `requirements.txt` file.
    ```bash
    pip install -r requirements.txt
    ```

4.  **Create the `.env` File:**
    This file stores your secret credentials for local development. Create a file named `.env` in the root of the project and add your test credentials:
    ```ini
    API_BASE_URL=https://partner-api-dev.iute.al
    AUTH_TOKEN=your_test_auth_token_here
    POS_ID=your_test_pos_id_here
    ```

5.  **Run the Development Server:**
    Start the local Flask server.
    ```bash
    flask run --host=0.0.0.0
    ```
    The server will be running at `http://127.0.0.1:5000`.

---

## 4. API Documentation & Testing

Once the server is running locally, you can access the interactive Swagger API documentation in your browser:

*   **URL:** `http://127.0.0.1:5000/apidocs`

You can use the "Try it out" feature on this page to send test requests directly to your local server.

---

## 5. Deployment to Google Cloud Run

This application is designed to be deployed as a serverless container on Google Cloud Run. The deployment process is managed by the Google Cloud SDK (`gcloud`).

### Deployment Prerequisites

1.  A Google Cloud Project with billing enabled.
2.  The [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) installed and initialized (`gcloud init`).
3.  The following Google Cloud APIs enabled in your project:
    *   Cloud Run API (`run.googleapis.com`)
    *   Cloud Build API (`cloudbuild.googleapis.com`)
    *   Secret Manager API (`secretmanager.googleapis.com`)
    *   Artifact Registry API (`artifactregistry.googleapis.com`)

### Deployment Steps

1.  **Store Secrets in Google Secret Manager:**
    Instead of using a `.env` file, production secrets are securely stored in Secret Manager.
    ```bash
    # Set your project
    gcloud config set project <your-gcp-project-id>

    # Create secrets
    echo "https://partner-api.iute.al" | gcloud secrets create IUTE_API_BASE_URL --data-file=-
    echo "your_production_auth_token" | gcloud secrets create IUTE_AUTH_TOKEN --data-file=-
    echo "your_production_pos_id" | gcloud secrets create IUTE_POS_ID --data-file=-
    ```

2.  **Grant Permissions:**
    The Cloud Run service needs permission to access the secrets. This command grants the "Secret Manager Secret Accessor" role to the service's identity.
    ```bash
    # Note: Replace <project-number> with your actual GCP project number
    gcloud projects add-iam-policy-binding <your-gcp-project-id> \
        --member="serviceAccount:<project-number>-compute@developer.gserviceaccount.com" \
        --role="roles/secretmanager.secretAccessor"
    ```

3.  **Deploy the Service:**
    Navigate to the project's root directory and run the following command. This command tells Cloud Build to use the `Dockerfile` to build a container, push it to the Artifact Registry, and deploy it to Cloud Run, injecting the secrets as environment variables.
    ```bash
    gcloud run deploy iute-integration-service \
      --source . \
      --region <your-chosen-region> \
      --allow-unauthenticated \
      --update-secrets=API_BASE_URL=IUTE_API_BASE_URL:latest \
      --update-secrets=AUTH_TOKEN=IUTE_AUTH_TOKEN:latest \
      --update-secrets=POS_ID=IUTE_POS_ID:latest
    ```

4.  **Finalize Integration:**
    Once deployed, `gcloud` will provide a permanent **Service URL**. The webhook endpoints at this URL must be provided to Iute to complete the integration.
    *   **Confirmation URL:** `https://<service-url>/iute/confirmation`
    *   **Cancellation URL:** `https://<service-url>/iute/cancellation`
