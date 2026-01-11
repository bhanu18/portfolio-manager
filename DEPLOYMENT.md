# 🚀 Cloud Run Deployment Guide

Complete guide for deploying Portfolio Tracker API to Google Cloud Run.

---

## 📋 Prerequisites

Before deploying, ensure you have:

1. **Google Cloud Account**
   - Create one at: https://cloud.google.com/
   - Enable billing for your project

2. **Google Cloud SDK (gcloud CLI)**
   - Install from: https://cloud.google.com/sdk/docs/install
   - Verify: `gcloud --version`

3. **Docker** (for local testing)
   - Install from: https://docs.docker.com/get-docker/
   - Verify: `docker --version`

4. **PostgreSQL Database** (for production)
   - Google Cloud SQL (recommended)
   - Or any other PostgreSQL hosting service

---

## 🛠️ Setup Steps

### 1. Install and Configure gcloud CLI

```bash
# Install gcloud CLI (if not installed)
# Follow instructions at: https://cloud.google.com/sdk/docs/install

# Initialize gcloud
gcloud init

# Login to your Google account
gcloud auth login

# Create a new project (or use existing)
gcloud projects create YOUR_PROJECT_ID --name="Portfolio Tracker"

# Set the project as default
gcloud config set project YOUR_PROJECT_ID

# Enable required APIs
gcloud services enable cloudbuild.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable containerregistry.googleapis.com
gcloud services enable sqladmin.googleapis.com
```

---

### 2. Set Up Cloud SQL (PostgreSQL Database)

#### Option A: Using Google Cloud Console (Easier)

1. Go to: https://console.cloud.google.com/sql
2. Click "CREATE INSTANCE"
3. Choose "PostgreSQL"
4. Configure:
   - **Instance ID**: `portfolio-tracker-db`
   - **Password**: Set a strong password
   - **Region**: `asia-southeast1` (Singapore)
   - **Machine type**: `db-f1-micro` (for testing) or `db-n1-standard-1` (production)
5. Click "CREATE INSTANCE" (takes ~10 minutes)

#### Option B: Using gcloud CLI

```bash
# Create Cloud SQL instance
gcloud sql instances create portfolio-tracker-db \
    --database-version=POSTGRES_14 \
    --tier=db-f1-micro \
    --region=asia-southeast1

# Set root password
gcloud sql users set-password postgres \
    --instance=portfolio-tracker-db \
    --password=YOUR_STRONG_PASSWORD

# Create database
gcloud sql databases create portfolio_tracker \
    --instance=portfolio-tracker-db
```

#### Get Database Connection String

```bash
# Get the connection name
gcloud sql instances describe portfolio-tracker-db \
    --format='value(connectionName)'

# Output will be: YOUR_PROJECT_ID:asia-southeast1:portfolio-tracker-db
```

**Database URLs:**
```
# For Cloud Run (using Unix socket)
DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@/portfolio_tracker?host=/cloudsql/YOUR_PROJECT_ID:asia-southeast1:portfolio-tracker-db

# For sync operations
SYNC_DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@/portfolio_tracker?host=/cloudsql/YOUR_PROJECT_ID:asia-southeast1:portfolio-tracker-db
```

---

### 3. Configure Environment Variables

Create a `.env.production` file with your production secrets:

```bash
# Database
DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@/portfolio_tracker?host=/cloudsql/YOUR_CONNECTION_NAME
SYNC_DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@/portfolio_tracker?host=/cloudsql/YOUR_CONNECTION_NAME
TEST_DATABASE_URL=postgresql+asyncpg://postgres:test@localhost:5432/test_portfolio

# Security
SECRET_KEY=your-super-secret-key-min-32-chars-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Email
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
EMAIL_FROM=your-email@gmail.com
EMAIL_FROM_NAME=Portfolio Tracker
```

**⚠️ IMPORTANT:** Generate a strong SECRET_KEY:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

### 4. Deploy Using the Deploy Script (Recommended)

The easiest way to deploy:

