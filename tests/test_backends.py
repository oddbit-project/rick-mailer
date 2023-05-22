import sys
from email import message_from_bytes
from email.header import Header
from email.utils import parseaddr
from io import StringIO
import socket
from smtplib import SMTPException, SMTP
from ssl import SSLError

import pytest
from aiosmtpd.controller import Controller

import rick_mailer
from rick_mailer.backends import SMTPEmailBackend
from rick_mailer.backends import registry, SMTPFactory
from rick_mailer import EmailMessage, Mailer, BadHeaderError
from tests.common import HeadersCheckMixin


class BaseBackendTest(HeadersCheckMixin):
    def setup_method(self, test_method):
        self.email_backend = None

    def teardown_method(self, test_method):
        pass

    def assertStartsWith(self, first, second):
        if not first.startswith(second):
            self.longMessage = True
            assert first[: len(second)] == second

    def get_mailbox_content(self):
        raise NotImplementedError(
            "subclasses of BaseEmailBackendTests must provide a get_mailbox_content() "
            "method"
        )

    def flush_mailbox(self):
        raise NotImplementedError(
            "subclasses of BaseEmailBackendTests may require a flush_mailbox() method"
        )

    def get_the_message(self):
        mailbox = self.get_mailbox_content()
        assert len(mailbox) == 1
        return mailbox[0]

    def test_send(self):
        email = EmailMessage(
            "Subject", "Content", "from@example.com", ["to@example.com"]
        )
        num_sent = self.email_backend.send_messages([email])
        assert num_sent == 1
        message = self.get_the_message()
        assert message["subject"] == "Subject"
        assert message.get_payload() == "Content"
        assert message["from"] == "from@example.com"
        assert message.get_all("to") == ["to@example.com"]

    def test_send_unicode(self):
        email = EmailMessage(
            "Chère maman", "Je t'aime très fort", "from@example.com", ["to@example.com"]
        )
        num_sent = self.email_backend.send_messages([email])
        assert num_sent == 1
        message = self.get_the_message()
        assert message["subject"] == "=?utf-8?q?Ch=C3=A8re_maman?="
        assert message.get_payload(decode=True).decode() == "Je t'aime très fort"

    def test_send_long_lines(self):
        """
        Email line length is limited to 998 chars by the RFC 5322 Section
        2.1.1.
        Message body containing longer lines are converted to Quoted-Printable
        to avoid having to insert newlines, which could be hairy to do properly.
        """
        # Unencoded body length is < 998 (840) but > 998 when utf-8 encoded.
        email = EmailMessage(
            "Subject", "В южных морях " * 60, "from@example.com", ["to@example.com"]
        )
        email.send(self.email_backend)
        message = self.get_the_message()
        self.assertMessageHasHeaders(
            message,
            {
                ("MIME-Version", "1.0"),
                ("Content-Type", 'text/plain; charset="utf-8"'),
                ("Content-Transfer-Encoding", "quoted-printable"),
            },
        )

    def test_send_many(self):
        email1 = EmailMessage(
            "Subject", "Content1", "from@example.com", ["to@example.com"]
        )
        email2 = EmailMessage(
            "Subject", "Content2", "from@example.com", ["to@example.com"]
        )
        # send_messages() may take a list or an iterator.
        emails_lists = ([email1, email2], iter((email1, email2)))
        for emails_list in emails_lists:
            self.flush_mailbox()
            num_sent = self.email_backend.send_messages(emails_list)
            assert num_sent == 2
            msgs = self.get_mailbox_content()
            assert len(msgs) == 2
            assert msgs[0].get_payload() == "Content1"
            assert msgs[1].get_payload() == "Content2"
            self.flush_mailbox()

    def test_send_verbose_name(self):
        email = EmailMessage(
            "Subject",
            "Content",
            '"Firstname Sürname" <from@example.com>',
            ["to@example.com"],
        )
        email.send(self.email_backend)
        message = self.get_the_message()
        assert message["subject"] == "Subject"
        assert message.get_payload() == "Content"
        assert (
            message["from"] == "=?utf-8?q?Firstname_S=C3=BCrname?= <from@example.com>"
        )

    def test_plaintext_send_mail(self):
        """
        Test send_mail without the html_message
        regression test for adding html_message parameter to send_mail()
        """
        mailer = Mailer(self.email_backend)
        mailer.send_mail(
            "Subject", "Content", "sender@example.com", ["nobody@example.com"]
        )
        message = self.get_the_message()

        assert message.get("subject") == "Subject"
        assert message.get_all("to") == ["nobody@example.com"]
        assert message.is_multipart() is False
        assert message.get_payload() == "Content"
        assert message.get_content_type() == "text/plain"

    def test_html_send_mail(self):
        """Test html_message argument to send_mail"""
        mailer = Mailer(self.email_backend)
        mailer.send_mail(
            "Subject",
            "Content",
            "sender@example.com",
            ["nobody@example.com"],
            html_message="HTML Content",
        )
        message = self.get_the_message()

        assert message.get("subject") == "Subject"
        assert message.get_all("to") == ["nobody@example.com"]
        assert message.is_multipart() is True
        assert len(message.get_payload()) == 2
        assert message.get_payload(0).get_payload() == "Content"
        assert message.get_payload(0).get_content_type() == "text/plain"
        assert message.get_payload(1).get_payload() == "HTML Content"
        assert message.get_payload(1).get_content_type() == "text/html"

    def test_message_cc_header(self):
        """
        Regression test for #7722
        """
        email = EmailMessage(
            "Subject",
            "Content",
            "from@example.com",
            ["to@example.com"],
            cc=["cc@example.com"],
        )
        self.email_backend.send_messages([email])
        message = self.get_the_message()
        self.assertMessageHasHeaders(
            message,
            {
                ("MIME-Version", "1.0"),
                ("Content-Type", 'text/plain; charset="utf-8"'),
                ("Content-Transfer-Encoding", "7bit"),
                ("Subject", "Subject"),
                ("From", "from@example.com"),
                ("To", "to@example.com"),
                ("Cc", "cc@example.com"),
            },
        )
        assert message.as_string().find("\nDate: ") != -1

    def test_idn_send(self):
        """
        Regression test for #14301
        """
        mailer = Mailer(self.email_backend)
        assert (
            mailer.send_mail("Subject", "Content", "from@öäü.com", ["to@öäü.com"]) == 1
        )
        message = self.get_the_message()
        assert message.get("subject") == "Subject"
        assert message.get("from") == "from@xn--4ca9at.com"
        assert message.get("to") == "to@xn--4ca9at.com"

        self.flush_mailbox()
        m = EmailMessage(
            "Subject", "Content", "from@öäü.com", ["to@öäü.com"], cc=["cc@öäü.com"]
        )
        num_sent = self.email_backend.send_messages([m])
        assert num_sent == 1
        message = self.get_the_message()
        assert message.get("subject") == "Subject"
        assert message.get("from") == "from@xn--4ca9at.com"
        assert message.get("to") == "to@xn--4ca9at.com"
        assert message.get("cc") == "cc@xn--4ca9at.com"

    def test_recipient_without_domain(self):
        """
        Regression test for #15042
        """
        mailer = Mailer(self.email_backend)
        assert mailer.send_mail("Subject", "Content", "tester", ["django"]) == 1
        message = self.get_the_message()
        assert message.get("subject") == "Subject"
        assert message.get("from") == "tester"
        assert message.get("to") == "django"

    def test_close_connection(self):
        """
        Connection can be closed (even when not explicitly opened)
        """
        conn = self.email_backend
        conn.close()

    def test_use_as_contextmanager(self):
        """
        The connection can be used as a contextmanager.
        """
        opened = [False]
        closed = [False]
        conn = self.email_backend

        def open():
            opened[0] = True

        conn.open = open

        def close():
            closed[0] = True

        conn.close = close
        with conn as same_conn:
            assert opened[0] is True
            assert same_conn == conn
            assert closed[0] is False
        assert closed[0] is True


