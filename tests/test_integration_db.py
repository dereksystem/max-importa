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


def test_import_produtos_dry_run_nao_grava(db_conn):
    """DRY-RUN de Produtos: nada pode ser gravado — nem em `produto`, nem nas
    tabelas de REFERÊNCIA que o import cria sozinho (fabricante, grupoProd,
    subGrupoProd, produtoUn), nem via DBCC/IDENTITY_INSERT."""
    cur = db_conn.cursor()
    def contar(t):
        return cur.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
    tabelas = ("produto", "produto_empresa", "fabricante", "grupoProd",
               "subGrupoProd", "produtoUn")
    antes = {t: contar(t) for t in tabelas}

    tag = uuid.uuid4().hex[:8].upper()
    # nomes inéditos: se o dry-run gravasse, criaria estas referências
    linha = {"proId": "", "proDescricao": f"PROD DRY {tag}", "proCodCst2": "00",
             "proCodigo": f"{tag}DRY", "proUn": f"U{tag[:3]}",
             "ncmCodigoNCM": _ncm_existente(cur), "proVenda": "10,50",
             "proEstoqueAtual": "5",
             "fabNome": f"FABRICANTE DRY {tag}", "gdpNome": f"GRUPO DRY {tag}"}
    df = pd.DataFrame([linha])
    obj = _harness_produtos(db_conn, df, {c: c for c in linha.keys()})
    obj._dry_run = True
    obj._inserir_produtos()

    depois = {t: contar(t) for t in tabelas}
    assert depois == antes, f"dry-run gravou: {antes} → {depois}"
    assert obj._ultimo_resultado["inseridos"] == 1     # 1 SERIA inserido
    # e o resumo lista o que teria sido executado
    assert any("SERIAM executados" in l for l in obj._resumo_simulacao())


def test_import_clientes_dry_run_nao_grava(db_conn):
    """DRY-RUN de Clientes: nem `cliente`/`cliente_empresa`, nem o reseed de
    IDENTITY (DBCC CHECKIDENT) podem acontecer."""
    cur = db_conn.cursor()
    antes_cli = cur.execute("SELECT COUNT(*) FROM cliente").fetchone()[0]
    antes_ce = cur.execute("SELECT COUNT(*) FROM cliente_empresa").fetchone()[0]
    antes_ident = cur.execute(
        "SELECT IDENT_CURRENT('cliente')").fetchone()[0]

    tag = uuid.uuid4().hex[:8].upper()
    linha = _linha_cliente(tag, "DRYRUN", "11222333000181")
    df = pd.DataFrame([linha])
    obj = _harness_clientes(db_conn, df, {c: c for c in linha.keys()})
    obj._dry_run = True
    obj._inserir_clientes()

    assert cur.execute("SELECT COUNT(*) FROM cliente").fetchone()[0] == antes_cli
    assert cur.execute("SELECT COUNT(*) FROM cliente_empresa").fetchone()[0] == antes_ce
    # o IDENTITY não pode ter sido reconfigurado (DBCC não é transacional!)
    assert cur.execute("SELECT IDENT_CURRENT('cliente')").fetchone()[0] == antes_ident
    assert obj._ultimo_resultado["inseridos"] == 1


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


