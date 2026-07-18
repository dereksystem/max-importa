"""mi_arquivo — leitura resiliente de arquivos tabulares para importação.

Unifica o que antes era DUPLICADO nos 3 `_carregar_colunas` (Produtos/Clientes/
Financeiro): detecção de encoding, detecção de separador e leitura via pandas.
Novidades desta camada:
  - suporte a **.xlsx/.xlsm** (via openpyxl), além de .txt/.csv;
  - **autodetecção de encoding** (BOM → charset-normalizer → fallback cp1252),
    no lugar do `latin1` fixo que corrompia acentos de arquivos utf-8/cp1252.

Sempre devolve um DataFrame de STRINGS (`dtype=str`) com as colunas já `strip()`,
igual ao que as janelas esperavam. Só depende de pandas (+ openpyxl para Excel).
"""
import os

import pandas as pd

# Filtros do diálogo de seleção de arquivo (as 3 janelas usam o mesmo).
FILETYPES = [
    ("Planilhas e textos", "*.xlsx *.xlsm *.csv *.txt"),
    ("Excel", "*.xlsx *.xlsm"),
    ("CSV / TXT", "*.csv *.txt"),
    ("Todos", "*.*"),
]

_EXT_EXCEL = (".xlsx", ".xlsm")


def detectar_encoding(path, amostra_bytes=65536):
    """Detecta o encoding de um arquivo de texto (domínio PT-BR: utf-8 × cp1252).
    1) BOM (determinístico): utf-8-sig, utf-16;
    2) tenta decodificar a amostra em **utf-8 estrito** — utf-8 é auto-validável,
       texto cp1252 com acento quase nunca é utf-8 válido por acidente;
    3) senão, assume **cp1252** (Windows-BR, superset do latin1 — cobre acentos e €).
    Deliberadamente NÃO usa detector estatístico (charset-normalizer): em amostras
    curtas ele erra o code page single-byte (cp1250/mac) e corromperia justamente os
    acentos que queremos preservar. Nunca lança: em qualquer falha, cai no fallback.
    """
    try:
        with open(path, "rb") as f:
            raw = f.read(amostra_bytes)
    except Exception:
        return "cp1252"
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        # A amostra pode ter cortado um caractere utf-8 multibyte ao meio; apara até
        # 3 bytes finais e re-tenta antes de descartar o utf-8.
        for corte in (1, 2, 3):
            try:
                raw[:-corte].decode("utf-8")
                return "utf-8"
            except UnicodeDecodeError:
                continue
        return "cp1252"


def detectar_separador(primeira_linha):
    """Heurística simples e estável: TAB > ';' > ',' (a mesma de antes)."""
    return "\t" if "\t" in primeira_linha else (";" if ";" in primeira_linha else ",")


def ler_arquivo_tabular(path, log=None):
    """Lê .xlsx/.xlsm/.csv/.txt como DataFrame de strings.
    - Excel: openpyxl (ignora encoding/separador — não se aplica).
    - Texto: encoding autodetectado + separador autodetectado.
    Retorna (df, info) onde `info` descreve o que foi detectado (para logar).
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in _EXT_EXCEL:
        df = pd.read_excel(path, dtype=str, engine="openpyxl")
        info = f"Excel ({ext}) via openpyxl"
    else:
        enc = detectar_encoding(path)
        try:
            with open(path, "r", encoding=enc, errors="replace") as f:
                primeira = f.readline().strip()
        except Exception:
            enc, primeira = "cp1252", ""
            with open(path, "r", encoding=enc, errors="replace") as f:
                primeira = f.readline().strip()
        sep = detectar_separador(primeira)
        df = pd.read_csv(path, sep=sep, encoding=enc, dtype=str,
                         on_bad_lines="warn")
        sep_nome = {"\t": "TAB", ";": "';'", ",": "','"}.get(sep, sep)
        info = f"texto (encoding={enc}, separador={sep_nome})"

    df.columns = [str(c).strip() for c in df.columns]
    if callable(log):
        try:
            log(f"📄 Lido como {info} — {len(df)} linha(s), {len(df.columns)} coluna(s)")
        except Exception:
            pass
    return df, info
