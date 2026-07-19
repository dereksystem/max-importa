"""Testes do gerador do histórico de versões (gerar_historico.py).

O script roda a cada release para derivar `historico_versoes.html` do CHANGELOG.md.
Se o parser quebrar, a documentação sai errada silenciosamente — daí os testes.
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import gerar_historico as G


_CHANGELOG_FAKE = """# Changelog — Max_Importa

Texto de cabeçalho que deve ser ignorado.

---

## [9.9.9] — 2026-12-31

### Nova funcionalidade brilhante
- Faz `algo` novo com **destaque**.
- Segunda linha do item.

### Correções
- Conserta o bug do rodapé.

---

## [9.9.8] — 2026-12-01

### 🚨 CRÍTICO — dado era perdido
- Perdia tudo.

### Performance — bulk insert
- Ficou 10x mais rápido.
"""


@pytest.fixture
def changelog(tmp_path):
    p = tmp_path / "CHANGELOG.md"
    p.write_text(_CHANGELOG_FAKE, encoding="utf-8")
    return str(p)


def test_parse_extrai_versoes_e_datas(changelog):
    vs = G.parse_changelog(changelog)
    assert [v["versao"] for v in vs] == ["9.9.9", "9.9.8"]
    assert vs[0]["data"] == "2026-12-31"


def test_parse_extrai_blocos_e_itens(changelog):
    vs = G.parse_changelog(changelog)
    blocos = vs[0]["blocos"]
    assert [b["titulo"] for b in blocos] == ["Nova funcionalidade brilhante", "Correções"]
    assert len(blocos[0]["itens"]) == 2
    assert "algo" in blocos[0]["itens"][0]


def test_classificacao_por_tipo(changelog):
    vs = G.parse_changelog(changelog)
    tipos = {b["titulo"]: b["tipo"] for v in vs for b in v["blocos"]}
    assert tipos["Nova funcionalidade brilhante"] == "novidade"
    assert tipos["Correções"] == "correcao"
    assert tipos["🚨 CRÍTICO — dado era perdido"] == "critico"
    assert tipos["Performance — bulk insert"] == "performance"


def test_parse_arquivo_inexistente_devolve_vazio(tmp_path):
    assert G.parse_changelog(str(tmp_path / "nao_existe.md")) == []


def test_gera_html_com_estrutura_e_sem_ref_externa(changelog):
    html = G.gerar_html(G.parse_changelog(changelog))
    assert html.startswith("<!DOCTYPE html>")
    assert "Histórico de Versões" in html
    assert "v9.9.9" in html and "v9.9.8" in html
    assert "http://" not in html and "https://" not in html   # autocontido
    assert "<style>" in html                                   # CSS embutido


def test_html_escapa_conteudo(tmp_path):
    p = tmp_path / "CHANGELOG.md"
    p.write_text("## [1.0.0] — 2026-01-01\n\n### Teste\n- <script>alert(1)</script>\n",
                 encoding="utf-8")
    html = G.gerar_html(G.parse_changelog(str(p)))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_markdown_inline_vira_html(tmp_path):
    p = tmp_path / "CHANGELOG.md"
    p.write_text("## [1.0.0] — 2026-01-01\n\n### T\n- usa `codigo` e **negrito**\n",
                 encoding="utf-8")
    html = G.gerar_html(G.parse_changelog(str(p)))
    assert "<code>codigo</code>" in html
    assert "<strong>negrito</strong>" in html


def test_changelog_real_do_projeto_e_parseavel():
    """O CHANGELOG.md de verdade precisa continuar parseável — se alguém mudar o
    formato dos cabeçalhos, este teste avisa antes da documentação sair vazia."""
    vs = G.parse_changelog(G._CHANGELOG)
    assert len(vs) >= 30, "esperava dezenas de versões no CHANGELOG real"
    assert all(v["versao"] and v["data"] for v in vs)
    assert sum(len(v["blocos"]) for v in vs) >= 40


def test_topo_do_changelog_bate_com_app_version():
    """Guard-rail de release: a versão LIBERADA mais recente do CHANGELOG tem de
    ser a APP_VERSION — pega o esquecimento clássico de subir uma e não a outra.
    O bloco '[Não liberado]' no topo é estado de trabalho válido (mudanças já
    commitadas, versão ainda não fechada) e é ignorado."""
    from mi_config import APP_VERSION
    vs = G.parse_changelog(G._CHANGELOG)
    liberadas = [v for v in vs if not v["versao"].lower().startswith("não liberado")
                 and not v["versao"].lower().startswith("nao liberado")]
    assert liberadas, "nenhuma versão liberada no CHANGELOG"
    assert liberadas[0]["versao"] == APP_VERSION, (
        f"última versão liberada no CHANGELOG ({liberadas[0]['versao']}) "
        f"!= APP_VERSION ({APP_VERSION})")
