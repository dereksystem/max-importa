"""Nucleo multi-loja (mi_multiloja) — sem GUI e sem banco.

Regras cobertas aqui:
  - detectar multi-loja = mais de uma linha em `config`;
  - `registrar_filtro` grava UMA linha de empresaFiltro por empresa marcada, com
    IF NOT EXISTS (reimportar o mesmo arquivo nao pode duplicar);
  - a grafia de emfPkField e SEMPRE a canonica (a base real do MAX_GROW tem
    'cliId' e 'cliid' misturados — o MaxImporta nao propaga essa bagunca).
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import mi_multiloja as ml


class _Cursor:
    """Cursor falso: registra (sql, params) e devolve o que for programado."""
    def __init__(self, retorno=None):
        self.execs = []
        self._retorno = list(retorno or [])

    def execute(self, sql, *params):
        self.execs.append((sql, params[0] if len(params) == 1 else params))
        return self

    def fetchall(self):
        return list(self._retorno)

    def fetchone(self):
        return self._retorno[0] if self._retorno else None

    def close(self):
        pass


# ── listar_empresas / e_multiloja ────────────────────────────────────────────
def test_listar_empresas_devolve_id_e_fantasia():
    cur = _Cursor([(1, "GROW SUPLEMENTOS"), (2, "GROW SUPLEMENTOS"),
                   (3, "GROW SUPLEMENTOS LTDA")])
    emps = ml.listar_empresas(cur)
    assert [e["cofId"] for e in emps] == [1, 2, 3]
    assert emps[2]["cofEmpFantasia"] == "GROW SUPLEMENTOS LTDA"
    assert "config" in cur.execs[0][0]


def test_listar_empresas_sem_fantasia_usa_rotulo_generico():
    """cofEmpFantasia NULL nao pode virar 'None' na tela."""
    cur = _Cursor([(1, None)])
    assert ml.listar_empresas(cur)[0]["cofEmpFantasia"] == "(sem nome)"


@pytest.mark.parametrize("linhas,esperado", [
    ([(1, "LOJA")], False),                            # banco de uma loja
    ([(1, "A"), (2, "B")], True),
    ([(1, "A"), (2, "B"), (3, "C")], True),
    ([], False),                                       # banco sem config
])
def test_e_multiloja(linhas, esperado):
    assert ml.e_multiloja(_Cursor(linhas)) is esperado


# ── registrar_filtro ─────────────────────────────────────────────────────────
def test_registrar_filtro_uma_linha_por_empresa_marcada():
    cur = _Cursor()
    n = ml.registrar_filtro(cur, [1, 3], "produto", "proId", 50)
    assert n == 2
    assert len(cur.execs) == 2
    for (sql, params), emp in zip(cur.execs, (1, 3)):
        assert "empresaFiltro" in sql
        assert params[0] == emp
        assert params[1] == "produto"
        assert params[2] == "proId"
        assert params[3] == 50


def test_registrar_filtro_usa_if_not_exists():
    """Reimportar o mesmo arquivo nao pode duplicar a visibilidade."""
    cur = _Cursor()
    ml.registrar_filtro(cur, [1], "cliente", "cliId", 77)
    sql = cur.execs[0][0]
    assert "IF NOT EXISTS" in sql.upper()
    assert sql.upper().index("IF NOT EXISTS") < sql.upper().index("INSERT")


def test_registrar_filtro_grava_usuario_admin_por_padrao():
    """emfUsuId e int NOT NULL sem default no banco — precisa ir preenchido."""
    cur = _Cursor()
    ml.registrar_filtro(cur, [1], "produto", "proId", 9)
    assert ml.USU_ID_PADRAO == 2
    assert ml.USU_ID_PADRAO in cur.execs[0][1]


def test_registrar_filtro_aceita_outro_usuario():
    cur = _Cursor()
    ml.registrar_filtro(cur, [1], "produto", "proId", 9, usu_id=683)
    assert 683 in cur.execs[0][1]


@pytest.mark.parametrize("emp_ids", [[], None])
def test_registrar_filtro_sem_empresa_nao_executa_nada(emp_ids):
    cur = _Cursor()
    assert ml.registrar_filtro(cur, emp_ids, "produto", "proId", 1) == 0
    assert cur.execs == []


def test_registrar_filtro_sem_pk_nao_executa_nada():
    """Sem o id do registro nao ha o que vincular (proId None em erro anterior)."""
    cur = _Cursor()
    assert ml.registrar_filtro(cur, [1], "produto", "proId", None) == 0
    assert cur.execs == []


def test_registrar_filtro_ignora_empresa_repetida():
    cur = _Cursor()
    assert ml.registrar_filtro(cur, [1, 1, 2], "produto", "proId", 5) == 2


# ── tabela/pk por modulo ─────────────────────────────────────────────────────
@pytest.mark.parametrize("modulo,tabela,pk", [
    ("PRODUTOS", "produto", "proId"),
    ("CLIENTES", "cliente", "cliId"),
])
def test_tabela_por_modulo(modulo, tabela, pk):
    assert ml.TABELA_POR_MODULO[modulo] == (tabela, pk)


def test_pk_field_e_a_grafia_canonica():
    """A base real tem 'cliId' e 'cliid'; o MaxImporta grava sempre 'cliId'."""
    cur = _Cursor()
    ml.registrar_filtro(cur, [1], *ml.TABELA_POR_MODULO["CLIENTES"], 42)
    assert cur.execs[0][1][2] == "cliId"


# ── _resolver_empresas (mixin de banco) ──────────────────────────────────────
from mi_db import MapeamentoDBMixin


class _Obj(MapeamentoDBMixin):
    def __init__(self, **kw):
        self.mapping = {}
        for k, v in kw.items():
            setattr(self, k, v)


def test_resolver_empresas_banco_de_uma_loja():
    """Uma empresa: as duas listas sao iguais — tudo se comporta como antes."""
    obj = _Obj()
    todas, alvo = obj._resolver_empresas(_Cursor([(7, "LOJA UNICA")]))
    assert todas == [7] and alvo == [7]


def test_resolver_empresas_sem_selecao_usa_todas():
    obj = _Obj()
    todas, alvo = obj._resolver_empresas(_Cursor([(1, "A"), (2, "B"), (3, "C")]))
    assert todas == [1, 2, 3] and alvo == [1, 2, 3]


def test_resolver_empresas_respeita_a_selecao():
    """As linhas nascem em TODAS; so a visibilidade/alteracao usa as marcadas."""
    obj = _Obj(empresas_alvo=[1, 3])
    todas, alvo = obj._resolver_empresas(_Cursor([(1, "A"), (2, "B"), (3, "C")]))
    assert todas == [1, 2, 3]
    assert alvo == [1, 3]


def test_resolver_empresas_sem_config_cai_no_fallback():
    """Banco atipico sem config: mantem o fallback historico do _get_emp_id (1)."""
    obj = _Obj()
    todas, alvo = obj._resolver_empresas(_Cursor([]))
    assert todas == [1] and alvo == [1]


def test_resolver_empresas_nao_consulta_o_banco_duas_vezes():
    """A lista e memoizada: 50 mil linhas nao podem virar 50 mil SELECTs na config."""
    obj = _Obj()
    cur = _Cursor([(1, "A"), (2, "B")])
    obj._resolver_empresas(cur)
    obj._resolver_empresas(cur)
    obj._resolver_empresas(cur)
    assert len(cur.execs) == 1


# ── _aplicar_selecao_empresas (cola entre a tela e o importador) ─────────────
import max_importa as MI_MAIN


class _Tela(MI_MAIN.CancelavelMixin):
    def __init__(self, resposta):
        self._resposta = resposta
        self.logs = []
        self._log = self.logs.append

    def _selecionar_empresas(self, is_insert=True, conn=None):
        return self._resposta


def test_aplicar_selecao_banco_de_uma_loja_segue_sem_perguntar():
    t = _Tela(None)
    assert t._aplicar_selecao_empresas() is True
    assert t.empresas_alvo is None


def test_aplicar_selecao_guarda_a_escolha():
    t = _Tela([1, 3])
    assert t._aplicar_selecao_empresas() is True
    assert t.empresas_alvo == [1, 3]


def test_aplicar_selecao_cancelada_aborta():
    t = _Tela(False)
    assert t._aplicar_selecao_empresas() is False
    assert any("cancelada" in l.lower() for l in t.logs)


def test_selecionar_empresas_sem_conexao_falha_alto():
    """Nao pode devolver None em silencio: seria multi-loja ignorado sem ninguem ver.

    Foi o que aconteceu ao ligar a JanelaMigracao, que NAO tem self.conn — o
    try/except engolia o AttributeError e a migracao seguia como banco de uma loja.
    """
    class _SemConn(MI_MAIN.CancelavelMixin):
        _log = staticmethod(lambda *a: None)

    with pytest.raises(RuntimeError, match="conexão"):
        _SemConn()._selecionar_empresas()
