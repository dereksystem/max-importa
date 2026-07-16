"""Configuração compartilhada dos testes do Max_Importa.

- Coloca a pasta da instalação (onde está max_importa.py) no sys.path.
- Fornece a infra de banco da Fase B: um banco DESCARTÁVEL (BD_ZERO_TEST) criado
  por CÓPIA do BD_ZERO (backup COPY_ONLY + restore), com um Database Snapshot para
  reverter o estado a cada teste. O BD_ZERO original NUNCA é tocado.

Credenciais/instância vêm de variáveis de ambiente. A SENHA não tem default (nunca
fica no código-fonte): sem MI_TEST_PASS, os testes de banco fazem SKIP. Se o SQL
Server não responder, também fazem SKIP — a suíte continua verde em máquinas sem
o servidor.

    MI_TEST_SERVER  (default: localhost\\BD_2022)
    MI_TEST_USER    (default: sa)
    MI_TEST_PASS    (SEM default — obrigatória p/ rodar os testes de banco)
    MI_TEST_SRCDB   (default: BD_ZERO)   banco-modelo a ser copiado

Ex.:  set MI_TEST_PASS=suasenha  &&  python -m pytest
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

SERVER = os.environ.get("MI_TEST_SERVER", r"localhost\BD_2022")
USER   = os.environ.get("MI_TEST_USER", "sa")
PWD    = os.environ.get("MI_TEST_PASS")   # sem default: senha NUNCA no código-fonte
SRC_DB = os.environ.get("MI_TEST_SRCDB", "BD_ZERO")


def _cs(db: str) -> str:
    return ("DRIVER={ODBC Driver 17 for SQL Server};"
            f"SERVER={SERVER};UID={USER};PWD={PWD};DATABASE={db};"
            "TrustServerCertificate=yes;")


class _BDController:
    """Cria/reverte/dropa o banco descartável BD_ZERO_TEST (cópia do BD_ZERO)."""
    TEST_DB = "BD_ZERO_TEST"
    SNAP    = "BD_ZERO_TEST_SNAP"

    def __init__(self):
        import pyodbc
        self._pyodbc = pyodbc
        self.master = pyodbc.connect(_cs("master"), timeout=15)
        self.master.autocommit = True   # BACKUP/RESTORE/DDL não rodam em transação

    def _exec(self, sql: str):
        cur = self.master.cursor()
        cur.execute(sql)
        while cur.nextset():
            pass

    def _db_existe(self, nome: str) -> bool:
        return self.master.cursor().execute(
            "SELECT DB_ID(?)", nome).fetchone()[0] is not None

    def setup(self):
        cur = self.master.cursor()
        data_path = cur.execute(
            "SELECT CAST(SERVERPROPERTY('InstanceDefaultDataPath') AS nvarchar(500))").fetchone()[0]
        bak_path = cur.execute(
            "SELECT CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS nvarchar(500))").fetchone()[0]
        arqs = cur.execute(
            "SELECT name, type_desc FROM sys.master_files WHERE database_id=DB_ID(?)",
            SRC_DB).fetchall()
        self._data_logical = next(n for n, t in arqs if t == "ROWS")
        self._log_logical  = next(n for n, t in arqs if t == "LOG")
        self._bak       = os.path.join(bak_path, "BD_ZERO_copy_test.bak")
        self._mdf       = os.path.join(data_path, self.TEST_DB + ".mdf")
        self._ldf       = os.path.join(data_path, self.TEST_DB + "_log.ldf")
        self._snap_file = os.path.join(data_path, self.TEST_DB + "_snap.ss")

        self.drop()   # limpeza de execução anterior interrompida
        self._exec(f"BACKUP DATABASE [{SRC_DB}] TO DISK=N'{self._bak}' "
                   "WITH COPY_ONLY, INIT, FORMAT")
        self._exec(f"""RESTORE DATABASE [{self.TEST_DB}] FROM DISK=N'{self._bak}' WITH
            MOVE '{self._data_logical}' TO N'{self._mdf}',
            MOVE '{self._log_logical}'  TO N'{self._ldf}',
            REPLACE, RECOVERY""")
        self._exec(f"CREATE DATABASE [{self.SNAP}] "
                   f"ON (NAME='{self._data_logical}', FILENAME=N'{self._snap_file}') "
                   f"AS SNAPSHOT OF [{self.TEST_DB}]")

    def revert(self):
        """Reverte BD_ZERO_TEST ao estado do snapshot (desfaz TUDO, inclusive DDL
        não-transacional). Exige acesso exclusivo — derruba conexões pendentes."""
        self._exec(f"ALTER DATABASE [{self.TEST_DB}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")
        self._exec(f"RESTORE DATABASE [{self.TEST_DB}] FROM DATABASE_SNAPSHOT='{self.SNAP}'")
        self._exec(f"ALTER DATABASE [{self.TEST_DB}] SET MULTI_USER")

    def drop(self):
        try:
            if self._db_existe(self.SNAP):
                self._exec(f"DROP DATABASE [{self.SNAP}]")
        except Exception:
            pass
        try:
            if self._db_existe(self.TEST_DB):
                self._exec(f"ALTER DATABASE [{self.TEST_DB}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")
                self._exec(f"DROP DATABASE [{self.TEST_DB}]")
        except Exception:
            pass

    def close(self):
        try:
            self.master.close()
        except Exception:
            pass


@pytest.fixture(scope="session")
def bd_test():
    """Prepara o banco descartável uma vez por sessão; dropa no fim.
    SKIP automático se o SQL Server de teste não estiver acessível."""
    if not PWD:
        pytest.skip("defina MI_TEST_PASS para rodar os testes de banco "
                    "(a senha não fica no código-fonte)")
    try:
        import pyodbc  # noqa: F401
    except Exception:
        pytest.skip("pyodbc não disponível")
    try:
        ctrl = _BDController()
    except Exception as e:
        pytest.skip(f"SQL Server de teste indisponível ({SERVER}): {str(e)[:120]}")
    try:
        ctrl.setup()
    except Exception as e:
        ctrl.close()
        pytest.skip(f"Falha ao preparar {_BDController.TEST_DB}: {str(e)[:160]}")
    yield ctrl
    ctrl.drop()
    ctrl.close()


@pytest.fixture
def db_conn(bd_test):
    """Conexão ao banco descartável (DESTINO). Ao final do teste, reverte o
    snapshot para o próximo teste começar do zero."""
    import pyodbc
    conn = pyodbc.connect(_cs(_BDController.TEST_DB), timeout=15)
    yield conn
    try:
        conn.close()
    except Exception:
        pass
    bd_test.revert()


@pytest.fixture
def orig_conn(bd_test):
    """Conexão ao banco-modelo (ORIGEM, ex.: BD_ZERO) — usada como origem nas
    migrações. Somente leitura; a origem nunca é modificada."""
    import pyodbc
    conn = pyodbc.connect(_cs(SRC_DB), timeout=15)
    yield conn
    try:
        conn.close()
    except Exception:
        pass
