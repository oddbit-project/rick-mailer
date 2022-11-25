RICK_MAILER_VERSION = ["0", "9", "0"]


def get_version():
    return ".".join(RICK_MAILER_VERSION)


__version__ = get_version()
