// SPDX-License-Identifier: MIT
import XCTest
@testable import OperatorCore

final class OperatorCoreTests: XCTestCase {
    private func json(_ cmd: String, _ code: String, _ exit: Int, _ extras: String = "") -> Data {
        """
        {"schema":"game2mobile.operator.v1","command":"\(cmd)","code":"\(code)","exit_code":\(exit),"ok":\(exit == 0),"scope":"local-read-only","playability":"unverified"\(extras)}
        """.data(using: .utf8)!
    }
    func testNoImplicitBuildPermission() {
        XCTAssertEqual(OperatorRequest.buildPlan.arguments, ["build-plan"])
        XCTAssertFalse(OperatorRequest.buildPlan.isMutating)
        XCTAssertTrue(OperatorRequest.buildLocal(workspace: "/private/my work", profile: .metal4,
                                                     stage: .preflight).isMutating)
        XCTAssertEqual(OperatorRequest.buildLocal(workspace: "/private/my work", profile: .m3, stage: .all).arguments,
                       ["build", "--execute-local", "--workspace", "/private/my work", "--profile", "m3", "--stage", "all"])
    }
    func testFinderToolPathPreservesInheritedAndPreventsCwdSearch() {
        let path = LocalToolPath.construct(inherited: "/custom/bin::/opt/homebrew/bin:/another/bin")
        XCTAssertTrue(path.hasPrefix("/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:"))
        XCTAssertTrue(path.contains(":/custom/bin:"))
        XCTAssertTrue(path.hasSuffix(":/another/bin"))
        XCTAssertFalse(path.contains("::"))
        XCTAssertEqual(path.components(separatedBy: ":").filter { $0 == "/opt/homebrew/bin" }.count, 1)
        XCTAssertTrue(LocalToolPath.construct(inherited: nil).contains(":/usr/bin:"))
    }
    func testPathArgumentsRemainSingleTokens() {
        let file = "/private/name ; /game (a) ' $HOME"
        XCTAssertEqual(OperatorRequest.bootStatus(log: file).arguments, ["status", "--log", file])
        XCTAssertEqual(OperatorRequest.jobStatus(file: file).arguments, ["job-status", "--status-file", file])
    }
    func testReadOnlyPlanContract() throws {
        let data = json("build-plan", "OK", 0, ",\"stages\":[{\"stage\":\"preflight\",\"description\":\"owner check\"}]")
        let reply = try OperatorReply.parse(data, for: .buildPlan, processExit: 0)
        XCTAssertTrue(reply.ok)
        XCTAssertEqual(reply.stages?.first?.stage, "preflight")
        XCTAssertTrue(reply.summaryLines.contains("阶段：preflight"))
        XCTAssertTrue(reply.summaryLines.last!.contains("未验证"))
    }
    func testRunningJobIsNotPlayabilityOrLiveProcessProof() throws {
        let data = json("job-status", "M1_JOB_RUNNING", 1, ",\"job_liveness\":\"not_checked\",\"job\":{\"state\":\"running\",\"current_stage\":\"prepare\",\"profile\":\"metal4\",\"result\":\"incomplete\"}")
        let reply = try OperatorReply.parse(data, for: .jobStatus(file: "/private/run.json"), processExit: 1)
        XCTAssertEqual(reply.job_liveness, "not_checked")
        XCTAssertTrue(reply.summaryLines.contains("当前阶段：prepare"))
        XCTAssertTrue(reply.summaryLines.last!.contains("未验证"))
    }
    func testRejectWrongSchemaCommandOrExitCode() {
        let request = OperatorRequest.buildPlan
        XCTAssertThrowsError(try OperatorReply.parse(Data("[]".utf8), for: request, processExit: 0))
        XCTAssertThrowsError(try OperatorReply.parse(json("status", "OK", 0), for: request, processExit: 0))
        XCTAssertThrowsError(try OperatorReply.parse(json("build-plan", "OK", 0), for: request, processExit: 1))
        XCTAssertThrowsError(try OperatorReply.parse(json("build-plan", "BAD path", 2), for: request, processExit: 2))
        XCTAssertThrowsError(try OperatorReply.parse(Data(repeating: 0x61, count: 128 * 1024 + 1), for: request, processExit: 2))
        let wrong = Data("{\"schema\":\"other\",\"command\":\"build-plan\",\"code\":\"OK\",\"exit_code\":0,\"ok\":true,\"scope\":\"local-read-only\"}".utf8)
        XCTAssertThrowsError(try OperatorReply.parse(wrong, for: request, processExit: 0))
    }
    func testNeverEchoPrivateFreeformFields() throws {
        let data = json("status", "AWAITING_GPU_SUBMIT", 1, ",\"private\":\"/Users/private/secret\",\"observation\":{\"result\":\"awaiting_gpu_submit\",\"next_action\":\"private tokens should not appear\",\"run_id\":\"bad unsafe run id\"}")
        let reply = try OperatorReply.parse(data, for: .bootStatus(log: "/private/boot.txt"), processExit: 1)
        XCTAssertFalse(reply.summaryLines.joined().contains("/Users/private"))
        XCTAssertFalse(reply.summaryLines.joined().contains("private tokens"))
        XCTAssertFalse(reply.summaryLines.joined().contains("bad unsafe run"))
        XCTAssertTrue(reply.summaryLines.last!.contains("未验证"))
    }
}
