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


# ══════════════════════════════════════════════════════════════════════════
# cliCelular — campo opcional, mesmo tratamento do cliFone
# ══════════════════════════════════════════════════════════════════════════
def test_cliCelular_e_opcional_na_tela():
    campos = {n: ob for n, _t, _d, ob in MI_MAIN.JanelaClientes.CAMPOS_CLIENTE}
    assert "cliCelular" in campos, "cliCelular precisa estar mapeável na tela"
    assert campos["cliCelular"] is False, "cliCelular é OPCIONAL"
    assert "cliCelular" not in MI_MAIN.JanelaClientes.CAMPOS_OBRIGATORIOS


def test_cliCelular_entra_no_insert():
    from mi_importadores import ClientesImportMixin as C
    for ident in (True, False):
        sql = C._sql_cli(ident, 1)
        assert "cliCelular" in sql, f"cliCelular ausente do INSERT (identity={ident})"


@pytest.mark.parametrize("ident,n_emp", [(True, 1), (True, 3), (False, 1), (False, 3)])
def test_cliCelular_nao_desalinhou_os_markers(ident, n_emp):
    """O campo novo entra na lista de colunas E na de valores — senão desloca tudo."""
    import re
    from mi_importadores import ClientesImportMixin as C
    sql = C._sql_cli(ident, n_emp)
    for m in re.finditer(r"INSERT INTO (\w+) \(([^)]*)\) VALUES \(([^)]*)\)", sql, re.S):
        nc = len([c for c in m.group(2).split(",") if c.strip()])
        nv = len([v for v in m.group(3).split(",") if v.strip()])
        assert nc == nv, f"{m.group(1)}: {nc} colunas x {nv} valores"
    # 18 campos do cliente (era 17) + por empresa
    base = 18 if ident else 1 + 19
    assert sql.count("?") == base + n_emp * (9 if ident else 11)


def test_cliCelular_atualiza_quando_preenchido():
    imp, cur = _montar(
        ClientesImportadorHeadless,
        {"cliId": "ID", "cliCelular": "CEL"},
        {"ID": "1234", "CEL": "63999887766"},
    )
    imp._atualizar_clientes()
    assert "cliCelular" in cur.sets_de("cliente")
    assert "63999887766" in cur.params_de("cliente")


def test_cliCelular_vazio_nao_apaga():
    """Mesma regra dos demais: célula vazia mantém o que está no banco."""
    imp, cur = _montar(
        ClientesImportadorHeadless,
        {"cliId": "ID", "cliNome": "NOME", "cliCelular": "CEL"},
        {"ID": "1234", "NOME": "FULANO", "CEL": "  "},
    )
    imp._atualizar_clientes()
    cols = cur.sets_de("cliente")
    assert "cliNome" in cols
    assert "cliCelular" not in cols, "celula vazia APAGARIA o celular existente"


def test_cliCelular_e_cortado_em_20(monkeypatch):
    """A coluna é varchar(20), igual ao cliFone — valor maior não pode estourar."""
    imp, cur = _montar(
        ClientesImportadorHeadless,
        {"cliId": "ID", "cliCelular": "CEL"},
        {"ID": "1234", "CEL": "9" * 30},
    )
    imp._atualizar_clientes()
    grav = [p for p in cur.params_de("cliente") if isinstance(p, str) and p.startswith("9")]
    assert grav and len(grav[0]) == 20, f"esperava corte em 20, veio {grav}"


def test_cliCelular_no_update_por_cpf():
    imp, cur = _por_cpf({"12345678901": [77]},
                        {"DOC": "12345678901", "NOME": "N"})
    imp.mapping = {"cliCpfCgc": "DOC", "cliCelular": "CEL"}
    imp.df = pd.DataFrame([{"DOC": "12345678901", "CEL": "63988776655"}])
    imp._atualizar_clientes_por_cpf()
    assert "cliCelular" in cur.sets_de("cliente")


# ══════════════════════════════════════════════════════════════════════════
# Corte de textos no UPDATE — os MESMOS limites do INSERT
# ══════════════════════════════════════════════════════════════════════════
# O INSERT sempre cortou cada texto no tamanho da coluna (_get_str_max); o UPDATE
# só cortava o cliFatEndNumero. Consequência: um cliNome de 60 caracteres ENTRAVA
# pelo INSERT (cortado em 50) e a MESMA linha morria no UPDATE com o erro 22001
# ("String or binary data would be truncated"), indo para o arquivo de erros sem
# motivo aparente para quem só olha o arquivo de origem.

