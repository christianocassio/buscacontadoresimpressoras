from email import policy
from email.parser import BytesParser
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import requests

import consulta_impressoras as app


HTML_PRODUTO = """
<html><head><title>WF-M5899 Series</title></head><body>
<dl>
<dt>Firmware :</dt><dd>08.41.DG12PC</dd>
<dt>Número de série :</dt><dd>SNTEST12345</dd>
<dt>Endereço MAC da rede :</dt><dd>02:00:00:00:00:01</dd>
<dt>Data e Hora :</dt><dd>16-11-2026 08:45 UTC+00:00</dd>
</dl>
</body></html>
"""

HTML_REDE = """
<html><body><table>
<tr><td>Nome do disposit. :</td><td>EPSONTEST01</td></tr>
</table></body></html>
"""

HTML_CONTADORES = """
<html><body><dl>
<dt><span>Número total de páginas&nbsp;:</span></dt><dd><div>11407</div></dd>
<dt><span>Número total de páginas a P&amp;B&nbsp;:</span></dt><dd><div>11407</div></dd>
<dt><span>Número total de páginas a Cor&nbsp;:</span></dt><dd><div>0</div></dd>
<dt><span>Número total de páginas de impressão em 2 faces&nbsp;:</span></dt><dd><div>3</div></dd>
<dt><span>Número total de páginas de impressão em 1 face&nbsp;:</span></dt><dd><div>11404</div></dd>
</dl></body></html>
"""