```bash
# Export environment variables
export DATABASE_URL="your-database-url"
export SYNC_DATABASE_URL="your-sync-database-url"
export SECRET_KEY="your-secret-key"
export SMTP_USER="your-email@gmail.com"
export SMTP_PASSWORD="your-app-password"
export EMAIL_FROM="your-email@gmail.com"

# Run the deployment script
./deploy.sh YOUR_PROJECT_ID
```

---

### 5. Manual Deployment (Alternative)

If you prefer manual control:

#### Step 5.1: Build the Docker Image

```bash
# Build locally (optional - for testing)
docker build -t portfolio-tracker .

# Test locally (optional)
docker run -p 8080:8080 --env-file .env portfolio-tracker

# Build and push to Google Container Registry
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/portfolio-tracker
```

#### Step 5.2: Deploy to Cloud Run

```bash
gcloud run deploy portfolio-tracker \
  --image gcr.io/YOUR_PROJECT_ID/portfolio-tracker \
  --platform managed \
  --region asia-southeast1 \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --timeout 300 \
  --max-instances 10 \
  --add-cloudsql-instances YOUR_PROJECT_ID:asia-southeast1:portfolio-tracker-db \
  --set-env-vars "DATABASE_URL=${DATABASE_URL}" \
  --set-env-vars "SYNC_DATABASE_URL=${SYNC_DATABASE_URL}" \
  --set-env-vars "SECRET_KEY=${SECRET_KEY}" \
  --set-env-vars "SMTP_HOST=smtp.gmail.com" \
  --set-env-vars "SMTP_PORT=587" \
  --set-env-vars "SMTP_USER=${SMTP_USER}" \
  --set-env-vars "SMTP_PASSWORD=${SMTP_PASSWORD}" \
  --set-env-vars "EMAIL_FROM=${EMAIL_FROM}"
```

---

### 6. Using Cloud Build (CI/CD - Recommended for Production)

For automatic deployments from GitHub:

1. **Connect GitHub Repository**
```bash
# In Google Cloud Console:
# Cloud Build > Triggers > Connect Repository
# Select your GitHub repo
```

2. **Create Build Trigger**
```bash
# The cloudbuild.yaml file is already configured
# Cloud Build will automatically:
# 1. Build the Docker image
# 2. Push to Container Registry
# 3. Deploy to Cloud Run
```

3. **Configure Secrets**
```bash
# Add secrets in Cloud Build settings:
# Cloud Build > Settings > Secret Manager
# Add: DATABASE_URL, SECRET_KEY, SMTP_PASSWORD, etc.
```

---

## 🔧 Post-Deployment Configuration

### 1. Get Your Service URL

```bash
gcloud run services describe portfolio-tracker \
  --region asia-southeast1 \
  --format 'value(status.url)'
```

### 2. Update CORS Configuration

Edit `main.py` and add your Cloud Run URL to allowed origins:

```python
origins = [
    "http://localhost:5173",      # Local dev
    "https://www.paulbespokesuits.com",  # Your frontend
    "https://portfolio-tracker-xxxxx.run.app",  # Your Cloud Run URL
]
```

Redeploy after updating.

### 3. Test Your Deployment

```bash
# Health check
curl https://your-service-url.run.app/

# API documentation
open https://your-service-url.run.app/docs
```

### 4. Run Database Migrations

Migrations run automatically on startup (configured in `main.py`).

To manually run migrations:
```bash
# Connect to Cloud SQL
gcloud sql connect portfolio-tracker-db --user=postgres

# Or run migrations via Cloud Run job
gcloud run jobs create migrate-db \
  --image gcr.io/YOUR_PROJECT_ID/portfolio-tracker \
  --command="alembic,upgrade,head" \
  --region=asia-southeast1
```

---

## 🔐 Security Best Practices

### 1. Use Secret Manager (Recommended)

Instead of environment variables, use Google Secret Manager:

