import hashlib
import json
import math
import os
import random
import secrets
import string

from concurrency.exceptions import RecordModifiedError
from concurrency.fields import IntegerVersionField
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.db.utils import IntegrityError
from django.utils import timezone
from django.utils.crypto import get_random_string

from accounts.models import Organization, User, UserRole
from bots.webhook_utils import trigger_webhook

# Create your models here.


class Project(models.Model):
    name = models.CharField(max_length=255)
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name="projects")

    OBJECT_ID_PREFIX = "proj_"
    object_id = models.CharField(max_length=32, unique=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def accessible_to(cls, user):
        if not user.is_active:
            return cls.objects.none()
        if user.role == UserRole.ADMIN:
            return cls.objects.filter(organization=user.organization)
        return cls.objects.filter(organization=user.organization).filter(project_accesses__user=user)

    def users_with_access(self):
        return self.organization.users.filter(is_active=True).filter(Q(project_accesses__project=self) | Q(role=UserRole.ADMIN))

    def concurrent_bots_limit(self):
        return int(os.getenv("CONCURRENT_BOTS_LIMIT", 2500))

    def save(self, *args, **kwargs):
        if not self.object_id:
            # Generate a random 16-character string
            random_string = "".join(random.choices(string.ascii_letters + string.digits, k=16))
            self.object_id = f"{self.OBJECT_ID_PREFIX}{random_string}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class CalendarPlatform(models.TextChoices):
    GOOGLE = "google"
    MICROSOFT = "microsoft"


class CalendarStates(models.IntegerChoices):
    CONNECTED = 1
    DISCONNECTED = 2


class Calendar(models.Model):
    OBJECT_ID_PREFIX = "cal_"

    object_id = models.CharField(max_length=32, unique=True, editable=False)
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="calendars")
    platform = models.CharField(max_length=255, choices=CalendarPlatform.choices)
    state = models.IntegerField(choices=CalendarStates.choices, default=CalendarStates.CONNECTED)
    connection_failure_data = models.JSONField(null=True, default=None)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = IntegerVersionField()

    metadata = models.JSONField(null=True, blank=True)
    deduplication_key = models.CharField(max_length=1024, null=True, blank=True, help_text="Optional key for deduplicating calendars")

    client_id = models.CharField(max_length=255)
    platform_uuid = models.CharField(max_length=1024, null=True, blank=True)

    last_attempted_sync_at = models.DateTimeField(null=True, blank=True)
    last_successful_sync_at = models.DateTimeField(null=True, blank=True)
    last_successful_sync_time_window_start = models.DateTimeField(null=True, blank=True)
    last_successful_sync_time_window_end = models.DateTimeField(null=True, blank=True)
    last_successful_sync_started_at = models.DateTimeField(null=True, blank=True)
    sync_task_enqueued_at = models.DateTimeField(null=True, blank=True)
    sync_task_requested_at = models.DateTimeField(null=True, blank=True)

    _encrypted_data = models.BinaryField(
        null=True,
        editable=False,  # Prevents editing through admin/forms
    )

    def set_credentials(self, credentials_dict):
        """Encrypt and save credentials"""
        f = Fernet(settings.CREDENTIALS_ENCRYPTION_KEY)
        json_data = json.dumps(credentials_dict)
        self._encrypted_data = f.encrypt(json_data.encode())
        self.save()

    def get_credentials(self):
        """Decrypt and return credentials"""
        if not self._encrypted_data:
            return None
        f = Fernet(settings.CREDENTIALS_ENCRYPTION_KEY)
        decrypted_data = f.decrypt(bytes(self._encrypted_data))
        return json.loads(decrypted_data.decode())

    def save(self, *args, **kwargs):
        if not self.object_id:
            # Generate a random 16-character string
            random_string = "".join(random.choices(string.ascii_letters + string.digits, k=16))
            self.object_id = f"{self.OBJECT_ID_PREFIX}{random_string}"
        super().save(*args, **kwargs)

    class Meta:
        # Within a project, we don't want to allow calendars in the same project with the same deduplication key
        constraints = [
            models.UniqueConstraint(fields=["project", "deduplication_key"], name="unique_calendar_deduplication_key"),
        ]


class CalendarEvent(models.Model):
    OBJECT_ID_PREFIX = "evt_"

    object_id = models.CharField(max_length=255, unique=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    calendar = models.ForeignKey(Calendar, on_delete=models.CASCADE, related_name="events")

    platform_uuid = models.CharField(max_length=1024)

    meeting_url = models.CharField(max_length=511, null=True, blank=True)

    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    is_deleted = models.BooleanField(default=False)
    attendees = models.JSONField(null=True, blank=True)
    ical_uid = models.CharField(max_length=1024, null=True, blank=True)
    name = models.CharField(max_length=1024, null=True, blank=True)

    raw = models.JSONField()

    def save(self, *args, **kwargs):
        if not self.object_id:
            # Generate a random 16-character string
            random_string = "".join(random.choices(string.ascii_letters + string.digits, k=16))
            self.object_id = f"{self.OBJECT_ID_PREFIX}{random_string}"
        super().save(*args, **kwargs)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["calendar", "platform_uuid"], name="unique_calendar_event_platform_uuid"),
        ]


class ProjectAccess(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="project_accesses")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="project_accesses")


class ApiKey(models.Model):
    name = models.CharField(max_length=255)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="api_keys")

    OBJECT_ID_PREFIX = "key_"
    object_id = models.CharField(max_length=32, unique=True, editable=False)

    def save(self, *args, **kwargs):
        if not self.object_id:
            # Generate a random 16-character string
            random_string = "".join(random.choices(string.ascii_letters + string.digits, k=16))
            self.object_id = f"{self.OBJECT_ID_PREFIX}{random_string}"
        super().save(*args, **kwargs)

    key_hash = models.CharField(max_length=64, unique=True)  # SHA-256 hash is 64 chars
    disabled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def create(cls, project, name):
        # Generate a random API key (you might want to adjust the length)
        api_key = get_random_string(length=32)
        # Create hash of the API key
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        instance = cls(project=project, name=name, key_hash=key_hash)
        instance.save()

        # Return both the instance and the plain text key
        # The plain text key will only be available during creation
        return instance, api_key

    def __str__(self):
        return f"{self.name} ({self.project.name})"


class MeetingTypes(models.TextChoices):
    ZOOM = "zoom"
    GOOGLE_MEET = "google_meet"
    TEAMS = "teams"


class BotStates(models.IntegerChoices):
    READY = 1, "Ready"
    JOINING = 2, "Joining"
    JOINED_NOT_RECORDING = 3, "Joined - Not Recording"
    JOINED_RECORDING = 4, "Joined - Recording"
    LEAVING = 5, "Leaving"
    POST_PROCESSING = 6, "Post Processing"
    FATAL_ERROR = 7, "Fatal Error"
    WAITING_ROOM = 8, "Waiting Room"
    ENDED = 9, "Ended"
    DATA_DELETED = 10, "Data Deleted"
    SCHEDULED = 11, "Scheduled"
    STAGED = 12, "Staged"
    JOINED_RECORDING_PAUSED = 13, "Joined - Recording Paused"
    JOINING_BREAKOUT_ROOM = 14, "Joining Breakout Room"
    LEAVING_BREAKOUT_ROOM = 15, "Leaving Breakout Room"

    @classmethod
    def _get_state_to_api_code_mapping(cls):
        """Get the trigger type to API code mapping"""
        return {
            cls.READY: "ready",
            cls.JOINING: "joining",
            cls.JOINED_NOT_RECORDING: "joined_not_recording",
            cls.JOINED_RECORDING: "joined_recording",
            cls.LEAVING: "leaving",
            cls.POST_PROCESSING: "post_processing",
            cls.FATAL_ERROR: "fatal_error",
            cls.WAITING_ROOM: "waiting_room",
            cls.ENDED: "ended",
            cls.DATA_DELETED: "data_deleted",
            cls.SCHEDULED: "scheduled",
            cls.STAGED: "staged",
            cls.JOINED_RECORDING_PAUSED: "joined_recording_paused",
            cls.JOINING_BREAKOUT_ROOM: "joining_breakout_room",
            cls.LEAVING_BREAKOUT_ROOM: "leaving_breakout_room",
        }

    @classmethod
    def state_to_api_code(cls, value):
        """Returns the API code for a given state value"""
        return cls._get_state_to_api_code_mapping().get(value)

    @classmethod
    def api_code_to_state(cls, api_code):
        """Returns the state value for a given API code"""
        reverse_mapping = {v: k for k, v in cls._get_state_to_api_code_mapping().items()}
        return reverse_mapping.get(api_code)

    @classmethod
    def post_meeting_states(cls):
        return [cls.FATAL_ERROR, cls.ENDED, cls.DATA_DELETED]

    @classmethod
    def pre_meeting_states(cls):
        return [cls.READY, cls.SCHEDULED, cls.STAGED]


class RecordingFormats(models.TextChoices):
    MP4 = "mp4"
    WEBM = "webm"
    MP3 = "mp3"
    NONE = "none"


class RecordingViews(models.TextChoices):
    SPEAKER_VIEW = "speaker_view"
    GALLERY_VIEW = "gallery_view"
    SPEAKER_VIEW_NO_SIDEBAR = "speaker_view_no_sidebar"


