from django.db import models
from django.utils.crypto import get_random_string
import hashlib
from accounts.models import Organization
import string
import random
from concurrency.fields import IntegerVersionField
from django.db import transaction
from django.core.exceptions import ValidationError
from concurrency.exceptions import RecordModifiedError
from django.db import models
from django.db.models import Q
from cryptography.fernet import Fernet
from django.conf import settings
import json

# Create your models here.

class Project(models.Model):
    name = models.CharField(max_length=255)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name='projects'
    )

    OBJECT_ID_PREFIX = 'proj_'
    object_id = models.CharField(max_length=32, unique=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.object_id:
            # Generate a random 16-character string
            random_string = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            self.object_id = f"{self.OBJECT_ID_PREFIX}{random_string}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class ApiKey(models.Model):
    name = models.CharField(max_length=255)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='api_keys'
    )

    OBJECT_ID_PREFIX = 'key_'
    object_id = models.CharField(max_length=32, unique=True, editable=False)

    def save(self, *args, **kwargs):
        if not self.object_id:
            # Generate a random 16-character string
            random_string = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
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
        
        instance = cls(
            project=project,
            name=name,
            key_hash=key_hash
        )
        instance.save()
        
        # Return both the instance and the plain text key
        # The plain text key will only be available during creation
        return instance, api_key

    def __str__(self):
        return f"{self.name} ({self.project.name})"

class BotStates(models.IntegerChoices):
    READY = 1, 'Ready'
    JOINING_REQ_NOT_STARTED_BY_BOT = 2, 'Joining - Request Not Started By Bot'
    JOINING_REQ_STARTED_BY_BOT = 3, 'Joining - Request Started By Bot'
    JOINED_NOT_RECORDING = 4, 'Joined - Not Recording'
    JOINED_RECORDING = 5, 'Joined - Recording'
    LEAVING_REQ_NOT_STARTED_BY_BOT = 6, 'Leaving - Request Not Started By Bot'
    LEAVING_REQ_STARTED_BY_BOT = 7, 'Leaving - Request Started By Bot'
    ENDED = 8, 'Ended'
    FATAL_ERROR = 9, 'Fatal Error'
    WAITING_ROOM = 10, 'Waiting Room'

    @classmethod
    def state_to_api_code(cls, value):
        """Returns the API code for a given state value"""
        mapping = {
            cls.READY: 'ready',
            # These are different states under the hood, but we want to return the same api code for them
            cls.JOINING_REQ_NOT_STARTED_BY_BOT: 'joining',
            cls.JOINING_REQ_STARTED_BY_BOT: 'joining',
            cls.JOINED_NOT_RECORDING: 'joined_not_recording',
            cls.JOINED_RECORDING: 'joined_recording',
            # These are different states under the hood, but we want to return the same api code for them
            cls.LEAVING_REQ_NOT_STARTED_BY_BOT: 'leaving',
            cls.LEAVING_REQ_STARTED_BY_BOT: 'leaving',
            cls.ENDED: 'ended',
            cls.FATAL_ERROR: 'fatal_error',
            cls.WAITING_ROOM: 'waiting_room'
        }
        return mapping.get(value)

class BotSubStates(models.IntegerChoices):
    FATAL_ERROR_MEETING_NOT_STARTED_WAITING_FOR_HOST = 1, 'Fatal Error - Meeting Not Started - Waiting for Host'
    FATAL_ERROR_PROCESS_TERMINATED = 2, 'Fatal Error - Process Terminated'

    @classmethod
    def state_to_api_code(cls, value):
        """Returns the API code for a given state value"""
        mapping = {
            cls.FATAL_ERROR_MEETING_NOT_STARTED_WAITING_FOR_HOST: 'meeting_not_started',
            cls.FATAL_ERROR_PROCESS_TERMINATED: 'process_terminated'
        }
        return mapping.get(value)

