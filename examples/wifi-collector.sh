#!/data/data/com.termux/files/usr/bin/sh
# FireLab WiFi collector (Termux, NOT inside PRoot).
#
# Order matters: the Python client must be listening BEFORE the broadcast is
# sent, because `am broadcast` blocks until the helper's one-shot socket closes.
#
# Install:
#   cp wifi-collector.sh   $HOME/firelab-wifi-collector.sh
#   cp firelab-wifi-client.py $HOME/firelab-wifi-client.py
#   chmod 700 $HOME/firelab-wifi-collector.sh
#
# Run it from the boot runner or by hand:
#   $HOME/firelab-wifi-collector.sh >> $HOME/firelab-wifi.log 2>&1 &

export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:/system/bin
export LD_LIBRARY_PATH=$PREFIX/lib
export TMPDIR=$PREFIX/tmp

TARGET=$HOME/firelab-wifi.json
TEMP=$HOME/.firelab-wifi.json.tmp
CLIENT=$HOME/firelab-wifi-client.py

while true; do
    python3 "$CLIENT" "$TARGET" "$TEMP" &
    CLIENT_PID=$!
    sleep 0.3

    # `am` aborts with signal 6 if it inherits Termux's LD_LIBRARY_PATH.
    env -u LD_LIBRARY_PATH /system/bin/am broadcast --user 0 \
        -a com.firelab.wifi.COLLECT \
        -n com.firelab.wifi/.WifiReceiver >/dev/null 2>&1

    wait "$CLIENT_PID" 2>/dev/null
    sleep 10
done
