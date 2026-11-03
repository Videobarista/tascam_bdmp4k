# Contributing

Issues and pull requests are welcome. This is a hobby project, so responses may take a while.

## Reporting problems

Include the integration version, your Home Assistant version, and debug logs. Enable debug
logging by adding this to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.tascam_bdmp4k: debug
```

The protocol layer logs every command, reply and pushed notification at debug level, which
is usually enough to diagnose an issue.

## Checks

Every push and pull request runs Ruff, the tests, hassfest, HACS validation and CodeQL.
To run Ruff and the tests locally (Python 3.14):

```bash
pip install ruff==0.16.8 -r requirements_test.txt
ruff check .
ruff format --check .
pytest --cov --cov-report=term-missing
```

Ruff is configured in `ruff.toml`, in line with Home Assistant core style, and includes the
Bandit security rules (`S`). The tests use
[pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component);
the protocol tests talk to a fake player on 127.0.0.1, so no hardware is needed.

## Protocol documentation

The TEAC "BD-MP4K RS-232C/ETHERNET Protocol Specification" v1.01 is the authoritative
source. It is copyrighted by TEAC Corporation and is therefore not included in this
repository; it is available from TEAC/Tascam support.

## Adding commands

Commands and status requests live in `const.py`, named as in the specification. Entity
behaviour lives in `media_player.py`, `sensor.py` and `button.py`. The connection itself is
handled entirely in `protocol.py` and should not be duplicated elsewhere: the player accepts
only one client at a time.
