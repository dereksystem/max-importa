"""mi_validacao — regras de validação PURAS da importação por arquivo.

Extraído dos métodos `_iniciar` das janelas na refatoração do monólito. São funções
puras (recebem o DataFrame + o mapping campo→coluna e devolvem o resultado), sem GUI e
sem banco — logo, testáveis diretamente. As janelas continuam cuidando da parte de
interface (ler os combos, mostrar messagebox, disparar a thread).

Convenção de "vazio": '', 'NULL', 'NONE', 'NAN' (case-insensitive) contam como vazio.
As linhas retornadas são 1-based do ARQUIVO (idx do DataFrame + 2, contando o cabeçalho).
"""

import re
from datetime import datetime

_VAZIOS = ("", "NULL", "NONE", "NAN")


def _e_vazio(valor) -> bool:
    s = str(valor).strip() if valor is not None else ""
    return s.upper() in _VAZIOS


# ─────────────────────────────────────────────────────────────────────────────
# Regras de NEGÓCIO por célula (usadas durante a importação, linha a linha).
# Todas devolvem True/False e NUNCA lançam — dado ruim não pode derrubar o import.
# Convenção: valor vazio NÃO é inválido (é ausência); quem exige preenchimento é a
# validação de obrigatórios.
# ─────────────────────────────────────────────────────────────────────────────
def so_digitos(valor) -> str:
    """Mantém apenas os dígitos (tira ponto, traço, barra, espaço)."""
    return re.sub(r"\D", "", str(valor)) if valor is not None else ""


def cpf_valido(doc) -> bool:
    """Dígitos verificadores do CPF (11 dígitos). Rejeita repetidos (111...)."""
    d = so_digitos(doc)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for tam in (9, 10):
        soma = sum(int(d[i]) * (tam + 1 - i) for i in range(tam))
        resto = soma % 11
        dv = 0 if resto < 2 else 11 - resto
        if dv != int(d[tam]):
            return False
    return True


def cnpj_valido(doc) -> bool:
    """Dígitos verificadores do CNPJ (14 dígitos). Rejeita repetidos."""
    d = so_digitos(doc)
    if len(d) != 14 or d == d[0] * 14:
        return False
    for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2],
                  [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        tam = len(pesos)
        soma = sum(int(d[i]) * pesos[i] for i in range(tam))
        resto = soma % 11
        dv = 0 if resto < 2 else 11 - resto
        if dv != int(d[tam]):
            return False
    return True


def cpf_cnpj_valido(doc) -> bool:
    """True se for CPF (11) ou CNPJ (14) com dígitos verificadores corretos.
    Vazio devolve True (ausência não é erro de formato)."""
    if _e_vazio(doc):
        return True
    d = so_digitos(doc)
    if len(d) == 11:
        return cpf_valido(d)
    if len(d) == 14:
        return cnpj_valido(d)
    return False          # nem CPF nem CNPJ (quantidade de dígitos errada)


_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


def email_valido(valor) -> bool:
    """Formato de e-mail. Vazio é válido (ausência não é erro)."""
    if _e_vazio(valor):
        return True
    return bool(_RE_EMAIL.match(str(valor).strip()))


def data_plausivel(dt, ano_min: int = 1900, ano_max: int = None) -> bool:
    """Data dentro de uma faixa razoável. Fora disso costuma ser erro de parse
    (ex.: dia/mês trocados virando 0202, ou serial Excel lido como ano).
    None é plausível (ausência). ano_max padrão = ano atual + 10."""
    if dt is None:
        return True
    if ano_max is None:
        ano_max = datetime.now().year + 10
    try:
        return ano_min <= dt.year <= ano_max
    except Exception:
        return True


def valor_positivo(valor) -> bool:
    """Valor monetário/quantidade não-negativo. Vazio é válido."""
    if valor is None:
        return True
    try:
        return float(valor) >= 0
    except Exception:
        return True       # não numérico é problema de outra regra, não desta


# ─────────────────────────────────────────────────────────────────────────────
# DEDUPE de clientes — detecta duplicados PROVÁVEIS, para conferência humana.
# NUNCA funde registros automaticamente: juntar dois clientes é irreversível e o
# risco de unir empresas distintas (matriz × filial, homônimos) é real. Aqui só
# se APONTA o par suspeito; a decisão é de quem conhece a base.
# ─────────────────────────────────────────────────────────────────────────────
import unicodedata

# Sufixos societários e ruídos que atrapalham a comparação de nomes.
_SUFIXOS = ("LTDA", "LTDA ME", "ME", "EPP", "EIRELI", "MEI", "SA", "S A",
            "CIA", "COMPANHIA", "SOCIEDADE ANONIMA", "EM RECUPERACAO JUDICIAL")


def normalizar_nome(nome) -> str:
    """Forma canônica para comparar: sem acento, maiúsculo, sem pontuação,
    sem sufixo societário e com espaços colapsados."""
    if nome is None:
        return ""
    s = unicodedata.normalize("NFKD", str(nome))
    s = "".join(c for c in s if not unicodedata.combining(c))   # tira acentos
    s = s.upper()
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)          # pontuação vira espaço
    s = re.sub(r"\s+", " ", s).strip()
    # remove sufixos societários no FIM do nome (repete: "X LTDA ME" -> "X")
    mudou = True
    while mudou:
        mudou = False
        for suf in sorted(_SUFIXOS, key=len, reverse=True):
            if s.endswith(" " + suf):
                s = s[: -(len(suf) + 1)].strip()
                mudou = True
    return s


