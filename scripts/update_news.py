#!/usr/bin/env python3
"""Aggregate updates from multiple AI news sites and produce 24h snapshot data."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.radar import wire_modules as _wire_modules
from scripts.radar import common as _common
from scripts.radar import config_runtime as _config_runtime
from scripts.radar import pipeline as _pipeline
from scripts.radar import cli as _cli
from scripts.radar.fetchers import agentmail as _agentmail
from scripts.radar.fetchers import bilibili as _bilibili
from scripts.radar.fetchers import mediacrawler as _mediacrawler
from scripts.radar.fetchers import paid as _paid
from scripts.radar.fetchers import public as _public
from scripts.radar.fetchers import subscriptions as _subscriptions
from scripts.radar.fetchers import waytoagi as _waytoagi

_UPDATE_NEWS_MODULES = [
    _common,
    _waytoagi,
    _public,
    _subscriptions,
    _pipeline,
    _config_runtime,
    _agentmail,
    _bilibili,
    _mediacrawler,
    _paid,
    _cli,
]
_wire_modules(_UPDATE_NEWS_MODULES)

from scripts.radar.common import *  # noqa: F401,F403,E402
from scripts.radar.fetchers.waytoagi import *  # noqa: F401,F403,E402
from scripts.radar.fetchers.public import *  # noqa: F401,F403,E402
from scripts.radar.fetchers.subscriptions import *  # noqa: F401,F403,E402
from scripts.radar.pipeline import *  # noqa: F401,F403,E402
from scripts.radar.config_runtime import *  # noqa: F401,F403,E402
from scripts.radar.fetchers.agentmail import *  # noqa: F401,F403,E402
from scripts.radar.fetchers.bilibili import *  # noqa: F401,F403,E402
from scripts.radar.fetchers.mediacrawler import *  # noqa: F401,F403,E402
from scripts.radar.fetchers.paid import *  # noqa: F401,F403,E402
from scripts.radar.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
