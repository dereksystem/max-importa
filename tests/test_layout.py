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
