# Consulta de impressoras Epson

Aplicativo para Windows que consulta impressoras Epson na rede, acompanha tinta e comunicação e gera relatórios HTML e CSV.

## Recursos

- Consulta status, consumíveis, identificação técnica, número de série e contadores.
- Destaca tinta vazia/baixa e falhas de comunicação; nível de papel fica apenas no detalhamento técnico.
- Gera relatório HTML com resumo, alertas prioritários e tabela final horizontal; também salva CSV. Os IPs no relatório e no e-mail abrem a página de gestão Epson, os links também seguem no WhatsApp, e o nível de tinta fica junto dos contadores.
- Cria rascunho de e-mail `.eml` com a tabela e abre conversas de WhatsApp com mensagem pronta. O envio é manual.
- Na tabela de alertas, clique diretamente no IP para abrir a página de gestão da impressora no navegador. A tabela destaca falhas de comunicação e alertas de tinta, com rolagem vertical e horizontal.
- O cadastro de impressoras inclui número de série: ele é extraído na consulta quando disponível, salvo no cadastro e pode ser digitado ou corrigido manualmente. Os identificadores (incluindo número de série, modelo e MAC) ficam agrupados com o IP nos relatórios, no e-mail e no WhatsApp.
- Interface compacta para mostrar os controles em uma tela, mantendo os oito alertas visíveis com rolagem interna. O cabeçalho informa a versão, o horário do executável e o desenvolvedor, e inclui um atalho para Releases.

## Download

Baixe o executável Windows na página de [Releases](https://github.com/christianocassio/buscacontadoresimpressoras/releases).

## Configuração inicial

Os valores de `config.example.json` são apenas exemplos: usam nomes genéricos e endereços reservados para documentação (`192.0.2.0/24`), que não apontam para impressoras reais. Os campos de e-mail e WhatsApp começam vazios.

Na primeira execução, o aplicativo copia essa configuração para:

`%APPDATA%\ConsultaImpressoras\config.json`

Cadastre os dispositivos reais e a faixa CIDR da rede da filial pelo botão **Gerenciar impressoras** e pelo arquivo de configuração. O número de série pode ser preenchido manualmente ou detectado durante a consulta. Informe os destinatários nos campos de e-mail e WhatsApp; vários contatos podem ser separados por ponto e vírgula. O limite de tinta padrão é 20%.

Uma configuração que já exista em `%APPDATA%\ConsultaImpressoras\config.json` é preservada. Não publique arquivos de configuração reais, relatórios ou dados de impressoras: eles podem conter contatos, endereços IP, números de série e endereços MAC.

## Executar a partir do código

Requisitos: Windows e Python 3.10 ou superior.

```powershell
py -m pip install -r requirements.txt
py consulta_impressoras.py
```

## Gerar o executável

No Windows, execute `gerar_exe.bat`. O script instala as dependências e gera:

`dist\ConsultaImpressoras.exe`

O executável incorpora somente `config.example.json`, sem configurações pessoais ou endereços de impressoras reais.

## Testes

```powershell
py -m unittest -v
```

## Rede e certificados

O computador precisa estar conectado à rede que alcança as impressoras, diretamente ou por VPN autorizada. A faixa corporativa deve ser configurada corretamente; a aplicação avisa e interrompe a consulta se o endereço de saída não pertencer a ela.

As páginas dos equipamentos são consultadas por HTTPS. Para compatibilidade com certificados locais, a validação do certificado está desativada (`verify=False`); a conexão é criptografada, mas a identidade do equipamento não é validada. Para uso em produção, alinhe a validação de certificados com a equipe de TI.

Os relatórios podem conter informações operacionais e identificadores dos dispositivos. Compartilhe-os apenas com destinatários autorizados.
