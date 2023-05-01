package no.nav.helse.spissnok

import com.fasterxml.jackson.databind.DeserializationFeature
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule
import com.fasterxml.jackson.module.kotlin.jacksonObjectMapper
import com.fasterxml.jackson.module.kotlin.readValue
import net.logstash.logback.argument.StructuredArguments.keyValue
import net.schmizz.sshj.SSHClient
import net.schmizz.sshj.sftp.OpenMode
import net.schmizz.sshj.sftp.SFTPClient
import net.schmizz.sshj.transport.verification.OpenSSHKnownHosts
import no.nav.helse.rapids_rivers.*
import no.nav.helse.spissnok.UtbetalingDTO.Companion.tilCsv
import org.intellij.lang.annotations.Language
import java.io.*
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.time.Duration
import java.time.LocalDate
import java.time.LocalDateTime

private val mapper = jacksonObjectMapper()
    .registerModule(JavaTimeModule())
    .disable(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES)

fun main() {
    val env = System.getenv()

    val config = mapper.readTree(File("/config.json")).map { it.path("bruker").asText() }
    val sftpHost = env.getValue("SFTP_HOST")
    val spokelseUrl = env.getValue("SPOKELSE_URL")
    val tokenUrl = env.getValue("AZURE_OPENID_CONFIG_TOKEN_ENDPOINT")
    val clientId = env.getValue("AZURE_APP_CLIENT_ID")
    val scope = env.getValue("SPORBAR_CLIENT_ID")
    val clientSecret = env.getValue("AZURE_APP_CLIENT_SECRET")

    val spissnok = Spissnok(config, sftpHost, spokelseUrl, tokenUrl, clientId, scope, clientSecret)

    if (env["KJOR_SOM_JOBB"]?.equals("true", true) == true) return spissnok.kjør()

    App(env, spissnok).run()
}

private class App(env: Map<String, String>, spissnok: Spissnok) : RapidsConnection.StatusListener {
    private val rapidsConnection = RapidApplication.create(env)

    init {
        rapidsConnection
            .apply { SpissnokRiver(this, spissnok) }
            .register(this)
    }

    fun run() {
        rapidsConnection.start()
    }

    private class SpissnokRiver(rapidsConnection: RapidsConnection, private val spissnok: Spissnok) : River.PacketListener {
        private val logg = Logg.ny(this::class)
        init {
            River(rapidsConnection)
                .validate {
                    if (System.getenv("NAIS_CLUSTER_NAME") == "dev-gcp") {
                        it.demandValue("@event_name", "halv_time")
                    } else {
                        it.demandValue("@event_name", "hel_time")
                        it.requireValue("time", "14")
                    }
                }.register(this)
        }

        override fun onPacket(packet: JsonMessage, context: MessageContext) {
            try {
                spissnok.kjør()
            } catch (err: Exception) {
                logg.error("Alvorlig feil under kjøring av spissnok: ${err.message}", err)
            }
        }
    }
}

