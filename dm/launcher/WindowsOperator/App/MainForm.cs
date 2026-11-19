// SPDX-License-Identifier: MIT
// Windows-only offline inspection; no shell, remote Mac control, iOS build or game assets.
using System.Drawing;
using System.Text;
using System.Text.Json;
using System.Windows.Forms;
using Game2Mobile.Operator.Core;

namespace Game2Mobile.Operator.Windows;

public sealed class MainForm : Form
{
    private static readonly Color Back = Color.FromArgb(17, 19, 24);
    private static readonly Color Surface = Color.FromArgb(29, 32, 40);
    private static readonly Color TextColor = Color.FromArgb(236, 239, 245);
    private static readonly Color Muted = Color.FromArgb(152, 160, 174);
    private static readonly Color Accent = Color.FromArgb(135, 171, 255);
    private readonly FlowLayoutPanel actions = new();
    private readonly RichTextBox results = new();
    private readonly Label status = new();
    private Inspection? latest;
    private bool working;

    public MainForm()
    {
        Text = "Game2Mobile Operator · Windows";
        MinimumSize = new Size(820, 560);
        Size = new Size(1040, 730);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Back;
        ForeColor = TextColor;
        Font = new Font("Segoe UI", 11f);

        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill, Padding = new Padding(28), BackColor = Back,
            ColumnCount = 1, RowCount = 5
        };
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 68));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 86));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 125));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 46));
        Controls.Add(root);

        var title = new Label
        {
            Text = "Game2Mobile  /  Operator", Dock = DockStyle.Fill,
            Font = new Font("Segoe UI Semibold", 25f, FontStyle.Bold), ForeColor = TextColor,
            TextAlign = ContentAlignment.MiddleLeft
        };
        root.Controls.Add(title, 0, 0);

        var banner = new Label
        {
            Text = "WINDOWS · 离线工程诊断\r\n" +
                   "可检查从 Mac 带来的启动日志、M1 状态和诊断包。Windows 无法本机编译或签名 iOS 游戏。",
            Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft,
            Font = new Font("Segoe UI", 11f), ForeColor = Accent,
            BackColor = Surface, Padding = new Padding(18, 8, 12, 8)
        };
        root.Controls.Add(banner, 0, 1);

        actions.Dock = DockStyle.Fill;
        actions.FlowDirection = FlowDirection.LeftToRight;
        actions.WrapContents = true;
        actions.BackColor = Back;
        actions.Padding = new Padding(0, 12, 0, 4);
        root.Controls.Add(actions, 0, 2);
        AddAction("选择启动日志", () => SelectAndInspect("启动日志 | *.txt;*.log|*.txt;*.log|所有文件 | *.*|*.*", BootLogInspector.Inspect));
        AddAction("选择 M1 状态", () => SelectAndInspect("M1 JSON | *.json|*.json", M1SnapshotInspector.Inspect));
        AddAction("检查诊断 ZIP", () => SelectAndInspect("诊断 ZIP | *.zip|*.zip", DiagnosticBundleInspector.Inspect));
        AddAction("Windows 环境与能力", () => Show(WindowsCapability.Check()));
        AddAction("Mac 构建说明", () => Show(new Inspection("MAC_BUILD_REQUIRED", false,
            ["在 Apple Silicon Mac 上打开仓库，并依法准备版本匹配的游戏资源。",
             "执行 python3 scripts/g2mctl.py doctor 检查 Mac 工具链。",
             "审核后使用 macOS 工程操作器执行明确授权的 M1 阶段。",
             "Windows 版不会通过 SSH、代理或网络代替 Mac 构建。",
             "真实游戏 App、签名、iPhone 安装和游玩均需另行验收。"])));
        AddAction("导出脱敏摘要", ExportSummary);

        results.Dock = DockStyle.Fill;
        results.ReadOnly = true;
        results.BorderStyle = BorderStyle.None;
        results.BackColor = Surface;
        results.ForeColor = TextColor;
        results.Font = new Font("Consolas", 11f);
        results.WordWrap = true;
        results.DetectUrls = false;
        results.TabStop = false;
        results.Text = "Game2Mobile Operator for Windows\r\n\r\n" +
            "选择明确的本机文件进行只读检查。\r\n" +
            "不会搜索你的磁盘、上传私有日志或读写游戏资源。\r\n" +
            "不提供 Windows→iPhone 编译、设备安装或远程 Mac 控制。";
        root.Controls.Add(results, 0, 3);

        status.Dock = DockStyle.Fill;
        status.TextAlign = ContentAlignment.MiddleLeft;
        status.ForeColor = Muted;
        status.Text = "READY   •   仅本地 / 无网络 / 不执行游戏";
        root.Controls.Add(status, 0, 4);
    }

    private void AddAction(string label, Action action)
    {
        var button = new Button
        {
            Text = label, Width = 158, Height = 42,
            FlatStyle = FlatStyle.Flat, BackColor = Surface, ForeColor = TextColor,
            Margin = new Padding(0, 0, 10, 8), Cursor = Cursors.Hand,
            UseVisualStyleBackColor = false
        };
        button.FlatAppearance.BorderColor = Color.FromArgb(62, 68, 82);
        button.Click += (_, _) => { if (!working) action(); };
        actions.Controls.Add(button);
    }

    private void Show(Inspection item)
    {
        latest = item;
        var text = new StringBuilder();
        text.AppendLine("  " + item.Code).AppendLine();
        foreach (string line in item.Lines) text.AppendLine("  •  " + line);
        if (item.RunId is not null) text.AppendLine("  同次运行标识：" + item.RunId);
        text.AppendLine().AppendLine("  声明来源及设备真实性：未认证");
        results.Text = text.ToString();
        status.Text = item.Passed ? "CHECKED   •   本机文件/结构检查，非设备验收" :
            "INCOMPLETE   •   检查未通过或仍需 Apple Silicon Mac";
    }

    private void SelectAndInspect(string filter, Func<string, Inspection> inspect)
    {
        using var dialog = new OpenFileDialog
        {
            Filter = filter, Title = "明确选择本机证据文件（不自动扫描）",
            CheckFileExists = true, Multiselect = false, RestoreDirectory = true
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        string path = dialog.FileName;
        working = true;
        foreach (Control control in actions.Controls) control.Enabled = false;
        status.Text = "CHECKING   •   正在读取用户选定的本机文件";
        _ = RunAsync(path, inspect);
    }

    private async Task RunAsync(string path, Func<string, Inspection> inspect)
    {
        Inspection item;
        try { item = await Task.Run(() => inspect(path)); }
        catch { item = Inspection.Invalid(); }
        if (IsDisposed || Disposing) return;
        working = false;
        foreach (Control control in actions.Controls) control.Enabled = true;
        Show(item);
    }

    private void ExportSummary()
    {
        if (latest is null) { status.Text = "先执行一次只读检查，再导出摘要。"; return; }
        using var dialog = new SaveFileDialog
        {
            Filter = "JSON 摘要 | *.json|*.json", DefaultExt = "json",
            FileName = "Game2Mobile-Windows-summary.json", Title = "保存供人工审查的脱敏摘要",
            OverwritePrompt = true
        };
        if (dialog.ShowDialog(this) != DialogResult.OK) return;
        try
        {
            // Exclusive creation: do not overwrite user files even if the dialog says yes.
            string destination = SafeLocalFile.LocalPath(dialog.FileName, false);
            var value = new
            {
                schema = "game2mobile.windows-operator-summary.v1", scope = "local-unattested-summary",
                code = latest.Code, passed = latest.Passed, run_id = latest.RunId,
                playability = "unverified", device_authenticity = "not_attested",
                reviewed_before_sharing = false
            };
            using var output = new FileStream(destination, FileMode.CreateNew, FileAccess.Write, FileShare.None);
            JsonSerializer.Serialize(output, value, new JsonSerializerOptions { WriteIndented = true });
            output.Flush(true);
            status.Text = "已保存脱敏记录（未上传）。分享前请审查。";
        }
        catch { status.Text = "保存失败或目标文件已存在；未覆盖任何文件。"; }
    }
}
