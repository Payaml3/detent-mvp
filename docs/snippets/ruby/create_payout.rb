# Create the quickstart payout. Run from a folder that holds payout.json: ruby create_payout.rb
# docs:start
require "json"
require "net/http"
require "securerandom"

uri = URI("#{ENV.fetch('DEKERNAI_BASE_URL')}/v1/payment_intents")
request = Net::HTTP::Post.new(uri)
request["Authorization"] = "Bearer #{ENV.fetch('DEKERNAI_API_KEY')}"
request["Idempotency-Key"] = SecureRandom.uuid
request["Content-Type"] = "application/json"
request.body = File.read("payout.json")
response = Net::HTTP.start(uri.hostname, uri.port, use_ssl: uri.scheme == "https") { |http| http.request(request) }
raise "#{response.code}: #{response.body}" unless response.is_a?(Net::HTTPSuccess)

payment = JSON.parse(response.body)
puts "#{payment['id']} #{payment['status']}"
# docs:end