# ─────────────────────────────────────────────────────────────────────────────
# UPDATE não apaga o que já está no banco (célula vazia = "não mexer")
# ─────────────────────────────────────────────────────────────────────────────
def test_update_produtos_celula_vazia_preserva_banco(db_conn):
    """Insere um produto completo e depois roda um UPDATE em que só a descrição
    vem preenchida. Os demais campos MAPEADOS estão vazios no arquivo e devem
    ficar INTACTOS no banco — antes viravam NULL (texto) ou 0.0 (FLOAT_NOT_NULL,
    caso de proVenda/proCusto: o preço era zerado)."""
    cur = db_conn.cursor()
    ncm = _ncm_existente(cur)
    tag = uuid.uuid4().hex[:8].upper()

    campos_ins = ["proId", "proDescricao", "proAplicacao", "proCodCst2", "proCodigo",
                  "proUn", "ncmCodigoNCM", "proVenda", "proCusto", "proEstoqueAtual"]
    df_ins = pd.DataFrame([{
        "proId": "", "proDescricao": f"PROD {tag} ORIG", "proAplicacao": "APLICACAO ORIGINAL",
        "proCodCst2": "00", "proCodigo": f"{tag}U", "proUn": "UN", "ncmCodigoNCM": ncm,
        "proVenda": "99,90", "proCusto": "50,00", "proEstoqueAtual": "7",
    }])
    obj = _harness_produtos(db_conn, df_ins, {c: c for c in campos_ins})
    obj._inserir_produtos()
    assert obj._ultimo_resultado["inseridos"] == 1, obj._logs[-5:]

    cur = db_conn.cursor()
    pro_id = cur.execute("SELECT proId FROM produto_empresa WHERE proCodigo = ?",
                         f"{tag}U").fetchone()[0]

    # UPDATE: só a descrição preenchida; os outros campos seguem MAPEADOS e VAZIOS
    df_upd = pd.DataFrame([{
        "proId": str(pro_id), "proDescricao": f"PROD {tag} NOVA",
        "proAplicacao": "", "proVenda": "", "proCusto": "", "proEstoqueAtual": "",
    }])
    obj2 = _harness_produtos(db_conn, df_upd, {
        c: c for c in ["proId", "proDescricao", "proAplicacao",
                       "proVenda", "proCusto", "proEstoqueAtual"]})
    obj2._atualizar_produtos()

    cur = db_conn.cursor()
    desc, apl = cur.execute(
        "SELECT proDescricao, proAplicacao FROM produto WHERE proId = ?", pro_id).fetchone()
    venda, custo, estoque = cur.execute(
        "SELECT proVenda, proCusto, proEstoqueAtual FROM produto_empresa "
        "WHERE proId = ?", pro_id).fetchone()

    assert desc == f"PROD {tag} NOVA"                    # o que veio preenchido MUDA
    assert apl == "APLICACAO ORIGINAL"                   # vazio NÃO virou NULL
    assert float(venda) == pytest.approx(99.90)          # vazio NÃO zerou o preço
    assert float(custo) == pytest.approx(50.00)          # vazio NÃO zerou o custo
    assert float(estoque) == pytest.approx(7)


def test_update_clientes_celula_vazia_preserva_banco(db_conn):
    """Mesma regra nos Clientes: e-mail/telefone/endereço vazios no arquivo não
    podem apagar o cadastro existente."""
    tag = uuid.uuid4().hex[:8].upper()
    campos = ["cliId", "cliCpfCgc", "cliNome", "cliFantasia", "cliRgInsc",
              "cliFatEnd", "cliFatEndNumero", "cliFatBairro", "cliFatCidade",
              "cliFatUf", "cliFatCep", "cliFatCidCodIBGE"]
    linha = _linha_cliente(tag, "UPD", "12345678000190")
    obj = _harness_clientes(db_conn, pd.DataFrame([linha]), {c: c for c in campos})
    obj._inserir_clientes()
    assert obj._ultimo_resultado["inseridos"] == 1, obj._logs[-6:]

    cur = db_conn.cursor()
    cli_id = cur.execute("SELECT cliId FROM cliente WHERE cliNome = ?",
                         f"CLIENTE {tag} UPD").fetchone()[0]

    df_upd = pd.DataFrame([{
        "cliId": str(cli_id), "cliNome": f"CLIENTE {tag} RENOMEADO",
        "cliFantasia": "", "cliFatEnd": "", "cliFatCidade": "", "cliFatUf": "",
    }])
    obj2 = _harness_clientes(db_conn, df_upd, {
        c: c for c in ["cliId", "cliNome", "cliFantasia",
                       "cliFatEnd", "cliFatCidade", "cliFatUf"]})
    obj2._atualizar_clientes()

    cur = db_conn.cursor()
    nome, fant, end, cid, uf = cur.execute(
        "SELECT cliNome, cliFantasia, cliFatEnd, cliFatCidade, cliFatUf "
        "FROM cliente WHERE cliId = ?", cli_id).fetchone()

    assert nome == f"CLIENTE {tag} RENOMEADO"    # preenchido MUDA
    assert fant == f"FANT {tag}UPD"              # vazios ficam INTACTOS
    assert end == "RUA TESTE"
    assert cid == "SAO PAULO"
    assert uf == "SP"


