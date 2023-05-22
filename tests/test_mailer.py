import mimetypes
import os
import shutil
import socket
import sys
import tempfile
from email import charset, message_from_binary_file, message_from_bytes
from email.header import Header
from email.mime.text import MIMEText
from email.utils import parseaddr
from io import StringIO
from pathlib import Path
from smtplib import SMTP, SMTPException
from ssl import SSLError
from unittest import mock, skipUnless

import pytest
import rick_mailer as mail
from rick_mailer.backends import SMTPEmailBackend, ConsoleEmailBackend, MemEmailBackend
from rick_mailer.message import sanitize_address
from rick_mailer.backends import registry
from rick_mailer import (
    DNS_NAME,
    EmailMessage,
    EmailMultiAlternatives,
    BadHeaderError,
)
from .custombackend import EmailBackend
from .common import HeadersCheckMixin


class TestMail(HeadersCheckMixin):
    """
    Non-backend specific tests.
    """

    def get_decoded_attachments(self, django_message):
        """
        Encode the specified django.core.mail.message.EmailMessage, then decode
        it using Python's email.parser module and, for each attachment of the
        message, return a list of tuples with (filename, content, mimetype).
        """
        msg_bytes = django_message.message().as_bytes()
        email_message = message_from_bytes(msg_bytes)

        def iter_attachments():
            for i in email_message.walk():
                if i.get_content_disposition() == "attachment":
                    filename = i.get_filename()
                    content = i.get_payload(decode=True)
                    mimetype = i.get_content_type()
                    yield filename, content, mimetype

        return list(iter_attachments())

    def test_ascii(self):
        email = EmailMessage(
            "Subject", "Content", "from@example.com", ["to@example.com"]
        )
        message = email.message()
        assert message["Subject"] == "Subject"
        assert message.get_payload() == "Content"
        assert message["From"] == "from@example.com"
        assert message["To"] == "to@example.com"

    def test_multiple_recipients(self):
        email = EmailMessage(
            "Subject",
            "Content",
            "from@example.com",
            ["to@example.com", "other@example.com"],
        )
        message = email.message()
        assert message["Subject"] == "Subject"
        assert message.get_payload() == "Content"
        assert message["From"] == "from@example.com"
        assert message["To"] == "to@example.com, other@example.com"

    def test_header_omitted_for_no_to_recipients(self):
        message = EmailMessage(
            "Subject", "Content", "from@example.com", cc=["cc@example.com"]
        ).message()
        assert str(message).find("To") == -1

    def test_recipients_with_empty_strings(self):
        """
        Empty strings in various recipient arguments are always stripped
        off the final recipient list.
        """
        email = EmailMessage(
            "Subject",
            "Content",
            "from@example.com",
            ["to@example.com", ""],
            cc=["cc@example.com", ""],
            bcc=["", "bcc@example.com"],
            reply_to=["", None],
        )
        assert email.recipients() == [
            "to@example.com",
            "cc@example.com",
            "bcc@example.com",
        ]

    def test_cc(self):
        """Regression test for #7722"""
        email = EmailMessage(
            "Subject",
            "Content",
            "from@example.com",
            ["to@example.com"],
            cc=["cc@example.com"],
        )
        message = email.message()
        assert message["Cc"] == "cc@example.com"
        assert email.recipients() == ["to@example.com", "cc@example.com"]

        # Test multiple CC with multiple To
        email = EmailMessage(
            "Subject",
            "Content",
            "from@example.com",
            ["to@example.com", "other@example.com"],
            cc=["cc@example.com", "cc.other@example.com"],
        )
        message = email.message()
        assert message["Cc"] == "cc@example.com, cc.other@example.com"
        assert email.recipients() == [
            "to@example.com",
            "other@example.com",
            "cc@example.com",
            "cc.other@example.com",
        ]

        # Testing with Bcc
        email = EmailMessage(
            "Subject",
            "Content",
            "from@example.com",
            ["to@example.com", "other@example.com"],
            cc=["cc@example.com", "cc.other@example.com"],
            bcc=["bcc@example.com"],
        )
        message = email.message()
        assert message["Cc"] == "cc@example.com, cc.other@example.com"
        assert email.recipients() == [
            "to@example.com",
            "other@example.com",
            "cc@example.com",
            "cc.other@example.com",
            "bcc@example.com",
        ]

    def test_cc_headers(self):
        message = EmailMessage(
            "Subject",
            "Content",
            "bounce@example.com",
            ["to@example.com"],
            cc=["foo@example.com"],
            headers={"Cc": "override@example.com"},
        ).message()
        assert message["Cc"] == "override@example.com"

    def test_cc_in_headers_only(self):
        message = EmailMessage(
            "Subject",
            "Content",
            "bounce@example.com",
            ["to@example.com"],
            headers={"Cc": "foo@example.com"},
        ).message()
        assert message["Cc"] == "foo@example.com"

    def test_reply_to(self):
        email = EmailMessage(
            "Subject",
            "Content",
            "from@example.com",
            ["to@example.com"],
            reply_to=["reply_to@example.com"],
        )
        message = email.message()
        assert message["Reply-To"] == "reply_to@example.com"

        email = EmailMessage(
            "Subject",
            "Content",
            "from@example.com",
            ["to@example.com"],
            reply_to=["reply_to1@example.com", "reply_to2@example.com"],
        )
        message = email.message()
        assert message["Reply-To"] == "reply_to1@example.com, reply_to2@example.com"

    def test_recipients_as_tuple(self):
        email = EmailMessage(
            "Subject",
            "Content",
            "from@example.com",
            ("to@example.com", "other@example.com"),
            cc=("cc@example.com", "cc.other@example.com"),
            bcc=("bcc@example.com",),
        )
        message = email.message()
        assert message["Cc"] == "cc@example.com, cc.other@example.com"
        assert email.recipients() == [
            "to@example.com",
            "other@example.com",
            "cc@example.com",
            "cc.other@example.com",
            "bcc@example.com",
        ]

    def test_recipients_as_string(self):
        with pytest.raises((TypeError)):
            EmailMessage(to="foo@example.com")
        with pytest.raises((TypeError)):
            EmailMessage(cc="foo@example.com")
        with pytest.raises((TypeError)):
            EmailMessage(bcc="foo@example.com")
        with pytest.raises((TypeError)):
            EmailMessage(reply_to="reply_to@example.com")

    def test_header_injection(self):
        msg = "Header values can't contain newlines "
        email = EmailMessage(
            "Subject\nInjection Test", "Content", "from@example.com", ["to@example.com"]
        )
        with pytest.raises(BadHeaderError):
            email.message()

        email = EmailMessage(
            "Subject\nInjection Test",
            "Content",
            "from@example.com",
            ["to@example.com"],
        )
        with pytest.raises(BadHeaderError):
            email.message()
        with pytest.raises(BadHeaderError):
            EmailMessage(
                "Subject",
                "Content",
                "from@example.com",
                ["Name\nInjection test <to@example.com>"],
            ).message()

    def test_space_continuation(self):
        """
        Test for space continuation character in long (ASCII) subject headers (#7747)
        """
        email = EmailMessage(
            "Long subject lines that get wrapped should contain a space continuation "
            "character to get expected behavior in Outlook and Thunderbird",
            "Content",
            "from@example.com",
            ["to@example.com"],
        )
        message = email.message()
        assert (
            message["Subject"].encode()
            == b"Long subject lines that get wrapped should contain a space continuation\n character to get expected behavior in Outlook and Thunderbird"
        )

    def test_message_header_overrides(self):
        """
        Specifying dates or message-ids in the extra headers overrides the
        default values (#9233)
        """
        headers = {"date": "Fri, 09 Nov 2001 01:08:47 -0000", "Message-ID": "foo"}
        email = EmailMessage(
            "subject",
            "content",
            "from@example.com",
            ["to@example.com"],
            headers=headers,
        )

        self.assertMessageHasHeaders(
            email.message(),
            {
                ("Content-Transfer-Encoding", "7bit"),
                ("Content-Type", 'text/plain; charset="utf-8"'),
                ("From", "from@example.com"),
                ("MIME-Version", "1.0"),
                ("Message-ID", "foo"),
                ("Subject", "subject"),
                ("To", "to@example.com"),
                ("date", "Fri, 09 Nov 2001 01:08:47 -0000"),
            },
        )

    def test_from_header(self):
        """
        Make sure we can manually set the From header (#9214)
        """
        email = EmailMessage(
            "Subject",
            "Content",
            "bounce@example.com",
            ["to@example.com"],
            headers={"From": "from@example.com"},
        )
        message = email.message()
        assert message["From"] == "from@example.com"

    def test_to_header(self):
        """
        Make sure we can manually set the To header (#17444)
        """
        email = EmailMessage(
            "Subject",
            "Content",
            "bounce@example.com",
            ["list-subscriber@example.com", "list-subscriber2@example.com"],
            headers={"To": "mailing-list@example.com"},
        )
        message = email.message()
        assert message["To"] == "mailing-list@example.com"
        assert email.to == [
            "list-subscriber@example.com",
            "list-subscriber2@example.com",
        ]

        # If we don't set the To header manually, it should default to the `to`
        # argument to the constructor.
        email = EmailMessage(
            "Subject",
            "Content",
            "bounce@example.com",
            ["list-subscriber@example.com", "list-subscriber2@example.com"],
        )
        message = email.message()

        assert (
            message["To"] == "list-subscriber@example.com, list-subscriber2@example.com"
        )
        assert email.to == [
            "list-subscriber@example.com",
            "list-subscriber2@example.com",
        ]

    def test_to_in_headers_only(self):
        message = EmailMessage(
            "Subject",
            "Content",
            "bounce@example.com",
            headers={"To": "to@example.com"},
        ).message()
        assert message["To"] == "to@example.com"

    def test_reply_to_header(self):
        """
        Specifying 'Reply-To' in headers should override reply_to.
        """
        email = EmailMessage(
            "Subject",
            "Content",
            "bounce@example.com",
            ["to@example.com"],
            reply_to=["foo@example.com"],
            headers={"Reply-To": "override@example.com"},
        )
        message = email.message()
        assert message["Reply-To"] == "override@example.com"

    def test_reply_to_in_headers_only(self):
        message = EmailMessage(
            "Subject",
            "Content",
            "from@example.com",
            ["to@example.com"],
            headers={"Reply-To": "reply_to@example.com"},
        ).message()
        assert message["Reply-To"] == "reply_to@example.com"

    def test_multiple_message_call(self):
        """
        Regression for #13259 - Make sure that headers are not changed when
        calling EmailMessage.message()
        """
        email = EmailMessage(
            "Subject",
            "Content",
            "bounce@example.com",
            ["to@example.com"],
            headers={"From": "from@example.com"},
        )
        message = email.message()
        assert message["From"] == "from@example.com"
        message = email.message()
        assert message["From"] == "from@example.com"

    def test_unicode_address_header(self):
        """
        Regression for #11144 - When a to/from/cc header contains Unicode,
        make sure the email addresses are parsed correctly (especially with
        regards to commas)
        """
        email = EmailMessage(
            "Subject",
            "Content",
            "from@example.com",
            ['"Firstname Sürname" <to@example.com>', "other@example.com"],
        )
        assert (
            email.message()["To"]
            == "=?utf-8?q?Firstname_S=C3=BCrname?= <to@example.com>, other@example.com"
        )

        email = EmailMessage(
            "Subject",
            "Content",
            "from@example.com",
            ['"Sürname, Firstname" <to@example.com>', "other@example.com"],
        )
        assert (
            email.message()["To"]
            == "=?utf-8?q?S=C3=BCrname=2C_Firstname?= <to@example.com>, other@example.com"
        )

    def test_unicode_headers(self):
        email = EmailMessage(
            "Gżegżółka",
            "Content",
            "from@example.com",
            ["to@example.com"],
            headers={
                "Sender": '"Firstname Sürname" <sender@example.com>',
                "Comments": "My Sürname is non-ASCII",
            },
        )
        message = email.message()
        assert message["Subject"] == "=?utf-8?b?R8W8ZWfFvMOzxYJrYQ==?="
        assert (
            message["Sender"]
            == "=?utf-8?q?Firstname_S=C3=BCrname?= <sender@example.com>"
        )
        assert message["Comments"] == "=?utf-8?q?My_S=C3=BCrname_is_non-ASCII?="

    def test_safe_mime_multipart(self):
        """
        Make sure headers can be set with a different encoding than utf-8 in
        SafeMIMEMultipart as well
        """
        headers = {"Date": "Fri, 09 Nov 2001 01:08:47 -0000", "Message-ID": "foo"}
        from_email, to = "from@example.com", '"Sürname, Firstname" <to@example.com>'
        text_content = "This is an important message."
        html_content = "<p>This is an <strong>important</strong> message.</p>"
        msg = EmailMultiAlternatives(
            "Message from Firstname Sürname",
            text_content,
            from_email,
            [to],
            headers=headers,
        )
        msg.attach_alternative(html_content, "text/html")
        msg.encoding = "iso-8859-1"
        assert (
            msg.message()["To"]
            == "=?iso-8859-1?q?S=FCrname=2C_Firstname?= <to@example.com>"
        )
        assert (
            msg.message()["Subject"]
            == "=?iso-8859-1?q?Message_from_Firstname_S=FCrname?="
        )

    def test_safe_mime_multipart_with_attachments(self):
        """
        EmailMultiAlternatives includes alternatives if the body is empty and
        it has attachments.
        """
        msg = EmailMultiAlternatives(body="")
        html_content = "<p>This is <strong>html</strong></p>"
        msg.attach_alternative(html_content, "text/html")
        msg.attach("example.txt", "Text file content", "text/plain")
        assert msg.message().as_string().find(html_content) > -1

    def test_none_body(self):
        msg = EmailMessage("subject", None, "from@example.com", ["to@example.com"])
        assert msg.body == ""
        assert msg.message().get_payload() == ""

    @mock.patch("socket.getfqdn", return_value="漢字")
    def test_non_ascii_dns_non_unicode_email(self, mocked_getfqdn):
        delattr(DNS_NAME, "_fqdn")
        email = EmailMessage(
            "subject", "content", "from@example.com", ["to@example.com"]
        )
        email.encoding = "iso-8859-1"
        assert email.message()["Message-ID"].find("@xn--p8s937b>") > -1

    def test_encoding(self):
        """
        Regression for #12791 - Encode body correctly with other encodings
        than utf-8
        """
        email = EmailMessage(
            "Subject",
            "Firstname Sürname is a great guy.",
            "from@example.com",
            ["other@example.com"],
        )
        email.encoding = "iso-8859-1"
        message = email.message()
        self.assertMessageHasHeaders(
            message,
            {
                ("MIME-Version", "1.0"),
                ("Content-Type", 'text/plain; charset="iso-8859-1"'),
                ("Content-Transfer-Encoding", "quoted-printable"),
                ("Subject", "Subject"),
                ("From", "from@example.com"),
                ("To", "other@example.com"),
            },
        )
        assert message.get_payload() == "Firstname S=FCrname is a great guy."

        # MIME attachments works correctly with other encodings than utf-8.
        text_content = "Firstname Sürname is a great guy."
        html_content = "<p>Firstname Sürname is a <strong>great</strong> guy.</p>"
        msg = EmailMultiAlternatives(
            "Subject", text_content, "from@example.com", ["to@example.com"]
        )
        msg.encoding = "iso-8859-1"
        msg.attach_alternative(html_content, "text/html")
        payload0 = msg.message().get_payload(0)
        self.assertMessageHasHeaders(
            payload0,
            {
                ("MIME-Version", "1.0"),
                ("Content-Type", 'text/plain; charset="iso-8859-1"'),
                ("Content-Transfer-Encoding", "quoted-printable"),
            },
        )
        assert (
            payload0.as_bytes().endswith(b"\n\nFirstname S=FCrname is a great guy.")
            is True
        )

        payload1 = msg.message().get_payload(1)
        self.assertMessageHasHeaders(
            payload1,
            {
                ("MIME-Version", "1.0"),
                ("Content-Type", 'text/html; charset="iso-8859-1"'),
                ("Content-Transfer-Encoding", "quoted-printable"),
            },
        )
        assert (
            payload1.as_bytes().endswith(
                b"\n\n<p>Firstname S=FCrname is a <strong>great</strong> guy.</p>"
            )
            is True
        )

    def test_attachments(self):
        """Regression test for #9367"""
        headers = {"Date": "Fri, 09 Nov 2001 01:08:47 -0000", "Message-ID": "foo"}
        subject, from_email, to = "hello", "from@example.com", "to@example.com"
        text_content = "This is an important message."
        html_content = "<p>This is an <strong>important</strong> message.</p>"
        msg = EmailMultiAlternatives(
            subject, text_content, from_email, [to], headers=headers
        )
        msg.attach_alternative(html_content, "text/html")
        msg.attach("an attachment.pdf", b"%PDF-1.4.%...", mimetype="application/pdf")
        msg_bytes = msg.message().as_bytes()
        message = message_from_bytes(msg_bytes)
        assert message.is_multipart() is True
        assert message.get_content_type() == "multipart/mixed"
        assert message.get_default_type() == "text/plain"
        payload = message.get_payload()
        assert payload[0].get_content_type() == "multipart/alternative"
        assert payload[1].get_content_type() == "application/pdf"

    def test_attachments_two_tuple(self):
        msg = EmailMessage(attachments=[("filename1", "content1")])
        filename, content, mimetype = self.get_decoded_attachments(msg)[0]
        assert filename == "filename1"
        assert content == b"content1"
        assert mimetype == "application/octet-stream"

    def test_attachments_MIMEText(self):
        txt = MIMEText("content1")
        msg = EmailMessage(attachments=[txt])
        payload = msg.message().get_payload()
        assert payload[0] == txt

    def test_non_ascii_attachment_filename(self):
        """Regression test for #14964"""
        headers = {"Date": "Fri, 09 Nov 2001 01:08:47 -0000", "Message-ID": "foo"}
        subject, from_email, to = "hello", "from@example.com", "to@example.com"
        content = "This is the message."
        msg = EmailMessage(subject, content, from_email, [to], headers=headers)
        # Unicode in file name
        msg.attach("une pièce jointe.pdf", b"%PDF-1.4.%...", mimetype="application/pdf")
        msg_bytes = msg.message().as_bytes()
        message = message_from_bytes(msg_bytes)
        payload = message.get_payload()
        assert payload[1].get_filename() == "une pièce jointe.pdf"

    def test_attach_file(self):
        """
        Test attaching a file against different mimetypes and make sure that
        a file will be attached and sent properly even if an invalid mimetype
        is specified.
        """
        files = (
            # filename, actual mimetype
            ("file.txt", "text/plain"),
            ("file.png", "image/png"),
            ("file_txt", None),
            ("file_png", None),
            ("file_txt.png", "image/png"),
            ("file_png.txt", "text/plain"),
            ("file.eml", "message/rfc822"),
        )
        test_mimetypes = ["text/plain", "image/png", None]

        connection = registry.get("testing")()
        for basename, real_mimetype in files:
            for mimetype in test_mimetypes:
                email = EmailMessage(
                    "subject", "body", "from@example.com", ["to@example.com"]
                )
                assert mimetypes.guess_type(basename)[0] == real_mimetype
                assert email.attachments == []
                file_path = os.path.join(
                    os.path.dirname(__file__), "attachments", basename
                )
                email.attach_file(file_path, mimetype=mimetype)
                assert len(email.attachments) == 1
                assert email.attachments[0][0].find(basename) > -1
                msgs_sent_num = email.send(connection)
                assert msgs_sent_num == 1

    def test_attach_text_as_bytes(self):
        connection = registry.get("testing")()
        msg = EmailMessage("subject", "body", "from@example.com", ["to@example.com"])
        msg.attach("file.txt", b"file content")
        sent_num = msg.send(connection)
        assert sent_num == 1
        filename, content, mimetype = self.get_decoded_attachments(msg)[0]
        assert filename == "file.txt"
        assert content == b"file content"
        assert mimetype == "text/plain"

    def test_attach_utf8_text_as_bytes(self):
        """
        Non-ASCII characters encoded as valid UTF-8 are correctly transported
        and decoded.
        """
        msg = EmailMessage("subject", "body", "from@example.com", ["to@example.com"])
        msg.attach("file.txt", b"\xc3\xa4")  # UTF-8 encoded a umlaut.
        filename, content, mimetype = self.get_decoded_attachments(msg)[0]
        assert filename == "file.txt"
        assert content == b"\xc3\xa4"
        assert mimetype == "text/plain"

    def test_attach_non_utf8_text_as_bytes(self):
        """
        Binary data that can't be decoded as UTF-8 overrides the MIME type
        instead of decoding the data.
        """
        msg = EmailMessage("subject", "body", "from@example.com", ["to@example.com"])
        msg.attach("file.txt", b"\xff")  # Invalid UTF-8.
        filename, content, mimetype = self.get_decoded_attachments(msg)[0]
        assert filename == "file.txt"
        # Content should be passed through unmodified.
        assert content == b"\xff"
        assert mimetype == "application/octet-stream"

    def test_attach_mimetext_content_mimetype(self):
        email_msg = EmailMessage()
        txt = MIMEText("content")
        msg = (
            "content and mimetype must not be given when a MIMEBase instance "
            "is provided."
        )
        with pytest.raises(ValueError):
            email_msg.attach(txt, content="content")
        with pytest.raises(ValueError):
            email_msg.attach(txt, mimetype="text/plain")

    def test_attach_content_none(self):
        email_msg = EmailMessage()
        msg = "content must be provided."
        with pytest.raises(ValueError):
            email_msg.attach("file.txt", mimetype="application/pdf")

    def test_arbitrary_keyword(self):
        """
        Make sure that get_connection() accepts arbitrary keyword that might be
        used with custom backends.
        """
        c = registry.get("testing")(fail_silently=True, foo="bar")
        assert c.fail_silently is True

    def test_custom_backend(self):
        """Test custom backend defined in this suite."""
        conn = registry.get("testing")()
        assert hasattr(conn, "test_outbox") is True
        email = EmailMessage(
            "Subject",
            "Content",
            "bounce@example.com",
            ["to@example.com"],
            headers={"From": "from@example.com"},
        )
        conn.send_messages([email])
        assert len(conn.test_outbox) == 1

    def test_backend_arg(self):
        """Test backend argument of mail.get_connection()"""
        assert isinstance(registry.get("smtp")(), SMTPEmailBackend) is True
        assert isinstance(registry.get("mem")(), MemEmailBackend) is True
        assert isinstance(registry.get("console")(), ConsoleEmailBackend) is True

    def test_connection_arg(self):
        """Test connection argument to send_mail(), et. al."""
        # Send using non-default connection
        connection = registry.get("testing")()
        mailer = mail.Mailer(connection)
        mailer.send_mail("Subject", "Content", "from@example.com", ["to@example.com"])
        assert len(connection.test_outbox) == 1
        assert connection.test_outbox[0].subject == "Subject"

        connection.test_outbox = []
        mailer.send_mass_mail(
            [
                ("Subject1", "Content1", "from1@example.com", ["to1@example.com"]),
                ("Subject2", "Content2", "from2@example.com", ["to2@example.com"]),
            ]
        )
        assert len(connection.test_outbox) == 2
        assert connection.test_outbox[0].subject == "Subject1"
        assert connection.test_outbox[1].subject == "Subject2"

    def test_dont_mangle_from_in_body(self):
        # Regression for #13433 - Make sure that EmailMessage doesn't mangle
        # 'From ' in message body.
        email = EmailMessage(
            "Subject",
            "From the future",
            "bounce@example.com",
            ["to@example.com"],
            headers={"From": "from@example.com"},
        )
        assert email.message().as_bytes().find(b">From the future") == -1

    def test_dont_base64_encode(self):
        # Ticket #3472
        # Shouldn't use Base64 encoding at all
        msg = EmailMessage(
            "Subject",
            "UTF-8 encoded body",
            "bounce@example.com",
            ["to@example.com"],
            headers={"From": "from@example.com"},
        )
        assert msg.message().as_bytes().find(b"Content-Transfer-Encoding: 7bit") != -1

        # Ticket #11212
        # Shouldn't use quoted printable, should detect it can represent
        # content with 7 bit data.
        msg = EmailMessage(
            "Subject",
            "Body with only ASCII characters.",
            "bounce@example.com",
            ["to@example.com"],
            headers={"From": "from@example.com"},
        )
        s = msg.message().as_bytes()
        assert s.find(b"Content-Transfer-Encoding: 7bit") != -1

        # Shouldn't use quoted printable, should detect it can represent
        # content with 8 bit data.
        msg = EmailMessage(
            "Subject",
            "Body with latin characters: àáä.",
            "bounce@example.com",
            ["to@example.com"],
            headers={"From": "from@example.com"},
        )
        s = msg.message().as_bytes()
        assert s.find(b"Content-Transfer-Encoding: 8bit") != -1
        s = msg.message().as_string()
        assert s.find("Content-Transfer-Encoding: 8bit") != -1

        msg = EmailMessage(
            "Subject",
            "Body with non latin characters: А Б В Г Д Е Ж Ѕ З И І К Л М Н О П.",
            "bounce@example.com",
            ["to@example.com"],
            headers={"From": "from@example.com"},
        )
        s = msg.message().as_bytes()
        assert s.find(b"Content-Transfer-Encoding: 8bit") != -1
        s = msg.message().as_string()
        assert s.find("Content-Transfer-Encoding: 8bit") != -1

    def test_dont_base64_encode_message_rfc822(self):
        # Ticket #18967
        # Shouldn't use base64 encoding for a child EmailMessage attachment.
        # Create a child message first
        child_msg = EmailMessage(
            "Child Subject",
            "Some body of child message",
            "bounce@example.com",
            ["to@example.com"],
            headers={"From": "from@example.com"},
        )
        child_s = child_msg.message().as_string()

        # Now create a parent
        parent_msg = EmailMessage(
            "Parent Subject",
            "Some parent body",
            "bounce@example.com",
            ["to@example.com"],
            headers={"From": "from@example.com"},
        )

        # Attach to parent as a string
        parent_msg.attach(content=child_s, mimetype="message/rfc822")
        parent_s = parent_msg.message().as_string()

        # The child message header is not base64 encoded
        assert parent_s.find("Child Subject") != -1

        # Feature test: try attaching email.Message object directly to the mail.
        parent_msg = EmailMessage(
            "Parent Subject",
            "Some parent body",
            "bounce@example.com",
            ["to@example.com"],
            headers={"From": "from@example.com"},
        )
        parent_msg.attach(content=child_msg.message(), mimetype="message/rfc822")
        parent_s = parent_msg.message().as_string()

        # The child message header is not base64 encoded
        assert parent_s.find("Child Subject") != -1

        # Feature test: try attaching Django's EmailMessage object directly to the mail.
        parent_msg = EmailMessage(
            "Parent Subject",
            "Some parent body",
            "bounce@example.com",
            ["to@example.com"],
            headers={"From": "from@example.com"},
        )
        parent_msg.attach(content=child_msg, mimetype="message/rfc822")
        parent_s = parent_msg.message().as_string()

        # The child message header is not base64 encoded
        assert parent_s.find("Child Subject") != -1

    def test_custom_utf8_encoding(self):
        """A UTF-8 charset with a custom body encoding is respected."""
        body = "Body with latin characters: àáä."
        msg = EmailMessage("Subject", body, "bounce@example.com", ["to@example.com"])
        encoding = charset.Charset("utf-8")
        encoding.body_encoding = charset.QP
        msg.encoding = encoding
        message = msg.message()
        self.assertMessageHasHeaders(
            message,
            {
                ("MIME-Version", "1.0"),
                ("Content-Type", 'text/plain; charset="utf-8"'),
                ("Content-Transfer-Encoding", "quoted-printable"),
            },
        )
        assert message.get_payload() == encoding.body_encode(body)

    def test_sanitize_address(self):
        """Email addresses are properly sanitized."""
        for email_address, encoding, expected_result in (
            # ASCII addresses.
            ("to@example.com", "ascii", "to@example.com"),
            ("to@example.com", "utf-8", "to@example.com"),
            (("A name", "to@example.com"), "ascii", "A name <to@example.com>"),
            (
                ("A name", "to@example.com"),
                "utf-8",
                "A name <to@example.com>",
            ),
            ("localpartonly", "ascii", "localpartonly"),
            # ASCII addresses with display names.
            ("A name <to@example.com>", "ascii", "A name <to@example.com>"),
            ("A name <to@example.com>", "utf-8", "A name <to@example.com>"),
            ('"A name" <to@example.com>', "ascii", "A name <to@example.com>"),
            ('"A name" <to@example.com>', "utf-8", "A name <to@example.com>"),
            # Unicode addresses (supported per RFC-6532).
            ("tó@example.com", "utf-8", "=?utf-8?b?dMOz?=@example.com"),
            ("to@éxample.com", "utf-8", "to@xn--xample-9ua.com"),
            (
                ("Tó Example", "tó@example.com"),
                "utf-8",
                "=?utf-8?q?T=C3=B3_Example?= <=?utf-8?b?dMOz?=@example.com>",
            ),
            # Unicode addresses with display names.
            (
                "Tó Example <tó@example.com>",
                "utf-8",
                "=?utf-8?q?T=C3=B3_Example?= <=?utf-8?b?dMOz?=@example.com>",
            ),
            (
                "To Example <to@éxample.com>",
                "ascii",
                "To Example <to@xn--xample-9ua.com>",
            ),
            (
                "To Example <to@éxample.com>",
                "utf-8",
                "To Example <to@xn--xample-9ua.com>",
            ),
            # Addresses with two @ signs.
            ('"to@other.com"@example.com', "utf-8", r'"to@other.com"@example.com'),
            (
                '"to@other.com" <to@example.com>',
                "utf-8",
                '"to@other.com" <to@example.com>',
            ),
            (
                ("To Example", "to@other.com@example.com"),
                "utf-8",
                'To Example <"to@other.com"@example.com>',
            ),
            # Addresses with long unicode display names.
            (
                "Tó Example very long" * 4 + " <to@example.com>",
                "utf-8",
                "=?utf-8?q?T=C3=B3_Example_very_longT=C3=B3_Example_very_longT"
                "=C3=B3_Example_?=\n"
                " =?utf-8?q?very_longT=C3=B3_Example_very_long?= "
                "<to@example.com>",
            ),
            (
                ("Tó Example very long" * 4, "to@example.com"),
                "utf-8",
                "=?utf-8?q?T=C3=B3_Example_very_longT=C3=B3_Example_very_longT"
                "=C3=B3_Example_?=\n"
                " =?utf-8?q?very_longT=C3=B3_Example_very_long?= "
                "<to@example.com>",
            ),
            # Address with long display name and unicode domain.
            (
                ("To Example very long" * 4, "to@exampl€.com"),
                "utf-8",
                "To Example very longTo Example very longTo Example very longT"
                "o Example very\n"
                " long <to@xn--exampl-nc1c.com>",
            ),
        ):
            assert sanitize_address(email_address, encoding) == expected_result

    def test_sanitize_address_invalid(self):
        for email_address in (
            # Invalid address with two @ signs.
            "to@other.com@example.com",
            # Invalid address without the quotes.
            "to@other.com <to@example.com>",
            # Other invalid addresses.
            "@",
            "to@",
            "@example.com",
        ):
            with pytest.raises(ValueError):
                sanitize_address(email_address, encoding="utf-8")

    def test_sanitize_address_header_injection(self):
        msg = "Invalid address; address parts cannot contain newlines."
        tests = [
            "Name\nInjection <to@example.com>",
            ("Name\nInjection", "to@xample.com"),
            "Name <to\ninjection@example.com>",
            ("Name", "to\ninjection@example.com"),
        ]
        for email_address in tests:
            with pytest.raises(ValueError):
                sanitize_address(email_address, encoding="utf-8")

    def test_email_multi_alternatives_content_mimetype_none(self):
        email_msg = EmailMultiAlternatives()
        msg = "Both content and mimetype must be provided."
        with pytest.raises(ValueError):
            email_msg.attach_alternative(None, "text/html")
        with pytest.raises(ValueError):
            email_msg.attach_alternative("<p>content</p>", None)


