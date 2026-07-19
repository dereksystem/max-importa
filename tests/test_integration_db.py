"""Fase B — testes de INTEGRAÇÃO contra um banco MaxData real (descartável).

Rodam contra BD_ZERO_TEST (cópia do BD_ZERO), com revert de snapshot a cada teste
(ver conftest.py). Fazem SKIP automático se o SQL Server de teste não responder.

Estratégia p/ rodar a lógica real sem GUI: cria a janela via __new__ (não roda
__init__, não abre tela) e injeta só o que o worker usa — conexão, DataFrame,
mapping — com stubs para as chamadas de interface (_log, after, progress, etc.).
"""
import types
import uuid
from datetime import datetime

import pandas as pd
import pytest

import max_importa as m
from conftest import SRC_DB, SERVER, USER, PWD

# Todos os testes deste arquivo são de integração (exigem o SQL Server de teste).
pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _sem_export_arquivos(monkeypatch):
    """Evita que os testes de integração escrevam RESULTADO_*.json/ERROS_*.csv
    na pasta Log real (o export é testado em test_helpers.py). Após a refatoração,
    _pos_importacao chama _exportar_resultado no módulo mi_report."""
    import mi_report
    monkeypatch.setattr(mi_report, "_exportar_resultado", lambda *a, **k: None)


def _stub_gui(obj):
    """Aplica os stubs comuns de GUI a uma janela criada via __new__."""
    obj._cancelado = False
    obj.csv_path = None
    obj._logs = []
    obj._log = lambda msg, o=obj: o._logs.append(str(msg))
    obj.after = lambda *a, **k: None                  # ignora updates de GUI
    obj.progress = types.SimpleNamespace(set=lambda *a, **k: None)
    obj.btn_import = types.SimpleNamespace(configure=lambda *a, **k: None)
    obj._salvar_relatorio = lambda *a, **k: None       # sem escrever relatório
    return obj


def _harness_produtos(conn, df, mapping):
    """JanelaProdutos headless pronta para chamar _inserir_produtos()."""
    obj = m.JanelaProdutos.__new__(m.JanelaProdutos)   # sem __init__ → sem GUI
    obj.conn = conn
    obj.df = df
    obj.mapping = mapping
    _stub_gui(obj)
    obj._verificar_acerto_apos_sucesso = lambda *a, **k: None
    return obj


def _harness_clientes(conn, df, mapping):
    """JanelaClientes headless pronta para chamar _inserir_clientes()."""
    obj = m.JanelaClientes.__new__(m.JanelaClientes)
    obj.conn = conn
    obj.df = df
    obj.mapping = mapping
    _stub_gui(obj)
    return obj


def _harness_financeiro(conn, df, mapping):
    """JanelaFinanceiro headless pronta para chamar _inserir_financeiro()."""
    obj = m.JanelaFinanceiro.__new__(m.JanelaFinanceiro)
    obj.conn = conn
    obj.df = df
    obj.mapping = mapping
    _stub_gui(obj)
    obj.nao_encontrados = []
    return obj


def _harness_migracao(origem_db):
    """JanelaMigracao headless para chamar as rotinas de migração (próprias, as que
    reusam o importador HEADLESS via _get_importador, e o orquestrador _migrar)."""
    obj = m.JanelaMigracao.__new__(m.JanelaMigracao)
    obj._origem = origem_db
    obj._totais = {}
    obj._opcoes = {"cli_ciente": True, "cli_duplicados": "manter"}
    obj._imp = {}                 # cache de importadores (produtos/financeiro)
    obj._imp_atual = None
    obj._estoque_obs = None
    obj._acerto_info = None
    obj._cancelado = False
    obj.after = lambda *a, **k: None      # _migrar/_set_progresso agendam GUI via after
    obj._logs = []
    obj._log = lambda msg, o=obj: o._logs.append(str(msg))
    return obj


def _zerar_auditoria(conn):
    """Esvazia MaxImporta_Auditoria no destino (se existir). O BD_ZERO pode já conter
    linhas de auditoria de migrações reais anteriores — que a cópia de teste herda e o
    revert de snapshot não limpa — então os testes que CONTAM auditoria as zeram antes."""
    cur = conn.cursor()
    if cur.execute("SELECT OBJECT_ID('dbo.MaxImporta_Auditoria')").fetchone()[0] is not None:
        cur.execute("DELETE FROM MaxImporta_Auditoria")
        conn.commit()