class Bot(models.Model):
    OBJECT_ID_PREFIX = "bot_"

    object_id = models.CharField(max_length=32, unique=True, editable=False)

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="bots")

    name = models.CharField(max_length=255, default="My bot")
    meeting_url = models.CharField(max_length=511)
    meeting_uuid = models.CharField(max_length=511, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = IntegerVersionField()

    state = models.IntegerField(choices=BotStates.choices, default=BotStates.READY, null=False)

    settings = models.JSONField(null=False, default=dict)
    metadata = models.JSONField(null=True, blank=True)

    first_heartbeat_timestamp = models.IntegerField(null=True, blank=True)
    last_heartbeat_timestamp = models.IntegerField(null=True, blank=True)

    join_at = models.DateTimeField(null=True, blank=True, help_text="The time the bot should join the meeting")
    deduplication_key = models.CharField(max_length=1024, null=True, blank=True, help_text="Optional key for deduplicating bots")
    calendar_event = models.ForeignKey(CalendarEvent, on_delete=models.SET_NULL, null=True, blank=True, related_name="bots")

    def delete_data(self):
        # Check if bot is in a state where the data deleted event can be created
        if not BotEventManager.event_can_be_created_for_state(BotEventTypes.DATA_DELETED, self.state):
            raise ValueError("Bot is not in a state where the data deleted event can be created")

        with transaction.atomic():
            # Delete all debug screenshots from bot events
            BotDebugScreenshot.objects.filter(bot_event__bot=self).delete()

            # Delete all utterances and recording files for each recording
            for recording in self.recordings.all():
                # Delete all utterances first
                recording.utterances.all().delete()

                # Delete the actual recording file if it exists
                if recording.file and recording.file.name:
                    recording.file.delete()

            # Delete all participants
            self.participants.all().delete()

            # Delete all chat messages
            self.chat_messages.all().delete()

            # Delete all webhook delivery attempts that have a trigger other than BOT_STATE_CHANGE, since these contain sensitive data
            webhook_delivery_attempts_with_sensitive_data = self.webhook_delivery_attempts.exclude(webhook_trigger_type=WebhookTriggerTypes.BOT_STATE_CHANGE)
            webhook_delivery_attempts_with_sensitive_data.delete()

            BotEventManager.create_event(bot=self, event_type=BotEventTypes.DATA_DELETED)

    def set_heartbeat(self):
        retry_count = 0
        max_retries = 10
        while retry_count < max_retries:
            try:
                self.refresh_from_db()
                current_timestamp = int(timezone.now().timestamp())
                if self.first_heartbeat_timestamp is None:
                    self.first_heartbeat_timestamp = current_timestamp
                self.last_heartbeat_timestamp = current_timestamp
                self.save()
                return
            except RecordModifiedError:
                retry_count += 1
                if retry_count >= max_retries:
                    raise
                continue

    def bot_duration_seconds(self) -> int:
        if self.first_heartbeat_timestamp is None or self.last_heartbeat_timestamp is None:
            return 0
        if self.last_heartbeat_timestamp < self.first_heartbeat_timestamp:
            return 0
        seconds_active = self.last_heartbeat_timestamp - self.first_heartbeat_timestamp
        # If first and last heartbeat are the same, we don't know the exact time the bot was active
        # So we'll assume it ran for 30 seconds
        if self.last_heartbeat_timestamp == self.first_heartbeat_timestamp:
            seconds_active = 30
        return seconds_active

    def centicredits_consumed(self) -> int:
        if self.first_heartbeat_timestamp is None or self.last_heartbeat_timestamp is None:
            return 0
        if self.last_heartbeat_timestamp < self.first_heartbeat_timestamp:
            return 0
        seconds_active = self.last_heartbeat_timestamp - self.first_heartbeat_timestamp
        # If first and last heartbeat are the same, we don't know the exact time the bot was active
        # and that will make a difference to the charge. So we'll assume it ran for 30 seconds
        if self.last_heartbeat_timestamp == self.first_heartbeat_timestamp:
            seconds_active = 30
        hours_active = seconds_active / 3600
        # The rate is 1 credit per hour
        centicredits_active = hours_active * 100
        return math.ceil(centicredits_active)

    def cpu_request(self):
        from bots.utils import meeting_type_from_url

        bot_meeting_type = meeting_type_from_url(self.meeting_url)
        meeting_type_env_var_substring = {
            MeetingTypes.GOOGLE_MEET: "GOOGLE_MEET",
            MeetingTypes.TEAMS: "TEAMS",
            MeetingTypes.ZOOM: "ZOOM",
        }.get(bot_meeting_type, "UNKNOWN")

        recording_mode_env_var_substring = {
            RecordingTypes.AUDIO_AND_VIDEO: "AUDIO_AND_VIDEO",
            RecordingTypes.AUDIO_ONLY: "AUDIO_ONLY",
            RecordingTypes.NO_RECORDING: "NO_RECORDING",
        }.get(self.recording_type(), "UNKNOWN")

        env_var_name = f"{meeting_type_env_var_substring}_{recording_mode_env_var_substring}_BOT_CPU_REQUEST"

        default_cpu_request = os.getenv("BOT_CPU_REQUEST", "4") or "4"
        value_from_env_var = os.getenv(env_var_name, default_cpu_request)
        if not value_from_env_var:
            return default_cpu_request
        return value_from_env_var

    def openai_transcription_prompt(self):
        return self.settings.get("transcription_settings", {}).get("openai", {}).get("prompt", None)

    def openai_transcription_model(self):
        default_model = os.getenv("OPENAI_MODEL_NAME", "gpt-4o-transcribe")
        return self.settings.get("transcription_settings", {}).get("openai", {}).get("model", default_model)

    def openai_transcription_language(self):
        return self.settings.get("transcription_settings", {}).get("openai", {}).get("language", None)

    def gladia_code_switching_languages(self):
        return self.settings.get("transcription_settings", {}).get("gladia", {}).get("code_switching_languages", None)

    def gladia_enable_code_switching(self):
        return self.settings.get("transcription_settings", {}).get("gladia", {}).get("enable_code_switching", False)

    def assembly_ai_language_code(self):
        return self.settings.get("transcription_settings", {}).get("assembly_ai", {}).get("language_code", None)

    def assembly_ai_language_detection(self):
        return self.settings.get("transcription_settings", {}).get("assembly_ai", {}).get("language_detection", False)

    def assemblyai_keyterms_prompt(self):
        return self.settings.get("transcription_settings", {}).get("assembly_ai", {}).get("keyterms_prompt", None)

    def assemblyai_speech_model(self):
        return self.settings.get("transcription_settings", {}).get("assembly_ai", {}).get("speech_model", None)

    def sarvam_language_code(self):
        return self.settings.get("transcription_settings", {}).get("sarvam", {}).get("language_code", None)

    def sarvam_model(self):
        return self.settings.get("transcription_settings", {}).get("sarvam", {}).get("model", None)

    def elevenlabs_model_id(self):
        return self.settings.get("transcription_settings", {}).get("elevenlabs", {}).get("model_id", "scribe_v1")

    def elevenlabs_language_code(self):
        return self.settings.get("transcription_settings", {}).get("elevenlabs", {}).get("language_code", None)

    def elevenlabs_tag_audio_events(self):
        return self.settings.get("transcription_settings", {}).get("elevenlabs", {}).get("tag_audio_events", None)

    def deepgram_language(self):
        return self.settings.get("transcription_settings", {}).get("deepgram", {}).get("language", None)

    def deepgram_detect_language(self):
        return self.settings.get("transcription_settings", {}).get("deepgram", {}).get("detect_language", None)

    def deepgram_callback(self):
        return self.settings.get("transcription_settings", {}).get("deepgram", {}).get("callback", None)

    def deepgram_keyterms(self):
        return self.settings.get("transcription_settings", {}).get("deepgram", {}).get("keyterms", None)

    def deepgram_keywords(self):
        return self.settings.get("transcription_settings", {}).get("deepgram", {}).get("keywords", None)

    def deepgram_use_streaming(self):
        return self.deepgram_callback() is not None

    def deepgram_model(self):
        model_from_settings = self.settings.get("transcription_settings", {}).get("deepgram", {}).get("model", None)
        if model_from_settings:
            return model_from_settings

        # nova-3 does not have multilingual support yet, so we need to use nova-2 if we're transcribing with a non-default language
        if (self.deepgram_language() != "en" and self.deepgram_language()) or self.deepgram_detect_language():
            deepgram_model = "nova-2"
        else:
            deepgram_model = "nova-3"

        # Special case: we can use nova-3 for language=multi
        if self.deepgram_language() == "multi":
            deepgram_model = "nova-3"

        return deepgram_model

    def deepgram_redaction_settings(self):
        return self.settings.get("transcription_settings", {}).get("deepgram", {}).get("redact", [])

    def google_meet_closed_captions_language(self):
        return self.settings.get("transcription_settings", {}).get("meeting_closed_captions", {}).get("google_meet_language", None)

    def teams_closed_captions_language(self):
        return self.settings.get("transcription_settings", {}).get("meeting_closed_captions", {}).get("teams_language", None)

    def zoom_closed_captions_language(self):
        return self.settings.get("transcription_settings", {}).get("meeting_closed_captions", {}).get("zoom_language", None)

    def meeting_closed_captions_merge_consecutive_captions(self):
        return self.settings.get("transcription_settings", {}).get("meeting_closed_captions", {}).get("merge_consecutive_captions", False)

    def teams_use_bot_login(self):
        return self.settings.get("teams_settings", {}).get("use_login", False)

    def use_zoom_web_adapter(self):
        return self.settings.get("zoom_settings", {}).get("sdk", "native") == "web"

    def zoom_meeting_settings(self):
        return self.settings.get("zoom_settings", {}).get("meeting_settings", {})

    def rtmp_destination_url(self):
        rtmp_settings = self.settings.get("rtmp_settings")
        if not rtmp_settings:
            return None

        destination_url = rtmp_settings.get("destination_url", "").rstrip("/")
        stream_key = rtmp_settings.get("stream_key", "")

        if not destination_url:
            return None

        return f"{destination_url}/{stream_key}"

    def websocket_audio_url(self):
        """Websocket URL is used to send/receive audio chunks to/from the bot"""
        websocket_settings = self.settings.get("websocket_settings") or {}
        websocket_audio_settings = websocket_settings.get("audio") or {}
        return websocket_audio_settings.get("url")

    def websocket_audio_sample_rate(self):
        websocket_settings = self.settings.get("websocket_settings") or {}
        websocket_audio_settings = websocket_settings.get("audio") or {}
        return websocket_audio_settings.get("sample_rate", 16000)

    def zoom_tokens_callback_url(self):
        callback_settings = self.settings.get("callback_settings", {})
        if callback_settings is None:
            callback_settings = {}
        return callback_settings.get("zoom_tokens_url", None)

    def recording_format(self):
        recording_settings = self.settings.get("recording_settings", {})
        if recording_settings is None:
            recording_settings = {}
        return recording_settings.get("format", RecordingFormats.MP4)

    def recording_type(self):
        # Recording type is derived from the recording format
        recording_format = self.recording_format()
        if recording_format == RecordingFormats.MP4 or recording_format == RecordingFormats.WEBM:
            return RecordingTypes.AUDIO_AND_VIDEO
        elif recording_format == RecordingFormats.MP3:
            return RecordingTypes.AUDIO_ONLY
        elif recording_format == RecordingFormats.NONE:
            return RecordingTypes.NO_RECORDING
        else:
            raise ValueError(f"Invalid recording format: {recording_format}")

    def recording_dimensions(self):
        recording_settings = self.settings.get("recording_settings", {})
        if recording_settings is None:
            recording_settings = {}
        resolution_value = recording_settings.get("resolution", RecordingResolutions.HD_1080P)
        return RecordingResolutions.get_dimensions(resolution_value)

    def recording_view(self):
        recording_settings = self.settings.get("recording_settings", {})
        if recording_settings is None:
            recording_settings = {}
        return recording_settings.get("view", RecordingViews.SPEAKER_VIEW)

    def save_resource_snapshots(self):
        save_resource_snapshots_env_var_value = os.getenv("SAVE_BOT_RESOURCE_SNAPSHOTS", "false")
        return str(save_resource_snapshots_env_var_value).lower() == "true"

    def create_debug_recording(self):
        from bots.utils import meeting_type_from_url

        # Temporarily enabling this for all google meet meetings
        bot_meeting_type = meeting_type_from_url(self.meeting_url)
        if (bot_meeting_type == MeetingTypes.GOOGLE_MEET or bot_meeting_type == MeetingTypes.TEAMS or (bot_meeting_type == MeetingTypes.ZOOM and self.use_zoom_web_adapter)) and self.recording_type() == RecordingTypes.AUDIO_AND_VIDEO:
            return True

        debug_settings = self.settings.get("debug_settings", {})
        if debug_settings is None:
            debug_settings = {}
        return debug_settings.get("create_debug_recording", False)

    def external_media_storage_bucket_name(self):
        external_media_storage_settings = self.settings.get("external_media_storage_settings", {})
        if external_media_storage_settings is None:
            external_media_storage_settings = {}
        return external_media_storage_settings.get("bucket_name", None)

    def external_media_storage_recording_file_name(self):
        external_media_storage_settings = self.settings.get("external_media_storage_settings", {})
        if external_media_storage_settings is None:
            external_media_storage_settings = {}
        return external_media_storage_settings.get("recording_file_name", None)

    def last_bot_event(self):
        return self.bot_events.order_by("-created_at").first()

    def save(self, *args, **kwargs):
        if not self.object_id:
            # Generate a random 16-character string
            random_string = "".join(random.choices(string.ascii_letters + string.digits, k=16))
            self.object_id = f"{self.OBJECT_ID_PREFIX}{random_string}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.object_id} - {self.project.name} in {self.meeting_url}"

    def k8s_pod_name(self):
        return f"bot-pod-{self.id}-{self.object_id}".lower().replace("_", "-")

    def automatic_leave_settings(self):
        return self.settings.get("automatic_leave_settings", {})

    class Meta:
        # We'll have to do a periodic query to find bots that have a join_at that is within 5 minutes of now.
        # The partial index will exclude bots without a join_at which should speed up the query and reduce the space used by the index.
        indexes = [
            models.Index(fields=["join_at"], name="bot_join_at_idx", condition=models.Q(join_at__isnull=False)),
        ]

        # Within a project, we don't want to allow bots that aren't in apost-meeting state with the same deduplication key.
        constraints = [
            models.UniqueConstraint(fields=["project", "deduplication_key"], name="unique_bot_deduplication_key", condition=~models.Q(state__in=BotStates.post_meeting_states())),
        ]


class CreditTransaction(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, null=False, related_name="credit_transactions")
    created_at = models.DateTimeField(auto_now_add=True)
    centicredits_before = models.IntegerField(null=False)
    centicredits_after = models.IntegerField(null=False)
    centicredits_delta = models.IntegerField(null=False)
    parent_transaction = models.ForeignKey("self", on_delete=models.PROTECT, null=True, related_name="child_transactions")
    bot = models.ForeignKey(Bot, on_delete=models.PROTECT, null=True, related_name="credit_transactions")
    stripe_payment_intent_id = models.CharField(max_length=255, null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["parent_transaction"], name="unique_child_transaction", condition=models.Q(parent_transaction__isnull=False)),
            models.UniqueConstraint(fields=["organization"], name="unique_root_transaction", condition=models.Q(parent_transaction__isnull=True)),
            models.UniqueConstraint(fields=["bot"], name="unique_bot_transaction", condition=models.Q(bot__isnull=False)),
            models.UniqueConstraint(fields=["stripe_payment_intent_id"], name="unique_stripe_payment_intent_id", condition=models.Q(stripe_payment_intent_id__isnull=False)),
        ]

    def __str__(self):
        return f"{self.organization.name} - {self.centicredits_delta}"

    def credits_delta(self):
        return self.centicredits_delta / 100

    def credits_after(self):
        return self.centicredits_after / 100

    def credits_before(self):
        return self.centicredits_before / 100


