#!/data/data/com.termux/files/usr/bin/sh
# FireLab ad-blocker agent (Termux, NOT inside PRoot).
#
# Polls a command file written by the dashboard, forwards start/stop/setup to
# the blocker APK, then publishes the blocker's HTTP status as JSON.
#
# Install:
#   cp firelab-adblock-agent.sh   $HOME/firelab-adblock-agent.sh
#   cp firelab-adblock-status.py  $HOME/firelab-adblock-status.py
#   chmod 700 $HOME/firelab-adblock-agent.sh
#
# Run:
#   $HOME/firelab-adblock-agent.sh >> $HOME/firelab-adblock.log 2>&1 &

export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:/system/bin
export LD_LIBRARY_PATH=$PREFIX/lib
export TMPDIR=$PREFIX/tmp

CMD=$HOME/firelab-adblock.cmd
OUT=$HOME/firelab-adblock.json
TMP=$HOME/.firelab-adblock.json.tmp
CLIENT=$HOME/firelab-adblock-status.py

# Make sure the status file exists even before the first start command.
if [ ! -f "$OUT" ]; then
    python3 "$CLIENT" "$OUT" "$TMP" 2>/dev/null
fi

while true; do
    if [ -f "$CMD" ]; then
        action=$(head -n 1 "$CMD" 2>/dev/null | tr -d '\r\n ')

        # Remove the command first so a malformed or repeated write cannot
        # execute twice. The dashboard writes atomically.
        rm -f "$CMD"

        case "$action" in
            start|stop|setup)
                env -u LD_LIBRARY_PATH /system/bin/am broadcast --user 0 \
                    -a com.firelab.adblock.CONTROL \
                    -n com.firelab.adblock/.ControlReceiver \
                    --es cmd "$action" >/dev/null 2>&1
                ;;
            "")
                ;;
            *)
                printf '%s unsupported action=%s\n' \
                    "$(date '+%Y-%m-%d %H:%M:%S')" "$action" \
                    >> "$HOME/firelab-adblock-actions.log"
                ;;
        esac
    fi

    python3 "$CLIENT" "$OUT" "$TMP" 2>/dev/null
    sleep 3
done
