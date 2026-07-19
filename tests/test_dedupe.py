"""Testes do dedupe de clientes (mi_validacao): normalização, placeholder,
similaridade e detecção de pares prováveis.

Princípio testado: o dedupe APONTA, nunca funde. E vazio/placeholder não pode
gerar falso positivo em massa (todos os '00000000000' viram "o mesmo cliente").
"""
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import mi_validacao as val


# ── Normalização de nome ─────────────────────────────────────────────────────
@pytest.mark.parametrize("entrada, esperado", [
    ("Construtora São José LTDA", "CONSTRUTORA SAO JOSE"),
    ("CONSTRUTORA SAO JOSE ltda", "CONSTRUTORA SAO JOSE"),
    ("Comércio de Alimentos ME", "COMERCIO DE ALIMENTOS"),
    ("Padaria  Dois   Irmãos", "PADARIA DOIS IRMAOS"),
    ("AGRO-PECUÁRIA S/A", "AGRO PECUARIA"),
    ("Transportes X LTDA ME", "TRANSPORTES X"),
    ("", ""),
    (None, ""),
])
def test_normalizar_nome(entrada, esperado):
    assert val.normalizar_nome(entrada) == esperado


def test_normalizar_nome_iguala_variacoes_de_grafia():
    a = val.normalizar_nome("MARCOS JOSÉ SCHUCH")
    b = val.normalizar_nome("marcos jose schuch")
    assert a == b


# ── Documento placeholder ────────────────────────────────────────────────────
@pytest.mark.parametrize("doc, ehph", [
    ("00000000000", True),      # o caso REAL da base do usuário
    ("000.000.000-00", True),
    ("11111111111", True),
    ("", True),
    (None, True),
    ("52998224725", False),
    ("11222333000181", False),
])
def test_documento_placeholder(doc, ehph):
    assert val.documento_placeholder(doc) is ehph


# ── Similaridade ─────────────────────────────────────────────────────────────
def test_similaridade():
    assert val.similaridade("ABC", "ABC") == 1.0
    assert val.similaridade("", "ABC") == 0.0
    alta = val.similaridade("CONSTRUTORA SAO JOSE", "CONSTRUTORA SAO JOSE II")
    assert 0.85 < alta < 1.0
    baixa = val.similaridade("PADARIA CENTRAL", "METALURGICA NORTE")
    assert baixa < 0.5


# ── Detecção de duplicados ───────────────────────────────────────────────────
def _reg(ref, nome, doc, origem="arquivo"):
    return {"ref": ref, "nome": nome, "doc": doc, "origem": origem}


def test_detecta_mesmo_documento():
    pares = val.detectar_duplicados([
        _reg("A", "PADARIA CENTRAL", "52998224725"),
        _reg("B", "PADARIA CENTRAL LTDA", "529.982.247-25"),
    ])
    tipos = {p["tipo"] for p in pares}
    assert "documento" in tipos
    assert any(p["a"] == "A" and p["b"] == "B" for p in pares)


def test_placeholder_NAO_agrupa_todo_mundo():
    """Regressão do risco central: 7 clientes com 00000000000 não podem virar
    21 pares 'mesmo documento' — o placeholder não identifica ninguém."""
    regs = [_reg(f"L{i}", f"CLIENTE DIFERENTE {i}", "00000000000") for i in range(7)]
    pares = val.detectar_duplicados(regs)
    assert not any(p["tipo"] == "documento" for p in pares)


def test_detecta_nome_identico_apos_normalizacao():
    pares = val.detectar_duplicados([
        _reg("A", "Construtora São José LTDA", "00000000000"),
        _reg("B", "CONSTRUTORA SAO JOSE", ""),
    ])
    assert any(p["tipo"] == "nome-exato" for p in pares)


def test_nome_identico_com_documentos_diferentes_sinaliza_matriz_filial():
    pares = val.detectar_duplicados([
        _reg("A", "SUPERMERCADO BOM PRECO", "11222333000181"),
        _reg("B", "SUPERMERCADO BOM PRECO", "52998224725"),
    ])
    assert any("matriz/filial" in p["motivo"] for p in pares)


