# -*- coding: utf-8 -*-
import os
import re
import shutil
import csv
import html
import ipaddress
import json
import socket
import sys
import subprocess
import threading
import time
import unicodedata
import webbrowser
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk

import requests
import urllib3
from bs4 import BeautifulSoup

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ================= LISTA DE IMPRESSORAS =================
impressoras = [
    {"nome": "Impressora 01", "setor": "Setor 01", "ip": "192.0.2.220", "host": "PRINTER-01"},
    {"nome": "Impressora 02", "setor": "Setor 02", "ip": "192.0.2.221", "host": "PRINTER-02"},
    {"nome": "Impressora 03", "setor": "Setor 03", "ip": "192.0.2.222", "host": "PRINTER-03"},
    {"nome": "Impressora 04", "setor": "Setor 04", "ip": "192.0.2.223", "host": "PRINTER-04"},
    {"nome": "Impressora 05", "setor": "Setor 05", "ip": "192.0.2.224", "host": "PRINTER-05"},
    {"nome": "Impressora 06", "setor": "Setor 06", "ip": "192.0.2.225", "host": "PRINTER-06"},
    {"nome": "Impressora 07", "setor": "Setor 07", "ip": "192.0.2.226", "host": "PRINTER-07"},
    {"nome": "Impressora 08", "setor": "Setor 08", "ip": "192.0.2.227", "host": "PRINTER-08"},
    {"nome": "Impressora 09", "setor": "Setor 09", "ip": "192.0.2.228", "host": "PRINTER-09"},
]

CAMINHO_ESTADO = "/PRESENTATION/ADVANCED/INFO_PRTINFO/TOP"
CAMINHO_CONTADOR = "/PRESENTATION/ADVANCED/INFO_MENTINFO/TOP"
CAMINHO_REDE = "/PRESENTATION/ADVANCED/COMMON/TOP"
EMAIL_PADRAO = ""
WHATSAPP_PADRAO = ""
CONFIG_PADRAO = {
    "email_padrao": EMAIL_PADRAO,
    "whatsapp_padrao": WHATSAPP_PADRAO,
    "limite_tinta": 20,
    "faixa_rede_corporativa": "192.0.2.0/24",
    "mapa_aps_titulo": "Mapa dos APs CD05 Contagem-MG PagMenos",
    "nome_unidade": "Pague Menos CD05 Contagem-MG",
    "wifi_coletores": "",
    "faixa_rede_coletores": "",
    "coletores": [],
    "impressoras": [dict(impressora) for impressora in impressoras]
}
PASTA_DADOS = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "ConsultaImpressoras"
APP_VERSION = "1.0.22"
APP_DEVELOPER = "Christiano Miranda"
NOME_PLATAFORMA = "Gestor de Infraestrutura de TI"
URL_RELEASES = "https://github.com/christianocassio/buscacontadoresimpressoras/releases"
TIPOS_CONEXAO = ("USB", "CABO", "WIFI")
FAIXA_REDE_EXEMPLO = "192.0.2.0/24"


def texto_versao_aplicativo():
    if getattr(sys, "frozen", False):
        caminho_executavel = Path(sys.executable)
        data_build = datetime.fromtimestamp(caminho_executavel.stat().st_mtime)
        build = data_build.strftime("%d/%m/%Y %H:%M")
    else:
        build = "código-fonte"
    return f"v{APP_VERSION} | {build} | Desenvolvedor: {APP_DEVELOPER}"


def tipo_conexao_padrao(nome):
    nome_normalizado = unicodedata.normalize("NFKD", str(nome))
    nome_normalizado = ''.join(
        caractere for caractere in nome_normalizado
        if not unicodedata.combining(caractere)
    ).casefold()
    return "USB" if "pulmao" in nome_normalizado else "CABO"


def filtrar_impressoras_de_rede(lista_impressoras):
    return [
        impressora
        for impressora in lista_impressoras
        if str(
            impressora.get("tipo_conexao")
            or tipo_conexao_padrao(impressora.get("nome", ""))
        ).strip().upper() != "USB"
    ]


def normalizar_mac(valor):
    texto = str(valor or "").strip()
    if not texto or texto.casefold() in ("-", "--", "none", "null"):
        return ""
    if not re.fullmatch(r"[0-9A-Fa-f:.-]+", texto):
        return ""
    octetos = re.sub(r"[-:.]", "", texto)
    if not re.fullmatch(r"[0-9A-Fa-f]{12}", octetos):
        return ""
    return ":".join(
        octetos[indice:indice + 2].upper()
        for indice in range(0, 12, 2)
    )


def caminho_recurso(nome):
    pasta = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return pasta / nome


def carregar_config():
    PASTA_DADOS.mkdir(parents=True, exist_ok=True)
    caminho = PASTA_DADOS / "config.json"
    if not caminho.exists():
        try:
            config_inicial = json.loads(
                caminho_recurso("config.example.json").read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            config_inicial = CONFIG_PADRAO
        caminho.write_text(
            json.dumps(config_inicial, ensure_ascii=False, indent=4),
            encoding="utf-8"
        )

    try:
        config_carregada = json.loads(caminho.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Arquivo de configuração inválido: {caminho}") from exc

    if not isinstance(config_carregada, dict):
        raise ValueError(f"O arquivo de configuração deve conter um objeto JSON: {caminho}")

    config = {**CONFIG_PADRAO, **config_carregada}
    for chave in (
        "email_padrao", "whatsapp_padrao", "mapa_aps_titulo",
        "nome_unidade", "wifi_coletores", "faixa_rede_coletores",
    ):
        if not isinstance(config[chave], str):
            raise ValueError(f"O valor de '{chave}' deve ser texto.")
    config.pop("limite_papel", None)
    config.pop("mapa_aps_arquivo", None)
    config["impressoras"] = validar_lista_impressoras(config["impressoras"])
    config["coletores"] = validar_lista_coletores(config["coletores"])
    config["wifi_coletores"] = config["wifi_coletores"].strip()
    config["faixa_rede_coletores"] = config["faixa_rede_coletores"].strip()
    validar_faixa_coletores(config["faixa_rede_coletores"])
    valor_limite_tinta = config["limite_tinta"]
    if (
        not isinstance(valor_limite_tinta, int)
        or isinstance(valor_limite_tinta, bool)
        or not 0 <= valor_limite_tinta <= 100
    ):
        raise ValueError("O valor de 'limite_tinta' deve ser um número inteiro de 0 a 100.")
    if not isinstance(config["faixa_rede_corporativa"], str):
        raise ValueError("O valor de 'faixa_rede_corporativa' deve ser texto.")
    try:
        faixa_rede = ipaddress.ip_network(config["faixa_rede_corporativa"], strict=False)
    except ValueError as exc:
        raise ValueError(
            "A faixa de rede corporativa deve estar em formato CIDR IPv4, por exemplo 192.0.2.0/24."
        ) from exc
    if faixa_rede.version != 4:
        raise ValueError("A faixa de rede corporativa deve ser IPv4.")
    if config != config_carregada:
        salvar_config(config, caminho)

    return config, caminho


def salvar_config(config, caminho):
    caminho.write_text(
        json.dumps(config, ensure_ascii=False, indent=4),
        encoding="utf-8"
    )


NOME_ARQUIVO_MAPA_APS = "mapa_aps.html"


def instalar_mapa_aps(origem=None, pasta_destino=None):
    """Copia o mapa dos APs embutido no programa para a pasta do app.

    O exe é temporário (PyInstaller), então o mapa precisa de um endereço fixo
    para o botão do app e o link do relatório. Retorna None se o mapa não veio
    junto nesta compilação.
    """
    origem = Path(origem or caminho_recurso(NOME_ARQUIVO_MAPA_APS))
    if not origem.is_file():
        return None
    pasta_destino = Path(pasta_destino or PASTA_DADOS / "mapa_aps")
    pasta_destino.mkdir(parents=True, exist_ok=True)
    destino = pasta_destino / NOME_ARQUIVO_MAPA_APS
    conteudo = origem.read_bytes()
    if not destino.is_file() or destino.read_bytes() != conteudo:
        destino.write_bytes(conteudo)
    return destino


def dados_mapa_aps(config, caminho_mapa=None):
    """Retorna (título, endereço file://) do mapa dos APs, ou None se não houver mapa."""
    caminho = Path(caminho_mapa or PASTA_DADOS / "mapa_aps" / NOME_ARQUIVO_MAPA_APS)
    if not caminho.is_file():
        return None
    titulo = str(config.get("mapa_aps_titulo") or "").strip() or "Mapa dos APs"
    return titulo, caminho.resolve().as_uri()


def validar_lista_impressoras(lista):
    if not isinstance(lista, list) or not lista:
        raise ValueError("A lista deve conter ao menos uma impressora.")

    impressoras_validadas = []
    ips_cadastrados = set()
    for indice, item in enumerate(lista, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"A impressora {indice} deve ser um objeto.")

        nome = item.get("nome")
        setor = item.get("setor", "Não informado")
        supervisor = item.get("supervisor", "")
        host = item.get("host")
        ip = item.get("ip")
        numero_serie = item.get("numero_serie", "")
        mac = item.get("mac", "")
        total_geral_manual = item.get("total_geral_manual", "")
        tinta_preto_manual = item.get("tinta_preto_manual", "")
        total_geral_consultado = item.get("total_geral_consultado", "-")
        tinta_preto_consultada = item.get("tinta_preto_consultada", "-")
        situacao_consultada = item.get("situacao_consultada", "-")
        if situacao_consultada not in ("ONLINE", "OFF-LINE"):
            situacao_consultada = "-"
        tipo_conexao = item.get("tipo_conexao")
        if not all(isinstance(valor, str) and valor.strip() for valor in (nome, setor, host, ip)):
            raise ValueError(
                f"Preencha identificação, setor, hostname e IP da impressora {indice}."
            )
        if not isinstance(numero_serie, str):
            raise ValueError(f"O número de série da impressora {indice} deve ser texto.")
        if supervisor is None:
            supervisor = ""
        if not isinstance(supervisor, str):
            raise ValueError(f"O supervisor da impressora {indice} deve ser texto.")
        if not isinstance(mac, str):
            raise ValueError(f"O endereço MAC da impressora {indice} deve ser texto.")
        mac_normalizado = normalizar_mac(mac)
        if mac.strip() and mac.strip() not in ("-", "--") and not mac_normalizado:
            raise ValueError(f"Endereço MAC inválido na impressora {indice}: {mac}")
        if not isinstance(total_geral_manual, str):
            raise ValueError(
                f"O número de páginas manual da impressora {indice} deve ser texto."
            )
        total_geral_manual = total_geral_manual.strip()
        if total_geral_manual and not re.fullmatch(r"\d+", total_geral_manual):
            raise ValueError(
                f"O número de páginas manual da impressora {indice} deve ser um inteiro não negativo."
            )
        if not isinstance(tinta_preto_manual, str):
            raise ValueError(
                f"O nível de tinta manual da impressora {indice} deve ser texto."
            )
        tinta_preto_manual = tinta_preto_manual.strip().removesuffix("%").strip()
        if tinta_preto_manual:
            if not re.fullmatch(r"\d{1,3}", tinta_preto_manual) or not 0 <= int(tinta_preto_manual) <= 100:
                raise ValueError(
                    f"O nível de tinta manual da impressora {indice} deve estar entre 0 e 100%."
                )
            tinta_preto_manual = f"{int(tinta_preto_manual)}%"
        if not isinstance(total_geral_consultado, str):
            raise ValueError(
                f"O contador de páginas consultado da impressora {indice} deve ser texto."
            )
        total_geral_consultado = total_geral_consultado.strip()
        if total_geral_consultado in ("", "--", "None", "null"):
            total_geral_consultado = "-"
        if total_geral_consultado != "-" and not re.fullmatch(
            r"\d+", total_geral_consultado
        ):
            raise ValueError(
                f"O contador de páginas consultado da impressora {indice} "
                "deve conter apenas números."
            )
        if not isinstance(tinta_preto_consultada, str):
            raise ValueError(
                f"O nível de tinta consultado da impressora {indice} deve ser texto."
            )
        tinta_preto_consultada = tinta_preto_consultada.strip()
        if tinta_preto_consultada in ("", "--", "None", "null"):
            tinta_preto_consultada = "-"
        if tipo_conexao is None or (
            isinstance(tipo_conexao, str) and not tipo_conexao.strip()
        ):
            tipo_conexao = tipo_conexao_padrao(nome)
        elif isinstance(tipo_conexao, str):
            tipo_conexao = tipo_conexao.strip().upper()
        if tipo_conexao not in TIPOS_CONEXAO:
            raise ValueError(
                f"Tipo de conexão inválido na impressora {indice}. "
                f"Use: {', '.join(TIPOS_CONEXAO)}."
            )
        try:
            endereco = ipaddress.ip_address(ip.strip())
        except ValueError as exc:
            raise ValueError(f"IP inválido na impressora {indice}: {ip}") from exc
        if endereco.version != 4:
            raise ValueError(f"O IP da impressora {indice} deve ser IPv4.")
        ip_normalizado = str(endereco)
        if ip_normalizado in ips_cadastrados:
            raise ValueError(f"O IP {ip_normalizado} está cadastrado mais de uma vez.")
        ips_cadastrados.add(ip_normalizado)

        impressoras_validadas.append({
            "nome": nome.strip(),
            "setor": setor.strip(),
            "supervisor": supervisor.strip(),
            "host": host.strip(),
            "ip": ip_normalizado,
            "numero_serie": numero_serie.strip(),
            "mac": mac_normalizado,
            "tipo_conexao": tipo_conexao,
            "total_geral_manual": total_geral_manual,
            "tinta_preto_manual": tinta_preto_manual,
            "total_geral_consultado": total_geral_consultado,
            "tinta_preto_consultada": tinta_preto_consultada,
            "situacao_consultada": situacao_consultada
        })

    return impressoras_validadas


def situacao_cadastrada(impressora):
    tipo_conexao = str(
        impressora.get("tipo_conexao")
        or tipo_conexao_padrao(impressora.get("nome", ""))
    ).strip().upper()
    if tipo_conexao == "USB":
        return "USB"
    situacao = impressora.get("situacao_consultada")
    return situacao if situacao in ("ONLINE", "OFF-LINE") else "-"


def valores_contadores_cadastrados(impressora):
    tipo_conexao = str(
        impressora.get("tipo_conexao")
        or tipo_conexao_padrao(impressora.get("nome", ""))
    ).strip().upper()
    if tipo_conexao == "USB":
        return (
            limpar_texto(impressora.get("total_geral_manual")),
            limpar_texto(impressora.get("tinta_preto_manual")),
        )
    return (
        limpar_texto(impressora.get("total_geral_consultado")),
        limpar_texto(impressora.get("tinta_preto_consultada")),
    )


def atualizar_seriais_cadastrados(config, resultados):
    resultados_por_ip = {
        limpar_texto(item.get('ip')): item
        for item in resultados
    }
    resultados_por_mac = {
        mac: item
        for item in resultados
        if (mac := normalizar_mac(item.get('mac')))
    }
    alterou = False
    for impressora in config['impressoras']:
        mac_cadastrado = normalizar_mac(impressora.get('mac'))
        resultado = resultados_por_mac.get(mac_cadastrado) if mac_cadastrado else None
        if resultado is None:
            resultado = resultados_por_ip.get(impressora['ip'])
        if resultado is None:
            continue

        mac_encontrado = normalizar_mac(resultado.get('mac'))
        numero_serie = limpar_texto(resultado.get('numero_serie'))
        mac_diferente = (
            mac_cadastrado and mac_encontrado and mac_cadastrado != mac_encontrado
        )
        if mac_diferente and numero_serie == '-':
            if impressora.get('numero_serie'):
                impressora['numero_serie'] = ''
                alterou = True
        elif numero_serie != '-' and impressora.get('numero_serie', '') != numero_serie:
            impressora['numero_serie'] = numero_serie
            alterou = True
        if mac_encontrado and impressora.get('mac', '') != mac_encontrado:
            impressora['mac'] = mac_encontrado
            alterou = True
    return alterou


def atualizar_leituras_cadastradas(config, resultados):
    resultados_por_ip = {
        limpar_texto(item.get("ip")): item
        for item in resultados
    }
    resultados_por_mac = {
        mac: item
        for item in resultados
        if (mac := normalizar_mac(item.get("mac")))
    }
    alterou = False
    for impressora in config["impressoras"]:
        tipo_conexao = str(
            impressora.get("tipo_conexao")
            or tipo_conexao_padrao(impressora.get("nome", ""))
        ).strip().upper()
        if tipo_conexao == "USB":
            continue

        mac_cadastrado = normalizar_mac(impressora.get("mac"))
        resultado = resultados_por_mac.get(mac_cadastrado) if mac_cadastrado else None
        if resultado is None:
            resultado = resultados_por_ip.get(limpar_texto(impressora.get("ip")))
        if resultado is None:
            continue

        total_geral = limpar_texto(resultado.get("total_geral"))
        tinta_preto = limpar_texto(resultado.get("tinta_preto"))
        if impressora.get("total_geral_consultado", "-") != total_geral:
            impressora["total_geral_consultado"] = total_geral
            alterou = True
        if impressora.get("tinta_preto_consultada", "-") != tinta_preto:
            impressora["tinta_preto_consultada"] = tinta_preto
            alterou = True
        situacao = situacao_conexao(resultado)
        if impressora.get("situacao_consultada", "-") != situacao:
            impressora["situacao_consultada"] = situacao
            alterou = True
    return alterou


def limpar_texto(valor, padrao='-'):
    if valor is None:
        return padrao
    texto = str(valor).strip()
    if not texto or texto in ('-', '--', 'None', 'null'):
        return padrao
    return texto


def obter_ips_de_rota(lista_impressoras=None):
    ips = set()
    for impressora in lista_impressoras or impressoras:
        conexao = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            conexao.connect((impressora["ip"], 443))
            ip_local = conexao.getsockname()[0]
            if ip_local and ip_local != "0.0.0.0":
                ips.add(ip_local)
        except OSError:
            continue
        finally:
            conexao.close()

    if not ips:
        try:
            enderecos = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM)
        except socket.gaierror:
            enderecos = []
        ips.update(
            endereco[4][0]
            for endereco in enderecos
            if endereco[4][0] != "127.0.0.1"
        )

    return sorted(ips, key=lambda endereco: tuple(int(parte) for parte in endereco.split(".")))


def verificar_rede_corporativa(faixa_configurada, lista_impressoras=None):
    faixa = ipaddress.ip_network(faixa_configurada, strict=False)
    dispositivos = lista_impressoras if lista_impressoras is not None else impressoras
    dispositivos_rede = filtrar_impressoras_de_rede(dispositivos)
    if not dispositivos_rede:
        return [], False
    ips_locais = obter_ips_de_rota(dispositivos_rede)
    dentro_da_faixa = any(
        ipaddress.ip_address(endereco) in faixa
        for endereco in ips_locais
    )
    if not dentro_da_faixa and faixa == ipaddress.ip_network(FAIXA_REDE_EXEMPLO):
        redes_locais = obter_faixas_de_rede_locais(ips_locais)
        dentro_da_faixa = any(
            ipaddress.ip_address(endereco) in rede
            and any(
                ipaddress.ip_address(impressora["ip"]) in rede
                for impressora in dispositivos_rede
            )
            for endereco in ips_locais
            for rede in redes_locais
        )
    return ips_locais, dentro_da_faixa


def obter_faixas_de_rede_locais(ips_locais):
    if not ips_locais:
        return []

    comando = (
        "Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred "
        "| Select-Object IPAddress,PrefixLength | ConvertTo-Json -Compress"
    )
    diretorio_sistema = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    powershell = str(
        diretorio_sistema / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    )
    adaptadores = None
    try:
        processo = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", comando],
            capture_output=True,
            check=True,
            text=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        adaptadores = json.loads(processo.stdout or "[]")
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        pass

    if isinstance(adaptadores, dict):
        adaptadores = [adaptadores]
    redes = []
    ips_de_saida = set(ips_locais)
    if isinstance(adaptadores, list):
        for adaptador in adaptadores:
            if not isinstance(adaptador, dict):
                continue
            try:
                endereco = ipaddress.ip_address(adaptador.get("IPAddress", ""))
                prefixo = int(adaptador.get("PrefixLength"))
                if endereco.version == 4 and str(endereco) in ips_de_saida:
                    redes.append(
                        ipaddress.ip_network(f"{endereco}/{prefixo}", strict=False)
                    )
            except (TypeError, ValueError):
                continue
    if redes:
        return redes

    try:
        processo = subprocess.run(
            [str(diretorio_sistema / "ipconfig.exe")],
            capture_output=True,
            check=True,
            encoding="oem",
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "Não foi possível identificar a máscara da rede ativa do Windows "
            "usando PowerShell nem ipconfig."
        ) from exc

    redes_ipconfig = []
    for bloco in re.split(r"\r?\n\s*\r?\n", processo.stdout or ""):
        enderecos = []
        mascaras = []
        for linha in bloco.splitlines():
            rotulo = unicodedata.normalize("NFKD", linha.casefold())
            rotulo = "".join(
                caractere for caractere in rotulo
                if not unicodedata.combining(caractere)
            )
            rotulo = re.sub(r"[^a-z0-9]+", " ", rotulo).strip()
            correspondencias = re.findall(
                r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)", linha
            )
            if (
                "ipv4 address" in rotulo
                or "endereco ipv4" in rotulo
                or "direccion ipv4" in rotulo
            ):
                enderecos.extend(correspondencias)
            elif (
                "subnet mask" in rotulo
                or "mascara de sub rede" in rotulo
                or "mascara sub rede" in rotulo
                or "mascara de subred" in rotulo
            ):
                mascaras.extend(correspondencias)
        for endereco in enderecos:
            if endereco not in ips_de_saida:
                continue
            for mascara in mascaras:
                try:
                    rede = ipaddress.ip_interface(f"{endereco}/{mascara}").network
                except ValueError:
                    continue
                if rede not in redes_ipconfig:
                    redes_ipconfig.append(rede)
                break
    return redes_ipconfig


