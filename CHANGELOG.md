# Changelog — Max_Importa

Formato **MAJOR.MINOR.PATCH**. A versão fica em `max_importa.py` → `APP_VERSION`
e aparece na tela de login, nos títulos das janelas e no cabeçalho dos relatórios.

> Registro em markdown. O histórico detalhado original também está em
> [`CHANGELOG.txt`](CHANGELOG.txt).

---

## [Não liberado] — versão a definir

### Interface: Produtos e Clientes no novo visual + janela maximizada — FASE 3
Etapa final do redesign: o visual aprovado passa a valer nas **três** telas de
importação, e a janela abre ocupando o monitor inteiro.
- **Abre maximizada** (`state("zoomed")`), adaptando-se a qualquer resolução — quem
  faz o ajuste é o próprio sistema, sem tamanho fixo no código. Há fallback para
  ambientes que não suportam e `minsize` de 1024×640 para a janela restaurada não
  encolher além do utilizável. A área de mapeamento já cresce com a janela.
- **Produtos** e **Clientes** ganharam os mesmos estados de linha do Financeiro
  (mapeado / faltando / chave), os selos em pílula e o rodapé com contador
  "Obrigatórios: X de Y" + barra de progresso.
- Campo-chave por tela: `proId` (Produtos), `cliId` (Clientes) e `cliCpfCgc`
  (Financeiro, usado no lookup).
- **Novo estado âmbar** para os campos de preenchimento assistido do Clientes
  (`CAMPOS_INTERATIVOS`), com o âmbar da especificação (`#FFF7ED` / `#F5E0BE`) e o
  selo `AUTO` — antes eram só um texto "[AUTO/OPCIONAL]".
- 3 testes novos cobrindo a pintura por estado, o destaque do campo-chave e o
  contador/barra. O teste antigo passou a exercitar explicitamente o caminho legado
  (`layout_1b=False`), que segue valendo para telas não convertidas.

### Interface: tela de Financeiro no novo visual (layout 1b) — FASE 2
Segunda etapa do redesign: o **Financeiro é a tela piloto** do visual aprovado. As
demais seguem inalteradas — o novo estilo é **opt-in por tela** (`_LAYOUT_1B`), então
Produtos e Clientes só mudam na fase 3.
- **Linhas de mapeamento com estado por cor**, conforme a especificação: mapeado
  (`#EAF7F0` / borda `#CDEBDC`), obrigatório faltando (`#FDECEC` / `#F6D6D6`) e campo
  de lookup (`#FBEEEC` / `#F3D9D5`), com raio 9 px, borda de 1 px e respiro 9×12.
- **Selos**: `CHAVE` no campo usado para localizar o cliente (`cliCpfCgc`) e `FALTA`
  nos obrigatórios ainda não mapeados. O `FALTA` é **estado, não rótulo fixo** —
  desaparece assim que o campo é mapeado.
- **Rodapé do mapeamento** com contador "Obrigatórios: X de Y" e barra de progresso
  (150×7, raio 999), que fica verde quando todos os obrigatórios estão preenchidos.
- A janela passou a **dimensionar-se pela tela disponível** (até 1460×880): com a
  sidebar consumindo 236 px, o conteúdo precisa de mais largura do que as antigas
  janelas soltas de 980 px — sem isso a coluna de seleção de coluna ficava cortada.

### Interface: janela única com sidebar (layout 1b aprovado) — FASE 1
Primeira etapa do redesign aprovado em `layout-1b-aprovado/`. **Só a navegação mudou;
o conteúdo das telas continua idêntico** (o visual de cada tela é a fase 2).
- Antes cada módulo era um `CTkToplevel` próprio, e navegar significava `withdraw()`
  numa janela e `deiconify()` em outra. Agora existe **uma janela** (`JanelaShell`):
  sidebar fixa de 236 px à esquerda, cabeçalho com breadcrumb e título, e os módulos
  montados como frames na área de conteúdo.
- **Sidebar** com grupos "IMPORTAR" (Produtos, Clientes, Financeiro) e "FERRAMENTAS"
  (Migração, Pasta de logs, Alternar tema, Sair), item ativo em `#CC0000` e, no rodapé,
  o status de conexão (bolinha verde + banco) — como especificado no layout.
- **Pílula Inserir / Atualizar** no cabeçalho das telas que aceitam as duas operações,
  substituindo os botões separados do antigo menu (nenhuma função foi perdida).
- **Como as ~2.800 linhas de tela não precisaram ser reescritas:** o mixin
  `TelaHospedada` absorve as chamadas que só existem em janela
  (`title`/`resizable`/`protocol`/`withdraw`/`deiconify`/`grab_set`…). O código das
  telas segue chamando `self.title(...)`, que agora alimenta o cabeçalho do shell.
  `centralizar()` virou no-op quando recebe um frame.
- As 4 telas passaram de `CTkToplevel` para `TelaHospedada + CTkFrame`, montadas na
  área de conteúdo (`master = shell.conteudo`), com `menu_win` ainda apontando para o
  shell — o que preserva `login_win`, `conn` e o fluxo de fechamento.
- ⚠️ Os 243 testes **não cobrem a GUI** (usam `Janela*.__new__` com stubs): eles
  garantem que a lógica seguiu intacta, mas a verificação da interface foi manual —
  as 5 telas foram montadas e inspecionadas uma a uma.

### Dry-run (simulação) também em Produtos e Clientes
A caixa **"🔎 Simular (não grava)"**, que existia só no Financeiro, passa a valer nas
três telas — incluindo os modos de UPDATE.
- **Como é feito:** um **cursor simulado** (`mi_db._CursorSimulado`) encaminha as
  leituras e descarta as escritas. A alternativa — espalhar `if dry_run` pelos ~200
  comandos de INSERT de produtos/clientes — seria invasiva e, pior, um ponto esquecido
  **gravaria no banco durante uma "simulação"**. Aqui a regra é única e central.
