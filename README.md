# Rick-mailer - Library to send emails 

[![Tests](https://github.com/oddbit-project/rick-mailer/workflows/Tests/badge.svg?branch=master)](https://github.com/oddbit-project/rick-mailer/actions)
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

## Related tools

Check out [MailHog](https://github.com/mailhog/MailHog), a mail testing tool for developers.

## License
As rick_mailer is mostly Django code, it is licensed under Django license and copyright - see the included [License file](LICENSE).