class Bot(models.Model):
    OBJECT_ID_PREFIX = 'bot_'

    object_id = models.CharField(max_length=32, unique=True, editable=False)

    project = models.ForeignKey(
        Project,
        on_delete=models.PROTECT,
        related_name='bots'
    )

    meeting_url = models.CharField(max_length=511)
    meeting_uuid = models.CharField(max_length=511, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    version = IntegerVersionField()

    state = models.IntegerField(
        choices=BotStates.choices,
        default=BotStates.READY,
        null=False
    )

    sub_state = models.IntegerField(
        choices=BotSubStates.choices,
        default=None,
        null=True
    )

    def save(self, *args, **kwargs):
        if not self.object_id:
            # Generate a random 16-character string
            random_string = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            self.object_id = f"{self.OBJECT_ID_PREFIX}{random_string}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.object_id} - {self.project.name} in {self.meeting_url}"

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    # For FATAL_ERROR state, must have one of the valid sub-states
                    (Q(state=BotStates.FATAL_ERROR) & 
                     (Q(sub_state=BotSubStates.FATAL_ERROR_MEETING_NOT_STARTED_WAITING_FOR_HOST) |
                      Q(sub_state=BotSubStates.FATAL_ERROR_PROCESS_TERMINATED))) |
                    
                    # For all other states, sub_state must be null
                    (~Q(state=BotStates.FATAL_ERROR) & Q(sub_state__isnull=True))
                ),
                name='valid_state_substate_combinations'
            )
        ]

