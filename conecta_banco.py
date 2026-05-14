#conecta_banco.py

import configparser
import os
from pathlib import Path

import psycopg2
import pyodbc
from sqlalchemy import create_engine


def resolver_caminho_config():
    """Procura o config.ini: variavel de ambiente CAMINHO_ARQUIVO_CONFIGURACAO ou caminhos relativos ao script."""
    caminho_env = (os.environ.get("CAMINHO_ARQUIVO_CONFIGURACAO") or "").strip()
    if caminho_env and os.path.isfile(caminho_env):
        return caminho_env
    pasta_script = Path(__file__).resolve().parent
    for rel in ("../config.ini", "../../config.ini", "../../../config.ini", "./config.ini"):
        candidato = (pasta_script / rel).resolve()
        if candidato.is_file():
            return str(candidato)
    raise FileNotFoundError(
        "config.ini nao encontrado. Defina CAMINHO_ARQUIVO_CONFIGURACAO ou "
        "coloque o arquivo em uma pasta ancestral do script."
    )


def _carregar_config_db():
    """Le a secao [database] do config.ini e devolve um dicionario com as credenciais."""
    parser = configparser.ConfigParser()
    parser.read(resolver_caminho_config(), encoding="utf-8")
    if "database" not in parser:
        raise KeyError("Secao [database] ausente no config.ini")
    secao = parser["database"]
    return {
        "server": secao.get("server", "").strip(),
        "port": secao.get("port", "5432").strip(),
        "database": secao.get("database", "").strip(),
        "uid": secao.get("uid", "").strip(),
        "pwd": secao.get("pwd", "").strip(),
    }


_cfg_cache = None


def _get_cfg():
    """Le e cacheia a secao [database]. Primeira chamada le do config.ini; demais devolvem do cache."""
    global _cfg_cache
    if _cfg_cache is None:
        _cfg_cache = _carregar_config_db()
    return _cfg_cache


def get_sqlalchemy_engine():
    # Conexao com PostgreSQL usando SQLAlchemy
    c = _get_cfg()
    return create_engine(f"postgresql://{c['uid']}:{c['pwd']}@{c['server']}:{c['port']}/{c['database']}")


def get_pyodbc_connection():
    # Conexao com PostgreSQL usando pyodbc
    c = _get_cfg()
    driver = '{PostgreSQL Unicode(x64)}'
    conn_string = (
        f"DRIVER={driver};SERVER={c['server']};PORT={c['port']};"
        f"DATABASE={c['database']};UID={c['uid']};PWD={c['pwd']}"
    )
    return pyodbc.connect(conn_string)


def get_psycopg2_connection():
    # Conexao com PostgreSQL usando psycopg2
    c = _get_cfg()
    return psycopg2.connect(
        dbname=c["database"],
        user=c["uid"],
        password=c["pwd"],
        host=c["server"],
        port=c["port"],
    )
