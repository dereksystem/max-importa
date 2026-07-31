import customtkinter as ctk
from tkinter import filedialog, messagebox, ttk, simpledialog
import pandas as pd
import pyodbc
import logging
import threading
from datetime import datetime
import os
import sys
import re
from PIL import Image as PILImage

import mi_arquivo   # leitura resiliente de arquivos (xlsx + autodetecção de encoding)
import mi_perfis    # perfis de mapeamento de colunas por layout de arquivo
import mi_multiloja # empresas (config) e visibilidade por loja (empresaFiltro)

# ── Config, cores, cripto e credenciais (extraídos para mi_config.py) ──────────
from mi_config import (
    APP_VERSION,
    MD_RED, MD_RED_HOV, MD_GRAY, MD_GRAY_HOV,
    TC_TEXT_MAIN, TC_FIELD_OBL_BG, TC_FIELD_OBL_TXT,
    TC_FIELD_KEY_BG, TC_FIELD_KEY_TXT, TC_STATUS_OK,
    _resource_path, _get_log_dir, _set_log_dir, _DEFAULT_LOG_DIR,
    _get_conexao, _set_conexao, _dpapi_encrypt, _dpapi_decrypt,
)

_LOGO_PATH = _resource_path("logo_maxdata.png")

def _logo_label(parent, height=50):
    try:
        img = PILImage.open(_LOGO_PATH)
        ratio = img.width / img.height
        w = int(height * ratio)
        ctkimg = ctk.CTkImage(light_image=img, dark_image=img, size=(w, height))
        lbl = ctk.CTkLabel(parent, image=ctkimg, text="")
        lbl._logo_img = ctkimg
        return lbl
    except Exception:
        return ctk.CTkLabel(parent, text="MaxData",
                            font=ctk.CTkFont(size=18, weight="bold"),
                            text_color=MD_RED)

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

# ── Tema "Clean Corporate" — sobrescreve as SUPERFICIES do CustomTkinter ───────
# Sem isso, janela/cards/inputs ficariam no cinza padrao do tema "blue"; aqui eles
# passam a ser pagina clara + cards brancos (e equivalentes no escuro). Roda no
# import, ANTES de qualquer janela ser criada, entao vale para todos os widgets.
_CC_PAGE  = ["#F7F8FA", "#16181C"]   # fundo da janela
_CC_CARD  = ["#FFFFFF", "#1D2025"]   # cards / frames de conteudo
_CC_SUTIL = ["#F0F2F5", "#20242A"]   # superficie sutil
_CC_BORDA = ["#E3E6EA", "#2E323A"]   # bordas
_CC_INPUT = ["#FFFFFF", "#24272D"]   # inputs / combos
_CC_TXT   = ["#1A1D21", "#E6E8EB"]   # texto principal
_CC_TXT2  = ["#5B6470", "#8A9099"]   # texto secundario
_CC_GREEN = ["#2E9E6B", "#35B37E"]   # sucesso / marcado
def _aplicar_tema_clean_corporate():
    t = ctk.ThemeManager.theme
    t["CTk"]["fg_color"] = list(_CC_PAGE)
    t["CTkToplevel"]["fg_color"] = list(_CC_PAGE)
    t["CTkFrame"].update(fg_color=list(_CC_CARD), top_fg_color=list(_CC_PAGE),
                         border_color=list(_CC_BORDA))
    t["CTkButton"].update(fg_color=list(MD_RED), hover_color=list(MD_RED_HOV),
                          text_color=["#FFFFFF", "#FFFFFF"])
    t["CTkEntry"].update(fg_color=list(_CC_INPUT), border_color=list(_CC_BORDA),
                         text_color=list(_CC_TXT), placeholder_text_color=list(_CC_TXT2))
    t["CTkComboBox"].update(fg_color=list(_CC_INPUT), border_color=list(_CC_BORDA),
                            button_color=list(_CC_TXT2), button_hover_color=["#454C56", "#6E7680"],
                            text_color=list(_CC_TXT))
    t["CTkOptionMenu"].update(fg_color=list(_CC_INPUT), button_color=list(_CC_TXT2),
                              text_color=list(_CC_TXT))
    t["CTkCheckBox"].update(fg_color=list(_CC_GREEN), hover_color=["#268A5D", "#2E9E6B"],
                            border_color=["#B4BAC2", "#4A505A"], checkmark_color=["#FFFFFF", "#FFFFFF"],
                            text_color=list(_CC_TXT))
    t["CTkTextbox"].update(fg_color=list(_CC_CARD), border_color=list(_CC_BORDA),
                           text_color=list(_CC_TXT))
    t["CTkProgressBar"].update(fg_color=list(_CC_BORDA))
    t["CTkScrollableFrame"].update(label_fg_color=list(_CC_SUTIL))
    t["CTkScrollbar"].update(button_color=["#C4CAD3", "#3A3F47"],
                             button_hover_color=["#AEB6C0", "#4A505A"])
    t["CTkSegmentedButton"].update(fg_color=list(_CC_SUTIL), selected_color=list(MD_RED),
                                   selected_hover_color=list(MD_RED_HOV),
                                   unselected_color=list(_CC_SUTIL), unselected_hover_color=list(_CC_BORDA),
                                   text_color=list(_CC_TXT))
_aplicar_tema_clean_corporate()

# ── Relatórios/export ao final da importação (extraídos para mi_report.py) ─────
from mi_report import (
    _gerar_arquivo_erros, _montar_msg_obrigatorios, _marcar_arquivo_importado,
    _resetar_selecao, _nome_banco, _exportar_resultado, _pos_importacao,
)
# ── Helpers de leitura de células mapeadas e de banco (mixin, mi_db.py) ────────
from mi_db import MapeamentoDBMixin
# ── Lógica da migração banco→banco (mixin, mi_migracao.py) ─────────────────────
from mi_migracao import MigracaoMixin
# ── Lógica de importação por arquivo, por entidade (mixins, mi_importadores.py) ─
from mi_importadores import (
    ProdutosImportMixin, ClientesImportMixin, FinanceiroImportMixin,
    ProdutosImportadorHeadless, ClientesImportadorHeadless, FinanceiroImportadorHeadless,
)
# ── Regras de validação puras da importação (mi_validacao.py) ──────────────────
from mi_validacao import (
    campos_nao_mapeados, validar_obrigatorios, linhas_ao_menos_um, ids_reservados,
)


# ─────────────────────────────────────────────────────────────────────────────
# UTILITÁRIO: Centralizar janela
# ─────────────────────────────────────────────────────────────────────────────
def centralizar(janela, largura, altura):
    # Telas hospedadas no shell são CTkFrame, não janelas: não têm geometry().
    # Em vez de espalhar `if` pelos chamadores, a função vira no-op nesse caso.
    if not hasattr(janela, "geometry"):
        return
    janela.update_idletasks()
    sw = janela.winfo_screenwidth()
    sh = janela.winfo_screenheight()
    x = (sw - largura) // 2
    y = (sh - altura) // 2
    janela.geometry(f"{largura}x{altura}+{x}+{y}")


# ─────────────────────────────────────────────────────────────────────────────
# Cancelamento de operações longas (importação / migração)
# ─────────────────────────────────────────────────────────────────────────────
class CancelavelMixin:
    """Dá às janelas de importação/migração um botão CANCELAR e uma flag
    cooperativa (self._cancelado). As operações rodam em thread daemon e
    checam a flag em pontos SEGUROS:
      - importadores: entre linhas (commit é por linha, nada fica pela metade);
      - migração: entre entidades (a entidade atual termina inteira, mantendo o
        banco consistente e as FKs reabilitadas).
    O botão é criado por _criar_btn_cancelar() e controlado por _op_iniciada()
    / _op_finalizada(). Requer que a janela tenha self._log e (opcionalmente)
    self.btn_cancelar."""

    def _criar_btn_cancelar(self, parent, **pack_kwargs):
        self._cancelado = False
        self.btn_cancelar = ctk.CTkButton(
            parent, text="⏹  Cancelar",
            fg_color=MD_GRAY, hover_color=MD_GRAY_HOV,
            state="disabled", command=self._pedir_cancelamento)
        self.btn_cancelar.pack(**pack_kwargs)
        return self.btn_cancelar

    def _op_iniciada(self):
        """Chamar ANTES de disparar a thread da operação: zera a flag e
        habilita o botão Cancelar."""
        self._cancelado = False
        btn = getattr(self, "btn_cancelar", None)
        if btn is not None:
            btn.configure(state="normal", text="⏹  Cancelar")
        lbl = getattr(self, "lbl_progresso", None)
        if lbl is not None:
            lbl.configure(text="iniciando...")

    def _set_progresso(self, atual, total, contexto=""):
        """Atualiza a barra E o rótulo 'X de Y (NN%)' por registro. Thread-safe:
        agenda a atualização na thread da GUI via self.after."""
        frac = (atual / total) if total else 0.0
        pre  = (contexto + " — ") if contexto else ""
        txt  = f"{pre}{atual} de {total}  ({int(frac * 100)}%)"
        def _upd():
            try:
                self.progress.set(frac)
            except Exception:
                pass
            lbl = getattr(self, "lbl_progresso", None)
            if lbl is not None:
                try:
                    lbl.configure(text=txt)
                except Exception:
                    pass
        try:
            self.after(0, _upd)
        except Exception:
            pass

    def _reset_progresso(self, total=None):
        """Zera a barra e o rótulo no início de uma operação."""
        try:
            self.progress.set(0)
        except Exception:
            pass
        lbl = getattr(self, "lbl_progresso", None)
        if lbl is not None:
            lbl.configure(text=(f"0 de {total}  (0%)" if total else ""))

    def _op_finalizada(self):
        """Chamar ao FIM da operação (mesmo cancelada): desabilita o botão."""
        btn = getattr(self, "btn_cancelar", None)
        if btn is not None:
            self.after(0, lambda: btn.configure(state="disabled", text="⏹  Cancelar"))

    def _pedir_cancelamento(self):
        if getattr(self, "_cancelado", False):
            return
        self._cancelado = True
        # Na migração, a entidade em andamento roda num importador HEADLESS que tem
        # seu PRÓPRIO _cancelado. Sem propagar, o loop dele (ex.: financeiro com 140k
        # linhas) checaria um flag nunca setado e não pararia. Propaga p/ ele parar
        # cooperativamente na próxima linha.
        imp = getattr(self, "_imp_atual", None)
        if imp is not None:
            imp._cancelado = True
        try:
            self._log("⏹️ Cancelamento solicitado — encerrando com segurança "
                      "(o registro/entidade em andamento é concluído)...")
        except Exception:
            pass
        btn = getattr(self, "btn_cancelar", None)
        if btn is not None:
            btn.configure(state="disabled", text="⏹  Cancelando...")

    # ── Feedback visual do mapeamento de colunas ───────────────────────────────
    _IGNORAR_MAP = "[ ignorar ]"
    _ROW_OK_BG = ("#EAF7F0", "#16291F")   # verde suave (claro, escuro) p/ linha mapeada

    # ── Estados da linha de mapeamento — layout 1b aprovado ────────────────────
    # (fundo, borda) em tuplas (claro, escuro). Ativado por tela via _LAYOUT_1B,
    # para as telas ainda não convertidas seguirem com o visual antigo.
    _L1B_MAPEADO = (("#EAF7F0", "#16291F"), ("#CDEBDC", "#24503C"))
    _L1B_FALTA   = (("#FDECEC", "#2A1A1A"), ("#F6D6D6", "#5A2E2E"))
    _L1B_CHAVE   = (("#FBEEEC", "#2A1E1C"), ("#F3D9D5", "#5A3A36"))
    _L1B_NEUTRO  = (("#FFFFFF", "#1B1E24"), ("#E3E6EA", "#2A2E36"))
    _L1B_AMBAR   = (("#FFF7ED", "#3A2E1C"), ("#F5E0BE", "#5A4A2C"))

    def _pintar_linha_1b(self, campo, linha, mapeado, e_obrig):
        """Aplica fundo + borda do estado, conforme a especificação do layout."""
        if campo == getattr(self, "CAMPO_CHAVE", None) and not mapeado:
            fundo, borda = self._L1B_CHAVE
        elif not mapeado and campo in (getattr(self, "CAMPOS_INTERATIVOS", ()) or ()):
            fundo, borda = self._L1B_AMBAR     # preenchimento assistido (Clientes)
        elif mapeado:
            fundo, borda = self._L1B_MAPEADO
        elif e_obrig:
            fundo, borda = self._L1B_FALTA
        else:
            fundo, borda = self._L1B_NEUTRO
        try:
            linha.configure(fg_color=fundo, border_color=borda, border_width=1)
        except Exception:
            pass

    # ── Multi-loja ────────────────────────────────────────────────────────
    def _selecionar_empresas(self, is_insert=True, conn=None):
        """Pergunta em quais lojas a importação vale. Devolve:
             lista de empId  → seguir com essa seleção
             None            → banco de UMA loja (nada a perguntar, segue igual)
             False           → o usuário cancelou

        A marcação significa coisas DIFERENTES por operação, e o texto da janela diz
        qual: no INSERT define onde o registro vai APARECER (grava o `empresaFiltro`);
        no UPDATE define em quais lojas os DADOS mudam.

        `conn` é obrigatório em quem não tem `self.conn` — a JanelaMigracao, por
        exemplo, só abre a conexão do DESTINO dentro do `_migrar`."""
        alvo = conn if conn is not None else getattr(self, "conn", None)
        if alvo is None:
            raise RuntimeError(
                "_selecionar_empresas precisa de uma conexão: esta tela não tem "
                "self.conn, então passe conn= explicitamente.")
        try:
            empresas = mi_multiloja.listar_empresas(alvo.cursor())
        except Exception as e:
            self._log(f"⚠️  Não foi possível ler a tabela config: {str(e)[:150]}")
            return None
        if len(empresas) <= 1:
            return None

        dlg = ctk.CTkToplevel(self)
        dlg.title("Banco multi-loja")
        dlg.resizable(False, False)
        centralizar(dlg, 620, 190 + 34 * len(empresas))
        dlg.transient(self.winfo_toplevel())
        dlg.grab_set()

        resultado = {"ok": False}
        cab = ctk.CTkFrame(dlg, fg_color="transparent")
        cab.pack(fill="x", padx=20, pady=(16, 6))
        ctk.CTkLabel(cab, text="🏬  Este banco tem mais de uma empresa",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(
            cab, justify="left", text_color=MD_GRAY, font=ctk.CTkFont(size=11),
            text=("Marque as lojas em que os registros devem APARECER.\n"
                  "Os dados são gravados em todas as empresas; a marcação define a "
                  "visibilidade (empresaFiltro)."
                  if is_insert else
                  "Marque as lojas em que os DADOS devem ser alterados.\n"
                  "A visibilidade já configurada (empresaFiltro) não é alterada."),
        ).pack(anchor="w", pady=(4, 0))

        corpo = ctk.CTkScrollableFrame(dlg, fg_color=("#FFFFFF", "#1B1E24"), height=34 * len(empresas))
        corpo.pack(fill="both", expand=True, padx=20, pady=8)

        hdr = ctk.CTkFrame(corpo, fg_color="transparent")
        hdr.pack(fill="x")
        for txt, w in (("SELECIONAR", 100), ("ID EMPRESA", 110), ("NOME DA EMPRESA", 300)):
            ctk.CTkLabel(hdr, text=txt, width=w, anchor="w",
                         font=ctk.CTkFont(size=10, weight="bold"),
                         text_color="#A2A9B2").pack(side="left", padx=4)

        vars_emp = {}

        def _linha(var, id_txt, nome, cmd=None):
            fr = ctk.CTkFrame(corpo, fg_color="transparent")
            fr.pack(fill="x", pady=1)
            ctk.CTkCheckBox(fr, text="", variable=var, width=100,
                            command=cmd).pack(side="left", padx=4)
            ctk.CTkLabel(fr, text=id_txt, width=110, anchor="w",
                         font=ctk.CTkFont(size=12)).pack(side="left", padx=4)
            ctk.CTkLabel(fr, text=nome, width=300, anchor="w",
                         font=ctk.CTkFont(size=12)).pack(side="left", padx=4)

        var_todas = ctk.BooleanVar(value=True)

        def _alternar_todas():
            for v in vars_emp.values():
                v.set(var_todas.get())

        def _revisar_todas(*_):
            var_todas.set(all(v.get() for v in vars_emp.values()))

        _linha(var_todas, "TODAS", "TODAS AS EMPRESAS", _alternar_todas)
        for emp in empresas:
            v = ctk.BooleanVar(value=True)
            vars_emp[emp["cofId"]] = v
            _linha(v, str(emp["cofId"]), emp["cofEmpFantasia"], _revisar_todas)

        rod = ctk.CTkFrame(dlg, fg_color="transparent")
        rod.pack(fill="x", padx=20, pady=(4, 16))

        def _confirmar():
            if not any(v.get() for v in vars_emp.values()):
                messagebox.showwarning("Nenhuma empresa",
                                       "Marque ao menos uma empresa.", parent=dlg)
                return
            resultado["ok"] = True
            dlg.destroy()

        ctk.CTkButton(rod, text="Continuar", width=130, height=34, fg_color=MD_RED,
                      hover_color=MD_RED_HOV, corner_radius=9,
                      command=_confirmar).pack(side="left")
        ctk.CTkButton(rod, text="Cancelar", width=110, height=34, fg_color="transparent",
                      border_width=1, text_color=TC_TEXT_MAIN, corner_radius=9,
                      command=dlg.destroy).pack(side="left", padx=(8, 0))

        dlg.wait_window()
        if not resultado["ok"]:
            return False
        return [cof for cof, v in vars_emp.items() if v.get()]

    def _aplicar_selecao_empresas(self, is_insert=True):
        """Roda o diálogo multi-loja e guarda a escolha em `self.empresas_alvo`.

        Devolve False quando o usuário cancelou (o chamador deve abortar). Em banco de
        uma loja não pergunta nada, zera a seleção e segue — comportamento idêntico ao
        de antes do multi-loja."""
        escolha = self._selecionar_empresas(is_insert=is_insert)
        if escolha is False:
            self._log("Importação cancelada na seleção de empresas.")
            return False
        self.empresas_alvo = escolha        # None em banco de uma loja
        if escolha:
            self._log(f"🏬 Empresas selecionadas: {escolha}")
        return True

    def _obrigatorios_efetivos(self):
        """Conjunto de campos realmente obrigatórios para a operação da tela.

        No **INSERT** vale o `CAMPOS_OBRIGATORIOS` completo — a linha está sendo
        criada do zero e o banco exige esses campos.
        No **UPDATE** só a CHAVE (`CAMPO_CHAVE`: proId / cliId) é obrigatória: o
        registro já existe, e um campo não mapeado — ou com a célula vazia — apenas
        fica de fora do SET, preservando o que está no banco.

        Usado tanto pela pintura do mapeamento quanto pelos selos, para que a tela
        não marque como "FALTA" um campo que a importação não vai exigir."""
        todos = getattr(self, "CAMPOS_OBRIGATORIOS", ()) or ()
        if "INSERT" in getattr(self, "_operacao", "INSERT"):
            return set(todos)
        chave = getattr(self, "CAMPO_CHAVE", None)
        return {chave} if chave else set()

    def _atualizar_status_mapeamento(self, *_):
        """Atualiza o indicador (✓/✗/—) de cada campo do mapeamento e o rótulo de
        resumo ('X/Y campos mapeados' + aviso se faltam obrigatórios). Chamado pelo
        `command` de cada combobox e após o auto-mapeamento em _carregar_colunas.
        Usa self.mapping_vars, self.map_status (por campo), self.lbl_map_resumo e
        self.CAMPOS_OBRIGATORIOS — tudo opcional (getattr), então é seguro."""
        vars_ = getattr(self, "mapping_vars", None)
        if not vars_:
            return
        obrigatorios = self._obrigatorios_efetivos()
        status = getattr(self, "map_status", {}) or {}
        rows = getattr(self, "map_rows", {}) or {}       # frame de cada linha
        bgs = getattr(self, "map_row_bg", {}) or {}       # cor original de cada linha
        mapeados = 0
        obrig_faltando = []
        for campo, var in vars_.items():
            val = var.get()
            ok = bool(val) and val != self._IGNORAR_MAP
            e_obrig = campo in obrigatorios
            if ok:
                mapeados += 1
            elif e_obrig:
                obrig_faltando.append(campo)
            lbl = status.get(campo)
            if lbl is not None:
                if ok:
                    lbl.configure(text="✓", text_color=TC_STATUS_OK)
                elif e_obrig:
                    lbl.configure(text="✗", text_color="#FF5252")
                else:
                    lbl.configure(text="—", text_color="gray")
            # linha inteira: verde suave quando mapeada; cor original caso contrário
            linha = rows.get(campo)
            if linha is not None:
                if getattr(self, "_LAYOUT_1B", False):
                    self._pintar_linha_1b(campo, linha, ok, e_obrig)
                    selo = (getattr(self, "map_badge", {}) or {}).get(campo)
                    if selo is not None:
                        try:
                            if ok:
                                selo.pack_forget()
                            elif not selo.winfo_ismapped():
                                selo.pack(side="left", padx=(8, 0))
                        except Exception:
                            pass
                else:
                    try:
                        linha.configure(fg_color=self._ROW_OK_BG if ok
                                        else bgs.get(campo, "transparent"))
                    except Exception:
                        pass
        total = len(vars_)

        # Contador de obrigatórios + barra de progresso (rodapé do layout 1b)
        barra = getattr(self, "map_barra", None)
        lbl_cont = getattr(self, "map_contador", None)
        if barra is not None or lbl_cont is not None:
            n_obrig = len([c for c in vars_ if c in obrigatorios])
            ok_obrig = n_obrig - len(obrig_faltando)
            if lbl_cont is not None:
                lbl_cont.configure(text=f"Obrigatórios: {ok_obrig} de {n_obrig}")
            if barra is not None:
                try:
                    barra.set((ok_obrig / n_obrig) if n_obrig else 0)
                    barra.configure(progress_color=TC_STATUS_OK if not obrig_faltando
                                    else MD_RED)
                except Exception:
                    pass

        resumo = getattr(self, "lbl_map_resumo", None)
        if resumo is None:
            return
        if obrig_faltando:
            resumo.configure(
                text=(f"⚠  {mapeados}/{total} campos mapeados — faltam obrigatórios: "
                      + ", ".join(sorted(obrig_faltando))),
                text_color=("#B00000", "#FF6B6B"))
        elif mapeados == 0:
            resumo.configure(
                text="Nenhum campo mapeado ainda — selecione as colunas do arquivo.",
                text_color=MD_GRAY)
        else:
            resumo.configure(
                text=f"✓  {mapeados}/{total} campos mapeados — todos os obrigatórios OK.",
                text_color=TC_STATUS_OK)

    # ── Barra de ações padronizada (layout 1b) ──────────────────────────────
    def _criar_barra_acoes(self, parent, com_acerto=False):
        """Rodapé de ação das 3 telas de importação, criado num lugar só para as
        telas ficarem idênticas por construção — antes cada uma montava a sua e a
        ordem divergia (o 'Simular' aparecia no meio numa e no fim das outras).

        Ordem: ação primária → Simular (modifica o que a primária faz, então fica
        colada nela) → Cancelar → [Acerto de Estoque]. O 'Voltar' vai para a ponta
        OPOSTA: é navegação, não ação sobre os dados, e não deve ficar ao lado de
        um clique que grava."""
        bot = ctk.CTkFrame(parent, fg_color="transparent")
        bot.pack(padx=24, pady=(10, 4), fill="x")

        self.btn_import = ctk.CTkButton(
            bot, text="🚀  INICIAR IMPORTAÇÃO", height=48, corner_radius=9,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=MD_RED, hover_color=MD_RED_HOV,
            state="disabled", command=self._iniciar)
        self.btn_import.pack(side="left", padx=(0, 10))

        self.simular_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            bot, text="🔎 Simular (não grava)", variable=self.simular_var,
            font=ctk.CTkFont(size=12), checkbox_width=18, checkbox_height=18,
            onvalue=True, offvalue=False).pack(side="left", padx=(0, 18))

        self._criar_btn_cancelar(bot, side="left", padx=(0, 10))
        self.btn_cancelar.configure(height=48, corner_radius=9,
                                    font=ctk.CTkFont(size=13, weight="bold"))

        if com_acerto:
            self.btn_acerto = ctk.CTkButton(
                bot, text="📦  Gerar Acerto de Estoque", height=48, corner_radius=9,
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color=MD_GRAY, hover_color=MD_GRAY_HOV,
                state="disabled", command=self._gerar_acerto_estoque)
            self.btn_acerto.pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            bot, text="↩  Voltar", height=48, width=120, corner_radius=9,
            fg_color="transparent", border_width=1, text_color=TC_TEXT_MAIN,
            hover_color=("#EAECEF", "#242832"),
            command=self._fechar).pack(side="right")
        return bot

    # ── Rodapé fixo das 3 telas (ancorado ao FUNDO) ─────────────────────────
    def _montar_rodape(self, modulo, com_acerto=False):
        """Monta todo o rodapé (contador+barra de obrigatórios, resumo, perfis,
        barra de ação, progresso e log) dentro de um frame ancorado ao FUNDO da
        janela (side="bottom", empacotado ANTES do scroll_map). Assim os botões de
        ação NUNCA saem da tela em resolução baixa (1366×768): o scroll_map preenche
        o espaço acima e ENCOLHE quando falta altura, em vez de empurrar o rodapé
        para fora. Antes, este bloco era duplicado em cada _build e o rodapé era
        empacotado DEPOIS do scroll (top), então era cortado em telas pequenas.

        IMPORTANTE: chame este método ANTES de empacotar o scroll_map, e empacote o
        scroll_map com side="top", fill="both", expand=True logo em seguida."""
        rodape = ctk.CTkFrame(self, fg_color="transparent")
        rodape.pack(side="bottom", fill="x")

        # Linha 1 — estado do mapeamento: contador + barra + resumo NA MESMA LINHA.
        # Eram 2 linhas dizendo a mesma coisa ("Obrigatórios: X de Y" em cima e
        # "X/Y campos mapeados — faltam obrigatórios: …" embaixo); juntar devolve
        # ~40 px de altura ao mapeamento, que é onde o usuário trabalha.
        rod_map = ctk.CTkFrame(rodape, fg_color="transparent")
        rod_map.pack(padx=24, pady=(6, 0), fill="x")
        self.map_contador = ctk.CTkLabel(
            rod_map, text="Obrigatórios: 0 de 0",
            font=ctk.CTkFont(size=12), text_color=("#5B6470", "#C7CCD4"))
        self.map_contador.pack(side="left")
        self.map_barra = ctk.CTkProgressBar(rod_map, width=150, height=7,
                                            corner_radius=999, progress_color=MD_RED,
                                            fg_color=("#EDEFF2", "#2A2E36"))
        self.map_barra.set(0)
        self.map_barra.pack(side="left", padx=(10, 12))
        self.lbl_map_resumo = ctk.CTkLabel(
            rod_map, text="Nenhum campo mapeado ainda — selecione as colunas do arquivo.",
            font=ctk.CTkFont(size=11), text_color=MD_GRAY, anchor="w")
        self.lbl_map_resumo.pack(side="left", fill="x", expand=True)
        self._atualizar_status_mapeamento()   # estado inicial (obrigatórios = ✗)

        self._criar_barra_perfis(rodape, modulo).pack(padx=24, pady=(4, 0), anchor="w")

        self._criar_barra_acoes(rodape, com_acerto=com_acerto)

        # Linha de progresso — barra e rótulo "X de Y (NN%)" lado a lado. O rótulo
        # ficava numa linha própria, ocupando ~35 px mesmo vazio (fora de importação).
        _prog = ctk.CTkFrame(rodape, fg_color="transparent")
        _prog.pack(padx=24, pady=(4, 0), fill="x")
        self.lbl_progresso = ctk.CTkLabel(_prog, text="", font=ctk.CTkFont(size=11),
                                          text_color=MD_GRAY, width=190, anchor="e")
        self.lbl_progresso.pack(side="right", padx=(10, 0))
        self.progress = ctk.CTkProgressBar(_prog, height=10, progress_color=MD_RED)
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress.set(0)

        _log_wrap = ctk.CTkFrame(rodape, fg_color="transparent")
        _log_wrap.pack(padx=24, pady=(6, 10), fill="x")
        # ⚠️ `height=1` é OBRIGATÓRIO nesta barrinha decorativa: CTkFrame sem height
        # nasce com o default de 200 px e `fill="y"` NÃO encolhe abaixo do tamanho
        # requisitado — ela puxava o bloco do log para 250 px (o textbox pede 105),
        # roubando ~145 px do mapeamento. Com height=1 ela só ESTICA até o textbox.
        ctk.CTkFrame(_log_wrap, width=4, height=1, fg_color=MD_RED,
                     corner_radius=0).pack(side="left", fill="y", padx=(0, 6))
        self.text_log = ctk.CTkTextbox(_log_wrap, height=84,
                                        font=ctk.CTkFont(size=11, family="Consolas"))
        self.text_log.pack(side="left", fill="both", expand=True)
        return rodape

    # ── Perfis de mapeamento (salvar/aplicar por layout de arquivo) ──────────
    # O auto-mapeamento só casa nomes IDÊNTICOS; arquivos de terceiros exigem
    # remapear tudo na mão a cada importação. O perfil guarda esse trabalho.
    def _criar_barra_perfis(self, parent, modulo):
        """Barra 'Perfil de mapeamento': combo + Aplicar/Salvar/Excluir.
        `modulo` = PRODUTOS | CLIENTES | FINANCEIRO (namespace no arquivo de perfis)."""
        self._perfil_modulo = modulo
        barra = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkLabel(barra, text="Perfil de mapeamento:",
                     font=ctk.CTkFont(size=11), text_color=MD_GRAY).pack(side="left")
        self.combo_perfil = ctk.CTkComboBox(barra, width=210, state="readonly",
                                            font=ctk.CTkFont(size=11), values=[])
        self.combo_perfil.pack(side="left", padx=(6, 6))
        for txt, cmd, cor in (("Aplicar", self._aplicar_perfil, None),
                              ("Salvar…", self._salvar_perfil, None),
                              ("Excluir", self._excluir_perfil, "#8A1F1F")):
            ctk.CTkButton(barra, text=txt, width=72, height=26,
                          font=ctk.CTkFont(size=11),
                          fg_color=cor or "transparent", border_width=0 if cor else 1,
                          text_color="white" if cor else TC_TEXT_MAIN,
                          command=cmd).pack(side="left", padx=(0, 6))
        self._recarregar_perfis()
        return barra

    def _recarregar_perfis(self):
        combo = getattr(self, "combo_perfil", None)
        if combo is None:
            return
        nomes = mi_perfis.listar(getattr(self, "_perfil_modulo", ""))
        combo.configure(values=nomes or ["(nenhum perfil salvo)"])
        combo.set(nomes[0] if nomes else "(nenhum perfil salvo)")

    def _mapping_atual(self):
        """{campo: coluna} do que está selecionado nos combos agora."""
        return {campo: var.get()
                for campo, var in (getattr(self, "mapping_vars", {}) or {}).items()
                if var.get() and var.get() != self._IGNORAR_MAP}

    def _salvar_perfil(self):
        mapping = self._mapping_atual()
        if not mapping:
            messagebox.showwarning("Perfil", "Nenhum campo mapeado para salvar.",
                                   parent=self)
            return
        nome = simpledialog.askstring("Salvar perfil de mapeamento",
                                      "Nome do perfil (ex.: 'Planilha Contmatic'):",
                                      parent=self)
        if not nome or not nome.strip():
            return
        nome = nome.strip()
        if nome in mi_perfis.listar(self._perfil_modulo) and not messagebox.askyesno(
                "Perfil", f"Já existe um perfil '{nome}'. Sobrescrever?", parent=self):
            return
        if mi_perfis.salvar(self._perfil_modulo, nome, mapping):
            self._recarregar_perfis()
            self.combo_perfil.set(nome)
            self._log(f"💾 Perfil '{nome}' salvo com {len(mapping)} campo(s).")
        else:
            messagebox.showerror("Perfil", "Não foi possível gravar o perfil.", parent=self)

    def _aplicar_perfil(self):
        nome = (getattr(self, "combo_perfil", None) and self.combo_perfil.get()) or ""
        perfil = mi_perfis.obter(self._perfil_modulo, nome)
        if not perfil:
            messagebox.showwarning("Perfil", "Selecione um perfil salvo.", parent=self)
            return
        if getattr(self, "df", None) is None:
            messagebox.showwarning("Perfil", "Carregue o arquivo antes de aplicar o perfil.",
                                   parent=self)
            return
        aplicaveis, ausentes = mi_perfis.aplicavel(perfil, list(self.df.columns))
        for campo, var in (getattr(self, "mapping_vars", {}) or {}).items():
            if campo in aplicaveis:
                var.set(aplicaveis[campo])
        self._atualizar_status_mapeamento()
        self._log(f"📋 Perfil '{nome}' aplicado — {len(aplicaveis)} campo(s) mapeado(s).")
        if ausentes:
            det = ", ".join(f"{c}→'{col}'" for c, col in list(ausentes.items())[:8])
            self._log(f"⚠️  {len(ausentes)} campo(s) do perfil não existem neste arquivo "
                      f"(layout mudou): {det}")
            messagebox.showwarning(
                "Perfil aplicado parcialmente",
                f"{len(aplicaveis)} campo(s) mapeado(s).\n\n"
                f"{len(ausentes)} coluna(s) do perfil NÃO existem neste arquivo:\n"
                + "\n".join(f"  • {c} → '{col}'" for c, col in list(ausentes.items())[:12]),
                parent=self)

    def _excluir_perfil(self):
        nome = (getattr(self, "combo_perfil", None) and self.combo_perfil.get()) or ""
        if not mi_perfis.obter(self._perfil_modulo, nome):
            return
        if messagebox.askyesno("Perfil", f"Excluir o perfil '{nome}'?", parent=self):
            mi_perfis.excluir(self._perfil_modulo, nome)
            self._recarregar_perfis()
            self._log(f"🗑️ Perfil '{nome}' excluído.")


