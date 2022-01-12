FROM navikt/python:3.9

COPY requirements.txt .
USER apprunner
RUN pip install --user -r requirements.txt

COPY src/ .
COPY config.json /