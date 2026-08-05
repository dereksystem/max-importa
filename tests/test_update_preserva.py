"""UPDATE nao pode APAGAR o que ja esta no banco.

Regra: no UPDATE, uma celula VAZIA no arquivo significa "nao mexer neste campo" —
nunca "gravar NULL". Antes, o SET era montado por campo MAPEADO (nao por campo
PREENCHIDO): mapear uma coluna e deixar a celula em branco gerava
`SET cliEmail = NULL`, apagando o dado existente.

O padrao correto ja existia no proprio codigo (cliTipo e cliDatCad so entram no SET
quando ha valor); estes testes o estendem a todos os campos.
"""
import os
import sys

import pandas as pd
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import max_importa as MI_MAIN
import mi_importadores as MI
from mi_importadores import ClientesImportadorHeadless, ProdutosImportadorHeadless


class _Cursor:
    """Cursor falso: registra (sql, params) e devolve None em qualquer SELECT.

    fetchone() -> None faz os lookups (_lookup/_get_or_create/_get_emp_id)
    devolverem None sem tocar em banco nenhum.
    """
    def __init__(self):
        self.execs = []

    def execute(self, sql, *params):
        self.execs.append((sql, params[0] if len(params) == 1 else params))
        return self

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def close(self):
        pass

    # ── consultas ──
    def sets_de(self, tabela):
        """Colunas presentes no SET do UPDATE da tabela informada."""
        alvo = f"UPDATE {tabela} SET "
        cols = []
        for sql, _p in self.execs:
            if sql.startswith(alvo):
                trecho = sql[len(alvo):].split(" WHERE ")[0]
                cols += [p.split("=")[0].strip() for p in trecho.split(",")]
        return cols

    def params_de(self, tabela):
        alvo = f"UPDATE {tabela} SET "
        for sql, p in self.execs:
            if sql.startswith(alvo):
                return list(p)
        return []


class _Conn:
    def __init__(self, cursor):
        self._c = cursor
        self.commits = 0

    def cursor(self):
        return self._c

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


@pytest.fixture(autouse=True)
def _sem_efeito_colateral(monkeypatch):
    """_pos_importacao grava arquivos de relatorio — nao interessa aqui."""
    monkeypatch.setattr(MI, "_pos_importacao", lambda *a, **k: None)


def _montar(classe, mapping, linha):
    cur = _Cursor()
    imp = classe()
    imp.conn = _Conn(cur)
    imp.mapping = mapping
    imp.df = pd.DataFrame([linha])
    return imp, cur


# ══════════════════════════════════════════════════════════════════════════
# Clientes
# ══════════════════════════════════════════════════════════════════════════
def test_clientes_celula_vazia_nao_entra_no_set():
    """cliEmail/cliFone mapeados mas VAZIOS no arquivo: nao podem virar NULL."""
    imp, cur = _montar(
        ClientesImportadorHeadless,
        {"cliId": "ID", "cliNome": "NOME", "cliEmail": "EMAIL", "cliFone": "FONE"},
        {"ID": "1234", "NOME": "CLIENTE TESTE", "EMAIL": "", "FONE": "   "},
    )
    imp._atualizar_clientes()

    cols = cur.sets_de("cliente")
    assert "cliNome" in cols, "campo preenchido deve ser atualizado"
    assert "cliEmail" not in cols, "celula vazia APAGARIA o e-mail existente"
    assert "cliFone" not in cols, "celula so com espacos APAGARIA o telefone"
    assert None not in cur.params_de("cliente"), "nenhum NULL pode ir no SET"


def test_clientes_valor_zero_continua_sendo_gravado():
    """0 e um VALOR (cliDesativa=0 = ativo), nao pode ser confundido com vazio."""
    imp, cur = _montar(
        ClientesImportadorHeadless,
        {"cliId": "ID", "cliDesativa": "DES"},
        {"ID": "1234", "DES": "0"},
    )
    imp._atualizar_clientes()

    assert "cliDesativa" in cur.sets_de("cliente")
    assert 0 in cur.params_de("cliente")


def test_clientes_linha_sem_nenhum_dado_nao_gera_update():
    """So a chave preenchida: nada a atualizar, nenhum UPDATE deve sair."""
    imp, cur = _montar(
        ClientesImportadorHeadless,
        {"cliId": "ID", "cliNome": "NOME", "cliEmail": "EMAIL"},
        {"ID": "1234", "NOME": "", "EMAIL": ""},
    )
    imp._atualizar_clientes()

    assert cur.sets_de("cliente") == []


