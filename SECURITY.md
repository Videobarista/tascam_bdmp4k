# Security Policy

## Supported versions

Only the latest release of this integration receives security updates. Please update to the
newest release before reporting an issue.

| Version | Supported |
| ------- | --------- |
| 2.5.x   | Yes       |
| < 2.5   | No        |

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Report them privately through
GitHub: [Security → Report a vulnerability](https://github.com/Videobarista/tascam_bdmp4k/security/advisories/new).

You can expect an acknowledgement within 14 days. This is a hobby project maintained in spare
time, so fixes are made on a best-effort basis; credit is given in the release notes unless
you prefer otherwise.

## What the integration does

- It speaks the Tascam BD-MP4K control protocol over **plain TCP to port 9030** of the player,
  over one connection that stays open.
- With a MAC address configured, it sends a Wake-on-LAN magic packet as a UDP broadcast to
  port 9 on the local network.
- It opens **no listening ports**, makes no internet connections and has **no runtime Python
  dependencies**.
- The config entry holds only the host, port and optional MAC address. There are no
  credentials, because the player has no login.

## Safeguards in the integration

- Only the fixed commands defined in `const.py` are sent. Every command is checked before it
  goes out; anything with other characters, such as a carriage return, is refused, so no
  value from Home Assistant or a user can reach the protocol.
- Everything the player sends is treated as untrusted. Messages longer than the protocol's
  600-byte maximum are dropped, unknown codes show as *unknown*, and the receive buffer stays
  bounded whatever the device sends.
- Host, port and MAC address are validated in the config flow before any connection is made.
- Commands keep the protocol's 30 ms minimum interval. A player in standby is contacted once
  per poll, without retries, and status notifications that change nothing are ignored.
- Logs contain protocol messages and the player's address only; no MAC address is logged.

## What only your network can protect

The BD-MP4K control protocol has **no authentication and no encryption**. That is a property
of the device, not of this integration, and no integration can fix it. Anyone who can reach
port 9030 can control the player, take its single client slot (which locks Home Assistant
out), and even send commands such as a factory reset or a firmware upgrade.

Recommended network setup:

1. Put the player on an isolated IoT VLAN, never on a guest network, and never expose port
   9030 to the internet.
2. Allow TCP port 9030 to the player **only from the Home Assistant host**. This also stops
   another device from taking the player's single client slot.
3. Wake-on-LAN is a broadcast and does not cross VLANs: either keep Home Assistant on the
   player's VLAN, or allow UDP port 9 from Home Assistant into that VLAN.
4. Block internet access for the player, and set **BD-Live** to *Off* in the player's setup
   menu, unless you need online disc content.
5. If you play files from a network share, allow the player to reach only that NAS (SMB,
   TCP port 445).

## Scope

In scope: vulnerabilities in this integration's code, such as injection through device
responses, unsafe handling of config entry data, or denial of service triggered by malformed
protocol messages.

Out of scope: the lack of authentication in the Tascam control protocol itself, and issues in
Home Assistant core or HACS (report those to their own projects).
