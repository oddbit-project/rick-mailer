# Rick-mailer - Library to send emails 

[![CI](https://github.com/oddbit-project/rick-mailer/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/oddbit-project/rick-mailer/actions/workflows/ci.yml)
[![pypi](https://img.shields.io/pypi/v/rick-mailer.svg)](https://pypi.org/project/rick-mailer/)
[![license](https://img.shields.io/pypi/l/rick-mailer.svg)](https://github.com/oddbit-project/rick-mailer/blob/master/LICENSE)


rick_mailer is a standalone version of Django's email library implementation, with minor changes.

## Installation

```shell
$ pip3 install rick-mailer
```

## Usage

```python
from rick_mailer import SMTPFactory, Mailer

cfg = {
    'smtp_host': '127.0.0.1',
    'smtp_port': 25,
    'smtp_username': 'relay@local',
    'smtp_password': 'securePassword',
    'smtp_use_tls': False,
    'smtp_use_ssl': False,
}
conn = SMTPFactory(cfg)

mailer = Mailer(conn)
mailer.send_mail('some subject', 'message contents', 'noreply@localhost', ['user1@domain.tld', 'user2@domain.tld'])
```

### Configuration options

`SMTPFactory(cfg)` reads the following keys from `cfg`:

| Key | Default | Description |
| --- | --- | --- |
| `smtp_host` | `'localhost'` | SMTP server hostname. |
| `smtp_port` | `25` | SMTP server port. |
| `smtp_username` | `''` | Username for authentication (empty disables login). |
| `smtp_password` | `''` | Password for authentication. |
| `smtp_use_tls` | `False` | Use STARTTLS on a plain connection. |
| `smtp_use_ssl` | `False` | Use an implicit TLS (SSL) connection. Mutually exclusive with `smtp_use_tls`. |
| `smtp_timeout` | `None` | Socket timeout in seconds. |
| `smtp_ssl_keyfile` | `None` | Path to a client-side private key (PEM). |
| `smtp_ssl_certfile` | `None` | Path to a client-side certificate (PEM); required when `smtp_ssl_keyfile` is set. |

> **Security note:** `smtp_use_tls` and `smtp_use_ssl` default to `False`. When sending credentials
> (`smtp_username`/`smtp_password`), enable one of them (`smtp_use_tls=True` for STARTTLS, or
> `smtp_use_ssl=True` for an implicit TLS connection) so the password is not transmitted in cleartext.

## Related tools

Check out [Mailpit](https://github.com/axllent/mailpit), a mail testing tool for developers.

## License
As rick_mailer is mostly Django code, it is licensed under Django license and copyright - see the included [License file](LICENSE).
