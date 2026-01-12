# 🚀 Deployment Guide

## Recommended: GitHub to Cloud Run (MySQL)

**👉 See [GITHUB_DEPLOYMENT.md](GITHUB_DEPLOYMENT.md) for complete instructions**

This is the recommended approach for deploying from GitHub with automatic CI/CD.

### Quick Overview:

1. ✅ **Create Google Cloud project**
2. ✅ **Create Cloud SQL MySQL database**
3. ✅ **Create secrets in Secret Manager**
4. ✅ **Connect GitHub repository**
5. ✅ **Create Cloud Build trigger**
6. ✅ **Push to main → Automatic deployment!**

---

## Alternative: Manual Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for manual deployment using `deploy.sh` script.

---

## Database: MySQL

This project uses **MySQL** (Cloud SQL for MySQL) instead of PostgreSQL.

**Connection format:**
```
mysql+aiomysql://root:PASSWORD@/portfolio_tracker?unix_socket=/cloudsql/PROJECT:REGION:INSTANCE
```

---

## Files Explained

| File | Purpose |
|------|---------|
| `GITHUB_DEPLOYMENT.md` | **⭐ Recommended**: GitHub to Cloud Run with MySQL |
| `DEPLOYMENT.md` | Manual deployment guide |
| `deploy.sh` | Automated deployment script |
| `Dockerfile` | Container configuration |
| `cloudbuild.yaml` | CI/CD pipeline configuration |
| `.dockerignore` | Files to exclude from Docker build |

---

## Quick Start

### For GitHub Deployment (Recommended):

```bash
# 1. Follow GITHUB_DEPLOYMENT.md to set up secrets and triggers

# 2. Push to deploy
git push origin main

# 3. Done! Build happens automatically
```

### For Manual Deployment:

```bash
# 1. Set environment variables
export DATABASE_URL="your-mysql-url"
export SECRET_KEY="your-secret"
# ... etc

# 2. Run deploy script
./deploy.sh YOUR_PROJECT_ID
```

---

## Environment Variables

Create these secrets in Google Secret Manager:

- `DATABASE_URL` - MySQL connection string
- `SYNC_DATABASE_URL` - Sync MySQL connection string
- `SECRET_KEY` - JWT secret key (32+ chars)
- `SMTP_PASSWORD` - Email app password

Configure these in Cloud Build trigger substitutions:

- `_CLOUDSQL_INSTANCE` - MySQL instance connection name
- `_SMTP_HOST` - Email server (smtp.gmail.com)
- `_SMTP_PORT` - Email port (587)
- `_SMTP_USER` - Your email address
- `_EMAIL_FROM` - From email address

---

## After Deployment

1. **Get your service URL:**
   ```bash
   gcloud run services describe portfolio-tracker \
     --region asia-southeast1 \
     --format='value(status.url)'
   ```

2. **Update CORS in `main.py`:**
   ```python
   origins = [
       "http://localhost:5173",
       "https://www.paulbespokesuits.com",
       "https://your-cloud-run-url.run.app",  # Add this
   ]
   ```

3. **Test your API:**
   - Root: `https://your-url.run.app/`
   - Docs: `https://your-url.run.app/docs`

---

## Support

**Detailed guides:**
- [GITHUB_DEPLOYMENT.md](GITHUB_DEPLOYMENT.md) - GitHub CI/CD deployment
- [DEPLOYMENT.md](DEPLOYMENT.md) - Manual deployment

**Google Cloud Docs:**
- [Cloud Run](https://cloud.google.com/run/docs)
- [Cloud Build](https://cloud.google.com/build/docs)
- [Cloud SQL MySQL](https://cloud.google.com/sql/docs/mysql)