class BotEvent(models.Model):
    class EventTypes(models.IntegerChoices):
        JOIN_REQUESTED_BY_API = 1, 'Join Requested by API'
        JOIN_REQUESTED_BY_BOT = 2, 'Join Requested by Bot'
        WAITING_FOR_HOST_TO_START_MEETING_MSG_RECEIVED = 3, 'Waiting for Host to Start Meeting Message Received'
        BOT_PUT_IN_WAITING_ROOM = 4, 'Bot Put in Waiting Room'
        BOT_JOINED_MEETING = 5, 'Bot Joined Meeting'
        BOT_RECORDING_PERMISSION_GRANTED = 6, 'Bot Recording Permission Granted'
        PROCESS_TERMINATED = 7, 'Process Terminated'
        MEETING_ENDED = 8, 'Meeting Ended',
        LEAVE_REQUESTED_BY_API = 9, 'Leave Requested by API'
        LEAVE_REQUESTED_BY_BOT = 10, 'Leave Requested by Bot'
        BOT_LEFT_MEETING = 11, 'Bot Left Meeting'

    bot = models.ForeignKey(
        Bot,
        on_delete=models.CASCADE,
        related_name='bot_events'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    old_state = models.IntegerField(choices=BotStates.choices)
    new_state = models.IntegerField(choices=BotStates.choices)

    old_sub_state = models.IntegerField(choices=BotSubStates.choices, null=True)
    new_sub_state = models.IntegerField(choices=BotSubStates.choices, null=True)

    event_type = models.IntegerField(choices=EventTypes.choices)
    version = models.BigIntegerField()

    def __str__(self):
        old_state_str = BotStates(self.old_state).label
        new_state_str = BotStates(self.new_state).label
        
        if self.old_sub_state:
            old_state_str += f" ({BotSubStates(self.old_sub_state).label})"
        if self.new_sub_state:
            new_state_str += f" ({BotSubStates(self.new_sub_state).label})"
            
        return (f"{self.bot.object_id} - ["
                f"{self.EventTypes(self.event_type).label}] - "
                f"{old_state_str} -> {new_state_str}")

    class Meta:
        ordering = ['created_at']

class BotEventManager:
    # Define valid state transitions for each event type

    VALID_TRANSITIONS = {
        BotEvent.EventTypes.JOIN_REQUESTED_BY_API: {
            'from': BotStates.READY,
            'to': BotStates.JOINING_REQ_NOT_STARTED_BY_BOT,
        },
        BotEvent.EventTypes.JOIN_REQUESTED_BY_BOT: {
            'from': BotStates.JOINING_REQ_NOT_STARTED_BY_BOT,
            'to': BotStates.JOINING_REQ_STARTED_BY_BOT,
        },
        BotEvent.EventTypes.WAITING_FOR_HOST_TO_START_MEETING_MSG_RECEIVED: {
            'from': BotStates.JOINING_REQ_STARTED_BY_BOT,
            'to': {
                'state': BotStates.FATAL_ERROR,
                'sub_state': BotSubStates.FATAL_ERROR_MEETING_NOT_STARTED_WAITING_FOR_HOST
            },
        },
        BotEvent.EventTypes.BOT_PUT_IN_WAITING_ROOM: {
            'from': BotStates.JOINING_REQ_STARTED_BY_BOT,
            'to': BotStates.WAITING_ROOM,
        },
        BotEvent.EventTypes.BOT_JOINED_MEETING: {
            'from': [BotStates.WAITING_ROOM, BotStates.JOINING_REQ_STARTED_BY_BOT],
            'to': BotStates.JOINED_NOT_RECORDING,
        },
        BotEvent.EventTypes.BOT_RECORDING_PERMISSION_GRANTED: {
            'from': BotStates.JOINED_NOT_RECORDING,
            'to': BotStates.JOINED_RECORDING,
        },
        BotEvent.EventTypes.MEETING_ENDED: {
            'from': [BotStates.JOINED_RECORDING, BotStates.JOINED_NOT_RECORDING,
                    BotStates.WAITING_ROOM, BotStates.JOINING_REQ_STARTED_BY_BOT, 
                    BotStates.LEAVING_REQ_NOT_STARTED_BY_BOT, BotStates.LEAVING_REQ_STARTED_BY_BOT],
            'to': BotStates.ENDED,
        },
        BotEvent.EventTypes.PROCESS_TERMINATED: {
            'from': [BotStates.JOINED_RECORDING, BotStates.JOINED_NOT_RECORDING,
                    BotStates.WAITING_ROOM, BotStates.JOINING_REQ_STARTED_BY_BOT],
            'to': {
                'state': BotStates.FATAL_ERROR,
                'sub_state': BotSubStates.FATAL_ERROR_PROCESS_TERMINATED
            },
        },
        BotEvent.EventTypes.LEAVE_REQUESTED_BY_API: {
            'from': [BotStates.JOINED_RECORDING, BotStates.JOINED_NOT_RECORDING,
                    BotStates.WAITING_ROOM, BotStates.JOINING_REQ_STARTED_BY_BOT],
            'to': BotStates.LEAVING_REQ_NOT_STARTED_BY_BOT,
        },
        BotEvent.EventTypes.LEAVE_REQUESTED_BY_BOT: {
            'from': BotStates.LEAVING_REQ_NOT_STARTED_BY_BOT,
            'to': BotStates.LEAVING_REQ_STARTED_BY_BOT,
        },
        BotEvent.EventTypes.BOT_LEFT_MEETING: {
            'from': BotStates.LEAVING_REQ_STARTED_BY_BOT,
            'to': BotStates.ENDED,
        },
    }

    @classmethod
    def is_terminal_state(cls, state: int):
        return state == BotStates.ENDED or state == BotStates.FATAL_ERROR

    @classmethod
    def create_event(cls, bot: Bot, event_type: int, max_retries: int = 3) -> BotEvent:
        """
        Creates a new event and updates the bot state, handling concurrency issues.
        
        Args:
            bot: The Bot instance
            event_type: The type of event (from BotEvent.EventTypes)
            max_retries: Maximum number of retries for concurrent modifications
        
        Returns:
            BotEvent instance
        
        Raises:
            ValidationError: If the state transition is not valid
        """
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                with transaction.atomic():
                    # Get fresh bot state
                    bot.refresh_from_db()
                    old_state = bot.state
                    old_sub_state = bot.sub_state

                    # Get valid transition for this event type
                    transition = cls.VALID_TRANSITIONS.get(event_type)
                    if not transition:
                        raise ValidationError(f"No valid transitions defined for event type {event_type}")

                    # Check if current state is valid for this transition
                    valid_from_states = transition['from']
                    if isinstance(valid_from_states, (list, tuple)):
                        if old_state not in valid_from_states:
                            raise ValidationError(
                                f"Invalid state transition. Event {event_type} not allowed in state {old_state}. "
                                f"Valid states are: {valid_from_states}"
                            )
                    elif old_state != valid_from_states:
                        raise ValidationError(
                            f"Invalid state transition. Event {event_type} not allowed in state {old_state}. "
                            f"Valid state is: {valid_from_states}"
                        )

                    # Update bot state based on 'to' definition
                    new_state = transition['to']
                    if isinstance(new_state, dict):
                        bot.state = new_state['state']
                        bot.sub_state = new_state['sub_state']
                    else:
                        bot.state = new_state
                        bot.sub_state = None

                    bot.save()  # This will raise RecordModifiedError if version mismatch
                    
                    # Create event record
                    event = BotEvent.objects.create(
                        bot=bot,
                        old_state=old_state,
                        old_sub_state=old_sub_state,
                        new_state=bot.state,
                        new_sub_state=bot.sub_state,
                        event_type=event_type,
                        version=bot.version
                    )

                    # If we're in a terminal state 
                    if cls.is_terminal_state(new_state):
                        # if no utterances are left, set the transcription analysis tasks that are in progress to complete
                        if Utterance.objects.filter(bot=bot, transcription__isnull=True).count() == 0:
                            analysis_tasks = bot.analysis_tasks.filter(analysis_type=AnalysisTaskTypes.SPEECH_TRANSCRIPTION, state=AnalysisTaskStates.IN_PROGRESS)
                            for analysis_task in analysis_tasks:
                                AnalysisTaskManager.set_task_complete(analysis_task)

                        # Start the recording generation task
                        from .tasks import generate_recording
                        generate_recording.delay(bot.id)

                    return event
                    
            except RecordModifiedError:
                retry_count += 1
                if retry_count >= max_retries:
                    raise
                continue

class Participant(models.Model):
    bot = models.ForeignKey(
        Bot,
        on_delete=models.CASCADE,
        related_name='participants'
    )
    uuid = models.CharField(max_length=255)
    user_uuid = models.CharField(max_length=255, null=True, blank=True)
    full_name = models.CharField(max_length=255, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['bot', 'uuid'],
                name='unique_participant_per_bot'
            )
        ]

    def __str__(self):
        display_name = self.full_name or self.uuid
        return f"{display_name} in {self.bot.object_id}"

