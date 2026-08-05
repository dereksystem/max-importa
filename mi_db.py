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


# ─────────────────────────────────────────────────────────────────────────────
# DRY-RUN de Produtos/Clientes — cursor que LÊ de verdade e IGNORA escritas.
#
# Por que interceptar no cursor em vez de guardar cada execute(): a lógica de
# INSERT de produtos/clientes tem dezenas de comandos entrelaçados (IF NOT EXISTS
# ... INSERT, SCOPE_IDENTITY, IDENTITY_INSERT, produto_empresa, codBarras).
# Espalhar `if dry_run` por tudo isso seria invasivo e fácil de esquecer um ponto —
# e um ponto esquecido GRAVA no banco durante uma "simulação".
#
# Aqui a regra é única e central: comando de escrita não chega ao servidor. E como
# a numeração (SCOPE_IDENTITY) não existiria sem o INSERT, o cursor devolve um id
# fictício — senão o worker abortaria a linha com "SCOPE_IDENTITY retornou NULL" e
# a simulação reportaria erros que não existem.
# ─────────────────────────────────────────────────────────────────────────────
_RE_ESCRITA = re.compile(
    r"\b(insert\s+into|update\s+\S+\s+set|delete\s+from|merge\s+into|dbcc|"
    r"set\s+identity_insert|truncate\s+table|create\s+table|alter\s+table|"
    r"drop\s+table)\b", re.IGNORECASE)


