"""Testes de mi_arquivo — leitura resiliente (xlsx + autodetecção de encoding/sep).

Sem banco: só criam arquivos temporários e conferem o DataFrame lido.
"""
import os
import sys

import pandas as pd
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import mi_arquivo as A


# ── Separador ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("linha, esperado", [
    ("a\tb\tc", "\t"),
    ("a;b;c", ";"),
    ("a,b,c", ","),
    ("a\tb;c,d", "\t"),   # TAB tem prioridade
    ("a;b,c", ";"),        # ';' antes de ','
])
def test_detectar_separador(linha, esperado):
    assert A.detectar_separador(linha) == esperado


# ── Encoding ─────────────────────────────────────────────────────────────────
def test_detectar_encoding_bom_utf8(tmp_path):
    p = tmp_path / "bom.txt"
    p.write_bytes(b"\xef\xbb\xbfcol\nvalor\n")
    assert A.detectar_encoding(str(p)) == "utf-8-sig"


def test_detectar_encoding_utf16_bom(tmp_path):
    p = tmp_path / "u16.txt"
    p.write_bytes(b"\xff\xfec\x00o\x00l\x00")
    assert A.detectar_encoding(str(p)) == "utf-16"


def test_detectar_encoding_cp1252_acentos(tmp_path):
    # "coração" em cp1252 (não é utf-8 válido) — não pode quebrar nem detectar utf-8.
    p = tmp_path / "latin.txt"
    p.write_bytes("coração\nendereço\n".encode("cp1252"))
    enc = A.detectar_encoding(str(p))
    # aceita cp1252 ou o equivalente que o charset-normalizer devolva (windows-1252/latin-1)
    txt = open(str(p), encoding=enc, errors="strict").read()
    assert "coração" in txt   # o importante: lê o acento certo


# ── Leitura CSV/TXT com acento (regressão do latin1 fixo) ────────────────────
def test_ler_csv_utf8_com_acento(tmp_path):
    p = tmp_path / "u8.csv"
    p.write_text("nome;cidade\nJOSÉ;SÃO PAULO\n", encoding="utf-8")
    df, info = A.ler_arquivo_tabular(str(p))
    assert list(df.columns) == ["nome", "cidade"]
    assert df.iloc[0]["nome"] == "JOSÉ"
    assert df.iloc[0]["cidade"] == "SÃO PAULO"
    assert "encoding" in info


def test_ler_txt_tab_latin1(tmp_path):
    p = tmp_path / "l1.txt"
    p.write_bytes("cliCpfCgc\tpgtCliNome\n123\tMARÇO LTDA\n".encode("cp1252"))
    df, _ = A.ler_arquivo_tabular(str(p))
    assert list(df.columns) == ["cliCpfCgc", "pgtCliNome"]
    assert df.iloc[0]["pgtCliNome"] == "MARÇO LTDA"


def test_colunas_sao_stripadas(tmp_path):
    p = tmp_path / "sp.csv"
    p.write_text("  a ;b  \n1;2\n", encoding="utf-8")
    df, _ = A.ler_arquivo_tabular(str(p))
    assert list(df.columns) == ["a", "b"]


# ── Leitura XLSX (nova capacidade) ───────────────────────────────────────────
def test_ler_xlsx(tmp_path):
    p = tmp_path / "dados.xlsx"
    pd.DataFrame({
        "cliCpfCgc": ["123", "456"],
        "pgtValor": ["10,50", "20,00"],
        "pgtData": ["2026-03-01", "01/03/2026"],
    }).to_excel(str(p), index=False)
    df, info = A.ler_arquivo_tabular(str(p))
    assert "Excel" in info
    assert list(df.columns) == ["cliCpfCgc", "pgtValor", "pgtData"]
    assert len(df) == 2
    assert df.iloc[0]["cliCpfCgc"] == "123"       # veio como string (dtype=str)


def test_ler_xlsx_valores_como_string(tmp_path):
    """Excel guarda número/data como tipo nativo; a leitura deve devolver STRING
    (dtype=str) para o pipeline de mapeamento/_get_* funcionar igual ao CSV."""
    p = tmp_path / "num.xlsx"
    pd.DataFrame({"n": [42], "x": [3.5]}).to_excel(str(p), index=False)
    df, _ = A.ler_arquivo_tabular(str(p))
    assert isinstance(df.iloc[0]["n"], str)
    assert df.iloc[0]["n"] in ("42", "42.0")
