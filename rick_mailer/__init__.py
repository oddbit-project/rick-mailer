"""
Tools for sending email.
"""
from rick_mailer.backends import SMTPFactory, BaseEmailBackend

from .message import (
    DEFAULT_ATTACHMENT_MIME_TYPE,
    BadHeaderError,
    EmailMessage,
    EmailMultiAlternatives,
    SafeMIMEMultipart,
    SafeMIMEText,
    forbid_multi_line_headers,
    make_msgid,
)
from .utils import DNS_NAME, CachedDnsName

__all__ = [
    "CachedDnsName",
    "DNS_NAME",
    "EmailMessage",
    "EmailMultiAlternatives",
    "SafeMIMEText",
    "SafeMIMEMultipart",
    "DEFAULT_ATTACHMENT_MIME_TYPE",
    "make_msgid",
    "BadHeaderError",
    "forbid_multi_line_headers",
    "Mailer",
    "SMTPFactory",
    "Mailer",
]


class Mailer:
    def __init__(self, backend: BaseEmailBackend):
        self.backend = backend

    def send_mail(
        self, subject, message, from_email, recipient_list, html_message=None
    ):
        """
        Easy wrapper for sending a single message to a recipient list. All members
        of the recipient list will see the other recipients in the 'To' field.

        If from_email is None, use the DEFAULT_FROM_EMAIL setting.
        If auth_user is None, use the EMAIL_HOST_USER setting.
        If auth_password is None, use the EMAIL_HOST_PASSWORD setting.

        Note: The API for this method is frozen. New code wanting to extend the
        functionality should use the EmailMessage class directly.
        """
        mail = EmailMultiAlternatives(
            subject, message, from_email, recipient_list, connection=self.backend
        )
        if html_message:
            mail.attach_alternative(html_message, "text/html")

        return mail.send()

    def send_mass_mail(self, datatuple):
        """
        Given a datatuple of (subject, message, from_email, recipient_list), send
        each message to each recipient list. Return the number of emails sent.
        """
        messages = [
            EmailMessage(subject, message, sender, recipient, connection=self.backend)
            for subject, message, sender, recipient in datatuple
        ]
        return self.backend.send_messages(messages)