class TestMemBackend(BaseBackendTest):
    email_backend = None

    def setup_method(self, test_method):
        self.email_backend = registry.get("mem")()

    def teardown_method(self, test_method):
        self.flush_mailbox()

    def get_mailbox_content(self):
        return [m.message() for m in rick_mailer.outbox]

    def flush_mailbox(self):
        rick_mailer.outbox = []

    def test_locmem_shared_messages(self):
        """
        Make sure that the locmen backend populates the outbox.
        """
        connection = registry.get("mem")()
        connection2 = registry.get("mem")()
        email = EmailMessage(
            "Subject",
            "Content",
            "bounce@example.com",
            ["to@example.com"],
            headers={"From": "from@example.com"},
        )
        connection.send_messages([email])
        connection2.send_messages([email])
        assert len(rick_mailer.outbox) == 2

    def test_validate_multiline_headers(self):
        # Ticket #18861 - Validate emails when using the locmem backend
        mailer = Mailer(self.email_backend)
        with pytest.raises(BadHeaderError):
            mailer.send_mail(
                "Subject\nMultiline", "Content", "from@example.com", ["to@example.com"]
            )


class TestConsoleBackend(BaseBackendTest):
    def setup_method(self, test_method):
        self.__stdout = sys.stdout
        self.stream = sys.stdout = StringIO()
        self.email_backend = registry.get("console")()

    def teardown_method(self, test_method):
        sys.stdout = self.__stdout
        del self.__stdout
        self.flush_mailbox()

    def flush_mailbox(self):
        self.stream.truncate(0)
        self.stream.seek(0)

    def get_mailbox_content(self):
        messages = self.stream.getvalue().split("\n" + ("-" * 79) + "\n")
        result = []
        for m in messages:
            if len(m) > 0:
                result.append(message_from_bytes(m.encode()))
        return result

    def test_console_stream_kwarg(self):
        """
        The console backend can be pointed at an arbitrary stream.
        """
        s = StringIO()
        mailer = Mailer(registry.get("console")(stream=s))
        mailer.send_mail("Subject", "Content", "from@example.com", ["to@example.com"])
        message = s.getvalue().split("\n" + ("-" * 79) + "\n")[0].encode()
        self.assertMessageHasHeaders(
            message,
            {
                ("MIME-Version", "1.0"),
                ("Content-Type", 'text/plain; charset="utf-8"'),
                ("Content-Transfer-Encoding", "7bit"),
                ("Subject", "Subject"),
                ("From", "from@example.com"),
                ("To", "to@example.com"),
            },
        )
        assert message.find(b"\nDate: ") != -1


