# Cobertura de campos — levantamento para revisão

> Documento de **análise** (nada foi alterado no código ainda). Objetivo: decidir,
> por entidade, quais colunas passar a importar/migrar. Baseado no schema real do
> MaxData e no uso real em `MAX_CENTRAL` (3.015 clientes, 19.205 produtos,
> 73.631 lançamentos). O `BD_ZERO` foi usado para as regras de obrigatoriedade.

## Resumo executivo

- ✅ **Nenhum gap crítico:** nenhuma coluna **NOT NULL sem default** está de fora em
  nenhuma tabela. As importações **não falham** por campo faltando — tudo que falta é
  **opcional** (aceita NULL) ou tem default no banco.
- As tabelas são enormes (padrão MaxData): cliente **433**, produto **266**,
  vendaPgto **192**, produto_empresa **115**, cliente_empresa **18** colunas.
- Hoje o importador grava um subconjunto enxuto (ver abaixo). A maioria das colunas
  restantes é **operacional/sistema** ou **legado (`zzz_`)** e **NÃO deve** ser importada.

### O que o código grava hoje
| Tabela | Grava | de | Observação |
|---|---:|---:|---|
| cliente | 18 | 433 | dados cadastrais básicos |
| cliente_empresa | 9 | 18 | vínculo + rateio |
| produto | 19 | 266 | cadastro básico + fiscal (NCM/CEST/unid.) |
| produto_empresa | 18 | 115 | preços, estoque, códigos |
| vendaPgto | 14 | 192 | lançamento financeiro básico |

---

## Regras que DEVEM permanecer NULL (não mexer)

- **`pgtTipoVista` / `pgtTipoPrazo`** (vendaPgto): individualmente aceitam NULL; a regra
  é "ao menos um dos dois preenchido". Já tratado assim. **Manter.**
- **Auditoria** (todas as tabelas): `DataInclusao`, `DataUltAlteracao`,
  `DataUltAlteracaoNaoAtualizar`, `IdUuid` — populadas por trigger/sistema. **Não importar.**
- **Colunas `zzz_...`**: renomeadas/legado (desativadas). **Ignorar.**

---

## ⛔ NÃO importar (mesmo tendo dado) — e por quê

Estas aparecem preenchidas em MAX_CENTRAL, mas são **runtime/sistema** ou **FK** para
outras tabelas — importá-las quebraria integridade ou não tem sentido num cadastro novo:

- **vendaPgto — operacional/PDV/TEF/PIX/boleto:** `pgt_POS_*`, `pgtTef*`, `pgtPix*`,
  `pgtLote`, `pgtCaixa`, `pgtUsuLanc`, `pgtUsuarioQuitou`, `pgtDataLanc`, `pgtStatus`,
  `pgtSelecionado`, `pgtMarcado/pgtMarcou`, `pgtRemessa*`, `pgtSerasa*`, `pgtRecarga*`,
  `pgtBoleto*`, `pgtLoteEnvioConciliadora`, `pgtVendaId`, `pgtEntradaNf`, `pgt*Faturou`.
  → São dados de **cada transação/operação**, gerados pelo sistema. Não se "cadastram".
- **FK para outras tabelas:** `pgtPlcId`, `pgtCecId`, `pgtSubPc`, `pgtBancoRef`,
  `pgtAtendente`, `cliTabPreco`, `cliVendPref`, `cliRotaId`, `cliEmpIdCad`, `cliUsuCad`,
  `proIccId`, `proMunicipioIdIncidencia`, `proReferencia`, `proFormacaoPrecoId`,
  `proFarmaPrincipioAtivo`, `proFoodDepartamento`, `proEcommId/Status`, `proPedCompraVedId`.
  → Precisam do registro-alvo existir no destino; risco de FK inválida.
- **Credenciais/usuário do cliente:** `cliUsuSenha`, `cliUsuLoginId`, `cliUsuPerfil`,
  `cliVedWebUsuSenha`, `cliUsuIdPDV*`, `cliUsuFarmaciaPopular*` — clientes que também são
  **usuários do sistema**; sensível e já coberto pela migração de Permissões. **Não importar.**
- **Blobs/foto:** `cliImgFoto`, `proImgFoto`, `cliFoto`, `proFoto` (varbinary/caminho).
  → Fora de escopo de importação por arquivo `.txt`.

---

## ✅ Candidatos CADASTRAIS (gerais) — recomendados para avaliar

Preenchimento alto em MAX_CENTRAL, sem FK, sem sensibilidade — os que mais fazem falta:

