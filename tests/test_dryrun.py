"""Testes do cursor simulado do dry-run (mi_db._CursorSimulado).

Esta é a peça de SEGURANÇA da simulação de Produtos/Clientes: se ela deixar passar
um comando de escrita, uma "simulação" grava no banco de verdade. Por isso os testes
cobrem as formas reais em que a escrita aparece no código (inclusive
`IF NOT EXISTS (...) INSERT`, que não começa com INSERT).
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from mi_db import MapeamentoDBMixin, _CursorSimulado


class _CursorReal:
    """Cursor de mentira que REGISTRA tudo que chegaria ao banco."""
    def __init__(self, retorno=None):
        self.executados = []
        self._retorno = retorno or []
    def execute(self, sql, *params):
        self.executados.append(sql)
        return self
    def executemany(self, sql, seq):
        self.executados.append(sql)
        return self
    def fetchone(self):
        return self._retorno[0] if self._retorno else None
    def fetchall(self):
        return list(self._retorno)
    def close(self):
        pass


@pytest.mark.parametrize("sql", [
    "INSERT INTO produto (proId) VALUES (?)",
    "insert into produto_empresa (proId, empId) values (?,?)",
    "IF NOT EXISTS (SELECT 1 FROM produto WHERE proId = ?) INSERT INTO produto (proId) VALUES (?)",
    "UPDATE cliente SET cliNome = ? WHERE cliId = ?",
    "DELETE FROM vendaPgto WHERE pgtId = ?",
    "SET IDENTITY_INSERT cliente ON",
    "SET IDENTITY_INSERT produto OFF",
    "DBCC CHECKIDENT ('cliente', RESEED, 100)",
    "TRUNCATE TABLE cliente_empresa",
])
def test_escrita_NAO_chega_ao_banco(sql):
    real = _CursorReal()
    sim = _CursorSimulado(real)
    sim.execute(sql)
    assert real.executados == [], f"vazou para o banco: {sql}"
    assert sum(sim.escritas.values()) == 1


@pytest.mark.parametrize("sql", [
    "SELECT cliId FROM cliente WHERE cliCpfCgc = ?",
    "SELECT TOP 1 cofId FROM config",
    "SELECT COUNT(*) FROM produto",
    "SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(?)",
])
def test_leitura_PASSA_para_o_banco(sql):
    real = _CursorReal(retorno=[(7,)])
    sim = _CursorSimulado(real)
    sim.execute(sql)
    assert real.executados == [sql]
    assert sim.fetchone() == (7,)
    assert sim.escritas == {}


def test_scope_identity_devolve_id_ficticio():
    """Sem o INSERT, SCOPE_IDENTITY seria NULL e o worker abortaria a linha com
    'SCOPE_IDENTITY retornou NULL' — a simulação reportaria erros inexistentes."""
    real = _CursorReal(retorno=[(None,)])
    sim = _CursorSimulado(real)
    sim.execute("INSERT INTO produto (proDescricao) VALUES (?)", ("X",))
    sim.execute("SELECT SCOPE_IDENTITY()")
    id1 = sim.fetchone()[0]
    assert id1 is not None and id1 > 0
    sim.execute("SELECT SCOPE_IDENTITY()")
    assert sim.fetchone()[0] == id1 + 1        # ids fictícios não se repetem


def test_insert_e_scope_identity_no_MESMO_comando():
    """Caso real do import de produtos: 'SET NOCOUNT ON; INSERT ...; SELECT
    SCOPE_IDENTITY()' vem num único execute(). A escrita é descartada, mas o id
    fictício PRECISA vir — senão o worker aborta a linha e a simulação reporta
    um erro inexistente (era o que acontecia: 0 inseridos / 1 erro)."""
    real = _CursorReal()
    sim = _CursorSimulado(real)
    sim.execute("SET NOCOUNT ON; INSERT INTO produto (proDescricao) VALUES (?); "
                "SELECT SCOPE_IDENTITY();", ("X",))
    assert real.executados == []              # não gravou
    linha = sim.fetchone()
    assert linha is not None and linha[0] > 0  # mas devolveu o id
    assert sim.escritas.get("INSERT produto") == 1


def test_executemany_conta_todas_as_linhas():
    real = _CursorReal()
    sim = _CursorSimulado(real)
    sim.executemany("INSERT INTO vendaPgto (empId) VALUES (?)", [(1,), (1,), (1,)])
    assert real.executados == []
    assert sum(sim.escritas.values()) == 3


def test_rotulos_por_tabela():
    sim = _CursorSimulado(_CursorReal())
    sim.execute("INSERT INTO produto (a) VALUES (?)")
    sim.execute("INSERT INTO produto (a) VALUES (?)")
    sim.execute("INSERT INTO produto_empresa (a) VALUES (?)")
    sim.execute("UPDATE cliente SET x = 1 WHERE y = 2")
    assert sim.escritas["INSERT produto"] == 2
    assert sim.escritas["INSERT produto_empresa"] == 1
    assert sim.escritas["UPDATE cliente"] == 1


def test_fetchall_apos_escrita_e_vazio():
    sim = _CursorSimulado(_CursorReal(retorno=[(1,), (2,)]))
    sim.execute("INSERT INTO x (a) VALUES (1)")
    assert sim.fetchall() == []
    assert sim.fetchone() is None


def test_delega_atributos_desconhecidos():
    real = _CursorReal()
    real.description = "coluna-x"
    assert _CursorSimulado(real).description == "coluna-x"


# ── _cursor() e o resumo da simulação ────────────────────────────────────────
class _Obj(MapeamentoDBMixin):
    def __init__(self, dry):
        self.mapping = {}
        self._dry_run = dry
        self.conn = self
        self.logs = []
        self._log = self.logs.append
    def cursor(self):
        return _CursorReal()


def test_cursor_normal_fora_do_dry_run():
    o = _Obj(dry=False)
    assert not isinstance(o._cursor(), _CursorSimulado)
    assert o._resumo_simulacao() == []


def test_cursor_simulado_no_dry_run_e_resumo():
    o = _Obj(dry=True)
    c1, c2 = o._cursor(), o._cursor()
    assert isinstance(c1, _CursorSimulado)
    c1.execute("INSERT INTO produto (a) VALUES (1)")
    c2.execute("INSERT INTO produto (a) VALUES (2)")
    c2.execute("UPDATE cliente SET x = 1 WHERE y = 2")
    resumo = o._resumo_simulacao()
    assert len(resumo) == 1
    assert "INSERT produto: 2" in resumo[0]     # agregado entre os dois cursores
    assert "UPDATE cliente: 1" in resumo[0]


def test_resumo_vazio_quando_nada_seria_gravado():
    o = _Obj(dry=True)
    o._cursor().execute("SELECT 1")
    assert o._resumo_simulacao() == []