class SMTPHandler:
    def __init__(self, *args, **kwargs):
        self.mailbox = []

    async def handle_DATA(self, server, session, envelope):
        data = envelope.content
        mail_from = envelope.mail_from

        message = message_from_bytes(data.rstrip())
        message_addr = parseaddr(message.get("from"))[1]
        if mail_from != message_addr:
            # According to the spec, mail_from does not necessarily match the
            # From header - this is the case where the local part isn't
            # encoded, so try to correct that.
            lp, domain = mail_from.split("@", 1)
            lp = Header(lp, "utf-8").encode()
            mail_from = "@".join([lp, domain])

        if mail_from != message_addr:
            return f"553 '{mail_from}' != '{message_addr}'"
        self.mailbox.append(message)
        return "250 OK"

    def flush_mailbox(self):
        self.mailbox[:] = []


class BaseSMTPBackendTest(BaseBackendTest):
    def setup_method(self, test_method):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self.smtp_handler = SMTPHandler()
        self.smtp_controller = Controller(
            self.smtp_handler,
            hostname="127.0.0.1",
            port=port,
        )
        self.config = {"smtp_host": "127.0.0.1", "smtp_port": port}
        self.smtp_controller.start()

    def teardown_method(self, test_method):
        self.smtp_controller.stop()


