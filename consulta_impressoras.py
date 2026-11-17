# -*- coding: utf-8 -*-
import os
import re
import csv
import html
import ipaddress
import json
import socket
import sys
import threading
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
    "impressoras": [dict(impressora) for impressora in impressoras]
}
PASTA_DADOS = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "ConsultaImpressoras"
APP_VERSION = "1.0.4"
APP_DEVELOPER = "Christiano Miranda"
URL_RELEASES = "https://github.com/christianocassio/buscacontadoresimpressoras/releases"
TIPOS_CONEXAO = ("USB", "CABO", "WIFI")


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
    for chave in ("email_padrao", "whatsapp_padrao"):
        if not isinstance(config[chave], str):
            raise ValueError(f"O valor de '{chave}' deve ser texto.")
    config.pop("limite_papel", None)
    config["impressoras"] = validar_lista_impressoras(config["impressoras"])
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
        host = item.get("host")
        ip = item.get("ip")
        numero_serie = item.get("numero_serie", "")
        tipo_conexao = item.get("tipo_conexao")
        if not all(isinstance(valor, str) and valor.strip() for valor in (nome, setor, host, ip)):
            raise ValueError(
                f"Preencha identificação, setor, hostname e IP da impressora {indice}."
            )
        if not isinstance(numero_serie, str):
            raise ValueError(f"O número de série da impressora {indice} deve ser texto.")
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
            "host": host.strip(),
            "ip": ip_normalizado,
            "numero_serie": numero_serie.strip(),
            "tipo_conexao": tipo_conexao
        })

    return impressoras_validadas


def atualizar_seriais_cadastrados(config, resultados):
    seriais_por_ip = {
        limpar_texto(item.get('ip')): limpar_texto(item.get('numero_serie'))
        for item in resultados
        if limpar_texto(item.get('numero_serie')) != '-'
    }
    alterou = False
    for impressora in config['impressoras']:
        numero_serie = seriais_por_ip.get(impressora['ip'])
        if numero_serie and impressora.get('numero_serie', '') != numero_serie:
            impressora['numero_serie'] = numero_serie
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
    ips_locais = obter_ips_de_rota(lista_impressoras)
    dentro_da_faixa = any(
        ipaddress.ip_address(endereco) in faixa
        for endereco in ips_locais
    )
    return ips_locais, dentro_da_faixa


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
    dados = {'nome_dispositivo': '-', 'numero_serie': '-'}

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
            'serial number', 'serial no'
        )):
            chave = 'numero_serie'
        else:
            return

        valor_limpo = limpar_texto(valor)
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
        'estado_digitalizador': '-',
        'tinta_preto': '-',
        'caixa_manutencao': '-',
        'nivel_papel': '-',
        'nivel_papel_bandeja1': '-',
        'tamanho_papel': '-',
        'tipo_papel': '-',
        'firmware': '-',
        'mac': '-',
        'nome_dispositivo': '-',
        'numero_serie': '-',
        'data_hora': '-',
        'epson_connect': '-',
        'leitor_cartao': '-'
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
        'estado_digitalizador': r'Estado do digitalizador\s*[:：]\s*([^\n]+)',
        'caixa_manutencao': r'Caixa de manutenção\s*[:：]\s*([^\n]+)',
        'nivel_papel': r'Nível de Papel Restante\s*[:：]\s*([^\n]+)',
        'nivel_papel_bandeja1': r'Aliment\.?\s*1[\s\S]{0,30}Nível de Papel Restante\s*[:：]\s*([^\n]+)',
        'tamanho_papel': r'Tamanho do papel\s*[:：]\s*([^\n]+)',
        'tipo_papel': r'Tipo papel\s*[:：]\s*([^\n]+)',
        'firmware': r'Firmware\s*[:：]\s*([^\n]+)',
        'mac': r'Endereço MAC da rede\s*[:：]\s*([0-9A-Fa-f:]{17})',
        'data_hora': r'Data e Hora\s*[:：]\s*([^\n]+)',
        'epson_connect': r'Estado de Epson Connect\s*[:：]\s*([^\n]+)',
        'leitor_cartao': r'Status do leitor de cartão\s*[:：]\s*([^\n]+)'
    }

    for chave, padrao in padroes.items():
        match = re.search(padrao, texto, re.IGNORECASE)
        if match:
            dados[chave] = match.group(1).strip()

    dados['tinta_preto'] = extrair_nivel_tinta(soup, texto)
    dados.update(extrair_identificacao_dispositivo(soup))
    return dados