- Cobre `INSERT`/`UPDATE`/`DELETE`, e também `DBCC CHECKIDENT` e `SET IDENTITY_INSERT`
  — que **não são transacionais** e por isso jamais poderiam ser "desfeitos" por um
  rollback. Era a razão de a simulação ter de ser *sem escrita*, e não *com rollback*.
- O INSERT de produtos vem no mesmo comando que o `SELECT SCOPE_IDENTITY()`. Descartar
  tudo fazia o worker abortar a linha com "SCOPE_IDENTITY retornou NULL" e reportar
  erro inexistente; o cursor devolve um **id fictício** para o fluxo seguir.
- Em simulação o **acerto de estoque não é gerado** (ele gravaria no banco) e o arquivo
  não é renomeado. O resumo lista os comandos que **seriam** executados, por tabela.
- Testes: 22 sem banco (inclusive `IF NOT EXISTS (...) INSERT`, que não começa com
  INSERT) e 2 de integração que provam contagem inalterada em `produto`,
  `produto_empresa`, `fabricante`, `grupoProd`, `subGrupoProd`, `produtoUn`,
  `cliente`, `cliente_empresa` **e no `IDENT_CURRENT`**.

### Dedupe inteligente de clientes (aponta, nunca funde)
O dedup existente casava apenas por **documento exato** — e a base real tem vários
clientes com CPF `00000000000`, que não identifica ninguém. Agora a importação de
Clientes analisa duplicidade provável antes de inserir e **relata**.
- Funções puras em `mi_validacao.py`: `normalizar_nome` (sem acento, maiúsculo, sem
  pontuação e sem sufixo societário — LTDA/ME/EPP/S.A./EIRELI), `documento_placeholder`
  (documento vazio ou de dígitos repetidos), `similaridade` (via `difflib`, sem
  dependência nova) e `detectar_duplicados`.
- Quatro classificações: **ja-cadastrado** (arquivo × banco com mesmo documento e nome
  — informativo, não é suspeita), **documento** (mesmo CPF/CNPJ, destacando quando os
  nomes divergem), **nome-exato** (com aviso de possível matriz/filial quando os
  documentos diferem) e **nome-parecido** (similaridade ≥ 88%).
- **Nunca funde registros:** juntar clientes é irreversível e arrisca unir empresas
  distintas. A saída vai para o log (amostra), o relatório HTML e um
  `DUPLICADOS_CLIENTES_<ts>.csv` para conferência no Excel.
- **Desempenho:** blocagem por prefixo do nome evita o O(n×m) de comparações — 3.800
  registros (430 do arquivo × 3.370 do banco) processados em ~1 s.
- Medido na base real: **479 suspeitas** reais, separadas de 365 "já cadastrado".
  Achados concretos incluem o mesmo CNPJ sob nomes diferentes
  (`FAZENDA INHUMAS` × `SIERENTZ AGRO BRASIL LTDA`) — padrão de fazenda × empresa que
  só quem conhece a base sabe julgar. 31 testes novos.

---

## [3.8.0] — 2026-07-18

### Relatório HTML de fechamento
Além do `.txt` (ler no editor) e do `.json` (integrar), cada importação passa a gerar
`RELATORIO_<OPERAÇÃO>_<ts>.html` na pasta de logs — para **entender de relance**.
- Cartões (inseridos / pulados / erros / total), **barras proporcionais**, banner de
  status (sucesso, com erros ou **SIMULAÇÃO**), tabela de CPF/CNPJ não encontrados,
  itens com erro e o log completo num bloco recolhível.
- Seção **Qualidade dos dados** consolidando os alertas: regras de negócio, datas não
  reconhecidas e `pgtPago` fora do padrão, cada um com quantidade e tratamento aplicado.
- **Autocontido:** CSS inline, zero requisição externa — abre offline com duplo clique
  e imprime bem (`@media print`). Todo conteúdo vindo do arquivo do usuário é
  escapado (teste cobre tentativa de injeção de `<script>`).
- Tabelas grandes são limitadas a 1.000 linhas com aviso, para o arquivo não explodir.

### Perfis de mapeamento salvos
O auto-mapeamento só casa nomes IDÊNTICOS; arquivos de terceiros exigiam remapear
tudo na mão a cada importação. Agora dá para salvar esse trabalho.
- Novo módulo `mi_perfis.py` + barra **"Perfil de mapeamento"** nas 3 telas
  (Produtos/Clientes/Financeiro): combo + **Aplicar / Salvar… / Excluir**.
- Perfis ficam em `max_importa_perfis.json`, ao lado do executável, **separados por
  módulo** (um perfil de Clientes não aparece em Financeiro).
- Ao aplicar, confronta o perfil com as colunas do arquivo carregado: mapeia o que
  existe e **avisa explicitamente** quais colunas sumiram (layout mudou), em vez de
  falhar em silêncio.
- Arquivo de perfis corrompido não derruba nada (best-effort, com teste).

### Validação de regras de negócio no parse (qualidade do dado)
Novas funções puras em `mi_validacao.py` — `cpf_valido`, `cnpj_valido`,
`cpf_cnpj_valido`, `email_valido`, `data_plausivel`, `valor_positivo` — aplicadas
linha a linha durante a importação. **Avisam, não bloqueiam**: o registro entra, mas
o problema aparece no log (amostra) e num resumo agregado no fim.
- **Financeiro:** CPF/CNPJ com dígito verificador inválido, `pgtValor` negativo e datas
  fora da faixa plausível. O check de documento é o mais útil: um CPF/CNPJ inválido
  **nunca** casa no lookup, então o aviso EXPLICA o "CPF/CNPJ não encontrado" —
  distingue *dado ruim na origem* de *cliente ausente no destino*.
- **Clientes:** CPF/CNPJ inválido e e-mail malformado.
- Mecanismo genérico `_registrar_alerta`/`_resumo_alertas` em `mi_db.py` (conta por
  categoria, loga amostra, nunca lança) — unifica o padrão que já existia para datas
  e `pgtPago`.
- Convenção: **vazio nunca é inválido** (ausência é assunto da validação de
  obrigatórios); nenhuma regra lança exceção.
