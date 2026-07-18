"""mi_importadores — lógica de importação por ARQUIVO (mixins por entidade).

Extraído de max_importa.py na refatoração do monólito. Cada mixin reúne a LÓGICA de
inserção/atualização de uma entidade (Produtos, Clientes, Financeiro), que a janela
correspondente herda. Os métodos usam a instância (self) por duck typing: self.conn,
self.df, self.mapping, self._cancelado, self._log, self.after, self._set_progresso,
self.btn_import/btn_acerto e os helpers de MapeamentoDBMixin — tudo provido pela janela.

Fica na janela o que constrói widgets/lê a tela: __init__, _build, _selecionar_arquivo,
_carregar_colunas, _iniciar (validação + dispatch), _log, _salvar_relatorio, _fechar.
"""
import re
import pandas as pd
from tkinter import messagebox

from decimal import Decimal
from mi_report import _pos_importacao
from mi_db import MapeamentoDBMixin


class ProdutosImportMixin:
    # Floats NOT NULL no banco: quando vêm vazios, entram como 0.0 (ver _get_float
    # em MapeamentoDBMixin). Fica aqui para ser herdado pela janela E pelo importador
    # headless da migração.
    FLOAT_NOT_NULL = {
        "proMedVenda", "proMultiplo", "proPeso", "proQtdComEntrada",
        "proAtacado", "proCusto", "proEstoqueAtual", "proEstoqueMin", "proVenda"
    }

    def _inserir_produtos(self):
        cursor   = self.conn.cursor()
        total    = len(self.df)
        sucessos = 0
        erros    = 0
        emp_id   = self._get_emp_id(cursor)
        self._lookup_cache = {}   # cache de lookups (NCM/CEST) por execução

        self._log(f"🔄 Iniciando INSERT — {total} registros | empId={emp_id}")

        nomes_erro = []       # nomes dos produtos que deram erro na importacao
        uns_criadas = set()   # unidades proUn cadastradas automaticamente em produtoUn

        for idx, row in self.df.iterrows():
            if self._cancelado:
                break
            pro_id = None
            try:
                pro_id_raw = self._get_str(row, "proId")
                # proId vazio → segue a numeracao do banco (coluna IDENTITY)
                auto_id = not pro_id_raw
                pro_id  = None if auto_id else int(float(pro_id_raw))

                # Lookups auxiliares
                fab_id      = self._get_or_create(cursor, "fabricante",    "fabId", "fabNome",     self._get_str(row, "fabNome"))
                grupo_id    = self._get_or_create(cursor, "grupoProd",     "gdpId", "gdpNome",      self._get_str(row, "gdpNome"))
                subgrupo_id = self._get_or_create(cursor, "subGrupoProd",  "sgpId", "sgpNome",      self._get_str(row, "sgpNome"),
                                                   extra_cols={"sgpIdGdp": grupo_id})
                classe_id   = self._get_or_create(cursor, "produtoClasse", "pclId", "pclDescricao", self._get_str(row, "pclDescricao"),
                                                   extra_cols={"pclDesativa": 0})
                ncm_id      = self._lookup(cursor, "proNCM",  "ncmId", "ncmCodigoNCM", self._get_str(row, "ncmCodigoNCM"))
                cest_id     = self._lookup(cursor, "proCEST", "cesId", "cesCodigo",    self._get_str(row, "cesCodigo"))

                # ── unidade em produtoUn (cadastra se nao existir) ────────────
                pro_un_str  = self._get_str_max(row, "proUn", 10)
                un_info     = self._get_or_create_unidade(cursor, pro_un_str)
                unp_id      = un_info["unpId"] if un_info else None
                unp_un      = un_info["unpUn"] if un_info else None
                if un_info and un_info.get("criada"):
                    uns_criadas.add(unp_un)

                # ── tabela produto ──
                if auto_id:
                    # proId vazio → deixa o banco gerar o ID (IDENTITY) e captura
                    # o valor gerado via SCOPE_IDENTITY() para vincular os demais
                    # registros (produto_empresa, codBarras).
                    # INSERT + SELECT no MESMO batch (SCOPE_IDENTITY so vale no
                    # mesmo escopo) e SET NOCOUNT ON para as triggers AFTER da
                    # tabela nao atrapalharem o retorno do SELECT.
                    cursor.execute("""
                        SET NOCOUNT ON;
                        INSERT INTO produto (
                            proDescricao, proAplicacao, proBalanca,
                            proMedVenda, proMultiplo, proPeso, proQtdComEntrada,
                            proUn, proTipo,
                            proFab, proGrupo, proSubGrupo,
                            proClasseId, proNcmId, proCestId,
                            proUnComercialId, proUnTrib, proUnTribId
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
                        SELECT SCOPE_IDENTITY();
                    """, (
                        self._get_str_max(row, "proDescricao", 100),
                        self._get_str(row, "proAplicacao"),
                        self._get_int(row, "proBalanca", 0),
                        self._get_float(row, "proMedVenda"),
                        self._get_float(row, "proMultiplo"),
                        self._get_float(row, "proPeso"),
                        self._get_float(row, "proQtdComEntrada"),
                        pro_un_str,
                        self._get_str_max(row, "proTipo", 1),
                        fab_id, grupo_id, subgrupo_id,
                        classe_id, ncm_id, cest_id,
                        unp_id, unp_un, unp_id
                    ))
                    fetched = cursor.fetchone()
                    new_id = fetched[0] if fetched else None
                    if new_id is None:
                        raise ValueError("SCOPE_IDENTITY() retornou NULL — INSERT do produto nao foi executado.")
                    pro_id = int(new_id)
                else:
                    # proId informado no arquivo → insere o ID explicitamente.
                    cursor.execute("SET IDENTITY_INSERT produto ON")
                    cursor.execute("""
                        IF NOT EXISTS (SELECT 1 FROM produto WHERE proId = ?)
                        INSERT INTO produto (
                            proId, proDescricao, proAplicacao, proBalanca,
                            proMedVenda, proMultiplo, proPeso, proQtdComEntrada,
                            proUn, proTipo,
                            proFab, proGrupo, proSubGrupo,
                            proClasseId, proNcmId, proCestId,
                            proUnComercialId, proUnTrib, proUnTribId
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        pro_id,
                        pro_id,
                        self._get_str_max(row, "proDescricao", 100),
                        self._get_str(row, "proAplicacao"),
                        self._get_int(row, "proBalanca", 0),
                        self._get_float(row, "proMedVenda"),
                        self._get_float(row, "proMultiplo"),
                        self._get_float(row, "proPeso"),
                        self._get_float(row, "proQtdComEntrada"),
                        pro_un_str,
                        self._get_str_max(row, "proTipo", 1),
                        fab_id, grupo_id, subgrupo_id,
                        classe_id, ncm_id, cest_id,
                        unp_id, unp_un, unp_id
                    ))
                    cursor.execute("SET IDENTITY_INSERT produto OFF")

                # ── tabela produto_empresa ──
                cursor.execute("""
                    IF NOT EXISTS (SELECT 1 FROM produto_empresa WHERE proId = ? AND empId = ?)
                    INSERT INTO produto_empresa (
                        proId, empId,
                        proAtacado, proCodCSOSN, proCodCst2, proCodigo,
                        proCusto, proDesativaProd, proEstoqueAtual, proEstoqueMin,
                        proLocalizador, proPrateleira, proVenda,
                        proUn,
                        proUnComercialId, proUnTrib, proUnTribId
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    pro_id, emp_id,
                    pro_id, emp_id,
                    self._get_float(row, "proAtacado"),
                    self._get_str_max(row, "proCodCSOSN", 3),
                    self._get_str_max(row, "proCodCst2", 2),
                    self._get_str_max(row, "proCodigo", 50),
                    self._get_float(row, "proCusto"),
                    self._get_int(row, "proDesativaProd", 0),
                    self._get_float(row, "proEstoqueAtual"),
                    self._get_float(row, "proEstoqueMin"),
                    self._get_str_max(row, "proLocalizador", 20),
                    self._get_str_max(row, "proPrateleira", 20),
                    self._get_float(row, "proVenda"),
                    pro_un_str,
                    unp_id, unp_un, unp_id
                ))

                # ── Inserir Codigo EAN em codBarras ──────────────────────────
                ean = self._get_str(row, "cdbCodigo")
                if ean and pro_id is not None and pro_id != "AUTO":
                    cursor.execute("""
                        IF NOT EXISTS (
                            SELECT 1 FROM codBarras
                            WHERE cdbCodigo = ? AND cdbIdProd = ?
                        )
                        INSERT INTO codBarras (cdbCodigo, cdbIdProd)
                        VALUES (?, ?)
                    """, (ean, pro_id, ean, pro_id))

                self.conn.commit()
                sucessos += 1
                if sucessos <= 5 or sucessos % 50 == 0:
                    self._log(f"✅ proId {pro_id} inserido")

            except Exception as e:
                self.conn.rollback()
                erros += 1
                nomes_erro.append(self._get_str(row, "proDescricao") or f"(linha {idx+2}, proId={pro_id})")
                if erros <= 5 or erros % 50 == 0:   # throttle: não inunda a GUI
                    self._log(f"❌ Erro linha {idx+2} proId={pro_id}: {str(e)[:200]}")

            self._set_progresso(idx + 1, total)

        # ── Reconfigurar IDENTITY após inserção ──────────────────────────
        try:
            cursor.execute("SELECT ISNULL(MAX(proId), 0) FROM produto")
            max_final = cursor.fetchone()[0]
            cursor.execute(f"DBCC CHECKIDENT ('produto', RESEED, {max_final})")
            self.conn.commit()
            self._log(f"🔧 IDENTITY reconfigurado — proximo proId sera {max_final + 1}.")
        except Exception as e:
            self._log(f"⚠️  Nao foi possivel reconfigurar IDENTITY: {e}")

        self._log(f"🎉 INSERT finalizado — ✅ {sucessos} inseridos | ❌ {erros} erros")
        self._ultimo_resultado = {"inseridos": sucessos, "pulados": 0, "erros": erros}

        # ── Aviso de unidades cadastradas automaticamente ────────────────
        if uns_criadas:
            uns_lista = sorted(u for u in uns_criadas if u)
            msg = ("As seguintes unidades NAO existiam na tabela produtoUn "
                   "e foram CADASTRADAS automaticamente, ja vinculadas aos "
                   "produtos importados:\n\n" +
                   "\n".join("  - " + u for u in uns_lista) +
                   "\n\nRevise a descricao dessas unidades no sistema, se desejar.")
            self._log("Unidades cadastradas automaticamente em produtoUn: " + ", ".join(uns_lista))
            self.after(0, lambda m=msg: messagebox.showinfo(
                "Unidades Cadastradas Automaticamente", m, parent=self))

        _pos_importacao(self, "PRODUTOS", nomes_erro, erros > 0)
        self._salvar_relatorio()
        self._verificar_acerto_apos_sucesso(sucessos)
        self.after(0, lambda: self.btn_import.configure(state="normal"))

    # ── UPDATE ────────────────────────────────────────────────────────────
    def _atualizar_produtos(self):
        cursor   = self.conn.cursor()
        total    = len(self.df)
        sucessos = 0
        erros    = 0
        emp_id   = self._get_emp_id(cursor)
        self._lookup_cache = {}   # cache de lookups (NCM/CEST) por execução

        self._log(f"🔄 Iniciando UPDATE — {total} registros | empId={emp_id}")

        nomes_erro = []       # nomes dos produtos que deram erro na atualizacao
        uns_criadas_upd = set()

        for idx, row in self.df.iterrows():
            if self._cancelado:
                break
            pro_id = None
            try:
                pro_id = self._get_str(row, "proId")
                if not pro_id:
                    continue

                # Lookups auxiliares
                fab_id      = self._get_or_create(cursor, "fabricante",    "fabId", "fabNome",     self._get_str(row, "fabNome"))
                grupo_id    = self._get_or_create(cursor, "grupoProd",     "gdpId", "gdpNome",      self._get_str(row, "gdpNome"))
                subgrupo_id = self._get_or_create(cursor, "subGrupoProd",  "sgpId", "sgpNome",      self._get_str(row, "sgpNome"),
                                                   extra_cols={"sgpIdGdp": grupo_id})
                classe_id   = self._get_or_create(cursor, "produtoClasse", "pclId", "pclDescricao", self._get_str(row, "pclDescricao"),
                                                   extra_cols={"pclDesativa": 0})
                ncm_id      = self._lookup(cursor, "proNCM",  "ncmId", "ncmCodigoNCM", self._get_str(row, "ncmCodigoNCM"))
                cest_id     = self._lookup(cursor, "proCEST", "cesId", "cesCodigo",    self._get_str(row, "cesCodigo"))

                # ── unidade em produtoUn (cadastra se nao existir) ────────────
                pro_un_upd  = self._get_str(row, "proUn") if "proUn" in self.mapping else None
                un_info_upd = self._get_or_create_unidade(cursor, pro_un_upd) if pro_un_upd else None
                if un_info_upd and un_info_upd.get("criada"):
                    uns_criadas_upd.add(un_info_upd["unpUn"])

                # Campos a atualizar na tabela produto (apenas os mapeados)
                set_prod  = []
                vals_prod = []
                mapa_prod = {
                    "proDescricao":     (lambda r, c: self._get_str_max(r, c, 100), "proDescricao"),
                    "proAplicacao":     (self._get_str,   "proAplicacao"),
                    "proBalanca":       (self._get_int,   "proBalanca"),
                    "proMedVenda":      (self._get_float, "proMedVenda"),
                    "proMultiplo":      (self._get_float, "proMultiplo"),
                    "proPeso":          (self._get_float, "proPeso"),
                    "proQtdComEntrada": (self._get_float, "proQtdComEntrada"),
                    "proUn":            (lambda r, c: self._get_str_max(r, c, 10),  "proUn"),
                    "proTipo":          (lambda r, c: self._get_str_max(r, c, 1),   "proTipo"),
                }
                for col_db, (fn, campo) in mapa_prod.items():
                    if campo in self.mapping:
                        set_prod.append(f"{col_db} = ?")
                        vals_prod.append(fn(row, campo))

                if fab_id      is not None: set_prod.append("proFab = ?");      vals_prod.append(fab_id)
                if grupo_id    is not None: set_prod.append("proGrupo = ?");    vals_prod.append(grupo_id)
                if subgrupo_id is not None: set_prod.append("proSubGrupo = ?"); vals_prod.append(subgrupo_id)
                if classe_id   is not None: set_prod.append("proClasseId = ?"); vals_prod.append(classe_id)
                if ncm_id      is not None: set_prod.append("proNcmId = ?");    vals_prod.append(ncm_id)
                if cest_id     is not None: set_prod.append("proCestId = ?");   vals_prod.append(cest_id)

                # Unidade encontrada → atualiza campos de unidade em produto
                if pro_un_upd and un_info_upd:
                    set_prod.append("proUnComercialId = ?"); vals_prod.append(un_info_upd["unpId"])
                    set_prod.append("proUnTrib = ?");        vals_prod.append(un_info_upd["unpUn"])
                    set_prod.append("proUnTribId = ?");      vals_prod.append(un_info_upd["unpId"])

                if set_prod:
                    cursor.execute(
                        f"UPDATE produto SET {', '.join(set_prod)} WHERE proId = ?",
                        vals_prod + [pro_id]
                    )

                # Campos a atualizar em produto_empresa
                set_emp  = []
                vals_emp = []
                mapa_emp = {
                    "proAtacado":      (self._get_float, "proAtacado"),
                    "proCodCSOSN":     (lambda r, c: self._get_str_max(r, c, 3),  "proCodCSOSN"),
                    "proCodCst2":      (lambda r, c: self._get_str_max(r, c, 2),  "proCodCst2"),
                    "proCodigo":       (lambda r, c: self._get_str_max(r, c, 50), "proCodigo"),
                    "proCusto":        (self._get_float, "proCusto"),
                    "proDesativaProd": (self._get_int,   "proDesativaProd"),
                    "proEstoqueAtual": (self._get_float, "proEstoqueAtual"),
                    "proEstoqueMin":   (self._get_float, "proEstoqueMin"),
                    "proLocalizador":  (lambda r, c: self._get_str_max(r, c, 20), "proLocalizador"),
                    "proPrateleira":   (lambda r, c: self._get_str_max(r, c, 20), "proPrateleira"),
                    "proVenda":        (self._get_float, "proVenda"),
                }
                for col_db, (fn, campo) in mapa_emp.items():
                    if campo in self.mapping:
                        set_emp.append(f"{col_db} = ?")
                        vals_emp.append(fn(row, campo))

                # Unidade encontrada → atualiza campos de unidade em produto_empresa
                if pro_un_upd and un_info_upd:
                    set_emp.append("proUnComercialId = ?"); vals_emp.append(un_info_upd["unpId"])
                    set_emp.append("proUnTrib = ?");        vals_emp.append(un_info_upd["unpUn"])
                    set_emp.append("proUnTribId = ?");      vals_emp.append(un_info_upd["unpId"])

                if set_emp:
                    cursor.execute(
                        f"UPDATE produto_empresa SET {', '.join(set_emp)} "
                        f"WHERE proId = ? AND empId = ?",
                        vals_emp + [pro_id, emp_id]
                    )

                self.conn.commit()
                # ── Inserir Codigo EAN em codBarras ──────────────────────────
                if "cdbCodigo" in self.mapping:
                    ean_upd = self._get_str(row, "cdbCodigo")
                    if ean_upd and pro_id:
                        cursor.execute("""
                            IF NOT EXISTS (
                                SELECT 1 FROM codBarras
                                WHERE cdbCodigo = ? AND cdbIdProd = ?
                            )
                            INSERT INTO codBarras (cdbCodigo, cdbIdProd)
                            VALUES (?, ?)
                        """, (ean_upd, pro_id, ean_upd, pro_id))

                sucessos += 1
                if sucessos <= 5 or sucessos % 50 == 0:
                    self._log(f"✅ proId {pro_id} atualizado")

            except Exception as e:
                self.conn.rollback()
                erros += 1
                nomes_erro.append(self._get_str(row, "proDescricao") or f"(linha {idx+2}, proId={pro_id})")
                if erros <= 5 or erros % 50 == 0:   # throttle: não inunda a GUI
                    self._log(f"❌ Erro linha {idx+2} proId={pro_id}: {str(e)[:200]}")

            self._set_progresso(idx + 1, total)

        self._log(f"🎉 UPDATE finalizado — ✅ {sucessos} atualizados | ❌ {erros} erros")

        # ── Aviso de unidades cadastradas automaticamente ────────────────
        if uns_criadas_upd:
            uns_lista_upd = sorted(u for u in uns_criadas_upd if u)
            msg_upd = ("As seguintes unidades NAO existiam na tabela produtoUn "
                       "e foram CADASTRADAS automaticamente, ja vinculadas aos "
                       "produtos atualizados:\n\n" +
                       "\n".join("  - " + u for u in uns_lista_upd) +
                       "\n\nRevise a descricao dessas unidades no sistema, se desejar.")
            self._log("Unidades cadastradas automaticamente (UPDATE): " + ", ".join(uns_lista_upd))
            self.after(0, lambda m=msg_upd: messagebox.showinfo(
                "Unidades Cadastradas Automaticamente", m, parent=self))

        _pos_importacao(self, "PRODUTOS", nomes_erro, erros > 0)
        self._salvar_relatorio()
        self._verificar_acerto_apos_sucesso(sucessos)
        self.after(0, lambda: self.btn_import.configure(state="normal"))
    # ── Log / Relatório ───────────────────────────────────────────────────

    def _verificar_acerto_apos_sucesso(self, sucessos):
        """Apos importar com sucesso, verifica se ha produtos com estoque > 0.
        Se houver, habilita o botao de gerar acerto; se nao, informa."""
        if not sucessos:
            return
        if getattr(self, "_suprimir_acerto", False):
            return   # migracao entre bancos nao dispara o acerto por entidade
        try:
            cur = self.conn.cursor()
            emp_id = self._get_emp_id(cur)
            cur.execute("SELECT COUNT(*) FROM produto_empresa "
                        "WHERE proEstoqueAtual > 0 AND empId = ?", (emp_id,))
            qtd = cur.fetchone()[0]
        except Exception as e:
            self._log(f"⚠️  Nao foi possivel verificar estoque para acerto: {str(e)[:150]}")
            return
        if qtd and qtd > 0:
            self.after(0, lambda: self.btn_acerto.configure(state="normal"))
            self.after(0, lambda q=qtd: messagebox.showinfo(
                "Acerto de Estoque",
                f"Importacao concluida com sucesso.\n\n"
                f"Ha {q} produto(s) com estoque (proEstoqueAtual > 0).\n\n"
                "Clique em '📦 Gerar Acerto de Estoque' para criar o acerto "
                "PENDENTE, que devera ser rodado no Manager.", parent=self))
        else:
            self.after(0, lambda: messagebox.showinfo(
                "Acerto de Estoque",
                "Importacao concluida.\n\nNao existe estoque (proEstoqueAtual > 0) "
                "para gerar acerto de estoque.", parent=self))

    def _gerar_acerto_estoque(self):
        """Gera um acerto de estoque PENDENTE (status 'A') no banco de destino,
        com todos os produtos que tem proEstoqueAtual > 0."""
        if not messagebox.askyesno(
                "Gerar Acerto de Estoque",
                "Isso vai criar um ACERTO DE ESTOQUE PENDENTE no banco, com os "
                "produtos que tem estoque > 0.\n\n"
                "Depois de gerar, RODE o acerto no Manager.\n\nConfirma?", parent=self):
            return
        try:
            cur = self.conn.cursor()
            emp_id = self._get_emp_id(cur)

            # usuario administrador (cliUsuLoginId = 2)
            cur.execute("SELECT TOP 1 cliId FROM cliente WHERE cliUsuLoginId = 2")
            r = cur.fetchone()
            if not r or r[0] is None:
                messagebox.showerror(
                    "Acerto de Estoque",
                    "Usuario administrador (cliUsuLoginId = 2) nao encontrado neste "
                    "banco. Nao foi possivel gerar o acerto.", parent=self)
                return
            admin_id = r[0]

            # confere se ha estoque
            cur.execute("SELECT COUNT(*) FROM produto_empresa "
                        "WHERE proEstoqueAtual > 0 AND empId = ?", (emp_id,))
            qtd = cur.fetchone()[0]
            if not qtd:
                messagebox.showinfo(
                    "Acerto de Estoque",
                    "Nao existe estoque (proEstoqueAtual > 0) para gerar acerto.",
                    parent=self)
                return

            # cabecalho — captura paeId no mesmo batch (triggers AFTER na tabela)
            cur.execute("""
                SET NOCOUNT ON;
                INSERT INTO produtoAcertoEstoque
                    (empId, paeVedId, paeVedIdSaida, paeStatus, paeUsuId,
                     paeDataOcorrencia, paeObs)
                VALUES (?, NULL, NULL, 'A', ?, GETDATE(), ?);
                SELECT SCOPE_IDENTITY();
            """, (emp_id, admin_id, "MAXDATA SISTEMA - IMPORTACAO"))
            fetched = cur.fetchone()
            if not fetched or fetched[0] is None:
                raise ValueError("Nao foi possivel obter o ID do acerto (SCOPE_IDENTITY nulo).")
            pae_id = int(fetched[0])

            # itens — um por produto com estoque > 0
            cur.execute("""
                INSERT INTO produtoAcertoEstoqueItem
                    (paiPaeId, paiProId, paiProEstoque, paiQtdInf, paiLote, paiLoteEstoque)
                SELECT ?, pe.proId, 0, pe.proEstoqueAtual, 'X', 0
                FROM produto_empresa pe
                WHERE pe.proEstoqueAtual > 0 AND pe.empId = ?
            """, (pae_id, emp_id))
            self.conn.commit()

            self._log(f"✅ Acerto de estoque PENDENTE gerado — paeId={pae_id} | {qtd} item(ns) | empId={emp_id}")
            self.after(0, lambda: self.btn_acerto.configure(state="disabled"))
            messagebox.showinfo(
                "Acerto de Estoque",
                f"Acerto de estoque PENDENTE gerado com sucesso.\n\n"
                f"Nº do acerto (paeId): {pae_id}\nItens: {qtd}\n\n"
                "Agora RODE o acerto de estoque no Manager.", parent=self)
        except Exception as e:
            try:
                self.conn.rollback()
            except Exception:
                pass
            self._log(f"❌ Erro ao gerar acerto de estoque: {str(e)[:200]}")
            messagebox.showerror(
                "Acerto de Estoque",
                f"Falha ao gerar o acerto de estoque:\n{str(e)[:300]}", parent=self)



