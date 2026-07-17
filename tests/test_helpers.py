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