- Medido nos arquivos reais do usuário: `cad_receber.txt` → 35 documentos inválidos
  (todos `00000000000`, parte dos 287 "não encontrados" — agora explicados);
  `cad_cliente.txt` → 7 documentos inválidos e 1 e-mail com dois endereços colados
  num campo só. 35 testes novos.

### Pré-flight: compatibilidade de schema origem × destino (antes de migrar)
Novo botão **"🔍 Verificar compatibilidade"** na tela de Migração e **gate automático**
no início da migração (se houver bloqueante, exige confirmação explícita). Roda
**somente leitura** — nenhuma escrita, nenhuma transação.
- Compara, por tabela de cada entidade escolhida: existência da tabela, colunas só na
  origem (dado que não seria copiado), **tipo** divergente, **tamanho menor no destino**,
  precisão/escala de decimais, **collation** divergente e destino NOT NULL onde a
  origem aceita NULL. Mostra também as contagens origem → destino.
- **Truncamento medido, não teórico:** quando a coluna do destino é menor, conta
  quantas linhas da origem **realmente** excedem (`LEN(col) > tam`) — vira
  "🔴 12 linha(s) excedem" em vez de um aviso genérico.
- Checa ainda FKs já desabilitadas no destino e a existência de `config` (empId).
- Validado no mundo real: `BD_ZERO → DB_VENDAS` acusou 6 bloqueantes (o destino nem é
  um banco MaxManager); `BD_ZERO → MAX_ARKALT` passou limpo, com as contagens.
- 7 testes sem banco (conexão falsa exercita cada ramo) + 1 de integração que confirma
  schema idêntico sem bloqueante **e** que nada foi escrito.

### Correções
- **`pgtPago`**: o MaxManager espera **S = Concluído / N = Aberto**, mas os arquivos (e o
  próprio modelo de importação) traziam `C` de "Concluído" — valor inválido. Novo
  `_norm_pago` normaliza sinônimos (C/SIM/PAGO/QUITADO/1 → `S`; N/A/ABERTO/0 → `N`);
  valor fora do padrão deriva do `pgtDataQuitou` e loga aviso. Modelo corrigido.
- **"Salvar linhas não inseridas (.txt)"** quebrava com `'NoneType' object has no
  attribute 'iloc'`: o `_resetar_selecao` zerava `self.df` com o diálogo ainda aberto.
  Agora o diálogo tira um snapshot das linhas ao abrir.

---

## [3.7.0] — 2026-07-17

### Importação por arquivo: Excel, encoding automático e simulação (dry-run)
Novo módulo `mi_arquivo.py` centraliza a leitura de arquivos (antes duplicada nos
três `_carregar_colunas`) e traz três recursos:
- **Importar `.xlsx`/`.xlsm` direto** (via openpyxl), além de `.txt`/`.csv` — sem
  precisar exportar a planilha para texto antes. O diálogo das 3 telas (Produtos,
  Clientes, Financeiro) já aceita Excel.
- **Autodetecção de encoding** — no lugar do `latin1` fixo (que corrompia acentos de
  arquivos utf-8/cp1252). Estratégia determinística p/ o domínio PT-BR: BOM
  (utf-8-sig/utf-16) → utf-8 estrito (auto-validável) → fallback cp1252. Evita de
  propósito o detector estatístico (charset-normalizer), que erra o code page em
  amostras curtas e corromperia justamente os acentos.
- **Dry-run (simulação) no Financeiro** — checkbox "🔎 Simular (não grava)": percorre
  lookup + parse + validações e reporta o que ACONTECERIA (seriam inseridos, CPFs não
  encontrados, datas não reconhecidas) **sem gravar nada**. Não renomeia nem reseta o
  arquivo. Escolhida simulação sem-escrita (não rollback) porque os INSERTs de
  Produtos/Clientes usam `DBCC CHECKIDENT`/`IDENTITY_INSERT`, que não são
  transacionais — um rollback deixaria efeito colateral.

### Testes
- `tests/test_arquivo.py` (13 casos): separador, encoding (BOM/utf-8/cp1252), leitura
  de `.xlsx`/`.csv`/`.txt` com acento.
- `test_import_financeiro_dry_run_nao_grava`: confirma **0 gravações** na simulação.
- `test_migracao_financeiro_via_headless` tornou-se determinístico (zera o destino
  descartável antes de migrar, em vez de depender do estado do BD_ZERO).
- Build: `openpyxl` (+ `mi_arquivo`) adicionados ao `.spec`.

---

## [3.6.12] — 2026-07-17

### Datas — mais formatos aceitos e fim do descarte silencioso
- `_get_datetime` passou a reconhecer **muito mais formatos** de data no arquivo,
  além do ISO (`aaaa-mm-dd`) e barra BR (`dd/mm/aaaa`) que já funcionavam:
  traço BR (`dd-mm-aaaa`), ponto (`dd.mm.aaaa`), ISO com barra (`aaaa/mm/dd`),
  US (`mm/dd/aaaa`, só como fallback quando o BR não casa), ano com 2 dígitos e
  **serial do Excel** (nº de dias, faixa ~1954–2119). BR tem prioridade sobre US
  (ERP brasileiro), e formato de 4 dígitos vence o de 2.
