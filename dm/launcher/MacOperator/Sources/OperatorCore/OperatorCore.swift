// SPDX-License-Identifier: MIT
// Narrow protocol adapter to the existing scripts/g2mctl.py executor.
// No arbitrary command strings, remote transport, or private-file discovery.
import Foundation

public enum OperatorRequest: Equatable {
    case capabilities
    case buildPlan
    case bootStatus(log: String)
    case jobStatus(file: String)
    case buildLocal(workspace: String, profile: Profile, stage: Stage)

    public enum Profile: String, CaseIterable, Identifiable {
        case metal4, m3
        public var id: String { rawValue }
    }

    public enum Stage: String, CaseIterable, Identifiable {
        case preflight, prepare, headers, verify, build, all
        public var id: String { rawValue }
    }

    public var arguments: [String] {
        switch self {
        case .capabilities: return ["capabilities"]
        case .buildPlan: return ["build-plan"]
        case .bootStatus(let log): return ["status", "--log", log]
        case .jobStatus(let file): return ["job-status", "--status-file", file]
        case .buildLocal(let workspace, let profile, let stage):
            return ["build", "--execute-local", "--workspace", workspace,
                    "--profile", profile.rawValue, "--stage", stage.rawValue]
        }
    }

    public var command: String {
        switch self {
        case .capabilities: return "capabilities"
        case .buildPlan: return "build-plan"
        case .bootStatus: return "status"
        case .jobStatus: return "job-status"
        case .buildLocal: return "build"
        }
    }

    public var isMutating: Bool {
        if case .buildLocal = self { return true }
        return false
    }
}

public enum OperatorProtocolError: Error, Equatable {
    case invalidEncoding
    case invalidSchema
    case invalidCode
    case wrongCommand
    case inconsistentExit
    case oversizedResponse
}

public struct OperatorReply: Decodable {
    public let schema: String
    public let command: String
    public let code: String
    public let ok: Bool
    public let exit_code: Int
    public let scope: String
    public let playability: String?
    public let job_liveness: String?
    public let stages: [StageInfo]?
    public let observation: BootObservation?
    public let job: JobInfo?

    public struct StageInfo: Decodable {
        public let stage: String
        public let description: String
    }
    public struct BootObservation: Decodable {
        public let run_id: String?
        public let result: String?
        public let next_action: String?
    }
    public struct JobInfo: Decodable {
        public let state: String
        public let current_stage: String?
        public let profile: String
        public let result: String
    }

    public static func parse(_ bytes: Data, for request: OperatorRequest,
                             processExit: Int32) throws -> OperatorReply {
        guard bytes.count <= 128 * 1024 else { throw OperatorProtocolError.oversizedResponse }
        guard let result = try? JSONDecoder().decode(OperatorReply.self, from: bytes) else {
            throw OperatorProtocolError.invalidEncoding
        }
        guard result.schema == "game2mobile.operator.v1", result.scope == "local-read-only" ||
                (request.isMutating && result.scope == "explicit-local-build") else {
            throw OperatorProtocolError.invalidSchema
        }
        // Fixed command protocol, no free-form shell or path text in the UI.
        guard result.command == request.command ||
                (result.command == "unknown" && result.code == "BAD_ARGUMENT") else {
            throw OperatorProtocolError.wrongCommand
        }
        guard !result.code.isEmpty, result.code.count <= 64,
              result.code.utf8.allSatisfy({ (65...90).contains(Int($0)) ||
                  (48...57).contains(Int($0)) || $0 == 95 }) else {
            throw OperatorProtocolError.invalidCode
        }
        // Python exits with 130 for cancellation, 0/1/2/3 for all others.
        guard [0, 1, 2, 3, 130].contains(result.exit_code),
              result.exit_code == Int(processExit),
              result.ok == (result.exit_code == 0) else {
            throw OperatorProtocolError.inconsistentExit
        }
        return result
    }

    public var summaryLines: [String] {
        var lines: [String] = ["状态码：\(code)", "命令结果：\(ok ? "完成该命令范围" : "未完成或失败")"]
        if let value = observation {
            if let run = value.run_id, run.count == 32,
               run.utf8.allSatisfy({ (48...57).contains(Int($0)) || (97...102).contains(Int($0)) }) {
                lines.append("运行标识：\(run)")
            }
            let allowedBootStates: Set<String> = ["first_present_observed", "no_boot_evidence",
                "run_not_found", "input_error", "invalid_evidence", "startup_incomplete",
                "awaiting_gpu_submit", "awaiting_first_present", "host_returned_before_first_present",
                "runtime_error"]
            if let status = value.result, allowedBootStates.contains(status) {
                lines.append("启动观察：\(status)")
            }
        }
        if let value = job {
            // Never echo free-form private data; only known protocol enums.
            if ["running", "failed", "cancelled", "partial", "passed"].contains(value.state) {
                lines.append("构建阶段状态：\(value.state)")
            }
            if let stage = value.current_stage,
               ["preflight", "prepare", "headers", "verify", "build", "source", "environment", "arguments"].contains(stage) {
                lines.append("当前阶段：\(stage)")
            }
        }
        if let stages = stages, stages.count <= 6 {
            for stage in stages where OperatorRequest.Stage(rawValue: stage.stage) != nil {
                lines.append("阶段：\(stage.stage)")
            }
        }
        lines.append("可玩性：未验证；以上结果不代表游戏已在设备上运行")
        return lines
    }
}