class ClientesImportMixin:
    def _calc_cli_tipo(self, row):
        """Define cliTipo. Se o campo estiver mapeado e preenchido, usa o valor.
        Caso contrário, deriva do cliCpfCgc: CPF (11 díg) = 0 (Pessoa Física),
        CNPJ (14 díg) = 1 (Pessoa Jurídica). Se o CPF/CNPJ estiver vazio (ou com
        tamanho inesperado), retorna None (deixa vazio/NULL).

        Vive AQUI (no mixin), não na JanelaClientes, para que o importador HEADLESS
        (migração) também o tenha — é lógica pura (sem GUI). A JanelaClientes herda
        ClientesImportMixin, então continua tendo o método por herança."""
        v = self._get_int(row, "cliTipo", None)
        if v is not None:
            return v
        cpf = self._get_str(row, "cliCpfCgc")
        dig = re.sub(r"\D", "", cpf) if cpf else ""
        if len(dig) == 14:
            return 1
        if len(dig) == 11:
            return 0
        return None

    def _inserir_clientes(self):
        total    = len(self.df)
        sucessos = 0
        erros    = 0

        # Cursor normal para DML (INSERT/SELECT com transação)
        cursor = self.conn.cursor()
        emp_id = self._get_emp_id(cursor)

        self._log(f"Iniciando INSERT clientes — {total} registros | empId={emp_id}")

        nomes_erro = []       # nomes dos clientes que deram erro na importacao

        # Verifica se cliId está mapeado e tem valores válidos
        col_id        = self.mapping.get("cliId")
        ids_arq       = []
        usar_identity = True

        if col_id:
            raw_ids = self.df[col_id].dropna().astype(str).str.strip()
            raw_ids = raw_ids[~raw_ids.str.upper().isin(["", "NULL", "NONE", "NAN"])]
            try:
                ids_arq = [int(float(v)) for v in raw_ids]
            except Exception:
                ids_arq = []

        if ids_arq:
            usar_identity = False
            # Checa quais IDs já existem — avisa mas NÃO aborta; serão pulados no loop
            ids_set = set(ids_arq)
            fmt = ",".join(str(i) for i in ids_set)
            cursor.execute(f"SELECT cliId FROM cliente WHERE cliId IN ({fmt})")
            self.cliids_ja_existentes = {r[0] for r in cursor.fetchall()}
            if self.cliids_ja_existentes:
                lista   = sorted(self.cliids_ja_existentes)
                amostra = ", ".join(str(x) for x in lista[:20])
                suf     = " ... (+" + str(len(lista) - 20) + " mais)" if len(lista) > 20 else ""
                self._log("Aviso — cliId ja existentes (serao pulados): " + amostra + suf)
            else:
                self.cliids_ja_existentes = set()
        else:
            self.cliids_ja_existentes = set()

        # ── Comandos DDL/admin em autocommit (DBCC e IDENTITY_INSERT) ────────
        # Precisam de autocommit para não serem afetados por rollback de DML
        self.conn.autocommit = True
        cur_ddl = self.conn.cursor()
        try:
            if usar_identity:
                # Consulta o MAX real da tabela para reajustar o seed corretamente.
                # O seed do SQL Server pode estar adiantado em relação ao MAX(cliId)
                # por causa de tentativas anteriores com rollback — por isso SEMPRE
                # fazemos o RESEED explícito antes de inserir.
                cur_ddl.execute("SELECT ISNULL(MAX(cliId), 0) FROM cliente")
                max_atual = cur_ddl.fetchone()[0]
                seed_novo = max(max_atual, 10)   # garante mínimo 10 → próximo ≥ 11
                cur_ddl.execute(f"DBCC CHECKIDENT ('cliente', RESEED, {seed_novo})")
                proximo = seed_novo + 1
                self._log(f"Seed reajustado para {seed_novo} — proximo cliId sera {proximo}.")
            else:
                max_arq = max(ids_arq)
                cur_ddl.execute("SELECT ISNULL(MAX(cliId), 0) FROM cliente")
                max_db = cur_ddl.fetchone()[0]
                self._log(f"cliId do arquivo: min={min(ids_arq)} max={max_arq} | max DB: {max_db}")
                cur_ddl.execute("SET IDENTITY_INSERT cliente ON")
        except Exception as e:
            self._log(f"Erro ao preparar IDENTITY: {e}")
            self.conn.autocommit = False
            self.after(0, lambda: self.btn_import.configure(state="normal"))
            return
        finally:
            cur_ddl.close()

        # Volta ao modo transacional para os INSERTs
        self.conn.autocommit = False
        cursor = self.conn.cursor()

        # Monta dict idx -> cliId do arquivo
        id_map = {}
        if not usar_identity and col_id:
            for idx, row in self.df.iterrows():
                raw = str(row.get(col_id, "")).strip()
                try:
                    id_map[idx] = int(float(raw))
                except Exception:
                    id_map[idx] = None

        for idx, row in self.df.iterrows():
            if self._cancelado:
                break
            cli_id = None
            try:
                if usar_identity:
                    cli_id = "AUTO"
                else:
                    cli_id = id_map.get(idx)
                    if cli_id is None:
                        self._log(f"Linha {idx+2}: cliId invalido, ignorando.")
                        continue

                # Pula IDs que já existiam na tabela antes do import
                if not usar_identity and isinstance(cli_id, int) and cli_id in self.cliids_ja_existentes:
                    self._log(f"Linha {idx+2}: cliId {cli_id} ja existe — pulado.")
                    continue

                # Valida reservados (< 10) — segurança extra por linha
                if cli_id != "AUTO" and isinstance(cli_id, int) and cli_id < 10:
                    self._log(f"Linha {idx+2}: cliId {cli_id} reservado, ignorando.")
                    continue

                data_inc = self._get_datetime(row, "DataInclusao")

                if usar_identity:
                    # Tabela tem triggers — OUTPUT não é compatível.
                    # Usamos SET NOCOUNT OFF + INSERT + SELECT @@IDENTITY
                    # em um único batch para garantir o ID gerado.
                    cursor.execute("SET NOCOUNT OFF")
                    cursor.execute("""
                        INSERT INTO cliente (
                            cliCpfCgc, cliNome, cliFantasia, cliRgInsc,
                            cliFatEnd, cliFatEndNumero, cliFatBairro,
                            cliFatCidade, cliFatUf, cliFatCep,
                            cliFatCidCodIBGE,
                            cliEmail, cliFone, cliDesativa, cliTipoCad, cliTipo,
                            cliDatCad
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        self._get_str_max(row, "cliCpfCgc",        20),
                        self._get_str_max(row, "cliNome",           50),
                        self._get_str_max(row, "cliFantasia",       50),
                        self._get_str_max(row, "cliRgInsc",         20),
                        self._get_str_max(row, "cliFatEnd",        120),
                        self._get_str_max(row, "cliFatEndNumero",   10),
                        self._get_str_max(row, "cliFatBairro",      70),
                        self._get_str_max(row, "cliFatCidade",      30),
                        self._get_str_max(row, "cliFatUf",           2),
                        self._get_str_max(row, "cliFatCep",          9),
                        self._get_str_max(row, "cliFatCidCodIBGE",  20),
                        self._get_str_max(row, "cliEmail",         254),
                        self._get_str_max(row, "cliFone",           20),
                        self._get_int(row, "cliDesativa", 0),
                        self._get_int(row, "cliTipoCad",  0),
                        self._calc_cli_tipo(row),
                        data_inc
                    ))
                    # @@IDENTITY funciona mesmo com triggers (pega o último ID
                    # gerado na sessão, incluindo os disparados por triggers)
                    cursor.execute("SELECT @@IDENTITY")
                    row_id = cursor.fetchone()[0]
                    if row_id is None:
                        raise ValueError("@@IDENTITY retornou NULL — INSERT nao foi executado.")
                    cli_id = int(row_id)
                else:
                    cursor.execute("""
                        IF NOT EXISTS (SELECT 1 FROM cliente WHERE cliId = ?)
                        INSERT INTO cliente (
                            cliId,
                            cliCpfCgc, cliNome, cliFantasia, cliRgInsc,
                            cliFatEnd, cliFatEndNumero, cliFatBairro,
                            cliFatCidade, cliFatUf, cliFatCep,
                            cliFatCidCodIBGE,
                            cliEmail, cliFone, cliDesativa, cliTipoCad, cliTipo,
                            cliDatCad
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        cli_id,
                        cli_id,
                        self._get_str_max(row, "cliCpfCgc",        20),
                        self._get_str_max(row, "cliNome",           50),
                        self._get_str_max(row, "cliFantasia",       50),
                        self._get_str_max(row, "cliRgInsc",         20),
                        self._get_str_max(row, "cliFatEnd",        120),
                        self._get_str_max(row, "cliFatEndNumero",   10),
                        self._get_str_max(row, "cliFatBairro",      70),
                        self._get_str_max(row, "cliFatCidade",      30),
                        self._get_str_max(row, "cliFatUf",           2),
                        self._get_str_max(row, "cliFatCep",          9),
                        self._get_str_max(row, "cliFatCidCodIBGE",  20),
                        self._get_str_max(row, "cliEmail",         254),
                        self._get_str_max(row, "cliFone",           20),
                        self._get_int(row, "cliDesativa", 0),
                        self._get_int(row, "cliTipoCad",  0),
                        self._calc_cli_tipo(row),
                        data_inc
                    ))

                # ── cliente_empresa ──────────────────────────────────────────
                _zero_dec = Decimal('0.00000')
                cursor.execute("""
                    IF NOT EXISTS (SELECT 1 FROM cliente_empresa WHERE cliId = ? AND empId = ?)
                    INSERT INTO cliente_empresa (
                        empId, cliId,
                        cliCalculaIcmsSubst,
                        cliDescontoAutoAplicar,
                        cliDescontoAutoAliq,
                        cliMaxdataRateioCredito_Aliq_01,
                        cliMaxdataRateioCredito_Aliq_02,
                        cliMaxdataRateioCredito_Aliq_03,
                        cliDatCad
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                """, (
                    cli_id, emp_id,
                    emp_id, cli_id,
                    0,          # cliCalculaIcmsSubst   int
                    0,          # cliDescontoAutoAplicar bit
                    _zero_dec,  # cliDescontoAutoAliq            decimal(18,5)
                    _zero_dec,  # cliMaxdataRateioCredito_Aliq_01 decimal(18,5)
                    _zero_dec,  # cliMaxdataRateioCredito_Aliq_02 decimal(18,5)
                    _zero_dec,  # cliMaxdataRateioCredito_Aliq_03 decimal(18,5)
                    data_inc
                ))

                self.conn.commit()
                sucessos += 1
                if sucessos <= 5 or sucessos % 50 == 0:
                    self._log(f"✅ cliId {cli_id} inserido")

            except Exception as e:
                self.conn.rollback()
                erros += 1
                nomes_erro.append(self._get_str(row, "cliNome") or f"(linha {idx+2}, cliId={cli_id})")
                if erros <= 5 or erros % 50 == 0:   # throttle: não inunda a GUI
                    self._log(f"❌ Erro linha {idx+2} cliId={cli_id}: {str(e)[:200]}")
                # Após rollback no modo identity, o seed SQL Server pode ter avançado.
                # Reajusta para MAX real da tabela antes de tentar o próximo registro.
                if usar_identity:
                    try:
                        self.conn.autocommit = True
                        cur_re = self.conn.cursor()
                        cur_re.execute("SELECT ISNULL(MAX(cliId), 0) FROM cliente")
                        max_re = cur_re.fetchone()[0]
                        seed_re = max(max_re, 10)
                        cur_re.execute(f"DBCC CHECKIDENT ('cliente', RESEED, {seed_re})")
                        cur_re.close()
                        self.conn.autocommit = False
                    except Exception:
                        self.conn.autocommit = False

            self._set_progresso(idx + 1, total)

        # Desliga IDENTITY_INSERT e reajusta seed — em autocommit
        self.conn.autocommit = True
        cur_fim = self.conn.cursor()
        try:
            if not usar_identity:
                cur_fim.execute("SET IDENTITY_INSERT cliente OFF")
            cur_fim.execute("SELECT ISNULL(MAX(cliId), 10) FROM cliente")
            max_final = cur_fim.fetchone()[0]
            cur_fim.execute(f"DBCC CHECKIDENT ('cliente', RESEED, {max_final})")
            self._log(f"IDENTITY reconfigurado — proximo cliId sera {max_final + 1}.")
        except Exception as e:
            self._log(f"Aviso: nao foi possivel reconfigurar IDENTITY: {e}")
        finally:
            cur_fim.close()
        self.conn.autocommit = False

        pulados = len(self.cliids_ja_existentes)
        if pulados:
            self._log(f"ℹ️  {pulados} cliId ja existentes foram pulados (use UPDATE para atualiza-los).")
        self._log(f"🎉 INSERT finalizado — ✅ {sucessos} inseridos | ⏭️ {pulados} pulados | ❌ {erros} erros")
        self._ultimo_resultado = {"inseridos": sucessos, "pulados": pulados, "erros": erros}
        _pos_importacao(self, "CLIENTES", nomes_erro, erros > 0)
        self._salvar_relatorio()
        self.after(0, lambda: self.btn_import.configure(state="normal"))

    # ── Confirmação de UPDATE por CPF/CNPJ ───────────────────────────────

    def _atualizar_clientes_por_cpf(self):
        cursor   = self.conn.cursor()
        total    = len(self.df)
        sucessos = 0
        erros    = 0
        nao_enc  = 0
        emp_id   = self._get_emp_id(cursor)

        self._log(f"Iniciando UPDATE por CPF/CNPJ — {total} registros | empId={emp_id}")

        nomes_erro = []       # nomes dos clientes que deram erro na atualizacao

        for idx, row in self.df.iterrows():
            if self._cancelado:
                break
            cpf_cnpj = None
            try:
                cpf_cnpj = self._get_str(row, "cliCpfCgc")
                if not cpf_cnpj:
                    self._log(f"Linha {idx+2}: cliCpfCgc vazio, ignorando.")
                    nao_enc += 1
                    self._set_progresso(idx + 1, total)
                    continue

                cursor.execute(
                    "SELECT TOP 1 cliId FROM cliente WHERE cliCpfCgc = ?",
                    (cpf_cnpj,)
                )
                row_db = cursor.fetchone()
                if not row_db:
                    self._log(f"Linha {idx+2}: CPF/CNPJ '{cpf_cnpj}' nao encontrado — pulado.")
                    nao_enc += 1
                    self._set_progresso(idx + 1, total)
                    continue

                cli_id   = row_db[0]
                data_inc = self._get_datetime(row, "DataInclusao")

                if isinstance(cli_id, int) and cli_id < 10:
                    self._log(f"Linha {idx+2}: cliId {cli_id} reservado (<10), ignorando.")
                    self._set_progresso(idx + 1, total)
                    continue

                set_cli  = []
                vals_cli = []
                mapa_cli = {
                    "cliNome":          (self._get_str, "cliNome"),
                    "cliFantasia":      (self._get_str, "cliFantasia"),
                    "cliRgInsc":        (self._get_str, "cliRgInsc"),
                    "cliFatEnd":        (self._get_str, "cliFatEnd"),
                    "cliFatEndNumero":  (lambda r, c: self._get_str_max(r, c, 10), "cliFatEndNumero"),
                    "cliFatBairro":     (self._get_str, "cliFatBairro"),
                    "cliFatCidade":     (self._get_str, "cliFatCidade"),
                    "cliFatUf":         (self._get_str, "cliFatUf"),
                    "cliFatCep":        (self._get_str, "cliFatCep"),
                    "cliFatCidCodIBGE": (self._get_str, "cliFatCidCodIBGE"),
                    "cliEmail":         (self._get_str, "cliEmail"),
                    "cliFone":          (self._get_str, "cliFone"),
                    "cliDesativa":      (self._get_int, "cliDesativa"),
                    "cliTipoCad":       (self._get_int, "cliTipoCad"),
                }
                for col_db, (fn, campo) in mapa_cli.items():
                    if campo in self.mapping:
                        set_cli.append(f"{col_db} = ?")
                        vals_cli.append(fn(row, campo))

                # cliTipo: usa o mapeado; senão deriva do CPF/CNPJ (só atualiza
                # quando há valor — CPF/CNPJ vazio deixa o campo como está)
                _tipo = self._calc_cli_tipo(row)
                if _tipo is not None:
                    set_cli.append("cliTipo = ?")
                    vals_cli.append(_tipo)

                if "DataInclusao" in self.mapping and data_inc is not None:
                    set_cli.append("cliDatCad = ?")
                    vals_cli.append(data_inc)

                if set_cli:
                    cursor.execute(
                        f"UPDATE cliente SET {', '.join(set_cli)} WHERE cliId = ?",
                        vals_cli + [cli_id]
                    )

                set_emp  = []
                vals_emp = []
                if "DataInclusao" in self.mapping and data_inc is not None:
                    set_emp.append("cliDatCad = ?")
                    vals_emp.append(data_inc)

                if set_emp:
                    cursor.execute(
                        f"UPDATE cliente_empresa SET {', '.join(set_emp)} "
                        f"WHERE cliId = ? AND empId = ?",
                        vals_emp + [cli_id, emp_id]
                    )

                self.conn.commit()
                sucessos += 1
                if sucessos <= 5 or sucessos % 50 == 0:
                    self._log(f"OK CPF/CNPJ {cpf_cnpj} -> cliId {cli_id} atualizado")

            except Exception as e:
                self.conn.rollback()
                erros += 1
                nomes_erro.append(self._get_str(row, "cliNome") or f"(linha {idx+2}, CPF/CNPJ={cpf_cnpj})")
                self._log(f"Erro linha {idx+2} CPF/CNPJ={cpf_cnpj}: {str(e)[:200]}")

            self._set_progresso(idx + 1, total)

        self._log(f"UPDATE por CPF/CNPJ finalizado — "
                  f"{sucessos} atualizados | "
                  f"{nao_enc} nao encontrados | "
                  f"{erros} erros")
        _pos_importacao(self, "CLIENTES", nomes_erro, erros > 0)
        self._salvar_relatorio()
        self.after(0, lambda: self.btn_import.configure(state="normal"))

    # ── UPDATE clientes ───────────────────────────────────────────────────
    def _atualizar_clientes(self):
        cursor   = self.conn.cursor()
        total    = len(self.df)
        sucessos = 0
        erros    = 0
        emp_id   = self._get_emp_id(cursor)

        self._log(f"Iniciando UPDATE clientes — {total} registros | empId={emp_id}")

        nomes_erro = []       # nomes dos clientes que deram erro na atualizacao

        for idx, row in self.df.iterrows():
            if self._cancelado:
                break
            cli_id = None
            try:
                cli_id = self._get_str(row, "cliId")
                if not cli_id:
                    self._log(f"Linha {idx+2}: cliId vazio, ignorando.")
                    continue

                # Valida reservados
                try:
                    if int(float(cli_id)) < 10:
                        self._log(f"Linha {idx+2}: cliId {cli_id} reservado (<10), ignorando.")
                        continue
                except Exception:
                    pass

                data_inc = self._get_datetime(row, "DataInclusao")

                # ── UPDATE cliente ───────────────────────────────────────────
                set_cli  = []
                vals_cli = []
                mapa_cli = {
                    "cliCpfCgc":        (self._get_str, "cliCpfCgc"),
                    "cliNome":          (self._get_str, "cliNome"),
                    "cliFantasia":      (self._get_str, "cliFantasia"),
                    "cliRgInsc":        (self._get_str, "cliRgInsc"),
                    "cliFatEnd":        (self._get_str, "cliFatEnd"),
                    "cliFatEndNumero":  (lambda r, c: self._get_str_max(r, c, 10), "cliFatEndNumero"),
                    "cliFatBairro":     (self._get_str, "cliFatBairro"),
                    "cliFatCidade":     (self._get_str, "cliFatCidade"),
                    "cliFatUf":         (self._get_str, "cliFatUf"),
                    "cliFatCep":        (self._get_str, "cliFatCep"),
                    "cliFatCidCodIBGE": (self._get_str, "cliFatCidCodIBGE"),
                    "cliEmail":         (self._get_str, "cliEmail"),
                    "cliFone":          (self._get_str, "cliFone"),
                    "cliDesativa":      (self._get_int, "cliDesativa"),
                    "cliTipoCad":       (self._get_int, "cliTipoCad"),
                }
                for col_db, (fn, campo) in mapa_cli.items():
                    if campo in self.mapping:
                        set_cli.append(f"{col_db} = ?")
                        vals_cli.append(fn(row, campo))

                # cliTipo: usa o mapeado; senão deriva do CPF/CNPJ (só atualiza
                # quando há valor — CPF/CNPJ vazio deixa o campo como está)
                _tipo = self._calc_cli_tipo(row)
                if _tipo is not None:
                    set_cli.append("cliTipo = ?")
                    vals_cli.append(_tipo)

                if "DataInclusao" in self.mapping and data_inc is not None:
                    set_cli.append("cliDatCad = ?")
                    vals_cli.append(data_inc)

                if set_cli:
                    cursor.execute(
                        f"UPDATE cliente SET {', '.join(set_cli)} WHERE cliId = ?",
                        vals_cli + [cli_id]
                    )

                # ── UPDATE cliente_empresa ───────────────────────────────────
                set_emp  = []
                vals_emp = []
                if "DataInclusao" in self.mapping and data_inc is not None:
                    set_emp.append("cliDatCad = ?")
                    vals_emp.append(data_inc)

                if set_emp:
                    cursor.execute(
                        f"UPDATE cliente_empresa SET {', '.join(set_emp)} "
                        f"WHERE cliId = ? AND empId = ?",
                        vals_emp + [cli_id, emp_id]
                    )

                self.conn.commit()
                sucessos += 1
                if sucessos <= 5 or sucessos % 50 == 0:
                    self._log(f"✅ cliId {cli_id} atualizado")

            except Exception as e:
                self.conn.rollback()
                erros += 1
                nomes_erro.append(self._get_str(row, "cliNome") or f"(linha {idx+2}, cliId={cli_id})")
                if erros <= 5 or erros % 50 == 0:   # throttle: não inunda a GUI
                    self._log(f"❌ Erro linha {idx+2} cliId={cli_id}: {str(e)[:200]}")

            self._set_progresso(idx + 1, total)

        self._log(f"🎉 UPDATE finalizado — ✅ {sucessos} atualizados | ❌ {erros} erros")
        _pos_importacao(self, "CLIENTES", nomes_erro, erros > 0)
        self._salvar_relatorio()
        self.after(0, lambda: self.btn_import.configure(state="normal"))

    # ── Log / Relatório ───────────────────────────────────────────────────


