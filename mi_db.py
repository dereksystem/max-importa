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
from datetime import datetime
from decimal import Decimal, InvalidOperation


class MapeamentoDBMixin:
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
        # ISO 8601 primeiro (aceita "2026-03-01" e "2026-03-01 12:34:56[.ffffff]").
        try:
            return datetime.fromisoformat(s.replace("T", " "))
        except Exception:
            pass
        # Formatos BR/US. IMPORTANTE: parse na STRING INTEIRA — NÃO usar s[:len(fmt)]:
        # len("%Y-%m-%d")==8 mas a data tem 10 chars, o que truncava e falhava sempre.
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue
        return None

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
