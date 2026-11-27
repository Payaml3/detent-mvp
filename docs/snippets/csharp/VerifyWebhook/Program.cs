// Run the signature vectors: dotnet run --project VerifyWebhook -- ../webhook-vectors.txt
using System.Text;

var failures = 0;
foreach (var line in File.ReadAllLines(args[0], Encoding.UTF8))
{
    if (line.Length == 0 || line.StartsWith('#')) continue;
    var f = line.Split('|', 6);
    if (Webhooks.VerifyWebhook(f[2], f[4], Encoding.UTF8.GetBytes(f[5]), long.Parse(f[3])) != (f[1] == "ok"))
    {
        Console.WriteLine($"FAIL {f[0]}: expected {f[1]}");
        failures++;
    }
}
Console.WriteLine(failures == 0 ? "csharp: all vectors pass" : $"csharp: {failures} vector(s) failed");
return failures == 0 ? 0 : 1;
