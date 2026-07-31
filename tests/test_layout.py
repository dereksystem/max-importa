"""Regressao de LAYOUT das telas de importacao — medido, nao olhado.

A suite nao renderiza telas em lugar nenhum; aqui abrimos uma janela Tk de verdade
e MEDIMOS a geometria (`winfo_height`/`winfo_rooty`), que e como este projeto
verifica interface (screenshot ja se provou pior: chegou a fotografar a janela
errada). Faz SKIP sozinho onde nao ha display, entao nao atrapalha o gate do BUILD.

Dois invariantes:
  1. o MAPEAMENTO fica com a maior parte da altura util — e a area de trabalho;
  2. o BOTAO de acao NUNCA sai da janela (a regressao de 1366x768 da v4.0.1).
"""
import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

ctk = pytest.importorskip("customtkinter")


@pytest.fixture(scope="module")
def root():
    """UM root Tk para o modulo inteiro.

    ⚠️ Criar e destruir um `CTk()` por teste FALHA de forma intermitente: o CTk agenda
    callbacks (o rastreador de DPI, entre outros) que sobrevivem ao `destroy()` — daí o
    ruído "invalid command name … (after script)" — e depois de alguns ciclos a criação
    do próximo root estoura com TclError. Reusando o root e descartando só o container
    de cada teste, a suíte fica estável (medido: 0 falhas em execuções repetidas).
    """
    try:
        r = ctk.CTk()
    except Exception as e:                      # sem display / Tk indisponivel
        pytest.skip(f"sem ambiente grafico: {e}")
    yield r
    try:
        r.destroy()
    except Exception:
        pass


@pytest.fixture
def tela(request, root):
    """Monta uma tela de importacao real dentro do root, no tamanho pedido."""
    import max_importa as M

    classe_nome, altura = request.param
    root.geometry(f"1366x{altura}")

    conteudo = ctk.CTkFrame(root, fg_color="transparent")
    conteudo.pack(fill="both", expand=True)
    shell = types.SimpleNamespace(
        conteudo=conteudo,
        login_win=types.SimpleNamespace(conn=None, current_db="BD_ZERO"))

    classe = getattr(M, classe_nome)
    # JanelaFinanceiro e so INSERT — nao aceita operacao_inicial
    t = (classe(shell) if classe_nome == "JanelaFinanceiro"
         else classe(shell, operacao_inicial="INSERIR (INSERT)"))
    t.pack(fill="both", expand=True)
    root.update_idletasks()
    root.update()
    yield root, t
    conteudo.destroy()


# Alturas: 600 = janela minima apertada (o caso dificil) e 768 = 1366x768, o monitor
# que gerou a regressao da v4.0.1. Acima de 768 a medicao e IDENTICA (o shell limita a
# altura util), entao incluir 1080 so criaria mais um root Tk por caso — e abrir dezenas
# deles no mesmo processo chega a falhar por esgotamento de recurso.
_TELAS = [(c, a) for c in ("JanelaProdutos", "JanelaClientes", "JanelaFinanceiro")
          for a in (600, 768)]
_IDS = [f"{c.replace('Janela','')}-{a}px" for c, a in _TELAS]


@pytest.mark.parametrize("tela", _TELAS, ids=_IDS, indirect=True)
def test_botao_de_acao_nunca_sai_da_janela(tela):
    """Regressao da v4.0.1: em 1366x768 o rodape era empurrado para fora da tela."""
    root, t = tela
    btn = t.btn_import
    fim = btn.winfo_rooty() - root.winfo_rooty() + btn.winfo_height()
    assert fim <= root.winfo_height(), (
        f"botao termina em y={fim}, fora da janela de {root.winfo_height()}px")


_TELAS_COM_FOLGA = [(c, a) for c, a in _TELAS if a >= 768]
_IDS_COM_FOLGA = [f"{c.replace('Janela','')}-{a}px" for c, a in _TELAS_COM_FOLGA]