def _ncm_existente(cur):
    row = cur.execute(
        "SELECT TOP 1 ncmCodigoNCM FROM proNCM "
        "WHERE ncmCodigoNCM IS NOT NULL ORDER BY ncmId").fetchone()
    return row[0] if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Smoke — a cópia subiu e as tabelas-base respondem
# ─────────────────────────────────────────────────────────────────────────────
def test_copia_subiu_e_tabelas_respondem(db_conn):
    cur = db_conn.cursor()
    for tabela in ("cliente", "produto", "produto_empresa", "vendaPgto", "config"):
        n = cur.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
        assert n >= 0


# ─────────────────────────────────────────────────────────────────────────────
# Importação de produtos (proId AUTO, unidade auto-criada, vínculo empresa)
# ─────────────────────────────────────────────────────────────────────────────
def test_import_produtos_basico(db_conn):
    cur = db_conn.cursor()
    ncm = _ncm_existente(cur)
    prod_antes = cur.execute("SELECT COUNT(*) FROM produto").fetchone()[0]
    un_antes = cur.execute("SELECT COUNT(*) FROM produtoUn WHERE UPPER(unpUn)='UTST'").fetchone()[0]
    assert un_antes == 0    # unidade de teste não existe ainda

    tag = uuid.uuid4().hex[:8].upper()
    campos = ["proId", "proDescricao", "proCodCst2", "proCodigo", "proUn",
              "ncmCodigoNCM", "proVenda", "proEstoqueAtual"]
    mapping = {c: c for c in campos}
    df = pd.DataFrame([
        {"proId": "", "proDescricao": f"PROD {tag} A", "proCodCst2": "00",
         "proCodigo": f"{tag}A", "proUn": "UTST", "ncmCodigoNCM": ncm,
         "proVenda": "10,50", "proEstoqueAtual": "5"},
        {"proId": "", "proDescricao": f"PROD {tag} B", "proCodCst2": "00",
         "proCodigo": f"{tag}B", "proUn": "UTST", "ncmCodigoNCM": ncm,
         "proVenda": "20", "proEstoqueAtual": "0"},
    ])

    obj = _harness_produtos(db_conn, df, mapping)
    obj._inserir_produtos()

    # resultado reportado pelo próprio worker
    assert obj._ultimo_resultado == {"inseridos": 2, "pulados": 0, "erros": 0}, obj._logs[-5:]

    cur = db_conn.cursor()
    assert cur.execute("SELECT COUNT(*) FROM produto").fetchone()[0] == prod_antes + 2
    # produto_empresa vinculado aos 2 novos produtos
    pe = cur.execute(
        "SELECT COUNT(*) FROM produto_empresa pe "
        "JOIN produto p ON p.proId = pe.proId "
        "WHERE p.proDescricao LIKE ?", f"PROD {tag}%").fetchone()[0]
    assert pe == 2
    # unidade 'UTST' cadastrada automaticamente em produtoUn
    assert cur.execute("SELECT COUNT(*) FROM produtoUn WHERE UPPER(unpUn)='UTST'").fetchone()[0] == 1
    # preço convertido (10,50 -> 10.5)
    venda = cur.execute(
        "SELECT pe.proVenda FROM produto_empresa pe "
        "JOIN produto p ON p.proId = pe.proId "
        "WHERE p.proDescricao = ?", f"PROD {tag} A").fetchone()[0]
    assert float(venda) == pytest.approx(10.5)


def test_import_produtos_trunca_descricao(db_conn):
    """proDescricao acima de 100 chars deve ser cortada no INSERT (evita erro 22001)."""
    cur = db_conn.cursor()
    ncm = _ncm_existente(cur)
    tag = uuid.uuid4().hex[:8].upper()
    desc_longa = "X" * 150
    mapping = {c: c for c in ["proId", "proDescricao", "proCodCst2", "proCodigo",
                              "proUn", "ncmCodigoNCM"]}
    df = pd.DataFrame([{
        "proId": "", "proDescricao": desc_longa, "proCodCst2": "00",
        "proCodigo": f"{tag}T", "proUn": "UN", "ncmCodigoNCM": ncm,
    }])

    obj = _harness_produtos(db_conn, df, mapping)
    obj._inserir_produtos()
    assert obj._ultimo_resultado["inseridos"] == 1, obj._logs[-5:]

    cur = db_conn.cursor()
    guardada = cur.execute(
        "SELECT p.proDescricao FROM produto p "
        "JOIN produto_empresa pe ON pe.proId = p.proId "
        "WHERE pe.proCodigo = ?", f"{tag}T").fetchone()[0]
    assert len(guardada) == 100
    assert guardada == "X" * 100


