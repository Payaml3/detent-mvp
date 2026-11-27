<?php
// Create the quickstart payout. Run from a folder that holds payout.json: php create_payout.php
// docs:start
$context = stream_context_create(['http' => [
    'method' => 'POST',
    'header' => implode("\r\n", [
        'Authorization: Bearer ' . getenv('DEKERNAI_API_KEY'),
        'Idempotency-Key: ' . bin2hex(random_bytes(16)),
        'Content-Type: application/json',
    ]),
    'content' => file_get_contents('payout.json'),
    'ignore_errors' => true,
]]);
$body = file_get_contents(getenv('DEKERNAI_BASE_URL') . '/v1/payment_intents', false, $context);
$status = (int) explode(' ', $http_response_header[0])[1];
if ($status >= 300) {
    throw new RuntimeException("$status: $body");
}
$payment = json_decode($body, true);
echo $payment['id'] . ' ' . $payment['status'] . "\n";
// docs:end
