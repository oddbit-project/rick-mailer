"""
Backend for test environment.
"""

import rick_mailer as mail
from .base import BaseEmailBackend, registry


@registry.register("mem")
class MemEmailBackend(BaseEmailBackend):
    """
    An email backend for use during test sessions.

    The test connection stores email messages in a dummy outbox,
    rather than sending them out on the wire.

    The dummy outbox is accessible through the outbox instance attribute.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not hasattr(mail, "outbox"):
            mail.outbox = []

    def send_messages(self, email_messages):
        """Redirect messages to the dummy outbox"""
        msg_count = 0
        for message in email_messages:  # .message() triggers header validation
            message.message()
            mail.outbox.append(message)
            msg_count += 1
        return msg_count