def test_revert_isola_testes(db_conn):
    """Prova que o snapshot isola cada teste: a unidade sintética 'UTST' (criada
    só pelos testes de importação anteriores) NÃO deve existir após o revert."""
    cur = db_conn.cursor()
    assert cur.execute(
        "SELECT COUNT(*) FROM produtoUn WHERE UPPER(unpUn)='UTST'").fetchone()[0] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Importação de CLIENTES (cliId AUTO, vínculo cliente_empresa, cliTipo derivado)
# ─────────────────────────────────────────────────────────────────────────────
def _linha_cliente(tag, sufixo, cpf):
    return {
        "cliId": "", "cliCpfCgc": cpf, "cliNome": f"CLIENTE {tag} {sufixo}",
        "cliFantasia": f"FANT {tag}{sufixo}", "cliRgInsc": "ISENTO",
        "cliFatEnd": "RUA TESTE", "cliFatEndNumero": "100",
        "cliFatBairro": "CENTRO", "cliFatCidade": "SAO PAULO",
        "cliFatUf": "SP", "cliFatCep": "01000-000", "cliFatCidCodIBGE": "3550308",
    }


def test_import_clientes_basico(db_conn):
    cur = db_conn.cursor()
    cli_antes = cur.execute("SELECT COUNT(*) FROM cliente").fetchone()[0]
    tag = uuid.uuid4().hex[:8].upper()
    campos = ["cliId", "cliCpfCgc", "cliNome", "cliFantasia", "cliRgInsc",
              "cliFatEnd", "cliFatEndNumero", "cliFatBairro", "cliFatCidade",
              "cliFatUf", "cliFatCep", "cliFatCidCodIBGE"]
    mapping = {c: c for c in campos}
    # 1 CNPJ (14 díg → cliTipo=1/PJ) e 1 CPF (11 díg → cliTipo=0/PF)
    df = pd.DataFrame([
        _linha_cliente(tag, "PJ", "12345678000190"),
        _linha_cliente(tag, "PF", "12345678901"),
    ])

    obj = _harness_clientes(db_conn, df, mapping)
    obj._inserir_clientes()
    assert obj._ultimo_resultado == {"inseridos": 2, "pulados": 0, "erros": 0}, obj._logs[-6:]

    cur = db_conn.cursor()
    assert cur.execute("SELECT COUNT(*) FROM cliente").fetchone()[0] == cli_antes + 2
    # vínculo cliente_empresa para os 2 novos
    pe = cur.execute(
        "SELECT COUNT(*) FROM cliente_empresa ce JOIN cliente c ON c.cliId = ce.cliId "
        "WHERE c.cliNome LIKE ?", f"CLIENTE {tag}%").fetchone()[0]
    assert pe == 2
    # cliTipo derivado do CPF/CNPJ
    tipo_pj = cur.execute("SELECT cliTipo FROM cliente WHERE cliNome = ?",
                          f"CLIENTE {tag} PJ").fetchone()[0]
    tipo_pf = cur.execute("SELECT cliTipo FROM cliente WHERE cliNome = ?",
                          f"CLIENTE {tag} PF").fetchone()[0]
    assert tipo_pj == 1   # CNPJ → Pessoa Jurídica
    assert tipo_pf == 0   # CPF  → Pessoa Física


