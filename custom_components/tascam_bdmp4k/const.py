"""Constants for the Tascam BD-MP4K integration."""

from __future__ import annotations

DOMAIN = "tascam_bdmp4k"

DEFAULT_PORT = 9030
DEFAULT_NAME = "Tascam BD-MP4K"
DEFAULT_SCAN_INTERVAL = 10

MANUFACTURER = "Tascam (TEAC Corporation)"
MODEL = "BD-MP4K"

# Key control commands (spec 5.1).
CMD_PLAY = "!7PLY"
CMD_PAUSE = "!7PAS"
CMD_STOP = "!7STP"
CMD_SKIP_NEXT = "!7SKPNX"
CMD_SKIP_PREV = "!7SKPPV"
CMD_GROUP_NEXT = "!7GSKNX"
CMD_GROUP_PREV = "!7GSKPV"
CMD_POWER_ON = "!7PWR01"  # RS-232C only; invalid over Ethernet (use WoL).
CMD_POWER_OFF = "!7PWR00"
CMD_TRAY_OPEN = "!7OPCOP"
CMD_TRAY_CLOSE = "!7OPCCL"
CMD_HOME = "!7HOM"
CMD_ENTER = "!7ENT"
CMD_RETURN = "!7RET"
CMD_TOP_MENU = "!7TMN"
CMD_SETUP_MENU = "!7SMN"
CMD_POPUP_MENU = "!7PMN"
CMD_OPTION_MENU = "!7OMN"
CMD_DISPLAY = "!7DSP"
CMD_SUBTITLE = "!7SBT1"
CMD_AUDIO_NEXT = "!7ADG+"
CMD_MUTE_ON = "!7MUT00"
CMD_MUTE_OFF = "!7MUT01"

# Status requests (spec 5.3).
REQ_POWER = "!7?PWR"
REQ_DISC = "!7?MST"
REQ_STATUS = "!7?SST"
REQ_ELAPSED = "!7?SET"
REQ_REMAIN = "!7?SRT"
REQ_TOTAL_CHAPTER = "!7?STT"
REQ_CURRENT_CHAPTER = "!7?STC"
REQ_TOTAL_TITLE = "!7?STG"
REQ_CURRENT_TITLE = "!7?SGN"

DISC_STATUS_MAP = {
    "NC": "no_disc",
    "CI": "disc_present",
    "UF": "unformatted",
    "TO": "tray_open",
    "TC": "tray_closed",
    "TE": "tray_error",
}

PLAYBACK_STATUS_MAP = {
    "PL": "playing",
    "ST": "stopped",
    "PP": "paused",
    "DVSR": "slow_reverse",
    "DVSF": "slow_forward",
    "DVFR": "search_reverse",
    "DVFF": "search_forward",
    "DVSU": "setup",
    "DVMC": "media_center",
    "DVTR": "track_menu",
    "DVHM": "home_menu",
}