### cliente
| Coluna | Tipo | % preench. | O que é |
|---|---|---:|---|
| `cliCelular` | varchar | 85,7% | **Celular** — ✅ mapeável desde a v4.1.2 |
| `cliFax` | varchar | 84,9% | Fax |
| `cliCobEnd`, `cliCobEndNumero`, `cliCobBairro`, `cliCobCidade`, `cliCobUf`, `cliCobCep`, `cliCobCidCodIBGE` | varchar/int | ~83% | **Endereço de cobrança** (hoje só grava o de faturamento) |
| `cliContNome1`, `cliContFone1`, `cliContDepto1` | varchar | 82,8% | Contato principal |
| `cliCadNomePai`, `cliCadNomeMae`, `cliCadNomeConjuge` | varchar | ~82% | Filiação (PF) |
| `cliCadSexo`, `cliCadEstCivil` | varchar | 57% | Sexo / estado civil (PF) |
| `cliIM` | varchar | 57% | Inscrição Municipal |
| `cliDeferidoIe` | varchar | 64% | Situação da IE |
| `cliObsGeral`, `cliObsNfe`, `cliMaxdataObs` | varchar | 57% | Observações (geral / p/ NF-e) |
| `cliRamoAtividade` | varchar | 57% | Ramo de atividade |
| `cliSite` | varchar | 57% | Site |

### produto
| Coluna | Tipo | % | O que é |
|---|---|---:|---|
| `proInfAdProd` | varchar | 100% | Informação adicional do produto (NF-e) |
| `proDescPdv` | varchar | 86,5% | Descrição no PDV |
| `proMsg`, `proMsg2` | varchar | 70% | Mensagens do produto |
| `proReferencia` (int) | int | 12% | ⚠️ confirmar se é FK |
| `proVolume`, `proEmbalagem`, `proApresentacao`, `proCodigoSKU`, `proGarantia`, `proLote` | varchar | 70% | Dados comerciais/logísticos |

### cliente_empresa
| Coluna | Tipo | % | O que é |
|---|---|---:|---|
| `cliObsVend` | varchar | 74,5% | Observação p/ o vendedor |

---

## 🧾 Candidatos FISCAIS — avaliar com o contador/uso real

### produto_empresa
| Coluna | % | O que é |
|---|---:|---|
| `proCodCSOSNProdutorRural`, `proCodCst2ProdutorRural` | 99,5% | CSOSN/CST p/ produtor rural |
| `proCurvaABC` | 99,1% | Curva ABC |
| `proExcCstPisSaidaPJ/PF`, `proExcCstCofinsSaidaPJ/PF` | 59% | CST PIS/COFINS por tipo de cliente |
| `proCodBeneficioFiscal` | 27% | Código de benefício fiscal |

### produto
| Coluna | % | O que é |
|---|---:|---|
| `proReducaoIcms`, `proIva`, `proIpi`, `proIpiEnt`, `proPauta` | 23–70% | Tributação (ICMS/IVA/IPI/pauta) |
| `proRegistroMS` | 70% | Registro MS (medicamento) |

### vendaPgto (só se migrar financeiro "aberto")
| Coluna | % | O que é |
|---|---:|---|
| `pgtHistorico` | 77,8% | Histórico do lançamento |
| `pgtPortador`, `pgtBanco`, `pgtAgencia`, `pgtContaC` | ~80% | Dados de cobrança/portador |
| `pgtValorJuros` | 61% | Juros |

---

## ⚠️ Segmento-específico — importar SÓ se o cliente for do ramo

Preenchidos conforme o ramo da loja; não faz sentido genérico:

- **Farmácia:** `proRegistroMS`, `proFarmaPosologia`, `proFarmaIndicacao`,
  `proFarmaPrincipioAtivo`, `proMedicamento*`, `proControlado`, `cliUsuFarmaciaPopular*`.
- **Food/Restaurante/Pizzaria:** `proFood*`, `proDescTamPizza`, `proQtdeSaborPizza`.
- **Agro:** `proAgro*`.
- **Posto de combustível:** `cliPostoPrecoComb1..10`, `cliPostoUsaPrecoDif`, `proCodCombANP`, `proDescricaoCombANP`.
- **Ótica:** `cliOticaArmacao*`, `cliOticaObs`.
- **Veterinário:** `cliVetCrmv`.
- **Crédito/Cadastro completo (PF):** `cliDadosProf*` (dados profissionais),
  `cliDadosBanc*` (dados bancários), `cliRefPes*`/`cliRefCom*` (referências),
  `cliSocio*` (sócios). Úteis para **carnê/crediário**.

---

## Próximo passo (aguardando sua escolha)

1. **Confirmar o conjunto CADASTRAL geral** (tabela ✅ acima) — é o mais seguro e útil.
2. Dizer se quer os **FISCAIS** (🧾) e quais.
3. Dizer o **segmento** do(s) cliente(s)-alvo para incluir os campos específicos (⚠️).

Para cada campo aprovado, incluo no INSERT/UPDATE do importador **e** no SELECT da
migração **e** nos modelos (`.txt`/`.xlsx`), com o mesmo tratamento de vazio (NULL quando
em branco), e adiciono/atualizo os testes de regressão.