# ─────────────────────────────────────────────────────────────────────────────
# Importação de FINANCEIRO (lookup CPF→cliId; não-encontrado é pulado)
# ─────────────────────────────────────────────────────────────────────────────
def test_import_financeiro_lookup_cliente(db_conn):
    tag = uuid.uuid4().hex[:8].upper()
    cpf_ok = "11222333000181"      # CNPJ VÁLIDO (dígito verificador confere)

    # 1) cria um cliente com CPF conhecido (reusa o importador de clientes)
    map_cli = {c: c for c in _linha_cliente(tag, "FIN", cpf_ok).keys()}
    obj_cli = _harness_clientes(db_conn, pd.DataFrame([_linha_cliente(tag, "FIN", cpf_ok)]), map_cli)
    obj_cli._inserir_clientes()
    assert obj_cli._ultimo_resultado["inseridos"] == 1, obj_cli._logs[-6:]
    cur = db_conn.cursor()
    cli_id = cur.execute("SELECT cliId FROM cliente WHERE cliCpfCgc = ?", cpf_ok).fetchone()[0]

    # 2) 2 lançamentos: um com CPF existente, outro inexistente (deve ser pulado)
    campos = ["cliCpfCgc", "pgtCliNome", "pgtValor", "pgtData", "pgtVecmto",
              "pgtTipoConta", "pgtPago", "pgtTipoVista"]
    mapping = {c: c for c in campos}
    # pgtData em formato BR-traço (04-07-2026) exercita, ponta-a-ponta, os formatos
    # que antes iam NULL em silêncio; pgtVecmto em ISO. Ambos DEVEM chegar ao banco.
    df = pd.DataFrame([
        # pgtPago="C" (Concluído, como vinha nos arquivos/modelo antigo) DEVE ser
        # normalizado para "S" — o Max espera S = Concluído / N = Aberto.
        {"cliCpfCgc": cpf_ok, "pgtCliNome": f"CLIENTE {tag} FIN", "pgtValor": "150,75",
         "pgtData": "04-07-2026", "pgtVecmto": "2026-08-04", "pgtTipoConta": "R",
         "pgtPago": "C", "pgtTipoVista": "1"},
        {"cliCpfCgc": "00000000000000", "pgtCliNome": "INEXISTENTE", "pgtValor": "10",
         "pgtData": "2026-07-04", "pgtVecmto": "2026-08-04", "pgtTipoConta": "R",
         "pgtPago": "N", "pgtTipoVista": "1"},
    ])
    obj_fin = _harness_financeiro(db_conn, df, mapping)
    obj_fin._inserir_financeiro()

    assert obj_fin._ultimo_resultado["inseridos"] == 1, obj_fin._logs[-6:]
    assert len(obj_fin.nao_encontrados) == 1     # o CPF inexistente foi pulado

    cur = db_conn.cursor()
    row = cur.execute(
        "SELECT pgtClienteId, pgtValor, pgtData, pgtVecmto, pgtPago FROM vendaPgto "
        "WHERE pgtClienteId = ?", cli_id).fetchone()
    assert row is not None
    assert row[0] == cli_id
    assert float(row[1]) == pytest.approx(150.75)
    # As datas NÃO podem chegar NULL (regressão do bug 3.6.9 + formatos ampliados):
    assert row[2] is not None and row[2].date() == datetime(2026, 7, 4).date()
    assert row[3] is not None and row[3].date() == datetime(2026, 8, 4).date()
    # pgtPago normalizado: "C" do arquivo → "S" (Concluído) no banco.
    assert row[4] == "S", f"pgtPago deveria ser 'S', veio {row[4]!r}"
    # Regra de negócio: o CPF/CNPJ "00000000000000" da 2ª linha é inválido (dígito
    # verificador) e deve ter sido SINALIZADO — é o que explica o "não encontrado".
    assert obj_fin._alertas_regras.get("CPF/CNPJ inválido") == 1
    assert any("QUALIDADE DOS DADOS" in l for l in obj_fin._resumo_alertas())


def test_import_financeiro_dry_run_nao_grava(db_conn):
    """DRY-RUN: a simulação NÃO pode inserir nenhuma linha em vendaPgto, mas ainda
    reporta quantas SERIAM inseridas e quais CPFs não seriam encontrados."""
    cur = db_conn.cursor()
    antes = cur.execute("SELECT COUNT(*) FROM vendaPgto").fetchone()[0]

    tag = uuid.uuid4().hex[:8].upper()
    cpf_ok = "99888777000199"
    map_cli = {c: c for c in _linha_cliente(tag, "DRY", cpf_ok).keys()}
    obj_cli = _harness_clientes(db_conn, pd.DataFrame([_linha_cliente(tag, "DRY", cpf_ok)]), map_cli)
    obj_cli._inserir_clientes()

    campos = ["cliCpfCgc", "pgtCliNome", "pgtValor", "pgtData", "pgtVecmto",
              "pgtTipoConta", "pgtPago", "pgtTipoVista"]
    mapping = {c: c for c in campos}
    df = pd.DataFrame([
        {"cliCpfCgc": cpf_ok, "pgtCliNome": f"DRY {tag}", "pgtValor": "99,90",
         "pgtData": "10/01/2026", "pgtVecmto": "10/02/2026", "pgtTipoConta": "R",
         "pgtPago": "N", "pgtTipoVista": "1"},
        {"cliCpfCgc": "00000000000000", "pgtCliNome": "INEXISTENTE", "pgtValor": "1",
         "pgtData": "10/01/2026", "pgtVecmto": "10/02/2026", "pgtTipoConta": "R",
         "pgtPago": "N", "pgtTipoVista": "1"},
    ])
    obj = _harness_financeiro(db_conn, df, mapping)
    obj._dry_run = True                       # liga a SIMULAÇÃO
    obj._inserir_financeiro()

    # Contagem em vendaPgto é EXATAMENTE a de antes — nada foi gravado.
    depois = cur.execute("SELECT COUNT(*) FROM vendaPgto").fetchone()[0]
    assert depois == antes, "dry-run NÃO pode inserir linhas em vendaPgto"
    # Mas o relatório reflete o que SERIA feito.
    assert obj._ultimo_resultado["simulacao"] is True
    assert obj._ultimo_resultado["inseridos"] == 1        # 1 seria inserido
    assert len(obj.nao_encontrados) == 1                  # 1 CPF não encontrado


