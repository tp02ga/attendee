from celery import shared_task, current_app
from celery.signals import celeryd_init, worker_shutting_down, worker_process_init, worker_process_shutdown
from .models import Bot, BotEvent, BotEventManager, BotStates, Utterance, AnalysisTask, AnalysisTaskTypes, AnalysisTaskStates, AnalysisTaskSubTypes, AnalysisTaskManager, Participant, Credentials
from celery.exceptions import SoftTimeLimitExceeded
from django.utils import timezone
import redis
import json
import os
import signal
import random
from asgiref.sync import async_to_sync
from urllib.parse import urlparse, parse_qs
import re

def parse_join_url(join_url):
    # Parse the URL into components
    parsed = urlparse(join_url)
    
    # Extract meeting ID using regex to match only numeric characters
    meeting_id_match = re.search(r'(\d+)', parsed.path)
    meeting_id = meeting_id_match.group(1) if meeting_id_match else None
    
    # Extract password from query parameters
    query_params = parse_qs(parsed.query)
    password = query_params.get('pwd', [None])[0]
    
    return (meeting_id, password)

@shared_task(bind=True, soft_time_limit=3600)
def process_utterance(self, utterance_id):
    from .utils import pcm_to_mp3
    import json

    from deepgram import (
        DeepgramClient,
        PrerecordedOptions,
        FileSource,
    )

    utterance = Utterance.objects.get(id=utterance_id)
    print(f"Processing utterance {utterance_id}")

    analysis_task = AnalysisTask.objects.get(bot=utterance.bot, analysis_type=AnalysisTaskTypes.SPEECH_TRANSCRIPTION)
    AnalysisTaskManager.set_task_in_progress(analysis_task)

    # if utterance file format is pcm, convert to mp3
    if utterance.audio_format == Utterance.AudioFormat.PCM:
        mp3_data = pcm_to_mp3(utterance.audio_blob)
        utterance.audio_blob = mp3_data
        utterance.audio_format = Utterance.AudioFormat.MP3
        utterance.save()
        utterance.refresh_from_db()

    if utterance.transcription is None:
        payload: FileSource = {
            "buffer": utterance.audio_blob.tobytes(),
        }

        options = PrerecordedOptions(
            model="nova-2",
            smart_format=True,
        )

        deepgram_credentials_record = analysis_task.bot.project.credentials.filter(credential_type=Credentials.CredentialTypes.DEEPGRAM).first()
        if not deepgram_credentials_record:
            raise Exception("Deepgram credentials record not found")

        deepgram_credentials = deepgram_credentials_record.get_credentials()
        if not deepgram_credentials:
            raise Exception("Deepgram credentials not found")

        deepgram = DeepgramClient(deepgram_credentials['api_key'])

        response = deepgram.listen.rest.v("1").transcribe_file(payload, options)
        utterance.transcription = json.loads(response.results.channels[0].alternatives[0].to_json())
        utterance.save()

    if BotEventManager.is_terminal_state(utterance.bot.state) and Utterance.objects.filter(bot=utterance.bot, transcription__isnull=True).count() == 0:
        AnalysisTaskManager.set_task_complete(analysis_task)

