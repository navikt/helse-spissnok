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
from logging.handlers import RotatingFileHandler
from pythonjsonlogger import jsonlogger
import paramiko
from datetime import datetime


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    def add_fields(self, log_record, record, message_dict):
        super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)
        log_record['level'] = record.levelname.capitalize()
        log_record['@timestamp'] = datetime.now().isoformat()


logger = logging.getLogger("app")
logger.setLevel(logging.DEBUG)
logHandler = logging.StreamHandler(sys.stdout)
logHandler.setFormatter(CustomJsonFormatter(json_ensure_ascii=False))
logger.addHandler(logHandler)

sikker_logg = logging.getLogger("sikker_logg")
sikker_logg.setLevel(logging.INFO)
sikker_logg_handler = RotatingFileHandler("/secure-logs/secure.log", maxBytes=69000000, backupCount=5)
sikker_logg_handler.setFormatter(CustomJsonFormatter(json_ensure_ascii=False))
sikker_logg.addHandler(sikker_logg_handler)

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


async def hent_vedtaksperioder(access_token: str, f??dselsnumre: list[str]) -> list[dict]:
    response = requests.post(
        "http://spokelse.tbd.svc.nais.local/utbetalinger",
        json=f??dselsnumre,
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


def utg??ende_fil(filnavn: str):
    return filnavn


def hent_f??dselsnumre_fra_filslusa(host: str, brukernavn: str) -> dict[str, list[str]]:
    client = paramiko.SSHClient()
    client.load_host_keys(known_hosts)
    client.connect(host, username=brukernavn, pkey=paramiko.ed25519key.Ed25519Key(filename=ssh_key))
    sftp_client = client.open_sftp()

    inbound = sftp_client.listdir(path="inbound")
    outbound = sftp_client.listdir(path="outbound")
    filer = [fil for fil in inbound if utg??ende_fil(fil) not in outbound]

    foresp??rsler = {}

    for fil in filer:
        f??dselsnumre = []
        with BytesIO() as csvfil:
            logger.info(f"Leser inputfil {fil}")
            sftp_client.getfo(f"inbound/{fil}", csvfil)
            csvfil.seek(0)
            csv_reader = csv.reader(io.TextIOWrapper(csvfil))
            next(csv_reader)
            for rad in csv_reader:
                f??dselsnummer = rad[0]
                sikker_logg.info(f"Henter informasjon for \"{f??dselsnummer}\" "
                                 + f"hex={f??dselsnummer.encode('UTF-8').hex(':')}")
                f??dselsnumre.append(f??dselsnummer)
        foresp??rsler[fil] = f??dselsnumre

    client.close()

    return foresp??rsler


def skriv_resultat_til_filslusa(host: str, brukernavn: str, fil: str, output: str):
    client = paramiko.SSHClient()
    client.load_host_keys(known_hosts)
    client.connect(host, username=brukernavn, pkey=paramiko.ed25519key.Ed25519Key(filename=ssh_key))
    sftp_client = client.open_sftp()

    utg??ende_filnavn = utg??ende_fil(fil)

    data = output.encode("UTF-8")
    hash = sha256(data).hexdigest()

    logger.info(f"Skriver {utg??ende_filnavn} til slusa")
    sftp_client.putfo(BytesIO(hash.encode("UTF-8")), f"outbound/{utg??ende_filnavn}.sha256")
    sftp_client.putfo(BytesIO(data), f"outbound/{utg??ende_filnavn}")

    logger.info("Verifserer at hash til utg??ende melding er lik den originale hashen")
    with BytesIO() as remote_csv:
        sftp_client.getfo(f"outbound/{utg??ende_filnavn}", remote_csv)
        remote_csv.seek(0)
        remote_hash = sha256(remote_csv.read()).hexdigest()
        if remote_hash == hash:
            logger.info(f"Hashen til utg??ende melding er lik original, sletter inbound/{fil}")
            sftp_client.remove(f"inbound/{fil}")
        else:
            logger.error(f"Hashen for utg??ende melding er ulik den originale hashen???, original={hash} remote={remote_hash}")

    client.close()


def map_vedtaksperiode_resultat(input: list[dict]):
    with StringIO() as csv_out:
        writer = csv.writer(csv_out)

        writer.writerow(
            ["f??dselsnummer", "fom", "tom", "grad", "gjenst??endeSykedager", "utbetaltTidspunkt", "refusjonstype"])
        for vedtak in input:
            sikker_logg.info(f"sender vedtak for {vedtak['f??dselsnummer']}, fom={vedtak['fom']},"
                             + f" tom={vedtak['tom']}, refusjonstype={vedtak['refusjonstype']}")
            writer.writerow(
                [vedtak["f??dselsnummer"], vedtak["fom"], vedtak["tom"], vedtak["grad"], vedtak["gjenst??endeSykedager"],
                 vedtak["utbetaltTidspunkt"], vedtak["refusjonstype"]])
        return csv_out.getvalue()


async def h??ndter_foresp??rsler_fra_filslusa(host: str, brukernavn: str):
    inbound = hent_f??dselsnumre_fra_filslusa(host, brukernavn)
    access_token = await hent_access_token()
    for file, f??dselsnumre in inbound.items():
        logger.info(f"H??ndterer fil {file}")
        vedtaksperioder = await hent_vedtaksperioder(access_token, f??dselsnumre)
        skriv_resultat_til_filslusa(host, brukernavn, file, map_vedtaksperiode_resultat(vedtaksperioder))


if __name__ == '__main__':
    print_hei('Hege')
    try:
        sftp_host = os.getenv("SFTP_HOST")

        with open("/config.json") as config_json:
            jason = json.load(config_json)

        for sluse in jason:
            bruker = sluse["bruker"]
            logger.info(f"H??ndterer foresp??rsel for {bruker}")
            asyncio.run(h??ndter_foresp??rsler_fra_filslusa(sftp_host, bruker))
            logger.info(f"Fullf??rt h??ndtering av foresp??rsel for {bruker}")
    except Exception:
        logger.exception("Spissnok har ikke spist nok :(")

    logger.info("You sluse, you luse ????")
    print_ha_det("Hege")