def test_detecta_nome_parecido():
    pares = val.detectar_duplicados([
        _reg("A", "DISTRIBUIDORA HORIZONTE", "00000000000"),
        _reg("B", "DISTRIBUIDORA HORIZONTES", "00000000000"),
    ])
    assert any(p["tipo"] == "nome-parecido" for p in pares)
    p = [x for x in pares if x["tipo"] == "nome-parecido"][0]
    assert "sem documento válido" in p["motivo"]


def test_nomes_diferentes_nao_geram_par():
    pares = val.detectar_duplicados([
        _reg("A", "PADARIA CENTRAL", "52998224725"),
        _reg("B", "METALURGICA NORTE", "11222333000181"),
    ])
    assert pares == []


def test_par_banco_x_banco_e_descartado():
    """Duplicidade que já existia no destino não foi criada por esta importação."""
    regs = [_reg("X", "MESMO NOME", "52998224725", origem="banco"),
            _reg("Y", "MESMO NOME", "52998224725", origem="banco")]
    assert val.detectar_duplicados(regs) == []
    # mas se um lado vier do arquivo, o par É relevante
    regs[1]["origem"] = "arquivo"
    assert len(val.detectar_duplicados(regs)) >= 1


def test_ja_cadastrado_nao_e_suspeita():
    """Arquivo × banco com MESMO documento e MESMO nome = cliente já cadastrado.
    Sem esta distinção, reimportar um arquivo já importado gerava centenas de
    falsos positivos (medido: 759 de 844 pares na base real)."""
    pares = val.detectar_duplicados([
        _reg("arquivo:linha 2", "PADARIA CENTRAL LTDA", "52998224725"),
        _reg("banco:cliId 10", "Padaria Central", "529.982.247-25", origem="banco"),
    ])
    assert len(pares) == 1
    assert pares[0]["tipo"] == "ja-cadastrado"


def test_mesmo_documento_com_nomes_DIFERENTES_e_suspeita_real():
    """Caso encontrado na base do usuário: dois nomes distintos sob o mesmo CNPJ."""
    pares = val.detectar_duplicados([
        _reg("arquivo:linha 5", "SAO JOSE AGRO INDUSTRIA", "43650452000121"),
        _reg("banco:cliId 90", "E F L XAVIER AGROINDUSTRIA LTDA", "43650452000121",
             origem="banco"),
    ])
    assert len(pares) == 1
    assert pares[0]["tipo"] == "documento"
    assert "NOMES DIFERENTES" in pares[0]["motivo"]


def test_duplicata_dentro_do_arquivo_continua_suspeita():
    """Dois registros iguais no MESMO arquivo são duplicata de verdade —
    não podem ser confundidos com 'já cadastrado'."""
    pares = val.detectar_duplicados([
        _reg("arquivo:linha 2", "PADARIA CENTRAL", "52998224725"),
        _reg("arquivo:linha 9", "PADARIA CENTRAL", "52998224725"),
    ])
    assert len(pares) == 1
    assert pares[0]["tipo"] == "documento"


def test_arquivo_contra_banco():
    pares = val.detectar_duplicados([
        _reg("arquivo:linha 2", "MARCOS JOSE SCHUCH", "00000000000"),
        _reg("banco:cliId 55", "Marcos José Schuch", "", origem="banco"),
    ])
    assert len(pares) == 1
    assert pares[0]["tipo"] == "nome-exato"


def test_nao_duplica_o_mesmo_par():
    """Um par que casa por documento E por nome deve aparecer uma vez só."""
    pares = val.detectar_duplicados([
        _reg("A", "PADARIA CENTRAL", "52998224725"),
        _reg("B", "PADARIA CENTRAL", "52998224725"),
    ])
    assert len(pares) == 1


def test_entrada_vazia_ou_none():
    assert val.detectar_duplicados([]) == []
    assert val.detectar_duplicados(None) == []


def test_desempenho_com_volume_realista():
    """430 do arquivo × 3.370 do banco (tamanho real da base) precisa rodar rápido —
    é o motivo da blocagem por prefixo em vez de comparar todos contra todos."""
    import time
    regs = [_reg(f"a{i}", f"CLIENTE NUMERO {i}", f"{i:011d}") for i in range(430)]
    regs += [_reg(f"b{i}", f"EMPRESA COMERCIAL {i}", f"{i + 500000:011d}", "banco")
             for i in range(3370)]
    ini = time.time()
    val.detectar_duplicados(regs)
    assert time.time() - ini < 10.0