class _CursorSimulado:
    """Encaminha SELECT para o cursor real; descarta qualquer comando de escrita,
    contabilizando o que TERIA sido gravado."""

    def __init__(self, real):
        self._real = real
        self._fake = None            # None = a última execução foi leitura real
        self._fake_id = 900000000    # faixa fictícia, longe de ids reais
        self.escritas = {}           # {operação: quantidade}

    @staticmethod
    def _rotulo(sql_norm):
        m = _RE_ESCRITA.search(sql_norm)
        op = (m.group(1) if m else "escrita").lower()
        op = re.sub(r"\s+", " ", op)
        if op.startswith("insert"):
            alvo = re.search(r"insert\s+into\s+\[?(\w+)", sql_norm, re.IGNORECASE)
            return f"INSERT {alvo.group(1)}" if alvo else "INSERT"
        if op.startswith("update"):
            alvo = re.search(r"update\s+\[?(\w+)", sql_norm, re.IGNORECASE)
            return f"UPDATE {alvo.group(1)}" if alvo else "UPDATE"
        if op.startswith("delete"):
            alvo = re.search(r"delete\s+from\s+\[?(\w+)", sql_norm, re.IGNORECASE)
            return f"DELETE {alvo.group(1)}" if alvo else "DELETE"
        return op.upper()

    @staticmethod
    def _pede_identity(sql_norm):
        b = sql_norm.lower()
        return "scope_identity" in b or "@@identity" in b

    def execute(self, sql, *params):
        s = " ".join(str(sql).split())
        if _RE_ESCRITA.search(s):
            rot = self._rotulo(s)
            self.escritas[rot] = self.escritas.get(rot, 0) + 1
            # O INSERT de produtos vem junto do SELECT SCOPE_IDENTITY() no MESMO
            # comando. Descartar tudo faria o fetchone() devolver None e o worker
            # abortaria a linha com "SCOPE_IDENTITY retornou NULL" — reportando um
            # erro que só existe por causa da simulação. Devolve o id fictício.
            if self._pede_identity(s):
                self._fake_id += 1
                self._fake = [(self._fake_id,)]
            else:
                self._fake = []                 # nada a devolver
            return self
        if self._pede_identity(s):
            self._fake_id += 1                  # id que o INSERT teria gerado
            self._fake = [(self._fake_id,)]
            return self
        self._fake = None
        self._real.execute(sql, *params)
        return self

    def executemany(self, sql, seq):
        s = " ".join(str(sql).split())
        if _RE_ESCRITA.search(s):
            rot = self._rotulo(s)
            self.escritas[rot] = self.escritas.get(rot, 0) + len(list(seq))
            self._fake = []
            return self
        self._fake = None
        self._real.executemany(sql, seq)
        return self

    def fetchone(self):
        if self._fake is not None:
            return self._fake[0] if self._fake else None
        return self._real.fetchone()

    def fetchall(self):
        if self._fake is not None:
            return list(self._fake)
        return self._real.fetchall()

    def close(self):
        try:
            self._real.close()
        except Exception:
            pass

    def __getattr__(self, nome):
        return getattr(self._real, nome)      # description, nextset, rowcount...


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

    # ── UPDATE: célula vazia = "não mexer" ────────────────────────────────
    def _celula_preenchida(self, row, campo) -> bool:
        """True se a célula do arquivo tem conteúdo de verdade.

        Serve ao UPDATE, onde célula VAZIA significa "não mexer neste campo" —
        nunca "grave NULL por cima". Olha o valor CRU, e não o que os _get_*
        devolvem, porque eles convertem vazio para algo gravável: _get_float
        devolve 0.0 para os campos de FLOAT_NOT_NULL (correto no INSERT, onde a
        coluna não aceita NULL; destrutivo no UPDATE, onde zeraria preço/custo)."""
        col = self.mapping.get(campo)
        if not col:
            return False
        val = row.get(col)
        if val is None:
            return False
        # NaN do pandas vira a string 'nan' — capturado junto com os demais vazios
        return str(val).strip().upper() not in ('', 'NULL', 'NONE', 'NAN')

    def _montar_set_update(self, row, mapa):
        """Monta (lista de "col = ?", lista de valores) para um UPDATE, incluindo
        SOMENTE os campos mapeados E preenchidos nesta linha.

        `mapa` é {coluna_db: (funcao_de_leitura, campo_do_mapeamento)}.

        Este é o padrão que cliTipo e cliDatCad já seguiam individualmente ("só
        entra no SET quando há valor"); aqui ele vale para todos os campos."""
        sets, vals = [], []
        for col_db, (fn, campo) in mapa.items():
            if not self._celula_preenchida(row, campo):
                continue
            sets.append(f"{col_db} = ?")
            vals.append(fn(row, campo))
        return sets, vals

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

    # ── Cursor consciente do dry-run ──────────────────────────────────────────
    def _cursor(self):
        """Cursor para gravação. Em dry-run devolve o cursor SIMULADO, que lê de
        verdade e descarta escritas — garantindo que a simulação não toque no banco.
        Os cursores simulados ficam em self._cursores_sim para o resumo final."""
        cur = self.conn.cursor()
        if not getattr(self, "_dry_run", False):
            return cur
        sim = _CursorSimulado(cur)
        if not hasattr(self, "_cursores_sim"):
            self._cursores_sim = []
        self._cursores_sim.append(sim)
        return sim

    def _resumo_simulacao(self):
        """Linhas com o que TERIA sido gravado no banco. [] fora do dry-run."""
        cursores = getattr(self, "_cursores_sim", None)
        if not cursores:
            return []
        total = {}
        for c in cursores:
            for op, n in c.escritas.items():
                total[op] = total.get(op, 0) + n
        if not total:
            return []
        det = " · ".join(f"{op}: {n}" for op, n in sorted(total.items()))
        return [f"🔎 Comandos que SERIAM executados no banco — {det}"]

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

    def _linhas_afetadas(self, cursor):
        """Linhas afetadas pelo último comando, ou None quando não dá para confiar.

        `None` significa "não sei" e o chamador NÃO deve concluir que o registro
        sumiu. Dois casos:
          - **dry-run**: o `_CursorSimulado` descarta a escrita, então o `rowcount`
            que sobra é o do último SELECT real — leitura enganosa;
          - driver/cursor que não expõe `rowcount` (devolve −1 ou nem tem o atributo).
        """
        if getattr(self, "_dry_run", False):
            return None
        n = getattr(cursor, "rowcount", -1)
        try:
            n = int(n)
        except Exception:
            return None
        return None if n < 0 else n

    def _registrar_nao_atualizado(self, row, idx, motivo):
        """Guarda uma linha que NÃO foi atualizada, com o motivo.

        Vai para o mesmo arquivo de erros que o resto da importação, porque o efeito
        para quem importou é o mesmo: aquela linha não entrou. Sem isso, um arquivo com
        IDs errados ou documentos repetidos terminava com "tudo certo" no resumo."""
        lista = getattr(self, "_nao_atualizados", None)
        if lista is None:
            lista = self._nao_atualizados = []
        try:
            linha = {c: row.get(col, "") for c, col in (self.mapping or {}).items()}
        except Exception:
            linha = {}
        linha["_linha"]  = idx + 2
        linha["_motivo"] = motivo
        lista.append(linha)

    def _resolver_empresas(self, cursor):
        """Devolve `(todas, marcadas)` para a gravação multi-loja.

        - **todas** — um `empId` por `cofId` da `config`. É onde nascem as linhas de
          `produto_empresa`/`cliente_empresa`: uma por empresa, sempre.
        - **marcadas** — onde o registro deve APARECER (vai para o `empresaFiltro` no
          INSERT, e delimita o `WHERE empId IN (…)` no UPDATE). Vem de
          `self.empresas_alvo`, preenchido pela tela ou pelo wizard da migração.

        Em banco de **uma loja** as duas listas têm o mesmo e único `empId`, então todo
        o caminho a seguir se comporta exatamente como antes do multi-loja. Sem
        `config` (banco atípico) cai no fallback histórico do `_get_emp_id`."""
        import mi_multiloja

        todas = getattr(self, "empresas_todas", None)
        if not todas:
            todas = [e["cofId"] for e in mi_multiloja.listar_empresas(cursor)]
            if not todas:
                todas = [self._get_emp_id(cursor)]
            self.empresas_todas = todas

        alvo = getattr(self, "empresas_alvo", None)
        # Sem seleção (banco de uma loja, ou chamador que não passou nada): tudo.
        return todas, list(alvo) if alvo else list(todas)

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
