from celery import shared_task
from .models import Bot, BotEvent, BotEventTypes, BotEventSubTypes, BotEventManager, BotStates, Utterance, Recording, RecordingStates, BotMediaRequestMediaTypes, BotMediaRequestStates, BotMediaRequestManager, BotMediaRequest, RecordingTranscriptionStates, RecordingManager, Participant, Credentials
from celery.exceptions import SoftTimeLimitExceeded
from django.utils import timezone
import redis
import json
import os
import signal
from urllib.parse import urlparse, parse_qs
import re
import hashlib
from celery.signals import worker_shutting_down

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

def convert_utterance_audio_blob_to_mp3(utterance):
    from .utils import pcm_to_mp3

    if utterance.audio_format == Utterance.AudioFormat.PCM:
        mp3_data = pcm_to_mp3(utterance.audio_blob)
        utterance.audio_blob = mp3_data
        utterance.audio_format = Utterance.AudioFormat.MP3
        utterance.save()
        utterance.refresh_from_db() # because of the .tobytes() issue

@shared_task(bind=True, soft_time_limit=3600)
def process_utterance(self, utterance_id):
    import json

    from deepgram import (
        DeepgramClient,
        PrerecordedOptions,
        FileSource,
    )

    utterance = Utterance.objects.get(id=utterance_id)
    print(f"Processing utterance {utterance_id}")

    recording = utterance.recording
    RecordingManager.set_recording_transcription_in_progress(recording)

    # if utterance file format is pcm, convert to mp3
    convert_utterance_audio_blob_to_mp3(utterance)

    if utterance.transcription is None:
        payload: FileSource = {
            "buffer": utterance.audio_blob.tobytes(),
        }

        options = PrerecordedOptions(
            model="nova-2",
            smart_format=True,
        )

        deepgram_credentials_record = recording.bot.project.credentials.filter(credential_type=Credentials.CredentialTypes.DEEPGRAM).first()
        if not deepgram_credentials_record:
            raise Exception("Deepgram credentials record not found")

        deepgram_credentials = deepgram_credentials_record.get_credentials()
        if not deepgram_credentials:
            raise Exception("Deepgram credentials not found")

        deepgram = DeepgramClient(deepgram_credentials['api_key'])

        response = deepgram.listen.rest.v("1").transcribe_file(payload, options)
        utterance.transcription = json.loads(response.results.channels[0].alternatives[0].to_json())
        utterance.save()

    # If the recording is in a terminal state and there are no more utterances to transcribe, set the recording's transcription state to complete
    if RecordingManager.is_terminal_state(utterance.recording.state) and Utterance.objects.filter(recording=utterance.recording, transcription__isnull=True).count() == 0:
        RecordingManager.set_recording_transcription_complete(utterance.recording)