@pytest.mark.parametrize("tela", _TELAS_COM_FOLGA, ids=_IDS_COM_FOLGA, indirect=True)
def test_mapeamento_fica_com_a_maior_parte_da_altura(tela):
    """Havendo espaco (>=768px), o mapeamento leva mais altura que o rodape — e a
    area de trabalho.

    Pegou o caso real em que a barrinha vermelha decorativa do log (CTkFrame sem
    `height`, que nasce com o default de 200px e nao encolhe com fill="y") inflava
    o rodape para 516px e deixava so 213px — 4 linhas — para o mapeamento.

    Abaixo de 768px o rodape tem um minimo proprio (~327px: contador, perfis, botoes,
    progresso e log) e passa a dominar; ali o que se garante e o teste do botao
    visivel + o minimo de linhas abaixo.
    """
    root, t = tela
    area_map = t.scroll_map.master.winfo_height()
    rodape = t.winfo_children()[-1].winfo_height()
    assert area_map >= 0.9 * rodape, (
        f"mapeamento com {area_map}px contra {rodape}px de rodape — "
        "o rodape esta comendo a area de trabalho")


@pytest.mark.parametrize("tela", _TELAS, ids=_IDS, indirect=True)
def test_mapeamento_mostra_linhas_ate_na_janela_minima(tela):
    """Mesmo espremido, o mapeamento tem de mostrar linhas — nao pode virar uma fresta.

    Com o bug da barrinha, a 768px sobravam 213px (4 linhas); a 600px seria pior.
    """
    _root, t = tela
    area_map = t.scroll_map.master.winfo_height()
    linha = next(iter(t.map_rows.values()))
    visiveis = area_map // max(linha.winfo_height(), 1)
    assert visiveis >= 2, (
        f"so {visiveis} linha(s) visiveis no mapeamento ({area_map}px "
        f"para linhas de {linha.winfo_height()}px)")


@pytest.mark.parametrize("tela", [("JanelaProdutos", 768)], ids=["Produtos-768px"],
                         indirect=True)
def test_bloco_do_log_nao_estoura_a_altura_do_textbox(tela):
    """A barrinha decorativa deve ESTICAR ate o textbox, nunca defini-lo.

    Sem `height=1` nela, o bloco do log pedia ~250px para um textbox de ~105px.
    """
    _root, t = tela
    log_wrap = t.text_log.master
    assert log_wrap.winfo_height() <= t.text_log.winfo_height() + 20, (
        f"bloco do log com {log_wrap.winfo_height()}px para um textbox de "
        f"{t.text_log.winfo_height()}px — algo dentro dele pede altura demais")


# ── Ordenacao das listas de campos ───────────────────────────────────────────
@pytest.mark.parametrize("classe_nome,atributo", [
    ("JanelaProdutos", "CAMPOS_PRODUTO"),
    ("JanelaClientes", "CAMPOS_CLIENTE"),
])
def test_campos_obrigatorios_vem_todos_antes_dos_opcionais(classe_nome, atributo):
    """A tela decide onde por o cabecalho "CAMPOS OPCIONAIS" pela PRIMEIRA tupla com
    obrigatorio=False. Um campo opcional no meio do bloco de cima empurraria o
    cabecalho para antes de obrigatorios que viessem depois — ja aconteceu ao incluir
    o proCodCst1. Este teste nao precisa de GUI: le a lista.
    """
    import max_importa as M
    campos = getattr(getattr(M, classe_nome), atributo)
    # a chave (proId/cliId) e a excecao declarada: vem primeiro com obrigatorio=False
    resto = [(nome, ob) for nome, _tab, _descr, ob in campos if nome not in ("proId", "cliId")]
    obrigatorios = [i for i, (_n, ob) in enumerate(resto) if ob]
    opcionais = [i for i, (_n, ob) in enumerate(resto) if not ob]
    assert not obrigatorios or not opcionais or max(obrigatorios) < min(opcionais), (
        f"{atributo}: '{resto[min(opcionais)][0]}' (opcional) aparece antes de "
        f"'{resto[max(obrigatorios)][0]}' (obrigatorio) — quebra o separador de secao")


# ══════════════════════════════════════════════════════════════════════════
# Janela de selecao de empresas (multi-loja) — RENDERIZADA de verdade
# ══════════════════════════════════════════════════════════════════════════
# Sem isto, as ~90 linhas que montam a janela nunca executam: os testes de
# unidade substituem o metodo por um stub e os de integracao setam
# `empresas_alvo` direto. Um argumento errado de widget so apareceria na
# primeira vez que um usuario abrisse a tela num banco multi-loja.


class _CursorConfig:
    def __init__(self, linhas):
        self._linhas = linhas

    def execute(self, *a, **k):
        return self

    def fetchall(self):
        return list(self._linhas)

    def fetchone(self):
        return self._linhas[0] if self._linhas else None


class _ConnConfig:
    def __init__(self, linhas):
        self._linhas = linhas

    def cursor(self):
        return _CursorConfig(self._linhas)