def linhas_usb_cadastradas(impressoras_usb, ips_resultados=None):
    ips_resultados = ips_resultados or set()
    linhas = []
    for impressora in impressoras_usb or ():
        tipo_conexao = str(
            impressora.get("tipo_conexao")
            or tipo_conexao_padrao(impressora.get("nome", ""))
        ).strip().upper()
        ip = limpar_texto(impressora.get("ip"))
        if tipo_conexao != "USB" or ip in ips_resultados:
            continue
        linhas.append({
            "setor": limpar_texto(impressora.get("setor"), "Não informado"),
            "supervisor": limpar_texto(impressora.get("supervisor")),
            "host": limpar_texto(impressora.get("host")),
            "ip": ip,
            "tipo_conexao": "USB",
            "nome": limpar_texto(impressora.get("nome")),
            "numero_serie": limpar_texto(impressora.get("numero_serie")),
            "total_geral": limpar_texto(impressora.get("total_geral_manual")),
            "tinta_preto": limpar_texto(impressora.get("tinta_preto_manual")),
            "status": "USB — não consultada (conexão local)",
        })
    return linhas


def aplicar_dados_cadastro(resultados, impressoras_cadastradas):
    """Atualiza setor e supervisor dos resultados com o cadastro atual (por IP)."""
    cadastro_por_ip = {
        limpar_texto(impressora.get("ip")): impressora
        for impressora in impressoras_cadastradas or ()
    }
    for item in resultados or ():
        impressora = cadastro_por_ip.get(limpar_texto(item.get("ip")))
        if impressora is None:
            continue
        item["supervisor"] = limpar_texto(impressora.get("supervisor"))
        item["setor"] = limpar_texto(impressora.get("setor"), "Não informado")
    return resultados


def situacao_conexao(item):
    """Classifica a impressora como ONLINE, OFF-LINE ou USB (não consultada)."""
    tipo_conexao = str(
        item.get("tipo_conexao") or tipo_conexao_padrao(item.get("nome", ""))
    ).strip().upper()
    if tipo_conexao == "USB":
        return "USB"
    status = str(item.get("status") or "")
    return "ONLINE" if status.startswith("Sucesso") else "OFF-LINE"


CORES_SITUACAO = {
    "ONLINE": "#22c55e",
    "OFF-LINE": "#ef4444",
    "USB": "#60a5fa",
}


def indicador_situacao_html(situacao, texto_estado=None):
    cor = CORES_SITUACAO.get(situacao, "#94a3b8")
    rotulo = "USB (local)" if situacao == "USB" else situacao
    detalhe = limpar_texto(texto_estado)
    complemento = (
        f' <span style="font-weight:normal;opacity:.85">· {html.escape(detalhe)}</span>'
        if detalhe != '-' and situacao == "ONLINE"
        else ''
    )
    return (
        f'<span class="indicador-situacao" style="display:inline-block;width:11px;height:11px;'
        f'border-radius:50%;background:{cor};border:2px solid #fff;'
        f'box-shadow:0 0 0 1px rgba(15,23,42,.35);vertical-align:middle;margin-right:6px"></span>'
        f'<span style="vertical-align:middle">{html.escape(rotulo)}</span>{complemento}'
    )


def impressoras_usb_pendentes(impressoras_usb):
    pendentes = []
    for impressora in impressoras_usb or ():
        tipo_conexao = str(
            impressora.get("tipo_conexao")
            or tipo_conexao_padrao(impressora.get("nome", ""))
        ).strip().upper()
        if tipo_conexao != "USB":
            continue
        campos = []
        if limpar_texto(impressora.get("total_geral_manual")) == "-":
            campos.append("Páginas")
        if limpar_texto(impressora.get("tinta_preto_manual")) == "-":
            campos.append("Tinta preta")
        if campos:
            pendentes.append({
                "nome": limpar_texto(impressora.get("nome")),
                "campos": campos
            })
    return pendentes


def escapar_html(valor):
    return html.escape(limpar_texto(valor))


def url_gestao_impressora(ip):
    try:
        endereco = ipaddress.ip_address(limpar_texto(ip))
    except ValueError:
        return None
    if endereco.version != 4:
        return None
    return f"https://{endereco}{CAMINHO_REDE}"


def link_gestao_impressora_html(ip):
    endereco = limpar_texto(ip)
    url = url_gestao_impressora(endereco)
    if not url:
        return escapar_html(endereco)
    return (
        f'<a href="{escapar_html(url)}" target="_blank" rel="noopener noreferrer" '
        'title="Abrir página de gestão da impressora" '
        'style="color:inherit;text-decoration:underline">'
        f'{escapar_html(endereco)}</a>'
    )


def abrir_gestao_impressora(ip):
    url = url_gestao_impressora(ip)
    if not url:
        raise ValueError(f'Endereço IPv4 inválido para abrir a gestão: {limpar_texto(ip)}')
    if not webbrowser.open(url, new=2):
        raise RuntimeError(f'Não foi possível abrir a página de gestão em {url}.')
    return url


def extrair_porcentagem(valor):
    if valor is None:
        return None
    texto = str(valor)
    match = re.search(r'(\d{1,3})\s*%', texto)
    if match:
        return int(match.group(1))
    return None


def extrair_nivel_tinta(soup, texto):
    for tanque in soup.select('ul.inksection li'):
        rotulo_cor = tanque.select_one('.clrname')
        if not rotulo_cor:
            continue
        cor = rotulo_cor.get_text(' ', strip=True).casefold()
        if cor not in ('bk', 'black', 'preto', 'preta'):
            continue

        indicador = tanque.select_one('.tank[style]')
        if indicador:
            gradiente = re.search(
                r'linear-gradient\(\s*to\s+top\s*,([^)]*)\)',
                indicador.get('style', ''),
                re.IGNORECASE
            )
            if gradiente:
                paradas = re.findall(r'(\d{1,3})\s*%', gradiente.group(1))
                if len(paradas) >= 2:
                    return f'{int(paradas[1])}%'

    padrao_textual = re.compile(
        r'(?:Preto\s*\(BK\)|Tinta\s+preta|Black\s+ink)\s*[:：]?\s*([^\n]+)',
        re.IGNORECASE
    )
    for correspondencia in padrao_textual.finditer(texto):
        candidato = correspondencia.group(1).strip()
        normalizado = unicodedata.normalize('NFKD', candidato.casefold())
        normalizado = ''.join(
            caractere for caractere in normalizado
            if not unicodedata.combining(caractere)
        )
        if extrair_porcentagem(candidato) is not None or any(
            termo in normalizado
            for termo in (
                'vazio', 'empty', 'esgotad', 'acabou', 'sem tinta',
                'substitui', 'replace', 'baixo', 'baixa', 'low', 'acabando'
            )
        ):
            return candidato
    return '-'


def extrair_identificacao_dispositivo(conteudo):
    soup = (
        conteudo if isinstance(conteudo, BeautifulSoup)
        else BeautifulSoup(conteudo, 'html.parser')
    )
    dados = {
        'nome_dispositivo': '-',
        'numero_serie': '-',
        'mac': '-'
    }

    def registrar(rotulo, valor):
        rotulo_normalizado = unicodedata.normalize('NFKD', str(rotulo).casefold())
        rotulo_normalizado = ''.join(
            caractere for caractere in rotulo_normalizado
            if not unicodedata.combining(caractere)
        )
        rotulo_normalizado = re.sub(r'[^a-z0-9]+', ' ', rotulo_normalizado).strip()

        if rotulo_normalizado.startswith('nome do disposit'):
            chave = 'nome_dispositivo'
        elif rotulo_normalizado.startswith((
            'numero de serie', 'numero serie', 'n de serie', 'n o de serie',
            'n serie', 'no de serie',
            'serial number', 'serial no', 'serialnumber', 'serialno'
        )) or rotulo_normalizado.startswith('serial '):
            chave = 'numero_serie'
        elif rotulo_normalizado.startswith((
            'endereco mac', 'mac address', 'macaddress', 'network mac', 'networkmac',
            'mac'
        )):
            chave = 'mac'
        else:
            return

        valor_limpo = limpar_texto(valor)
        if chave == 'mac':
            valor_limpo = normalizar_mac(valor_limpo) or '-'
        if valor_limpo != '-' and dados[chave] == '-':
            dados[chave] = valor_limpo

    for rotulo in soup.find_all('dt'):
        valor = rotulo.find_next_sibling('dd')
        if valor:
            registrar(rotulo.get_text(' ', strip=True), valor.get_text(' ', strip=True))

    for linha in soup.find_all('tr'):
        celulas = linha.find_all(['th', 'td'])
        for indice in range(0, len(celulas) - 1, 2):
            registrar(
                celulas[indice].get_text(' ', strip=True),
                celulas[indice + 1].get_text(' ', strip=True)
            )

    for elemento in soup.find_all(True):
        rotulo = ' '.join(
            elemento.get(atributo, '')
            for atributo in ('id', 'name', 'aria-label', 'title', 'data-label', 'alt')
        )
        valor = (
            elemento.get('value')
            or elemento.get('data-value')
            or elemento.get_text(' ', strip=True)
        )
        if rotulo and valor:
            registrar(rotulo, valor)

    linhas_texto = [
        linha.strip() for linha in soup.get_text('\n', strip=True).splitlines()
        if linha.strip()
    ]
    for indice, linha in enumerate(linhas_texto):
        rotulo, separador, valor = linha.partition(':')
        if not separador or not valor.strip():
            valor = linhas_texto[indice + 1] if indice + 1 < len(linhas_texto) else ''
        registrar(rotulo, valor)
    return dados


def extrair_estado_produto(html):
    soup = BeautifulSoup(html, 'html.parser')
    for elemento in soup.find_all(True):
        if elemento.get_text(strip=True):
            continue
        for atributo in ('aria-valuetext', 'aria-label', 'alt', 'title', 'data-value', 'value'):
            valor_acessivel = elemento.get(atributo)
            if valor_acessivel:
                elemento.insert_after(str(valor_acessivel))
                break
    texto = soup.get_text('\n', strip=True)

    dados = {
        'modelo': 'Não identificado',
        'estado_impressora': '-',
        'tinta_preto': '-',
        'caixa_manutencao': '-',
        'nivel_papel': '-',
        'firmware': '-',
        'mac': '-',
        'nome_dispositivo': '-',
        'numero_serie': '-',
        'data_hora': '-',
    }

    titulo = soup.find('title')
    if titulo and titulo.string:
        dados['modelo'] = titulo.string.strip()
    else:
        match = re.search(r'(WF-[A-Z0-9]+[\s\S]{0,15}Series)', texto, re.IGNORECASE)
        if match:
            dados['modelo'] = match.group(1)

    padroes = {
        'estado_impressora': r'Estado da impressora\s*[:：]\s*([^\n]+)',
        'caixa_manutencao': r'Caixa de manutenção\s*[:：]\s*([^\n]+)',
        'nivel_papel': r'Nível de Papel Restante\s*[:：]\s*([^\n]+)',
        'firmware': r'Firmware\s*[:：]\s*([^\n]+)',
        'mac': r'(?:Endereço\s+)?MAC(?:\s+da\s+rede)?\s*[:：]\s*([0-9A-Fa-f:.-]{12,17})',
        'data_hora': r'Data e Hora\s*[:：]\s*([^\n]+)',
    }

    for chave, padrao in padroes.items():
        match = re.search(padrao, texto, re.IGNORECASE)
        if match:
            dados[chave] = (
                normalizar_mac(match.group(1)) or '-'
                if chave == 'mac'
                else match.group(1).strip()
            )

    dados['tinta_preto'] = extrair_nivel_tinta(soup, texto)
    dados.update(extrair_identificacao_dispositivo(soup))
    return dados


def extrair_contadores(html):
    dados = {
        'total_geral': '-',
        'total_pb': '-',
        'total_2faces': '-',
        'total_1face': '-'
    }

    def normalizar_rotulo(valor):
        texto_normalizado = unicodedata.normalize('NFKD', valor)
        texto_sem_acentos = ''.join(
            caractere for caractere in texto_normalizado
            if not unicodedata.combining(caractere)
        )
        return re.sub(r'\s+', ' ', texto_sem_acentos).strip().rstrip(':').strip().casefold()

    chaves_por_rotulo = {
        'numero total de paginas': 'total_geral',
        'numero total de paginas a p&b': 'total_pb',
        'numero total de paginas de impressao em 2 faces': 'total_2faces',
        'numero total de paginas de impressao em 1 face': 'total_1face'
    }

    soup = BeautifulSoup(html, 'html.parser')
    for rotulo in soup.find_all('dt'):
        chave = chaves_por_rotulo.get(
            normalizar_rotulo(rotulo.get_text(' ', strip=True))
        )
        valor_tag = rotulo.find_next_sibling('dd')
        if not chave or not valor_tag:
            continue
        match = re.search(r'\d[\d.,\s]*', valor_tag.get_text(' ', strip=True))
        if match:
            dados[chave] = re.sub(r'\D', '', match.group(0))

    return dados


def gerar_alertas(resultados, limite_tinta=20):
    alertas = []

    def adicionar_alerta(item, tipo, descricao, acao):
        alertas.append({
            'nome': item.get('nome', 'Impressora'),
            'setor': limpar_texto(item.get('setor')),
            'supervisor': limpar_texto(item.get('supervisor')),
            'host': limpar_texto(item.get('host')),
            'ip': limpar_texto(item.get('ip')),
            'mac': limpar_texto(item.get('mac')),
            'nome_dispositivo': limpar_texto(item.get('nome_dispositivo')),
            'numero_serie': limpar_texto(item.get('numero_serie')),
            'modelo': limpar_texto(item.get('modelo')),
            'tipo': tipo,
            'descricao': descricao,
            'acao': acao
        })

    for item in resultados:
        status = item.get('status', '')
        setor = limpar_texto(item.get('setor'))
        if status.startswith(('Erro ', 'Falha de comunicação')):
            adicionar_alerta(
                item,
                'Sem comunicação',
                f"Não foi possível consultar a impressora. Status: {status}",
                f'Acionar o TI da filial para verificar a conexão no setor {setor}.'
            )
            continue

        texto_tinta = limpar_texto(item.get('tinta_preto')).casefold()
        texto_tinta_normalizado = unicodedata.normalize('NFKD', texto_tinta)
        texto_tinta_normalizado = ''.join(
            caractere for caractere in texto_tinta_normalizado
            if not unicodedata.combining(caractere)
        )
        tinta = extrair_porcentagem(texto_tinta)
        tinta_vazia = tinta == 0 or any(
            termo in texto_tinta_normalizado
            for termo in (
                'vazio', 'empty', 'esgotad', 'acabou', 'sem tinta',
                'substitui', 'replace', 'out of ink'
            )
        )
        tinta_baixa = any(
            termo in texto_tinta_normalizado
            for termo in (
                'baixo', 'baixa', 'low', 'acabando', 'quase vazia', 'running low'
            )
        )

        if tinta_vazia:
            adicionar_alerta(
                item,
                'Tinta vazia',
                f"Tinta preta sem nível disponível: {limpar_texto(item.get('tinta_preto'))}.",
                f'Substituir o cartucho preto no setor {setor}.'
            )
        elif tinta_baixa or (tinta is not None and tinta <= limite_tinta):
            adicionar_alerta(
                item,
                'Tinta baixa',
                (
                    f"Nível de tinta preta: {tinta}% (baixo)."
                    if tinta is not None
                    else f"Tinta preta em nível baixo: {limpar_texto(item.get('tinta_preto'))}."
                ),
                f'Solicitar a troca do insumo no setor {setor}.'
            )

    prioridade = {
        'Sem comunicação': 0,
        'Tinta vazia': 1,
        'Tinta baixa': 2
    }
    return sorted(alertas, key=lambda alerta: prioridade.get(alerta['tipo'], 4))


def valores_linha_alerta_painel(alerta):
    return (
        alerta["tipo"],
        limpar_texto(alerta.get("supervisor")),
        alerta["setor"],
        alerta["nome"],
        alerta["ip"],
        limpar_texto(alerta.get("host")),
        alerta["numero_serie"],
        alerta["modelo"],
        limpar_texto(alerta.get("mac")),
    )


COLUNAS_TABELA_COMPLETA = (
    ('estado_impressora', 'Estado da impressora'),
    ('supervisor', 'Supervisor'),
    ('setor', 'Setor físico'),
    ('host', 'Hostname'),
    ('modelo', 'Modelo'),
    ('firmware', 'Firmware'),
    ('tipo_conexao', 'Tipo Conexão'),
    ('mac', 'MAC'),
    ('ip', 'IP'),
    ('numero_serie', 'Número de série'),
    ('tinta_preto', 'Tinta preta'),
    ('total_geral', 'Número total de páginas'),
    ('total_pb', 'P&B'),
    ('total_2faces', 'Impressão em 2 faces'),
    ('total_1face', 'Impressão em 1 face'),
    ('status', 'Status'),
    ('caixa_manutencao', 'Caixa de manutenção'),
    ('nivel_papel', 'Nível de papel geral'),
    ('data_hora', 'Data/hora da impressora')
)


COLUNAS_FIXAS_TABELA = ('estado_impressora', 'supervisor', 'setor', 'host')


def texto_estado_tabela(item):
    situacao = situacao_conexao(item)
    texto = "USB (local)" if situacao == "USB" else situacao
    estado = limpar_texto(item.get('estado_impressora'))
    if situacao == "ONLINE" and estado != '-':
        texto += f" · {estado}"
    return texto


def posicoes_colunas_fixas(resultados):
    """Calcula (esquerda, largura) em px das colunas fixas pelo maior texto de cada uma."""
    rotulos = dict(COLUNAS_TABELA_COMPLETA)
    posicoes = {}
    esquerda = 0
    for chave in COLUNAS_FIXAS_TABELA:
        textos = [rotulos[chave]]
        for item in resultados:
            if chave == 'estado_impressora':
                textos.append(texto_estado_tabela(item) + '   ')  # bolinha
            else:
                textos.append(limpar_texto(item.get(chave)))
        largura = max(70, min(320, round(max(map(len, textos)) * 8 + 24)))
        posicoes[chave] = (esquerda, largura)
        esquerda += largura
    return posicoes


def estilo_coluna_fixa(chave, posicoes, cabecalho=False):
    esquerda, largura = posicoes[chave]
    estilo = (
        f'position:sticky;left:{esquerda}px;z-index:{3 if cabecalho else 2};'
        f'width:{largura}px;min-width:{largura}px;max-width:{largura}px;'
        'box-sizing:border-box;white-space:normal;overflow-wrap:anywhere;'
    )
    if chave == 'host':
        estilo += 'box-shadow:4px 0 6px -2px rgba(15,23,42,.35);'
    return estilo


