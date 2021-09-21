import io
import json
import sys
from io import StringIO, BytesIO

import asyncio
from hashlib import sha256
import requests
import os
import csv
import logging
from pythonjsonlogger import jsonlogger
import paramiko


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
        log_record['level'] = record.levelname.capitalize()


logger = logging.getLogger("app")
logger.setLevel(logging.DEBUG)
logHandler = logging.StreamHandler(sys.stdout)
logHandler.setFormatter(CustomJsonFormatter(json_ensure_ascii=False))
logger.addHandler(logHandler)
ssh_key = "/var/run/ssh-keys/id_ed25519"
known_hosts = "/var/run/ssh-keys/known_hosts"


def print_hei(name):
    logger.info(f'Hei, {name}')


def print_ha_det(name):
    logger.info(f'Ha det, {name}')


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
    )

    if not response.ok:
        raise Exception(f"Fikk ikke-ok HTTP-respons under henting av access_token:\n"
                        f"response_text: {response.text}\n"
                        f"status_code: {response.status_code}")

    return response.json()["access_token"]


async def hent_vedtaksperioder(access_token: str, fødselsnumre: list[str]) -> list[dict]:
    response = requests.post(
        "http://spokelse.tbd.svc.nais.local/utbetalinger",
        json=fødselsnumre,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
    )

    if not response.ok:
        raise Exception(f"Fikk ikke-ok HTTP-Respons under henting av utbetalinger:\n"
                        f"response_text: {response.text}\n"
                        f"status_code: {response.status_code}")

    return response.json()


def utgående_fil(filnavn: str):
    return filnavn


def hent_fødselsnumre_fra_filslusa(host: str, brukernavn: str) -> dict[str, list[str]]:
    client = paramiko.SSHClient()
    client.load_host_keys(known_hosts)
    client.connect(host, username=brukernavn, pkey=paramiko.ed25519key.Ed25519Key(filename=ssh_key))
    sftp_client = client.open_sftp()

    inbound = sftp_client.listdir(path="inbound")
    outbound = sftp_client.listdir(path="outbound")
    filer = [fil for fil in inbound if utgående_fil(fil) not in outbound]

    forespørsler = {}

    for fil in filer:
        fødselsnumre = []
        with BytesIO() as csvfil:
            logger.info(f"Leser inputfil {fil}")
            sftp_client.getfo(f"inbound/{fil}", csvfil)
            csvfil.seek(0)
            csv_reader = csv.reader(io.TextIOWrapper(csvfil))
            next(csv_reader)
            for rad in csv_reader:
                fødselsnumre.append(rad[0])
        forespørsler[fil] = fødselsnumre

    client.close()

    return forespørsler


def skriv_resultat_til_filslusa(host: str, brukernavn: str, fil: str, output: str):
    client = paramiko.SSHClient()
    client.load_host_keys(known_hosts)
    client.connect(host, username=brukernavn, pkey=paramiko.ed25519key.Ed25519Key(filename=ssh_key))
    sftp_client = client.open_sftp()

    utgående_filnavn = utgående_fil(fil)

    data = output.encode("UTF-8")
    hash = sha256(data).hexdigest()

    logger.info(f"Skriver {utgående_filnavn} til slusa")
    sftp_client.putfo(BytesIO(hash.encode("UTF-8")), f"outbound/{utgående_filnavn}.sha256")
    sftp_client.putfo(BytesIO(data), f"outbound/{utgående_filnavn}")

    logger.info("Verifserer at hash til utgående melding er lik den originale hashen")
    with BytesIO() as remote_csv:
        sftp_client.getfo(f"outbound/{utgående_filnavn}", remote_csv)
        remote_csv.seek(0)
        remote_hash = sha256(remote_csv.read()).hexdigest()
        if remote_hash == hash:
            logger.info(f"Hashen til utgående melding er lik original, sletter inbound/{fil}")
            sftp_client.remove(f"inbound/{fil}")
        else:
            logger.error(f"Hashen for utgående melding er ulik den originale hashen⁉, original={hash} remote={remote_hash}")

    client.close()


def map_vedtaksperiode_resultat(input: list[dict]):
    with StringIO() as csv_out:
        writer = csv.writer(csv_out)

        writer.writerow(
            ["fødselsnummer", "fom", "tom", "grad", "gjenståendeSykedager", "utbetaltTidspunkt", "refusjonstype"])
        for vedtak in input:
            writer.writerow(
                [vedtak["fødselsnummer"], vedtak["fom"], vedtak["tom"], vedtak["grad"], vedtak["gjenståendeSykedager"],
                 vedtak["utbetaltTidspunkt"], vedtak["refusjonstype"]])
        return csv_out.getvalue()


async def håndter_forespørsler_fra_filslusa(host: str, brukernavn: str):
    inbound = hent_fødselsnumre_fra_filslusa(host, brukernavn)
    access_token = await hent_access_token()
    for file, fødselsnumre in inbound.items():
        logger.info(f"Håndterer fil {file}")
        vedtaksperioder = await hent_vedtaksperioder(access_token, fødselsnumre)
        skriv_resultat_til_filslusa(host, brukernavn, file, map_vedtaksperiode_resultat(vedtaksperioder))


if __name__ == '__main__':
    print_hei('Hege')
    try:
        sftp_host = os.getenv("SFTP_HOST")

        with open("/config.json") as config_json:
            jason = json.load(config_json)

        for sluse in jason:
            bruker = sluse["bruker"]
            logger.info(f"Håndterer forespørsel for {bruker}")
            asyncio.run(håndter_forespørsler_fra_filslusa(sftp_host, bruker))
            logger.info(f"Fullført håndtering av forespørsel for {bruker}")
    except Exception:
        logger.exception("Spissnok har ikke spist nok :(")

    logger.info("You sluse, you luse 🥴")
    print_ha_det("Hege")
