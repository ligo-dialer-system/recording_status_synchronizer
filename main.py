import logging
import os
from datetime import date

from config import load_config
from connection import DBConnection
from file_ops import acquire_lock, list_pending_files, list_projects, move_file
from log_manager import LogConfig
from parsing import parse_line
from retry_queue import enqueue_retry, process_retry_queue

log = logging.getLogger("logger_file")


def process_line(fields):
    sql = ("exec SPR_RM_UPD_AUDIO_FILE @P_CODE_IP_DEVICE = ?, @P_NM_FILE = ?, "
           "@P_ID_PROJECT = ?, @P_MUST_MERGE_FILES = ?")
    params = (fields.get("NM_DEVICE"), fields.get("NM_FILE"),
              fields.get("ID_PROJECT"), fields.get("MUST_MERGE_FILES"))
    try:
        result = DBConnection().cmd_sqlserver(sql, "proc", params)
    except Exception as e:
        log.exception(f"[LINHA_ERRO] excecao ao chamar SP: {e}")
        return False
    # -1/excecao = falha de infra; 0 = SP recusou (ex: registro nao encontrado
    # ainda no banco); qualquer outro valor = sucesso.
    return result not in (0, -1, None)


def process_pending_file(project_dir, path, backoff_seconds):
    log.info(f"[ARQUIVO_PROCESSANDO] processando arquivo: {path}")
    had_failure = False
    with open(path, "r") as f:
        linhas = f.readlines()
    for linha in linhas:
        if not linha.strip():
            continue
        fields = parse_line(linha)
        if not process_line(fields):
            had_failure = True
            enqueue_retry(project_dir, fields, "falha no update inicial",
                           os.path.basename(path), backoff_seconds)

    if had_failure:
        log.error(f"[ARQUIVO_FALHA_PARCIAL] arquivo: {path} -> copy_log_partial "
                  f"(linhas com erro seguem na fila de retry)")
        move_file(path, os.path.join(project_dir, "copy_log_partial"))
    else:
        log.info(f"[ARQUIVO_SUCESSO] arquivo processado com sucesso: {path} -> copy_log_success")
        move_file(path, os.path.join(project_dir, "copy_log_success"))


def process_pending(project, project_dir, backoff_seconds):
    for path in list_pending_files(project_dir):
        try:
            process_pending_file(project_dir, path, backoff_seconds)
        except Exception:
            log.exception(f"[ARQUIVO_ERRO] falha ao processar arquivo {path}, projeto {project}")


def read_file():
    config = load_config()
    source_rep = config["paths"]["source_rep"]
    backoff_seconds = config["retry"]["backoff_seconds"]
    max_retries = config["retry"]["max_retries"]

    for project in list_projects(source_rep):
        project_dir = os.path.join(source_rep, project)
        try:
            process_retry_queue(project_dir, backoff_seconds, max_retries, process_line)
            process_pending(project, project_dir, backoff_seconds)
        except Exception:
            log.exception(f"[PROJETO_ERRO] falha ao processar projeto {project}")


if __name__ == '__main__':
    config = load_config()
    log_dir = config["paths"]["log_dir"]
    lock_path = config["paths"]["lock_file"]
    log_level = config.get("logging", {}).get("level", "INFO")

    name = "log_read_file_{0}".format(date.today())
    FORMAT = "%(asctime)s [%(thread)d] %(levelname)-5s %(name)s - %(message)s. [file=%(filename)s:%(lineno)d]"
    log_config = LogConfig(name, log_dir, level=log_level, fmt=FORMAT)
    log_config.config_logging()

    if not acquire_lock(lock_path):
        log.warning("[LOCK_OCUPADO] execucao anterior ainda em andamento, encerrando sem processar.")
    else:
        read_file()
