import Foundation

struct RunnerInput: Codable {
    let url: String?
    let platform: String?
    let captureProfile: String?

    enum CodingKeys: String, CodingKey {
        case url, platform
        case captureProfile = "capture_profile"
    }
}

struct AgentResult: Codable {
    let sourceURL: String
    let platform: String
    let title: String
    let author: String
    let captureStatus: String
    let rawFileReference: String
    let duration: String
    let language: String
    let subtitleDetected: String
    let audioDetected: String
    let visualTextPossible: String
    let failureReason: String
    let captureTool: String

    enum CodingKeys: String, CodingKey {
        case sourceURL = "source_url"
        case platform, title, author
        case captureStatus = "capture_status"
        case rawFileReference = "raw_file_reference"
        case duration, language
        case subtitleDetected = "subtitle_detected"
        case audioDetected = "audio_detected"
        case visualTextPossible = "visual_text_possible"
        case failureReason = "failure_reason"
        case captureTool = "capture_tool"
    }
}

struct CaptureProtocolV2: Codable {
    let protocolName: String?
    let source: CaptureSource?
    let capture: CaptureMetadata?
    let media: CaptureMedia?
    let subtitle: CaptureSubtitle?
    let audio: CaptureAudio?
    let visual: CaptureVisual?

    enum CodingKeys: String, CodingKey {
        case protocolName = "protocol"
        case source, capture, media, subtitle, audio, visual
    }
}

struct CaptureSource: Codable {
    let platform: String?
    let sourceURL: String?
    let title: String?
    let author: String?
    let capturedAt: String?

    enum CodingKeys: String, CodingKey {
        case platform
        case sourceURL = "source_url"
        case title, author
        case capturedAt = "captured_at"
    }
}

struct CaptureMetadata: Codable {
    let captureStatus: String?
    let captureMethod: String?
    let warnings: [String]?

    enum CodingKeys: String, CodingKey {
        case captureStatus = "capture_status"
        case captureMethod = "capture_method"
        case warnings
    }
}

struct CaptureMedia: Codable {
    let files: [CaptureFile]?
}

struct CaptureFile: Codable {
    let type: String?
    let path: String?
    let format: String?
    let size: String?
}

struct CaptureSubtitle: Codable {
    let status: String?
    let language: String?
    let reference: String?
}

struct CaptureAudio: Codable {
    let status: String?
    let reference: String?
}

struct CaptureVisual: Codable {
    let textPossible: String?

    enum CodingKeys: String, CodingKey {
        case textPossible = "text_possible"
    }
}

struct CommandResult {
    let status: Int32
    let stdout: Data
    let stderr: Data

    var stdoutText: String { String(data: stdout, encoding: .utf8) ?? "" }
    var stderrText: String { String(data: stderr, encoding: .utf8) ?? "" }
}

enum RunnerError: LocalizedError {
    case usage
    case missingURL
    case invalidURL(String)
    case invalidInput(String)
    case commandFailed(String, String)
    case doctorUnavailable(String)

    var errorDescription: String? {
        switch self {
        case .usage: return "invalid command usage"
        case .missingURL: return "missing required input field: url"
        case .invalidURL(let value): return "invalid URL: \(value)"
        case .invalidInput(let detail): return "invalid input: \(detail)"
        case .commandFailed(let command, let detail): return "\(command) failed: \(detail)"
        case .doctorUnavailable(let detail): return "Agent-Reach YouTube backend unavailable: \(detail)"
        }
    }
}

func value(_ name: String) -> String? {
    let arguments = Array(CommandLine.arguments.dropFirst())
    guard let index = arguments.firstIndex(of: name), arguments.index(after: index) < arguments.endIndex else { return nil }
    return arguments[arguments.index(after: index)]
}

func required(_ name: String) throws -> String {
    guard let value = value(name), !value.isEmpty else { throw RunnerError.missingURL }
    return value
}

func unknown(_ value: String?) -> String {
    guard let value, !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return "unknown" }
    return value
}

func writeJSON<T: Encodable>(_ value: T, to url: URL) throws {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
    try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    try encoder.encode(value).write(to: url, options: .atomic)
}

func run(_ command: String, arguments: [String]) throws -> CommandResult {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
    process.arguments = [command] + arguments
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent("agent-reach-runner-\(UUID().uuidString)", isDirectory: true)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    let stdoutURL = directory.appendingPathComponent("stdout")
    let stderrURL = directory.appendingPathComponent("stderr")
    FileManager.default.createFile(atPath: stdoutURL.path, contents: nil)
    FileManager.default.createFile(atPath: stderrURL.path, contents: nil)
    let stdoutHandle = try FileHandle(forWritingTo: stdoutURL)
    let stderrHandle = try FileHandle(forWritingTo: stderrURL)
    process.standardOutput = stdoutHandle
    process.standardError = stderrHandle
    try process.run()
    process.waitUntilExit()
    try stdoutHandle.close()
    try stderrHandle.close()
    let result = CommandResult(
        status: process.terminationStatus,
        stdout: try Data(contentsOf: stdoutURL),
        stderr: try Data(contentsOf: stderrURL)
    )
    try? FileManager.default.removeItem(at: directory)
    return result
}

