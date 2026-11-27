<?php
// Verify a DekernAI webhook delivery. Run: php verify_webhook.php ../webhook-vectors.txt

// docs:start
/** True if the DekernAI-Signature header matches the raw body and is within the time window. */
function verify_webhook(string $secret, string $header, string $body, ?int $now = null, int $tolerance = 300): bool
{
    $timestamp = null;
    $signatures = [];
    foreach (explode(',', $header) as $part) {
        if (!str_contains($part, '=')) {
            return false;
        }
        [$key, $value] = array_map('trim', explode('=', $part, 2));
        if ($key === 't') {
            if ($timestamp !== null || !ctype_digit($value)) {
                return false;
            }
            $timestamp = (int) $value;
        } elseif ($key === 'v1') {
            $signatures[] = $value;
        }
    }
    if ($timestamp === null || !$signatures) {
        return false;
    }
    if (abs(($now ?? time()) - $timestamp) > $tolerance) {
        return false;
    }
    $expected = hash_hmac('sha256', $timestamp . '.' . $body, $secret);
    foreach ($signatures as $signature) {
        if (hash_equals($expected, $signature)) {
            return true;
        }
    }
    return false;
}
// docs:end

$failures = 0;
foreach (file($argv[1], FILE_IGNORE_NEW_LINES) as $line) {
    if ($line === '' || $line[0] === '#') {
        continue;
    }
    [$name, $expect, $secret, $now, $header, $body] = explode('|', $line, 6);
    if (verify_webhook($secret, $header, $body, (int) $now) !== ($expect === 'ok')) {
        echo "FAIL $name: expected $expect\n";
        $failures++;
    }
}
echo $failures ? "php: $failures vector(s) failed\n" : "php: all vectors pass\n";
exit($failures ? 1 : 0);