# ─────────────────────────────────────────────────────────────────────────────
# MIGRAÇÃO banco→banco (rotinas próprias, sem a janela importadora)
# Origem = BD_ZERO (modelo, só leitura); Destino = BD_ZERO_TEST (descartável).
# ─────────────────────────────────────────────────────────────────────────────
def test_migracao_permissoes_cross_database(orig_conn, db_conn):
    orig_total = orig_conn.cursor().execute("SELECT COUNT(*) FROM UsuarioPermissao").fetchone()[0]

    mig = _harness_migracao(SRC_DB)
    res = mig._migrar_permissoes(orig_conn, db_conn)

    assert res["erros"] == 0, mig._logs[-6:]
    dest_total = db_conn.cursor().execute("SELECT COUNT(*) FROM UsuarioPermissao").fetchone()[0]
    assert dest_total == res["inseridos"]
    # tudo o que veio da origem ou entrou (inseridos) ou foi ignorado por FK (pulados)
    assert res["inseridos"] + res["pulados"] == orig_total


def test_migracao_clientes_banco_zero(orig_conn, db_conn):
    """Exercita o caminho mais crítico: desabilita ~FKs, limpa e recopia clientes,
    e REABILITA as FKs. Origem e destino idênticos → contagem deve bater e nenhuma
    FK pode ficar desabilitada ao final."""
    cur_o = orig_conn.cursor()
    src_emp = (cur_o.execute("SELECT TOP 1 cofId FROM config").fetchone() or [1])[0]
    orig_cli = cur_o.execute("SELECT COUNT(*) FROM cliente").fetchone()[0]

    mig = _harness_migracao(SRC_DB)
    res = mig._migrar_clientes(orig_conn, db_conn, src_emp)

    assert res["erros"] == 0, mig._logs[-8:]
    cur_d = db_conn.cursor()
    dest_cli = cur_d.execute("SELECT COUNT(*) FROM cliente").fetchone()[0]
    assert dest_cli == orig_cli    # cópia idêntica preserva a contagem
    # nenhuma FK pode ter ficado DESABILITADA (a rotina reabilita todas)
    fks_off = cur_d.execute("SELECT COUNT(*) FROM sys.foreign_keys WHERE is_disabled = 1").fetchone()[0]
    assert fks_off == 0, "FKs ficaram desabilitadas após a migração de clientes"