def documento_placeholder(doc) -> bool:
    """True quando o documento é um 'preenchedor' que NÃO identifica ninguém —
    vazio ou todos os dígitos iguais (00000000000, 11111111111...). Encontrado
    de verdade na base: 7 clientes e 35 lançamentos com 00000000000."""
    d = so_digitos(doc)
    return (not d) or (len(set(d)) == 1)


def similaridade(a, b) -> float:
    """0.0 a 1.0 entre dois nomes JÁ normalizados. Usa difflib (biblioteca
    padrão) — sem dependência nova."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    import difflib
    return difflib.SequenceMatcher(None, a, b).ratio()


def _bloco(nome_norm: str) -> str:
    """Chave de BLOCAGEM: só compara nomes que começam igual. Sem isto seria
    O(n×m) de difflib (430 × 3.370 ≈ 1,4 milhão de comparações)."""
    return nome_norm[:4]


def detectar_duplicados(registros, limiar: float = 0.88, so_com_arquivo: bool = True,
                        max_achados: int = 5000, max_grupo: int = 30,
                        orcamento_similaridade: int = 120000):
    """Acha pares provavelmente duplicados.

    registros: lista de dicts {'ref': qualquer, 'nome': str, 'doc': str,
               'origem': 'arquivo'|'banco'}
    Retorna lista de dicts {'tipo','motivo','score','a','b'} ordenada por score
    decrescente. `tipo` ∈ ja-cadastrado | documento | nome-exato | nome-parecido.
    **ja-cadastrado** = arquivo × banco com mesmo documento E mesmo nome: não é
    suspeita, é o cliente que já existe no destino (o chamador costuma só contar).

    so_com_arquivo=True descarta pares banco×banco (duplicidade que já existia e
    não foi introduzida por esta importação).

    LIMITES (essenciais em base grande — dezenas de milhares de clientes):
    - um grupo com mais de `max_grupo` registros iguais vira **um resumo** em vez de
      C(k,2) pares — 200 clientes com o mesmo nome é 1 achado acionável, não 20 mil;
    - para em `max_achados` no total (além disso o relatório vira ruído);
    - a busca por nome PARECIDO respeita um orçamento de comparações.
    Sem esses limites, importar 55 mil clientes gerava ~8 MILHÕES de pares e um CSV de
    >1 GB, com o app congelado por minutos.
    """
    itens = []
    for r in registros or []:
        itens.append({
            "ref": r.get("ref"),
            "origem": r.get("origem", "arquivo"),
            "nome_norm": normalizar_nome(r.get("nome")),
            "doc": so_digitos(r.get("doc")),
            "doc_ph": documento_placeholder(r.get("doc")),
            "nome": r.get("nome"),
        })

    pares, vistos = [], set()

    def _cap():
        return len(pares) >= max_achados

    def _add(a, b, tipo, motivo, score):
        if _cap():
            return
        if so_com_arquivo and a["origem"] == "banco" and b["origem"] == "banco":
            return
        chave = tuple(sorted((str(a["ref"]), str(b["ref"]))))
        if chave in vistos:
            return
        vistos.add(chave)
        pares.append({"tipo": tipo, "motivo": motivo, "score": round(score, 3),
                      "a": a["ref"], "b": b["ref"],
                      "nome_a": a["nome"], "nome_b": b["nome"]})

    def _resumo(grupo, tipo, motivo):
        """Grupo grande demais para enumerar: 1 achado que representa o grupo."""
        if _cap():
            return
        a = grupo[0]
        pares.append({"tipo": tipo, "motivo": motivo, "score": 1.0,
                      "a": a["ref"], "b": f"+{len(grupo) - 1} outro(s)",
                      "nome_a": a["nome"], "nome_b": ""})

    # 1) mesmo documento REAL (placeholder não identifica ninguém)
    por_doc = {}
    for it in itens:
        if it["doc"] and not it["doc_ph"]:
            por_doc.setdefault(it["doc"], []).append(it)
    for doc, grupo in por_doc.items():
        if _cap():
            break
        if len(grupo) > max_grupo:      # doc repetido dezenas de vezes: resume
            _resumo(grupo, "documento",
                    f"CPF/CNPJ ({doc}) repetido em {len(grupo)} registros")
            continue
        for i in range(len(grupo)):
            for j in range(i + 1, len(grupo)):
                a, b = grupo[i], grupo[j]
                # Mesmo documento E mesmo nome, vindo de lados diferentes
                # (arquivo × banco), NÃO é duplicata suspeita: é o cliente que já
                # está cadastrado no destino. Sem esta distinção, reimportar um
                # arquivo já importado gera centenas de falsos positivos e o
                # sinal de verdade (mesmo doc com nomes DIFERENTES) se perde.
                if (a["origem"] != b["origem"]
                        and a["nome_norm"] and a["nome_norm"] == b["nome_norm"]):
                    _add(a, b, "ja-cadastrado",
                         "já cadastrado no destino (mesmo documento e nome)", 1.0)
                else:
                    motivo = f"mesmo CPF/CNPJ ({doc})"
                    if a["nome_norm"] != b["nome_norm"]:
                        motivo += " com NOMES DIFERENTES"
                    _add(a, b, "documento", motivo, 1.0)

    # 2) nome idêntico após normalização
    por_nome = {}
    for it in itens:
        if it["nome_norm"]:
            por_nome.setdefault(it["nome_norm"], []).append(it)
    for nome, grupo in por_nome.items():
        if _cap():
            break
        if len(grupo) > max_grupo:      # nome genérico repetido: resume
            _resumo(grupo, "nome-exato",
                    f"{len(grupo)} registros com o nome idêntico '{nome}'")
            continue
        for i in range(len(grupo)):
            for j in range(i + 1, len(grupo)):
                a, b = grupo[i], grupo[j]
                if a["doc"] and b["doc"] and a["doc"] != b["doc"] \
                        and not (a["doc_ph"] or b["doc_ph"]):
                    motivo = "nome idêntico, mas CPF/CNPJ diferentes (matriz/filial?)"
                else:
                    motivo = "nome idêntico"
                _add(a, b, "nome-exato", motivo, 1.0)

    # 3) nome PARECIDO — só dentro do mesmo bloco (performance) + orçamento
    comparacoes = 0
    blocos = {}
    for it in itens:
        if it["nome_norm"]:
            blocos.setdefault(_bloco(it["nome_norm"]), []).append(it)
    for _b, grupo in blocos.items():
        if _cap() or comparacoes >= orcamento_similaridade:
            break
        if len(grupo) < 2 or len(grupo) > 400:      # bloco gigante: não vale o custo
            continue
        for i in range(len(grupo)):
            if _cap() or comparacoes >= orcamento_similaridade:
                break
            for j in range(i + 1, len(grupo)):
                a, b = grupo[i], grupo[j]
                if a["nome_norm"] == b["nome_norm"]:
                    continue                        # já tratado no passo 2
                comparacoes += 1
                if comparacoes >= orcamento_similaridade:
                    break
                s = similaridade(a["nome_norm"], b["nome_norm"])
                if s >= limiar:
                    suf = " (ambos sem documento válido)" if (a["doc_ph"] and b["doc_ph"]) else ""
                    _add(a, b, "nome-parecido",
                         f"nomes {int(s * 100)}% parecidos{suf}", s)

    pares.sort(key=lambda p: (-p["score"], str(p["a"])))
    return pares


def campos_nao_mapeados(mapping: dict, campos_obrigatorios) -> list:
    """Retorna os campos obrigatórios que NÃO estão no mapping (ordem de entrada)."""
    return [c for c in campos_obrigatorios if c not in mapping]


def validar_obrigatorios(df, mapping: dict, campos_obrigatorios,
                         apenas_mapeados: bool = False) -> dict:
    """Retorna {campo_db: [linha_arquivo, ...]} das células obrigatórias VAZIAS.

    - apenas_mapeados=False (modo INSERT): checa todos os obrigatórios (assume que já
      foram validados como mapeados antes);
    - apenas_mapeados=True (modo UPDATE): checa só os obrigatórios que ESTÃO mapeados
      (os não mapeados mantêm o valor atual do banco).
    """
    invalidos = {}
    for idx, row in df.iterrows():
        linha = idx + 2
        for campo in campos_obrigatorios:
            col = mapping.get(campo)
            if col is None:
                continue   # não mapeado: INSERT já barrou antes; UPDATE mantém o banco
            if _e_vazio(row.get(col, None)):
                invalidos.setdefault(campo, []).append(linha)
    return invalidos


def linhas_ao_menos_um(df, mapping: dict, campo_a: str, campo_b: str) -> list:
    """Regra 'ao menos um dos dois preenchido por linha' (ex.: pgtTipoVista/pgtTipoPrazo).
    Retorna as linhas do arquivo em que AMBOS estão vazios. Se nenhum dos dois está
    mapeado, não há o que validar (retorna [])."""
    col_a = mapping.get(campo_a)
    col_b = mapping.get(campo_b)
    if not (col_a or col_b):
        return []
    erros = []
    for idx, row in df.iterrows():
        vazio_a = _e_vazio(row.get(col_a, "")) if col_a else True
        vazio_b = _e_vazio(row.get(col_b, "")) if col_b else True
        if vazio_a and vazio_b:
            erros.append(idx + 2)
    return erros


def ids_reservados(df, mapping: dict, campo: str, limite: int = 10) -> list:
    """Retorna os IDs (< limite) informados no arquivo que são RESERVADOS pelo sistema
    (ex.: cliId < 10). Ignora vazios e valores não numéricos. Se o campo não está
    mapeado, retorna []."""
    col = mapping.get(campo)
    if not col:
        return []
    reservados = []
    for _idx, row in df.iterrows():
        raw = str(row.get(col, "")).strip()
        if raw.upper() in _VAZIOS:
            continue
        try:
            v = int(float(raw))
        except Exception:
            continue
        if v < limite:
            reservados.append(v)
    return reservados
