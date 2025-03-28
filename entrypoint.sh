#!/bin/bash

# --- Configuration ---
# Define the name and description for the virtual speaker
VIRTUAL_SINK_NAME="VirtualSpeaker"
VIRTUAL_SINK_DESCRIPTION="My Virtual Speaker Output"

# --- Script Start ---
echo "Cleaning up previous PulseAudio state..."
# cleanup to be "stateless" on startup, otherwise pulseaudio daemon can't start
rm -rf /var/run/pulse /var/lib/pulse /root/.config/pulse

echo "Starting PulseAudio system-wide daemon..."
# start pulseaudio as system wide daemon; for debugging it helps to start in non-daemon mode
# Using --start ensures the command waits until the daemon is ready, potentially more robust than -D
pulseaudio --start --verbose --exit-idle-time=-1 --system --disallow-exit

# Brief pause to ensure the daemon is fully initialized (optional, but can help)
sleep 2

echo "Creating virtual audio sink (speaker): ${VIRTUAL_SINK_NAME}"
# Load the null sink module to create a virtual output device (speaker)
# It effectively discards any audio sent to it, but applications can select it as output.
pactl load-module module-null-sink \
    sink_name=${VIRTUAL_SINK_NAME} \
    sink_properties=device.description="${VIRTUAL_SINK_DESCRIPTION}"

# Check if module loaded successfully (optional but good practice)
if ! pactl list sinks short | grep -q "${VIRTUAL_SINK_NAME}"; then
    echo "Error: Failed to create virtual sink ${VIRTUAL_SINK_NAME}." >&2
    # Consider exiting or other error handling here if critical
fi

echo "Allowing PulseAudio access via TCP (localhost only)..."
# Allow pulse audio to be accessed via TCP (from localhost only), to allow other users/processes to access the virtual devices
# Using pactl load-module is generally preferred over pacmd nowadays
pactl load-module module-native-protocol-tcp auth-ip-acl=127.0.0.1

# Configure client connection settings (if needed for specific users/processes)
# NOTE: Setting client.conf in /home/.pulse might be specific to your setup.
# If this script runs as root and you need root processes to use TCP,
# configure /root/.config/pulse/client.conf instead or in addition.
echo "Configuring default client connection (if needed)..."
# https://manpages.ubuntu.com/manpages/trusty/en/man5/pulse-client.conf.5.html
mkdir -p /home/.pulse
echo "default-server = 127.0.0.1" > /home/.pulse/client.conf
# Optionally, configure for root user as well if running script as root
mkdir -p /root/.config/pulse
echo "default-server = 127.0.0.1" > /root/.config/pulse/client.conf

echo "Setting default sink (speaker): ${VIRTUAL_SINK_NAME}"
# Set the newly created virtual sink as the default output device
pactl set-default-sink ${VIRTUAL_SINK_NAME}

echo "--- Setup Complete ---"
echo "Virtual Speaker '${VIRTUAL_SINK_NAME}' created and set as default output."
echo "You can list sinks with: pactl list sinks short"
echo "Any application using the default PulseAudio output will now send audio to '${VIRTUAL_SINK_NAME}' (which discards it)."