def test_auditoria_registra_no_destino(db_conn):
    """A migração grava, no destino, uma linha por entidade na tabela de
    auditoria (auto-criada), com contagens, origem/destino e usuário."""
    _zerar_auditoria(db_conn)      # BD_ZERO pode carregar auditoria de execuções reais
    mig = _harness_migracao(SRC_DB)
    mig._cancelado = False
    mig._totais = {
        "clientes": {"inseridos": 7, "pulados": 0, "erros": 0},
        "produtos": {"inseridos": 10, "pulados": 2, "erros": 1},
    }
    mig._registrar_auditoria(db_conn, "BD_ZERO", "BD_ZERO_TEST")

    cur = db_conn.cursor()
    assert cur.execute("SELECT OBJECT_ID('dbo.MaxImporta_Auditoria')").fetchone()[0] is not None
    rows = cur.execute(
        "SELECT audEntidade, audInseridos, audPulados, audErros, audOperacao, "
        "audOrigem, audDestino, audUsuario, audCancelada, audSessao "
        "FROM MaxImporta_Auditoria ORDER BY audEntidade").fetchall()
    assert len(rows) == 2
    d = {r[0]: r for r in rows}
    # rótulos (Clientes/Produtos) e contagens
    assert d["Clientes"][1] == 7 and d["Clientes"][2] == 0 and d["Clientes"][3] == 0
    assert d["Produtos"][1] == 10 and d["Produtos"][2] == 2 and d["Produtos"][3] == 1
    # metadados comuns
    for r in rows:
        assert r[4] == "MIGRACAO"       # audOperacao
        assert r[5] == "BD_ZERO"        # audOrigem
        assert r[6] == "BD_ZERO_TEST"   # audDestino
        assert r[7]                     # audUsuario (SUSER_SNAME) preenchido
        assert r[8] == 0                # audCancelada
    # as duas linhas da mesma execução compartilham o audSessao
    assert rows[0][9] == rows[1][9] and rows[0][9]


# ─────────────────────────────────────────────────────────────────────────────
# Fase B+ — migração de PRODUTOS e FINANCEIRO via importador HEADLESS (sem GUI)
# _get_importador agora cria ProdutosImportadorHeadless/FinanceiroImportadorHeadless
# em vez de janelas ctk, então _migrar_entidade roda ponta-a-ponta sem tela.
# ─────────────────────────────────────────────────────────────────────────────
def test_migracao_produtos_via_headless(orig_conn, db_conn):
    """Origem = BD_ZERO (cópia idêntica do destino): produtos já existem, então a
    migração é idempotente (mantém IDs, pula existentes) — sem erros, sem duplicar,
    e usando o importador HEADLESS (não abre janela)."""
    from mi_importadores import ProdutosImportadorHeadless
    src_emp = (orig_conn.cursor().execute("SELECT TOP 1 cofId FROM config").fetchone() or [1])[0]
    # Se a origem (BD_ZERO) não tiver produtos, não há o que migrar: a migração nem
    # cria o importador headless. Pula em vez de falhar (BD_ZERO pode estar zerado).
    prod_origem = orig_conn.cursor().execute("SELECT COUNT(*) FROM produto").fetchone()[0]
    if prod_origem == 0:
        pytest.skip("BD_ZERO sem produtos — nada a migrar neste teste")
    prod_antes = db_conn.cursor().execute("SELECT COUNT(*) FROM produto").fetchone()[0]

    mig = _harness_migracao(SRC_DB)
    mig._opcoes = {"prd_estoque": "zerar"}     # não migra estoque (evita acerto)
    mig._migrar_entidade("produtos", orig_conn, db_conn, src_emp)

    res = mig._totais["produtos"]
    assert res["erros"] == 0, mig._logs[-10:]
    assert isinstance(mig._imp["produtos"], ProdutosImportadorHeadless)  # headless, sem GUI
    prod_depois = db_conn.cursor().execute("SELECT COUNT(*) FROM produto").fetchone()[0]
    assert prod_depois == prod_antes           # idempotente (pula os já existentes)


def test_preflight_bancos_reais_compativeis(orig_conn, db_conn):
    """PRÉ-FLIGHT contra bancos REAIS: BD_ZERO_TEST é cópia do BD_ZERO, então o
    schema é idêntico → nenhum bloqueante. Também prova que é SOMENTE LEITURA."""
    mig = _harness_migracao(SRC_DB)
    ents = ["clientes", "produtos", "codbarras", "financeiro"]
    antes = db_conn.cursor().execute("SELECT COUNT(*) FROM cliente").fetchone()[0]

    linhas, res = mig._preflight(orig_conn, db_conn, ents)

    assert res["bloqueantes"] == 0, [l for l in linhas if l.startswith("🔴")]
    assert res["ok"] >= 4                     # ao menos as tabelas-base compatíveis
    assert any("schema compatível" in l for l in linhas)
    # somente leitura: nada mudou no destino
    depois = db_conn.cursor().execute("SELECT COUNT(*) FROM cliente").fetchone()[0]
    assert depois == antes