func validURL(_ raw: String) -> Bool {
    guard let components = URLComponents(string: raw),
          let scheme = components.scheme?.lowercased(),
          ["http", "https"].contains(scheme),
          let host = components.host?.lowercased() else { return false }
    return host == "youtube.com" || host.hasSuffix(".youtube.com") || host == "youtu.be"
}

func failedResult(sourceURL: String, platform: String, reason: String) -> AgentResult {
    AgentResult(
        sourceURL: sourceURL,
        platform: platform,
        title: "unknown",
        author: "unknown",
        captureStatus: "failed",
        rawFileReference: "none",
        duration: "unknown",
        language: "unknown",
        subtitleDetected: "unknown",
        audioDetected: "unknown",
        visualTextPossible: "unknown",
        failureReason: reason,
        captureTool: "agent-reach / yt-dlp"
    )
}

func doctorHasYouTubeBackend(_ data: Data) -> Bool {
    guard let root = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let youtube = root["youtube"] as? [String: Any],
          let status = youtube["status"] as? String,
          let backend = youtube["active_backend"] as? String else { return false }
    return status == "ok" && backend == "yt-dlp"
}

func metadataString(_ metadata: [String: Any], _ key: String) -> String {
    if let value = metadata[key] as? String { return unknown(value) }
    if let value = metadata[key] as? NSNumber { return value.stringValue }
    return "unknown"
}

func subtitleLanguages(_ metadata: [String: Any]) -> [String] {
    let priorities = ["zh-Hans", "zh", "zh-CN", "en"]
    let manual = Set((metadata["subtitles"] as? [String: Any])?.map { $0.key } ?? [])
    let automatic = Set((metadata["automatic_captions"] as? [String: Any])?.map { $0.key } ?? [])
    return priorities.filter { manual.contains($0) || automatic.contains($0) }
}

func protocolResult(_ captureProtocol: CaptureProtocolV2) throws -> AgentResult {
    guard captureProtocol.protocolName == "capture-protocol-v2" else {
        throw RunnerError.invalidInput("protocol must be capture-protocol-v2")
    }
    let source = captureProtocol.source
    let capture = captureProtocol.capture
    let subtitle = captureProtocol.subtitle
    let audio = captureProtocol.audio
    let visual = captureProtocol.visual
    let mediaFiles = captureProtocol.media?.files ?? []
    let mediaReference = mediaFiles.compactMap { file -> String? in
        guard let path = file.path, !path.isEmpty else { return nil }
        return path
    }.first ?? "none"
    let warnings = capture?.warnings ?? []
    let warningText = warnings.joined(separator: " | ")
    return AgentResult(
        sourceURL: unknown(source?.sourceURL),
        platform: unknown(source?.platform),
        title: unknown(source?.title),
        author: unknown(source?.author),
        captureStatus: unknown(capture?.captureStatus),
        rawFileReference: mediaReference != "none" ? mediaReference : unknown(subtitle?.reference),
        duration: "unknown",
        language: unknown(subtitle?.language),
        subtitleDetected: unknown(subtitle?.status),
        audioDetected: unknown(audio?.status),
        visualTextPossible: unknown(visual?.textPossible),
        failureReason: warningText,
        captureTool: unknown(capture?.captureMethod)
    )
}

func usage() -> Never {
    print("Usage: agent-reach-runner --input capture-protocol-v2.json --output agent-result.json; legacy URL replay additionally requires --legacy-replay true")
    exit(2)
}

