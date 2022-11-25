from rick.util.misc import optional

from .base import BaseEmailBackend, registry
from .console import ConsoleEmailBackend
from .smtp import SMTPEmailBackend
from .locmem import MemEmailBackend


def SMTPFactory(cfg: dict, fail_silently=False) -> SMTPEmailBackend:
    cls = registry.get("smtp")
    return cls(
        host=optional("smtp_host", cfg, "localhost"),
        port=optional("smtp_port", cfg, 25),
        username=optional("smtp_username", cfg, ""),
        password=optional("smtp_password", cfg, ""),
        use_tls=optional("smtp_use_tls", cfg, False),
        fail_silently=fail_silently,
        use_ssl=optional("smtp_use_ssl", cfg, False),
        timeout=optional("smtp_timeout", cfg, None),
        ssl_keyfile=optional("smtp_ssl_keyfile", cfg),
        ssl_certfile=optional("smtp_ssl_certfile", cfg),
    )
