// SPDX-License-Identifier: MIT
// Optional macOS control surface for the existing owner-local Python M1 pipeline.
// The UI never opens game files, signs apps, installs to devices, or sends traffic.
import Foundation
import SwiftUI
import AppKit
import OperatorCore

@MainActor
final class OperatorState: ObservableObject {
    @Published var busy = false
    @Published var lines: [String] = ["选择本机 Game2Mobile 源码仓库后，使用只读查询。", "游戏可玩性仍未验证。"]
    private var active: Process?

    func run(_ request: OperatorRequest, repository: URL) {
        guard !busy else { return }
        let script = repository.appendingPathComponent("scripts/g2mctl.py")
        guard FileManager.default.fileExists(atPath: script.path),
              FileManager.default.fileExists(atPath: repository.appendingPathComponent("scripts/m1_local_pipeline.py").path) else {
            lines = ["仓库无效：缺少原有的操作器或 M1 构建脚本。"]
            return
        }
        // Explicit known local Python executables only: no shell interpolation.
        let pythonCandidates = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
        guard let python = pythonCandidates.first(where: FileManager.default.isExecutableFile(atPath:)) else {
            lines = ["未找到受支持的本机 Python 3；请安装 Python 3 和 Xcode 命令行工具。"]
            return
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        process.arguments = [script.path] + request.arguments
        process.currentDirectoryURL = repository
        // Finder has a restricted PATH; retain owner settings but put standard
        // Apple Silicon build tools ahead of them. Arguments never use a shell.
        var environment = ProcessInfo.processInfo.environment
        environment["PATH"] = LocalToolPath.construct(inherited: environment["PATH"])
        process.environment = environment
        let output = Pipe()
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice  // Never show private traceback/log paths.
        busy = true
        lines = ["正在执行 \(request.command)；不会自动安装或上传游戏资源。"]
        active = process
        do { try process.run() } catch {
            busy = false
            active = nil
            lines = ["本机操作器无法启动；没有执行任何游戏安装。"]
            return
        }
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            // Drain stdout while the process runs to avoid pipe deadlocks.
            // The CLI produces one small JSON line, but cap everything anyway.
            var payload = Data()
            var oversized = false
            while true {
                let chunk = output.fileHandleForReading.readData(ofLength: 8192)
                if chunk.isEmpty { break }
                if payload.count + chunk.count <= 128 * 1024 { payload.append(chunk) }
                else { oversized = true }
            }
            process.waitUntilExit()
            let parsed = oversized ? nil : try? OperatorReply.parse(payload, for: request,
                                                                      processExit: process.terminationStatus)
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.active = nil
                self.busy = false
                self.lines = parsed?.summaryLines ?? ["结果格式、退出码不匹配或操作被中止；请在本机查看私有构建证据。", "可玩性：未验证"]
            }
        }
    }

    func cancel() {
        guard let process = active, process.isRunning else { return }
        process.terminate() // Python catches SIGTERM and cleans its own process session.
        lines = ["已请求停止；等待原有构建器完成取消及进程清理。", "取消确认以前不视为成功。"]
    }
}

struct ContentView: View {
    // Owner lives at App scope so closing/reopening a window does not orphan
    // a running M1 process or lose its cancellation button.
    @ObservedObject var controller: OperatorState
    @State private var repository: URL?
    @State private var workspace: URL?
    @State private var bootLog: URL?
    @State private var jobFile: URL?
    @State private var profile: OperatorRequest.Profile = .metal4
    @State private var stage: OperatorRequest.Stage = .preflight