# ─────────────────────────────────────────────────────────────────────────────
# proCodCst1 — origem da mercadoria (INT 0-9), compoe o CST com o proCodCst2
# ─────────────────────────────────────────────────────────────────────────────
def test_insert_produto_grava_cst1_mapeado(db_conn):
    cur = db_conn.cursor()
    ncm = _ncm_existente(cur)
    tag = uuid.uuid4().hex[:8].upper()
    campos = ["proId", "proDescricao", "proCodCst1", "proCodCst2", "proCodigo",
              "proUn", "ncmCodigoNCM"]
    df = pd.DataFrame([{
        "proId": "", "proDescricao": f"PROD {tag} CST", "proCodCst1": "3",
        "proCodCst2": "60", "proCodigo": f"{tag}C", "proUn": "UN",
        "ncmCodigoNCM": ncm,
    }])
    obj = _harness_produtos(db_conn, df, {c: c for c in campos})
    obj._inserir_produtos()
    assert obj._ultimo_resultado["inseridos"] == 1, obj._logs[-5:]

    cst1, cst2 = db_conn.cursor().execute(
        "SELECT proCodCst1, proCodCst2 FROM produto_empresa WHERE proCodigo = ?",
        f"{tag}C").fetchone()
    assert cst1 == 3          # gravado como INT, nao como texto
    assert cst2 == "60"       # o par continua intacto


def test_insert_produto_sem_cst1_usa_o_padrao_zero(db_conn):
    """Campo nao mapeado: entra 0 (Nacional), como o resto da base ja usa."""
    cur = db_conn.cursor()
    ncm = _ncm_existente(cur)
    tag = uuid.uuid4().hex[:8].upper()
    campos = ["proId", "proDescricao", "proCodCst2", "proCodigo", "proUn", "ncmCodigoNCM"]
    df = pd.DataFrame([{
        "proId": "", "proDescricao": f"PROD {tag} SEMCST", "proCodCst2": "00",
        "proCodigo": f"{tag}S", "proUn": "UN", "ncmCodigoNCM": ncm,
    }])
    obj = _harness_produtos(db_conn, df, {c: c for c in campos})
    obj._inserir_produtos()
    assert obj._ultimo_resultado["inseridos"] == 1, obj._logs[-5:]

    cst1 = db_conn.cursor().execute(
        "SELECT proCodCst1 FROM produto_empresa WHERE proCodigo = ?", f"{tag}S").fetchone()[0]
    assert cst1 == 0


def test_insert_produto_cst1_invalido_avisa_e_usa_o_padrao(db_conn):
    """55 nao e origem valida: o produto entra, o campo cai no padrao e fica o alerta."""
    cur = db_conn.cursor()
    ncm = _ncm_existente(cur)
    tag = uuid.uuid4().hex[:8].upper()
    campos = ["proId", "proDescricao", "proCodCst1", "proCodCst2", "proCodigo",
              "proUn", "ncmCodigoNCM"]
    df = pd.DataFrame([{
        "proId": "", "proDescricao": f"PROD {tag} RUIM", "proCodCst1": "55",
        "proCodCst2": "00", "proCodigo": f"{tag}R", "proUn": "UN", "ncmCodigoNCM": ncm,
    }])
    obj = _harness_produtos(db_conn, df, {c: c for c in campos})
    obj._inserir_produtos()

    assert obj._ultimo_resultado["inseridos"] == 1, "linha nao deve falhar por causa do CST1"
    cst1 = db_conn.cursor().execute(
        "SELECT proCodCst1 FROM produto_empresa WHERE proCodigo = ?", f"{tag}R").fetchone()[0]
    assert cst1 == 0
    assert obj._alertas_regras.get("proCodCst1 fora de 0-9") == 1