# ══════════════════════════════════════════════════════════════════════════
# Produtos
# ══════════════════════════════════════════════════════════════════════════
def test_produtos_celula_vazia_nao_entra_no_set():
    imp, cur = _montar(
        ProdutosImportadorHeadless,
        {"proId": "ID", "proDescricao": "DESC", "proAplicacao": "APL",
         "proVenda": "VENDA", "proCusto": "CUSTO"},
        {"ID": "50", "DESC": "PRODUTO TESTE", "APL": "", "VENDA": "9,90", "CUSTO": ""},
    )
    imp._atualizar_produtos()

    cols_prod = cur.sets_de("produto")
    assert "proDescricao" in cols_prod
    assert "proAplicacao" not in cols_prod, "celula vazia APAGARIA a aplicacao"
    assert None not in cur.params_de("produto")

    cols_emp = cur.sets_de("produto_empresa")
    assert "proVenda" in cols_emp
    assert "proCusto" not in cols_emp, "celula vazia APAGARIA o custo"
    assert None not in cur.params_de("produto_empresa")


def test_produtos_valor_zero_continua_sendo_gravado():
    """proVenda = 0 e um preco valido; proDesativaProd = 0 significa ativo."""
    imp, cur = _montar(
        ProdutosImportadorHeadless,
        {"proId": "50", "proVenda": "VENDA", "proDesativaProd": "DES"},
        {"proId": "50", "VENDA": "0", "DES": "0"},
    )
    imp.mapping = {"proId": "ID", "proVenda": "VENDA", "proDesativaProd": "DES"}
    imp.df = pd.DataFrame([{"ID": "50", "VENDA": "0", "DES": "0"}])
    imp._atualizar_produtos()

    cols = cur.sets_de("produto_empresa")
    assert "proVenda" in cols and "proDesativaProd" in cols
    assert 0.0 in cur.params_de("produto_empresa")


# ══════════════════════════════════════════════════════════════════════════
# Obrigatoriedade por operacao: no UPDATE, so a CHAVE
# ══════════════════════════════════════════════════════════════════════════
class _Tela(MI_MAIN.CancelavelMixin):
    """So o necessario para _obrigatorios_efetivos — sem GUI."""
    CAMPOS_OBRIGATORIOS = {"proDescricao", "proCodCst2", "proCodigo", "proUn",
                           "ncmCodigoNCM"}
    CAMPO_CHAVE = "proId"

    def __init__(self, operacao):
        self._operacao = operacao


def test_insert_exige_todos_os_obrigatorios():
    assert _Tela("INSERIR (INSERT)")._obrigatorios_efetivos() == _Tela.CAMPOS_OBRIGATORIOS


def test_update_exige_apenas_a_chave():
    assert _Tela("ATUALIZAR (UPDATE)")._obrigatorios_efetivos() == {"proId"}


# ══════════════════════════════════════════════════════════════════════════
# UPDATE por CPF/CNPJ: documento AMBIGUO nao pode sobrescrever ninguem
# ══════════════════════════════════════════════════════════════════════════
# Medido nas bases reais: MAX_CENTRAL tem um CNPJ com 19 clientes, o BD_ZERO um
# CPF com 15 e sete clientes com o placeholder 00000000000. Um "SELECT TOP 1"
# sem ORDER BY escolhia um deles de forma nao deterministica e gravava por cima.


class _CursorCli(_Cursor):
    """Cursor que responde ao lookup por documento com N clientes."""
    def __init__(self, ids_por_doc):
        super().__init__()
        self._ids = ids_por_doc
        self._ult = []

    def execute(self, sql, *params):
        super().execute(sql, *params)
        if "FROM cliente WHERE cliCpfCgc" in sql:
            doc = (params[0][0] if params else None)
            self._ult = [(i,) for i in self._ids.get(doc, [])]
        else:
            self._ult = []
        return self

    def fetchone(self):
        return self._ult[0] if self._ult else None

    def fetchall(self):
        return list(self._ult)


def _por_cpf(ids_por_doc, linha):
    cur = _CursorCli(ids_por_doc)
    imp = ClientesImportadorHeadless()
    imp.conn = _Conn(cur)
    imp.mapping = {"cliCpfCgc": "DOC", "cliNome": "NOME"}
    imp.df = pd.DataFrame([linha])
    imp.logs = []                       # o headless nasce com _log mudo
    imp._log = imp.logs.append
    return imp, cur


