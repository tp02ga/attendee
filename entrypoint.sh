# cleanup to be "stateless" on startup, otherwise pulseaudio daemon can't start
rm -rf /var/run/pulse /var/lib/pulse /root/.config/pulse

# start pulseaudio as system wide daemon; for debugging it helps to start in non-daemon mode
pulseaudio -D --verbose --exit-idle-time=-1 --system --disallow-exit

# create a virtual audio source; fixed by adding source master and format
echo "Creating virtual audio source: ";
pactl load-module module-virtual-source master=auto_null.monitor format=s16le source_name=VirtualMic

# sllow pulse audio to be accssed via TCP (from localhost only), to allow other users to access the virtual devices
pacmd load-module module-native-protocol-tcp auth-ip-acl=127.0.0.1

# https://manpages.ubuntu.com/manpages/trusty/en/man5/pulse-client.conf.5.html
mkdir -p /home/.pulse
echo "default-server = 127.0.0.1" > /home/.pulse/client.conf

# set VirtualMic as default input source;
echo "Setting default source: ";
pactl set-default-source VirtualMic