def test_update_produto_altera_cst1_e_invalido_preserva(db_conn):
    cur = db_conn.cursor()
    ncm = _ncm_existente(cur)
    tag = uuid.uuid4().hex[:8].upper()
    campos = ["proId", "proDescricao", "proCodCst1", "proCodCst2", "proCodigo",
              "proUn", "ncmCodigoNCM"]
    df = pd.DataFrame([{
        "proId": "", "proDescricao": f"PROD {tag} UPD", "proCodCst1": "2",
        "proCodCst2": "00", "proCodigo": f"{tag}X", "proUn": "UN", "ncmCodigoNCM": ncm,
    }])
    obj = _harness_produtos(db_conn, df, {c: c for c in campos})
    obj._inserir_produtos()
    pro_id = db_conn.cursor().execute(
        "SELECT proId FROM produto_empresa WHERE proCodigo = ?", f"{tag}X").fetchone()[0]

    # UPDATE valido: 2 -> 8
    o2 = _harness_produtos(db_conn, pd.DataFrame([{"proId": str(pro_id), "proCodCst1": "8"}]),
                           {"proId": "proId", "proCodCst1": "proCodCst1"})
    o2._atualizar_produtos()
    assert db_conn.cursor().execute(
        "SELECT proCodCst1 FROM produto_empresa WHERE proId = ?", pro_id).fetchone()[0] == 8

    # UPDATE invalido: mantem o 8 que estava no banco (nao zera, nao grava 99)
    o3 = _harness_produtos(db_conn, pd.DataFrame([{"proId": str(pro_id), "proCodCst1": "99"}]),
                           {"proId": "proId", "proCodCst1": "proCodCst1"})
    o3._atualizar_produtos()
    assert db_conn.cursor().execute(
        "SELECT proCodCst1 FROM produto_empresa WHERE proId = ?", pro_id).fetchone()[0] == 8
    assert o3._alertas_regras.get("proCodCst1 fora de 0-9") == 1


# ─────────────────────────────────────────────────────────────────────────────
# MULTI-LOJA — produto_empresa/cliente_empresa em TODAS as empresas,
# visibilidade (empresaFiltro) só nas MARCADAS
# ─────────────────────────────────────────────────────────────────────────────
def _filtro(conn, tabela, pk_value):
    """empIds em que o registro esta visivel, segundo o empresaFiltro."""
    return [r[0] for r in conn.cursor().execute(
        "SELECT empId FROM empresaFiltro WHERE emfTable = ? AND emfPkValue = ? "
        "ORDER BY empId", tabela, pk_value)]


def test_multiloja_insert_produto_cria_linha_em_todas_e_filtra_nas_marcadas(db_multiloja):
    conn, emps = db_multiloja
    assert emps == [1, 2, 3]
    cur = conn.cursor()
    ncm = _ncm_existente(cur)
    tag = uuid.uuid4().hex[:8].upper()

    campos = ["proId", "proDescricao", "proCodCst2", "proCodigo", "proUn", "ncmCodigoNCM"]
    df = pd.DataFrame([{"proId": "", "proDescricao": f"PROD {tag} ML", "proCodCst2": "00",
                        "proCodigo": f"{tag}M", "proUn": "UN", "ncmCodigoNCM": ncm}])
    obj = _harness_produtos(conn, df, {c: c for c in campos})
    obj.empresas_alvo = [1, 3]           # usuario marcou 1 e 3 na tela
    obj._inserir_produtos()
    assert obj._ultimo_resultado["inseridos"] == 1, obj._logs[-6:]

    pro_id = conn.cursor().execute(
        "SELECT proId FROM produto_empresa WHERE proCodigo = ?", f"{tag}M").fetchone()[0]
    # dados em TODAS as empresas
    n = conn.cursor().execute(
        "SELECT COUNT(*) FROM produto_empresa WHERE proId = ?", pro_id).fetchone()[0]
    assert n == 3, "produto_empresa precisa de 1 linha por cofId"
    # visibilidade so nas marcadas
    assert _filtro(conn, "produto", pro_id) == [1, 3]


