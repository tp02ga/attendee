#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# --- Configuration ---
# Define the name and description for the virtual speaker
VIRTUAL_SINK_NAME="VirtualSpeaker"
VIRTUAL_SINK_DESCRIPTION="My Virtual Speaker Output"
PULSE_START_TIMEOUT=5 # Seconds to wait for PulseAudio daemon to start

# --- Script Start ---
echo "Cleaning up previous PulseAudio state..."
# cleanup to be "stateless" on startup, otherwise pulseaudio daemon can't start
rm -rf /var/run/pulse /var/lib/pulse /root/.config/pulse

echo "Starting PulseAudio system-wide daemon..."
# start pulseaudio as system wide daemon; use -D as --start is not compatible with --system
pulseaudio -D --verbose --exit-idle-time=-1 --system --disallow-exit

# Wait and check if PulseAudio daemon is responsive
echo "Waiting up to ${PULSE_START_TIMEOUT} seconds for PulseAudio daemon to become responsive..."
success=0
for (( i=1; i<=${PULSE_START_TIMEOUT}; i++ )); do
    if pactl info &> /dev/null; then
        echo "PulseAudio daemon is responsive."
        success=1
        break
    fi
    echo -n "."
    sleep 1
done
echo # Newline after dots

if [[ ${success} -eq 0 ]]; then
    echo "Error: PulseAudio daemon did not become responsive within ${PULSE_START_TIMEOUT} seconds." >&2
    echo "Check PulseAudio logs for details (e.g., journalctl -u pulseaudio or check syslog)." >&2
    exit 1
fi

echo "Creating virtual audio sink (speaker): ${VIRTUAL_SINK_NAME}"
# Load the null sink module to create a virtual output device (speaker)
pactl load-module module-null-sink \
    sink_name=${VIRTUAL_SINK_NAME} \
    sink_properties=device.description="${VIRTUAL_SINK_DESCRIPTION}"

# Check if module loaded successfully
if ! pactl list sinks short | grep -q "${VIRTUAL_SINK_NAME}"; then
    echo "Error: Failed to create virtual sink ${VIRTUAL_SINK_NAME}." >&2
    exit 1 # Exit if sink creation failed
else
    echo "Virtual sink '${VIRTUAL_SINK_NAME}' created successfully."
fi

echo "Allowing PulseAudio access via TCP (localhost only)..."
# Allow pulse audio to be accessed via TCP (from localhost only)
pactl load-module module-native-protocol-tcp auth-ip-acl=127.0.0.1

echo "Configuring default client connection (if needed)..."
# Configure client connection settings for specific users if necessary
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
echo "Any application using the default PulseAudio output will now send audio to '${VIRTUAL_SINK_NAME}'."