@shared_task(bind=True, soft_time_limit=3600)
def run_bot(self, bot_id):
    import gi
    gi.require_version('GLib', '2.0')
    from gi.repository import GLib
    from bots.zoom_bot.zoom_bot import ZoomBot
    from bots.zoom_bot.utterance_processing_queue import UtteranceProcessingQueue
    from bots.zoom_bot.audio_output_manager import AudioOutputManager

    redis_url = os.getenv('REDIS_URL') + ("?ssl_cert_reqs=none" if os.getenv('DISABLE_REDIS_SSL') else "")
    redis_client = redis.from_url(redis_url)
    pubsub = redis_client.pubsub()
    channel = f"bot_{bot_id}"
    pubsub.subscribe(channel)

    zoom_bot = None
    main_loop = None
    
    first_timeout_call = True

    def cleanup_bot():
        normal_quitting_process_worked = False
        import threading
        def terminate_worker():
            import time
            time.sleep(20)
            if normal_quitting_process_worked:
                print("Normal quitting process worked, not force terminating worker")
                return
            print("Terminating worker with hard timeout...")
            os.kill(os.getpid(), signal.SIGKILL)  # Force terminate the worker process
        
        termination_thread = threading.Thread(target=terminate_worker, daemon=True)
        termination_thread.start()

        if zoom_bot:
            print("Leaving meeting...")
            zoom_bot.leave()
            print("Cleaning up zoom bot...")
            zoom_bot.cleanup()
        if main_loop and main_loop.is_running():
            main_loop.quit()
        normal_quitting_process_worked = True
    
    def handle_glib_shutdown():
        print("handle_glib_shutdown called")

        try:
            BotEventManager.create_event(
                bot=bot_in_db,
                event_type=BotEventTypes.FATAL_ERROR,
                event_sub_type=BotEventSubTypes.FATAL_ERROR_PROCESS_TERMINATED
            )
        except Exception as e:
            print(f"Error creating FATAL_ERROR event: {e}")

        cleanup_bot()
        return False

    def take_action_based_on_message_from_zoom_bot(message):
        if message.get('message') == ZoomBot.Messages.MEETING_ENDED:
            print("Received message that meeting ended")
            if utterance_processing_queue:
                print("Flushing utterances...")
                utterance_processing_queue.flush_utterances()

            if bot_in_db.state == BotStates.LEAVING:
                BotEventManager.create_event(
                    bot=bot_in_db,
                    event_type=BotEventTypes.BOT_LEFT_MEETING
                )
            else:
                BotEventManager.create_event(
                    bot=bot_in_db,
                    event_type=BotEventTypes.MEETING_ENDED
                )
            cleanup_bot()
            return

        if message.get('message') == ZoomBot.Messages.LEAVE_MEETING_WAITING_FOR_HOST:
            print("Received message to Leave meeting because received waiting for host status")
            BotEventManager.create_event(
                bot=bot_in_db,
                event_type=BotEventTypes.COULD_NOT_JOIN,
                event_sub_type=BotEventSubTypes.COULD_NOT_JOIN_MEETING_NOT_STARTED_WAITING_FOR_HOST
            )
            cleanup_bot()
            return

        if message.get('message') == ZoomBot.Messages.BOT_PUT_IN_WAITING_ROOM:
            print("Received message to put bot in waiting room")
            BotEventManager.create_event(
                bot=bot_in_db,
                event_type=BotEventTypes.BOT_PUT_IN_WAITING_ROOM
            )
            return

        if message.get('message') == ZoomBot.Messages.BOT_JOINED_MEETING:
            print("Received message that bot joined meeting")
            BotEventManager.create_event(
                bot=bot_in_db,
                event_type=BotEventTypes.BOT_JOINED_MEETING
            )
            return

        if message.get('message') == ZoomBot.Messages.BOT_RECORDING_PERMISSION_GRANTED:
            print("Received message that bot recording permission granted")
            BotEventManager.create_event(
                bot=bot_in_db,
                event_type=BotEventTypes.BOT_RECORDING_PERMISSION_GRANTED
            )
            return

        if message.get('message') == ZoomBot.Messages.NEW_UTTERANCE:
            print(f"Received message that new utterance was detected")

            # Create participant record if it doesn't exist
            participant, _ = Participant.objects.get_or_create(
                bot=bot_in_db,
                uuid=message['participant_uuid'],
                defaults={
                    'user_uuid': message['participant_user_uuid'],
                    'full_name': message['participant_full_name'],
                }
            )

            # Create new utterance record
            recordings_in_progress = Recording.objects.filter(bot=bot_in_db, state=RecordingStates.IN_PROGRESS)
            if recordings_in_progress.count() == 0:
                raise Exception("No recording in progress found")
            if recordings_in_progress.count() > 1:
                raise Exception(f"Expected at most one recording in progress for bot {bot_in_db.object_id}, but found {recordings_in_progress.count()}")
            recording_in_progress = recordings_in_progress.first()
            utterance = Utterance.objects.create(
                recording=recording_in_progress,
                participant=participant,
                audio_blob=message['audio_data'],
                audio_format=Utterance.AudioFormat.PCM,
                timestamp_ms=message['timestamp_ms'],
                duration_ms=len(message['audio_data']) / 64,
            )

            # Process the utterance immediately
            process_utterance.delay(utterance.id)
            return
        
    def currently_playing_audio_media_request_finished(audio_media_request):
        print("currently_playing_audio_media_request_finished called")
        BotMediaRequestManager.set_media_request_finished(audio_media_request)
        take_action_based_on_audio_media_requests_in_db()

    def take_action_based_on_audio_media_requests_in_db():
        media_type = BotMediaRequestMediaTypes.AUDIO
        oldest_enqueued_media_request = bot_in_db.media_requests.filter(state=BotMediaRequestStates.ENQUEUED, media_type=media_type).order_by('created_at').first()
        if not oldest_enqueued_media_request:
            return
        currently_playing_media_request = bot_in_db.media_requests.filter(state=BotMediaRequestStates.PLAYING, media_type=media_type).first()
        if currently_playing_media_request:
            print(f"Currently playing media request {currently_playing_media_request.id} so cannot play another media request")
            return
        
        from .utils import mp3_to_pcm
        try:
            BotMediaRequestManager.set_media_request_playing(oldest_enqueued_media_request)
            zoom_bot.send_raw_audio(mp3_to_pcm(oldest_enqueued_media_request.media_blob.blob, sample_rate=8000))
            audio_output_manager.start_playing_audio_media_request(oldest_enqueued_media_request)
        except Exception as e:
            print(f"Error sending raw audio: {e}")
            BotMediaRequestManager.set_media_request_failed_to_play(oldest_enqueued_media_request)

    def take_action_based_on_image_media_requests_in_db():
        from .utils import png_to_yuv420_frame

        media_type = BotMediaRequestMediaTypes.IMAGE
        
        # Get all enqueued image media requests for this bot, ordered by creation time
        enqueued_requests = bot_in_db.media_requests.filter(
            state=BotMediaRequestStates.ENQUEUED,
            media_type=media_type
        ).order_by('created_at')

        if not enqueued_requests.exists():
            return

        # Get the most recently created request
        most_recent_request = enqueued_requests.last()
        
        # Mark the most recent request as FINISHED
        try:
            BotMediaRequestManager.set_media_request_playing(most_recent_request)
            zoom_bot.send_raw_image(png_to_yuv420_frame(most_recent_request.media_blob.blob))
            BotMediaRequestManager.set_media_request_finished(most_recent_request)
        except Exception as e:
            print(f"Error sending raw image: {e}")
            BotMediaRequestManager.set_media_request_failed_to_play(most_recent_request)
        
        # Mark all other enqueued requests as DROPPED
        for request in enqueued_requests.exclude(id=most_recent_request.id):
            BotMediaRequestManager.set_media_request_dropped(request)

    def take_action_based_on_media_requests_in_db():
        take_action_based_on_audio_media_requests_in_db()
        take_action_based_on_image_media_requests_in_db()
                
    def take_action_based_on_bot_in_db():
        if bot_in_db.state == BotStates.JOINING:
            print("take_action_based_on_bot_in_db - JOINING")
            BotEventManager.set_requested_bot_action_taken_at(bot_in_db)
            zoom_bot.init()
        if bot_in_db.state == BotStates.LEAVING:
            print("take_action_based_on_bot_in_db - LEAVING")
            BotEventManager.set_requested_bot_action_taken_at(bot_in_db)
            zoom_bot.leave()

    def get_participant(participant_id):
        return zoom_bot.get_participant(participant_id)
    
    def get_recording_filename():
        recording = Recording.objects.get(bot_id=bot_id, is_default_recording=True)
        return f"{hashlib.md5(recording.object_id.encode()).hexdigest()}.mp4"
    
    def recording_file_saved(s3_storage_key):
        recording = Recording.objects.get(bot_id=bot_id, is_default_recording=True)
        recording.file = s3_storage_key
        recording.first_buffer_timestamp_ms = zoom_bot.get_first_buffer_timestamp_ms()
        recording.save()

    def handle_redis_message(message):
        if message and message['type'] == 'message':
            data = json.loads(message['data'].decode('utf-8'))
            command = data.get('command')
            
            if command == 'sync':
                print(f"Syncing bot {bot_in_db.object_id}")
                bot_in_db.refresh_from_db()
                take_action_based_on_bot_in_db()
            elif command == 'sync_media_requests':
                print(f"Syncing media requests for bot {bot_in_db.object_id}")
                bot_in_db.refresh_from_db()
                take_action_based_on_media_requests_in_db()
            else:
                print(f"Unknown command: {command}")

    def on_timeout():
        try:
            nonlocal first_timeout_call
            
            if first_timeout_call:
                print("First timeout call - taking initial action")
                bot_in_db.refresh_from_db()
                take_action_based_on_bot_in_db()
                first_timeout_call = False

            # Process audio chunks
            utterance_processing_queue.process_chunks()

            # Process audio output
            audio_output_manager.monitor_currently_playing_audio_media_request()
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


        utterance_processing_queue = UtteranceProcessingQueue(save_utterance_callback=take_action_based_on_message_from_zoom_bot, get_participant_callback=get_participant)
        audio_output_manager = AudioOutputManager(currently_playing_audio_media_request_finished_callback=currently_playing_audio_media_request_finished)

        zoom_bot = ZoomBot(
            display_name=bot_in_db.name,
            send_message_callback=take_action_based_on_message_from_zoom_bot,
            add_audio_chunk_callback=utterance_processing_queue.add_chunk,
            get_recording_filename_callback=get_recording_filename,
            saved_recording_file_callback=recording_file_saved,
            zoom_client_id=zoom_oauth_credentials['client_id'],
            zoom_client_secret=zoom_oauth_credentials['client_secret'],
            meeting_id=meeting_id,
            meeting_password=meeting_password,
        )
        
        # Create GLib main loop
        main_loop = GLib.MainLoop()
        
        # Set up Redis listener in a separate thread
        import threading
        def redis_listener():
            while True:
                try:
                    message = pubsub.get_message(timeout=1.0)
                    if message:
                        # Schedule Redis message handling in the main GLib loop
                        GLib.idle_add(lambda: handle_redis_message(message))
                except Exception as e:
                    print(f"Error in Redis listener: {e}")
                    break

        redis_thread = threading.Thread(target=redis_listener, daemon=True)
        redis_thread.start()

        # Add timeout just for audio processing
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

def kill_child_processes():
    # Get the process group ID (PGID) of the current process
    pgid = os.getpgid(os.getpid())
    
    try:
        # Send SIGTERM to all processes in the process group
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        pass  # Process group may no longer exist

@worker_shutting_down.connect
def shutting_down_handler(sig, how, exitcode, **kwargs):
    # Just adding this code so we can see how to shut down all the tasks
    # when the main process is terminated.
    # It's likely overkill.
    print("Celery worker shutting down, sending SIGTERM to all child processes")
    kill_child_processes()