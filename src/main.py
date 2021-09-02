import io
import sys
from io import StringIO, BytesIO

import asyncio
import requests
import os
import csv
import logging
from pythonjsonlogger import jsonlogger
import paramiko

logger = logging.getLogger("app")
logger.setLevel(logging.DEBUG)
logHandler = logging.StreamHandler(sys.stdout)
logHandler.setFormatter(jsonlogger.JsonFormatter())
logger.addHandler(logHandler)


def print_hei(name):
    logger.info(f'Hei, {name}')


async def hent_access_token():
    token_url = os.getenv("AZURE_OPENID_CONFIG_TOKEN_ENDPOINT")
    client_id = os.getenv("AZURE_APP_CLIENT_ID")
    client_secret = os.getenv("AZURE_APP_CLIENT_SECRET")
    scope = os.getenv("SPORBAR_CLIENT_ID")

    response = requests.post(
        token_url,
        data={
            "client_id": client_id,
            "scope": scope,
            "grant_type": "client_credentials",
            "client_secret": client_secret,
        },
        headers={
            "Accept": "application/json"
        }
    ).json()

    return response["access_token"]


async def hent_vedtaksperioder(access_token: str, fødselsnumre: list[str]) -> list[dict]:
    response = requests.post(
        "http://sporbar.tbd.svc.nais.local/api/v1/vedtak",
        json=fødselsnumre,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
    ).json()

    return response


def result_file_name(file_name: str):
    return file_name


def hent_fødselsnumre_fra_filslusa(host: str, brukernavn: str) -> dict[str, list[str]]:
    client = paramiko.SSHClient()
    client.load_host_keys("/known_hosts")
    client.connect(host, username=brukernavn, pkey=paramiko.ed25519key.Ed25519Key(filename="/id_ed25519"))
    sftp_client = client.open_sftp()

    inbound = sftp_client.listdir(path="inbound")
    outbound = sftp_client.listdir(path="outbound")
    files = [file for file in inbound if result_file_name(file) not in outbound]

    forespørsler = {}

    for file in files:
        fødselsnumre = []
        with BytesIO() as csvfile:
            logger.info(f"Leser inputfil {file}")
            sftp_client.getfo(f"inbound/{file}", csvfile)
            csvfile.seek(0)
            csv_reader = csv.reader(io.TextIOWrapper(csvfile))
            for row in csv_reader:
                fødselsnumre.append(row[0])
        forespørsler[file] = fødselsnumre

    client.close()

    return forespørsler


def skriv_resultat_til_filslusa(host: str, brukernavn: str, file: str, output: str):
    client = paramiko.SSHClient()
    client.load_host_keys("/known_hosts")
    client.connect(host, username=brukernavn, pkey=paramiko.ed25519key.Ed25519Key(filename="/id_ed25519"))
    sftp_client = client.open_sftp()

    sftp_client.putfo(BytesIO(output.encode("UTF-8")), f"outbound/{result_file_name(file)}")

    client.close()


def map_vedtaksperiode_resultat(input: list[dict]):
    with StringIO() as csv_out:
        writer = csv.writer(csv_out)

        writer.writerow(["fødselsnummer", "fom", "tom", "grad"])
        for vedtak in input:
            writer.writerow([vedtak["fødselsnummer"], vedtak["fom"], vedtak["tom"], vedtak["grad"]])
        return csv_out.getvalue()


async def håndter_forespørsler_fra_filslusa(host: str, brukernavn: str):
    inbound = hent_fødselsnumre_fra_filslusa(host, brukernavn)
    access_token = await hent_access_token()
    for file, fødselsnumre in inbound.items():
        vedtaksperioder = await hent_vedtaksperioder(access_token, fødselsnumre)
        skriv_resultat_til_filslusa(host, brukernavn, file, map_vedtaksperiode_resultat(vedtaksperioder))


if __name__ == '__main__':
    print_hei('Hege')
    host = "sftp.nav.no"
    asyncio.run(håndter_forespørsler_fra_filslusa(host, "denvercoder9"))