    private func chooseDirectory(_ apply: (URL) -> Void) {
        let p = NSOpenPanel()
        p.canChooseDirectories = true
        p.canChooseFiles = false
        p.allowsMultipleSelection = false
        if p.runModal() == .OK, let url = p.url { apply(url) }
    }
    private func chooseFile(_ apply: (URL) -> Void) {
        let p = NSOpenPanel()
        p.canChooseDirectories = false
        p.canChooseFiles = true
        p.allowsMultipleSelection = false
        if p.runModal() == .OK, let url = p.url { apply(url) }
    }
    private func run(_ action: OperatorRequest) {
        guard let repo = repository else { return }
        controller.run(action, repository: repo)
    }
    private func confirmBuild() {
        guard let ws = workspace else { return }
        let alert = NSAlert()
        alert.messageText = "确认执行本机 M1 阶段？"
        alert.informativeText = "将调用仓库现有的私有构建执行器（\(stage.rawValue), \(profile.rawValue)），可能消耗本机资源并使用已有的本机签名配置。不会安装到手机或上传游戏文件。"
        alert.alertStyle = .warning
        alert.addButton(withTitle: "执行本机构建")
        alert.addButton(withTitle: "取消")
        if alert.runModal() == .alertFirstButtonReturn {
            run(.buildLocal(workspace: ws.path, profile: profile, stage: stage))
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Game2Mobile · 本机工程操作器")
                .font(.system(size: 24, weight: .semibold, design: .rounded))
            Text("独立的 macOS 工具，不是已验证可玩的游戏启动器。所有构建留在本机。")
                .foregroundStyle(.secondary)
            HStack {
                Button(repository == nil ? "选择源码仓库" : "更换源码仓库") {
                    chooseDirectory { repository = $0 }
                }
                Text(repository == nil ? "尚未选择" : "仓库已选择")
                    .foregroundStyle(.secondary)
                Spacer()
                Button("检查构建环境") { run(.doctor) }.disabled(repository == nil || controller.busy)
                Button("查看能力") { run(.capabilities) }.disabled(repository == nil || controller.busy)
                Button("查看阶段计划") { run(.buildPlan) }.disabled(repository == nil || controller.busy)
            }
            Divider()
            GroupBox("只读检查") {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Button("选择启动日志") { chooseFile { bootLog = $0 } }
                        Text(bootLog == nil ? "未选择" : "已选择")
                            .foregroundStyle(.secondary)
                        Button("检查启动") { if let log = bootLog { run(.bootStatus(log: log.path)) } }
                            .disabled(repository == nil || bootLog == nil || controller.busy)
                    }
                    HStack {
                        Button("选择 M1 阶段记录") { chooseFile { jobFile = $0 } }
                        Text(jobFile == nil ? "未选择" : "已选择")
                            .foregroundStyle(.secondary)
                        Button("读取进度") { if let file = jobFile { run(.jobStatus(file: file.path)) } }
                            .disabled(repository == nil || jobFile == nil || controller.busy)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            GroupBox("明确授权的本机构建") {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Button("选择私有工作区") { chooseDirectory { workspace = $0 } }
                        Text(workspace == nil ? "未选择" : "已选择")
                            .foregroundStyle(.secondary)
                    }
                    HStack {
                        Picker("图形配置", selection: $profile) {
                            ForEach(OperatorRequest.Profile.allCases) { value in Text(value.rawValue).tag(value) }
                        }.frame(width: 170)
                        Picker("阶段", selection: $stage) {
                            ForEach(OperatorRequest.Stage.allCases) { value in Text(value.rawValue).tag(value) }
                        }.frame(width: 230)
                        Spacer()
                        Button("确认并运行") { confirmBuild() }
                            .disabled(repository == nil || workspace == nil || controller.busy)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            HStack {
                Text(controller.busy ? "正在执行；请勿关闭本机工作区" : "空闲")
                    .foregroundStyle(controller.busy ? Color.orange : Color.secondary)
                Spacer()
                Button("请求取消") { controller.cancel() }.disabled(!controller.busy)
            }
            GroupBox("结果（只显示白名单字段）") {
                ScrollView {
                    VStack(alignment: .leading, spacing: 5) {
                        ForEach(Array(controller.lines.enumerated()), id: \.offset) { _, text in
                            Text(text).font(.system(.body, design: .monospaced))
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }.padding(4)
                }.frame(minHeight: 130)
            }
            Text("提示：阶段 passed、首次上屏和真实可玩性是不同结论。M1 真机验收仍需合法游戏资源、签名与设备。")
                .font(.footnote).foregroundStyle(.secondary)
        }
        .padding(22)
        .frame(minWidth: 760, minHeight: 640)
    }
}

@main
struct Game2MobileOperatorApp: App {
    @StateObject private var controller = OperatorState()
    var body: some Scene {
        WindowGroup("Game2Mobile Operator") { ContentView(controller: controller) }
    }
}
