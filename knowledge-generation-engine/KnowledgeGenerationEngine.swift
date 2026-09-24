import Foundation

struct AssetDraft: Decodable {
    let protocolName: String
    let asset: Asset
    let source: Source
    let content: DraftContent
    let review: DraftReview
    enum CodingKeys: String, CodingKey { case protocolName = "protocol", asset, source, content, review }
}
struct Asset: Decodable { let assetID: String; let type: String; let status: String
    enum CodingKeys: String, CodingKey { case assetID = "asset_id"; case type, status }
}
struct Source: Decodable { let materialID: String; let taskID: String; let sourceReference: String
    enum CodingKeys: String, CodingKey { case materialID = "material_id"; case taskID = "task_id"; case sourceReference = "source_reference" }
}
struct DraftContent: Decodable { let title: String; let references: [String]
    enum CodingKeys: String, CodingKey { case title, references }
}
struct DraftReview: Decodable { let needConfirmation: Bool; let confirmed: Bool
    enum CodingKeys: String, CodingKey { case needConfirmation = "need_confirmation"; case confirmed }
}
struct Plan: Decodable {
    let protocolName: String
    let input: PlanInput
    let generation: Generation
    let output: PlanOutput
    enum CodingKeys: String, CodingKey { case protocolName = "protocol", input, generation, output }
}
struct PlanInput: Decodable { let assetDraftID: String; let materialID: String; let sourceReference: String
    enum CodingKeys: String, CodingKey { case assetDraftID = "asset_draft_id"; case materialID = "material_id"; case sourceReference = "source_reference" }
}
struct Generation: Decodable { let assetType: String; let template: String; let requirements: [String]
    enum CodingKeys: String, CodingKey { case assetType = "asset_type"; case template, requirements }
}
struct PlanOutput: Decodable { let draftReference: String; let needConfirmation: Bool
    enum CodingKeys: String, CodingKey { case draftReference = "draft_reference"; case needConfirmation = "need_confirmation" }
}
struct VideoUnderstandingPackageInput: Decodable {
    let protocolName: String
    let status: String
    let taskID: String
    let sourceReference: String
    let confidenceScore: Double
    let mainTopic: UnderstandingTopic
    let coreClaims: [UnderstandingClaim]
    let argumentStructure: [UnderstandingArgument]
    let uncertainties: [String]
    let knowledgeGenerationGate: UnderstandingGenerationGate
    enum CodingKeys: String, CodingKey {
        case protocolName = "protocol"; case status; case taskID = "task_id"; case sourceReference = "source_reference"
        case confidenceScore = "confidence_score"; case mainTopic = "main_topic"; case coreClaims = "core_claims"
        case argumentStructure = "argument_structure"; case uncertainties; case knowledgeGenerationGate = "knowledge_generation_gate"
    }
}
struct UnderstandingTopic: Decodable {
    let statement: String
    let scope: String
    let confidence: String
}
struct UnderstandingClaim: Decodable {
    let id: String
    let claim: String
    let completeness: String
}
struct UnderstandingArgument: Decodable {
    let order: Int
    let role: String
    let summary: String
}
struct UnderstandingGenerationGate: Decodable {
    let status: String
    let reasons: [String]
    let requiresConfirmation: Bool
    enum CodingKeys: String, CodingKey { case status, reasons; case requiresConfirmation = "requires_confirmation" }
}
struct SourceMaterialV3Input: Decodable {
    let protocolName: String
    let schemaVersion: String
    let materialID: String
    let revisionID: String
    let source: SourceMaterialSource
    let quality: SourceMaterialQuality
    let lifecycle: SourceMaterialLifecycle
    let assetManifestReference: String
    enum CodingKeys: String, CodingKey {
        case protocolName = "protocol"; case schemaVersion = "schema_version"
        case materialID = "material_id"; case revisionID = "revision_id"
        case source, quality, lifecycle
        case assetManifestReference = "asset_manifest_reference"
    }
}
struct SourceMaterialSource: Decodable {
    let sourceURL: String
    let title: String?
    let author: String?
    let platform: String?
    let language: String?
    enum CodingKeys: String, CodingKey { case sourceURL = "source_url"; case title, author, platform, language }
}
struct SourceMaterialQuality: Decodable {
    let reviewRequired: Bool
    let uncertainties: [String]?
    enum CodingKeys: String, CodingKey { case reviewRequired = "review_required"; case uncertainties }
}
struct SourceMaterialLifecycle: Decodable {
    let reviewStatus: String
    enum CodingKeys: String, CodingKey { case reviewStatus = "review_status" }
}
struct UnderstandingSidecarInput: Decodable {
    let protocolName: String
    let schemaVersion: String
    let sidecarID: String
    let materialID: String
    let revisionID: String
    let status: String
    enum CodingKeys: String, CodingKey {
        case protocolName = "protocol"; case schemaVersion = "schema_version"
        case sidecarID = "sidecar_id"; case materialID = "material_id"
        case revisionID = "revision_id"; case status
    }
}
struct SourceValidationReceipt: Decodable {
    let status: String
    let materialID: String
    let revisionID: String
    let manifestStatus: String?
    enum CodingKeys: String, CodingKey {
        case status; case materialID = "material_id"; case revisionID = "revision_id"
        case manifestStatus = "manifest_status"
    }
}

