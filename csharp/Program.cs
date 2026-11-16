// Mini-Task API — version C# / ASP.NET Core Minimal API (Kestrel, .NET 8), port 8083.
using System.Text.Encodings.Web;
using System.Text.Json;

const int MaxN = 40;

var builder = WebApplication.CreateBuilder(args);
builder.Logging.ClearProviders();
builder.WebHost.UseUrls("http://127.0.0.1:8083");
builder.Services.ConfigureHttpJsonOptions(o =>
{
    o.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.CamelCase;
    o.SerializerOptions.Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping; // UTF-8 non échappé
});

var app = builder.Build();

// --- Données en mémoire (instantané immuable, remplacé à chaque POST) ----------
var json = new JsonSerializerOptions(JsonSerializerDefaults.Web);
var initial = JsonSerializer.Deserialize<List<TaskItem>>(
    File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "tasks.json")), json)!;
var state = new State(initial.ToArray(), initial.ToDictionary(t => t.Id));
var writeLock = new object();
var StrictUtf8 = new System.Text.UTF8Encoding(false, true);

IResult NotFound() => Results.Json(new ErrorBody("not found"), statusCode: 404);
IResult BadPayload() => Results.Json(new ErrorBody("invalid payload"), statusCode: 400);

static long Fib(int n) => n < 2 ? n : Fib(n - 1) + Fib(n - 2);

static bool AllDigits(string s) => s.Length is >= 1 and <= 18 && s.All(c => c is >= '0' and <= '9');

// --- Routes ---------------------------------------------------------------------
app.MapGet("/health", () => Results.Json(new { status = "ok" }));

app.MapGet("/tasks", () => Results.Json(Volatile.Read(ref state).List));

app.MapGet("/tasks/{id}", (string id) =>
{
    if (AllDigits(id) && Volatile.Read(ref state).ById.TryGetValue(int.TryParse(id, out var i) ? i : -1, out var task))
        return Results.Json(task);
    return NotFound();
});

app.MapPost("/tasks", async (HttpRequest request) =>
{
    JsonElement root;
    try
    {
        using var ms = new MemoryStream();
        await request.Body.CopyToAsync(ms);
        var text = StrictUtf8.GetString(ms.ToArray()); // refuse l'UTF-8 invalide
        using var doc = JsonDocument.Parse(text);
        root = doc.RootElement.Clone();
    }
    catch (Exception e) when (e is JsonException or ArgumentException) { return BadPayload(); }

    if (root.ValueKind != JsonValueKind.Object) return BadPayload();

    if (!root.TryGetProperty("title", out var titleEl) || titleEl.ValueKind != JsonValueKind.String) return BadPayload();
    var title = titleEl.GetString();
    if (string.IsNullOrEmpty(title)) return BadPayload();

    if (!root.TryGetProperty("priority", out var prioEl) || prioEl.ValueKind != JsonValueKind.Number
        || !prioEl.TryGetInt32(out var priority) || priority < 1 || priority > 5) return BadPayload();

    var done = false;
    if (root.TryGetProperty("done", out var doneEl))
    {
        if (doneEl.ValueKind is not (JsonValueKind.True or JsonValueKind.False)) return BadPayload();
        done = doneEl.GetBoolean();
    }

    lock (writeLock)
    {
        var current = state;
        var task = new TaskItem(current.List.Length + 1, title!, done, priority);
        var list = new TaskItem[current.List.Length + 1];
        current.List.CopyTo(list, 0);
        list[^1] = task;
        var map = new Dictionary<int, TaskItem>(current.ById) { [task.Id] = task };
        Volatile.Write(ref state, new State(list, map));
        return Results.Json(task, statusCode: 201);
    }
});

app.MapGet("/compute", (HttpRequest request) =>
{
    var raw = request.Query["n"].ToString();
    if (!request.Query.ContainsKey("n") || !AllDigits(raw) || !int.TryParse(raw, out var n) || n > MaxN)
        return Results.Json(new ErrorBody("invalid n"), statusCode: 400);
    return Results.Json(new { n, result = Fib(n) });
});

// Toute route ou méthode inconnue -> 404 au format du contrat.
app.MapFallback(() => NotFound());

app.Run();

record TaskItem(int Id, string Title, bool Done, int Priority);
record ErrorBody(string Error);
record State(TaskItem[] List, Dictionary<int, TaskItem> ById);
