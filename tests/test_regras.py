"""Testes das REGRAS DE NEGÓCIO por célula (mi_validacao) e do mecanismo de alertas.

Sem banco e sem GUI. Convenção testada: vazio NUNCA é inválido (ausência é tratada
pela validação de obrigatórios), e nenhuma regra pode lançar exceção.
"""
import os
import sys
from datetime import datetime

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import mi_validacao as val
from mi_db import MapeamentoDBMixin


# ── CPF ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("doc", [
    "52998224725",        # CPF válido conhecido
    "529.982.247-25",     # com máscara
    "11144477735",
])
def test_cpf_valido(doc):
    assert val.cpf_valido(doc) is True
    assert val.cpf_cnpj_valido(doc) is True


@pytest.mark.parametrize("doc", [
    "52998224726",        # último dígito errado
    "11111111111",        # todos repetidos
    "00000000000",
    "1234567890",         # 10 dígitos
])
def test_cpf_invalido(doc):
    assert val.cpf_valido(doc) is False


# ── CNPJ ─────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("doc", [
    "11222333000181",
    "11.222.333/0001-81",
])
def test_cnpj_valido(doc):
    assert val.cnpj_valido(doc) is True
    assert val.cpf_cnpj_valido(doc) is True


@pytest.mark.parametrize("doc", [
    "11222333000182",     # dígito errado
    "11111111111111",     # repetidos
    "1122233300018",      # 13 dígitos
])
def test_cnpj_invalido(doc):
    assert val.cnpj_valido(doc) is False


def test_cpf_cnpj_vazio_nao_e_invalido():
    """Ausência não é erro de formato — quem exige preenchimento é outra regra."""
    for vazio in ("", None, "NULL", "  ", "nan"):
        assert val.cpf_cnpj_valido(vazio) is True


def test_cpf_cnpj_quantidade_de_digitos_errada():
    assert val.cpf_cnpj_valido("123") is False
    assert val.cpf_cnpj_valido("123456789012") is False    # 12 dígitos


def test_documentos_reais_do_arquivo_do_usuario():
    """Documentos do cad_receber.txt real. O 07634590002105 aparecia como
    'CPF/CNPJ não encontrado' no log e é um CNPJ VÁLIDO — ou seja, o problema era
    cliente ausente no destino, não documento ruim. É justamente essa distinção
    que a regra passa a explicitar no log."""
    assert val.cpf_cnpj_valido("07634590002105") is True
    assert val.so_digitos("46.186.000/044-") == "46186000044"


# ── E-mail ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("mail, ok", [
    ("a@b.com", True),
    ("nome.sobrenome@empresa.com.br", True),
    ("", True),               # vazio é válido
    (None, True),
    ("semarroba.com", False),
    ("a@b", False),           # sem TLD
    ("a@@b.com", False),
    ("com espaco@b.com", False),
])
def test_email_valido(mail, ok):
    assert val.email_valido(mail) is ok


# ── Faixa de datas ───────────────────────────────────────────────────────────
def test_data_plausivel():
    assert val.data_plausivel(datetime(2026, 3, 1)) is True
    assert val.data_plausivel(None) is True                 # ausência é plausível
    assert val.data_plausivel(datetime(1800, 1, 1)) is False
    assert val.data_plausivel(datetime(2200, 1, 1)) is False
    # faixa customizada
    assert val.data_plausivel(datetime(1950, 1, 1), ano_min=1900) is True
    assert val.data_plausivel(datetime(1950, 1, 1), ano_min=1980) is False


# ── Valor ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("v, ok", [
    (10, True), (0, True), ("15,5".replace(",", "."), True),
    (-1, False), (-0.01, False),
    (None, True),          # ausência
    ("abc", True),         # não numérico é problema de outra regra
])
def test_valor_positivo(v, ok):
    assert val.valor_positivo(v) is ok


# ── Mecanismo de alertas (contagem + amostra + resumo) ───────────────────────
class _Obj(MapeamentoDBMixin):
    def __init__(self):
        self.mapping = {}
        self.logs = []
        self._log = self.logs.append


def test_registrar_alerta_conta_e_loga_amostra():
    o = _Obj()
    for i in range(7):
        o._registrar_alerta("CPF/CNPJ inválido", f"doc{i}")
    assert o._alertas_regras["CPF/CNPJ inválido"] == 7
    assert len(o.logs) == 5          # amostra: só os 5 primeiros


def test_resumo_alertas_agrega_por_categoria():
    o = _Obj()
    o._registrar_alerta("CPF/CNPJ inválido", "x")
    o._registrar_alerta("CPF/CNPJ inválido", "y")
    o._registrar_alerta("e-mail inválido", "z")
    resumo = o._resumo_alertas()
    assert len(resumo) == 1
    assert "3 ocorrência(s)" in resumo[0]
    assert "CPF/CNPJ inválido=2" in resumo[0]
    assert "e-mail inválido=1" in resumo[0]


def test_resumo_vazio_quando_nao_ha_alerta():
    assert _Obj()._resumo_alertas() == []


def test_alerta_nao_quebra_sem_log():
    """Objeto sem _log (headless cru) não pode explodir ao registrar alerta."""
    class _SemLog(MapeamentoDBMixin):
        mapping = {}
    o = _SemLog()
    o._registrar_alerta("qualquer", "valor")
    assert o._alertas_regras["qualquer"] == 1
