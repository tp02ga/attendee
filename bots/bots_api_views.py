from django.shortcuts import render, get_object_or_404
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import Bot, BotEvent, BotEventManager, Recording, RecordingTypes, TranscriptionTypes, TranscriptionProviders, Utterance
from .serializers import CreateBotSerializer, BotSerializer, TranscriptUtteranceSerializer, RecordingSerializer
from .authentication import ApiKeyAuthentication
from .tasks import run_bot
import redis
import json
import os
from drf_spectacular.utils import extend_schema, OpenApiResponse, OpenApiParameter

TokenHeaderParameter = [
    OpenApiParameter(
        name="Authorization",
        type=str,
        location=OpenApiParameter.HEADER,
        description="API key for authentication",
        required=True,
        default="Token YOUR_API_KEY_HERE"
    ),
    OpenApiParameter(
        name="Content-Type",
        type=str,
        location=OpenApiParameter.HEADER,
        description="Should always be application/json",
        required=True,
        default="application/json"
    )
]

@extend_schema(exclude=True)
class NotFoundView(APIView):    
    def get(self, request, *args, **kwargs):
        return self.handle_request(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        return self.handle_request(request, *args, **kwargs)

    def put(self, request, *args, **kwargs):
        return self.handle_request(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        return self.handle_request(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        return self.handle_request(request, *args, **kwargs)

    def handle_request(self, request, *args, **kwargs):
        return Response(
            {'error': 'Not found'},
            status=status.HTTP_404_NOT_FOUND
        )

class BotCreateView(APIView):
    authentication_classes = [ApiKeyAuthentication]

    @extend_schema(
        operation_id='Create Bot',
        summary='Create a new bot',
        description='After being created,the bot will attempt to join the specified meeting.',
        request=CreateBotSerializer,
        responses={
            201: OpenApiResponse(response=BotSerializer, description='Bot created successfully'),
            400: OpenApiResponse(description='Invalid input')
        },
        parameters=TokenHeaderParameter, 
        tags=['Bots'],
    )
    def post(self, request):
        serializer = CreateBotSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Access the bot through the api key
        project = request.auth.project
        
        meeting_url = serializer.validated_data['meeting_url']
        bot_name = serializer.validated_data['bot_name']
        bot = Bot.objects.create(
            project=project,
            meeting_url=meeting_url,
            name=bot_name
        )

        Recording.objects.create(
            bot=bot,
            recording_type=RecordingTypes.AUDIO_AND_VIDEO,
            transcription_type=TranscriptionTypes.NON_REALTIME,
            transcription_provider=TranscriptionProviders.DEEPGRAM,
            is_default_recording=True
        )
        
        # Try to transition the state from READY to JOINING_REQ_NOT_STARTED_BY_BOT
        BotEventManager.create_event(bot, BotEvent.EventTypes.JOIN_REQUESTED_BY_API)

        # Launch the Celery task after successful creation
        run_bot.delay(bot.id)
        
        return Response(
            BotSerializer(bot).data,
            status=status.HTTP_201_CREATED
        )
        
class BotLeaveView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    
    def send_sync_command(self, bot):
        redis_url = os.getenv('REDIS_URL') + ("?ssl_cert_reqs=none" if os.getenv('DISABLE_REDIS_SSL') else "")
        redis_client = redis.from_url(redis_url)
        channel = f"bot_{bot.id}"
        message = {
            'command': 'sync'
        }
        redis_client.publish(channel, json.dumps(message))
    
    @extend_schema(
        operation_id='Leave Meeting',
        summary='Leave a meeting',
        description='Causes the bot to leave the meeting.',
        responses={
            200: OpenApiResponse(response=BotSerializer, description='Successfully requested to leave meeting'),
            404: OpenApiResponse(description='Bot not found')
        },
        parameters=TokenHeaderParameter,
        tags=['Bots'],
    )
    def post(self, request, object_id):
        try:
            bot = Bot.objects.get(object_id=object_id, project=request.auth.project)
            
            BotEventManager.create_event(bot, BotEvent.EventTypes.LEAVE_REQUESTED_BY_API)

            self.send_sync_command(bot)
            
            return Response(
                BotSerializer(bot).data,
                status=status.HTTP_200_OK
            )
            
        except Bot.DoesNotExist:
            return Response(
                {'error': 'Bot not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )

class RecordingView(APIView):
    authentication_classes = [ApiKeyAuthentication]

    @extend_schema(
        operation_id='Get Bot Recording',
        summary='Get the recording for a bot',
        description='Returns a short-lived S3 URL for the recording of the bot.',
        responses={
            200: OpenApiResponse(response=RecordingSerializer, description='Signed URL for the recording')
        },
        parameters=TokenHeaderParameter,
        tags=['Bots'],
    )
    def get(self, request, object_id):
        try:
            bot = Bot.objects.get(object_id=object_id, project=request.auth.project)

            recording = Recording.objects.filter(bot=bot, is_default_recording=True).first()
            if not recording:
                return Response(
                    {'error': 'No recording found for bot'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            recording_file = recording.file
            if not recording_file:
                return Response(
                    {'error': 'No recording file found for bot'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            return Response(RecordingSerializer(recording).data)
            
        except Bot.DoesNotExist:
            return Response(
                {'error': 'Bot not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )

class TranscriptView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    
    @extend_schema(
        operation_id='Get Bot Transcript',
        summary='Get the transcript for a bot',
        description='If the meeting is still in progress, this returns the transcript so far.',
        responses={
            200: OpenApiResponse(response=TranscriptUtteranceSerializer(many=True), description='List of transcribed utterances'),
            404: OpenApiResponse(description='Bot not found')
        },
        parameters=TokenHeaderParameter,
        tags=['Bots'],
    )
    def get(self, request, object_id):
        try:
            bot = Bot.objects.get(object_id=object_id, project=request.auth.project)
            
            recording = Recording.objects.filter(bot=bot, is_default_recording=True).first()
            if not recording:
                return Response(
                    {'error': 'No recording found for bot'}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Get all utterances with transcriptions, sorted by timeline
            utterances = Utterance.objects.select_related('participant').filter(
                recording=recording,
                transcription__isnull=False
            ).order_by('timestamp_ms')
            
            # Format the response, skipping empty transcriptions
            transcript_data = [
                {
                    'speaker_name': utterance.participant.full_name,
                    'speaker_uuid': utterance.participant.uuid,
                    'speaker_user_uuid': utterance.participant.user_uuid,
                    'timestamp_ms': utterance.timestamp_ms,
                    'duration_ms': utterance.duration_ms,
                    'transcription': utterance.transcription['transcript']
                }
                for utterance in utterances     
                if utterance.transcription.get('words', [])
            ]
            
            serializer = TranscriptUtteranceSerializer(transcript_data, many=True)
            return Response(serializer.data)
            
        except Bot.DoesNotExist:
            return Response(
                {'error': 'Bot not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )

class BotDetailView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    
    @extend_schema(
        operation_id='Get Bot',
        summary='Get the details for a bot',
        responses={
            200: OpenApiResponse(response=BotSerializer, description='Bot details'),
            404: OpenApiResponse(description='Bot not found')
        },
        parameters=TokenHeaderParameter,
        tags=['Bots'],
    )        
    def get(self, request, object_id):
        try:
            bot = Bot.objects.get(object_id=object_id, project=request.auth.project)
            return Response(BotSerializer(bot).data)
            
        except Bot.DoesNotExist:
            return Response(
                {'error': 'Bot not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
