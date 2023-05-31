from .base import BaseEmailBackend, registry
from .console import ConsoleEmailBackend
from .smtp import SMTPEmailBackend
from .locmem import MemEmailBackend


def SMTPFactory(cfg: dict, fail_silently=False) -> SMTPEmailBackend:
    cls = registry.get("smtp")
    return cls(
        host=cfg.get("smtp_host", "localhost"),
        port=cfg.get("smtp_port", 25),
        username=cfg.get("smtp_username", ""),
        password=cfg.get("smtp_password", ""),
        use_tls=cfg.get("smtp_use_tls", False),
        fail_silently=fail_silently,
        use_ssl=cfg.get("smtp_use_ssl", False),
        timeout=cfg.get("smtp_timeout", None),
        ssl_keyfile=cfg.get("smtp_ssl_keyfile"),
        ssl_certfile=cfg.get("smtp_ssl_certfile"),
    )
