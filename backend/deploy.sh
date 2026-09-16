#!/bin/bash

# Portfolio Tracker - Cloud Run Deployment Script
# This script deploys your FastAPI application to Google Cloud Run

set -e  # Exit on error
cd "$(dirname "$0")"  # always build from backend/

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Portfolio Tracker - Cloud Run Deployment${NC}"
echo -e "${BLUE}========================================${NC}\n"

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}Error: gcloud CLI is not installed${NC}"
    echo "Please install it from: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Configuration
PROJECT_ID="${1:-}"
SERVICE_NAME="portfolio-tracker"
REGION="asia-southeast1"  # Singapore region
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}"

# Check if PROJECT_ID was provided
if [ -z "$PROJECT_ID" ]; then
    echo -e "${YELLOW}Usage: ./deploy.sh YOUR_PROJECT_ID${NC}"
    echo ""
    echo "Available projects:"
    gcloud projects list
    exit 1
fi

echo -e "${GREEN}✓${NC} Using project: ${PROJECT_ID}"
echo -e "${GREEN}✓${NC} Service name: ${SERVICE_NAME}"
echo -e "${GREEN}✓${NC} Region: ${REGION}\n"

# Set the active project
echo -e "${BLUE}Setting active project...${NC}"
gcloud config set project ${PROJECT_ID}

# Enable required APIs
echo -e "\n${BLUE}Enabling required APIs...${NC}"
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable containerregistry.googleapis.com

# Build the container image
echo -e "\n${BLUE}Building container image...${NC}"
gcloud builds submit --tag ${IMAGE_NAME}

# Deploy to Cloud Run
echo -e "\n${BLUE}Deploying to Cloud Run...${NC}"
gcloud run deploy ${SERVICE_NAME} \
  --image ${IMAGE_NAME} \
  --platform managed \
  --region ${REGION} \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --timeout 300 \
  --max-instances 10 \
  --set-env-vars "DATABASE_URL=${DATABASE_URL}" \
  --set-env-vars "SYNC_DATABASE_URL=${SYNC_DATABASE_URL}" \
  --set-env-vars "SECRET_KEY=${SECRET_KEY}" \
  --set-env-vars "SMTP_HOST=${SMTP_HOST:-smtp.gmail.com}" \
  --set-env-vars "SMTP_PORT=${SMTP_PORT:-587}" \
  --set-env-vars "SMTP_USER=${SMTP_USER}" \
  --set-env-vars "SMTP_PASSWORD=${SMTP_PASSWORD}" \
  --set-env-vars "EMAIL_FROM=${EMAIL_FROM}"

# Get the service URL
echo -e "\n${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Successful!${NC}"
echo -e "${GREEN}========================================${NC}\n"

SERVICE_URL=$(gcloud run services describe ${SERVICE_NAME} --region ${REGION} --format 'value(status.url)')
echo -e "${GREEN}✓${NC} Service URL: ${SERVICE_URL}"
echo -e "${GREEN}✓${NC} API Docs: ${SERVICE_URL}/docs"
echo -e "${GREEN}✓${NC} Health Check: ${SERVICE_URL}/"

echo -e "\n${YELLOW}Note:${NC} Make sure to configure your database connection strings as secrets or environment variables."
echo -e "${YELLOW}Note:${NC} Update CORS origins in main.py to include: ${SERVICE_URL}"
