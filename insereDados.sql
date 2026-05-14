
INSERT INTO lw_octadesk.monitoramento_contatos
    (data_processamento,
    dados_inicio,
    hora_inicio,
    data_fim,
    hora_fim,
    dia_util,
    media_comparativa,
    quantidade_atendimentos,
    percentual,
    notificou,
    chave_analise_ia,
    data_insercao,
    data_modificacao)
SELECT
    "data"::TIMESTAMP,
    data_inicio::DATE,
    hora_inicio::TIME,
    data_fim::DATE,
    hora_fim::TIME, 
    dia_util::BOOLEAN,
    media_comparativa::FLOAT,
    atendimentos::INTEGER,
    percentual::FLOAT,
    notificou::BOOLEAN,
    chave_analise::VARCHAR,
    NOW() AS data_insercao,
    NOW() AS data_modificacao
FROM lw_octadesk.rawdata_monitoramento