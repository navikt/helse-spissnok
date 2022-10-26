# Spissnok

![Bygg og deploy](https://github.com/navikt/helse-spissnok/workflows/master/badge.svg)

Svarer på forespørsler om vedtak via filsluse

Det var en gang en spissnok som ikke hadde spist nok, så møtte den en spissnok som hadde spist nok, da hjalp spissnoken som hadde spist nok den andre spissnoken så den fikk spist nok.

# Bruk
1. Rydd opp i filer med `./prepare_slusing.sh`
2. Bygg docker-compose oppsettet med `docker-compose build`
3. Start opp docker-compose med `docker-compose up`
4. Når jobben er ferdig kan du avsluttet docker-compose med ctrl+c

Eventuelt:
```bash
./prepare_slusing.sh; docker-compose build; docker-compose up
```
som en kommando

## Bug:
Det kan godt være at noen av mappene `prepare_slusing.sh` jobber med lastes ned som filer, ikke mapper, pga. git og gøy og galskap. Slett de filene, og lag mapper i stedet.

## Bug2:
Det ser ikke ut som om all testdataen er lagt inn i git

## Hvordan fungerer det?
`./prepare_slusing.sh` rydder opp i outbound-mapper og kopierer inputfil inn i `testresources/inbound`

docker-compose setter opp:
* en sftp server med alle inputfiler fra `testresources/inbound`
* en mock som returnerer samme data som spokelse ville gjort
* en instanse av spissnok som peker mot sftp serveren og spokelse-mocken

## Ellers da?

Filmottak slik vi gjør det i NAV er dokumentert på confluence: https://confluence.adeo.no/display/linuxdrift/Ekstern+filsluse



# Henvendelser

Spørsmål knyttet til koden eller prosjektet kan stilles som issues her på GitHub.

## For NAV-ansatte

Interne henvendelser kan sendes via Slack i kanalen #område-helse.