def extrair_contadores(html):
    dados = {
        'total_geral': '-',
        'total_pb': '-',
        'total_cor': '-',
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
        'numero total de paginas a cor': 'total_cor',
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


COLUNAS_TABELA_COMPLETA = (
    ('setor', 'Setor físico'),
    ('host', 'Hostname'),
    ('ip', 'IP'),
    ('nome', 'Identificação'),
    ('nome_dispositivo', 'Nome do dispositivo'),
    ('numero_serie', 'Número de série'),
    ('modelo', 'Modelo'),
    ('mac', 'MAC'),
    ('firmware', 'Firmware'),
    ('total_geral', 'Número total de páginas'),
    ('total_pb', 'P&B'),
    ('total_cor', 'Cor'),
    ('total_2faces', 'Impressão em 2 faces'),
    ('total_1face', 'Impressão em 1 face'),
    ('tinta_preto', 'Tinta preta'),
    ('status', 'Status'),
    ('estado_impressora', 'Estado da impressora'),
    ('estado_digitalizador', 'Estado do digitalizador'),
    ('leitor_cartao', 'Leitor de cartão'),
    ('epson_connect', 'Epson Connect'),
    ('caixa_manutencao', 'Caixa de manutenção'),
    ('nivel_papel', 'Nível de papel geral'),
    ('nivel_papel_bandeja1', 'Bandeja 1'),
    ('tamanho_papel', 'Tamanho do papel'),
    ('tipo_papel', 'Tipo de papel'),
    ('data_hora', 'Data/hora da impressora')
)


def gerar_tabela_completa(resultados, limite_tinta=20):
    cabecalho = []
    contadores = {'total_pb', 'total_cor', 'total_2faces', 'total_1face'}
    colunas_contadores_destaque = contadores | {'tinta_preto'}
    identificacao = {
        'setor', 'host', 'ip', 'nome', 'nome_dispositivo',
        'numero_serie', 'modelo', 'mac', 'firmware'
    }
    alertas_por_ip = {
        alerta['ip']: alerta['tipo']
        for alerta in gerar_alertas(resultados, limite_tinta)
    }
    for chave, rotulo in COLUNAS_TABELA_COMPLETA:
        estilo = (
            'border:1px solid #cbd5e1;padding:8px 10px;text-align:left;'
            'white-space:nowrap;background:#0f4c81;color:#fff;'
        )
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
            f'<th scope="col" style="{estilo}">{escapar_html(rotulo)}</th>'
        )

    linhas = []
    for item in resultados:
        status = limpar_texto(item.get('status'))
        tipo_alerta = alertas_por_ip.get(limpar_texto(item.get('ip')))
        if tipo_alerta == 'Sem comunicação':
            classe_linha = 'sem-comunicacao'
            estilo_linha = 'background:#fee2e2;color:#991b1b;'
        elif tipo_alerta == 'Tinta vazia':
            classe_linha = 'alerta-tinta-vazia'
            estilo_linha = 'background:#fecaca;color:#991b1b;'
        elif tipo_alerta == 'Tinta baixa':
            classe_linha = 'alerta-tinta-baixa'
            estilo_linha = 'background:#ffedd5;color:#9a3412;'
        elif status.startswith('Sucesso parcial'):
            classe_linha = 'sucesso-parcial'
            estilo_linha = 'background:#fef3c7;color:#92400e;'
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
            valor = (
                link_gestao_impressora_html(item.get(chave))
                if chave == 'ip'
                else escapar_html(item.get(chave))
            )
            celulas.append(f'<td{classe} style="{estilo}">{valor}</td>')
        classes_linha = ' '.join(
            classe for classe in ('linha-impressora', classe_linha) if classe
        )
        linhas.append(
            f'<tr class="{classes_linha}">{"".join(celulas)}</tr>'
        )
    if not linhas:
        return '<p>Nenhuma impressora foi consultada.</p>'

    return (
        '<div class="tabela-horizontal" '
        'style="max-width:100%;overflow-x:auto;overscroll-behavior-x:contain;">'
        '<table class="dados-impressora" '
        'style="border-collapse:collapse;table-layout:auto;min-width:2400px;'
        'font:13px Arial,sans-serif;">'
        f'<thead><tr>{"".join(cabecalho)}</tr></thead>'
        f'<tbody>{"".join(linhas)}</tbody></table></div>'
    )


