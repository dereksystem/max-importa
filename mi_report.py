"""mi_report — geração de relatórios/arquivos de resultado do Max_Importa.

Extraído de max_importa.py na refatoração do monólito. Reúne os utilitários que
rodam ao FINAL de cada importação (arquivo de erros, mensagem amigável de
obrigatórios, renomear o arquivo importado, resetar a tela, exportação
estruturada em JSON/CSV e o pós-importação que orquestra tudo).

As funções recebem a janela (`win`) por parâmetro (duck typing: usam win._log,
win.conn, win.csv_path, etc.), então NÃO importam as classes de GUI — evitando
dependência circular com max_importa.
"""
import os
import csv
import html
import json
from datetime import datetime

from mi_config import _get_log_dir, APP_VERSION, MD_GRAY


# ─────────────────────────────────────────────────────────────────────────────
# Relatório HTML de fechamento — autocontido (CSS inline, sem CDN/JS externo),
# abre com duplo clique em qualquer navegador. Complementa o .txt/.json: o .txt é
# para ler no editor, o .json para integrar, e o HTML para ENTENDER de relance
# (cartões, barras proporcionais e as falhas em tabela filtrável pelo navegador).
# ─────────────────────────────────────────────────────────────────────────────
_CSS = """
:root{--vermelho:#CC0000;--ok:#1a7a3c;--alerta:#B8860B;--erro:#B00000;
      --texto:#1F2328;--suave:#6B7280;--borda:#E5E7EB;--fundo:#F7F8FA}
*{box-sizing:border-box}
body{margin:0;padding:24px;background:var(--fundo);color:var(--texto);
     font-family:'Segoe UI',system-ui,-apple-system,sans-serif;font-size:14px}
.wrap{max-width:1100px;margin:0 auto}
header{border-left:5px solid var(--vermelho);padding:4px 0 4px 14px;margin-bottom:18px}
h1{margin:0;font-size:21px}
.meta{color:var(--suave);font-size:12px;margin-top:6px;line-height:1.7}
.meta b{color:var(--texto);font-weight:600}
.banner{padding:12px 16px;border-radius:8px;margin:16px 0;font-weight:600}
.b-ok{background:#E8F5EC;color:var(--ok);border:1px solid #BFE3CB}
.b-erro{background:#FDECEC;color:var(--erro);border:1px solid #F5C2C2}
.b-sim{background:#EEF2FF;color:#3730A3;border:1px solid #C7D2FE}
.cards{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}
.card{flex:1 1 150px;background:#fff;border:1px solid var(--borda);border-radius:10px;
      padding:14px 16px}
.card .n{font-size:26px;font-weight:700;line-height:1.1}
.card .r{color:var(--suave);font-size:12px;margin-top:2px}
.barras{background:#fff;border:1px solid var(--borda);border-radius:10px;padding:14px 16px}
.linha{display:flex;align-items:center;gap:10px;margin:7px 0}
.linha .rot{width:130px;font-size:12px;color:var(--suave);flex:none}
.linha .trilho{flex:1;background:#EFF1F4;border-radius:5px;height:14px;overflow:hidden}
.linha .fill{height:100%;border-radius:5px}
.linha .val{width:70px;text-align:right;font-size:12px;font-variant-numeric:tabular-nums}
section{background:#fff;border:1px solid var(--borda);border-radius:10px;
        padding:14px 16px;margin:16px 0}
section>h2{margin:0 0 10px;font-size:15px}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--borda)}
th{background:#FAFBFC;font-weight:600;position:sticky;top:0}
.rolagem{max-height:340px;overflow:auto;border:1px solid var(--borda);border-radius:8px}
.mono{font-family:Consolas,'Courier New',monospace;font-size:12px;white-space:pre-wrap;
      line-height:1.55;margin:0}
details>summary{cursor:pointer;font-weight:600;font-size:15px}
.nota{color:var(--suave);font-size:11.5px;margin-top:8px}
footer{color:var(--suave);font-size:11.5px;text-align:center;margin:22px 0 4px}
@media print{body{background:#fff;padding:0}.rolagem{max-height:none}}
"""


