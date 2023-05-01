FROM navikt/java:17

COPY build/libs/*.jar ./
COPY config.json /