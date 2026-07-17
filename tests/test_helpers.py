"""Fase A — testes de regressão das FUNÇÕES PURAS do Max_Importa.

Sem GUI e sem banco. Para exercitar os métodos de parsing (que são métodos das
janelas mas só dependem de self.mapping), criamos a instância via __new__ — isso
NÃO roda __init__, então nenhuma janela é construída.

Cobre:
  - _to_decimal        (parsing numérico BR/US)
  - _get_int/_get_str  (leitura mapeada de células)
  - _get_str_max       (corte no tamanho da coluna — evita erro 22001)
  - _calc_cli_tipo     (deriva cliTipo de CPF/CNPJ)
  - DPAPI              (cifra/decifra a senha — round-trip e falhas)
  - [Conexao] no .ini  (persistência: sem plaintext, windows sem senha, limpeza)
  - _montar_msg_obrigatorios (contagem de obrigatórios em branco)
  - _exportar_resultado (logs estruturados JSON/CSV)
"""
import base64
import json
import types

import pandas as pd
import pytest

import max_importa as m
import mi_report   # funções de relatório/export vivem aqui após a refatoração
import mi_validacao as val   # regras de validação puras


def _fake(cls, mapping):
    """Instância da janela SEM __init__ (não abre GUI), só com o .mapping que os
    helpers de parsing precisam."""
    obj = cls.__new__(cls)
    obj.mapping = mapping
    return obj


# ─────────────────────────────────────────────────────────────────────────────
# _to_decimal — parsing numérico (vírgula decimal BR, ponto de milhar, lixo)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("entrada, esperado", [
    ("1.234,56",       1234.56),    # BR: ponto milhar + vírgula decimal
    ("1.234.567,89",   1234567.89), # BR com vários milhares
    ("1,5",            1.5),        # só vírgula → decimal
    ("1234.56",        1234.56),    # só ponto → decimal (US)
    ("-5,5",          -5.5),        # negativo
    ("R$ 1.234,56",    1234.56),    # símbolos são removidos
    ("0",              0.0),
    ("",               None),
    ("   ",            None),
    ("NULL",           None),
    ("abc",            None),
    (None,             None),
])
def test_to_decimal(entrada, esperado):
    # _to_decimal não usa self → chamável direto pela classe
    got = m.JanelaProdutos._to_decimal(None, entrada)
    if esperado is None:
        assert got is None
    else:
        assert got == pytest.approx(esperado)


# ─────────────────────────────────────────────────────────────────────────────
# _get_int / _get_str — leitura mapeada de células
# ─────────────────────────────────────────────────────────────────────────────
def test_get_int():
    obj = _fake(m.JanelaProdutos, {"proBalanca": "col"})
    assert obj._get_int({"col": "1"}, "proBalanca") == 1
    assert obj._get_int({"col": "1.0"}, "proBalanca") == 1        # "1.0" via float
    assert obj._get_int({"col": ""}, "proBalanca") is None        # vazio → default
    assert obj._get_int({"col": "NULL"}, "proBalanca") is None
    assert obj._get_int({"col": "abc"}, "proBalanca") is None     # inválido → default
    assert obj._get_int({"col": "5"}, "proBalanca", default=9) == 5
    assert obj._get_int({}, "campo_nao_mapeado", default=7) == 7  # sem mapping → default


def test_get_str():
    obj = _fake(m.JanelaProdutos, {"proDescricao": "col"})
    assert obj._get_str({"col": "  Café  "}, "proDescricao") == "Café"  # strip
    assert obj._get_str({"col": "NULL"}, "proDescricao") is None
    assert obj._get_str({"col": ""}, "proDescricao") is None
    assert obj._get_str({}, "campo_nao_mapeado") is None


def test_get_str_max_trunca():
    """Corte no tamanho da coluna do banco (evita o erro 'dados truncados')."""
    obj = _fake(m.JanelaProdutos, {"proDescricao": "col"})
    longo = "X" * 150
    assert obj._get_str_max({"col": longo}, "proDescricao", 100) == "X" * 100
    assert obj._get_str_max({"col": "curto"}, "proDescricao", 100) == "curto"
    assert obj._get_str_max({"col": "NULL"}, "proDescricao", 100) is None