def garantir_pasta_logs(parent):
    """Na inicialização: se a pasta de logs configurada (padrão = ao lado do .exe,
    ex.: C:\\Max\\MaxImporta\\Log) ainda NÃO existir, PERGUNTA ao usuário se deseja
    criá-la. Se sim, cria e grava o caminho no max_importa.ini (passa a persistir).
    Se não, apenas avisa que dá para configurar depois. Retorna o caminho garantido
    ou None se o usuário recusou / houve erro."""
    log_dir = _get_log_dir()
    if os.path.isdir(log_dir):
        return log_dir
    criar = messagebox.askyesno(
        "Pasta de logs não encontrada",
        "A pasta onde os logs e relatórios de importação serão salvos ainda não "
        f"existe:\n\n{log_dir}\n\nDeseja criá-la agora?",
        parent=parent)
    if not criar:
        messagebox.showinfo(
            "Pasta de logs",
            "Nenhuma pasta foi criada. Você pode definir/criar a pasta a qualquer "
            "momento em \"Configurar pasta de logs\", no menu principal.",
            parent=parent)
        return None
    try:
        _set_log_dir(log_dir)   # cria a pasta e grava o caminho no .ini
        return log_dir
    except Exception as e:
        messagebox.showerror(
            "Erro ao criar pasta",
            f"Não foi possível criar a pasta de logs:\n{log_dir}\n\n{e}",
            parent=parent)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# JANELA 1 – Login / Conexão com SQL Server