def test_update_por_cpf_documento_unico_atualiza():
    imp, cur = _por_cpf({"12345678901": [77]}, {"DOC": "12345678901", "NOME": "NOVO NOME"})
    imp._atualizar_clientes_por_cpf()
    assert "cliNome" in cur.sets_de("cliente"), "documento único deve atualizar"


def test_update_por_cpf_documento_ambiguo_NAO_grava():
    """19 clientes no mesmo CNPJ: nao da para saber qual — nao pode gravar em nenhum."""
    imp, cur = _por_cpf({"27840027000491": list(range(100, 119))},
                        {"DOC": "27840027000491", "NOME": "NOVO NOME"})
    imp._atualizar_clientes_por_cpf()
    assert cur.sets_de("cliente") == [], "documento ambiguo NAO pode sobrescrever ninguem"
    assert cur.sets_de("cliente_empresa") == []


def test_update_por_cpf_ambiguo_e_reportado():
    imp, cur = _por_cpf({"00000000000": [1, 2, 3, 4, 5, 6, 7]},
                        {"DOC": "00000000000", "NOME": "X"})
    imp._atualizar_clientes_por_cpf()
    txt = " ".join(imp.logs)
    assert "ambíguo" in txt.lower() or "ambiguo" in txt.lower(), \
        f"o motivo tem de aparecer no log: {txt[:200]}"
    assert "7" in txt, "quantos clientes casaram precisa estar no aviso"


def test_update_por_cpf_lookup_e_deterministico():
    """A consulta precisa de ORDER BY: sem ele o SQL Server nao garante a ordem."""
    imp, cur = _por_cpf({"12345678901": [77]}, {"DOC": "12345678901", "NOME": "N"})
    imp._atualizar_clientes_por_cpf()
    sql = next(s for s, _p in cur.execs if "FROM cliente WHERE cliCpfCgc" in s)
    assert "ORDER BY" in sql.upper(), "lookup por documento sem ORDER BY é não determinístico"


# ══════════════════════════════════════════════════════════════════════════
# UPDATE que nao acha o registro NAO pode contar como sucesso
# ══════════════════════════════════════════════════════════════════════════
class _CursorRowcount(_Cursor):
    """Cursor cujo UPDATE afeta `afetadas` linhas (0 = id inexistente)."""
    def __init__(self, afetadas=1):
        super().__init__()
        self.rowcount = -1
        self._afetadas = afetadas

    def execute(self, sql, *params):
        super().execute(sql, *params)
        self.rowcount = self._afetadas if sql.startswith("UPDATE ") else -1
        return self


def _com_rowcount(classe, mapping, linha, afetadas):
    cur = _CursorRowcount(afetadas)
    imp = classe()
    imp.conn = _Conn(cur)
    imp.mapping = mapping
    imp.df = pd.DataFrame([linha])
    imp.logs = []
    imp._log = imp.logs.append
    return imp, cur


def test_update_produto_com_id_inexistente_nao_conta_sucesso():
    """proId que nao existe: 0 linhas afetadas — nao pode virar '1 atualizado'."""
    imp, _cur = _com_rowcount(
        ProdutosImportadorHeadless,
        {"proId": "ID", "proDescricao": "DESC"},
        {"ID": "999999", "DESC": "NAO EXISTE"}, afetadas=0)
    imp._atualizar_produtos()
    txt = " ".join(imp.logs)
    assert "0 atualizados" in txt or "nao encontrado" in txt.lower(), \
        f"deveria reportar que nada foi atualizado: {txt[:250]}"


def test_update_cliente_com_id_inexistente_nao_conta_sucesso():
    imp, _cur = _com_rowcount(
        ClientesImportadorHeadless,
        {"cliId": "ID", "cliNome": "NOME"},
        {"ID": "999999", "NOME": "NAO EXISTE"}, afetadas=0)
    imp._atualizar_clientes()
    txt = " ".join(imp.logs)
    assert "0 atualizados" in txt or "nao encontrado" in txt.lower(), \
        f"deveria reportar que nada foi atualizado: {txt[:250]}"


def test_update_que_afeta_linha_continua_contando_sucesso():
    imp, _cur = _com_rowcount(
        ProdutosImportadorHeadless,
        {"proId": "ID", "proDescricao": "DESC"},
        {"ID": "50", "DESC": "EXISTE"}, afetadas=1)
    imp._atualizar_produtos()
    assert "1 atualizados" in " ".join(imp.logs)