# ─────────────────────────────────────────────────────────────────────────────
# _get_datetime — parsing de datas (regressão: s[:len(fmt)] truncava e perdia
# TODAS as datas na migração — pgtData/pgtVecmto iam NULL para o destino).
# ─────────────────────────────────────────────────────────────────────────────
from datetime import datetime as _dt

@pytest.mark.parametrize("entrada, esperado", [
    ("2026-03-01",                 _dt(2026, 3, 1)),               # ISO só data (o que quebrava)
    ("2026-03-01 12:34:56",        _dt(2026, 3, 1, 12, 34, 56)),   # ISO com hora
    ("2026-03-01 12:34:56.789000", _dt(2026, 3, 1, 12, 34, 56, 789000)),  # com microssegundos
    ("2026-03-01T12:34:56",        _dt(2026, 3, 1, 12, 34, 56)),   # ISO com 'T'
    ("01/03/2026",                 _dt(2026, 3, 1)),               # BR só data
    ("01/03/2026 12:34:56",        _dt(2026, 3, 1, 12, 34, 56)),   # BR com hora
    (_dt(2026, 3, 1, 12, 34, 56),  _dt(2026, 3, 1, 12, 34, 56)),   # já é datetime (migração)
    ("",                            None),
    ("NULL",                        None),
    ("lixo",                        None),
    (None,                          None),
])
def test_get_datetime(entrada, esperado):
    obj = _fake(m.JanelaFinanceiro, {"pgtData": "col"})
    assert obj._get_datetime({"col": entrada}, "pgtData") == esperado


def test_get_datetime_pandas_timestamp_e_nat():
    """Timestamp do pandas (subclasse de datetime) vem da migração; NaT -> NULL."""
    obj = _fake(m.JanelaFinanceiro, {"pgtData": "col"})
    assert obj._get_datetime({"col": pd.Timestamp("2026-03-01 08:00:00")}, "pgtData") == _dt(2026, 3, 1, 8)
    assert obj._get_datetime({"col": pd.NaT}, "pgtData") is None


# ─────────────────────────────────────────────────────────────────────────────
# Retry de erros transientes do SQL Server (deadlock/timeout/queda de conexão)
# ─────────────────────────────────────────────────────────────────────────────
def test_e_transiente_classifica():
    obj = _fake(m.JanelaFinanceiro, {})
    # TRANSIENTES (vale re-tentar)
    assert obj._e_transiente(Exception("Transaction was deadlocked ... victim. (1205)"))
    assert obj._e_transiente(Exception("Lock request time out period exceeded. (1222)"))
    assert obj._e_transiente(Exception("[HYT00] Query timeout expired"))
    assert obj._e_transiente(Exception("08S01", "Communication link failure"))   # sqlstate em args[0]
    # NÃO transientes (erro de DADOS — deve subir na hora)
    assert not obj._e_transiente(Exception("Violation of PRIMARY KEY constraint (2627)"))
    assert not obj._e_transiente(Exception("String or binary data would be truncated (8152)"))
    assert not obj._e_transiente(Exception("Cannot insert the value NULL (515)"))


def test_com_retry_repete_transiente_e_desiste_de_erro_de_dados(monkeypatch):
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda *a, **k: None)   # não espera de verdade
    obj = _fake(m.JanelaFinanceiro, {})
    obj._log = lambda *a, **k: None
    obj._cancelado = False

    # transiente: falha 2x, depois sucesso → retorna OK (3 chamadas)
    chamadas = {"n": 0}
    def op_transiente():
        chamadas["n"] += 1
        if chamadas["n"] < 3:
            raise Exception("deadlock (1205)")
        return "ok"
    assert obj._com_retry(op_transiente, tentativas=4) == "ok"
    assert chamadas["n"] == 3

    # erro de dados: sobe na 1ª tentativa, SEM re-tentar
    c2 = {"n": 0}
    def op_dados():
        c2["n"] += 1
        raise Exception("Violation of PRIMARY KEY (2627)")
    with pytest.raises(Exception):
        obj._com_retry(op_dados, tentativas=4)
    assert c2["n"] == 1