def test_migracao_financeiro_via_headless(orig_conn, db_conn):
    """Financeiro ponta-a-ponta via headless: lê a origem, localiza o cliente por
    CPF/CNPJ no destino e insere. Para ser DETERMINÍSTICO (o dedup é value-based e
    casaria os lançamentos já presentes no destino, que é cópia da origem), ZERA o
    vendaPgto do destino descartável antes de migrar — assim há o que reinserir
    independentemente do conteúdo do BD_ZERO. Confere inserção via o headless."""
    from mi_importadores import FinanceiroImportadorHeadless
    src_emp = (orig_conn.cursor().execute("SELECT TOP 1 cofId FROM config").fetchone() or [1])[0]
    vp_origem = orig_conn.cursor().execute("SELECT COUNT(*) FROM vendaPgto").fetchone()[0]
    if vp_origem == 0:
        pytest.skip("BD_ZERO sem lançamentos em vendaPgto — nada a migrar neste teste")
    # Destino zerado (é o BD_ZERO_TEST, revertido por snapshot ao fim do teste).
    db_conn.cursor().execute("DELETE FROM vendaPgto")
    db_conn.commit()

    mig = _harness_migracao(SRC_DB)
    mig._migrar_entidade("financeiro", orig_conn, db_conn, src_emp)

    res = mig._totais["financeiro"]
    assert res["erros"] == 0, mig._logs[-10:]
    assert isinstance(mig._imp["financeiro"], FinanceiroImportadorHeadless)
    assert res["inseridos"] > 0                # migrou de verdade via headless
    vp_depois = db_conn.cursor().execute("SELECT COUNT(*) FROM vendaPgto").fetchone()[0]
    assert vp_depois == res["inseridos"]       # destino começou vazio → total = inseridos


# ─────────────────────────────────────────────────────────────────────────────
# Orquestrador _migrar ponta-a-ponta — as 5 entidades numa execução, com
# reconciliação e auditoria. O wizard (_dialogo_opcoes) é GUI e roda ANTES do
# _migrar em produção; aqui injetamos self._opcoes direto (mesmo contrato).
# ─────────────────────────────────────────────────────────────────────────────
def test_migrar_orquestrador_ponta_a_ponta(orig_conn, db_conn):
    mig = _harness_migracao(SRC_DB)
    # base_conn_str sem DATABASE — _migrar abre as próprias conexões origem/destino
    mig.base_conn_str = ("DRIVER={ODBC Driver 17 for SQL Server};"
                         f"SERVER={SERVER};UID={USER};PWD={PWD};"
                         "TrustServerCertificate=yes;")
    # decisões que o wizard coletaria (backup=False: já estamos num banco descartável)
    mig._opcoes = {"backup": False, "cli_ciente": True,
                   "cli_duplicados": "manter", "prd_estoque": "zerar"}
    mig._salvar_relatorio_migracao = lambda: None   # sem escrever relatório/JSON
    mig.log_lines = []

    _zerar_auditoria(db_conn)      # independe de auditoria herdada do BD_ZERO
    # 'permissoes' entra automaticamente porque 'clientes' está no plano
    mig._migrar(SRC_DB, "BD_ZERO_TEST", ["clientes", "produtos", "codbarras", "financeiro"])

    # todas as 5 entidades executaram, sem erros
    assert set(mig._totais) == {"clientes", "permissoes", "produtos",
                                "codbarras", "financeiro"}, mig._logs[-10:]
    for ent, r in mig._totais.items():
        assert r["erros"] == 0, (ent, r, mig._logs[-12:])

    cur = db_conn.cursor()
    # clientes: cópia idêntica → contagem bate com a origem
    orig_cli = orig_conn.cursor().execute("SELECT COUNT(*) FROM cliente").fetchone()[0]
    assert cur.execute("SELECT COUNT(*) FROM cliente").fetchone()[0] == orig_cli
    # nenhuma FK ficou desabilitada
    assert cur.execute("SELECT COUNT(*) FROM sys.foreign_keys "
                       "WHERE is_disabled = 1").fetchone()[0] == 0
    # auditoria: 1 linha por entidade, todas da MESMA sessão, não cancelada
    n, sessoes, canceladas = cur.execute(
        "SELECT COUNT(*), COUNT(DISTINCT audSessao), SUM(CAST(audCancelada AS INT)) "
        "FROM MaxImporta_Auditoria").fetchone()
    assert (n, sessoes, canceladas) == (5, 1, 0)
    # reconciliação rodou e a migração concluiu
    assert any("CONFERÊNCIA ORIGEM × DESTINO" in l for l in mig._logs)
    assert any("Migração concluída" in l for l in mig._logs)
