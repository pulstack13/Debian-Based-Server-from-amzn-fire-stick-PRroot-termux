# Publishing checklist

Use this before you push a fork of FireLab to GitHub. Every item is a real
mistake that is easy to make when the project grew on a live device.

## 1. Confirm the export folder contains only documentation

Expected layout:

```text
README.md
LICENSE
.gitignore
docs/
  FIRELAB_GITHUB.md
  PUBLISHING.md
examples/
  firelab-adblock-agent.sh
  firelab-adblock-status.py
  firelab-wifi-client.py
  wifi-collector.sh
```

There should be **no** APK, keystore, auth file, log, token, tunnel URL file or
PID file in the folder.

```powershell
Get-ChildItem . -Recurse -File |
  Where-Object { $_.Extension -in ".apk", ".jks", ".keystore", ".log", ".pid" }
```

The command must return nothing.

## 2. Scan for personal values

Replace the placeholders with the values that exist on your own device and run
the scan from the repository root. Any match means the value must be removed or
replaced before publishing.

```powershell
$needles = @(
  "YOUR_WIFI_NAME",
  "YOUR_BSSID",
  "YOUR_MAC",
  "YOUR_LAN_IP",
  "YOUR_PUBLIC_TUNNEL_HOST",
  "YOUR_TELEGRAM_CHAT_ID",
  "YOUR_KEYSTORE_PASSWORD",
  "C:\Users\YOUR_WINDOWS_USER"
)

Get-ChildItem . -Recurse -File |
  Where-Object { $_.FullName -notmatch "\\\.git\\" } |
  Select-String -SimpleMatch -Pattern $needles |
  Select-Object Path, LineNumber, Line
```

Also check for:

- `trycloudflare.com` links that are not obviously placeholders
- long random strings that look like bot tokens (`123456789:AA...`)
- IPv4 addresses other than documented examples such as `192.168.1.10`
- email addresses, device serials and Amazon account names

## 3. Check the documented examples

The documentation intentionally contains these public values:

- `1.1.1.1` and `8.8.8.8` — public DNS resolvers
- `10.111.222.1` and `10.111.222.2` — private addresses used by the example VPN
- `192.168.1.10` — a generic LAN example, not a real device
- `127.0.0.1` — loopback
- `AA:BB:CC:DD:EE:FF` — an obvious placeholder MAC

Anything else should be reviewed.

## 4. Initialize the repository

```powershell
cd github-export
git init
git add .
git status
```

Read the `git status` output before committing. If a file you did not expect
appears, stop and remove it.

```powershell
git commit -m "FireLab: non-rooted Fire TV dashboard, WiFi helper and DNS ad blocker"
git branch -M main
```

## 5. Create the remote and push

### Option A — GitHub CLI

```powershell
gh auth login
gh repo create firelab --public --source . --remote origin --push
```

### Option B — GitHub website + git

Create an empty public repository on GitHub, then:

```powershell
git remote add origin https://github.com/YOUR_USER/firelab.git
git push -u origin main
```

If Git asks for a password, use a personal access token with `repo` scope, not
your account password. Never paste the token into a file in the repository.

## 6. After pushing

- Add a repository description: "Self-hosted dashboard, WiFi helper and DNS ad
  blocker for a non-rooted Fire TV Stick".
- Add topics: `fire-tv`, `termux`, `proot`, `self-hosted`, `dashboard`,
  `cloudflare`, `android`, `adblocker`.
- Open the rendered README and the documentation on GitHub and check that no
  personal value is visible.
- If a secret was ever committed, rotate it immediately. Deleting the commit is
  not enough because the value stays in the Git history and in forks.

## 7. What not to publish

| Item | Why |
|---|---|
| `firelab-auth.json` | Contains the password hash and salt |
| Bot token or chat ID | Allows sending messages as your bot |
| `firelab-public-url.txt` | Reveals the live tunnel hostname |
| APKs signed with your key | Lets others distribute builds that look like yours |
| Keystore or its password | Allows signing updates as you |
| Logs | Contain IPs, SSIDs, tokens and command lines |
| Screenshots of the dashboard | Often include the tunnel URL or WiFi name |