- **Fim do `None` silencioso:** quando um valor de data **não-vazio** não é
  reconhecido, agora é **contabilizado e logado** (amostra no LOG + alerta agregado
  no fim do Financeiro: *"N valor(es) de data NÃO reconhecido(s)… gravado(s) como
  NULL"*). Era a mesma classe do bug 3.6.9 — data em formato inesperado sumia sem
  deixar rastro. A chamada de log é blindada (nunca aborta a importação).
- **Cobertura de teste:** o teste de integração do Financeiro agora **confere
  `pgtData`/`pgtVecmto` no banco** (com data em formato BR-traço), fechando a lacuna
  que deixou o bug de datas passar. +10 casos no teste unitário de `_get_datetime`.
- Diagnóstico associado: quando "as datas não aparecem" mas a importação nova está
  correta, geralmente são **lançamentos legados** (pré-3.6.9) com data já NULL no
  banco — precisam ser refeitos da origem, não é o importador atual.

---

## [3.6.11] — 2026-07-13

### Robustez e segurança da migração (integridade, backup, retry, guard-rail)
- **Integridade referencial pós-migração:** a reconciliação agora detecta **FKs
  desabilitadas** no destino (sem enforcement) e **linhas órfãs** (referência para
  um pai inexistente) nas relações-chave (`cliente_empresa→cliente`,
  `vendaPgto→cliente`, `produto_empresa→produto`, `codBarras→produto`). Pega o risco
  silencioso da FK "não-confiável" (que o SQL Server não valida sozinho).
- **Backup obrigatório na migração destrutiva:** como Clientes é a única entidade que
  APAGA o destino antes de reinserir, o backup passou a ser **marcado e travado** no
  wizard quando Clientes está no plano — garante um ponto de restauração.
- **Retry em erro transiente:** deadlock (1205), lock/query timeout (1222/-2), queda de
  conexão (08S01)… agora **re-tentam** com backoff exponencial em vez de abortar a
  migração. Erros de dados (PK, truncamento, NULL) NÃO re-tentam — sobem na hora.
  Aplicado no bulk do Financeiro (lote atômico, seguro re-tentar) e respeita o cancelamento.
- **Guard-rail estrutural (teste permanente):** uma auditoria AST falha o CI se um mixin
  de importação usar `self.X` que só a GUI provê e o importador *headless* (migração)
  não tem — a causa-raiz de 4 bugs recentes (log_lines, _aviso_nao_encontrados,
  cancelamento, _calc_cli_tipo). Fecha a classe de bug automaticamente.

---

## [3.6.10] — 2026-07-13

### Reconciliação — validação de CONTEÚDO por coluna (pega perda silenciosa)
- A reconciliação origem × destino comparava só **contagem** (COUNT) e **soma**
  (SUM de valor/estoque). Isso não pega corrupção de conteúdo — foi por isso que o
  bug de datas (3.6.9), que zerou 100% das datas, passou meses invisível.
- Novo `_validar_conteudo`: compara a **taxa de preenchimento (não-NULL) por coluna**
  entre origem e destino, **normalizada** (proporção — funciona mesmo com linhas
  puladas/dedup/pré-existentes). Sinaliza:
  - 🔴 **forte** quando origem ≥30% preenchida e destino ≤2% (coluna praticamente
    vazia no destino — possível perda de dados);
  - ⚠️ **aviso** quando o preenchimento cai mais de 15 pontos;
  - ✅ resumo quando tudo coerente.
- Colunas cobertas: clientes (nome, CPF, endereço/cobrança, limite, celular, e-mail…),
  produtos (descrição, código, preço), financeiro (**pgtData/pgtVecmto/pgtDataQuitou**,
  valor, cliente, documento…). Aparece no bloco "CONFERÊNCIA ORIGEM × DESTINO".
- Validado contra dados reais corrompidos: sinalizou exatamente as 3 colunas de data
  esvaziadas. 2 testes de regressão (sem banco) adicionados.

---

## [3.6.9] — 2026-07-13

### 🚨 CRÍTICO — datas eram PERDIDAS (iam NULL) na importação/migração
- `_get_datetime` retornava **None para toda entrada**: usava `s[:len(fmt)]`, mas
  `len("%Y-%m-%d")` == 8 enquanto a data formatada tem 10 caracteres — truncava
  `"2026-03-01"` para `"2026-03-"` e o parse falhava sempre.
- **Impacto:** toda migração/importação de **Financeiro** gravava `pgtData`,
  `pgtVecmto` e `pgtDataQuitou` **NULL**; idem `DataInclusao` de clientes. A
  reconciliação (COUNT + SUM de valor) não detectava, pois não compara datas.
- **Correção:** parse na string inteira (sem truncar), `datetime.fromisoformat`
  para ISO, e uso direto quando o valor já é `datetime`/`Timestamp` (caso da
  migração — a data vem do banco como objeto). NaT/None → NULL. **12 testes de
  regressão** adicionados (não havia teste para `_get_datetime` — por isso passou).
- **AÇÃO NECESSÁRIA:** migrações de Financeiro feitas em versões anteriores estão
  com as datas NULL no destino e precisam ser **refeitas** com esta versão.

### Performance — bulk insert no Financeiro (`fast_executemany`)
- `_inserir_financeiro` passou a gravar em **lote** via `cursor.executemany` com
  `fast_executemany=True` (envia o lote num único RPC — tipicamente 10-40× mais
  rápido). Padrão **híbrido**: se um lote falhar, desfaz e reprocessa **linha-a-linha
  só aquele lote**, isolando a(s) linha(s) ruim(s) sem perder as boas.
- Dedup de idempotência preservado, inclusive a semântica NULL do SQL e a
  deduplicação **dentro do próprio lote** (via conjunto de chaves pendentes).
- Medido: ~1.760 linhas/s no ambiente de teste (as ~140k do exemplo caem de 40+ min
  para ~1-2 min).

---

## [3.6.8] — 2026-07-13

### Correção preventiva — `_calc_cli_tipo` movido para o mixin (robustez headless)
- Uma varredura estática (AST) dos mixins de importação procurou a mesma assinatura
  dos bugs recentes: métodos/atributos que os mixins usam mas que só a **GUI** provê —
  quebrariam com `AttributeError` no importador *headless* (migração).
- Achado: **`_calc_cli_tipo`** (deriva `cliTipo` de CPF/CNPJ — 11 díg = PF, 14 = PJ)
  era definido só na `JanelaClientes`, mas o `ClientesImportMixin` o chama em 4 pontos.
  `ClientesImportadorHeadless._inserir_clientes()`/`_atualizar_clientes()` quebrariam
  se rodassem headless. **Dormente hoje** (a migração de clientes usa cópia direta,
  não o importador), mas era uma mina.
- Correção: `_calc_cli_tipo` (lógica pura) passou para o `ClientesImportMixin`. Como
  `JanelaClientes` herda o mixin, a GUI mantém o método por herança; o headless também
  passa a tê-lo. Removido o código morto `elif entidade == "clientes"` em `_migrar_entidade`
  (clientes já retornava antes, por cópia direta). Teste de regressão adicionado.
- Os demais candidatos da varredura são falsos positivos (usos dentro de
  `after(0, lambda…)`, que no headless nunca executam) ou já corrigidos.

---

## [3.6.7] — 2026-07-13

### Correção — botão "Iniciar Migração" sumia no diálogo de opções
- No wizard **Confirmar migração — opções**, quando **Produtos não estava marcado**
  (ex.: Clientes + Permissões + Financeiro), a janela era criada com **460px** de
  altura, mas o conteúdo precisa de ~518 (cabeçalho + scroll de 340 + mensagem +
  botões) → os botões **Iniciar Migração / Cancelar ficavam cortados**. Agravava o
  problema o `scroll` ser empacotado **antes** dos botões com `expand=True`, ficando
  com todo o espaço livre.
- **Correção:** o rodapé (botões + mensagem de erro) agora é **fixo** — empacotado
  com `side="bottom"` **antes** do scroll, garantindo o espaço dele. O scroll passa a
  ocupar só o que sobra (encolhe e rola). O botão fica **sempre visível**, em qualquer
  combinação de opções. Altura do diálogo ajustada (560 / 520 / 420 conforme as seções).

### Verificado (sem alteração) — fabricante / grupo / subgrupo na importação de produtos
- Confirmado por teste real: quando informados no arquivo, são **criados** em
  `fabricante`, `grupoProd` e `subGrupoProd`, e os ids gerados são **vinculados ao
  produto** (`proFab`, `proGrupo`, `proSubGrupo`); o subgrupo fica ligado ao grupo
  (`sgpIdGdp`). Idem para a classe (`proClasseId`). Sem erros.

---

## [3.6.6] — 2026-07-06

### Migração de clientes — cópia COMPLETA de `cliente` e `cliente_empresa`
- **Antes:** a migração de clientes copiava só ~18 campos (o cadastro básico, os
  mesmos do import por arquivo). Os outros **400+ campos** de `cliente` ficavam
  NULL/default no destino (endereço de cobrança, limite de crédito, celular, obs,
  data de nascimento, tabela de preço, etc.), e `cliente_empresa` era criada **zerada**.
- **Agora:** copia **TODAS as colunas** (exceto *computed*) de `cliente` (440) e
  `cliente_empresa` (18), mantendo os `cliId`/`cleId` (via `IDENTITY_INSERT`), lendo a
  origem em *streaming* (não carrega tudo na memória).
- Passa a **desabilitar também as FKs de saída** (`cliVendPref`, `cliTabPreco`,
  `cliImpostoId`…) durante a cópia, reabilitando ao final (sem validar quando a linha
  referenciada não existe no destino — mesmo padrão já usado para as FKs de entrada).
- `cliente_empresa` é copiada da origem para a empresa do destino (`empId` remapeado);
  cliente sem vínculo na origem recebe uma linha mínima (mantém o vínculo).
- Novos helpers `_colunas_completas` e `_fks_da_tabela` em `mi_migracao.py`.

---

## [3.6.5] — 2026-07-06

### Correção — migração do Financeiro travava e o Cancelar não parava
Bancos com dezenas de milhares de lançamentos (ex.: 140k+) faziam a migração do
Financeiro parecer "travada" por 40+ min, e o botão **Cancelar** não tinha efeito.
Causas e correções:
- **Cancelar não propagava:** setava o `_cancelado` da janela, mas o loop roda num
  importador *headless* com o `_cancelado` **dele**. Agora `_pedir_cancelamento`
  propaga para `_imp_atual._cancelado` → o loop para na próxima linha.
- **Log por linha inundava a GUI:** cada "CPF/CNPJ não encontrado — pulado" (e cada
  erro) era logado via `after()`; com 140k linhas, a fila do Tk entupia e a interface
  congelava (o clique no Cancelar mal era processado). Agora os logs por linha são
  **amostrados** (primeiros 5 + a cada 500/50); todos seguem no relatório/CSV e no
  resumo. Vale para produtos/clientes/financeiro.
- **AttributeError no fim do Financeiro:** `_aviso_nao_encontrados` (método só da GUI)
  era acessado no headless quando havia linhas não encontradas. Corrigido (lazy + guard).

### Performance — Financeiro
- **Cache de lookup CPF→cliId** por execução (a tabela cliente não muda durante o
  INSERT do financeiro) — evita 1 SELECT por linha.
- **Commit em lote** (a cada 500) em vez de por linha, com **savepoint por linha** que
  preserva o isolamento de erro (linha ruim é desfeita sozinha, sem derrubar o lote).

---

## [3.6.4] — 2026-07-06

### Correção — migração Max→Max travava nos Produtos (`log_lines`)
- A migração de **Produtos/Financeiro** (que usa importadores *headless*) parava logo
  no primeiro log do INSERT com `AttributeError: 'ProdutosImportadorHeadless' object
  has no attribute 'log_lines'`.
- **Causa:** a `JanelaMigracao` injeta seu `_log`, que **espelha** cada linha em
  `_imp_atual.log_lines` (relatório da entidade), mas `_ImportadorHeadless.__init__`
  nunca criava esse atributo.
- **Correção:** o headless agora inicializa `log_lines = []`. **Clientes/Permissões**
  não eram afetados (usam cópia direta cross-database).
- Adicionado **teste de regressão sem banco** (o gate padrão `-m "not db"` não cobria
  o caminho de migração, que exige banco).

---

## [3.6.3] — 2026-07-06

### Correção — pasta de logs padrão no `.exe` (C:\Max\MaxImporta\Log)
- **Bug:** instalado como `.exe` (PyInstaller *one-file*), o app **não** usava
  `C:\Max\MaxImporta\Log` como padrão e a configuração **não persistia**. Causa: o
  caminho base era derivado de `__file__`, que no one-file aponta para a pasta
  **temporária** de extração (`sys._MEIPASS`) — apagada ao fechar. Logo o `Log` e o
  `max_importa.ini` iam parar na temp.
- **Correção:** quando *frozen*, o caminho base passa a ser a pasta **real do
  executável** (`os.path.dirname(sys.executable)`). Instalado em `C:\Max\MaxImporta`,
  o padrão volta a ser `C:\Max\MaxImporta\Log` e o `.ini` persiste ao lado do exe.

### Novo — pergunta antes de criar a pasta de logs
- Na abertura, se a pasta de logs não existir, um diálogo **Sim/Não** pergunta se deve
  criá-la (e grava o caminho no `.ini`). O "Configurar pasta de logs" também pergunta
  antes de criar uma pasta inexistente. Gravações mantêm rede de segurança
  (`makedirs`) para não quebrar se a pasta for removida durante o uso.

### Correção — truncamento de `cliFatEndNumero` (número do endereço)
- A coluna real é `varchar(10)`, mas o INSERT truncava em **20** e o UPDATE **não
  truncava** — um número de endereço longo causaria erro 22001 (dados truncados) no
  banco. Agora corta corretamente em **10** no INSERT e no UPDATE de clientes.

---

## [3.6.2] — 2026-07-05

### Visual — Clean Corporate agora aplica as superfícies (correção)
- Na 3.6.1 só os **acentos** (vermelho/tons) tinham mudado; janela, cards e inputs
  seguiam no cinza do tema interno do CustomTkinter — no claro a diferença ficava quase
  imperceptível.
- Agora o tema sobrescreve as **superfícies** (uma função no startup): janela = página
  clara (`#F7F8FA`/`#16181C`), **cards brancos** (`#FFFFFF`/`#1D2025`), inputs/combos/
  textbox/checkbox/scroll/segmented no padrão Clean Corporate. Botões seguem o vermelho da
  marca (`#CC0000`). Sem alterar nenhuma função — só tema.

---

## [3.6.1] — 2026-07-05

### Visual — tema "Clean Corporate" (paleta claro/escuro)
- Retematização para um visual mais limpo/corporativo, **sem alterar nenhuma função ou
  lógica** — só cores/tons e a fonte do log.
- Paleta centralizada em `mi_config.py` passou a usar **tuplas `(claro, escuro)`** — o
  CustomTkinter alterna sozinho; o botão de tema do menu deixa os dois modos consistentes.
- **Vermelho da marca mantido** (`#CC0000` no claro, `#E5433D` no escuro), agora como
  **acento** e não plano de fundo. Fundos obrigatório/chave em **vermelho suave** (fim do
  rosa saturado); texto principal mais nítido; verde de "campo mapeado" mais discreto.
- Modo padrão continua **claro**. Log em **Consolas** no lugar de Courier.

---

## [3.6.0] — 2026-07-05

### Mapeamento de colunas — feedback visual
- Nas telas de importação (**Produtos, Clientes, Financeiro**), cada campo do mapeamento
  mostra um **indicador**: **✓** (verde) mapeado · **✗** (vermelho) obrigatório não mapeado ·
  **—** (cinza) opcional não mapeado.
- A **linha inteira** do campo fica com um **verde suave** quando mapeada (volta à cor
  original ao desmapear).
- Um **resumo** abaixo da lista informa em tempo real: `✓ X/Y campos mapeados — todos os
  obrigatórios OK.` ou `⚠ X/Y — faltam obrigatórios: <lista>`.
- Atualiza a cada seleção de coluna e após o auto-mapeamento (ao carregar o arquivo).

---

## [3.5.0] — 2026-07-04

### Auditoria no destino — tabela `MaxImporta_Auditoria`
- Ao final de cada **migração**, registra no próprio banco de **destino** o que foi
  feito, numa tabela **criada automaticamente** (`dbo.MaxImporta_Auditoria`, prefixo
  próprio — não colide com o MaxData).
- **Uma linha por entidade migrada**: data/hora, versão, origem, destino, **usuário SQL**
  (`SUSER_SNAME()`), entidade, inseridos/pulados/erros, cancelada, e `audSessao` (agrupa
  a execução).
- Histórico acumulado (a tabela é reaproveitada). Registro **best-effort** — não
  interrompe a migração se falhar.
- Consulta: `SELECT * FROM MaxImporta_Auditoria ORDER BY audDataHora DESC`.

---

## [3.4.0] — 2026-07-04

### Logs estruturados — exportação em JSON e CSV (além do `.txt`)
- Ao concluir cada importação (**Produtos/Clientes/Financeiro**), além do
  `RELATORIO_*.txt`, são gerados na pasta de logs:
  - `RESULTADO_<OP>_<data_hora>.json` — resumo estruturado: versão, banco, contagens
    (inseridos/pulados/erros), itens com erro e, no Financeiro, os CPF/CNPJ não encontrados.
  - `ERROS_<OP>_<data_hora>.csv` — itens com erro em CSV (abre no Excel; UTF-8 com BOM),
    quando houver erros.
- Na **migração**: `RESULTADO_MIGRACAO_<data_hora>.json` com os **totais por entidade**,
  origem e se foi cancelada.
- Exportação **best-effort**: se falhar, só registra um aviso e não interrompe a operação.

---

## [3.3.0] — 2026-07-04

### Progresso por registro — contador "X de Y (NN%)"
- Além da barra, um **rótulo** mostra em tempo real quantos registros já foram
  processados — ex.: `1.250 de 8.000 (15%)`.
- Vale para os 3 importadores (**Produtos, Clientes, Financeiro**), incluindo os
  UPDATEs. Na **migração**, mostra a etapa com o nome da entidade — ex.:
  `Clientes — 1 de 5 (20%)`.
- Reinicia (`iniciando...`) a cada operação; atualização thread-safe (agendada na GUI).

---

## [3.2.2] — 2026-07-04

### Login — Botão "Confirmar Banco e Avançar" só após validar
- O botão **"Confirmar Banco e Avançar"** agora **aparece somente após a conexão ser
  validada** (credenciais OK e bancos listados). Antes ficava sempre visível, apenas
  desabilitado.
- Some novamente ao **trocar credenciais**, em **falha de conexão** ou quando **nenhum
  banco** é encontrado — reforçando que é preciso conectar de novo.

---

## [3.2.1] — 2026-07-04

### Segurança — Credenciais de conexão
- A **senha padrão saiu do binário**. Antes o app trazia usuário **e senha fixos no
  código** (extraíveis do `.exe`). Agora só o usuário `sa` (não é segredo) é sugerido;
  a **senha começa vazia** e é digitada pelo usuário.
- Novo seletor de **autenticação** em *Editar credenciais*:
  - **SQL Server** (usuário + senha), ou
  - **Windows** (integrada — `Trusted_Connection`, **sem senha**; campos usuário/senha
    ficam desabilitados e nada sensível é guardado).
- Novo **"Lembrar credenciais nesta máquina"**: salva servidor/usuário/modo no
  `max_importa.ini` e a **senha criptografada via Windows DPAPI** (`CryptProtectData`).
  O texto cifrado só é decifrável pelo **mesmo usuário Windows, na mesma máquina** — não
  fica em texto puro nem é portável. Sem "lembrar", a seção `[Conexao]` é **removida**.
  Criptografia via `ctypes` (API nativa do Windows) — **sem dependência nova**.
- Connection string centralizada em `_montar_base_conn_str` (login/menu/migração
  reaproveitam a mesma base; SQL auth idêntico ao anterior).

---

## [3.2.0] — 2026-07-04

### Botão Cancelar — interromper importação/migração com segurança
- Todas as janelas (**Produtos, Clientes, Financeiro e Migração**) ganharam um botão
  **"⏹ Cancelar"**, habilitado apenas enquanto uma operação está em andamento.
- Cancelamento **cooperativo**, apenas em pontos **seguros**:
  - **Importadores** (Produtos/Clientes/Financeiro): **entre registros**. Como o commit
    é por linha, os registros já gravados permanecem e nada fica pela metade.
  - **Migração**: **entre entidades**. A entidade em andamento é concluída inteira
    (banco consistente, FKs reabilitadas) e as restantes **não** são executadas. Não
    interrompe no meio de uma entidade (FKs desabilitadas, `IDENTITY_INSERT`, commits em
    lote) para não deixar o destino inconsistente.
- Migração cancelada mostra **título/mensagem próprios**, lista no log as entidades não
  migradas e só faz a **conferência** (origem × destino) das entidades efetivamente migradas.
- O botão é **rearmado automaticamente** a cada nova operação.

---

## [3.1.5] — 2026-07-04

### Migração — Performance
- **Permissões** e **Códigos de Barras** passaram a ser copiados via
  **cross-database `INSERT...SELECT`** (uma única instrução — origem e destino na
  mesma instância) em vez de linha a linha. Ex.: ~907 permissões em ~0,2s. A guarda
  de FK continua (só copia registros cujo `cliId`/`proId` exista no destino).
- **Produtos:** cache em memória (por execução) dos lookups de **NCM/CEST**. Como é
  somente leitura, é seguro e elimina milhares de SELECTs repetidos em catálogos
  grandes (1000 lookups → 3 SELECTs no teste).

---

## [3.1.4] — 2026-07-04

### Migração — Idempotência do Financeiro (não duplica)
- Na migração de **Financeiro**, antes de inserir cada lançamento, verifica se já
  existe um **igual** no destino e, se existir, **pula** (não duplica). Rodar a
  migração 2× (ex.: após falha) **não gera lançamentos repetidos**.
- Chave: `empId + pgtClienteId + pgtValor + pgtData + pgtVecmto + pgtNumDoc + pgtTipoConta`.
- A importação por **arquivo** continua sem dedup (inalterada); o dedup vale só na migração.

---

## [3.1.3] — 2026-07-03

### Migração — Backup automático e FKs desabilitadas
- **Backup automático** do banco de destino antes de migrar (opção no wizard, marcada
  por padrão): gera um `.bak` **COPY_ONLY** na pasta de backup padrão do SQL Server.
  Se o backup falhar, a migração é **abortada por segurança**.
- **Pré-flight:** ao iniciar, detecta FKs **desabilitadas** (`is_disabled=1`) no destino
  — sinal de migração anterior **interrompida** — e oferece **reabilitá-las** (com
  validação). Ignora as apenas "não confiáveis" (`is_not_trusted`), normais no MaxData.

---

## [3.1.2] — 2026-07-02

### Migração — Wizard de decisões antecipadas (execução não assistida)
- Todas as perguntas que antes apareciam **durante** a migração foram movidas para
  um **único diálogo antes de iniciar** (wizard). A migração roda do início ao fim
  **sem interação** — ideal para bases grandes.
- O wizard coleta: **Clientes** (ciência da limpeza + política de duplicados) e
  **Produtos** (estoque migrar/zerar + negativos zerar/manter).
- O aviso de "acerto de estoque gerado" **não interrompe mais o fluxo**: vai para o
  log e para o **resumo final** da migração.

---

## [3.1.1] — 2026-07-02

### Migração — NCM/CEST faltantes (evita perda fiscal silenciosa)
- Ao migrar **Produtos**, o sistema **copia** da origem para o destino os cadastros
  de **NCM** (`proNCM`) e **CEST** (`proCEST`) usados pelos produtos que não existem
  no destino — assim o produto migra com o NCM/CEST correto (antes ficava
  `proNcmId`/`proCestId = NULL` sem avisar, impedindo emissão fiscal).
  - Copia só os códigos **usados e faltantes**; o id é gerado pelo destino; colunas
    de identity e de auditoria são ignoradas.
- A **conferência pós-migração** passou a incluir "produtos sem NCM (proNcmId nulo)"
  no destino, com alerta quando > 0.

---

## [3.1.0] — 2026-07-02

### Migração — Conferência ORIGEM × DESTINO (reconciliação)
- Ao final da migração, o sistema **confere automaticamente** a origem contra o
  destino e mostra o comparativo na tela, no log e no `RELATORIO_MIGRACAO_*.txt`:
  - **Contagens:** `cliente`, `cliente_empresa`, `UsuarioPermissao`, `produto`,
    `codBarras`, `vendaPgto`;
  - **Somas:** estoque (`SUM proEstoqueAtual` por empresa) e financeiro
    (`SUM pgtValor`).
- Status por linha: **✅ confere**, **ℹ️ diferença esperada** (ex.: estoque zerado
  por opção do usuário) ou **⚠️ divergente** (com a possível causa).
- Só confere as entidades migradas na execução.

---

## [3.0.4] — 2026-07-02

### Migração — Códigos de Barras (codBarras)
- Nova opção **"Códigos de Barras"** na migração: copia o conteúdo **completo** da
  tabela `codBarras` (todos os códigos de cada produto), com a **mesma lógica das
  permissões** (limpa o destino + cópia idêntica; o `cdbId` é gerado pelo destino).
- Ordem: `Clientes → Permissões → Produtos → Códigos de Barras → Financeiro`
  (codBarras entra após Produtos por causa da FK `cdbIdProd → produto.proId`).
- Ignora (sem erro) códigos cujo produto não existe no destino; `cdbProUnId`
  inexistente vira NULL. Desabilita a FK `proLote → codBarras` para permitir a
  limpeza e a reabilita ao final.

---

## [3.0.3] — 2026-07-02

### Migração de Clientes — limpeza robusta (FK) e Permissões idênticas
- **Corrige** o erro `DELETE conflitou com a restrição REFERENCE fk_UsuarioPermissao…`
  ao limpar o destino. Num banco "zero", os usuários-base são referenciados por
  **284 FKs** — limpar só a `UsuarioPermissao` não bastava.
- A migração de Clientes agora **desabilita temporariamente** as FKs que referenciam
  `cliente`/`cliente_empresa`, **limpa** `UsuarioPermissao` + `cliente_empresa` +
  `cliente`, insere idêntico (mantendo os `cliId`) e **reabilita** as FKs (validando;
  como os cliId são preservados, as referências das demais tabelas seguem válidas).
- **`UsuarioPermissao`** passou a ser **limpa e recopiada idêntica** à origem.
- Permissões entram **automaticamente** quando Clientes é migrado.

---

## [3.0.2] — 2026-07-01

### Migração de Produtos — estoque e acerto automático
- Ao iniciar a migração de **Produtos**, pergunta se deseja **migrar o estoque atual**
  (`proEstoqueAtual`):
  - **Não** → todos os produtos entram com estoque **zero** no destino.
  - **Sim** → se houver produtos com estoque **negativo** na origem, pergunta se
    deseja iniciá-los com zero (Sim = zera só os negativos | Não = mantém da origem).
- Após concluir a migração de produtos, se houver estoque > 0 no destino, gera
  automaticamente o **acerto de estoque PENDENTE** (status `'A'`) com esses produtos
  e avisa o usuário para **rodar o acerto no Manager**.

---

## [3.0.1] — 2026-07-01

### Migração de Clientes — modo "banco zero"
- A migração de **Clientes** passou a ser uma **cópia idêntica com limpeza do destino**:
  - Antes de iniciar, **avisa** que `cliente` e `cliente_empresa` do destino serão
    **apagadas** e sugere usar um **banco zerado**.
  - Após ciência, **limpa** as duas tabelas (em transação — se houver dados
    relacionados/FK, a limpeza é bloqueada e nada é apagado) e **reseta os identities**
    (`DBCC CHECKIDENT reseed 0` → começa do 1).
  - Copia **todos os `cliId`** (inclusive 1–10) idênticos à origem, **sem** validação
    de obrigatórios e **sem** a regra de cliId reservado.
  - **Duplicados** (`cliNome` + `cliCpfCgc`): pergunta se deseja **desativar** os
    repetidos (mantém ativo só o mais novo — maior cliId — e `cliDesativa = -1` nos
    demais) ou manter todos.

---

## [3.0.0] — 2026-07-01 — Migração entre Bancos MaxData

### Novo módulo — Migração banco → banco
- Copia dados direto de um banco para outro da **mesma instância SQL**, sem arquivo.
- Escolha de **origem** e **destino**; migra **Clientes, Permissões, Produtos, Financeiro**.
- Ordem: `Clientes → Permissões → Produtos → Financeiro`.
- Reutiliza a lógica de INSERT dos importadores.

### Resiliência a schema + relatório
- SELECTs de origem **montados dinamicamente**; colunas ausentes viram `NULL`
  (funciona entre versões/schemas diferentes do MaxData).
- **Sempre** gera `RELATORIO_MIGRACAO_*.txt`, inclusive em erro.

### Permissões e totais
- Opção **Permissões de Usuário** (`UsuarioPermissao`): pula existentes; ignora
  (sem erro) usuários inexistentes no destino.
- **Totais consolidados** na tela ao final.

### Acerto de estoque (produtos)
- Após import/update de produtos com sucesso, se houver `proEstoqueAtual > 0`,
  habilita **"Gerar Acerto de Estoque"** (cria acerto PENDENTE para rodar no Manager).

### Correções
- Tela de login redimensionada (botão "Confirmar Banco" visível).

---

## [2.1.0] — 2026-07-01 — Baseline (pré-migração)

### Produtos
- `proId` vazio segue a numeração do banco (IDENTITY via `SCOPE_IDENTITY`).
- **Unidade** inexistente cadastrada automaticamente em `produtoUn`.
- **Corte automático** de textos longos (fim do erro "dados truncados").

### Clientes
- Novo campo **`cliTipo`** (0=PF, 1=PJ); derivado do CPF/CNPJ quando não mapeado.
- Campos **Fantasia / RG / Número** com tratamento interativo (não bloqueiam).

### Mensagens / Logs
- Mensagens de erro de obrigatórios **amigáveis** (3 importadores).
- Relatório + `ERROS_*` gerados também na falha de validação.
- Arquivo importado **renomeado** com status + data/hora; seleção limpa na tela.

### Build
- `BUILD.bat` instala o **Python** automaticamente e se reabre **sem elevação**.
- **Pillow** empacotado no `.exe` (fim do erro "No module named 'PIL'").
- **Ícone** do X da MaxData aplicado ao `.exe`.
