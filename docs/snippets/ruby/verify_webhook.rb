# Verify a DekernAI webhook delivery. Run: ruby verify_webhook.rb ../webhook-vectors.txt

# docs:start
require "openssl"

# True if the DekernAI-Signature header matches the raw body and is within the time window.
def verify_webhook(secret, header, body, now: Time.now.to_i, tolerance: 300)
  timestamp = nil
  signatures = []
  header.split(",", -1).each do |part|
    return false unless part.include?("=")

    key, value = part.split("=", 2).map(&:strip)
    if key == "t"
      return false if timestamp || !value.match?(/\A[0-9]+\z/)

      timestamp = value.to_i
    elsif key == "v1"
      signatures << value
    end
  end
  return false if timestamp.nil? || signatures.empty?
  return false if (now - timestamp).abs > tolerance

  expected = OpenSSL::HMAC.hexdigest("SHA256", secret, "#{timestamp}.#{body}")
  signatures.any? { |s| OpenSSL.secure_compare(expected, s) }
end
# docs:end

if $PROGRAM_NAME == __FILE__
  failures = 0
  File.readlines(ARGV[0], chomp: true, encoding: "UTF-8").each do |line|
    next if line.empty? || line.start_with?("#")

    name, expect, secret, now, header, body = line.split("|", 6)
    next if verify_webhook(secret, header, body, now: now.to_i) == (expect == "ok")

    puts "FAIL #{name}: expected #{expect}"
    failures += 1
  end
  puts failures.zero? ? "ruby: all vectors pass" : "ruby: #{failures} vector(s) failed"
  exit(failures.zero? ? 0 : 1)
end