def gerar_tabela_completa(resultados, limite_tinta=20):
    cabecalho = []
    contadores = {'total_pb', 'total_2faces', 'total_1face'}
    colunas_contadores_destaque = contadores | {'tinta_preto'}
    identificacao = {
        'estado_impressora', 'supervisor', 'setor', 'host', 'ip',
        'tipo_conexao', 'nome', 'nome_dispositivo',
        'numero_serie', 'modelo', 'mac', 'firmware'
    }
    alertas_por_ip = {
        alerta['ip']: alerta['tipo']
        for alerta in gerar_alertas(resultados, limite_tinta)
    }
    posicoes_fixas = posicoes_colunas_fixas(resultados)
    for chave, rotulo in COLUNAS_TABELA_COMPLETA:
        estilo = (
            'border:1px solid #cbd5e1;padding:8px 10px;text-align:left;'
            'white-space:nowrap;background:#1d4ed8;color:#fff;font-weight:bold;'
        )
        if chave in COLUNAS_FIXAS_TABELA:
            estilo += estilo_coluna_fixa(chave, posicoes_fixas, cabecalho=True)
        if chave == 'total_geral':
            estilo = (
                'border:1px solid #cbd5e1;padding:8px 10px;text-align:left;'
                'white-space:nowrap;background:#facc15;color:#713f12;'
            )
        elif chave in colunas_contadores_destaque:
            estilo = (
                'border:1px solid #cbd5e1;padding:8px 10px;text-align:left;'
                'white-space:nowrap;background:#dbeafe;color:#1e3a8a;'
            )
        cabecalho.append(
            f'<th scope="col"{' class="coluna-fixa"' if chave in COLUNAS_FIXAS_TABELA else ''} style="{estilo}">{escapar_html(rotulo)}</th>'
        )

    linhas = []
    for item in resultados:
        tipo_conexao = str(
            item.get('tipo_conexao')
            or tipo_conexao_padrao(item.get('nome', ''))
        ).strip().upper()
        is_usb = tipo_conexao == 'USB'
        tipo_alerta = alertas_por_ip.get(limpar_texto(item.get('ip')))
        if tipo_alerta == 'Sem comunicação':
            classe_linha = 'sem-comunicacao'
            estilo_linha = 'background:#991b1b;color:#fff;font-weight:bold;'
        elif tipo_alerta == 'Tinta vazia':
            classe_linha = 'alerta-tinta-vazia'
            estilo_linha = 'background:#b91c1c;color:#fff;font-weight:bold;'
        elif tipo_alerta == 'Tinta baixa':
            classe_linha = 'alerta-tinta-baixa'
            estilo_linha = 'background:#c2410c;color:#fff;font-weight:bold;'
        elif is_usb:
            classe_linha = 'conexao-usb'
            estilo_linha = 'background:#1d4ed8;color:#fff;font-weight:bold;'
        else:
            classe_linha = ''
            estilo_linha = ''

        celulas = []
        for chave, _rotulo in COLUNAS_TABELA_COMPLETA:
            estilo = (
                'border:1px solid #cbd5e1;padding:8px 10px;'
                'text-align:left;vertical-align:top;white-space:nowrap;'
            )
            classe = ''
            if chave == 'total_geral':
                estilo += 'background:#fff1b8;color:#713f12;font-weight:bold;'
                classe = ' class="contador-paginas"'
            elif estilo_linha:
                estilo += estilo_linha
            elif chave in colunas_contadores_destaque:
                estilo += 'background:#eff6ff;color:#1e3a8a;'
            elif chave in identificacao:
                estilo += 'background:#f8fafc;font-weight:bold;'
            if chave in COLUNAS_FIXAS_TABELA:
                estilo += estilo_coluna_fixa(chave, posicoes_fixas)
                classe = ' class="coluna-fixa"'
            valor = (
                link_gestao_impressora_html(item.get(chave))
                if chave == 'ip'
                else indicador_situacao_html(
                    situacao_conexao(item), item.get('estado_impressora')
                )
                if chave == 'estado_impressora'
                else escapar_html(tipo_conexao)
                if chave == 'tipo_conexao'
                else escapar_html(item.get(chave))
            )
            celulas.append(f'<td{classe} style="{estilo}">{valor}</td>')
        classes = ['linha-impressora']
        if classe_linha:
            classes.append(classe_linha)
        if is_usb and 'conexao-usb' not in classes:
            classes.append('conexao-usb')
        classes_linha = ' '.join(classes)
        linhas.append(
            f'<tr class="{classes_linha}">{"".join(celulas)}</tr>'
        )
    if not linhas:
        return '<p>Nenhuma impressora foi consultada.</p>'

    return (
        '<div class="tabela-horizontal" '
        'style="max-width:100%;overflow-x:auto;overscroll-behavior-x:contain;">'
        '<table class="dados-impressora" '
        'style="border-collapse:separate;border-spacing:0;table-layout:auto;width:max-content;min-width:100%;'
        'font:13px Arial,sans-serif;">'
        f'<thead><tr>{"".join(cabecalho)}</tr></thead>'
        f'<tbody>{"".join(linhas)}</tbody></table></div>'
    )


NOME_ARQUIVO_RELATORIO_HTML = "Clique Aqui Contadores.html"
TITULO_RELATORIO = "Inventário de Impressoras CD05"


def botao_mapa_aps_html(mapa_aps):
    if not mapa_aps:
        return ''
    titulo, endereco = mapa_aps
    return (
        f'<a class="botao-mapa" href="{escapar_html(endereco)}" target="_blank" '
        f'rel="noopener noreferrer">🗺️ {escapar_html(titulo)}</a>'
    )
SUBTITULO_RELATORIO = "Envio ao fornecedor de locação"


def icone_impressora_svg(situacao):
    cor = CORES_SITUACAO.get(situacao, "#94a3b8")
    opacidade = "1" if situacao == "ONLINE" else ".6"
    return (
        f'<svg class="icone-impressora" viewBox="0 0 64 64" width="72" height="72" '
        f'aria-hidden="true" style="opacity:{opacidade}">'
        '<rect x="17" y="6" width="30" height="16" rx="2" fill="#e2e8f0" stroke="#94a3b8"/>'
        '<rect x="5" y="20" width="54" height="26" rx="6" fill="#f8fafc" stroke="#94a3b8"/>'
        '<rect x="5" y="20" width="54" height="7" rx="3" fill="#cbd5e1"/>'
        '<rect x="15" y="38" width="34" height="20" rx="2" fill="#ffffff" stroke="#94a3b8"/>'
        '<line x1="21" y1="45" x2="43" y2="45" stroke="#cbd5e1" stroke-width="2"/>'
        '<line x1="21" y1="51" x2="37" y2="51" stroke="#cbd5e1" stroke-width="2"/>'
        f'<circle cx="50" cy="33" r="4" fill="{cor}" stroke="#ffffff" stroke-width="1.5"/>'
        '</svg>'
    )


def indicadores_mapa_html(item, limite_tinta=20):
    texto_tinta = limpar_texto(item.get('tinta_preto'))
    tinta = extrair_porcentagem(texto_tinta)
    if tinta is None:
        largura, cor_tinta = 0, "#64748b"
    else:
        largura = max(0, min(100, tinta))
        cor_tinta = "#ef4444" if tinta <= limite_tinta else "#22c55e"
    return (
        '<div class="mapa-dados">'
        '<div class="mapa-dado"><span>Tinta preta</span>'
        f'<strong>{escapar_html(texto_tinta)}</strong></div>'
        '<div class="mapa-barra" role="img" '
        f'aria-label="Nível de tinta preta: {escapar_html(texto_tinta)}">'
        f'<div style="width:{largura}%;background:{cor_tinta}"></div></div>'
        '<div class="mapa-dado"><span>Páginas</span>'
        f'<strong>{escapar_html(item.get("total_geral"))}</strong></div>'
        '</div>'
    )


def gerar_mapa_impressoras(itens, limite_tinta=20):
    if not itens:
        return ''
    contagem = {"ONLINE": 0, "OFF-LINE": 0, "USB": 0}
    blocos = []
    for item in itens:
        situacao = situacao_conexao(item)
        contagem[situacao] += 1
        cor = CORES_SITUACAO[situacao]
        rotulo = "USB (local)" if situacao == "USB" else situacao
        blocos.append(
            f'<div class="mapa-item mapa-{situacao.lower().replace("-", "")}" '
            f'style="border-top-color:{cor}">'
            '<div class="mapa-rotulo">'
            f'<div class="mapa-setor">{escapar_html(item.get("setor"))}</div>'
            f'<div class="mapa-linha"><span>Hostname</span> {escapar_html(item.get("host"))}</div>'
            f'<div class="mapa-linha"><span>Supervisor</span> {escapar_html(item.get("supervisor"))}</div>'
            '</div>'
            f'{icone_impressora_svg(situacao)}'
            f'{indicadores_mapa_html(item, limite_tinta)}'
            f'<div class="mapa-situacao"><span class="mapa-bolinha" style="background:{cor}"></span>'
            f'{escapar_html(rotulo)}</div>'
            '</div>'
        )
    return f"""
        <section class="mapa-impressoras" aria-label="Situação das impressoras">
            <div class="mapa-cabecalho">
                <h2>Situação das impressoras</h2>
                <div class="mapa-legenda">
                    <span><span class="mapa-bolinha" style="background:{CORES_SITUACAO['ONLINE']}"></span>ONLINE: {contagem['ONLINE']}</span>
                    <span><span class="mapa-bolinha" style="background:{CORES_SITUACAO['OFF-LINE']}"></span>OFF-LINE: {contagem['OFF-LINE']}</span>
                    <span><span class="mapa-bolinha" style="background:{CORES_SITUACAO['USB']}"></span>USB (local): {contagem['USB']}</span>
                </div>
            </div>
            <div class="mapa-grade">{''.join(blocos)}</div>
        </section>
"""


def gerar_html(
    resultados, data_consulta, limite_tinta=20, impressoras_usb=None, mapa_aps=None
):
    alertas = gerar_alertas(resultados, limite_tinta)
    ips_resultados = {limpar_texto(item.get('ip')) for item in resultados}
    linhas_usb = linhas_usb_cadastradas(impressoras_usb, ips_resultados)

    equipamentos_ok = sum(item.get('status') == 'Sucesso' for item in resultados)
    equipamentos_parciais = sum(
        item.get('status', '').startswith('Sucesso parcial')
        for item in resultados
    )
    equipamentos_com_falha = sum(
        item.get('status', '').startswith(('Erro ', 'Falha de comunicação'))
        for item in resultados
    )
    html = f"""<!DOCTYPE html>
<html lang=\"pt-BR\">
<head>
    <meta charset=\"UTF-8\">
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
    <title>{escapar_html(TITULO_RELATORIO)}</title>
    <style>
        html {{ zoom: 75%; }}
        * {{ box-sizing: border-box; font-family: Arial, sans-serif; }}
        body {{ margin: 0; background: #eef3f8; color: #1e293b; padding: 24px; }}
        .container {{ max-width: 1280px; margin: 0 auto; }}
        .cabecalho {{ background: linear-gradient(135deg, #0f4c81, #1a73c5); color: white; padding: 28px 24px; border-radius: 12px; text-align: center; margin-bottom: 18px; }}
        .cabecalho h1 {{ margin: 0 0 6px; font-size: 30px; }}
        .cabecalho p {{ margin: 0; opacity: 0.9; }}
        .info-topo {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 10px; }}
        .botao-mapa {{ display: inline-block; background: linear-gradient(135deg, #0284c7, #06b6d4); color: #fff; text-decoration: none; font-weight: 700; font-size: 14px; padding: 9px 16px; border-radius: 8px; box-shadow: 0 3px 10px rgba(6,182,212,.35); }}
        .botao-mapa:hover {{ filter: brightness(1.08); }}
        .info-bar {{ background: white; border-radius: 10px; padding: 16px 20px; margin-bottom: 20px; box-shadow: 0 2px 6px rgba(0,0,0,0.06); }}
        .resumo {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 18px 0 0; }}
        .chip {{ background: #f1f5f9; border: 1px solid #dfe7f1; border-radius: 8px; padding: 12px 14px; }}
        .chip strong {{ display: block; font-size: 11px; color: #475569; margin-bottom: 5px; text-transform: uppercase; }}
        .chip span {{ font-size: 15px; font-weight: 700; }}
        .resumo-titulo {{ font-size: 18px; margin: 20px 0 0; color: #0f172a; }}
        .observacao {{ color: #475569; font-size: 13px; margin-top: 12px; }}
        .card {{ background: white; border-radius: 12px; box-shadow: 0 2px 6px rgba(0,0,0,0.06); overflow: hidden; margin-bottom: 22px; }}
        .card-header {{ background: #f8fafc; border-bottom: 1px solid #e2e8f0; padding: 16px 20px; font-size: 18px; font-weight: 700; display: flex; justify-content: space-between; align-items: center; }}
        .status {{ font-size: 12px; padding: 6px 10px; border-radius: 999px; font-weight: 700; }}
        .status-ok {{ background: #dcfce7; color: #166534; }}
        .status-erro {{ background: #fee2e2; color: #991b1b; }}
        .status-parcial {{ background: #fef3c7; color: #92400e; }}
        .card-body {{ padding: 20px; }}
        .localizacao-destaque {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; margin-bottom: 20px; }}
        .localizacao-item {{ padding: 13px 16px; border-radius: 9px; border-left: 5px solid; }}
        .localizacao-setor {{ background: #fff7ed; color: #9a3412; border-color: #f97316; }}
        .localizacao-ip {{ background: #eff6ff; color: #1d4ed8; border-color: #2563eb; }}
        .localizacao-item span {{ display: block; font-size: 10px; font-weight: 700; letter-spacing: .7px; margin-bottom: 4px; }}
        .localizacao-item strong {{ font-size: 17px; overflow-wrap: anywhere; }}
        .acoes-prioritarias {{ background: #fff; border: 2px solid #f59e0b; border-radius: 12px; box-shadow: 0 3px 10px rgba(146, 64, 14, .12); padding: 18px; margin: -4px 0 22px; }}
        .acoes-prioritarias h2 {{ color: #7c2d12; font-size: 20px; margin: 0 0 6px; }}
        .acoes-prioritarias > p {{ color: #475569; font-size: 13px; margin: 0 0 14px; }}
        .acoes-lista {{ display: grid; gap: 10px; }}
        .acao-item {{ background: #fffbeb; border-left: 6px solid #f59e0b; border-radius: 8px; padding: 12px 14px; }}
        .acao-comunicacao {{ background: #fef2f2; border-left-color: #dc2626; }}
        .acao-tinta-vazia {{ background: #fef2f2; border-left-color: #dc2626; }}
        .acao-tinta-baixa {{ background: #fff7ed; border-left-color: #f97316; }}
        .acao-cabecalho {{ align-items: center; display: flex; flex-wrap: wrap; gap: 8px; justify-content: space-between; }}
        .acao-tipo {{ color: #92400e; font-size: 15px; font-weight: 700; }}
        .acao-comunicacao .acao-tipo, .acao-tinta-vazia .acao-tipo {{ color: #991b1b; }}
        .acao-tinta-baixa .acao-tipo {{ color: #9a3412; }}
        .acao-equipamento {{ color: #0f172a; font-weight: 700; }}
        .acao-detalhe {{ color: #475569; font-size: 13px; margin: 7px 0 0; }}
        .acao-providencia {{ color: #7c2d12; font-weight: 700; margin: 8px 0 0; }}
        .acao-comunicacao .acao-providencia, .acao-tinta-vazia .acao-providencia {{ color: #991b1b; }}
        .acao-tinta-baixa .acao-providencia {{ color: #9a3412; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 18px; }}
        .titulo-secao {{ font-size: 15px; font-weight: 700; margin-bottom: 12px; color: #334155; border-bottom: 2px solid #e2e8f0; padding-bottom: 6px; }}
        .item {{ border-bottom: 1px solid #f1f5f9; padding: 8px 0; }}
        .label {{ font-size: 11px; color: #64748b; text-transform: uppercase; letter-spacing: .6px; }}
        .valor {{ font-size: 14px; color: #0f172a; font-weight: 600; margin-top: 2px; }}
        .alerta-box {{ background: #fff7ed; border: 1px solid #fdba74; border-left: 5px solid #f97316; padding: 14px 16px; border-radius: 8px; margin-top: 18px; }}
        .alerta-box h3 {{ margin: 0 0 12px; color: #9a4d00; }}
        .alerta-item {{ padding: 8px 0; border-bottom: 1px dashed #fed7aa; }}
        .alerta-item:last-child {{ border-bottom: none; }}
        .tabela-final {{ box-sizing: border-box; margin: 24px 0; padding: 20px; background: #fff; border: 1px solid #cbd5e1; border-radius: 12px; }}
        .tabela-final h2 {{ margin: 0 0 8px; color: #0f4c81; }}
        .tabela-final p {{ margin: 0 0 18px; color: #475569; }}
        .rodape {{ text-align: center; padding: 20px; font-size: 12px; color: #64748b; }}
        .localizacao-supervisor {{ background: #f0fdf4; color: #166534; border-color: #22c55e; }}
        .mapa-impressoras {{ background: radial-gradient(circle at 50% 0%, #1e3a8a 0%, #0b1f4d 55%, #071433 100%); border-radius: 14px; padding: 20px 22px 24px; margin-bottom: 20px; color: #e2e8f0; box-shadow: 0 4px 14px rgba(7,20,51,.35); }}
        .mapa-cabecalho {{ display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 16px; }}
        .mapa-cabecalho h2 {{ margin: 0; font-size: 20px; color: #fff; letter-spacing: .3px; }}
        .mapa-legenda {{ display: flex; flex-wrap: wrap; gap: 14px; font-size: 13px; font-weight: 700; }}
        .mapa-bolinha {{ display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 6px; vertical-align: -1px; box-shadow: 0 0 6px currentColor; border: 2px solid rgba(255,255,255,.85); }}
        .mapa-grade {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 14px; }}
        .mapa-item {{ background: rgba(15,23,42,.55); border: 1px solid rgba(148,163,184,.35); border-top: 5px solid; border-radius: 12px; padding: 12px; text-align: center; }}
        .mapa-rotulo {{ background: linear-gradient(180deg, #dbeafe, #bfdbfe); color: #0f172a; border-radius: 22px; padding: 8px 10px; margin-bottom: 8px; }}
        .mapa-setor {{ font-weight: 800; font-size: 14px; text-transform: uppercase; overflow-wrap: anywhere; }}
        .mapa-linha {{ font-size: 12px; margin-top: 2px; overflow-wrap: anywhere; }}
        .mapa-linha span {{ color: #1e40af; font-weight: 700; font-size: 10px; text-transform: uppercase; letter-spacing: .5px; }}
        .mapa-situacao {{ display: inline-block; margin-top: 4px; padding: 4px 12px; border-radius: 999px; background: rgba(2,6,23,.6); font-weight: 800; font-size: 13px; letter-spacing: .6px; }}
        .mapa-offline .mapa-situacao {{ color: #fecaca; }}
        .mapa-online .mapa-situacao {{ color: #bbf7d0; }}
        .mapa-usb .mapa-situacao {{ color: #bfdbfe; }}
        .mapa-dados {{ background: rgba(2,6,23,.45); border-radius: 10px; padding: 8px 10px; margin: 4px 0 8px; text-align: left; }}
        .mapa-dado {{ display: flex; justify-content: space-between; gap: 8px; font-size: 12px; }}
        .mapa-dado span {{ color: #93c5fd; font-weight: 700; font-size: 10px; text-transform: uppercase; letter-spacing: .5px; align-self: center; }}
        .mapa-dado strong {{ color: #fff; font-size: 14px; }}
        .mapa-barra {{ height: 8px; background: rgba(148,163,184,.3); border-radius: 999px; overflow: hidden; margin: 4px 0 8px; }}
        .mapa-barra div {{ height: 100%; border-radius: 999px; }}
        @media (max-width: 768px) {{ .card-header {{ display: block; }} .status {{ display: inline-block; margin-top: 10px; }} }}
    </style>
</head>
<body>
    <div class=\"container\">
        <div class=\"cabecalho\">
            <h1>🖨️ {escapar_html(TITULO_RELATORIO)}</h1>
            <p>{escapar_html(SUBTITULO_RELATORIO)}</p>
        </div>

        <div class=\"info-bar\">
            <div class=\"info-topo\">
                <div><strong>📅 Data da consulta:</strong> {escapar_html(data_consulta)}</div>
                {botao_mapa_aps_html(mapa_aps)}
            </div>
            <h2 class=\"resumo-titulo\">Resumo executivo</h2>
            <div class=\"resumo\">
                <div class=\"chip\"><strong>Total de equipamentos</strong><span>{len(resultados) + len(linhas_usb)}</span></div>
                <div class=\"chip\"><strong>Consultas concluídas</strong><span>{equipamentos_ok}</span></div>
                <div class=\"chip\"><strong>Consultas parciais</strong><span>{equipamentos_parciais}</span></div>
                <div class=\"chip\"><strong>Falhas de comunicação</strong><span>{equipamentos_com_falha}</span></div>
                <div class=\"chip\"><strong>Itens para atenção</strong><span>{len(alertas)}</span></div>
            </div>
            <p class=\"observacao\">O relatório detalha os equipamentos consultados; impressoras USB aparecem como não consultadas, com páginas e tinta digitadas no cadastro quando informadas.</p>
        </div>
"""

    html += gerar_mapa_impressoras(resultados + linhas_usb, limite_tinta)

    html += f"""
        <section class="tabela-final">
            <h2>Relatório por Setor x Dispositivos</h2>
            <p>Linhas de CABO ficam com fundo branco e USB é destacada em azul; falhas e alertas mantêm cores fortes. A tinta aparece antes dos contadores de páginas.</p>
            {gerar_tabela_completa(resultados + linhas_usb, limite_tinta)}
        </section>
"""

    if alertas:
        itens_acao_html = []
        for alerta in alertas:
            classe_acao = {
                'Sem comunicação': 'acao-comunicacao',
                'Tinta vazia': 'acao-tinta-vazia',
                'Tinta baixa': 'acao-tinta-baixa'
            }.get(alerta['tipo'], '')
            itens_acao_html.append(
                f"""
                <article class=\"acao-item {classe_acao}\">
                    <div class=\"acao-cabecalho\">
                        <span class=\"acao-tipo\">⚠ {escapar_html(alerta['tipo'])}</span>
                        <span class=\"acao-equipamento\">{escapar_html(alerta['nome'])} — {escapar_html(alerta['modelo'])}</span>
                    </div>
                    <p class=\"acao-detalhe\">
                        <strong>Supervisor:</strong> {escapar_html(alerta.get('supervisor'))}
                        &nbsp; | &nbsp; <strong>Setor físico:</strong> {escapar_html(alerta['setor'])}
                        &nbsp; | &nbsp; <strong>Endereço IP:</strong> {link_gestao_impressora_html(alerta['ip'])}
                        &nbsp; | &nbsp; <strong>Hostname:</strong> {escapar_html(alerta['host'])}
                    </p>
                    <p class="acao-detalhe">
                        <strong>Número de série:</strong> {escapar_html(alerta['numero_serie'])}
                    </p>
                    <p class=\"acao-detalhe\">{escapar_html(alerta['descricao'])}</p>
                    <p class=\"acao-providencia\">Ação: {escapar_html(alerta['acao'])}</p>
                </article>
                """
            )
        html += f"""
        <section class=\"acoes-prioritarias\" aria-label=\"Ações prioritárias\">
            <h2>⚠ Ações que precisam de atenção agora</h2>
            <p>Verifique os itens abaixo com prioridade e encaminhe a equipe responsável ao setor indicado.</p>
            <div class=\"acoes-lista\">{''.join(itens_acao_html)}</div>
        </section>
"""

    for r in resultados:
        if r['status'] == 'Sucesso':
            status_class = 'status-ok'
        elif r['status'].startswith('Sucesso'):
            status_class = 'status-parcial'
        else:
            status_class = 'status-erro'
        alertas_dispositivo = [a for a in alertas if a['nome'] == r['nome']]
        alertas_html = ''
        if alertas_dispositivo:
            alertas_html = '<div class="alerta-box"><h3>⚠️ Alertas</h3>' + ''.join(
                f'<div class="alerta-item"><strong>{escapar_html(a["tipo"])}</strong><br>{escapar_html(a["descricao"])}<br><strong>Ação:</strong> {escapar_html(a["acao"])}</div>'
                for a in alertas_dispositivo
            ) + '</div>'

        html += f"""
        <div class=\"card\">
            <div class=\"card-header\">
                <span>{escapar_html(r['nome'])} — {escapar_html(r['modelo'])}</span>
                <span class=\"status {status_class}\">{escapar_html(r['status'])}</span>
            </div>
            <div class=\"card-body\">
                <div class=\"localizacao-destaque\">
                    <div class=\"localizacao-item localizacao-supervisor\">
                        <span>SUPERVISOR</span>
                        <strong>{escapar_html(r.get('supervisor'))}</strong>
                    </div>
                    <div class=\"localizacao-item localizacao-setor\">
                        <span>SETOR FÍSICO</span>
                        <strong>{escapar_html(r.get('setor'))}</strong>
                    </div>
                    <div class=\"localizacao-item localizacao-ip\">
                        <span>ENDEREÇO IP</span>
                        <strong>{link_gestao_impressora_html(r.get('ip'))}</strong>
                    </div>
                </div>
                <div class=\"grid\">
                    <div>
                        <div class=\"titulo-secao\">📡 Dados da rede</div>
                        <div class=\"item\"><div class=\"label\">Hostname</div><div class=\"valor\">{escapar_html(r['host'])}</div></div>
                        <div class=\"item\"><div class=\"label\">Número de série</div><div class=\"valor\">{escapar_html(r.get('numero_serie'))}</div></div>
                        <div class=\"item\"><div class=\"label\">MAC</div><div class=\"valor\">{escapar_html(r['mac'])}</div></div>
                        <div class=\"item\"><div class=\"label\">Firmware</div><div class=\"valor\">{escapar_html(r['firmware'])}</div></div>
                        <div class=\"item\"><div class=\"label\">Data/Hora</div><div class=\"valor\">{escapar_html(r['data_hora'])}</div></div>
                    </div>

                    <div>
                        <div class=\"titulo-secao\">✅ Estado do equipamento</div>
                        <div class=\"item\"><div class=\"label\">Impressora</div><div class=\"valor\">{escapar_html(r['estado_impressora'])}</div></div>
                    </div>
                </div>

                <div class=\"grid\" style=\"margin-top: 20px;\">
                    <div>
                        <div class=\"titulo-secao\">🖋️ Insumos</div>
                        <div class=\"item\"><div class=\"label\">Tinta Preto (BK)</div><div class=\"valor\">{escapar_html(r['tinta_preto'])}</div></div>
                        <div class=\"item\"><div class=\"label\">Caixa de manutenção</div><div class=\"valor\">{escapar_html(r['caixa_manutencao'])}</div></div>
                    </div>

                    <div>
                        <div class=\"titulo-secao\">📄 Papel</div>
                        <div class=\"item\"><div class=\"label\">Nível de papel geral</div><div class=\"valor\">{escapar_html(r['nivel_papel'])}</div></div>
                    </div>

                    <div>
                        <div class=\"titulo-secao\">📊 Contadores</div>
                        <div class=\"item\"><div class=\"label\">Total geral</div><div class=\"valor\" style=\"font-size:16px; color:#0f4c81\">{escapar_html(r['total_geral'])}</div></div>
                        <div class=\"item\"><div class=\"label\">P&B</div><div class=\"valor\">{escapar_html(r['total_pb'])}</div></div>
                        <div class=\"item\"><div class=\"label\">2 faces / 1 face</div><div class=\"valor\">{escapar_html(r['total_2faces'])} / {escapar_html(r['total_1face'])}</div></div>
                    </div>
                </div>

                {alertas_html}
            </div>
        </div>
"""

    html += f"""
        <div class=\"rodape\">
            Relatório de monitoramento de impressoras • Gerado em {data_consulta}
        </div>
    </div>
</body>
</html>
"""
    return html