class FinanceiroImportMixin:
    # SQL de INSERT do vendaPgto — módulo-nível (reutilizado no bulk e no fallback).
    _SQL_INS_VENDAPGTO = (
        "INSERT INTO vendaPgto (empId, pgtClienteId, pgtCliNome, pgtTipoVista, "
        "pgtTipoPrazo, pgtValor, pgtNumDoc, pgtData, pgtVecmto, pgtObs, "
        "pgtTipoConta, pgtPago, pgtDataQuitou, pgtNossoNumero) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
    )

    def _inserir_financeiro(self):
        ins = self.conn.cursor()          # cursor do INSERT (bulk via executemany)
        rd  = self.conn.cursor()          # cursor de leitura (lookup / dedup)
        try:
            ins.fast_executemany = True   # envia o lote num único RPC (10-40x)
        except Exception:
            pass
        total      = len(self.df)
        sucessos   = 0
        erros      = 0
        nao_enc    = 0
        duplicados = 0
        emp_id     = self._get_emp_id(rd)
        dedup_on   = bool(getattr(self, "_dedup_financeiro", False))
        dry_run    = bool(getattr(self, "_dry_run", False))

        self._log((f"🔎 SIMULAÇÃO vendaPgto (não grava) — {total} registros | empId={emp_id}"
                   if dry_run else
                   f"Iniciando INSERT vendaPgto — {total} registros | empId={emp_id}")
                  + (" | dedup ativo" if dedup_on else "")
                  + ("" if dry_run else " | bulk (executemany)"))

        nomes_erro = []          # CPF/CNPJ dos lancamentos que deram erro
        SQL   = self._SQL_INS_VENDAPGTO
        BATCH = 1000
        lote  = []               # [(vals_tuple, idx, cpf_cnpj), ...]
        pend  = set()            # chaves de dedup do lote AINDA não gravado

        def flush():
            """Grava o lote acumulado com executemany (caminho rápido), com retry em
            erro TRANSIENTE (deadlock/timeout — o lote é atômico, seguro re-tentar).
            Se falhar por erro de DADOS, desfaz e reprocessa linha-a-linha SÓ aquele
            lote, isolando a(s) ruim(s) sem perder as boas (cada linha também com retry)."""
            nonlocal sucessos, erros, lote, pend
            if not lote:
                return
            if dry_run:                        # SIMULAÇÃO: conta o que ENTRARIA, não grava
                sucessos += len(lote)
                lote = []
                pend = set()
                return

            def _bulk():
                try:
                    self.conn.rollback()      # estado limpo antes de (re)tentar
                except Exception:
                    pass
                ins.executemany(SQL, [t[0] for t in lote])
                self.conn.commit()

            try:
                self._com_retry(_bulk, f"vendaPgto (lote de {len(lote)})")
                sucessos += len(lote)
            except Exception:                 # não-transiente → isola linha-a-linha
                try:
                    self.conn.rollback()
                except Exception:
                    pass
                for vals, idx, cpf in lote:   # fallback isolado (caminho lento)
                    def _row(vals=vals):
                        ins.execute(SQL, vals)
                        self.conn.commit()
                    try:
                        self._com_retry(_row, f"linha {idx+2}")
                        sucessos += 1
                    except Exception as e:
                        try:
                            self.conn.rollback()
                        except Exception:
                            pass
                        erros += 1
                        nomes_erro.append(cpf or f"(linha {idx+2})")
                        if erros <= 5 or erros % 50 == 0:
                            self._log(f"❌ Erro linha {idx+2}: {str(e)[:200]}")
            lote = []
            pend = set()          # já gravado → o dedup por SELECT passa a enxergar

        for idx, row in self.df.iterrows():
            if self._cancelado:
                break
            # ── Lookup CPF/CNPJ → cliId ────────────────────────────────────
            cpf_cnpj = self._get_str(row, "cliCpfCgc")
            cli_id   = self._lookup_cli_id(rd, cpf_cnpj)
            if cli_id is None:
                nao_enc += 1
                linha_dict = {col: row.get(self.mapping[campo], "")
                              for campo, col in
                              [(c, self.mapping[c]) for c in self.mapping]}
                linha_dict["_linha"]   = idx + 2
                linha_dict["_cpfcnpj"] = cpf_cnpj or ""
                self.nao_encontrados.append(linha_dict)
                if nao_enc <= 5 or nao_enc % 500 == 0:
                    self._log(f"⚠️  Linha {idx+2}: CPF/CNPJ '{cpf_cnpj}' nao encontrado — "
                              f"pulado (amostra; {nao_enc} até agora).")
                self._set_progresso(idx + 1, total)
                continue

            # ── Converte tipos ─────────────────────────────────────────────
            pgt_valor      = self._get_decimal(row, "pgtValor")
            pgt_data       = self._get_datetime(row, "pgtData")
            pgt_vecmto     = self._get_datetime(row, "pgtVecmto")
            pgt_data_quit  = self._get_datetime(row, "pgtDataQuitou")
            pgt_tipo_vista = self._get_int(row, "pgtTipoVista")
            pgt_tipo_prazo = self._get_int(row, "pgtTipoPrazo")
            pgt_numdoc     = self._get_str_max(row, "pgtNumDoc", 30)
            pgt_tipoconta  = self._get_str_max(row, "pgtTipoConta", 1)

            # ── Idempotência (migração): pula se já existe lançamento igual ──
            if dedup_on:
                # O SELECT nunca casa se um campo comparado com '=' for NULL
                # (semântica SQL). Só dedupamos DENTRO do lote quando a chave é
                # totalmente casável — assim o comportamento é idêntico ao antigo.
                casavel = (pgt_valor is not None and pgt_data is not None
                           and pgt_vecmto is not None)
                chave = (cli_id, pgt_valor, pgt_data, pgt_vecmto,
                         pgt_numdoc or '', pgt_tipoconta or '')
                if casavel and chave in pend:
                    duplicados += 1
                    self._set_progresso(idx + 1, total)
                    continue
                rd.execute(
                    "SELECT TOP 1 1 FROM vendaPgto WHERE empId = ? AND pgtClienteId = ? "
                    "AND pgtValor = ? AND pgtData = ? AND pgtVecmto = ? "
                    "AND ISNULL(pgtNumDoc,'') = ISNULL(?,'') "
                    "AND ISNULL(pgtTipoConta,'') = ISNULL(?,'')",
                    (emp_id, cli_id, pgt_valor, pgt_data, pgt_vecmto,
                     pgt_numdoc, pgt_tipoconta))
                if rd.fetchone():
                    duplicados += 1
                    self._set_progresso(idx + 1, total)
                    continue
                if casavel:
                    pend.add(chave)

            vals = (
                emp_id, cli_id,
                self._get_str_max(row, "pgtCliNome", 50),
                pgt_tipo_vista, pgt_tipo_prazo, pgt_valor, pgt_numdoc,
                pgt_data, pgt_vecmto,
                self._get_str_max(row, "pgtObs", 1000),
                pgt_tipoconta,
                self._get_str_max(row, "pgtPago", 1),
                pgt_data_quit,
                self._get_str_max(row, "pgtNossoNumero", 30),
            )
            lote.append((vals, idx, cpf_cnpj))
            if len(lote) >= BATCH:
                flush()
                self._log(f"── vendaPgto: {sucessos} inseridos...")
            self._set_progresso(idx + 1, total)

        flush()      # grava o resto (mesmo se cancelado, confirma o que entrou)

        # ── Resumo final ─────────────────────────────────────────────────
        if dry_run:
            self._log(f"🔎 SIMULAÇÃO concluída — ✅ {sucessos} SERIAM inseridos "
                      f"| ⚠️ {nao_enc} CPF/CNPJ nao encontrados (seriam pulados) "
                      f"| ❌ 0 erros de gravação (nada foi gravado)")
        else:
            self._log(f"🎉 INSERT finalizado — ✅ {sucessos} inseridos "
                      f"| ⏭️ {duplicados} já existentes (dup) "
                      f"| ⚠️ {nao_enc} CPF/CNPJ nao encontrados "
                      f"| ❌ {erros} erros")
        # Alerta agregado de datas não reconhecidas. Na importação real elas viram
        # NULL; na SIMULAÇÃO, é justamente o que o usuário quer ver ANTES de gravar.
        di = getattr(self, "_datas_invalidas", None)
        if di:
            tot = sum(di.values())
            det = ", ".join(f"{k}={v}" for k, v in di.items())
            self._log(f"⚠️  ATENÇÃO: {tot} valor(es) de data NÃO reconhecido(s) "
                      + (f"(seriam gravados como NULL)" if dry_run else "e gravado(s) como NULL")
                      + f" ({det}). Verifique o formato das datas no arquivo "
                      f"(ex.: dd/mm/aaaa, aaaa-mm-dd).")
        if dry_run:
            self._log("ℹ️  Nada foi gravado (modo simulação). Desmarque "
                      "'🔎 Simular' para importar de verdade.")
        self._ultimo_resultado = {"simulacao": dry_run, "inseridos": sucessos,
                                  "pulados": nao_enc + duplicados, "erros": erros}

        # ── Aviso e opção de salvar linhas não encontradas ────────────────
        # lambda (lazy): no headless da migração, after() é no-op e NÃO acessa
        # _aviso_nao_encontrados (método só da GUI) — evita AttributeError.
        if self.nao_encontrados and hasattr(self, "_aviso_nao_encontrados"):
            self.after(0, lambda: self._aviso_nao_encontrados())

        # _pos_importacao NÃO renomeia/reseta em dry-run (ver guarda lá dentro).
        _pos_importacao(self, "FINANCEIRO", nomes_erro, erros > 0)
        self._salvar_relatorio()
        self.after(0, lambda: self.btn_import.configure(state="normal"))