def test_multiloja_insert_cliente_cria_linha_em_todas_e_filtra_nas_marcadas(db_multiloja):
    conn, _ = db_multiloja
    tag = uuid.uuid4().hex[:8].upper()
    campos = ["cliId", "cliCpfCgc", "cliNome", "cliFantasia", "cliRgInsc", "cliFatEnd",
              "cliFatEndNumero", "cliFatBairro", "cliFatCidade", "cliFatUf", "cliFatCep",
              "cliFatCidCodIBGE"]
    obj = _harness_clientes(conn, pd.DataFrame([_linha_cliente(tag, "ML", "12345678000190")]),
                            {c: c for c in campos})
    obj.empresas_alvo = [2]
    obj._inserir_clientes()
    assert obj._ultimo_resultado["inseridos"] == 1, obj._logs[-6:]

    cli_id = conn.cursor().execute(
        "SELECT cliId FROM cliente WHERE cliNome = ?", f"CLIENTE {tag} ML").fetchone()[0]
    n = conn.cursor().execute(
        "SELECT COUNT(*) FROM cliente_empresa WHERE cliId = ?", cli_id).fetchone()[0]
    assert n == 3, "cliente_empresa precisa de 1 linha por cofId"
    assert _filtro(conn, "cliente", cli_id) == [2]


def test_multiloja_reimportar_nao_duplica_o_filtro(db_multiloja):
    """Rodar o mesmo arquivo duas vezes nao pode dobrar as linhas de empresaFiltro."""
    conn, _ = db_multiloja
    cur = conn.cursor()
    ncm = _ncm_existente(cur)
    tag = uuid.uuid4().hex[:8].upper()
    campos = ["proId", "proDescricao", "proCodCst2", "proCodigo", "proUn", "ncmCodigoNCM"]
    linha = {"proId": "", "proDescricao": f"PROD {tag} DUP", "proCodCst2": "00",
             "proCodigo": f"{tag}D", "proUn": "UN", "ncmCodigoNCM": ncm}

    o1 = _harness_produtos(conn, pd.DataFrame([linha]), {c: c for c in campos})
    o1.empresas_alvo = [1, 2]
    o1._inserir_produtos()
    pro_id = conn.cursor().execute(
        "SELECT proId FROM produto_empresa WHERE proCodigo = ?", f"{tag}D").fetchone()[0]
    assert _filtro(conn, "produto", pro_id) == [1, 2]

    # segunda passada com o proId ja conhecido (modo cliId/proId do arquivo)
    linha2 = dict(linha, proId=str(pro_id))
    o2 = _harness_produtos(conn, pd.DataFrame([linha2]), {c: c for c in campos})
    o2.empresas_alvo = [1, 2]
    o2._inserir_produtos()

    assert _filtro(conn, "produto", pro_id) == [1, 2], "empresaFiltro duplicou"
    n = conn.cursor().execute(
        "SELECT COUNT(*) FROM produto_empresa WHERE proId = ?", pro_id).fetchone()[0]
    assert n == 3, "produto_empresa duplicou"


def test_multiloja_update_altera_so_as_marcadas_e_nao_toca_no_filtro(db_multiloja):
    conn, _ = db_multiloja
    cur = conn.cursor()
    ncm = _ncm_existente(cur)
    tag = uuid.uuid4().hex[:8].upper()
    campos = ["proId", "proDescricao", "proCodCst2", "proCodigo", "proUn",
              "ncmCodigoNCM", "proVenda"]
    df = pd.DataFrame([{"proId": "", "proDescricao": f"PROD {tag} UPD", "proCodCst2": "00",
                        "proCodigo": f"{tag}U", "proUn": "UN", "ncmCodigoNCM": ncm,
                        "proVenda": "10,00"}])
    o1 = _harness_produtos(conn, df, {c: c for c in campos})
    o1.empresas_alvo = [1, 2, 3]
    o1._inserir_produtos()
    pro_id = conn.cursor().execute(
        "SELECT proId FROM produto_empresa WHERE proCodigo = ?", f"{tag}U").fetchone()[0]
    filtro_antes = _filtro(conn, "produto", pro_id)
    assert filtro_antes == [1, 2, 3]

    # UPDATE de preco marcando SO a empresa 2
    o2 = _harness_produtos(conn, pd.DataFrame([{"proId": str(pro_id), "proVenda": "99,90"}]),
                           {"proId": "proId", "proVenda": "proVenda"})
    o2.empresas_alvo = [2]
    o2._atualizar_produtos()

    precos = {r[0]: float(r[1]) for r in conn.cursor().execute(
        "SELECT empId, proVenda FROM produto_empresa WHERE proId = ? ORDER BY empId", pro_id)}
    assert precos[2] == pytest.approx(99.90), "a empresa marcada tinha de mudar"
    assert precos[1] == pytest.approx(10.00), "empresa nao marcada nao pode mudar"
    assert precos[3] == pytest.approx(10.00)
    assert _filtro(conn, "produto", pro_id) == filtro_antes, "UPDATE nao pode mexer no filtro"


