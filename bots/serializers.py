from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer, OpenApiExample
from .models import Bot, BotEventSubTypes, BotStates, Recording, RecordingStates, RecordingTranscriptionStates

@extend_schema_serializer(
    examples=[
        OpenApiExample(
            'Valid meeting URL',
            value={'meeting_url': 'https://zoom.us/j/123?pwd=456'},
            description='Example of a valid Zoom meeting URL'
        )
    ]
)
class CreateBotSerializer(serializers.Serializer):
    meeting_url = serializers.CharField(
        help_text="The URL of the meeting to join, e.g. https://zoom.us/j/123?pwd=456"
    )
    bot_name = serializers.CharField(
        help_text="The name of the bot to create, e.g. 'My Bot'"
    )

@extend_schema_serializer(
    examples=[
        OpenApiExample(
            'Meeting URL',
            value={'id': 'bot_weIAju4OXNZkDTpZ', 'meeting_url': 'https://zoom.us/j/123?pwd=456', 'state': 'joining', 'sub_state': None, 'transcription_state': 'not_started', 'recording_state': 'not_started'},
        )
    ]
)
class BotSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source='object_id')
    state = serializers.SerializerMethodField()
    sub_state = serializers.SerializerMethodField()
    transcription_state = serializers.SerializerMethodField()
    recording_state = serializers.SerializerMethodField()

    @extend_schema_field({
        'type': 'string',
        'enum': [BotStates.state_to_api_code(state.value) for state in BotStates]
    })
    def get_state(self, obj):
        return BotStates.state_to_api_code(obj.state)

    @extend_schema_field({
        'type': 'string',
        'enum': [BotEventSubTypes.state_to_api_code(state.value) for state in BotEventSubTypes],
        'nullable': True
    })
    def get_sub_state(self, obj):
        last_bot_event = obj.last_bot_event()
        if not last_bot_event:
            return None
        if not last_bot_event.event_sub_type:
            return None
        return BotEventSubTypes.state_to_api_code(last_bot_event.event_sub_type)

    @extend_schema_field({
        'type': 'string',
        'enum': [RecordingTranscriptionStates.state_to_api_code(state.value) for state in RecordingTranscriptionStates],
    })
    def get_transcription_state(self, obj):
        default_recording = Recording.objects.filter(bot=obj, is_default_recording=True).first()
        if not default_recording:
            return None
            
        return RecordingTranscriptionStates.state_to_api_code(default_recording.transcription_state)

    @extend_schema_field({
        'type': 'string',
        'enum': [RecordingStates.state_to_api_code(state.value) for state in RecordingStates],
    })
    def get_recording_state(self, obj):
        default_recording = Recording.objects.filter(bot=obj, is_default_recording=True).first()
        if not default_recording:
            return None
            
        return RecordingStates.state_to_api_code(default_recording.state)

    class Meta:
        model = Bot
        fields = ['id', 'meeting_url', 'state', 'sub_state', 'transcription_state', 'recording_state']
        read_only_fields = fields

class TranscriptUtteranceSerializer(serializers.Serializer):
    speaker_name = serializers.CharField()
    speaker_uuid = serializers.CharField()
    speaker_user_uuid = serializers.CharField(allow_null=True)
    timestamp_ms = serializers.IntegerField()
    duration_ms = serializers.IntegerField()
    transcription = serializers.JSONField()

@extend_schema_serializer(
    examples=[
        OpenApiExample(
            'Recording Upload',
            value={'url': 'https://attendee-short-term-storage-production.s3.amazonaws.com/e4da3b7fbbce2345d7772b0674a318d5.mp4?...', 'start_timestamp_ms': 1733114771000},
        )
    ]
)
class RecordingSerializer(serializers.ModelSerializer):
    start_timestamp_ms = serializers.IntegerField(source='first_buffer_timestamp_ms')

    class Meta:
        model = Recording
        fields = ['url', 'start_timestamp_ms']