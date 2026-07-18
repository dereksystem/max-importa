"""mi_migracao — lógica da migração banco→banco (mixin MigracaoMixin).

Extraído de max_importa.py na refatoração do monólito. Contém a LÓGICA da migração
MaxData→MaxData: leitura dinâmica da origem, SQLs resilientes a schema, cópia
cross-database (permissões/códigos de barras), migração de clientes "banco zero"
(desabilita/reabilita FKs), produtos/financeiro (via importador), reconciliação,
relatório/JSON, auditoria no destino e backup.

JanelaMigracao herda este mixin. Os métodos usam a instância (self) por duck typing:
self._log / self.after / self.progress / self._set_progresso / self._get_importador /
self._pergunta_thread / self.base_conn_str / self._ROTULOS / self._ORDEM / self._opcoes
etc. — tudo provido pela janela. O que constrói widgets (__init__, _build, wizard
_dialogo_opcoes, _iniciar, _pergunta_thread, _get_importador, _fechar) FICA na janela.
"""
import os
import re
import json
import uuid
from datetime import datetime
from decimal import Decimal

import pyodbc
import pandas as pd
from tkinter import messagebox

from mi_config import APP_VERSION, _get_log_dir


class MigracaoMixin:
    def _df_origem(self, orig_conn, sql):
        cur = orig_conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        data = [['' if v is None else str(v) for v in r] for r in rows]
        return pd.DataFrame(data, columns=cols)

    # ── SELECTs dinâmicos (resilientes a schema diferente) ──────────────────
    def _cols(self, conn, tabela):
        """Retorna o conjunto (minúsculo) de colunas existentes na tabela."""
        try:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sys.columns WHERE object_id = OBJECT_ID(?)", (tabela,))
            return {r[0].lower() for r in cur.fetchall()}
        except Exception:
            return set()

    @staticmethod
    def _c(cols, alias, col):
        """'alias.col AS col' se a coluna existir; senão 'NULL AS col'."""
        return f"{alias}.{col} AS {col}" if col.lower() in cols else f"NULL AS {col}"

    # colunas de auditoria/sistema que não devem ser copiadas (triggers/defaults)
    _COLS_AUDIT = {"datainclusao", "datultalteracao",
                   "datultalteracaonaoatualizar", "iduuid"}

    def _colunas_copiaveis(self, conn, tabela):
        """Colunas da tabela que podem ser copiadas: exclui identity e as colunas
        de auditoria/sistema (mantém a ORDEM original)."""
        try:
            cur = conn.cursor()
            cur.execute("SELECT name, is_identity FROM sys.columns "
                        "WHERE object_id = OBJECT_ID(?) ORDER BY column_id", (tabela,))
            out = []
            for nome, ident in cur.fetchall():
                if ident:
                    continue
                if nome.lower() in self._COLS_AUDIT:
                    continue
                out.append(nome)
            return out
        except Exception:
            return []

    def _colunas_completas(self, conn, tabela):
        """TODAS as colunas inseríveis da tabela (na ordem), excluindo apenas as
        computed e rowversion/timestamp (não aceitam INSERT). INCLUI a identity —
        o chamador usa SET IDENTITY_INSERT para preservar o id. Usado na cópia
        COMPLETA de cliente/cliente_empresa (todos os campos)."""
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT c.name FROM sys.columns c "
                "JOIN sys.types ty ON ty.user_type_id = c.user_type_id "
                "WHERE c.object_id = OBJECT_ID(?) AND c.is_computed = 0 "
                "AND ty.name NOT IN ('timestamp', 'rowversion') "
                "ORDER BY c.column_id", (tabela,))
            return [r[0] for r in cur.fetchall()]
        except Exception:
            return []

    def _copiar_ref_faltante(self, orig_conn, dest_conn, tabela, cod_col, codigos):
        """Copia da ORIGEM para o DESTINO os registros de uma tabela de referência
        (proNCM/proCEST) cujo código está em `codigos` mas NÃO existe no destino.
        O id (identity) é gerado pelo destino; assim o lookup por código no import
        de produtos passa a encontrar o registro. Retorna a quantidade copiada."""
        if not codigos:
            return 0
        try:
            cur_d = dest_conn.cursor()
            cur_d.execute(f"SELECT {cod_col} FROM {tabela}")
            existentes = set(str(r[0]).strip() for r in cur_d.fetchall() if r[0] is not None)
            faltantes = [c for c in codigos if c not in existentes]
            if not faltantes:
                return 0
            # colunas comuns (origem ∩ destino), preservando a ordem da origem
            dest_cols = self._cols(dest_conn, tabela)
            cols = [c for c in self._colunas_copiaveis(orig_conn, tabela)
                    if c.lower() in dest_cols]
            if cod_col not in cols:
                cols.append(cod_col)
            collist = ", ".join(f"[{c}]" for c in cols)
            marks = ", ".join("?" for _ in cols)

            cur_o = orig_conn.cursor()
            copiados = 0
            ja = set()
            dest_conn.autocommit = False
            # busca em lotes (evita IN gigante)
            faltantes_lote = list(faltantes)
            for i in range(0, len(faltantes_lote), 500):
                bloco = faltantes_lote[i:i + 500]
                ph = ",".join("?" for _ in bloco)
                cur_o.execute(f"SELECT {collist} FROM {tabela} WHERE {cod_col} IN ({ph})", bloco)
                idx_cod = cols.index(cod_col)
                for row in cur_o.fetchall():
                    codigo = str(row[idx_cod]).strip()
                    if codigo in ja or codigo in existentes:
                        continue
                    ja.add(codigo)
                    try:
                        cur_d.execute(f"INSERT INTO {tabela} ({collist}) VALUES ({marks})", tuple(row))
                        copiados += 1
                    except Exception as e:
                        self._log(f"⚠️ {tabela}: não copiou código {codigo}: {str(e)[:100]}")
            dest_conn.commit()
            return copiados
        except Exception as e:
            self._log(f"⚠️ Falha ao copiar referência {tabela}: {str(e)[:150]}")
            try:
                dest_conn.rollback()
            except Exception:
                pass
            return 0

    def _lookup_sub(self, conn, base_alias, fk_col, base_cols,
                    ref_table, ref_id, ref_col, as_name):
        """Subquery isolada para um lookup; vira NULL se faltar coluna/tabela."""
        ref_cols = self._cols(conn, ref_table)
        if (fk_col.lower() in base_cols and ref_id.lower() in ref_cols
                and ref_col.lower() in ref_cols):
            return (f"(SELECT TOP 1 _r.{ref_col} FROM {ref_table} _r "
                    f"WHERE _r.{ref_id} = {base_alias}.{fk_col}) AS {as_name}")
        return f"NULL AS {as_name}"

    def _sql_produtos(self, conn, src_emp):
        p  = self._cols(conn, "produto")
        pe = self._cols(conn, "produto_empresa")
        cols = ["p.proId AS proId"]
        for c in ("proDescricao", "proAplicacao", "proBalanca", "proMedVenda",
                  "proMultiplo", "proPeso", "proQtdComEntrada", "proUn", "proTipo"):
            cols.append(self._c(p, "p", c))
        for c in ("proAtacado", "proCodCSOSN", "proCodCst2", "proCodigo", "proCusto",
                  "proDesativaProd", "proEstoqueAtual", "proEstoqueMin",
                  "proLocalizador", "proPrateleira", "proVenda"):
            cols.append(self._c(pe, "pe", c))
        cols.append(self._lookup_sub(conn, "p", "proClasseId", p, "produtoClasse", "pclId", "pclDescricao", "pclDescricao"))
        cols.append(self._lookup_sub(conn, "p", "proCestId",   p, "proCEST",      "cesId", "cesCodigo",    "cesCodigo"))
        cols.append(self._lookup_sub(conn, "p", "proFab",      p, "fabricante",   "fabId", "fabNome",      "fabNome"))
        cols.append(self._lookup_sub(conn, "p", "proGrupo",    p, "grupoProd",    "gdpId", "gdpNome",      "gdpNome"))
        cols.append(self._lookup_sub(conn, "p", "proSubGrupo", p, "subGrupoProd", "sgpId", "sgpNome",      "sgpNome"))
        cols.append(self._lookup_sub(conn, "p", "proNcmId",    p, "proNCM",       "ncmId", "ncmCodigoNCM", "ncmCodigoNCM"))
        cdb = self._cols(conn, "codBarras")
        if "cdbcodigo" in cdb and "cdbidprod" in cdb:
            cols.append("(SELECT TOP 1 cb.cdbCodigo FROM codBarras cb WHERE cb.cdbIdProd = p.proId) AS cdbCodigo")
        else:
            cols.append("NULL AS cdbCodigo")
        join = (f"LEFT JOIN produto_empresa pe ON pe.proId = p.proId AND pe.empId = {src_emp}"
                if pe else "")
        return f"SELECT {', '.join(cols)} FROM produto p {join} ORDER BY p.proId"

    def _sql_clientes(self, conn, src_emp, todos=False):
        c  = self._cols(conn, "cliente")
        ce = self._cols(conn, "cliente_empresa")
        cols = ["c.cliId AS cliId"]
        for col in ("cliCpfCgc", "cliNome", "cliFantasia", "cliRgInsc", "cliFatEnd",
                    "cliFatEndNumero", "cliFatBairro", "cliFatCidade", "cliFatCidCodIBGE",
                    "cliFatUf", "cliFatCep", "cliEmail", "cliFone", "cliDesativa",
                    "cliTipoCad", "cliTipo"):
            cols.append(self._c(c, "c", col))
        # DataInclusao: cliente_empresa.cliDatCad -> cliente.cliDatCad -> NULL
        if "clidatcad" in ce:
            cols.append("ce.cliDatCad AS DataInclusao")
        elif "clidatcad" in c:
            cols.append("c.cliDatCad AS DataInclusao")
        else:
            cols.append("NULL AS DataInclusao")
        join  = (f"LEFT JOIN cliente_empresa ce ON ce.cliId = c.cliId AND ce.empId = {src_emp}"
                 if ce else "")
        # todos=True (migração zero) traz TODOS os cliId; senão só >= 11
        where = "" if todos else ("WHERE c.cliId >= 11" if "cliid" in c else "")
        return f"SELECT {', '.join(cols)} FROM cliente c {join} {where} ORDER BY c.cliId"

    def _sql_financeiro(self, conn):
        vp  = self._cols(conn, "vendaPgto")
        cli = self._cols(conn, "cliente")
        cols = []
        if "pgtclienteid" in vp and "clicpfcgc" in cli and "cliid" in cli:
            cols.append("(SELECT TOP 1 _c.cliCpfCgc FROM cliente _c "
                        "WHERE _c.cliId = vp.pgtClienteId) AS cliCpfCgc")
        else:
            cols.append("NULL AS cliCpfCgc")
        for col in ("pgtCliNome", "pgtTipoVista", "pgtTipoPrazo", "pgtValor", "pgtData",
                    "pgtVecmto", "pgtTipoConta", "pgtPago", "pgtNumDoc", "pgtObs",
                    "pgtDataQuitou", "pgtNossoNumero"):
            cols.append(self._c(vp, "vp", col))
        order = "ORDER BY vp.pgtId" if "pgtid" in vp else ""
        return f"SELECT {', '.join(cols)} FROM vendaPgto vp {order}"

    def _migrar(self, origem, destino, entidades):
        self._totais = {}          # {entidade: {"inseridos","pulados","erros"}}
        self._estoque_obs = None   # motivo de divergência esperada no estoque
        self._acerto_info = None   # info do acerto de estoque gerado (p/ resumo final)
        self._origem = origem      # nome do banco de origem (p/ cross-database)
        try:
            orig_conn = pyodbc.connect(self.base_conn_str + f"DATABASE={origem};", timeout=15)
            dest_conn = pyodbc.connect(self.base_conn_str + f"DATABASE={destino};", timeout=15)
        except Exception as e:
            self._log(f"❌ Falha ao conectar aos bancos: {str(e)[:200]}")
            self._salvar_relatorio_migracao()
            self.after(0, lambda: self.btn_migrar.configure(state="normal"))
            self._op_finalizada()
            return

        try:
            cur = orig_conn.cursor()
            cur.execute("SELECT TOP 1 cofId FROM config")
            row = cur.fetchone()
            src_emp = row[0] if row else 1
        except Exception:
            src_emp = 1

        self._log(f"════════ MIGRAÇÃO  {origem} → {destino}  (v{APP_VERSION}) ════════")
        self._log(f"empId da origem = {src_emp}")

        # BACKUP do destino (se solicitado no wizard) — se falhar, aborta
        if (getattr(self, "_opcoes", None) or {}).get("backup"):
            self._log(f"── Fazendo BACKUP (COPY_ONLY) do destino '{destino}'...")
            bak = self._backup_destino(destino)
            if bak:
                self._log(f"── ✅ BACKUP do destino salvo em: {bak}")
            else:
                self._log("❌ BACKUP do destino FALHOU — migração ABORTADA por segurança.")
                self._salvar_relatorio_migracao()
                try:
                    orig_conn.close(); dest_conn.close()
                except Exception:
                    pass
                self._pergunta_thread(
                    "Backup falhou — migração abortada",
                    "Não foi possível fazer o BACKUP do banco de destino, então a migração "
                    "foi ABORTADA por segurança.\n\nVerifique permissões/espaço no servidor "
                    "e tente novamente (ou desmarque o backup, por sua conta e risco).",
                    tipo="info")
                self.after(0, lambda: self.btn_migrar.configure(state="normal"))
                self._op_finalizada()
                return

        # A migração de Clientes APAGA UsuarioPermissao; então, se Clientes for
        # migrado, Permissões entra automaticamente (para repor idêntico à origem).
        ents = set(entidades)
        if "clientes" in ents and "permissoes" not in ents:
            ents.add("permissoes")
            self._log("ℹ️ Permissões incluídas automaticamente (a limpeza de Clientes "
                      "apaga UsuarioPermissao; será reposta idêntica à origem).")
        plano = [e for e in self._ORDEM if e in ents]
        total_ent = len(plano)
        for i, entidade in enumerate(plano):
            # Ponto SEGURO de cancelamento: entre entidades (a entidade anterior
            # já concluiu inteira, com as FKs reabilitadas e o banco consistente).
            if self._cancelado:
                restantes = [self._ROTULOS[e] for e in plano[i:]]
                self._log("⏹️ Migração CANCELADA pelo usuário — entidades NÃO "
                          "migradas: " + ", ".join(restantes) + ".")
                # Só as entidades já processadas entram na conferência.
                plano = plano[:i]
                break
            try:
                self._migrar_entidade(entidade, orig_conn, dest_conn, src_emp)
            except Exception as e:
                self._log(f"❌ Erro ao migrar {self._ROTULOS[entidade]}: {str(e)[:300]}")
            self._set_progresso(i + 1, total_ent, contexto=self._ROTULOS.get(entidade, ""))

        self._imp_atual = None

        # ── Conferência ORIGEM × DESTINO (reconciliação) ──────────────────
        rec_txt = ""
        try:
            rec = self._reconciliar(orig_conn, dest_conn, set(plano), src_emp)
            if rec:
                self._log("──────── CONFERÊNCIA ORIGEM × DESTINO ────────")
                for l in rec:
                    self._log("   " + l)
                rec_txt = "\n\nCONFERÊNCIA ORIGEM × DESTINO:\n\n" + "\n".join(rec)
        except Exception as e:
            self._log(f"⚠️ Falha na conferência origem × destino: {str(e)[:150]}")

        # ── Auditoria no destino (o que esta migração fez) ────────────────
        self._registrar_auditoria(dest_conn, origem, destino)

        try:
            orig_conn.close(); dest_conn.close()
        except Exception:
            pass

        resumo = self._resumo_totais()
        self._log("──────── TOTAIS MIGRADOS ────────")
        for l in resumo.split("\n"):
            self._log("   " + l)
        acerto = getattr(self, "_acerto_info", None)
        if acerto:
            self._log("   " + acerto)
        cancelada = getattr(self, "_cancelado", False)
        self._log("⏹️ Migração CANCELADA — o que já havia sido migrado foi mantido."
                  if cancelada else "🏁 Migração concluída.")
        self._salvar_relatorio_migracao()
        self.after(0, lambda: self.btn_migrar.configure(state="normal"))
        self._op_finalizada()
        ac_txt = ("\n\n" + acerto) if acerto else ""
        titulo = "Migração cancelada" if cancelada else "Migração concluída"
        abertura = (f"Migração de {origem} para {destino} CANCELADA pelo usuário.\n"
                    "As entidades já migradas foram mantidas (banco consistente); "
                    "as demais não foram alteradas.\n\n"
                    if cancelada else
                    f"Migração de {origem} para {destino} finalizada.\n\n")
        self.after(0, lambda t=titulo, ab=abertura, r=resumo, rc=rec_txt, ac=ac_txt:
                   messagebox.showinfo(
            t,
            f"{ab}"
            f"TOTAIS MIGRADOS:\n\n{r}{rc}{ac}\n\n"
            "Confira os relatórios (RELATORIO_*.txt) na pasta de logs.", parent=self))

    def _resumo_totais(self):
        """Monta o resumo consolidado com os totais de cada entidade migrada."""
        linhas = []
        for chave in self._ORDEM:
            r = self._totais.get(chave)
            if not r:
                continue
            rot, lbl2 = self._TOTAL_FMT[chave]
            parte = f"{rot}:  {r.get('inseridos', 0)} inseridos"
            if lbl2 is not None:
                parte += f"  |  {r.get('pulados', 0)} {lbl2}"
            parte += f"  |  {r.get('erros', 0)} erros"
            linhas.append(parte)
        return "\n".join(linhas) if linhas else "(nada migrado)"

    def _salvar_relatorio_migracao(self):
        """Salva SEMPRE um relatório da migração (mesmo quando há erro), com o
        log completo e os totais consolidados."""
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M")
            log_dir = _get_log_dir()
            os.makedirs(log_dir, exist_ok=True)
            path = os.path.join(log_dir, f"RELATORIO_MIGRACAO_{ts}.txt")
            self._log(f"📄 Relatório da migração salvo: {path}")
            with open(path, "w", encoding="utf-8") as f:
                f.write("=== RELATÓRIO — MIGRAÇÃO ENTRE BANCOS MAXDATA ===\n")
                f.write(f"Versao: {APP_VERSION}\n\n")
                for l in self.log_lines:
                    f.write(l + "\n")
            # Também em JSON (estruturado) — totais por entidade, p/ auditoria/planilha
            jpath = os.path.join(log_dir, f"RESULTADO_MIGRACAO_{ts}.json")
            dados = {
                "app_version": APP_VERSION,
                "operacao":   "MIGRACAO",
                "gerado_em":  datetime.now().isoformat(timespec="seconds"),
                "origem":     getattr(self, "_origem", None),
                "cancelada":  bool(getattr(self, "_cancelado", False)),
                "totais":     getattr(self, "_totais", {}) or {},
            }
            with open(jpath, "w", encoding="utf-8") as jf:
                json.dump(dados, jf, ensure_ascii=False, indent=2, default=str)
            self._log(f"🧾 Resultado da migração (JSON) salvo: {os.path.basename(jpath)}")
        except Exception as e:
            self._log(f"⚠️ Não foi possível salvar o relatório da migração: {str(e)[:150]}")

    def _registrar_auditoria(self, dest_conn, origem, destino):
        """Registra na tabela de AUDITORIA do destino (uma linha por entidade
        migrada) o que a migração fez: quando, versão, origem/destino, usuário,
        contagens e se foi cancelada. Cria a tabela se não existir. As linhas de
        uma mesma execução compartilham um 'audSessao'. Best-effort: nunca
        interrompe a migração."""
        totais = getattr(self, "_totais", None) or {}
        if not totais:
            return
        prev = None
        try:
            prev = dest_conn.autocommit
            dest_conn.autocommit = True   # DDL + inserts fora de transação
            cur = dest_conn.cursor()
            cur.execute("""
                IF OBJECT_ID('dbo.MaxImporta_Auditoria','U') IS NULL
                CREATE TABLE dbo.MaxImporta_Auditoria (
                    audId        INT IDENTITY(1,1) PRIMARY KEY,
                    audDataHora  DATETIME     NOT NULL DEFAULT GETDATE(),
                    audVersao    VARCHAR(20)  NULL,
                    audOperacao  VARCHAR(20)  NOT NULL,
                    audOrigem    VARCHAR(128) NULL,
                    audDestino   VARCHAR(128) NULL,
                    audUsuario   VARCHAR(128) NULL,
                    audEntidade  VARCHAR(30)  NOT NULL,
                    audInseridos INT          NOT NULL DEFAULT 0,
                    audPulados   INT          NOT NULL DEFAULT 0,
                    audErros     INT          NOT NULL DEFAULT 0,
                    audCancelada BIT          NOT NULL DEFAULT 0,
                    audSessao    VARCHAR(40)  NULL
                )
            """)
            sessao    = uuid.uuid4().hex
            cancelada = 1 if getattr(self, "_cancelado", False) else 0
            n = 0
            for chave in self._ORDEM:
                r = totais.get(chave)
                if not r:
                    continue
                cur.execute("""
                    INSERT INTO dbo.MaxImporta_Auditoria
                        (audVersao, audOperacao, audOrigem, audDestino, audUsuario,
                         audEntidade, audInseridos, audPulados, audErros,
                         audCancelada, audSessao)
                    VALUES (?, 'MIGRACAO', ?, ?, SUSER_SNAME(), ?, ?, ?, ?, ?, ?)
                """, (APP_VERSION, origem, destino, self._ROTULOS.get(chave, chave),
                      r.get("inseridos", 0), r.get("pulados", 0), r.get("erros", 0),
                      cancelada, sessao))
                n += 1
            dest_conn.autocommit = prev
            self._log(f"🧾 Auditoria registrada no destino "
                      f"({n} linha(s) em MaxImporta_Auditoria).")
        except Exception as e:
            try:
                if prev is not None:
                    dest_conn.autocommit = prev
            except Exception:
                pass
            self._log(f"⚠️ Não foi possível registrar a auditoria no destino: {str(e)[:150]}")

    # Colunas de "conteúdo" cujo PREENCHIMENTO (não-NULL) deve ser coerente entre
    # origem e destino. Pega corrupção de valor que COUNT/SUM não enxergam — ex.:
    # uma coluna preenchida na origem que chega vazia no destino (foi assim que o
    # bug de datas ficou meses invisível: a reconciliação por contagem/soma passava).
    _COLS_CONTEUDO = {
        "clientes": [("cliente", c) for c in (
            "cliNome", "cliCpfCgc", "cliFatEnd", "cliFatCidade", "cliFatUf",
            "cliDatCad", "cliCobEnd", "cliLimitCred", "cliCelular", "cliEmail")],
        "produtos": [("produto", "proDescricao"),
                     ("produto_empresa", "proCodigo"),
                     ("produto_empresa", "proVenda")],
        "financeiro": [("vendaPgto", c) for c in (
            "pgtData", "pgtVecmto", "pgtDataQuitou", "pgtValor",
            "pgtClienteId", "pgtCliNome", "pgtNumDoc", "pgtTipoConta")],
    }

    # ─────────────────────────────────────────────────────────────────────────
    # PRÉ-FLIGHT — compatibilidade de schema origem × destino, ANTES de migrar.
    # Tudo SOMENTE LEITURA: nenhuma escrita, nenhuma transação. A ideia é
    # transformar surpresa de runtime (truncamento 22001, coluna inexistente,
    # collation divergente) em um checklist que o usuário lê antes de decidir.
    # ─────────────────────────────────────────────────────────────────────────
    _TABELAS_ENT = {
        "clientes":   ["cliente", "cliente_empresa"],
        "permissoes": ["UsuarioPermissao"],
        "produtos":   ["produto", "produto_empresa"],
        "codbarras":  ["codBarras"],
        "financeiro": ["vendaPgto"],
    }
    # Tipos de texto: max_length vem em BYTES; nos unicode (n*) são 2 bytes/char.
    _TIPOS_TEXTO = {"varchar", "nvarchar", "char", "nchar"}
    _TIPOS_UNICODE = {"nvarchar", "nchar"}

    def _schema_tabela(self, conn, tabela):
        """Metadados das colunas: {nome_lower: {nome, tipo, tam, prec, escala,
        collation, nulavel}}. tam = tamanho em CARACTERES (-1 = MAX). {} se a
        tabela não existir."""
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT c.name, ty.name, c.max_length, c.precision, c.scale, "
                "       c.collation_name, c.is_nullable "
                "FROM sys.columns c "
                "JOIN sys.types ty ON ty.user_type_id = c.user_type_id "
                "WHERE c.object_id = OBJECT_ID(?) ORDER BY c.column_id", (tabela,))
            out = {}
            for nome, tipo, mlen, prec, esc, coll, nul in cur.fetchall():
                tam = mlen
                if mlen not in (None, -1) and tipo in self._TIPOS_UNICODE:
                    tam = mlen // 2
                out[nome.lower()] = {"nome": nome, "tipo": tipo, "tam": tam,
                                     "prec": prec, "escala": esc,
                                     "collation": coll, "nulavel": nul}
            return out
        except Exception:
            return {}

    def _contar_excedentes(self, conn, tabela, coluna, limite):
        """Quantas linhas da ORIGEM realmente estourariam o tamanho do destino.
        Transforma 'pode truncar' em 'N linhas VÃO truncar'. None se não der."""
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM [{tabela}] WHERE LEN([{coluna}]) > ?",
                        (limite,))
            return cur.fetchone()[0]
        except Exception:
            return None

    def _preflight(self, orig_conn, dest_conn, entidades):
        """Compara schema origem × destino para as entidades escolhidas.
        Retorna (linhas, resumo) — resumo = {"bloqueantes": n, "avisos": n, "ok": n}.
        NÃO escreve nada."""
        linhas, bloq, avisos, oks = [], 0, 0, 0
        tabelas = []
        for ent in entidades:
            for t in self._TABELAS_ENT.get(ent, []):
                if t not in tabelas:
                    tabelas.append(t)

        for tabela in tabelas:
            so = self._schema_tabela(orig_conn, tabela)
            sd = self._schema_tabela(dest_conn, tabela)
            if not so:
                avisos += 1
                linhas.append(f"⚠️ {tabela}: não existe na ORIGEM — nada a migrar.")
                continue
            if not sd:
                bloq += 1
                linhas.append(f"🔴 {tabela}: NÃO EXISTE no DESTINO — a migração desta "
                              f"entidade vai falhar.")
                continue

            try:
                n_orig = orig_conn.cursor().execute(
                    f"SELECT COUNT(*) FROM [{tabela}]").fetchone()[0]
                n_dest = dest_conn.cursor().execute(
                    f"SELECT COUNT(*) FROM [{tabela}]").fetchone()[0]
            except Exception:
                n_orig = n_dest = "?"

            probs = []
            faltantes = [d["nome"] for k, d in so.items() if k not in sd]
            if faltantes:
                avisos += 1
                amostra = ", ".join(faltantes[:8])
                mais = f" (+{len(faltantes) - 8})" if len(faltantes) > 8 else ""
                probs.append(f"   ⚠️ {len(faltantes)} coluna(s) só na origem — o dado "
                             f"NÃO será copiado: {amostra}{mais}")

            for k, o in so.items():
                d = sd.get(k)
                if not d:
                    continue
                # tipo base diferente
                if o["tipo"] != d["tipo"]:
                    avisos += 1
                    probs.append(f"   ⚠️ {o['nome']}: tipo origem {o['tipo']} × destino "
                                 f"{d['tipo']} — risco de conversão")
                    continue
                # texto menor no destino → mede o estrago REAL na origem
                if (o["tipo"] in self._TIPOS_TEXTO and o["tam"] not in (None, -1)
                        and d["tam"] not in (None, -1) and d["tam"] < o["tam"]):
                    n = self._contar_excedentes(orig_conn, tabela, o["nome"], d["tam"])
                    if n:
                        bloq += 1
                        probs.append(f"   🔴 {o['nome']}: destino {d['tipo']}({d['tam']}) "
                                     f"< origem ({o['tam']}) e **{n} linha(s) excedem** "
                                     f"— truncamento/erro 22001 garantido")
                    else:
                        avisos += 1
                        probs.append(f"   ⚠️ {o['nome']}: destino {d['tipo']}({d['tam']}) "
                                     f"< origem ({o['tam']}), mas nenhuma linha excede hoje")
                # numérico com menos precisão/escala
                elif (o["tipo"] in ("decimal", "numeric")
                      and (d["prec"], d["escala"]) < (o["prec"], o["escala"])):
                    avisos += 1
                    probs.append(f"   ⚠️ {o['nome']}: destino {d['tipo']}({d['prec']},"
                                 f"{d['escala']}) menor que origem ({o['prec']},{o['escala']})"
                                 f" — risco de arredondamento")
                # collation divergente (afeta comparação/ordenação e acentuação)
                elif o["collation"] and d["collation"] and o["collation"] != d["collation"]:
                    avisos += 1
                    probs.append(f"   ⚠️ {o['nome']}: collation origem {o['collation']} × "
                                 f"destino {d['collation']}")
                # destino NOT NULL onde a origem permite NULL → INSERT pode falhar
                elif o["nulavel"] and not d["nulavel"]:
                    avisos += 1
                    probs.append(f"   ⚠️ {o['nome']}: destino é NOT NULL mas a origem "
                                 f"aceita NULL — linhas com vazio falham")

            cab = f"{tabela}: origem {n_orig} linha(s) → destino {n_dest} linha(s)"
            if probs:
                linhas.append(f"⚠️ {cab}")
                linhas.extend(probs)
            else:
                oks += 1
                linhas.append(f"✅ {cab} — schema compatível")

        # FKs já desabilitadas no destino ANTES de começar (migração anterior travada?)
        try:
            fks_off = self._fks_desabilitadas(dest_conn)
            if fks_off:
                avisos += 1
                linhas.append(f"⚠️ destino tem {len(fks_off)} FK(s) já DESABILITADA(s) "
                              f"antes de migrar — resquício de execução interrompida.")
        except Exception:
            pass

        # config/empId no destino (o import usa 'SELECT TOP 1 cofId FROM config')
        try:
            if dest_conn.cursor().execute(
                    "SELECT COUNT(*) FROM config").fetchone()[0] == 0:
                bloq += 1
                linhas.append("🔴 destino sem linha em 'config' — empId não resolve.")
        except Exception:
            avisos += 1
            linhas.append("⚠️ não foi possível ler 'config' no destino.")

        resumo = {"bloqueantes": bloq, "avisos": avisos, "ok": oks}
        return linhas, resumo

    def _validar_conteudo(self, orig_conn, dest_conn, entidades):
        """Valida CONTEÚDO (não só a contagem): compara a taxa de preenchimento
        (não-NULL) de colunas-chave entre origem e destino. Normalizado (proporção),
        então funciona mesmo quando o destino tem menos linhas (pulados/dedup/pré-
        existentes). Sinaliza quando uma coluna preenchida na origem chega quase
        vazia no destino — sinal de perda de dados silenciosa."""
        def ratio(conn, tabela, col):
            try:
                cur = conn.cursor()
                cur.execute(f"SELECT COUNT(*), COUNT([{col}]) FROM [{tabela}]")
                tot, fill = cur.fetchone()
                return (fill / float(tot)) if tot else None
            except Exception:
                return None

        linhas, flags, checadas = [], 0, 0
        for ent in entidades:
            for tabela, col in self._COLS_CONTEUDO.get(ent, []):
                if (col.lower() not in self._cols(orig_conn, tabela)
                        or col.lower() not in self._cols(dest_conn, tabela)):
                    continue
                o = ratio(orig_conn, tabela, col)
                d = ratio(dest_conn, tabela, col)
                if o is None or d is None:
                    continue
                checadas += 1
                op, dp = f"{o*100:.0f}%", f"{d*100:.0f}%"
                if o >= 0.30 and d <= 0.02:
                    flags += 1
                    linhas.append(f"🔴 {tabela}.{col}: origem {op} preenchido, destino {dp} — "
                                  f"coluna praticamente VAZIA no destino (possível perda de dados!)")
                elif o - d > 0.15:
                    flags += 1
                    linhas.append(f"⚠️ {tabela}.{col}: preenchimento origem {op} → destino {dp} — "
                                  f"caiu mais que o esperado")
        if checadas:
            if flags == 0:
                linhas.append(f"✅ conteúdo: {checadas} coluna(s) com preenchimento coerente "
                              f"origem × destino.")
            else:
                linhas.insert(0, f"⚠️ conteúdo: {flags} de {checadas} coluna(s) com "
                                 f"preenchimento divergente:")
        return linhas

    # Relações-chave (filha.fk → pai.pk) verificadas contra ÓRFÃOS após a migração.
    # Uma FK "não-confiável" (is_not_trusted) não valida os dados existentes e o
    # otimizador a ignora — órfãos passam despercebidos. Este check acha os órfãos
    # DIRETAMENTE (independe do estado da FK), fechando o risco silencioso.
    _REL_FK = {
        "clientes":   [("cliente_empresa", "cliId", "cliente", "cliId"),
                       ("UsuarioPermissao", "cliId", "cliente", "cliId")],
        "produtos":   [("produto_empresa", "proId", "produto", "proId")],
        "codbarras":  [("codBarras", "cdbIdProd", "produto", "proId")],
        "financeiro": [("vendaPgto", "pgtClienteId", "cliente", "cliId")],
    }

    def _validar_integridade_fk(self, dest_conn, entidades):
        """Integridade referencial no destino: (1) FKs que ficaram DESABILITADAS
        (sem enforcement — a migração não conseguiu reabilitar) e (2) linhas ÓRFÃS
        (referência apontando para um pai inexistente). Complementa a FK não-confiável,
        que o SQL Server não valida sozinho."""
        linhas = []
        desab = self._fks_desabilitadas(dest_conn)
        if desab:
            amostra = ", ".join(f"{fk} em {tbl}" for tbl, fk in desab[:6])
            linhas.append(f"🔴 {len(desab)} FK(s) DESABILITADA(s) no destino — sem enforcement: "
                          + amostra + (" ..." if len(desab) > 6 else ""))

        def cnt(sql):
            try:
                cur = dest_conn.cursor(); cur.execute(sql)
                r = cur.fetchone()
                return r[0] if r else 0
            except Exception:
                return None

        checadas = 0
        for ent in entidades:
            for filha, fk, pai, pk in self._REL_FK.get(ent, []):
                if (fk.lower() not in self._cols(dest_conn, filha)
                        or pk.lower() not in self._cols(dest_conn, pai)):
                    continue
                n = cnt(f"SELECT COUNT(*) FROM [{filha}] f WHERE f.[{fk}] IS NOT NULL "
                        f"AND NOT EXISTS (SELECT 1 FROM [{pai}] p WHERE p.[{pk}] = f.[{fk}])")
                if n is None:
                    continue
                checadas += 1
                if n > 0:
                    linhas.append(f"🔴 {filha}.{fk} → {pai}.{pk}: {n} linha(s) ÓRFÃ(s) "
                                  f"(aponta(m) para {pai} inexistente)")
        if desab == [] and not any("ÓRFÃ" in l for l in linhas) and checadas:
            linhas.append(f"✅ integridade referencial: nenhuma FK desabilitada e "
                          f"nenhum órfão em {checadas} relação(ões)-chave.")
        return linhas

    def _reconciliar(self, orig_conn, dest_conn, entidades, src_emp):
        """Confere ORIGEM × DESTINO após a migração: contagens por tabela e
        somas (estoque, valores do financeiro). Retorna as linhas do comparativo
        para log, relatório e tela. Divergências conhecidas (ex.: estoque zerado
        por opção) são marcadas como 'esperada'."""
        def q(conn, sql, params=()):
            try:
                cur = conn.cursor()
                cur.execute(sql, params)
                r = cur.fetchone()
                return r[0] if r and r[0] is not None else 0
            except Exception:
                return None

        def num(v):
            try:
                return float(v)
            except Exception:
                return None

        linhas = []

        def comp(nome, o, d, obs="", esperado=False):
            if o is None or d is None:
                linhas.append(f"{nome}: origem={'?' if o is None else o} | "
                              f"destino={'?' if d is None else d} | ⚠️ não conferido")
                return
            if isinstance(o, float) or isinstance(d, float):
                iguais = abs((o or 0.0) - (d or 0.0)) < 0.005
                o_s, d_s = f"{o:.2f}", f"{d:.2f}"
            else:
                iguais = o == d
                o_s, d_s = str(o), str(d)
            if iguais:
                linhas.append(f"{nome}: origem={o_s} | destino={d_s} | ✅ confere")
            elif esperado and obs:
                linhas.append(f"{nome}: origem={o_s} | destino={d_s} | "
                              f"ℹ️ diferença esperada — {obs}")
            else:
                suf = f" — {obs}" if obs else ""
                linhas.append(f"{nome}: origem={o_s} | destino={d_s} | ⚠️ divergente{suf}")

        dest_emp = q(dest_conn, "SELECT TOP 1 cofId FROM config") or 1

        if "clientes" in entidades:
            comp("👥 cliente",
                 q(orig_conn, "SELECT COUNT(*) FROM cliente"),
                 q(dest_conn, "SELECT COUNT(*) FROM cliente"),
                 "cópia deveria ser idêntica — verifique os erros no log")
            comp("👥 cliente_empresa (clientes vinculados)",
                 q(orig_conn, "SELECT COUNT(DISTINCT cliId) FROM cliente_empresa"),
                 q(dest_conn, "SELECT COUNT(DISTINCT cliId) FROM cliente_empresa"))

        if "permissoes" in entidades:
            comp("🔐 UsuarioPermissao",
                 q(orig_conn, "SELECT COUNT(*) FROM UsuarioPermissao"),
                 q(dest_conn, "SELECT COUNT(*) FROM UsuarioPermissao"),
                 "permissões de usuários inexistentes no destino são ignoradas")

        if "produtos" in entidades:
            comp("📦 produto",
                 q(orig_conn, "SELECT COUNT(*) FROM produto"),
                 q(dest_conn, "SELECT COUNT(*) FROM produto"),
                 "produtos já existentes no destino são pulados")
            o_est = num(q(orig_conn, "SELECT SUM(ISNULL(proEstoqueAtual,0)) "
                                     "FROM produto_empresa WHERE empId = ?", (src_emp,)))
            d_est = num(q(dest_conn, "SELECT SUM(ISNULL(proEstoqueAtual,0)) "
                                     "FROM produto_empresa WHERE empId = ?", (dest_emp,)))
            obs_est = getattr(self, "_estoque_obs", None)
            comp("📦 estoque (soma proEstoqueAtual)", o_est, d_est,
                 obs_est or "verifique o log", esperado=bool(obs_est))
            # produtos sem NCM no destino (risco fiscal)
            sem_ncm = q(dest_conn, "SELECT COUNT(*) FROM produto WHERE proNcmId IS NULL")
            if sem_ncm is not None:
                if sem_ncm == 0:
                    linhas.append("📦 produtos sem NCM (proNcmId nulo): 0 | ✅ todos com NCM")
                else:
                    linhas.append(f"📦 produtos sem NCM (proNcmId nulo): {sem_ncm} | "
                                  "⚠️ verifique — NCM é obrigatório para emissão fiscal")

        if "codbarras" in entidades:
            comp("🏷️ codBarras",
                 q(orig_conn, "SELECT COUNT(*) FROM codBarras"),
                 q(dest_conn, "SELECT COUNT(*) FROM codBarras"),
                 "códigos sem produto no destino são ignorados")

        if "financeiro" in entidades:
            comp("💰 vendaPgto",
                 q(orig_conn, "SELECT COUNT(*) FROM vendaPgto"),
                 q(dest_conn, "SELECT COUNT(*) FROM vendaPgto"),
                 "não encontrados são pulados; destino pode ter lançamentos pré-existentes")
            comp("💰 valor (soma pgtValor)",
                 num(q(orig_conn, "SELECT SUM(ISNULL(pgtValor,0)) FROM vendaPgto")),
                 num(q(dest_conn, "SELECT SUM(ISNULL(pgtValor,0)) FROM vendaPgto")),
                 "segue os lançamentos pulados/pré-existentes")

        # Validação de CONTEÚDO por coluna (pega corrupção que contagem/soma não veem)
        conteudo = self._validar_conteudo(orig_conn, dest_conn, entidades)
        if conteudo:
            linhas.append("── VALIDAÇÃO DE CONTEÚDO (preenchimento não-NULL por coluna) ──")
            linhas.extend(conteudo)

        # Integridade referencial (FKs desabilitadas + linhas órfãs)
        integridade = self._validar_integridade_fk(dest_conn, entidades)
        if integridade:
            linhas.append("── INTEGRIDADE REFERENCIAL (FKs e órfãos) ──")
            linhas.extend(integridade)

        return linhas

    def _migrar_entidade(self, entidade, orig_conn, dest_conn, src_emp):
        rot = self._ROTULOS[entidade]

        # Permissões: cópia direta de tabela (não usa importador)
        if entidade == "permissoes":
            self._imp_atual = None
            self._totais[entidade] = self._migrar_permissoes(orig_conn, dest_conn)
            return

        # Clientes: migração 'banco zero' (limpa destino + cópia idêntica)
        if entidade == "clientes":
            self._imp_atual = None
            self._totais[entidade] = self._migrar_clientes(orig_conn, dest_conn, src_emp)
            return

        # Códigos de barras: wipe + cópia idêntica (igual às permissões)
        if entidade == "codbarras":
            self._imp_atual = None
            self._totais[entidade] = self._migrar_codbarras(orig_conn, dest_conn)
            return

        if entidade == "produtos":
            sql = self._sql_produtos(orig_conn, src_emp)
        else:
            sql = self._sql_financeiro(orig_conn)
        self._imp_atual = None
        self._log(f"── {rot}: lendo da origem...")
        df = self._df_origem(orig_conn, sql)
        self._log(f"── {rot}: {len(df)} registro(s) na origem.")
        if len(df) == 0:
            self._log(f"── {rot}: nada a migrar.")
            self._totais[entidade] = {"inseridos": 0, "pulados": 0, "erros": 0}
            return

        # Produtos: pergunta se migra o estoque atual (e trata negativos)
        if entidade == "produtos":
            self._tratar_estoque_migracao(df)
            # Copia NCM/CEST usados pelos produtos que faltam no destino, para
            # evitar produto migrado com proNcmId/proCestId NULL (risco fiscal).
            if "ncmCodigoNCM" in df.columns:
                cods = set(str(v).strip() for v in df["ncmCodigoNCM"]
                           if str(v).strip() and str(v).strip().upper() not in ("NULL", "NONE", "NAN"))
                n = self._copiar_ref_faltante(orig_conn, dest_conn, "proNCM", "ncmCodigoNCM", cods)
                if n:
                    self._log(f"── Produtos: {n} NCM(s) copiado(s) da origem para o destino (faltavam).")
            if "cesCodigo" in df.columns:
                cods = set(str(v).strip() for v in df["cesCodigo"]
                           if str(v).strip() and str(v).strip().upper() not in ("NULL", "NONE", "NAN"))
                n = self._copiar_ref_faltante(orig_conn, dest_conn, "proCEST", "cesCodigo", cods)
                if n:
                    self._log(f"── Produtos: {n} CEST(s) copiado(s) da origem para o destino (faltavam).")

        imp = self._get_importador(entidade)
        imp.conn    = dest_conn
        imp.df      = df
        imp.mapping = {c: c for c in df.columns}
        imp._ultimo_resultado = None
        if entidade == "financeiro":
            imp.nao_encontrados = []
            imp._dedup_financeiro = True   # idempotência: não duplica se rodar 2×
        self._imp_atual = imp     # a partir daqui o log alimenta o relatorio da entidade

        # Só produtos e financeiro chegam aqui via importador headless. Clientes
        # (e permissões/codbarras) retornam antes, por cópia direta (ver acima).
        if entidade == "produtos":
            imp._inserir_produtos()
        else:
            imp._inserir_financeiro()
        self._imp_atual = None

        # captura os totais que o importador registrou
        self._totais[entidade] = getattr(imp, "_ultimo_resultado", None) or \
            {"inseridos": 0, "pulados": 0, "erros": 0}

        # Produtos: pós-migração — gera acerto de estoque pendente se houver
        # estoque > 0 no destino e avisa o usuário para rodar no Manager
        if entidade == "produtos":
            self._acerto_estoque_pos_migracao(dest_conn)

    def _tratar_estoque_migracao(self, df):
        """Aplica as opções de estoque escolhidas no wizard (self._opcoes), sem
        interação: 'zerar' -> proEstoqueAtual = 0 para todos; 'migrar' -> copia da
        origem e, conforme prd_negativos, zera ou mantém os estoques negativos."""
        if "proEstoqueAtual" not in df.columns:
            return
        op = getattr(self, "_opcoes", None) or {}

        def _num(v):
            s = str(v).strip() if v is not None else ""
            if s.upper() in ("", "NULL", "NONE", "NAN"):
                return 0.0
            try:
                return float(s.replace(",", "."))
            except Exception:
                return 0.0

        if op.get("prd_estoque") == "zerar":
            df["proEstoqueAtual"] = "0"
            self._estoque_obs = "estoque zerado por opção do usuário (não migrado)"
            self._log("── Produtos: estoque NÃO migrado — proEstoqueAtual = 0 para todos.")
            return

        vals = df["proEstoqueAtual"].apply(_num)
        mask_neg = vals < 0
        n_neg = int(mask_neg.sum())
        if n_neg:
            if op.get("prd_negativos") == "zerar":
                df.loc[mask_neg, "proEstoqueAtual"] = "0"
                self._estoque_obs = f"{n_neg} estoque(s) negativo(s) zerado(s) por opção"
                self._log(f"── Produtos: {n_neg} produto(s) com estoque negativo iniciados com ZERO.")
            else:
                self._log(f"── Produtos: {n_neg} produto(s) com estoque negativo mantidos como na origem.")
        self._log("── Produtos: estoque atual será migrado da origem.")

    def _acerto_estoque_pos_migracao(self, dest_conn):
        """Após migrar produtos: se houver estoque > 0 no destino, gera o
        ACERTO DE ESTOQUE PENDENTE (status 'A') e avisa o usuário para rodar
        o acerto no Manager."""
        try:
            cur = dest_conn.cursor()
            cur.execute("SELECT TOP 1 cofId FROM config")
            r = cur.fetchone()
            emp_id = r[0] if r else 1

            cur.execute("SELECT COUNT(*) FROM produto_empresa "
                        "WHERE proEstoqueAtual > 0 AND empId = ?", (emp_id,))
            qtd = cur.fetchone()[0]
            if not qtd:
                self._log("── Produtos: sem estoque > 0 no destino — acerto de estoque não é necessário.")
                return

            cur.execute("SELECT TOP 1 cliId FROM cliente WHERE cliUsuLoginId = 2")
            r = cur.fetchone()
            if not r or r[0] is None:
                self._log("⚠️ Acerto de estoque: usuário admin (cliUsuLoginId=2) não "
                          "encontrado no destino — acerto NÃO gerado.")
                return
            admin_id = r[0]

            # cabeçalho — SCOPE_IDENTITY no mesmo batch (triggers AFTER)
            cur.execute("""
                SET NOCOUNT ON;
                INSERT INTO produtoAcertoEstoque
                    (empId, paeVedId, paeVedIdSaida, paeStatus, paeUsuId,
                     paeDataOcorrencia, paeObs)
                VALUES (?, NULL, NULL, 'A', ?, GETDATE(), ?);
                SELECT SCOPE_IDENTITY();
            """, (emp_id, admin_id, "MAXDATA SISTEMA - MIGRACAO"))
            fetched = cur.fetchone()
            if not fetched or fetched[0] is None:
                raise ValueError("SCOPE_IDENTITY() retornou NULL ao criar o acerto.")
            pae_id = int(fetched[0])

            # itens — um por produto com estoque > 0
            cur.execute("""
                INSERT INTO produtoAcertoEstoqueItem
                    (paiPaeId, paiProId, paiProEstoque, paiQtdInf, paiLote, paiLoteEstoque)
                SELECT ?, pe.proId, 0, pe.proEstoqueAtual, 'X', 0
                FROM produto_empresa pe
                WHERE pe.proEstoqueAtual > 0 AND pe.empId = ?
            """, (pae_id, emp_id))
            dest_conn.commit()

            self._log(f"── Produtos: ✅ acerto de estoque PENDENTE gerado — "
                      f"paeId={pae_id} | {qtd} item(ns) | empId={emp_id}")
            # não interrompe o fluxo — a informação vai no resumo final
            self._acerto_info = (f"⚠️ Acerto de estoque PENDENTE gerado (nº {pae_id}, "
                                 f"{qtd} itens). RODE o acerto no Manager para efetivar "
                                 "o estoque dos produtos migrados.")
        except Exception as e:
            try:
                dest_conn.rollback()
            except Exception:
                pass
            self._log(f"❌ Erro ao gerar acerto de estoque pós-migração: {str(e)[:200]}")

    def _fks_referenciando(self, conn, tabelas):
        """Retorna [(schema.tabela_filha, constraint)] das FKs que referenciam as
        tabelas informadas (para desabilitar antes de limpar a tabela pai)."""
        try:
            cur = conn.cursor()
            placeholders = ",".join("OBJECT_ID(?)" for _ in tabelas)
            cur.execute(
                "SELECT s.name, t.name, fk.name "
                "FROM sys.foreign_keys fk "
                "JOIN sys.tables t ON t.object_id = fk.parent_object_id "
                "JOIN sys.schemas s ON s.schema_id = t.schema_id "
                f"WHERE fk.referenced_object_id IN ({placeholders})", tabelas)
            return [(f"[{r[0]}].[{r[1]}]", f"[{r[2]}]") for r in cur.fetchall()]
        except Exception as e:
            self._log(f"⚠️ Não foi possível listar FKs: {str(e)[:120]}")
            return []

    def _fks_da_tabela(self, conn, tabelas):
        """Retorna [(schema.tabela, constraint)] das FKs DEFINIDAS NAS tabelas (de
        saída — ex.: cliente.cliVendPref → cliente, cliente.cliTabPreco → tabPreco).
        Precisam ser desabilitadas na cópia COMPLETA, senão copiar o valor dessas
        colunas-FK viola a restrição se a linha referenciada não existir no destino."""
        try:
            cur = conn.cursor()
            placeholders = ",".join("OBJECT_ID(?)" for _ in tabelas)
            cur.execute(
                "SELECT s.name, t.name, fk.name "
                "FROM sys.foreign_keys fk "
                "JOIN sys.tables t ON t.object_id = fk.parent_object_id "
                "JOIN sys.schemas s ON s.schema_id = t.schema_id "
                f"WHERE fk.parent_object_id IN ({placeholders})", tabelas)
            return [(f"[{r[0]}].[{r[1]}]", f"[{r[2]}]") for r in cur.fetchall()]
        except Exception as e:
            self._log(f"⚠️ Não foi possível listar FKs de saída: {str(e)[:120]}")
            return []

    def _fks_desabilitadas(self, conn):
        """FKs DESABILITADAS (is_disabled=1) — sinal de migração interrompida
        (FKs que ficaram sem enforcement). Não considera as apenas 'não confiáveis'
        (is_not_trusted), que são normais em bancos MaxData."""
        try:
            cur = conn.cursor()
            cur.execute("SELECT s.name, t.name, fk.name FROM sys.foreign_keys fk "
                        "JOIN sys.tables t ON t.object_id = fk.parent_object_id "
                        "JOIN sys.schemas s ON s.schema_id = t.schema_id "
                        "WHERE fk.is_disabled = 1")
            return [(f"[{r[0]}].[{r[1]}]", f"[{r[2]}]") for r in cur.fetchall()]
        except Exception:
            return []

    def _reabilitar_fks(self, conn, fks):
        """Reabilita as FKs (WITH CHECK; se não validar, sem validação). Retorna
        quantas foram reabilitadas."""
        cur = conn.cursor()
        prev = conn.autocommit
        conn.autocommit = True
        ok = 0
        for tbl, fk in fks:
            try:
                cur.execute(f"ALTER TABLE {tbl} WITH CHECK CHECK CONSTRAINT {fk}")
                ok += 1
            except Exception:
                try:
                    cur.execute(f"ALTER TABLE {tbl} CHECK CONSTRAINT {fk}")
                    ok += 1
                except Exception:
                    pass
        conn.autocommit = prev
        return ok

    def _backup_destino(self, destino):
        """Faz BACKUP COPY_ONLY do banco de destino no caminho padrão da instância.
        Retorna o caminho do .bak ou None em caso de falha."""
        try:
            conn = pyodbc.connect(self.base_conn_str, timeout=60)
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("SELECT CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS varchar(500))")
            row = cur.fetchone()
            path = row[0] if row else None
            if not path:
                cur.execute("DECLARE @p varchar(500); EXEC master.dbo.xp_instance_regread "
                            "N'HKEY_LOCAL_MACHINE', "
                            "N'Software\\Microsoft\\MSSQLServer\\MSSQLServer', "
                            "N'BackupDirectory', @p OUTPUT; SELECT @p")
                r2 = cur.fetchone()
                path = r2[0] if r2 else None
            if not path:
                self._log("⚠️ BACKUP: caminho de backup padrão não encontrado.")
                conn.close()
                return None
            ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe = re.sub(r"[^A-Za-z0-9_]", "_", destino)
            bak  = f"{path.rstrip(chr(92))}\\{safe}_pre_migracao_{ts}.bak"
            cur.execute(f"BACKUP DATABASE [{destino}] TO DISK = N'{bak}' "
                        f"WITH COPY_ONLY, INIT, NAME = N'MaxImporta pre-migracao {destino}'")
            while cur.nextset():
                pass
            conn.close()
            return bak
        except Exception as e:
            self._log(f"⚠️ BACKUP do destino falhou: {str(e)[:180]}")
            return None

    def _migrar_clientes(self, orig_conn, dest_conn, src_emp):
        """Migração de CLIENTES tipo 'banco zero': avisa o usuário, DESABILITA as
        FKs (as que referenciam E as definidas em cliente/cliente_empresa), LIMPA
        UsuarioPermissao, cliente_empresa e cliente do destino, reseta os identities,
        copia cliente e cliente_empresa COMPLETOS — TODAS as colunas (exceto computed),
        mantendo TODOS os cliId — e REABILITA as FKs. A cliente_empresa é copiada da
        origem para a empresa do destino (empId remapeado); cliente sem vínculo na
        origem recebe uma linha mínima. Também trata nomes duplicados (cliNome+cliCpfCgc)."""
        rot = self._ROTULOS["clientes"]
        op = getattr(self, "_opcoes", None) or {}

        # 1) Ciência do usuário — confirmada no wizard antes de iniciar
        if not op.get("cli_ciente"):
            self._log(f"── {rot}: ciência da limpeza não confirmada. Nada foi alterado.")
            return {"inseridos": 0, "pulados": 0, "erros": 0}

        # 2) Colunas a copiar = TODAS (origem ∩ destino), exceto computed. INCLUI a
        #    identity (usamos SET IDENTITY_INSERT p/ manter os ids). Cópia COMPLETA.
        dcols_cli = self._cols(dest_conn, "cliente")
        dcols_ce  = self._cols(dest_conn, "cliente_empresa")
        cli_cols = [c for c in self._colunas_completas(orig_conn, "cliente")
                    if c.lower() in dcols_cli]
        ce_cols  = [c for c in self._colunas_completas(orig_conn, "cliente_empresa")
                    if c.lower() in dcols_ce]
        if not cli_cols:
            self._log(f"❌ {rot}: não foi possível ler as colunas de cliente.")
            return {"inseridos": 0, "pulados": 0, "erros": 1}
        lc_cli   = [c.lower() for c in cli_cols]
        i_cliid  = lc_cli.index("cliid")
        i_desat  = lc_cli.index("clidesativa") if "clidesativa" in lc_cli else None
        i_datcad = lc_cli.index("clidatcad")   if "clidatcad"   in lc_cli else None

        # 3) Duplicados: mesmo cliNome + cliCpfCgc (leitura leve, só 3 colunas)
        self._log(f"── {rot}: lendo da origem (todas as colunas)...")
        oc = orig_conn.cursor()
        oc.execute("SELECT cliId, cliNome, cliCpfCgc FROM cliente")
        base = oc.fetchall()
        total = len(base)
        self._log(f"── {rot}: {total} cliente(s) na origem.")
        if total == 0:
            return {"inseridos": 0, "pulados": 0, "erros": 0}
        desativar_ids = set()
        grupos = {}
        for cid_r, nome_r, cpf_r in base:
            nome = (str(nome_r).strip().upper() if nome_r else "")
            cpf  = re.sub(r"\D", "", str(cpf_r) if cpf_r else "")
            cid  = self._to_int(cid_r)
            if cid is None or (not nome and not cpf):
                continue
            grupos.setdefault((nome, cpf), []).append(cid)
        dups = {k: v for k, v in grupos.items() if len(v) > 1}
        if dups:
            n_grupos = len(dups)
            n_extra  = sum(len(v) - 1 for v in dups.values())
            if op.get("cli_duplicados") == "desativar":
                for v in dups.values():
                    mais_novo = max(v)
                    for cid in v:
                        if cid != mais_novo:
                            desativar_ids.add(cid)
                self._log(f"── {rot}: {n_grupos} nome(s)+CPF repetido(s) — "
                          f"{len(desativar_ids)} duplicado(s) serão DESATIVADOS (cliDesativa=-1).")
            else:
                self._log(f"── {rot}: {n_grupos} nome(s)+CPF repetido(s) ({n_extra} extras) "
                          f"MANTIDOS como na origem (opção do usuário).")

        # cliente_empresa da origem (para src_emp), COMPLETA, indexada por cliId
        ce_por_cli = {}
        i_ce_emp = i_ce_cli = i_ce_cle = None
        if ce_cols:
            lc_ce    = [c.lower() for c in ce_cols]
            i_ce_cli = lc_ce.index("cliid")
            i_ce_emp = lc_ce.index("empid") if "empid" in lc_ce else None
            i_ce_cle = lc_ce.index("cleid") if "cleid" in lc_ce else None
            oc.execute(f"SELECT {', '.join('['+c+']' for c in ce_cols)} "
                       f"FROM cliente_empresa WHERE empId = ?", src_emp)
            for r in oc.fetchall():
                ce_por_cli[self._to_int(r[i_ce_cli])] = list(r)

        # 4) empId do destino (para cliente_empresa)
        try:
            dc0 = dest_conn.cursor(); dc0.execute("SELECT TOP 1 cofId FROM config")
            rr = dc0.fetchone(); dest_emp = rr[0] if rr else 1
        except Exception:
            dest_emp = 1

        # 5) Desabilita as FKs que REFERENCIAM cliente/cliente_empresa (p/ limpar) E
        #    as DEFINIDAS NELAS (de saída) — necessário porque a cópia completa traz
        #    colunas-FK (cliVendPref, cliTabPreco, cliImpostoId...) que podem apontar
        #    p/ linhas ausentes no destino. Reabilitadas ao final (sem validar se preciso).
        dc = dest_conn.cursor()
        fks = self._fks_referenciando(dest_conn, ["cliente", "cliente_empresa"]) \
            + self._fks_da_tabela(dest_conn, ["cliente", "cliente_empresa"])
        vistos = set(); fks_u = []
        for item in fks:
            if item not in vistos:
                vistos.add(item); fks_u.append(item)
        fks = fks_u
        dest_conn.autocommit = True
        desab = []
        for tbl, fk in fks:
            try:
                dc.execute(f"ALTER TABLE {tbl} NOCHECK CONSTRAINT {fk}")
                desab.append((tbl, fk))
            except Exception as e:
                self._log(f"⚠️ {rot}: não desabilitou FK {fk} de {tbl}: {str(e)[:80]}")
        self._log(f"── {rot}: {len(desab)} FK(s) desabilitada(s) temporariamente.")

        inseridos = erros = desativados = ce_ins = 0
        try:
            # LIMPA em transação (se falhar, nada é apagado)
            self._log(f"── {rot}: limpando 'UsuarioPermissao', 'cliente_empresa' e 'cliente'...")
            dest_conn.autocommit = False
            try:
                dc.execute("DELETE FROM UsuarioPermissao")
                dc.execute("DELETE FROM cliente_empresa")
                dc.execute("DELETE FROM cliente")
                dest_conn.commit()
            except Exception as e:
                dest_conn.rollback()
                self._log(f"❌ {rot}: falha ao limpar o destino: {str(e)[:180]}")
                self._pergunta_thread(
                    "Não foi possível limpar o destino",
                    "Falha ao apagar 'cliente'/'cliente_empresa'/'UsuarioPermissao'.\n\n"
                    f"Detalhe: {str(e)[:220]}\n\n"
                    "Use um banco de destino ZERADO e tente novamente.", tipo="info")
                return {"inseridos": 0, "pulados": 0, "erros": 1}

            # reseta os contadores incrementais (próximo id = 1)
            dest_conn.autocommit = True
            for t in ("cliente", "cliente_empresa", "UsuarioPermissao"):
                try:
                    dc.execute(f"DBCC CHECKIDENT ('{t}', RESEED, 0)")
                except Exception:
                    pass
            self._log(f"── {rot}: contadores (identity) resetados para iniciar do 1.")
            _zero = Decimal('0.00000')

            # 6) INSERT cliente — TODAS as colunas, mantendo cliId (IDENTITY_INSERT).
            #    Streaming da origem (não carrega 440 colunas × N linhas na memória).
            collist_cli = ", ".join(f"[{c}]" for c in cli_cols)
            marks_cli   = ", ".join("?" for _ in cli_cols)
            self._log(f"── {rot}: inserindo {total} cliente(s) (todas as {len(cli_cols)} colunas)...")
            dest_conn.autocommit = False
            dc.execute("SET IDENTITY_INSERT cliente ON")
            oc.execute(f"SELECT {collist_cli} FROM cliente ORDER BY cliId")
            for r in oc:
                cid = self._to_int(r[i_cliid])
                if cid is None:
                    erros += 1
                    continue
                vals = list(r)
                if i_desat is not None and cid in desativar_ids:
                    vals[i_desat] = -1
                    desativados += 1
                try:
                    dc.execute(f"INSERT INTO cliente ({collist_cli}) VALUES ({marks_cli})", vals)
                    inseridos += 1
                    if inseridos % 500 == 0:
                        dest_conn.commit()
                        self._log(f"── {rot}: {inseridos} inseridos...")
                except Exception as e:
                    erros += 1
                    if erros <= 5:
                        self._log(f"❌ {rot}: erro cliId={cid}: {str(e)[:150]}")
            dc.execute("SET IDENTITY_INSERT cliente OFF")
            dest_conn.commit()

            # 7) INSERT cliente_empresa — COMPLETA (origem p/ src_emp), remapeando
            #    empId → dest_emp. Cliente sem vínculo na origem recebe um mínimo.
            if ce_cols:
                collist_ce = ", ".join(f"[{c}]" for c in ce_cols)
                marks_ce   = ", ".join("?" for _ in ce_cols)
                self._log(f"── {rot}: inserindo cliente_empresa (todas as {len(ce_cols)} colunas)...")
                dc.execute("SET IDENTITY_INSERT cliente_empresa ON")
                max_cle = 0
                # 7a) vínculos existentes na origem (cópia completa)
                for cid, ce in ce_por_cli.items():
                    vals = list(ce)
                    if i_ce_emp is not None:
                        vals[i_ce_emp] = dest_emp
                    if i_ce_cle is not None:
                        cle = self._to_int(ce[i_ce_cle])
                        if cle is not None:
                            max_cle = max(max_cle, cle)
                    try:
                        dc.execute(f"INSERT INTO cliente_empresa ({collist_ce}) VALUES ({marks_ce})", vals)
                        ce_ins += 1
                        if ce_ins % 500 == 0:
                            dest_conn.commit()
                    except Exception as e:
                        erros += 1
                        if erros <= 8:
                            self._log(f"❌ {rot}: erro cliente_empresa cliId={cid}: {str(e)[:150]}")
                # 7b) clientes sem vínculo na origem → linha mínima (mantém o vínculo)
                prox_cle = max_cle
                oc2 = orig_conn.cursor()
                oc2.execute("SELECT cliId, cliDatCad FROM cliente")
                for cid_r, datcad in oc2.fetchall():
                    cid = self._to_int(cid_r)
                    if cid is None or cid in ce_por_cli:
                        continue
                    prox_cle += 1
                    minimo = {"cleid": prox_cle, "empid": dest_emp, "cliid": cid,
                              "clidatcad": datcad, "clicalculaicmssubst": 0,
                              "clidescontoautoaplicar": 0, "clidescontoautoaliq": _zero,
                              "climaxdatarateiocredito_aliq_01": _zero,
                              "climaxdatarateiocredito_aliq_02": _zero,
                              "climaxdatarateiocredito_aliq_03": _zero}
                    vals = [minimo.get(c.lower(), None) for c in ce_cols]
                    try:
                        dc.execute(f"INSERT INTO cliente_empresa ({collist_ce}) VALUES ({marks_ce})", vals)
                        ce_ins += 1
                    except Exception as e:
                        erros += 1
                        if erros <= 8:
                            self._log(f"❌ {rot}: erro cliente_empresa (mínimo) cliId={cid}: {str(e)[:150]}")
                dc.execute("SET IDENTITY_INSERT cliente_empresa OFF")
                dest_conn.commit()

            # finaliza: ajusta o seed dos identities para o MAX real
            try:
                dest_conn.autocommit = True
                for t, col in (("cliente", "cliId"), ("cliente_empresa", "cleId")):
                    dc.execute(f"SELECT ISNULL(MAX({col}), 0) FROM {t}")
                    mx = dc.fetchone()[0]
                    dc.execute(f"DBCC CHECKIDENT ('{t}', RESEED, {mx})")
            except Exception as e:
                self._log(f"⚠️ {rot}: pós-ajuste do identity: {str(e)[:120]}")
        finally:
            # REABILITA as FKs (SEMPRE, mesmo se der erro no meio)
            try:
                dest_conn.autocommit = True
            except Exception:
                pass
            reok = 0
            for tbl, fk in desab:
                try:
                    dc.execute(f"ALTER TABLE {tbl} WITH CHECK CHECK CONSTRAINT {fk}")
                    reok += 1
                except Exception:
                    try:
                        dc.execute(f"ALTER TABLE {tbl} CHECK CONSTRAINT {fk}")
                        reok += 1
                        self._log(f"⚠️ {rot}: FK {fk} de {tbl} reabilitada SEM validar (verifique os dados).")
                    except Exception as e2:
                        self._log(f"⚠️ {rot}: FK {fk} de {tbl} NÃO reabilitada: {str(e2)[:80]}")
            self._log(f"── {rot}: {reok}/{len(desab)} FK(s) reabilitada(s).")
            try:
                dest_conn.autocommit = False
            except Exception:
                pass

        self._log(f"── {rot}: ✅ {inseridos} cliente(s) | 🔗 {ce_ins} vínculo(s) empresa "
                  f"| ⛔ {desativados} desativados | ❌ {erros} erros")
        return {"inseridos": inseridos, "pulados": desativados, "erros": erros}

    # helpers de conversão (migração direta, sem importador)
    @staticmethod
    def _to_str(v):
        s = (str(v).strip() if v is not None else "")
        return None if s.upper() in ("", "NULL", "NONE", "NAN") else s

    @staticmethod
    def _to_int(v):
        s = (str(v).strip() if v is not None else "")
        if s.upper() in ("", "NULL", "NONE", "NAN"):
            return None
        try:
            return int(float(s))
        except Exception:
            return None

    @staticmethod
    def _to_dt(v):
        s = (str(v).strip() if v is not None else "")
        if s.upper() in ("", "NULL", "NONE", "NAN"):
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
                    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y"):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                pass
        try:
            return datetime.fromisoformat(s)
        except Exception:
            return None

    def _migrar_permissoes(self, orig_conn, dest_conn):
        """Deixa UsuarioPermissao IDÊNTICA à origem via cross-database INSERT...SELECT
        (uma instrução — origem e destino na mesma instância). LIMPA o destino e copia
        todos os registros da origem cujo usuário (cliId) exista no destino
        (FK uspUsuId -> cliente.cliId). O uspId é gerado pelo destino."""
        rot = self._ROTULOS["permissoes"]
        org = self._origem
        dc  = dest_conn.cursor()
        cur_o = orig_conn.cursor()
        cur_o.execute("SELECT COUNT(*) FROM UsuarioPermissao")
        total = cur_o.fetchone()[0]
        self._log(f"── {rot}: {total} registro(s) na origem — copiando (cross-database)...")

        dest_conn.autocommit = False
        try:
            dc.execute("DELETE FROM UsuarioPermissao")
            dc.execute(f"INSERT INTO UsuarioPermissao (uspUsuId, uspObjeto) "
                       f"SELECT o.uspUsuId, o.uspObjeto FROM [{org}].dbo.UsuarioPermissao o "
                       f"WHERE o.uspUsuId IN (SELECT cliId FROM cliente)")
            dest_conn.commit()
        except Exception as e:
            try:
                dest_conn.rollback()
            except Exception:
                pass
            self._log(f"❌ {rot}: falha na cópia: {str(e)[:180]}")
            return {"inseridos": 0, "pulados": 0, "erros": 1}

        dc.execute("SELECT COUNT(*) FROM UsuarioPermissao")
        inseridos   = dc.fetchone()[0]
        sem_usuario = max(0, total - inseridos)
        if sem_usuario:
            self._log(f"── {rot}: {sem_usuario} ignorada(s) — usuário (cliId) não existe no destino.")
        self._log(f"── {rot}: ✅ {inseridos} inseridos (cross-database) "
                  f"| ⚠️ {sem_usuario} sem usuário | ❌ 0 erros")
        return {"inseridos": inseridos, "pulados": sem_usuario, "erros": 0}

    def _migrar_codbarras(self, orig_conn, dest_conn):
        """Deixa codBarras IDÊNTICA à origem via cross-database INSERT...SELECT.
        LIMPA o destino e copia todo o conteúdo da origem cujo produto (cdbIdProd)
        exista no destino (FK -> produto.proId); cdbProUnId inexistente vira NULL.
        A FK de proLote -> codBarras é desabilitada para permitir o DELETE."""
        rot = self._ROTULOS["codbarras"]
        org = self._origem
        dc  = dest_conn.cursor()
        cur_o = orig_conn.cursor()
        cur_o.execute("SELECT COUNT(*) FROM codBarras")
        total = cur_o.fetchone()[0]
        self._log(f"── {rot}: {total} registro(s) na origem — copiando (cross-database)...")

        # desabilita FKs que referenciam codBarras (ex.: proLote) p/ poder limpar
        fks = self._fks_referenciando(dest_conn, ["codBarras"])
        dest_conn.autocommit = True
        desab = []
        for tbl, fk in fks:
            try:
                dc.execute(f"ALTER TABLE {tbl} NOCHECK CONSTRAINT {fk}")
                desab.append((tbl, fk))
            except Exception:
                pass

        inseridos = erros = 0
        try:
            dest_conn.autocommit = False
            dc.execute("DELETE FROM codBarras")
            dc.execute(f"""
                INSERT INTO codBarras (cdbIdProd, cdbCodigo, cdbCxFechada,
                    cdbCxFechadaQtde, cdbCxFechadaVlrUn, cdbProUnId)
                SELECT o.cdbIdProd, o.cdbCodigo, o.cdbCxFechada, o.cdbCxFechadaQtde,
                       o.cdbCxFechadaVlrUn,
                       CASE WHEN o.cdbProUnId IN (SELECT unpId FROM produtoUn)
                            THEN o.cdbProUnId ELSE NULL END
                FROM [{org}].dbo.codBarras o
                WHERE o.cdbIdProd IN (SELECT proId FROM produto)""")
            dest_conn.commit()
            dc.execute("SELECT COUNT(*) FROM codBarras")
            inseridos = dc.fetchone()[0]
        except Exception as e:
            try:
                dest_conn.rollback()
            except Exception:
                pass
            erros = 1
            self._log(f"❌ {rot}: falha na cópia: {str(e)[:180]}")
        finally:
            # reabilita as FKs (sempre)
            try:
                dest_conn.autocommit = True
            except Exception:
                pass
            for tbl, fk in desab:
                try:
                    dc.execute(f"ALTER TABLE {tbl} WITH CHECK CHECK CONSTRAINT {fk}")
                except Exception:
                    try:
                        dc.execute(f"ALTER TABLE {tbl} CHECK CONSTRAINT {fk}")
                    except Exception:
                        pass
            try:
                dest_conn.autocommit = False
            except Exception:
                pass

        sem_produto = max(0, total - inseridos) if erros == 0 else 0
        if sem_produto:
            self._log(f"── {rot}: {sem_produto} ignorado(s) — produto não existe no destino.")
        self._log(f"── {rot}: ✅ {inseridos} inseridos (cross-database) "
                  f"| ⚠️ {sem_produto} sem produto | ❌ {erros} erros")
        return {"inseridos": inseridos, "pulados": sem_produto, "erros": erros}