```bash
# Create secrets
echo -n "your-secret-key" | gcloud secrets create SECRET_KEY --data-file=-
echo -n "your-db-password" | gcloud secrets create DB_PASSWORD --data-file=-

# Grant Cloud Run access
gcloud secrets add-iam-policy-binding SECRET_KEY \
  --member=serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com \
  --role=roles/secretmanager.secretAccessor

# Deploy with secrets
gcloud run deploy portfolio-tracker \
  --update-secrets="SECRET_KEY=SECRET_KEY:latest" \
  --update-secrets="DATABASE_PASSWORD=DB_PASSWORD:latest"
```

### 2. Enable HTTPS Only

Cloud Run automatically provides HTTPS. Ensure your frontend always uses `https://` URLs.

### 3. Configure Custom Domain (Optional)

```bash
# Map custom domain
gcloud run domain-mappings create \
  --service portfolio-tracker \
  --domain api.yourdomain.com \
  --region asia-southeast1

# Follow DNS configuration instructions
```

---

## 📊 Monitoring and Logs

### View Logs

```bash
# Real-time logs
gcloud run services logs tail portfolio-tracker --region asia-southeast1

# View in console
open https://console.cloud.google.com/run/detail/asia-southeast1/portfolio-tracker/logs
```

### Monitoring Dashboard

```bash
# Open monitoring dashboard
open https://console.cloud.google.com/run/detail/asia-southeast1/portfolio-tracker/metrics
```

---

## 💰 Cost Optimization

### Free Tier Includes:
- 2 million requests per month
- 360,000 GB-seconds of memory
- 180,000 vCPU-seconds

### Optimize Costs:
```bash
# Set minimum instances to 0 (cold starts but no idle costs)
gcloud run services update portfolio-tracker \
  --min-instances 0 \
  --region asia-southeast1

# Set request timeout
gcloud run services update portfolio-tracker \
  --timeout 60 \
  --region asia-southeast1

# Limit concurrency
gcloud run services update portfolio-tracker \
  --concurrency 80 \
  --region asia-southeast1
```

---

## 🔄 Updating Your Deployment

### Quick Update

```bash
# After code changes, simply run:
./deploy.sh YOUR_PROJECT_ID
```

### Manual Update

```bash
# Build new image
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/portfolio-tracker

# Deploy new version
gcloud run deploy portfolio-tracker \
  --image gcr.io/YOUR_PROJECT_ID/portfolio-tracker \
  --region asia-southeast1
```

---

## 🐛 Troubleshooting

### Check Service Status

```bash
gcloud run services describe portfolio-tracker --region asia-southeast1
```

### Common Issues

**1. Database Connection Failed**
```bash
# Ensure Cloud SQL instance is running
gcloud sql instances describe portfolio-tracker-db

# Check connection string format
# Must use Unix socket: /cloudsql/PROJECT:REGION:INSTANCE
```

**2. Environment Variables Not Set**
```bash
# List current env vars
gcloud run services describe portfolio-tracker \
  --region asia-southeast1 \
  --format 'value(spec.template.spec.containers[0].env)'
```

**3. Container Build Failed**
```bash
# Check build logs
gcloud builds list --limit 5
gcloud builds log BUILD_ID
```

---

## 📚 Additional Resources

- [Cloud Run Documentation](https://cloud.google.com/run/docs)
- [Cloud SQL for PostgreSQL](https://cloud.google.com/sql/docs/postgres)
- [Secret Manager](https://cloud.google.com/secret-manager/docs)
- [Cloud Build](https://cloud.google.com/build/docs)

---

## 🎉 Success Checklist

- [ ] gcloud CLI installed and configured
- [ ] Project created and APIs enabled
- [ ] Cloud SQL database created and configured
- [ ] Environment variables configured
- [ ] Application deployed to Cloud Run
- [ ] CORS origins updated with Cloud Run URL
- [ ] Database migrations completed
- [ ] API endpoints tested
- [ ] Custom domain configured (optional)
- [ ] Monitoring and alerts set up

---

**Your API is now live! 🚀**

Access your API at: `https://portfolio-tracker-xxxxx.run.app`

API Documentation: `https://portfolio-tracker-xxxxx.run.app/docs`
