from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    api_key: str | None
    host: str
    port: int
    transport: str
    log_level: str
    allowed_hosts: list[str] = field(default_factory=list)


def load_config() -> Config:
    raw_hosts = os.getenv("SANDBOX_ALLOWED_HOSTS", "")
    allowed_hosts = [h.strip() for h in raw_hosts.split(",") if h.strip()]
    return Config(
        api_key=os.getenv("SANDBOX_API_KEY") or None,
        host=os.getenv("SANDBOX_HOST", "127.0.0.1"),
        port=int(os.getenv("SANDBOX_PORT", "8765")),
        transport=os.getenv("SANDBOX_TRANSPORT", "stdio"),
        log_level=os.getenv("SANDBOX_LOG_LEVEL", "INFO"),
        allowed_hosts=allowed_hosts,
    )
