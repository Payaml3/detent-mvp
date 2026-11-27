// Verify a DekernAI webhook delivery (WHK-02). The runner is Program.cs.
// docs:start
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;

public static class Webhooks
{
    /// <summary>True if the DekernAI-Signature header matches the raw body and is within the time window.</summary>
    public static bool VerifyWebhook(string secret, string header, byte[] body, long now, long tolerance = 300)
    {
        long? timestamp = null;
        var signatures = new List<string>();
        foreach (var part in header.Split(','))
        {
            var i = part.IndexOf('=');
            if (i < 0) return false;
            var key = part[..i].Trim();
            var value = part[(i + 1)..].Trim();
            if (key == "t")
            {
                if (timestamp != null || !Regex.IsMatch(value, "^[0-9]+$")) return false;
                timestamp = long.Parse(value);
            }
            else if (key == "v1")
            {
                signatures.Add(value);
            }
        }
        if (timestamp == null || signatures.Count == 0) return false;
        if (Math.Abs(now - timestamp.Value) > tolerance) return false;
        using var hmac = new HMACSHA256(Encoding.UTF8.GetBytes(secret));
        var signed = Encoding.UTF8.GetBytes($"{timestamp}.").Concat(body).ToArray();
        var expected = Encoding.UTF8.GetBytes(Convert.ToHexString(hmac.ComputeHash(signed)).ToLowerInvariant());
        return signatures.Any(s => CryptographicOperations.FixedTimeEquals(expected, Encoding.UTF8.GetBytes(s)));
    }
}
// docs:end