# ─────────────────────────────────────────────────────────────────────────────
# Importadores HEADLESS (sem GUI) — a migração reutiliza a lógica dos mixins de
# import sem construir janelas ctk (ver JanelaMigracao._get_importador).
# ─────────────────────────────────────────────────────────────────────────────
class _ImportadorHeadless:
    """Provê os stubs que os workers de import esperam quando NÃO há janela:
      - after(): no-op (não executa callbacks de GUI — progress/messagebox/botões);
      - _set_progresso()/_salvar_relatorio(): vazios;
      - _log: injetado pela migração (encaminha ao log/relatório da migração);
      - _suprimir_acerto=True: o worker de Produtos não dispara o acerto por
        entidade (a migração cuida disso em _acerto_estoque_pos_migracao).
    O _verificar_acerto_apos_sucesso REAL (do mixin) é reusado e já no-opa com
    _suprimir_acerto=True."""
    def __init__(self, log=None):
        self._cancelado = False
        self._suprimir_acerto = True
        self.csv_path = None
        self._ultimo_resultado = None
        self._lookup_cache = {}
        # A migração injeta seu _log, que ESPELHA cada linha em _imp_atual.log_lines
        # (o "relatório da entidade"). Sem esta lista, _inserir_produtos/_financeiro
        # quebram com AttributeError ao logar. Ver JanelaMigracao._log.
        self.log_lines = []
        self._log = log or (lambda *a, **k: None)

    def after(self, delay, func=None, *args, **kwargs):
        return None

    def _set_progresso(self, *a, **k):
        return None

    def _salvar_relatorio(self, *a, **k):
        return None


class ProdutosImportadorHeadless(ProdutosImportMixin, MapeamentoDBMixin, _ImportadorHeadless):
    pass


class ClientesImportadorHeadless(ClientesImportMixin, MapeamentoDBMixin, _ImportadorHeadless):
    pass


class FinanceiroImportadorHeadless(FinanceiroImportMixin, MapeamentoDBMixin, _ImportadorHeadless):
    pass
