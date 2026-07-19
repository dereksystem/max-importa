"""gerar_historico.py — gera `historico_versoes.html` a partir do CHANGELOG.md.

Por que GERAR em vez de escrever à mão: o CHANGELOG.md já é a fonte da verdade do
que mudou em cada versão. Manter uma segunda cópia em HTML garantiria divergência na
primeira release em que alguém esquecesse de atualizar as duas. Aqui a página é
derivada — basta rodar este script ao fechar uma versão.

    python gerar_historico.py

Saída: historico_versoes.html (autocontido: CSS inline, sem CDN/fonte externa, abre
offline com duplo clique). Cada bloco do changelog é classificado em CORREÇÃO,
NOVIDADE, PERFORMANCE, VISUAL ou TESTES, com filtro por tipo na própria página.
"""
import html
import os
import re
import sys
from datetime import datetime

_AQUI = os.path.dirname(os.path.abspath(__file__))
_CHANGELOG = os.path.join(_AQUI, "CHANGELOG.md")
_SAIDA = os.path.join(_AQUI, "historico_versoes.html")

# Classificação do bloco pelo título da subseção (### ...). A ordem importa:
# a primeira regra que casar vence.
_TIPOS = [
    ("critico",     ("crítico", "critico", "🚨"),                    "🚨", "CRÍTICO"),
    ("correcao",    ("correç", "correc", "corrig", "fix "),          "🔧", "CORREÇÃO"),
    ("performance", ("performance", "perf", "bulk insert"),          "⚡", "PERFORMANCE"),
    ("teste",       ("teste",),                                      "🧪", "TESTES"),
    ("visual",      ("visual", "tema", "interface"),                 "🎨", "VISUAL"),
    ("verificado",  ("verificado",),                                 "ℹ️", "VERIFICAÇÃO"),
]
_PADRAO = ("novidade", "✨", "NOVIDADE")


def _classificar(titulo: str):
    t = titulo.lower()
    for chave, termos, icone, rotulo in _TIPOS:
        if any(termo in t for termo in termos):
            return chave, icone, rotulo
    return _PADRAO


def _inline_md(txt: str) -> str:
    """Converte o mínimo de markdown inline (negrito, código, links) para HTML,
    escapando o resto. Nada de biblioteca externa."""
    esc = html.escape(txt)
    esc = re.sub(r"`([^`]+)`", r"<code>\1</code>", esc)
    esc = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", esc)
    esc = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", esc)   # link vira só o texto
    return esc


def parse_changelog(caminho: str) -> list:
    """[{'versao','data','blocos':[{'titulo','tipo','icone','rotulo','itens':[str]}]}]"""
    if not os.path.exists(caminho):
        return []
    with open(caminho, encoding="utf-8") as f:
        linhas = f.read().splitlines()

    versoes, atual, bloco = [], None, None
    re_versao = re.compile(r"^##\s+\[([^\]]+)\]\s*[—\-–]\s*(.+?)\s*$")
    for ln in linhas:
        m = re_versao.match(ln)
        if m:
            atual = {"versao": m.group(1).strip(), "data": m.group(2).strip(),
                     "blocos": []}
            versoes.append(atual)
            bloco = None
            continue
        if atual is None:
            continue
        if ln.startswith("### "):
            titulo = ln[4:].strip()
            chave, icone, rotulo = _classificar(titulo)
            bloco = {"titulo": titulo, "tipo": chave, "icone": icone,
                     "rotulo": rotulo, "itens": []}
            atual["blocos"].append(bloco)
            continue
        if bloco is not None and ln.strip().startswith("- "):
            bloco["itens"].append(ln.strip()[2:].strip())
        elif bloco is not None and ln.startswith("  ") and ln.strip() and bloco["itens"]:
            bloco["itens"][-1] += " " + ln.strip()      # continuação da linha anterior
    return versoes


