import logging
import pathlib
from termcolor import colored


class ColorFormatter(logging.Formatter):
    COLORS = {
        "WARNING": "yellow",
        "INFO": "green",
        "DEBUG": "blue",
        "CRITICAL": "red",
        "ERROR": "red",
    }

    RESET_SEQ = "\033[0m"

    def __init__(self, fmt, datefmt):
        super().__init__(fmt=fmt, datefmt=datefmt)

    def format(self, record):
        levelname = record.levelname
        if levelname in self.COLORS:
            colored_levelname = colored(
                levelname, self.COLORS[levelname], attrs=["bold"]
            )
            record.levelname = colored_levelname + self.RESET_SEQ
        return super(ColorFormatter, self).format(record)


class NoColorFormatter(logging.Formatter):
    def __init__(self, fmt, datefmt):
        super().__init__(fmt=fmt, datefmt=datefmt)

    def format(self, record):
        return super(NoColorFormatter, self).format(record)


def setup_logging():
    logger = logging.getLogger(__name__)
    if not logger.handlers:  # Ensure handlers are added only once
        logger.setLevel(logging.INFO)
        logger.propagate = False

        fileLogFormat = "%(asctime)s [%(levelname)-7.7s]  %(message)s"
        dateFormat = "%Y/%m/%d %H:%M:%S"
        fileLogFormatter = NoColorFormatter(fileLogFormat, dateFormat)

        consoleLogFormat = "[%(name)s] [%(levelname)s]  %(message)s"
        dateFormat = "%H:%M:%S"
        consoleLogFormatter = ColorFormatter(consoleLogFormat, dateFormat)

        log_path = "Output"
        log_name = "log"
        log_file_path = pathlib.Path(log_path, f"{log_name}.log")
        log_file_path.parent.mkdir(parents=True, exist_ok=True)

        fileHandler = logging.FileHandler(log_file_path)
        fileHandler.setFormatter(fileLogFormatter)
        logger.addHandler(fileHandler)

        consoleHandler = logging.StreamHandler()
        consoleHandler.setFormatter(consoleLogFormatter)
        logger.addHandler(consoleHandler)

    return logger