@main
struct AgentReachRunnerMain {
    static func main() {
        do {
            guard let inputArgument = value("--input"), let outputArgument = value("--output") else { throw RunnerError.usage }
            let inputURL = URL(fileURLWithPath: inputArgument).standardizedFileURL
            let outputURL = URL(fileURLWithPath: outputArgument).standardizedFileURL
            guard FileManager.default.fileExists(atPath: inputURL.path) else {
                throw RunnerError.invalidInput("input file does not exist: \(inputURL.path)")
            }

            let input: RunnerInput
            let inputData = try Data(contentsOf: inputURL)
            if let protocolInput = try? JSONDecoder().decode(CaptureProtocolV2.self, from: inputData),
               protocolInput.protocolName == "capture-protocol-v2" {
                let result = try protocolResult(protocolInput)
                try writeJSON(result, to: outputURL)
                print("AGENT_RESULT=\(outputURL.path)")
                print("CAPTURE_STATUS=\(result.captureStatus)")
                print("PROTOCOL=capture-protocol-v2")
                print("PLATFORM=\(result.platform)")
                exit(0)
            }
            do { input = try JSONDecoder().decode(RunnerInput.self, from: inputData) }
            catch { throw RunnerError.invalidInput(error.localizedDescription) }
            guard value("--legacy-replay") == "true" else {
                throw RunnerError.invalidInput("legacy URL mode is blocked in production; use Capture Provider Router or pass --legacy-replay true for historical replay")
            }
            guard let rawURL = input.url, !rawURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw RunnerError.missingURL }
            guard validURL(rawURL) else {
                let result = failedResult(sourceURL: rawURL, platform: unknown(input.platform), reason: "only valid YouTube http(s) URLs are supported by the active backend")
                try writeJSON(result, to: outputURL)
                print("AGENT_RESULT=\(outputURL.path)")
                print("CAPTURE_STATUS=failed")
                print("FAILURE_REASON=invalid URL")
                exit(0)
            }

            let doctor = try run("agent-reach", arguments: ["doctor", "--json"])
            guard doctor.status == 0, doctorHasYouTubeBackend(doctor.stdout) else {
                throw RunnerError.doctorUnavailable((doctor.stderrText.isEmpty ? doctor.stdoutText : doctor.stderrText).trimmingCharacters(in: .whitespacesAndNewlines))
            }

            let captureRoot = outputURL.deletingLastPathComponent().appendingPathComponent("capture", isDirectory: true)
            let rawRoot = captureRoot.appendingPathComponent("raw", isDirectory: true)
            try FileManager.default.createDirectory(at: rawRoot, withIntermediateDirectories: true)
            let metadataURL = rawRoot.appendingPathComponent("video.info.json")
            let metadataResult = try run("yt-dlp", arguments: ["--dump-single-json", "--no-playlist", rawURL])
            guard metadataResult.status == 0 else {
                let result = failedResult(sourceURL: rawURL, platform: unknown(input.platform), reason: metadataResult.stderrText.trimmingCharacters(in: .whitespacesAndNewlines))
                try writeJSON(result, to: outputURL)
                print("AGENT_RESULT=\(outputURL.path)")
                print("CAPTURE_STATUS=failed")
                exit(0)
            }
            try metadataResult.stdout.write(to: metadataURL, options: .atomic)
            guard let metadata = try JSONSerialization.jsonObject(with: metadataResult.stdout) as? [String: Any] else {
                throw RunnerError.invalidInput("yt-dlp metadata is not a JSON object")
            }

            let languages = subtitleLanguages(metadata)
            var subtitlePath = "none"
            var selectedLanguage = "unknown"
            var subtitleStatus = "no"
            var subtitleFailure = ""
            for language in languages {
                let subtitleResult = try run("yt-dlp", arguments: ["--write-sub", "--write-auto-sub", "--sub-lang", language, "--skip-download", "--no-playlist", "-o", rawRoot.appendingPathComponent("%(id)s").path, rawURL])
                let candidate = rawRoot.appendingPathComponent("\(metadataString(metadata, "id")).\(language).vtt")
                if subtitleResult.status == 0 && FileManager.default.fileExists(atPath: candidate.path) {
                    subtitlePath = candidate.path
                    selectedLanguage = language
                    subtitleStatus = "available"
                    break
                }
                subtitleFailure = subtitleResult.stderrText.trimmingCharacters(in: .whitespacesAndNewlines)
            }

            let result = AgentResult(
                sourceURL: rawURL,
                platform: unknown(input.platform == nil ? "YouTube" : input.platform),
                title: metadataString(metadata, "title"),
                author: metadataString(metadata, "uploader"),
                captureStatus: "complete",
                rawFileReference: subtitleStatus == "available" ? subtitlePath : metadataURL.path,
                duration: metadataString(metadata, "duration"),
                language: selectedLanguage,
                subtitleDetected: subtitleStatus,
                audioDetected: "true",
                visualTextPossible: "unknown",
                failureReason: subtitleFailure,
                captureTool: "agent-reach / yt-dlp"
            )
            try writeJSON(result, to: outputURL)
            print("AGENT_RESULT=\(outputURL.path)")
            print("CAPTURE_STATUS=\(result.captureStatus)")
            print("SUBTITLE_LANGUAGE=\(result.language)")
            print("RAW_FILE=\(result.rawFileReference)")
        } catch {
            fputs("ERROR: \(error.localizedDescription)\n", stderr)
            exit(3)
        }
    }
}