def test_banco_de_uma_loja_continua_igual(db_conn):
    """Regressao: sem multi-loja nada muda — 1 linha e NENHUM empresaFiltro."""
    cur = db_conn.cursor()
    assert cur.execute("SELECT COUNT(*) FROM config").fetchone()[0] == 1
    ncm = _ncm_existente(cur)
    tag = uuid.uuid4().hex[:8].upper()
    campos = ["proId", "proDescricao", "proCodCst2", "proCodigo", "proUn", "ncmCodigoNCM"]
    df = pd.DataFrame([{"proId": "", "proDescricao": f"PROD {tag} UNI", "proCodCst2": "00",
                        "proCodigo": f"{tag}1", "proUn": "UN", "ncmCodigoNCM": ncm}])
    obj = _harness_produtos(db_conn, df, {c: c for c in campos})
    obj._inserir_produtos()
    assert obj._ultimo_resultado["inseridos"] == 1, obj._logs[-6:]

    pro_id = db_conn.cursor().execute(
        "SELECT proId FROM produto_empresa WHERE proCodigo = ?", f"{tag}1").fetchone()[0]
    assert db_conn.cursor().execute(
        "SELECT COUNT(*) FROM produto_empresa WHERE proId = ?", pro_id).fetchone()[0] == 1
    assert _filtro(db_conn, "produto", pro_id) == [], \
        "banco de uma loja nao deve gerar empresaFiltro"


def test_multiloja_financeiro_usa_o_empid_do_arquivo(db_multiloja):
    """Cada titulo vai para a empresa informada na propria linha; sem valor, para a 1."""
    conn, emps = db_multiloja
    tag = uuid.uuid4().hex[:8].upper()
    cpf = "11222333000181"

    obj_cli = _harness_clientes(conn, pd.DataFrame([_linha_cliente(tag, "FML", cpf)]),
                                {c: c for c in _linha_cliente(tag, "FML", cpf)})
    obj_cli._inserir_clientes()
    cli_id = conn.cursor().execute(
        "SELECT cliId FROM cliente WHERE cliCpfCgc = ?", cpf).fetchone()[0]

    campos = ["cliCpfCgc", "pgtCliNome", "pgtValor", "pgtData", "pgtVecmto",
              "pgtTipoConta", "pgtPago", "pgtTipoVista", "empId"]
    base = {"cliCpfCgc": cpf, "pgtCliNome": f"CLIENTE {tag} FML",
            "pgtData": "2026-07-04", "pgtVecmto": "2026-08-04",
            "pgtTipoConta": "R", "pgtPago": "N", "pgtTipoVista": "1"}
    df = pd.DataFrame([
        dict(base, pgtValor="10",  empId="3"),   # empresa informada
        dict(base, pgtValor="20",  empId=""),    # vazio -> padrao 1
        dict(base, pgtValor="30",  empId="99"),  # inexistente -> pulada
    ])
    obj = _harness_financeiro(conn, df, {c: c for c in campos})
    obj._inserir_financeiro()

    assert obj._ultimo_resultado["inseridos"] == 2, obj._logs[-8:]
    por_valor = {float(r[0]): r[1] for r in conn.cursor().execute(
        "SELECT pgtValor, empId FROM vendaPgto WHERE pgtClienteId = ?", cli_id)}
    assert por_valor[10.0] == 3, "empId do arquivo deve ser respeitado"
    assert por_valor[20.0] == 1, "empId vazio deve cair no padrao 1"
    assert 30.0 not in por_valor, "empId inexistente na config nao pode ser gravado"
    assert any("99" in l and "config" in l for l in obj._logs), \
        "a linha pulada precisa aparecer no log"
    assert any(d.get("_motivo", "").startswith("empId 99") for d in obj.nao_encontrados)