def test_com_retry_para_se_cancelado(monkeypatch):
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda *a, **k: None)
    obj = _fake(m.JanelaFinanceiro, {})
    obj._log = lambda *a, **k: None
    obj._cancelado = True                     # já cancelado
    c = {"n": 0}
    def op():
        c["n"] += 1
        raise Exception("deadlock (1205)")    # transiente, mas cancelado → não re-tenta
    with pytest.raises(Exception):
        obj._com_retry(op, tentativas=4)
    assert c["n"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# _calc_cli_tipo — deriva cliTipo (0=PF, 1=PJ) do CPF/CNPJ
# ─────────────────────────────────────────────────────────────────────────────
def test_calc_cli_tipo_deriva_cpf_cnpj():
    obj = _fake(m.JanelaClientes, {"cliCpfCgc": "doc"})   # cliTipo NÃO mapeado
    assert obj._calc_cli_tipo({"doc": "123.456.789-01"}) == 0   # 11 díg → PF
    assert obj._calc_cli_tipo({"doc": "12.345.678/0001-90"}) == 1  # 14 díg → PJ
    assert obj._calc_cli_tipo({"doc": ""}) is None              # vazio → None
    assert obj._calc_cli_tipo({"doc": "123"}) is None           # tamanho estranho → None


def test_calc_cli_tipo_mapeado_tem_prioridade():
    obj = _fake(m.JanelaClientes, {"cliTipo": "t", "cliCpfCgc": "doc"})
    # cliTipo explícito (1) vence, mesmo com CPF de 11 díg (que derivaria 0)
    assert obj._calc_cli_tipo({"t": "1", "doc": "123.456.789-01"}) == 1


def test_validar_conteudo_flags_coluna_que_esvaziou():
    """Reconciliação de CONTEÚDO: sinaliza quando uma coluna preenchida na origem
    chega quase vazia no destino (o padrão exato do bug de datas). Colunas com
    preenchimento coerente NÃO aparecem. Testa a lógica com conexões fake."""
    import re as _re
    mig = m.JanelaMigracao.__new__(m.JanelaMigracao)
    TOTAL = 1000
    ORIG = {"pgtData": 1.0, "pgtValor": 1.0, "pgtNumDoc": 0.4}
    DEST = {"pgtData": 0.0, "pgtValor": 1.0, "pgtNumDoc": 0.4}   # só a data caiu p/ 0

    class _Cur:
        def __init__(self, fills): self.fills = fills; self._r = None
        def execute(self, sql, *a):
            if "sys.columns" in sql:
                self._r = [(c,) for c in ("pgtData", "pgtValor", "pgtNumDoc")]
            else:
                col = _re.search(r"COUNT\(\[(\w+)\]\)", sql).group(1)
                self._r = (TOTAL, int(TOTAL * self.fills.get(col, 0)))
            return self
        def fetchall(self): return self._r
        def fetchone(self): return self._r

    class _Conn:
        def __init__(self, fills): self.fills = fills
        def cursor(self): return _Cur(self.fills)

    linhas = mig._validar_conteudo(_Conn(ORIG), _Conn(DEST), ["financeiro"])
    txt = "\n".join(linhas)
    assert "pgtData" in txt and "🔴" in txt          # data esvaziou → flag forte
    assert "pgtValor" not in txt                      # 100%→100% → não aparece
    assert "pgtNumDoc" not in txt                     # 40%→40% (coerente) → não aparece
    assert any("divergente" in l for l in linhas)     # resumo acusa divergência


def test_validar_conteudo_ok_quando_coerente():
    """Sem divergência → linha de resumo verde, sem flags."""
    import re as _re
    mig = m.JanelaMigracao.__new__(m.JanelaMigracao)
    fills = {"pgtData": 1.0, "pgtValor": 1.0, "pgtNumDoc": 0.4}

    class _Cur:
        def __init__(self): self._r = None
        def execute(self, sql, *a):
            if "sys.columns" in sql:
                self._r = [(c,) for c in ("pgtData", "pgtValor", "pgtNumDoc")]
            else:
                col = _re.search(r"COUNT\(\[(\w+)\]\)", sql).group(1)
                self._r = (1000, int(1000 * fills.get(col, 0)))
            return self
        def fetchall(self): return self._r
        def fetchone(self): return self._r

    class _Conn:
        def cursor(self): return _Cur()

    linhas = mig._validar_conteudo(_Conn(), _Conn(), ["financeiro"])
    assert any(l.startswith("✅ conteúdo") for l in linhas)
    assert not any("🔴" in l or "⚠️" in l for l in linhas)


def test_validar_integridade_fk_detecta_orfaos_e_fk_desabilitada():
    """Integridade referencial: reporta FK desabilitada (sem enforcement) e linhas
    órfãs (referência para pai inexistente). Testa com conexões fake."""
    import re as _re
    mig = m.JanelaMigracao.__new__(m.JanelaMigracao)
    ORFAOS = {"vendaPgto": 12}          # 12 lançamentos p/ cliente inexistente

    class _Cur:
        def __init__(self): self._r = None
        def execute(self, sql, *a):
            if "is_disabled = 1" in sql:                    # _fks_desabilitadas
                self._r = [("dbo", "cliente_empresa", "fk_ce_cli")]
            elif "sys.columns" in sql:                      # _cols
                self._r = [(c,) for c in ("cliId", "proId", "cdbIdProd", "pgtClienteId")]
            elif "COUNT(*)" in sql:                          # órfãos
                filha = _re.search(r"FROM \[(\w+)\]", sql).group(1)
                self._r = (ORFAOS.get(filha, 0),)
            return self
        def fetchall(self): return self._r
        def fetchone(self): return self._r

    class _Conn:
        def cursor(self): return _Cur()

    linhas = mig._validar_integridade_fk(_Conn(), ["clientes", "financeiro"])
    txt = "\n".join(linhas)
    assert "DESABILITADA" in txt                            # FK sem enforcement
    assert "12 linha(s) ÓRFÃ" in txt and "vendaPgto" in txt # órfãos detectados


def test_validar_integridade_fk_ok_quando_limpo():
    """Sem FK desabilitada e sem órfão → linha verde de resumo."""
    mig = m.JanelaMigracao.__new__(m.JanelaMigracao)

    class _Cur:
        def __init__(self): self._r = None
        def execute(self, sql, *a):
            if "is_disabled = 1" in sql:
                self._r = []                                # nenhuma FK desabilitada
            elif "sys.columns" in sql:
                self._r = [(c,) for c in ("cliId", "proId", "cdbIdProd", "pgtClienteId")]
            elif "COUNT(*)" in sql:
                self._r = (0,)                              # nenhum órfão
            return self
        def fetchall(self): return self._r
        def fetchone(self): return self._r

    class _Conn:
        def cursor(self): return _Cur()

    linhas = mig._validar_integridade_fk(_Conn(), ["financeiro"])
    assert any(l.startswith("✅ integridade referencial") for l in linhas)
    assert not any("🔴" in l for l in linhas)


def test_calc_cli_tipo_no_importador_headless():
    """Regressão: _calc_cli_tipo vive no ClientesImportMixin (não só na GUI), então
    o ClientesImportadorHeadless (usado pela migração) também o tem. Antes, ele era
    definido só na JanelaClientes → _inserir_clientes headless quebraria (mesma
    assinatura dos bugs de log_lines/_aviso_nao_encontrados)."""
    from mi_importadores import ClientesImportadorHeadless
    imp = ClientesImportadorHeadless(log=lambda *a, **k: None)
    imp.mapping = {"cliCpfCgc": "doc"}                 # cliTipo NÃO mapeado
    assert hasattr(imp, "_calc_cli_tipo")             # existe no headless (via mixin)
    assert imp._calc_cli_tipo({"doc": "123.456.789-01"}) == 0     # CPF → PF
    assert imp._calc_cli_tipo({"doc": "12.345.678/0001-90"}) == 1  # CNPJ → PJ
    assert imp._calc_cli_tipo({"doc": ""}) is None


# ─────────────────────────────────────────────────────────────────────────────
# DPAPI — cifra/decifra da senha salva
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("segredo", [
    "senha-fake-teste",
    "S3nh@ com acento çãõ e símbolos !@#%^&*()",
    "x" * 500,
])
def test_dpapi_roundtrip(segredo):
    cifrado = m._dpapi_encrypt(segredo)
    assert cifrado is not None
    assert segredo not in cifrado                 # não é texto puro
    assert "%" not in cifrado                     # base64 seguro p/ configparser
    assert m._dpapi_decrypt(cifrado) == segredo   # volta idêntico


def test_dpapi_vazio_e_lixo():
    assert m._dpapi_encrypt("") is None                 # nada a cifrar
    assert m._dpapi_decrypt("") is None
    lixo = base64.b64encode(b"isto-nao-e-dpapi").decode()
    assert m._dpapi_decrypt(lixo) is None               # falha graciosa, sem crash


# ─────────────────────────────────────────────────────────────────────────────
# Persistência das credenciais ([Conexao] no .ini)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def ini_tmp(tmp_path, monkeypatch):
    """Aponta _INI_PATH para um arquivo temporário durante o teste. Como
    _get_conexao/_set_conexao vivem em mi_config, o patch é feito lá."""
    import mi_config
    caminho = str(tmp_path / "max_importa.ini")
    monkeypatch.setattr(mi_config, "_INI_PATH", caminho)
    return caminho


def test_conexao_sql_lembrar_cifra_senha(ini_tmp):
    m._set_conexao("SRV\\INST", "sa", "sql", "senha-fake-teste", True)
    cx = m._get_conexao()
    assert cx == {"servidor": "SRV\\INST", "usuario": "sa", "auth": "sql",
                  "senha": "senha-fake-teste", "lembrar": True}
    # a senha NÃO pode aparecer em texto puro no arquivo
    with open(ini_tmp, encoding="utf-8") as f:
        conteudo = f.read()
    assert "senha-fake-teste" not in conteudo
    assert "[Conexao]" in conteudo


def test_conexao_windows_nao_grava_senha(ini_tmp):
    m._set_conexao("SRV\\INST", "sa", "windows", "ignorada", True)
    cx = m._get_conexao()
    assert cx["auth"] == "windows"
    assert cx["senha"] == ""          # windows auth não guarda senha
    with open(ini_tmp, encoding="utf-8") as f:
        assert "ignorada" not in f.read()


def test_conexao_sem_lembrar_remove_secao(ini_tmp):
    m._set_conexao("SRV\\INST", "sa", "sql", "senha-fake-teste", True)   # grava
    m._set_conexao("SRV\\INST", "sa", "sql", "senha-fake-teste", False)  # desmarca lembrar
    with open(ini_tmp, encoding="utf-8") as f:
        assert "[Conexao]" not in f.read()   # nada sensível fica em disco
    cx = m._get_conexao()
    assert cx["lembrar"] is False
    assert cx["servidor"] is None            # volta aos defaults


# ─────────────────────────────────────────────────────────────────────────────
# _montar_msg_obrigatorios — contagem de campos obrigatórios em branco
# ─────────────────────────────────────────────────────────────────────────────
def test_montar_msg_obrigatorios_conta(monkeypatch):
    # evita escrever arquivo de erros no disco durante o teste
    monkeypatch.setattr(mi_report, "_gerar_arquivo_erros", lambda *a, **k: None)
    invalidos = {"proDescricao": [2, 3], "proCodigo": [3]}
    descr = {"proDescricao": "Descrição", "proCodigo": "Código Interno"}
    msg, ep, total, n_linhas = m._montar_msg_obrigatorios(invalidos, descr, "PRODUTOS")
    assert total == 3            # 2 + 1 células
    assert n_linhas == 2         # linhas distintas afetadas: {2, 3}
    assert ep is None
    assert "Descrição" in msg    # usa o nome amigável na mensagem


# ─────────────────────────────────────────────────────────────────────────────
# _exportar_resultado — logs estruturados (JSON de resumo + CSV de erros)
# ─────────────────────────────────────────────────────────────────────────────
def _fake_win(**kw):
    base = {"_ultimo_resultado": {"inseridos": 0, "pulados": 0, "erros": 0},
            "conn": None, "csv_path": None, "_log": lambda *a, **k: None}
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_exportar_resultado_json_e_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(mi_report, "_get_log_dir", lambda: str(tmp_path))
    win = _fake_win(_ultimo_resultado={"inseridos": 3, "pulados": 1, "erros": 2},
                    csv_path=r"C:\dados\produtos.txt")
    mi_report._exportar_resultado(win, "PRODUTOS", ["Item A", "Item B"])

    jsons = list(tmp_path.glob("RESULTADO_PRODUTOS_*.json"))
    assert len(jsons) == 1
    dados = json.loads(jsons[0].read_text(encoding="utf-8"))
    assert dados["operacao"] == "PRODUTOS"
    assert dados["app_version"] == m.APP_VERSION
    assert dados["resultado"] == {"inseridos": 3, "pulados": 1, "erros": 2}
    assert dados["itens_com_erro"] == ["Item A", "Item B"]
    assert dados["arquivo"] == "produtos.txt"
    assert dados["banco"] == ""          # conn=None → DB_NAME() indisponível

    csvs = list(tmp_path.glob("ERROS_PRODUTOS_*.csv"))
    assert len(csvs) == 1
    conteudo = csvs[0].read_text(encoding="utf-8-sig")
    assert "item_com_erro" in conteudo
    assert "Item A" in conteudo and "Item B" in conteudo


def test_exportar_resultado_sem_erros_nao_gera_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(mi_report, "_get_log_dir", lambda: str(tmp_path))
    win = _fake_win(_ultimo_resultado={"inseridos": 5, "pulados": 0, "erros": 0})
    mi_report._exportar_resultado(win, "CLIENTES", [])
    assert len(list(tmp_path.glob("RESULTADO_CLIENTES_*.json"))) == 1
    assert list(tmp_path.glob("ERROS_CLIENTES_*.csv")) == []   # sem erros → sem CSV


# ─────────────────────────────────────────────────────────────────────────────
# mi_validacao — regras puras dos _iniciar (sem GUI/banco)
# ─────────────────────────────────────────────────────────────────────────────
def test_campos_nao_mapeados():
    assert val.campos_nao_mapeados({"a": "x"}, ["a", "b", "c"]) == ["b", "c"]
    assert val.campos_nao_mapeados({"a": "x", "b": "y"}, ["a", "b"]) == []


def test_validar_obrigatorios_insert():
    # mapping: campo->coluna; df com uma célula vazia e um NULL textual
    df = pd.DataFrame([
        {"cnpj": "123", "nome": "ACME"},
        {"cnpj": "",    "nome": "NULL"},
        {"cnpj": "456", "nome": "  "},
    ])
    mapping = {"cliCpfCgc": "cnpj", "cliNome": "nome"}
    inv = val.validar_obrigatorios(df, mapping, ["cliCpfCgc", "cliNome"])
    # linha de arquivo = idx+2 → linhas 3 (cnpj vazio), 3 e 4 (nome NULL/branco)
    assert inv == {"cliCpfCgc": [3], "cliNome": [3, 4]}


def test_validar_obrigatorios_update_apenas_mapeados():
    df = pd.DataFrame([{"nome": ""}])          # cliNome mapeado e vazio
    mapping = {"cliNome": "nome"}               # cliCpfCgc NÃO mapeado
    inv = val.validar_obrigatorios(df, mapping, ["cliCpfCgc", "cliNome"],
                                   apenas_mapeados=True)
    assert inv == {"cliNome": [2]}              # só o mapeado é cobrado


def test_linhas_ao_menos_um():
    df = pd.DataFrame([
        {"v": "1", "p": ""},     # ok (vista preenchido)
        {"v": "",  "p": "2"},    # ok (prazo preenchido)
        {"v": "",  "p": ""},     # erro: ambos vazios → linha 4
    ])
    mapping = {"pgtTipoVista": "v", "pgtTipoPrazo": "p"}
    assert val.linhas_ao_menos_um(df, mapping, "pgtTipoVista", "pgtTipoPrazo") == [4]
    # nenhum dos dois mapeado → nada a validar
    assert val.linhas_ao_menos_um(df, {}, "pgtTipoVista", "pgtTipoPrazo") == []


def test_ids_reservados():
    df = pd.DataFrame([{"id": "5"}, {"id": "10"}, {"id": "3"}, {"id": ""}, {"id": "x"}])
    mapping = {"cliId": "id"}
    assert val.ids_reservados(df, mapping, "cliId", limite=10) == [5, 3]
    # campo não mapeado → []
    assert val.ids_reservados(df, {}, "cliId") == []


# ─────────────────────────────────────────────────────────────────────────────
# _atualizar_status_mapeamento — feedback visual do mapeamento (lógica, sem GUI)
# ─────────────────────────────────────────────────────────────────────────────
class _FakeVar:
    def __init__(self, v): self._v = v
    def get(self): return self._v


class _FakeLabel:
    def __init__(self): self.kw = {}
    def configure(self, **kw): self.kw.update(kw)


def _obj_status(mapping_vals, obrigatorios):
    """JanelaProdutos via __new__ (herda o método do CancelavelMixin), com vars/labels/
    frames falsos — testa só a lógica de ✓/✗/—, o resumo e a recoloração da linha, sem
    abrir janela."""
    obj = m.JanelaProdutos.__new__(m.JanelaProdutos)
    obj.CAMPOS_OBRIGATORIOS = set(obrigatorios)
    obj.mapping_vars = {c: _FakeVar(v) for c, v in mapping_vals.items()}
    obj.map_status = {c: _FakeLabel() for c in mapping_vals}
    obj.map_rows = {c: _FakeLabel() for c in mapping_vals}      # frame falso da linha
    obj.map_row_bg = {c: "transparent" for c in mapping_vals}   # cor original
    obj.lbl_map_resumo = _FakeLabel()
    obj._atualizar_status_mapeamento()
    return obj


def test_status_mapeamento_marca_e_avisa_faltantes():
    obj = _obj_status(
        {"a": "col1", "b": "[ ignorar ]", "c": "[ ignorar ]"},  # b (obrig) e c (opc) vazios
        obrigatorios=["a", "b"])
    assert obj.map_status["a"].kw["text"] == "✓"   # mapeado
    assert obj.map_status["b"].kw["text"] == "✗"   # obrigatório vazio
    assert obj.map_status["c"].kw["text"] == "—"   # opcional vazio
    # linha mapeada fica verde suave; não mapeada volta à cor original
    assert obj.map_rows["a"].kw["fg_color"] == obj._ROW_OK_BG
    assert obj.map_rows["b"].kw["fg_color"] == "transparent"
    txt = obj.lbl_map_resumo.kw["text"]
    assert "1/3" in txt and "faltam obrigatórios" in txt and "b" in txt


def test_status_mapeamento_todos_obrigatorios_ok():
    obj = _obj_status(
        {"a": "col1", "b": "col2", "c": "[ ignorar ]"},   # obrig a,b mapeados
        obrigatorios=["a", "b"])
    txt = obj.lbl_map_resumo.kw["text"]
    assert txt.startswith("✓") and "2/3" in txt and "obrigatórios OK" in txt


# ─────────────────────────────────────────────────────────────────────────────
# Migração Max→Max: importador HEADLESS precisa de log_lines
# Regressão: a JanelaMigracao injeta seu _log, que espelha cada linha em
# _imp_atual.log_lines. Sem esse atributo no headless, _inserir_produtos/
# _financeiro quebravam com AttributeError e a migração parava nos Produtos.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("classe_nome", [
    "ProdutosImportadorHeadless",
    "ClientesImportadorHeadless",
    "FinanceiroImportadorHeadless",
])
def test_headless_tem_log_lines_e_espelha(classe_nome):
    import mi_importadores as mi

    class _FakeMig:
        """Reproduz JanelaMigracao._log (espelha no relatório da entidade)."""
        def __init__(self):
            self.log_lines = []
            self._imp_atual = None
        def _log(self, msg):
            self.log_lines.append(msg)
            if self._imp_atual is not None:
                self._imp_atual.log_lines.append(msg)

    mig = _FakeMig()
    imp = getattr(mi, classe_nome)(log=mig._log)   # como _get_importador
    assert imp.log_lines == []                     # atributo existe já no __init__
    mig._imp_atual = imp                           # como _migrar_entidade
    imp._log("Iniciando INSERT — 1 registro")      # antes: AttributeError
    assert imp.log_lines == mig.log_lines and len(imp.log_lines) == 1


