from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from .models import BotSession, BotSessionStates, AnalysisTaskTypes, AnalysisTaskStates, BotSessionSubStates

@extend_schema_serializer(
    examples=[
        OpenApiExample(
            'Valid meeting URL',
            value={'meeting_url': 'https://us05web.zoom.us/j/xxx?pwd=xxxx'},
            description='Example of a valid Zoom meeting URL'
        )
    ]
)
class CreateSessionSerializer(serializers.Serializer):
    meeting_url = serializers.CharField(
        help_text="The URL of the meeting to join"
    )

class SessionSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source='object_id')
    state = serializers.SerializerMethodField()
    sub_state = serializers.SerializerMethodField()
    transcription_state = serializers.SerializerMethodField()

    @extend_schema_field({
        'type': 'string',
        'enum': [BotSessionStates.state_to_api_code(state.value) for state in BotSessionStates]
    })
    def get_state(self, obj):
        return BotSessionStates.state_to_api_code(obj.state)

    @extend_schema_field({
        'type': 'string',
        'enum': [BotSessionSubStates.state_to_api_code(state.value) for state in BotSessionSubStates],
        'nullable': True
    })
    def get_sub_state(self, obj):
        if not obj.sub_state:
            return None
        return BotSessionSubStates.state_to_api_code(obj.sub_state)

    @extend_schema_field({
        'type': 'string',
        'enum': [AnalysisTaskStates.state_to_api_code(state.value) for state in AnalysisTaskStates],
    })
    def get_transcription_state(self, obj):
        analysis_task = obj.analysis_tasks.filter(
            analysis_type=AnalysisTaskTypes.SPEECH_TRANSCRIPTION
        ).first()
        
        if not analysis_task:
            return None
            
        return AnalysisTaskStates.state_to_api_code(analysis_task.state)

    class Meta:
        model = BotSession
        fields = ['id', 'meeting_url', 'state', 'sub_state', 'transcription_state']
        read_only_fields = fields

class TranscriptUtteranceSerializer(serializers.Serializer):
    speaker_name = serializers.CharField()
    speaker_uuid = serializers.CharField()
    speaker_user_uuid = serializers.CharField(allow_null=True)
    timestamp_ms = serializers.IntegerField()
    duration_ms = serializers.IntegerField()
    transcription = serializers.CharField()