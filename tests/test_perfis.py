"""Testes de mi_perfis — perfis de mapeamento de colunas por layout de arquivo.

Sem GUI e sem banco. O arquivo de perfis é redirecionado para tmp_path via
monkeypatch, então nenhum teste toca o max_importa_perfis.json real.
"""
import json
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import mi_perfis as P


@pytest.fixture(autouse=True)
def _perfis_tmp(tmp_path, monkeypatch):
    """Isola o arquivo de perfis por teste."""
    monkeypatch.setattr(P, "_PERFIS_PATH", str(tmp_path / "perfis.json"))


def test_listar_vazio_quando_nao_existe_arquivo():
    assert P.listar("FINANCEIRO") == []
    assert P.obter("FINANCEIRO", "qualquer") is None


def test_salvar_e_obter():
    mapping = {"cliCpfCgc": "CNPJ", "pgtValor": "VALOR"}
    assert P.salvar("FINANCEIRO", "Contmatic", mapping) is True
    assert P.listar("FINANCEIRO") == ["Contmatic"]
    assert P.obter("FINANCEIRO", "Contmatic") == mapping


def test_perfis_sao_isolados_por_modulo():
    P.salvar("FINANCEIRO", "X", {"a": "1"})
    P.salvar("CLIENTES", "Y", {"b": "2"})
    assert P.listar("FINANCEIRO") == ["X"]
    assert P.listar("CLIENTES") == ["Y"]
    assert P.obter("CLIENTES", "X") is None      # não vaza entre módulos


def test_sobrescrever_perfil():
    P.salvar("PRODUTOS", "P1", {"proDescricao": "DESC"})
    P.salvar("PRODUTOS", "P1", {"proDescricao": "NOME", "proCodigo": "COD"})
    assert P.obter("PRODUTOS", "P1") == {"proDescricao": "NOME", "proCodigo": "COD"}
    assert P.listar("PRODUTOS") == ["P1"]        # não duplicou


def test_listar_ordem_alfabetica():
    for n in ("Zeta", "alfa", "Beta"):
        P.salvar("CLIENTES", n, {"x": "y"})
    assert P.listar("CLIENTES") == sorted(["Zeta", "alfa", "Beta"])


def test_excluir():
    P.salvar("CLIENTES", "A", {"x": "1"})
    P.salvar("CLIENTES", "B", {"y": "2"})
    assert P.excluir("CLIENTES", "A") is True
    assert P.listar("CLIENTES") == ["B"]
    assert P.excluir("CLIENTES", "inexistente") is False


def test_excluir_ultimo_remove_o_modulo():
    P.salvar("CLIENTES", "unico", {"x": "1"})
    P.excluir("CLIENTES", "unico")
    assert P.listar("CLIENTES") == []


def test_salvar_rejeita_nome_ou_mapping_vazio():
    assert P.salvar("CLIENTES", "", {"a": "b"}) is False
    assert P.salvar("CLIENTES", "   ", {"a": "b"}) is False
    assert P.salvar("CLIENTES", "ok", {}) is False
    assert P.listar("CLIENTES") == []


def test_arquivo_corrompido_nao_derruba():
    """Perder um perfil não pode impedir a importação."""
    with open(P._PERFIS_PATH, "w", encoding="utf-8") as f:
        f.write("{isso não é json}")
    assert P.listar("FINANCEIRO") == []
    assert P.obter("FINANCEIRO", "x") is None
    # e ainda consegue gravar por cima
    assert P.salvar("FINANCEIRO", "novo", {"a": "b"}) is True
    assert P.listar("FINANCEIRO") == ["novo"]


def test_json_gravado_e_legivel():
    P.salvar("FINANCEIRO", "Perfil A", {"cliCpfCgc": "DOC"})
    with open(P._PERFIS_PATH, encoding="utf-8") as f:
        dados = json.load(f)
    assert dados == {"FINANCEIRO": {"Perfil A": {"cliCpfCgc": "DOC"}}}


# ── aplicavel(): confronta o perfil com as colunas do arquivo carregado ──────
def test_aplicavel_separa_existentes_e_ausentes():
    perfil = {"cliCpfCgc": "CNPJ", "pgtValor": "VALOR", "pgtData": "EMISSAO"}
    aplic, ausentes = P.aplicavel(perfil, ["CNPJ", "VALOR", "OUTRA"])
    assert aplic == {"cliCpfCgc": "CNPJ", "pgtValor": "VALOR"}
    assert ausentes == {"pgtData": "EMISSAO"}    # layout do arquivo mudou


def test_aplicavel_tudo_ausente():
    aplic, ausentes = P.aplicavel({"a": "X"}, ["Y", "Z"])
    assert aplic == {}
    assert ausentes == {"a": "X"}


def test_aplicavel_tolera_entradas_vazias():
    assert P.aplicavel(None, ["A"]) == ({}, {})
    assert P.aplicavel({"a": "X"}, None) == ({}, {"a": "X"})