_CSS = """
:root{--bg:#080c14;--surface:#0d1421;--card:#111927;--border:#1a2640;
 --azul:#3b82f6;--verde:#10b981;--ambar:#f59e0b;--vermelho:#ef4444;
 --roxo:#a855f7;--rosa:#ec4899;--texto:#e2e8f0;--suave:#64748b;--suave2:#94a3b8;
 --mono:'Consolas','IBM Plex Mono',monospace;
 --corpo:'Segoe UI',system-ui,-apple-system,sans-serif}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--texto);font-family:var(--corpo);
 font-size:15px;line-height:1.7;padding:40px 24px}
.wrap{max-width:960px;margin:0 auto}
header{border-left:4px solid var(--azul);padding-left:18px;margin-bottom:28px}
h1{font-size:28px;font-weight:700;letter-spacing:-.02em}
.sub{color:var(--suave2);font-size:14px;margin-top:6px}
.stats{display:flex;flex-wrap:wrap;gap:12px;margin:24px 0}
.stat{background:var(--card);border:1px solid var(--border);border-radius:10px;
 padding:12px 18px;flex:1 1 130px}
.stat .n{font-size:24px;font-weight:700;font-family:var(--mono)}
.stat .r{color:var(--suave);font-size:11px;text-transform:uppercase;
 letter-spacing:.08em;margin-top:2px}
.filtros{display:flex;flex-wrap:wrap;gap:8px;margin:22px 0 28px;
 position:sticky;top:0;background:var(--bg);padding:12px 0;z-index:10;
 border-bottom:1px solid var(--border)}
.filtro{background:var(--surface);border:1px solid var(--border);color:var(--suave2);
 border-radius:20px;padding:6px 14px;font-size:12px;cursor:pointer;
 font-family:var(--mono);transition:.15s}
.filtro:hover{border-color:var(--azul);color:var(--texto)}
.filtro.on{background:var(--azul);border-color:var(--azul);color:#fff}
.versao{margin-bottom:34px;scroll-margin-top:80px}
.vh{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;
 border-bottom:1px solid var(--border);padding-bottom:8px;margin-bottom:14px}
.vnum{font-family:var(--mono);font-size:20px;font-weight:600;color:#fff}
.vdata{color:var(--suave);font-size:12.5px;font-family:var(--mono)}
.vtags{margin-left:auto;display:flex;gap:6px;flex-wrap:wrap}
.bloco{background:var(--card);border:1px solid var(--border);border-radius:10px;
 padding:14px 18px;margin-bottom:10px;border-left:3px solid var(--suave)}
.bloco.critico{border-left-color:var(--vermelho)}
.bloco.correcao{border-left-color:var(--ambar)}
.bloco.novidade{border-left-color:var(--verde)}
.bloco.performance{border-left-color:var(--roxo)}
.bloco.visual{border-left-color:var(--rosa)}
.bloco.teste{border-left-color:var(--azul)}
.bt{display:flex;align-items:center;gap:9px;margin-bottom:8px;flex-wrap:wrap}
.bt h3{font-size:14.5px;font-weight:600;color:#fff}
.tag{font-family:var(--mono);font-size:9.5px;letter-spacing:.09em;
 padding:2px 8px;border-radius:4px;background:var(--surface);
 border:1px solid var(--border);color:var(--suave2);white-space:nowrap}
.tag.critico{color:var(--vermelho);border-color:#7f1d1d}
.tag.correcao{color:var(--ambar);border-color:#78350f}
.tag.novidade{color:var(--verde);border-color:#065f46}
.tag.performance{color:var(--roxo);border-color:#581c87}
.tag.visual{color:var(--rosa);border-color:#831843}
.tag.teste{color:var(--azul);border-color:#1e3a8a}
ul{list-style:none;padding-left:2px}
li{position:relative;padding-left:16px;margin:5px 0;font-size:13.5px;
 color:var(--suave2);line-height:1.65}
li:before{content:"▸";position:absolute;left:0;color:var(--suave)}
li strong{color:var(--texto);font-weight:600}
code{font-family:var(--mono);font-size:12px;background:var(--surface);
 border:1px solid var(--border);border-radius:4px;padding:1px 5px;color:#a5d6ff}
.oculto{display:none}
footer{color:var(--suave);font-size:12px;text-align:center;margin-top:40px;
 padding-top:20px;border-top:1px solid var(--border)}
@media print{body{background:#fff;color:#000}.filtros{display:none}}
"""