def salvar_relatorio(html, caminho):
    caminho = Path(caminho)
    caminho.write_text(html, encoding='utf-8')
    return caminho.resolve()


def salvar_csv(resultados, caminho, impressoras_usb=None):
    itens_relatorio = resultados + linhas_usb_cadastradas(
        impressoras_usb,
        {limpar_texto(item.get("ip")) for item in resultados}
    )
    colunas = [
        ('supervisor', 'Supervisor'),
        ('setor', 'Setor físico'),
        ('host', 'Hostname'),
        ('ip', 'IP'),
        ('numero_serie', 'Número de série'),
        ('modelo', 'Modelo'),
        ('mac', 'MAC'),
        ('firmware', 'Firmware'),
        ('total_geral', 'Total geral'),
        ('total_pb', 'Total P&B'),
        ('total_2faces', 'Total 2 faces'),
        ('total_1face', 'Total 1 face'),
        ('status', 'Status'),
        ('estado_impressora', 'Estado da impressora'),
        ('tinta_preto', 'Tinta preta'),
        ('caixa_manutencao', 'Caixa de manutenção'),
        ('nivel_papel', 'Nível de papel'),
        ('data_hora', 'Data/hora da impressora'),
    ]
    caminho = Path(caminho)
    with caminho.open('w', newline='', encoding='utf-8-sig') as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=[rotulo for _, rotulo in colunas])
        escritor.writeheader()
        for item in itens_relatorio:
            escritor.writerow({
                rotulo: limpar_texto(item.get(chave))
                for chave, rotulo in colunas
            })
    return caminho.resolve()


# ---------------------------------------------------------------------------
# Módulo 3: coletores (Zebra / Honeywell)
# ---------------------------------------------------------------------------
FABRICANTES_COLETOR = ("Zebra", "Honeywell", "Outro")
TITULO_COLETORES = "Coletores CD05"
SUBTITULO_COLETORES = "Levantamento de coletores Zebra e Honeywell por setor"
NOME_ARQUIVO_RELATORIO_COLETORES = "Clique Aqui Coletores.html"
CAMPOS_TEXTO_COLETOR = (
    "setor", "supervisor", "fabricante", "modelo", "numero_serie",
    "versao_app", "versao_anterior", "hostname", "mac", "usuario", "observacao",
)
CAMPOS_STATUS_COLETOR = ("situacao_consultada", "ip_atual", "verificado_em", "visto_online_em")
SITUACOES_COLETOR = {
    "ONLINE": "Online",
    "OFF-LINE": "Offline",
    "SEM MAC": "Sem MAC",
    "-": "Não verificado",
}
MAX_ENDERECOS_FAIXA_COLETORES = 4096
COLUNAS_COLETORES = (
    ("situacao_consultada", "Status"),
    ("setor", "Setor físico"),
    ("supervisor", "Supervisor"),
    ("fabricante", "Fabricante"),
    ("modelo", "Modelo"),
    ("numero_serie", "Número de série"),
    ("versao_app", "Versão do app"),
    ("versao_anterior", "Versão anterior"),
    ("hostname", "Hostname"),
    ("mac", "MAC Wi-Fi"),
    ("ip_atual", "IP atual"),
    ("visto_online_em", "Visto online em"),
    ("usuario", "Usuário"),
    ("piloto", "Piloto"),
    ("observacao", "Observação"),
)


def validar_lista_coletores(lista):
    if lista is None:
        return []
    if not isinstance(lista, list):
        raise ValueError("A lista de coletores deve ser uma lista.")
    validados = []
    series = set()
    for indice, item in enumerate(lista, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"O coletor {indice} está em formato inválido.")
        coletor = {}
        for chave in CAMPOS_TEXTO_COLETOR:
            valor = item.get(chave, "")
            if valor is None:
                valor = ""
            if not isinstance(valor, str):
                raise ValueError(f"O campo {chave} do coletor {indice} deve ser texto.")
            coletor[chave] = valor.strip()
        if not coletor["setor"]:
            raise ValueError(f"Informe o setor do coletor {indice}.")
        coletor["numero_serie"] = coletor["numero_serie"].upper()
        if not coletor["numero_serie"]:
            raise ValueError(f"Informe o número de série do coletor {indice}.")
        if coletor["numero_serie"] in series:
            raise ValueError(
                f"O número de série {coletor['numero_serie']} está cadastrado mais de uma vez."
            )
        series.add(coletor["numero_serie"])
        fabricante = next(
            (f for f in FABRICANTES_COLETOR if f.casefold() == coletor["fabricante"].casefold()),
            None,
        )
        if fabricante is None:
            raise ValueError(
                f"Fabricante inválido no coletor {indice}. Use: {', '.join(FABRICANTES_COLETOR)}."
            )
        coletor["fabricante"] = fabricante
        if coletor["mac"]:
            mac = normalizar_mac(coletor["mac"])
            if not mac:
                raise ValueError(f"MAC inválido no coletor {indice}: {coletor['mac']}")
            coletor["mac"] = mac
        coletor["piloto"] = bool(item.get("piloto", False))
        for chave in CAMPOS_STATUS_COLETOR:
            valor = item.get(chave, "")
            coletor[chave] = valor.strip() if isinstance(valor, str) else ""
        if coletor["situacao_consultada"] not in SITUACOES_COLETOR:
            coletor["situacao_consultada"] = "-"
        validados.append(coletor)
    return validados


def supervisor_do_setor(setor, registros):
    """Supervisor já usado para o setor em qualquer cadastro (impressoras ou coletores)."""
    alvo = str(setor or "").strip().casefold()
    for registro in registros or []:
        if str(registro.get("setor", "")).strip().casefold() == alvo:
            supervisor = str(registro.get("supervisor", "")).strip()
            if supervisor:
                return supervisor
    return ""


def setores_e_supervisores(registros):
    """Listas de setores e supervisores já cadastrados, sem repetir (ignora maiúsculas)."""
    def unicos(chave):
        vistos = {}
        for registro in registros or []:
            valor = str(registro.get(chave, "") or "").strip()
            if valor and valor.casefold() not in vistos:
                vistos[valor.casefold()] = valor
        return sorted(vistos.values(), key=str.casefold)
    return unicos("setor"), unicos("supervisor")


def ligar_setor_ao_supervisor(variavel_setor, variavel_supervisor, registros):
    """Ao escolher um setor conhecido, preenche o supervisor ligado a ele."""
    def ao_mudar_setor(*_args):
        supervisor = supervisor_do_setor(variavel_setor.get(), registros())
        if supervisor:
            variavel_supervisor.set(supervisor)
    variavel_setor.trace_add("write", ao_mudar_setor)


def coletores_ordenados(coletores):
    return sorted(
        coletores,
        key=lambda c: (
            c.get("setor", "").casefold(), c.get("fabricante", ""), c.get("numero_serie", "")
        ),
    )


def texto_coluna_coletor(coletor, chave):
    if chave == "situacao_consultada":
        return SITUACOES_COLETOR.get(coletor.get(chave) or "-", "Não verificado")
    if chave == "piloto":
        return "Sim" if coletor.get("piloto") else "Não"
    return limpar_texto(coletor.get(chave))


