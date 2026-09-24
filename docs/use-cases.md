# From a YouTube Link to Reusable Knowledge

[简体中文](use-cases.zh-CN.md) · [Back to README](../README.md) · [Architecture](architecture.md) · [Provider limits](providers.md)

> The video title, content and notes in this guide are an illustrative example. They do not refer to a real channel, author or video. In actual use, paste a video URL that you are permitted to access.

## Why use Guanlan?

A bookmark answers “where did I leave that video?” It does not necessarily answer “what did I learn from it?” A month after watching an hour-long video, recalling one useful idea may still mean reopening the video, scrubbing through it and reconstructing the context.

Guanlan turns that experience into a reviewable knowledge workflow. It preserves the source, separates readable source material from AI-derived knowledge, lets you decide what deserves formal publication, and can later connect formal assets when there is enough evidence for a useful relationship. A Learning Note makes review faster; it does not replace the source when wording, context or qualifications matter.

## One complete YouTube workflow

Imagine that I find an illustrative video titled **“How Can We Tell Whether a Claim Is Supported by Evidence?”** My goal is not to have AI publish a conclusion for me. I want to retain the source, review a note that takes minutes to read, and decide what enters my knowledge base.

### 1. Give the video to Guanlan

I copy the link and, in a Codex environment where Guanlan orchestration and a suitable capture tool have already been configured, send:

```text
Capture
<YouTube video URL>
```

In a Chinese-configured environment the user-level instruction is `采集`. This is a natural-language orchestration example, **not a CLI command automatically installed into every Codex environment by this repository**. Users must configure their own Codex workflow, Vault paths and available Providers.

Capture should collect verifiable source facts rather than publish a Learning Note. A qualifying result becomes a review projection in `00 收件箱` and may retain the title, original URL, available subtitles or transcript, evidence references, quality and missing-content information, and stable source identity.

YouTube support is environment-dependent. It can require an external downloader, network and source permissions, usable subtitles, or separately configured transcription. If a Provider is unavailable, access is restricted, or evidence is insufficient, the workflow should stop or request the missing condition. It must not disguise an AI guess as video source material. See [Provider limits](providers.md).

### 2. Organize the source

Once the capture has readable content, evidence and a passing quality result, I identify that inbox item and ask the configured orchestration layer to organize it:

```text
Organize
The inbox item “How Can We Tell Whether a Claim Is Supported by Evidence?”
```

The Chinese user-level instruction is `整理`. If several items are waiting, I must identify the intended item or Source rather than asking the system to guess. Organize creates a Candidate Bundle in `awaiting_user_confirmation`; it does not write formal assets. The Bundle can contain:

- a Source Candidate faithful to the captured material;
- an independently identified Learning Note Candidate;
- honest decisions that another asset type is inapplicable, blocked or needs more evidence.

Organizing is not merely squeezing a transcript into one paragraph. It first protects a readable source, then produces reviewable derivative candidates. The fragment below is entirely illustrative—not a transcript or summary of a real video:

```markdown
# How Can We Tell Whether a Claim Is Supported by Evidence?

## Core question

How do we distinguish a persuasive-sounding claim from one supported by evidence?

## Source claims

- A claim is not itself evidence.
- Evaluating an argument requires checking where its evidence comes from.
- Evidence can differ in reliability and scope.

## Reusable understanding framework | AI structural synthesis

Guanlan derived this AI_candidate structure from the source; the source did not
necessarily state it step by step: identify the claim, then examine provenance,
scope and uncertainty of the evidence.

## Source

A stable reference to the captured Source Asset and its evidence.
```

The candidate is faster to revisit than an isolated link. When exact wording, qualifications or context matter, I still follow its source reference. A time index can be retained when the evidence provides one, but the workflow does not promise a precise timestamp link for every note.

### 3. Review before publishing

A Candidate is not knowledge that Guanlan has declared correct. I review whether:

- the Source Candidate is faithful and free of injected AI opinion;
- the Learning Candidate misunderstands or omits something important;
- AI-labelled summaries and abstractions are reasonable;
- each candidate is worth keeping as a formal asset.

The configured interface or orchestration layer should show the current Candidate Bundle and its Candidate IDs. I can approve all displayed `publishable` candidates or explicitly exclude one. A user-level exchange might be:

```text
Approve the displayed Source Candidate and Learning Note Candidate in this Candidate Bundle.
Publish (`入库`).
```

This is again an orchestration example, not a standalone public CLI. Before writing, the Publisher revalidates the Candidate identity, Source revision, content hash, quality gate and approval binding. The exact content I approved is the content eligible for publication. A candidate marked `needs_corroboration`, `needs_validation`, `blocked` or `not_applicable` cannot bypass its gate merely because I said “publish.”

### 4. What appears in the knowledge base

This example mainly involves three locations:

- `00 收件箱`: a work queue awaiting review, not a formal asset class;
- `10 原始资料`: the confirmed, traceable Source Asset;
- `20 学习笔记`: the confirmed Learning Note for quick reading and reuse.

Source and Learning are different assets. A Learning Note does not overwrite the Source, and AI structural synthesis cannot be written back as if it were the author's words. Stable references let quick review and source verification coexist. See [Architecture](architecture.md) for the complete directory model.

### 5. Curate relationships when useful

Suppose the Vault already contains another illustrative formal note: **“How to Recognize Common Biases in Research Material.”** It may be relevant to the new note, but a shared title word or topic is not enough to create a formal relationship.

In a configured Codex environment I can explicitly trigger the user operation `整理关系图谱` (“curate the relation graph”). Relation Curation scans eligible formal assets and uses stable identity plus semantic evidence. Strong, high-confidence relationships that pass the governance gate can be executed; Medium candidates enter the Observation Pool without a formal Markdown projection; Weak matches are filtered. The Relation Registry is the relationship fact store, while Obsidian links are projections for navigation.

If the two illustrative notes actually met the current evidence standard, the browsing idea could be pictured as:

```text
Learning Note A: Is this claim supported by evidence?
                         ↕
Learning Note B: What biases affect research material?
```

This diagram is only a conceptual illustration. It does not claim that a real Vault or the public repository contains this relationship, and Guanlan does not connect every similar-looking article.

## How this becomes useful over time

Weeks later, I may find an article about evaluating evidence. I can capture, organize, review and publish it through the same boundary, then curate relationships when warranted. The new item is no longer just another saved link: it can become part of a verified path through prior knowledge, while every asset keeps its own source trail.

## Before you begin

The real YouTube scenario requires configured Codex orchestration, a Vault, external capture tools, source permission, and usable subtitles or transcription. Real AI organization also depends on a model environment supplied by the user. The public repository verifies the core contracts, empty-Vault initialization, and a synthetic Source/Candidate/Publish/Relation flow; it has not reproduced a complete real-user production installation with every optional Provider in a clean environment.

Read the [project README](../README.md), [Provider limits](providers.md) and [Architecture](architecture.md) before connecting real sources.

## Try the core workflow now

If you do not want to configure a YouTube Provider yet, run the README's [isolated synthetic workflow](../README.md#quick-start-isolated-synthetic-workflow) or inspect the [demo script](../examples/synthetic-demo/run_demo.py).

The demo uses an invented Source, a prewritten Candidate and synthetic test approval. It does not access YouTube, call a paid model, log into a platform or demonstrate a completed real-user production deployment.
