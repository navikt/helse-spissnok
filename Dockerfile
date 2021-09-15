FROM navikt/python:3.9

COPY requirements.txt .
USER root
RUN groupadd --system --gid 1069 apprunner2
RUN useradd --system --home-dir "/home/apprunner2" --uid 1069 --gid apprunner2 apprunner2
RUN mkdir -p "/home/apprunner2"
RUN chown 1069:1069 /home/apprunner2
USER apprunner2
RUN ls -lah /home/apprunner2
RUN pip install --user -r requirements.txt

COPY src/ .
COPY config.json /