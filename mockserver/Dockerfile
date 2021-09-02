FROM navikt/python:3.9

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py .

CMD [".local/bin/flask", "run"]