# FireLab

A self-hosted control center running on a **non-rooted Amazon Fire TV Stick**
using **Termux + PRoot Debian**. No root, no custom ROM, no system modification.

FireLab started as a small Python dashboard and grew into a practical home-server
stack for a low-power Android TV device:

- Authenticated dashboard with sessions, CSRF protection and login throttling
- Live system monitoring and a file manager
- A **Network** tab with WiFi link, addressing, DNS and traffic details
- A rootless **DNS ad blocker** built on Android `VpnService`
- Optional Cloudflare quick tunnel for remote HTTPS access
- Auto-start and restart loop through Termux:Boot

## Documentation

The full build and operations write-up is here:

- [docs/FIRELAB_GITHUB.md](docs/FIRELAB_GITHUB.md) — architecture, build steps,
  helper APKs, boot loop, Cloudflare tunnel, ad blocker, problems and fixes
- [docs/PUBLISHING.md](docs/PUBLISHING.md) — safe GitHub publishing checklist
- [examples/](examples/) — sanitized collector, client and agent scripts

## Architecture at a glance

```text
Fire TV Stick (Fire OS, non-rooted)
│
├── Termux (Android app)
│   ├── Termux:Boot ──> start-firelab.sh
│   │                    ├── WiFi collector  ──> helper APK (localhost socket)
│   │                    ├── ad blocker agent ──> blocker APK (localhost socket)
│   │                    ├── Cloudflare tunnel supervisor
│   │                    └── PRoot Debian 12
│   │                         └── Python dashboard on 127.0.0.1:18081
│   │
│   ├── helper APK  ── WiFiManager data + Termux RUN_COMMAND launcher
│   └── blocker APK ── VpnService DNS sinkhole
│
└── Remote access: Cloudflare quick tunnel ──> dashboard only
```

## Tested environment

- Amazon Fire TV Stick, Fire OS 5.1.1 (Android API 22, `armeabi-v7a`)
- Termux and Termux:Boot installed from the same source/signature
- Debian 12 rootfs under PRoot
- Python 3.11 inside the guest
- No root, no Magisk, no custom recovery

Newer Fire OS versions may work, but background restrictions and VPN behavior can
differ. Treat the versions above as the reference environment.

## Security notice

This project exposes an authenticated dashboard, not an anonymous file server.
If you publish your own fork:

- Never commit passwords, bot tokens, tunnel URLs, WiFi names, MAC addresses,
  public IPs or device serials.
- Never forward ADB `5555` or SSH `2222` to the internet.
- Expose only the dashboard, preferably through Cloudflare with authentication
  still enabled at the origin.
- Use a strong dashboard password and keep the auth file out of Git.

## License

The documentation and original scripts in this repository are released under the
MIT License. The optional blocklist is derived from
[StevenBlack/hosts](https://github.com/StevenBlack/hosts); keep its attribution
and license when redistributing it.
