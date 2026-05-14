#notifica.py

import configparser
import os
from datetime import date, datetime
import locale

import pandas as pd
from slack_sdk import WebClient

from conecta_banco import resolver_caminho_config


# Configurando o idioma para português
locale.setlocale(locale.LC_TIME, "pt_BR.utf8")


def _carregar_token_slack():
    """Le o bot_token da secao [slack] do config.ini. SLACK_BOT_TOKEN no ambiente tem prioridade."""
    token_env = (os.environ.get("SLACK_BOT_TOKEN") or "").strip()
    if token_env:
        return token_env
    parser = configparser.ConfigParser()
    parser.read(resolver_caminho_config(), encoding="utf-8")
    if "slack" not in parser or "bot_token" not in parser["slack"]:
        raise KeyError("bot_token ausente em [slack] do config.ini")
    return parser["slack"]["bot_token"].strip()


_client = None


def _get_client():
    """WebClient Slack inicializado sob demanda (lazy) na primeira chamada de notifica/notifica_boas_noticias."""
    global _client
    if _client is None:
        _client = WebClient(_carregar_token_slack())
    return _client

#destinatarios =  ['C07MS3A645D'] #Canal Oficial Monitoramento LW
destinatarios = ['C07NSPQ69TL'] #Canal teste

def notifica(content,percentual,media):
    # Obtendo o nome do mês
    mes_atual = datetime.now().strftime("%B")

    mensagem = {
	"blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": ":-alert:  Monitoramento de contatos Recebidos :logo-locaweb_ico:",
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"O sistema de monitoramento de contatos identificou um aumento de *`{percentual}`* na quantidade de contatos recebidos em relação a média de *`{media}`* contatos da última semana. "
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{content}"
                }
            }
        ]
    }

    for destinatario in destinatarios:
        # Verificar se o destinatário começa com 'U'
        if destinatario.startswith('U'):
            # Abrir um direct com o usuário do Slack
            response_dm = _get_client().conversations_open(users=destinatario)
            channel_id = response_dm["channel"]["id"]

            # Enviar a mensagem no direct
            response_message = _get_client().chat_postMessage(channel=channel_id, blocks=mensagem["blocks"], text="Report Diário")
            print(f"Mensagem enviada para o direct do usuário {destinatario}.")
        # Verificar se o destinatário começa com 'C'
        elif destinatario.startswith('C'):
            # Usar o código que já possui para destinatários que começam com 'C'
            response_message = _get_client().chat_postMessage(channel=destinatario, blocks=mensagem["blocks"], text="Report Diário")
            print(f"Mensagem enviada para {destinatario}.")




def notifica_boas_noticias(hora_inicio, hora_fim,percentual):

    mensagem = {
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "Monitoramento de Contatos de Chat e WhatsApp"
                        }
                    },
                    {
                        "type": "divider"
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"O monitoramento de contatos das *`{hora_inicio}`* as *`{hora_fim}`* identificou que estamos com uma demanda de *{percentual} *% em relação ao mesmo período dos ultimos 7 dias!\n"
                                )
                        },
                        "accessory": {
                            "type": "image",
                            "image_url": "https://www.locaweb.com.br/images/open-graph.jpg",
                            "alt_text": "logo locaweb"
                        }
                    }
                ]
            }
    
    for destinatario in destinatarios:
        # Verificar se o destinatário começa com 'U'
        if destinatario.startswith('U'):
            # Abrir um direct com o usuário do Slack
            response_dm = _get_client().conversations_open(users=destinatario)
            channel_id = response_dm["channel"]["id"]

            # Enviar a mensagem no direct
            response_message = _get_client().chat_postMessage(channel=channel_id, blocks=mensagem["blocks"], text="Monitoramento de Contatos")
            print(f"Mensagem enviada para o direct do usuário {destinatario}.")
        # Verificar se o destinatário começa com 'C'
        elif destinatario.startswith('C'):
            # Usar o código que já possui para destinatários que começam com 'C'
            response_message = _get_client().chat_postMessage(channel=destinatario, blocks=mensagem["blocks"], text="Monitoramento de Contatos")
            print(f"Mensagem enviada para {destinatario}.")