class TestSMTPBackend(BaseSMTPBackendTest):
    def setup_method(self, test_method):
        super().setup_method(test_method)
        self.smtp_handler.flush_mailbox()
        self.email_backend = SMTPFactory(self.config)

    def teardown_method(self, test_method):
        self.smtp_handler.flush_mailbox()
        super().teardown_method(test_method)

    def flush_mailbox(self):
        self.smtp_handler.flush_mailbox()

    def get_mailbox_content(self):
        return self.smtp_handler.mailbox

    def test_email_authentication_use_settings(self):
        cfg = self.config
        cfg["smtp_username"] = "not empty username"
        cfg["smtp_password"] = "not empty password"

        backend = SMTPFactory(cfg)
        assert backend.username == "not empty username"
        assert backend.password == "not empty password"

    def test_email_disabled_authentication(self):
        backend = SMTPFactory(self.config)
        assert backend.username == ""
        assert backend.password == ""

    def test_auth_attempted(self):
        """
        Opening the backend with non empty username/password tries
        to authenticate against the SMTP server.
        """
        cfg = self.config
        cfg["smtp_username"] = "not empty username"
        cfg["smtp_password"] = "not empty password"
        backend = SMTPFactory(cfg)
        with pytest.raises(SMTPException):
            with backend:
                pass

    def test_server_open(self):
        """
        open() returns whether it opened a connection.
        """
        backend = SMTPFactory(self.config)
        assert backend.connection is None
        assert backend.open() is True
        backend.close()

    def test_reopen_connection(self):
        backend = SMTPFactory(self.config)
        # Simulate an already open connection.
        backend.connection = True
        assert backend.open() is False

    def test_email_tls_use_settings(self):
        cfg = self.config
        cfg["smtp_use_tls"] = True
        backend = SMTPFactory(cfg)
        assert backend.use_tls is True

    def test_email_tls_override_settings(self):
        cfg = self.config
        cfg["smtp_use_tls"] = False
        backend = SMTPFactory(cfg)
        assert backend.use_tls is False

    def test_email_tls_default_disabled(self):
        backend = SMTPFactory(self.config)
        assert backend.use_tls is False

    def test_ssl_tls_mutually_exclusive(self):
        with pytest.raises(ValueError):
            cfg = self.config
            cfg["smtp_use_ssl"] = True
            cfg["smtp_use_tls"] = True
            backend = SMTPFactory(cfg)

    def test_email_ssl_use_settings(self):
        cfg = self.config
        cfg["smtp_use_ssl"] = True
        backend = SMTPFactory(cfg)
        assert backend.use_ssl is True

    def test_email_ssl_override_settings(self):
        cfg = self.config
        cfg["smtp_use_ssl"] = False
        backend = SMTPFactory(cfg)
        assert backend.use_ssl is False

    def test_email_ssl_default_disabled(self):
        backend = SMTPFactory(self.config)
        assert backend.use_ssl is False

    def test_email_ssl_certfile_use_settings(self):
        cfg = self.config
        cfg["smtp_ssl_certfile"] = "foo"
        backend = SMTPFactory(cfg)
        assert backend.ssl_certfile == "foo"

    def test_email_ssl_certfile_default_disabled(self):
        backend = SMTPFactory(self.config)
        assert backend.ssl_certfile is None

    def test_email_ssl_keyfile_use_settings(self):
        cfg = self.config
        cfg["smtp_ssl_keyfile"] = "foo"
        backend = SMTPFactory(cfg)
        assert backend.ssl_keyfile == "foo"

    def test_email_ssl_keyfile_default_disabled(self):
        backend = SMTPFactory(self.config)
        assert backend.ssl_keyfile is None

    def test_email_tls_attempts_starttls(self):
        cfg = self.config
        cfg["smtp_use_tls"] = True
        backend = SMTPFactory(cfg)
        assert backend.use_tls is True
        with pytest.raises(SMTPException):
            with backend:
                pass

    def test_email_ssl_attempts_ssl_connection(self):
        cfg = self.config
        cfg["smtp_use_ssl"] = True
        backend = SMTPFactory(cfg)
        assert backend.use_ssl is True
        with pytest.raises(SSLError):
            with backend:
                pass

    def test_connection_timeout_default(self):
        backend = SMTPFactory(self.config)
        assert backend.timeout is None

    def test_connection_timeout_custom(self):
        """The timeout parameter can be customized."""
        cfg = self.config
        cfg["smtp_timeout"] = 42
        backend = SMTPFactory(cfg)
        assert backend.timeout == 42

    def test_email_msg_uses_crlf(self):
        """#23063 -- RFC-compliant messages are sent over SMTP."""
        send = SMTP.send
        try:
            smtp_messages = []

            def mock_send(self, s):
                smtp_messages.append(s)
                return send(self, s)

            SMTP.send = mock_send

            email = EmailMessage(
                "Subject", "Content", "from@example.com", ["to@example.com"]
            )
            SMTPFactory(self.config).send_messages([email])

            # Find the actual message
            msg = None
            for i, m in enumerate(smtp_messages):
                if m[:4] == "data":
                    msg = smtp_messages[i + 1]
                    break

            assert len(msg) > 0

            msg = msg.decode()
            # The message only contains CRLF and not combinations of CRLF, LF, and CR.
            msg = msg.replace("\r\n", "")
            assert msg.find("\r") == -1
            assert msg.find("\n") == -1

        finally:
            SMTP.send = send

    def test_send_messages_after_open_failed(self):
        """
        send_messages() shouldn't try to send messages if open() raises an
        exception after initializing the connection.
        """
        backend = SMTPEmailBackend()

        # Simulate connection initialization success and a subsequent
        # connection exception.
        backend.connection = object()
        backend.open = lambda: None
        email = EmailMessage(
            "Subject", "Content", "from@example.com", ["to@example.com"]
        )
        assert backend.send_messages([email]) == 0

    def test_send_messages_empty_list(self):
        backend = SMTPEmailBackend()
        backend.connection = object()
        assert backend.send_messages([]) == 0

    def test_send_messages_zero_sent(self):
        """A message isn't sent if it doesn't have any recipients."""
        backend = SMTPEmailBackend()
        backend.connection = object
        email = EmailMessage("Subject", "Content", "from@example.com", to=[])
        sent = backend.send_messages([email])
        assert sent == 0
