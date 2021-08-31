import requests
import os
import csv
import paramiko


def print_hei(name):
    print(f'Hei, {name}')


async def hent_access_token():
    token_url = os.getenv("AZURE_OPENID_CONFIG_TOKEN_ENDPOINT")
    client_id = os.getenv("AZURE_APP_CLIENT_ID")
    client_secret = os.getenv("AZURE_APP_CLIENT_SECRET")
    scope = os.getenv("SPORBAR_CLIENT_ID")

    response = await requests.post(
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


async def hent_vedtaksperioder(access_token: str, fødselsnumre: list[str]):
    response = await requests.post(
        "http://sporbar.tbd.svc.nais.local/api/v1/vedtak",
        json=fødselsnumre,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {access_token}"
        }
    ).json()

    return response


def hent_fødselsnumre_fra_fil(path):
    fødselsnumre = []
    with open(path, "r") as csvfile:
        csv_reader = csv.reader(csvfile)
        for row in csv_reader:
            fødselsnumre += row
    return fødselsnumre


def hent_fødselsnumre_fra_filslusa(host: str, path: str):
    fødselsnumre = []

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.connect(host)
    sftp_client = client.open_sftp()

    files = sftp_client.listdir(path=path)

    for file in files:
        with open(file, "r") as csvfile:
            csv_reader = csv.reader(csvfile)
            for row in csv_reader:
                fødselsnumre += row

    return fødselsnumre


if __name__ == '__main__':
    print_hei('Hege')
    print(hent_fødselsnumre_fra_fil("test.csv"))
