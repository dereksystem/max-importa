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
import json
from datetime import datetime

from mi_config import _get_log_dir, APP_VERSION, MD_GRAY


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
       4) reseta a selecao na tela (evita duplicidade de importacao)."""
    if nomes_erro:
        ep = _gerar_arquivo_erros(prefixo, nomes_erro)
        if ep:
            win._log(f"📄 Arquivo de erros gerado: {ep}")
    _exportar_resultado(win, prefixo, nomes_erro)
    novo = _marcar_arquivo_importado(getattr(win, "csv_path", None), houve_erros)
    if novo:
        win._log(f"📦 Arquivo importado renomeado para: {os.path.basename(novo)}")
    win.after(0, lambda: _resetar_selecao(win))
    # Desabilita o botão Cancelar ao encerrar a importação
    fin = getattr(win, "_op_finalizada", None)
    if fin:
        fin()