class ConsultaImpressorasTests(unittest.TestCase):
    def test_informacoes_de_versao_mostram_data_de_modificacao_do_executavel(self):
        with tempfile.TemporaryDirectory() as diretorio:
            executavel = Path(diretorio) / "ConsultaImpressoras.exe"
            executavel.touch()
            with (
                patch.object(app.sys, "frozen", True, create=True),
                patch.object(app.sys, "executable", str(executavel))
            ):
                informacoes = app.texto_versao_aplicativo()

        self.assertRegex(
            informacoes,
            rf"v{app.APP_VERSION} \|\s+\d{{2}}/\d{{2}}/\d{{4}} \d{{2}}:\d{{2}}"
        )
        self.assertIn(f"Desenvolvedor: {app.APP_DEVELOPER}", informacoes)

    def test_lista_rejeita_ips_duplicados(self):
        impressoras = [
            {"nome": "A", "setor": "TI", "host": "IMP-A", "ip": "10.0.0.1"},
            {"nome": "B", "setor": "RH", "host": "IMP-B", "ip": "10.0.0.1"},
        ]

        with self.assertRaisesRegex(ValueError, "cadastrado mais de uma vez"):
            app.validar_lista_impressoras(impressoras)

    def test_lista_preserva_numero_de_serie_e_adiciona_campo_vazio_em_cadastros_antigos(self):
        lista = app.validar_lista_impressoras([
            {
                "nome": "Impressora Pulmão", "setor": "TI", "host": "IMP-A",
                "ip": "10.0.0.1", "numero_serie": " SN-123 "
            },
            {"nome": "B", "setor": "RH", "host": "IMP-B", "ip": "10.0.0.2"},
            {
                "nome": "Outro Pulmão", "setor": "TI", "host": "IMP-C",
                "ip": "10.0.0.3", "tipo_conexao": "CABO"
            },
        ])

        self.assertEqual(lista[0]["numero_serie"], "SN-123")
        self.assertEqual(lista[1]["numero_serie"], "")
        self.assertEqual(lista[0]["tipo_conexao"], "USB")
        self.assertEqual(lista[1]["tipo_conexao"], "CABO")
        self.assertEqual(lista[2]["tipo_conexao"], "CABO")

    def test_tipo_conexao_aceita_apenas_opcoes_fixas(self):
        impressora = {
            "nome": "Impressora WiFi",
            "setor": "TI",
            "host": "IMP-WIFI",
            "ip": "10.0.0.1",
            "tipo_conexao": "wifi",
        }

        validada = app.validar_lista_impressoras([impressora])

        self.assertEqual(validada[0]["tipo_conexao"], "WIFI")
        self.assertEqual(app.TIPOS_CONEXAO, ("USB", "CABO", "WIFI"))
        with self.assertRaisesRegex(ValueError, "Tipo de conexão inválido"):
            app.validar_lista_impressoras([
                {**impressora, "tipo_conexao": "BLUETOOTH"}
            ])

    def test_verificacao_de_faixa_ignora_usb_mantida_no_cadastro(self):
        usb = {
            "nome": "Pulmão", "ip": "198.51.100.220", "tipo_conexao": "USB"
        }
        cabo = {
            "nome": "Impressora de rede", "ip": "10.0.0.20",
            "tipo_conexao": "CABO"
        }
        with patch.object(
            app, "obter_ips_de_rota", return_value=["10.0.0.15"]
        ) as obter_ips:
            ips, dentro_da_faixa = app.verificar_rede_corporativa(
                "10.0.0.0/24", [usb, cabo]
            )

        self.assertEqual(ips, ["10.0.0.15"])
        self.assertTrue(dentro_da_faixa)
        obter_ips.assert_called_once_with([cabo])

    def test_verificacao_sem_dispositivos_de_rede_nao_consulta_enderecos(self):
        with patch.object(app, "obter_ips_de_rota") as obter_ips:
            ips, dentro_da_faixa = app.verificar_rede_corporativa(
                "10.0.0.0/24",
                [{"nome": "Pulmão", "ip": "198.51.100.220", "tipo_conexao": "USB"}]
            )

        self.assertEqual(ips, [])
        self.assertFalse(dentro_da_faixa)
        obter_ips.assert_not_called()

    def test_atualiza_numero_de_serie_cadastrado_sem_apagar_valor_existente(self):
        config = {
            "impressoras": [
                {"ip": "10.0.0.1", "numero_serie": ""},
                {"ip": "10.0.0.2", "numero_serie": "SN-MANUAL"},
            ]
        }

        alterou = app.atualizar_seriais_cadastrados(config, [
            {"ip": "10.0.0.1", "numero_serie": "SN-AUTO"},
            {"ip": "10.0.0.2", "numero_serie": "-"},
        ])

        self.assertTrue(alterou)
        self.assertEqual(config["impressoras"][0]["numero_serie"], "SN-AUTO")
        self.assertEqual(config["impressoras"][1]["numero_serie"], "SN-MANUAL")

    def test_configuracao_preserva_contatos_configurados_e_remove_limite_de_papel(self):
        with tempfile.TemporaryDirectory() as pasta_temporaria:
            pasta_dados = Path(pasta_temporaria)
            (pasta_dados / "config.json").write_text(
                '{"email_padrao":"operador@example.com; ti@example.com",'
                '"whatsapp_padrao":"+44 7700 900123; +44 7700 900124","limite_papel":20}',
                encoding="utf-8",
            )
            with patch.object(app, "PASTA_DADOS", pasta_dados):
                config, caminho = app.carregar_config()

            self.assertEqual(
                config["email_padrao"],
                "operador@example.com; ti@example.com",
            )
            self.assertEqual(
                config["whatsapp_padrao"],
                "+44 7700 900123; +44 7700 900124",
            )
            self.assertNotIn("limite_papel", config)
            self.assertEqual(
                app.separar_whatsapp_numeros(config["whatsapp_padrao"]),
                ["447700900123", "447700900124"],
            )
            config_salva = app.json.loads(caminho.read_text(encoding="utf-8"))
            self.assertEqual(config_salva["email_padrao"], config["email_padrao"])
            self.assertNotIn("limite_papel", config_salva)

    def test_configuracao_inicial_usa_exemplo_generico_sem_contatos(self):
        with tempfile.TemporaryDirectory() as pasta_temporaria:
            with patch.object(app, "PASTA_DADOS", Path(pasta_temporaria)):
                config, caminho = app.carregar_config()

            self.assertEqual(config["email_padrao"], "")
            self.assertEqual(config["whatsapp_padrao"], "")
            self.assertEqual(config["faixa_rede_corporativa"], "192.0.2.0/24")
            self.assertEqual(config["impressoras"][0]["ip"], "192.0.2.220")
            self.assertEqual(config["impressoras"][0]["tipo_conexao"], "CABO")
            self.assertTrue(caminho.exists())

    def test_whatsapp_abre_conversa_para_cada_numero(self):
        with patch.object(app.webbrowser, "open", return_value=True) as abrir:
            app.abrir_whatsapp(
                "+44 7700 900123; +44 7700 900124",
                "Relatório de teste",
            )

        self.assertEqual(abrir.call_count, 2)
        urls = [chamada.args[0] for chamada in abrir.call_args_list]
        self.assertTrue(urls[0].startswith("https://wa.me/447700900123?text="))
        self.assertTrue(urls[1].startswith("https://wa.me/447700900124?text="))
        self.assertEqual(urls[0].split("?text=", 1)[1], urls[1].split("?text=", 1)[1])

    def test_abrir_gestao_impressora_abre_url_do_ip(self):
        with patch.object(app.webbrowser, "open", return_value=True) as abrir:
            url = app.abrir_gestao_impressora("192.0.2.220")

        self.assertEqual(
            url,
            "https://192.0.2.220/PRESENTATION/ADVANCED/COMMON/TOP",
        )
        abrir.assert_called_once_with(url, new=2)

    def test_abrir_gestao_impressora_rejeita_ip_invalido(self):
        with self.assertRaisesRegex(ValueError, "IPv4 inválido"):
            app.abrir_gestao_impressora('192.0.2.220"><script>')

    def test_extrai_nivel_de_tinta_do_atributo_acessivel_do_icone(self):
        pagina = """
        <html><body>
        <div>Preto (BK):</div>
        <div><img alt="Tinta baixa 15%"></div>
        </body></html>
        """

        dados = app.extrair_estado_produto(pagina)

        self.assertIn("Tinta baixa 15%", dados["tinta_preto"])

    def test_extrai_percentual_da_barra_visual_e_nao_confunde_cartucho(self):
        pagina = """
        <html><body>
        <ul class="inksection">
            <li class="tank">
                <div class="tank" style="background:linear-gradient(
                    to top, #000000 0%, #000000 84%, #FFFFFF 84%, #FFFFFF 100%
                );"></div>
                <div class="clrname">BK</div>
            </li>
        </ul>
        <dl>
            <dt>Preto (BK):</dt><dd>T12B1/T12C1</dd>
        </dl>
        </body></html>
        """

        dados = app.extrair_estado_produto(pagina)

        self.assertEqual(dados["tinta_preto"], "84%")
        self.assertEqual(app.gerar_alertas([{
            "nome": "Impressora 01",
            "setor": "Setor 01",
            "status": "Sucesso",
            "tinta_preto": dados["tinta_preto"],
        }]), [])

    def test_extrai_nome_do_dispositivo_e_numero_de_serie(self):
        identificacao = app.extrair_identificacao_dispositivo(HTML_REDE)
        estado = app.extrair_estado_produto(HTML_PRODUTO)

        self.assertEqual(identificacao["nome_dispositivo"], "EPSONTEST01")
        self.assertEqual(estado["numero_serie"], "SNTEST12345")

    def test_consulta_usa_lista_configurada_e_atualiza_progresso(self):
        lista = [
            {"nome": "Impressora 01", "setor": "Setor 01", "host": "PRINTER-01", "ip": "192.0.2.220"},
            {
                "nome": "Impressora 02", "setor": "Setor 02",
                "host": "PRINTER-02", "ip": "192.0.2.221",
                "numero_serie": "SN-OFFLINE-2"
            },
            {
                "nome": "Pulmão", "setor": "Setor 03",
                "host": "PRINTER-USB", "ip": "198.51.100.220",
                "tipo_conexao": "USB"
            },
        ]
        progresso = []

        class Resposta:
            status_code = 200

            def __init__(self, conteudo):
                self.content = conteudo.encode("utf-8")

        def fake_get(url, **kwargs):
            if "198.51.100.220" in url:
                raise AssertionError("USB printer must not be queried over the network")
            if "192.0.2.221" in url:
                raise requests.ConnectionError("falha simulada")
            if app.CAMINHO_ESTADO in url:
                conteudo = HTML_PRODUTO
            elif app.CAMINHO_CONTADOR in url:
                conteudo = HTML_CONTADORES
            else:
                conteudo = HTML_REDE
            return Resposta(conteudo)

        with patch.object(app.requests, "get", side_effect=fake_get):
            resultados = app.consultar_impressoras(
                progress_callback=lambda atual, total, nome: progresso.append((atual, total, nome)),
                lista_impressoras=lista,
            )

        self.assertEqual(resultados[0]["nome"], "Impressora 01")
        self.assertEqual(len(resultados), 2)
        self.assertEqual(resultados[0]["setor"], "Setor 01")
        self.assertEqual(resultados[0]["modelo"], "WF-M5899 Series")
        self.assertEqual(resultados[0]["mac"], "02:00:00:00:00:01")
        self.assertEqual(resultados[0]["nome_dispositivo"], "EPSONTEST01")
        self.assertEqual(resultados[0]["numero_serie"], "SNTEST12345")
        self.assertEqual(
            [resultados[0][chave] for chave in (
                "total_geral", "total_pb", "total_cor", "total_2faces", "total_1face"
            )],
            ["11407", "11407", "0", "3", "11404"],
        )
        self.assertTrue(resultados[1]["status"].startswith("Falha de comunicação"))
        self.assertEqual(resultados[1]["setor"], "Setor 02")
        self.assertEqual(resultados[1]["numero_serie"], "SN-OFFLINE-2")
        self.assertEqual(progresso, [(1, 2, "Impressora 01"), (2, 2, "Impressora 02")])

    def test_whatsapp_inclui_localizacao_e_contadores_sem_alerta_de_tinta(self):
        item = {
            "nome": "Impressora 1",
            "setor": "Setor A",
            "modelo": "WF-M5899 Series",
            "host": "PRINTER-01",
            "ip": "192.0.2.220",
            "mac": "02:00:00:00:00:01",
            "nome_dispositivo": "EPSONTEST01",
            "numero_serie": "SNTEST12345",
            "status": "Sucesso",
            "tinta_preto": "15%",
            "total_geral": "11407",
            "total_pb": "11407",
            "total_cor": "0",
            "total_2faces": "3",
            "total_1face": "11404",
        }

        falha = {
            **item,
            "nome": "Impressora 02",
            "setor": "Setor B",
            "host": "PRINTER-02",
            "ip": "192.0.2.221",
            "status": "Falha de comunicação: timeout",
        }
        mensagem = app.montar_whatsapp_body([item, falha], "16/11/2026")

        for valor in (
            "WF-M5899 Series", "Setor A", "PRINTER-01",
            "192.0.2.220", "02:00:00:00:00:01", "11407", "11404"
        ):
            self.assertIn(valor, mensagem)
        self.assertIn("*⚠️ IMPRESSORAS SEM COMUNICAÇÃO — ACIONAR O TI DA FILIAL*", mensagem)
        self.assertIn("*Impressora 02 — SEM COMUNICAÇÃO*", mensagem)
        self.assertIn("Setor: Setor B", mensagem)
        self.assertIn(
            "IP: 192.0.2.221 | Gestão: https://192.0.2.221/PRESENTATION/ADVANCED/COMMON/TOP | "
            "MAC: 02:00:00:00:00:01",
            mensagem,
        )
        self.assertIn("Nome do dispositivo: EPSONTEST01", mensagem)
        self.assertIn("Número de série: SNTEST12345", mensagem)
        self.assertNotIn("*⚠️ IMPRESSORAS COM TINTA VAZIA OU BAIXA*", mensagem)
        self.assertIn("Identificação: Impressora 1 | Modelo: WF-M5899 Series", mensagem)
        self.assertIn(
            "Setor físico: Setor A",
            mensagem,
        )
        self.assertIn(
            "Hostname: PRINTER-01 | IP: 192.0.2.220 | "
            "Gestão: https://192.0.2.220/PRESENTATION/ADVANCED/COMMON/TOP | "
            "MAC: 02:00:00:00:00:01",
            mensagem,
        )
        self.assertIn("Tinta preta: 15%", mensagem)
        self.assertIn(
            "Contadores — Total: 11407 | P&B: 11407 | Cor: 0 | 2 faces: 3 | 1 face: 11404",
            mensagem,
        )
        self.assertNotIn("Setor físico | Hostname | IP", mensagem)
        self.assertLess(
            mensagem.index("*⚠️ IMPRESSORAS SEM COMUNICAÇÃO"),
            mensagem.index("*DETALHAMENTO COMPLETO*"),
        )

    def test_rascunho_email_cria_eml_com_tabela_e_contador_destacado(self):
        item = {
            "nome": "Impressora 01",
            "setor": "Tecnologia <teste>",
            "modelo": "WF-M5899 Series",
            "host": "PRINTER-01",
            "ip": "192.0.2.220",
            "mac": "02:00:00:00:00:01",
            "nome_dispositivo": "EPSONTEST01",
            "numero_serie": "SNTEST12345",
            "firmware": "08.41.DG12PC",
            "status": "Sucesso",
            "estado_impressora": "Pronta",
            "estado_digitalizador": "-",
            "leitor_cartao": "-",
            "epson_connect": "-",
            "tinta_preto": "80%",
            "caixa_manutencao": "OK",
            "nivel_papel": "Restante",
            "nivel_papel_bandeja1": "Restante (80%)",
            "tamanho_papel": "A4",
            "tipo_papel": "Papel Normal",
            "total_geral": "11407",
            "total_pb": "11407",
            "total_cor": "0",
            "total_2faces": "3",
            "total_1face": "11404",
            "data_hora": "16-11-2026 08:45",
        }
        corpo = app.montar_email_body([item], "16/11/2026", "relatorio.html", "relatorio.csv")

        for rotulo in (
            "Setor físico", "Hostname", "IP", "Número total de páginas",
            "P&amp;B", "Cor", "Impressão em 2 faces", "Impressão em 1 face",
            "Nome do dispositivo", "Número de série", "Modelo", "MAC",
            "Firmware", "Status", "Estado da impressora", "Estado do digitalizador",
            "Leitor de cartão", "Epson Connect", "Tinta preta", "Caixa de manutenção",
            "Nível de papel geral", "Bandeja 1", "Tamanho do papel", "Tipo de papel",
            "Data/hora da impressora"
        ):
            self.assertIn(rotulo, corpo)
        self.assertIn('<th scope="col"', corpo)
        self.assertLess(corpo.index("Setor físico"), corpo.index("Hostname"))
        self.assertLess(corpo.index("Hostname"), corpo.index(">IP<"))
        self.assertLess(corpo.index(">IP<"), corpo.index(">Nome do dispositivo<"))
        self.assertLess(corpo.index(">Número de série<"), corpo.index(">MAC<"))
        self.assertLess(corpo.index(">MAC<"), corpo.index(">Número total de páginas<"))
        self.assertLess(corpo.index("Impressão em 1 face"), corpo.index("Tinta preta"))
        self.assertEqual(corpo.count(">Tinta preta<"), 1)
        self.assertIn(">Identificação<", corpo)
        self.assertEqual(corpo.count('<tr class="linha-impressora">'), 1)
        self.assertIn('overflow-x:auto', corpo)
        self.assertIn('min-width:2400px', corpo)
        self.assertIn('class="contador-paginas"', corpo)
        self.assertIn("background:#fff1b8", corpo)
        self.assertIn("Tecnologia &lt;teste&gt;", corpo)
        self.assertIn("EPSONTEST01", corpo)
        self.assertIn("SNTEST12345", corpo)
        self.assertIn(
            'href="https://192.0.2.220/PRESENTATION/ADVANCED/COMMON/TOP"',
            corpo,
        )
        self.assertNotIn("Tecnologia <teste>", corpo)

        with tempfile.TemporaryDirectory() as pasta_temporaria:
            with patch.object(app, "PASTA_DADOS", Path(pasta_temporaria)):
                with patch.object(app.os, "startfile") as abrir_arquivo:
                    caminho_eml = app.abrir_email(
                        "ti@example.com; suporte@example.com",
                        corpo,
                    )
                    abrir_arquivo.assert_called_once_with(str(caminho_eml))

            with caminho_eml.open("rb") as arquivo:
                mensagem = BytesParser(policy=policy.default).parse(arquivo)

            self.assertEqual(
                [endereco.addr_spec for endereco in mensagem["To"].addresses],
                ["ti@example.com", "suporte@example.com"],
            )
            self.assertEqual(mensagem["X-Unsent"], "1")
            parte_html = mensagem.get_body(preferencelist=("html",))
            self.assertIsNotNone(parte_html)
            self.assertIn("Número total de páginas", parte_html.get_content())
            self.assertIn("11407", parte_html.get_content())

    def test_rascunho_eml_permanece_salvo_se_nao_houver_app_associado(self):
        corpo = app.montar_email_body([], "16/11/2026", "relatorio.html", "relatorio.csv")
        with tempfile.TemporaryDirectory() as pasta_temporaria:
            with patch.object(app, "PASTA_DADOS", Path(pasta_temporaria)):
                with patch.object(
                    app.os,
                    "startfile",
                    side_effect=OSError("nenhum aplicativo associado"),
                ):
                    with self.assertRaisesRegex(RuntimeError, "rascunho foi criado"):
                        app.abrir_email("ti@example.com", corpo)

            arquivos_eml = list((Path(pasta_temporaria) / "rascunhos").glob("*.eml"))
            self.assertEqual(len(arquivos_eml), 1)

    def test_tabela_destaca_linhas_com_falhas_e_alertas(self):
        sem_comunicacao = {
            "setor": "Setor B",
            "host": "PRINTER-02",
            "ip": "192.0.2.221",
            "status": "Falha de comunicação: timeout",
            "tinta_preto": "-",
        }
        tinta_baixa = {
            "setor": "Setor C",
            "host": "PRINTER-03",
            "ip": "192.0.2.222",
            "status": "Sucesso",
            "tinta_preto": "15%",
        }
        usb = {
            "nome": "Pulmão",
            "ip": "198.51.100.220",
            "tipo_conexao": "USB",
            "status": "Sucesso",
        }

        tabela = app.gerar_tabela_completa([sem_comunicacao, tinta_baixa, usb])

        self.assertIn('class="linha-impressora sem-comunicacao"', tabela)
        self.assertIn('class="linha-impressora alerta-tinta-baixa"', tabela)
        self.assertIn('class="linha-impressora conexao-usb"', tabela)
        self.assertIn("background:#991b1b;color:#fff;font-weight:bold;", tabela)
        self.assertIn("background:#c2410c;color:#fff;font-weight:bold;", tabela)
        self.assertIn("background:#1d4ed8;color:#fff;font-weight:bold;", tabela)

    def test_csv_inclui_nome_dispositivo_numero_serie_e_contadores_no_inicio(self):
        with tempfile.TemporaryDirectory() as pasta_temporaria:
            caminho_csv = Path(pasta_temporaria) / "relatorio.csv"
            app.salvar_csv([{
                "nome": "Impressora 01",
                "setor": "Tecnologia",
                "host": "PRINTER-01",
                "ip": "192.0.2.220",
                "nome_dispositivo": "EPSONTEST01",
                "numero_serie": "SNTEST12345",
                "total_geral": "11407",
            }], caminho_csv)

            with caminho_csv.open(encoding="utf-8-sig", newline="") as arquivo:
                leitor = app.csv.DictReader(arquivo)
                linha = next(leitor)
                colunas = leitor.fieldnames

        self.assertEqual(linha["Nome do dispositivo"], "EPSONTEST01")
        self.assertEqual(linha["Número de série"], "SNTEST12345")
        self.assertEqual(linha["Total geral"], "11407")
        self.assertEqual(colunas[:9], [
            "Setor físico", "Hostname", "IP", "Identificação",
            "Nome do dispositivo", "Número de série", "Modelo", "MAC", "Firmware"
        ])
        self.assertEqual(colunas[9], "Total geral")

    def test_relatorio_destaca_setor_e_ip(self):
        item = {
            "nome": "Impressora 01",
            "setor": "Tecnologia",
            "modelo": "WF-M5899 Series",
            "host": "PRINTER-01",
            "ip": "192.0.2.220",
            "mac": "02:00:00:00:00:01",
            "nome_dispositivo": "EPSONTEST01",
            "numero_serie": "SNTEST12345",
            "firmware": "08.41.DG12PC",
            "data_hora": "16-11-2026 08:45",
            "status": "Sucesso",
            "estado_impressora": "Pronta",
            "estado_digitalizador": "-",
            "leitor_cartao": "-",
            "epson_connect": "-",
            "tinta_preto": "-",
            "caixa_manutencao": "-",
            "nivel_papel": "-",
            "nivel_papel_bandeja1": "-",
            "tamanho_papel": "-",
            "tipo_papel": "-",
            "total_geral": "11407",
            "total_pb": "11407",
            "total_cor": "0",
            "total_2faces": "3",
            "total_1face": "11404",
        }

        relatorio = app.gerar_html(
            [item],
            "16/11/2026",
            impressoras_usb=[{
                "nome": "Pulmão",
                "setor": "Produção",
                "host": "PRINTER-USB",
                "ip": "198.51.100.220",
                "numero_serie": "SNUSB123",
                "tipo_conexao": "USB",
            }],
        )

        self.assertIn("localizacao-setor", relatorio)
        self.assertIn("localizacao-ip", relatorio)
        self.assertIn('<section class="tabela-final">', relatorio)
        self.assertIn("Nome do dispositivo", relatorio)
        self.assertIn("Número de série", relatorio)
        self.assertIn("Tipo Conexão", relatorio)
        self.assertIn('class="linha-impressora conexao-usb"', relatorio)
        self.assertIn("USB — não consultada (conexão local)", relatorio)
        self.assertIn('<strong>Total de equipamentos</strong><span>2</span>', relatorio)
        self.assertIn("EPSONTEST01", relatorio)
        self.assertIn("SNTEST12345", relatorio)
        self.assertIn(
            'href="https://192.0.2.220/PRESENTATION/ADVANCED/COMMON/TOP"',
            relatorio,
        )
        self.assertIn('class="dados-impressora"', relatorio)
        self.assertIn('<th scope="col"', relatorio)
        self.assertEqual(relatorio.count('<tr class="linha-impressora">'), 1)
        self.assertIn('overflow-x:auto', relatorio)
        self.assertIn('html { zoom: 75%; }', relatorio)
        self.assertIn('class="contador-paginas"', relatorio)
        self.assertIn("Tecnologia", relatorio)
        self.assertIn("192.0.2.220", relatorio)

    def test_relatorio_alerta_tinta_vazia_ou_baixa_sem_alertar_papel(self):
        base = {
            "setor": "Setor A",
            "modelo": "WF-M5899 Series",
            "host": "PRINTER-01",
            "ip": "192.0.2.220",
            "mac": "02:00:00:00:00:01",
            "firmware": "08.41.DG12PC",
            "data_hora": "16-11-2026 08:45",
            "estado_impressora": "Pronta",
            "estado_digitalizador": "-",
            "leitor_cartao": "-",
            "epson_connect": "-",
            "tinta_preto": "80%",
            "caixa_manutencao": "-",
            "nivel_papel": "Restante",
            "nivel_papel_bandeja1": "Vazio",
            "tamanho_papel": "A4",
            "tipo_papel": "Papel Normal",
            "total_geral": "11407",
            "total_pb": "11407",
            "total_cor": "0",
            "total_2faces": "3",
            "total_1face": "11404",
        }
        papel_vazio = {
            **base,
            "nome": "Impressora 01",
            "tinta_preto": "Vazio",
            "status": "Sucesso",
        }
        sem_comunicacao = {
            **base,
            "nome": "Impressora 02",
            "setor": "Setor B",
            "ip": "192.0.2.221",
            "status": "Falha de comunicação: timeout",
        }
        papel_baixo = {
            **base,
            "nome": "Impressora 03",
            "setor": "Setor C",
            "ip": "192.0.2.222",
            "tinta_preto": "15%",
            "nivel_papel": "Restante (10%)",
            "nivel_papel_bandeja1": "Restante (35%)",
            "status": "Sucesso",
        }
        papel_vazio_tinta_ok = {
            **base,
            "nome": "Impressora 04",
            "setor": "Setor D",
            "ip": "192.0.2.223",
            "tinta_preto": "45%",
            "nivel_papel": "Vazio",
            "nivel_papel_bandeja1": "Vazio",
            "status": "Sucesso",
        }

        resultados = [papel_vazio, sem_comunicacao, papel_baixo, papel_vazio_tinta_ok]
        alertas = app.gerar_alertas(resultados)
        relatorio = app.gerar_html(resultados, "16/11/2026")

        self.assertEqual(
            [alerta["tipo"] for alerta in alertas],
            ["Sem comunicação", "Tinta vazia", "Tinta baixa"],
        )
        self.assertEqual(alertas[0]["mac"], "02:00:00:00:00:01")
        self.assertLess(
            relatorio.index("Ações que precisam de atenção agora"),
            relatorio.index('<div class="card">'),
        )
        self.assertIn("Acionar o TI da filial", relatorio)
        self.assertIn(
            'href="https://192.0.2.221/PRESENTATION/ADVANCED/COMMON/TOP"',
            relatorio,
        )
        self.assertIn("Substituir o cartucho preto no setor Setor A", relatorio)
        self.assertIn("Nível de tinta preta: 15%", relatorio)
        self.assertNotIn("Papel vazio", relatorio)
        self.assertNotIn("Papel baixo", relatorio)
        self.assertNotIn("Limite de papel", relatorio)
        self.assertNotIn("Limite de tinta", relatorio)
        self.assertIn("192.0.2.221", relatorio)
        self.assertIn("192.0.2.220", relatorio)


if __name__ == "__main__":
    unittest.main()