struct QualityReport: Encodable {
    let generationQualityCheck: GenerationQualityCheck
    enum CodingKeys: String, CodingKey { case generationQualityCheck = "generation-quality-check" }
}
struct GenerationMetadata: Encodable {
    let modelName: String
    let modelVersion: String
    let generatedAt: String
    let promptVersion: String
    let provider: String
    enum CodingKeys: String, CodingKey { case modelName = "model_name"; case modelVersion = "model_version"; case generatedAt = "generated_at"; case promptVersion = "prompt_version"; case provider }
}
struct GenerationRecord: Encodable {
    let assetID: String
    let model: String
    let promptVersion: String
    let inputReference: [String]
    let outputReference: String
    let qualityReference: String
    let status: String
    let confirmationStatus: String
    enum CodingKeys: String, CodingKey { case assetID = "asset_id"; case model; case promptVersion = "prompt_version"; case inputReference = "input_reference"; case outputReference = "output_reference"; case qualityReference = "quality_reference"; case status; case confirmationStatus = "confirmation_status" }
}
struct GenerationQualityCheck: Encodable {
    let sourceTraceability: String
    let contentCompleteness: String
    let hallucinationRisk: String
    let missingInformation: [String]
    let intentionalScopeBoundaries: [String]
    let sourceLanguage: String
    let outputLanguage: String
    let translationRequired: Bool
    let semanticRedundancy: String
    let cognitiveDelta: String
    let cognitiveDeltaSignals: [String]
    let groundingStatus: String
    let unsupportedFactualExpansions: [String]
    let sourceBoundary: String
    let authorityBoundary: String
    let aiCandidateSections: [String]
    let sourceClaimLabeling: String
    let userConfirmedView: String
    let generatedTitle: String
    let titleConsistency: String
    let publishable: Bool
    let blockingReasons: [String]
    let method: String
    enum CodingKeys: String, CodingKey {
        case sourceTraceability = "source_traceability"
        case contentCompleteness = "content_completeness"
        case hallucinationRisk = "hallucination_risk"
        case missingInformation = "missing_information"
        case intentionalScopeBoundaries = "intentional_scope_boundaries"
        case sourceLanguage = "source_language"
        case outputLanguage = "output_language"
        case translationRequired = "translation_required"
        case semanticRedundancy = "semantic_redundancy"
        case cognitiveDelta = "cognitive_delta"
        case cognitiveDeltaSignals = "cognitive_delta_signals"
        case groundingStatus = "grounding_status"
        case unsupportedFactualExpansions = "unsupported_factual_expansions"
        case sourceBoundary = "source_boundary"
        case authorityBoundary = "authority_boundary"
        case aiCandidateSections = "ai_candidate_sections"
        case sourceClaimLabeling = "source_claim_labeling"
        case userConfirmedView = "user_confirmed_view"
        case generatedTitle = "generated_title"
        case titleConsistency = "title_consistency"
        case publishable
        case blockingReasons = "blocking_reasons"
        case method
    }
}

enum EngineError: LocalizedError {
    case usage
    case invalid(String)
    var errorDescription: String? {
        switch self {
        case .usage: return "Usage: knowledge-generation-engine --draft DRAFT.json --plan PLAN.json --source-material SOURCE.json --source-validation VALIDATION.json [--readable-source READABLE.md] [--candidate-generation true] [--understanding-sidecar SIDECAR.json] --output DRAFT.md --quality QUALITY.json; legacy replay additionally requires --understanding-package LEGACY.json --legacy-replay true"
        case .invalid(let message): return message
        }
    }
}

func argument(_ name: String) -> String? {
    let args = Array(CommandLine.arguments.dropFirst())
    guard let index = args.firstIndex(of: name), args.index(after: index) < args.endIndex else { return nil }
    return args[args.index(after: index)]
}
func required(_ name: String) throws -> String { guard let value = argument(name), !value.isEmpty else { throw EngineError.usage }; return value }
func read<T: Decodable>(_ type: T.Type, path: String) throws -> T {
    do { return try JSONDecoder().decode(type, from: Data(contentsOf: URL(fileURLWithPath: path))) }
    catch { throw EngineError.invalid("invalid JSON at \(path): \(error.localizedDescription)") }
}
func write<T: Encodable>(_ value: T, path: String) throws {
    let url = URL(fileURLWithPath: path)
    try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
    try encoder.encode(value).write(to: url, options: .atomic)
}
func writeText(_ text: String, path: String) throws {
    let url = URL(fileURLWithPath: path)
    try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    try text.write(to: url, atomically: true, encoding: .utf8)
}

