# Changelog

## 2.6.1

- Fixed: status notifications were acknowledged too late for the player, which waits only
  30 ms, so it sent every notification twice and sometimes refused the next request;
  notifications are now acknowledged within about 10 ms and the ack keeps the 30 ms gap
- Fixed: right after a play or pause change the status could show unknown until the next
  poll; a status request the player does not answer now keeps the last known value
- Fixed: current chapter and title could stay unknown, because the player sends them as
  TNxxxx and GNMXxxxx instead of the documented TNMxxxx and GNMxxxx; both forms are read
  now, and chapter and title notifications update the sensors straight away
- Added: disc status "Loading disc", which the player reports while it loads a disc

## 2.6.0

- Added arrow buttons (up, down, left, right) to move the cursor in the player's menus

## 2.5.0

Security hardening, and a fresh start of the repository under Videobarista.

- Every command is checked before it is sent: only well-formed BD-MP4K commands from
  `const.py` can go out, so no carriage return or other value can reach the player
- Messages from the player longer than the protocol's 600-byte maximum are dropped; the
  receive buffer stays bounded whatever the device sends
- Fixed: a complete message longer than 16 characters that ended a network read was lost
- The player's busy reply (`@0BDERBUSY`) is recognised and the command is resent once,
  instead of being treated as a lost connection
- A player in standby is contacted once per poll without retries, instead of up to four
  connection attempts; it is still picked up at the next poll once it is switched on
- Status notifications that change nothing no longer cause state writes
- The config flow refuses a host with spaces or slashes (such as `http://`) and a port
  outside 1-65535 before connecting, instead of failing with an unexpected error
- `SECURITY.md` describes the safeguards and a recommended network setup
- Ruff now also runs the Bandit security rules; workflow actions are pinned to commit SHAs
  and checkout no longer keeps credentials
- Repository, links, code owner and copyright moved to Videobarista

## 2.4.0

- Aligned with the Bronze tier of the Home Assistant integration quality scale; the status
  per rule is recorded in `quality_scale.yaml`
- Added tests for the config flow, setup, polling, push notifications, the entities and the
  protocol client, plus a Tests workflow and badge
- The config flow explains each field, re-fills the form after an error, ignores an empty
  MAC address, and reports unexpected errors instead of failing silently
- The HACS brands check is enabled again: the icon and logo come from the
  home-assistant/brands repository
- Fixed: a message split across two network reads could be lost, which caused a missed reply
  and a retry; a status notification running straight into a reply is now told apart too
- The media position now carries the time it was read from the player
- Closing the connection now waits for the reader task to stop
- Moved the Ruff configuration to `ruff.toml` (line length 100) and reformatted the code
- README: entity table, configuration fields, removal instructions and a quality scale section

## 2.3.1

- Added the My Home Assistant "Open in HACS" badge, so the repository can
  be added to HACS with one click
- Added a My Home Assistant link for starting the config flow
- Pinned the workflow status badges to the main branch

## 2.3.0

- Renamed entities so that Home Assistant's alphabetical ordering groups
  them logically: tray controls, menu controls, mute and the time
  sensors now sit together
- Added manual trigger (workflow_dispatch) to the CodeQL workflow

## 2.2.1

- Reformatted the integration code so it passes `ruff format --check`
- Pinned the Ruff version in CI and `pyproject.toml` so a future Ruff
  release cannot break the check unexpectedly
- Updated `actions/checkout` to v5

## 2.2.0

- Added hassfest, HACS, CodeQL and Ruff validation workflows
- Added `SECURITY.md` with a security policy and threat model
- Added Dependabot for monthly GitHub Actions updates
- Added issue template and contributing guide
- Added `Brand/` folder describing how logos are handled
- Added entity icons (`icons.json`) and translated sensor states in
  English and Dutch
- Removed runtime assertions and silent exception handling from the
  protocol layer; all failure paths are now logged
- Corrected `iot_class` to `local_push`

## 2.1.2

- Commands that fail to connect are retried once after a short delay
- Commands sent while the player is off are logged at debug level

## 2.1.1

- Fixed a tokenizer issue where an `ack` arriving in the same TCP read
  as a status notification could be swallowed

## 2.1.0

- Added power on via Wake-on-LAN (optional MAC address)
- Switched to push-based updates with a persistent listener task

## 2.0.3

- Fixed a crash on unknown disc/playback status codes
- Media player reports "off" instead of "unavailable" when powered off

## 2.0.2

- Reconnect and retry once before marking the device unavailable
- Status notifications are acknowledged as the specification requires

## 2.0.1

- Switched license from GPL-3.0 to MIT

## 2.0.0

- Complete rewrite around a single persistent connection and a
  DataUpdateCoordinator
