# Tascam BD-MP4K for Home Assistant

[![Hassfest](https://github.com/Videobarista/tascam_bdmp4k/actions/workflows/hassfest.yml/badge.svg?branch=main)](https://github.com/Videobarista/tascam_bdmp4k/actions/workflows/hassfest.yml)
[![HACS validation](https://github.com/Videobarista/tascam_bdmp4k/actions/workflows/hacs.yml/badge.svg?branch=main)](https://github.com/Videobarista/tascam_bdmp4k/actions/workflows/hacs.yml)
[![CodeQL](https://github.com/Videobarista/tascam_bdmp4k/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/Videobarista/tascam_bdmp4k/actions/workflows/codeql.yml)
[![Ruff](https://github.com/Videobarista/tascam_bdmp4k/actions/workflows/ruff.yml/badge.svg?branch=main)](https://github.com/Videobarista/tascam_bdmp4k/actions/workflows/ruff.yml)
[![Tests](https://github.com/Videobarista/tascam_bdmp4k/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/Videobarista/tascam_bdmp4k/actions/workflows/tests.yml)
[![HACS custom](https://img.shields.io/badge/HACS-custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Quality scale: Bronze (aligned)](https://img.shields.io/badge/quality%20scale-bronze%20(aligned)-cd7f32.svg)](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Release](https://img.shields.io/github/v/release/Videobarista/tascam_bdmp4k?display_name=tag)](https://github.com/Videobarista/tascam_bdmp4k/releases)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Videobarista&repository=tascam_bdmp4k&category=integration)

Control a **Tascam BD-MP4K** professional Blu-ray player from Home Assistant over its
Ethernet control protocol (TCP port 9030): transport control, disc and playback status,
elapsed and remaining time, menu navigation, and power on with Wake-on-LAN.

## Entities

All entities belong to one device, **Tascam BD-MP4K**.

| Entity | Type | Description |
|---|---|---|
| Tascam BD-MP4K | Media player | Play, pause, stop, next/previous chapter, standby, and power on via Wake-on-LAN when a MAC address is set. Shows the position and the duration (elapsed + remaining time). Shows **off** when the player is in standby or unreachable. |
| Disc status | Sensor (enum) | No disc, disc present, unknown disc, tray open, tray closed, tray error. |
| Playback status | Sensor (enum) | Playing, paused, stopped, slow or search forward/reverse, and the menus. |
| Time elapsed / Time remaining | Sensor (duration, s) | Numeric, so they work in templates and statistics. Unknown when nothing plays. |
| Current chapter / Current title | Sensor | Chapter (or file) and title (or CD track) number. |
| Tray open / Tray close | Button | Disc tray. |
| Arrow up / down / left / right | Button | Move the cursor in menus. |
| Menu home, enter, return, top (disc), popup, setup | Button | Menu navigation. |
| Display info, Subtitle next | Button | On-screen info, next subtitle language. |
| Mute on / Mute off | Button | Audio mute. |
| Power off (standby) | Button | Puts the player in standby. |

Status changes pushed by the player, including ones made with its own remote control, appear
in Home Assistant straight away. Names are available in English and Dutch.

## Installation

### HACS (recommended)

Click the **Open in HACS** badge above, or
[this link](https://my.home-assistant.io/redirect/hacs_repository/?owner=Videobarista&repository=tascam_bdmp4k&category=integration),
to open this repository in HACS on your own Home Assistant instance. Download it and
restart Home Assistant.

Adding it by hand works too:

1. In HACS, open the menu (three dots) and choose **Custom repositories**.
2. Add `https://github.com/Videobarista/tascam_bdmp4k` with type **Integration**.
3. Download **Tascam BD-MP4K** and restart Home Assistant.

### Manual

1. Copy `custom_components/tascam_bdmp4k` into the `custom_components` folder of your
   Home Assistant configuration.
2. Restart Home Assistant.

## Configuration

Go to **Settings → Devices & services → Add integration** and search for
**Tascam BD-MP4K**, or use
[this link](https://my.home-assistant.io/redirect/config_flow_start/?domain=tascam_bdmp4k).

| Field | Description |
|---|---|
| Host | IP address or host name of the player. |
| Port | TCP control port. The player always uses 9030. |
| MAC address | Optional. Needed to switch the player on with Wake-on-LAN. |

The connection is tested before the entry is created. To switch the player on from Home
Assistant, also enable network standby / Wake-on-LAN in the player's own setup menu; without
it the player ignores the magic packet.

## How it works

The BD-MP4K protocol requires that the TCP connection stays open and accepts **only one
client** at a time. The integration keeps a single shared connection for all entities and
keeps the 30 ms minimum interval between commands from the specification.

Transport and disc changes are pushed by the player and processed immediately. A poll every
10 seconds is the fallback and reads the elapsed and remaining time, which the player does
not push.

## Limitations

- **Power on over Ethernet is not part of the protocol.** The specification prescribes
  Wake-on-LAN, which this integration uses when a MAC address is set.
- **Only one controller can be connected at a time.** Disconnect other control systems
  (Bitfocus Companion, Crestron and the like) while using this integration.
- The player answers `nack` to status requests that do not apply to its current mode, for
  example the remaining time while stopped. Those values show as *unknown*; that is normal.

## Troubleshooting

Enable debug logging to see every command, reply and notification:

```yaml
logger:
  default: info
  logs:
    custom_components.tascam_bdmp4k: debug
```

If the entities go unavailable now and then, the player was in standby, or another system
claimed its single client slot.

## Removal

1. Go to **Settings → Devices & services** and open **Tascam BD-MP4K**.
2. Open the menu (three dots) next to the entry and choose **Delete**.
3. To remove the files as well: in HACS, open **Tascam BD-MP4K** and choose **Remove**, or
   delete `custom_components/tascam_bdmp4k` for a manual installation. Restart Home
   Assistant afterwards.

Nothing is changed on the player itself.

## Quality scale

This integration is aligned with the **Bronze** tier of the
[Home Assistant integration quality scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/).
Home Assistant only grades integrations that ship with Home Assistant itself, so this is a
self-assessment, not an official rating. The status per rule is recorded in
[`quality_scale.yaml`](custom_components/tascam_bdmp4k/quality_scale.yaml).

## Development

The tests use
[pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)
and run on every push. To run them locally (Python 3.14):

```bash
pip install -r requirements_test.txt
pytest --cov --cov-report=term-missing
```

Code style is checked with [Ruff](https://docs.astral.sh/ruff/) (configuration in
`ruff.toml`); see [CONTRIBUTING.md](CONTRIBUTING.md).

## Security

The player's control protocol has no authentication or encryption, so anyone who can reach
port 9030 can control it. The integration only sends its own fixed commands and treats
everything the player sends as untrusted, but the real protection is the network: put the
player on an isolated VLAN and allow port 9030 only from Home Assistant. See
[SECURITY.md](SECURITY.md) for the safeguards and a recommended network setup.

## License

MIT — see [LICENSE](LICENSE).

## Disclaimer

This integration is not affiliated with or endorsed by TEAC Corporation. Tascam, TEAC and
BD-MP4K are trademarks of their respective owners. The icon and logo shown in Home
Assistant come from the [home-assistant/brands](https://github.com/home-assistant/brands)
repository; see [Brand/](Brand/README.md).
