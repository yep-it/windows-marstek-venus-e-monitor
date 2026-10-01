"""Notification and system events (stored in the Events tab and delivered to channels)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Event:
    ts: float
    kind: str                 # "notification" | "system"
    rule_id: str
    priority: str             # "normal" | "critical"
    title_key: str
    body_key: str
    params: dict = field(default_factory=dict)
    desktop: str = "off"      # off | pending | sent | held | failed
    telegram: str = "off"     # off | pending | sent | retrying | held | failed
    id: int | None = None
