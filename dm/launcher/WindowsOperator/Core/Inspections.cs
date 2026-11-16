// SPDX-License-Identifier: MIT
// Offline Windows-side inspection of owner-selected Game2Mobile engineering evidence.
// This is NOT the native Apple M1 executor or proof of an actual game/device run.
using System.Globalization;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Game2Mobile.Operator.Core;

public sealed record Inspection(string Code, bool Passed, IReadOnlyList<string> Lines, string? RunId = null)
{
    public static Inspection Invalid(string code = "LOCAL_EVIDENCE_INVALID") => new(code, false,
        ["无法核验所选本机文件。不会显示原始内容或私有路径。", "游戏可玩性：未验证"]);
}

public static class SafeLocalFile
{
    public const int MaxJobBytes = 32 * 1024;
    public const int MaxBundleBytes = 256 * 1024;
    public const int MaxBootBytes = 16 * 1024 * 1024;

    public static string LocalPath(string path, bool mustExist)
    {
        if (string.IsNullOrWhiteSpace(path) || path.StartsWith(@"\\", StringComparison.Ordinal) ||
            path.StartsWith("//", StringComparison.Ordinal) || !Path.IsPathFullyQualified(path))
            throw new InvalidDataException("Only explicitly selected local absolute files are supported");
        string full = Path.GetFullPath(path);
        var parent = new DirectoryInfo(Path.GetDirectoryName(full) ?? throw new InvalidDataException());
        // Do not follow symlinked/junction parent directories (including a network redirection).
        for (DirectoryInfo? d = parent; d is not null; d = d.Parent)
            if (d.Exists && (d.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("Reparse-point input is unsupported");
        if (mustExist)
        {
            var info = new FileInfo(full);
            info.Refresh();
            if (!info.Exists || (info.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("Not a regular local file");
        }
        return full;
    }

    public static byte[] Read(string path, int maximum)
    {
        string full = LocalPath(path, true);
        using var stream = new FileStream(full, FileMode.Open, FileAccess.Read, FileShare.Read,
                                          16 * 1024, FileOptions.SequentialScan);
        if (stream.Length > maximum || stream.Length < 0) throw new InvalidDataException("Input is too large");
        // Validate the same file handle's actual size, not only FileInfo's possibly stale metadata.
        using var buffer = new MemoryStream();
        byte[] chunk = new byte[8192];
        int count;
        while ((count = stream.Read(chunk, 0, chunk.Length)) > 0)
        {
            if (buffer.Length + count > maximum) throw new InvalidDataException("Input exceeded limit");
            buffer.Write(chunk, 0, count);
        }
        return buffer.ToArray();
    }
}

public static class StrictJson
{
    public static JsonDocument Parse(byte[] bytes)
    {
        var doc = JsonDocument.Parse(bytes, new JsonDocumentOptions { MaxDepth = 20,
            AllowTrailingCommas = false, CommentHandling = JsonCommentHandling.Disallow });
        try { CheckKeys(doc.RootElement); return doc; }
        catch { doc.Dispose(); throw; }
    }

    private static void CheckKeys(JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var field in element.EnumerateObject())
            {
                if (!names.Add(field.Name)) throw new InvalidDataException("Duplicate JSON field");
                CheckKeys(field.Value);
            }
        }
        else if (element.ValueKind == JsonValueKind.Array)
            foreach (var item in element.EnumerateArray()) CheckKeys(item);
    }

    public static JsonElement Required(JsonElement item, string property)
    {
        if (item.ValueKind != JsonValueKind.Object || !item.TryGetProperty(property, out var value))
            throw new InvalidDataException("Missing protocol field");
        return value;
    }
    public static string String(JsonElement item, string property)
    {
        var value = Required(item, property);
        return value.ValueKind == JsonValueKind.String ? value.GetString()! :
            throw new InvalidDataException("Invalid protocol string");
    }
    public static bool Boolean(JsonElement item, string property)
    {
        var value = Required(item, property);
        return value.ValueKind == JsonValueKind.True ? true :
               value.ValueKind == JsonValueKind.False ? false :
               throw new InvalidDataException("Invalid protocol bool");
    }
    public static bool IsHex(string value, int count) => value.Length == count &&
        value.All(x => (x >= '0' && x <= '9') || (x >= 'a' && x <= 'f'));
}

public static class M1SnapshotInspector
{
    private static readonly HashSet<string> Stages = ["preflight", "prepare", "headers", "verify", "build"];
    private static readonly HashSet<string> ErrorStages = ["source", "environment", "arguments"];
    private static readonly HashSet<string> States = ["running", "failed", "cancelled", "partial", "passed"];
    private static readonly HashSet<string> Results = ["incomplete", "failed", "cancelled", "partial", "passed"];

    public static Inspection Inspect(string path)
    {
        try { return InspectBytes(SafeLocalFile.Read(path, SafeLocalFile.MaxJobBytes)); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException or JsonException or InvalidOperationException or InvalidDataException)
        { return Inspection.Invalid("M1_STATUS_INVALID"); }
    }

    public static Inspection InspectBytes(byte[] bytes)
    {
        try
        {
            using var doc = StrictJson.Parse(bytes);
            var job = doc.RootElement;
            string schema = StrictJson.String(job, "schema");
            if (schema is not ("game2mobile.m1-job-status.v1" or "game2mobile.m1-job-status.v2"))
                throw new InvalidDataException();
            string id = StrictJson.String(job, "job_id"), commit = StrictJson.String(job, "source_commit");
            if (!StrictJson.IsHex(id, 32) || !StrictJson.IsHex(commit, 40)) throw new InvalidDataException();
            string profile = StrictJson.String(job, "profile"), action = StrictJson.String(job, "action");
            if (profile is not ("metal4" or "m3") || (action != "all" && !Stages.Contains(action)))
                throw new InvalidDataException();
            string state = StrictJson.String(job, "state"), result = StrictJson.String(job, "result");
            if (!States.Contains(state) || !Results.Contains(result) ||
                (state == "running" ? result != "incomplete" : state != result)) throw new InvalidDataException();
            JsonElement active = StrictJson.Required(job, "current_stage");
            string? stage = active.ValueKind switch { JsonValueKind.Null => null,
                JsonValueKind.String => active.GetString(), _ => throw new InvalidDataException() };
            if (stage is not null && !Stages.Contains(stage) && !ErrorStages.Contains(stage))
                throw new InvalidDataException();
            if ((state is "passed" or "partial") && stage is not null) throw new InvalidDataException();
            if ((state == "passed" && action != "all") || (state == "partial" && action == "all"))
                throw new InvalidDataException();
            var stepsValue = StrictJson.Required(job, "steps");
            if (stepsValue.ValueKind != JsonValueKind.Object) throw new InvalidDataException();
            var steps = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var step in stepsValue.EnumerateObject())
            {
                if ((!Stages.Contains(step.Name) && !ErrorStages.Contains(step.Name)) ||
                    step.Value.ValueKind != JsonValueKind.String ||
                    step.Value.GetString() is not ("passed" or "failed")) throw new InvalidDataException();
                steps.Add(step.Name, step.Value.GetString()!);
            }
            if (steps.Count > 8 || (state is "failed" or "cancelled" && !steps.Values.Contains("failed")))
                throw new InvalidDataException();
            if (state == "passed" && (steps.Count != 5 || Stages.Any(s => !steps.TryGetValue(s, out var value) || value != "passed")))
                throw new InvalidDataException();
            if (state == "partial" && (steps.Count != 1 || !steps.TryGetValue(action, out var value) || value != "passed"))
                throw new InvalidDataException();
            if (state == "running" && steps.Values.Any(v => v != "passed")) throw new InvalidDataException();
            if (action != "all" && steps.Keys.Any(k => k != action && !ErrorStages.Contains(k)))
                throw new InvalidDataException();
            bool built = StrictJson.Boolean(job, "full_game_app_built");
            bool signed = StrictJson.Boolean(job, "app_signed_locally");
            bool verified = StrictJson.Boolean(job, "end_to_end_build_stages_verified");
            if (built != signed || verified != (state == "passed") ||
                (built && (!steps.TryGetValue("build", out var b) || b != "passed")) ||
                (state == "passed" && !built)) throw new InvalidDataException();
            string updated = StrictJson.String(job, "updated_utc");
            if (!DateTime.TryParseExact(updated, "yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture,
                DateTimeStyles.AssumeUniversal | DateTimeStyles.AdjustToUniversal, out _))
                throw new InvalidDataException();
            var text = new List<string> { "M1 阶段记录：结构有效（不证明运行来源真实）",
                $"配置：{profile}", $"申请阶段：{action}", $"记录状态：{state}",
                $"记录步骤：{steps.Count}/5", "进程是否仍在运行：未检查", "设备画面、音频、输入和存档：未验证" };
            if (stage is not null) text.Insert(4, $"当前阶段：{stage}");
            string code = state switch { "passed" => "M1_STAGES_PASSED", "partial" => "M1_JOB_PARTIAL",
                "running" => "M1_JOB_RUNNING", "cancelled" => "M1_JOB_CANCELLED", _ => "M1_JOB_FAILED" };
            return new Inspection(code, state == "passed", text, id);
        }
        catch (Exception ex) when (ex is InvalidDataException or JsonException or InvalidOperationException or ArgumentException or OverflowException)
        { return Inspection.Invalid("M1_STATUS_INVALID"); }
    }
}

public static class DiagnosticBundleInspector
{
    public static Inspection Inspect(string path)
    {
        try
        {
            var contents = SafeLocalFile.Read(path, SafeLocalFile.MaxBundleBytes);
            using var input = new MemoryStream(contents, writable: false);
            using var archive = new ZipArchive(input, ZipArchiveMode.Read, leaveOpen: false);
            if (archive.Entries.Count != 2 ||
                archive.Entries.Count(x => x.FullName == "summary.json") != 1 ||
                archive.Entries.Count(x => x.FullName == "manifest.json") != 1)
                throw new InvalidDataException();
            static byte[] ReadEntry(ZipArchiveEntry entry)
            {
                if (entry.Length < 1 || entry.Length > 128 * 1024) throw new InvalidDataException();
                using var output = new MemoryStream();
                using var source = entry.Open();
                byte[] buffer = new byte[4096]; int length;
                while ((length = source.Read(buffer, 0, buffer.Length)) > 0)
                {
                    if (output.Length + length > 128 * 1024) throw new InvalidDataException();
                    output.Write(buffer, 0, length);
                }
                return output.ToArray();
            }
            byte[] manifestBytes = ReadEntry(archive.GetEntry("manifest.json")!);
            byte[] summaryBytes = ReadEntry(archive.GetEntry("summary.json")!);
            using var manifest = StrictJson.Parse(manifestBytes);
            using var summary = StrictJson.Parse(summaryBytes);
            const string schema = "game2mobile.diagnostic-bundle.v1";
            if (StrictJson.String(manifest.RootElement, "schema") != schema ||
                StrictJson.String(summary.RootElement, "schema") != schema ||
                StrictJson.String(summary.RootElement, "scope") != "local-unattested-summary" ||
                StrictJson.String(summary.RootElement, "playability") != "unverified" ||
                StrictJson.Boolean(summary.RootElement, "contains_raw_logs") ||
                StrictJson.Boolean(summary.RootElement, "contains_game_files")) throw new InvalidDataException();
            var files = StrictJson.Required(manifest.RootElement, "files");
            if (files.ValueKind != JsonValueKind.Object || files.EnumerateObject().Count() != 1)
                throw new InvalidDataException();
            var proof = StrictJson.Required(files, "summary.json");
            var size = StrictJson.Required(proof, "size");
            if (!size.TryGetInt32(out int expectedSize) || expectedSize != summaryBytes.Length)
                throw new InvalidDataException();
            string hash = StrictJson.String(proof, "sha256");
            if (!StrictJson.IsHex(hash, 64) || !string.Equals(hash,
                  Convert.ToHexString(SHA256.HashData(summaryBytes)).ToLowerInvariant(), StringComparison.Ordinal))
                throw new InvalidDataException();
            return new Inspection("DIAGNOSTIC_INTEGRITY_CHECKED", true,
                ["本地诊断摘要包：目录、大小和 SHA-256 一致", "只读取 manifest.json 与 summary.json；未提取文件",
                 "档案完整性不等于来源真实性，也不证明设备启动或游戏可玩", "原始日志和商业游戏资源：未包含在该格式中"]);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException or JsonException or InvalidDataException or InvalidOperationException or NotSupportedException)
        { return Inspection.Invalid("DIAGNOSTIC_INTEGRITY_INVALID"); }
    }
}

public static class WindowsCapability
{
    public static Inspection Check() => new("WINDOWS_READ_ONLY", true,
        ["Windows 工程操作器：本机离线查看与核对摘要",
         "支持：启动日志、M1 状态快照、诊断摘要 ZIP 完整性检查、脱敏记录导出",
         "不支持：Windows 本机编译、签名或安装 iOS 游戏 App",
         "完整构建必须在拥有合法游戏文件的 Apple Silicon Mac 上执行",
         "程序不连接 Mac、不上传资源、不调用远程构建或外部服务器"]);
}