# ─────────────────────────────────────────────────────────────────────────────
class JanelaLogin(ctk.CTk):
    # Padroes NAO-sensiveis. A senha NAO fica embutida no binario (segurança):
    # começa vazia e é digitada pelo usuário (ou lembrada, cifrada via DPAPI).
    _DEFAULT_SERVER = "localhost\\SQLEXPRESS"
    _DEFAULT_USER   = "sa"

    def __init__(self):
        super().__init__()
        self.title(f"Max_Importa  v{APP_VERSION}")
        self.resizable(False, True)
        centralizar(self, 520, 585)

        self.base_conn_str = None
        self.conn          = None
        self.current_db    = None

        # Carrega credenciais salvas (se houver); senão, usa os padrões.
        cx = _get_conexao()
        self._servidor = cx["servidor"] or self._DEFAULT_SERVER
        self._usuario  = cx["usuario"]  or self._DEFAULT_USER
        self._auth     = cx["auth"] if cx["auth"] in ("sql", "windows") else "sql"
        self._senha    = cx["senha"]
        self._lembrar  = cx["lembrar"]
        self._build()
        # Pergunta (uma vez, na abertura) se deve criar a pasta de logs quando ela
        # não existir — ex.: primeiro uso após instalar em C:\Max\MaxImporta.
        garantir_pasta_logs(self)

    def _identidade_txt(self):
        """Texto exibido no rótulo 'Usuario' conforme o modo de autenticação."""
        return "Windows (integrada)" if self._auth == "windows" else self._usuario

    def _montar_base_conn_str(self):
        """Monta a connection string base (sem DATABASE) conforme o modo de auth.
        Reutilizada por todas as janelas via self.base_conn_str."""
        s = ("DRIVER={ODBC Driver 17 for SQL Server};"
             f"SERVER={self._servidor};")
        if self._auth == "windows":
            s += "Trusted_Connection=yes;"
        else:
            s += f"UID={self._usuario};PWD={self._senha};"
        s += "TrustServerCertificate=yes;"
        return s

    def _build(self):
        # Layout 1b: fundo de canvas + cabeçalho com título forte (23/800)
        self.configure(fg_color=("#E9EBEF", "#16181C"))
        _logo_label(self, height=60).pack(pady=(26, 2))
        ctk.CTkLabel(self, text="Importador MaxManager",
                     font=ctk.CTkFont(size=13),
                     text_color=("#5B6470", "#C7CCD4")).pack(pady=(2, 0))
        ctk.CTkLabel(self, text=f"VERSÃO {APP_VERSION}",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     text_color=("#A2A9B2", "#6B7480")).pack(pady=(2, 18))

        # Secao 1: info de conexao
        frame1 = ctk.CTkFrame(self, corner_radius=12,
                              fg_color=("#FFFFFF", "#1B1E24"), border_width=1,
                              border_color=("#E3E6EA", "#2A2E36"))
        frame1.pack(padx=40, pady=(0, 10), fill="x")

        hdr = ctk.CTkFrame(frame1, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(12, 6))
        ctk.CTkLabel(hdr, text="CONEXÃO COM SQL SERVER",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=("#A2A9B2", "#6B7480")).pack(side="left")
        ctk.CTkButton(hdr, text="Editar credenciais", corner_radius=8,
                       width=160, height=30, font=ctk.CTkFont(size=11),
                       fg_color="transparent", border_width=1, text_color=TC_TEXT_MAIN,
                       hover_color=("#EAECEF", "#242832"),
                       command=self._editar_credenciais).pack(side="right")

        info = ctk.CTkFrame(frame1, fg_color="transparent")
        info.pack(fill="x", padx=20, pady=(0, 6))
        ctk.CTkLabel(info, text="Servidor:", font=ctk.CTkFont(size=11),
                     text_color="gray", width=70).pack(side="left")
        self.lbl_servidor = ctk.CTkLabel(info, text=self._servidor,
                                          font=ctk.CTkFont(size=11), text_color=TC_TEXT_MAIN)
        self.lbl_servidor.pack(side="left", padx=(4, 20))
        ctk.CTkLabel(info, text="Usuario:", font=ctk.CTkFont(size=11),
                     text_color="gray", width=60).pack(side="left")
        self.lbl_usuario = ctk.CTkLabel(info, text=self._identidade_txt(),
                                         font=ctk.CTkFont(size=11), text_color=TC_TEXT_MAIN)
        self.lbl_usuario.pack(side="left", padx=(4, 0))

        self.btn_connect = ctk.CTkButton(
            frame1, text="Conectar e Listar Bancos",
            width=440, height=44, corner_radius=9,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=MD_RED, hover_color=MD_RED_HOV,
            command=self._conectar)
        self.btn_connect.pack(padx=20, pady=(8, 14))


        # Secao 2: banco
        frame2 = ctk.CTkFrame(self, corner_radius=12,
                              fg_color=("#FFFFFF", "#1B1E24"), border_width=1,
                              border_color=("#E3E6EA", "#2A2E36"))
        frame2.pack(padx=40, pady=(8, 10), fill="x")

        ctk.CTkLabel(frame2, text="SELECIONAR BANCO DE DADOS",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=("#A2A9B2", "#6B7480")).pack(anchor="w", padx=20, pady=(12, 6))
        ctk.CTkLabel(frame2, text="Banco disponivel na instancia",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(anchor="w", padx=20)
        self.combo_db = ctk.CTkComboBox(frame2, width=440, state="readonly",
                                         values=["[ conecte primeiro ]"])
        self.combo_db.pack(padx=20, pady=(2, 14))

        # Só aparece DEPOIS de conectar/validar as credenciais (via
        # _mostrar_btn_confirmar); por isso não é empacotado aqui.
        self.btn_confirm = ctk.CTkButton(
            self, text="✔  Confirmar Banco e Avançar",
            width=440, height=48, corner_radius=9,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=MD_RED, hover_color=MD_RED_HOV,
            command=self._confirmar)

        # Status no padrão do layout: bolinha + texto (igual ao rodapé da sidebar)
        self._frm_status = ctk.CTkFrame(self, fg_color="transparent")
        self._frm_status.pack(pady=(6, 16))
        _st = self._frm_status
        self.lbl_status_dot = ctk.CTkLabel(_st, text="●", font=ctk.CTkFont(size=13),
                                           text_color=("#A2A9B2", "#6B7480"))
        self.lbl_status_dot.pack(side="left", padx=(0, 6))
        self.lbl_status = ctk.CTkLabel(_st, text="Aguardando conexão...",
                                        font=ctk.CTkFont(size=12),
                                        text_color=("#5B6470", "#C7CCD4"))
        self.lbl_status.pack(side="left")

    def _status(self, texto, cor):
        """Atualiza o texto do status e a bolinha junto — verde quando conectado."""
        self.lbl_status.configure(text=texto, text_color=cor)
        try:
            self.lbl_status_dot.configure(text_color=cor)
        except Exception:
            pass

    def _mostrar_btn_confirmar(self, mostrar: bool):
        """Exibe ou oculta o botão 'Confirmar Banco e Avançar'. Ele só surge
        após a conexão ser validada (bancos listados) e some ao trocar
        credenciais ou em falha de conexão."""
        if mostrar:
            if not self.btn_confirm.winfo_ismapped():
                # 'before' precisa referenciar um IRMÃO na ordem de pack da janela.
                # O lbl_status vive dentro de _frm_status, então referenciá-lo aqui
                # fazia o botão não aparecer.
                self.btn_confirm.pack(padx=40, pady=(8, 4), before=self._frm_status)
        else:
            self.btn_confirm.pack_forget()

    def _editar_credenciais(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Editar Credenciais")
        dlg.resizable(False, False)
        centralizar(dlg, 470, 470)
        dlg.grab_set()

        ctk.CTkLabel(dlg, text="Editar Credenciais de Conexao",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(18, 10))

        frm = ctk.CTkFrame(dlg, fg_color="transparent")
        frm.pack(padx=30, fill="x")

        ctk.CTkLabel(frm, text="Instancia do Servidor",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(anchor="w")
        e_srv = ctk.CTkEntry(frm, width=400)
        e_srv.insert(0, self._servidor)
        e_srv.pack(pady=(2, 8))

        # Modo de autenticação
        ctk.CTkLabel(frm, text="Autenticacao",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(anchor="w")
        seg_auth = ctk.CTkSegmentedButton(frm, values=["SQL Server", "Windows"])
        seg_auth.set("Windows" if self._auth == "windows" else "SQL Server")
        seg_auth.pack(pady=(2, 8), anchor="w")

        ctk.CTkLabel(frm, text="Usuario",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(anchor="w")
        e_usr = ctk.CTkEntry(frm, width=400)
        e_usr.insert(0, self._usuario)
        e_usr.pack(pady=(2, 8))

        ctk.CTkLabel(frm, text="Senha",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(anchor="w")
        e_pwd = ctk.CTkEntry(frm, width=400, show="*")
        e_pwd.insert(0, self._senha)
        e_pwd.pack(pady=(2, 8))

        # Lembrar credenciais (senha cifrada via DPAPI)
        var_lembrar = ctk.BooleanVar(value=self._lembrar)
        chk_lembrar = ctk.CTkCheckBox(
            frm, text="Lembrar credenciais nesta maquina (senha criptografada)",
            variable=var_lembrar, font=ctk.CTkFont(size=11))
        chk_lembrar.pack(anchor="w", pady=(4, 2))

        def _aplicar_modo(_=None):
            """Habilita/desabilita usuário e senha conforme o modo de auth."""
            if seg_auth.get() == "Windows":
                e_usr.configure(state="disabled")
                e_pwd.configure(state="disabled")
            else:
                e_usr.configure(state="normal")
                e_pwd.configure(state="normal")
        seg_auth.configure(command=_aplicar_modo)
        _aplicar_modo()

        def salvar():
            self._auth = "windows" if seg_auth.get() == "Windows" else "sql"
            self._servidor = e_srv.get().strip() or self._servidor
            if self._auth == "sql":
                self._usuario = e_usr.get().strip() or self._usuario
                self._senha   = e_pwd.get()
            self._lembrar = bool(var_lembrar.get())
            # Persiste (ou limpa) no .ini conforme "lembrar"
            _set_conexao(self._servidor, self._usuario, self._auth,
                         self._senha, self._lembrar)
            self.lbl_servidor.configure(text=self._servidor)
            self.lbl_usuario.configure(text=self._identidade_txt())
            self.combo_db.configure(values=["[ conecte primeiro ]"])
            self.combo_db.set("[ conecte primeiro ]")
            self._mostrar_btn_confirmar(False)
            self._status("Credenciais alteradas — conecte novamente.",
                         ("#8A6D3B", "#E0C48A"))
            dlg.destroy()

        ctk.CTkButton(dlg, text="✔  Salvar", width=400, height=38,
                       fg_color=MD_RED, hover_color=MD_RED_HOV,
                       command=salvar).pack(pady=(6, 10))

    def _conectar(self):
        if not self._servidor:
            messagebox.showwarning("Atencao",
                "Informe a instancia do servidor em Editar credenciais.", parent=self)
            return
        if self._auth == "sql" and (not self._usuario or not self._senha):
            messagebox.showwarning("Atencao",
                "Autenticacao SQL Server exige usuario e senha.\n"
                "Preencha em 'Editar credenciais' (ou use Autenticacao do Windows).",
                parent=self)
            return
        try:
            self.base_conn_str = self._montar_base_conn_str()
            conn = pyodbc.connect(self.base_conn_str, timeout=8)
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sys.databases "
                "WHERE state_desc = 'ONLINE' "
                "AND name NOT IN ('master','tempdb','model','msdb') "
                "ORDER BY name"
            )
            bancos = [r[0] for r in cur.fetchall()]
            conn.close()
            if not bancos:
                self._mostrar_btn_confirmar(False)
                messagebox.showinfo("Info", "Nenhum banco encontrado.", parent=self)
                return
            self.combo_db.configure(values=bancos)
            self.combo_db.set(bancos[0])
            # Credenciais validadas → agora sim exibe o botão de avançar.
            self._mostrar_btn_confirmar(True)
            self._status(f"Conectado como '{self._identidade_txt()}' — selecione o banco.",
                         TC_STATUS_OK)
        except Exception as e:
            self._mostrar_btn_confirmar(False)
            messagebox.showerror("Erro de Conexao", str(e), parent=self)
            self._status("Falha na conexão", MD_RED)

    def _confirmar(self):
        db = self.combo_db.get()
        if not db or db == "[ conecte primeiro ]":
            return
        try:
            self.conn = pyodbc.connect(self.base_conn_str + f"DATABASE={db};")
            self.current_db = db
            self._status(f"Conectado: {db}", TC_STATUS_OK)
            self.withdraw()
            JanelaShell(self).mainloop_child()
        except Exception as e:
            messagebox.showerror("Erro", str(e), parent=self)


class JanelaMenu(ctk.CTkToplevel):
    def __init__(self, login_win: JanelaLogin):
        super().__init__(login_win)
        self.login_win = login_win
        self.title(f"Max_Importa – Menu Principal  v{APP_VERSION}")
        self.resizable(False, False)
        centralizar(self, 740, 580)
        self.protocol("WM_DELETE_WINDOW", self._fechar)
        self._tema_escuro = (ctk.get_appearance_mode() == "Dark")
        self._build()

    def mainloop_child(self):
        self.wait_window()

    def _build(self):
        # ── Cabeçalho: logo + botão de tema ──────────────────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=24, pady=(16, 2))
        _logo_label(hdr, height=50).pack(side="left")

        ctk.CTkLabel(self, text="Selecione o Módulo de Importação",
                     font=ctk.CTkFont(size=15, weight="bold")).pack(pady=(6, 2))
        _db_bar = ctk.CTkFrame(self, fg_color="transparent")
        _db_bar.pack(pady=(0, 14))
        ctk.CTkLabel(_db_bar, text=f" \U0001f5c4  {self.login_win.current_db} ",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     fg_color=MD_GRAY, text_color="white",
                     corner_radius=6).pack()

        # ── Duas colunas ──────────────────────────────────────────────────
        cols = ctk.CTkFrame(self, fg_color="transparent")
        cols.pack(padx=24, fill="x")

        # ── Coluna ESQUERDA — ATUALIZAR ───────────────────────────────────
        frm_upd = ctk.CTkFrame(cols, corner_radius=12)
        frm_upd.pack(side="left", fill="both", expand=True, padx=(0, 8))

        ctk.CTkLabel(frm_upd, text="◄  ATUALIZAR",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=MD_GRAY).pack(pady=(16, 1))
        ctk.CTkLabel(frm_upd, text="Atualiza registros existentes",
                     font=ctk.CTkFont(size=10), text_color="gray").pack()
        ctk.CTkFrame(frm_upd, height=2, fg_color=MD_GRAY).pack(
            fill="x", padx=16, pady=(10, 12))

        for texto, cmd in [
            ("📦  Produtos  →",           self._abrir_produtos_upd),
            ("👥  Clientes / Forn.  →",   self._abrir_clientes_upd),
        ]:
            ctk.CTkButton(frm_upd, text=texto, width=240, height=48,
                           font=ctk.CTkFont(size=13),
                           fg_color=MD_GRAY, hover_color=MD_GRAY_HOV,
                           command=cmd).pack(pady=5, padx=16)

        ctk.CTkButton(frm_upd, text="💰  Financeiro", width=240, height=48,
                       font=ctk.CTkFont(size=13),
                       fg_color="transparent", border_width=1, text_color=TC_TEXT_MAIN,
                       state="disabled").pack(pady=5, padx=16)
        ctk.CTkLabel(frm_upd, text="Somente INSERT",
                     font=ctk.CTkFont(size=9), text_color="gray").pack(pady=(0, 16))

        # ── Coluna DIREITA — INSERIR ──────────────────────────────────────
        frm_ins = ctk.CTkFrame(cols, corner_radius=12)
        frm_ins.pack(side="left", fill="both", expand=True, padx=(8, 0))

        ctk.CTkLabel(frm_ins, text="INSERIR  ►",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=MD_RED).pack(pady=(16, 1))
        ctk.CTkLabel(frm_ins, text="Insere novos registros",
                     font=ctk.CTkFont(size=10), text_color="gray").pack()
        ctk.CTkFrame(frm_ins, height=2, fg_color=MD_RED).pack(
            fill="x", padx=16, pady=(10, 12))

        for texto, cmd in [
            ("📦  Produtos  →",           self._abrir_produtos_ins),
            ("👥  Clientes / Forn.  →",   self._abrir_clientes_ins),
            ("💰  Financeiro  →",         self._abrir_financeiro),
        ]:
            ctk.CTkButton(frm_ins, text=texto, width=240, height=48,
                           font=ctk.CTkFont(size=13),
                           fg_color=MD_RED, hover_color=MD_RED_HOV,
                           command=cmd).pack(pady=5, padx=16)
        ctk.CTkLabel(frm_ins, text="").pack(pady=(0, 16))  # alinha altura

        # ── Migração entre bancos ─────────────────────────────────────────
        ctk.CTkButton(self, text="🔄  Migração entre Bancos MaxData",
                       width=460, height=40, font=ctk.CTkFont(size=13, weight="bold"),
                       fg_color=MD_GRAY, hover_color=MD_GRAY_HOV,
                       command=self._abrir_migracao).pack(pady=(14, 0))

        # ── Configurar pasta de logs ──────────────────────────────────────
        ctk.CTkButton(self, text="⚙  Configurar pasta de logs",
                       width=460, height=30, font=ctk.CTkFont(size=11),
                       fg_color="transparent", border_width=1, text_color=TC_TEXT_MAIN,
                       command=self._configurar_logs).pack(pady=(10, 0))

        # ── Voltar + Tema ─────────────────────────────────────────────────
        _bot = ctk.CTkFrame(self, fg_color="transparent")
        _bot.pack(pady=(16, 14))
        ctk.CTkButton(_bot, text="↩  Voltar / Trocar Banco", width=320, height=36,
                       fg_color="transparent", border_width=1, text_color=TC_TEXT_MAIN,
                       command=self._fechar).pack(side="left", padx=(0, 8))
        self.btn_tema = ctk.CTkButton(
            _bot,
            text="\U0001f319  Escuro" if not self._tema_escuro else "☀️  Claro",
            width=130, height=36, font=ctk.CTkFont(size=11),
            fg_color="transparent", border_width=1, text_color=TC_TEXT_MAIN,
            command=self._toggle_tema)
        self.btn_tema.pack(side="left")

    def _toggle_tema(self):
        self._tema_escuro = not self._tema_escuro
        ctk.set_appearance_mode("Dark" if self._tema_escuro else "Light")
        self.btn_tema.configure(
            text="☀️  Claro" if self._tema_escuro else "🌙  Escuro"
        )

    def _configurar_logs(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Configurar Pasta de Logs")
        dlg.resizable(False, False)
        centralizar(dlg, 540, 240)
        dlg.grab_set()

        ctk.CTkLabel(dlg, text="Pasta de Logs e Relatórios",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(20, 2))
        ctk.CTkLabel(dlg, text="Todos os arquivos .log e .txt serão salvos nesta pasta.",
                     font=ctk.CTkFont(size=11), text_color="gray").pack()

        _frm = ctk.CTkFrame(dlg, fg_color="transparent")
        _frm.pack(padx=24, pady=(12, 4), fill="x")

        e_path = ctk.CTkEntry(_frm, width=400, font=ctk.CTkFont(size=11))
        e_path.insert(0, _get_log_dir())
        e_path.pack(side="left", padx=(0, 8))

        def _browse():
            pasta = filedialog.askdirectory(parent=dlg, initialdir=_get_log_dir())
            if pasta:
                e_path.delete(0, "end")
                e_path.insert(0, pasta)

        ctk.CTkButton(_frm, text="📂", width=44, height=32,
                       fg_color=MD_GRAY, hover_color=MD_GRAY_HOV,
                       command=_browse).pack(side="left")

        def _salvar():
            pasta = e_path.get().strip()
            if not pasta:
                messagebox.showwarning("Atenção", "Informe uma pasta válida.", parent=dlg)
                return
            if not os.path.isdir(pasta):
                if not messagebox.askyesno(
                        "Criar pasta?",
                        f"A pasta abaixo ainda não existe:\n\n{pasta}\n\nDeseja criá-la?",
                        parent=dlg):
                    return
            _set_log_dir(pasta)
            dlg.destroy()
            messagebox.showinfo("Configuração salva",
                                f"Pasta de logs definida para:\n{pasta}", parent=self)

        def _restaurar():
            e_path.delete(0, "end")
            e_path.insert(0, _DEFAULT_LOG_DIR)

        ctk.CTkButton(dlg, text="✔  Salvar", width=490, height=38,
                       fg_color=MD_RED, hover_color=MD_RED_HOV,
                       command=_salvar).pack(padx=24, pady=(8, 4))
        ctk.CTkButton(dlg, text="↺  Restaurar caminho padrão  (" + _DEFAULT_LOG_DIR + ")",
                       width=490, height=30, font=ctk.CTkFont(size=10),
                       fg_color="transparent", border_width=1, text_color=TC_TEXT_MAIN,
                       command=_restaurar).pack(padx=24, pady=(0, 16))

    def _abrir_produtos_upd(self):
        self.withdraw()
        JanelaProdutos(self, operacao_inicial="ATUALIZAR (UPDATE)")

    def _abrir_produtos_ins(self):
        self.withdraw()
        JanelaProdutos(self, operacao_inicial="INSERIR (INSERT)")

    def _abrir_clientes_upd(self):
        self.withdraw()
        JanelaClientes(self, operacao_inicial="ATUALIZAR (UPDATE)")

    def _abrir_clientes_ins(self):
        self.withdraw()
        JanelaClientes(self, operacao_inicial="INSERIR (INSERT)")

    def _abrir_financeiro(self):
        self.withdraw()
        JanelaFinanceiro(self)

    def _abrir_migracao(self):
        if not getattr(self.login_win, "base_conn_str", None):
            messagebox.showwarning("Atenção",
                "Conexão não disponível. Volte ao login e conecte novamente.", parent=self)
            return
        self.withdraw()
        JanelaMigracao(self)

    def _fechar(self):
        self.login_win.deiconify()
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# JANELA 3 – Importação de Produtos
# ─────────────────────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════════
# SHELL — janela única com sidebar fixa (layout 1b aprovado), FASE 1.
#
# Antes: cada módulo era um CTkToplevel próprio e a navegação acontecia por
# withdraw()/deiconify() entre janelas. Agora existe UMA janela; os módulos são
# frames montados na área de conteúdo.
#
# Para não reescrever as ~2.800 linhas das telas nesta fase, `TelaHospedada`
# absorve as chamadas que só existem em janela (title/resizable/protocol/...).
# Assim o código das telas segue idêntico — `self.title(...)` passa a alimentar o
# cabeçalho do shell — e a mudança fica contida na camada de navegação.
# ═══════════════════════════════════════════════════════════════════════════
class TelaHospedada:
    """Compatibiliza um CTkFrame com o código escrito para CTkToplevel."""

    def title(self, texto=None):
        if texto is None:
            return getattr(self, "_titulo_tela", "")
        self._titulo_tela = texto
        shell = getattr(self, "menu_win", None)
        if shell is not None and hasattr(shell, "definir_titulo"):
            shell.definir_titulo(texto)
        return None

    # Sem efeito num frame — a janela é do shell.
    def resizable(self, *a, **k):
        return None

    def protocol(self, *a, **k):
        return None

    def iconbitmap(self, *a, **k):
        return None

    def wm_attributes(self, *a, **k):
        return None

    def attributes(self, *a, **k):
        return None

    def withdraw(self):
        return None

    def deiconify(self):
        return None

    def transient(self, *a, **k):
        return None

    def grab_set(self):
        return None

    def grab_release(self):
        return None


class JanelaShell(ctk.CTkToplevel):
    """Janela única: sidebar fixa à esquerda + cabeçalho + área de conteúdo.
    Substitui o antigo JanelaMenu, preservando TODAS as suas ações."""

    LARG_SIDEBAR = 236

    # (chave, rótulo, ícone textual, grupo, aceita Inserir/Atualizar)
    ITENS = [
        ("produtos",   "Produtos",    "📦", "IMPORTAR",    True),
        ("clientes",   "Clientes",    "👥", "IMPORTAR",    True),
        ("financeiro", "Financeiro",  "💰", "IMPORTAR",    False),
        ("migracao",   "Migração",    "🔄", "FERRAMENTAS", False),
    ]

    def __init__(self, login_win):
        super().__init__(login_win)
        self.login_win = login_win
        self.conn = login_win.conn
        self.title(f"Max_Importa  v{APP_VERSION}")
        self.resizable(True, True)
        # Abre MAXIMIZADA e se adapta a qualquer resolução: 'zoomed' faz o próprio
        # Windows ajustar ao monitor (inclusive troca de monitor/DPI), sem depender
        # de tamanho fixo. A geometria abaixo é só o fallback de quando o usuário
        # restaura a janela, e o minsize evita encolher além do utilizável — com a
        # sidebar ocupando 236 px, o conteúdo precisa de mais largura que as antigas
        # janelas soltas (980 px).
        self.update_idletasks()
        _lp = min(1460, max(1100, self.winfo_screenwidth() - 120))
        _ap = min(880, max(700, self.winfo_screenheight() - 140))
        centralizar(self, _lp, _ap)
        self.minsize(1024, 640)
        self.after(0, self._maximizar)
        self.protocol("WM_DELETE_WINDOW", self._fechar)

        self._tela_atual = None
        self._chave_atual = None
        self._operacao = "INSERIR (INSERT)"
        self._nav_btns = {}

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_area()
        self.ir_para("inicio")

    # ── Sidebar ────────────────────────────────────────────────────────────
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=self.LARG_SIDEBAR, corner_radius=0,
                          fg_color=("#F7F8FA", "#1B1E24"))
        sb.grid(row=0, column=0, sticky="nsw")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(90, weight=1)      # empurra o rodapé p/ baixo

        topo = ctk.CTkFrame(sb, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=18, pady=(20, 14))
        _logo_label(topo, height=34).pack(anchor="w")

        linha = 1
        grupo_atual = None
        for chave, rotulo, icone, grupo, _op in self.ITENS:
            if grupo != grupo_atual:
                grupo_atual = grupo
                ctk.CTkLabel(sb, text=grupo, font=ctk.CTkFont(size=10, weight="bold"),
                             text_color=("#A2A9B2", "#6B7480"),
                             anchor="w").grid(row=linha, column=0, sticky="ew",
                                              padx=18, pady=(14, 4))
                linha += 1
            b = ctk.CTkButton(
                sb, text=f"  {icone}   {rotulo}", anchor="w", height=38,
                corner_radius=8, font=ctk.CTkFont(size=13),
                fg_color="transparent", hover_color=("#EAECEF", "#242832"),
                text_color=("#5B6470", "#C7CCD4"),
                command=lambda c=chave: self.ir_para(c))
            b.grid(row=linha, column=0, sticky="ew", padx=10, pady=1)
            self._nav_btns[chave] = b
            linha += 1

        # Ferramentas auxiliares (antes no menu principal)
        for rotulo, icone, cmd in (("Pasta de logs", "⚙", self._configurar_logs),
                                   ("Alternar tema", "🌗", self._toggle_tema),
                                   ("Sair para o login", "↩", self._fechar)):
            ctk.CTkButton(sb, text=f"  {icone}   {rotulo}", anchor="w", height=34,
                          corner_radius=8, font=ctk.CTkFont(size=12),
                          fg_color="transparent", hover_color=("#EAECEF", "#242832"),
                          text_color=("#8A9099", "#8A9099"),
                          command=cmd).grid(row=linha, column=0, sticky="ew",
                                            padx=10, pady=1)
            linha += 1

        # Rodapé: status da conexão (bolinha + banco), como no layout aprovado
        rod = ctk.CTkFrame(sb, fg_color="transparent")
        rod.grid(row=99, column=0, sticky="ew", padx=18, pady=(10, 16))
        ctk.CTkLabel(rod, text="●", font=ctk.CTkFont(size=13),
                     text_color="#2E9E6B").pack(side="left", padx=(0, 6))
        ctk.CTkLabel(rod, text=getattr(self.login_win, "current_db", "") or "—",
                     font=ctk.CTkFont(size=11),
                     text_color=("#5B6470", "#C7CCD4")).pack(side="left")

    # ── Cabeçalho + conteúdo ───────────────────────────────────────────────
    def _build_area(self):
        area = ctk.CTkFrame(self, fg_color=("#E9EBEF", "#16181C"), corner_radius=0)
        area.grid(row=0, column=1, sticky="nsew")
        area.grid_rowconfigure(1, weight=1)
        area.grid_columnconfigure(0, weight=1)

        cab = ctk.CTkFrame(area, fg_color="transparent")
        cab.grid(row=0, column=0, sticky="ew", padx=24, pady=(18, 6))
        esq = ctk.CTkFrame(cab, fg_color="transparent")
        esq.pack(side="left", anchor="w")
        self.lbl_breadcrumb = ctk.CTkLabel(
            esq, text="MAX_IMPORTA", font=ctk.CTkFont(size=10, weight="bold"),
            text_color=("#A2A9B2", "#6B7480"), anchor="w")
        self.lbl_breadcrumb.pack(anchor="w")
        self.lbl_titulo = ctk.CTkLabel(
            esq, text="Início", font=ctk.CTkFont(size=22, weight="bold"),
            text_color=TC_TEXT_MAIN, anchor="w")
        self.lbl_titulo.pack(anchor="w")

        # Pílula Inserir / Atualizar — só nas telas que aceitam as duas operações
        self.seg_operacao = ctk.CTkSegmentedButton(
            cab, values=["Inserir", "Atualizar"], command=self._trocar_operacao,
            font=ctk.CTkFont(size=12, weight="bold"),
            selected_color=MD_RED, selected_hover_color=MD_RED_HOV)
        self.seg_operacao.set("Inserir")

        self.conteudo = ctk.CTkFrame(area, fg_color="transparent")
        self.conteudo.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.conteudo.grid_rowconfigure(0, weight=1)
        self.conteudo.grid_columnconfigure(0, weight=1)

    def _maximizar(self):
        """Maximiza usando o recurso do próprio sistema. 'zoomed' é o caminho no
        Windows; em outros ambientes cai para o tamanho do monitor. Nunca derruba a
        aplicação se o gerenciador de janelas não suportar."""
        try:
            self.state("zoomed")
            return
        except Exception:
            pass
        try:
            self.attributes("-zoomed", True)      # alguns gerenciadores X11
        except Exception:
            try:
                self.geometry(f"{self.winfo_screenwidth()}x"
                              f"{self.winfo_screenheight()}+0+0")
            except Exception:
                pass

    def definir_titulo(self, texto):
        """Recebe o que a tela passaria para title() e mostra no cabeçalho."""
        limpo = str(texto).replace("Max_Importa", "").lstrip(" –-—")
        limpo = re.sub(r"\s*v\d+\.\d+\.\d+\s*$", "", limpo).strip()
        if hasattr(self, "lbl_titulo"):
            self.lbl_titulo.configure(text=limpo or "Início")

    # ── Navegação ──────────────────────────────────────────────────────────
    def _aceita_operacao(self, chave):
        return next((op for c, _r, _i, _g, op in self.ITENS if c == chave), False)

    def _trocar_operacao(self, valor):
        self._operacao = ("INSERIR (INSERT)" if valor == "Inserir"
                          else "ATUALIZAR (UPDATE)")
        if self._chave_atual in ("produtos", "clientes"):
            self.ir_para(self._chave_atual, manter_operacao=True)

    def ir_para(self, chave, manter_operacao=False):
        """Troca o conteúdo. Destrói a tela anterior (cada uma reconstrói seu
        estado do zero, como acontecia quando eram janelas separadas)."""
        anterior = self._tela_atual
        if anterior is not None:
            try:
                if anterior.winfo_exists():
                    anterior.destroy()
            except Exception:
                pass
        self._tela_atual = None
        self._chave_atual = chave

        for c, b in self._nav_btns.items():
            ativo = (c == chave)
            b.configure(fg_color=MD_RED if ativo else "transparent",
                        text_color="#FFFFFF" if ativo else ("#5B6470", "#C7CCD4"))

        if self._aceita_operacao(chave):
            self.seg_operacao.pack(side="right", anchor="e")
            if not manter_operacao:
                self.seg_operacao.set("Inserir")
                self._operacao = "INSERIR (INSERT)"
        else:
            self.seg_operacao.pack_forget()

        tela = None
        if chave == "inicio":
            tela = self._tela_inicio()
        elif chave == "produtos":
            tela = JanelaProdutos(self, operacao_inicial=self._operacao)
        elif chave == "clientes":
            tela = JanelaClientes(self, operacao_inicial=self._operacao)
        elif chave == "financeiro":
            tela = JanelaFinanceiro(self)
        elif chave == "migracao":
            tela = JanelaMigracao(self)

        if tela is not None:
            tela.grid(row=0, column=0, sticky="nsew")
            self._tela_atual = tela
        if chave == "inicio":
            self.definir_titulo("Início")

    def _tela_inicio(self):
        """Painel inicial: o que a antiga tela de menu explicava, sem os botões
        (a navegação agora vive na sidebar)."""
        f = ctk.CTkFrame(self.conteudo, fg_color=("#FFFFFF", "#1B1E24"),
                         corner_radius=12)
        ctk.CTkLabel(f, text="Selecione um módulo na barra lateral",
                     font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=TC_TEXT_MAIN).pack(padx=28, pady=(30, 6), anchor="w")
        ctk.CTkLabel(
            f, justify="left", anchor="w", wraplength=760,
            font=ctk.CTkFont(size=13), text_color=MD_GRAY,
            text=("📦 Produtos · 👥 Clientes/Fornecedores · 💰 Financeiro — importam "
                  "planilhas .xlsx e arquivos .txt/.csv.\n"
                  "🔄 Migração — copia dados de um banco MaxData para outro.\n\n"
                  "Em Produtos e Clientes, use o seletor Inserir / Atualizar no topo. "
                  "Nas telas de importação há a opção “Simular (não grava)”, que mostra "
                  "o resultado sem tocar no banco.")
        ).pack(padx=28, pady=(0, 24), anchor="w")
        ctk.CTkLabel(f, text=f"Banco conectado: {getattr(self.login_win, 'current_db', '—')}",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=TC_STATUS_OK).pack(padx=28, pady=(0, 28), anchor="w")
        return f

    # ── Ações herdadas do antigo menu ──────────────────────────────────────
    def _toggle_tema(self):
        novo = "dark" if ctk.get_appearance_mode().lower() == "light" else "light"
        ctk.set_appearance_mode(novo)

    def _configurar_logs(self):
        JanelaMenu._configurar_logs(self)

    def mainloop_child(self):
        self.mainloop()

    def _fechar(self):
        self.login_win.deiconify()
        self.destroy()


class JanelaProdutos(ProdutosImportMixin, MapeamentoDBMixin, CancelavelMixin,
                     TelaHospedada, ctk.CTkFrame):

    # ── Layout 1b aprovado (fase 3) ──────────────────────────────────
    _LAYOUT_1B = True
    CAMPO_CHAVE = "proId"        # chave primária do produto

    # Campos obrigatorios — validados antes de iniciar a importacao
    CAMPOS_OBRIGATORIOS = {"proDescricao", "proCodCst2", "proCodigo", "proUn", "ncmCodigoNCM"}
    # FLOAT_NOT_NULL vive em ProdutosImportMixin (mi_importadores), herdado por esta
    # janela e pelo importador headless usado na migração.

    # Campos do mapeamento — obrigatórios PRIMEIRO, depois opcionais
    # Tupla: (campo_db, tabela, descrição, obrigatório)
    CAMPOS_PRODUTO = [
        # ── OBRIGATÓRIOS ──────────────────────────────────────────────────
        ("proId",            "produto",         "ID do produto (chave primária)",  False),  # regra especial
        ("proDescricao",     "produto",         "Descrição do produto",            True),
        ("proCodCst2",       "produto_empresa", "Cód. CST2",                       True),
        ("proCodigo",        "produto_empresa", "Código Interno",                  True),
        ("proUn",            "produto",         "Unidade",                         True),
        ("ncmCodigoNCM",     "proNCM",          "Código NCM",                      True),
        # ── OPCIONAIS ─────────────────────────────────────────────────────
        # ⚠️ A tela separa as seções pela PRIMEIRA tupla com obrigatório=False (fora o
        # proId): um campo opcional no meio do bloco de cima jogaria o cabeçalho
        # "CAMPOS OPCIONAIS" para antes dos obrigatórios que viessem depois. Por isso o
        # CST1 fica aqui, e não colado no CST2 — a lista é ORDENADA por seção.
        # CST1 = origem da mercadoria (0–9, 0 = Nacional); não mapeado entra o padrão 0
        # no INSERT (ver ProdutosImportMixin.CST1_DEFAULT).
        ("proCodCst1",       "produto_empresa", "Cód. CST1 — origem (0 a 9)",      False),
        ("proAplicacao",     "produto",         "Aplicação",                       False),
        ("proBalanca",       "produto",         "Balança (0/1)",                   False),
        ("proMedVenda",      "produto",         "Med. Venda",                      False),
        ("proMultiplo",      "produto",         "Múltiplo",                        False),
        ("proPeso",          "produto",         "Peso",                            False),
        ("proQtdComEntrada", "produto",         "Qtd. com Entrada",                False),
        ("proTipo",          "produto",         "Tipo (P/S)",                      False),
        ("proAtacado",       "produto_empresa", "Preço Atacado",                   False),
        ("proCodCSOSN",      "produto_empresa", "Cód. CSOSN",                      False),
        ("proCusto",         "produto_empresa", "Custo",                           False),
        ("proDesativaProd",  "produto_empresa", "Desativado (-1/0)",               False),
        ("proEstoqueAtual",  "produto_empresa", "Estoque Atual",                   False),
        ("proEstoqueMin",    "produto_empresa", "Estoque Mínimo",                  False),
        ("proLocalizador",   "produto_empresa", "Localizador",                     False),
        ("proPrateleira",    "produto_empresa", "Prateleira",                      False),
        ("proVenda",         "produto_empresa", "Preço Venda",                     False),
        ("pclDescricao",     "produtoClasse",   "Classe do produto",               False),
        ("cesCodigo",        "proCEST",         "Código CEST",                     False),
        ("fabNome",          "fabricante",      "Nome do Fabricante",              False),
        ("gdpNome",          "grupoProd",       "Nome do Grupo",                   False),
        ("sgpNome",          "subGrupoProd",    "Nome do SubGrupo",                False),
        ("cdbCodigo",        "codBarras",       "Codigo EAN / Codigo de Barras",   False),
    ]

    def __init__(self, menu_win: JanelaMenu, operacao_inicial="ATUALIZAR (UPDATE)"):
        # Hospedada no shell: o master é a ÁREA DE CONTEÚDO, mas menu_win
        # segue sendo o shell (login_win, navegação, título do cabeçalho).
        super().__init__(getattr(menu_win, "conteudo", menu_win))
        self.menu_win = menu_win
        self.login_win = menu_win.login_win
        self.conn = self.login_win.conn
        self._operacao = operacao_inicial          # operação definida pelo menu
        self.title(f"Max_Importa – Produtos  [{operacao_inicial.split()[0]}]  v{APP_VERSION}")
        self.resizable(True, True)
        centralizar(self, 960, 720)
        self.protocol("WM_DELETE_WINDOW", self._fechar)

        self.csv_path = None
        self.df = None
        self.mapping = {}
        self.mapping_vars = {}
        self.mapping_widgets = {}
        self.log_lines = []

        self._setup_logging()
        self._build()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build(self):
        # ── Cabeçalho: logo + título + badge de operação ─────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(padx=24, pady=(10, 0), fill="x")
        _logo_label(hdr, height=38).pack(side="left")
        ctk.CTkLabel(hdr, text="📦  Importação de Produtos",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(side="left", padx=(16, 0))

        # Badge da operação — cor vermelha para INSERT, cinza para UPDATE
        _op_cor  = MD_RED  if "INSERT"   in self._operacao else MD_GRAY
        _op_hov  = MD_RED_HOV if "INSERT" in self._operacao else MD_GRAY_HOV
        _op_icon = "►" if "INSERT" in self._operacao else "◄"
        ctk.CTkLabel(hdr,
                     text=f" {_op_icon}  {self._operacao.split('(')[0].strip()} ",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     fg_color=_op_cor, text_color="white",
                     corner_radius=8).pack(side="right", padx=(0, 4))

        _db_bar = ctk.CTkFrame(self, fg_color="transparent")
        _db_bar.pack()
        ctk.CTkLabel(_db_bar, text=f" \U0001f5c4  {self.login_win.current_db} ",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     fg_color=MD_GRAY, text_color="white",
                     corner_radius=6).pack(pady=(2, 0))

        # ── Faixa de arquivo ──────────────────────────────────────────────
        top = ctk.CTkFrame(self)
        top.pack(padx=24, pady=(8, 4), fill="x")

        ctk.CTkLabel(top, text="Arquivo:", font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=0, padx=12, pady=10, sticky="w")
        self.btn_arquivo = ctk.CTkButton(top, text="📂  Selecionar CSV / TXT",
                                          width=220, fg_color=_op_cor, hover_color=_op_hov,
                                          command=self._selecionar_arquivo)
        self.btn_arquivo.grid(row=0, column=1, padx=12, pady=10, sticky="w")

        self.lbl_arquivo = ctk.CTkLabel(top, text="Nenhum arquivo selecionado",
                                         text_color="gray", font=ctk.CTkFont(size=11))
        self.lbl_arquivo.grid(row=0, column=2, padx=12, pady=10, sticky="w")

        # Área de mapeamento (scroll)
        ctk.CTkLabel(self, text="Mapeamento de Colunas",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=24, pady=(4, 0))

        # Empacotado no FIM de _build (após o rodapé fixo) — ver _montar_rodape.
        self.scroll_map = ctk.CTkScrollableFrame(self, height=180)

        # Cabecalho com pack
        hdr_frame = ctk.CTkFrame(self.scroll_map, fg_color="transparent")
        hdr_frame.pack(fill="x", padx=4, pady=(4, 2))
        ctk.CTkLabel(hdr_frame, text="Campo DB / Descricao",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MD_GRAY).pack(side="left", padx=8)
        ctk.CTkLabel(hdr_frame, text="Coluna do Arquivo",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MD_GRAY, width=260).pack(side="right", padx=8)
        ctk.CTkLabel(hdr_frame, text="Tabela",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MD_GRAY, width=120).pack(side="right", padx=4)

        secao_obrig_exibida = False
        secao_opc_exibida   = False
        _alt_idx = 0   # alternância de linhas opcionais

        self.map_status = {}   # indicador ✓/✗/— por campo
        self.map_rows = {}     # frame de cada linha (recolorir quando mapeada)
        self.map_row_bg = {}   # cor original de cada linha
        self.map_badge = {}    # selo "FALTA" por campo (some ao mapear)
        # No UPDATE só o proId é exigido — os demais viram opcionais (a célula
        # vazia mantém o valor do banco). O agrupamento continua, mudam o rótulo
        # da seção e os selos.
        _obrig_ef = self._obrigatorios_efetivos()
        _titulo_sec = ("  ★  CAMPOS OBRIGATÓRIOS"
                       if "INSERT" in self._operacao else
                       "  ★  CAMPOS PRINCIPAIS  (opcionais no UPDATE — vazio mantém o banco)")
        for campo, tabela, descr, obrig in self.CAMPOS_PRODUTO:
            if obrig and not secao_obrig_exibida:
                ctk.CTkFrame(self.scroll_map, height=2, fg_color=MD_RED).pack(
                    fill="x", padx=4, pady=(8, 2))
                ctk.CTkLabel(self.scroll_map, text=_titulo_sec,
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=MD_RED).pack(anchor="w", padx=6, pady=(0, 4))
                secao_obrig_exibida = True

            if not obrig and campo != "proId" and not secao_opc_exibida:
                ctk.CTkFrame(self.scroll_map, height=2, fg_color=MD_GRAY).pack(
                    fill="x", padx=4, pady=(10, 2))
                ctk.CTkLabel(self.scroll_map, text="  CAMPOS OPCIONAIS",
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=MD_GRAY).pack(anchor="w", padx=6, pady=(0, 4))
                secao_opc_exibida = True

            if campo == "proId":
                bg, tc, badge, bc, fw = TC_FIELD_KEY_BG, TC_FIELD_KEY_TXT, " [CHAVE]",        MD_RED,    "bold"
            elif campo in _obrig_ef:
                bg, tc, badge, bc, fw = TC_FIELD_OBL_BG, TC_FIELD_OBL_TXT, " [OBRIGATORIO]", "#FF5252", "bold"
            else:
                _alt_bg = ("#F0F2F5", "#20242A") if _alt_idx % 2 == 0 else "transparent"
                bg, tc, badge, bc, fw = _alt_bg, TC_TEXT_MAIN, "", "gray", "normal"
                _alt_idx += 1

            lf = ctk.CTkFrame(self.scroll_map, fg_color=bg, corner_radius=9,
                              border_width=1, border_color=("#E3E6EA", "#2A2E36"))
            lf.pack(fill="x", padx=4, pady=3)

            var = ctk.StringVar(value="[ ignorar ]")
            self.mapping_vars[campo] = var
            cb = ctk.CTkComboBox(lf, variable=var, width=260,
                                  values=["[ ignorar ]"], state="readonly",
                                  command=self._atualizar_status_mapeamento)
            cb.pack(side="right", padx=8, pady=5)
            self.mapping_widgets[campo] = cb  # referência direta para update de values

            ctk.CTkLabel(lf, text=tabela, font=ctk.CTkFont(size=10),
                         text_color="gray", width=120).pack(side="right", padx=4, pady=5)

            nf = ctk.CTkFrame(lf, fg_color="transparent")
            nf.pack(side="left", padx=8, pady=5)
            st = ctk.CTkLabel(nf, text="—", width=18,
                              font=ctk.CTkFont(size=13, weight="bold"), text_color="gray")
            st.pack(side="left", padx=(0, 4))
            self.map_status[campo] = st
            self.map_rows[campo] = lf
            self.map_row_bg[campo] = lf.cget("fg_color")
            ctk.CTkLabel(nf, text=campo,
                         font=ctk.CTkFont(size=11, weight=fw),
                         text_color=tc).pack(side="left")
            ctk.CTkLabel(nf, text=f"  {descr}",
                         font=ctk.CTkFont(size=10), text_color="gray").pack(side="left")
            if campo == self.CAMPO_CHAVE:
                ctk.CTkLabel(nf, text=" CHAVE ", font=ctk.CTkFont(size=10, weight="bold"),
                             corner_radius=5, fg_color=("#F6DAD5", "#5A3A36"),
                             text_color=("#A93226", "#E8A79E")).pack(side="left", padx=(8, 0))
            elif campo in _obrig_ef:
                # "FALTA" é ESTADO: escondido assim que o campo é mapeado.
                _b = ctk.CTkLabel(nf, text=" FALTA ", font=ctk.CTkFont(size=10, weight="bold"),
                                  corner_radius=5, fg_color=MD_RED, text_color="#FFFFFF")
                _b.pack(side="left", padx=(8, 0))
                self.map_badge[campo] = _b

        # Rodapé fixo (ancorado ao fundo) + o scroll preenche o meio. Empacotar o
        # rodapé ANTES do scroll é o que impede os botões de saírem da tela.
        self._montar_rodape("PRODUTOS", com_acerto=True)
        self.scroll_map.pack(side="top", padx=24, pady=6, fill="both", expand=True)

    # ── Arquivo ───────────────────────────────────────────────────────────
    def _selecionar_arquivo(self):
        path = filedialog.askopenfilename(
            parent=self,
            filetypes=mi_arquivo.FILETYPES
        )
        if not path:
            return
        self.csv_path = path
        self.lbl_arquivo.configure(text=os.path.basename(path), text_color=TC_STATUS_OK)
        self._carregar_colunas()

    def _carregar_colunas(self):
        try:
            self.df, _ = mi_arquivo.ler_arquivo_tabular(self.csv_path, log=self._log)
            cols = ["[ ignorar ]"] + list(self.df.columns)

            # Atualiza todos os comboboxes via referência direta
            for campo, var in self.mapping_vars.items():
                widget = self.mapping_widgets.get(campo)
                if widget:
                    widget.configure(values=cols)
                # Auto-mapeamento por nome igual
                if campo in self.df.columns:
                    var.set(campo)
                else:
                    var.set("[ ignorar ]")

            self.btn_import.configure(state="normal")
            self._atualizar_status_mapeamento()   # reflete o auto-mapeamento
            self._log(f"✅ Arquivo carregado: {os.path.basename(self.csv_path)} "
                      f"({len(self.df)} linhas, {len(self.df.columns)} colunas)")
        except Exception as e:
            messagebox.showerror("Erro ao ler arquivo", str(e), parent=self)

    # ── Importação ────────────────────────────────────────────────────────
    def _iniciar(self):
        if self.df is None:
            messagebox.showwarning("Atencao", "Selecione um arquivo primeiro!", parent=self)
            return

        # Monta mapping campo_db -> coluna_csv
        self.mapping = {}
        for campo, var in self.mapping_vars.items():
            val = var.get()
            if val and val != "[ ignorar ]":
                self.mapping[campo] = val

        operacao  = self._operacao
        is_insert = "INSERT" in operacao

        # ══════════════════════════════════════════════════════════════════
        # MODO UPDATE — proId unico obrigatorio; demais campos opcionais
        # ══════════════════════════════════════════════════════════════════
        if not is_insert:
            if "proId" not in self.mapping:
                messagebox.showerror(
                    "Campo Obrigatorio para UPDATE",
                    "O campo proId precisa estar mapeado para realizar o UPDATE.\n"
                    "Ele e usado para localizar o produto no banco.",
                    parent=self
                )
                return

            # Verifica se ha pelo menos um campo alem do proId para atualizar
            outros = [c for c in self.mapping if c != "proId"]
            if not outros:
                messagebox.showwarning(
                    "Nenhum Campo para Atualizar",
                    "Somente o campo proId esta mapeado.\n\n"
                    "Nao ha nenhuma informacao para atualizar alem da chave.\n"
                    "Mapeie ao menos um campo de dados antes de continuar.",
                    parent=self
                )
                return

            # Nenhuma outra validacao de obrigatorios: no UPDATE, so o proId e
            # exigido. Celula vazia num campo mapeado NAO e erro nem apaga o
            # banco — o campo simplesmente fica de fora do SET daquela linha
            # (ver _montar_set_update em mi_db).
            self._log("Validacao UPDATE OK — apenas proId e obrigatorio.")
            if not self._aplicar_selecao_empresas(is_insert=False):
                return
            self.btn_import.configure(state="disabled")
            self.progress.set(0)
            self._dry_run = bool(self.simular_var.get())
            self._op_iniciada()
            threading.Thread(target=self._atualizar_produtos, daemon=True).start()
            return

        # ══════════════════════════════════════════════════════════════════
        # MODO INSERT — campos obrigatorios todos necessarios
        # ══════════════════════════════════════════════════════════════════
        campos_obrig = list(self.CAMPOS_OBRIGATORIOS)
        nao_mapeados = campos_nao_mapeados(self.mapping, campos_obrig)
        if nao_mapeados:
            messagebox.showerror(
                "Campos Obrigatorios Nao Mapeados",
                "Os seguintes campos obrigatorios nao foram mapeados:\n\n" +
                "\n".join("  - " + c for c in sorted(nao_mapeados)) +
                "\n\nMapeie todos os campos obrigatorios antes de importar.",
                parent=self
            )
            return

        self._log("Validando campos obrigatorios em todo o arquivo...")
        invalidos = validar_obrigatorios(self.df, self.mapping, campos_obrig)

        if invalidos:
            descr_map = {campo: descr for campo, _tab, descr, _ob in self.CAMPOS_PRODUTO}
            msg, ep, total_erros, n_linhas = _montar_msg_obrigatorios(
                invalidos, descr_map, "PRODUTOS_VALIDACAO")
            messagebox.showerror("Campos obrigatorios em branco", msg, parent=self)
            self._log(f"Validacao falhou — {total_erros} celula(s) vazia(s) em {n_linhas} linha(s).")
            if ep:
                self._log("Arquivo de erros gerado: " + ep)
            self._salvar_relatorio()
            return

        self._log("Validacao OK — todos os campos obrigatorios preenchidos.")
        if not self._aplicar_selecao_empresas(is_insert=True):
            return
        self.btn_import.configure(state="disabled")
        self.progress.set(0)
        self._dry_run = bool(self.simular_var.get())
        self._op_iniciada()
        threading.Thread(target=self._inserir_produtos, daemon=True).start()
    # ── INSERT ────────────────────────────────────────────────────────────
    def _setup_logging(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        log_dir = _get_log_dir()
        os.makedirs(log_dir, exist_ok=True)
        self._log_file = os.path.join(log_dir, f"LOG_MAX_IMPORTA_{ts}.log")
        self._logger = logging.getLogger(f"produtos_{ts}_{id(self)}")
        self._logger.setLevel(logging.INFO)
        fh = logging.FileHandler(self._log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s", datefmt="%H:%M:%S"))
        self._logger.addHandler(fh)

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        linha = f"{ts} | {msg}"
        self.log_lines.append(linha)
        self._logger.info(msg)
        self.after(0, lambda l=linha: (
            self.text_log.insert("end", l + "\n"),
            self.text_log.see("end")
        ))

    def _salvar_relatorio(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        log_dir = _get_log_dir()
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, f"RELATORIO_MAX_IMPORTA_{ts}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("=== RELATÓRIO FINAL — MAX_IMPORTA ===\n")
            f.write(f"Versao: {APP_VERSION}\n\n")
            for l in self.log_lines:
                f.write(l + "\n")
        self._log(f"📄 Relatório salvo: {path}")

    # ── Acerto de estoque ──────────────────────────────────────────────────
    def _fechar(self):
        self.menu_win.deiconify()
        self.destroy()



# ─────────────────────────────────────────────────────────────────────────────
# JANELA 4 – Importação de Clientes / Fornecedores
# ─────────────────────────────────────────────────────────────────────────────
class JanelaClientes(ClientesImportMixin, MapeamentoDBMixin, CancelavelMixin,
                     TelaHospedada, ctk.CTkFrame):

    # ── Layout 1b aprovado (fase 3) ──────────────────────────────────
    _LAYOUT_1B = True
    CAMPO_CHAVE = "cliId"        # chave primária do cliente

    CAMPOS_OBRIGATORIOS = {
        "cliCpfCgc", "cliFatBairro", "cliFatCep",
        "cliFatCidade", "cliFatCidCodIBGE", "cliFatEnd",
        "cliFatUf", "cliNome"
    }

    # Campos tratados de forma interativa quando vazios (perguntam ao usuario
    # ao iniciar a importacao): NAO bloqueiam a validacao de obrigatorios.
    CAMPOS_INTERATIVOS = {"cliFantasia", "cliRgInsc", "cliFatEndNumero"}

    # (campo_db, tabela, descrição, obrigatório)
    CAMPOS_CLIENTE = [
        # ── OBRIGATÓRIOS ──────────────────────────────────────────────────
        ("cliId",            "cliente", "ID do cliente (chave primária)",  False),  # regra especial
        ("cliCpfCgc",        "cliente", "CPF / CNPJ",                      True),
        ("cliNome",          "cliente", "Razão Social / Nome",             True),
        ("cliFantasia",      "cliente", "Nome Fantasia",                   True),
        ("cliRgInsc",        "cliente", "RG / Insc. Estadual",             True),
        ("cliFatEnd",        "cliente", "Endereço Faturamento",            True),
        ("cliFatEndNumero",  "cliente", "Número",                          True),
        ("cliFatBairro",     "cliente", "Bairro",                          True),
        ("cliFatCidade",     "cliente", "Cidade",                          True),
        ("cliFatCidCodIBGE", "cliente", "Cód. IBGE da Cidade",            True),
        ("cliFatUf",         "cliente", "UF",                              True),
        ("cliFatCep",        "cliente", "CEP",                             True),
        # ── OPCIONAIS ─────────────────────────────────────────────────────
        ("DataInclusao",     "cliente", "Data de Inclusão",                False),
        ("cliDesativa",      "cliente", "Desativado (0/1)",                False),
        ("cliEmail",         "cliente", "E-mail",                          False),
        ("cliFone",          "cliente", "Telefone",                        False),
        ("cliTipoCad",       "cliente", "Tipo de Cadastro",                False),
        ("cliTipo",          "cliente", "Tipo (0=Pessoa Física, 1=Pessoa Jurídica)", False),
    ]

    def __init__(self, menu_win, operacao_inicial="ATUALIZAR (UPDATE)"):
        # Hospedada no shell: o master é a ÁREA DE CONTEÚDO, mas menu_win
        # segue sendo o shell (login_win, navegação, título do cabeçalho).
        super().__init__(getattr(menu_win, "conteudo", menu_win))
        self.menu_win  = menu_win
        self.login_win = menu_win.login_win
        self.conn      = self.login_win.conn
        self._operacao = operacao_inicial
        self.title(f"Max_Importa – Clientes / Forn.  [{operacao_inicial.split()[0]}]  v{APP_VERSION}")
        self.resizable(True, True)
        centralizar(self, 980, 730)
        self.protocol("WM_DELETE_WINDOW", self._fechar)

        self.csv_path    = None
        self.df          = None
        self.mapping     = {}
        self.mapping_vars = {}
        self.log_lines   = []

        self._setup_logging()
        self._build()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build(self):
        # ── Cabeçalho: logo + título + badge de operação ─────────────────
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(padx=24, pady=(10, 0), fill="x")
        _logo_label(hdr, height=38).pack(side="left")
        ctk.CTkLabel(hdr, text="👥  Importação de Clientes / Fornecedores",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(side="left", padx=(16, 0))

        _op_cor = MD_RED  if "INSERT"   in self._operacao else MD_GRAY
        _op_hov = MD_RED_HOV if "INSERT" in self._operacao else MD_GRAY_HOV
        _op_icon = "►" if "INSERT" in self._operacao else "◄"
        ctk.CTkLabel(hdr,
                     text=f" {_op_icon}  {self._operacao.split('(')[0].strip()} ",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     fg_color=_op_cor, text_color="white",
                     corner_radius=8).pack(side="right", padx=(0, 4))

        _db_bar = ctk.CTkFrame(self, fg_color="transparent")
        _db_bar.pack()
        ctk.CTkLabel(_db_bar, text=f" \U0001f5c4  {self.login_win.current_db} ",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     fg_color=MD_GRAY, text_color="white",
                     corner_radius=6).pack(pady=(2, 0))

        # ── Faixa de arquivo ──────────────────────────────────────────────
        top = ctk.CTkFrame(self)
        top.pack(padx=24, pady=(8, 4), fill="x")

        ctk.CTkLabel(top, text="Arquivo:", font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=0, padx=12, pady=10, sticky="w")
        self.btn_arquivo = ctk.CTkButton(top, text="📂  Selecionar CSV / TXT",
                                          width=220, fg_color=_op_cor, hover_color=_op_hov,
                                          command=self._selecionar_arquivo)
        self.btn_arquivo.grid(row=0, column=1, padx=12, pady=10, sticky="w")

        self.lbl_arquivo = ctk.CTkLabel(top, text="Nenhum arquivo selecionado",
                                         text_color="gray", font=ctk.CTkFont(size=11))
        self.lbl_arquivo.grid(row=0, column=2, padx=12, pady=10, sticky="w")

        # Mapeamento
        ctk.CTkLabel(self, text="Mapeamento de Colunas",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=24, pady=(4, 0))

        # Empacotado no FIM de _build (após o rodapé fixo) — ver _montar_rodape.
        self.scroll_map = ctk.CTkScrollableFrame(self, height=180)
        self.scroll_map.columnconfigure(0, weight=1)
        self.scroll_map.columnconfigure(1, weight=0)
        self.scroll_map.columnconfigure(2, weight=0)

        # Cabeçalho
        for txt, col in [("Campo DB / Descrição", 0), ("Tabela", 1), ("Coluna do Arquivo", 2)]:
            ctk.CTkLabel(self.scroll_map, text=txt,
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=MD_GRAY).grid(row=0, column=col, padx=6, pady=(6, 4), sticky="w")

        secao_obrig_ok = False
        secao_opc_ok   = False
        grid_row = 1
        _alt_idx = 0   # alternância de linhas opcionais

        self.map_status = {}   # indicador ✓/✗/— por campo
        self.map_rows = {}     # frame de cada linha (recolorir quando mapeada)
        self.map_row_bg = {}   # cor original de cada linha
        self.map_badge = {}    # selo "FALTA" por campo (some ao mapear)
        # No UPDATE só o cliId é exigido — ver _obrigatorios_efetivos.
        _obrig_ef = self._obrigatorios_efetivos()
        _titulo_sec = ("  ★  CAMPOS OBRIGATÓRIOS"
                       if "INSERT" in self._operacao else
                       "  ★  CAMPOS PRINCIPAIS  (opcionais no UPDATE — vazio mantém o banco)")
        for campo, tabela, descr, obrig in self.CAMPOS_CLIENTE:
            # Separadores de seção
            if campo == "cliId" and not secao_obrig_ok:
                sep = ctk.CTkFrame(self.scroll_map, height=2, fg_color=MD_RED)
                sep.grid(row=grid_row, column=0, columnspan=3, padx=4, pady=(8, 2), sticky="ew")
                grid_row += 1
                ctk.CTkLabel(self.scroll_map, text=_titulo_sec,
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=MD_RED).grid(
                                 row=grid_row, column=0, columnspan=3, padx=6, pady=(0, 4), sticky="w")
                grid_row += 1
                secao_obrig_ok = True

            if not obrig and campo != "cliId" and not secao_opc_ok:
                sep2 = ctk.CTkFrame(self.scroll_map, height=2, fg_color=MD_GRAY)
                sep2.grid(row=grid_row, column=0, columnspan=3, padx=4, pady=(10, 2), sticky="ew")
                grid_row += 1
                ctk.CTkLabel(self.scroll_map, text="  ○  CAMPOS OPCIONAIS",
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=MD_GRAY).grid(
                                 row=grid_row, column=0, columnspan=3, padx=6, pady=(0, 4), sticky="w")
                grid_row += 1
                secao_opc_ok = True

            # Visual por tipo
            if campo == "cliId":
                bg_cor, txt_cor, badge_txt, badge_cor, fw = TC_FIELD_KEY_BG, TC_FIELD_KEY_TXT, " [CHAVE]",        MD_RED,    "bold"
            elif campo in self.CAMPOS_INTERATIVOS:
                bg_cor, txt_cor, badge_txt, badge_cor, fw = TC_FIELD_OBL_BG, TC_FIELD_OBL_TXT, " [AUTO/OPCIONAL]", "#E69500", "bold"
            elif campo in _obrig_ef:
                bg_cor, txt_cor, badge_txt, badge_cor, fw = TC_FIELD_OBL_BG, TC_FIELD_OBL_TXT, " [OBRIGATÓRIO]", "#FF5252", "bold"
            else:
                _alt_bg = ("#F0F2F5", "#20242A") if _alt_idx % 2 == 0 else "transparent"
                bg_cor, txt_cor, badge_txt, badge_cor, fw = _alt_bg, TC_TEXT_MAIN, "", "gray", "normal"
                _alt_idx += 1

            lf = ctk.CTkFrame(self.scroll_map, fg_color=bg_cor, corner_radius=9,
                              border_width=1, border_color=("#E3E6EA", "#2A2E36"))
            lf.grid(row=grid_row, column=0, columnspan=3, padx=4, pady=3, sticky="ew")
            self.scroll_map.columnconfigure(0, weight=1)
            lf.columnconfigure(0, weight=1)
            lf.columnconfigure(1, weight=0)
            lf.columnconfigure(2, weight=0)

            nf = ctk.CTkFrame(lf, fg_color="transparent")
            nf.grid(row=0, column=0, padx=8, pady=5, sticky="w")
            st = ctk.CTkLabel(nf, text="—", width=18,
                              font=ctk.CTkFont(size=13, weight="bold"), text_color="gray")
            st.pack(side="left", padx=(0, 4))
            self.map_status[campo] = st
            self.map_rows[campo] = lf
            self.map_row_bg[campo] = lf.cget("fg_color")
            ctk.CTkLabel(nf, text=campo,
                         font=ctk.CTkFont(size=11, weight=fw),
                         text_color=txt_cor).pack(side="left")
            ctk.CTkLabel(nf, text=f"  {descr}",
                         font=ctk.CTkFont(size=10), text_color="gray").pack(side="left")
            if campo == self.CAMPO_CHAVE:
                ctk.CTkLabel(nf, text=" CHAVE ", font=ctk.CTkFont(size=10, weight="bold"),
                             corner_radius=5, fg_color=("#F6DAD5", "#5A3A36"),
                             text_color=("#A93226", "#E8A79E")).pack(side="left", padx=(8, 0))
            elif campo in self.CAMPOS_INTERATIVOS:
                # Âmbar do layout aprovado: preenchido de forma assistida.
                ctk.CTkLabel(nf, text=" AUTO ", font=ctk.CTkFont(size=10, weight="bold"),
                             corner_radius=5, fg_color=("#FFF7ED", "#3A2E1C"),
                             text_color=("#8A6D3B", "#E0C48A")).pack(side="left", padx=(8, 0))
            elif campo in _obrig_ef:
                _b = ctk.CTkLabel(nf, text=" FALTA ", font=ctk.CTkFont(size=10, weight="bold"),
                                  corner_radius=5, fg_color=MD_RED, text_color="#FFFFFF")
                _b.pack(side="left", padx=(8, 0))
                self.map_badge[campo] = _b

            ctk.CTkLabel(lf, text=tabela,
                         font=ctk.CTkFont(size=10), text_color="gray",
                         width=80).grid(row=0, column=1, padx=8, pady=5, sticky="w")

            var = ctk.StringVar(value="[ ignorar ]")
            self.mapping_vars[campo] = var
            cb = ctk.CTkComboBox(lf, variable=var, width=260,
                                  values=["[ ignorar ]"], state="readonly",
                                  command=self._atualizar_status_mapeamento)
            cb.grid(row=0, column=2, padx=(0, 8), pady=5, sticky="e")
            grid_row += 1

        # Rodapé fixo (ancorado ao fundo) + o scroll preenche o meio. Empacotar o
        # rodapé ANTES do scroll é o que impede os botões de saírem da tela.
        self._montar_rodape("CLIENTES")
        self.scroll_map.pack(side="top", padx=24, pady=6, fill="both", expand=True)

    # ── Arquivo ───────────────────────────────────────────────────────────
    def _selecionar_arquivo(self):
        path = filedialog.askopenfilename(
            parent=self,
            filetypes=mi_arquivo.FILETYPES
        )
        if not path:
            return
        self.csv_path = path
        self.lbl_arquivo.configure(text=os.path.basename(path), text_color=TC_STATUS_OK)
        self._carregar_colunas()

    def _carregar_colunas(self):
        try:
            self.df, _ = mi_arquivo.ler_arquivo_tabular(self.csv_path, log=self._log)
            cols = ["[ ignorar ]"] + list(self.df.columns)
            for campo, var in self.mapping_vars.items():
                for w in self.scroll_map.winfo_children():
                    if isinstance(w, ctk.CTkComboBox):
                        try:
                            if w.cget("variable") is var:
                                w.configure(values=cols)
                        except Exception:
                            pass
                    for child in w.winfo_children():
                        if isinstance(child, ctk.CTkComboBox):
                            try:
                                if child.cget("variable") is var:
                                    child.configure(values=cols)
                            except Exception:
                                pass
                var.set(campo if campo in self.df.columns else "[ ignorar ]")
            # DataInclusao → nome no arquivo pode ser diferente
            if "DataInclusao" not in self.df.columns:
                for col in self.df.columns:
                    if "data" in col.lower() and "incl" in col.lower():
                        self.mapping_vars["DataInclusao"].set(col)
                        break
            self.btn_import.configure(state="normal")
            self._atualizar_status_mapeamento()   # reflete o auto-mapeamento
            self._log(f"✅ Arquivo: {os.path.basename(self.csv_path)} "
                      f"({len(self.df)} linhas, {len(self.df.columns)} colunas)")
        except Exception as e:
            messagebox.showerror("Erro ao ler arquivo", str(e), parent=self)

    # ── Helpers ───────────────────────────────────────────────────────────
    # _calc_cli_tipo foi movido para ClientesImportMixin (mi_importadores.py) — é
    # lógica pura e precisa existir também no importador HEADLESS. JanelaClientes
    # herda ClientesImportMixin, então continua tendo o método por herança.

    # ── Iniciar: validação + dispatch ─────────────────────────────────────
    def _tratar_campos_vazios_clientes(self):
        """Pergunta ao usuario como tratar os campos especiais vazios e
        preenche o dataframe conforme a escolha:
          - cliFantasia vazio  -> usar o Nome ou deixar em branco
          - cliRgInsc vazio    -> se CPF: deixa em branco; se CNPJ: pergunta ISENTO ou branco
          - cliFatEndNumero vazio -> usar 'S/N' ou deixar vazio
        """
        def _vazio(v):
            if v is None:
                return True
            s = str(v).strip()
            return s.upper() in ("", "NULL", "NONE", "NAN")
        def _so_digitos(v):
            return re.sub(r"\D", "", str(v if v is not None else ""))

        df = self.df
        m  = self.mapping

        # 1) cliFantasia vazio -> CPF deixa em branco; CNPJ pergunta repetir Nome/branco
        col_fant = m.get("cliFantasia"); col_nome = m.get("cliNome")
        col_cpf  = m.get("cliCpfCgc")
        if col_fant and col_nome and col_cpf:
            mask_f = df[col_fant].apply(_vazio)
            if int(mask_f.sum()):
                dig_f       = df[col_cpf].apply(_so_digitos)
                mask_cnpj_f = mask_f & (dig_f.str.len() == 14)
                mask_cpf_f  = mask_f & (dig_f.str.len() != 14)
                n_cpf_f  = int(mask_cpf_f.sum())
                n_cnpj_f = int(mask_cnpj_f.sum())
                if n_cpf_f:
                    self._log(f"Fantasia: {n_cpf_f} de CPF mantida(s) em branco (automatico).")
                if n_cnpj_f:
                    if messagebox.askyesno(
                            "Nome Fantasia vazio (CNPJ)",
                            f"{n_cnpj_f} cliente(s) com CNPJ estao com 'Nome Fantasia' vazio.\n\n"
                            "Deseja REPETIR o Nome no campo Fantasia?\n\n"
                            "Sim = usar o Nome    |    Nao = deixar em branco\n\n"
                            "ATENCAO: repetir o Nome no Fantasia (ou quando o cliente ja "
                            "possui um Fantasia proprio) PODE GERAR PROBLEMAS na emissao de "
                            "documentos fiscais no futuro. Recomenda-se CONFERIR esses "
                            "cadastros APOS a importacao.",
                            parent=self):
                        df.loc[mask_cnpj_f, col_fant] = df.loc[mask_cnpj_f, col_nome]
                        self._log(f"Fantasia: {n_cnpj_f} de CNPJ preenchida(s) com o Nome "
                                  f"(CONFERIR apos importacao — risco em documentos fiscais).")
                    else:
                        self._log(f"Fantasia: {n_cnpj_f} de CNPJ mantida(s) em branco.")

        # 2) cliRgInsc vazio -> CPF deixa em branco; CNPJ pergunta ISENTO/branco
        col_rg = m.get("cliRgInsc"); col_cpf = m.get("cliCpfCgc")
        if col_rg and col_cpf:
            mask_rg = df[col_rg].apply(_vazio)
            if int(mask_rg.sum()):
                digitos   = df[col_cpf].apply(_so_digitos)
                mask_cnpj = mask_rg & (digitos.str.len() == 14)
                mask_cpf  = mask_rg & (digitos.str.len() != 14)
                n_cpf  = int(mask_cpf.sum())
                n_cnpj = int(mask_cnpj.sum())
                if n_cpf:
                    self._log(f"RG/Insc: {n_cpf} de CPF mantida(s) em branco (automatico).")
                if n_cnpj:
                    if messagebox.askyesno(
                            "RG/Inscricao vazio (CNPJ)",
                            f"{n_cnpj} cliente(s) com CNPJ estao com 'RG/Inscricao' vazio.\n\n"
                            "Deseja preencher com 'ISENTO'?\n\n"
                            "Sim = ISENTO    |    Nao = deixar em branco",
                            parent=self):
                        df.loc[mask_cnpj, col_rg] = "ISENTO"
                        self._log(f"RG/Insc: {n_cnpj} de CNPJ preenchida(s) com ISENTO.")
                    else:
                        self._log(f"RG/Insc: {n_cnpj} de CNPJ mantida(s) em branco.")

        # 3) cliFatEndNumero vazio -> 'S/N' ou vazio
        col_num = m.get("cliFatEndNumero")
        if col_num:
            mask = df[col_num].apply(_vazio)
            n = int(mask.sum())
            if n:
                if messagebox.askyesno(
                        "Numero do endereco vazio",
                        f"{n} linha(s) estao com 'Numero' do endereco vazio.\n\n"
                        "Deseja preencher com 'S/N'?\n\n"
                        "Sim = S/N    |    Nao = deixar vazio",
                        parent=self):
                    df.loc[mask, col_num] = "S/N"
                    self._log(f"Numero: {n} preenchido(s) com S/N.")
                else:
                    self._log(f"Numero: {n} mantido(s) vazio(s).")

    def _iniciar(self):
        if self.df is None:
            messagebox.showwarning("Atencao", "Selecione um arquivo primeiro!", parent=self)
            return

        # Monta mapping
        self.mapping = {}
        for campo, var in self.mapping_vars.items():
            val = var.get()
            if val and val != "[ ignorar ]":
                self.mapping[campo] = val

        operacao  = self._operacao
        is_insert = "INSERT" in operacao

        # ══════════════════════════════════════════════════════════════════
        # MODO UPDATE — so a CHAVE e obrigatoria; os demais campos sao opcionais
        # ══════════════════════════════════════════════════════════════════
        # A chave e o cliId. Sem ele, cliCpfCgc pode servir de chave alternativa
        # (o _confirmar_update_por_cpf trata esse caminho). Celula vazia num campo
        # mapeado nao e erro: aquele campo fica de fora do SET e o valor atual do
        # banco e preservado (ver _montar_set_update em mi_db).
        if not is_insert:
            if "cliId" not in self.mapping and "cliCpfCgc" not in self.mapping:
                messagebox.showerror(
                    "Campo Obrigatorio para UPDATE",
                    "Para atualizar e preciso mapear o cliId (ou, na falta dele, "
                    "o cliCpfCgc como chave alternativa).\n"
                    "Ele e usado para localizar o cliente no banco.",
                    parent=self
                )
                return

            outros = [c for c in self.mapping if c not in ("cliId", "cliCpfCgc")]
            if not outros:
                messagebox.showwarning(
                    "Nenhum Campo para Atualizar",
                    "Somente a chave esta mapeada.\n\n"
                    "Nao ha nenhuma informacao para atualizar alem dela.\n"
                    "Mapeie ao menos um campo de dados antes de continuar.",
                    parent=self
                )
                return

            self._log("Validacao UPDATE OK — apenas a chave e obrigatoria.")
            if not self._aplicar_selecao_empresas(is_insert=False):
                return
            self._despachar_update_clientes()
            return

        # ── Validação 1: campos obrigatórios mapeados ─────────────────────
        nao_mapeados = campos_nao_mapeados(self.mapping, self.CAMPOS_OBRIGATORIOS)
        if nao_mapeados:
            messagebox.showerror(
                "Campos Obrigatorios Nao Mapeados",
                "Os seguintes campos obrigatorios nao foram mapeados:\n\n" +
                "\n".join("  - " + c for c in sorted(nao_mapeados)) +
                "\n\nMapeie todos antes de importar.",
                parent=self
            )
            return

        # ── Tratamento interativo de campos especiais vazios ──────────────
        # (Fantasia, RG/Insc, Numero do endereco) — pergunta ao usuario e
        # preenche o dataframe antes de validar/importar.
        self._tratar_campos_vazios_clientes()

        # ── Validação 2: dados válidos em todo o arquivo ──────────────────
        self._log("Validando campos obrigatorios no arquivo...")
        invalidos = validar_obrigatorios(self.df, self.mapping, self.CAMPOS_OBRIGATORIOS)

        if invalidos:
            descr_map = {campo: descr for campo, _tab, descr, _ob in self.CAMPOS_CLIENTE}
            msg, ep, total_erros, n_linhas = _montar_msg_obrigatorios(
                invalidos, descr_map, "CLIENTES_VALIDACAO")
            messagebox.showerror("Campos obrigatorios em branco", msg, parent=self)
            self._log(f"Validacao falhou — {total_erros} celula(s) vazia(s) em "
                      f"{n_linhas} linha(s).")
            if ep:
                self._log("Arquivo de erros gerado: " + ep)
            self._salvar_relatorio()
            return

        # ── Validação 3: cliId < 10 reservados ───────────────────────────
        reservados = ids_reservados(self.df, self.mapping, "cliId", limite=10)
        if reservados:
            messagebox.showwarning(
                "IDs Reservados pelo Sistema",
                "Os seguintes cliId sao menores que 10 e estao RESERVADOS pelo sistema:\n\n" +
                "  " + ", ".join(str(x) for x in sorted(set(reservados))) +
                "\n\nRemova ou corrija esses registros antes de importar.",
                parent=self
            )
            self._log("Abortado — cliId reservados encontrados: " +
                      ", ".join(str(x) for x in sorted(set(reservados))))
            return

        self._log("Validacao OK — iniciando INSERT...")

        if not self._aplicar_selecao_empresas(is_insert=True):
            return
        self.btn_import.configure(state="disabled")
        self.progress.set(0)
        self._dry_run = bool(self.simular_var.get())
        self._op_iniciada()
        threading.Thread(target=self._inserir_clientes, daemon=True).start()

    def _despachar_update_clientes(self):
        """Escolhe a chave do UPDATE e dispara o worker: cliId quando o arquivo
        traz IDs de verdade; senao, cai no CPF/CNPJ (com confirmacao)."""
        col_id  = self.mapping.get("cliId")
        tem_ids = False
        if col_id:
            vals = self.df[col_id].dropna().astype(str).str.strip()
            vals = vals[~vals.str.upper().isin(["", "NULL", "NONE", "NAN"])]
            tem_ids = len(vals) > 0

        if not tem_ids:
            # cliId ausente/ignorado — perguntar se usa CPF/CNPJ
            self._confirmar_update_por_cpf()
            return

        self.btn_import.configure(state="disabled")
        self.progress.set(0)
        self._dry_run = bool(self.simular_var.get())
        self._op_iniciada()
        threading.Thread(target=self._atualizar_clientes, daemon=True).start()

    # ── INSERT clientes ───────────────────────────────────────────────────
    def _confirmar_update_por_cpf(self):
        """Exibe dialogo centralizado perguntando se usa cliCpfCgc como chave."""
        if "cliCpfCgc" not in self.mapping:
            messagebox.showerror(
                "Sem chave de atualizacao",
                "O campo cliId nao esta mapeado e cliCpfCgc tambem nao foi mapeado.\n"
                "Mapeie ao menos um dos dois para usar o UPDATE.",
                parent=self
            )
            return

        dlg = ctk.CTkToplevel(self)
        dlg.title("Confirmar modo de atualizacao")
        dlg.resizable(False, False)
        centralizar(dlg, 520, 280)
        dlg.grab_set()

        ctk.CTkLabel(dlg, text="cliId nao mapeado / ignorado",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color="#FFA726").pack(pady=(28, 8))
        ctk.CTkLabel(dlg,
                     text="O campo cliId nao possui informacoes no arquivo.\n"
                          "Deseja localizar os cadastros pelo campo\n"
                          "cliCpfCgc (CPF / CNPJ) para realizar o UPDATE?",
                     font=ctk.CTkFont(size=13), justify="center").pack(pady=(0, 24))

        btn_frame = ctk.CTkFrame(dlg, fg_color="transparent")
        btn_frame.pack()

        def confirmar():
            dlg.destroy()
            self.btn_import.configure(state="disabled")
            self.progress.set(0)
            self._dry_run = bool(self.simular_var.get())
            self._op_iniciada()
            threading.Thread(target=self._atualizar_clientes_por_cpf, daemon=True).start()

        def cancelar():
            dlg.destroy()
            self._log("UPDATE cancelado pelo usuario.")

        ctk.CTkButton(btn_frame, text="Sim, usar CPF/CNPJ",
                       width=210, height=42,
                       font=ctk.CTkFont(size=13, weight="bold"),
                       fg_color="#1a7a3c", hover_color="#145f2e",
                       command=confirmar).pack(side="left", padx=(0, 12))
        ctk.CTkButton(btn_frame, text="Cancelar",
                       width=140, height=42,
                       fg_color="transparent", border_width=1, text_color=TC_TEXT_MAIN,
                       command=cancelar).pack(side="left")

    # ── UPDATE clientes por CPF/CNPJ ──────────────────────────────────────
    def _setup_logging(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        log_dir = _get_log_dir()
        os.makedirs(log_dir, exist_ok=True)
        self._log_file = os.path.join(log_dir, f"LOG_MAX_IMPORTA_CLI_{ts}.log")
        self._logger = logging.getLogger(f"clientes_{ts}_{id(self)}")
        self._logger.setLevel(logging.INFO)
        fh = logging.FileHandler(self._log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s", datefmt="%H:%M:%S"))
        self._logger.addHandler(fh)

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        linha = f"{ts} | {msg}"
        self.log_lines.append(linha)
        self._logger.info(msg)
        self.after(0, lambda l=linha: (
            self.text_log.insert("end", l + "\n"),
            self.text_log.see("end")
        ))

    def _salvar_relatorio(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        log_dir = _get_log_dir()
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, f"RELATORIO_MAX_IMPORTA_CLI_{ts}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("=== RELATÓRIO FINAL — MAX_IMPORTA CLIENTES ===\n")
            f.write(f"Versao: {APP_VERSION}\n\n")
            for l in self.log_lines:
                f.write(l + "\n")
        self._log(f"📄 Relatório salvo: {path}")

    def _fechar(self):
        self.menu_win.deiconify()
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# JANELA 5 – Importação Financeiro (vendaPgto) — somente INSERT
# ─────────────────────────────────────────────────────────────────────────────
class JanelaFinanceiro(FinanceiroImportMixin, MapeamentoDBMixin, CancelavelMixin,
                       TelaHospedada, ctk.CTkFrame):

    # ── Layout 1b aprovado (fase 2): esta tela é a piloto do novo visual ──
    _LAYOUT_1B = True
    CAMPO_CHAVE = "cliCpfCgc"    # documento usado no lookup do cliente

    CAMPOS_OBRIGATORIOS = {
        "cliCpfCgc", "pgtCliNome",
        "pgtValor", "pgtData", "pgtVecmto", "pgtTipoConta", "pgtPago"
    }
    # pgtTipoVista e pgtTipoPrazo aceitam NULL individualmente,
    # mas ao menos um deve ter valor — validado separadamente por linha.
    CAMPOS_VISTA_PRAZO = ("pgtTipoVista", "pgtTipoPrazo")

    # (campo_db, tabela, descrição, obrigatório)
    CAMPOS_FIN = [
        # ── OBRIGATÓRIOS ──────────────────────────────────────────────────
        ("cliCpfCgc",    "cliente",   "CPF/CNPJ — consulta pgtClienteId",  True),
        ("pgtCliNome",   "vendaPgto", "Nome do cliente",                    True),
        ("pgtTipoVista", "vendaPgto", "Tipo Vista — NULL aceito, mas um dos dois é obrigatorio", True),
        ("pgtTipoPrazo", "vendaPgto", "Tipo Prazo — NULL aceito, mas um dos dois é obrigatorio", True),
        ("pgtValor",     "vendaPgto", "Valor decimal(18,5)",                True),
        ("pgtData",      "vendaPgto", "Data do lançamento",                 True),
        ("pgtVecmto",    "vendaPgto", "Data de vencimento",                 True),
        ("pgtTipoConta", "vendaPgto", "Tipo Conta (varchar 1)",             True),
        ("pgtPago",      "vendaPgto", "Situação: S = Concluído / N = Aberto", True),
        # ── OPCIONAIS ─────────────────────────────────────────────────────
        # Multi-loja: cada título é de UMA empresa, informada aqui. Sem o campo (ou com
        # a célula vazia) o título vai para a empresa 1 — ver mi_multiloja.
        ("empId",           "vendaPgto", "Empresa (loja) do título — padrão 1", False),
        ("pgtNumDoc",       "vendaPgto", "Número do documento",             False),
        ("pgtObs",          "vendaPgto", "Observação",                      False),
        ("pgtDataQuitou",   "vendaPgto", "Data de quitação",                False),
        ("pgtNossoNumero",  "vendaPgto", "Nosso Número",                    False),
    ]

    def __init__(self, menu_win):
        # Hospedada no shell: o master é a ÁREA DE CONTEÚDO, mas menu_win
        # segue sendo o shell (login_win, navegação, título do cabeçalho).
        super().__init__(getattr(menu_win, "conteudo", menu_win))
        self.menu_win  = menu_win
        self.login_win = menu_win.login_win
        self.conn      = self.login_win.conn
        self.title(f"Max_Importa – Importação Financeiro (vendaPgto)  v{APP_VERSION}")
        self.resizable(True, True)
        centralizar(self, 980, 730)
        self.protocol("WM_DELETE_WINDOW", self._fechar)

        self.csv_path     = None
        self.df           = None
        self.mapping      = {}
        self.mapping_vars = {}
        self.log_lines    = []
        self.nao_encontrados = []   # linhas cujo CPF/CNPJ não foi localizado

        self._setup_logging()
        self._build()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build(self):
        # Cabeçalho com logo
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(padx=24, pady=(10, 0), fill="x")
        _logo_label(hdr, height=38).pack(side="left")
        ctk.CTkLabel(hdr, text="💰  Importação Financeiro — vendaPgto",
                     font=ctk.CTkFont(size=18, weight="bold")).pack(side="left", padx=(16, 0))
        ctk.CTkLabel(hdr, text=" ►  INSERIR ",
                     font=ctk.CTkFont(size=13, weight="bold"),
                     fg_color=MD_RED, text_color="white",
                     corner_radius=8).pack(side="right", padx=(0, 4))

        _db_bar = ctk.CTkFrame(self, fg_color="transparent")
        _db_bar.pack()
        ctk.CTkLabel(_db_bar, text=f" \U0001f5c4  {self.login_win.current_db} ",
                     font=ctk.CTkFont(size=10, weight="bold"),
                     fg_color=MD_GRAY, text_color="white",
                     corner_radius=6).pack(pady=(2, 0))

        # Topo: arquivo
        top = ctk.CTkFrame(self)
        top.pack(padx=24, pady=10, fill="x")
        ctk.CTkLabel(top, text="Arquivo:", font=ctk.CTkFont(size=12, weight="bold")).grid(
            row=0, column=0, padx=12, pady=10, sticky="w")
        self.btn_arquivo = ctk.CTkButton(top, text="📂  Selecionar CSV / TXT",
                                          width=220, fg_color=MD_RED, hover_color=MD_RED_HOV,
                                          command=self._selecionar_arquivo)
        self.btn_arquivo.grid(row=0, column=1, padx=12, pady=10)
        self.lbl_arquivo = ctk.CTkLabel(top, text="Nenhum arquivo selecionado",
                                         text_color="gray", font=ctk.CTkFont(size=11))
        self.lbl_arquivo.grid(row=1, column=0, columnspan=3, padx=12, pady=(0, 8), sticky="w")

        # Mapeamento
        ctk.CTkLabel(self, text="Mapeamento de Colunas",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w", padx=24, pady=(4, 0))

        # Empacotado no FIM de _build (após o rodapé fixo) — ver _montar_rodape.
        self.scroll_map = ctk.CTkScrollableFrame(self, height=180)
        self.scroll_map.columnconfigure(0, weight=1)

        # Cabeçalho
        for txt, col in [("Campo DB / Descrição", 0), ("Tabela", 1), ("Coluna do Arquivo", 2)]:
            ctk.CTkLabel(self.scroll_map, text=txt,
                         font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=MD_GRAY).grid(
                             row=0, column=col, padx=6, pady=(6, 4), sticky="w")

        secao_obrig_ok = False
        secao_opc_ok   = False
        grid_row = 1
        _alt_idx = 0   # alternância de linhas opcionais

        self.map_status = {}   # indicador ✓/✗/— por campo
        self.map_rows = {}     # frame de cada linha (recolorir quando mapeada)
        self.map_row_bg = {}   # cor original de cada linha
        self.map_badge = {}    # selo "FALTA" por campo (escondido ao mapear)
        for campo, tabela, descr, obrig in self.CAMPOS_FIN:
            if obrig and not secao_obrig_ok:
                sep = ctk.CTkFrame(self.scroll_map, height=2, fg_color=MD_RED)
                sep.grid(row=grid_row, column=0, columnspan=3, padx=4, pady=(8, 2), sticky="ew")
                grid_row += 1
                ctk.CTkLabel(self.scroll_map, text="  ★  CAMPOS OBRIGATÓRIOS",
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=MD_RED).grid(
                                 row=grid_row, column=0, columnspan=3, padx=6, pady=(0, 4), sticky="w")
                grid_row += 1
                secao_obrig_ok = True

            if not obrig and not secao_opc_ok:
                sep2 = ctk.CTkFrame(self.scroll_map, height=2, fg_color=MD_GRAY)
                sep2.grid(row=grid_row, column=0, columnspan=3, padx=4, pady=(10, 2), sticky="ew")
                grid_row += 1
                ctk.CTkLabel(self.scroll_map, text="  ○  CAMPOS OPCIONAIS",
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=MD_GRAY).grid(
                                 row=grid_row, column=0, columnspan=3, padx=6, pady=(0, 4), sticky="w")
                grid_row += 1
                secao_opc_ok = True

            if obrig:
                bg, tc, badge, bc, fw = TC_FIELD_OBL_BG, TC_FIELD_OBL_TXT, " [OBRIGATÓRIO]", "#FF5252", "bold"
            else:
                _alt_bg = ("#F0F2F5", "#20242A") if _alt_idx % 2 == 0 else "transparent"
                bg, tc, badge, bc, fw = _alt_bg, TC_TEXT_MAIN, "", "gray", "normal"
                _alt_idx += 1

            # Layout 1b: raio 9, borda 1px e respiro 9x12 (o estado é pintado
            # por _pintar_linha_1b, chamado no _atualizar_status_mapeamento).
            lf = ctk.CTkFrame(self.scroll_map, fg_color=bg, corner_radius=9,
                              border_width=1, border_color=("#E3E6EA", "#2A2E36"))
            lf.grid(row=grid_row, column=0, columnspan=3, padx=4, pady=3, sticky="ew")
            self.scroll_map.columnconfigure(0, weight=1)
            lf.columnconfigure(0, weight=1)
            lf.columnconfigure(1, weight=0)
            lf.columnconfigure(2, weight=0)

            nf = ctk.CTkFrame(lf, fg_color="transparent")
            nf.grid(row=0, column=0, padx=12, pady=9, sticky="w")
            st = ctk.CTkLabel(nf, text="—", width=18,
                              font=ctk.CTkFont(size=13, weight="bold"), text_color="gray")
            st.pack(side="left", padx=(0, 4))
            self.map_status[campo] = st
            self.map_rows[campo] = lf
            self.map_row_bg[campo] = lf.cget("fg_color")
            ctk.CTkLabel(nf, text=campo,
                         font=ctk.CTkFont(size=12, weight="bold" if obrig else "normal"),
                         text_color=tc).pack(side="left")
            ctk.CTkLabel(nf, text=f"  {descr}",
                         font=ctk.CTkFont(size=11),
                         text_color=("#8A9099", "#8A9099")).pack(side="left")
            # Selo do estado: CHAVE (campo de lookup) ou FALTA (obrigatório vazio)
            if campo == self.CAMPO_CHAVE:
                ctk.CTkLabel(nf, text=" CHAVE ", font=ctk.CTkFont(size=10, weight="bold"),
                             corner_radius=5, fg_color=("#F6DAD5", "#5A3A36"),
                             text_color=("#A93226", "#E8A79E")).pack(side="left", padx=(8, 0))
            elif campo in self.CAMPOS_OBRIGATORIOS:
                # "FALTA" é ESTADO, não rótulo fixo: _atualizar_status_mapeamento
                # esconde o selo assim que o campo é mapeado.
                _b = ctk.CTkLabel(nf, text=" FALTA ", font=ctk.CTkFont(size=10, weight="bold"),
                                  corner_radius=5, fg_color=MD_RED, text_color="#FFFFFF")
                _b.pack(side="left", padx=(8, 0))
                self.map_badge[campo] = _b

            ctk.CTkLabel(lf, text=tabela,
                         font=ctk.CTkFont(size=10), text_color="gray",
                         width=80).grid(row=0, column=1, padx=8, pady=5, sticky="w")

            var = ctk.StringVar(value="[ ignorar ]")
            self.mapping_vars[campo] = var
            cb = ctk.CTkComboBox(lf, variable=var, width=260,
                                  values=["[ ignorar ]"], state="readonly",
                                  command=self._atualizar_status_mapeamento)
            cb.grid(row=0, column=2, padx=(0, 8), pady=5, sticky="e")
            grid_row += 1

        # Rodapé fixo (ancorado ao fundo) + o scroll preenche o meio. Empacotar o
        # rodapé ANTES do scroll é o que impede os botões de saírem da tela.
        self._montar_rodape("FINANCEIRO")
        self.scroll_map.pack(side="top", padx=24, pady=6, fill="both", expand=True)

    # ── Arquivo ───────────────────────────────────────────────────────────
    def _selecionar_arquivo(self):
        path = filedialog.askopenfilename(
            parent=self,
            filetypes=mi_arquivo.FILETYPES
        )
        if not path:
            return
        self.csv_path = path
        self.lbl_arquivo.configure(text=os.path.basename(path), text_color=TC_STATUS_OK)
        self._carregar_colunas()

    def _carregar_colunas(self):
        try:
            self.df, _ = mi_arquivo.ler_arquivo_tabular(self.csv_path, log=self._log)
            cols = ["[ ignorar ]"] + list(self.df.columns)
            for campo, var in self.mapping_vars.items():
                for w in self._iter_comboboxes():
                    try:
                        if w.cget("variable") is var:
                            w.configure(values=cols)
                    except Exception:
                        pass
                var.set(campo if campo in self.df.columns else "[ ignorar ]")
            self.btn_import.configure(state="normal")
            self._atualizar_status_mapeamento()   # reflete o auto-mapeamento
            self._log(f"✅ Arquivo: {os.path.basename(self.csv_path)} "
                      f"({len(self.df)} linhas, {len(self.df.columns)} colunas)")
        except Exception as e:
            messagebox.showerror("Erro ao ler arquivo", str(e), parent=self)

    def _iter_comboboxes(self):
        """Percorre recursivamente todos os CTkComboBox no scroll_map."""
        for w in self.scroll_map.winfo_children():
            if isinstance(w, ctk.CTkComboBox):
                yield w
            for c in w.winfo_children():
                if isinstance(c, ctk.CTkComboBox):
                    yield c
                for gc in c.winfo_children():
                    if isinstance(gc, ctk.CTkComboBox):
                        yield gc

    # ── Helpers ───────────────────────────────────────────────────────────
    # ── Iniciar: validação + dispatch ─────────────────────────────────────
    def _iniciar(self):
        if self.df is None:
            messagebox.showwarning("Atencao", "Selecione um arquivo primeiro!", parent=self)
            return

        # Monta mapping
        self.mapping = {}
        for campo, var in self.mapping_vars.items():
            val = var.get()
            if val and val != "[ ignorar ]":
                self.mapping[campo] = val

        # ── Validação 1: campos obrigatórios mapeados ─────────────────────
        nao_mapeados = campos_nao_mapeados(self.mapping, self.CAMPOS_OBRIGATORIOS)
        if nao_mapeados:
            messagebox.showerror(
                "Campos Obrigatorios Nao Mapeados",
                "Os seguintes campos obrigatorios nao foram mapeados:\n\n" +
                "\n".join("  - " + c for c in sorted(nao_mapeados)) +
                "\n\nMapeie todos antes de importar.",
                parent=self
            )
            return

        # ── Validação 2: dados válidos em todo o arquivo ──────────────────
        self._log("Validando campos obrigatorios no arquivo...")
        invalidos = validar_obrigatorios(self.df, self.mapping, self.CAMPOS_OBRIGATORIOS)

        if invalidos:
            descr_map = {campo: descr for campo, _tab, descr, _ob in self.CAMPOS_FIN}
            msg, ep, total_erros, n_linhas = _montar_msg_obrigatorios(
                invalidos, descr_map, "FINANCEIRO_VALIDACAO")
            messagebox.showerror("Campos obrigatorios em branco", msg, parent=self)
            self._log(f"Validacao falhou — {total_erros} celula(s) vazia(s) em {n_linhas} linha(s).")
            if ep:
                self._log("Arquivo de erros gerado: " + ep)
            self._salvar_relatorio()
            return

        # ── Validação 3: pgtTipoVista e pgtTipoPrazo — ao menos um por linha ──
        erros_vp = linhas_ao_menos_um(self.df, self.mapping, "pgtTipoVista", "pgtTipoPrazo")
        if erros_vp:
            amostra = ", ".join(str(l) for l in erros_vp[:15])
            suf = " ... (+" + str(len(erros_vp) - 15) + " mais)" if len(erros_vp) > 15 else ""
            messagebox.showerror(
                "pgtTipoVista / pgtTipoPrazo Invalidos",
                "Nas linhas abaixo AMBOS pgtTipoVista e pgtTipoPrazo estao vazios.\n"
                "Ao menos um dos dois deve ter valor em cada linha.\n\n"
                "Linhas: " + amostra + suf,
                parent=self
            )
            self._log("Validacao falhou — pgtTipoVista e pgtTipoPrazo ambos vazios em "
                      + str(len(erros_vp)) + " linha(s).")
            return

        if not self._avisar_multiloja_financeiro():
            return

        self._dry_run = bool(self.simular_var.get())
        self._log("Modo SIMULAÇÃO (não grava) — iniciando..." if self._dry_run
                  else "Validacao OK — iniciando importacao...")
        self.btn_import.configure(state="disabled")
        self.progress.set(0)
        self.nao_encontrados = []
        self._op_iniciada()
        threading.Thread(target=self._inserir_financeiro, daemon=True).start()

    def _avisar_multiloja_financeiro(self):
        """No Financeiro não há seleção de lojas: cada título traz o seu `empId`.

        O que existe é um aviso — banco multi-loja com o campo `empId` NÃO mapeado
        significa que TODOS os títulos vão para a empresa 1. Devolve False se o usuário
        preferir cancelar para corrigir o arquivo."""
        try:
            empresas = mi_multiloja.listar_empresas(self.conn.cursor())
        except Exception as e:
            self._log(f"⚠️  Não foi possível ler a tabela config: {str(e)[:150]}")
            return True
        if len(empresas) <= 1 or "empId" in self.mapping:
            return True

        padrao = mi_multiloja.EMP_ID_PADRAO_FINANCEIRO
        lojas = "\n".join(f"    {e['cofId']} — {e['cofEmpFantasia']}" for e in empresas)
        segue = messagebox.askyesno(
            "Banco multi-loja",
            f"Este banco tem {len(empresas)} empresas:\n\n{lojas}\n\n"
            f"O campo 'empId' NAO foi mapeado, entao TODOS os {len(self.df)} titulos "
            f"serao gravados na empresa {padrao}.\n\n"
            "Se o arquivo tem a coluna da loja, cancele e mapeie o campo 'empId'.\n\n"
            "Deseja continuar mesmo assim?",
            parent=self)
        if not segue:
            self._log("Importação cancelada: mapear o campo 'empId' para distribuir "
                      "os títulos entre as lojas.")
            return False
        self._log(f"⚠️  Multi-loja sem 'empId' mapeado — todos os títulos irão para a "
                  f"empresa {padrao} (confirmado pelo usuário).")
        return True

    # ── INSERT vendaPgto ──────────────────────────────────────────────────
    def _aviso_nao_encontrados(self):
        # SNAPSHOT das linhas AGORA: logo após a importação, _pos_importacao chama
        # _resetar_selecao, que zera self.df — mas este diálogo continua aberto e o
        # usuário clica "Salvar" DEPOIS. Sem o snapshot, dava
        # "'NoneType' object has no attribute 'iloc'".
        _df_snapshot = None
        try:
            if getattr(self, "df", None) is not None:
                _idx = sorted({item["_linha"] - 2 for item in self.nao_encontrados})
                _df_snapshot = self.df.iloc[_idx].copy()
        except Exception:
            _df_snapshot = None

        win = ctk.CTkToplevel(self)
        win.title("CPF/CNPJ Não Encontrados")
        win.resizable(True, True)
        centralizar(win, 700, 500)

        ctk.CTkLabel(win,
                     text=f"⚠️  {len(self.nao_encontrados)} linha(s) não inserida(s)",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color="#FF5252").pack(pady=(20, 4))
        ctk.CTkLabel(win,
                     text="Os CPF/CNPJ abaixo não foram encontrados na tabela cliente.",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(pady=(0, 12))

        # Lista
        frame_lista = ctk.CTkScrollableFrame(win, height=280)
        frame_lista.pack(padx=20, fill="both", expand=True)

        ctk.CTkLabel(frame_lista, text=f"{'Linha':>6}   CPF/CNPJ",
                     font=ctk.CTkFont(size=11, weight="bold", family="Consolas"),
                     text_color=MD_RED).pack(anchor="w", padx=6, pady=(4, 2))

        for item in self.nao_encontrados:
            txt = f"{str(item.get('_linha','')):>6}   {item.get('_cpfcnpj','')}"
            ctk.CTkLabel(frame_lista, text=txt,
                         font=ctk.CTkFont(size=11, family="Consolas"),
                         text_color=TC_TEXT_MAIN).pack(anchor="w", padx=6, pady=1)

        # Botões
        bot = ctk.CTkFrame(win, fg_color="transparent")
        bot.pack(padx=20, pady=12, fill="x")

        def salvar_txt():
            path = filedialog.asksaveasfilename(
                parent=win,
                defaultextension=".txt",
                initialfile="nao_inseridos_financeiro.txt",
                filetypes=[("Texto", "*.txt"), ("Todos", "*.*")]
            )
            if not path:
                return
            try:
                # Usa o SNAPSHOT tirado ao abrir o diálogo (self.df já pode ter sido
                # zerado pelo _resetar_selecao). Fallback: reconstrói a partir dos
                # valores já guardados em nao_encontrados (só as colunas mapeadas).
                df_nao = _df_snapshot
                if df_nao is None:
                    df_nao = pd.DataFrame([
                        {k: v for k, v in item.items() if not k.startswith("_")}
                        for item in self.nao_encontrados
                    ])
                df_nao.to_csv(path, sep="\t", index=False, encoding="utf-8")
                messagebox.showinfo("Salvo",
                    f"Arquivo salvo com {len(df_nao)} linha(s) nao inserida(s):\n{path}",
                    parent=win)
                self._log(f"📄 Nao inseridos salvos em: {path}")
            except Exception as e:
                messagebox.showerror("Erro ao salvar", str(e), parent=win)

        ctk.CTkButton(bot, text="💾  Salvar linhas não inseridas (.txt)",
                       height=42, font=ctk.CTkFont(size=13, weight="bold"),
                       fg_color="#1a7a3c", hover_color="#145f2e",
                       command=salvar_txt).pack(side="left", padx=(0, 12))
        ctk.CTkButton(bot, text="Fechar", height=42,
                       fg_color="transparent", border_width=1, text_color=TC_TEXT_MAIN,
                       command=win.destroy).pack(side="left")

    # ── Log / Relatório ───────────────────────────────────────────────────
    def _setup_logging(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        log_dir = _get_log_dir()
        os.makedirs(log_dir, exist_ok=True)
        self._log_file = os.path.join(log_dir, f"LOG_MAX_IMPORTA_FIN_{ts}.log")
        self._logger = logging.getLogger(f"financeiro_{ts}_{id(self)}")
        self._logger.setLevel(logging.INFO)
        fh = logging.FileHandler(self._log_file, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s | %(message)s", datefmt="%H:%M:%S"))
        self._logger.addHandler(fh)

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        linha = f"{ts} | {msg}"
        self.log_lines.append(linha)
        self._logger.info(msg)
        self.after(0, lambda l=linha: (
            self.text_log.insert("end", l + "\n"),
            self.text_log.see("end")
        ))

    def _salvar_relatorio(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        log_dir = _get_log_dir()
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, f"RELATORIO_MAX_IMPORTA_FIN_{ts}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("=== RELATÓRIO FINAL — MAX_IMPORTA FINANCEIRO ===\n")
            f.write(f"Versao: {APP_VERSION}\n\n")
            for l in self.log_lines:
                f.write(l + "\n")
        self._log(f"📄 Relatório salvo: {path}")

    def _fechar(self):
        self.menu_win.deiconify()
        self.destroy()

# ─────────────────────────────────────────────────────────────────────────────
# JANELA 6 – Migração entre Bancos MaxData (banco -> banco)
# ─────────────────────────────────────────────────────────────────────────────
class JanelaMigracao(MigracaoMixin, CancelavelMixin, TelaHospedada, ctk.CTkFrame):
    """Migra dados entre dois bancos MaxData da MESMA instancia SQL, reutilizando
    a logica de INSERT dos importadores (unidade automatica, corte de tamanho,
    etc.). Mantem os IDs (proId/cliId) e pula os que ja existirem no destino."""

    # Os SELECTs na ORIGEM são montados DINAMICAMENTE (ver _sql_*), detectando
    # quais colunas existem no banco de origem — assim funciona mesmo entre
    # versões/schemas diferentes do MaxData (colunas ausentes viram NULL).

    _ROTULOS = {"clientes": "Clientes", "produtos": "Produtos",
                "financeiro": "Financeiro", "permissoes": "Permissões de Usuário",
                "codbarras": "Códigos de Barras"}

    # Ordem fixa da migração (codBarras depois de produtos — FK cdbIdProd->produto)
    _ORDEM = ("clientes", "permissoes", "produtos", "codbarras", "financeiro")

    # Formatação dos totais no resumo final:
    #   chave -> (rótulo, label do 2º número ou None p/ ocultar)
    _TOTAL_FMT = {
        "clientes":   ("👥 Clientes",   "desativados"),
        "permissoes": ("🔐 Permissões", "não inseridas"),
        "produtos":   ("📦 Produtos",   None),
        "codbarras":  ("🏷️ Cód. Barras", "sem produto"),
        "financeiro": ("💰 Financeiro", "não migrados"),
    }

    def __init__(self, menu_win):
        # Hospedada no shell: o master é a ÁREA DE CONTEÚDO, mas menu_win
        # segue sendo o shell (login_win, navegação, título do cabeçalho).
        super().__init__(getattr(menu_win, "conteudo", menu_win))
        self.menu_win      = menu_win
        self.login_win     = menu_win.login_win
        self.base_conn_str = self.login_win.base_conn_str
        self.title(f"Max_Importa – Migração entre Bancos  v{APP_VERSION}")
        self.resizable(True, True)
        centralizar(self, 920, 700)
        self.protocol("WM_DELETE_WINDOW", self._fechar)
        self.log_lines  = []
        self._imp       = {}      # janelas importadoras ocultas (reuso do INSERT)
        self._imp_atual = None    # importadora da entidade em andamento
        self._build()

    # ── UI ─────────────────────────────────────────────────────────────────
    def _build(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=24, pady=(16, 2))
        _logo_label(hdr, height=46).pack(side="left")
        ctk.CTkLabel(self, text="Migração entre Bancos MaxData",
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(6, 0))
        ctk.CTkLabel(self, text="Copia os dados de um banco para outro na mesma instância SQL",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(pady=(0, 10))

        bancos = self._bancos_disponiveis()

        # Origem / Destino
        sel = ctk.CTkFrame(self, corner_radius=12)
        sel.pack(padx=24, pady=(0, 10), fill="x")
        linha = ctk.CTkFrame(sel, fg_color="transparent")
        linha.pack(padx=16, pady=14)
        ctk.CTkLabel(linha, text="Banco de ORIGEM",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MD_GRAY).grid(row=0, column=0, padx=10, sticky="w")
        ctk.CTkLabel(linha, text="",).grid(row=0, column=1)
        ctk.CTkLabel(linha, text="Banco de DESTINO",
                     font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=MD_RED).grid(row=0, column=2, padx=10, sticky="w")
        self.combo_orig = ctk.CTkComboBox(linha, width=320, state="readonly", values=bancos)
        self.combo_orig.grid(row=1, column=0, padx=10)
        ctk.CTkLabel(linha, text="  ➜  ", font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=MD_RED).grid(row=1, column=1)
        self.combo_dest = ctk.CTkComboBox(linha, width=320, state="readonly", values=bancos)
        self.combo_dest.grid(row=1, column=2, padx=10)
        if bancos:
            self.combo_orig.set(bancos[0])
            # destino sugerido: banco do login, se diferente da origem
            dest_sug = self.login_win.current_db if self.login_win.current_db in bancos else (
                bancos[1] if len(bancos) > 1 else bancos[0])
            self.combo_dest.set(dest_sug)

        # Entidades
        ent = ctk.CTkFrame(self, corner_radius=12)
        ent.pack(padx=24, pady=(0, 10), fill="x")
        ctk.CTkLabel(ent, text="O que migrar",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=MD_RED).pack(anchor="w", padx=16, pady=(12, 4))
        chkfrm = ctk.CTkFrame(ent, fg_color="transparent")
        chkfrm.pack(anchor="w", padx=16, pady=(0, 12))
        self.chk = {}
        for chave, rotulo in (("clientes", "👥  Clientes / Fornecedores"),
                              ("permissoes", "🔐  Permissões de Usuário"),
                              ("produtos", "📦  Produtos"),
                              ("codbarras", "🏷️  Códigos de Barras"),
                              ("financeiro", "💰  Financeiro (vendaPgto)")):
            var = ctk.BooleanVar(value=True)
            ctk.CTkCheckBox(chkfrm, text=rotulo, variable=var,
                            font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 24))
            self.chk[chave] = var

        # Aviso
        ctk.CTkLabel(self,
            text="⚠️  CLIENTES: apaga 'cliente'/'cliente_empresa' do destino e copia idêntico (use banco ZERO). "
                 "Produtos/Financeiro: mantêm os IDs e pulam os já existentes. "
                 "Faça BACKUP do destino antes. Ordem: Clientes → Permissões → Produtos → Financeiro.",
            font=ctk.CTkFont(size=10), text_color=("darkorange", "orange"),
            wraplength=840, justify="left").pack(padx=24, pady=(0, 8), anchor="w")

        # Botões migrar / cancelar
        botmig = ctk.CTkFrame(self, fg_color="transparent")
        botmig.pack(pady=(2, 8))
        self.btn_migrar = ctk.CTkButton(botmig, text="▶  Iniciar Migração",
                                        width=460, height=44, font=ctk.CTkFont(size=14, weight="bold"),
                                        fg_color=MD_RED, hover_color=MD_RED_HOV,
                                        command=self._iniciar)
        self.btn_migrar.pack(side="left", padx=(0, 12))
        # Pré-flight: confere compatibilidade de schema SEM escrever nada.
        self.btn_preflight = ctk.CTkButton(
            botmig, text="🔍  Verificar compatibilidade", width=250, height=44,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color="transparent", border_width=1, text_color=TC_TEXT_MAIN,
            command=self._rodar_preflight)
        self.btn_preflight.pack(side="left", padx=(0, 12))
        # Botão Cancelar — habilita só durante a migração (cancela entre entidades)
        self._criar_btn_cancelar(botmig, side="left")
        self.btn_cancelar.configure(width=200, height=44,
                                    font=ctk.CTkFont(size=14, weight="bold"))

        self.progress = ctk.CTkProgressBar(self, width=840)
        self.progress.set(0)
        self.progress.pack(pady=(0, 8))
        self.lbl_progresso = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=11),
                                          text_color=MD_GRAY)
        self.lbl_progresso.pack(pady=(0, 6))

        # Log
        self.text_log = ctk.CTkTextbox(self, width=860, height=230,
                                       font=ctk.CTkFont(size=11, family="Consolas"))
        self.text_log.pack(padx=24, pady=(0, 8), fill="both", expand=True)

        ctk.CTkButton(self, text="↩  Voltar ao Menu", width=200, height=34,
                      fg_color="transparent", border_width=1, text_color=TC_TEXT_MAIN,
                      command=self._fechar).pack(pady=(0, 14))

    # ── Infra ──────────────────────────────────────────────────────────────
    def _bancos_disponiveis(self):
        try:
            conn = pyodbc.connect(self.base_conn_str, timeout=8)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sys.databases WHERE state_desc='ONLINE' "
                        "AND name NOT IN ('master','tempdb','model','msdb') ORDER BY name")
            bancos = [r[0] for r in cur.fetchall()]
            conn.close()
            return bancos
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível listar os bancos:\n{e}", parent=self)
            return []

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        linha = f"{ts} | {msg}"
        self.log_lines.append(linha)
        if self._imp_atual is not None:      # espelha no relatorio da entidade
            self._imp_atual.log_lines.append(linha)
        self.after(0, lambda l=linha: (
            self.text_log.insert("end", l + "\n"), self.text_log.see("end")))

    def _get_importador(self, chave):
        """Cria (uma vez) um importador HEADLESS (sem GUI) que reutiliza a lógica
        dos mixins de import, com o log redirecionado para esta janela de migração.
        Antes construía uma janela ctk oculta; agora não precisa — a lógica está em
        mixins e o headless não abre janela (mais leve e testável)."""
        if chave not in self._imp:
            classe = {
                "produtos":   ProdutosImportadorHeadless,
                "clientes":   ClientesImportadorHeadless,
                "financeiro": FinanceiroImportadorHeadless,
            }[chave]
            self._imp[chave] = classe(log=self._log)
        return self._imp[chave]

    def _dialogo_opcoes(self, origem, destino, entidades):
        """Wizard com TODAS as decisões antes da migração começar. Retorna um dict
        com as opções, ou None se o usuário cancelar. Assim a migração roda sem
        precisar de interação no meio do processo."""
        rot = ", ".join(self._ROTULOS[e] for e in self._ORDEM if e in entidades)
        tem_cli = "clientes" in entidades
        tem_prd = "produtos" in entidades

        dlg = ctk.CTkToplevel(self)
        dlg.title("Confirmar migração — opções")
        dlg.resizable(False, False)
        dlg.transient(self)
        # Altura conforme as seções exibidas (o rodapé é fixo, então o botão aparece
        # em qualquer altura — isto é só para o conteúdo não ficar apertado).
        centralizar(dlg, 640, 560 if (tem_cli and tem_prd)
                    else (520 if (tem_cli or tem_prd) else 420))

        res = {"ok": False}
        v_ciente = ctk.BooleanVar(value=False)
        v_dup    = ctk.StringVar(value="desativar")
        v_est    = ctk.StringVar(value="migrar")
        v_neg    = ctk.StringVar(value="zerar")
        v_backup = ctk.BooleanVar(value=True)

        ctk.CTkLabel(dlg, text="Confirmar migração", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=MD_RED).pack(pady=(16, 2))
        ctk.CTkLabel(dlg, text=f"{rot}\nDE:  {origem}      PARA:  {destino}",
                     font=ctk.CTkFont(size=12), justify="center").pack(pady=(0, 6))
        ctk.CTkLabel(dlg, text="Responda tudo agora — a migração roda sem interrupções.",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(pady=(0, 8))

        # Criado agora, mas empacotado só NO FIM: os botões do rodapé são empacotados
        # ANTES (side="bottom") para reservarem o espaço deles. Assim o scroll fica
        # com o que sobra e o botão de confirmar NUNCA some, independentemente das
        # opções marcadas / da altura da janela.
        scroll = ctk.CTkScrollableFrame(dlg, width=590, height=340)

        fb = ctk.CTkFrame(scroll, corner_radius=8)
        fb.pack(fill="x", padx=4, pady=6)
        ctk.CTkLabel(fb, text="🛟  SEGURANÇA", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=MD_RED).pack(anchor="w", padx=12, pady=(10, 2))
        # Backup OBRIGATÓRIO quando Clientes está no plano: essa é a única entidade
        # que APAGA o destino (DELETE) antes de reinserir — sem um ponto de restauração,
        # um erro no meio da inserção deixaria o destino com os dados apagados. Nesse
        # caso o checkbox fica marcado e travado. Nos demais, é opcional (recomendado).
        if tem_cli:
            v_backup.set(True)
        _txt_bkp = ("Fazer BACKUP do banco de DESTINO antes de migrar"
                    + (" (OBRIGATÓRIO — Clientes limpa o destino)" if tem_cli else " (recomendado)"))
        ctk.CTkCheckBox(fb, text=_txt_bkp, variable=v_backup, font=ctk.CTkFont(size=12),
                        state=("disabled" if tem_cli else "normal")).pack(anchor="w", padx=12, pady=(0, 4))
        _obs_bkp = ("Gera um .bak (COPY_ONLY) na pasta de backup do SQL Server. "
                    "Se o backup falhar, a migração é abortada por segurança.")
        if tem_cli:
            _obs_bkp += (" Exigido porque a migração de Clientes APAGA o destino — o .bak "
                         "é o seu ponto de restauração se algo falhar no meio.")
        ctk.CTkLabel(fb, wraplength=540, justify="left", font=ctk.CTkFont(size=10),
                     text_color="gray", text=_obs_bkp).pack(anchor="w", padx=12, pady=(0, 10))

        if tem_cli:
            fc = ctk.CTkFrame(scroll, fg_color=TC_FIELD_OBL_BG, corner_radius=8)
            fc.pack(fill="x", padx=4, pady=6)
            ctk.CTkLabel(fc, text="👥  CLIENTES", font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=MD_RED).pack(anchor="w", padx=12, pady=(10, 2))
            ctk.CTkLabel(fc, wraplength=540, justify="left", font=ctk.CTkFont(size=11),
                         text="A migração de Clientes APAGA 'cliente', 'cliente_empresa' e "
                              "'UsuarioPermissao' do DESTINO e copia idêntico da origem "
                              "(mantendo os cliId). Use um banco de destino ZERADO. "
                              "As Permissões entram automaticamente.").pack(anchor="w", padx=12, pady=(0, 6))
            ctk.CTkCheckBox(fc, text="Estou ciente e desejo LIMPAR o destino",
                            variable=v_ciente, font=ctk.CTkFont(size=12, weight="bold"),
                            text_color=MD_RED).pack(anchor="w", padx=12, pady=(0, 8))
            ctk.CTkLabel(fc, text="Se houver clientes duplicados (mesmo Nome + CPF/CNPJ):",
                         font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", padx=12, pady=(2, 0))
            ctk.CTkRadioButton(fc, text="Desativar repetidos (mantém só o mais novo ativo) — recomendado",
                               variable=v_dup, value="desativar",
                               font=ctk.CTkFont(size=11)).pack(anchor="w", padx=24, pady=2)
            ctk.CTkRadioButton(fc, text="Manter todos como na origem",
                               variable=v_dup, value="manter",
                               font=ctk.CTkFont(size=11)).pack(anchor="w", padx=24, pady=(2, 10))

        if tem_prd:
            fp = ctk.CTkFrame(scroll, corner_radius=8)
            fp.pack(fill="x", padx=4, pady=6)
            ctk.CTkLabel(fp, text="📦  PRODUTOS — Estoque", font=ctk.CTkFont(size=13, weight="bold"),
                         text_color=MD_RED).pack(anchor="w", padx=12, pady=(10, 2))
            ctk.CTkRadioButton(fp, text="Migrar o estoque atual (proEstoqueAtual) da origem",
                               variable=v_est, value="migrar",
                               font=ctk.CTkFont(size=11)).pack(anchor="w", padx=24, pady=2)
            ctk.CTkRadioButton(fp, text="Zerar o estoque (todos os produtos entram com 0)",
                               variable=v_est, value="zerar",
                               font=ctk.CTkFont(size=11)).pack(anchor="w", padx=24, pady=(2, 6))
            ctk.CTkLabel(fp, text="Se houver produtos com estoque NEGATIVO (só vale se migrar o estoque):",
                         font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", padx=12, pady=(2, 0))
            ctk.CTkRadioButton(fp, text="Iniciar os negativos com ZERO",
                               variable=v_neg, value="zerar",
                               font=ctk.CTkFont(size=11)).pack(anchor="w", padx=24, pady=2)
            ctk.CTkRadioButton(fp, text="Manter os valores negativos da origem",
                               variable=v_neg, value="manter",
                               font=ctk.CTkFont(size=11)).pack(anchor="w", padx=24, pady=(2, 10))

        lbl_err = ctk.CTkLabel(dlg, text="", font=ctk.CTkFont(size=11), text_color=MD_RED)

        def _ok():
            if tem_cli and not v_ciente.get():
                lbl_err.configure(text="⚠️ Marque 'Estou ciente' para limpar o destino, ou cancele.")
                return
            res.update({"ok": True, "cli_ciente": bool(v_ciente.get()),
                        "cli_duplicados": v_dup.get(), "prd_estoque": v_est.get(),
                        "prd_negativos": v_neg.get(), "backup": bool(v_backup.get())})
            dlg.destroy()

        # Rodapé FIXO: empacotado ANTES do scroll e ancorado embaixo, então sempre
        # tem espaço garantido (o scroll é que encolhe/rola). Ordem: 1º o frame dos
        # botões (vai pro fundo), 2º a mensagem de erro (fica logo acima dele).
        bot = ctk.CTkFrame(dlg, fg_color="transparent")
        bot.pack(side="bottom", pady=(2, 14))
        ctk.CTkButton(bot, text="▶  Iniciar Migração", width=220, height=40,
                      fg_color=MD_RED, hover_color=MD_RED_HOV,
                      font=ctk.CTkFont(size=13, weight="bold"), command=_ok).pack(side="left", padx=8)
        ctk.CTkButton(bot, text="Cancelar", width=140, height=40, fg_color="transparent",
                      border_width=1, text_color=TC_TEXT_MAIN, command=dlg.destroy).pack(side="left", padx=8)
        lbl_err.pack(side="bottom")
        # Agora sim o scroll ocupa o espaço restante entre o cabeçalho e o rodapé.
        scroll.pack(padx=20, pady=(0, 8), fill="both", expand=True)

        dlg.after(150, lambda: (dlg.lift(), dlg.focus_force(),
                                 dlg.grab_set() if dlg.winfo_exists() else None))
        self.wait_window(dlg)
        if not res.get("ok"):
            return None
        return {k: v for k, v in res.items() if k != "ok"}

    # ── Pré-flight de schema (SOMENTE LEITURA) ─────────────────────────────
    def _selecao_migracao(self):
        """Valida e devolve (origem, destino, entidades) ou None (já avisou o usuário)."""
        origem, destino = self.combo_orig.get(), self.combo_dest.get()
        if not origem or not destino:
            messagebox.showwarning("Atenção", "Selecione origem e destino.", parent=self)
            return None
        if origem == destino:
            messagebox.showwarning("Atenção",
                "Origem e destino devem ser bancos DIFERENTES.", parent=self)
            return None
        entidades = [k for k, v in self.chk.items() if v.get()]
        if not entidades:
            messagebox.showwarning("Atenção", "Marque ao menos um tipo de dado.", parent=self)
            return None
        return origem, destino, entidades

    def _preflight_conectado(self, origem, destino, entidades):
        """Abre as duas conexões, roda o pré-flight e fecha. Retorna (linhas, resumo)."""
        oc = pyodbc.connect(self.base_conn_str + f"DATABASE={origem};", timeout=15)
        try:
            dc = pyodbc.connect(self.base_conn_str + f"DATABASE={destino};", timeout=15)
            try:
                return self._preflight(oc, dc, entidades)
            finally:
                try:
                    dc.close()
                except Exception:
                    pass
        finally:
            try:
                oc.close()
            except Exception:
                pass

    def _rodar_preflight(self):
        sel = self._selecao_migracao()
        if not sel:
            return
        self.btn_preflight.configure(state="disabled")
        threading.Thread(target=self._preflight_worker, args=sel, daemon=True).start()

    def _preflight_worker(self, origem, destino, entidades):
        try:
            self._log("")
            self._log(f"🔍 PRÉ-FLIGHT — schema {origem} → {destino} (somente leitura)")
            linhas, resumo = self._preflight_conectado(origem, destino, entidades)
            for l in linhas:
                self._log(l)
            b, a, ok = resumo["bloqueantes"], resumo["avisos"], resumo["ok"]
            self._log(f"🔍 PRÉ-FLIGHT concluído — 🔴 {b} bloqueante(s) | ⚠️ {a} aviso(s) "
                      f"| ✅ {ok} tabela(s) compatível(is)")
            if b:
                txt = (f"{b} problema(s) BLOQUEANTE(S) e {a} aviso(s).\n\n"
                       "Migrar assim provavelmente vai FALHAR ou PERDER dados.\n"
                       "O detalhe está no log desta tela.")
                self.after(0, lambda t=txt: messagebox.showerror(
                    "Pré-flight: bloqueante", t, parent=self))
            elif a:
                txt = f"Nenhum bloqueante, mas {a} aviso(s).\n\nRevise o log antes de migrar."
                self.after(0, lambda t=txt: messagebox.showwarning(
                    "Pré-flight: avisos", t, parent=self))
            else:
                self.after(0, lambda: messagebox.showinfo(
                    "Pré-flight OK",
                    "Schema compatível: nenhum problema encontrado.", parent=self))
        except Exception as e:
            self._log(f"❌ Pré-flight falhou: {str(e)[:200]}")
            self.after(0, lambda m=str(e): messagebox.showerror(
                "Erro no pré-flight", m, parent=self))
        finally:
            self.after(0, lambda: self.btn_preflight.configure(state="normal"))

    # ── Fluxo ──────────────────────────────────────────────────────────────
    def _iniciar(self):
        origem  = self.combo_orig.get()
        destino = self.combo_dest.get()
        if not origem or not destino:
            messagebox.showwarning("Atenção", "Selecione origem e destino.", parent=self)
            return
        if origem == destino:
            messagebox.showwarning("Atenção", "Origem e destino devem ser bancos DIFERENTES.", parent=self)
            return
        entidades = [k for k, v in self.chk.items() if v.get()]
        if not entidades:
            messagebox.showwarning("Atenção", "Marque ao menos um tipo de dado.", parent=self)
            return

        # Pré-flight de SCHEMA: se houver bloqueante, exige confirmação explícita.
        try:
            _linhas, _res = self._preflight_conectado(origem, destino, entidades)
            if _res["bloqueantes"]:
                for _l in _linhas:
                    self._log(_l)
                if not messagebox.askyesno(
                        "Pré-flight: problemas bloqueantes",
                        f"O pré-flight encontrou {_res['bloqueantes']} problema(s) "
                        f"BLOQUEANTE(S) de schema (detalhe no log).\n\n"
                        "Migrar assim provavelmente vai FALHAR ou PERDER dados.\n\n"
                        "Deseja continuar mesmo assim?", parent=self):
                    self._log("⛔ Migração abortada pelo pré-flight.")
                    return
        except Exception:
            pass

        # Pré-flight: FKs DESABILITADAS no destino (resto de migração interrompida)
        try:
            _pf = pyodbc.connect(self.base_conn_str + f"DATABASE={destino};", timeout=10)
            fks_off = self._fks_desabilitadas(_pf)
            if fks_off:
                if messagebox.askyesno(
                        "FKs desabilitadas no destino",
                        f"Detectei {len(fks_off)} chave(s) estrangeira(s) DESABILITADA(S) no "
                        f"banco '{destino}'.\n\nIsso costuma ser resto de uma migração ANTERIOR "
                        "interrompida (as FKs ficaram sem validação).\n\n"
                        "Deseja REABILITÁ-LAS agora (com validação)?", parent=self):
                    n = self._reabilitar_fks(_pf, fks_off)
                    messagebox.showinfo("FKs reabilitadas",
                        f"{n}/{len(fks_off)} FK(s) reabilitada(s) no destino.", parent=self)
            _pf.close()
        except Exception:
            pass

        # Wizard: coleta TODAS as decisões ANTES de iniciar (migração não
        # assistida). Retorna None se o usuário cancelar.
        opcoes = self._dialogo_opcoes(origem, destino, entidades)
        if opcoes is None:
            return
        self._opcoes = opcoes

        # Multi-loja: se o DESTINO tiver mais de uma empresa, a seleção entra aqui —
        # ainda no wizard, para a migração seguir sem interação no meio. A conexão do
        # destino só é aberta dentro do _migrar, então abrimos uma temporária aqui.
        try:
            _cfg = pyodbc.connect(self.base_conn_str + f"DATABASE={destino};", timeout=15)
        except Exception as e:
            messagebox.showerror("Destino inacessível",
                                 f"Não foi possível conectar em {destino}:\n{str(e)[:300]}",
                                 parent=self)
            return
        try:
            empresas = self._selecionar_empresas(is_insert=True, conn=_cfg)
        finally:
            try:
                _cfg.close()
            except Exception:
                pass
        if empresas is False:
            self._log("Migração cancelada na seleção de empresas.")
            return
        self._opcoes["empresas"] = empresas
        if empresas:
            self._log(f"🏬 Destino multi-loja — empresas selecionadas: {empresas}")

        # pré-cria as importadoras ocultas (thread principal) — só as que
        # reutilizam o importador (produtos e financeiro). Clientes e permissões
        # são migrados por rotina própria.
        for e in entidades:
            if e in ("produtos", "financeiro"):
                self._get_importador(e).empresas_alvo = empresas
        self.btn_migrar.configure(state="disabled")
        self.progress.set(0)
        self._op_iniciada()
        threading.Thread(target=self._migrar, args=(origem, destino, entidades), daemon=True).start()

    def _pergunta_thread(self, titulo, msg, tipo="yesno"):
        """Mostra um diálogo na THREAD PRINCIPAL e bloqueia a thread de migração
        até o usuário responder. tipo='yesno' -> True/False; 'info' -> True."""
        res = {}
        ev = threading.Event()
        def _go():
            try:
                if tipo == "yesno":
                    res["v"] = messagebox.askyesno(titulo, msg, parent=self)
                else:
                    messagebox.showinfo(titulo, msg, parent=self)
                    res["v"] = True
            finally:
                ev.set()
        self.after(0, _go)
        ev.wait()
        return res.get("v", False)

    def _fechar(self):
        for w in list(self._imp.values()):
            try:
                w.destroy()
            except Exception:
                pass
        self.menu_win.deiconify()
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = JanelaLogin()
    app.mainloop()