def valor_csv_seguro(valor):
    """Evita que o Excel interprete o texto como fórmula."""
    texto = str(valor)
    if texto != "-" and texto[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + texto
    return texto


def salvar_csv_coletores(coletores, caminho):
    caminho = Path(caminho)
    with caminho.open("w", newline="", encoding="utf-8-sig") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow([rotulo for _, rotulo in COLUNAS_COLETORES])
        for coletor in coletores_ordenados(coletores):
            escritor.writerow([
                valor_csv_seguro(texto_coluna_coletor(coletor, chave))
                for chave, _ in COLUNAS_COLETORES
            ])
    return caminho.resolve()


# ================= STATUS DOS COLETORES (REDE WI-FI) =================
def validar_faixa_coletores(faixa_texto):
    if not faixa_texto:
        return None
    try:
        faixa = ipaddress.ip_network(faixa_texto, strict=False)
    except ValueError as exc:
        raise ValueError(
            "A faixa da rede dos coletores deve estar em formato CIDR IPv4, por exemplo 10.50.0.0/22."
        ) from exc
    if faixa.version != 4:
        raise ValueError("A faixa da rede dos coletores deve ser IPv4.")
    if faixa.num_addresses > MAX_ENDERECOS_FAIXA_COLETORES:
        raise ValueError(
            "A faixa da rede dos coletores é grande demais (máximo /20, 4096 endereços)."
        )
    return faixa


def aviso_rede_coletores(config):
    wifi = str(config.get("wifi_coletores") or "").strip()
    unidade = str(config.get("nome_unidade") or "").strip() or "da unidade"
    rede = f' "{wifi}"' if wifi else ""
    return (
        f"Conecte na rede Wi-Fi dos coletores{rede} para ter o resultado de status "
        f"online e offline de todos os coletores cadastrados como ativo {unidade}."
    )


def ssids_conectados():
    """Nomes das redes Wi-Fi conectadas agora (netsh wlan show interfaces)."""
    netsh = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "netsh.exe"
    try:
        processo = subprocess.run(
            [str(netsh), "wlan", "show", "interfaces"],
            capture_output=True, encoding="oem", errors="replace", timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return extrair_ssids(processo.stdout)


def extrair_ssids(texto):
    return re.findall(r"^\s*SSID\s*:\s*(.+?)\s*$", texto or "", re.MULTILINE)


def ip_local_para(destino):
    """IP deste computador usado para chegar ao destino ('' se não houver rota)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as conexao:
        try:
            conexao.connect((str(destino), 9))
            return conexao.getsockname()[0]
        except OSError:
            return ""


def situacao_rede_coletores(config, ssids=None, ip_local=None):
    """(conectado, mensagem): o computador está na rede Wi-Fi/faixa dos coletores?"""
    faixa = validar_faixa_coletores(str(config.get("faixa_rede_coletores") or "").strip())
    if faixa is None:
        return False, (
            "A rede dos coletores ainda não foi configurada. Informe "
            '"wifi_coletores" e "faixa_rede_coletores" no config.json.'
        )
    wifi = str(config.get("wifi_coletores") or "").strip()
    if wifi:
        if ssids is None:
            ssids = ssids_conectados()
        if not any(s.casefold() == wifi.casefold() for s in ssids):
            return False, aviso_rede_coletores(config)
    if ip_local is None:
        ip_local = ip_local_para(next(faixa.hosts(), faixa.network_address))
    try:
        dentro = bool(ip_local) and ipaddress.ip_address(ip_local) in faixa
    except ValueError:
        dentro = False
    if not dentro:
        return False, aviso_rede_coletores(config)
    return True, f"Conectado à rede dos coletores (IP deste computador: {ip_local})."


def ler_tabela_arp(texto=None):
    """{MAC: IP} da tabela ARP do Windows (arp -a), sem broadcast/multicast."""
    if texto is None:
        arp = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "arp.exe"
        try:
            texto = subprocess.run(
                [str(arp), "-a"], capture_output=True, encoding="oem", errors="replace",
                timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return {}
    tabela = {}
    for ip, mac_bruto in re.findall(
        r"((?:\d{1,3}\.){3}\d{1,3})\s+([0-9A-Fa-f]{2}(?:[-:][0-9A-Fa-f]{2}){5})", texto or ""
    ):
        mac = normalizar_mac(mac_bruto)
        if not mac or mac in ("FF:FF:FF:FF:FF:FF", "00:00:00:00:00:00"):
            continue
        if int(mac[:2], 16) & 1:  # multicast
            continue
        tabela[mac] = ip
    return tabela


def macs_na_rede_coletores(faixa_texto, passadas=2, espera=2.0):
    """Provoca a resolução ARP de todos os IPs da faixa e devolve {MAC: IP} encontrados."""
    faixa = validar_faixa_coletores(faixa_texto)
    if faixa is None:
        return {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as conexao:
        conexao.setblocking(False)
        for _ in range(passadas):
            for endereco in faixa.hosts():
                try:
                    conexao.sendto(b"\0", (str(endereco), 9))
                except OSError:
                    pass
            time.sleep(espera)
    return {
        mac: ip for mac, ip in ler_tabela_arp().items()
        if ipaddress.ip_address(ip) in faixa
    }


def aplicar_status_coletores(coletores, macs_online, quando):
    """Marca cada coletor como ONLINE/OFF-LINE/SEM MAC pelo MAC Wi-Fi cadastrado."""
    atualizados = []
    for coletor in coletores:
        novo = dict(coletor)
        mac = normalizar_mac(novo.get("mac"))
        novo["verificado_em"] = quando
        if not mac:
            novo["situacao_consultada"] = "SEM MAC"
            novo["ip_atual"] = ""
        elif mac in macs_online:
            novo["situacao_consultada"] = "ONLINE"
            novo["ip_atual"] = macs_online[mac]
            novo["visto_online_em"] = quando
        else:
            novo["situacao_consultada"] = "OFF-LINE"
            novo["ip_atual"] = ""
        atualizados.append(novo)
    return atualizados


def ultima_verificacao_coletores(coletores):
    datas = [c.get("verificado_em") for c in coletores if c.get("verificado_em")]
    if not datas:
        return ""
    return max(datas, key=lambda d: datetime.strptime(d, "%d/%m/%Y %H:%M:%S")
               if re.fullmatch(r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}", d) else datetime.min)


def resumo_status_coletores(coletores):
    contagem = {chave: 0 for chave in SITUACOES_COLETOR}
    for coletor in coletores:
        contagem[coletor.get("situacao_consultada") or "-"] = (
            contagem.get(coletor.get("situacao_consultada") or "-", 0) + 1
        )
    return contagem


def gerar_html_coletores(coletores, data_geracao, aviso=""):
    ordenados = coletores_ordenados(coletores)
    status = resumo_status_coletores(ordenados)
    ultima = ultima_verificacao_coletores(ordenados)
    por_fabricante = {
        f: sum(c["fabricante"] == f for c in ordenados) for f in FABRICANTES_COLETOR
    }
    setores = []
    for c in ordenados:
        if c["setor"] not in setores:
            setores.append(c["setor"])
    versoes = {}
    for c in ordenados:
        versao = c.get("versao_app") or "Não informada"
        versoes[versao] = versoes.get(versao, 0) + 1

    chips_status = (
        ("Online", status["ONLINE"], "online"),
        ("Offline", status["OFF-LINE"], "offline"),
        ("Não verificado", status["-"], "neutro"),
        ("Sem MAC", status["SEM MAC"], "neutro"),
    )
    html_chips_status = "".join(
        f'<div class="chip chip-{classe}"><strong>{escapar_html(rotulo)}</strong><span>{valor}</span></div>'
        for rotulo, valor, classe in chips_status
    )
    html_aviso = (
        f'<div class="aviso">📶 {escapar_html(aviso)}</div>' if aviso else ""
    )
    texto_ultima = (
        f"Última verificação de status: {escapar_html(ultima)}" if ultima
        else "Status ainda não verificado nesta unidade."
    )
    chips = (
        ("Total de coletores", len(ordenados)),
        ("Zebra", por_fabricante["Zebra"]),
        ("Honeywell", por_fabricante["Honeywell"]),
        ("Outros", por_fabricante["Outro"]),
        ("No piloto", sum(bool(c.get("piloto")) for c in ordenados)),
        ("Setores", len(setores)),
    )
    html_chips = "".join(
        f'<div class="chip"><strong>{escapar_html(rotulo)}</strong><span>{valor}</span></div>'
        for rotulo, valor in chips
    )
    html_versoes = "".join(
        f'<span class="versao"><strong>{escapar_html(versao)}</strong> · {qtd}</span>'
        for versao, qtd in sorted(versoes.items(), key=lambda par: (-par[1], par[0]))
    ) or '<span class="versao">Nenhum coletor cadastrado</span>'

    total_colunas = len(COLUNAS_COLETORES)
    cabecalho = "".join(f"<th>{escapar_html(rotulo)}</th>" for _, rotulo in COLUNAS_COLETORES)
    linhas = []
    for setor in setores:
        do_setor = [c for c in ordenados if c["setor"] == setor]
        linhas.append(
            f'<tr class="grupo-setor"><td colspan="{total_colunas}">'
            f'{escapar_html(setor)} — {len(do_setor)} coletor(es)</td></tr>'
        )
        for c in do_setor:
            classe = ' class="piloto"' if c.get("piloto") else ""
            celulas = "".join(
                (
                    f'<td><span class="status st-{escapar_html((c.get(chave) or "-").lower())}">'
                    f"{escapar_html(texto_coluna_coletor(c, chave))}</span></td>"
                ) if chave == "situacao_consultada" else
                f"<td>{escapar_html(texto_coluna_coletor(c, chave))}</td>"
                for chave, _ in COLUNAS_COLETORES
            )
            linhas.append(f"<tr{classe}>{celulas}</tr>")
    corpo_tabela = "".join(linhas) or (
        f'<tr><td colspan="{total_colunas}">Nenhum coletor cadastrado.</td></tr>'
    )

    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escapar_html(TITULO_COLETORES)}</title>
<style>
    body {{ margin: 0; padding: 20px; background: #eef3f8; color: #1e293b; font-family: Arial, sans-serif; }}
    .container {{ max-width: 1280px; margin: 0 auto; }}
    .cabecalho {{ background: linear-gradient(135deg, #0f4c81, #1d72b8); color: #fff; border-radius: 12px; padding: 22px; text-align: center; margin-bottom: 18px; }}
    .cabecalho h1 {{ margin: 0 0 6px; font-size: 26px; }}
    .cabecalho p {{ margin: 0; opacity: .9; }}
    .bloco {{ background: #fff; border-radius: 10px; padding: 16px 20px; margin-bottom: 18px; box-shadow: 0 2px 6px rgba(0,0,0,.06); }}
    .resumo {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-top: 12px; }}
    .chip {{ background: #f1f5f9; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px; }}
    .chip strong {{ display: block; font-size: 11px; text-transform: uppercase; color: #475569; letter-spacing: .4px; }}
    .chip span {{ font-size: 20px; font-weight: 700; color: #0f4c81; }}
    .versoes {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }}
    .versao {{ background: #e0f2fe; color: #075985; border-radius: 999px; padding: 4px 12px; font-size: 13px; }}
    h2 {{ margin: 0 0 8px; color: #0f4c81; font-size: 18px; }}
    .tabela {{ overflow-x: auto; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th {{ background: #1d4ed8; color: #fff; text-align: left; padding: 8px 10px; white-space: nowrap; }}
    td {{ border-bottom: 1px solid #e2e8f0; padding: 7px 10px; white-space: nowrap; }}
    tr.grupo-setor td {{ background: #dbeafe; color: #1e3a8a; font-weight: 700; text-transform: uppercase; }}
    tr.piloto td {{ background: #fef9c3; }}
    .legenda {{ font-size: 12px; color: #64748b; margin-top: 8px; }}
    .aviso {{ background: #fff7ed; border: 1px solid #fdba74; color: #9a3412; border-radius: 10px; padding: 12px 16px; margin-bottom: 18px; font-weight: 700; }}
    .chip-online {{ background: #dcfce7; border-color: #86efac; }}
    .chip-online span {{ color: #15803d; }}
    .chip-offline {{ background: #fee2e2; border-color: #fca5a5; }}
    .chip-offline span {{ color: #b91c1c; }}
    .chip-neutro span {{ color: #64748b; }}
    .verificacao {{ font-size: 13px; color: #475569; margin-top: 6px; }}
    .status {{ display: inline-block; border-radius: 999px; padding: 2px 10px; font-weight: 700; font-size: 12px; }}
    .status::before {{ content: "●"; margin-right: 5px; }}
    .st-online {{ background: #dcfce7; color: #15803d; }}
    .st-off-line {{ background: #fee2e2; color: #b91c1c; }}
    .st-- , .st-sem {{ background: #f1f5f9; color: #64748b; }}
</style>
</head>
<body>
<div class="container">
    <div class="cabecalho">
        <h1>📟 {escapar_html(TITULO_COLETORES)}</h1>
        <p>{escapar_html(SUBTITULO_COLETORES)}</p>
    </div>
    {html_aviso}
    <div class="bloco">
        <h2>Situação dos coletores</h2>
        <div class="verificacao">{texto_ultima}</div>
        <div class="resumo">{html_chips_status}</div>
    </div>
    <div class="bloco">
        <strong>📅 Gerado em:</strong> {escapar_html(data_geracao)}
        <div class="resumo">{html_chips}</div>
        <h2 style="margin-top:16px">Versões do app de gerenciamento</h2>
        <div class="versoes">{html_versoes}</div>
    </div>
    <div class="bloco">
        <h2>Coletores por setor</h2>
        <div class="tabela"><table class="tabela-coletores">
            <thead><tr>{cabecalho}</tr></thead>
            <tbody>{corpo_tabela}</tbody>
        </table></div>
        <p class="legenda">Linhas em amarelo: coletores do piloto da versão nova do app.</p>
    </div>
</div>
</body>
</html>
"""


def abrir_relatorio_navegador(caminho_arquivo):
    if not webbrowser.open(Path(caminho_arquivo).resolve().as_uri(), new=2):
        raise RuntimeError('Não foi possível abrir o navegador padrão.')


def limpar_numero_whatsapp(numero):
    numero = re.sub(r'[^0-9]', '', str(numero))
    if numero.startswith('00'):
        numero = numero[2:]
    if numero.startswith('55'):
        return numero
    if numero.startswith('0'):
        numero = numero[1:]
    if len(numero) in (10, 11):
        return f'55{numero}'
    return numero


def separar_whatsapp_numeros(numeros):
    numeros_digitados = [numero.strip() for numero in re.split(r'[;,]', str(numeros))]
    if not numeros_digitados or any(not numero for numero in numeros_digitados):
        raise ValueError('Informe números de WhatsApp separados por ponto e vírgula.')

    numeros_formatados = []
    for numero in numeros_digitados:
        numero_formatado = limpar_numero_whatsapp(numero)
        if not 12 <= len(numero_formatado) <= 15:
            raise ValueError(
                f'Número de WhatsApp inválido: {numero}. Informe DDD e número ou DDI.'
            )
        if numero_formatado not in numeros_formatados:
            numeros_formatados.append(numero_formatado)
    return numeros_formatados


def atualizar_relatorios_salvos(
    resultados, data_consulta, caminho_html, caminho_csv,
    limite_tinta=20, impressoras_usb=None, mapa_aps=None
):
    if resultados is None or caminho_html is None or caminho_csv is None:
        raise ValueError("Não há consulta concluída para atualizar os relatórios.")
    aplicar_dados_cadastro(resultados, impressoras_usb)
    html_relatorio = gerar_html(
        resultados,
        data_consulta,
        limite_tinta,
        impressoras_usb=impressoras_usb,
        mapa_aps=mapa_aps
    )
    caminho_html = salvar_relatorio(html_relatorio, caminho_html)
    caminho_csv = salvar_csv(resultados, caminho_csv, impressoras_usb)
    return caminho_html, caminho_csv


def montar_email_body(
    resultados, data_consulta, caminho_html, caminho_csv, limite_tinta=20,
    impressoras_usb=None
):
    itens_relatorio = resultados + linhas_usb_cadastradas(
        impressoras_usb,
        {limpar_texto(item.get("ip")) for item in resultados}
    )
    return f"""<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"><title>Relatório Mensal de Impressoras</title></head>
<body style="font-family:Arial,sans-serif;color:#1e293b;">
    <p>Prezados,</p>
    <p>Encaminho o relatório técnico mensal dos equipamentos de impressão locados.</p>
    <p><strong>Data da consulta:</strong> {escapar_html(data_consulta)}<br>
    <strong>Equipamentos consultados pela rede:</strong> {len(resultados)}<br>
    <strong>Impressoras USB cadastradas:</strong> {len(itens_relatorio) - len(resultados)}</p>
    <h2 style="color:#0f4c81;">Detalhamento dos equipamentos</h2>
    <p>Os dados de identificação ficam agrupados com IP e MAC, antes dos contadores; as linhas destacadas indicam falhas ou alertas. O total de páginas está em amarelo.</p>
    {gerar_tabela_completa(itens_relatorio, limite_tinta)}
    <h3 style="color:#0f4c81;">Arquivos do relatório</h3>
    <p>HTML: {escapar_html(caminho_html)}<br>
    CSV: {escapar_html(caminho_csv)}</p>
    <p>Anexe os arquivos HTML e CSV a este rascunho antes do envio.</p>
    <p>Atenciosamente,<br>TI / Suporte</p>
</body>
</html>"""


def converter_email_html_para_texto(body):
    texto = re.sub(r'<style\b[^>]*>.*?</style>', '', body, flags=re.IGNORECASE | re.DOTALL)
    texto = re.sub(r'<br\s*/?>', '\n', texto, flags=re.IGNORECASE)
    texto = re.sub(r'</t[hd]\s*>', ' | ', texto, flags=re.IGNORECASE)
    texto = re.sub(r'</tr\s*>', '\n', texto, flags=re.IGNORECASE)
    texto = re.sub(r'</(?:p|h[1-6]|div)\s*>', '\n', texto, flags=re.IGNORECASE)
    texto = re.sub(r'<[^>]+>', '', texto)
    texto = html.unescape(texto)
    return '\n'.join(linha.strip() for linha in texto.splitlines() if linha.strip())


def montar_whatsapp_body(resultados, data_consulta, impressoras_usb=None):
    itens_relatorio = resultados + linhas_usb_cadastradas(
        impressoras_usb,
        {limpar_texto(item.get("ip")) for item in resultados}
    )
    linhas = [
        'Bom dia,',
        '',
        'Segue Relatório Mensal de Impressoras:',
        f'Data: {data_consulta}',
        ''
    ]

    falhas_comunicacao = [
        item for item in resultados
        if item.get('status', '').startswith(('Erro ', 'Falha de comunicação'))
    ]
    if falhas_comunicacao:
        linhas.extend([
            '*⚠️ IMPRESSORAS SEM COMUNICAÇÃO — ACIONAR O TI DA FILIAL*',
            ''
        ])
        for item in falhas_comunicacao:
            ip = limpar_texto(item.get('ip'))
            linhas.extend([
                f"*{limpar_texto(item.get('nome'), 'Impressora')} — SEM COMUNICAÇÃO*",
                f"Setor: {limpar_texto(item.get('setor'))} | "
                f"Supervisor: {limpar_texto(item.get('supervisor'))}",
                f"Máquina: {limpar_texto(item.get('host'))}",
                f"IP: {ip} | Gestão: {url_gestao_impressora(ip) or '-'} | "
                f"MAC: {limpar_texto(item.get('mac'))}",
                f"Número de série: {limpar_texto(item.get('numero_serie'))} | "
                f"Modelo: {limpar_texto(item.get('modelo'))}",
                '*Ação: acionar o TI da filial.*',
                ''
            ])
    else:
        linhas.extend(['*Sem falhas de comunicação registradas.*', ''])

    linhas.extend(['*DETALHAMENTO COMPLETO*', ''])
    for item in itens_relatorio:
        ip = limpar_texto(item.get('ip'))
        linhas.extend([
            f"Setor físico: {limpar_texto(item.get('setor'))} | "
            f"Supervisor: {limpar_texto(item.get('supervisor'))}",
            f"Hostname: {limpar_texto(item.get('host'))} | IP: {ip} | "
            f"Gestão: {url_gestao_impressora(ip) or '-'} | "
            f"MAC: {limpar_texto(item.get('mac'))}",
            f"Número de série: {limpar_texto(item.get('numero_serie'))} | "
            f"Modelo: {limpar_texto(item.get('modelo'))}",
            f"Status: {limpar_texto(item.get('status'))}",
            f"Tinta preta: {limpar_texto(item.get('tinta_preto'))}",
            (
                f"Contadores — Total: {limpar_texto(item.get('total_geral'))} | "
                f"P&B: {limpar_texto(item.get('total_pb'))} | "
                f"2 faces: {limpar_texto(item.get('total_2faces'))} | "
                f"1 face: {limpar_texto(item.get('total_1face'))}"
            ),
            ''
        ])

    linhas.extend([
        '',
        'Obrigado.',
        'TI'
    ])
    return '\n'.join(linhas)


def separar_emails(email):
    enderecos = [endereco.strip() for endereco in re.split(r'[;,]', str(email))]
    if not enderecos or any(
        not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', endereco)
        for endereco in enderecos
    ):
        raise ValueError(
            'Informe endereços de e-mail válidos, separados por ponto e vírgula.'
        )
    return enderecos


def abrir_email(email, body, assunto='Relatório Mensal de Impressoras'):
    enderecos = separar_emails(email)
    abrir_arquivo = getattr(os, 'startfile', None)
    if not callable(abrir_arquivo):
        raise RuntimeError('A abertura de rascunhos .eml está disponível apenas no Windows.')

    mensagem = EmailMessage()
    mensagem['To'] = ', '.join(enderecos)
    mensagem['Subject'] = assunto
    mensagem['X-Unsent'] = '1'
    mensagem.set_content(converter_email_html_para_texto(body))
    mensagem.add_alternative(body, subtype='html')

    pasta_rascunhos = PASTA_DADOS / 'rascunhos'
    pasta_rascunhos.mkdir(parents=True, exist_ok=True)
    caminho_eml = pasta_rascunhos / f"rascunho_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.eml"
    with caminho_eml.open('wb') as arquivo:
        arquivo.write(mensagem.as_bytes())
    caminho_eml = caminho_eml.resolve()
    try:
        abrir_arquivo(str(caminho_eml))
    except OSError as exc:
        raise RuntimeError(
            f'O rascunho foi criado em {caminho_eml}, mas o Windows não conseguiu '
            'abrir arquivos .eml. Se o Outlook estiver instalado, configure-o como '
            'aplicativo padrão para arquivos .eml e tente novamente.'
        ) from exc
    return caminho_eml


def abrir_whatsapp(numero, body):
    if not numero:
        raise ValueError('Número do WhatsApp não informado.')
    numeros_formatados = separar_whatsapp_numeros(numero)
    texto_url = quote(body, safe='')
    for numero_formatado in numeros_formatados:
        url = f'https://wa.me/{numero_formatado}?text={texto_url}'
        if not webbrowser.open(url, new=2):
            raise RuntimeError(
                f'Não foi possível abrir a conversa do WhatsApp para {numero_formatado}.'
            )


def consultar_impressoras(progress_callback=None, lista_impressoras=None):
    resultados = []
    dispositivos = lista_impressoras if lista_impressoras is not None else impressoras
    dispositivos = filtrar_impressoras_de_rede(dispositivos)
    total_impressoras = len(dispositivos)
    for indice, imp in enumerate(dispositivos, start=1):
        nome = imp['nome']
        setor = imp.get('setor', 'Não informado')
        ip = imp['ip']
        host = imp['host']
        supervisor = limpar_texto(imp.get('supervisor'))
        try:
            url_estado = f'https://{ip}{CAMINHO_ESTADO}'
            resp_estado = requests.get(url_estado, timeout=8, verify=False)
            if resp_estado.status_code != 200:
                resultados.append({
                    'nome': nome,
                    'setor': setor,
                    'supervisor': supervisor,
                    'ip': ip,
                    'host': host,
                    'tipo_conexao': (
                        imp.get('tipo_conexao') or tipo_conexao_padrao(nome)
                    ),
                    'status': f'Erro {resp_estado.status_code}',
                    'modelo': '-', 'estado_impressora': '-',
                    'tinta_preto': '-', 'caixa_manutencao': '-', 'nivel_papel': '-',
                    'firmware': '-', 'mac': normalizar_mac(imp.get('mac')) or '-',
                    'nome_dispositivo': '-',
                    'numero_serie': limpar_texto(imp.get('numero_serie')),
                    'data_hora': '-',
                    'total_geral': '-', 'total_pb': '-',
                    'total_2faces': '-', 'total_1face': '-'
                })
                continue

            dados_estado = extrair_estado_produto(resp_estado.content)
            dados_identificacao = {
                chave: limpar_texto(dados_estado.get(chave))
                for chave in ('nome_dispositivo', 'numero_serie', 'mac')
            }
            url_contador = f'https://{ip}{CAMINHO_CONTADOR}'
            resp_contador = requests.get(url_contador, timeout=8, verify=False)

            dados_contador = {
                'total_geral': '-', 'total_pb': '-',
                'total_2faces': '-', 'total_1face': '-'
            }
            avisos_parciais = []
            if resp_contador.status_code == 200:
                dados_contador = extrair_contadores(resp_contador.content)
                if all(valor == '-' for valor in dados_contador.values()):
                    avisos_parciais.append('contadores não encontrados')
            else:
                avisos_parciais.append(f'contadores HTTP {resp_contador.status_code}')

            if any(
                dados_identificacao[chave] == '-'
                for chave in ('numero_serie', 'mac')
            ):
                url_rede = f'https://{ip}{CAMINHO_REDE}'
                try:
                    resp_rede = requests.get(url_rede, timeout=4, verify=False)
                    if resp_rede.status_code == 200:
                        dados_rede = extrair_identificacao_dispositivo(resp_rede.content)
                        for chave in dados_identificacao:
                            if dados_identificacao[chave] == '-':
                                dados_identificacao[chave] = limpar_texto(dados_rede.get(chave))
                    else:
                        avisos_parciais.append(
                            f'identificação de rede HTTP {resp_rede.status_code}'
                        )
                except requests.RequestException as exc:
                    avisos_parciais.append(f'consulta de identificação de rede falhou: {exc}')

            if dados_identificacao['numero_serie'] == '-':
                mac_cadastrado = normalizar_mac(imp.get('mac'))
                mac_encontrado = normalizar_mac(dados_identificacao.get('mac'))
                serial_cadastrado = limpar_texto(imp.get('numero_serie'))
                if (
                    serial_cadastrado != '-'
                    and not (
                        mac_cadastrado and mac_encontrado
                        and mac_cadastrado != mac_encontrado
                    )
                ):
                    dados_identificacao['numero_serie'] = serial_cadastrado
            if dados_identificacao['mac'] == '-':
                dados_identificacao['mac'] = normalizar_mac(imp.get('mac')) or '-'
            identificacao_ausente = [
                rotulo
                for chave, rotulo in (
                    ('numero_serie', 'número de série'),
                )
                if dados_identificacao[chave] == '-'
            ]
            if identificacao_ausente:
                avisos_parciais.append(
                    f'{", ".join(identificacao_ausente)} não identificado(s)'
                )
            resultados_status = (
                'Sucesso' if not avisos_parciais
                else f"Sucesso parcial - {'; '.join(avisos_parciais)}"
            )

            resultados.append({
                'nome': nome,
                'setor': setor,
                'supervisor': supervisor,
                'ip': ip,
                'host': host,
                'tipo_conexao': (
                    imp.get('tipo_conexao') or tipo_conexao_padrao(nome)
                ),
                'status': resultados_status,
                'nome_dispositivo': dados_identificacao['nome_dispositivo'],
                'numero_serie': dados_identificacao['numero_serie'],
                'modelo': limpar_texto(dados_estado.get('modelo')),
                'estado_impressora': limpar_texto(dados_estado.get('estado_impressora')),
                'tinta_preto': limpar_texto(dados_estado.get('tinta_preto')),
                'caixa_manutencao': limpar_texto(dados_estado.get('caixa_manutencao')),
                'nivel_papel': limpar_texto(dados_estado.get('nivel_papel')),
                'firmware': limpar_texto(dados_estado.get('firmware')),
                'mac': dados_identificacao['mac'],
                'data_hora': limpar_texto(dados_estado.get('data_hora')),
                'total_geral': limpar_texto(dados_contador.get('total_geral')),
                'total_pb': limpar_texto(dados_contador.get('total_pb')),
                'total_2faces': limpar_texto(dados_contador.get('total_2faces')),
                'total_1face': limpar_texto(dados_contador.get('total_1face'))
            })
        except requests.RequestException as exc:
            resultados.append({
                'nome': nome,
                'setor': setor,
                'supervisor': supervisor,
                'ip': ip,
                'host': host,
                'tipo_conexao': (
                    imp.get('tipo_conexao') or tipo_conexao_padrao(nome)
                ),
                'status': f'Falha de comunicação: {exc}',
                'modelo': '-', 'estado_impressora': '-',
                'tinta_preto': '-', 'caixa_manutencao': '-', 'nivel_papel': '-',
                'firmware': '-', 'mac': normalizar_mac(imp.get('mac')) or '-',
                'nome_dispositivo': '-',
                'numero_serie': limpar_texto(imp.get('numero_serie')),
                'data_hora': '-',
                'total_geral': '-', 'total_pb': '-',
                'total_2faces': '-', 'total_1face': '-'
            })
        finally:
            if progress_callback:
                progress_callback(indice, total_impressoras, nome)

    return resultados


def construir_interface(config, caminho_config):
    root = tk.Tk()
    root.title(NOME_PLATAFORMA)
    root.geometry('1024x700')
    root.minsize(820, 620)
    root.state('zoomed')
    root.configure(bg='#eef3f8')

    dados = {'resultados': None, 'data': None, 'html': None, 'csv': None}
    alertas_por_iid = {}
    pasta_relatorios = PASTA_DADOS / 'relatorios'
    pasta_relatorios.mkdir(parents=True, exist_ok=True)

    area_rolagem = tk.Frame(root, bg='#eef3f8')
    canvas = tk.Canvas(area_rolagem, bg='#eef3f8', borderwidth=0, highlightthickness=0)
    rolagem_vertical = ttk.Scrollbar(
        area_rolagem,
        orient='vertical',
        command=canvas.yview
    )
    canvas.configure(yscrollcommand=rolagem_vertical.set)
    canvas.pack(side='left', fill='both', expand=True)
    rolagem_vertical.pack(side='right', fill='y')

    frame = tk.Frame(canvas, padx=14, pady=10, bg='white')
    frame_id = canvas.create_window((8, 8), window=frame, anchor='nw')

    def atualizar_largura_conteudo(event):
        canvas.itemconfigure(frame_id, width=max(1, event.width - 16))

    def atualizar_area_rolagem(_event=None):
        canvas.configure(scrollregion=canvas.bbox('all'))

    canvas.bind('<Configure>', atualizar_largura_conteudo)
    frame.bind('<Configure>', atualizar_area_rolagem)
    frame.columnconfigure(0, weight=1)

    cabecalho = tk.Frame(frame, bg='white')
    cabecalho.grid(row=0, column=0, sticky='ew')
    cabecalho.columnconfigure(1, weight=1)
    tk.Label(
        cabecalho,
        text='Gestão Impressoras',
        font=('Arial', 16, 'bold'),
        fg='#0f4c81',
        bg='white'
    ).grid(row=0, column=0, sticky='w')

    def abrir_releases():
        if not webbrowser.open(URL_RELEASES, new=2):
            messagebox.showerror(
                'Não foi possível abrir Releases',
                'Verifique a conexão e abra a página de Releases manualmente.',
                parent=root
            )

    tk.Label(
        cabecalho,
        text=texto_versao_aplicativo(),
        font=('Arial', 8),
        fg='#475569',
        bg='white'
    ).grid(row=0, column=1, sticky='e', padx=(8, 6))
    tk.Button(
        cabecalho,
        text='Releases',
        command=abrir_releases,
        bg='#0f4c81',
        fg='white',
        activebackground='#0b3a63',
        activeforeground='white',
        font=('Arial', 8, 'bold'),
        relief='flat',
        padx=8,
        pady=3
    ).grid(row=0, column=2, sticky='e')

    try:
        caminho_mapa_aps = instalar_mapa_aps()
    except OSError:
        caminho_mapa_aps = None

    def abrir_mapa_aps():
        if caminho_mapa_aps is None or not caminho_mapa_aps.is_file():
            messagebox.showwarning(
                'Mapa não disponível',
                'O mapa dos APs não está incluído nesta versão do programa.',
                parent=root
            )
            return
        try:
            abrir_relatorio_navegador(caminho_mapa_aps)
        except RuntimeError as exc:
            messagebox.showerror('Não foi possível abrir o mapa', str(exc), parent=root)

    tk.Label(
        frame,
        text=(
            'Consulta dos totalizadores, tinta e situação das impressoras. '
            'A consulta inicia ao abrir esta tela e o relatório abre no navegador ao terminar.'
        ),
        font=('Arial', 9),
        fg='#475569',
        bg='white',
        wraplength=690,
        justify='left'
    ).grid(row=1, column=0, sticky='w', pady=(3, 8))

    tk.Label(
        frame,
        text='E-mails do fornecedor (separe com ponto e vírgula)',
        font=('Arial', 9, 'bold'),
        bg='white'
    ).grid(
        row=2, column=0, sticky='w', pady=(0, 3)
    )
    email_var = tk.StringVar(value=config['email_padrao'])
    tk.Entry(frame, textvariable=email_var, font=('Arial', 10)).grid(
        row=3, column=0, sticky='ew', pady=(0, 7), ipady=2
    )

    tk.Label(
        frame,
        text='WhatsApp do fornecedor (separe os números com ponto e vírgula)',
        font=('Arial', 9, 'bold'),
        bg='white'
    ).grid(
        row=4, column=0, sticky='w', pady=(0, 3)
    )
    whatsapp_var = tk.StringVar(value=config['whatsapp_padrao'])
    tk.Entry(frame, textvariable=whatsapp_var, font=('Arial', 10)).grid(
        row=5, column=0, sticky='ew', pady=(0, 7), ipady=2
    )

    status_var = tk.StringVar(value='Verificando a conexão com a rede corporativa...')
    status_label = tk.Label(
        frame,
        textvariable=status_var,
        font=('Arial', 9, 'bold'),
        fg='#0f4c81',
        bg='white',
        wraplength=690,
        justify='left'
    )
    status_label.grid(row=6, column=0, sticky='w', pady=(0, 5))

    falhas_frame = tk.LabelFrame(
        frame,
        text='Alertas imediatos — comunicação e tinta',
        font=('Arial', 9, 'bold'),
        fg='#991b1b',
        bg='white',
        padx=5,
        pady=3
    )
    falhas_frame.grid(row=7, column=0, sticky='ew', pady=(0, 6))
    falhas_frame.columnconfigure(0, weight=1)
    colunas_alertas = (
        'tipo', 'supervisor', 'setor', 'nome', 'ip', 'host',
        'numero_serie', 'modelo', 'mac'
    )
    COLUNA_IP_PAINEL = f"#{colunas_alertas.index('ip') + 1}"
    falhas_lista = ttk.Treeview(
        falhas_frame,
        columns=colunas_alertas,
        show='headings',
        selectmode='browse',
        height=8,
        style='Alertas.Treeview',
    )
    falhas_lista.grid(row=0, column=0, sticky='ew')
    falhas_scroll = ttk.Scrollbar(falhas_frame, orient='vertical', command=falhas_lista.yview)
    falhas_scroll.grid(row=0, column=1, sticky='ns')
    falhas_horizontal = ttk.Scrollbar(
        falhas_frame,
        orient='horizontal',
        command=falhas_lista.xview
    )
    falhas_horizontal.grid(row=1, column=0, sticky='ew')
    falhas_lista.configure(
        yscrollcommand=falhas_scroll.set,
        xscrollcommand=falhas_horizontal.set
    )
    for coluna, titulo, largura in (
        ('tipo', 'Alerta', 145),
        ('supervisor', 'Supervisor', 120),
        ('setor', 'Setor físico', 140),
        ('nome', 'Impressora', 150),
        ('ip', 'IP (clique para abrir)', 190),
        ('host', 'Hostname', 160),
        ('numero_serie', 'Número de série', 140),
        ('modelo', 'Modelo', 170),
        ('mac', 'MAC', 140)
    ):
        falhas_lista.heading(coluna, text=titulo)
        falhas_lista.column(coluna, width=largura, anchor='w', stretch=False)

    falhas_lista.tag_configure(
        'sem-comunicacao',
        background='#fef2f2',
        foreground='#991b1b'
    )
    falhas_lista.tag_configure(
        'tinta-vazia',
        background='#fef2f2',
        foreground='#991b1b'
    )
    falhas_lista.tag_configure(
        'tinta-baixa',
        background='#fff7ed',
        foreground='#9a3412'
    )
    falhas_lista.insert(
        '',
        tk.END,
        values=('Aguardando a primeira consulta.', '', '', '', '', '', '', '')
    )

    def abrir_ip_da_linha(event):
        if (
            falhas_lista.identify_region(event.x, event.y) != 'cell'
            or falhas_lista.identify_column(event.x) != COLUNA_IP_PAINEL
        ):
            return
        iid = falhas_lista.identify_row(event.y)
        alerta = alertas_por_iid.get(iid)
        if not alerta:
            return
        try:
            abrir_gestao_impressora(alerta['ip'])
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror(
                'Não foi possível abrir a gestão',
                str(exc),
                parent=root
            )

    def atualizar_cursor_ip(event):
        sobre_ip = (
            falhas_lista.identify_region(event.x, event.y) == 'cell'
            and falhas_lista.identify_column(event.x) == COLUNA_IP_PAINEL
            and bool(falhas_lista.identify_row(event.y))
        )
        falhas_lista.configure(cursor='hand2' if sobre_ip else '')

    falhas_lista.bind('<Button-1>', abrir_ip_da_linha, add='+')
    falhas_lista.bind('<Motion>', atualizar_cursor_ip, add='+')
    falhas_lista.bind('<Leave>', lambda _event: falhas_lista.configure(cursor=''), add='+')

    def rolar_painel_com_mouse(event):
        if event.widget is falhas_lista:
            return

        widget = event.widget
        dentro_do_painel = False
        while widget is not None:
            if widget is frame or widget is canvas:
                dentro_do_painel = True
                break
            widget = getattr(widget, 'master', None)
        if not dentro_do_painel or not event.delta:
            return

        unidades = max(1, abs(event.delta) // 120)
        if event.widget is falhas_scroll:
            falhas_lista.yview_scroll(-unidades if event.delta > 0 else unidades, 'units')
        else:
            canvas.yview_scroll(-unidades if event.delta > 0 else unidades, 'units')
        return 'break'

    root.bind_all('<MouseWheel>', rolar_painel_com_mouse, add='+')

    estilo = ttk.Style(root)
    estilo.configure('Alertas.Treeview', font=('Arial', 8), rowheight=18)
    estilo.configure('Alertas.Treeview.Heading', font=('Arial', 8, 'bold'))
    progresso_frame = tk.Frame(frame, bg='#f1f5f9', padx=8, pady=5)
    progresso_frame.grid(row=8, column=0, sticky='ew', pady=(0, 7))
    progresso_frame.columnconfigure(0, weight=1)
    tk.Label(
        progresso_frame,
        text='Progresso da consulta',
        font=('Arial', 8, 'bold'),
        fg='#334155',
        bg='#f1f5f9'
    ).grid(row=0, column=0, sticky='w', pady=(0, 3))
    progresso_var = tk.DoubleVar(value=0)
    progresso_percentual_var = tk.StringVar(value='0%')
    tk.Label(
        progresso_frame,
        textvariable=progresso_percentual_var,
        font=('Arial', 8, 'bold'),
        fg='#0f4c81',
        bg='#f1f5f9'
    ).grid(row=0, column=1, sticky='e', pady=(0, 3))
    estilo.configure(
        'Consulta.Horizontal.TProgressbar',
        troughcolor='#dbe4ee',
        background='#2563eb',
        thickness=10
    )
    progresso = ttk.Progressbar(
        progresso_frame,
        mode='determinate',
        maximum=100,
        variable=progresso_var,
        style='Consulta.Horizontal.TProgressbar'
    )
    progresso.grid(row=1, column=0, columnspan=2, sticky='ew')

    botoes = tk.Frame(frame, bg='white')
    botoes.grid(row=9, column=0, sticky='ew')
    for coluna in range(3):
        botoes.columnconfigure(coluna, weight=1)
    atualizar_frame = tk.Frame(
        botoes,
        bg='#eff6ff',
        padx=6,
        pady=5,
        highlightbackground='#93c5fd',
        highlightthickness=1
    )
    atualizar_frame.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 6))
    tk.Label(
        atualizar_frame,
        text='Buscar os dados das impressoras novamente',
        font=('Arial', 9, 'bold'),
        fg='#1e3a8a',
        bg='#eff6ff'
    ).pack(anchor='w', pady=(0, 3))
    botao_atualizar = tk.Button(
        atualizar_frame,
        text='ATUALIZAR CONSULTA',
        command=lambda: iniciar_consulta(),
        bg='#0f4c81',
        fg='white',
        activebackground='#0b3a63',
        activeforeground='white',
        font=('Arial', 10, 'bold'),
        relief='flat',
        padx=10,
        pady=6
    )
    botao_atualizar.pack(fill='x')
    ttk.Separator(botoes, orient='horizontal').grid(
        row=1, column=0, columnspan=3, sticky='ew', pady=(0, 5)
    )
    botoes_secundarios = tk.Frame(botoes, bg='white')
    botoes_secundarios.grid(row=2, column=0, columnspan=3, sticky='ew')
    for coluna in range(3):
        botoes_secundarios.columnconfigure(coluna, weight=1)

    def persistir_contatos():
        config['email_padrao'] = email_var.get().strip()
        config['whatsapp_padrao'] = whatsapp_var.get().strip()
        salvar_config(config, caminho_config)

    def abrir_relatorio():
        if dados['html'] is None:
            messagebox.showinfo('Aguarde', 'O relatório ainda está sendo gerado.')
            return
        try:
            abrir_relatorio_navegador(dados['html'])
        except (OSError, RuntimeError) as exc:
            messagebox.showerror('Falha ao abrir relatório', str(exc))

    def abrir_pasta_relatorios():
        try:
            os.startfile(str(pasta_relatorios))
        except OSError as exc:
            messagebox.showerror('Falha ao abrir pasta', str(exc))

    def abrir_configuracao():
        try:
            os.startfile(str(caminho_config))
        except OSError as exc:
            messagebox.showerror('Falha ao abrir configuração', str(exc))

    def abrir_configuracao_impressoras():
        if consultando['ativo']:
            messagebox.showinfo(
                'Consulta em andamento',
                'Aguarde a consulta terminar para alterar a lista de impressoras.'
            )
            return

        janela = tk.Toplevel(root)
        janela.title('Lista de impressoras da unidade')
        janela.geometry('1300x460')
        janela.minsize(1180, 400)
        janela.transient(root)
        janela.columnconfigure(0, weight=1)
        janela.rowconfigure(0, weight=1)

        lista_editada = [dict(item) for item in config['impressoras']]
        colunas = (
            'setor', 'supervisor', 'host', 'ip', 'numero_serie',
            'tipo_conexao', 'total_geral_manual', 'tinta_preto_manual'
        )
        tabela = ttk.Treeview(
            janela, columns=colunas, show='tree headings', selectmode='browse'
        )
        tabela.heading('#0', text='Estado da impressora', anchor='w')
        tabela.column('#0', width=170, minwidth=150, anchor='w', stretch=False)

        def criar_bolinha(cor):
            imagem = tk.PhotoImage(master=janela, width=14, height=14)
            for y in range(14):
                for x in range(14):
                    distancia = (x - 6.5) ** 2 + (y - 6.5) ** 2
                    if distancia <= 30:
                        imagem.put(cor, (x, y))
                    elif distancia <= 46:
                        imagem.put('#ffffff', (x, y))
            return imagem

        bolinhas = {
            situacao: criar_bolinha(cor) for situacao, cor in CORES_SITUACAO.items()
        }
        bolinhas['-'] = criar_bolinha('#94a3b8')
        rotulos_situacao = {
            'ONLINE': 'ONLINE', 'OFF-LINE': 'OFF-LINE',
            'USB': 'USB (local)', '-': 'Não consultada'
        }
        janela.bolinhas = bolinhas
        for coluna, titulo, largura in (
            ('setor', 'Setor físico', 150),
            ('supervisor', 'Supervisor', 120),
            ('host', 'Hostname', 170),
            ('ip', 'IP', 130),
            ('numero_serie', 'Número de série', 170),
            ('tipo_conexao', 'Tipo Conexão', 110),
            ('total_geral_manual', 'Número de páginas', 130),
            ('tinta_preto_manual', 'Tinta preta', 110)
        ):
            tabela.heading(coluna, text=titulo)
            tabela.column(coluna, width=largura, anchor='w')
        tabela.grid(row=0, column=0, columnspan=4, sticky='nsew', padx=(12, 0), pady=12)
        tabela_scroll = ttk.Scrollbar(janela, orient='vertical', command=tabela.yview)
        tabela_scroll.grid(row=0, column=4, sticky='ns', padx=(0, 12), pady=12)
        tabela.configure(yscrollcommand=tabela_scroll.set)

        def atualizar_tabela():
            itens_atuais = tabela.get_children()
            if itens_atuais:
                tabela.delete(*itens_atuais)
            for indice, item in enumerate(lista_editada):
                total_geral, tinta_preto = valores_contadores_cadastrados(item)
                situacao = situacao_cadastrada(item)
                tabela.insert(
                    '',
                    tk.END,
                    iid=str(indice),
                    text=f" {rotulos_situacao[situacao]}",
                    image=bolinhas[situacao],
                    values=(
                        item['setor'],
                        item.get('supervisor') or '-',
                        item['host'],
                        item['ip'],
                        item.get('numero_serie') or '-',
                        item['tipo_conexao'],
                        total_geral,
                        tinta_preto
                    )
                )

        def editar_impressora(indice=None):
            registro = lista_editada[indice] if indice is not None else {
                'nome': '', 'setor': '', 'supervisor': '', 'host': '', 'ip': '',
                'numero_serie': '', 'tipo_conexao': 'CABO',
                'mac': '', 'total_geral_manual': '', 'tinta_preto_manual': '',
                'total_geral_consultado': '-', 'tinta_preto_consultada': '-',
                'situacao_consultada': '-'
            }
            formulario = tk.Toplevel(janela)
            formulario.title('Editar impressora' if indice is not None else 'Adicionar impressora')
            formulario.geometry('500x525')
            formulario.resizable(False, False)
            formulario.transient(janela)
            formulario.grab_set()

            campos = (
                ('Identificação', 'nome'),
                ('Setor físico', 'setor'),
                ('Supervisor', 'supervisor'),
                ('Hostname', 'host'),
                ('IP IPv4', 'ip'),
                ('Número de Série', 'numero_serie')
            )
            variaveis = {}
            entradas = {}
            setores_opcoes, supervisores_opcoes = setores_e_supervisores(
                lista_editada + config.get('coletores', [])
            )
            for linha, (rotulo, chave) in enumerate(campos):
                tk.Label(formulario, text=rotulo, font=('Arial', 10, 'bold')).grid(
                    row=linha, column=0, sticky='w', padx=16, pady=(12 if linha == 0 else 6, 3)
                )
                variavel = tk.StringVar(value=registro.get(chave, ''))
                variaveis[chave] = variavel
                if chave in ('setor', 'supervisor'):
                    entrada = ttk.Combobox(
                        formulario, textvariable=variavel, width=37,
                        values=setores_opcoes if chave == 'setor' else supervisores_opcoes
                    )
                else:
                    entrada = tk.Entry(formulario, textvariable=variavel, font=('Arial', 10), width=40)
                entrada.grid(
                    row=linha, column=1, sticky='ew', padx=(8, 16), pady=(12 if linha == 0 else 6, 3)
                )
                entradas[chave] = entrada
            formulario.columnconfigure(1, weight=1)
            ligar_setor_ao_supervisor(
                variaveis['setor'], variaveis['supervisor'],
                lambda: lista_editada + config.get('coletores', [])
            )
            variaveis['tipo_conexao'] = tk.StringVar(
                value=registro.get('tipo_conexao')
                or tipo_conexao_padrao(registro.get('nome', ''))
            )
            linha_conexao = len(campos)
            tk.Label(
                formulario,
                text='Tipo Conexão:',
                font=('Arial', 10, 'bold')
            ).grid(row=linha_conexao, column=0, sticky='w', padx=16, pady=6)
            combo_tipo_conexao = ttk.Combobox(
                formulario,
                textvariable=variaveis['tipo_conexao'],
                values=TIPOS_CONEXAO,
                state='readonly',
                width=37
            )
            combo_tipo_conexao.grid(
                row=linha_conexao,
                column=1,
                sticky='ew',
                padx=(8, 16),
                pady=6
            )
            linha_paginas = linha_conexao + 1
            for linha, (rotulo, chave) in enumerate((
                ('Número total de páginas (USB - manual)', 'total_geral_manual'),
                ('Nível de tinta preta % (USB - manual)', 'tinta_preto_manual')
            ), start=linha_paginas):
                tk.Label(
                    formulario, text=rotulo, font=('Arial', 10, 'bold')
                ).grid(row=linha, column=0, sticky='w', padx=16, pady=6)
                variavel = tk.StringVar(value=registro.get(chave, ''))
                variaveis[chave] = variavel
                entrada = tk.Entry(
                    formulario, textvariable=variavel, font=('Arial', 10), width=40
                )
                entrada.grid(
                    row=linha, column=1, sticky='ew', padx=(8, 16), pady=6
                )
                entradas[chave] = entrada

            linha_ajuda = linha_paginas + 2
            tk.Label(
                formulario,
                text='Para USB, preencha os dados manualmente. Em CABO/WIFI, a consulta usa os valores encontrados no equipamento.',
                font=('Arial', 8),
                fg='#475569',
                wraplength=455,
                justify='left'
            ).grid(
                row=linha_ajuda, column=0, columnspan=2, sticky='w',
                padx=16, pady=(2, 8)
            )

            def atualizar_campos_usb(_event=None):
                estado = (
                    'normal' if variaveis['tipo_conexao'].get() == 'USB'
                    else 'disabled'
                )
                for chave in ('total_geral_manual', 'tinta_preto_manual'):
                    entradas[chave].configure(state=estado)

            conexao_escolhida = {
                'manualmente': (
                    registro.get('tipo_conexao')
                    != tipo_conexao_padrao(registro.get('nome', ''))
                )
            }

            def atualizar_tipo_sugerido(_event=None):
                if not conexao_escolhida['manualmente']:
                    variaveis['tipo_conexao'].set(
                        tipo_conexao_padrao(variaveis['nome'].get())
                    )
                    atualizar_campos_usb()

            combo_tipo_conexao.bind(
                '<<ComboboxSelected>>',
                lambda _event: conexao_escolhida.update(manualmente=True),
                add='+'
            )
            combo_tipo_conexao.bind(
                '<<ComboboxSelected>>', atualizar_campos_usb, add='+'
            )
            atualizar_campos_usb()
            entradas['nome'].bind('<KeyRelease>', atualizar_tipo_sugerido, add='+')

            def salvar_impressora():
                nova_impressora = {
                    chave: variavel.get().strip()
                    for chave, variavel in variaveis.items()
                }
                nova_impressora['mac'] = registro.get('mac', '')
                nova_lista = [dict(item) for item in lista_editada]
                if indice is None:
                    nova_lista.append(nova_impressora)
                else:
                    nova_lista[indice] = nova_impressora
                nova_impressora['total_geral_consultado'] = registro.get(
                    'total_geral_consultado', '-'
                )
                nova_impressora['tinta_preto_consultada'] = registro.get(
                    'tinta_preto_consultada', '-'
                )
                nova_impressora['situacao_consultada'] = (
                    registro.get('situacao_consultada', '-')
                    if nova_impressora.get('ip') == registro.get('ip')
                    else '-'
                )
                try:
                    lista_validada = validar_lista_impressoras(nova_lista)
                except ValueError as exc:
                    messagebox.showerror('Dados inválidos', str(exc), parent=formulario)
                    return
                lista_editada[:] = lista_validada
                atualizar_tabela()
                formulario.destroy()

            tk.Button(
                formulario,
                text='Salvar',
                command=salvar_impressora,
                bg='#0f4c81',
                fg='white',
                relief='flat',
                padx=16,
                pady=7
            ).grid(row=linha_ajuda + 1, column=0, columnspan=2, pady=14)

        def adicionar_impressora():
            editar_impressora()

        def alterar_impressora():
            selecao = tabela.selection()
            if not selecao:
                messagebox.showinfo('Selecione uma impressora', 'Selecione uma impressora para editar.', parent=janela)
                return
            editar_impressora(int(selecao[0]))

        def remover_impressora():
            selecao = tabela.selection()
            if not selecao:
                messagebox.showinfo('Selecione uma impressora', 'Selecione uma impressora para remover.', parent=janela)
                return
            del lista_editada[int(selecao[0])]
            atualizar_tabela()

        def salvar_lista():
            try:
                impressoras_validadas = validar_lista_impressoras(lista_editada)
                config_atualizada = {
                    **config,
                    'email_padrao': email_var.get().strip(),
                    'whatsapp_padrao': whatsapp_var.get().strip(),
                    'impressoras': impressoras_validadas
                }
                salvar_config(config_atualizada, caminho_config)
            except (OSError, ValueError) as exc:
                messagebox.showerror('Não foi possível salvar a lista', str(exc), parent=janela)
                return
            config.update(config_atualizada)
            if dados['resultados'] is not None:
                try:
                    dados['html'], dados['csv'] = atualizar_relatorios_salvos(
                        dados['resultados'],
                        dados['data'],
                        dados['html'],
                        dados['csv'],
                        config['limite_tinta'],
                        impressoras_usb=config['impressoras'],
                        mapa_aps=dados_mapa_aps(config)
                    )
                except (OSError, RuntimeError, ValueError) as exc:
                    messagebox.showerror(
                        'Dados salvos; relatórios não atualizados',
                        f'O cadastro foi salvo, mas os relatórios não puderam ser '
                        f'atualizados: {exc}\n\nClique em Salvar lista novamente '
                        'para tentar atualizar os arquivos.',
                        parent=janela
                    )
                    status_var.set(
                        'Os dados USB foram salvos, mas os relatórios precisam ser atualizados.'
                    )
                    return
            janela.destroy()
            if dados['resultados'] is not None:
                status_var.set(
                    f"Lista de {len(config['impressoras'])} impressora(s) salva. "
                    'Relatórios HTML e CSV atualizados com os dados USB. '
                    'Revise antes de enviar ao fornecedor.'
                )
            else:
                status_var.set(
                    f"Lista de {len(config['impressoras'])} impressora(s) salva. "
                    'Clique em Atualizar consulta para buscar os dados.'
                )

        tk.Button(janela, text='Adicionar', command=adicionar_impressora).grid(
            row=1, column=0, sticky='w', padx=12, pady=(0, 12)
        )
        tk.Button(janela, text='Editar', command=alterar_impressora).grid(
            row=1, column=1, sticky='w', padx=4, pady=(0, 12)
        )
        tk.Button(janela, text='Remover', command=remover_impressora).grid(
            row=1, column=2, sticky='w', padx=4, pady=(0, 12)
        )
        tk.Button(
            janela,
            text='Salvar lista',
            command=salvar_lista,
            bg='#0f4c81',
            fg='white',
            relief='flat',
            padx=14
        ).grid(row=1, column=3, sticky='e', padx=(4, 12), pady=(0, 12))
        atualizar_tabela()

    def abrir_coletores():
        janela = tk.Toplevel(root)
        janela.title('Coletores da unidade')
        janela.geometry('1320x480')
        janela.minsize(1100, 400)
        janela.transient(root)
        janela.columnconfigure(0, weight=1)
        janela.rowconfigure(0, weight=1)

        lista_editada = [dict(item) for item in config.get('coletores', [])]
        colunas = tuple(chave for chave, _ in COLUNAS_COLETORES if chave != 'observacao')
        larguras = {
            'situacao_consultada': 100, 'ip_atual': 105, 'visto_online_em': 135,
            'setor': 130, 'supervisor': 110, 'fabricante': 90, 'modelo': 90,
            'numero_serie': 130, 'versao_app': 100, 'versao_anterior': 100,
            'hostname': 120, 'mac': 130, 'usuario': 110, 'piloto': 60,
        }
        tabela = ttk.Treeview(janela, columns=colunas, show='headings', selectmode='browse')
        for chave, rotulo in COLUNAS_COLETORES:
            if chave in colunas:
                tabela.heading(chave, text=rotulo)
                tabela.column(chave, width=larguras[chave], anchor='w')
        tabela.tag_configure('piloto', background='#fef9c3')
        tabela.tag_configure('online', foreground='#15803d')
        tabela.tag_configure('offline', foreground='#b91c1c')
        tabela.grid(row=0, column=0, columnspan=6, sticky='nsew', padx=(12, 0), pady=12)
        rolagem = ttk.Scrollbar(janela, orient='vertical', command=tabela.yview)
        rolagem.grid(row=0, column=6, sticky='ns', padx=(0, 12), pady=12)
        tabela.configure(yscrollcommand=rolagem.set)

        total_var = tk.StringVar()

        def atualizar_tabela():
            itens = tabela.get_children()
            if itens:
                tabela.delete(*itens)
            for indice, item in enumerate(lista_editada):
                tabela.insert(
                    '', tk.END, iid=str(indice),
                    values=[texto_coluna_coletor(item, chave) for chave in colunas],
                    tags=tuple(
                        tag for tag, ativo in (
                            ('piloto', item.get('piloto')),
                            ('online', item.get('situacao_consultada') == 'ONLINE'),
                            ('offline', item.get('situacao_consultada') == 'OFF-LINE'),
                        ) if ativo
                    ),
                )
            total_var.set(
                f"{len(lista_editada)} coletor(es) | "
                f"{sum(bool(c.get('piloto')) for c in lista_editada)} no piloto"
            )

        def editar_coletor(indice=None):
            registro = lista_editada[indice] if indice is not None else {
                chave: '' for chave in CAMPOS_TEXTO_COLETOR
            }
            if indice is None:
                registro['fabricante'] = 'Zebra'
                registro['piloto'] = False
            formulario = tk.Toplevel(janela)
            formulario.title('Editar coletor' if indice is not None else 'Adicionar coletor')
            formulario.geometry('520x560')
            formulario.resizable(False, False)
            formulario.transient(janela)
            formulario.grab_set()
            formulario.columnconfigure(1, weight=1)

            setores_opcoes, supervisores_opcoes = setores_e_supervisores(
                config['impressoras'] + lista_editada
            )
            campos = (
                ('Setor físico', 'setor'),
                ('Supervisor', 'supervisor'),
                ('Fabricante', 'fabricante'),
                ('Modelo', 'modelo'),
                ('Número de série', 'numero_serie'),
                ('Versão do app', 'versao_app'),
                ('Versão anterior (piloto)', 'versao_anterior'),
                ('Hostname', 'hostname'),
                ('MAC Wi-Fi', 'mac'),
                ('Usuário / responsável', 'usuario'),
                ('Observação', 'observacao'),
            )
            variaveis = {}
            for linha, (rotulo, chave) in enumerate(campos):
                tk.Label(formulario, text=rotulo, font=('Arial', 10, 'bold')).grid(
                    row=linha, column=0, sticky='w', padx=16, pady=(12 if linha == 0 else 5, 3)
                )
                variavel = tk.StringVar(value=registro.get(chave, ''))
                variaveis[chave] = variavel
                if chave in ('setor', 'supervisor'):
                    campo = ttk.Combobox(
                        formulario, textvariable=variavel, width=37,
                        values=setores_opcoes if chave == 'setor' else supervisores_opcoes
                    )
                elif chave == 'fabricante':
                    campo = ttk.Combobox(
                        formulario, textvariable=variavel, values=FABRICANTES_COLETOR,
                        state='readonly', width=37
                    )
                else:
                    campo = tk.Entry(formulario, textvariable=variavel, font=('Arial', 10), width=40)
                campo.grid(
                    row=linha, column=1, sticky='ew', padx=(8, 16),
                    pady=(12 if linha == 0 else 5, 3)
                )

            ligar_setor_ao_supervisor(
                variaveis['setor'], variaveis['supervisor'],
                lambda: config['impressoras'] + lista_editada
            )

            piloto_var = tk.BooleanVar(value=bool(registro.get('piloto')))
            tk.Checkbutton(
                formulario, text='Coletor do piloto da versão nova do app',
                variable=piloto_var, font=('Arial', 10)
            ).grid(row=len(campos), column=0, columnspan=2, sticky='w', padx=16, pady=(8, 2))

            def salvar_coletor():
                novo = {chave: variavel.get().strip() for chave, variavel in variaveis.items()}
                novo['piloto'] = piloto_var.get()
                if normalizar_mac(novo['mac']) == normalizar_mac(registro.get('mac')):
                    for chave in CAMPOS_STATUS_COLETOR:
                        novo[chave] = registro.get(chave, '')
                nova_lista = [dict(item) for item in lista_editada]
                if indice is None:
                    nova_lista.append(novo)
                else:
                    nova_lista[indice] = novo
                try:
                    lista_validada = validar_lista_coletores(nova_lista)
                except ValueError as exc:
                    messagebox.showerror('Dados inválidos', str(exc), parent=formulario)
                    return
                lista_editada[:] = lista_validada
                atualizar_tabela()
                formulario.destroy()

            tk.Button(
                formulario, text='Salvar', command=salvar_coletor,
                bg='#0f4c81', fg='white', relief='flat', padx=16, pady=7
            ).grid(row=len(campos) + 1, column=0, columnspan=2, pady=14)

        def selecionado(acao):
            selecao = tabela.selection()
            if not selecao:
                messagebox.showinfo(
                    'Selecione um coletor', f'Selecione um coletor para {acao}.', parent=janela
                )
                return None
            return int(selecao[0])

        def alterar_coletor():
            indice = selecionado('editar')
            if indice is not None:
                editar_coletor(indice)

        def remover_coletor():
            indice = selecionado('remover')
            if indice is None:
                return
            item = lista_editada[indice]
            if messagebox.askyesno(
                'Remover coletor',
                f"Remover o coletor {item.get('numero_serie')} ({item.get('setor')})?",
                parent=janela
            ):
                del lista_editada[indice]
                atualizar_tabela()

        def salvar_lista(fechar=True):
            try:
                coletores_validados = validar_lista_coletores(lista_editada)
                config_atualizada = {**config, 'coletores': coletores_validados}
                salvar_config(config_atualizada, caminho_config)
            except (OSError, ValueError) as exc:
                messagebox.showerror('Não foi possível salvar os coletores', str(exc), parent=janela)
                return False
            config.update(config_atualizada)
            status_var.set(f"Lista de {len(coletores_validados)} coletor(es) salva.")
            atualizar_resumo_coletores()
            if fechar:
                janela.destroy()
            return True

        def gerar_relatorio():
            if salvar_lista(fechar=False):
                gerar_e_abrir_relatorio_coletores(janela)

        tk.Button(janela, text='Adicionar', command=editar_coletor).grid(
            row=1, column=0, sticky='w', padx=12, pady=(0, 12)
        )
        tk.Button(janela, text='Editar', command=alterar_coletor).grid(
            row=1, column=1, sticky='w', padx=4, pady=(0, 12)
        )
        tk.Button(janela, text='Remover', command=remover_coletor).grid(
            row=1, column=2, sticky='w', padx=4, pady=(0, 12)
        )
        tk.Label(janela, textvariable=total_var, fg='#475569').grid(
            row=1, column=3, sticky='w', padx=12, pady=(0, 12)
        )
        tk.Button(
            janela, text='Gerar relatório', command=gerar_relatorio,
            bg='#0891b2', fg='white', relief='flat', padx=14
        ).grid(row=1, column=4, sticky='e', padx=4, pady=(0, 12))
        tk.Button(
            janela, text='Salvar lista', command=salvar_lista,
            bg='#0f4c81', fg='white', relief='flat', padx=14
        ).grid(row=1, column=5, sticky='e', padx=(4, 12), pady=(0, 12))
        tabela.bind('<Double-1>', lambda _event: alterar_coletor())
        atualizar_tabela()

    def avisar_dados_usb_pendentes():
        pendentes = impressoras_usb_pendentes(config['impressoras'])
        if not pendentes:
            return False
        detalhes = '\n'.join(
            f"• {item['nome']}: {', '.join(item['campos'])}"
            for item in pendentes
        )
        messagebox.showwarning(
            'Complete os dados das impressoras USB',
            'Antes de preparar o envio ao fornecedor, informe os valores reais '
            'de páginas e tinta das impressoras USB.\n\n'
            f'{detalhes}\n\n'
            'Use Gerenciar impressoras > selecione a impressora > Editar e '
            'depois clique em Salvar lista.'
        )
        status_var.set(
            'Preencha páginas e tinta das impressoras USB antes de preparar o envio.'
        )
        return True

    def abrir_rascunho_email():
        if dados['resultados'] is None:
            messagebox.showinfo('Aguarde', 'A consulta das impressoras ainda está em andamento.')
            return
        if avisar_dados_usb_pendentes():
            return
        try:
            persistir_contatos()
            body = montar_email_body(
                dados['resultados'],
                dados['data'],
                dados['html'],
                dados['csv'],
                config['limite_tinta'],
                impressoras_usb=config['impressoras']
            )
            caminho_eml = abrir_email(email_var.get().strip(), body)
            messagebox.showinfo(
                'Rascunho aberto',
                f'O arquivo .eml foi salvo em {caminho_eml}. Revise o destinatário e anexe os arquivos HTML e CSV antes de enviar.'
            )
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror('Não foi possível abrir o e-mail', str(exc))

    def abrir_conversa_whatsapp():
        if dados['resultados'] is None:
            messagebox.showinfo('Aguarde', 'A consulta das impressoras ainda está em andamento.')
            return
        if avisar_dados_usb_pendentes():
            return
        try:
            persistir_contatos()
            abrir_whatsapp(
                whatsapp_var.get().strip(),
                montar_whatsapp_body(
                    dados['resultados'],
                    dados['data'],
                    impressoras_usb=config['impressoras']
                )
            )
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror('Não foi possível abrir o WhatsApp', str(exc))

    consultando = {'ativo': False}
    botoes_config = [
        ('Gerenciar impressoras', abrir_configuracao_impressoras, '#475569'),
        ('Abrir relatório', abrir_relatorio, '#0f4c81'),
        ('Rascunho de e-mail', abrir_rascunho_email, '#1d4ed8'),
        ('Enviar WhatsApp', abrir_conversa_whatsapp, '#16a34a'),
        ('Pasta dos relatórios', abrir_pasta_relatorios, '#475569'),
        ('Abrir configurações', abrir_configuracao, '#475569'),
    ]
    for indice, (rotulo, acao, cor) in enumerate(botoes_config):
        botao = tk.Button(
            botoes_secundarios,
            text=rotulo,
            command=acao,
            bg=cor,
            fg='white',
            activebackground=cor,
            activeforeground='white',
            font=('Arial', 9, 'bold'),
            relief='flat',
            padx=6,
            pady=5
        )
        botao.grid(row=indice // 3, column=indice % 3, padx=3, pady=3, sticky='ew')

    tk.Label(
        frame,
        text=f'Configuração: {caminho_config} | Contatos são salvos para a próxima execução; envio de e-mail e anexos são manuais.',
        font=('Arial', 8),
        fg='#64748b',
        bg='white',
        wraplength=690,
        justify='left'
    ).grid(row=10, column=0, sticky='w', pady=(7, 0))

    def consulta_sem_impressoras_rede():
        consultando['ativo'] = False
        botao_atualizar.config(state='normal')
        atualizar_progresso(
            100,
            'Consulta concluída: nenhuma impressora de rede cadastrada.'
        )
        status_var.set(
            'As impressoras USB permanecem no cadastro, mas não entram na busca de rede.'
        )

    def consulta_em_segundo_plano():
        try:
            dispositivos_rede = filtrar_impressoras_de_rede(config['impressoras'])
            if not dispositivos_rede:
                root.after(0, consulta_sem_impressoras_rede)
                return

            ips_locais, dentro_da_faixa = verificar_rede_corporativa(
                config['faixa_rede_corporativa'],
                dispositivos_rede
            )
            if not dentro_da_faixa:
                root.after(
                    0,
                    lambda enderecos=ips_locais: rede_fora_da_faixa(enderecos)
                )
                return

            root.after(0, lambda: atualizar_progresso(
                5, 'Rede corporativa detectada. Consultando as impressoras...'
            ))
            data_consulta = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            resultados = consultar_impressoras(
                progress_callback=atualizar_progresso_impressora,
                lista_impressoras=dispositivos_rede
            )
            root.after(0, lambda: atualizar_progresso(82, 'Montando o relatório...'))
            html_relatorio = gerar_html(
                resultados,
                data_consulta,
                config['limite_tinta'],
                impressoras_usb=config['impressoras'],
                mapa_aps=dados_mapa_aps(config)
            )
            root.after(0, lambda: atualizar_progresso(90, 'Salvando o relatório HTML...'))
            marca_tempo = datetime.now().strftime('%Y%m%d_%H%M%S')
            caminho_html = salvar_relatorio(
                html_relatorio,
                pasta_relatorios / NOME_ARQUIVO_RELATORIO_HTML
            )
            root.after(0, lambda: atualizar_progresso(95, 'Salvando o relatório CSV...'))
            caminho_csv = salvar_csv(
                resultados,
                pasta_relatorios / f'relatorio_impressoras_{marca_tempo}.csv',
                impressoras_usb=config['impressoras']
            )
            root.after(0, lambda: atualizar_progresso(100, 'Consulta concluída.'))
            root.after(0, lambda: consulta_concluida(resultados, data_consulta, caminho_html, caminho_csv))
        except (OSError, requests.RequestException, ValueError, RuntimeError) as exc:
            root.after(0, lambda erro=str(exc): consulta_falhou(erro))

    def atualizar_progresso(percentual, mensagem=None):
        progresso_var.set(percentual)
        progresso_percentual_var.set(f'{int(percentual)}%')
        if mensagem:
            status_var.set(mensagem)

    def atualizar_progresso_impressora(indice, total, nome):
        percentual = 5 + int(75 * indice / total)
        root.after(
            0,
            lambda valor=percentual, atual=indice, quantidade=total, dispositivo=nome:
                atualizar_progresso(
                    valor,
                    f'Consultando impressoras ({atual}/{quantidade}): {dispositivo}'
                )
        )

    def consulta_concluida(resultados, data_consulta, caminho_html, caminho_csv):
        consultando['ativo'] = False
        botao_atualizar.config(state='normal')
        cadastro_alterado = atualizar_seriais_cadastrados(config, resultados)
        cadastro_alterado = (
            atualizar_leituras_cadastradas(config, resultados)
            or cadastro_alterado
        )
        if cadastro_alterado:
            try:
                salvar_config(config, caminho_config)
            except OSError as exc:
                messagebox.showwarning(
                    'Dados de impressora detectados',
                    f'Os dados da consulta foram atualizados, mas não foi possível '
                    f'salvar o cadastro: {exc}',
                    parent=root
                )
        dados.update({
            'resultados': resultados,
            'data': data_consulta,
            'html': caminho_html,
            'csv': caminho_csv
        })
        itens_alertas = falhas_lista.get_children()
        if itens_alertas:
            falhas_lista.delete(*itens_alertas)
        alertas = gerar_alertas(resultados, config['limite_tinta'])
        alertas_imediatos = [
            alerta for alerta in alertas
            if alerta['tipo'] in ('Sem comunicação', 'Tinta vazia', 'Tinta baixa')
        ]
        alertas_por_iid.clear()
        if alertas_imediatos:
            estilos_alerta = {
                'Sem comunicação': 'sem-comunicacao',
                'Tinta vazia': 'tinta-vazia',
                'Tinta baixa': 'tinta-baixa'
            }
            for indice, alerta in enumerate(alertas_imediatos):
                iid = f'alerta-{indice}'
                falhas_lista.insert(
                    '',
                    tk.END,
                    iid=iid,
                    values=valores_linha_alerta_painel(alerta),
                    tags=(estilos_alerta[alerta['tipo']],)
                )
                alertas_por_iid[iid] = alerta
        else:
            falhas_lista.insert(
                '',
                tk.END,
                values=('Nenhuma falha ou alerta de tinta.', '', '', '', '', '', '', '')
            )
        falhas = sum(not item.get('status', '').startswith('Sucesso') for item in resultados)
        status_var.set(
            f'Consulta concluída: {len(resultados) - falhas}/{len(resultados)} equipamentos consultados. '
            f'{len(alertas)} alerta(s). Arquivos HTML e CSV salvos em {pasta_relatorios}.'
        )
        try:
            abrir_relatorio_navegador(caminho_html)
        except (OSError, RuntimeError) as exc:
            messagebox.showwarning('Relatório gerado', f'O arquivo foi salvo, mas o navegador não abriu: {exc}')

    def consulta_falhou(mensagem):
        consultando['ativo'] = False
        botao_atualizar.config(state='normal')
        status_var.set('Não foi possível concluir a consulta ou gerar os relatórios.')
        messagebox.showerror('Falha na consulta', mensagem)

    def rede_fora_da_faixa(ips_locais):
        consultando['ativo'] = False
        botao_atualizar.config(state='normal')
        atualizar_progresso(0)
        ip_detectado = ', '.join(ips_locais) if ips_locais else 'Não foi possível identificar'
        faixa = config['faixa_rede_corporativa']
        status_var.set(f'Fora da faixa de rede configurada ({faixa}). Consulta não iniciada.')
        messagebox.showwarning(
            'Rede corporativa não detectada',
            f'IP(s) detectado(s) para acessar as impressoras: {ip_detectado}\n\n'
            f'Faixa configurada: {faixa}\n\n'
            'A consulta foi interrompida. Conecte-se à rede corporativa ou à VPN autorizada. '
            'Se a faixa do computador corporativo for diferente, atualize '
            '"faixa_rede_corporativa" no arquivo de configurações.'
        )

    def iniciar_consulta():
        if consultando['ativo']:
            return
        consultando['ativo'] = True
        botao_atualizar.config(state='disabled')
        atualizar_progresso(0, 'Verificando a conexão com a rede corporativa...')
        threading.Thread(target=consulta_em_segundo_plano, daemon=True).start()

    # ------------------------------------------------------------------
    # Navegação: tela inicial, Gestão Impressoras e Gestão Coletores
    # ------------------------------------------------------------------
    COR_FUNDO = '#eef3f8'
    telas = {}
    consulta_iniciada = {'feita': False}

    def mostrar_tela(nome):
        for tela in (tela_inicial, area_rolagem, tela_coletores):
            tela.pack_forget()
        telas[nome].pack(fill='both', expand=True)
        titulos = {
            'inicio': NOME_PLATAFORMA,
            'impressoras': f'{NOME_PLATAFORMA} — Gestão Impressoras',
            'coletores': f'{NOME_PLATAFORMA} — Gestão Coletores',
        }
        root.title(titulos[nome])

    def mostrar_inicio():
        mostrar_tela('inicio')

    def mostrar_impressoras():
        mostrar_tela('impressoras')
        if not consulta_iniciada['feita']:
            consulta_iniciada['feita'] = True
            iniciar_consulta()

    def mostrar_coletores():
        conferir_rede_coletores()
        atualizar_resumo_coletores()
        mostrar_tela('coletores')

    def mostrar_sobre():
        messagebox.showinfo(
            'Sobre',
            f'{NOME_PLATAFORMA}\n\n'
            f'Versão {APP_VERSION}\n'
            f'{texto_versao_aplicativo()}\n\n'
            'Módulos: Gestão Impressoras, Gestão APs e Gestão Coletores.',
            parent=root
        )

    rede_coletores = {'conectado': False, 'mensagem': ''}

    def conferir_rede_coletores():
        try:
            conectado, mensagem = situacao_rede_coletores(config)
        except ValueError as exc:
            conectado, mensagem = False, str(exc)
        rede_coletores.update(conectado=conectado, mensagem=mensagem)
        return conectado, mensagem

    def gerar_e_abrir_relatorio_coletores(parent):
        try:
            pasta_relatorios.mkdir(parents=True, exist_ok=True)
            agora = datetime.now()
            aviso = '' if rede_coletores['conectado'] else aviso_rede_coletores(config)
            caminho_html = salvar_relatorio(
                gerar_html_coletores(
                    config['coletores'], agora.strftime('%d/%m/%Y %H:%M:%S'), aviso
                ),
                pasta_relatorios / NOME_ARQUIVO_RELATORIO_COLETORES
            )
            salvar_csv_coletores(
                config['coletores'],
                pasta_relatorios / f"coletores_{agora.strftime('%Y%m%d_%H%M%S')}.csv"
            )
            abrir_relatorio_navegador(caminho_html)
        except (OSError, RuntimeError) as exc:
            messagebox.showerror('Não foi possível gerar o relatório', str(exc), parent=parent)
            return False
        status_var.set(
            f"Relatório de {len(config['coletores'])} coletor(es) gerado em {pasta_relatorios}."
        )
        return True

    def botao_voltar(pai):
        return tk.Button(
            pai, text='← Início', command=mostrar_inicio,
            bg='#e2e8f0', fg='#0f172a', activebackground='#cbd5e1',
            font=('Arial', 9, 'bold'), relief='flat', padx=10, pady=3, cursor='hand2'
        )

    # Botão "Início" na tela de impressoras (ao lado de Releases)
    botao_voltar(cabecalho).grid(row=0, column=3, sticky='e', padx=(6, 0))

    # Menu do sistema
    barra_menu = tk.Menu(root)
    menu_sistema = tk.Menu(barra_menu, tearoff=0)
    menu_sistema.add_command(label='Início', command=mostrar_inicio)
    menu_sistema.add_separator()
    menu_sistema.add_command(label='Sair', command=root.destroy)
    barra_menu.add_cascade(label='Sistema', menu=menu_sistema)
    menu_modulos = tk.Menu(barra_menu, tearoff=0)
    menu_modulos.add_command(label='Gestão Impressoras', command=mostrar_impressoras)
    menu_modulos.add_command(label='Gestão APs', command=abrir_mapa_aps)
    menu_modulos.add_command(label='Gestão Coletores', command=mostrar_coletores)
    barra_menu.add_cascade(label='Módulos', menu=menu_modulos)
    menu_ajuda = tk.Menu(barra_menu, tearoff=0)
    menu_ajuda.add_command(label='Sobre', command=mostrar_sobre)
    menu_ajuda.add_command(label='Releases', command=abrir_releases)
    barra_menu.add_cascade(label='Ajuda', menu=menu_ajuda)
    root.config(menu=barra_menu)

    # Tela inicial
    tela_inicial = tk.Frame(root, bg=COR_FUNDO)
    centro = tk.Frame(tela_inicial, bg=COR_FUNDO)
    centro.place(relx=0.5, rely=0.45, anchor='center')
    faixa_titulo = tk.Frame(centro, bg='#0f4c81', padx=40, pady=22)
    faixa_titulo.pack(fill='x')
    tk.Label(
        faixa_titulo, text=NOME_PLATAFORMA, font=('Arial', 24, 'bold'),
        fg='white', bg='#0f4c81'
    ).pack()
    tk.Label(
        faixa_titulo, text='Escolha o módulo que deseja abrir',
        font=('Arial', 11), fg='#dbeafe', bg='#0f4c81'
    ).pack(pady=(4, 0))

    cartoes = tk.Frame(centro, bg=COR_FUNDO)
    cartoes.pack(pady=24)
    for coluna, (titulo, descricao, cor, cor_ativa, comando) in enumerate((
        ('Gestão Impressoras', 'Contadores, tinta, situação\ne relatórios das impressoras',
         '#0f4c81', '#0b3a63', mostrar_impressoras),
        ('Gestão APs', 'Mapa dos access points\ne racks da unidade',
         '#0891b2', '#0e7490', abrir_mapa_aps),
        ('Gestão Coletores', 'Cadastro e mapa dos\ncoletores Zebra e Honeywell',
         '#7c3aed', '#6d28d9', mostrar_coletores),
    )):
        tk.Button(
            cartoes, text=f'{titulo}\n\n{descricao}', command=comando,
            bg=cor, fg='white', activebackground=cor_ativa, activeforeground='white',
            font=('Arial', 12, 'bold'), relief='flat', width=22, height=6,
            justify='center', cursor='hand2'
        ).grid(row=0, column=coluna, padx=10)

    caixa_sobre = tk.LabelFrame(
        centro, text=' Sobre ', font=('Arial', 10, 'bold'),
        bg='white', fg='#0f4c81', padx=16, pady=10
    )
    caixa_sobre.pack(fill='x')
    caixa_sobre.columnconfigure(0, weight=1)
    tk.Label(
        caixa_sobre, text=texto_versao_aplicativo(), font=('Arial', 10),
        fg='#334155', bg='white'
    ).grid(row=0, column=0, sticky='w')
    tk.Label(
        caixa_sobre,
        text='Desenvolvido para apoio ao TI: impressoras, access points e coletores.',
        font=('Arial', 9), fg='#64748b', bg='white'
    ).grid(row=1, column=0, sticky='w', pady=(2, 0))
    tk.Button(
        caixa_sobre, text='Releases', command=abrir_releases,
        bg='#0f4c81', fg='white', activebackground='#0b3a63', activeforeground='white',
        font=('Arial', 9, 'bold'), relief='flat', padx=12, pady=4, cursor='hand2'
    ).grid(row=0, column=1, rowspan=2, sticky='e')

    # Tela Gestão Coletores
    tela_coletores = tk.Frame(root, bg=COR_FUNDO)
    painel_coletores = tk.Frame(tela_coletores, bg='white', padx=20, pady=16)
    painel_coletores.pack(fill='x', padx=16, pady=16)
    painel_coletores.columnconfigure(0, weight=1)
    tk.Label(
        painel_coletores, text='Gestão Coletores', font=('Arial', 16, 'bold'),
        fg='#7c3aed', bg='white'
    ).grid(row=0, column=0, sticky='w')
    botao_voltar(painel_coletores).grid(row=0, column=1, sticky='e')
    resumo_coletores_var = tk.StringVar()
    tk.Label(
        painel_coletores, textvariable=resumo_coletores_var, font=('Arial', 10),
        fg='#475569', bg='white', justify='left'
    ).grid(row=1, column=0, columnspan=2, sticky='w', pady=(6, 4))
    status_coletores_var = tk.StringVar()
    rotulo_status_coletores = tk.Label(
        painel_coletores, textvariable=status_coletores_var, font=('Arial', 11, 'bold'),
        bg='white', justify='left'
    )
    rotulo_status_coletores.grid(row=2, column=0, columnspan=2, sticky='w', pady=(0, 8))
    aviso_coletores_var = tk.StringVar()
    rotulo_aviso_coletores = tk.Label(
        painel_coletores, textvariable=aviso_coletores_var, font=('Arial', 10, 'bold'),
        justify='left', anchor='w', wraplength=900, padx=12, pady=8
    )
    rotulo_aviso_coletores.grid(row=3, column=0, columnspan=2, sticky='ew', pady=(0, 14))

    def atualizar_resumo_coletores():
        coletores = config.get('coletores', [])
        zebra = sum(c.get('fabricante') == 'Zebra' for c in coletores)
        honeywell = sum(c.get('fabricante') == 'Honeywell' for c in coletores)
        piloto = sum(bool(c.get('piloto')) for c in coletores)
        setores = len({c.get('setor', '').casefold() for c in coletores})
        resumo_coletores_var.set(
            f'{len(coletores)} coletor(es) cadastrado(s) — Zebra: {zebra} | '
            f'Honeywell: {honeywell} | No piloto: {piloto} | Setores: {setores}'
        )
        contagem = resumo_status_coletores(coletores)
        ultima = ultima_verificacao_coletores(coletores)
        status_coletores_var.set(
            f"● Online: {contagem['ONLINE']}    ● Offline: {contagem['OFF-LINE']}    "
            f"Não verificado: {contagem['-']}    Sem MAC: {contagem['SEM MAC']}    "
            + (f'(última verificação: {ultima})' if ultima else '(status ainda não verificado)')
        )
        rotulo_status_coletores.config(
            fg='#15803d' if contagem['ONLINE'] and not contagem['OFF-LINE'] else
            '#b91c1c' if contagem['OFF-LINE'] else '#475569'
        )
        if rede_coletores['conectado']:
            aviso_coletores_var.set('📶 ' + rede_coletores['mensagem'])
            rotulo_aviso_coletores.config(bg='#dcfce7', fg='#166534')
        else:
            aviso_coletores_var.set('📶 ' + (rede_coletores['mensagem'] or aviso_rede_coletores(config)))
            rotulo_aviso_coletores.config(bg='#fff7ed', fg='#9a3412')

    def verificar_status_coletores():
        if not config.get('coletores'):
            messagebox.showinfo('Coletores', 'Nenhum coletor cadastrado.', parent=root)
            return
        botao_verificar.config(state='disabled', text='Verificando...\naguarde')
        status_var.set('Verificando a rede dos coletores...')

        def concluir(erro=None, atualizados=None, encontrados=0):
            botao_verificar.config(state='normal', text=TEXTO_BOTAO_VERIFICAR)
            if erro:
                atualizar_resumo_coletores()
                status_var.set(erro)
                messagebox.showwarning('Rede dos coletores', erro, parent=root)
                return
            try:
                config_atualizada = {**config, 'coletores': validar_lista_coletores(atualizados)}
                salvar_config(config_atualizada, caminho_config)
            except (OSError, ValueError) as exc:
                messagebox.showerror('Não foi possível salvar o status', str(exc), parent=root)
                return
            config.update(config_atualizada)
            atualizar_resumo_coletores()
            contagem = resumo_status_coletores(config['coletores'])
            status_var.set(
                f"Status dos coletores: {contagem['ONLINE']} online, "
                f"{contagem['OFF-LINE']} offline ({encontrados} aparelho(s) na rede)."
            )
            gerar_e_abrir_relatorio_coletores(root)

        def em_segundo_plano():
            try:
                conectado, mensagem = conferir_rede_coletores()
                if not conectado:
                    root.after(0, lambda: concluir(erro=mensagem))
                    return
                macs = macs_na_rede_coletores(config['faixa_rede_coletores'])
                quando = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
                atualizados = aplicar_status_coletores(config['coletores'], macs, quando)
                root.after(0, lambda: concluir(atualizados=atualizados, encontrados=len(macs)))
            except Exception as exc:  # noqa: BLE001 - mostra qualquer falha na tela
                root.after(0, lambda exc=exc: concluir(erro=f'Falha ao verificar: {exc}'))

        threading.Thread(target=em_segundo_plano, daemon=True).start()

    TEXTO_BOTAO_VERIFICAR = 'Verificar status online\nRede Wi-Fi dos coletores'
    botoes_coletores = tk.Frame(painel_coletores, bg='white')
    botoes_coletores.grid(row=4, column=0, columnspan=2, sticky='w')
    for titulo, descricao, cor, cor_ativa, comando in (
        ('Gerenciar coletores', 'Incluir, editar e remover', '#7c3aed', '#6d28d9',
         lambda: abrir_coletores()),
        ('Verificar status online', 'Rede Wi-Fi dos coletores', '#15803d', '#166534',
         verificar_status_coletores),
        ('Ver mapa dos coletores', 'Painel por setor', '#0891b2', '#0e7490',
         lambda: gerar_e_abrir_relatorio_coletores(root)),
    ):
        botao = tk.Button(
            botoes_coletores, text=f'{titulo}\n{descricao}', command=comando,
            bg=cor, fg='white', activebackground=cor_ativa, activeforeground='white',
            disabledforeground='#d1fae5',
            font=('Arial', 11, 'bold'), relief='flat', width=24, height=3,
            cursor='hand2'
        )
        botao.pack(side='left', padx=(0, 12))
        if comando is verificar_status_coletores:
            botao_verificar = botao

    telas.update(inicio=tela_inicial, impressoras=area_rolagem, coletores=tela_coletores)
    mostrar_inicio()
    root.mainloop()


def main():
    try:
        config, caminho_config = carregar_config()
    except (OSError, ValueError) as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror('Erro de configuração', str(exc))
        root.destroy()
        return

    construir_interface(config, caminho_config)


if __name__ == '__main__':
    main()
