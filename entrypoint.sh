# cleanup to be "stateless" on startup, otherwise pulseaudio daemon can't start
rm -rf /var/run/pulse /var/lib/pulse /root/.config/pulse

# start pulseaudio as system wide daemon; for debugging it helps to start in non-daemon mode
pulseaudio -D --verbose --exit-idle-time=-1 --system --disallow-exit

# Wait for PulseAudio to fully start
sleep 2

# create a virtual audio sink (speaker); fixed by adding sink master and format
echo "Creating virtual audio sink: ";
pactl load-module module-virtual-sink master=auto_null format=s16le sink_name=VirtualSpeaker

# allow pulse audio to be accessed via TCP (from localhost only), to allow other users to access the virtual devices
pactl load-module module-native-protocol-tcp auth-ip-acl=127.0.0.1

# https://manpages.ubuntu.com/manpages/trusty/en/man5/pulse-client.conf.5.html
mkdir -p /home/.pulse
echo "default-server = 127.0.0.1" > /home/.pulse/client.conf

# set VirtualSpeaker as default output sink;
echo "Setting default sink: ";
pactl set-default-sink VirtualSpeaker