@shared_task(bind=True, soft_time_limit=3600)
def run_bot(self, bot_id):
    import gi
    gi.require_version('GLib', '2.0')
    from gi.repository import GLib
    from bots.zoom_bot.zoom_bot import ZoomBot
    from bots.zoom_bot.audio_processing_queue import AudioProcessingQueue

    redis_url = os.getenv('REDIS_URL') + ("?ssl_cert_reqs=none" if os.getenv('DISABLE_REDIS_SSL') else "")
    redis_client = redis.from_url(redis_url)
    pubsub = redis_client.pubsub()
    channel = f"bot_{bot_id}"
    pubsub.subscribe(channel)

    zoom_bot = None
    main_loop = None
    
    first_timeout_call = True

    def cleanup_bot():
        if zoom_bot:
            print("Leaving meeting...")
            zoom_bot.leave()
            print("Cleaning up zoom bot...")
            zoom_bot.cleanup()
        if main_loop and main_loop.is_running():
            main_loop.quit()
    
    def handle_glib_shutdown():
        print("handle_glib_shutdown called")

        try:
            BotEventManager.create_event(
                bot=bot_in_db,
                event_type=BotEvent.EventTypes.PROCESS_TERMINATED
            )
        except Exception as e:
            print(f"Error creating PROCESS_TERMINATED event: {e}")

        cleanup_bot()
        return False

    def take_action_based_on_message_from_zoom_bot(message):
        if message.get('message') == ZoomBot.Messages.MEETING_ENDED:
            print("Received message that meeting ended")
            if bot_in_db.state == BotStates.LEAVING_REQ_STARTED_BY_BOT:
                BotEventManager.create_event(
                    bot=bot_in_db,
                    event_type=BotEvent.EventTypes.BOT_LEFT_MEETING
                )
            else:
                BotEventManager.create_event(
                    bot=bot_in_db,
                    event_type=BotEvent.EventTypes.MEETING_ENDED
                )
            cleanup_bot()
            return

        if message.get('message') == ZoomBot.Messages.LEAVE_MEETING_WAITING_FOR_HOST:
            print("Received message to Leave meeting because received waiting for host status")
            BotEventManager.create_event(
                bot=bot_in_db,
                event_type=BotEvent.EventTypes.WAITING_FOR_HOST_TO_START_MEETING_MSG_RECEIVED
            )
            cleanup_bot()
            return

        if message.get('message') == ZoomBot.Messages.BOT_PUT_IN_WAITING_ROOM:
            print("Received message to put bot in waiting room")
            BotEventManager.create_event(
                bot=bot_in_db,
                event_type=BotEvent.EventTypes.BOT_PUT_IN_WAITING_ROOM
            )
            return

        if message.get('message') == ZoomBot.Messages.BOT_JOINED_MEETING:
            print("Received message that bot joined meeting")
            BotEventManager.create_event(
                bot=bot_in_db,
                event_type=BotEvent.EventTypes.BOT_JOINED_MEETING
            )
            return

        if message.get('message') == ZoomBot.Messages.BOT_RECORDING_PERMISSION_GRANTED:
            print("Received message that bot recording permission granted")
            BotEventManager.create_event(
                bot=bot_in_db,
                event_type=BotEvent.EventTypes.BOT_RECORDING_PERMISSION_GRANTED
            )
            return

        if message.get('message') == ZoomBot.Messages.NEW_UTTERANCE:
            print(f"Received message that new utterance was detected")

            # Create participant record if it doesn't exist
            participant, _ = async_to_sync(Participant.objects.aget_or_create)(
                bot=bot_in_db,
                uuid=message['participant_uuid'],
                defaults={
                    'user_uuid': message['participant_user_uuid'],
                    'full_name': message['participant_full_name'],
                }
            )

            # Create new utterance record
            utterance = async_to_sync(Utterance.objects.acreate)(
                bot=bot_in_db,
                participant=participant,
                audio_blob=message['audio_data'],
                audio_format=Utterance.AudioFormat.PCM,
                timeline_ms=message['timeline_ms'],
                duration_ms=len(message['audio_data']) / 64,
            )

            # Process the utterance immediately
            process_utterance.delay(utterance.id)
            return

    def take_action_based_on_bot_in_db():
        if bot_in_db.state == BotStates.JOINING_REQ_NOT_STARTED_BY_BOT:
            print("take_action_based_on_bot_in_db - JOINING_REQ_NOT_STARTED_BY_BOT")
            BotEventManager.create_event(
                bot=bot_in_db,
                event_type=BotEvent.EventTypes.JOIN_REQUESTED_BY_BOT
            )
            zoom_bot.init()
        if bot_in_db.state == BotStates.LEAVING_REQ_NOT_STARTED_BY_BOT:
            print("take_action_based_on_bot_in_db - LEAVING_REQ_NOT_STARTED_BY_BOT")
            BotEventManager.create_event(
                bot=bot_in_db,
                event_type=BotEvent.EventTypes.LEAVE_REQUESTED_BY_BOT
            )
            zoom_bot.leave()

    def get_participant(participant_id):
        return zoom_bot.get_participant(participant_id)

    def on_timeout():
        try:
            nonlocal first_timeout_call
            
            # Call take_action_based_on_bot_in_db on first execution
            if first_timeout_call:
                print("First timeout call - taking initial action")
                bot_in_db.refresh_from_db()
                take_action_based_on_bot_in_db()
                first_timeout_call = False

            # Process audio chunks (not sure if this belongs in the zoom bot or in here)
            audio_processing_queue.process_chunks()

            # Original timeout logic
            message = pubsub.get_message()
            if message and message['type'] == 'message':
                data = json.loads(message['data'].decode('utf-8'))
                command = data.get('command')
                
                if command == 'sync':
                    print(f"Syncing bot {bot_in_db.object_id}")
                    bot_in_db.refresh_from_db()
                    take_action_based_on_bot_in_db()
                else:
                    print(f"Unknown command: {command}")

            return True
            
        except Exception as e:
            print(f"Error in timeout callback: {e}")
            cleanup_bot()
            return False

    try:
        bot_in_db = Bot.objects.get(id=bot_id)
        print(f"Bot {bot_in_db.object_id} worker started for meeting {bot_in_db.meeting_url}")
        
        # Initialize the bot
        zoom_oauth_credentials_record = bot_in_db.project.credentials.filter(credential_type=Credentials.CredentialTypes.ZOOM_OAUTH).first()
        if not zoom_oauth_credentials_record:
            raise Exception("Zoom OAuth credentials not found")

        zoom_oauth_credentials = zoom_oauth_credentials_record.get_credentials()
        if not zoom_oauth_credentials:
            raise Exception("Zoom OAuth credentials data not found")
        
        meeting_id, meeting_password = parse_join_url(bot_in_db.meeting_url)


        audio_processing_queue = AudioProcessingQueue(save_utterance_callback=take_action_based_on_message_from_zoom_bot, get_participant_callback=get_participant)

        zoom_bot = ZoomBot(
            send_message_callback=take_action_based_on_message_from_zoom_bot,
            add_audio_chunk_callback=audio_processing_queue.add_chunk,
            zoom_client_id=zoom_oauth_credentials['client_id'],
            zoom_client_secret=zoom_oauth_credentials['client_secret'],
            meeting_id=meeting_id,
            meeting_password=meeting_password,
        )
        
        # Create GLib main loop
        main_loop = GLib.MainLoop()
        
        # Add timeout function to check Redis messages every 100ms
        GLib.timeout_add(100, on_timeout)
        
        # Add signal handlers so that when we get a SIGTERM or SIGINT, we can clean up the bot
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, handle_glib_shutdown)
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, handle_glib_shutdown)
        
        # Run the main loop
        main_loop.run()
        
    except (SoftTimeLimitExceeded, KeyboardInterrupt):
        cleanup_bot()
        if bot_in_db:
            bot_in_db.left_at = timezone.now()
            bot_in_db.save()
    except Exception as e:
        print(f"Error in bot {bot_id}: {str(e)}")
        cleanup_bot()
    finally:
        # Clean up Redis subscription
        pubsub.unsubscribe(channel)
        pubsub.close()