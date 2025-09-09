# Attendee Fork: AssemblyAI + API Key + Transcript Windowing

This fork adds the following enhancements to the Attendee meeting bot platform:

## New Features

### 1. AssemblyAI Realtime ASR Provider
- **AssemblyAI** is now supported as an alternative to Deepgram for real-time speech recognition
- Configurable via environment variable `ASR_PROVIDER`
- Supports the same features as Deepgram (interim results, language selection, redaction)

### 2. API Authentication
- The API uses the original Attendee Token authentication system
- API keys are stored in the database (hashed) and tied to projects
- Use `Authorization: Token YOUR_API_KEY` header for all API calls
- Create API keys through Django admin or management commands

### 3. Enhanced Transcript Endpoint
The `/api/v1/bots/{id}/transcript` endpoint now supports:
- **`since_ms`**: Return only segments with end_ms > since_ms
- **`window_s`**: Return only last N seconds relative to latest transcript
- **`format=plain`**: Return joined text instead of segments
- **`last_timestamp_ms`**: Included in response for polling

### 4. Health Check Endpoints
- `/health` - Basic health check (existing)
- `/ready` - Readiness check for Kubernetes/Docker deployments

## Configuration

### Environment Variables

```bash
# ASR Provider Selection
ASR_PROVIDER=assemblyai   # options: assemblyai | deepgram

# AssemblyAI Configuration
ASSEMBLYAI_API_KEY=your_assemblyai_api_key
ASSEMBLYAI_REALTIME_URL=wss://api.assemblyai.com/v2/realtime/ws?sample_rate=16000

# API keys are managed through Django admin interface
# No environment variable needed for authentication

# Existing variables (unchanged)
DJANGO_SECRET_KEY=...
CREDENTIALS_ENCRYPTION_KEY=...
DATABASE_URL=...
REDIS_URL=...
AWS_RECORDING_STORAGE_BUCKET_NAME=...
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

### Quick Setup

1. Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

2. Generate encryption keys:
```bash
python init_env.py >> .env
```

3. Configure your ASR provider and API key in `.env`

4. Install dependencies:
```bash
pip install -r requirements.txt
```

5. Run migrations:
```bash
python manage.py migrate
```

6. Start the server:
```bash
python manage.py runserver
```

## API Usage Examples

### Authentication
All API requests require Token authentication using API keys from the database:

```bash
curl -H "Authorization: Token $API_KEY" \
     https://your-api.com/api/v1/bots
```

To create an API key:
```bash
# Using Django shell
python manage.py shell
>>> from bots.models import Project, ApiKey
>>> project = Project.objects.create(name="My Project", organization_id=1)
>>> api_key = ApiKey.create(project=project, name="My API Key")
>>> print(api_key)  # This is your API key - save it!
```

### Create Bot
```bash
curl -X POST https://your-api.com/api/v1/bots \
  -H "Authorization: Token $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "meeting_url": "https://zoom.us/j/123456789",
    "bot_name": "My Bot"
  }'
```

### Get Transcript with Filters

#### Get segments since timestamp:
```bash
curl "https://your-api.com/api/v1/bots/{id}/transcript?since_ms=15000" \
  -H "Authorization: Bearer $API_KEY"
```

#### Get last 60 seconds:
```bash
curl "https://your-api.com/api/v1/bots/{id}/transcript?window_s=60" \
  -H "Authorization: Bearer $API_KEY"
```

#### Get plain text format:
```bash
curl "https://your-api.com/api/v1/bots/{id}/transcript?format=plain&window_s=60" \
  -H "Authorization: Bearer $API_KEY"
```

Response (plain format):
```json
{
  "text": "Hello everyone, let's start the meeting...",
  "last_timestamp_ms": 125000
}
```

Response (json format):
```json
{
  "segments": [
    {
      "start_ms": 1000,
      "end_ms": 2000,
      "text": "Hello everyone",
      "is_final": true,
      "speaker_name": "John Doe",
      "speaker_uuid": "uuid-123"
    }
  ],
  "last_timestamp_ms": 2000
}
```

### Polling for Updates
Use `since_ms` with the `last_timestamp_ms` from previous response:

```bash
# First request
response=$(curl "https://your-api.com/api/v1/bots/{id}/transcript" \
  -H "Authorization: Bearer $API_KEY")
last_ts=$(echo $response | jq -r '.last_timestamp_ms')

# Poll for updates
curl "https://your-api.com/api/v1/bots/{id}/transcript?since_ms=$last_ts" \
  -H "Authorization: Bearer $API_KEY"
```

### End Bot
```bash
curl -X POST https://your-api.com/api/v1/bots/{id}/leave \
  -H "Authorization: Bearer $API_KEY"
```

## Provider Selection

### Using AssemblyAI
1. Set `ASR_PROVIDER=assemblyai` in your environment
2. Provide `ASSEMBLYAI_API_KEY`
3. Bots will automatically use AssemblyAI for transcription

### Using Deepgram (default)
1. Set `ASR_PROVIDER=deepgram` or leave unset
2. Configure Deepgram credentials through the web UI
3. Bots will use Deepgram for transcription

### Per-Project Configuration
You can also configure ASR providers per project through the Credentials system in the web UI.

## Migration from Original Attendee

1. **No breaking changes** - All existing endpoints work as before
2. **Authentication unchanged** - Uses the original Token authentication system
3. **Backward compatible** - Deepgram remains the default provider
4. **Database compatible** - No schema changes required

## Testing

### Test Health Endpoints
```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

### Test API Authentication
```bash
# Should fail without API key (if API_KEY is set)
curl http://localhost:8000/api/v1/bots

# Should succeed with API key
curl -H "Authorization: Bearer $API_KEY" \
     http://localhost:8000/api/v1/bots
```

### Test Transcript Filtering
```python
import requests
import time

api_key = "your_api_key"
bot_id = "bot_xxxxx"
headers = {"Authorization": f"Bearer {api_key}"}

# Get full transcript
resp = requests.get(
    f"https://your-api.com/api/v1/bots/{bot_id}/transcript",
    headers=headers
)
data = resp.json()

# Get only new segments
last_ts = data["last_timestamp_ms"]
time.sleep(5)
resp = requests.get(
    f"https://your-api.com/api/v1/bots/{bot_id}/transcript?since_ms={last_ts}",
    headers=headers
)
new_segments = resp.json()["segments"]

# Get last 30 seconds as plain text
resp = requests.get(
    f"https://your-api.com/api/v1/bots/{bot_id}/transcript?window_s=30&format=plain",
    headers=headers
)
text = resp.json()["text"]
```

## Troubleshooting

### AssemblyAI Not Working
1. Check `ASSEMBLYAI_API_KEY` is set correctly
2. Verify `ASR_PROVIDER=assemblyai`
3. Check logs for connection errors
4. Ensure audio is 16kHz PCM16 format

### API Authentication Issues
1. Ensure you have created a Project and API key in the database
2. Check Token format: `Authorization: Token YOUR_KEY`
3. Verify the API key is not disabled
4. Check that the key belongs to an active project

### Transcript Filtering Issues
1. Ensure timestamps are in milliseconds
2. Check that segments have proper end_ms values
3. Verify format parameter is "json" or "plain"
4. Use integer values for since_ms and window_s

## License

This fork maintains the same license as the original Attendee project.