class CreditTransactionManager:
    @classmethod
    def create_transaction(cls, organization: Organization, centicredits_delta: int, bot: Bot = None, stripe_payment_intent_id: str = None, description: str = None) -> CreditTransaction:
        """
        Creates a credit transaction for an organization. If no root transaction exists,
        creates one first. Otherwise creates a child transaction.

        Args:
            organization: The Organization instance
            centicredits_delta: The change in credits (positive for additions, negative for deductions)

        Returns:
            CreditTransaction instance

        Raises:
            RuntimeError: If max retries exceeded
        """
        max_retries = 10
        retry_count = 0

        while retry_count < max_retries:
            try:
                with transaction.atomic():
                    # Refresh org state from DB
                    organization.refresh_from_db()

                    # Calculate new credit balance
                    new_balance = organization.centicredits + centicredits_delta

                    # Find the leaf transaction (one with no child transactions)
                    leaf_transaction = CreditTransaction.objects.filter(organization=organization, child_transactions__isnull=True).first()

                    credit_transaction = CreditTransaction.objects.create(
                        organization=organization,
                        centicredits_before=organization.centicredits,
                        centicredits_after=new_balance,
                        centicredits_delta=centicredits_delta,
                        parent_transaction=leaf_transaction,
                        bot=bot,
                        stripe_payment_intent_id=stripe_payment_intent_id,
                        description=description,
                    )

                    # Update organization's credit balance
                    organization.centicredits = new_balance
                    organization.save()

                    return credit_transaction

            except IntegrityError:
                retry_count += 1
                if retry_count >= max_retries:
                    raise RuntimeError("Max retries exceeded while attempting to create credit transaction")
                continue


class BotEventTypes(models.IntegerChoices):
    BOT_PUT_IN_WAITING_ROOM = 1, "Bot Put in Waiting Room"
    BOT_JOINED_MEETING = 2, "Bot Joined Meeting"
    BOT_RECORDING_PERMISSION_GRANTED = 3, "Bot Recording Permission Granted"
    MEETING_ENDED = 4, "Meeting Ended"
    BOT_LEFT_MEETING = 5, "Bot Left Meeting"
    JOIN_REQUESTED = 6, "Bot requested to join meeting"
    FATAL_ERROR = 7, "Bot Encountered Fatal error"
    LEAVE_REQUESTED = 8, "Bot requested to leave meeting"
    COULD_NOT_JOIN = 9, "Bot could not join meeting"
    POST_PROCESSING_COMPLETED = 10, "Post Processing Completed"
    DATA_DELETED = 11, "Data Deleted"
    STAGED = 12, "Bot staged"
    RECORDING_PAUSED = 13, "Recording Paused"
    RECORDING_RESUMED = 14, "Recording Resumed"
    BOT_JOINED_BREAKOUT_ROOM = 15, "Bot joined breakout room"
    BOT_LEFT_BREAKOUT_ROOM = 16, "Bot left breakout room"
    BOT_BEGAN_JOINING_BREAKOUT_ROOM = 17, "Bot began joining breakout room"
    BOT_BEGAN_LEAVING_BREAKOUT_ROOM = 18, "Bot began leaving breakout room"

    @classmethod
    def type_to_api_code(cls, value):
        """Returns the API code for a given type value"""
        mapping = {
            cls.BOT_PUT_IN_WAITING_ROOM: "put_in_waiting_room",
            cls.BOT_JOINED_MEETING: "joined_meeting",
            cls.BOT_RECORDING_PERMISSION_GRANTED: "recording_permission_granted",
            cls.MEETING_ENDED: "meeting_ended",
            cls.BOT_LEFT_MEETING: "left_meeting",
            cls.JOIN_REQUESTED: "join_requested",
            cls.FATAL_ERROR: "fatal_error",
            cls.LEAVE_REQUESTED: "leave_requested",
            cls.COULD_NOT_JOIN: "could_not_join_meeting",
            cls.POST_PROCESSING_COMPLETED: "post_processing_completed",
            cls.DATA_DELETED: "data_deleted",
            cls.STAGED: "staged",
            cls.RECORDING_PAUSED: "recording_paused",
            cls.RECORDING_RESUMED: "recording_resumed",
            cls.BOT_JOINED_BREAKOUT_ROOM: "joined_breakout_room",
            cls.BOT_LEFT_BREAKOUT_ROOM: "left_breakout_room",
            cls.BOT_BEGAN_JOINING_BREAKOUT_ROOM: "began_joining_breakout_room",
            cls.BOT_BEGAN_LEAVING_BREAKOUT_ROOM: "began_leaving_breakout_room",
        }
        return mapping.get(value)


class RealtimeTriggerTypes(models.IntegerChoices):
    MIXED_AUDIO_CHUNK = 101, "Mixed audio chunk"
    BOT_OUTPUT_AUDIO_CHUNK = 102, "Bot output audio chunk"

    @classmethod
    def type_to_api_code(cls, value):
        """Returns the API code for a given type value"""
        mapping = {
            cls.MIXED_AUDIO_CHUNK: "realtime_audio.mixed",
            cls.BOT_OUTPUT_AUDIO_CHUNK: "realtime_audio.bot_output",
        }
        return mapping.get(value)


class BotEventSubTypes(models.IntegerChoices):
    COULD_NOT_JOIN_MEETING_NOT_STARTED_WAITING_FOR_HOST = (
        1,
        "Bot could not join meeting - Meeting Not Started - Waiting for Host",
    )
    FATAL_ERROR_PROCESS_TERMINATED = 2, "Fatal error - Process Terminated"
    COULD_NOT_JOIN_MEETING_ZOOM_AUTHORIZATION_FAILED = (
        3,
        "Bot could not join meeting - Zoom Authorization Failed",
    )
    COULD_NOT_JOIN_MEETING_ZOOM_MEETING_STATUS_FAILED = (
        4,
        "Bot could not join meeting - Zoom Meeting Status Failed",
    )
    COULD_NOT_JOIN_MEETING_UNPUBLISHED_ZOOM_APP = (
        5,
        "Bot could not join meeting - Unpublished Zoom Apps cannot join external meetings. See https://developers.zoom.us/docs/distribute/sdk-feature-review-requirements/",
    )
    FATAL_ERROR_RTMP_CONNECTION_FAILED = 6, "Fatal error - RTMP Connection Failed"
    COULD_NOT_JOIN_MEETING_ZOOM_SDK_INTERNAL_ERROR = (
        7,
        "Bot could not join meeting - Zoom SDK Internal Error",
    )
    FATAL_ERROR_UI_ELEMENT_NOT_FOUND = 8, "Fatal error - UI Element Not Found"
    COULD_NOT_JOIN_MEETING_REQUEST_TO_JOIN_DENIED = (
        9,
        "Bot could not join meeting - Request to join denied",
    )
    LEAVE_REQUESTED_USER_REQUESTED = 10, "Leave requested - User requested"
    LEAVE_REQUESTED_AUTO_LEAVE_SILENCE = 11, "Leave requested - Auto leave silence"
    LEAVE_REQUESTED_AUTO_LEAVE_ONLY_PARTICIPANT_IN_MEETING = 12, "Leave requested - Auto leave only participant in meeting"
    FATAL_ERROR_HEARTBEAT_TIMEOUT = 13, "Fatal error - Heartbeat timeout"
    COULD_NOT_JOIN_MEETING_MEETING_NOT_FOUND = 14, "Bot could not join meeting - Meeting not found"
    FATAL_ERROR_BOT_NOT_LAUNCHED = 15, "Fatal error - Bot not launched"
    COULD_NOT_JOIN_MEETING_WAITING_ROOM_TIMEOUT_EXCEEDED = (
        16,
        "Bot could not join meeting - Waiting room timeout exceeded",
    )
    LEAVE_REQUESTED_AUTO_LEAVE_MAX_UPTIME_EXCEEDED = 17, "Leave requested - Auto leave max uptime exceeded"
    COULD_NOT_JOIN_MEETING_LOGIN_REQUIRED = 18, "Bot could not join meeting - Login required. Use signed in bots: https://docs.attendee.dev/guides/signed-in-bots to resolve."
    COULD_NOT_JOIN_MEETING_BOT_LOGIN_ATTEMPT_FAILED = 19, "Bot could not join meeting - Bot login attempt failed"
    FATAL_ERROR_OUT_OF_CREDITS = 20, "Fatal error - Out of credits"
    COULD_NOT_JOIN_UNABLE_TO_CONNECT_TO_MEETING = 21, "Bot could not join meeting - Unable to connect to meeting. This usually means the meeting password in the URL is incorrect."
    FATAL_ERROR_ATTENDEE_INTERNAL_ERROR = 22, "Fatal error - Attendee internal error"

    @classmethod
    def sub_type_to_api_code(cls, value):
        """Returns the API code for a given sub type value"""
        mapping = {
            cls.COULD_NOT_JOIN_MEETING_NOT_STARTED_WAITING_FOR_HOST: "meeting_not_started_waiting_for_host",
            cls.FATAL_ERROR_PROCESS_TERMINATED: "process_terminated",
            cls.COULD_NOT_JOIN_MEETING_ZOOM_AUTHORIZATION_FAILED: "zoom_authorization_failed",
            cls.COULD_NOT_JOIN_MEETING_ZOOM_MEETING_STATUS_FAILED: "zoom_meeting_status_failed",
            cls.COULD_NOT_JOIN_MEETING_UNPUBLISHED_ZOOM_APP: "unpublished_zoom_app",
            cls.FATAL_ERROR_RTMP_CONNECTION_FAILED: "rtmp_connection_failed",
            cls.COULD_NOT_JOIN_MEETING_ZOOM_SDK_INTERNAL_ERROR: "zoom_sdk_internal_error",
            cls.FATAL_ERROR_UI_ELEMENT_NOT_FOUND: "ui_element_not_found",
            cls.COULD_NOT_JOIN_MEETING_REQUEST_TO_JOIN_DENIED: "request_to_join_denied",
            cls.LEAVE_REQUESTED_USER_REQUESTED: "user_requested",
            cls.LEAVE_REQUESTED_AUTO_LEAVE_SILENCE: "auto_leave_silence",
            cls.LEAVE_REQUESTED_AUTO_LEAVE_ONLY_PARTICIPANT_IN_MEETING: "auto_leave_only_participant_in_meeting",
            cls.FATAL_ERROR_HEARTBEAT_TIMEOUT: "heartbeat_timeout",
            cls.COULD_NOT_JOIN_MEETING_MEETING_NOT_FOUND: "meeting_not_found",
            cls.FATAL_ERROR_BOT_NOT_LAUNCHED: "bot_not_launched",
            cls.COULD_NOT_JOIN_MEETING_WAITING_ROOM_TIMEOUT_EXCEEDED: "waiting_room_timeout_exceeded",
            cls.LEAVE_REQUESTED_AUTO_LEAVE_MAX_UPTIME_EXCEEDED: "auto_leave_max_uptime_exceeded",
            cls.COULD_NOT_JOIN_MEETING_LOGIN_REQUIRED: "login_required",
            cls.COULD_NOT_JOIN_MEETING_BOT_LOGIN_ATTEMPT_FAILED: "bot_login_attempt_failed",
            cls.FATAL_ERROR_OUT_OF_CREDITS: "out_of_credits",
            cls.COULD_NOT_JOIN_UNABLE_TO_CONNECT_TO_MEETING: "unable_to_connect_to_meeting",
            cls.FATAL_ERROR_ATTENDEE_INTERNAL_ERROR: "attendee_internal_error",
        }
        return mapping.get(value)