def _achar(widget, classe, texto=None):
    """Varre a arvore de widgets procurando por classe (e texto, se dado)."""
    achados = []
    for filho in widget.winfo_children():
        if filho.__class__.__name__ == classe:
            if texto is None:
                achados.append(filho)
            else:
                try:
                    if filho.cget("text") == texto:
                        achados.append(filho)
                except Exception:
                    pass
        achados += _achar(filho, classe, texto)
    return achados


@pytest.fixture
def host(root):
    """Widget hospedeiro real (a janela precisa de um master ctk de verdade)."""
    import max_importa as M

    class _Host(M.CancelavelMixin, ctk.CTkFrame):
        def __init__(self, master, linhas):
            super().__init__(master)
            self.conn = _ConnConfig(linhas)
            self.logs = []
            self._log = self.logs.append

    criados = []

    def _criar(linhas):
        h = _Host(root, linhas)
        h.pack()
        criados.append(h)
        root.update_idletasks()
        return h

    yield _criar
    for h in criados:
        h.destroy()


def _toplevels(w):
    """CTkToplevel em qualquer nivel — o dialogo e filho do HOSPEDEIRO, nao do root."""
    achados = []
    for filho in w.winfo_children():
        if filho.__class__.__name__ == "CTkToplevel":
            achados.append(filho)
        achados += _toplevels(filho)
    return achados


def _rodar_dialogo(root, h, acao, is_insert=True):
    """Abre o diálogo e executa `acao(dlg)` assim que ele existir.

    `_selecionar_empresas` bloqueia em `wait_window`; agendamos a interação ANTES,
    e ela roda dentro do próprio laço de eventos do diálogo.

    ⚠️ A rede de segurança (`tentativas`) não é decoração: se a `acao` não fechar o
    diálogo, `wait_window` prende o processo para SEMPRE e o pytest só morre no
    timeout externo. Aqui, depois de ~5s, o diálogo é destruído e o teste falha
    com uma mensagem que diz o que aconteceu.
    """
    estado = {"tentativas": 0, "erro": None}

    def _interagir():
        estado["tentativas"] += 1
        dlgs = _toplevels(h) or _toplevels(root)
        if not dlgs:
            if estado["tentativas"] > 100:          # ~5s
                estado["erro"] = "o diálogo nunca apareceu"
                return
            root.after(50, _interagir)
            return
        dlg = dlgs[-1]
        try:
            acao(dlg)
        except Exception as e:                      # não deixa o wait_window preso
            estado["erro"] = f"{type(e).__name__}: {e}"
        finally:
            if dlg.winfo_exists():
                estado["erro"] = estado["erro"] or "a ação não fechou o diálogo"
                dlg.destroy()

    root.after(100, _interagir)
    r = h._selecionar_empresas(is_insert=is_insert)
    if estado["erro"]:
        raise AssertionError(estado["erro"])
    return r


_TRES = [(1, "GROW SUPLEMENTOS"), (2, "FILIAL CENTRO"), (3, "FILIAL NORTE")]


def test_dialogo_nao_aparece_em_banco_de_uma_loja(host):
    """Uma empresa: devolve None sem abrir janela nenhuma."""
    h = host([(1, "LOJA UNICA")])
    assert h._selecionar_empresas() is None


def test_dialogo_marca_tudo_por_padrao_e_devolve_todas(root, host):
    h = host(_TRES)
    r = _rodar_dialogo(root, h, lambda dlg: _achar(dlg, "CTkButton", "Continuar")[0].invoke())
    assert r == [1, 2, 3]


def test_dialogo_cancelar_devolve_false(root, host):
    h = host(_TRES)
    r = _rodar_dialogo(root, h, lambda dlg: _achar(dlg, "CTkButton", "Cancelar")[0].invoke())
    assert r is False


def test_dialogo_desmarcar_uma_empresa(root, host):
    """As checkboxes vem na ordem TODAS, empresa 1, 2, 3 — desmarcar a 2ª empresa."""
    h = host(_TRES)

    def _acao(dlg):
        chks = _achar(dlg, "CTkCheckBox")
        assert len(chks) == 4, f"esperava TODAS + 3 empresas, achei {len(chks)}"
        chks[2].toggle()                       # desmarca a empresa 2
        _achar(dlg, "CTkButton", "Continuar")[0].invoke()

    assert _rodar_dialogo(root, h, _acao) == [1, 3]


