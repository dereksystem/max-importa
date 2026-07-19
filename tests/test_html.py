"""Testes do relatório HTML de fechamento (mi_report._gerar_html).

Sem GUI e sem banco: usa um objeto-janela falso. O diretório de log é redirecionado
para tmp_path, então nenhum teste escreve na pasta Log real.
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import mi_report as R


class _Win:
    """Janela falsa com o que _gerar_html consome (duck typing)."""
    def __init__(self, **kw):
        self.csv_path = kw.get("csv_path", r"C:\dados\cad_receber.txt")
        self._ultimo_resultado = kw.get("resultado",
                                        {"inseridos": 10, "pulados": 2, "erros": 1})
        self.nao_encontrados = kw.get("nao_encontrados", [])
        self.log_lines = kw.get("log_lines", ["10:00:00 | iniciou", "10:00:05 | terminou"])
        for attr in ("_alertas_regras", "_datas_invalidas", "_pago_invalidos"):
            if attr in kw:
                setattr(self, attr, kw[attr])
        self.logs = []
        self._log = self.logs.append
        self.conn = None          # _nome_banco cai no except e devolve ''


@pytest.fixture(autouse=True)
def _log_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_get_log_dir", lambda: str(tmp_path))


def _html_de(win):
    caminho = R._gerar_html(win, "FINANCEIRO", [])
    assert caminho and os.path.exists(caminho)
    return open(caminho, encoding="utf-8").read()


def test_gera_arquivo_html_com_estrutura_basica():
    txt = _html_de(_Win())
    assert txt.startswith("<!DOCTYPE html>")
    assert "<title>Max_Importa — FINANCEIRO</title>" in txt
    assert "cad_receber.txt" in txt
    assert "</html>" in txt


def test_numeros_e_rotulos_aparecem():
    txt = _html_de(_Win(resultado={"inseridos": 659, "pulados": 287, "erros": 0}))
    assert "659" in txt and "287" in txt
    assert "Inseridos" in txt and "Pulados" in txt
    assert "946" in txt          # total processado = 659+287+0


def test_banner_sucesso_x_erro():
    ok = _html_de(_Win(resultado={"inseridos": 5, "pulados": 0, "erros": 0}))
    assert "Concluído sem erros" in ok
    ruim = _html_de(_Win(resultado={"inseridos": 5, "pulados": 0, "erros": 3}))
    assert "Concluído com 3 erro" in ruim


def test_banner_simulacao():
    txt = _html_de(_Win(resultado={"simulacao": True, "inseridos": 7,
                                   "pulados": 1, "erros": 0}))
    assert "SIMULAÇÃO" in txt
    assert "nenhum dado foi gravado" in txt
    assert "Seriam inseridos" in txt      # rótulo muda no modo simulação


def test_tabela_de_nao_encontrados():
    win = _Win(nao_encontrados=[{"_linha": 40, "_cpfcnpj": "00000000000"},
                                {"_linha": 822, "_cpfcnpj": "07634590002105"}])
    txt = _html_de(win)
    assert "CPF/CNPJ não encontrados (2)" in txt
    assert "07634590002105" in txt
    assert "<td>822</td>" in txt


def test_secao_alertas_com_dados():
    win = _Win(_alertas_regras={"CPF/CNPJ inválido": 35, "e-mail inválido": 1},
               _datas_invalidas={"pgtData": 4},
               _pago_invalidos={"C": 12})
    txt = _html_de(win)
    assert "Qualidade dos dados" in txt
    assert "CPF/CNPJ inválido" in txt and "35" in txt
    assert "Data não reconhecida em pgtData" in txt
    assert "pgtPago fora do padrão" in txt


def test_secao_alertas_vazia_mostra_ok():
    txt = _html_de(_Win())
    assert "Nenhum alerta" in txt


def test_log_completo_embutido():
    txt = _html_de(_Win(log_lines=["linha A", "linha B", "linha C"]))
    assert "Log completo (3 linhas)" in txt
    assert "linha B" in txt


def test_escapa_html_perigoso():
    """Conteúdo vindo do arquivo do usuário não pode injetar markup."""
    win = _Win(nao_encontrados=[{"_linha": 1, "_cpfcnpj": "<script>alert(1)</script>"}],
               log_lines=["<img src=x onerror=alert(1)>"])
    txt = _html_de(win)
    assert "<script>alert(1)</script>" not in txt
    assert "&lt;script&gt;" in txt
    assert "<img src=x" not in txt


def test_nunca_lanca_com_janela_incompleta():
    """Objeto sem quase nada não pode derrubar a importação."""
    class _Vazio:
        pass
    caminho = R._gerar_html(_Vazio(), "CLIENTES", [])
    # ou gera um HTML mínimo, ou devolve '' — o que não pode é levantar exceção
    assert isinstance(caminho, str)


def test_itens_com_erro_listados():
    win = _Win()
    caminho = R._gerar_html(win, "CLIENTES", ["12345678900", "98765432100"])
    txt = open(caminho, encoding="utf-8").read()
    assert "Itens com erro (2)" in txt
    assert "98765432100" in txt


def test_tabela_limita_linhas_muito_grandes():
    win = _Win(nao_encontrados=[{"_linha": i, "_cpfcnpj": f"doc{i}"}
                                for i in range(1500)])
    txt = _html_de(win)
    assert "Mostrando as 1000 primeiras de 1500 linhas" in txt