class BotEvent(models.Model):
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name="bot_events")

    created_at = models.DateTimeField(auto_now_add=True)

    old_state = models.IntegerField(choices=BotStates.choices)
    new_state = models.IntegerField(choices=BotStates.choices)

    event_type = models.IntegerField(choices=BotEventTypes.choices)  # What happened
    event_sub_type = models.IntegerField(choices=BotEventSubTypes.choices, null=True)  # Why it happened
    metadata = models.JSONField(null=False, default=dict)
    requested_bot_action_taken_at = models.DateTimeField(null=True, blank=True)  # For when a bot action is requested, this is the time it was taken
    version = IntegerVersionField()

    def __str__(self):
        old_state_str = BotStates(self.old_state).label
        new_state_str = BotStates(self.new_state).label

        # Base string with event type
        base_str = f"{self.bot.object_id} - [{BotEventTypes(self.event_type).label}"

        # Add event sub type if it exists
        if self.event_sub_type is not None:
            base_str += f" - {BotEventSubTypes(self.event_sub_type).label}"

        # Add state transition
        base_str += f"] - {old_state_str} -> {new_state_str}"

        return base_str

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                check=(
                    # For FATAL_ERROR event type, must have one of the valid event subtypes
                    (Q(event_type=BotEventTypes.FATAL_ERROR) & (Q(event_sub_type=BotEventSubTypes.FATAL_ERROR_PROCESS_TERMINATED) | Q(event_sub_type=BotEventSubTypes.FATAL_ERROR_ATTENDEE_INTERNAL_ERROR) | Q(event_sub_type=BotEventSubTypes.FATAL_ERROR_OUT_OF_CREDITS) | Q(event_sub_type=BotEventSubTypes.FATAL_ERROR_RTMP_CONNECTION_FAILED) | Q(event_sub_type=BotEventSubTypes.FATAL_ERROR_UI_ELEMENT_NOT_FOUND) | Q(event_sub_type=BotEventSubTypes.FATAL_ERROR_HEARTBEAT_TIMEOUT) | Q(event_sub_type=BotEventSubTypes.FATAL_ERROR_BOT_NOT_LAUNCHED)))
                    |
                    # For COULD_NOT_JOIN event type, must have one of the valid event subtypes
                    (Q(event_type=BotEventTypes.COULD_NOT_JOIN) & (Q(event_sub_type=BotEventSubTypes.COULD_NOT_JOIN_MEETING_NOT_STARTED_WAITING_FOR_HOST) | Q(event_sub_type=BotEventSubTypes.COULD_NOT_JOIN_UNABLE_TO_CONNECT_TO_MEETING) | Q(event_sub_type=BotEventSubTypes.COULD_NOT_JOIN_MEETING_WAITING_ROOM_TIMEOUT_EXCEEDED) | Q(event_sub_type=BotEventSubTypes.COULD_NOT_JOIN_MEETING_ZOOM_AUTHORIZATION_FAILED) | Q(event_sub_type=BotEventSubTypes.COULD_NOT_JOIN_MEETING_LOGIN_REQUIRED) | Q(event_sub_type=BotEventSubTypes.COULD_NOT_JOIN_MEETING_BOT_LOGIN_ATTEMPT_FAILED) | Q(event_sub_type=BotEventSubTypes.COULD_NOT_JOIN_MEETING_ZOOM_MEETING_STATUS_FAILED) | Q(event_sub_type=BotEventSubTypes.COULD_NOT_JOIN_MEETING_UNPUBLISHED_ZOOM_APP) | Q(event_sub_type=BotEventSubTypes.COULD_NOT_JOIN_MEETING_ZOOM_SDK_INTERNAL_ERROR) | Q(event_sub_type=BotEventSubTypes.COULD_NOT_JOIN_MEETING_REQUEST_TO_JOIN_DENIED) | Q(event_sub_type=BotEventSubTypes.COULD_NOT_JOIN_MEETING_MEETING_NOT_FOUND)))
                    |
                    # For LEAVE_REQUESTED event type, must have one of the valid event subtypes or be null (for backwards compatibility, this will eventually be removed)
                    (Q(event_type=BotEventTypes.LEAVE_REQUESTED) & (Q(event_sub_type=BotEventSubTypes.LEAVE_REQUESTED_USER_REQUESTED) | Q(event_sub_type=BotEventSubTypes.LEAVE_REQUESTED_AUTO_LEAVE_SILENCE) | Q(event_sub_type=BotEventSubTypes.LEAVE_REQUESTED_AUTO_LEAVE_ONLY_PARTICIPANT_IN_MEETING) | Q(event_sub_type=BotEventSubTypes.LEAVE_REQUESTED_AUTO_LEAVE_MAX_UPTIME_EXCEEDED) | Q(event_sub_type__isnull=True)))
                    |
                    # For all other events, event_sub_type must be null
                    (~Q(event_type=BotEventTypes.FATAL_ERROR) & ~Q(event_type=BotEventTypes.COULD_NOT_JOIN) & ~Q(event_type=BotEventTypes.LEAVE_REQUESTED) & Q(event_sub_type__isnull=True))
                ),
                name="valid_event_type_event_sub_type_combinations",
            )
        ]


class BotEventTransitionFunctions:
    @classmethod
    def get_to_state_for_bot_breakout_room_event(cls, bot: Bot):
        recording_in_progress = RecordingManager.get_recording_in_progress(bot)
        if recording_in_progress is None:
            return BotStates.JOINED_NOT_RECORDING
        if recording_in_progress.state == RecordingStates.IN_PROGRESS:
            return BotStates.JOINED_RECORDING
        if recording_in_progress.state == RecordingStates.PAUSED:
            return BotStates.JOINED_RECORDING_PAUSED
        raise Exception(f"In get_to_state_for_bot_breakout_room_event unexpected recording state for recording in progress: {recording_in_progress.state}")


