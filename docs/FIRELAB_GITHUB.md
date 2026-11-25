# FireLab — a self-hosted control center on a non-rooted Fire TV Stick

> This document explains how FireLab was built, how each part works, and the
> problems that were found while running it on a real Amazon Fire TV Stick.
> Every personal value is replaced with a placeholder. See
> [Sanitization checklist](#sanitization-checklist) before publishing a fork.

## Contents

1. [What FireLab is](#1-what-firelab-is)
2. [Architecture](#2-architecture)
3. [Prerequisites](#3-prerequisites)
4. [Prepare the Fire TV](#4-prepare-the-fire-tv)
5. [Termux and Debian under PRoot](#5-termux-and-debian-under-proot)
6. [Dashboard and authentication](#6-dashboard-and-authentication)
7. [The Termux boot runner](#7-the-termux-boot-runner)
8. [WiFi helper APK](#8-wifi-helper-apk)
9. [WiFi collector](#9-wifi-collector)
10. [Network tab and backend](#10-network-tab-and-backend)
11. [The Cloudflare quick-tunnel loop](#11-the-cloudflare-quick-tunnel-loop)
12. [Rootless ad blocker](#12-rootless-ad-blocker)
13. [Security model](#13-security-model)
14. [Problems and fixes](#14-problems-and-fixes)
15. [Verification checklist](#15-verification-checklist)
16. [Operations and rollback](#16-operations-and-rollback)
17. [Publishing safely](#17-publishing-safely)
18. [Sanitization checklist](#sanitization-checklist)
19. [Appendix: key snippets](#19-appendix-key-snippets)

---

## 1. What FireLab is

FireLab is a small home-server dashboard that runs on an Android TV device
without root. The device stays useful after the TV is off: it can serve files,
show system metrics, expose WiFi details and block DNS-level ads for the whole
device.

The project deliberately avoids modifying the system partition:

- No root, no Magisk, no custom ROM.
- Termux provides the Linux userland.
- PRoot provides a Debian rootfs in userspace.
- Helper APKs provide Android-only data and services.
- Cloudflare provides the optional remote HTTPS entry point.

Tested reference environment:

| Item | Value |
|---|---|
| Device | Amazon Fire TV Stick |
| Fire OS | 5.1.1 |
| Android API | 22 |
| CPU ABI | `armeabi-v7a` |
| Guest | Debian 12 under PRoot |
| Runtime | Python 3.11 |
| Dashboard port | `18081` (local) |
| SSH port | `2222` (local only, optional) |
| ADB port | `5555` (local only) |

Newer Fire OS versions may behave differently, especially around background
services, VPN consent and Termux plugin permissions.

---

## 2. Architecture

```text
┌──────────────────────────────────────────────────────────────────┐
│ Amazon Fire TV Stick (non-rooted)                                │
│                                                                  │
│  ┌──────────────── Termux (Android app, UID u0_aXXX) ──────────┐  │
│  │                                                             │  │
│  │  Termux:Boot                                                │  │
│  │    └─> ~/.termux/boot/start-firelab.sh                      │  │
│  │          ├─> WiFi collector ──> helper APK socket :18082    │  │
│  │          ├─> ad blocker agent ─> blocker APK socket :18083  │  │
│  │          ├─> tunnel supervisor ─> cloudflared               │  │
│  │          └─> PRoot Debian 12                                │  │
│  │                └─> Python dashboard 127.0.0.1:18081         │  │
│  │                                                             │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Helper APK `com.firelab.wifi`                                   │
│    - reads WiFiManager data                                      │
│    - one-shot JSON socket on 127.0.0.1:18082                     │
│    - can start the Termux runner through RUN_COMMAND             │
│                                                                  │
│  Blocker APK `com.firelab.adblock`                               │
│    - VpnService DNS sinkhole                                     │
│    - status HTTP socket on 127.0.0.1:18083                       │
│    - control broadcast for start/stop/setup                      │
│                                                                  │
│  Optional: Cloudflare quick tunnel ──> dashboard only            │
└──────────────────────────────────────────────────────────────────┘
```

The dashboard is not exposed directly to the internet. If remote access is
enabled, Cloudflare forwards only `http://127.0.0.1:18081`. ADB `5555` and SSH
`2222` must never be tunneled or port-forwarded.

---

## 3. Prerequisites

### On the Windows/Linux workstation

- Android platform-tools (`adb`)
- A way to transfer files to the device (`adb push`)
- Optional: JDK 17 and Android build-tools if you want to build the helper APKs
  - `javac`
  - `d8`
  - `aapt2`
  - `zipalign`
  - `apksigner`
  - `android.jar` for the target API (API 22 for Fire OS 5.1.1)
- Optional: `ssh` client for the key-only Termux SSH listener
- Optional: a Cloudflare account if you want a stable named tunnel instead of a
  quick tunnel

### On the Fire TV

- Developer options and ADB debugging enabled
- Termux and Termux:Boot installed **from the same source**
  - Do not mix the Play Store build with the F-Droid/GitHub build; the
    `RUN_COMMAND` permission is signature-based.
- Network access to the same LAN as the workstation
- Enough free storage for the Debian rootfs and logs

---

## 4. Prepare the Fire TV

1. Enable developer options:
   - Settings → My Fire TV → About → click the device name several times.
2. Open Developer Options and enable **ADB debugging**.
3. Connect from the workstation:

```powershell
adb connect DEVICE_IP:5555
adb devices
```

4. Accept the authorization prompt on the TV if it appears.
5. Confirm the device is visible:

```powershell
adb shell getprop ro.build.version.sdk
adb shell getprop ro.product.cpu.abi
```

For the reference device this returned API `22` and `armeabi-v7a`.

> ADB over Wi-Fi can drop when the TV sleeps or the router changes the lease.
> Reconnect with `adb connect DEVICE_IP:5555`; use a DHCP reservation if the
> address changes often.

---

## 5. Termux and Debian under PRoot

### 5.1 Install Termux and Termux:Boot

Install both apps from the same distribution. Open Termux once and update the
package index:

```sh
pkg update
pkg upgrade
pkg install proot python net-tools
```

Optional packages:

```sh
pkg install openssh
pkg install proot-distro
```

### 5.2 Get a Debian rootfs

Two common approaches:

**Option A: proot-distro**

```sh
proot-distro install debian
proot-distro login debian
```

**Option B: a manual rootfs**

```sh
mkdir -p "$HOME/firelab-test"
# extract a Debian armhf/armv7 rootfs into:
#   $HOME/firelab-test/debian
# place the proot binary at:
#   $HOME/firelab-test/proot
```

The manual layout used by FireLab:

```text
$HOME/firelab-test/
├── proot
└── debian/
    ├── bin/
    ├── etc/
    ├── home/firelab/
    │   ├── firelab_api.py
    │   ├── firelab-auth.json      # mode 600, never served
    │   ├── storage/
    │   └── webroot/index.html
    └── usr/
```

### 5.3 Bind mounts

The guest needs Android's `/system` (for some tools) and the Termux home:

```sh
export PROOT_TMP_DIR="$HOME/tmp"
mkdir -p "$PROOT_TMP_DIR"
mkdir -p "$HOME/firelab-test/debian/host"
chmod 755 "$HOME/firelab-test/debian/host"

"$HOME/firelab-test/proot" \
  -S "$HOME/firelab-test/debian" \
  -b /system:/system \
  -b "$HOME:/host" \
  /usr/bin/python3.11 -u /home/firelab/firelab_api.py \
  --bind 0.0.0.0 --port 18081
```

Inside the guest, the Termux home is available at `/host`. This is how the
backend reads WiFi JSON and the public tunnel URL without exposing Android
storage.

### 5.4 Keep the CPU awake

Termux can request a wake lock:

```sh
termux-wake-lock
```

The boot runner calls it after startup. Fire OS may still impose background
limits; a foreground service or an active wake lock improves reliability.

---

## 6. Dashboard and authentication

The dashboard is a small Python HTTP server using only the standard library.
It serves one self-contained `index.html` and a JSON API.

Start it manually:

```sh
cd /home/firelab
python3.11 -u firelab_api.py --bind 0.0.0.0 --port 18081
```

Set or reset the password:

```sh
python3.11 firelab_api.py --set-password
```

### 6.1 Authentication design

- Passwords are stored as PBKDF2-HMAC-SHA256 hashes with 120,000 rounds.
- The auth file is mode `600` and is never served over HTTP.
- Sessions use random 256-bit tokens.
- Only SHA-256 hashes of session tokens are stored in server memory.
- Idle limit: 12 hours. Absolute limit: 24 hours.
- State-changing requests require a per-session CSRF token.
- Login failures are limited to 5 per IP in 10 minutes, followed by a
  15-minute block.
- Dashboard responses include CSP, frame-denial, MIME-sniffing and referrer
  protections.

### 6.2 API surface

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/` | No | Login page / dashboard |
| GET | `/api/health` | No | Liveness probe |
| GET | `/api/auth/session` | No | Session bootstrap |
| POST | `/api/auth/login` | No | Sign in |
| POST | `/api/auth/logout` | Yes | Sign out |
| POST | `/api/auth/password` | Yes | Change password |
| GET | `/api/status` | Yes | CPU, RAM, disk, uptime |
| GET | `/api/network` | Yes | WiFi, addressing, DNS, traffic |
| GET | `/api/adblock` | Yes | Ad blocker status and counters |
| POST | `/api/adblock/toggle` | Yes + CSRF | Queue start/stop/setup |
| GET | `/api/files` | Yes | List storage |
| POST | `/api/mkdir` | Yes + CSRF | Create folder |
| POST | `/api/upload` | Yes + CSRF | Upload file |
| GET | `/api/download` | Yes | Download file |

All authenticated endpoints return `401` without a session. Write endpoints
return `403` without the CSRF header.

### 6.3 UI

The UI is a single `index.html` with inline CSS and JavaScript, matching the
dashboard's CSP. Views are switched client-side:

- Overview
- System Monitoring
- File Manager
- Network
- Ad Blocker
- Terminal (placeholder/restricted)
- Applications (placeholder)
- Settings

The Network tab polls `/api/network` every 6 seconds when auto-refresh is on.
The Ad Blocker tab polls `/api/adblock` on the same cadence.

---

## 7. The Termux boot runner

The runner is the heart of the reliability story. It is a plain `sh` script in
Termux, not inside PRoot.

### 7.1 Why a custom loop

Android may kill the backend after memory pressure, a crash, or a reboot. A
simple `nohup python ... &` is not enough:

- It does not survive a reboot.
- It does not restart after a crash.
- It can leave an orphaned Python process holding the port.
- ADB-spawned processes can die when the ADB shell closes.

The runner uses:

- `Termux:Boot` for startup
- a PID file plus a port check for duplicate protection
- a `trap` for clean shutdown
- a restart backoff
- orphan cleanup before retrying
- log rotation
- a wake lock

### 7.2 Boot flow

1. Android sends `BOOT_COMPLETED`.
2. Termux:Boot schedules its job.
3. Termux:Boot runs every executable file in `~/.termux/boot/`.
4. `start-firelab.sh` takes a wake lock and waits 15 seconds for the network
   and storage to settle.
5. It starts the WiFi collector, the ad blocker agent and the tunnel
   supervisor.
6. It starts PRoot + Python.
7. When Python exits, it restarts with backoff.

Termux:Boot jobs can be delayed by Android. Allow up to three minutes after a
reboot before assuming auto-start failed.

### 7.3 Loop sketch

```sh
#!/data/data/com.termux/files/usr/bin/sh

HOME_DIR=/data/data/com.termux/files/home
LOG="$HOME_DIR/firelab-boot.log"
PIDFILE="$HOME_DIR/firelab-runner.pid"
PROOT="$HOME_DIR/firelab-test/proot"
ROOTFS="$HOME_DIR/firelab-test/debian"
PORT=18081

# duplicate guard
# port check
# trap cleanup INT TERM HUP

termux-wake-lock
sleep 15

start_collector
start_adblock_agent
start_tunnel_supervisor

backoff=5
while true; do
  if port_in_use; then
    kill_orphans
    sleep 2
  fi

  "$PROOT" -S "$ROOTFS" \
    -b /system:/system \
    -b "$HOME_DIR:/host" \
    /usr/bin/python3.11 -u /home/firelab/firelab_api.py \
    --bind 0.0.0.0 --port "$PORT" >> "$LOG" 2>&1 &
  CHILD=$!

  wait "$CHILD"
  # reset or increase backoff, then retry
done
```

### 7.4 Boot directory rules

- Every file in `~/.termux/boot/` is executed. Do not put backups there.
- Use LF line endings, not CRLF. Windows editors can silently break the script.
- Mode `700` is appropriate.
- Keep the scripts owned by the Termux UID.

### 7.5 Starting without a reboot

A helper receiver can start the runner through Termux `RUN_COMMAND`:

```powershell
adb shell "am broadcast --user 0 \
  -a com.firelab.wifi.START_DASHBOARD \
  -n com.firelab.wifi/.RunCommandReceiver"
```

This is more reliable than an ADB-spawned background process because Termux owns
the child.

---

## 8. WiFi helper APK

### 8.1 Why a helper APK was needed

The Fire TV is not rooted, and Termux:API could not be used because its
signature did not match the installed Termux build. Shell tools also did not
reliably expose the live SSID and link speed:

- `dumpsys wifi` output varies by Fire OS build.
- `ip`/`iw` under Termux may be restricted.
- `cmd wifi` is not available on older Fire OS versions.
- `run-as` cannot read all system services.

A tiny APK using the public `WifiManager` API is the most reliable option.

### 8.2 What the helper reads

`WifiReader` uses `WifiManager` and related APIs to collect:

- SSID and BSSID
- MAC address
- RSSI (dBm)
- link speed (Mbps)
- frequency (MHz)
- network ID
- hidden SSID flag
- supplicant state
- security type (from configured networks)
- IPv4 address

Example JSON shape:

```json
{
  "ok": true,
  "ssid": "<wifi-name>",
  "bssid": "AA:BB:CC:DD:EE:FF",
  "mac_address": "AA:BB:CC:DD:EE:FF",
  "rssi": -50,
  "link_speed_mbps": 144,
  "frequency": 2437,
  "network_id": 1,
  "hidden_ssid": false,
  "supplicant_state": "COMPLETED",
  "security": "WPA/WPA2-PSK",
  "ip": "192.168.1.10"
}
```

### 8.3 One-shot socket protocol

The helper does not poll or write to shared storage. It opens a one-shot TCP
server on loopback:

```text
Termux client ── connect ──> 127.0.0.1:18082
                              helper accepts
                              helper writes JSON
                              helper closes socket
```

Key points:

- Bind to `127.0.0.1`, not `0.0.0.0`.
- Use `goAsync()` in the broadcast receiver so Fire OS keeps the broadcast
  alive while the socket is open.
- Use an 8-second accept timeout.
- Allow only one collection at a time.
- Close the server socket in `finally`.

Simplified receiver:

```java
public class WifiReceiver extends BroadcastReceiver {
    private static final int PORT = 18082;

    @Override
    public void onReceive(Context context, Intent intent) {
        final PendingResult pending = goAsync();
        final Context app = context.getApplicationContext();

        new Thread(() -> {
            String text = WifiReader.read(app);
            try (ServerSocket server = new ServerSocket()) {
                server.setReuseAddress(true);
                server.bind(new InetSocketAddress(
                        InetAddress.getByName("127.0.0.1"), PORT));
                server.setSoTimeout(8000);
                try (Socket client = server.accept()) {
                    client.getOutputStream().write(
                            text.getBytes(StandardCharsets.UTF_8));
                }
            } catch (Exception ignored) {
                // Timeout or client disconnected.
            } finally {
                pending.finish();
            }
        }).start();
    }
}
```

### 8.4 RUN_COMMAND launcher

A second receiver starts the Termux runner without ADB:

```java
Intent intent = new Intent();
intent.setClassName("com.termux", "com.termux.app.RunCommandService");
intent.setAction("com.termux.RUN_COMMAND");
intent.putExtra("com.termux.RUN_COMMAND_PATH",
        "/data/data/com.termux/files/usr/bin/sh");
intent.putExtra("com.termux.RUN_COMMAND_ARGUMENTS",
        new String[]{"-c", "exec /data/data/com.termux/files/home/start-firelab.sh"});
intent.putExtra("com.termux.RUN_COMMAND_WORKDIR",
        "/data/data/com.termux/files/home");
intent.putExtra("com.termux.RUN_COMMAND_BACKGROUND", true);
context.startService(intent);
```

The command path and arguments must be exact. Use `sh -c 'exec ...'` so the
script replaces the shell process and survives the caller.

### 8.5 Manifest notes

```xml
<uses-permission android:name="android.permission.INTERNET" />

<receiver
    android:name=".WifiReceiver"
    android:exported="true">
    <intent-filter>
        <action android:name="com.firelab.wifi.COLLECT" />
    </intent-filter>
</receiver>

<receiver
    android:name=".RunCommandReceiver"
    android:exported="true">
    <intent-filter>
        <action android:name="com.firelab.wifi.START_DASHBOARD" />
    </intent-filter>
</receiver>
```

Termux must allow external apps:

```properties
# ~/.termux/termux.properties
allow-external-apps=true
```

### 8.6 Build and install

A minimal build pipeline using Android build-tools:

```powershell
javac -source 8 -target 8 -bootclasspath android.jar -d classes (Get-ChildItem src -Recurse -Filter *.java)
d8 --lib android.jar --min-api 21 --output dex (Get-ChildItem classes -Recurse -Filter *.class)
aapt2 link -o base.apk -I android.jar --manifest AndroidManifest.xml --min-sdk-version 21 --target-sdk-version 22
# add classes.dex to base.apk, then:
zipalign -f 4 base.apk aligned.apk
apksigner sign --ks YOUR_KEYSTORE --out firelab-wifi.apk aligned.apk
adb install -r firelab-wifi.apk
```

Use your own keystore. Never commit a keystore or its password. The manifest
must target an API level the device accepts; API 22 worked for Fire OS 5.1.1.

---

## 9. WiFi collector

The collector lives in Termux and calls the helper every ~10 seconds. The order
of operations is critical.

### 9.1 Correct order

```text
1. Start the Python socket client in the background.
2. Sleep 0.3 s.
3. Broadcast com.firelab.wifi.COLLECT with `am`.
4. Wait for the client to finish.
5. Atomically write the JSON file.
6. Sleep 10 s and repeat.
```

The client must start **before** the broadcast. `am broadcast` blocks until the
helper's 8-second accept window closes. If you broadcast first, the client starts
after the socket is already closed and always times out.

### 9.2 Working collector

```sh
#!/data/data/com.termux/files/usr/bin/sh
# FireLab WiFi collector: wait on the helper socket, trigger the helper,
# then save the received JSON. The client must start BEFORE the broadcast
# because `am broadcast` blocks until the helper's one-shot socket closes.

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
    env -u LD_LIBRARY_PATH /system/bin/am broadcast --user 0 \
        -a com.firelab.wifi.COLLECT \
        -n com.firelab.wifi/.WifiReceiver >/dev/null 2>&1
    wait "$CLIENT_PID" 2>/dev/null
    sleep 10
done
```

### 9.3 Status client

The client retries `127.0.0.1:18082` until the helper is listening, reads until
EOF, validates that the payload looks like JSON, writes a temporary file and
renames it into place. The rename makes readers see either the old complete file
or the new complete file, never a half-written one.

### 9.4 Why `env -u LD_LIBRARY_PATH`

Termux sets `LD_LIBRARY_PATH` to its own libraries. `/system/bin/am` is an
Android framework tool and aborts with signal 6 when it inherits Termux's
library path. Run it with the variable removed:

```sh
env -u LD_LIBRARY_PATH /system/bin/am broadcast ...
```

The same `am` command also aborts inside PRoot. For that reason the collector
must run in Termux, not in the Debian guest.

### 9.5 Why not use `dumpsys` or `iw`

`dumpsys wifi` and `iw` output differ across Fire OS builds and may omit the
live SSID or link speed. The helper's `WifiManager` data is more stable.

---

## 10. Network tab and backend

The backend merges several sources:

- Helper JSON at `/host/firelab-wifi.json`
- `/proc/net/route` for the default gateway
- `ip`/`ifconfig` for addresses and netmask
- `/proc/net/dev` for byte and packet counters
- `/host/firelab-public-url.txt` for the current tunnel URL

### 10.1 What the API returns

The `/api/network` payload includes:

- `connected`, `ssid`, `bssid`, `mac`
- `security`, `supplicant_state`, `network_id`
- `rssi_dbm`, `signal_quality`, `link_speed_mbps`
- `frequency_mhz`, `band`, `channel`
- `ip`, `prefix`, `netmask`, `gateway`
- `dhcp_server`, `dns`, `domain`, `lease_seconds`
- `interface`, `ipv6`, `hostname`
- `rx_bytes`, `tx_bytes`, `rx_packets`, `tx_packets`
- `rx_rate_bps`, `tx_rate_bps`
- `public_url`
- `ssid_source`, `wifi_sample_age`, `notes`

### 10.2 Netmask to prefix

Convert a dotted netmask to a prefix length by counting set bits:

```python
parts = [int(part) for part in netmask.split(".")]
prefix = sum(bin(part).count("1") for part in parts)
```

A gateway fallback reads `/proc/net/route` and decodes the little-endian hex
address when `ip route` is unavailable.

### 10.3 Traffic rates

Byte counters are cumulative. The backend stores the previous sample under a
lock and computes:

```text
rate = (current_bytes - previous_bytes) / elapsed_seconds
```

The first sample returns `0` rather than a misleading spike.

### 10.4 UI

The Network tab has:

- A hero card with SSID, signal bars, link speed and frequency
- Connection, addressing, DHCP/DNS, radio and traffic cards
- A public tunnel link
- Source and sample-age footer

All values come from the authenticated API; the page itself contains no secrets.

---

## 11. The Cloudflare quick-tunnel loop

Cloudflare is optional. It provides an HTTPS URL for the dashboard without
opening a router port. The origin still speaks plain HTTP on loopback.

### 11.1 Tunnel command

Inside PRoot, with the Termux home bound at `/host`:

```sh
/host/cloudflared tunnel \
  --url http://127.0.0.1:18081 \
  --no-autoupdate
```

`cloudflared` prints a random `https://<words>.trycloudflare.com` URL. The
supervisor captures it, writes it to `firelab-public-url.txt`, and optionally
sends a Telegram message when the URL changes.

### 11.2 Supervisor behavior

- Wait until port `18081` is listening (up to a timeout).
- Refuse to start a second supervisor using a PID file and command-line check.
- Start `cloudflared` and capture stdout/stderr to a log.
- Poll the log for the public URL.
- Write the URL atomically.
- Notify Telegram only when the URL differs from the last notified value.
- If `cloudflared` exits, restart it after a short delay.
- Rotate logs at a size limit.

### 11.3 Boot integration

The tunnel supervisor is a boot script:

```text
~/.termux/boot/start-tunnel.sh
```

The dashboard runner also requests it after starting:

```sh
if [ -x "$HOME/.termux/boot/start-tunnel.sh" ]; then
  "$HOME/.termux/boot/start-tunnel.sh" >> "$LOG" 2>&1 &
fi
```

The duplicate guard prevents two cloudflared processes when both Termux:Boot and
the runner request the tunnel.

### 11.4 The 530 problem

A quick tunnel can return HTTP `530` when:

- `cloudflared` exited and its random hostname expired.
- The supervisor died but the URL file still contained the old hostname.
- The dashboard port was not listening when the tunnel started.

Fix:

1. Check the supervisor log and the cloudflared log.
2. Confirm `18081` is listening.
3. Restart the supervisor.
4. Read the new URL from `firelab-public-url.txt`.
5. Update the bookmark and notify users.

Quick-tunnel URLs are disposable. They change after a restart. For a stable
address, use a named Cloudflare tunnel with a domain you control:

```sh
cloudflared tunnel login
cloudflared tunnel create firelab
cloudflared tunnel route dns firelab firelab.example.com
cloudflared tunnel run firelab
```

### 11.5 Never tunnel SSH or ADB

Only forward the dashboard port. Do not create a Cloudflare route, reverse
proxy, or port forward for:

- SSH `2222`
- ADB `5555`
- Any Termux service other than the dashboard

The dashboard's own authentication is still required even behind Cloudflare.

---

## 12. Rootless ad blocker

### 12.1 Why a VPN, not a hosts file

A system-wide `/etc/hosts` edit requires root. On a non-rooted Fire TV, the
supported way to intercept DNS for all apps is Android's `VpnService` API.

The blocker is a local VPN that intercepts **DNS traffic only**:

- It does not route normal traffic through a remote server.
- It does not need root.
- It does not modify the system partition.
- It shows the standard Android VPN key notification while active.

### 12.2 TUN configuration

```java
Builder builder = new Builder();
builder.setSession("FireLab Ad Blocker");
builder.addAddress("10.111.222.2", 32);
builder.addDnsServer("10.111.222.1");
builder.addRoute("10.111.222.1", 32);
builder.setMtu(1500);
builder.setBlocking(true);
ParcelFileDescriptor tun = builder.establish();
```

Because the only route is `10.111.222.1/32`, normal traffic continues to use
WiFi directly. Android sends app DNS queries to `10.111.222.1`, which is inside
the TUN.

### 12.3 DNS packet flow

```text
app DNS query
   │
   ▼
TUN (10.111.222.1:53)
   │
   ├─ domain blocked? ──> build local response
   │                       A     -> 0.0.0.0
   │                       AAAA  -> empty NOERROR
   │                       HTTPS -> empty NOERROR
   │
   └─ not blocked? ─────> forward to 1.1.1.1, then 8.8.8.8
                           write response back to TUN
```

Implementation details:

- Parse the IPv4 header (`version == 4`, protocol `17` for UDP).
- Require destination port `53`.
- Parse the DNS question name and type.
- Block exact matches and parent domains:
  - `ads.example.com` is blocked if `ads.example.com` or `example.com` is in
    the blocklist.
- Build the response with the original transaction ID.
- Set `QR=1`, `RD=1`, `RA=1`.
- For blocked A queries, add one answer pointing to `0.0.0.0` with a short TTL.
- For blocked AAAA/HTTPS queries, return NOERROR with zero answers so clients
  fall back to A.
- Recompute the IPv4 header checksum; UDP checksum `0` is valid for IPv4.
- Write the response packet back to the TUN file descriptor.

### 12.4 Blocklist

The example APK bundles a hosts-derived domain list:

- Source: [StevenBlack/hosts](https://github.com/StevenBlack/hosts)
- Strip comments and localhost entries.
- Keep valid domains.
- Deduplicate.
- Optionally add the base domain for `www.` entries.
- Write one domain per line to `assets/blocklist.txt`.
- Load it into a `HashSet` on a background thread at service start.

A list of roughly 80,000 domains fits comfortably in memory and makes the APK
about 0.6 MB compressed. A larger list can be downloaded on first run, but then
you need update/verification logic and storage permissions.

### 12.5 Status and control

The blocker service hosts a small HTTP status server on
`127.0.0.1:18083`:

```json
{
  "enabled": true,
  "service_running": true,
  "blocklist_ready": true,
  "blocklist_size": 80000,
  "queries_session": 120,
  "blocked_session": 35,
  "queries_total": 5000,
  "blocked_total": 1400,
  "last_blocked": "ads.example.com",
  "upstream": "1.1.1.1",
  "uptime_seconds": 600,
  "error": "",
  "version": "1.0"
}
```

Control is a separate exported receiver:

```text
action: com.firelab.adblock.CONTROL
extra:  cmd = start | stop | setup
```

`start` and `stop` start/stop the VPN service. `setup` opens the consent/status
activity on the TV. The service itself keeps the standard
`android.permission.BIND_VPN_SERVICE` protection; the control receiver starts it
from the same app UID.

The first run always requires the user to accept Android's VPN consent dialog on
the TV. After that, the service can be started without a dialog.

### 12.6 Termux agent

The agent polls a command file and publishes status:

```text
dashboard → POST /api/adblock/toggle
          → writes $HOME/firelab-adblock.cmd
          → Termux agent reads it
          → am broadcast com.firelab.adblock.CONTROL
          → blocker APK starts/stops
          → status socket :18083
          → agent writes $HOME/firelab-adblock.json
          → dashboard GET /api/adblock
```

The agent runs every 3 seconds. It also removes the command file after reading
it, so a command is not executed twice.

### 12.7 Dashboard integration

- `GET /api/adblock` reads `/host/firelab-adblock.json` and adds age/stale
  information.
- `POST /api/adblock/toggle` requires a session and CSRF token.
- Allowed actions: `start`, `stop`, `setup`.
- The endpoint writes the command file atomically and returns
  `{"success": true, "queued": true}`.
- The UI shows status, session queries, blocked count, block rate, uptime,
  blocklist size, last blocked domain and errors.
- Buttons: Enable/Disable blocking, Open setup on TV, Refresh, Auto refresh.

If the status file is older than 30 seconds, the UI marks it stale. If the
socket is unreachable, the agent still writes a valid "off" record so the
dashboard does not fail.

### 12.8 Limitations

DNS blocking cannot block everything:

- Ads served from the same domain as the content (for example, a video ad from
  the same CDN) are not distinguishable by DNS.
- Apps using DNS-over-HTTPS (DoH) or hardcoded DNS servers may bypass the VPN.
- IPv6 DNS is not intercepted in the reference build; the test network used
  IPv4.
- Fire OS may kill the VPN service under memory pressure. A foreground service
  and notification reduce this risk.
- A local VPN consumes a small amount of CPU and battery.
- The control receiver is exported. Any local app could send start/stop
  commands. For a hardened build, add a signature-level permission or a shared
  secret.

---

## 13. Security model

### Dashboard

- Strong password, PBKDF2-HMAC-SHA256, 120,000 rounds.
- Auth file mode `600`, never served.
- Session tokens are random, hashed at rest, idle/absolute expiry.
- CSRF token required on writes.
- Login throttle: 5 failures per IP per 10 minutes, then 15-minute block.
- CSP, frame denial, MIME-sniffing and referrer protections.
- File manager restricts paths to the storage root and rejects symlinks.

### Network exposure

- Dashboard binds `0.0.0.0:18081` for LAN access, or `127.0.0.1` behind a
  reverse proxy.
- Cloudflare forwards only the dashboard.
- SSH is key-only, user `firelab`, port `2222`, local only.
- ADB `5555` is local only.
- Never port-forward `18081`, `2222` or `5555` on the router.

### Secrets

- Telegram bot token in `~/.firelab_bot_token`, mode `600`.
- Do not put tokens, chat IDs, tunnel URLs, SSIDs, MAC addresses or public IPs
  in Git.
- Rotate any token that was ever pasted into a chat, log or screenshot.

### Ad blocker

- VPN consent is user-controlled.
- The blocker only routes DNS, not general traffic.
- The control receiver is a local convenience; harden it if the device is
  shared with untrusted apps.

---

## 14. Problems and fixes

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 1 | Termux:API commands fail with a permission/signature error | Termux and Termux:API were signed by different sources | Install Termux and Termux:API from the same source, or use a custom helper APK |
| 2 | `RUN_COMMAND` returns a generic plugin execution error | `allow-external-apps` was false when the Termux process started | Set `allow-external-apps=true`, then kill and reopen Termux so it reloads the property |
| 3 | `/system/bin/am` aborts with signal 6 | It inherited Termux's `LD_LIBRARY_PATH` | Run `env -u LD_LIBRARY_PATH /system/bin/am ...` |
| 4 | `am` also aborts inside PRoot | Android framework tools do not run reliably under PRoot | Run `am` in Termux, not in the Debian guest |
| 5 | WiFi JSON updates once and then stays stale | `am broadcast` blocks for the helper's 8-second accept, so a client started after it always misses the socket | Start the Python client first, sleep 0.3 s, then broadcast |
| 6 | Collector cannot create a temp file under `/data/local/tmp` | Heredoc/TMPDIR and permissions | Use a standalone Python client and set `TMPDIR` to Termux's `usr/tmp` |
| 7 | `run-as ... env ...` fails with permission denied | `run-as` cannot exec arbitrary binaries directly | Wrap commands in `run-as com.termux sh -c 'export ...; command'` |
| 8 | ADB `BOOT_COMPLETED` broadcast is denied | The receiver is not exported to shell | Use Termux:Boot or the helper's `RUN_COMMAND` path |
| 9 | Public URL returns HTTP 530 | The quick-tunnel supervisor died and the old hostname expired | Start the tunnel supervisor from the runner as well; keep a duplicate guard |
| 10 | Tunnel URL changes after every reboot | Cloudflare quick tunnels are ephemeral | Expected; use a named tunnel for a stable hostname |
| 11 | PRoot cannot see `/host` | Missing bind or wrong permissions | Add `-b "$HOME:/host"` and `chmod 755` the guest mount point |
| 12 | Dashboard dies when the ADB shell closes | ADB-spawned background process is tied to the shell | Start through Termux `RUN_COMMAND` or Termux:Boot |
| 13 | Backup scripts execute at boot | Termux:Boot runs every file in `~/.termux/boot/` | Keep only executable boot scripts there |
| 14 | Script fails with `no closing quote` | Windows PowerShell quoting vs. shell quoting | Put complex commands in a `.sh` file and run it with `sh` |
| 15 | WiFi helper works from ADB but not from Termux | `am` environment differs under the Termux UID | Remove `LD_LIBRARY_PATH` and use the explicit `/system/bin/am` path |
| 16 | Blocked domains still load | App uses DoH, hardcoded DNS, IPv6 or same-domain ads | Accept the limitation or add a full packet-level proxy (much larger scope) |

---

## 15. Verification checklist

Replace `DEVICE_IP` and `PUBLIC_HOST` with your own values.

### Dashboard

```powershell
adb shell "curl -s -o NUL -w '%{http_code}' http://127.0.0.1:18081/api/health"
# expected: 200
adb shell "curl -s -o NUL -w '%{http_code}' http://127.0.0.1:18081/api/network"
# expected: 401 without a session
adb shell "curl -s -o NUL -w '%{http_code}' http://127.0.0.1:18081/api/adblock"
# expected: 401 without a session
```

### WiFi

```powershell
adb shell "run-as com.termux cat /data/data/com.termux/files/home/firelab-wifi.json"
```

Check that the file updates every ~10 seconds and contains the expected fields.

### Cloudflare

```powershell
adb shell "run-as com.termux cat /data/data/com.termux/files/home/firelab-public-url.txt"
```

Open the URL and verify:

- `/` returns `200` and the login page.
- `/api/health` returns `200`.
- `/api/network` and `/api/adblock` return `401` without a session.

### Ad blocker

```sh
# On the device, resolve a known blocked domain and a control domain.
python3 - <<'PY'
import socket
for host in ("ads.example.com", "example.com"):
    try:
        print(host, socket.getaddrinfo(host, 80)[0][4][0])
    except Exception as exc:
        print(host, "FAIL", exc)
PY
```

Expected:

- A blocked domain resolves to `0.0.0.0`.
- A normal domain resolves to a real address.

Status socket:

```powershell
adb shell "curl -s http://127.0.0.1:18083/status"
```

### Boot

1. Reboot the Fire TV.
2. Wait up to three minutes.
3. Check:

```powershell
adb shell netstat -ltn | Select-String -Pattern "18081|18083|2222"
adb shell "run-as com.termux tail -n 30 /data/data/com.termux/files/home/firelab-boot.log"
```

Expected: dashboard, blocker status socket and optional SSH listener are up.

---

## 16. Operations and rollback

### Where things live

```text
$HOME/
├── .termux/
│   ├── termux.properties
│   └── boot/
│       ├── start-firelab.sh
│       ├── start-tunnel.sh
│       └── start-ssh.sh
├── firelab-test/
│   ├── proot
│   └── debian/
│       └── home/firelab/
│           ├── firelab_api.py
│           ├── firelab-auth.json
│           ├── storage/
│           └── webroot/index.html
├── firelab-wifi-collector.sh
├── firelab-wifi-client.py
├── firelab-wifi.json
├── firelab-adblock-agent.sh
├── firelab-adblock-status.py
├── firelab-adblock.json
├── firelab-public-url.txt
├── firelab-boot.log
├── firelab-tunnel.log
└── firelab-adblock.log
```

### Update files safely

1. Take a timestamped backup of the live file.
2. Push the new file to `/data/local/tmp`.
3. Copy it into place with `run-as com.termux`.
4. Fix ownership/mode.
5. Syntax-check (`sh -n`, `python -m py_compile`).
6. Restart the runner.
7. Verify `/api/health`.
8. Keep the backup until the new version is stable.

### Restart the stack

```powershell
adb shell "am broadcast --user 0 \
  -a com.firelab.wifi.START_DASHBOARD \
  -n com.firelab.wifi/.RunCommandReceiver"
```

The runner stops the old child, cleans orphans and starts a new one.

### Stop the stack

Read the PID and send SIGTERM:

```powershell
adb shell "run-as com.termux sh -c 'kill $(cat /data/data/com.termux/files/home/firelab-runner.pid)'"
```

The cleanup trap stops collector, agent and PRoot, removes the PID file and
kills an orphaned backend if needed.

### Logs

- `firelab-boot.log`: runner, PRoot and backend output
- `firelab-tunnel.log`: tunnel supervisor
- `firelab-cloudflared.log`: cloudflared output
- `firelab-adblock.log`: agent commands and errors
- `firelab-ssh.log`: SSH listener

Rotate logs at ~1 MiB. Never commit them.

### Rollback

The original installation is kept at a separate path and port. Do not modify or
delete it while experimenting. To roll back:

1. Stop the new runner.
2. Restore the backed-up `firelab_api.py`, `index.html` and boot script.
3. Start the original instance or the previous runner.
4. Verify health and login.

---

## 17. Publishing safely

This repository is ready to be published as a sanitized project. Before you
push:

1. Read [Sanitization checklist](#sanitization-checklist).
2. Run a secret scan.
3. Use the `.gitignore` provided in this repository.
4. Do not commit:
   - keystores (`*.keystore`, `*.jks`)
   - auth files (`firelab-auth.json`)
   - bot tokens (`.firelab_bot_token`)
   - tunnel URLs (`firelab-public-url.txt`)
   - logs (`*.log`)
   - PID files (`*.pid`)
   - APKs built with your private key unless you intend to distribute them
5. Create the repository:

```powershell
git init
git add .
git commit -m "Initial FireLab documentation and sanitized examples"
git branch -M main
git remote add origin https://github.com/<your-user>/<your-repo>.git
git push -u origin main
```

6. On GitHub, add a short description and topics such as:
   `fire-tv`, `termux`, `proot`, `self-hosted`, `dashboard`, `cloudflare`,
   `android`, `adblocker`.

See [docs/PUBLISHING.md](PUBLISHING.md) for a copy-paste checklist.

---

## 18. Sanitization checklist

Before publishing, confirm that none of these appear in the repository:

- [ ] Real WiFi SSID or BSSID
- [ ] Real MAC address
- [ ] Real private or public IP address
- [ ] Real router hostname or domain
- [ ] Real Cloudflare quick-tunnel URL
- [ ] Real Telegram bot token or chat ID
- [ ] Real dashboard password or password hash
- [ ] Real session cookie or CSRF token
- [ ] Device serial number
- [ ] Windows username or home directory path
- [ ] Personal email address
- [ ] Screenshots containing any of the above
- [ ] Logs containing any of the above
- [ ] Keystore files or signing passwords

Use placeholders:

```text
DEVICE_IP=192.168.1.10
DASHBOARD_PORT=18081
WIFI_NAME=<wifi-name>
WIFI_BSSID=AA:BB:CC:DD:EE:FF
PUBLIC_HOST=<random-words>.trycloudflare.com
TELEGRAM_CHAT_ID=<chat-id>
```

Public DNS servers such as `1.1.1.1` and `8.8.8.8` are fine to document. Generic
private addresses such as `192.168.1.10` are also fine; they are examples, not
your real device.

---

## 19. Appendix: key snippets

### A. WiFi client

```python
import os
import socket
import sys
import time

target, temp = sys.argv[1], sys.argv[2]
text = ""
deadline = time.time() + 10

while time.time() < deadline:
    try:
        sock = socket.create_connection(("127.0.0.1", 18082), timeout=0.3)
        sock.settimeout(5)
        chunks = []
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
        text = b"".join(chunks).decode("utf-8", "replace").strip()
        break
    except Exception:
        time.sleep(0.2)

if text.startswith("{") and text.endswith("}"):
    with open(temp, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(temp, target)
```

### B. Ad blocker status client

```python
import json
import os
import socket
import sys
import time

target, temp = sys.argv[1], sys.argv[2]
payload = None

try:
    sock = socket.create_connection(("127.0.0.1", 18083), timeout=1.0)
    sock.settimeout(2.0)
    sock.sendall(b"GET /status HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
    raw = b""
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        raw += chunk
    body = raw.split(b"\r\n\r\n", 1)[-1]
    parsed = json.loads(body.decode("utf-8", "replace"))
    if isinstance(parsed, dict):
        payload = parsed
except Exception:
    payload = None

if payload is None:
    payload = {
        "enabled": False,
        "service_running": False,
        "available": False,
    }

payload["available"] = payload.get("available", False)
payload["collected_at"] = int(time.time() * 1000)
payload["agent"] = True

with open(temp, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, separators=(",", ":"))
os.replace(temp, target)
```

### C. Ad blocker agent

```sh
#!/data/data/com.termux/files/usr/bin/sh
export PREFIX=/data/data/com.termux/files/usr
export HOME=/data/data/com.termux/files/home
export PATH=$PREFIX/bin:/system/bin
export LD_LIBRARY_PATH=$PREFIX/lib
export TMPDIR=$PREFIX/tmp

H=$HOME
CMD=$H/firelab-adblock.cmd
OUT=$H/firelab-adblock.json
TMP=$H/.firelab-adblock.json.tmp
CLIENT=$H/firelab-adblock-status.py

while true; do
    if [ -f "$CMD" ]; then
        action=$(head -n 1 "$CMD" 2>/dev/null | tr -d '\r\n ')
        rm -f "$CMD"
        case "$action" in
            start|stop|setup)
                env -u LD_LIBRARY_PATH /system/bin/am broadcast --user 0 \
                    -a com.firelab.adblock.CONTROL \
                    -n com.firelab.adblock/.ControlReceiver \
                    --es cmd "$action" >/dev/null 2>&1
                ;;
        esac
    fi
    python3 "$CLIENT" "$OUT" "$TMP" 2>/dev/null
    sleep 3
done
```

### D. DNS block response

```java
// Header
out.writeShort(transactionId);
out.writeShort(0x8180);        // QR=1, RD=1, RA=1, RCODE=0
out.writeShort(1);             // QDCOUNT
out.writeShort(type == 1 ? 1 : 0); // ANCOUNT
out.writeShort(0);             // NSCOUNT
out.writeShort(0);             // ARCOUNT

// Question
out.write(query, 12, questionEnd - 12);

// A answer: 0.0.0.0
if (type == 1) {
    out.writeShort(0xC00C);    // pointer to question name
    out.writeShort(1);         // TYPE A
    out.writeShort(1);         // CLASS IN
    out.writeInt(60);          // TTL
    out.writeShort(4);         // RDLENGTH
    out.writeInt(0);           // 0.0.0.0
}
```

### E. Tunnel URL extraction

```python
import re

match = re.search(
    r"https://[-a-z0-9]+\.trycloudflare\.com",
    log_text,
    re.IGNORECASE,
)
if match:
    public_url = match.group(0)
    public_url_file.write_text(public_url + "\n", encoding="utf-8")
```

---

## Final notes

FireLab is deliberately small and conservative:

- No root.
- No system partition changes.
- No direct internet exposure of SSH or ADB.
- Authentication at the origin, even behind Cloudflare.
- One helper APK for Android-only WiFi data.
- One optional helper APK for DNS blocking.
- Plain shell scripts and a single Python file that are easy to audit.

The most important lesson: on Fire OS, **process ownership and environment
variables matter as much as the code**. `RUN_COMMAND`, `goAsync`, `am` with a
clean `LD_LIBRARY_PATH`, and starting the socket client before the broadcast are
the difference between a demo and a stack that survives a reboot.