# Tamanho real das colunas de texto de `cliente` (oráculo independente do código).
_LIM_CLI = {
    "cliCpfCgc":         20,
    "cliNome":           50,
    "cliFantasia":       50,
    "cliRgInsc":         20,
    "cliFatEnd":        120,
    "cliFatEndNumero":   10,
    "cliFatBairro":      70,
    "cliFatCidade":      30,
    "cliFatUf":           2,
    "cliFatCep":          9,
    "cliFatCidCodIBGE":  20,
    "cliEmail":         254,
    "cliFone":           20,
    "cliCelular":        20,
}


def _gravado_com_X(cur, tabela):
    """O valor de teste ("XXXX…") tal como foi para o banco no SET."""
    return [p for p in cur.params_de(tabela) if isinstance(p, str) and p.startswith("X")]


@pytest.mark.parametrize("campo,limite", sorted(_LIM_CLI.items()))
def test_update_cliente_corta_texto_no_tamanho_da_coluna(campo, limite):
    """Valor maior que a coluna: o UPDATE corta, igual ao INSERT (não estoura)."""
    imp, cur = _montar(
        ClientesImportadorHeadless,
        {"cliId": "ID", campo: "VAL"},
        {"ID": "1234", "VAL": "X" * (limite + 10)},
    )
    imp._atualizar_clientes()

    grav = _gravado_com_X(cur, "cliente")
    assert grav, f"{campo} preenchido tinha de entrar no SET"
    assert len(grav[0]) == limite, \
        f"{campo}: esperava corte em {limite}, veio {len(grav[0])} (erro 22001 no banco)"


@pytest.mark.parametrize(
    "campo,limite",
    sorted((c, l) for c, l in _LIM_CLI.items() if c != "cliCpfCgc"))  # é a chave
def test_update_por_cpf_corta_texto_no_tamanho_da_coluna(campo, limite):
    """Mesmo corte no UPDATE por CPF/CNPJ — é outro mapa_cli, divergiu antes."""
    imp, cur = _por_cpf({"12345678901": [77]}, {"DOC": "12345678901"})
    imp.mapping = {"cliCpfCgc": "DOC", campo: "VAL"}
    imp.df = pd.DataFrame([{"DOC": "12345678901", "VAL": "X" * (limite + 10)}])
    imp._atualizar_clientes_por_cpf()

    grav = _gravado_com_X(cur, "cliente")
    assert grav, f"{campo} preenchido tinha de entrar no SET"
    assert len(grav[0]) == limite, \
        f"{campo}: esperava corte em {limite}, veio {len(grav[0])}"


def test_texto_curto_nao_e_alterado_pelo_corte():
    """O corte só age no que passa do limite — não mexe no valor normal."""
    imp, cur = _montar(
        ClientesImportadorHeadless,
        {"cliId": "ID", "cliNome": "NOME"},
        {"ID": "1234", "NOME": "CLIENTE NORMAL"},
    )
    imp._atualizar_clientes()
    assert "CLIENTE NORMAL" in cur.params_de("cliente")


def test_insert_e_update_de_cliente_usam_a_MESMA_tabela_de_limites():
    """Um só lugar guarda o tamanho das colunas: foi a duplicação (números no
    INSERT, nada no UPDATE) que produziu a divergência."""
    from mi_importadores import ClientesImportMixin
    assert ClientesImportMixin.TAM_MAX == _LIM_CLI


# ── Produtos: mesmo contrato (INSERT e UPDATE já cortavam; fica travado) ──
_LIM_PROD = {"proDescricao": 100, "proUn": 10, "proTipo": 1}
_LIM_PROD_EMP = {"proCodCSOSN": 3, "proCodCst2": 2, "proCodigo": 50,
                 "proLocalizador": 20, "proPrateleira": 20}


@pytest.mark.parametrize("tabela,campo,limite", sorted(
    [("produto", c, l) for c, l in _LIM_PROD.items()] +
    [("produto_empresa", c, l) for c, l in _LIM_PROD_EMP.items()]))
def test_update_produto_corta_texto_no_tamanho_da_coluna(tabela, campo, limite):
    imp, cur = _montar(
        ProdutosImportadorHeadless,
        {"proId": "ID", campo: "VAL"},
        {"ID": "50", "VAL": "X" * (limite + 10)},
    )
    imp._atualizar_produtos()

    grav = _gravado_com_X(cur, tabela)
    assert grav, f"{campo} preenchido tinha de entrar no SET de {tabela}"
    assert len(grav[0]) == limite, \
        f"{campo}: esperava corte em {limite}, veio {len(grav[0])}"
