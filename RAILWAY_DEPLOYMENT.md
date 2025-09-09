# Railway Deployment Guide for Attendee

## Prerequisites
- Railway account with a Pro plan (needed for sufficient resources)
- GitHub repository with your Attendee fork
- AWS S3 bucket for recording storage (optional but recommended)

## Step 1: Database Setup

### PostgreSQL
1. In Railway, create a new PostgreSQL service
2. Note the connection string (will be auto-injected as `DATABASE_URL`)

### Redis
1. Create a new Redis service in Railway
2. Note the connection URL (will be auto-injected as `REDIS_URL`)

## Step 2: Environment Variables

Set these environment variables in your Railway service:

### Required Variables
```bash
# Django Core Settings
DJANGO_SECRET_KEY=<generate-a-new-secure-key>
CREDENTIALS_ENCRYPTION_KEY=<generate-using-python-script-below>
DJANGO_SETTINGS_MODULE=attendee.settings.production

# Site Configuration
SITE_DOMAIN=your-app.up.railway.app
ALLOWED_HOSTS=your-app.up.railway.app

# Database (auto-injected by Railway)
DATABASE_URL=<auto-injected-by-railway>

# Redis (auto-injected by Railway)
REDIS_URL=<auto-injected-by-railway>

# Production Settings
DEBUG=False
CHARGE_CREDITS_FOR_BOTS=true

# ASR Provider
ASR_PROVIDER=assembly_ai
ASSEMBLYAI_API_KEY=<your-assemblyai-api-key>
ASSEMBLYAI_REALTIME_URL=wss://api.assemblyai.com/v2/realtime/ws?sample_rate=16000
```

### Optional Variables (for S3 storage)
```bash
AWS_RECORDING_STORAGE_BUCKET_NAME=<your-bucket-name>
AWS_ACCESS_KEY_ID=<your-aws-access-key>
AWS_SECRET_ACCESS_KEY=<your-aws-secret-key>
AWS_DEFAULT_REGION=us-east-1
AWS_S3_ADDRESSING_STYLE=virtual
```

### Generate Encryption Key
Run this Python script locally to generate a secure encryption key:
```python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

## Step 3: Create Production Settings File

Create `/home/tp02ga/git/attendee/attendee/settings/production.py`:

```python
from .base import *
import os

# Security Settings
DEBUG = False
ALLOWED_HOSTS = os.getenv('ALLOWED_HOSTS', '').split(',')
CSRF_TRUSTED_ORIGINS = [f"https://{host}" for host in ALLOWED_HOSTS]

# Database (Railway provides DATABASE_URL)
import dj_database_url
DATABASES = {
    'default': dj_database_url.config(
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# Static files
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Security
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# Email (optional, for production email sending)
if os.getenv('EMAIL_HOST'):
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
    EMAIL_HOST = os.getenv('EMAIL_HOST')
    EMAIL_PORT = int(os.getenv('EMAIL_PORT', 587))
    EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
    EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
    EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
    DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'noreply@attendee.dev')
```

## Step 4: Create Railway Configuration

Create `railway.toml` in your repository root:

```toml
[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile"

[deploy]
startCommand = "/opt/bin/entrypoint.sh && gunicorn attendee.wsgi:application --bind 0.0.0.0:$PORT --workers 4"
healthcheckPath = "/health/"
healthcheckTimeout = 300
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10

[[services]]
name = "worker"
startCommand = "/opt/bin/entrypoint.sh && celery -A attendee worker -l INFO"

[[services]]
name = "scheduler"
startCommand = "/opt/bin/entrypoint.sh && python manage.py run_scheduler"
```

## Step 5: Update Requirements

Ensure these are in `requirements.txt`:
```
gunicorn==21.2.0
whitenoise==6.5.0
dj-database-url==2.1.0
psycopg2-binary==2.9.9
```

## Step 6: Create Health Check Endpoint

Add to `/home/tp02ga/git/attendee/attendee/urls.py`:

```python
from django.http import JsonResponse

def health_check(request):
    return JsonResponse({"status": "healthy"})

urlpatterns = [
    path('health/', health_check),
    # ... existing patterns
]
```

## Step 7: Deployment Steps

1. **Commit all changes** to your GitHub repository
2. **In Railway:**
   - Create a new project
   - Connect your GitHub repository
   - Railway will auto-detect the Dockerfile
   - Add all environment variables
   - Deploy

3. **Post-deployment:**
   - Run migrations: Use Railway's CLI or web terminal:
     ```bash
     python manage.py migrate
     ```
   - Create superuser:
     ```bash
     python manage.py createsuperuser
     ```
   - Collect static files:
     ```bash
     python manage.py collectstatic --noinput
     ```

## Step 8: Configure Services

After deployment, access your app at `https://your-app.up.railway.app`:

1. **Create an account** and verify email
2. **Add Zoom credentials** in Settings → Credentials
3. **Add AssemblyAI credentials** in Settings → Credentials
4. **Configure webhooks** as needed

## Troubleshooting

### Common Issues:

1. **Memory issues**: Ensure you're on Railway's Pro plan for sufficient resources
2. **Worker not processing**: Check that Celery worker service is running
3. **No transcriptions**: Verify AssemblyAI credentials are added in the UI
4. **Bot can't join meetings**: Check Zoom credentials are properly configured

### Monitoring:

- Check Railway logs for each service (web, worker, scheduler)
- Monitor PostgreSQL and Redis connection health
- Set up error tracking (e.g., Sentry) for production

## Security Checklist

- [ ] Generate new `DJANGO_SECRET_KEY` for production
- [ ] Generate new `CREDENTIALS_ENCRYPTION_KEY`
- [ ] Set `DEBUG=False`
- [ ] Configure `ALLOWED_HOSTS` properly
- [ ] Use HTTPS (Railway provides this automatically)
- [ ] Set up proper CORS headers if needed
- [ ] Regular security updates for dependencies

## Scaling Considerations

- Use S3 for recording storage (local storage on Railway is ephemeral)
- Consider using a CDN for static files
- Monitor Redis memory usage
- Set up database backups
- Configure rate limiting for API endpoints