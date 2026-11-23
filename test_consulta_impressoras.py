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

HTML_REDE_COM_SERIE = """
<html><body><table>
<tr><th>Nome do dispositivo</th><td>EPSONTEST02</td></tr>
<tr><th>Serial Number</th><td>XC75056433</td></tr>
<tr><th>MAC Address</th><td>02-00-00-00-00-02</td></tr>
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
        self.assertEqual(lista[1]["total_geral_manual"], "")
        self.assertEqual(lista[1]["tinta_preto_manual"], "")
        self.assertEqual(lista[0]["tipo_conexao"], "USB")
        self.assertEqual(lista[1]["tipo_conexao"], "CABO")
        self.assertEqual(lista[2]["tipo_conexao"], "CABO")

    def test_lista_normaliza_e_valida_mac_de_dispositivo(self):
        impressora = {
            "nome": "Impressora", "setor": "TI", "host": "IMP-01",
            "ip": "10.0.0.1", "mac": "02-00-00-00-00-01"
        }

        validada = app.validar_lista_impressoras([impressora])

        self.assertEqual(validada[0]["mac"], "02:00:00:00:00:01")
        with self.assertRaisesRegex(ValueError, "Endereço MAC inválido"):
            app.validar_lista_impressoras([{**impressora, "mac": "não é um MAC"}])

    def test_lista_preserva_contadores_manuais_usb_e_valida_limites(self):
        usb = {
            "nome": "Pulmão", "setor": "Produção", "host": "IMP-USB",
            "ip": "198.51.100.220", "tipo_conexao": "USB",
            "total_geral_manual": " 1450 ", "tinta_preto_manual": " 80 % "
        }

        validada = app.validar_lista_impressoras([usb])[0]

        self.assertEqual(validada["total_geral_manual"], "1450")
        self.assertEqual(validada["tinta_preto_manual"], "80%")
        for campo, valor in (
            ("total_geral_manual", "-1"),
            ("total_geral_manual", "1.5"),
            ("tinta_preto_manual", "101"),
            ("tinta_preto_manual", "baixo"),
        ):
            with self.subTest(campo=campo, valor=valor):
                with self.assertRaises(ValueError):
                    app.validar_lista_impressoras([{**usb, campo: valor}])

    def test_lista_preserva_ultimas_leituras_de_impressoras_de_rede(self):
        cabo = {
            "nome": "Expedição", "setor": "Expedição", "host": "IMP-EXP-01",
            "ip": "10.0.0.1", "tipo_conexao": "CABO",
            "total_geral_consultado": "11407", "tinta_preto_consultada": "45%"
        }

        validada = app.validar_lista_impressoras([cabo])[0]

        self.assertEqual(validada["total_geral_consultado"], "11407")
        self.assertEqual(validada["tinta_preto_consultada"], "45%")
        with self.assertRaisesRegex(ValueError, "contador de páginas"):
            app.validar_lista_impressoras([{
                **cabo, "total_geral_consultado": "muitos"
            }])

    def test_lista_impressoras_usb_com_dados_manualmente_pendentes(self):
        pendentes = app.impressoras_usb_pendentes([
            {
                "nome": "Pulmão 1", "tipo_conexao": "USB",
                "total_geral_manual": "", "tinta_preto_manual": ""
            },
            {
                "nome": "Pulmão 2", "tipo_conexao": "USB",
                "total_geral_manual": "0", "tinta_preto_manual": "0%"
            },
            {
                "nome": "Impressora de rede", "tipo_conexao": "CABO",
                "total_geral_manual": "", "tinta_preto_manual": ""
            }
        ])

        self.assertEqual(pendentes, [{
            "nome": "Pulmão 1",
            "campos": ["Páginas", "Tinta preta"]
        }])

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

    def test_faixa_de_exemplo_reconhece_subrede_ativa_do_windows(self):
        ip_local = ["10.2.200.44"]
        rede_ativa = [app.ipaddress.ip_network("10.2.200.0/24")]
        cabo = {
            "nome": "Impressora de rede", "ip": "10.2.200.80",
            "tipo_conexao": "CABO"
        }
        with (
            patch.object(app, "obter_ips_de_rota", return_value=ip_local),
            patch.object(app, "obter_faixas_de_rede_locais", return_value=rede_ativa) as obter_redes
        ):
            ips, dentro_da_faixa = app.verificar_rede_corporativa(
                app.FAIXA_REDE_EXEMPLO, [cabo]
            )

        self.assertEqual(ips, ip_local)
        self.assertTrue(dentro_da_faixa)
        obter_redes.assert_called_once_with(ip_local)

    def test_detecta_prefixo_apenas_dos_adaptadores_que_roteam_para_impressora(self):
        saida_powershell = app.json.dumps([
            {"IPAddress": "10.2.200.44", "PrefixLength": 24},
            {"IPAddress": "192.168.1.15", "PrefixLength": 24},
        ])
        processo = app.subprocess.CompletedProcess(
            args=[], returncode=0, stdout=saida_powershell, stderr=""
        )
        with patch.object(app.subprocess, "run", return_value=processo) as executar:
            redes = app.obter_faixas_de_rede_locais(["10.2.200.44"])

        self.assertEqual(redes, [app.ipaddress.ip_network("10.2.200.0/24")])
        self.assertEqual(executar.call_args.kwargs["timeout"], 15)

    def test_usa_ipconfig_quando_powershell_nao_consegue_listar_a_rede(self):
        saida_ipconfig = """
Adaptador Ethernet Ethernet:
   Endereço IPv4. . . . . . . . . . . . . . : 10.2.200.44
   Máscara de Sub-rede . . . . . . . . . . . : 255.255.255.0
