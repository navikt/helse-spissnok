import datetime
import sys

from flask import Flask, jsonify, request
from datetime import date, timedelta

app = Flask("mockserver")
app.config['JSON_AS_ASCII'] = False


@app.route("/token", methods=["POST"])
def fetch_token():
    return {"access_token": "SUPDOGE"}


@app.route("/utbetalinger", methods=["POST"])
def hent_vedtak():
    json = request.get_json()
    result = []
    print(json, file=sys.stderr)
    for fødselsnummer in json:
        result.append({
            "fødselsnummer": fødselsnummer,
            "fom": (date.today() - timedelta(days=14)).isoformat(),
            "tom": date.today().isoformat(),
            "grad": 69
        })
    print(result, file=sys.stderr)
    return jsonify(result)


