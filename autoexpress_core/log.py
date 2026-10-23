"""Logger shared by the core. Uses loguru when installed, stdlib logging otherwise."""

try:
    from loguru import logger as log
except ImportError:  # WebUI environments do not always ship loguru
    import logging

    log = logging.getLogger("autoexpress")
