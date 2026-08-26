import logging
import pyodbc
import pymysql

from config import load_config

# SQL Server Native Client 11.0
# ODBC Driver 17 for SQL Server

class DBConnection:

    def cmd_sqlserver(self, cmd, tipo="select", params=None):
        db_cfg = load_config()["database"]["sqlserver"]
        db_connection = pyodbc.connect(
            'driver={driver};server={server};database={database};uid={uid};pwd={pwd};'.format(
                driver=db_cfg["driver"], server=db_cfg["server"], database=db_cfg["database"],
                uid=db_cfg["uid"], pwd=db_cfg["pwd"]))
        try:
            with db_connection.cursor() as cursor:
                logging.info(f'[SQLSERVER_CMD] cmd: {cmd}, tipo: {tipo}, params: {params}')
                if params is not None:
                    cursor.execute(cmd, params)
                else:
                    cursor.execute(cmd)

                if tipo == "select":
                    return_con = cursor.fetchall()
                    columns = [column[0] for column in cursor.description]
                    result_dict = []
                    for row in return_con:
                        result_dict.append(dict(zip(columns, row)))
                    result = result_dict
                elif tipo == "insert":
                    record_id = cursor.execute('SELECT @@IDENTITY AS id;').fetchone()[0]
                    result = record_id
                elif tipo in ("update", "delete"):
                    result = cursor.rowcount
                elif tipo == "exec":
                    result = cursor.nextset()
                elif tipo == "proc":
                    row = cursor.fetchone()
                    result = row[0] if row is not None else None
            if tipo != "select":
                db_connection.commit()
            return result
        except Exception as e:
            db_connection.rollback()
            logging.error(f'[SQLSERVER_ERRO] {e}')
            return -1
        finally:
            db_connection.close()

    def cmd_mysql(self, cmd, tipo="select"):
        db_cfg = load_config()["database"]["mysql"]
        db_connection2 = pymysql.connect(host=db_cfg["host"], user=db_cfg["user"], password=db_cfg["password"],
                                          db=db_cfg["db"], cursorclass=pymysql.cursors.DictCursor, autocommit=True)
        try:
            with db_connection2.cursor() as cursor:
                logging.info(f'[MYSQL_CMD] cmd: {cmd}, tipo: {tipo}')

                cursor.execute(cmd)

                if tipo == "select":
                    result = cursor.fetchall()
                elif tipo == "insert":
                    result = cursor.lastrowid
                elif tipo == "update":
                    result = cursor.rowcount
                elif tipo == "delete":
                    result = cursor.rowcount
                elif tipo == "call":
                    result = cursor.fetchall()
            db_connection2.close()
            return result
        except Exception as e:
            logging.error(f'[MYSQL_ERRO] erro de conexao: {e}')
            return False