"""
        processo_ipconfig = app.subprocess.CompletedProcess(
            args=[], returncode=0, stdout=saida_ipconfig, stderr=""
        )
        falha_powershell = app.subprocess.CalledProcessError(
            1, ["powershell.exe"]
        )
        with patch.object(
            app.subprocess, "run",
            side_effect=[falha_powershell, processo_ipconfig]
        ) as executar:
            redes = app.obter_faixas_de_rede_locais(["10.2.200.44"])

        self.assertEqual(redes, [app.ipaddress.ip_network("10.2.200.0/24")])
        self.assertEqual(executar.call_count, 2)

    def test_faixa_personalizada_nao_e_substituida_pela_rede_ativa(self):
        cabo = {
            "nome": "Impressora de rede", "ip": "10.2.200.80",
            "tipo_conexao": "CABO"
        }
        with (
            patch.object(app, "obter_ips_de_rota", return_value=["10.2.200.44"]),
            patch.object(app, "obter_faixas_de_rede_locais") as obter_redes
        ):
            _ips, dentro_da_faixa = app.verificar_rede_corporativa(
                "192.168.1.0/24", [cabo]
            )

        self.assertFalse(dentro_da_faixa)
        obter_redes.assert_not_called()

    def test_faixa_de_exemplo_nao_aprova_impressora_fora_da_subrede_ativa(self):
        cabo = {
            "nome": "Impressora de rede", "ip": "192.0.2.220",
            "tipo_conexao": "CABO"
        }
        with (
            patch.object(app, "obter_ips_de_rota", return_value=["10.2.200.44"]),
            patch.object(
                app, "obter_faixas_de_rede_locais",
                return_value=[app.ipaddress.ip_network("10.2.200.0/24")]
            )
        ):
            _ips, dentro_da_faixa = app.verificar_rede_corporativa(
                app.FAIXA_REDE_EXEMPLO, [cabo]
            )

        self.assertFalse(dentro_da_faixa)

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

    def test_salva_serial_e_mac_e_preserva_associacao_quando_o_ip_muda(self):
        config = {
            "impressoras": [{
                "ip": "10.0.0.1", "numero_serie": "", "mac": ""
            }]
        }

        alterou = app.atualizar_seriais_cadastrados(config, [{
            "ip": "10.0.0.1", "numero_serie": "SN-LIVE",
            "mac": "02-00-00-00-00-01"
        }])

        self.assertTrue(alterou)
        self.assertEqual(config["impressoras"][0]["numero_serie"], "SN-LIVE")
        self.assertEqual(config["impressoras"][0]["mac"], "02:00:00:00:00:01")

        config["impressoras"][0]["ip"] = "10.0.0.99"
        alterou = app.atualizar_seriais_cadastrados(config, [{
            "ip": "10.0.0.99", "numero_serie": "-",
            "mac": "02:00:00:00:00:01"
        }])

        self.assertFalse(alterou)
        self.assertEqual(config["impressoras"][0]["numero_serie"], "SN-LIVE")

    def test_limpa_serial_antigo_se_o_mac_confirmar_outro_dispositivo(self):
        config = {
            "impressoras": [{
                "ip": "10.0.0.1", "numero_serie": "SN-ANTIGO",
                "mac": "02:00:00:00:00:01"
            }]
        }

        alterou = app.atualizar_seriais_cadastrados(config, [{
            "ip": "10.0.0.1", "numero_serie": "-",
            "mac": "02:00:00:00:00:02"
        }])

        self.assertTrue(alterou)
        self.assertEqual(config["impressoras"][0]["numero_serie"], "")
        self.assertEqual(config["impressoras"][0]["mac"], "02:00:00:00:00:02")

    def test_atualiza_leituras_de_cabo_por_mac_sem_alterar_valores_usb(self):
        config = {
            "impressoras": [
                {
                    "nome": "Expedição", "host": "IMP-EXP-01",
                    "ip": "10.0.0.99", "tipo_conexao": "CABO",
                    "mac": "02:00:00:00:00:01",
                    "total_geral_consultado": "-", "tinta_preto_consultada": "-"
                },
                {
                    "nome": "Pulmão", "host": "IMP-USB",
                    "ip": "10.0.0.2", "tipo_conexao": "USB",
                    "total_geral_manual": "5555", "tinta_preto_manual": "45%",
                    "total_geral_consultado": "-", "tinta_preto_consultada": "-"
                },
            ]
        }

        alterou = app.atualizar_leituras_cadastradas(config, [{
            "ip": "10.0.0.1", "mac": "02-00-00-00-00-01",
            "total_geral": "11407", "tinta_preto": "80%"
        }])

        self.assertTrue(alterou)
        cabo, usb = config["impressoras"]
        self.assertEqual(cabo["total_geral_consultado"], "11407")
        self.assertEqual(cabo["tinta_preto_consultada"], "80%")
        self.assertEqual(usb["total_geral_manual"], "5555")
        self.assertEqual(usb["tinta_preto_manual"], "45%")
        self.assertEqual(
            app.valores_contadores_cadastrados(cabo), ("11407", "80%")
        )
        self.assertEqual(
            app.valores_contadores_cadastrados(usb), ("5555", "45%")
        )

    def test_cadastro_guarda_situacao_da_ultima_consulta(self):
        config = {"impressoras": [
            {"nome": "Exp", "host": "H1", "ip": "10.0.0.1", "tipo_conexao": "CABO"},
            {"nome": "RH", "host": "H2", "ip": "10.0.0.2", "tipo_conexao": "CABO"},
            {"nome": "Pulmão", "host": "H3", "ip": "10.0.0.3", "tipo_conexao": "USB"},
            {"nome": "Nova", "host": "H4", "ip": "10.0.0.4", "tipo_conexao": "CABO"},
        ]}
        alterou = app.atualizar_leituras_cadastradas(config, [
            {"ip": "10.0.0.1", "status": "Sucesso", "tipo_conexao": "CABO"},
            {"ip": "10.0.0.2", "status": "Falha de comunicação: timeout",
             "tipo_conexao": "CABO"},
        ])
        self.assertTrue(alterou)
        situacoes = [app.situacao_cadastrada(i) for i in config["impressoras"]]
        self.assertEqual(situacoes, ["ONLINE", "OFF-LINE", "USB", "-"])

        validada = app.validar_lista_impressoras(config["impressoras"])
        self.assertEqual(validada[0]["situacao_consultada"], "ONLINE")
        self.assertEqual(validada[1]["situacao_consultada"], "OFF-LINE")
        self.assertEqual(validada[3]["situacao_consultada"], "-")
        invalida = app.validar_lista_impressoras([
            {**config["impressoras"][0], "situacao_consultada": "qualquer"}
        ])
        self.assertEqual(invalida[0]["situacao_consultada"], "-")

    def test_config_de_exemplo_traz_campo_supervisor(self):
        exemplo = app.json.loads(
            app.caminho_recurso("config.example.json").read_text(encoding="utf-8")
        )
        self.assertTrue(all("supervisor" in i for i in exemplo["impressoras"]))

    def test_painel_de_alertas_exibe_supervisor_antes_do_setor_e_hostname(self):
        valores = app.valores_linha_alerta_painel({
            "tipo": "Sem comunicação", "setor": "Expedição",
            "supervisor": "Supervisor A",
            "nome": "Expedição", "ip": "10.0.0.1", "host": "IMP-EXP-01",
            "nome_dispositivo": "-", "numero_serie": "SN-123", "modelo": "WF-X",
            "mac": "-"
        })

        self.assertEqual(valores[1], "Supervisor A")
        self.assertEqual(valores[2], "Expedição")
        self.assertEqual(valores[4], "10.0.0.1")
        self.assertEqual(valores[5], "IMP-EXP-01")

    def test_cadastro_aceita_supervisor_opcional(self):
        base = {"nome": "Expedição", "setor": "EXPEDIÇÃO", "host": "IMP-EXP-01"}
        lista = app.validar_lista_impressoras([
            {**base, "ip": "10.0.0.1", "supervisor": "  Supervisor A  "},
            {**base, "ip": "10.0.0.2"},
            {**base, "ip": "10.0.0.3", "supervisor": None},
        ])
        self.assertEqual(
            [item["supervisor"] for item in lista],
            ["Supervisor A", "", ""],
        )
        with self.assertRaises(ValueError):
            app.validar_lista_impressoras([{**base, "ip": "10.0.0.4", "supervisor": 5}])

    def test_situacao_de_conexao_online_offline_e_usb(self):
        self.assertEqual(app.situacao_conexao({"status": "Sucesso"}), "ONLINE")
        self.assertEqual(
            app.situacao_conexao({"status": "Sucesso parcial - x"}), "ONLINE"
        )
        self.assertEqual(
            app.situacao_conexao({"status": "Falha de comunicação: timeout"}),
            "OFF-LINE",
        )
        self.assertEqual(app.situacao_conexao({"status": "Erro 500"}), "OFF-LINE")
        self.assertEqual(
            app.situacao_conexao({"status": "-", "tipo_conexao": "USB"}), "USB"
        )

    def test_dados_do_cadastro_atualizam_supervisor_dos_resultados(self):
        resultados = [{"ip": "10.0.0.1", "setor": "Antigo", "supervisor": "-"}]
        app.aplicar_dados_cadastro(resultados, [{
            "ip": "10.0.0.1", "setor": "EXPEDIÇÃO", "supervisor": "Supervisor A"
        }])
        self.assertEqual(resultados[0]["supervisor"], "Supervisor A")
        self.assertEqual(resultados[0]["setor"], "EXPEDIÇÃO")

    def test_relatorio_tem_mapa_visual_entre_resumo_e_tabela(self):
        online = {
            "nome": "Exp", "setor": "EXPEDIÇÃO", "supervisor": "Supervisor A",
            "host": "IMP-EXP-01", "ip": "10.0.0.1", "status": "Sucesso",
            "tipo_conexao": "CABO", "modelo": "WF", "estado_impressora": "Pronta",
            "mac": "-", "numero_serie": "-", "firmware": "-", "tinta_preto": "-",
            "caixa_manutencao": "-", "nivel_papel": "-", "data_hora": "-",
            "total_geral": "-", "total_pb": "-", "total_2faces": "-", "total_1face": "-",
        }
        offline = {
            **online, "setor": "RH", "supervisor": "Supervisor B",
            "host": "IMP-RH-01", "ip": "10.0.0.2",
            "status": "Falha de comunicação: timeout", "estado_impressora": "-",
        }
        relatorio = app.gerar_html([online, offline], "19/11/2026")

        self.assertIn("<h1>🖨️ Inventário de Impressoras CD05</h1>", relatorio)
        self.assertIn("<p>Envio ao fornecedor de locação</p>", relatorio)
        self.assertNotIn("Relatório Mensal de Impressoras", relatorio)
        self.assertNotIn("Inventário técnico, insumos", relatorio)
        self.assertLess(
            relatorio.index("Resumo executivo"),
            relatorio.index('<section class="mapa-impressoras"'),
        )
        self.assertLess(
            relatorio.index('<section class="mapa-impressoras"'),
            relatorio.index('<section class="tabela-final">'),
        )
        mapa = app.BeautifulSoup(relatorio, "html.parser").select_one(
            "section.mapa-impressoras"
        )
        itens = mapa.select(".mapa-item")
        self.assertEqual(len(itens), 2)
        self.assertIn("mapa-online", itens[0]["class"])
        self.assertIn("mapa-offline", itens[1]["class"])
        texto_online = itens[0].get_text(" ", strip=True)
        for valor in ("EXPEDIÇÃO", "IMP-EXP-01", "Supervisor A", "ONLINE"):
            self.assertIn(valor, texto_online)
        self.assertIn("OFF-LINE", itens[1].get_text(" ", strip=True))
        self.assertIsNotNone(itens[0].select_one("svg.icone-impressora"))
        self.assertIn("ONLINE: 1", mapa.get_text(" ", strip=True))
        self.assertIn("OFF-LINE: 1", mapa.get_text(" ", strip=True))

        tabela = app.BeautifulSoup(relatorio, "html.parser").select_one(
            "table.dados-impressora"
        )
        cabecalho = [th.get_text(strip=True) for th in tabela.select("thead th")]
        self.assertEqual(
            cabecalho[:4],
            ["Estado da impressora", "Supervisor", "Setor físico", "Hostname"],
        )
        self.assertEqual(cabecalho.count("Estado da impressora"), 1)
        primeira, segunda = tabela.select("tbody tr")
        celula_online = primeira.select("td")[0]
        self.assertIsNotNone(celula_online.select_one(".indicador-situacao"))
        self.assertIn("#22c55e", str(celula_online))
        self.assertIn("ONLINE", celula_online.get_text(" ", strip=True))
        self.assertIn("Pronta", celula_online.get_text(" ", strip=True))
        celula_offline = segunda.select("td")[0]
        self.assertIn("#ef4444", str(celula_offline))
        self.assertIn("OFF-LINE", celula_offline.get_text(" ", strip=True))
        self.assertEqual(primeira.select("td")[1].get_text(strip=True), "Supervisor A")

        self.assertIn("<span>SUPERVISOR</span>", relatorio)
        self.assertIn("<strong>Supervisor:</strong> Supervisor B", relatorio)


    def test_tabela_fixa_as_quatro_primeiras_colunas(self):
        item = {
            "setor": "CPD", "supervisor": "S", "host": "H", "ip": "10.0.0.9",
            "status": "Sucesso", "tipo_conexao": "CABO",
        }
        tabela = app.BeautifulSoup(
            app.gerar_tabela_completa([item]), "html.parser"
        ).select_one("table.dados-impressora")
        for linha in (tabela.select_one("thead tr"), tabela.select_one("tbody tr")):
            celulas = linha.find_all(["th", "td"])
            esquerdas = [
                c["style"].split("left:")[1].split("px")[0]
                for c in celulas[:4]
            ]
            posicoes = app.posicoes_colunas_fixas([item])
            esperado = [str(posicoes[c][0]) for c in app.COLUNAS_FIXAS_TABELA]
            self.assertEqual(esquerdas, esperado)
            for celula in celulas[:4]:
                self.assertIn("position:sticky", celula["style"])
                self.assertIn("coluna-fixa", celula.get("class", []))
            self.assertNotIn("position:sticky", celulas[4]["style"])
        self.assertIn("border-collapse:separate", tabela["style"])
        self.assertIn("width:max-content", tabela["style"])
        self.assertNotIn("min-width:2400px", tabela["style"])

    def test_colunas_fixas_ajustam_ao_maior_texto(self):
        curto = {"setor": "RH", "supervisor": "A", "host": "H", "ip": "1.1.1.1",
                 "status": "Sucesso", "tipo_conexao": "CABO", "estado_impressora": "-"}
        longo = {**curto, "setor": "ENT. DE NOTAS 2 - DOCA SUL"}
        p_curto = app.posicoes_colunas_fixas([curto])
        p_longo = app.posicoes_colunas_fixas([curto, longo])
        self.assertGreater(p_longo["setor"][1], p_curto["setor"][1])
        esquerda = 0
        for chave in app.COLUNAS_FIXAS_TABELA:
            self.assertEqual(p_longo[chave][0], esquerda)
            esquerda += p_longo[chave][1]

    def test_nome_fixo_do_relatorio_html(self):
        self.assertEqual(app.NOME_ARQUIVO_RELATORIO_HTML, "Clique Aqui Contadores.html")

    def test_mapa_aps_instalado_e_botao_no_relatorio(self):
        import tempfile
        with tempfile.TemporaryDirectory() as pasta:
            origem = Path(pasta) / "embutido" / "mapa_aps.html"
            origem.parent.mkdir()
            origem.write_text("<html>mapa</html>", encoding="utf-8")
            destino = app.instalar_mapa_aps(origem, Path(pasta) / "app")
            self.assertEqual(destino.name, "mapa_aps.html")
            self.assertEqual(destino.read_text(encoding="utf-8"), "<html>mapa</html>")
            origem.write_text("<html>mapa novo</html>", encoding="utf-8")
            app.instalar_mapa_aps(origem, Path(pasta) / "app")
            self.assertEqual(destino.read_text(encoding="utf-8"), "<html>mapa novo</html>")
            self.assertIsNone(app.instalar_mapa_aps(Path(pasta) / "nao.html", Path(pasta) / "app"))

            config = {"mapa_aps_titulo": "Mapa dos APs CD05"}
            titulo, endereco = app.dados_mapa_aps(config, destino)
            self.assertEqual(titulo, "Mapa dos APs CD05")
            self.assertTrue(endereco.startswith("file:///"))

            item = {
                "nome": "CPD", "setor": "CPD", "supervisor": "S", "host": "H",
                "ip": "10.0.0.9", "status": "Sucesso", "tipo_conexao": "CABO",
                "modelo": "WF", "estado_impressora": "-", "mac": "-",
                "numero_serie": "-", "firmware": "-", "tinta_preto": "-",
                "caixa_manutencao": "-", "nivel_papel": "-", "data_hora": "-",
                "total_geral": "-", "total_pb": "-", "total_2faces": "-",
                "total_1face": "-",
            }
            relatorio = app.gerar_html([item], "21/11/2026", mapa_aps=(titulo, endereco))
            botao = app.BeautifulSoup(relatorio, "html.parser").select_one(".info-bar a.botao-mapa")
            self.assertIsNotNone(botao)
            self.assertEqual(botao["href"], endereco)
            self.assertIn("Mapa dos APs CD05", botao.get_text())

            self.assertNotIn('class="botao-mapa"', app.gerar_html([item], "21/11/2026"))
            self.assertIsNone(app.dados_mapa_aps(config, Path(pasta) / "nao.html"))

    def test_coletores_validacao(self):
        lista = app.validar_lista_coletores([
            {"setor": " EXPEDIÇÃO ", "fabricante": "zebra", "modelo": "TC52",
             "numero_serie": " s123 ", "mac": "aa-bb-cc-dd-ee-ff", "piloto": True},
            {"setor": "RH", "fabricante": "Honeywell", "numero_serie": "H9"},
        ])
        self.assertEqual(lista[0]["setor"], "EXPEDIÇÃO")
        self.assertEqual(lista[0]["fabricante"], "Zebra")
        self.assertEqual(lista[0]["numero_serie"], "S123")
        self.assertEqual(lista[0]["mac"], "AA:BB:CC:DD:EE:FF")
        self.assertTrue(lista[0]["piloto"])
        self.assertFalse(lista[1]["piloto"])
        self.assertEqual(lista[1]["versao_app"], "")
        self.assertEqual(app.validar_lista_coletores(None), [])
        self.assertEqual(app.validar_lista_coletores([]), [])
        for invalido, trecho in (
            ({"fabricante": "Zebra", "numero_serie": "X"}, "setor"),
            ({"setor": "RH", "fabricante": "Zebra"}, "número de série"),
            ({"setor": "RH", "fabricante": "Samsung", "numero_serie": "X"}, "Fabricante"),
            ({"setor": "RH", "fabricante": "Zebra", "numero_serie": "X", "mac": "zz"}, "MAC"),
        ):
            with self.assertRaisesRegex(ValueError, trecho):
                app.validar_lista_coletores([invalido])
        with self.assertRaisesRegex(ValueError, "mais de uma vez"):
            app.validar_lista_coletores([
                {"setor": "RH", "fabricante": "Zebra", "numero_serie": "x1"},
                {"setor": "CPD", "fabricante": "Zebra", "numero_serie": "X1"},
            ])

    def test_coletores_supervisor_sugerido_pelo_setor(self):
        impressoras = [{"setor": "Expedição", "supervisor": "Supervisor A"},
                       {"setor": "RH", "supervisor": ""}]
        self.assertEqual(app.supervisor_do_setor("EXPEDIÇÃO ", impressoras), "Supervisor A")
        self.assertEqual(app.supervisor_do_setor("RH", impressoras), "")
        self.assertEqual(app.supervisor_do_setor("CPD", impressoras), "")

    def test_setores_e_supervisores_juntam_impressoras_e_coletores(self):
        impressoras = [{"setor": "EXPEDIÇÃO", "supervisor": "Jose"},
                       {"setor": "RH", "supervisor": "Cristiane"}]
        coletores = [{"setor": "expedição", "supervisor": "JOSE"},
                     {"setor": "DOCA NOVA", "supervisor": "Paulo"},
                     {"setor": "CPD", "supervisor": ""}]
        setores, supervisores = app.setores_e_supervisores(impressoras + coletores)
        self.assertEqual(setores, ["CPD", "DOCA NOVA", "EXPEDIÇÃO", "RH"])
        self.assertEqual(supervisores, ["Cristiane", "Jose", "Paulo"])
        # setor criado só nos coletores serve para as impressoras e vice-versa
        self.assertEqual(app.supervisor_do_setor("Doca Nova", impressoras + coletores), "Paulo")
        self.assertEqual(app.supervisor_do_setor("rh", coletores + impressoras), "Cristiane")

    def test_escolher_setor_preenche_supervisor(self):
        try:
            raiz = app.tk.Tk()
        except app.tk.TclError:
            self.skipTest("sem interface gráfica")
        try:
            setor, supervisor = app.tk.StringVar(master=raiz), app.tk.StringVar(master=raiz)
            registros = [{"setor": "RH", "supervisor": "Cristiane"}]
            app.ligar_setor_ao_supervisor(setor, supervisor, lambda: registros)
            setor.set("RH")
            self.assertEqual(supervisor.get(), "Cristiane")
            setor.set("SETOR NOVO")
            self.assertEqual(supervisor.get(), "Cristiane")
        finally:
            raiz.destroy()

    def test_coletores_relatorio_html_e_csv(self):
        import csv as modulo_csv
        import tempfile
        coletores = app.validar_lista_coletores([
            {"setor": "RH", "fabricante": "Honeywell", "modelo": "CK65",
             "numero_serie": "H1", "versao_app": "2.0", "piloto": True},
            {"setor": "EXPEDIÇÃO", "fabricante": "Zebra", "modelo": "TC52",
             "numero_serie": "Z1", "versao_app": "1.9", "usuario": "=CMD()"},
            {"setor": "EXPEDIÇÃO", "fabricante": "Zebra", "numero_serie": "Z2",
             "versao_app": "1.9", "observacao": "<b>tela</b>"},
        ])
        html = app.gerar_html_coletores(coletores, "21/11/2026 12:00:00")
        soup = app.BeautifulSoup(html, "html.parser")
        self.assertEqual(soup.title.get_text(), "Coletores CD05")
        texto = soup.get_text(" ", strip=True)
        for valor in ("Total de coletores 3", "Zebra 2", "Honeywell 1", "No piloto 1", "Setores 2"):
            self.assertIn(valor, texto)
        grupos = [g.get_text(" ", strip=True) for g in soup.select("tr.grupo-setor")]
        self.assertEqual(grupos, ["EXPEDIÇÃO — 2 coletor(es)", "RH — 1 coletor(es)"])
        self.assertEqual(len(soup.select("tr.piloto")), 1)
        self.assertIn("1.9 · 2", texto)
        self.assertNotIn("<b>tela</b>", html)
        with tempfile.TemporaryDirectory() as pasta:
            caminho = app.salvar_csv_coletores(coletores, Path(pasta) / "c.csv")
            with open(caminho, encoding="utf-8-sig", newline="") as arquivo:
                linhas = list(modulo_csv.reader(arquivo))
        self.assertEqual(linhas[0][:6], ["Status", "Setor físico", "Supervisor", "Fabricante", "Modelo", "Número de série"])
        self.assertEqual([l[5] for l in linhas[1:]], ["Z1", "Z2", "H1"])
        self.assertEqual(linhas[1][0], "Não verificado")
        usuario = linhas[0].index("Usuário")
        self.assertEqual(linhas[1][usuario], "'=CMD()")
        self.assertEqual(linhas[3][linhas[0].index("Piloto")], "Sim")

    def test_coletores_status_pelo_mac(self):
        coletores = app.validar_lista_coletores([
            {"setor": "RH", "fabricante": "Honeywell", "numero_serie": "H1", "mac": "aa-bb-cc-00-00-01"},
            {"setor": "RH", "fabricante": "Honeywell", "numero_serie": "H2", "mac": "AA:BB:CC:00:00:02"},
            {"setor": "RH", "fabricante": "Honeywell", "numero_serie": "H3"},
        ])
        self.assertEqual({c["situacao_consultada"] for c in coletores}, {"-"})
        arp = (
            "Interface: 10.50.0.10 --- 0x7\n"
            "  Endereço IP           Endereço físico       Tipo\n"
            "  10.50.0.21            aa-bb-cc-00-00-01     dinâmico\n"
            "  10.50.0.255           ff-ff-ff-ff-ff-ff     estático\n"
            "  224.0.0.22            01-00-5e-00-00-16     estático\n"
        )
        macs = app.ler_tabela_arp(arp)
        self.assertEqual(macs, {"AA:BB:CC:00:00:01": "10.50.0.21"})
        atualizados = app.validar_lista_coletores(
            app.aplicar_status_coletores(coletores, macs, "24/11/2026 08:00:00")
        )
        self.assertEqual([c["situacao_consultada"] for c in atualizados], ["ONLINE", "OFF-LINE", "SEM MAC"])
        self.assertEqual(atualizados[0]["ip_atual"], "10.50.0.21")
        self.assertEqual(atualizados[0]["visto_online_em"], "24/11/2026 08:00:00")
        self.assertEqual(app.ultima_verificacao_coletores(atualizados), "24/11/2026 08:00:00")
        html = app.gerar_html_coletores(atualizados, "24/11/2026 08:00:01")
        soup = app.BeautifulSoup(html, "html.parser")
        texto = soup.get_text(" ", strip=True)
        for valor in ("Online 1", "Offline 1", "Sem MAC 1", "Última verificação de status: 24/11/2026 08:00:00"):
            self.assertIn(valor, texto)
        self.assertEqual(len(soup.select("span.st-online")), 1)
        self.assertIsNone(soup.select_one(".aviso"))

    def test_coletores_aviso_rede_wifi(self):
        config = {"wifi_coletores": "PM-COLETORES", "faixa_rede_coletores": "10.50.0.0/22",
                  "nome_unidade": "Pague Menos CD05 Contagem-MG"}
        aviso = app.aviso_rede_coletores(config)
        self.assertIn('rede Wi-Fi dos coletores "PM-COLETORES"', aviso)
        self.assertIn("ativo Pague Menos CD05 Contagem-MG", aviso)
        self.assertEqual(app.situacao_rede_coletores(config, ssids=["CORPORATIVA"], ip_local="10.50.0.9"), (False, aviso))
        self.assertEqual(app.situacao_rede_coletores(config, ssids=["pm-coletores"], ip_local="10.2.0.9"), (False, aviso))
        conectado, mensagem = app.situacao_rede_coletores(config, ssids=["PM-COLETORES"], ip_local="10.50.1.9")
        self.assertTrue(conectado)
        self.assertIn("10.50.1.9", mensagem)
        self.assertFalse(app.situacao_rede_coletores({"faixa_rede_coletores": ""})[0])
        self.assertEqual(app.extrair_ssids(
            "    SSID                   : PM-COLETORES\n    BSSID                  : aa:bb\n"
        ), ["PM-COLETORES"])
        with self.assertRaises(ValueError):
            app.validar_faixa_coletores("10.0.0.0/16")
        html = app.gerar_html_coletores([], "24/11/2026 08:00:00", aviso)
        self.assertIn("PM-COLETORES", app.BeautifulSoup(html, "html.parser").select_one(".aviso").get_text())

    def test_mapa_mostra_nivel_de_tinta_e_paginas(self):
        base = {
            "setor": "CPD", "supervisor": "S", "host": "H", "ip": "10.0.0.9",
            "status": "Sucesso", "tipo_conexao": "CABO",
        }
        mapa = app.gerar_mapa_impressoras(
            [
                {**base, "tinta_preto": "75%", "total_geral": "12345"},
                {**base, "tinta_preto": "10%", "total_geral": "500"},
                {**base, "tinta_preto": "-", "total_geral": "-"},
            ],
            limite_tinta=20,
        )
        itens = app.BeautifulSoup(mapa, "html.parser").select(".mapa-item")
        texto = itens[0].get_text(" ", strip=True)
        for valor in ("Tinta preta", "75%", "Páginas", "12345"):
            self.assertIn(valor, texto)
        barra = itens[0].select_one(".mapa-barra div")["style"]
        self.assertIn("width:75%", barra)
        self.assertIn("#22c55e", barra)
        self.assertIn("#ef4444", itens[1].select_one(".mapa-barra div")["style"])
        self.assertIn("width:0%", itens[2].select_one(".mapa-barra div")["style"])

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

    def test_extrai_serial_e_mac_de_rotulos_em_tabela(self):
        identificacao = app.extrair_identificacao_dispositivo(HTML_REDE_COM_SERIE)

        self.assertEqual(identificacao["nome_dispositivo"], "EPSONTEST02")
        self.assertEqual(identificacao["numero_serie"], "XC75056433")
        self.assertEqual(identificacao["mac"], "02:00:00:00:00:02")

    def test_consulta_procura_serial_na_pagina_de_rede_quando_ausente_no_estado(self):
        conteudo_estado = HTML_PRODUTO.replace(
            "<dt>Número de série :</dt><dd>SNTEST12345</dd>\n", ""
        ).replace(
            "<dt>Endereço MAC da rede :</dt><dd>02:00:00:00:00:01</dd>\n", ""
        )

        class Resposta:
            status_code = 200

            def __init__(self, conteudo):
                self.content = conteudo.encode("utf-8")

        def fake_get(url, **kwargs):
            if app.CAMINHO_ESTADO in url:
                return Resposta(conteudo_estado)
            if app.CAMINHO_CONTADOR in url:
                return Resposta(HTML_CONTADORES)
            if app.CAMINHO_REDE in url:
                return Resposta(HTML_REDE_COM_SERIE)
            self.fail(f"Endpoint inesperado na consulta: {url}")

        with patch.object(app.requests, "get", side_effect=fake_get) as requisitar:
            resultados = app.consultar_impressoras(lista_impressoras=[{
                "nome": "Impressora 01", "setor": "TI",
                "host": "IMP-01", "ip": "10.0.0.10"
            }])

        self.assertEqual(resultados[0]["numero_serie"], "XC75056433")
        self.assertEqual(resultados[0]["mac"], "02:00:00:00:00:02")
        self.assertTrue(any(
            app.CAMINHO_REDE in chamada.args[0]
            for chamada in requisitar.call_args_list
        ))

    def test_consulta_usa_lista_configurada_e_atualiza_progresso(self):
        lista = [
            {
                "nome": "Impressora 01", "setor": "Setor 01",
                "host": "PRINTER-01", "ip": "192.0.2.220",
                "total_geral_manual": "1", "tinta_preto_manual": "2%"
            },
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
        self.assertEqual(resultados[0]["numero_serie"], "SNTEST12345")
        self.assertEqual(resultados[0]["status"], "Sucesso")
        self.assertEqual(
            [resultados[0][chave] for chave in (
                "total_geral", "total_pb", "total_2faces", "total_1face"
            )],
            ["11407", "11407", "3", "11404"],
        )
        for removido in (
            "total_cor", "estado_digitalizador", "leitor_cartao", "epson_connect",
            "nivel_papel_bandeja1", "tamanho_papel", "tipo_papel",
        ):
            self.assertNotIn(removido, resultados[0])
            self.assertNotIn(removido, resultados[1])
        self.assertEqual(resultados[0]["tinta_preto"], "-")
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

        self.assertIn("Segue Relatório Mensal de Impressoras:", mensagem)
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
        self.assertNotIn("Nome do dispositivo", mensagem)
        self.assertIn("Hostname: PRINTER-01", mensagem)
        self.assertIn("Número de série: SNTEST12345", mensagem)
        self.assertNotIn("*⚠️ IMPRESSORAS COM TINTA VAZIA OU BAIXA*", mensagem)
        self.assertNotIn("Identificação", mensagem)
        self.assertNotIn("Cor:", mensagem)
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
            "Contadores — Total: 11407 | P&B: 11407 | 2 faces: 3 | 1 face: 11404",
            mensagem,
        )
        self.assertNotIn("Setor físico | Hostname | IP", mensagem)
        self.assertLess(
            mensagem.index("*⚠️ IMPRESSORAS SEM COMUNICAÇÃO"),
            mensagem.index("*DETALHAMENTO COMPLETO*"),
        )

    def test_dados_manuais_usb_aparecem_nos_relatorios_e_nao_afetam_cabo(self):
        usb = {
            "nome": "Pulmão", "setor": "Produção", "host": "IMP-USB",
            "ip": "198.51.100.220", "numero_serie": "SNUSB123",
            "tipo_conexao": "USB", "total_geral_manual": "1450",
            "tinta_preto_manual": "65%"
        }
        cabo = {
            chave: "-"
            for chave in (
                *(chave for chave, _rotulo in app.COLUNAS_TABELA_COMPLETA),
                "estado_digitalizador", "leitor_cartao", "epson_connect",
                "nivel_papel_bandeja1", "tamanho_papel", "tipo_papel",
            )
        }
        cabo.update({
            "nome": "Impressora de rede", "setor": "TI", "host": "IMP-CABO",
            "ip": "10.2.200.80", "tipo_conexao": "CABO", "status": "Sucesso",
            "total_geral": "11407", "total_pb": "11407", "total_cor": "0",
            "total_2faces": "3", "total_1face": "11404", "tinta_preto": "80%"
        })

        html_relatorio = app.gerar_html(
            [cabo], "18/11/2026", impressoras_usb=[usb]
        )
        corpo_email = app.montar_email_body(
            [cabo], "18/11/2026", "relatorio.html", "relatorio.csv",
            impressoras_usb=[usb]
        )
        mensagem_whatsapp = app.montar_whatsapp_body(
            [cabo], "18/11/2026", impressoras_usb=[usb]
        )

        for conteudo in (html_relatorio, corpo_email, mensagem_whatsapp):
            self.assertIn("1450", conteudo)
            self.assertIn("65%", conteudo)
            self.assertIn("SNUSB123", conteudo)
        self.assertIn("11407", html_relatorio)
        self.assertIn("11407", corpo_email)
        self.assertIn("11407", mensagem_whatsapp)
        self.assertIn("80%", mensagem_whatsapp)

        with tempfile.TemporaryDirectory() as pasta_temporaria:
            caminho_csv = Path(pasta_temporaria) / "relatorio.csv"
            app.salvar_csv([cabo], caminho_csv, impressoras_usb=[usb])
            with caminho_csv.open(encoding="utf-8-sig", newline="") as arquivo:
                linhas = list(app.csv.DictReader(arquivo))

        linha_usb = next(linha for linha in linhas if linha["IP"] == usb["ip"])
        self.assertEqual(linha_usb["Total geral"], "1450")
        self.assertEqual(linha_usb["Tinta preta"], "65%")
        linha_cabo = next(linha for linha in linhas if linha["IP"] == cabo["ip"])
        self.assertEqual(linha_cabo["Total geral"], "11407")
        self.assertEqual(linha_cabo["Tinta preta"], "80%")

    def test_atualizar_dados_usb_refaz_html_e_csv_sem_nova_consulta(self):
        usb = {
            "nome": "Pulmão", "setor": "Produção", "host": "IMP-USB",
            "ip": "198.51.100.220", "tipo_conexao": "USB",
            "total_geral_manual": "", "tinta_preto_manual": ""
        }
        with tempfile.TemporaryDirectory() as pasta_temporaria:
            caminho_html = Path(pasta_temporaria) / "relatorio.html"
            caminho_csv = Path(pasta_temporaria) / "relatorio.csv"
            caminho_html, caminho_csv = app.atualizar_relatorios_salvos(
                [], "18/11/2026", caminho_html, caminho_csv,
                impressoras_usb=[usb]
            )

            usb["total_geral_manual"] = "1820"
            usb["tinta_preto_manual"] = "73%"
            caminho_html_atualizado, caminho_csv_atualizado = (
                app.atualizar_relatorios_salvos(
                    [], "18/11/2026", caminho_html, caminho_csv,
                    impressoras_usb=[usb]
                )
            )

            html_relatorio = caminho_html_atualizado.read_text(encoding="utf-8")
            with caminho_csv_atualizado.open(
                encoding="utf-8-sig", newline=""
            ) as arquivo:
                linhas = list(app.csv.DictReader(arquivo))

        self.assertIn("1820", html_relatorio)
        self.assertIn("73%", html_relatorio)
        self.assertEqual(linhas[0]["Total geral"], "1820")
        self.assertEqual(linhas[0]["Tinta preta"], "73%")

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
            "P&amp;B", "Impressão em 2 faces", "Impressão em 1 face",
            "Número de série", "Modelo", "MAC",
            "Firmware", "Status", "Estado da impressora",
            "Tinta preta", "Caixa de manutenção",
            "Nível de papel geral", "Data/hora da impressora"
        ):
            self.assertIn(rotulo, corpo)
        self.assertIn('<th scope="col"', corpo)
        self.assertLess(corpo.index("Setor físico"), corpo.index("Hostname"))
        self.assertLess(corpo.index("Hostname"), corpo.index(">Modelo<"))
        self.assertLess(corpo.index(">MAC<"), corpo.index(">IP<"))
        self.assertLess(corpo.index(">IP<"), corpo.index(">Número de série<"))
        self.assertLess(
            corpo.index(">Número de série<"),
            corpo.index(">Número total de páginas<"),
        )
        self.assertLess(
            corpo.index(">Número de série<"),
            corpo.index(">Tinta preta<"),
        )
        self.assertLess(
            corpo.index(">Tinta preta<"),
            corpo.index(">Número total de páginas<"),
        )
        self.assertEqual(corpo.count(">Tinta preta<"), 1)
        self.assertNotIn(">Identificação<", corpo)
        self.assertNotIn(">Cor<", corpo)
        self.assertEqual(corpo.count('<tr class="linha-impressora">'), 1)
        self.assertIn('overflow-x:auto', corpo)
        self.assertIn('width:max-content', corpo)
        self.assertIn('class="contador-paginas"', corpo)
        self.assertIn("background:#fff1b8", corpo)
        self.assertIn("Tecnologia &lt;teste&gt;", corpo)
        tabela_completa = app.BeautifulSoup(corpo, "html.parser").select_one(
            "table.dados-impressora"
        )
        self.assertIsNotNone(tabela_completa)
        cabecalho = [
            celula.get_text(" ", strip=True)
            for celula in tabela_completa.select("thead th")
        ]
        valores = [
            celula.get_text(" ", strip=True)
            for celula in tabela_completa.select("tbody tr:first-child td")
        ]
        self.assertNotIn("Nome do dispositivo", cabecalho)
        self.assertEqual(cabecalho.count("Hostname"), 1)
        self.assertEqual(valores[cabecalho.index("Hostname")], "PRINTER-01")
        self.assertEqual(len(valores), len(cabecalho))
        self.assertNotIn("EPSONTEST01", corpo)
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
            self.assertEqual(
                mensagem["Subject"], "Relatório Mensal de Impressoras"
            )
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
        sucesso_parcial = {
            "nome": "Impressora 04",
            "host": "PRINTER-04",
            "ip": "192.0.2.223",
            "tipo_conexao": "CABO",
            "status": "Sucesso parcial: alguns dados indisponíveis",
        }
        usb = {
            "nome": "Pulmão",
            "ip": "198.51.100.220",
            "tipo_conexao": "USB",
            "status": "Sucesso",
        }

        tabela = app.gerar_tabela_completa([
            sem_comunicacao, tinta_baixa, sucesso_parcial, usb
        ])

        self.assertIn('class="linha-impressora sem-comunicacao"', tabela)
        self.assertIn('class="linha-impressora alerta-tinta-baixa"', tabela)
        self.assertIn('class="linha-impressora conexao-usb"', tabela)
        self.assertIn('class="linha-impressora"><td', tabela)
        self.assertIn("background:#991b1b;color:#fff;font-weight:bold;", tabela)
        self.assertIn("background:#c2410c;color:#fff;font-weight:bold;", tabela)
        self.assertNotIn("background:#b45309;color:#fff;font-weight:bold;", tabela)
        self.assertIn("background:#1d4ed8;color:#fff;font-weight:bold;", tabela)
        self.assertGreaterEqual(tabela.count("white-space:nowrap;background:#1d4ed8"), 20)

    def test_csv_usa_hostname_numero_serie_e_contadores_no_inicio(self):
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

        self.assertNotIn("Nome do dispositivo", colunas)
        self.assertEqual(linha["Hostname"], "PRINTER-01")
        self.assertEqual(linha["Número de série"], "SNTEST12345")
        self.assertEqual(linha["Total geral"], "11407")
        self.assertEqual(colunas, [
            "Supervisor", "Setor físico", "Hostname", "IP",
            "Número de série", "Modelo", "MAC", "Firmware",
            "Total geral", "Total P&B", "Total 2 faces", "Total 1 face",
            "Status", "Estado da impressora", "Tinta preta",
            "Caixa de manutenção", "Nível de papel", "Data/hora da impressora"
        ])

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
        self.assertIn(
            "<title>Inventário de Impressoras CD05</title>", relatorio
        )
        self.assertIn('<section class="tabela-final">', relatorio)
        self.assertIn("<h2>Relatório por Setor x Dispositivos</h2>", relatorio)
        self.assertNotIn("Relatório completo em tabela", relatorio)
        self.assertNotIn(
            ">Nome do dispositivo<",
            str(app.BeautifulSoup(relatorio, "html.parser").select_one(
                "table.dados-impressora thead"
            ))
        )
        self.assertLess(
            relatorio.index('<section class="tabela-final">'),
            relatorio.index('<div class="card">')
        )
        self.assertNotIn("Nome do dispositivo", relatorio)
        self.assertNotIn("EPSONTEST01", relatorio)
        self.assertIn("Hostname", relatorio)
        self.assertIn("Número de série", relatorio)
        self.assertIn("Tipo Conexão", relatorio)
        self.assertIn('class="linha-impressora conexao-usb"', relatorio)
        self.assertIn("USB — não consultada (conexão local)", relatorio)
        self.assertIn('<strong>Total de equipamentos</strong><span>2</span>', relatorio)
        self.assertIn("SNTEST12345", relatorio)
        self.assertIn(
            'href="https://192.0.2.220/PRESENTATION/ADVANCED/COMMON/TOP"',
            relatorio,
        )
        self.assertIn('class="dados-impressora"', relatorio)
        self.assertIn('<th scope="col"', relatorio)
        inicio_cabecalho = relatorio.index('<thead>')
        fim_cabecalho = relatorio.index('</thead>', inicio_cabecalho)
        cabecalho = relatorio[inicio_cabecalho:fim_cabecalho]
        colunas_na_ordem = (
            '>MAC<', '>IP<', '>Número de série<',
            '>Tinta preta<', '>Número total de páginas<', '>P&amp;B<',
            '>Impressão em 2 faces<', '>Impressão em 1 face<',
        )
        posicoes_colunas = [cabecalho.index(rotulo) for rotulo in colunas_na_ordem]
        self.assertEqual(posicoes_colunas, sorted(posicoes_colunas))
        for rotulo_removido in (
            "Identificação", ">Cor<", "Digitalizador", "digitalizador",
            "Leitor de cartão", "Epson Connect", "Bandeja 1",
            "Tamanho do papel", "Tipo de papel", "Tamanho / Tipo",
        ):
            self.assertNotIn(rotulo_removido, relatorio)
        for removida in (
            '>Identificação<', '>Cor<', '>Estado do digitalizador<',
            '>Leitor de cartão<', '>Epson Connect<', '>Bandeja 1<',
            '>Tamanho do papel<', '>Tipo de papel<',
        ):
            self.assertNotIn(removida, cabecalho)
        self.assertEqual(cabecalho.count('<th scope="col"'), 19)
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