# ─────────────────────────────────────────────────────────────────────────────
# Cancelamento da migração deve PROPAGAR para o importador headless em execução.
# Regressão: o loop do importador checa self._cancelado (o DELE). Se o cancelamento
# só setasse o flag da janela, uma entidade grande (financeiro 140k linhas) não
# pararia. _pedir_cancelamento agora também seta _imp_atual._cancelado.
# ─────────────────────────────────────────────────────────────────────────────
def test_cancelamento_propaga_para_importador_headless():
    from mi_importadores import FinanceiroImportadorHeadless

    # Objeto com o comportamento do CancelavelMixin, sem GUI (via __new__).
    obj = m.CancelavelMixin.__new__(m.CancelavelMixin)
    obj._cancelado = False
    obj._log = lambda *a, **k: None        # _pedir_cancelamento chama self._log
    imp = FinanceiroImportadorHeadless(log=obj._log)
    obj._imp_atual = imp                    # entidade em andamento

    assert imp._cancelado is False
    obj._pedir_cancelamento()
    assert obj._cancelado is True
    assert imp._cancelado is True           # propagou → o loop do importador vai parar


# ─────────────────────────────────────────────────────────────────────────────
# GUARD-RAIL estrutural (#10): nenhum mixin de importação pode depender de um
# atributo que SÓ a GUI provê e que o importador HEADLESS (migração) não tem. Foi
# a causa-raiz de 4 bugs desta linha (log_lines, _aviso_nao_encontrados,
# _cancelado mal-propagado, _calc_cli_tipo). Este teste é a auditoria AST que
# achou o _calc_cli_tipo, agora permanente: qualquer nova dependência assim FALHA.
# ─────────────────────────────────────────────────────────────────────────────
def test_mixins_import_nao_dependem_de_atributos_so_da_gui():
    import ast
    import os

    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def _classes(arquivo):
        with open(os.path.join(raiz, arquivo), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}

    imp = _classes("mi_importadores.py")
    db = _classes("mi_db.py")

    def _providos(cls):
        """métodos + constantes de classe + atributos setados via self.X = ..."""
        nomes = set()
        # membros diretos do corpo da classe: métodos e constantes de classe
        # (ex.: _SQL_INS_VENDAPGTO). Só o corpo direto — não locais de métodos.
        for n in cls.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nomes.add(n.name)
            elif isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        nomes.add(t.id)
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                nomes.add(n.target.id)
        # atributos de instância setados via self.X = ... (em qualquer método)
        for n in ast.walk(cls):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if (isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name)
                            and t.value.id == "self"):
                        nomes.add(t.attr)
        return nomes

    def _usados(cls):
        return {n.attr for n in ast.walk(cls)
                if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                and n.value.id == "self" and isinstance(n.ctx, ast.Load)}

    # Providos a TODO headless: _ImportadorHeadless + MapeamentoDBMixin.
    comum = _providos(imp["_ImportadorHeadless"]) | _providos(db["MapeamentoDBMixin"])
    # Atributos setados de fora pela migração (ver JanelaMigracao._migrar_entidade).
    externos = {"conn", "df", "mapping", "_ultimo_resultado", "nao_encontrados",
                "_dedup_financeiro", "FLOAT_NOT_NULL"}
    # GUI-only cujo uso nos mixins é COMPROVADAMENTE seguro no headless:
    #   btn_import / btn_acerto → só dentro de self.after(0, lambda: ...); no headless
    #     after() é no-op e a lambda nunca chega a acessar o atributo.
    #   _aviso_nao_encontrados → protegido por hasattr(self, ...) antes do uso.
    # Adicionar aqui SÓ com justificativa — cada item é uma dependência GUI consciente.
    allowlist_gui_seguro = {"btn_import", "btn_acerto", "_aviso_nao_encontrados"}

    problemas = {}
    for mixin in ("ProdutosImportMixin", "ClientesImportMixin", "FinanceiroImportMixin"):
        provido = comum | _providos(imp[mixin]) | externos
        suspeitos = {a for a in _usados(imp[mixin])
                     if a not in provido and not a.startswith("__")
                     and a not in allowlist_gui_seguro}
        if suspeitos:
            problemas[mixin] = sorted(suspeitos)

    assert not problemas, (
        "Mixin(s) de importação usam self.X que só a GUI provê e o headless não tem "
        "(quebraria na migração, como os bugs de log_lines/_calc_cli_tipo). Mova a "
        "lógica para o mixin; ou, se for lazy (after-lambda) / hasattr e comprovadamente "
        "seguro, liste em allowlist_gui_seguro com justificativa. Suspeitos: " + repr(problemas))