private class Spissnok(
    private val config: List<String>,
    private val sftpHost: String,
    private val spokelseUrl: String,
    private val tokenUrl: String,
    private val clientId: String,
    private val scope: String,
    private val clientSecret: String
) {
    private val logger = Logg.ny(this::class)

    fun kjør() {
        config.forEach { username ->
            val inbound = hentFødselsnumreFraFilslusa(sftpHost, username)
            val accessToken = accessToken(
                tokenUrl = tokenUrl,
                clientId = clientId,
                scope = scope,
                clientSecret = clientSecret
            ) ?: return@forEach

            inbound.forEach { (fil, fnumre) ->
                logger.info("Håndterer fil $fil")
                val utbetalinger = hentVedtaksperioder(spokelseUrl, accessToken, fnumre) ?: return@forEach
                skrivResultatTilFilslusa(sftpHost, username, fil, utbetalinger.tilCsv(logger))
            }
        }
    }

    private fun accessToken(tokenUrl: String, clientId: String, scope: String, clientSecret: String): String? {
        @Language("JSON")
        val payload = """{
            "client_id": "$clientId",
            "scope": "$scope",
            "grant_type": "client_credentials",
            "client_secret": "$clientSecret"
        }"""
        return httpPost(tokenUrl, payload)?.let {
            mapper.readTree(it).path("access_token").asText()
        }
    }

    private fun hentVedtaksperioder(spokelseUrl: String, accessToken: String, fnumre: List<String>): List<UtbetalingDTO>? {
        logger.info("henter utbetalinger fra $spokelseUrl")
        val payload = mapper.writeValueAsString(fnumre)
        return httpPost("$spokelseUrl/utbetalinger", payload, mapOf(
            "Accept" to "application/json",
            "Authorization" to "Bearer $accessToken"
        ))?.let {
            mapper.readValue<List<UtbetalingDTO>>(it)
        }
    }

    private fun httpPost(url: String, data: String, headers: Map<String, String> = emptyMap()): String? {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.requestMethod = "POST"
        conn.doOutput = true
        conn.setRequestProperty("Content-Type", "application/json")
        conn.setRequestProperty("Content-Length", "${data.length}")
        headers.forEach { (key, value) -> conn.setRequestProperty(key, value) }
        conn.useCaches = false
        conn.connectTimeout = Duration.ofSeconds(1).toMillis().toInt()
        conn.readTimeout = Duration.ofSeconds(5).toMillis().toInt()

        DataOutputStream(conn.outputStream).use { it.writeBytes(data) }

        val readStream = { cis: InputStream -> cis.bufferedReader().use { it.readText() } }

        val responseCode = conn.responseCode
        if (responseCode !in 200..299) {
            logger
                .offentligError("kunne ikke hente access token, response code=$responseCode")
                .privatError("kunne ikke hente access token, response code=$responseCode:\n${readStream(conn.errorStream)}")
            return null
        }
        return readStream(conn.inputStream)
    }

    private fun skrivResultatTilFilslusa(host: String, username: String, fil: String, innhold: String) {
        sftClient(host, username).use { sftpClient ->
            logger.info("Skriver $fil til slusa")
            sftpClient.open("outbound/$fil", setOf(OpenMode.WRITE, OpenMode.CREAT, OpenMode.TRUNC)).use { fo ->
                fo.RemoteFileOutputStream().bufferedWriter().use { writer ->
                    writer.write(innhold)
                }
            }
            val expectedSha256 = innhold.sha256()
            sftpClient.open("outbound/$fil.sha256", setOf(OpenMode.WRITE, OpenMode.CREAT, OpenMode.TRUNC)).use { fo ->
                fo.RemoteFileOutputStream().bufferedWriter().use { writer ->
                    writer.write(expectedSha256)
                }
            }

            logger.info("Verifiserer at hash til utgående melding er lik den originale hashen")
            sftpClient.open("outbound/$fil").use { fo ->
                val actualSha256 = fo.RemoteFileInputStream().bufferedReader().use { it.readText() }.sha256()
                if (actualSha256 == expectedSha256) {
                    logger.info("Hashen til utgående melding er lik original, sletter inbound/$fil")
                    sftpClient.rm("inbound/$fil")
                } else {
                    logger.error("Hashen for utgående melding er ulik den originale hashen⁉, original=$expectedSha256 remote=$actualSha256")
                }
            }
        }
    }

    private fun String.sha256(): String {
        val md = MessageDigest.getInstance("SHA-256")
        return md.digest(toByteArray()).joinToString(separator = "") { "%02x".format(it) }
    }

    private fun sftClient(host: String, username: String): SFTPClient {
        logger.info("kobler til $host")
        val client = SSHClient()
        client.addHostKeyVerifier(OpenSSHKnownHosts(File("/var/run/ssh-keys/known_hosts")))
        client.connect(host)
        client.authPublickey(username, "/var/run/ssh-keys/id_ed25519")
        return client.newSFTPClient()
    }

    private fun hentFødselsnumreFraFilslusa(host: String, username: String): Map<String, List<String>> {
        val sftpClient = sftClient(host, username)
        val inbound = sftpClient.ls("inbound").map { it.name }
        logger.info("${inbound.size} inbound fil(er)")
        val outbound = sftpClient.ls("outbound").map { it.name }
        logger.info("${inbound.size} outbound fil(er)")

        return inbound
            .filterNot { it in outbound }
            .also { filer -> logger.info("behandler ${filer.size} fil(er)") }
            .associateWith { fil ->
                logger.info("Leser inputfil $fil")
                val fo = sftpClient.open("inbound/$fil")
                fo.RemoteFileInputStream().use { fis ->
                    fis.bufferedReader().use { reader ->
                        // skip header line
                        reader.readLine()
                        reader.readLines().map {
                            it.split(",")[0].also { fnr ->
                                logger.privatInfo("Henter informasjon for {}", keyValue("fødselsnummer", fnr))
                            }
                        }
                    }
                }
            }
    }
}

private data class UtbetalingDTO(
    val fødselsnummer: String,
    val fom: LocalDate?,
    val tom: LocalDate?,
    val grad: Double,
    val gjenståendeSykedager: Int?,
    val utbetaltTidspunkt: LocalDateTime?,
    val refusjonstype: Refusjonstype?
) {
    companion object {
        fun List<UtbetalingDTO>.tilCsv(logg: Logg): String {
            val header = "fødselsnummer,fom,tom,grad\n"
            return header + joinToString(separator = "\n") {
                logg.privatInfo("sender vedtak for {}, fom=${it.fom}, tom=${it.tom}", keyValue("fødselsnummer", it.fødselsnummer))
                "${it.fødselsnummer},${it.fom},${it.tom},${it.grad}"
            }
        }
    }
}
enum class Refusjonstype {
    REFUSJON_TIL_ARBEIDSGIVER,
    REFUSJON_TIL_PERSON;
}