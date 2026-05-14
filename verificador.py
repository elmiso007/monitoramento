#verifica.py

import pandas as pd
import json
import slack_sdk as sd
import sys
from get_atendimentos import get_atendimentos 
import time
from datetime import datetime, timedelta
import locale
from sqlalchemy import  text
from conecta_banco import *
import numpy as np
import holidays
from notifica import notifica, notifica_boas_noticias
from PromptGemini import analise_ia 
import uuid
import re
from pathlib import Path

sql_path = Path(__file__).parent

#|-------------------------------------------------------------------------------------------------------------------|

#VARIAVEIS DE DATA E HORA PARA QUERY E PARA CALCULO DO PERÍODO
task = 'monitoramento_lw_octadesk'

# Limiar de alta percentual sobre a media da ultima semana para acionar a analise via Gemini.
# Ajuste conforme sensibilidade desejada (ex.: 20 = dispara quando o volume atual estiver 20%+ acima da media).
LIMIAR_ALTA_PERCENTUAL = 20

# Limiar de queda percentual (valor negativo) para notificacao informativa via notifica_boas_noticias.
# Ex.: -20 = notifica quando o volume atual estiver 20%+ abaixo da media.
LIMIAR_QUEDA_PERCENTUAL = -20

# Obter a data e hora atuais
data_hoje = datetime.now().date()
hora_atual = datetime.now()
hora_atual_formatada = hora_atual.strftime("%H:%M:%S")
# Converter para objeto time
hora_formatada_time = datetime.strptime(hora_atual_formatada, "%H:%M:%S").time()

def verificar_horario_operacional(hora_atual):
    """Encerra o script se o horário estiver fora do intervalo 06:00–22:00."""
    hora_inicio_execucao = datetime.strptime("06:00:00", "%H:%M:%S").time()
    hora_fim_execucao = datetime.strptime("22:00:00", "%H:%M:%S").time()

    if not (hora_inicio_execucao <= hora_atual <= hora_fim_execucao):
        print(f"Horário atual {hora_atual} está fora do intervalo permitido (06:00 às 22:00). Encerrando.")
        sys.exit()

verificar_horario_operacional(hora_formatada_time)

# Calcular a hora e os minutos há 10 minutos
hora_10_minutos_atras = hora_atual - timedelta(minutes=10)
hora_10_minutos_atras_formatada = hora_10_minutos_atras.strftime("%H:%M:%S")

# Calcular a hora e os minutos há 10 minutos
hora_30_minutos_atras = hora_atual - timedelta(minutes=30)
hora_30_minutos_atras_formatada = hora_30_minutos_atras.strftime("%H:%M:%S")
# Converter para objeto time
hora_30_minutos_atras_formatada_time = datetime.strptime(hora_30_minutos_atras_formatada, "%H:%M:%S").time()

current_time = datetime.now()

# Lista de feriados no Brasil (ou outro país)
feriados_brasil = holidays.Brazil()

# Verificar se hoje é um dia útil — pipeline só roda em dia util
if not (data_hoje.weekday() < 5 and data_hoje not in feriados_brasil):
    print(f"{data_hoje} nao e um dia util. Encerrando.")
    sys.exit()

print(f"{data_hoje} e um dia util.")
data_primaria = datetime.now().date() - timedelta(days=11)
dia_util = True

#|-------------------------------------------------------------------------------------------------------------------|

#FUNÇÕES 

def count_rows(df, data=None, hora_inicio=None, hora_fim=None):
    # Filtrar por data, se fornecida
    if data:
        df = df[df['data_inicio_interacao'].dt.date == data]

    # Filtrar por hora de início, se fornecida
    if hora_inicio is not None:
        df = df[df['hora'] >= hora_inicio]  # Comparação direta com time

    # Filtrar por hora de fim, se fornecida
    if hora_fim is not None:
        df = df[df['hora'] <= hora_fim]  # Comparação direta com time

    # Contar o número de registros
    count = df.shape[0]
    return count

def gerar_chave_unica():
    return str(uuid.uuid4())

#|-------------------------------------------------------------------------------------------------------------------|

#QUERY E CONEXÃO COM O BANCO (script ja garantiu acima que e dia util)

query = f"""
SELECT
    c.protocolo,
    c.id as chave,
    c.data_inicio_interacao,
    DATE_TRUNC('day', c.data_inicio_interacao)::DATE AS dia,
    TO_CHAR(c.data_inicio_interacao, 'HH24:MI:SS')::TIME AS hora,
    c.contact_name as cliente,
    c.agent_name as analista,
    a.fila,
    a.produto,
    a.equipe,
    a.setor, d.dia_util, d.feriado, d.dia_semana,d.mes
FROM lw_octadesk.chat c
LEFT JOIN depara_chat a ON c.grupo_nome = a.fila
LEFT JOIN public.dias d ON DATE_TRUNC('day', c.data_inicio_interacao)::DATE  = d.dia
WHERE data_inicio_interacao BETWEEN '{data_primaria} {hora_30_minutos_atras_formatada}' AND '{data_hoje} {hora_atual_formatada}'
  AND a.setor = 'Suporte' AND d.dia_util IS TRUE;
"""