def gerar_html(resultados, data_consulta, limite_tinta=20):
    alertas = gerar_alertas(resultados, limite_tinta)
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
    <title>Relatório de Impressoras</title>
    <style>
        html {{ zoom: 75%; }}
        * {{ box-sizing: border-box; font-family: Arial, sans-serif; }}
        body {{ margin: 0; background: #eef3f8; color: #1e293b; padding: 24px; }}
        .container {{ max-width: 1280px; margin: 0 auto; }}
        .cabecalho {{ background: linear-gradient(135deg, #0f4c81, #1a73c5); color: white; padding: 28px 24px; border-radius: 12px; text-align: center; margin-bottom: 18px; }}
        .cabecalho h1 {{ margin: 0 0 6px; font-size: 30px; }}
        .cabecalho p {{ margin: 0; opacity: 0.9; }}
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
        .tabela-final {{ max-width: 1000px; margin: 24px auto; padding: 20px; background: #fff; border: 1px solid #cbd5e1; border-radius: 12px; }}
        .tabela-final h2 {{ margin: 0 0 8px; color: #0f4c81; }}
        .tabela-final p {{ margin: 0 0 18px; color: #475569; }}
        .rodape {{ text-align: center; padding: 20px; font-size: 12px; color: #64748b; }}
        @media (max-width: 768px) {{ .card-header {{ display: block; }} .status {{ display: inline-block; margin-top: 10px; }} }}
    </style>
</head>
<body>
    <div class=\"container\">
        <div class=\"cabecalho\">
            <h1>🖨️ Relatório Mensal de Impressoras</h1>
            <p>Inventário técnico, insumos, papel e contadores de impressão</p>
        </div>

        <div class=\"info-bar\">
            <strong>📅 Data da consulta:</strong> {escapar_html(data_consulta)}
            <h2 class=\"resumo-titulo\">Resumo executivo</h2>
            <div class=\"resumo\">
                <div class=\"chip\"><strong>Total de equipamentos</strong><span>{len(resultados)}</span></div>
                <div class=\"chip\"><strong>Consultas concluídas</strong><span>{equipamentos_ok}</span></div>
                <div class=\"chip\"><strong>Consultas parciais</strong><span>{equipamentos_parciais}</span></div>
                <div class=\"chip\"><strong>Falhas de comunicação</strong><span>{equipamentos_com_falha}</span></div>
                <div class=\"chip\"><strong>Itens para atenção</strong><span>{len(alertas)}</span></div>
            </div>
            <p class=\"observacao\">O relatório detalha localização, identificação técnica, estado, insumos e contadores de cada equipamento.</p>
        </div>
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
                        <strong>Setor físico:</strong> {escapar_html(alerta['setor'])}
                        &nbsp; | &nbsp; <strong>Endereço IP:</strong> {link_gestao_impressora_html(alerta['ip'])}
                        &nbsp; | &nbsp; <strong>Hostname:</strong> {escapar_html(alerta['host'])}
                    </p>
                    <p class="acao-detalhe">
                        <strong>Nome do dispositivo:</strong> {escapar_html(alerta['nome_dispositivo'])}
                        &nbsp; | &nbsp; <strong>Número de série:</strong> {escapar_html(alerta['numero_serie'])}
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
                        <div class=\"item\"><div class=\"label\">Nome do dispositivo</div><div class=\"valor\">{escapar_html(r.get('nome_dispositivo'))}</div></div>
                        <div class=\"item\"><div class=\"label\">Número de série</div><div class=\"valor\">{escapar_html(r.get('numero_serie'))}</div></div>
                        <div class=\"item\"><div class=\"label\">MAC</div><div class=\"valor\">{escapar_html(r['mac'])}</div></div>
                        <div class=\"item\"><div class=\"label\">Firmware</div><div class=\"valor\">{escapar_html(r['firmware'])}</div></div>
                        <div class=\"item\"><div class=\"label\">Data/Hora</div><div class=\"valor\">{escapar_html(r['data_hora'])}</div></div>
                    </div>

                    <div>
                        <div class=\"titulo-secao\">✅ Estado do equipamento</div>
                        <div class=\"item\"><div class=\"label\">Impressora</div><div class=\"valor\">{escapar_html(r['estado_impressora'])}</div></div>
                        <div class=\"item\"><div class=\"label\">Digitalizador</div><div class=\"valor\">{escapar_html(r['estado_digitalizador'])}</div></div>
                        <div class=\"item\"><div class=\"label\">Leitor de cartão</div><div class=\"valor\">{escapar_html(r['leitor_cartao'])}</div></div>
                        <div class=\"item\"><div class=\"label\">Epson Connect</div><div class=\"valor\">{escapar_html(r['epson_connect'])}</div></div>
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
                        <div class=\"item\"><div class=\"label\">Bandeja 1</div><div class=\"valor\">{escapar_html(r['nivel_papel_bandeja1'])}</div></div>
                        <div class=\"item\"><div class=\"label\">Tamanho / Tipo</div><div class=\"valor\">{escapar_html(r['tamanho_papel'])} / {escapar_html(r['tipo_papel'])}</div></div>
                    </div>

                    <div>
                        <div class=\"titulo-secao\">📊 Contadores</div>
                        <div class=\"item\"><div class=\"label\">Total geral</div><div class=\"valor\" style=\"font-size:16px; color:#0f4c81\">{escapar_html(r['total_geral'])}</div></div>
                        <div class=\"item\"><div class=\"label\">P&B</div><div class=\"valor\">{escapar_html(r['total_pb'])}</div></div>
                        <div class=\"item\"><div class=\"label\">Cor</div><div class=\"valor\">{escapar_html(r['total_cor'])}</div></div>
                        <div class=\"item\"><div class=\"label\">2 faces / 1 face</div><div class=\"valor\">{escapar_html(r['total_2faces'])} / {escapar_html(r['total_1face'])}</div></div>
                    </div>
                </div>

                {alertas_html}
            </div>
        </div>
"""

    html += f"""
        <section class="tabela-final">
            <h2>Relatório completo em tabela</h2>
            <p>Cada linha representa uma impressora. Os dados de identificação ficam agrupados com IP e MAC, antes dos contadores; linhas destacadas indicam falhas ou alertas. O total de páginas está destacado em amarelo.</p>
            {gerar_tabela_completa(resultados, limite_tinta)}
        </section>
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


def salvar_csv(resultados, caminho):
    colunas = [
        ('setor', 'Setor físico'),
        ('host', 'Hostname'),
        ('ip', 'IP'),
        ('nome', 'Identificação'),
        ('nome_dispositivo', 'Nome do dispositivo'),
        ('numero_serie', 'Número de série'),
        ('modelo', 'Modelo'),
        ('mac', 'MAC'),
        ('firmware', 'Firmware'),
        ('total_geral', 'Total geral'),
        ('total_pb', 'Total P&B'),
        ('total_cor', 'Total cor'),
        ('total_2faces', 'Total 2 faces'),
        ('total_1face', 'Total 1 face'),
        ('status', 'Status'),
        ('estado_impressora', 'Estado da impressora'),
        ('estado_digitalizador', 'Estado do digitalizador'),
        ('tinta_preto', 'Tinta preta'),
        ('caixa_manutencao', 'Caixa de manutenção'),
        ('nivel_papel', 'Nível de papel'),
        ('nivel_papel_bandeja1', 'Nível da bandeja 1'),
        ('tamanho_papel', 'Tamanho do papel'),
        ('tipo_papel', 'Tipo de papel'),
        ('data_hora', 'Data/hora da impressora'),
        ('epson_connect', 'Epson Connect'),
        ('leitor_cartao', 'Leitor de cartão')
    ]
    caminho = Path(caminho)
    with caminho.open('w', newline='', encoding='utf-8-sig') as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=[rotulo for _, rotulo in colunas])
        escritor.writeheader()
        for item in resultados:
            escritor.writerow({
                rotulo: limpar_texto(item.get(chave))
                for chave, rotulo in colunas
            })
    return caminho.resolve()


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


def montar_email_body(resultados, data_consulta, caminho_html, caminho_csv, limite_tinta=20):
    return f"""<!doctype html>
<html lang="pt-BR">
<head><meta charset="utf-8"><title>Relatório mensal de impressoras</title></head>
<body style="font-family:Arial,sans-serif;color:#1e293b;">
    <p>Prezados,</p>
    <p>Encaminho o relatório técnico mensal dos equipamentos de impressão locados.</p>
    <p><strong>Data da consulta:</strong> {escapar_html(data_consulta)}<br>
    <strong>Equipamentos consultados:</strong> {len(resultados)}</p>
    <h2 style="color:#0f4c81;">Detalhamento dos equipamentos</h2>
    <p>Os dados de identificação ficam agrupados com IP e MAC, antes dos contadores; as linhas destacadas indicam falhas ou alertas. O total de páginas está em amarelo.</p>
    {gerar_tabela_completa(resultados, limite_tinta)}
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


def montar_whatsapp_body(resultados, data_consulta):
    linhas = [
        'Bom dia,',
        '',
        'Segue relatório mensal das impressoras:',
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
                f"Setor: {limpar_texto(item.get('setor'))}",
                f"Máquina: {limpar_texto(item.get('host'))}",
                f"IP: {ip} | Gestão: {url_gestao_impressora(ip) or '-'} | "
                f"MAC: {limpar_texto(item.get('mac'))}",
                f"Nome do dispositivo: {limpar_texto(item.get('nome_dispositivo'))} | "
                f"Número de série: {limpar_texto(item.get('numero_serie'))} | "
                f"Modelo: {limpar_texto(item.get('modelo'))}",
                '*Ação: acionar o TI da filial.*',
                ''
            ])
    else:
        linhas.extend(['*Sem falhas de comunicação registradas.*', ''])

    linhas.extend(['*DETALHAMENTO COMPLETO*', ''])
    for item in resultados:
        ip = limpar_texto(item.get('ip'))
        linhas.extend([
            f"Identificação: {limpar_texto(item.get('nome'), 'Impressora')} | Modelo: {limpar_texto(item.get('modelo'))}",
            f"Setor físico: {limpar_texto(item.get('setor'))}",
            f"Hostname: {limpar_texto(item.get('host'))} | IP: {ip} | "
            f"Gestão: {url_gestao_impressora(ip) or '-'} | "
            f"MAC: {limpar_texto(item.get('mac'))}",
            f"Nome do dispositivo: {limpar_texto(item.get('nome_dispositivo'))} | "
            f"Número de série: {limpar_texto(item.get('numero_serie'))} | "
            f"Modelo: {limpar_texto(item.get('modelo'))}",
            f"Status: {limpar_texto(item.get('status'))}",
            f"Tinta preta: {limpar_texto(item.get('tinta_preto'))}",
            (
                f"Contadores — Total: {limpar_texto(item.get('total_geral'))} | "
                f"P&B: {limpar_texto(item.get('total_pb'))} | Cor: {limpar_texto(item.get('total_cor'))} | "
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


def abrir_email(email, body, assunto='Relatório mensal de impressoras'):
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
    total_impressoras = len(dispositivos)
    for indice, imp in enumerate(dispositivos, start=1):
        nome = imp['nome']
        setor = imp.get('setor', 'Não informado')
        ip = imp['ip']
        host = imp['host']
        try:
            url_estado = f'https://{ip}{CAMINHO_ESTADO}'
            resp_estado = requests.get(url_estado, timeout=8, verify=False)
            if resp_estado.status_code != 200:
                resultados.append({
                    'nome': nome,
                    'setor': setor,
                    'ip': ip,
                    'host': host,
                    'status': f'Erro {resp_estado.status_code}',
                    'modelo': '-', 'estado_impressora': '-', 'estado_digitalizador': '-',
                    'tinta_preto': '-', 'caixa_manutencao': '-', 'nivel_papel': '-',
                    'nivel_papel_bandeja1': '-', 'tamanho_papel': '-', 'tipo_papel': '-',
                    'firmware': '-', 'mac': '-', 'nome_dispositivo': '-',
                    'numero_serie': limpar_texto(imp.get('numero_serie')),
                    'data_hora': '-', 'epson_connect': '-',
                    'leitor_cartao': '-', 'total_geral': '-', 'total_pb': '-',
                    'total_cor': '-', 'total_2faces': '-', 'total_1face': '-'
                })
                continue

            dados_estado = extrair_estado_produto(resp_estado.content)
            dados_identificacao = {
                chave: limpar_texto(dados_estado.get(chave))
                for chave in ('nome_dispositivo', 'numero_serie')
            }
            url_contador = f'https://{ip}{CAMINHO_CONTADOR}'
            resp_contador = requests.get(url_contador, timeout=8, verify=False)

            dados_contador = {
                'total_geral': '-', 'total_pb': '-', 'total_cor': '-',
                'total_2faces': '-', 'total_1face': '-'
            }
            avisos_parciais = []
            if resp_contador.status_code == 200:
                dados_contador = extrair_contadores(resp_contador.content)
                if all(valor == '-' for valor in dados_contador.values()):
                    avisos_parciais.append('contadores não encontrados')
            else:
                avisos_parciais.append(f'contadores HTTP {resp_contador.status_code}')

            if '-' in dados_identificacao.values():
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
                dados_identificacao['numero_serie'] = limpar_texto(
                    imp.get('numero_serie')
                )
            identificacao_ausente = [
                rotulo
                for chave, rotulo in (
                    ('nome_dispositivo', 'nome do dispositivo'),
                    ('numero_serie', 'número de série')
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
                'ip': ip,
                'host': host,
                'status': resultados_status,
                'nome_dispositivo': dados_identificacao['nome_dispositivo'],
                'numero_serie': dados_identificacao['numero_serie'],
                'modelo': limpar_texto(dados_estado.get('modelo')),
                'estado_impressora': limpar_texto(dados_estado.get('estado_impressora')),
                'estado_digitalizador': limpar_texto(dados_estado.get('estado_digitalizador')),
                'tinta_preto': limpar_texto(dados_estado.get('tinta_preto')),
                'caixa_manutencao': limpar_texto(dados_estado.get('caixa_manutencao')),
                'nivel_papel': limpar_texto(dados_estado.get('nivel_papel')),
                'nivel_papel_bandeja1': limpar_texto(dados_estado.get('nivel_papel_bandeja1')),
                'tamanho_papel': limpar_texto(dados_estado.get('tamanho_papel')),
                'tipo_papel': limpar_texto(dados_estado.get('tipo_papel')),
                'firmware': limpar_texto(dados_estado.get('firmware')),
                'mac': limpar_texto(dados_estado.get('mac')),
                'data_hora': limpar_texto(dados_estado.get('data_hora')),
                'epson_connect': limpar_texto(dados_estado.get('epson_connect')),
                'leitor_cartao': limpar_texto(dados_estado.get('leitor_cartao')),
                'total_geral': limpar_texto(dados_contador.get('total_geral')),
                'total_pb': limpar_texto(dados_contador.get('total_pb')),
                'total_cor': limpar_texto(dados_contador.get('total_cor')),
                'total_2faces': limpar_texto(dados_contador.get('total_2faces')),
                'total_1face': limpar_texto(dados_contador.get('total_1face'))
            })
        except requests.RequestException as exc:
            resultados.append({
                'nome': nome,
                'setor': setor,
                'ip': ip,
                'host': host,
                'status': f'Falha de comunicação: {exc}',
                'modelo': '-', 'estado_impressora': '-', 'estado_digitalizador': '-',
                'tinta_preto': '-', 'caixa_manutencao': '-', 'nivel_papel': '-',
                'nivel_papel_bandeja1': '-', 'tamanho_papel': '-', 'tipo_papel': '-',
                'firmware': '-', 'mac': '-', 'nome_dispositivo': '-',
                'numero_serie': limpar_texto(imp.get('numero_serie')),
                'data_hora': '-', 'epson_connect': '-',
                'leitor_cartao': '-', 'total_geral': '-', 'total_pb': '-',
                'total_cor': '-', 'total_2faces': '-', 'total_1face': '-'
            })
        finally:
            if progress_callback:
                progress_callback(indice, total_impressoras, nome)

    return resultados


def construir_interface(config, caminho_config):
    root = tk.Tk()
    root.title('Monitoramento de Impressoras')
    root.geometry('1024x700')
    root.minsize(820, 620)
    root.state('zoomed')
    root.configure(bg='#eef3f8')

    dados = {'resultados': None, 'data': None, 'html': None, 'csv': None}
    alertas_por_iid = {}
    pasta_relatorios = PASTA_DADOS / 'relatorios'
    pasta_relatorios.mkdir(parents=True, exist_ok=True)

    area_rolagem = tk.Frame(root, bg='#eef3f8')
    area_rolagem.pack(fill='both', expand=True)
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
        text='Relatório mensal de impressoras',
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
    tk.Label(
        frame,
        text='A consulta inicia ao abrir o programa. O relatório será aberto no navegador ao terminar.',
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
        'tipo', 'setor', 'nome', 'ip', 'nome_dispositivo',
        'numero_serie', 'modelo', 'mac'
    )
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
        ('setor', 'Setor físico', 140),
        ('nome', 'Impressora', 150),
        ('ip', 'IP (clique para abrir)', 190),
        ('nome_dispositivo', 'Nome do dispositivo', 160),
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
            or falhas_lista.identify_column(event.x) != '#4'
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
            and falhas_lista.identify_column(event.x) == '#4'
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
        janela.geometry('930x460')
        janela.minsize(860, 400)
        janela.transient(root)
        janela.columnconfigure(0, weight=1)
        janela.rowconfigure(0, weight=1)

        lista_editada = [dict(item) for item in config['impressoras']]
        colunas = (
            'nome', 'setor', 'host', 'ip', 'numero_serie', 'tipo_conexao'
        )
        tabela = ttk.Treeview(janela, columns=colunas, show='headings', selectmode='browse')
        for coluna, titulo, largura in (
            ('nome', 'Identificação', 150),
            ('setor', 'Setor físico', 150),
            ('host', 'Hostname', 170),
            ('ip', 'IP', 130),
            ('numero_serie', 'Número de série', 170),
            ('tipo_conexao', 'Tipo Conexão', 110)
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
                tabela.insert(
                    '',
                    tk.END,
                    iid=str(indice),
                    values=(
                        item['nome'],
                        item['setor'],
                        item['host'],
                        item['ip'],
                        item.get('numero_serie') or '-',
                        item['tipo_conexao']
                    )
                )

        def editar_impressora(indice=None):
            registro = lista_editada[indice] if indice is not None else {
                'nome': '', 'setor': '', 'host': '', 'ip': '',
                'numero_serie': '', 'tipo_conexao': 'CABO'
            }
            formulario = tk.Toplevel(janela)
            formulario.title('Editar impressora' if indice is not None else 'Adicionar impressora')
            formulario.geometry('480x390')
            formulario.resizable(False, False)
            formulario.transient(janela)
            formulario.grab_set()

            campos = (
                ('Identificação', 'nome'),
                ('Setor físico', 'setor'),
                ('Hostname', 'host'),
                ('IP IPv4', 'ip'),
                ('Número de Série', 'numero_serie')
            )
            variaveis = {}
            entradas = {}
            for linha, (rotulo, chave) in enumerate(campos):
                tk.Label(formulario, text=rotulo, font=('Arial', 10, 'bold')).grid(
                    row=linha, column=0, sticky='w', padx=16, pady=(12 if linha == 0 else 6, 3)
                )
                variavel = tk.StringVar(value=registro.get(chave, ''))
                variaveis[chave] = variavel
                entrada = tk.Entry(formulario, textvariable=variavel, font=('Arial', 10), width=40)
                entrada.grid(
                    row=linha, column=1, sticky='ew', padx=(8, 16), pady=(12 if linha == 0 else 6, 3)
                )
                entradas[chave] = entrada
            formulario.columnconfigure(1, weight=1)
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

            combo_tipo_conexao.bind(
                '<<ComboboxSelected>>',
                lambda _event: conexao_escolhida.update(manualmente=True),
                add='+'
            )
            entradas['nome'].bind('<KeyRelease>', atualizar_tipo_sugerido, add='+')

            def salvar_impressora():
                nova_impressora = {
                    chave: variavel.get().strip()
                    for chave, variavel in variaveis.items()
                }
                nova_lista = [dict(item) for item in lista_editada]
                if indice is None:
                    nova_lista.append(nova_impressora)
                else:
                    nova_lista[indice] = nova_impressora
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
            ).grid(row=len(campos) + 1, column=0, columnspan=2, pady=14)

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
            janela.destroy()
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

    def abrir_rascunho_email():
        if dados['resultados'] is None:
            messagebox.showinfo('Aguarde', 'A consulta das impressoras ainda está em andamento.')
            return
        try:
            persistir_contatos()
            body = montar_email_body(
                dados['resultados'],
                dados['data'],
                dados['html'],
                dados['csv'],
                config['limite_tinta']
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
        try:
            persistir_contatos()
            abrir_whatsapp(
                whatsapp_var.get().strip(),
                montar_whatsapp_body(
                    dados['resultados'],
                    dados['data']
                )
            )
        except (OSError, RuntimeError, ValueError) as exc:
            messagebox.showerror('Não foi possível abrir o WhatsApp', str(exc))

    consultando = {'ativo': False}
    botoes_config = [
        ('Gerenciar impressoras', abrir_configuracao_impressoras, '#475569'),
        ('Abrir relatório', abrir_relatorio, '#0f4c81'),
        ('Rascunho de e-mail', abrir_rascunho_email, '#1d4ed8'),
        ('Abrir WhatsApp', abrir_conversa_whatsapp, '#16a34a'),
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

    def consulta_em_segundo_plano():
        try:
            ips_locais, dentro_da_faixa = verificar_rede_corporativa(
                config['faixa_rede_corporativa'],
                config['impressoras']
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
                lista_impressoras=config['impressoras']
            )
            root.after(0, lambda: atualizar_progresso(82, 'Montando o relatório...'))
            html_relatorio = gerar_html(
                resultados,
                data_consulta,
                config['limite_tinta']
            )
            root.after(0, lambda: atualizar_progresso(90, 'Salvando o relatório HTML...'))
            marca_tempo = datetime.now().strftime('%Y%m%d_%H%M%S')
            caminho_html = salvar_relatorio(
                html_relatorio,
                pasta_relatorios / f'relatorio_impressoras_{marca_tempo}.html'
            )
            root.after(0, lambda: atualizar_progresso(95, 'Salvando o relatório CSV...'))
            caminho_csv = salvar_csv(
                resultados,
                pasta_relatorios / f'relatorio_impressoras_{marca_tempo}.csv'
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
        if atualizar_seriais_cadastrados(config, resultados):
            try:
                salvar_config(config, caminho_config)
            except OSError as exc:
                messagebox.showwarning(
                    'Número de série detectado',
                    f'O número de série foi encontrado, mas não foi possível salvar '
                    f'o cadastro: {exc}',
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
                    values=(
                        alerta['tipo'],
                        alerta['setor'],
                        alerta['nome'],
                        alerta['ip'],
                        alerta['nome_dispositivo'],
                        alerta['numero_serie'],
                        alerta['modelo'],
                        alerta.get('mac', '-')
                    ),
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

    iniciar_consulta()
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
