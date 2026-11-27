// Create the quickstart payout. Run from a folder that holds payout.json: java CreatePayout.java
// docs:start
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Path;
import java.util.UUID;

public class CreatePayout {
    static final HttpClient HTTP = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1).build();

    public static void main(String[] args) throws Exception {
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(System.getenv("DEKERNAI_BASE_URL") + "/v1/payment_intents"))
                .header("Authorization", "Bearer " + System.getenv("DEKERNAI_API_KEY"))
                .header("Idempotency-Key", UUID.randomUUID().toString())
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofFile(Path.of("payout.json")))
                .build();
        HttpResponse<String> response = HTTP.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() >= 300) throw new RuntimeException(response.statusCode() + ": " + response.body());
        System.out.println(response.body()); // the payment intent, as JSON
    }
}
// docs:end
