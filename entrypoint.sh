#!/usr/bin/env bash

# Clean up old PulseAudio state
rm -rf /var/run/pulse /var/lib/pulse /root/.config/pulse

# Start PulseAudio as user
pulseaudio --start --exit-idle-time=-1 -v

# Load a virtual sink (speaker)
pactl load-module module-null-sink sink_name=VirtualSpeaker
pactl set-default-sink VirtualSpeaker