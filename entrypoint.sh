#!/usr/bin/env bash

# Clean up to be "stateless" on startup, otherwise pulseaudio daemon can't start
rm -rf /var/run/pulse /var/lib/pulse /root/.config/pulse

# Start pulseaudio as system-wide daemon; for debugging it helps to start in non-daemon mode
pulseaudio -D --verbose --exit-idle-time=-1 --system --disallow-exit

# Create a virtual audio sink (i.e., a "virtual speaker") 
# Note: You can also specify other parameters such as format, channels, etc. if needed. 
echo "Creating virtual audio sink: "
pactl load-module module-virtual-sink sink_name=VirtualSpeaker master=auto_null format=s16le

# Allow pulseaudio to be accessed via TCP (from localhost only), to allow other users to access the virtual devices
pacmd load-module module-native-protocol-tcp auth-ip-acl=127.0.0.1

# Configure client.conf to use our local Pulseaudio server
mkdir -p /home/.pulse
echo "default-server = 127.0.0.1" > /home/.pulse/client.conf

# Set VirtualSpeaker as default sink (i.e. default output device)
echo "Setting default sink: "
pactl set-default-sink VirtualSpeaker