"""mi_db — mixin com os helpers de LEITURA de células mapeadas e de BANCO.

Extraído de max_importa.py na refatoração do monólito. Reúne, num único lugar, os
helpers que antes eram DUPLICADOS nas três janelas importadoras (Produtos, Clientes,
Financeiro):
  - parsing de células mapeadas: _get_str, _get_str_max, _get_int, _get_float,
    _get_decimal, _get_datetime, _to_decimal;
  - utilidades de banco (recebem um cursor): _lookup (com cache), _get_or_create,
    _get_emp_id, _lookup_unidade, _get_or_create_unidade, _lookup_cli_id.

As classes de janela herdam este mixin, então as chamadas continuam `self._get_str(...)`
etc. (nenhum call-site muda). Depende apenas de `self.mapping` e, opcionalmente, de
`self.FLOAT_NOT_NULL` (via getattr) e `self._lookup_cache`.
"""
import re
import time
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation


class MapeamentoDBMixin:
    # ── Retry de erros TRANSIENTES do SQL Server ───────────────────────────────
    # Números/estados que valem re-tentar (deadlock, lock/query timeout, queda de
    # conexão). Erros de DADOS (violação de PK/FK, truncamento 22001, conversão) NÃO
    # entram aqui — devem subir na hora, não adianta re-tentar.
    _ERR_TRANSIENTE_COD = {"1205", "1222", "-2", "10928", "10929", "40001", "40143",
                           "40197", "40501", "40613", "08s01", "08001", "hyt00", "hyt01"}
    _ERR_TRANSIENTE_TXT = ("deadlock", "timeout expired", "lock request time",
                           "communication link failure", "transport-level",
                           "connection is busy", "server failed to resume")

    def _e_transiente(self, e) -> bool:
        """True se o erro do SQL Server for transiente (vale re-tentar)."""
        txt = str(e).lower()
        estado = ""
        try:
            estado = str(e.args[0]).lower()
        except Exception:
            pass
        if estado in self._ERR_TRANSIENTE_COD:
            return True
        for cod in re.findall(r"\(\s*(-?\d+)\s*\)", txt):   # ex.: "... (1205)"
            if cod in self._ERR_TRANSIENTE_COD:
                return True
        return any(s in txt for s in self._ERR_TRANSIENTE_TXT)

    def _com_retry(self, op, descr="operação", tentativas=4, base=0.6):
        """Executa op() com retry exponencial em erro transiente. op() DEVE ser
        idempotente/segura para repetir (ex.: fazer rollback antes de re-tentar).
        Erro não-transiente sobe na hora. Respeita o cancelamento (self._cancelado)."""
        for i in range(tentativas):
            try:
                return op()
            except Exception as e:
                if (i == tentativas - 1 or not self._e_transiente(e)
                        or getattr(self, "_cancelado", False)):
                    raise
                espera = base * (2 ** i)
                try:
                    self._log(f"⏳ {descr}: erro transiente [{str(e)[:80]}] — nova "
                              f"tentativa em {espera:.1f}s ({i + 2}/{tentativas})")
                except Exception:
                    pass
                time.sleep(espera)

    # ── Parsing de células mapeadas ────────────────────────────────────────────
    def _to_decimal(self, value):
        if value is None:
            return None
        s = str(value).strip()
        if s.upper() in ('', 'NULL', 'NAN', 'NONE'):
            return None
        tem_ponto   = '.' in s
        tem_virgula = ',' in s
        if tem_ponto and tem_virgula:
            if s.index('.') < s.index(','):
                s = s.replace('.', '').replace(',', '.')
            else:
                s = s.replace(',', '')
        elif tem_virgula:
            s = s.replace(',', '.')
        s = re.sub(r'[^\d.\-]', '', s)
        if not s or s in ('.', '-', '-.'):
            return None
        try:
            d = Decimal(s).quantize(Decimal('0.00000'))
            return float(d)
        except (InvalidOperation, Exception):
            return None

    def _get_float(self, row, campo):
        col = self.mapping.get(campo)
        raw = row.get(col) if col else None
        val = self._to_decimal(raw)
        if val is None and campo in getattr(self, "FLOAT_NOT_NULL", frozenset()):
            return 0.0
        return val

    def _get_int(self, row, campo, default=None):
        col = self.mapping.get(campo)
        raw = row.get(col) if col else None
        if raw is None:
            return default
        s = str(raw).strip()
        if s.upper() in ('', 'NULL', 'NONE', 'NAN'):
            return default
        try:
            return int(float(s))
        except Exception:
            return default

    def _get_str(self, row, campo):
        col = self.mapping.get(campo)
        if not col:
            return None
        val = row.get(col)
        if val is None:
            return None
        s = str(val).strip()
        return None if s.upper() in ('', 'NULL', 'NONE', 'NAN') else s

    def _get_str_max(self, row, campo, max_len):
        """Igual ao _get_str, mas corta o valor no tamanho da coluna do banco,
        evitando o erro 22001 (dados seriam truncados)."""
        s = self._get_str(row, campo)
        if s is not None and max_len and len(s) > max_len:
            s = s[:max_len]
        return s

    def _get_decimal(self, row, campo):
        col = self.mapping.get(campo)
        raw = row.get(col) if col else None
        if raw is None:
            return None
        s = str(raw).strip().replace(",", ".")
        s = re.sub(r"[^\d.\-]", "", s)
        if not s:
            return None
        try:
            return Decimal(s).quantize(Decimal("0.00000"))
        except Exception:
            return None

    def _get_datetime(self, row, campo):
        col = self.mapping.get(campo)
        if not col:
            return None
        val = row.get(col)
        if val is None:
            return None
        # Já é datetime/Timestamp (caso da MIGRAÇÃO: a data vem do banco como objeto,
        # não como texto). Usa direto — sem passar por str()/parse. NaT (pandas) não é
        # igual a si mesmo -> vira NULL. Remove timezone (SQL Server 'datetime' não tem).
        if isinstance(val, datetime):
            if val != val:                 # NaT/NaN
                return None
            return val.replace(tzinfo=None) if val.tzinfo else val
        s = str(val).strip()
        if s.upper() in ("", "NULL", "NONE", "NAN", "NAT"):
            return None
        dt = self._parse_data_str(s)
        if dt is None:
            # NÃO devolve None em silêncio (foi o que escondeu o bug 3.6.9 por meses):
            # registra e loga uma amostra para o valor não reconhecido aparecer no LOG.
            self._registrar_data_invalida(campo, s)
        return dt

    # Formatos aceitos, em ordem de prioridade. IMPORTANTE: parse na STRING INTEIRA
    # (o bug 3.6.9 era s[:len(fmt)] — len("%Y-%m-%d")==8, mas a data tem 10 chars).
    # BR (dia primeiro) tem prioridade sobre US: este é um ERP brasileiro, então
    # "05/06/2026" é 05/jun. Ano com 2 dígitos vem por último p/ o de 4 dígitos vencer.
    _FMT_DATA = (
        # ISO com separador '/'
        "%Y/%m/%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d",
        # ISO com separador '-' (além do fromisoformat, cobre casos sem 'T')
        "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
        # BR barra
        "%d/%m/%Y %H:%M:%S.%f", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
        # BR traço
        "%d-%m-%Y %H:%M:%S.%f", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y",
        # BR ponto
        "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y",
        # US barra (fallback: só casa quando o BR falha, ex.: mês > 12 no 1º campo)
        "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y",
        # ano com 2 dígitos (por último)
        "%d/%m/%y %H:%M:%S", "%d/%m/%y %H:%M", "%d/%m/%y",
        "%d-%m-%y", "%d.%m.%y",
    )

    def _parse_data_str(self, s):
        """Converte texto -> datetime tentando muitos formatos (ISO, BR, US, serial
        Excel). Retorna None só quando NADA reconhece — o chamador então registra o
        valor para não somir em silêncio."""
        # ISO 8601 primeiro (aceita "2026-03-01" e "2026-03-01 12:34:56[.ffffff]").
        try:
            return datetime.fromisoformat(s.replace("T", " "))
        except Exception:
            pass
        for fmt in self._FMT_DATA:
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue
        # Serial do Excel (dias desde 1899-12-30): só dígitos, faixa plausível de
        # datas (~1954..2119) p/ não confundir com um número qualquer.
        try:
            if s.isdigit():
                n = int(s)
                if 20000 <= n <= 80000:
                    return datetime(1899, 12, 30) + timedelta(days=n)
        except Exception:
            pass
        return None

    def _registrar_data_invalida(self, campo, valor):
        """Contabiliza um valor de data não reconhecido (gravado como NULL) e loga
        uma amostra. Torna VISÍVEL o que antes era um None silencioso."""
        cont = getattr(self, "_datas_invalidas", None)
        if cont is None:
            cont = self._datas_invalidas = {}
        cont[campo] = cont.get(campo, 0) + 1
        log = getattr(self, "_log", None)
        n = cont[campo]
        if callable(log) and (n <= 5 or n % 500 == 0):
            try:                       # logar NUNCA pode abortar a importação
                log(f"⚠️  Data não reconhecida em '{campo}': '{str(valor)[:40]}' — "
                    f"gravada como NULL (amostra; {n} até agora). Confira o formato no arquivo.")
            except Exception:
                pass

    # ── Alertas de REGRA DE NEGÓCIO (qualidade do dado) ───────────────────────
    # Mesmo princípio das datas: problema de dado NÃO pode sumir em silêncio nem
    # derrubar a importação. Conta por categoria, loga uma amostra e devolve um
    # resumo agregado no fim.
    def _registrar_alerta(self, categoria, detalhe=None, msg=None):
        """Contabiliza um alerta e loga amostra (5 primeiros, depois a cada 500)."""
        cont = getattr(self, "_alertas_regras", None)
        if cont is None:
            cont = self._alertas_regras = {}
        cont[categoria] = cont.get(categoria, 0) + 1
        n = cont[categoria]
        log = getattr(self, "_log", None)
        if callable(log) and (n <= 5 or n % 500 == 0):
            try:                       # logar nunca pode abortar a importação
                log(msg or f"⚠️  {categoria}: '{detalhe}' (amostra; {n} até agora).")
            except Exception:
                pass

    def _resumo_alertas(self):
        """Linha de resumo agregado dos alertas. Lista vazia se não houve nenhum."""
        cont = getattr(self, "_alertas_regras", None)
        if not cont:
            return []
        det = ", ".join(f"{k}={v}" for k, v in sorted(cont.items()))
        tot = sum(cont.values())
        return [f"⚠️  QUALIDADE DOS DADOS: {tot} ocorrência(s) — {det}. "
                f"Os registros foram processados; revise a origem."]

    # ── Utilidades de banco (recebem cursor) ───────────────────────────────────
    def _lookup(self, cursor, tabela, id_col, nome_col, valor):
        """Busca por valor; retorna id ou None. Usa cache em memória (por execução)
        — como é somente leitura, é seguro memoizar e evita 1 SELECT por linha em
        tabelas grandes (ex.: proNCM com ~29 mil linhas)."""
        if not valor or str(valor).strip() == '':
            return None
        valor = str(valor).strip()
        cache = getattr(self, "_lookup_cache", None)
        if cache is None:
            cache = self._lookup_cache = {}
        chave = (tabela, nome_col, valor)
        if chave in cache:
            return cache[chave]
        cursor.execute(f"SELECT {id_col} FROM {tabela} WHERE {nome_col} = ?", (valor,))
        row = cursor.fetchone()
        rid = row[0] if row else None
        cache[chave] = rid
        return rid

    def _get_or_create(self, cursor, tabela, id_col, nome_col, valor, extra_cols=None):
        """Busca ou insere registro; retorna id.
        extra_cols não-nulos entram tanto no WHERE da busca quanto no INSERT,
        garantindo vínculo correto (ex: sgpIdGdp ao criar subgrupo dentro de um grupo).
        """
        if not valor or str(valor).strip() in ('', 'NULL', 'NONE', 'NAN'):
            return None
        valor = str(valor).strip()

        # WHERE: nome + extra_cols cujo valor não seja None
        where_parts = [f"{nome_col} = ?"]
        where_vals  = [valor]
        if extra_cols:
            for col, val in extra_cols.items():
                if val is not None:
                    where_parts.append(f"{col} = ?")
                    where_vals.append(val)
        where_sql = " AND ".join(where_parts)

        cursor.execute(f"SELECT {id_col} FROM {tabela} WHERE {where_sql}", where_vals)
        row = cursor.fetchone()
        if row:
            return row[0]

        # INSERT
        if extra_cols:
            cols  = f"{nome_col}, " + ", ".join(extra_cols.keys())
            vals  = (valor,) + tuple(extra_cols.values())
            marks = ", ".join(["?"] * len(vals))
            cursor.execute(f"INSERT INTO {tabela} ({cols}) VALUES ({marks})", vals)
        else:
            cursor.execute(f"INSERT INTO {tabela} ({nome_col}) VALUES (?)", (valor,))

        cursor.execute(f"SELECT MAX({id_col}) FROM {tabela} WHERE {where_sql}", where_vals)
        return cursor.fetchone()[0]

    def _get_emp_id(self, cursor):
        cursor.execute("SELECT TOP 1 cofId FROM config")
        row = cursor.fetchone()
        return row[0] if row else 1

    def _lookup_unidade(self, cursor, pro_un):
        """Busca unidade na tabela produtoUn pelo campo unpUn (case-insensitive).
        Retorna dict {"unpId": int, "unpUn": str} ou None se não encontrada."""
        if not pro_un or str(pro_un).strip().upper() in ('', 'NULL', 'NONE', 'NAN'):
            return None
        un = str(pro_un).strip().upper()
        try:
            cursor.execute(
                "SELECT TOP 1 unpId, unpUn FROM produtoUn WHERE UPPER(unpUn) = ?",
                (un,)
            )
            row = cursor.fetchone()
            if row:
                return {"unpId": row[0], "unpUn": row[1]}
        except Exception:
            pass
        return None

    def _get_or_create_unidade(self, cursor, pro_un):
        """Busca a unidade em produtoUn (case-insensitive). Se NAO existir,
        cadastra automaticamente e retorna o registro recem-criado.
        Retorna dict {"unpId": int, "unpUn": str, "criada": bool} ou None
        quando a unidade do arquivo esta vazia/invalida."""
        if not pro_un or str(pro_un).strip().upper() in ('', 'NULL', 'NONE', 'NAN'):
            return None
        un = str(pro_un).strip().upper()[:10]   # unpUn = varchar(10)

        # 1) tenta localizar a unidade existente
        cursor.execute(
            "SELECT TOP 1 unpId, unpUn FROM produtoUn WHERE UPPER(unpUn) = ?",
            (un,)
        )
        row = cursor.fetchone()
        if row:
            return {"unpId": row[0], "unpUn": row[1], "criada": False}

        # 2) nao existe -> cadastra (unpDescricao e unpDesativar sao NOT NULL)
        cursor.execute(
            "INSERT INTO produtoUn (unpUn, unpDescricao, unpDesativar, DataInclusao) "
            "VALUES (?, ?, 0, GETDATE())",
            (un, un[:50])
        )
        cursor.execute(
            "SELECT TOP 1 unpId, unpUn FROM produtoUn WHERE UPPER(unpUn) = ? "
            "ORDER BY unpId DESC",
            (un,)
        )
        row = cursor.fetchone()
        if row:
            return {"unpId": row[0], "unpUn": row[1], "criada": True}
        return None

    def _lookup_cli_id(self, cursor, cpf_cnpj):
        """Busca cliId pelo CPF/CNPJ na tabela cliente. Cacheia por execução: na
        migração/financeiro muitos lançamentos repetem o mesmo cliente (e a tabela
        cliente não muda durante o INSERT do financeiro), então evita 1 SELECT por
        linha em bancos com dezenas de milhares de lançamentos."""
        if not cpf_cnpj:
            return None
        cpf = str(cpf_cnpj).strip()
        if not cpf:
            return None
        cache = getattr(self, "_lookup_cache", None)
        if cache is None:
            cache = self._lookup_cache = {}
        chave = ("__cli_id__", cpf)
        if chave in cache:
            return cache[chave]
        cursor.execute("SELECT TOP 1 cliId FROM cliente WHERE cliCpfCgc = ?", (cpf,))
        row = cursor.fetchone()
        rid = row[0] if row else None
        cache[chave] = rid
        return rid
