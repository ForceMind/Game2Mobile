// SPDX-License-Identifier: MIT
using System.Text;
using System.Text.Json;

namespace Game2Mobile.Operator.Core;

public static class BootLogInspector
{
    private const string Prefix = "G2M_BOOT ";
    private static readonly HashSet<string> Stages = ["host_start", "module_load", "relocation", "sdk_init",
        "module_init", "guest_entry", "gpu_submit", "first_present", "host_return"];
    private static readonly HashSet<string> Statuses = ["begin", "ok", "error"];

    private sealed class Run
    {
        public int LastSeq;
        public double LastElapsed;
        public int Events;
        public bool Started;
        public bool InitialBegin;
        public bool GuestEntry;
        public bool GpuSubmit;
        public bool FirstPresent;
        public bool Returned;
        public bool Fault;
        public bool Invalid;
        public string LastStage = "host_start";
    }

    public static Inspection Inspect(string path)
    {
        try
        {
            byte[] bytes = SafeLocalFile.Read(path, SafeLocalFile.MaxBootBytes);
            // UTF-8 must be valid: never reinterpret arbitrary private bytes as a successful event.
            string text = new UTF8Encoding(false, true).GetString(bytes);
            var runs = new Dictionary<string, Run>(StringComparer.Ordinal);
            string? latest = null;
            string? latestStart = null;
            int allEvents = 0;
            bool invalidProtocol = false;
            foreach (string line in text.Split('\n'))
            {
                var trimmed = line.EndsWith('\r') ? line[..^1] : line;
                if (!trimmed.StartsWith(Prefix, StringComparison.Ordinal)) continue;
                if (trimmed.Length > 16 * 1024 || allEvents >= 100_000)
                { invalidProtocol = true; break; }
                allEvents++;
                string data = trimmed[Prefix.Length..];
                try
                {
                    using var doc = StrictJson.Parse(Encoding.UTF8.GetBytes(data));
                    var v = doc.RootElement;
                    if (StrictJson.Required(v, "schema").GetInt32() != 1) throw new InvalidDataException();
                    string id = StrictJson.String(v, "run_id"), stage = StrictJson.String(v, "stage"),
                        status = StrictJson.String(v, "status"), code = StrictJson.String(v, "code");
                    if (!StrictJson.IsHex(id, 32) || !Stages.Contains(stage) || !Statuses.Contains(status) ||
                        code.Length > 63 || code.Any(c => !(c is >= 'a' and <= 'z' ||
                                                             c is >= '0' and <= '9' || c == '_')))
                        throw new InvalidDataException();
                    if (v.TryGetProperty("module", out var module) &&
                        (module.ValueKind != JsonValueKind.String || module.GetString() is not string m ||
                         m.Length is < 1 or > 15 || m.Any(ch => !char.IsAsciiLetterOrDigit(ch) && ch != '_')))
                        throw new InvalidDataException();
                    if (!StrictJson.Required(v, "seq").TryGetInt32(out int seq) || seq < 1)
                        throw new InvalidDataException();
                    if (!StrictJson.Required(v, "elapsed_ms").TryGetDouble(out double elapsed) ||
                        !double.IsFinite(elapsed) || elapsed < 0) throw new InvalidDataException();
                    if (!runs.TryGetValue(id, out var run))
                    {
                        if (runs.Count >= 1024) { invalidProtocol = true; break; }
                        run = new Run(); runs.Add(id, run);
                    }
                    if (seq != run.LastSeq + 1 || elapsed < run.LastElapsed ||
                        (run.Events == 0 && !(stage == "host_start" && status == "begin" && seq == 1)))
                        run.Invalid = true;
                    run.LastSeq = Math.Max(run.LastSeq, seq);
                    run.LastElapsed = Math.Max(run.LastElapsed, elapsed);
                    run.Events++;
                    run.LastStage = stage;
                    run.Fault |= status == "error";
                    if (stage == "host_start" && status == "begin")
                    {
                        if (run.InitialBegin || run.Started) run.Invalid = true;
                        run.InitialBegin = true;
                        if (seq == 1) latestStart = id;
                    }
                    if (stage == "host_start" && status == "ok")
                    {
                        if (run.Started) run.Invalid = true;
                        run.Started = true;
                    }
                    if (stage == "guest_entry" && status is "begin" or "ok") run.GuestEntry = true;
                    if (stage == "gpu_submit" && status == "ok")
                    {
                        if (run.GpuSubmit) run.Invalid = true;
                        run.GpuSubmit = true;
                    }
                    if (stage == "first_present" && status == "ok")
                    {
                        if (run.FirstPresent) run.Invalid = true;
                        run.FirstPresent = true;
                    }
                    if (stage == "host_return") run.Returned = true;
                    latest = id;
                }
                catch (Exception ex) when (ex is JsonException or InvalidDataException or InvalidOperationException or FormatException or OverflowException)
                { invalidProtocol = true; }
            }
            if (invalidProtocol) return Inspection.Invalid("BOOT_EVIDENCE_INVALID");
            string? selectedId = latestStart ?? latest;
            if (selectedId is null) return new Inspection("NO_BOOT_EVIDENCE", false,
                ["未发现合法 G2M_BOOT 事件", "旧式 DONE 行不能证明运行或画面", "游戏可玩性：未验证"]);
            var selected = runs[selectedId];
            if (selected.Invalid || (selected.GpuSubmit && !selected.GuestEntry) ||
                (selected.GuestEntry && !selected.Started) ||
                (selected.FirstPresent && !(selected.Started && selected.GuestEntry && selected.GpuSubmit)))
                return Inspection.Invalid("BOOT_EVIDENCE_INVALID");
            string result = selected.Fault ? "RUNTIME_ERROR" : selected.FirstPresent ?
                "FIRST_PRESENT_OBSERVED" : selected.Returned ? "HOST_RETURNED_EARLY" : "STARTUP_INCOMPLETE";
            return new Inspection(result, result == "FIRST_PRESENT_OBSERVED",
                ["启动日志：只读同次运行汇总", $"事件数：{selected.Events}", $"最近阶段：{selected.LastStage}",
                 $"宿主启动：{(selected.Started ? "已观察" : "尚无证据")}",
                 $"GPU 提交：{(selected.GpuSubmit ? "已观察" : "尚无证据")}",
                 $"首帧呈现回调：{(selected.FirstPresent ? "已观察" : "尚无证据")}",
                 "显示回调并不能证明像素正确、游戏可玩或真机执行", "正式判定请使用 macOS 主仓库启动诊断与设备验收工具"], selectedId);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or ArgumentException or DecoderFallbackException or InvalidOperationException or InvalidDataException)
        { return Inspection.Invalid("BOOT_INPUT_INVALID"); }
    }
}