func legacyPrompt(draftPath: String, planPath: String, understandingPackagePath: String) -> String {
    """
    你是知识整理助手。只读取并根据以下三个本地文件生成一篇 learning_note Markdown 草稿：
    \(draftPath)
    \(planPath)
    \(understandingPackagePath)

    仅使用 Video Understanding Package 中可追溯的主题、观点、论证和证据；保留原始链接、Material ID、Task ID和Package引用；结构必须包含 # 标题、## 来源、## 核心概念、## 关键知识点、## 内容整理、## 实践价值、## 参考资料；关键知识点3-7条；不添加来源没有的事实，不编造案例，不写个人观点或价值判断；信息不足明确写“素材未提供相关信息”。只输出Markdown正文，不要解释，不要修改任何文件。
    """
}
func sourceMaterialPromptV1(draftPath: String, planPath: String, sourceMaterialPath: String, readableSourcePath: String?, sidecarPath: String?) -> String {
    let sidecarInstruction: String
    if let sidecarPath {
        sidecarInstruction = """
        可选 Understanding Sidecar：
        \(sidecarPath)
        Sidecar 只提供候选理解。任何与 Source Material 冲突或无法回指证据的内容必须忽略。
        """
    } else {
        sidecarInstruction = "本次没有 Understanding Sidecar。不得因此阻断生成，也不得补写来源不存在的信息。"
    }
    let readableInstruction: String
    if let readableSourcePath {
        readableInstruction = "可读来源正文（唯一可读事实正文）：\n\(readableSourcePath)"
    } else {
        readableInstruction = "没有额外可读来源正文；只能依据 Source Material 中可追溯的事实。"
    }
    return """
    你是知识整理助手。只根据已经通过 Source Candidate Gate 或已获人工转换许可的 Source Material v3 生成一篇 learning_note Markdown 草稿。

    工作流草稿：
    \(draftPath)

    生成计划：
    \(planPath)

    唯一事实主输入 Source Material v3：
    \(sourceMaterialPath)

    \(readableInstruction)

    \(sidecarInstruction)

    Source Material 是事实权威。保留 Material ID、Revision ID、Manifest 引用和原始来源；结构必须包含 # 标题、## 来源、## 核心概念、## 关键知识点、## 内容整理、## 实践价值、## 参考资料；不添加来源没有的事实，不编造案例；AI 归纳必须能回指 Source Material，信息不足明确写“素材未提供相关信息”。只输出 Markdown 正文，不要解释，不要修改任何文件。
    """
}

func sourceMaterialPromptV2(draftPath: String, planPath: String, sourceMaterialPath: String, readableSourcePath: String?, sidecarPath: String?) throws -> String {
    let policyPath = argument("--prompt-file") ?? FileManager.default.currentDirectoryPath + "/core/prompt/learning-note-generation-v2.md"
    let policy: String
    do { policy = try String(contentsOf: URL(fileURLWithPath: policyPath), encoding: .utf8) }
    catch { throw EngineError.invalid("learning-note-generation-v2 prompt unavailable: \(policyPath)") }
    let sidecarInstruction: String
    if let sidecarPath {
        sidecarInstruction = "可选 Understanding Sidecar：\n\(sidecarPath)\nSidecar 只能帮助组织结构；任何无法回指 Source 的内容必须忽略。"
    } else {
        sidecarInstruction = "本次没有 Understanding Sidecar；不得因此补写外部事实。"
    }
    let readableInstruction = readableSourcePath.map { "可读来源正文（唯一可读事实正文）：\n\($0)" } ?? "没有额外可读正文；只能依据 Source Material 中可追溯事实。"
    return """
    \(policy)

    ## 本次输入

    工作流草稿：\(draftPath)
    生成计划：\(planPath)
    Source Material v3：\(sourceMaterialPath)
    \(readableInstruction)
    \(sidecarInstruction)

    只读取上述本地输入并输出一篇 Markdown Learning Note。不要解释执行过程，不要创建或修改任何文件。
    """
}

