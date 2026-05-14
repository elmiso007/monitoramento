INSERT INTO lw_octadesk.analise_monitoramento_contatos
(chave_analise_ia, data_processamento, data_inicio, data_fim, analise, setor, input_text, request_id , resposta_json, resposta_text, token_solicitacao,	token_resposta, model, data_insercao, data_modificacao)
SELECT 
a.chave::VARCHAR,
a.request::TIMESTAMP,
a.dados_de::TIMESTAMP,
a.dados_ate::TIMESTAMP, 
a.analise::VARCHAR,
a.setor::VARCHAR,
a.input_text::TEXT,
a.request_id::VARCHAR,
a.resposta_json::JSON,
a.resposta_text::TEXT,
a.token_prompt::INTEGER,
a.token_completion::INTEGER,
a.model::VARCHAR,
now() AS data_insercao,
now() AS data_modificacao
FROM lw_octadesk.rawdata_analise_monitoramento a




