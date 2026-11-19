// SPDX-License-Identifier: MIT
// Dependency-free synthetic smoke suite. No private game resources or live iPhone.
using Game2Mobile.Operator.Core;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

int tests = 0;
void Check(bool condition, string name)
{
    tests++;
    if (!condition) throw new Exception("Smoke assertion failed: " + name);
}

string id = new('a', 32), commit = new('b', 40);
string Job(string state = "running", string action = "all", string stage = "preflight",
    string steps = "{}", bool built = false, bool verified = false) => $$"""
    {"schema":"game2mobile.m1-job-status.v2","job_id":"{{id}}","source_commit":"{{commit}}",
    "profile":"metal4","action":"{{action}}","state":"{{state}}","result":"{{(state == "running" ? "incomplete" : state)}}",
    "current_stage":{{(stage == "" ? "null" : "\"" + stage + "\"")}},"steps":{{steps}},
    "updated_utc":"2026-11-16T02:00:00Z","full_game_app_built":{{built.ToString().ToLowerInvariant()}},
    "app_signed_locally":{{built.ToString().ToLowerInvariant()}},"end_to_end_build_stages_verified":{{verified.ToString().ToLowerInvariant()}}}
    """;

byte[] UTF(string s) => Encoding.UTF8.GetBytes(s);
Inspection passed = M1SnapshotInspector.InspectBytes(UTF(Job("passed", "all", "",
    "{\"preflight\":\"passed\",\"prepare\":\"passed\",\"headers\":\"passed\",\"verify\":\"passed\",\"build\":\"passed\"}", true, true)));
Check(passed.Code == "M1_STAGES_PASSED" && passed.Passed, "full staged job validated");
Check(M1SnapshotInspector.InspectBytes(UTF(Job())).Code == "M1_JOB_RUNNING", "in-progress valid but unverified");
Check(M1SnapshotInspector.InspectBytes(UTF(Job("partial", "preflight", "", "{\"preflight\":\"passed\"}"))).Code == "M1_JOB_PARTIAL", "partial not success");
Check(M1SnapshotInspector.InspectBytes(UTF(Job("failed", "all", "build", "{\"build\":\"failed\"}"))).Code == "M1_JOB_FAILED", "failure preserved");
Check(M1SnapshotInspector.InspectBytes(UTF(Job("cancelled", "all", "build", "{\"build\":\"failed\"}"))).Code == "M1_JOB_CANCELLED", "cancellation preserved");
Check(M1SnapshotInspector.InspectBytes(UTF(Job("passed", "all", "", "{}", true, true))).Code == "M1_STATUS_INVALID", "empty forged passed refused");
Check(M1SnapshotInspector.InspectBytes(UTF(Job("passed", "all", "", "{}", false, true))).Code == "M1_STATUS_INVALID", "inconsistent signature flags refused");
Check(M1SnapshotInspector.InspectBytes(UTF(Job().Replace("\"state\":\"running\"", "\"state\":\"passed\",\"state\":\"running\""))).Code == "M1_STATUS_INVALID", "duplicate key refused");
Check(M1SnapshotInspector.InspectBytes(UTF(Job().Replace("2026-11-16T02:00:00Z", "2026-15-16T02:00:00Z"))).Code == "M1_STATUS_INVALID", "bad calendar refused");

string Event(int seq, string stage, string status, string run = "") =>
    $"G2M_BOOT {{\"schema\":1,\"run_id\":\"{(run == "" ? id : run)}\",\"seq\":{seq},\"elapsed_ms\":{seq},\"stage\":\"{stage}\",\"status\":\"{status}\",\"code\":\"\"}}";
