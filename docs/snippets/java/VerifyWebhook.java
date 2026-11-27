// Verify a DekernAI webhook delivery. Run: java VerifyWebhook.java ../webhook-vectors.txt
// docs:start
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
// docs:end
import java.nio.file.Files;
import java.nio.file.Path;

public class VerifyWebhook {
    // docs:start
    /** True if the DekernAI-Signature header matches the raw body and is within the time window. */
    public static boolean verifyWebhook(String secret, String header, byte[] body, long now, long tolerance)
            throws Exception {
        Long timestamp = null;
        List<String> signatures = new ArrayList<>();
        for (String part : header.split(",", -1)) {
            int i = part.indexOf('=');
            if (i < 0) return false;
            String key = part.substring(0, i).trim();
            String value = part.substring(i + 1).trim();
            if (key.equals("t")) {
                if (timestamp != null || !value.matches("[0-9]+")) return false;
                timestamp = Long.parseLong(value);
            } else if (key.equals("v1")) {
                signatures.add(value);
            }
        }
        if (timestamp == null || signatures.isEmpty()) return false;
        if (Math.abs(now - timestamp) > tolerance) return false;
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        mac.update((timestamp + ".").getBytes(StandardCharsets.UTF_8));
        byte[] expected = HexFormat.of().formatHex(mac.doFinal(body)).getBytes(StandardCharsets.UTF_8);
        for (String s : signatures) {
            if (MessageDigest.isEqual(expected, s.getBytes(StandardCharsets.UTF_8))) return true;
        }
        return false;
    }
    // docs:end

    public static void main(String[] args) throws Exception {
        int failures = 0;
        for (String line : Files.readAllLines(Path.of(args[0]), StandardCharsets.UTF_8)) {
            if (line.isEmpty() || line.startsWith("#")) continue;
            String[] f = line.split("\\|", 6);
            byte[] body = f[5].getBytes(StandardCharsets.UTF_8);
            if (verifyWebhook(f[2], f[4], body, Long.parseLong(f[3]), 300) != f[1].equals("ok")) {
                System.out.println("FAIL " + f[0] + ": expected " + f[1]);
                failures++;
            }
        }
        System.out.println(failures == 0 ? "java: all vectors pass" : "java: " + failures + " vector(s) failed");
        System.exit(failures == 0 ? 0 : 1);
    }
}