def test_multiloja_financeiro_sem_campo_empid_usa_o_padrao(db_multiloja):
    """Campo nao mapeado: comportamento historico, tudo na empresa 1 (o aviso e na GUI)."""
    conn, _ = db_multiloja
    tag = uuid.uuid4().hex[:8].upper()
    cpf = "11222333000181"
    obj_cli = _harness_clientes(conn, pd.DataFrame([_linha_cliente(tag, "FP", cpf)]),
                                {c: c for c in _linha_cliente(tag, "FP", cpf)})
    obj_cli._inserir_clientes()
    cli_id = conn.cursor().execute(
        "SELECT cliId FROM cliente WHERE cliCpfCgc = ?", cpf).fetchone()[0]

    campos = ["cliCpfCgc", "pgtCliNome", "pgtValor", "pgtData", "pgtVecmto",
              "pgtTipoConta", "pgtPago", "pgtTipoVista"]
    df = pd.DataFrame([{"cliCpfCgc": cpf, "pgtCliNome": f"CLIENTE {tag} FP",
                        "pgtValor": "55", "pgtData": "2026-07-04",
                        "pgtVecmto": "2026-08-04", "pgtTipoConta": "R",
                        "pgtPago": "N", "pgtTipoVista": "1"}])
    obj = _harness_financeiro(conn, df, {c: c for c in campos})
    obj._inserir_financeiro()

    assert obj._ultimo_resultado["inseridos"] == 1, obj._logs[-6:]
    emp = conn.cursor().execute(
        "SELECT empId FROM vendaPgto WHERE pgtClienteId = ?", cli_id).fetchone()[0]
    assert emp == 1


def test_multiloja_migracao_clientes_cria_vinculo_em_todas_as_empresas(orig_conn, db_multiloja):
    """A migração de Clientes NÃO passa pelo importador (é cópia 'banco zero').

    Antes, ela resolvia o destino com `SELECT TOP 1 cofId` e criava UMA linha de
    cliente_empresa — num destino de 3 lojas, o cliente existia só na primeira.
    """
    conn, emps = db_multiloja
    assert emps == [1, 2, 3]
    mig = _harness_migracao(SRC_DB)
    mig._opcoes = {"cli_ciente": True, "cli_duplicados": "manter", "empresas": [1, 3]}
    src_emp = (orig_conn.cursor().execute(
        "SELECT TOP 1 cofId FROM config").fetchone() or [1])[0]
    res = mig._migrar_clientes(orig_conn, conn, src_emp)
    assert res["erros"] == 0, mig._logs[-10:]

    cur = conn.cursor()
    n_cli = cur.execute("SELECT COUNT(*) FROM cliente").fetchone()[0]
    assert n_cli > 0, "a migração não copiou cliente nenhum"

    # 1 linha de cliente_empresa por cliente POR EMPRESA
    por_emp = {r[0]: r[1] for r in cur.execute(
        "SELECT empId, COUNT(DISTINCT cliId) FROM cliente_empresa GROUP BY empId")}
    assert sorted(por_emp) == [1, 2, 3], f"faltou empresa em cliente_empresa: {por_emp}"
    assert set(por_emp.values()) == {n_cli}, \
        f"cada empresa devia ter os {n_cli} clientes, veio {por_emp}"

    # cleId continua unico (a PK e IDENTITY_INSERT ON durante a copia)
    total, distintos = cur.execute(
        "SELECT COUNT(*), COUNT(DISTINCT cleId) FROM cliente_empresa").fetchone()
    assert total == distintos == n_cli * 3, f"cleId duplicado: {total} linhas, {distintos} ids"

    # visibilidade so nas marcadas no wizard
    filtro = {r[0]: r[1] for r in cur.execute(
        "SELECT empId, COUNT(*) FROM empresaFiltro WHERE emfTable = 'cliente' "
        "GROUP BY empId")}
    assert sorted(filtro) == [1, 3], f"empresaFiltro nas empresas erradas: {filtro}"
    assert set(filtro.values()) == {n_cli}