class BotEventManager:
    # Define valid state transitions for each event type
    VALID_TRANSITIONS = {
        BotEventTypes.JOIN_REQUESTED: {
            "from": [BotStates.READY, BotStates.STAGED],
            "to": BotStates.JOINING,
        },
        BotEventTypes.STAGED: {
            "from": BotStates.SCHEDULED,
            "to": BotStates.STAGED,
        },
        BotEventTypes.COULD_NOT_JOIN: {
            "from": [BotStates.JOINING, BotStates.WAITING_ROOM],
            "to": BotStates.FATAL_ERROR,
        },
        BotEventTypes.FATAL_ERROR: {
            "from": [
                BotStates.JOINING,
                BotStates.JOINED_RECORDING_PAUSED,
                BotStates.JOINED_RECORDING,
                BotStates.JOINED_NOT_RECORDING,
                BotStates.WAITING_ROOM,
                BotStates.LEAVING,
                BotStates.POST_PROCESSING,
                BotStates.STAGED,
                BotStates.SCHEDULED,
                BotStates.JOINING_BREAKOUT_ROOM,
                BotStates.LEAVING_BREAKOUT_ROOM,
            ],
            "to": BotStates.FATAL_ERROR,
        },
        BotEventTypes.BOT_PUT_IN_WAITING_ROOM: {
            "from": BotStates.JOINING,
            "to": BotStates.WAITING_ROOM,
        },
        BotEventTypes.BOT_JOINED_MEETING: {
            "from": [BotStates.WAITING_ROOM, BotStates.JOINING],
            "to": BotStates.JOINED_NOT_RECORDING,
        },
        BotEventTypes.BOT_RECORDING_PERMISSION_GRANTED: {
            "from": BotStates.JOINED_NOT_RECORDING,
            "to": BotStates.JOINED_RECORDING,
        },
        BotEventTypes.MEETING_ENDED: {
            "from": [
                BotStates.JOINED_RECORDING_PAUSED,
                BotStates.JOINED_RECORDING,
                BotStates.JOINED_NOT_RECORDING,
                BotStates.WAITING_ROOM,
                BotStates.JOINING,
                BotStates.LEAVING,
                BotStates.JOINING_BREAKOUT_ROOM,
                BotStates.LEAVING_BREAKOUT_ROOM,
            ],
            "to": BotStates.POST_PROCESSING,
        },
        BotEventTypes.LEAVE_REQUESTED: {
            "from": [
                BotStates.JOINED_RECORDING_PAUSED,
                BotStates.JOINED_RECORDING,
                BotStates.JOINED_NOT_RECORDING,
                BotStates.WAITING_ROOM,
                BotStates.JOINING,
                BotStates.JOINING_BREAKOUT_ROOM,
                BotStates.LEAVING_BREAKOUT_ROOM,
            ],
            "to": BotStates.LEAVING,
        },
        BotEventTypes.BOT_LEFT_MEETING: {
            "from": BotStates.LEAVING,
            "to": BotStates.POST_PROCESSING,
        },
        BotEventTypes.POST_PROCESSING_COMPLETED: {
            "from": BotStates.POST_PROCESSING,
            "to": BotStates.ENDED,
        },
        BotEventTypes.DATA_DELETED: {
            "from": [BotStates.FATAL_ERROR, BotStates.ENDED],
            "to": BotStates.DATA_DELETED,
        },
        BotEventTypes.RECORDING_PAUSED: {
            "from": BotStates.JOINED_RECORDING,
            "to": BotStates.JOINED_RECORDING_PAUSED,
        },
        BotEventTypes.RECORDING_RESUMED: {
            "from": BotStates.JOINED_RECORDING_PAUSED,
            "to": BotStates.JOINED_RECORDING,
        },
        BotEventTypes.BOT_JOINED_BREAKOUT_ROOM: {
            "from": BotStates.JOINING_BREAKOUT_ROOM,
            # This is a special case where the to state depends on the current recording's state, so we specify a function
            # instead of a constant
            "to": BotEventTransitionFunctions.get_to_state_for_bot_breakout_room_event,
        },
        BotEventTypes.BOT_LEFT_BREAKOUT_ROOM: {
            "from": BotStates.LEAVING_BREAKOUT_ROOM,
            # This is a special case where the to state depends on the current recording's state, so we specify a function
            # instead of a constant
            "to": BotEventTransitionFunctions.get_to_state_for_bot_breakout_room_event,
        },
        BotEventTypes.BOT_BEGAN_JOINING_BREAKOUT_ROOM: {
            "from": [BotStates.JOINED_NOT_RECORDING, BotStates.JOINED_RECORDING, BotStates.JOINED_RECORDING_PAUSED],
            "to": BotStates.JOINING_BREAKOUT_ROOM,
        },
        BotEventTypes.BOT_BEGAN_LEAVING_BREAKOUT_ROOM: {
            "from": [BotStates.JOINED_NOT_RECORDING, BotStates.JOINED_RECORDING, BotStates.JOINED_RECORDING_PAUSED],
            "to": BotStates.LEAVING_BREAKOUT_ROOM,
        },
    }

    @classmethod
    def event_can_be_created_for_state(cls, event_type: BotEventTypes, state: BotStates):
        return state in cls.VALID_TRANSITIONS[event_type]["from"]

    @classmethod
    def set_requested_bot_action_taken_at(cls, bot: Bot):
        event_type = {
            BotStates.JOINING: BotEventTypes.JOIN_REQUESTED,
            BotStates.LEAVING: BotEventTypes.LEAVE_REQUESTED,
        }.get(bot.state)

        if event_type is None:
            raise ValueError(f"Bot {bot.object_id} is in state {bot.state}. This is not a valid state to initiate a bot request.")

        last_bot_event = bot.last_bot_event()

        if last_bot_event is None:
            raise ValueError(f"Bot {bot.object_id} has no bot events. This is not a valid state to initiate a bot request.")

        if last_bot_event.event_type != event_type:
            raise ValueError(f"Bot {bot.object_id} has unexpected event type {last_bot_event.event_type}. We expected {event_type} since it's in state {bot.state}")

        if last_bot_event.requested_bot_action_taken_at is not None:
            raise ValueError(f"Bot {bot.object_id} has already initiated this bot request")

        last_bot_event.requested_bot_action_taken_at = timezone.now()
        last_bot_event.save()

    @classmethod
    def is_state_that_can_play_media(cls, state: int):
        return state == BotStates.JOINED_RECORDING or state == BotStates.JOINED_NOT_RECORDING or state == BotStates.JOINED_RECORDING_PAUSED

    @classmethod
    def is_state_that_can_admit_from_waiting_room(cls, state: int):
        return state == BotStates.JOINED_RECORDING or state == BotStates.JOINED_NOT_RECORDING or state == BotStates.JOINED_RECORDING_PAUSED

    @classmethod
    def is_state_that_can_pause_recording(cls, state: int):
        valid_from_states = cls.VALID_TRANSITIONS[BotEventTypes.RECORDING_PAUSED]["from"]
        if not isinstance(valid_from_states, (list, tuple)):
            valid_from_states = [valid_from_states]
        return state in valid_from_states

    @classmethod
    def is_state_that_can_resume_recording(cls, state: int):
        valid_from_states = cls.VALID_TRANSITIONS[BotEventTypes.RECORDING_RESUMED]["from"]
        if not isinstance(valid_from_states, (list, tuple)):
            valid_from_states = [valid_from_states]
        return state in valid_from_states

    @classmethod
    def is_post_meeting_state(cls, state: int):
        return state in BotStates.post_meeting_states()

    @classmethod
    def bot_event_type_should_incur_charges(cls, event_type: int):
        if event_type == BotEventTypes.FATAL_ERROR:
            return False
        return True

    @classmethod
    def get_post_meeting_states_q_filter(cls):
        """Returns a Q object to filter for post meeting states"""
        q_filter = models.Q()
        for state in BotStates.post_meeting_states():
            q_filter |= models.Q(state=state)
        return q_filter

    @classmethod
    def get_pre_meeting_states_q_filter(cls):
        """Returns a Q object to filter for pre meeting states"""
        q_filter = models.Q()
        for state in BotStates.pre_meeting_states():
            q_filter |= models.Q(state=state)
        return q_filter

    @classmethod
    def get_in_meeting_states_q_filter(cls):
        """Returns a Q object to filter for in meeting states"""
        # In meeting states are all states that are not pre-meeting or post-meeting
        pre_meeting_q = cls.get_pre_meeting_states_q_filter()
        post_meeting_q = cls.get_post_meeting_states_q_filter()
        return ~(pre_meeting_q | post_meeting_q)

    @classmethod
    def after_new_state_is_joined_recording(cls, bot: Bot, event_type: BotEventTypes, new_state: BotStates):
        pending_recordings = bot.recordings.filter(state__in=[RecordingStates.NOT_STARTED, RecordingStates.PAUSED])
        if pending_recordings.count() != 1:
            # If bot was joining or leaving a breakout room, we don't expect there to be a recording that is ready to be started
            # so we just return, and don't raise an exception
            if event_type == BotEventTypes.BOT_JOINED_BREAKOUT_ROOM or event_type == BotEventTypes.BOT_LEFT_BREAKOUT_ROOM:
                return
            raise ValidationError(f"Expected exactly one pending recording for bot {bot.object_id} in state {BotStates.state_to_api_code(new_state)}, but found {pending_recordings.count()}")
        pending_recording = pending_recordings.first()
        RecordingManager.set_recording_in_progress(pending_recording)

    @classmethod
    def after_new_state_is_joined_recording_paused(cls, bot: Bot, new_state: BotStates):
        in_progress_recordings = bot.recordings.filter(state=RecordingStates.IN_PROGRESS)
        if in_progress_recordings.count() != 1:
            raise ValidationError(f"Expected exactly one in progress recording for bot {bot.object_id} in state {BotStates.state_to_api_code(new_state)}, but found {in_progress_recordings.count()}")
        in_progress_recording = in_progress_recordings.first()
        RecordingManager.set_recording_paused(in_progress_recording)

    @classmethod
    def after_new_state_is_staged(cls, bot: Bot, new_state: BotStates, event_metadata: dict):
        if "join_at" not in event_metadata:
            raise ValidationError(f"join_at is required in event_metadata for bot {bot.object_id} for transition to state {BotStates.state_to_api_code(new_state)}")
        if bot.join_at.isoformat() != event_metadata["join_at"]:
            raise ValidationError(f"join_at in event_metadata for bot {bot.object_id} for transition to state {BotStates.state_to_api_code(new_state)} is different from the join_at in the database for bot {bot.object_id}")

    # This method handles sets the state for recordings and credits for when the bot transitions to a post meeting state
    # It returns a dictionary of additional event metadata that should be added to the event
    @classmethod
    def after_transition_to_post_meeting_state(cls, bot: Bot, event_type: BotEventTypes, new_state: BotStates) -> dict:
        additional_event_metadata = {}
        additional_event_metadata["bot_duration_seconds"] = bot.bot_duration_seconds()

        # If there is an in progress recording, terminate it
        in_progress_recordings = bot.recordings.filter(state__in=[RecordingStates.IN_PROGRESS, RecordingStates.PAUSED])
        if in_progress_recordings.count() > 1:
            raise ValidationError(f"Expected at most one in progress recording for bot {bot.object_id} in state {BotStates.state_to_api_code(new_state)}, but found {in_progress_recordings.count()}")
        for recording in in_progress_recordings:
            RecordingManager.terminate_recording(recording)
        for failed_transcription_recording in bot.recordings.filter(transcription_state=RecordingTranscriptionStates.FAILED):
            # Collect all transcription errors
            if failed_transcription_recording.transcription_failure_data and failed_transcription_recording.transcription_failure_data.get("failure_reasons"):
                if "transcription_errors" not in additional_event_metadata:
                    additional_event_metadata["transcription_errors"] = []
                additional_event_metadata["transcription_errors"].extend(failed_transcription_recording.transcription_failure_data["failure_reasons"])

        if settings.CHARGE_CREDITS_FOR_BOTS and cls.bot_event_type_should_incur_charges(event_type):
            centicredits_consumed = bot.centicredits_consumed()
            if centicredits_consumed > 0:
                CreditTransactionManager.create_transaction(
                    organization=bot.project.organization,
                    centicredits_delta=-centicredits_consumed,
                    bot=bot,
                    description=f"For bot {bot.object_id}",
                )
                additional_event_metadata["credits_consumed"] = centicredits_consumed / 100

        return additional_event_metadata

    @classmethod
    def create_event(
        cls,
        bot: Bot,
        event_type: int,
        event_sub_type: int = None,
        event_metadata: dict = None,
        max_retries: int = 3,
    ) -> BotEvent:
        """
        Creates a new event and updates the bot state, handling concurrency issues.

        Args:
            bot: The Bot instance
            event_type: The type of event (from BotEventTypes)
            event_sub_type: Optional sub-type of the event
            event_metadata: Optional metadata dictionary (defaults to empty dict)
            max_retries: Maximum number of retries for concurrent modifications

        Returns:
            BotEvent instance

        Raises:
            ValidationError: If the state transition is not valid
        """
        if event_metadata is None:
            event_metadata = {}
        retry_count = 0

        while retry_count < max_retries:
            try:
                with transaction.atomic():
                    # Get fresh bot state
                    bot.refresh_from_db()
                    old_state = bot.state

                    # Get valid transition for this event type
                    transition = cls.VALID_TRANSITIONS.get(event_type)
                    if not transition:
                        raise ValidationError(f"No valid transitions defined for event type {event_type}")

                    # Check if current state is valid for this transition
                    valid_from_states = transition["from"]
                    if not isinstance(valid_from_states, (list, tuple)):
                        valid_from_states = [valid_from_states]

                    if old_state not in valid_from_states:
                        valid_states_labels = [BotStates.state_to_api_code(state) for state in valid_from_states]
                        raise ValidationError(f"Event {BotEventTypes.type_to_api_code(event_type)} not allowed when bot is in state {BotStates.state_to_api_code(old_state)}. It is only allowed in these states: {', '.join(valid_states_labels)}")

                    # Update bot state based on 'to' definition
                    if callable(transition["to"]):
                        # If 'to' is a function, call it with the bot to get the new state
                        new_state = transition["to"](bot)
                    else:
                        # If 'to' is a constant, use it directly
                        new_state = transition["to"]
                    bot.state = new_state

                    bot.save()  # This will raise RecordModifiedError if version mismatch

                    # There's a chance that some other thread in the same process will modify the bot state to be something other than new_state. This should never happen, but we
                    # should raise an exception if it does.
                    if bot.state != new_state:
                        raise ValidationError(f"Bot state was modified by another thread to be '{BotStates.state_to_api_code(bot.state)}' instead of '{BotStates.state_to_api_code(new_state)}'.")

                    # These four blocks below are hooks for things that need to happen when the bot state changes
                    if new_state == BotStates.STAGED:
                        cls.after_new_state_is_staged(bot=bot, new_state=new_state, event_metadata=event_metadata)

                    # If we moved to the recording state
                    if new_state == BotStates.JOINED_RECORDING:
                        cls.after_new_state_is_joined_recording(bot=bot, event_type=event_type, new_state=new_state)

                    if new_state == BotStates.JOINED_RECORDING_PAUSED:
                        cls.after_new_state_is_joined_recording_paused(bot=bot, new_state=new_state)

                    # If we transitioned to a post meeting state
                    transitioned_to_post_meeting_state = cls.is_post_meeting_state(new_state) and not cls.is_post_meeting_state(old_state)
                    if transitioned_to_post_meeting_state:
                        # This helper method handles setting the state for recordings and credits for when the bot transitions to a post meeting state
                        # It returns a dictionary of additional event metadata that should be added to the event
                        additional_event_metadata = cls.after_transition_to_post_meeting_state(bot=bot, event_type=event_type, new_state=new_state)
                        if additional_event_metadata:
                            if event_metadata is None:
                                event_metadata = {}
                            event_metadata.update(additional_event_metadata)

                    # Create event record
                    event = BotEvent.objects.create(
                        bot=bot,
                        old_state=old_state,
                        new_state=bot.state,
                        event_type=event_type,
                        event_sub_type=event_sub_type,
                        metadata=event_metadata,
                    )

                    # Trigger webhook for this event
                    trigger_webhook(
                        webhook_trigger_type=WebhookTriggerTypes.BOT_STATE_CHANGE,
                        bot=bot,
                        payload={
                            "event_type": BotEventTypes.type_to_api_code(event_type),
                            "event_sub_type": BotEventSubTypes.sub_type_to_api_code(event_sub_type),
                            "event_metadata": event_metadata,
                            "old_state": BotStates.state_to_api_code(old_state),
                            "new_state": BotStates.state_to_api_code(bot.state),
                            "created_at": event.created_at.isoformat(),
                        },
                    )

                    return event

            except RecordModifiedError:
                retry_count += 1
                if retry_count >= max_retries:
                    raise
                continue