func runCodex(prompt: String, outputPath: String, model: String) throws -> String {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/Applications/ChatGPT.app/Contents/Resources/codex")
    process.arguments = ["exec", "--ephemeral", "--sandbox", "read-only", "--skip-git-repo-check", "-C", FileManager.default.currentDirectoryPath, "-m", model, "-o", outputPath, prompt]
    let stderrPipe = Pipe(); process.standardError = stderrPipe
    try process.run(); process.waitUntilExit()
    guard process.terminationStatus == 0 else {
        let errorText = String(data: stderrPipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? "unknown codex error"
        throw EngineError.invalid("Codex provider failed: \(errorText.suffix(1000))")
    }
    return try String(contentsOf: URL(fileURLWithPath: outputPath), encoding: .utf8)
}

func markdown(draft: AssetDraft, understanding: VideoUnderstandingPackageInput, qualityReference: String) -> String {
    let references = Array(Set([draft.source.sourceReference, understanding.sourceReference] + draft.content.references)).sorted()
    let referenceLines = references.map { "- \($0)" }.joined(separator: "\n")
    return """
# \(draft.content.title)

## 来源

- 原始链接：\(draft.source.sourceReference)
- Material ID：\(draft.source.materialID)
- Task ID：\(draft.source.taskID)
- Video Understanding Package 来源：\(understanding.sourceReference)

## 核心概念

本地回退未生成知识正文。不得将回退结果视为来源内容。

## 关键知识点

- 状态：`fallback_no_content`
- 原因：本地回退模式不具备可靠的知识生成能力
- 后续：需要真实生成结果或人工整理后再进入确认流程

## 内容解释

当前仅保留来源与协议引用，不补写来源未提供的事实。

## 实践价值

未生成；请在人工确认前完成可靠内容整理。

## 参考来源

\(referenceLines)

## 生成状态

- 资产 ID：\(draft.asset.assetID)
- 生成模板：\(draft.asset.type)
- 生成方法：明确回退标记（未生成知识正文）
- 回退状态：`fallback_no_content`
- 模型：未调用
- 用户确认：待确认
- 质量评估引用：\(qualityReference)
"""
}
func sourceMaterialMarkdown(draft: AssetDraft, sourceMaterial: SourceMaterialV3Input, sidecar: UnderstandingSidecarInput?, qualityReference: String) -> String {
    let sidecarLine = sidecar.map { "- Understanding Sidecar：\($0.sidecarID)（validated，可选参考）" } ?? "- Understanding Sidecar：未提供"
    return """
# \(draft.content.title)

## 来源

- 原始链接：\(sourceMaterial.source.sourceURL)
- Source Material：\(sourceMaterial.materialID)
- Revision：\(sourceMaterial.revisionID)
- Asset Manifest：\(sourceMaterial.assetManifestReference)
\(sidecarLine)

## 核心概念

本地回退未生成知识正文。不得将回退结果视为来源内容。

## 关键知识点

- 状态：`fallback_no_content`
- 原因：本地回退模式不具备可靠的知识生成能力
- 后续：需要真实生成结果或人工整理后再进入确认流程

## 内容整理

当前仅保留 Source Material 与可选 Sidecar 引用，不补写来源未提供的事实。

## 实践价值

未生成；请在人工确认前完成可靠内容整理。

## 参考资料

- \(sourceMaterial.source.sourceURL)
- \(sourceMaterial.assetManifestReference)

## 生成状态

- 资产 ID：\(draft.asset.assetID)
- Material ID：\(sourceMaterial.materialID)
- Revision ID：\(sourceMaterial.revisionID)
- 生成方法：明确回退标记（未生成知识正文）
- 回退状态：`fallback_no_content`
- 模型：未调用
- 用户确认：待确认
- 质量评估引用：\(qualityReference)
"""
}

func firstHeading(_ markdown: String) -> String? {
    for rawLine in markdown.components(separatedBy: .newlines) {
        let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
        if line.hasPrefix("# ") {
            let title = String(line.dropFirst(2)).trimmingCharacters(in: .whitespacesAndNewlines)
            return title.isEmpty ? nil : title
        }
    }
    return nil
}

func inferredLanguage(_ text: String) -> String {
    var han = 0
    var latin = 0
    for scalar in text.unicodeScalars {
        switch scalar.value {
        case 0x4E00...0x9FFF: han += 1
        case 65...90, 97...122: latin += 1
        default: break
        }
    }
    if han > max(20, latin / 2) { return "zh-CN" }
    if latin > max(20, han * 2) { return "en" }
    return "unknown"
}

func meaningfulSections(_ markdown: String) -> [String] {
    var sections: [String] = []
    var current: [String] = []
    var ignored = false
    func flush() {
        let value = current.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
        if !ignored && value.count >= 80 { sections.append(value) }
        current = []
    }
    for line in markdown.components(separatedBy: .newlines) {
        if line.hasPrefix("## ") {
            flush()
            let heading = String(line.dropFirst(3))
            ignored = ["来源", "参考", "生成状态", "Provenance"].contains { heading.localizedCaseInsensitiveContains($0) }
        } else if !line.hasPrefix("# ") {
            current.append(line)
        }
    }
    flush()
    return sections
}

func normalizedCharacters(_ text: String) -> [Character] {
    Array(text.lowercased().filter { character in
        character.isLetter || character.isNumber
    })
}

func shingles(_ text: String, width: Int = 5) -> Set<String> {
    let characters = normalizedCharacters(text)
    guard characters.count >= width else { return Set([String(characters)]) }
    return Set((0...(characters.count - width)).map { String(characters[$0..<($0 + width)]) })
}

func redundancyLevel(_ markdown: String) -> String {
    let sections = meaningfulSections(markdown)
    guard sections.count >= 2 else { return "low" }
    var maximum = 0.0
    for leftIndex in 0..<sections.count {
        for rightIndex in (leftIndex + 1)..<sections.count {
            let left = shingles(sections[leftIndex])
            let right = shingles(sections[rightIndex])
            guard !left.isEmpty, !right.isEmpty else { continue }
            let overlap = Double(left.intersection(right).count) / Double(min(left.count, right.count))
            maximum = max(maximum, overlap)
        }
    }
    if maximum >= 0.58 { return "high" }
    if maximum >= 0.34 { return "medium" }
    return "low"
}

func cognitiveSignals(_ markdown: String) -> [String] {
    let groups: [(String, [String])] = [
        ("structural_abstraction", ["机制", "结构", "模型", "路径", "链条", "因果", "约束", "变量"]),
        ("concept_relationship", ["关系", "相互", "导致", "推动", "承接", "转向", "依赖", "前提"]),
        ("concept_distinction", ["区别", "区分", "不是", "而是", "层次"]),
        ("reusable_insight", ["可复用", "观察框架", "判断框架", "分析框架", "用于分析", "迁移"]),
    ]
    return groups.compactMap { name, markers in markers.contains(where: { markdown.contains($0) }) ? name : nil }
}

func sourceBoundaryStatus(_ markdown: String) -> String {
    let attributed = ["来源主张", "来源认为", "材料认为", "作者认为", "素材认为"].contains { markdown.contains($0) }
    let bounded = ["待核验", "未经核验", "来源边界", "不确定", "未提供", "尚未验证"].contains { markdown.contains($0) }
    return attributed && bounded ? "passed" : "insufficient"
}

struct AuthorityBoundaryCheck {
    let status: String
    let aiCandidateSections: [String]
    let sourceClaimLabeling: String
    let userConfirmedView: String
}

func authorityBoundaryCheck(_ markdown: String) -> AuthorityBoundaryCheck {
    let headings = markdown.split(separator: "\n", omittingEmptySubsequences: false).compactMap { line -> String? in
        let value = line.trimmingCharacters(in: .whitespaces)
        guard value.hasPrefix("## "), !value.hasPrefix("### ") else { return nil }
        return String(value.dropFirst(3)).trimmingCharacters(in: .whitespaces)
    }
    let aiLabels = ["AI结构化", "AI Structural Synthesis", "AI_candidate"]
    let derivedMarkers = ["认知核", "可复用", "理解框架", "分析框架", "分析问题", "机制模型", "机制链", "概念对照", "论证推进", "结构性洞见"]
    let sourceClaimMarkers = ["来源主张", "作者观点", "材料主张", "Source Claim"]
    let isAILabeled: (String) -> Bool = { heading in aiLabels.contains { heading.localizedCaseInsensitiveContains($0) } }
    let derived = headings.filter { heading in derivedMarkers.contains { heading.localizedCaseInsensitiveContains($0) } }
    let candidates = headings.filter(isAILabeled)
    let sourceClaims = headings.filter { heading in sourceClaimMarkers.contains { heading.localizedCaseInsensitiveContains($0) } }
    let sourceClaimLabeling = sourceClaims.contains(where: isAILabeled) ? "misclassified_as_ai_candidate" : "passed"
    let hasUnlabeledDerived = derived.contains { !isAILabeled($0) }
    let userMarkers = ["User Confirmed View", "user_confirmed", "用户确认观点", "用户已确认", "我的观点", "我的理解"]
    let hasUserConfirmed = userMarkers.contains { markdown.localizedCaseInsensitiveContains($0) }
    let userConfirmedAllowed = argument("--user-confirmed-view") == "true"
    let userStatus = hasUserConfirmed ? (userConfirmedAllowed ? "grounded" : "unverified") : "not_present"
    let status = !hasUnlabeledDerived && !candidates.isEmpty && sourceClaimLabeling == "passed" && userStatus != "unverified" ? "passed" : "failed"
    return AuthorityBoundaryCheck(status: status, aiCandidateSections: candidates, sourceClaimLabeling: sourceClaimLabeling, userConfirmedView: userStatus)
}

func regexMatches(_ pattern: String, in text: String) -> Set<String> {
    guard let regex = try? NSRegularExpression(pattern: pattern) else { return [] }
    let range = NSRange(text.startIndex..<text.endIndex, in: text)
    return Set(regex.matches(in: text, range: range).compactMap { match in
        Range(match.range, in: text).map { String(text[$0]) }
    })
}

func unsupportedNumbers(output: String, source: String) -> [String] {
    let pattern = #"(?<![A-Za-z0-9_])[0-9]+(?:\.[0-9]+)?%?(?![A-Za-z0-9_])"#
    let sourceTokens = regexMatches(pattern, in: source)
    let enumeration = try? NSRegularExpression(pattern: #"(?m)^\s*[0-9]+[\.、]\s*"#)
    let range = NSRange(output.startIndex..<output.endIndex, in: output)
    let semanticOutput = enumeration?.stringByReplacingMatches(in: output, range: range, withTemplate: "") ?? output
    return regexMatches(pattern, in: semanticOutput).subtracting(sourceTokens).filter { token in
        guard token.hasSuffix("%"), let value = Int(token.dropLast()), (0...100).contains(value) else { return true }
        let digits = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
        let chinese: String
        if value < 10 { chinese = digits[value] }
        else if value == 10 { chinese = "十" }
        else if value < 20 { chinese = "十" + digits[value % 10] }
        else if value < 100 { chinese = digits[value / 10] + "十" + (value % 10 == 0 ? "" : digits[value % 10]) }
        else { chinese = "一百" }
        return !source.contains("百分之" + chinese) && !source.contains("百分之" + String(value))
    }.sorted()
}

func missingInformation(source: SourceMaterialV3Input) -> [String] {
    var missing: [String] = []
    let title = (source.source.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    if title.isEmpty || title == "unknown" || title == "null" { missing.append("来源标题未知") }
    let author = (source.source.author ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    if author.isEmpty || author == "unknown" || author == "null" { missing.append("来源作者未知") }
    if (source.quality.uncertainties ?? []).contains(where: {
        let value = $0.lowercased()
        return value.contains("unreviewed") || value.contains("recognition") || value.contains("听辨") || value.contains("识别")
    }) {
        missing.append("ASR/转写尚未人工复核，局部听辨可能不准确")
    }
    return Array(Set(missing)).sorted()
}

func qualityReport(markdown: String, source: SourceMaterialV3Input?, sourceText: String, provider: String, promptVersion: String) -> QualityReport {
    if provider == "local" {
        return QualityReport(generationQualityCheck: GenerationQualityCheck(
            sourceTraceability: "high", contentCompleteness: "insufficient", hallucinationRisk: "not_applicable",
            missingInformation: ["本地回退未生成知识正文", "需要真实生成结果或人工整理"],
            intentionalScopeBoundaries: ["external_verification_not_requested"], sourceLanguage: "unknown", outputLanguage: "unknown",
            translationRequired: false, semanticRedundancy: "not_applicable", cognitiveDelta: "insufficient_cognitive_delta",
            cognitiveDeltaSignals: [], groundingStatus: "not_applicable", unsupportedFactualExpansions: [], sourceBoundary: "not_applicable",
            authorityBoundary: "not_applicable", aiCandidateSections: [], sourceClaimLabeling: "not_applicable", userConfirmedView: "not_present",
            generatedTitle: "", titleConsistency: "failed", publishable: false, blockingReasons: ["fallback_no_content"], method: "local_fallback_no_content"))
    }
    let sourceLanguage = argument("--source-language") ?? source?.source.language ?? inferredLanguage(sourceText)
    let outputLanguage = argument("--output-language") ?? inferredLanguage(markdown)
    let translationRequired = argument("--translation-required") == "true" ||
        (argument("--translation-policy") == "required" && sourceLanguage != "unknown" && outputLanguage != "unknown" && sourceLanguage != outputLanguage)
    let title = firstHeading(markdown) ?? ""
    let titleValid = !title.isEmpty && title.lowercased() != "unknown" && !title.hasPrefix("#")
    let redundancy = redundancyLevel(markdown)
    let signals = cognitiveSignals(markdown)
    let cognitive = signals.count >= 2 ? "passed" : "insufficient_cognitive_delta"
    let unsupported = unsupportedNumbers(output: markdown, source: sourceText)
    let grounding = unsupported.isEmpty ? "passed" : "failed"
    let boundary = sourceBoundaryStatus(markdown)
    let authority = authorityBoundaryCheck(markdown)
    var reasons: [String] = []
    if !titleValid { reasons.append("generation_metadata_inconsistent") }
    if redundancy == "high" { reasons.append("semantic_redundancy_high") }
    if cognitive != "passed" { reasons.append("insufficient_cognitive_delta") }
    if grounding != "passed" { reasons.append("unsupported_factual_expansion") }
    if boundary != "passed" { reasons.append("source_boundary_missing") }
    if authority.status != "passed" { reasons.append("authority_boundary_missing_or_invalid") }
    return QualityReport(generationQualityCheck: GenerationQualityCheck(
        sourceTraceability: grounding == "passed" ? "high" : "insufficient",
        contentCompleteness: reasons.isEmpty ? "high" : "medium",
        hallucinationRisk: grounding == "passed" ? "low" : "high",
        missingInformation: source.map(missingInformation) ?? [],
        intentionalScopeBoundaries: ["external_verification_not_requested"],
        sourceLanguage: sourceLanguage, outputLanguage: outputLanguage, translationRequired: translationRequired,
        semanticRedundancy: redundancy, cognitiveDelta: cognitive, cognitiveDeltaSignals: signals,
        groundingStatus: grounding, unsupportedFactualExpansions: unsupported, sourceBoundary: boundary,
        authorityBoundary: authority.status, aiCandidateSections: authority.aiCandidateSections,
        sourceClaimLabeling: authority.sourceClaimLabeling, userConfirmedView: authority.userConfirmedView,
        generatedTitle: title, titleConsistency: titleValid ? "passed" : "failed", publishable: reasons.isEmpty,
        blockingReasons: reasons, method: promptVersion == "learning-note-generation-v2" ? "source_grounded_cognitive_compression" : "source_preserving_generation"))
}

@main
struct KnowledgeGenerationEngineMain {
    static func main() {
        do {
            let draft = try read(AssetDraft.self, path: try required("--draft"))
            let plan = try read(Plan.self, path: try required("--plan"))
            guard draft.protocolName == "knowledge-asset-draft-v1" else { throw EngineError.invalid("draft protocol mismatch") }
            guard plan.protocolName == "knowledge-generation-v1" else { throw EngineError.invalid("generation plan protocol mismatch") }
            guard draft.asset.type == "learning_note", plan.generation.assetType == "learning_note", plan.generation.template == "learning_note" else { throw EngineError.invalid("MVP only supports learning_note") }
            guard draft.asset.status == "draft", draft.review.confirmed == false, plan.output.needConfirmation else { throw EngineError.invalid("draft must remain unconfirmed") }
            guard draft.asset.assetID == plan.input.assetDraftID, draft.source.materialID == plan.input.materialID, draft.source.sourceReference == plan.input.sourceReference else { throw EngineError.invalid("draft and plan reference mismatch") }
            let outputPath = try required("--output")
            let qualityReference = argument("--quality-reference") ?? "待生成"
            let provider = argument("--provider") ?? "local"
            let model = argument("--model") ?? "none"
            let generatedAt = ISO8601DateFormatter().string(from: Date())
            let sourceMaterialPath = argument("--source-material")
            let legacyUnderstandingPath = argument("--understanding-package")
            let promptVersion = argument("--prompt-version") ?? (sourceMaterialPath == nil ? "learning-note-generation-v1" : "learning-note-generation-v2")
            guard ["learning-note-generation-v1", "learning-note-generation-v2"].contains(promptVersion) else {
                throw EngineError.invalid("unsupported learning prompt version: \(promptVersion)")
            }
            guard sourceMaterialPath != nil || legacyUnderstandingPath != nil else { throw EngineError.usage }
            guard !(sourceMaterialPath != nil && legacyUnderstandingPath != nil) else { throw EngineError.invalid("use source-material mode or legacy understanding-package mode, not both") }
            if legacyUnderstandingPath != nil && argument("--legacy-replay") != "true" {
                throw EngineError.invalid("--understanding-package is blocked in production; historical replay requires --legacy-replay true")
            }
            let generatedText: String
            let generationInputs: [String]
            var sourceForQuality: SourceMaterialV3Input?
            var sourceTextForQuality = ""
            if let sourceMaterialPath {
                let sourceMaterial = try read(SourceMaterialV3Input.self, path: sourceMaterialPath)
                sourceForQuality = sourceMaterial
                let sourceValidationPath = try required("--source-validation")
                let sourceValidation = try read(SourceValidationReceipt.self, path: sourceValidationPath)
                guard sourceMaterial.protocolName == "source-material-v3", sourceMaterial.schemaVersion == "3.0.0" else { throw EngineError.invalid("knowledge generation requires source-material-v3 schema 3.0.0") }
                let validationPassed = sourceValidation.status == "valid" || sourceValidation.status == "passed"
                let manifestPassed = sourceValidation.manifestStatus == nil || sourceValidation.manifestStatus == "valid" || sourceValidation.manifestStatus == "verified"
                guard validationPassed, manifestPassed else { throw EngineError.invalid("source material requires successful schema and reference validation") }
                guard sourceValidation.materialID == sourceMaterial.materialID, sourceValidation.revisionID == sourceMaterial.revisionID else { throw EngineError.invalid("source validation receipt does not match material revision") }
                guard sourceMaterial.quality.reviewRequired else { throw EngineError.invalid("source material must retain review_required=true") }
                let candidateGeneration = argument("--candidate-generation") == "true"
                guard sourceMaterial.lifecycle.reviewStatus == "convert_approved" || candidateGeneration else { throw EngineError.invalid("source material requires human convert_approved or candidate-generation true") }
                guard draft.source.materialID == sourceMaterial.materialID, plan.input.materialID == sourceMaterial.materialID else { throw EngineError.invalid("source material_id mismatch") }
                guard draft.source.sourceReference == sourceMaterial.source.sourceURL else { throw EngineError.invalid("source material source_url mismatch") }
                let sidecarPath = argument("--understanding-sidecar")
                let sidecar: UnderstandingSidecarInput?
                if let sidecarPath {
                    let value = try read(UnderstandingSidecarInput.self, path: sidecarPath)
                    guard value.protocolName == "understanding-sidecar-v1", value.schemaVersion == "1.0.0" else { throw EngineError.invalid("optional sidecar protocol mismatch") }
                    guard value.status == "validated" else { throw EngineError.invalid("optional sidecar must be validated") }
                    guard value.materialID == sourceMaterial.materialID, value.revisionID == sourceMaterial.revisionID else { throw EngineError.invalid("optional sidecar source revision mismatch") }
                    sidecar = value
                } else {
                    sidecar = nil
                }
                let readableSourcePath = argument("--readable-source")
                sourceTextForQuality = (try? String(contentsOf: URL(fileURLWithPath: sourceMaterialPath), encoding: .utf8)) ?? ""
                if let readableSourcePath {
                    sourceTextForQuality += "\n" + ((try? String(contentsOf: URL(fileURLWithPath: readableSourcePath), encoding: .utf8)) ?? "")
                }
                switch provider {
                case "codex":
                    let prompt = promptVersion == "learning-note-generation-v2"
                        ? try sourceMaterialPromptV2(draftPath: argument("--draft") ?? "", planPath: argument("--plan") ?? "", sourceMaterialPath: sourceMaterialPath, readableSourcePath: readableSourcePath, sidecarPath: sidecarPath)
                        : sourceMaterialPromptV1(draftPath: argument("--draft") ?? "", planPath: argument("--plan") ?? "", sourceMaterialPath: sourceMaterialPath, readableSourcePath: readableSourcePath, sidecarPath: sidecarPath)
                    generatedText = try runCodex(prompt: prompt, outputPath: outputPath + ".model.md", model: model)
                case "file", "codex-replay": generatedText = try String(contentsOf: URL(fileURLWithPath: try required("--llm-output")), encoding: .utf8)
                case "local": generatedText = sourceMaterialMarkdown(draft: draft, sourceMaterial: sourceMaterial, sidecar: sidecar, qualityReference: qualityReference)
                default: throw EngineError.invalid("provider must be codex, codex-replay, file, or local")
                }
                generationInputs = [argument("--draft") ?? "", argument("--plan") ?? "", sourceMaterialPath, sourceValidationPath] + (sidecarPath.map { [$0] } ?? [])
            } else {
                let understandingPath = legacyUnderstandingPath!
                let understanding = try read(VideoUnderstandingPackageInput.self, path: understandingPath)
                guard understanding.protocolName == "video-understanding-package-v1" else { throw EngineError.invalid("legacy mode requires video-understanding-package-v1") }
                guard understanding.status == "ready" else { throw EngineError.invalid("video understanding package is not ready for generation") }
                let gate = understanding.knowledgeGenerationGate
                guard gate.status != "blocked" else { throw EngineError.invalid("video understanding package gate blocked: \(gate.reasons.joined(separator: ","))") }
                if gate.status == "warning" && argument("--understanding-confirmed") != "true" { throw EngineError.invalid("video understanding package requires confirmation; pass --understanding-confirmed true") }
                guard draft.source.taskID == understanding.taskID else { throw EngineError.invalid("task_id mismatch") }
                guard draft.source.sourceReference == understanding.sourceReference else { throw EngineError.invalid("source_reference mismatch") }
                guard !understanding.mainTopic.statement.isEmpty, !understanding.coreClaims.isEmpty, !understanding.argumentStructure.isEmpty else { throw EngineError.invalid("video understanding package is incomplete") }
                switch provider {
                case "codex": generatedText = try runCodex(prompt: legacyPrompt(draftPath: argument("--draft") ?? "", planPath: argument("--plan") ?? "", understandingPackagePath: understandingPath), outputPath: outputPath + ".model.md", model: model)
                case "file", "codex-replay": generatedText = try String(contentsOf: URL(fileURLWithPath: try required("--llm-output")), encoding: .utf8)
                case "local": generatedText = markdown(draft: draft, understanding: understanding, qualityReference: qualityReference)
                default: throw EngineError.invalid("provider must be codex, codex-replay, file, or local")
                }
                generationInputs = [argument("--draft") ?? "", argument("--plan") ?? "", understandingPath]
            }
            let finalText: String
            if provider == "local" { finalText = generatedText } else {
                if promptVersion == "learning-note-generation-v1" {
                    guard generatedText.contains("## 来源"), generatedText.contains("## 参考资料") else { throw EngineError.invalid("model output does not match learning_note v1 structure") }
                    finalText = generatedText + "\n\n## 生成状态\n\n- 资产 ID：\(draft.asset.assetID)\n- Material ID：\(draft.source.materialID)\n- 生成模型：\(model)\n- Prompt 版本：\(promptVersion)\n- 用户确认：待确认\n- 质量评估引用：\(qualityReference)\n"
                } else {
                    guard let generatedTitle = firstHeading(generatedText), generatedTitle.lowercased() != "unknown" else {
                        throw EngineError.invalid("learning_note v2 requires one non-empty generated H1 title")
                    }
                    finalText = generatedText.trimmingCharacters(in: .whitespacesAndNewlines) + "\n"
                }
            }
            try writeText(finalText, path: outputPath)
            let quality = qualityReport(markdown: finalText, source: sourceForQuality, sourceText: sourceTextForQuality, provider: provider, promptVersion: promptVersion)
            try write(quality, path: try required("--quality"))
            let metadataPath = try required("--metadata")
            let qualityPath = try required("--quality")
            let metadata = GenerationMetadata(modelName: model, modelVersion: argument("--model-version") ?? "unknown", generatedAt: generatedAt, promptVersion: promptVersion, provider: provider)
            try write(metadata, path: metadataPath)
            let record = GenerationRecord(assetID: draft.asset.assetID, model: model, promptVersion: promptVersion, inputReference: generationInputs, outputReference: outputPath, qualityReference: qualityPath, status: "generated", confirmationStatus: "waiting_confirmation")
            try write(record, path: try required("--record"))
            print("DRAFT=\(outputPath)")
            print("QUALITY=\(try required("--quality"))")
            print("ASSET_ID=\(draft.asset.assetID)")
            print("MATERIAL_ID=\(draft.source.materialID)")
        } catch { fputs("ERROR: \(error.localizedDescription)\n", stderr); exit(3) }
    }
}