def _esc(v) -> str:
    return html.escape("" if v is None else str(v))


def _card(numero, rotulo, cor) -> str:
    return (f'<div class="card"><div class="n" style="color:{cor}">{_esc(numero)}</div>'
            f'<div class="r">{_esc(rotulo)}</div></div>')


def _barras(itens) -> str:
    """itens = [(rótulo, valor, cor)] — barras proporcionais ao maior valor."""
    itens = [(r, v, c) for r, v, c in itens if isinstance(v, (int, float))]
    if not itens:
        return ""
    maior = max((v for _r, v, _c in itens), default=0) or 1
    linhas = []
    for rot, val, cor in itens:
        pct = max(0.0, (val / maior) * 100.0)
        linhas.append(
            f'<div class="linha"><div class="rot">{_esc(rot)}</div>'
            f'<div class="trilho"><div class="fill" style="width:{pct:.1f}%;'
            f'background:{cor}"></div></div>'
            f'<div class="val">{val:,}</div></div>'.replace(",", "."))
    return '<div class="barras">' + "".join(linhas) + "</div>"


def _tabela(colunas, linhas, limite=1000) -> str:
    if not linhas:
        return ""
    cortou = len(linhas) > limite
    corpo = []
    for ln in linhas[:limite]:
        corpo.append("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in ln) + "</tr>")
    nota = (f'<div class="nota">Mostrando as {limite} primeiras de '
            f'{len(linhas)} linhas.</div>') if cortou else ""
    return ('<div class="rolagem"><table><thead><tr>'
            + "".join(f"<th>{_esc(c)}</th>" for c in colunas)
            + "</tr></thead><tbody>" + "".join(corpo) + "</tbody></table></div>" + nota)


def _documento(titulo, meta_html, banner_html, corpo_html) -> str:
    return (
        "<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{_esc(titulo)}</title><style>{_CSS}</style></head><body><div class='wrap'>"
        f"<header><h1>{_esc(titulo)}</h1><div class='meta'>{meta_html}</div></header>"
        f"{banner_html}{corpo_html}"
        f"<footer>Max_Importa v{_esc(APP_VERSION)} — gerado em "
        f"{_esc(datetime.now().strftime('%d/%m/%Y %H:%M:%S'))}</footer>"
        "</div></body></html>")


def _secoes_alertas(win) -> str:
    """Alertas de qualidade acumulados: regras de negócio, datas e pgtPago."""
    linhas = []
    for cat, cont in sorted((getattr(win, "_alertas_regras", None) or {}).items()):
        linhas.append((cat, cont, "Regra de negócio"))
    for campo, cont in sorted((getattr(win, "_datas_invalidas", None) or {}).items()):
        linhas.append((f"Data não reconhecida em {campo}", cont, "Gravado como NULL"))
    for valor, cont in sorted((getattr(win, "_pago_invalidos", None) or {}).items()):
        linhas.append((f"pgtPago fora do padrão: '{valor}'", cont,
                       "Normalizado pelo pgtDataQuitou"))
    if not linhas:
        return ('<section><h2>✅ Qualidade dos dados</h2>'
                '<div class="nota">Nenhum alerta — documentos, datas e valores '
                'dentro do esperado.</div></section>')
    return ('<section><h2>⚠️ Qualidade dos dados</h2>'
            + _tabela(["Ocorrência", "Qtde", "Tratamento"], linhas)
            + '<div class="nota">Os registros foram processados; estes avisos apontam '
              'dados a revisar na ORIGEM.</div></section>')


def _gerar_html(win, prefixo: str, nomes_erro: list) -> str:
    """Gera o relatório HTML da importação. Retorna o caminho, ou '' se falhar.
    Best-effort: nunca interrompe a importação."""
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = _get_log_dir()
        os.makedirs(log_dir, exist_ok=True)
        res = getattr(win, "_ultimo_resultado", None) or {}
        ins = res.get("inseridos", 0) or 0
        pul = res.get("pulados", 0) or 0
        err = res.get("erros", 0) or 0
        simulacao = bool(res.get("simulacao"))

        meta = (f"<b>Operação:</b> {_esc(prefixo)} &nbsp;·&nbsp; "
                f"<b>Banco:</b> {_esc(_nome_banco(win) or '—')}<br>"
                f"<b>Arquivo:</b> "
                f"{_esc(os.path.basename(getattr(win, 'csv_path', '') or '') or '—')}")

        if simulacao:
            banner = ('<div class="banner b-sim">🔎 SIMULAÇÃO — nenhum dado foi gravado. '
                      'Os números abaixo mostram o que ACONTECERIA na importação real.</div>')
        elif err:
            banner = (f'<div class="banner b-erro">❌ Concluído com {err} erro(s) — '
                      f'veja a seção de falhas.</div>')
        else:
            banner = '<div class="banner b-ok">✅ Concluído sem erros.</div>'

        rot_ins = "Seriam inseridos" if simulacao else "Inseridos"
        cards = ('<div class="cards">'
                 + _card(ins, rot_ins, "var(--ok)")
                 + _card(pul, "Pulados", "var(--alerta)")
                 + _card(err, "Erros", "var(--erro)")
                 + _card(ins + pul + err, "Total processado", "var(--texto)")
                 + "</div>")
        graf = _barras([(rot_ins, ins, "#1a7a3c"), ("Pulados", pul, "#D9A21B"),
                        ("Erros", err, "#CC3333")])

        corpo = [cards, graf, _secoes_alertas(win)]

        nao_enc = getattr(win, "nao_encontrados", None) or []
        if nao_enc:
            linhas = [(i.get("_linha", ""), i.get("_cpfcnpj", "")) for i in nao_enc]
            corpo.append('<section><h2>⚠️ CPF/CNPJ não encontrados '
                         f'({len(nao_enc)})</h2>'
                         + _tabela(["Linha do arquivo", "CPF/CNPJ"], linhas)
                         + '<div class="nota">Estas linhas NÃO foram inseridas: o '
                           'documento não existe na tabela <code>cliente</code> do '
                           'destino.</div></section>')

        if nomes_erro:
            corpo.append(f'<section><h2>❌ Itens com erro ({len(nomes_erro)})</h2>'
                         + _tabela(["Item"], [(n,) for n in nomes_erro]) + "</section>")

        logs = getattr(win, "log_lines", None) or []
        if logs:
            corpo.append('<section><details><summary>📄 Log completo '
                         f'({len(logs)} linhas)</summary>'
                         f'<div class="rolagem" style="margin-top:10px">'
                         f'<pre class="mono">{_esc(chr(10).join(str(l) for l in logs))}'
                         f'</pre></div></details></section>')

        titulo = f"Max_Importa — {prefixo}" + (" (SIMULAÇÃO)" if simulacao else "")
        caminho = os.path.join(log_dir, f"RELATORIO_{prefixo}_{ts}.html")
        with open(caminho, "w", encoding="utf-8") as f:
            f.write(_documento(titulo, meta, banner, "".join(corpo)))
        return caminho
    except Exception:
        return ""


def _gerar_arquivo_erros(prefixo: str, nomes_erro: list) -> str:
    """Gera um TXT com os nomes dos itens/clientes que deram erro na importacao.
    Retorna o caminho do arquivo gerado, ou None se nao houver erros."""
    if not nomes_erro:
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = _get_log_dir()
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, f"ERROS_{prefixo}_{ts}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"=== ITENS COM ERRO NA IMPORTACAO ({prefixo}) ===\n")
        f.write(f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
        f.write(f"Total com erro: {len(nomes_erro)}\n\n")
        for n in nomes_erro:
            f.write(str(n) + "\n")
    return path


def _montar_msg_obrigatorios(invalidos: dict, descr_map: dict,
                             prefixo_erros: str, contexto: str = "") -> tuple:
    """Monta a mensagem AMIGAVEL de campos obrigatorios em branco e gera o
    arquivo de erros correspondente (com nomes amigaveis).

    invalidos     : {campo_db: [linha, ...]}
    descr_map     : {campo_db: "Nome amigavel"}
    prefixo_erros : usado no nome do arquivo ERROS_<prefixo>_...txt
    contexto      : texto opcional exibido logo no inicio da mensagem.

    Retorna (msg, caminho_arquivo_erros, total_celulas, total_linhas)."""
    total = sum(len(v) for v in invalidos.values())
    linhas_afetadas = set()
    for ls in invalidos.values():
        linhas_afetadas.update(ls)

    linhas_msg = []
    for campo in sorted(invalidos, key=lambda c: -len(invalidos[c])):
        ls = sorted(invalidos[campo])
        amostra = ", ".join(str(l) for l in ls[:8])
        suf = (f"  (e mais {len(ls) - 8} linha(s))") if len(ls) > 8 else ""
        nome = descr_map.get(campo, campo)
        linhas_msg.append(
            f"  • {nome}  [{campo}]\n"
            f"       {len(ls)} linha(s) em branco — ex.: {amostra}{suf}")

    linhas_erro = [f"{descr_map.get(campo, campo)} [{campo}] - linha {l}"
                   for campo in sorted(invalidos) for l in sorted(invalidos[campo])]
    ep = _gerar_arquivo_erros(prefixo_erros, linhas_erro)

    msg = (
        "A importacao foi INTERROMPIDA porque ha campos OBRIGATORIOS "
        "em branco no arquivo.\n\n"
        + ((contexto + "\n\n") if contexto else "")
        + f"Faltam preencher {total} celula(s), em {len(linhas_afetadas)} linha(s):\n\n"
        + "\n".join(linhas_msg)
        + "\n\n────────────────────────────────────────\n"
        "O QUE FAZER: abra o arquivo, preencha os campos acima nas "
        "linhas indicadas e importe novamente.\n"
        "(O numero da linha e o mesmo do arquivo, contando o cabecalho "
        "como linha 1.)"
    )
    if ep:
        msg += ("\n\nGeramos um arquivo com TODAS as linhas com problema:\n" + ep)
    return msg, ep, total, len(linhas_afetadas)


def _marcar_arquivo_importado(csv_path: str, houve_erros: bool) -> str:
    """Renomeia o arquivo importado acrescentando status + data/hora, para
    deixar claro que ele ja foi importado e evitar reimportacao acidental.
    Retorna o novo caminho, ou None se nao foi possivel renomear."""
    try:
        if not csv_path or not os.path.exists(csv_path):
            return None
        pasta       = os.path.dirname(csv_path)
        nome, ext   = os.path.splitext(os.path.basename(csv_path))
        status      = "COM_ERROS" if houve_erros else "OK"
        ts          = datetime.now().strftime("%Y%m%d_%H%M%S")
        novo        = os.path.join(pasta, f"{nome}_IMPORTADO_{status}_{ts}{ext}")
        os.rename(csv_path, novo)
        return novo
    except Exception:
        return None


def _resetar_selecao(win) -> None:
    """Limpa o arquivo carregado na tela (selecao, dataframe e botao) para
    impedir que o mesmo arquivo seja importado de novo por engano."""
    win.csv_path = None
    win.df = None
    try:
        win.lbl_arquivo.configure(text="Nenhum arquivo selecionado", text_color=MD_GRAY)
    except Exception:
        pass
    try:
        win.btn_import.configure(state="disabled")
    except Exception:
        pass


def _nome_banco(win) -> str:
    """Nome do banco conectado (via DB_NAME()), ou '' se indisponível."""
    try:
        cur = win.conn.cursor()
        cur.execute("SELECT DB_NAME()")
        return cur.fetchone()[0] or ""
    except Exception:
        return ""


def _exportar_resultado(win, prefixo: str, nomes_erro: list) -> None:
    """Exporta o resultado da operação de forma ESTRUTURADA (além dos .txt):
      - RESULTADO_<prefixo>_<ts>.json : resumo (versão, banco, contagens, erros);
      - ERROS_<prefixo>_<ts>.csv      : itens com erro (abre no Excel), se houver.
    Best-effort: nunca interrompe a importação se a exportação falhar."""
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = _get_log_dir()
        os.makedirs(log_dir, exist_ok=True)
        resultado = getattr(win, "_ultimo_resultado", None) or {}
        dados = {
            "app_version": APP_VERSION,
            "operacao":   prefixo,
            "gerado_em":  datetime.now().isoformat(timespec="seconds"),
            "banco":      _nome_banco(win),
            "arquivo":    (os.path.basename(getattr(win, "csv_path", "") or "") or None),
            "resultado": {
                "inseridos": resultado.get("inseridos", 0),
                "pulados":   resultado.get("pulados", 0),
                "erros":     resultado.get("erros", 0),
            },
            "itens_com_erro": [str(n) for n in (nomes_erro or [])],
        }
        nao_enc = getattr(win, "nao_encontrados", None)
        if nao_enc:
            dados["nao_encontrados"] = nao_enc
        json_path = os.path.join(log_dir, f"RESULTADO_{prefixo}_{ts}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(dados, f, ensure_ascii=False, indent=2, default=str)
        win._log(f"🧾 Resultado (JSON) salvo: {os.path.basename(json_path)}")

        if nomes_erro:
            csv_path = os.path.join(log_dir, f"ERROS_{prefixo}_{ts}.csv")
            # utf-8-sig p/ o Excel abrir os acentos corretamente
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(["item_com_erro"])
                for n in nomes_erro:
                    w.writerow([str(n)])
            win._log(f"🧾 Erros (CSV) salvos: {os.path.basename(csv_path)}")
    except Exception as e:
        try:
            win._log(f"⚠️ Falha ao exportar resultado CSV/JSON: {str(e)[:150]}")
        except Exception:
            pass


def _pos_importacao(win, prefixo: str, nomes_erro: list, houve_erros: bool) -> None:
    """Executado ao final de cada importacao (com falha ou sucesso):
       1) gera TXT com os nomes que deram erro (se houver);
       2) exporta o resultado estruturado em JSON/CSV (alem do .txt);
       3) renomeia o arquivo importado com status + data/hora;
       4) reseta a selecao na tela (evita duplicidade de importacao).
    Em DRY-RUN (win._dry_run), pula (3) e (4): o arquivo NAO foi importado, entao
    nao deve ser marcado nem des-selecionado — o usuario re-roda como importacao real."""
    if nomes_erro:
        ep = _gerar_arquivo_erros(prefixo, nomes_erro)
        if ep:
            win._log(f"📄 Arquivo de erros gerado: {ep}")
    _exportar_resultado(win, prefixo, nomes_erro)
    _html = _gerar_html(win, prefixo, nomes_erro)
    if _html:
        win._log(f"🌐 Relatório HTML: {os.path.basename(_html)}")
    if not getattr(win, "_dry_run", False):
        novo = _marcar_arquivo_importado(getattr(win, "csv_path", None), houve_erros)
        if novo:
            win._log(f"📦 Arquivo importado renomeado para: {os.path.basename(novo)}")
        win.after(0, lambda: _resetar_selecao(win))
    # Desabilita o botão Cancelar ao encerrar a importação
    fin = getattr(win, "_op_finalizada", None)
    if fin:
        fin()