class Participant(models.Model):
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name="participants")
    uuid = models.CharField(max_length=255)
    user_uuid = models.CharField(max_length=255, null=True, blank=True)
    full_name = models.CharField(max_length=255, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    object_id = models.CharField(max_length=255, unique=True, editable=False, blank=True, null=True)
    is_the_bot = models.BooleanField(default=False, db_default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["bot", "uuid"], name="unique_participant_per_bot")]

    OBJECT_ID_PREFIX = "par_"

    def save(self, *args, **kwargs):
        if not self.object_id:
            # Generate a random 16-character string
            random_string = "".join(random.choices(string.ascii_letters + string.digits, k=16))
            self.object_id = f"{self.OBJECT_ID_PREFIX}{random_string}"
        super().save(*args, **kwargs)

    def __str__(self):
        display_name = self.full_name or self.uuid
        return f"{display_name} in {self.bot.object_id}"


class ParticipantEventTypes(models.IntegerChoices):
    JOIN = 1, "Join"
    LEAVE = 2, "Leave"

    @classmethod
    def type_to_api_code(cls, value):
        """Returns the API code for a given type value"""
        mapping = {
            cls.JOIN: "join",
            cls.LEAVE: "leave",
        }
        return mapping.get(value)


class ParticipantEvent(models.Model):
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="events")
    event_type = models.IntegerField(choices=ParticipantEventTypes.choices)
    object_id = models.CharField(max_length=255, unique=True, editable=False)

    event_data = models.JSONField(null=False, default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    timestamp_ms = models.BigIntegerField()

    OBJECT_ID_PREFIX = "pe_"

    def save(self, *args, **kwargs):
        if not self.object_id:
            # Generate a random 16-character string
            random_string = "".join(random.choices(string.ascii_letters + string.digits, k=16))
            self.object_id = f"{self.OBJECT_ID_PREFIX}{random_string}"
        super().save(*args, **kwargs)


class RecordingStates(models.IntegerChoices):
    NOT_STARTED = 1, "Not Started"
    IN_PROGRESS = 2, "In Progress"
    COMPLETE = 3, "Complete"
    FAILED = 4, "Failed"
    PAUSED = 5, "Paused"

    @classmethod
    def state_to_api_code(cls, value):
        """Returns the API code for a given state value"""
        mapping = {
            cls.NOT_STARTED: "not_started",
            cls.IN_PROGRESS: "in_progress",
            cls.COMPLETE: "complete",
            cls.FAILED: "failed",
            cls.PAUSED: "paused",
        }
        return mapping.get(value)


class RecordingTranscriptionStates(models.IntegerChoices):
    NOT_STARTED = 1, "Not Started"
    IN_PROGRESS = 2, "In Progress"
    COMPLETE = 3, "Complete"
    FAILED = 4, "Failed"

    @classmethod
    def state_to_api_code(cls, value):
        """Returns the API code for a given state value"""
        mapping = {
            cls.NOT_STARTED: "not_started",
            cls.IN_PROGRESS: "in_progress",
            cls.COMPLETE: "complete",
            cls.FAILED: "failed",
        }
        return mapping.get(value)


class RecordingTypes(models.IntegerChoices):
    AUDIO_AND_VIDEO = 1, "Audio and Video"
    AUDIO_ONLY = 2, "Audio Only"
    NO_RECORDING = 3, "No Recording"


class RecordingResolutions(models.TextChoices):
    HD_1080P = "1080p"
    HD_720P = "720p"

    @classmethod
    def get_dimensions(cls, value):
        """Returns the width and height for a given resolution value"""
        dimensions = {
            cls.HD_1080P: (1920, 1080),
            cls.HD_720P: (1280, 720),
        }
        return dimensions.get(value)


class TranscriptionTypes(models.IntegerChoices):
    NON_REALTIME = 1, "Non realtime"
    REALTIME = 2, "Realtime"
    NO_TRANSCRIPTION = 3, "No Transcription"


class TranscriptionProviders(models.IntegerChoices):
    DEEPGRAM = 1, "Deepgram"
    CLOSED_CAPTION_FROM_PLATFORM = 2, "Closed Caption From Platform"
    GLADIA = 3, "Gladia"
    OPENAI = 4, "OpenAI"
    ASSEMBLY_AI = 5, "Assembly AI"
    SARVAM = 6, "Sarvam"
    ELEVENLABS = 7, "ElevenLabs"


from storages.backends.s3boto3 import S3Boto3Storage


class RecordingStorage(S3Boto3Storage):
    bucket_name = settings.AWS_RECORDING_STORAGE_BUCKET_NAME


class Recording(models.Model):
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name="recordings")

    recording_type = models.IntegerField(choices=RecordingTypes.choices, null=False)

    transcription_type = models.IntegerField(choices=TranscriptionTypes.choices, null=False)

    is_default_recording = models.BooleanField(default=False)

    state = models.IntegerField(choices=RecordingStates.choices, default=RecordingStates.NOT_STARTED, null=False)

    transcription_state = models.IntegerField(
        choices=RecordingTranscriptionStates.choices,
        default=RecordingTranscriptionStates.NOT_STARTED,
        null=False,
    )

    transcription_failure_data = models.JSONField(null=True, default=None)

    transcription_provider = models.IntegerField(choices=TranscriptionProviders.choices, null=True, blank=True)

    version = IntegerVersionField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    first_buffer_timestamp_ms = models.BigIntegerField(null=True, blank=True)

    file = models.FileField(storage=RecordingStorage())

    def __str__(self):
        return f"Recording for {self.bot.object_id}"

    @property
    def url(self):
        if not self.file.name:
            return None
        # Generate a temporary signed URL that expires in 30 minutes (1800 seconds)
        return self.file.storage.bucket.meta.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.file.storage.bucket_name, "Key": self.file.name},
            ExpiresIn=1800,
        )

    OBJECT_ID_PREFIX = "rec_"
    object_id = models.CharField(max_length=32, unique=True, editable=False)

    def save(self, *args, **kwargs):
        if not self.object_id:
            # Generate a random 16-character string
            random_string = "".join(random.choices(string.ascii_letters + string.digits, k=16))
            self.object_id = f"{self.OBJECT_ID_PREFIX}{random_string}"
        super().save(*args, **kwargs)