string work = Path.Combine(Path.GetTempPath(), "g2m-win-smoke-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(work);
try
{
    string log = Path.Combine(work, "boot.log");
    File.WriteAllText(log, string.Join("\n", new[] { Event(1,"host_start","begin"), Event(2,"host_start","ok"),
        Event(3,"guest_entry","begin"), Event(4,"gpu_submit","ok"), Event(5,"first_present","ok") }));
    var boot = BootLogInspector.Inspect(log);
    Check(boot.Code == "FIRST_PRESENT_OBSERVED" && boot.RunId == id, "real startup dependency chain");
    Check(boot.Lines.All(x => !x.Contains("private_secret", StringComparison.Ordinal)), "no arbitrary raw log");
    File.WriteAllText(log, Event(1,"host_start","begin") + "\n" + Event(2,"first_present","ok"));
    Check(BootLogInspector.Inspect(log).Code == "BOOT_EVIDENCE_INVALID", "no fake first present");
    File.WriteAllText(log, Event(1,"host_start","begin") + "\n" + Event(2,"host_start","ok") + "\n" + Event(3,"guest_entry","ok") + "\n" + Event(4,"gpu_submit","ok") + "\n" + Event(5,"first_present","ok") + "\n" + Event(6,"module_load","error"));
    Check(BootLogInspector.Inspect(log).Code == "RUNTIME_ERROR", "later error overrides frame");
    File.WriteAllText(log, Event(1,"host_start","begin") + "\n" + Event(2,"host_start","ok") + "\n" + Event(3,"guest_entry","ok") + "\n" + Event(4,"gpu_submit","ok") + "\n" + Event(5,"first_present","ok") + "\n" + Event(1,"host_start","begin", new string('c',32)));
    Check(BootLogInspector.Inspect(log).Code == "STARTUP_INCOMPLETE", "newest run not old frame");
    File.WriteAllText(log, string.Join("\n", new[] { Event(1,"host_start","begin"), Event(2,"host_start","ok"),
        Event(3,"guest_entry","ok"), Event(4,"gpu_submit","ok"), Event(5,"first_present","ok"),
        Event(1,"gpu_submit","ok", new string('d',32)) }));
    Check(BootLogInspector.Inspect(log).Code == "BOOT_EVIDENCE_INVALID", "new run missing host_start cannot borrow older rendered frame");
    string completeChain = string.Join("\n", new[] { Event(1,"host_start","begin"), Event(2,"host_start","ok"),
        Event(3,"guest_entry","ok"), Event(4,"gpu_submit","ok"), Event(5,"first_present","ok") });
    foreach (string torn in new[] { "G2M_", "G2M_BOOT", "G2M_BOOT{" })
    {
        File.WriteAllText(log, completeChain + "\n" + torn);
        Check(BootLogInspector.Inspect(log).Code == "BOOT_EVIDENCE_INVALID",
              "unterminated protocol prefix cannot borrow previous first present: " + torn);
    }
    File.WriteAllText(log, completeChain + "\nordinary non-protocol output");
    Check(BootLogInspector.Inspect(log).Code == "FIRST_PRESENT_OBSERVED",
          "non-protocol tail does not invalidate valid boot evidence");
    File.WriteAllText(log, "G2M_BO");
    Check(BootLogInspector.Inspect(log).Code == "BOOT_EVIDENCE_INVALID",
          "truncated prefix without preceding run is invalid");
    File.WriteAllText(log, "DONE\n");
    Check(BootLogInspector.Inspect(log).Code == "NO_BOOT_EVIDENCE", "legacy done isn't proof");
    File.WriteAllText(log, Event(1,"host_start","begin") + "\n" + Event(2,"host_start","ok").Replace("\"code\":\"\"", "\"code\":\"\",\"code\":\"\""));
    Check(BootLogInspector.Inspect(log).Code == "BOOT_EVIDENCE_INVALID", "duplicate event key refused");

    string zipPath = Path.Combine(work, "summary.zip");
    string summary = "{\"schema\":\"game2mobile.diagnostic-bundle.v1\",\"scope\":\"local-unattested-summary\",\"playability\":\"unverified\",\"contains_raw_logs\":false,\"contains_game_files\":false}";
    byte[] raw = UTF(summary);
    string hash = Convert.ToHexString(SHA256.HashData(raw)).ToLowerInvariant();
    string manifest = $"{{\"schema\":\"game2mobile.diagnostic-bundle.v1\",\"files\":{{\"summary.json\":{{\"size\":{raw.Length},\"sha256\":\"{hash}\"}}}}}}";
    void MakeZip(string meta, bool duplicate = false)
    {
        using var fs = new FileStream(zipPath, FileMode.Create, FileAccess.Write, FileShare.None);
        using var archive = new ZipArchive(fs, ZipArchiveMode.Create);
        var first = archive.CreateEntry("manifest.json"); using (var w = new StreamWriter(first.Open())) w.Write(meta);
        var second = archive.CreateEntry("summary.json"); using (var w = new StreamWriter(second.Open())) w.Write(summary);
        if (duplicate) { var third=archive.CreateEntry("summary.json"); using var w=new StreamWriter(third.Open()); w.Write(summary); }
    }
    MakeZip(manifest);
    Check(DiagnosticBundleInspector.Inspect(zipPath).Code == "DIAGNOSTIC_INTEGRITY_CHECKED", "actual summary ZIP manifest hash");
    MakeZip(manifest.Replace(hash, new string('a',64)));
    Check(DiagnosticBundleInspector.Inspect(zipPath).Code == "DIAGNOSTIC_INTEGRITY_INVALID", "tampered bundle denied");
    MakeZip(manifest, duplicate: true);
    Check(DiagnosticBundleInspector.Inspect(zipPath).Code == "DIAGNOSTIC_INTEGRITY_INVALID", "duplicate ZIP members denied");
    Check(WindowsCapability.Check().Code == "WINDOWS_READ_ONLY", "no Windows-local iOS build claim");
    Check(WindowsCapability.Check().Lines.Any(x => x.Contains("Apple Silicon")), "Mac requirement transparent");
    string symlink = Path.Combine(work, "linked.json");
    string normal = Path.Combine(work, "job.json");
    File.WriteAllText(normal, Job());
    try
    {
        File.CreateSymbolicLink(symlink, normal);
        Check(M1SnapshotInspector.Inspect(symlink).Code == "M1_STATUS_INVALID", "symlink input denied");
        Check(BootLogInspector.Inspect(symlink).Code == "BOOT_INPUT_INVALID", "symlink log denied without exception");
    }
    catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or PlatformNotSupportedException)
    { Console.WriteLine("Symlink creation not permitted; rejection test skipped by host policy."); }
    Check(M1SnapshotInspector.Inspect(normal).Code == "M1_JOB_RUNNING", "selected normal local file read");
}
finally
{
    try { Directory.Delete(work, recursive: true); } catch { /* Unprivileged test cleanup only */ }
}
Console.WriteLine($"PASS: {tests} synthetic, game-free Windows Operator core checks");