_JS = """
document.querySelectorAll('.filtro').forEach(function(b){
  b.addEventListener('click', function(){
    document.querySelectorAll('.filtro').forEach(function(x){x.classList.remove('on')});
    b.classList.add('on');
    var t = b.dataset.tipo;
    document.querySelectorAll('.bloco').forEach(function(el){
      el.classList.toggle('oculto', t !== 'todos' && !el.classList.contains(t));
    });
    document.querySelectorAll('.versao').forEach(function(v){
      var visiveis = v.querySelectorAll('.bloco:not(.oculto)').length;
      v.classList.toggle('oculto', visiveis === 0);
    });
  });
});
"""


def gerar_html(versoes: list) -> str:
    total_blocos = sum(len(v["blocos"]) for v in versoes)
    n_corr = sum(1 for v in versoes for b in v["blocos"]
                 if b["tipo"] in ("correcao", "critico"))
    n_nov = sum(1 for v in versoes for b in v["blocos"] if b["tipo"] == "novidade")
    atual = versoes[0]["versao"] if versoes else "—"

    filtros = [("todos", "TODOS"), ("novidade", "✨ NOVIDADES"),
               ("correcao", "🔧 CORREÇÕES"), ("critico", "🚨 CRÍTICOS"),
               ("performance", "⚡ PERFORMANCE"), ("visual", "🎨 VISUAL"),
               ("teste", "🧪 TESTES")]
    html_filtros = "".join(
        f'<button class="filtro{" on" if k == "todos" else ""}" data-tipo="{k}">{r}</button>'
        for k, r in filtros)

    partes = []
    for v in versoes:
        tipos = sorted({b["tipo"] for b in v["blocos"]})
        tags = "".join(
            f'<span class="tag {t}">{dict((x[0], x[3]) for x in _TIPOS).get(t, "NOVIDADE")}</span>'
            for t in tipos)
        blocos = []
        for b in v["blocos"]:
            itens = "".join(f"<li>{_inline_md(i)}</li>" for i in b["itens"])
            blocos.append(
                f'<div class="bloco {b["tipo"]}"><div class="bt">'
                f'<span>{b["icone"]}</span><h3>{_inline_md(b["titulo"])}</h3>'
                f'<span class="tag {b["tipo"]}">{b["rotulo"]}</span></div>'
                f'<ul>{itens}</ul></div>')
        partes.append(
            f'<div class="versao" id="v{html.escape(v["versao"])}">'
            f'<div class="vh"><span class="vnum">v{html.escape(v["versao"])}</span>'
            f'<span class="vdata">{html.escape(v["data"])}</span>'
            f'<span class="vtags">{tags}</span></div>'
            f'{"".join(blocos)}</div>')

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Max_Importa — Histórico de Versões</title>
<style>{_CSS}</style></head><body><div class="wrap">
<header>
  <h1>Max_Importa — Histórico de Versões</h1>
  <div class="sub">Tudo que mudou em cada versão: correções e novas implementações.
  Gerado a partir do <code>CHANGELOG.md</code>.</div>
</header>
<div class="stats">
  <div class="stat"><div class="n">{len(versoes)}</div><div class="r">versões</div></div>
  <div class="stat"><div class="n">v{html.escape(atual)}</div><div class="r">versão atual</div></div>
  <div class="stat"><div class="n">{n_nov}</div><div class="r">novidades</div></div>
  <div class="stat"><div class="n">{n_corr}</div><div class="r">correções</div></div>
  <div class="stat"><div class="n">{total_blocos}</div><div class="r">alterações</div></div>
</div>
<div class="filtros">{html_filtros}</div>
{''.join(partes)}
<footer>Max_Importa — documentação gerada em
{datetime.now().strftime('%d/%m/%Y %H:%M')} por <code>gerar_historico.py</code>
a partir do CHANGELOG.md</footer>
</div><script>{_JS}</script></body></html>"""


def main() -> int:
    versoes = parse_changelog(_CHANGELOG)
    if not versoes:
        print(f"ERRO: nenhuma versão encontrada em {_CHANGELOG}")
        return 1
    with open(_SAIDA, "w", encoding="utf-8") as f:
        f.write(gerar_html(versoes))
    blocos = sum(len(v["blocos"]) for v in versoes)
    print(f"OK: {os.path.basename(_SAIDA)} gerado — {len(versoes)} versões, "
          f"{blocos} alterações (mais recente: v{versoes[0]['versao']}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