class RecordingManager:
    # Moves the recording into a terminal state.
    # If the recording failed, then mark it as failed.
    # If the recording succeeded, then mark it as succeeded
    # If the transcription failed, then mark it as failed
    # If the transcription succeeded, then mark it as succeeded
    @classmethod
    def terminate_recording(cls, recording: Recording):
        if recording.state == RecordingStates.IN_PROGRESS or recording.state == RecordingStates.PAUSED:
            # If we don't have a recording file AND we intended to generate one, then it failed.
            if recording.file or recording.bot.recording_type() == RecordingTypes.NO_RECORDING:
                RecordingManager.set_recording_complete(recording)
            else:
                RecordingManager.set_recording_failed(recording)

        if recording.transcription_state == RecordingTranscriptionStates.IN_PROGRESS:
            # We'll mark it as failed if there are any failed utterances or any in progress utterances
            any_in_progress_utterances = recording.utterances.filter(transcription__isnull=True, failure_data__isnull=True).exists()
            any_failed_utterances = recording.utterances.filter(failure_data__isnull=False).exists()
            if any_failed_utterances or any_in_progress_utterances:
                failure_reasons = list(recording.utterances.filter(failure_data__has_key="reason").values_list("failure_data__reason", flat=True).distinct())
                if any_in_progress_utterances:
                    failure_reasons.append(TranscriptionFailureReasons.UTTERANCES_STILL_IN_PROGRESS_WHEN_RECORDING_TERMINATED)
                RecordingManager.set_recording_transcription_failed(recording, failure_data={"failure_reasons": failure_reasons})
            else:
                RecordingManager.set_recording_transcription_complete(recording)

    @classmethod
    def get_recording_in_progress(cls, bot: Bot):
        recordings_in_progress = Recording.objects.filter(bot=bot, state__in=[RecordingStates.IN_PROGRESS, RecordingStates.PAUSED])
        if recordings_in_progress.count() == 0:
            return None
        if recordings_in_progress.count() > 1:
            raise Exception(f"Expected at most one recording in progress for bot {bot.object_id}, but found {recordings_in_progress.count()}")
        return recordings_in_progress.first()

    @classmethod
    def set_recording_in_progress(cls, recording: Recording):
        recording.refresh_from_db()

        if recording.state == RecordingStates.IN_PROGRESS:
            return
        if recording.state != RecordingStates.NOT_STARTED and recording.state != RecordingStates.PAUSED:
            raise ValueError(f"Invalid state transition. Recording {recording.id} is in state {recording.get_state_display()}")

        if recording.state != RecordingStates.PAUSED:
            recording.started_at = timezone.now()
        recording.state = RecordingStates.IN_PROGRESS
        recording.save()

    @classmethod
    def set_recording_paused(cls, recording: Recording):
        recording.refresh_from_db()

        if recording.state == RecordingStates.PAUSED:
            return
        if recording.state != RecordingStates.IN_PROGRESS:
            raise ValueError(f"Invalid state transition. Recording {recording.id} is in state {recording.get_state_display()}")

        recording.state = RecordingStates.PAUSED
        recording.save()

    @classmethod
    def set_recording_complete(cls, recording: Recording):
        recording.refresh_from_db()

        if recording.state == RecordingStates.COMPLETE:
            return
        if recording.state != RecordingStates.IN_PROGRESS and recording.state != RecordingStates.PAUSED:
            raise ValueError(f"Invalid state transition. Recording {recording.id} is in state {recording.get_state_display()}")

        recording.state = RecordingStates.COMPLETE
        recording.completed_at = timezone.now()
        recording.save()

        # If there is an in progress transcription recording
        # that has no utterances left to transcribe, set it to complete
        if recording.transcription_state == RecordingTranscriptionStates.IN_PROGRESS and Utterance.objects.filter(recording=recording, transcription__isnull=True).count() == 0:
            RecordingManager.set_recording_transcription_complete(recording)

    @classmethod
    def set_recording_failed(cls, recording: Recording):
        recording.refresh_from_db()

        if recording.state == RecordingStates.FAILED:
            return
        if recording.state != RecordingStates.IN_PROGRESS and recording.state != RecordingStates.PAUSED:
            raise ValueError(f"Invalid state transition. Recording {recording.id} is in state {recording.get_state_display()}")

        # todo: ADD REASON WHY IT FAILED STORAGE? OR MAYBE PUT IN THE EVENTs?

        recording.state = RecordingStates.FAILED
        recording.save()

    @classmethod
    def set_recording_transcription_in_progress(cls, recording: Recording):
        recording.refresh_from_db()

        if recording.transcription_state == RecordingTranscriptionStates.IN_PROGRESS:
            return
        if recording.transcription_state != RecordingTranscriptionStates.NOT_STARTED:
            raise ValueError(f"Invalid state transition. Recording {recording.id} is in transcription state {recording.get_transcription_state_display()}")
        if recording.state != RecordingStates.COMPLETE and recording.state != RecordingStates.FAILED and recording.state != RecordingStates.IN_PROGRESS and recording.state != RecordingStates.PAUSED:
            raise ValueError(f"Invalid state transition. Recording {recording.id} is in recording state {recording.get_state_display()}")

        recording.transcription_state = RecordingTranscriptionStates.IN_PROGRESS
        recording.save()

    @classmethod
    def set_recording_transcription_complete(cls, recording: Recording):
        recording.refresh_from_db()

        if recording.transcription_state == RecordingTranscriptionStates.COMPLETE:
            return
        if recording.transcription_state != RecordingTranscriptionStates.IN_PROGRESS:
            raise ValueError(f"Invalid state transition. Recording {recording.id} is in transcription state {recording.get_transcription_state_display()}")
        if recording.state != RecordingStates.COMPLETE and recording.state != RecordingStates.FAILED:
            raise ValueError(f"Invalid state transition. Recording {recording.id} is in recording state {recording.get_state_display()}")

        recording.transcription_state = RecordingTranscriptionStates.COMPLETE
        recording.save()

    @classmethod
    def set_recording_transcription_failed(cls, recording: Recording, failure_data: dict):
        recording.refresh_from_db()

        if recording.transcription_state == RecordingTranscriptionStates.FAILED:
            return
        if recording.transcription_state != RecordingTranscriptionStates.IN_PROGRESS:
            raise ValueError(f"Invalid state transition. Recording {recording.id} is in transcription state {recording.get_transcription_state_display()}")
        if recording.state != RecordingStates.COMPLETE and recording.state != RecordingStates.FAILED and recording.state != RecordingStates.IN_PROGRESS and recording.state != RecordingStates.PAUSED:
            raise ValueError(f"Invalid state transition. Recording {recording.id} is in recording state {recording.get_state_display()}")

        recording.transcription_state = RecordingTranscriptionStates.FAILED
        recording.transcription_failure_data = failure_data
        recording.save()

    @classmethod
    def is_terminal_state(cls, state: int):
        return state == RecordingStates.COMPLETE or state == RecordingStates.FAILED


class TranscriptionFailureReasons(models.TextChoices):
    CREDENTIALS_NOT_FOUND = "credentials_not_found"
    CREDENTIALS_INVALID = "credentials_invalid"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    AUDIO_UPLOAD_FAILED = "audio_upload_failed"
    TRANSCRIPTION_REQUEST_FAILED = "transcription_request_failed"
    TIMED_OUT = "timed_out"
    INTERNAL_ERROR = "internal_error"
    # This reason applies to the transcription operation as a whole, not a specific utterance
    UTTERANCES_STILL_IN_PROGRESS_WHEN_RECORDING_TERMINATED = "utterances_still_in_progress_when_recording_terminated"


class Utterance(models.Model):
    # If transcription is None and failure_data is not None, then the transcription failed
    # If transcription is not None and failure_data is None, then the transcription succeeded
    # If transcription is None and failure_data is None, then the transcription is in progress

    class Sources(models.IntegerChoices):
        PER_PARTICIPANT_AUDIO = 1, "Per Participant Audio"
        CLOSED_CAPTION_FROM_PLATFORM = 2, "Closed Caption From Platform"

    class AudioFormat(models.IntegerChoices):
        PCM = 1, "PCM"
        MP3 = 2, "MP3"

    recording = models.ForeignKey(Recording, on_delete=models.CASCADE, related_name="utterances")
    participant = models.ForeignKey(Participant, on_delete=models.PROTECT, related_name="utterances")
    audio_blob = models.BinaryField()
    audio_format = models.IntegerField(choices=AudioFormat.choices, default=AudioFormat.PCM, null=True)
    timestamp_ms = models.BigIntegerField()
    duration_ms = models.IntegerField()
    transcription = models.JSONField(null=True, default=None)
    # To keep track of how many retries we've done for this utterance
    transcription_attempt_count = models.IntegerField(default=0)
    failure_data = models.JSONField(null=True, default=None)
    source_uuid = models.CharField(max_length=255, null=True, unique=True)
    sample_rate = models.IntegerField(null=True, default=None)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    source = models.IntegerField(choices=Sources.choices, default=Sources.PER_PARTICIPANT_AUDIO, null=False)

    def __str__(self):
        return f"Utterance at {self.timestamp_ms}ms ({self.duration_ms}ms long)"


class Credentials(models.Model):
    class CredentialTypes(models.IntegerChoices):
        DEEPGRAM = 1, "Deepgram"
        ZOOM_OAUTH = 2, "Zoom OAuth"
        GOOGLE_TTS = 3, "Google Text To Speech"
        GLADIA = 4, "Gladia"
        OPENAI = 5, "OpenAI"
        ASSEMBLY_AI = 6, "Assembly AI"
        SARVAM = 7, "Sarvam"
        TEAMS_BOT_LOGIN = 8, "Teams Bot Login"
        EXTERNAL_MEDIA_STORAGE = 9, "External Media Storage"
        ELEVENLABS = 10, "ElevenLabs"

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="credentials")
    credential_type = models.IntegerField(choices=CredentialTypes.choices, null=False)

    _encrypted_data = models.BinaryField(
        null=True,
        editable=False,  # Prevents editing through admin/forms
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["project", "credential_type"], name="unique_project_credentials")]

    def set_credentials(self, credentials_dict):
        """Encrypt and save credentials"""
        f = Fernet(settings.CREDENTIALS_ENCRYPTION_KEY)
        json_data = json.dumps(credentials_dict)
        self._encrypted_data = f.encrypt(json_data.encode())
        self.save()

    def get_credentials(self):
        """Decrypt and return credentials"""
        if not self._encrypted_data:
            return None
        f = Fernet(settings.CREDENTIALS_ENCRYPTION_KEY)
        decrypted_data = f.decrypt(bytes(self._encrypted_data))
        return json.loads(decrypted_data.decode())

    def __str__(self):
        return f"{self.project.name} - {self.get_credential_type_display()}"


class MediaBlob(models.Model):
    VALID_AUDIO_CONTENT_TYPES = [
        ("audio/mp3", "MP3 Audio"),
    ]
    VALID_VIDEO_CONTENT_TYPES = []
    VALID_IMAGE_CONTENT_TYPES = [
        ("image/png", "PNG Image"),
    ]

    OBJECT_ID_PREFIX = "blob_"
    object_id = models.CharField(max_length=32, unique=True, editable=False)

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="media_blobs")

    blob = models.BinaryField()
    content_type = models.CharField(
        max_length=255,
        choices=VALID_AUDIO_CONTENT_TYPES + VALID_VIDEO_CONTENT_TYPES + VALID_IMAGE_CONTENT_TYPES,
    )
    checksum = models.CharField(max_length=64, editable=False)  # SHA-256 hash is 64 chars
    created_at = models.DateTimeField(auto_now_add=True)
    duration_ms = models.IntegerField()

    def save(self, *args, **kwargs):
        if not self.object_id:
            # Generate a random 16-character string
            random_string = "".join(random.choices(string.ascii_letters + string.digits, k=16))
            self.object_id = f"{self.OBJECT_ID_PREFIX}{random_string}"

        if len(self.blob) > 10485760:
            raise ValueError("blob exceeds 10MB limit")

        # Calculate checksum if this is a new object
        if not self.checksum:
            self.checksum = hashlib.sha256(self.blob).hexdigest()

        # Calculate duration for audio content types
        if any(content_type == self.content_type for content_type, _ in self.VALID_AUDIO_CONTENT_TYPES):
            from .utils import calculate_audio_duration_ms

            self.duration_ms = calculate_audio_duration_ms(self.blob, self.content_type)

        if any(content_type == self.content_type for content_type, _ in self.VALID_IMAGE_CONTENT_TYPES):
            self.duration_ms = 0

        if self.id:
            raise ValueError("MediaBlob objects cannot be updated")

        super().save(*args, **kwargs)

    class Meta:
        # Ensure we don't store duplicate blobs within a project
        constraints = [models.UniqueConstraint(fields=["project", "checksum"], name="unique_project_blob")]

    def __str__(self):
        return f"{self.object_id} ({len(self.blob)} bytes)"

    @classmethod
    def get_or_create_from_blob(cls, project: Project, blob: bytes, content_type: str) -> "MediaBlob":
        checksum = hashlib.sha256(blob).hexdigest()

        existing = cls.objects.filter(project=project, checksum=checksum).first()

        if existing:
            return existing

        return cls.objects.create(project=project, blob=blob, content_type=content_type)


class TextToSpeechProviders(models.IntegerChoices):
    GOOGLE = 1, "Google"


class BotMediaRequestMediaTypes(models.IntegerChoices):
    IMAGE = 1, "Image"
    AUDIO = 2, "Audio"
    VIDEO = 3, "Video"


class BotMediaRequestStates(models.IntegerChoices):
    ENQUEUED = 1, "Enqueued"
    PLAYING = 2, "Playing"
    DROPPED = 3, "Dropped"
    FINISHED = 4, "Finished"
    FAILED_TO_PLAY = 5, "Failed to Play"

    @classmethod
    def state_to_api_code(cls, value):
        """Returns the API code for a given state value"""
        mapping = {
            cls.ENQUEUED: "enqueued",
            cls.PLAYING: "playing",
            cls.DROPPED: "dropped",
            cls.FINISHED: "finished",
            cls.FAILED_TO_PLAY: "failed_to_play",
        }
        return mapping.get(value)