def test_dialogo_todas_desmarca_tudo_e_marcar_de_volta(root, host):
    """A linha TODAS e um marcar/desmarcar-tudo de verdade."""
    h = host(_TRES)

    def _acao(dlg):
        chks = _achar(dlg, "CTkCheckBox")
        chks[0].toggle()                       # TODAS -> desmarca tudo
        assert not any(c.get() for c in chks[1:]), "TODAS deveria ter desmarcado todas"
        chks[0].toggle()                       # TODAS -> marca tudo de novo
        assert all(c.get() for c in chks[1:])
        _achar(dlg, "CTkButton", "Continuar")[0].invoke()

    assert _rodar_dialogo(root, h, _acao) == [1, 2, 3]


def test_dialogo_texto_muda_entre_insert_e_update(root, host):
    """A marcacao significa coisas diferentes por operacao — a janela tem de dizer."""
    textos = {}

    def _captura(chave):
        def _acao(dlg):
            textos[chave] = " ".join(
                (l.cget("text") or "") for l in _achar(dlg, "CTkLabel"))
            _achar(dlg, "CTkButton", "Cancelar")[0].invoke()
        return _acao

    h1 = host(_TRES)
    _rodar_dialogo(root, h1, _captura("insert"), is_insert=True)
    h2 = host(_TRES)
    _rodar_dialogo(root, h2, _captura("update"), is_insert=False)

    assert "APARECER" in textos["insert"]
    assert "empresaFiltro" in textos["insert"]
    assert "DADOS" in textos["update"]
    assert "não é alterada" in textos["update"] or "nao é alterada" in textos["update"]
    assert textos["insert"] != textos["update"]


def test_dialogo_sem_nenhuma_marcada_nao_deixa_continuar(root, host):
    """Continuar sem empresa nenhuma tem de barrar, nao devolver lista vazia."""
    import max_importa as M
    h = host(_TRES)
    avisos = []

    def _acao(dlg):
        chks = _achar(dlg, "CTkCheckBox")
        chks[0].toggle()                       # TODAS -> desmarca tudo
        _achar(dlg, "CTkButton", "Continuar")[0].invoke()   # deve avisar e NAO fechar
        assert avisos, "deveria ter avisado que nenhuma empresa esta marcada"
        _achar(dlg, "CTkButton", "Cancelar")[0].invoke()

    orig = M.messagebox.showwarning
    M.messagebox.showwarning = lambda *a, **k: avisos.append(a)
    try:
        r = _rodar_dialogo(root, h, _acao)
    finally:
        M.messagebox.showwarning = orig
    assert r is False, "so saiu pelo Cancelar — Continuar nao podia ter fechado"


# ── Aviso do Financeiro (multi-loja sem empId mapeado) ───────────────────────
def test_aviso_financeiro_so_aparece_quando_falta_o_empid(root, host, monkeypatch):
    """Multi-loja + campo nao mapeado = aviso. Com o campo, ou com uma loja, silencio."""
    import max_importa as M
    import pandas as pd

    perguntas = []
    monkeypatch.setattr(M.messagebox, "askyesno",
                        lambda *a, **k: (perguntas.append(a), True)[1])

    def _cenario(linhas, mapping):
        h = host(linhas)
        h.mapping = mapping
        h.df = pd.DataFrame([{"x": 1}])
        perguntas.clear()
        return M.JanelaFinanceiro._avisar_multiloja_financeiro(h), list(perguntas)

    # 1) multi-loja SEM empId -> avisa
    ok, p = _cenario(_TRES, {"cliCpfCgc": "cpf"})
    assert ok is True and len(p) == 1
    assert "empId" in p[0][1] and "empresa 1" in p[0][1]

    # 2) multi-loja COM empId -> nao avisa
    ok, p = _cenario(_TRES, {"cliCpfCgc": "cpf", "empId": "loja"})
    assert ok is True and p == []

    # 3) uma loja -> nao avisa
    ok, p = _cenario([(1, "UNICA")], {"cliCpfCgc": "cpf"})
    assert ok is True and p == []


def test_aviso_financeiro_cancelado_aborta(root, host, monkeypatch):
    import max_importa as M
    import pandas as pd
    monkeypatch.setattr(M.messagebox, "askyesno", lambda *a, **k: False)
    h = host(_TRES)
    h.mapping = {"cliCpfCgc": "cpf"}
    h.df = pd.DataFrame([{"x": 1}])
    assert M.JanelaFinanceiro._avisar_multiloja_financeiro(h) is False
    assert any("empId" in l for l in h.logs)
