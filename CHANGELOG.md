# Histórico de versões — ConsultaImpressoras

Padrão das páginas de Release no GitHub:

- **Título:** `ConsultaImpressoras vX.Y.Z — resumo curto`
- **Tag:** `vX.Y.Z`
- **Texto:** data e lista de alterações
- **Anexo:** `ConsultaImpressoras.zip` somente na versão mais recente

---

## v1.0.22 — Gestor de Infraestrutura de TI e módulo Coletores
**Data:** 23/11/2026

- Tela inicial "Gestor de Infraestrutura de TI" com menu (Sistema, Módulos, Ajuda), caixa Sobre e os módulos Gestão Impressoras, Gestão APs e Gestão Coletores
- Gestão Impressoras: tela própria com botão "← Início"; a consulta começa ao entrar nesta tela
- Gestão APs: abre o mapa dos APs embutido
- Gestão Coletores: cadastro de coletores Zebra/Honeywell (setor, supervisor, modelo, série, versão do app, hostname, MAC Wi-Fi, usuário, piloto) e painel "Clique Aqui Coletores.html" com CSV
- Status online/offline dos coletores pelo MAC Wi-Fi, com o computador conectado na rede Wi-Fi dos coletores (`wifi_coletores` e `faixa_rede_coletores` no `config.json`), e aviso quando estiver fora dessa rede
- Painel e lista dos coletores com Online, Offline, Não verificado, Sem MAC, IP atual e "Visto online em"
- Setor e supervisor em caixa de seleção, compartilhados entre impressoras e coletores

## v1.0.21 — Plataforma Gerenciamento TI
**Data:** 21/11/2026

- O app passa a se chamar "Gerenciamento TI", com duas funções: consulta dos totalizadores das impressoras e Mapa dos APs
- Título da janela e do cabeçalho atualizados

## v1.0.20 — Mapa dos APs embutido no programa
**Data:** 21/11/2026

- O botão "Mapa dos APs" abre o mapa direto, sem precisar escolher arquivo
- Removido o botão "Trocar mapa"
- O botão do mapa aparece no relatório HTML desde a primeira consulta

## v1.0.19 — Botão do mapa dos APs
**Data:** 21/11/2026

- Botão "Mapa dos APs" no cabeçalho do app
- Botão do mapa no quadro "Data da consulta" do relatório HTML
- Título do botão configurável por CD no `config.json` (`mapa_aps_titulo`)

## v1.0.18 — Supervisor, painel de situação e tabela com colunas fixas
**Data:** 19/11/2026

- Campo Supervisor no cadastro, relatório, CSV, alertas e WhatsApp
- Painel "Situação das impressoras" com ONLINE/OFF-LINE, tinta e páginas
- Título "Inventário de Impressoras CD05" e arquivo "Clique Aqui Contadores.html"
- Tabela com o estado na coluna 1, as 4 primeiras colunas fixas e largura ajustada ao conteúdo
- A lista de impressoras mostra o estado da última consulta
- Removidos campos sem uso: cor, digitalizador, leitor de cartão, Epson Connect, bandeja 1, tamanho e tipo de papel
- Inclui as alterações preparadas para a v1.0.17, que não teve publicação própria

## v1.0.16 — Somente hostname
**Data:** 18/11/2026

- O nome do dispositivo foi substituído pelo hostname em todo o relatório
- Tabela renomeada para "Relatório por Setor x Dispositivos"

## v1.0.15 — Hostname no relatório
**Data:** 18/11/2026

- O hostname passou a aparecer no relatório de dispositivos

## v1.0.14 — Contadores e hostname no cadastro
**Data:** 18/11/2026

- Os contadores consultados ficam gravados no cadastro das impressoras

## v1.0.13 — Ajustes no relatório completo
**Data:** 18/11/2026

- Reorganização da tabela completa do relatório

## v1.0.12 — Leituras manuais das impressoras USB
**Data:** 18/11/2026

- Os relatórios são atualizados com as leituras digitadas para as impressoras USB

## v1.0.11 — Detecção de rede no Windows
**Data:** 18/11/2026

- Alternativa para detectar a sub-rede corporativa pelo Windows

## v1.0.10 — Número de série pelo MAC
**Data:** 18/11/2026

- O número de série das impressoras fica vinculado ao endereço MAC

## v1.0.9 — Correção da detecção de rede e leituras USB
**Data:** 18/11/2026

- Corrigida a detecção da rede corporativa
- Corrigido o relatório das leituras manuais das impressoras USB

## v1.0.8 — Contadores agrupados no relatório
**Data:** 17/11/2026

- Os contadores aparecem depois dos dados de identificação da impressora

## v1.0.7 — Cabeçalhos do relatório em destaque
**Data:** 17/11/2026

- Cabeçalhos das colunas do relatório completo em azul forte
- Linhas USB destacadas em azul e identificadas como não consultadas
- Alertas de falha e tinta com cores fortes

## v1.0.6 — Impressoras USB destacadas
**Data:** 17/11/2026

- Impressoras USB destacadas no relatório completo

## v1.0.5 — Impressoras USB fora da busca na rede
**Data:** 17/11/2026

- As impressoras USB deixam de ser consultadas pela rede

## v1.0.4 — Tipo de conexão
**Data:** 17/11/2026

- Seleção do tipo de conexão da impressora (CABO ou USB)

## v1.0.3 — Número de série e tela compacta
**Data:** 17/11/2026

- Cadastro do número de série das impressoras
- Tela principal mais compacta

## v1.0.2 — Gestão da impressora pelos alertas
**Data:** 17/11/2026

- Clicar no IP do painel de alertas abre a página de gestão da impressora

## v1.0.1 — Links para os IPs
**Data:** 17/11/2026

- Os IPs das impressoras viram links no relatório

## v1.0.0 — Primeira versão
**Data:** 16/11/2026

- Primeira publicação do aplicativo de monitoramento de impressoras