class BotMediaRequest(models.Model):
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name="media_requests")

    text_to_speak = models.TextField(null=True, blank=True)

    text_to_speech_settings = models.JSONField(null=True, default=None)

    media_url = models.URLField(null=True, blank=True)

    media_blob = models.ForeignKey(
        MediaBlob,
        on_delete=models.PROTECT,
        related_name="bot_media_requests",
        null=True,
        blank=True,
    )

    media_type = models.IntegerField(choices=BotMediaRequestMediaTypes.choices, null=False)

    state = models.IntegerField(
        choices=BotMediaRequestStates.choices,
        default=BotMediaRequestStates.ENQUEUED,
        null=False,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def duration_ms(self):
        return self.media_blob.duration_ms

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["bot", "media_type"],
                condition=Q(state=BotMediaRequestStates.PLAYING),
                name="unique_playing_media_request_per_bot_and_type",
            )
        ]


class BotMediaRequestManager:
    @classmethod
    def set_media_request_playing(cls, media_request: BotMediaRequest):
        if media_request.state == BotMediaRequestStates.PLAYING:
            return
        if media_request.state != BotMediaRequestStates.ENQUEUED:
            raise ValueError(f"Invalid state transition. Media request {media_request.id} is in state {media_request.get_state_display()}")

        media_request.state = BotMediaRequestStates.PLAYING
        media_request.save()

    @classmethod
    def set_media_request_finished(cls, media_request: BotMediaRequest):
        if media_request.state == BotMediaRequestStates.FINISHED:
            return
        if media_request.state != BotMediaRequestStates.PLAYING:
            raise ValueError(f"Invalid state transition. Media request {media_request.id} is in state {media_request.get_state_display()}")

        media_request.state = BotMediaRequestStates.FINISHED
        media_request.save()

    @classmethod
    def set_media_request_failed_to_play(cls, media_request: BotMediaRequest):
        if media_request.state == BotMediaRequestStates.FAILED_TO_PLAY:
            return
        if media_request.state != BotMediaRequestStates.PLAYING:
            raise ValueError(f"Invalid state transition. Media request {media_request.id} is in state {media_request.get_state_display()}")

        media_request.state = BotMediaRequestStates.FAILED_TO_PLAY
        media_request.save()

    @classmethod
    def set_media_request_dropped(cls, media_request: BotMediaRequest):
        if media_request.state == BotMediaRequestStates.DROPPED:
            return
        if media_request.state != BotMediaRequestStates.PLAYING and media_request.state != BotMediaRequestStates.ENQUEUED:
            raise ValueError(f"Invalid state transition. Media request {media_request.id} is in state {media_request.get_state_display()}")

        media_request.state = BotMediaRequestStates.DROPPED
        media_request.save()


class BotChatMessageRequestStates(models.IntegerChoices):
    ENQUEUED = 1, "Enqueued"
    SENT = 2, "Sent"
    FAILED = 3, "Failed"


class BotChatMessageToOptions(models.TextChoices):
    EVERYONE = "everyone"
    SPECIFIC_USER = "specific_user"
    EVERYONE_BUT_HOST = "everyone_but_host"


class BotChatMessageRequest(models.Model):
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name="chat_message_requests")

    to_user_uuid = models.CharField(max_length=255, null=True, blank=True)
    to = models.CharField(max_length=50, choices=BotChatMessageToOptions.choices, null=False)

    message = models.TextField(null=False)
    additional_data = models.JSONField(null=False, default=dict)

    state = models.IntegerField(
        choices=BotChatMessageRequestStates.choices,
        default=BotChatMessageRequestStates.ENQUEUED,
        null=False,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    sent_at_timestamp_ms = models.BigIntegerField(null=True, blank=True)
    failure_data = models.JSONField(null=True, default=None)


class BotChatMessageRequestManager:
    @classmethod
    def set_chat_message_request_sent(cls, chat_message_request: BotChatMessageRequest):
        if chat_message_request.state == BotChatMessageRequestStates.SENT:
            return
        if chat_message_request.state != BotChatMessageRequestStates.ENQUEUED:
            raise ValueError(f"Invalid state transition. Chat message request {chat_message_request.id} is in state {chat_message_request.get_state_display()}")

        chat_message_request.state = BotChatMessageRequestStates.SENT
        chat_message_request.sent_at_timestamp_ms = int(timezone.now().timestamp() * 1000)
        chat_message_request.save()

    @classmethod
    def set_chat_message_request_failed(cls, chat_message_request: BotChatMessageRequest):
        if chat_message_request.state == BotChatMessageRequestStates.FAILED:
            return
        if chat_message_request.state != BotChatMessageRequestStates.ENQUEUED:
            raise ValueError(f"Invalid state transition. Chat message request {chat_message_request.id} is in state {chat_message_request.get_state_display()}")
        chat_message_request.state = BotChatMessageRequestStates.FAILED
        chat_message_request.save()


class BotDebugScreenshotStorage(S3Boto3Storage):
    bucket_name = settings.AWS_RECORDING_STORAGE_BUCKET_NAME


class BotDebugScreenshot(models.Model):
    OBJECT_ID_PREFIX = "shot_"
    object_id = models.CharField(max_length=32, unique=True, editable=False)

    bot_event = models.ForeignKey(BotEvent, on_delete=models.CASCADE, related_name="debug_screenshots")

    metadata = models.JSONField(null=False, default=dict)

    file = models.FileField(storage=BotDebugScreenshotStorage())
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.object_id:
            # Generate a random 16-character string
            random_string = "".join(random.choices(string.ascii_letters + string.digits, k=16))
            self.object_id = f"{self.OBJECT_ID_PREFIX}{random_string}"
        super().save(*args, **kwargs)

    @property
    def url(self):
        if not self.file.name:
            return None
        # Generate a temporary signed URL that expires in 30 minutes (1800 seconds)
        return self.file.storage.bucket.meta.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.file.storage.bucket_name, "Key": self.file.name},
            ExpiresIn=1800,
        )

    def __str__(self):
        return f"Debug Screenshot {self.object_id} for event {self.bot_event}"


class WebhookSecret(models.Model):
    _secret = models.BinaryField(
        null=True,
        editable=False,  # Prevents editing through admin/forms
    )
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="webhook_secrets")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def get_secret(self):
        """Decrypt and return secret"""
        if not self._secret:
            return None
        try:
            f = Fernet(settings.CREDENTIALS_ENCRYPTION_KEY)
            decrypted_data = f.decrypt(bytes(self._secret))
            return decrypted_data
        except (InvalidToken, ValueError):
            return None

    def save(self, *args, **kwargs):
        # Only generate a secret if this is a new object (not yet saved to DB)
        if not self.pk and not self._secret:
            secret = secrets.token_bytes(32)
            f = Fernet(settings.CREDENTIALS_ENCRYPTION_KEY)
            self._secret = f.encrypt(secret)
        super().save(*args, **kwargs)


class WebhookTriggerTypes(models.IntegerChoices):
    BOT_STATE_CHANGE = 1, "Bot State Change"
    TRANSCRIPT_UPDATE = 2, "Transcript Update"
    CHAT_MESSAGES_UPDATE = 3, "Chat Messages Update"
    PARTICIPANT_EVENTS_JOIN_LEAVE = 4, "Participant Join/Leave"
    CALENDAR_EVENTS_UPDATE = 5, "Calendar Events Update"
    CALENDAR_STATE_CHANGE = 6, "Calendar State Change"
    # add other event types here

    @classmethod
    def _get_mapping(cls):
        """Get the trigger type to API code mapping"""
        return {
            cls.BOT_STATE_CHANGE: "bot.state_change",
            cls.TRANSCRIPT_UPDATE: "transcript.update",
            cls.CHAT_MESSAGES_UPDATE: "chat_messages.update",
            cls.PARTICIPANT_EVENTS_JOIN_LEAVE: "participant_events.join_leave",
            cls.CALENDAR_EVENTS_UPDATE: "calendar.events_update",
            cls.CALENDAR_STATE_CHANGE: "calendar.state_change",
        }

    @classmethod
    def trigger_type_to_api_code(cls, value):
        return cls._get_mapping().get(value)

    @classmethod
    def api_code_to_trigger_type(cls, api_code):
        """Convert API code string to trigger type integer."""
        mapping = cls._get_mapping()
        api_code_to_trigger = {api_code: trigger_type.value for trigger_type, api_code in mapping.items()}
        return api_code_to_trigger.get(api_code)


class WebhookSubscription(models.Model):
    def default_triggers():
        return [WebhookTriggerTypes.BOT_STATE_CHANGE]

    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="webhook_subscriptions")
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name="bot_webhook_subscriptions", null=True, blank=True)

    OBJECT_ID_PREFIX = "webhook_"
    object_id = models.CharField(max_length=32, unique=True, editable=False)

    def save(self, *args, **kwargs):
        if not self.object_id:
            # Generate a random 16-character string
            random_string = "".join(random.choices(string.ascii_letters + string.digits, k=16))
            self.object_id = f"{self.OBJECT_ID_PREFIX}{random_string}"
        super().save(*args, **kwargs)

    url = models.URLField()
    triggers = models.JSONField(default=default_triggers)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class WebhookDeliveryAttemptStatus(models.IntegerChoices):
    PENDING = 1, "Pending"
    SUCCESS = 2, "Success"
    FAILURE = 3, "Failure"


class WebhookDeliveryAttempt(models.Model):
    webhook_subscription = models.ForeignKey(WebhookSubscription, on_delete=models.CASCADE, related_name="webhookdelivery_attempts")
    webhook_trigger_type = models.IntegerField(choices=WebhookTriggerTypes.choices, default=WebhookTriggerTypes.BOT_STATE_CHANGE, null=False)
    idempotency_key = models.UUIDField(unique=True, editable=False)
    bot = models.ForeignKey(Bot, on_delete=models.SET_NULL, null=True, related_name="webhook_delivery_attempts")
    calendar = models.ForeignKey(Calendar, on_delete=models.SET_NULL, null=True, related_name="webhook_delivery_attempts")
    payload = models.JSONField(default=dict)
    status = models.IntegerField(choices=WebhookDeliveryAttemptStatus.choices, default=WebhookDeliveryAttemptStatus.PENDING, null=False)
    attempt_count = models.IntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    succeeded_at = models.DateTimeField(null=True, blank=True)
    response_body_list = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def add_to_response_body_list(self, response_body):
        """Add content to the response body list without saving."""
        if self.response_body_list is None:
            self.response_body_list = [response_body]
        else:
            self.response_body_list.append(response_body)


class ChatMessageToOptions(models.IntegerChoices):
    ONLY_BOT = 1, "only_bot"
    EVERYONE = 2, "everyone"


class ChatMessage(models.Model):
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name="chat_messages")
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="chat_messages")
    to = models.IntegerField(choices=ChatMessageToOptions.choices, null=False)
    timestamp = models.IntegerField()
    additional_data = models.JSONField(null=False, default=dict)
    object_id = models.CharField(max_length=32, unique=True, editable=False)

    OBJECT_ID_PREFIX = "msg_"
    object_id = models.CharField(max_length=32, unique=True, editable=False)
    source_uuid = models.CharField(max_length=255, null=True, unique=True)

    def save(self, *args, **kwargs):
        if not self.object_id:
            # Generate a random 16-character string
            random_string = "".join(random.choices(string.ascii_letters + string.digits, k=16))
            self.object_id = f"{self.OBJECT_ID_PREFIX}{random_string}"
        super().save(*args, **kwargs)


class BotResourceSnapshot(models.Model):
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name="resource_snapshots")
    data = models.JSONField(null=False, default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Resource snapshot for {self.bot.object_id} at {self.created_at}"