class Utterance(models.Model):
    class AudioFormat(models.IntegerChoices):
        PCM = 1, 'PCM'
        MP3 = 2, 'MP3'

    bot = models.ForeignKey(
        Bot,
        on_delete=models.CASCADE,
        related_name='utterances'
    )
    participant = models.ForeignKey(
        Participant,
        on_delete=models.PROTECT,
        related_name='utterances'
    )
    audio_blob = models.BinaryField()
    audio_format = models.IntegerField(
        choices=AudioFormat.choices,
        default=AudioFormat.PCM
    )
    timeline_ms = models.IntegerField()
    duration_ms = models.IntegerField()
    transcription = models.JSONField(null=True, default=None)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Utterance at {self.timeline_ms}ms ({self.duration_ms}ms long)"

class AnalysisTaskStates(models.IntegerChoices):
    NOT_STARTED = 1, 'Not Started'
    IN_PROGRESS = 2, 'In Progress'
    COMPLETE = 3, 'Complete'
    FAILED = 4, 'Failed'

    @classmethod
    def state_to_api_code(cls, value):
        """Returns the API code for a given state value"""
        mapping = {
            cls.NOT_STARTED: 'not_started',
            cls.IN_PROGRESS: 'in_progress',
            cls.COMPLETE: 'complete',
            cls.FAILED: 'failed'
        }
        return mapping.get(value)

