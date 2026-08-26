import logging
import os
import re
import time
import uuid

from parsing import build_line, parse_line

log = logging.getLogger("logger_file")

RETRY_QUEUE_DIRNAME = os.path.join("copy_log_error", "retry_queue")
DEAD_LETTER_DIRNAME = os.path.join("copy_log_error", "dead_letter")

_RETRY_FILENAME_RE = re.compile(r"^(\d+)__a(\d+)__([0-9a-f]+)\.retry$")


def _retry_queue_dir(project_dir):
    return os.path.join(project_dir, RETRY_QUEUE_DIRNAME)


def _dead_letter_dir(project_dir):
    return os.path.join(project_dir, DEAD_LETTER_DIRNAME)


def enqueue_retry(project_dir, fields, last_error, src_file, backoff_seconds, attempts_made=0):
    queue_dir = _retry_queue_dir(project_dir)
    os.makedirs(queue_dir, exist_ok=True)
    next_due = int(time.time()) + backoff_seconds[attempts_made]
    filename = f"{next_due}__a{attempts_made}__{uuid.uuid4().hex[:8]}.retry"
    payload = dict(fields)
    payload["LAST_ERROR"] = _sanitize(last_error)
    payload["SRC_FILE"] = src_file
    with open(os.path.join(queue_dir, filename), "w") as f:
        f.write(build_line(payload))
    log.error(f"[RETRY_ENFILEIRADO] projeto={os.path.basename(project_dir)} "
              f"arquivo={filename} tentativa={attempts_made} erro={last_error}")


def _sanitize(value):
    return str(value).replace(";", ",").replace("\n", " ")


def _due_retry_files(project_dir, now):
    queue_dir = _retry_queue_dir(project_dir)
    if not os.path.isdir(queue_dir):
        return []
    due = []
    with os.scandir(queue_dir) as entries:
        for entry in entries:
            match = _RETRY_FILENAME_RE.match(entry.name)
            if not match:
                continue
            next_due_epoch = int(match.group(1))
            attempts_made = int(match.group(2))
            if next_due_epoch <= now:
                due.append((entry.path, attempts_made))
    return due


def process_retry_queue(project_dir, backoff_seconds, max_retries, process_fields):
    """Reprocessa itens vencidos da fila de retry.

    process_fields(fields: dict) -> bool (True = sucesso) deve encapsular a
    chamada de negócio (ex: SP no banco) para os campos de um item da fila.
    """
    now = int(time.time())
    for path, attempts_made in _due_retry_files(project_dir, now):
        fields, last_error, src_file = {}, None, None
        try:
            with open(path, "r") as f:
                linha = f.readline()
            fields = parse_line(linha)
            last_error = fields.pop("LAST_ERROR", None)
            src_file = fields.pop("SRC_FILE", None)
            success = process_fields(fields)
        except Exception as e:
            log.exception(f"[RETRY_ERRO_PROCESSAMENTO] arquivo={path}: {e}")
            success = False
            last_error = str(e)

        try:
            os.remove(path)
        except OSError:
            pass

        if success:
            log.info(f"[RETRY_SUCESSO] projeto={os.path.basename(project_dir)} "
                      f"arquivo={os.path.basename(path)} tentativa={attempts_made}")
            continue

        attempts_made += 1
        if attempts_made >= max_retries:
            _move_to_dead_letter(project_dir, fields, last_error, src_file, attempts_made)
        else:
            enqueue_retry(project_dir, fields, last_error, src_file, backoff_seconds, attempts_made)


def _move_to_dead_letter(project_dir, fields, last_error, src_file, attempts_made):
    dead_dir = _dead_letter_dir(project_dir)
    os.makedirs(dead_dir, exist_ok=True)
    filename = f"deadletter__a{attempts_made}__{uuid.uuid4().hex[:8]}.retry"
    payload = dict(fields)
    payload["LAST_ERROR"] = _sanitize(last_error)
    payload["SRC_FILE"] = src_file
    with open(os.path.join(dead_dir, filename), "w") as f:
        f.write(build_line(payload))
    log.error(f"[RETRY_ESGOTADO] projeto={os.path.basename(project_dir)} tentativas={attempts_made} "
              f"DEAD_LETTER requer intervencao manual arquivo={filename} campos={payload}")
