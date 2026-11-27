// Create the quickstart payout. Run from a folder that holds payout.json: dotnet run --project CreatePayout
// docs:start
using System.Net.Http.Headers;

using var http = new HttpClient();
var request = new HttpRequestMessage(HttpMethod.Post, Environment.GetEnvironmentVariable("DEKERNAI_BASE_URL") + "/v1/payment_intents")
{
    Content = new StringContent(File.ReadAllText("payout.json"), new MediaTypeHeaderValue("application/json")),
};
request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", Environment.GetEnvironmentVariable("DEKERNAI_API_KEY"));
request.Headers.Add("Idempotency-Key", Guid.NewGuid().ToString());
var response = await http.SendAsync(request);
var body = await response.Content.ReadAsStringAsync();
if (!response.IsSuccessStatusCode) throw new Exception($"{(int)response.StatusCode}: {body}");
Console.WriteLine(body); // the payment intent, as JSON
// docs:end