engine = get_sqlalchemy_engine()
conn = get_pyodbc_connection()
connection = engine.connect()

df = pd.read_sql_query(query, conn)

# Verifica se o DataFrame está vazio antes de continuar
if df.empty:
    print("Nenhum dado retornado da consulta. Interrompendo a execução da pipeline.")
    conn.close()
    connection.close()
    engine.dispose()
    sys.exit()

else:    

    tabela = 'rawdata_monitoramento'
    schema = 'lw_octadesk'

    # Filtrar os últimos 7 dias únicos existentes
    dias_unicos = df['dia'].drop_duplicates().sort_values(ascending=False)
    # Ignorar o dia atual e selecionar os 7 dias únicos anteriores
    dias_7_anteriores = dias_unicos[dias_unicos < data_hoje].head(7)

    # Filtrar o DataFrame para incluir apenas os dias selecionados
    df_filtrado = df[df['dia'].isin(dias_7_anteriores)]

    #|-------------------------------------------------------------------------------------------------------------------|

    #MANIPULAÇÃO DOS DADOS

    # astype(str) garante compatibilidade quando o driver entrega a coluna como datetime.time
    df['hora'] = pd.to_datetime(df['hora'].astype(str), format='%H:%M:%S').dt.time
    intervalos = []

    # Extrair valores únicos de data (ignorando as horas)
    dias = df_filtrado['dia'].unique()

    #função para localizar a quantidade de atendimentos dos últimos 7 dias para o período analisado
    for dia in dias:
        atendimentos = count_rows(df, dia, hora_30_minutos_atras_formatada_time, hora_formatada_time)
        intervalos.append(atendimentos)

    print(f'ultimos dias {intervalos}')
    chave = gerar_chave_unica()
    print(chave)

    #ARMAZENA A MEDIA DOS ATENDIMENTOS DOS ULTIMOS 7 DIAS PARA O MESMO HORÁRIO DA CONSULTA
    media_ultima_semana_float = np.mean(intervalos)
    media_ultima_semana = round(media_ultima_semana_float, 2)
    print(f"A media da ultima semana é {media_ultima_semana}")

    #ARMAZENA O TOTAL DE ATENDIMENTOS DE SUPORTE DOS ULTIMOS 30 MINUTOS.
    atendimentos_atuais = count_rows(df, data_hoje, hora_30_minutos_atras_formatada_time, hora_formatada_time)
    print(f"A quantidade de atendimentos de hoje é: {atendimentos_atuais}")

    if media_ultima_semana > 0:
        percentual = round(((atendimentos_atuais - media_ultima_semana) / media_ultima_semana) * 100, 2)
    else:
        # Sem base historica (media=0) - nao ha como calcular variacao percentual.
        percentual = 0.0
    print(f"O percentual em relação a mesma janela de horário é de : {percentual}")

    if percentual >= LIMIAR_ALTA_PERCENTUAL and atendimentos_atuais > 0:
        print("Analisando interações de clientes!")
        data_inicio = f"{data_hoje}  {hora_30_minutos_atras_formatada_time}"
        data_fim = f"{data_hoje} {hora_formatada_time}"
        print(f" Período :{data_inicio} a {data_fim}")

        conversas = get_atendimentos(data_inicio, data_fim)
        content = analise_ia(conversas, data_inicio, data_fim, task, 'Suporte', chave, task)

        # Aplicando a substituição com regex
        content = re.sub(r'\*\*', '*', content)

        # ADICIONE ESTA LINHA: Garante que haja uma linha nova antes do conteúdo
        if not content.startswith('\n'):
            content = '\n' + content

        notificou = True
        notifica(content, percentual, media_ultima_semana)

    elif percentual <= LIMIAR_QUEDA_PERCENTUAL and atendimentos_atuais > 0:
        # Queda relevante: notificacao informativa, sem analise via Gemini.
        print(f"Queda relevante detectada ({percentual}%). Enviando boas noticias.")
        notifica_boas_noticias(hora_30_minutos_atras_formatada, hora_atual_formatada, percentual)
        notificou = True

    else:
        notificou = False

    df = pd.DataFrame({
        'data': [current_time],
        'data_inicio': [data_primaria],
        'hora_inicio': [hora_10_minutos_atras_formatada],
        'data_fim': [data_hoje],
        'hora_fim': [hora_atual_formatada],
        'dia_util': [dia_util],
        'media_comparativa': [media_ultima_semana],
        'atendimentos': [atendimentos_atuais],
        'percentual': [percentual],
        'notificou': [notificou],
        'chave_analise': [chave],
        'created_at': [current_time],
        'updated_at': [current_time]
    })

    print('Gravando verificação no banco...')
    df.to_sql(tabela, con=engine, if_exists='replace', index=False, schema=schema)

    # Lê o script SQL do arquivo
    with open(rf'{sql_path}\insereDados.sql','r', encoding='utf-8') as file:
        sql_script = text(file.read())

    # Executando o script SQL
    connection.execute(sql_script)
    connection.commit()

    conn.close()
    connection.close()
    engine.dispose()