class TestMailTimeZone:
    def test_date_header_utc(self):
        """
        Datetime should be in UTC.
        """
        email = EmailMessage(
            "Subject", "Body", "bounce@example.com", ["to@example.com"]
        )
        assert email.message()["Date"].endswith("-0000") is True


class TestPythonGlobalState:
    """
    Tests for #12422 -- Django smarts (#2472/#11212) with charset of utf-8 text
    parts shouldn't pollute global email Python package charset registry when
    django.mail.message is imported.
    """

    def test_utf8(self):
        txt = MIMEText("UTF-8 encoded body", "plain", "utf-8")
        assert txt.as_string().find("Content-Transfer-Encoding: base64") != -1

    def test_7bit(self):
        txt = MIMEText("Body with only ASCII characters.", "plain", "utf-8")
        assert txt.as_string().find("Content-Transfer-Encoding: base64") != -1

    def test_8bit_latin(self):
        txt = MIMEText("Body with latin characters: àáä.", "plain", "utf-8")
        assert txt.as_string().find("Content-Transfer-Encoding: base64") != -1

    def test_8bit_non_latin(self):
        txt = MIMEText(
            "Body with non latin characters: А Б В Г Д Е Ж Ѕ З И І К Л М Н О П.",
            "plain",
            "utf-8",
        )
        assert txt.as_string().find("Content-Transfer-Encoding: base64") != -1