# ─────────────────────────────────────────────────────────────────────────────
# UPDATE nao pode sobrescrever o cadastro ERRADO nem mentir no resumo
# ─────────────────────────────────────────────────────────────────────────────
def test_update_por_cpf_documento_ambiguo_nao_altera_ninguem(db_conn):
    """O BD_ZERO tem 167 documentos repetidos (um deles em 15 clientes).

    Antes, o `SELECT TOP 1` sem ORDER BY escolhia um ao acaso e gravava por cima —
    o cadastro de um cliente que o usuario nem sabia que existia.
    """
    cur = db_conn.cursor()
    doc = cur.execute(
        "SELECT TOP 1 cliCpfCgc FROM cliente "
        "WHERE cliCpfCgc IS NOT NULL AND LTRIM(RTRIM(cliCpfCgc)) <> '' "
        "GROUP BY cliCpfCgc HAVING COUNT(*) > 1 ORDER BY COUNT(*) DESC").fetchone()
    if not doc:
        pytest.skip("o banco de teste nao tem documento repetido")
    doc = doc[0]
    antes = {r[0]: r[1] for r in cur.execute(
        "SELECT cliId, cliNome FROM cliente WHERE cliCpfCgc = ?", doc)}
    assert len(antes) > 1

    obj = _harness_clientes(
        db_conn, pd.DataFrame([{"cliCpfCgc": doc, "cliNome": "NOME QUE NAO PODE ENTRAR"}]),
        {"cliCpfCgc": "cliCpfCgc", "cliNome": "cliNome"})
    obj._atualizar_clientes_por_cpf()

    depois = {r[0]: r[1] for r in db_conn.cursor().execute(
        "SELECT cliId, cliNome FROM cliente WHERE cliCpfCgc = ?", doc)}
    assert depois == antes, "nenhum cadastro podia ter sido tocado"
    assert any("AMB" in l.upper() for l in obj._logs), obj._logs[-6:]
    assert getattr(obj, "_nao_atualizados", []), "a linha tinha de ser registrada"


def test_update_produto_id_inexistente_nao_conta_como_sucesso(db_conn):
    cur = db_conn.cursor()
    livre = (cur.execute("SELECT ISNULL(MAX(proId), 0) + 5000 FROM produto").fetchone()[0])
    obj = _harness_produtos(
        db_conn, pd.DataFrame([{"proId": str(livre), "proDescricao": "NAO EXISTE"}]),
        {"proId": "proId", "proDescricao": "proDescricao"})
    obj._atualizar_produtos()

    txt = " ".join(obj._logs)
    assert "0 atualizados" in txt, f"nao podia contar sucesso: {txt[-250:]}"
    assert "1 nao encontrados" in txt or "não existe" in txt, txt[-250:]
    assert getattr(obj, "_nao_atualizados", []), "a linha tinha de ser registrada"
    # e o produto realmente nao foi criado por acidente
    assert cur.execute("SELECT COUNT(*) FROM produto WHERE proId = ?", livre).fetchone()[0] == 0


def test_update_cliente_id_existente_continua_contando_sucesso(db_conn):
    """Regressao: a checagem nova nao pode fazer o caminho normal parar de contar."""
    cur = db_conn.cursor()
    alvo = cur.execute("SELECT TOP 1 cliId FROM cliente WHERE cliId >= 10 "
                       "ORDER BY cliId").fetchone()
    if not alvo:
        pytest.skip("banco de teste sem cliente >= 10")
    cli_id = alvo[0]
    tag = uuid.uuid4().hex[:6].upper()
    obj = _harness_clientes(
        db_conn, pd.DataFrame([{"cliId": str(cli_id), "cliNome": f"RENOMEADO {tag}"}]),
        {"cliId": "cliId", "cliNome": "cliNome"})
    obj._atualizar_clientes()

    assert "1 atualizados" in " ".join(obj._logs), obj._logs[-5:]
    assert db_conn.cursor().execute(
        "SELECT cliNome FROM cliente WHERE cliId = ?", cli_id).fetchone()[0] == f"RENOMEADO {tag}"
