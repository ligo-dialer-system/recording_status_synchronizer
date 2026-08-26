import sys
from os.path import exists
from os import makedirs
from logging import Formatter
from logging.config import dictConfig

FORMAT = "%(asctime)s [%(thread)d] %(levelname)-5s %(name)s " \
         "- %(message)s. [file=%(filename)s:%(lineno)d]"
DATEFMT = "%d/%m/%Y %H:%M:%S"

class ColorFormatter(Formatter):
    """Colore apenas a palavra do level (INFO/ERROR/...), mantendo o resto
    da linha na cor padrao do terminal, e so quando a saida for um
    terminal (evita sujar redirecionamentos/arquivos)."""

    _COLORS = {
        'DEBUG': '\033[36m',     # ciano
        'INFO': '\033[32m',      # verde
        'WARNING': '\033[33m',   # amarelo
        'ERROR': '\033[31m',     # vermelho
        'CRITICAL': '\033[1;31m',  # vermelho negrito
    }
    _RESET = '\033[0m'
    _TIME_COLOR = '\033[95m'  # rosa (magenta claro)
    _LEVELNAME_WIDTH = 5  # mantem o alinhamento do "%(levelname)-5s" do FORMAT

    def __init__(self, fmt=FORMAT, datefmt=DATEFMT, use_color=True):
        super().__init__(fmt, datefmt=datefmt)
        self.use_color = use_color

    def formatTime(self, record, datefmt=None):
        formatted = super().formatTime(record, datefmt)
        if self.use_color:
            return f"{self._TIME_COLOR}{formatted}{self._RESET}"
        return formatted

    def format(self, record):
        if not self.use_color:
            return super().format(record)
        color = self._COLORS.get(record.levelname, '')
        if not color:
            return super().format(record)
        original_levelname = record.levelname
        # padroniza a largura antes de aplicar a cor: os codigos ANSI sao
        # invisiveis mas contam como caracteres, o que quebraria o
        # alinhamento se o "-5s" do FORMAT tentasse preencher depois.
        padded = original_levelname.ljust(self._LEVELNAME_WIDTH)
        record.levelname = f"{color}{padded}{self._RESET}"
        try:
            return super().format(record)
        finally:
            record.levelname = original_levelname


class LogConfig(object):

    def __init__(self, log_name, log_dir, level='INFO', fmt=FORMAT, datefmt=DATEFMT):
        self.log_name = log_name
        self.log_dir = log_dir
        self.level = level
        self.formatted = fmt
        self.datefmt = datefmt

    def config_logging(self, when='D', utc=True,
                       backup_count=5):
        if not exists(self.log_dir):
            makedirs(self.log_dir)

        use_color = sys.stdout.isatty()

        logging_config = {
            "version": 1,
            'disable_existing_loggers': False,
            "formatters": {
                'standard': {
                    'format': self.formatted,
                    'datefmt': self.datefmt,
                },
                'colored': {
                    '()': ColorFormatter,
                    'fmt': self.formatted,
                    'datefmt': self.datefmt,
                    'use_color': use_color,
                },
            },
            "handlers": {
                'default': {
                    'class': 'logging.StreamHandler',
                    'formatter': 'colored',
                    'level': self.level,
                    'stream': 'ext://sys.stdout'
                },
                'file': {
                    'class': 'logging.handlers.TimedRotatingFileHandler',
                    'formatter': 'standard',
                    'level': self.level,
                    'when': when,
                    'utc': utc,
                    'backupCount': backup_count,
                    'filename': '{log_dir}/{log_name}.log'.format(
                        log_dir=self.log_dir, log_name=self.log_name),
                }
            },
            "loggers": {
                "": {
                    'handlers': ['default'],
                    'level': self.level
                },
                "logger_file": {
                    'handlers': ['default', 'file'],
                    'level': self.level
                },
            }
        }

        dictConfig(logging_config)
