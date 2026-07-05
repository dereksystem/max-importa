# Estrutura do Código

Mapa de `max_importa.py` (v3.0.1) — classes, principais métodos e tabelas tocadas.

---

## Constantes / configuração (topo do arquivo)

- `APP_VERSION = "3.0.1"` — versão (login, títulos, relatórios).
- Paleta MaxData (`MD_RED`, `MD_GRAY`, …) e cores adaptáveis ao tema.
- Pasta de logs em `max_importa.ini` (`_get_log_dir` / `_set_log_dir`).

## Funções de módulo (topo)

| Função | Papel |
|---|---|
| `_resource_path` | resolve recursos no `.py` e no `.exe` (PyInstaller) |
| `_logo_label` | monta o label da logo (usa PIL/CTkImage) |
| `_get_log_dir` / `_set_log_dir` | pasta de logs (via `.ini`) |
| `_gerar_arquivo_erros` | gera `ERROS_*.txt` com os nomes que falharam |
| `_montar_msg_obrigatorios` | mensagem amigável de obrigatórios em branco (3 importadores) |
| `_marcar_arquivo_importado` | renomeia o arquivo importado com status + data/hora |
| `_resetar_selecao` | limpa a seleção da tela após importar |
| `_pos_importacao` | orquestra erros + rename + reset ao final |
| `centralizar` | centraliza janelas |

---

## Janelas (classes)

### `JanelaLogin` (linha ~210)
Conexão SQL Server + escolha do banco. Mostra `versao <APP_VERSION>`.
Métodos: `_build`, `_editar_credenciais`, `_conectar`, `_confirmar`.

### `JanelaMenu` (~396)
Menu de módulos. Abre Produtos/Clientes/Financeiro (INSERT/UPDATE), Migração e a
configuração de pasta de logs. Métodos `_abrir_*`, `_configurar_logs`, `_toggle_tema`.

### `JanelaProdutos` (~600)
Tabelas: `produto`, `produto_empresa`, `codBarras`, `produtoUn`, `fabricante`,
`grupoProd`, `subGrupoProd`, `produtoClasse`, `proNCM`, `proCEST`,
`produtoAcertoEstoque`, `produtoAcertoEstoqueItem`.
Métodos-chave:
- `_iniciar` (validação + start), `_inserir_produtos`, `_atualizar_produtos`
- `_get_or_create_unidade` (unidade automática), `_get_or_create` (fab/grupo/etc.)
- `_get_str_max` (corte de tamanho)
- `_verificar_acerto_apos_sucesso`, `_gerar_acerto_estoque`

### `JanelaClientes` (~1637)
Tabelas: `cliente`, `cliente_empresa`.
- `CAMPOS_OBRIGATORIOS`, `CAMPOS_INTERATIVOS`, `CAMPOS_CLIENTE` (lista do mapeamento)
- `_iniciar`, `_tratar_campos_vazios_clientes` (prompts Fantasia/RG/Número)
- `_calc_cli_tipo` (0=PF, 1=PJ, derivado do CPF/CNPJ)
- `_inserir_clientes`, `_atualizar_clientes`, `_atualizar_clientes_por_cpf`,
  `_confirmar_update_por_cpf`

### `JanelaFinanceiro` (~2735)
Tabela: `vendaPgto`. Localiza cliente por CPF/CNPJ (`_lookup_cli_id`).
- `_iniciar`, `_inserir_financeiro`, `_aviso_nao_encontrados`

### `JanelaMigracao` (~3329)
Migração banco → banco. Constantes: `_ROTULOS`, `_ORDEM`, `_TOTAL_FMT`.
- SELECTs dinâmicos: `_cols`, `_c`, `_lookup_sub`, `_sql_produtos`,
  `_sql_clientes(todos=…)`, `_sql_financeiro`
- Fluxo: `_iniciar`, `_migrar`, `_migrar_entidade`
- Rotinas próprias: `_migrar_clientes` (modo "banco zero"), `_migrar_permissoes`
- Totais/relatório: `_resumo_totais`, `_salvar_relatorio_migracao`
- Diálogo thread-safe: `_pergunta_thread`
- Conversores: `_to_str`, `_to_int`, `_to_dt`
- Reuso de importadores ocultos: `_get_importador` (produtos/financeiro)

---

## Padrões importantes

- **Captura de IDENTITY:** `INSERT + SELECT SCOPE_IDENTITY()` no **mesmo batch** com
  `SET NOCOUNT ON` (por causa das triggers AFTER de datas).
- **Resiliência a schema (migração):** SELECTs montados a partir das colunas reais
  do banco de origem; ausência → `NULL`.
- **Relatórios sempre gerados**, inclusive em falha de validação.
- **Log redirecionado na migração:** o log do importador oculto é espelhado no
  relatório da migração (`_imp_atual`).

---

## Arquivos do projeto

| Arquivo | Papel |
|---|---|
| `max_importa.py` | código-fonte |
| `max_importa.spec` | build PyInstaller |
| `BUILD.bat` | script de build (com Python/PIL/anti-elevação) |
| `logo_maxdata.png`, `max_x.ico` | logo e ícone |
| `max_importa.ini` | pasta de logs configurada |
| `MaxImporta_Modelos_Importacao.xlsx`, `modelo de importação_*.txt` | modelos |
| `CHANGELOG.txt` | histórico de versões |
| `documentacao_max_importa.html` | documentação visual |
| `README.md`, `docs/*.md` | documentação em markdown |
