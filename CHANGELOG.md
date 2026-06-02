# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.1.2]

### Fixed
- `force_str()` returned `None` for every non-`str` input (a missing `return`), breaking `bytes`
  `message/rfc822` attachments and non-`str` address handling.
- `sanitize_address()` now raises a clear `ValueError` for a tuple address with no `@` instead of an
  opaque unpacking error.
- `EmailMessage.message()` omits the `From` header when no sender is set instead of emitting a
  literal `"None"` `From` header.
- Removed duplicate `"Mailer"` entry from `__all__`.
- Declared the `rick` dependency in `Pipfile`.

### Changed
- Publish workflow now builds with `python -m build` (wheel + sdist) and uses PyPI OIDC trusted
  publishing instead of the deprecated `setup.py sdist` and a stored API token.

### Documentation
- Added a security note about enabling TLS (`smtp_use_tls`/`smtp_use_ssl`) when sending SMTP
  credentials, which otherwise travel in cleartext.