class AnalysisTaskSubStates(models.IntegerChoices):
    AUTHORIZATION_FAILED = 1, 'Authorization Failed'

class AnalysisTaskTypes(models.IntegerChoices):
    SPEECH_TRANSCRIPTION = 1, 'Speech Transcription'
    RECORDING_GENERATION = 2, 'Recording Generation'

class AnalysisTaskSubTypes(models.IntegerChoices):
    DEEPGRAM = 1, 'Deepgram'
    RECORDING_GENERATION_STANDARD = 2, 'Recording Generation Standard'

class AnalysisTask(models.Model):
    bot = models.ForeignKey(
        Bot,
        on_delete=models.CASCADE,
        related_name='analysis_tasks'
    )
    
    analysis_type = models.IntegerField(
        choices=AnalysisTaskTypes.choices,
        null=False
    )
    
    analysis_sub_type = models.IntegerField(
        choices=AnalysisTaskSubTypes.choices,
        null=False
    )
    
    state = models.IntegerField(
        choices=AnalysisTaskStates.choices,
        default=AnalysisTaskStates.NOT_STARTED,
        null=False
    )
    
    sub_state = models.IntegerField(
        choices=AnalysisTaskSubStates.choices,
        null=True,
        blank=True
    )
    
    parameters = models.JSONField(
        null=False,
    )
    
    version = IntegerVersionField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(
                    # For FAILED state, can have sub-state
                    (Q(state=AnalysisTaskStates.FAILED) & 
                     Q(sub_state=AnalysisTaskSubStates.AUTHORIZATION_FAILED)) |
                    
                    # For all other states, sub_state must be null
                    (~Q(state=AnalysisTaskStates.FAILED) & Q(sub_state__isnull=True))
                ),
                name='valid_analysis_state_substate_combinations'
            ),
            models.UniqueConstraint(
                fields=['bot', 'analysis_type'],
                name='unique_analysis_task_per_bot'
            )
        ]

    def __str__(self):
        return f"Analysis Task ({self.get_analysis_type_display()}) - {self.get_state_display()}"

class AnalysisTaskManager:
    @classmethod
    def set_task_in_progress(cls, task: AnalysisTask):
        task.refresh_from_db()

        if task.state == AnalysisTaskStates.IN_PROGRESS:
            return
        if task.state != AnalysisTaskStates.NOT_STARTED:
            raise ValueError(f"Invalid state transition. Task {task.id} is in state {task.get_state_display()}")
        
        task.state = AnalysisTaskStates.IN_PROGRESS
        task.save()

    @classmethod
    def set_task_complete(cls, task: AnalysisTask):
        task.refresh_from_db()

        if task.state == AnalysisTaskStates.COMPLETE:
            return
        if task.state != AnalysisTaskStates.IN_PROGRESS:
            raise ValueError(f"Invalid state transition. Task {task.id} is in state {task.get_state_display()}")
        
        task.state = AnalysisTaskStates.COMPLETE
        task.save()

    @classmethod
    def set_task_failed(cls, task: AnalysisTask, sub_state: int):
        task.refresh_from_db()

        if task.state == AnalysisTaskStates.FAILED:
            return
        if task.state != AnalysisTaskStates.IN_PROGRESS:
            raise ValueError(f"Invalid state transition. Task {task.id} is in state {task.get_state_display()}")
        
        task.state = AnalysisTaskStates.FAILED
        task.sub_state = sub_state
        task.save()

class Credentials(models.Model):
    class CredentialTypes(models.IntegerChoices):
        DEEPGRAM = 1, 'Deepgram'
        ZOOM_OAUTH = 2, 'Zoom OAuth'

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name='credentials'
    )
    credential_type = models.IntegerField(
        choices=CredentialTypes.choices,
        null=False
    )

    _encrypted_data = models.BinaryField(
        null=True,
        editable=False,  # Prevents editing through admin/forms
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['project', 'credential_type'],
                name='unique_project_credentials'
            )
        ]

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
