from rest_framework import serializers
from .models import BotSession, BotSessionStates, AnalysisTaskTypes, AnalysisTaskStates, BotSessionSubStates

class CreateSessionSerializer(serializers.Serializer):
    meeting_url = serializers.CharField()

class SessionSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source='object_id')
    state = serializers.SerializerMethodField()
    sub_state = serializers.SerializerMethodField()
    transcription_state = serializers.SerializerMethodField()

    def get_state(self, obj):
        return BotSessionStates.state_to_api_code(obj.state)

    def get_sub_state(self, obj):
        if not obj.sub_state:
            return None
        return BotSessionSubStates.state_to_api_code(obj.sub_state)

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