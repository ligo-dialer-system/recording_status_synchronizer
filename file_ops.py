import fcntl
import logging
import os
import shutil
import time

log = logging.getLogger("logger_file")

_lock_file_handle = None


def acquire_lock(lock_path):
    global _lock_file_handle
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    handle = open(lock_path, "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False
    _lock_file_handle = handle
    return True


def list_projects(source_rep):
    with os.scandir(source_rep) as entries:
        return [entry.name for entry in entries if entry.is_dir()]


def list_pending_files(project_dir, min_age_seconds):
    pending_dir = os.path.join(project_dir, "copy_log_pending")
    if not os.path.isdir(pending_dir):
        return []
    now = time.time()
    files = []
    with os.scandir(pending_dir) as entries:
        for entry in entries:
            if not entry.is_file():
                continue
            mtime = entry.stat().st_mtime
            if now - mtime < min_age_seconds:
                continue
            files.append((mtime, entry.path))
    files.sort(key=lambda item: item[0])
    return [path for _, path in files]


def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def move_file(src, dest_dir):
    ensure_dir(dest_dir)
    shutil.move(src, dest_dir)
