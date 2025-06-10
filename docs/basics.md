# Basics of Bots

## What is a bot?
In the Attendee platform, a bot is an automated participant that can join virtual meetings across different platforms (Zoom, Google Meet, Microsoft Teams) to perform various tasks such as recording and transcription.

## Bot Capabilities

1. Recording: Bots can record audio and video from meetings
2. Transcription: Bots can transcribe meeting conversations in real-time or after the meeting ends
3. Speech: Bots can speak arbitrary audio into the meeting
4. Avatars: Bots can display arbitrary images as in their virtual webcam
5. Chat: Bots can record and send chat messages

## Bot States
Bots go through these lifecycle states:

1. Ready: Initial state when bot is created
2. Joining: Bot is attempting to join meeting
3. Joined - Not Recording: Bot has joined but isn't recording
4. Joined - Recording: Bot has joined and is recording
5. Leaving: Bot is leaving the meeting
6. Post Processing: Bot is processing recordings
7. Fatal Error: Bot encountered an unrecoverable error
8. Waiting Room: Bot is in meeting's waiting room
9. Ended: Bot has completed all tasks and recordings and transcripts are available for download

## Transcription Features

1. Realtime transcription
2. Multiple language support
3. Automatic language detection
4. Speaker identification / Diarization
5. Precise timestamps for each utterance
6. Transcripts from Platform closed captions

## Configuration Options
Bots can be configured with:

1. Transcription Settings
   - Language selection
   - Automatic language detection
   - Provider-specific options

2. Recording Settings
   - Recording type (Audio and Video / Audio Only)
   - Recording view (Speaker View / Gallery View)

3. Automatic leave settings
   - How long should the bot wait to be let into the meeting before giving up?
   - How long it should be silent before the bot leaves
   - How long should the bot be the only one in the meeting before it leaves
   - How long the meeting can last before the bot leaves

4. Webhooks
   - Webhook events for bot state changes
   - Webhook events for transcript updates

## Platform Support
Currently supported platforms:
1. Zoom
2. Google Meet
3. Microsoft Teams