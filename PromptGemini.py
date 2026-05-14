# PromptGemini.py

import configparser
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from textwrap import dedent

import pandas as pd
import spacy
from google import genai
from google.genai.errors import APIError
from sqlalchemy import text

from conecta_banco import resolver_caminho_config, get_sqlalchemy_engine


sql_path = Path(__file__).parent
resposta_path = Path(__file__).parent / "resposta_gemini.md"


def _carregar_config_gemini():
    """Le [gemini].api_key e [gemini].model do config.ini. GEMINI_API_KEY no ambiente tem prioridade."""
    parser = configparser.ConfigParser()
    parser.read(resolver_caminho_config(), encoding="utf-8")
    secao = parser["gemini"] if "gemini" in parser else {}
    api_key = (os.environ.get("GEMINI_API_KEY") or secao.get("api_key", "") or "").strip()
    if not api_key:
        raise KeyError("api_key ausente: defina GEMINI_API_KEY no ambiente ou [gemini].api_key no config.ini")
    model = (secao.get("model", "") or "gemini-2.5-flash").strip()
    return api_key, model


def analise_ia(dataset, data_inicial, data_fim, tarefa, setor, chave, task):
    tabela = 'rawdata_analise_monitoramento'
    schema = 'lw_octadesk'
    engine = get_sqlalchemy_engine()
    connection = engine.connect()

    # Credenciais do Gemini lidas do config.ini (ou GEMINI_API_KEY no ambiente)
    api_key, model = _carregar_config_gemini()

    # INICIALIZAÇÃO DO CLIENTE GEMINI
    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:
        print(f"Erro ao inicializar o cliente Gemini: {e}")
        return f"ERRO: Falha ao inicializar o cliente Gemini. Erro: {e}"


    # ----------------------------------------------------------------------
    # Limita o tamanho do dataset de entrada para 100.000 caracteres
    # ----------------------------------------------------------------------
    MAX_CHARS = 100000 
    dataset_bruto_str = str(dataset)
    
    if len(dataset_bruto_str) > MAX_CHARS:
        print(f"ATENÇÃO: Dataset truncado de {len(dataset_bruto_str)} para {MAX_CHARS} caracteres.")
        dataset_bruto_str = dataset_bruto_str[:MAX_CHARS] + '\n... (dataset truncado)'
    
    dataset_limpo = re.sub(r'\\n|\n', ' ', dataset_bruto_str)
    # ----------------------------------------------------------------------
    
    # PROMPT ATUALIZADO COM A INSTRUÇÃO "Traga apenas o numero de 3 protocolos..."
    prompt_estrutura = dedent('''
        Analisar cuidadosamente dataset fornecido:
        <dataset>
            {dataset}
        </dataset>
        
        Com base no dataset fornecido, que contém dados de atendimento ao cliente da minha empresa de hospedagem de sites, e-mails e outros serviços, analise os dados e responda às seguintes solicitações. Cada atendimento possui um número de protocolo único e o prefixo indica se a mensagem foi enviada por [c = cliente] ou [a = analista]. A chave 'mensagem' contém as mensagens trocadas pelo cliente e pelo analista.

        #Instruções de Formatação
        A resposta deve seguir exatamente as seguintes formatações:

        #Considere o parâmetro de Títulos obrigatório para formatação de títulos.

        1. *Títulos*: Formate os títulos em negrito, utilizando *apenas um asterisco* (exemplo: *Título*). Não utilize asteriscos duplos (Exemplo: '**').
        2. Números e Percentuais: Destaque os valores numéricos e percentuais com a formatação * ao redor do número (exemplo: *123*).
        
        #Solicitações
        1. Um título denominado *Análise de motivos de contato*. Certifique-se de formatar este título exatamente conforme as instruções, não utilize o caractere '#' para o titulo, utilizando a mesma formatação de números já definida. 
        2. Liste os 3 principais motivos de contato identificados nos protocolos existentes no dataset e utilize a mesma formatação de *Títulos* já definida. Para cada motivo:
            - Destaque os motivos utilizando a formatação de negrito já definida.
            - Informe seu percentual em relação ao total de protocolos distintos, seguindo a formatação de números especificada.
            - Justifique o motivo da classificação de cada motivo.
            - Traga apenas o numero de 3 protocolos analisados em cada motivo para exemplo de conferencia.
        3. Informe o número total de protocolos distintos que foram analisados, formatando o valor conforme as instruções.
        ''')

    # CORREÇÃO DO KEYERROR: Usamos replace para injetar o dataset
    prompt_final_com_dataset = prompt_estrutura.replace('{dataset}', dataset_limpo)
    prompt_mensagem = prompt_final_com_dataset


    resposta_conteudo = ""
    token_prompt = 0
    token_completion = 0
    request_id = 'N/A'
    input_text = prompt_mensagem 
    current_time = datetime.now()

    for i in range(5):
        try:
            print(f"Tentativa {i+1} de 5...")
            
            # CHAMADA À API DO GEMINI
            response = client.models.generate_content(
                model=model,
                contents=prompt_mensagem,
                config=genai.types.GenerateContentConfig(
                    # Continua 4096 (limite máximo para SAÍDA)
                    max_output_tokens=4096 
                )
            )

            # Verificação de conteúdo e motivo de bloqueio
            if not response.text:
                finish_reason = None
                if response.candidates and response.candidates[0].finish_reason:
                    finish_reason = response.candidates[0].finish_reason.name
                
                print(f"Tentativa {i+1} falhou: Resposta vazia. Motivo de finalização: {finish_reason}")
                
                if finish_reason == 'SAFETY' or finish_reason == 'MAX_TOKENS':
                    print(f"Motivo de falha: {finish_reason}. Aumentando o tempo de espera...")
                
                # TEMPO DE ESPERA AUMENTADO PARA 20 SEGUNDOS NA FALHA
                time.sleep(20 * (i + 1)) 
                continue 


            # Processamento da resposta (Só executa se response.text não for vazio)
            resposta_conteudo = response.text
            
            # Trata a ausência do atributo 'name' ou de 'candidates'
            request_id = 'N/A'
            if response.candidates and hasattr(response.candidates[0], 'name'):
                request_id = response.candidates[0].name
            elif response.candidates:
                request_id = f"candidate_index_{response.candidates[0].index}"

            current_time = datetime.now()
            
            # USO DE TOKENS (usage_metadata)
            if response.usage_metadata:
                token_prompt = response.usage_metadata.prompt_token_count
                token_completion = response.usage_metadata.candidates_token_count
            
            # Cria um log JSON simplificado para persistência
            resposta_json_log = {
                'model': model,
                'request_id': request_id,
                'prompt_tokens': token_prompt,
                'completion_tokens': token_completion,
                'response_text_snippet': resposta_conteudo[:200] + '...'
            }
            resposta_json_str = json.dumps(resposta_json_log)

            # Tempo de espera de 10 segundos no sucesso
            time.sleep(10)

            # Exportar a resposta para um arquivo md
            with open(resposta_path, 'w', encoding='utf-8') as arquivo:
                arquivo.write(resposta_conteudo)

            # Salvar a resposta no banco de dados usando pandas
            df = pd.DataFrame({
                'request': [current_time],
                'chave': [chave],
                'tarefa':[task],
                'dados_de':[data_inicial],
                'dados_ate': [data_fim],
                'analise': [tarefa],
                'setor':[setor],
                'input_text':[input_text],
                'request_id':[request_id],
                'resposta_json':[resposta_json_str],
                'resposta_text': [resposta_conteudo],
                'token_prompt': [token_prompt],
                'token_completion': [token_completion],
                'model': [model],
                'created_at': [current_time],
                'updated_at': [current_time]
                }
            )
            
            df.to_sql(tabela, con=engine, if_exists='replace', index=False, schema= schema)

            print(f"Resposta salva em '{resposta_path.name}' e no banco de dados.")
            
            # Lê o script SQL do arquivo
            with open(rf'{sql_path}\insereDadosAnaliseIA.sql', 'r', encoding='utf-8') as file:
                sql_script = text(file.read())

            # Executando o script SQL
            connection.execute(sql_script)
            connection.commit()

            connection.close()
            engine.dispose()
            break # SAI DO LOOP APÓS O SUCESSO

        # TRATAMENTO DE ERROS
        except APIError as e:
            if "RESOURCE_EXHAUSTED" in str(e): 
                print("Quota excedida ou limite de taxa atingido. Aguardando para tentar novamente...")
                time.sleep(20) # AUMENTADO para 20 segundos
            else:
                print(f"Erro da API do Gemini: {e}")
                break
        except Exception as e:
            # Erro genérico
            print(f"Erro inesperado durante a chamada ou processamento: {e}")
            time.sleep(20) # AUMENTADO para 20 segundos
            continue 

    # Garante o retorno de uma string em caso de falha total do loop
    if not resposta_conteudo:
        try:
            connection.close()
            engine.dispose()
        except:
            pass
        return "ERRO: O serviço de IA falhou após 5 tentativas. O campo 'content' está vazio."
        
    return resposta_conteudo