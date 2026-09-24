#!/usr/bin/env node

/**
 * Authenticated Douyin browser capture provider.
 *
 * This module deliberately stops at a validated local media file plus the
 * existing capture-protocol-v2 result.  It never reads browser cookies and it
 * never persists signed media URLs or request headers.
 */

import { createHash, randomUUID } from "node:crypto";
import { createReadStream, createWriteStream } from "node:fs";
import {
  access,
  chmod,
  mkdir,
  readFile,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { pipeline } from "node:stream/promises";
import { pathToFileURL } from "node:url";

const PROFILE_MARKER = ".guanlan-profile.json";
const AUTH_MARKER = ".guanlan-authenticated.json";
const DEFAULT_PORT = 9224;
const DEFAULT_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const DEFAULT_PROFILE = path.join(
  os.homedir(),
  "Library",
  "Application Support",
  "Guanlan",
  "douyin-browser-profile",
);
const DEFAULT_RUNTIME = path.join(
  os.homedir(),
  "Library",
  "Application Support",
  "Guanlan",
  "runtime",
  "capture",
);
const DOUYIN_HOME = "https://www.douyin.com/";
const USER_AGENT =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " +
  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36";

export const FAILURE_CODES = Object.freeze([
  "ambiguous_input",
  "unsupported_input",
  "auth_required",
  "auth_expired",
  "page_access_failed",
  "page_identity_mismatch",
  "content_deleted",
  "content_private",
  "unsupported_content_type",
  "anti_bot",
  "media_not_playing",
  "video_response_failed",
  "audio_response_failed",
  "media_capture_failed",
  "invalid_media",
  "disk_write_failed",
  "browser_interrupted",
  "unsafe_output_path",
]);

const STAGE_FAILURE_CODES = Object.freeze({
  short_link_redirect: "page_access_failed",
  page_404: "content_deleted",
  login_wall: "auth_required",
  expired_login_wall: "auth_expired",
  challenge: "anti_bot",
  playback: "media_not_playing",
  video_response: "video_response_failed",
  audio_response: "audio_response_failed",
  ffmpeg: "media_capture_failed",
  ffprobe: "invalid_media",
  disk_write: "disk_write_failed",
  browser_process: "browser_interrupted",
});

export function failureCodeForStage(stage) {
  const code = STAGE_FAILURE_CODES[stage];
  if (!code) throw new Error(`unknown capture stage: ${stage}`);
  return code;
}

class CaptureError extends Error {
  constructor(code, message = code) {
    super(message);
    this.name = "CaptureError";
    this.code = code;
  }
}

function nowIso() {
  return new Date().toISOString();
}

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function parseOptions(argv) {
  const options = { _: [] };
  for (let index = 0; index < argv.length; index += 1) {
    const item = argv[index];
    if (!item.startsWith("--")) {
      options._.push(item);
      continue;
    }
    const key = item.slice(2);
    const value = argv[index + 1];
    if (value === undefined || value.startsWith("--")) {
      options[key] = true;
    } else {
      options[key] = value;
      index += 1;
    }
  }
  return options;
}

function normalizeInputUrl(value) {
  return value.replace(/[\s，。；、】）》」』]+$/u, "");
}

export function extractDouyinInput(originalInput) {
  if (typeof originalInput !== "string" || !originalInput.trim()) {
    throw new CaptureError("unsupported_input", "input is empty");
  }
  const matches = originalInput.match(/https:\/\/[^\s<>"']+/giu) ?? [];
  const accepted = [];
  for (const candidate of matches) {
    const normalized = normalizeInputUrl(candidate);
    let parsed;
    try {
      parsed = new URL(normalized);
    } catch {
      continue;
    }
    const host = parsed.hostname.toLowerCase();
    const shortLink = host === "v.douyin.com" && /^\/[A-Za-z0-9_-]+\/?$/.test(parsed.pathname);
    const workLink =
      (host === "douyin.com" || host === "www.douyin.com") &&
      /^\/video\/\d+\/?$/.test(parsed.pathname);
    if (shortLink || workLink) accepted.push(parsed.toString());
  }
  const distinct = [...new Set(accepted)];
  if (distinct.length > 1) {
    throw new CaptureError("ambiguous_input", "multiple Douyin URLs found");
  }
  if (distinct.length === 0) {
    throw new CaptureError("unsupported_input", "no supported Douyin work URL found");
  }
  const extractedUrl = distinct[0];
  return {
    originalInput,
    extractedUrl,
    contentId: contentIdFromUrl(extractedUrl),
  };
}

export function contentIdFromUrl(value) {
  try {
    const pathname = new URL(value).pathname;
    return pathname.match(/\/(?:video|share\/video)\/(\d+)/)?.[1] ?? null;
  } catch {
    return null;
  }
}

export function sanitizePublicUrl(value) {
  const parsed = new URL(value);
  return `${parsed.protocol}//${parsed.host}${parsed.pathname}`;
}

function isAllowedPageHost(hostname) {
  const host = hostname.toLowerCase();
  return (
    host === "douyin.com" ||
    host.endsWith(".douyin.com") ||
    host === "iesdouyin.com" ||
    host.endsWith(".iesdouyin.com")
  );
}

function isAllowedMediaHost(hostname) {
  const host = hostname.toLowerCase();
  return host === "douyinvod.com" || host.endsWith(".douyinvod.com");
}

function validatePageUrl(value) {
  const parsed = new URL(value);
  if (parsed.protocol !== "https:" || !isAllowedPageHost(parsed.hostname)) {
    throw new CaptureError("page_access_failed", "navigation left the Douyin domain allowlist");
  }
}

function validateMediaUrl(value) {
  const parsed = new URL(value);
  if (parsed.protocol !== "https:" || !isAllowedMediaHost(parsed.hostname)) {
    throw new CaptureError("media_capture_failed", "media host is outside the observed Douyin CDN allowlist");
  }
}

async function exists(target) {
  try {
    await access(target);
    return true;
  } catch {
    return false;
  }
}

async function readJson(target) {
  return JSON.parse(await readFile(target, "utf8"));
}

async function atomicJson(target, value) {
  const parent = path.dirname(target);
  await mkdir(parent, { recursive: true, mode: 0o700 });
  const temporary = path.join(parent, `.${path.basename(target)}.${process.pid}.tmp`);
  const serialized = `${JSON.stringify(value, null, 2)}\n`;
  assertNoCredentialLeak(serialized);
  await writeFile(temporary, serialized, { mode: 0o600 });
  await rename(temporary, target);
}

export function assertNoCredentialLeak(serialized) {
  const forbidden = [
    /"cookie"\s*:/i,
    /"authorization"\s*:/i,
    /"passport[^"\s]*"\s*:/i,
    /"(?:access|refresh|session)[_-]?token"\s*:/i,
    /https:\/\/[^"\s]*douyinvod\.com[^"\s]*\?/i,
  ];
  if (forbidden.some((pattern) => pattern.test(serialized))) {
    throw new CaptureError("media_capture_failed", "credential-like data was blocked from persistence");
  }
}

export function ensureWithin(root, target) {
  const normalizedRoot = path.resolve(root);
  const normalizedTarget = path.resolve(target);
  if (normalizedTarget !== normalizedRoot && !normalizedTarget.startsWith(`${normalizedRoot}${path.sep}`)) {
    throw new CaptureError("unsafe_output_path", "output must stay inside the configured runtime root");
  }
}

export function createRunId() {
  return `douyin-${new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14)}-${randomUUID().slice(0, 8)}`;
}

function validateRunId(runId) {
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$/.test(runId)) {
    throw new CaptureError("unsafe_output_path", "invalid run_id");
  }
}

async function fetchJson(url, options = {}, timeoutMilliseconds = 3000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMilliseconds);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

async function cdpVersion(port) {
  try {
    return await fetchJson(`http://127.0.0.1:${port}/json/version`);
  } catch {
    return null;
  }
}

function browserEndpointId(version) {
  return version?.webSocketDebuggerUrl?.split("/").pop() || null;
}

export function browserBindingMatches(marker, version) {
  const endpointId = browserEndpointId(version);
  return Boolean(marker?.browser_endpoint_id && endpointId && marker.browser_endpoint_id === endpointId);
}

async function cdpReady(port) {
  return Boolean(browserEndpointId(await cdpVersion(port)));
}

async function waitForCdp(port, timeoutMilliseconds = 20000) {
  const deadline = Date.now() + timeoutMilliseconds;
  while (Date.now() < deadline) {
    if (await cdpReady(port)) return;
    await sleep(500);
  }
  throw new CaptureError("browser_interrupted", "dedicated browser did not expose its local control endpoint");
}

async function launchChrome({ chromePath, profileDir, port, initialUrl }) {
  if (!(await exists(chromePath))) {
    throw new CaptureError("browser_interrupted", "Google Chrome executable is unavailable");
  }
  await mkdir(profileDir, { recursive: true, mode: 0o700 });
  await chmod(profileDir, 0o700);
  const child = spawn(
    chromePath,
    [
      `--user-data-dir=${profileDir}`,
      "--remote-debugging-address=127.0.0.1",
      `--remote-debugging-port=${port}`,
      "--no-first-run",
      "--no-default-browser-check",
      initialUrl,
    ],
    { detached: true, stdio: "ignore" },
  );
  child.unref();
  await waitForCdp(port);
}

async function ensureBrowser(settings, initialUrl) {
  let version = await cdpVersion(settings.port);
  if (version) {
    const endpointId = browserEndpointId(version);
    if (!browserBindingMatches(settings.marker, version)) {
      throw new CaptureError(
        "browser_interrupted",
        "local browser port belongs to a different profile",
      );
    }
    return false;
  }
  await launchChrome({ ...settings, initialUrl });
  version = await cdpVersion(settings.port);
  const endpointId = browserEndpointId(version);
  if (!endpointId) {
    throw new CaptureError("browser_interrupted", "dedicated browser profile ownership could not be verified");
  }
  const marker = {
    ...settings.marker,
    protocol: "guanlan-douyin-profile-v1",
    profile_version: "1.0.0",
    created_at: settings.marker?.created_at || nowIso(),
    cdp_port: settings.port,
    purpose: "douyin_capture_only",
    browser_endpoint_id: endpointId,
    browser_bound_at: nowIso(),
  };
  await atomicJson(path.join(settings.profileDir, PROFILE_MARKER), marker);
  settings.marker = marker;
  return true;
}

class CdpClient {
  constructor(webSocketUrl) {
    this.webSocketUrl = webSocketUrl;
    this.socket = null;
    this.sequence = 0;
    this.pending = new Map();
  }

  async connect() {
    this.socket = new WebSocket(this.webSocketUrl);
    this.socket.addEventListener("message", (event) => {
      const message = JSON.parse(event.data);
      if (!message.id || !this.pending.has(message.id)) return;
      const pending = this.pending.get(message.id);
      this.pending.delete(message.id);
      clearTimeout(pending.timer);
      if (message.error) pending.reject(new Error(message.error.message));
      else pending.resolve(message.result);
    });
    await new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new CaptureError("browser_interrupted", "browser control connection timed out")),
        10000,
      );
      this.socket.addEventListener("open", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      this.socket.addEventListener("error", (error) => {
        clearTimeout(timer);
        reject(error);
      }, { once: true });
    });
  }

  call(method, params = {}, timeoutMilliseconds = 20000) {
    const id = ++this.sequence;
    this.socket.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        if (this.pending.delete(id)) reject(new CaptureError("browser_interrupted", `${method} timed out`));
      }, timeoutMilliseconds);
      this.pending.set(id, { resolve, reject, timer });
    });
  }

  async evaluate(expression) {
    const result = await this.call("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
      userGesture: false,
    });
    if (result.exceptionDetails) {
      throw new CaptureError("browser_interrupted", "page evaluation failed");
    }
    return result.result?.value ?? null;
  }

  close() {
    try {
      this.socket?.close();
    } catch {
      // The browser may already be gone; the capture result still records failure.
    }
  }
}

async function createPage(port) {
  const target = await fetchJson(
    `http://127.0.0.1:${port}/json/new?${encodeURIComponent("about:blank")}`,
    { method: "PUT" },
    10000,
  );
  if (!target.webSocketDebuggerUrl) {
    throw new CaptureError("browser_interrupted", "dedicated browser could not create an isolated capture tab");
  }
  const client = new CdpClient(target.webSocketDebuggerUrl);
  await client.connect();
  await client.call("Page.enable");
  await client.call("Runtime.enable");
  await client.call("Network.enable", { maxTotalBufferSize: 1048576, maxResourceBufferSize: 524288 });
  return client;
}

const PAGE_PROBE_EXPRESSION = `(() => {
  const body = document.body?.innerText || "";
  const videos = [...document.querySelectorAll("video")];
  const active = videos.sort((a, b) => (b.videoWidth * b.videoHeight) - (a.videoWidth * a.videoHeight))[0];
  const resources = performance.getEntriesByType("resource").map((entry) => ({
    name: entry.name,
    initiatorType: entry.initiatorType,
    transferSize: entry.transferSize,
    decodedBodySize: entry.decodedBodySize
  }));
  const media = resources.filter((entry) => /media-video|media-audio/i.test(entry.name));
  const loginControls = [...document.querySelectorAll("button,a")].filter((element) =>
    /^(登录|立即登录)$/.test((element.innerText || "").trim())
  );
  const author = body.match(/(?:^|\\n)@([^\\n]{1,80})(?:\\n|$)/)?.[1]?.trim() || "";
  const metaTitle = document.querySelector('meta[property="og:title"]')?.content || "";
  const title = (document.title || metaTitle).replace(/\\s*-\\s*抖音\\s*$/, "").trim();
  return {
    url: location.href,
    title,
    author,
    hasLoginWall: /扫码登录|验证码登录|登录后继续|立即登录/.test(body),
    hasLoginControl: loginControls.length > 0,
    hasAuthenticatedNavigation: /(?:^|\\n)我的(?:\\n|$)/.test(body),
    hasChallenge: /安全验证|滑动验证|访问过于频繁|完成验证/.test(body),
    isDeleted: /作品不存在|作品已删除|内容不存在|视频已删除/.test(body),
    isPrivate: /私密作品|暂无权限|作者仅允许/.test(body),
    isLive: /\\/live\\//.test(location.pathname),
    video: active ? {
      currentTime: Number(active.currentTime || 0),
      duration: Number(active.duration || 0),
      paused: Boolean(active.paused),
      readyState: Number(active.readyState || 0),
      networkState: Number(active.networkState || 0),
      bufferedEnd: active.buffered.length ? Number(active.buffered.end(active.buffered.length - 1)) : 0,
      width: Number(active.videoWidth || 0),
      height: Number(active.videoHeight || 0)
    } : null,
    videoCount: videos.length,
    mediaUrls: media.map((entry) => entry.name),
    mediaEvidence: media.map((entry) => {
      const url = new URL(entry.name);
      return {
        origin: url.origin,
        path: url.pathname,
        initiatorType: entry.initiatorType,
        transferSize: entry.transferSize,
        decodedBodySize: entry.decodedBodySize
      };
    })
  };
})()`;

async function navigate(client, url, timeoutMilliseconds) {
  validatePageUrl(url);
  await client.call("Page.navigate", { url }, timeoutMilliseconds);
  const deadline = Date.now() + timeoutMilliseconds;
  let probe = null;
  while (Date.now() < deadline) {
    await sleep(500);
    probe = await client.evaluate(PAGE_PROBE_EXPRESSION);
    if (probe?.url && !probe.url.startsWith("about:")) {
      validatePageUrl(probe.url);
      const id = contentIdFromUrl(probe.url);
      if (id || probe.hasChallenge || probe.hasLoginWall || probe.isDeleted || probe.isPrivate) {
        return probe;
      }
    }
  }
  return probe;
}

export function failureFromPageProbe(probe, previouslyAuthenticated = false) {
  if (!probe) return "page_access_failed";
  if (probe.hasChallenge) return "anti_bot";
  if (probe.isDeleted) return "content_deleted";
  if (probe.isPrivate) return "content_private";
  if (probe.hasLoginWall || probe.hasLoginControl) {
    return previouslyAuthenticated ? "auth_expired" : "auth_required";
  }
  if (probe.isLive) return "unsupported_content_type";
  return null;
}

async function establishWorkPage(client, extracted, timeoutMilliseconds, previouslyAuthenticated) {
  let probe = await navigate(client, extracted.extractedUrl, timeoutMilliseconds);
  let resolvedId = contentIdFromUrl(probe?.url ?? "");
  if (resolvedId && !new URL(probe.url).pathname.startsWith("/video/")) {
    probe = await navigate(client, `https://www.douyin.com/video/${resolvedId}`, timeoutMilliseconds);
    resolvedId = contentIdFromUrl(probe?.url ?? "");
  }
  const pageFailure = failureFromPageProbe(probe, previouslyAuthenticated);
  if (pageFailure) throw new CaptureError(pageFailure);
  if (!resolvedId) throw new CaptureError("page_access_failed", "short link did not resolve to a work page");
  if (extracted.contentId && extracted.contentId !== resolvedId) {
    throw new CaptureError("page_identity_mismatch");
  }
  if (!new URL(probe.url).pathname.startsWith("/video/")) {
    throw new CaptureError("unsupported_content_type");
  }
  return { probe, resolvedId };
}

async function waitForPlayback(client, timeoutMilliseconds) {
  await client.evaluate(`Promise.all([...document.querySelectorAll("video")].map((video) => video.play().catch(() => false)))`);
  const deadline = Date.now() + timeoutMilliseconds;
  let probe = null;
  while (Date.now() < deadline) {
    await sleep(750);
    probe = await client.evaluate(PAGE_PROBE_EXPRESSION);
    const pageFailure = failureFromPageProbe(probe, true);
    if (pageFailure) throw new CaptureError(pageFailure);
    if (playbackReady(probe)) return probe;
  }
  throw new CaptureError("media_not_playing");
}

export function playbackReady(probe) {
  const mediaUrls = probe?.mediaUrls ?? [];
  const hasVideo = mediaUrls.some((value) => /media-video/i.test(value));
  const hasAudio = mediaUrls.some((value) => /media-audio/i.test(value));
  const loaded =
    probe?.video &&
    probe.video.readyState >= 2 &&
    (probe.video.currentTime > 0 || probe.video.bufferedEnd > 0);
  return Boolean(loaded && hasVideo && hasAudio);
}

async function downloadMedia(url, target, pageUrl, kind) {
  validateMediaUrl(url);
  const temporary = `${target}.part`;
  await rm(temporary, { force: true });
  let response;
  try {
    response = await fetch(url, {
      headers: { "User-Agent": USER_AGENT, Referer: pageUrl, Accept: "*/*" },
      redirect: "follow",
    });
  } catch {
    throw new CaptureError(failureCodeForStage(`${kind}_response`));
  }
  if (!response.ok || !response.body) {
    throw new CaptureError(failureCodeForStage(`${kind}_response`));
  }
  const finalUrl = new URL(response.url);
  if (!isAllowedMediaHost(finalUrl.hostname)) {
    throw new CaptureError("media_capture_failed", "media redirect left the CDN allowlist");
  }
  const contentType = response.headers.get("content-type") ?? "unknown";
  if (!/(video|audio|octet-stream|mp4)/i.test(contentType)) {
    throw new CaptureError("invalid_media", `${kind} response is not media`);
  }
  try {
    await pipeline(response.body, createWriteStream(temporary, { mode: 0o600 }));
    const size = (await stat(temporary)).size;
    if (size <= 0) throw new CaptureError("invalid_media", `${kind} response is empty`);
    await rename(temporary, target);
    return {
      kind,
      status: response.status,
      contentType,
      sizeBytes: size,
      acceptRanges: response.headers.get("accept-ranges") ?? "unknown",
      origin: finalUrl.origin,
      path: finalUrl.pathname,
    };
  } catch (error) {
    await rm(temporary, { force: true });
    if (error instanceof CaptureError) throw error;
    throw new CaptureError(failureCodeForStage("disk_write"));
  }
}

async function runCommand(executable, args, failureCode) {
  return await new Promise((resolve, reject) => {
    const child = spawn(executable, args, { stdio: ["ignore", "pipe", "pipe"] });
    const stdout = [];
    const stderr = [];
    child.stdout.on("data", (chunk) => stdout.push(chunk));
    child.stderr.on("data", (chunk) => stderr.push(chunk));
    child.on("error", () => reject(new CaptureError(failureCode)));
    child.on("close", (code) => {
      if (code !== 0) reject(new CaptureError(failureCode, Buffer.concat(stderr).toString("utf8").slice(-400)));
      else resolve(Buffer.concat(stdout).toString("utf8"));
    });
  });
}

async function sha256File(target) {
  const digest = createHash("sha256");
  for await (const chunk of createReadStream(target)) digest.update(chunk);
  return digest.digest("hex");
}

export function validateFfprobe(probe, browserDuration = 0) {
  const streams = Array.isArray(probe?.streams) ? probe.streams : [];
  const duration = Number(probe?.format?.duration ?? 0);
  const size = Number(probe?.format?.size ?? 0);
  const hasVideo = streams.some((item) => item.codec_type === "video");
  const hasAudio = streams.some((item) => item.codec_type === "audio");
  if (!Number.isFinite(duration) || duration <= 0 || size <= 0 || !hasVideo || !hasAudio) {
    throw new CaptureError("invalid_media");
  }
  if (browserDuration > 0 && Math.abs(duration - browserDuration) > Math.max(10, browserDuration * 0.03)) {
    throw new CaptureError("invalid_media", "exported duration does not match page duration");
  }
  return { duration, size, hasVideo, hasAudio, streams };
}

async function muxAndVerify({ videoPath, audioPath, outputPath, ffmpegPath, ffprobePath, browserDuration }) {
  const temporary = `${outputPath}.part.mp4`;
  await rm(temporary, { force: true });
  try {
    await runCommand(
      ffmpegPath,
      [
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        videoPath,
        "-i",
        audioPath,
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c",
        "copy",
        temporary,
      ],
      failureCodeForStage("ffmpeg"),
    );
    const ffprobeOutput = await runCommand(
      ffprobePath,
      [
        "-v",
        "error",
        "-show_entries",
        "format=format_name,duration,size:stream=index,codec_type,codec_name,width,height",
        "-of",
        "json",
        temporary,
      ],
      failureCodeForStage("ffprobe"),
    );
    const probe = JSON.parse(ffprobeOutput);
    const verified = validateFfprobe(probe, browserDuration);
    await rename(temporary, outputPath);
    const sha256 = await sha256File(outputPath);
    return { ...verified, sha256, probe };
  } catch (error) {
    await rm(temporary, { force: true });
    throw error;
  }
}

export function selectMediaUrls(mediaUrls) {
  const unique = [...new Set(mediaUrls)];
  const video = [...unique].reverse().find((value) => /media-video/i.test(value));
  const audio = [...unique].reverse().find((value) => /media-audio/i.test(value));
  if (!video) throw new CaptureError("video_response_failed");
  if (!audio) throw new CaptureError("audio_response_failed");
  validateMediaUrl(video);
  validateMediaUrl(audio);
  return { video, audio };
}

function cleanPublicText(value, fallback = "unknown") {
  const text = String(value ?? "").replace(/[\u0000-\u001f]+/g, " ").trim();
  return text ? text.slice(0, 500) : fallback;
}

function resultSkeleton(extracted, runId, capturedAt) {
  return {
    protocol: "capture-protocol-v2",
    source: {
      platform: "douyin",
      source_url: extracted?.extractedUrl ?? "unknown",
      title: "unknown",
      author: "unknown",
      captured_at: capturedAt,
      original_input: extracted?.originalInput ?? "",
      original_url: extracted?.extractedUrl ?? "unknown",
      content_id: extracted?.contentId ?? null,
      published_at: null,
    },
    capture: {
      provider: "douyin",
      status: "failed",
      capture_status: "failed",
      capture_method: "authenticated_browser_session",
      authentication_mode: "browser_session",
      authenticated_session_used: false,
      run_id: runId,
      capture_time: capturedAt,
      warnings: [],
    },
    media: { files: [] },
    subtitle: { status: "unknown", language: "unknown", reference: "none" },
    audio: { status: "unknown", reference: "none" },
    visual: { text_possible: "unknown" },
  };
}

function safeFailureMessage(error) {
  if (error instanceof CaptureError) return error.message.replace(/https?:\/\/\S+/g, "<redacted-url>");
  return "unexpected provider failure";
}

async function writeAuthMarker(profileDir, port) {
  await atomicJson(path.join(profileDir, AUTH_MARKER), {
    protocol: "guanlan-douyin-auth-state-v1",
    authenticated_session_ready: true,
    validated_at: nowIso(),
    cdp_port: port,
  });
}

async function loadSettings(options) {
  const profileDir = path.resolve(options["profile-dir"] || DEFAULT_PROFILE);
  const runtimeRoot = path.resolve(options["runtime-root"] || DEFAULT_RUNTIME);
  const chromePath = path.resolve(options["chrome-path"] || DEFAULT_CHROME);
  const markerPath = path.join(profileDir, PROFILE_MARKER);
  let marker = null;
  if (await exists(markerPath)) {
    try {
      marker = await readJson(markerPath);
    } catch {
      throw new CaptureError("auth_required", "profile marker is invalid; run auth-init");
    }
  }
  const port = Number(options["cdp-port"] || marker?.cdp_port || DEFAULT_PORT);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) {
    throw new CaptureError("browser_interrupted", "invalid local browser port");
  }
  return {
    profileDir,
    runtimeRoot,
    chromePath,
    port,
    ffmpegPath: options.ffmpeg || "ffmpeg",
    ffprobePath: options.ffprobe || "ffprobe",
    marker,
  };
}

async function authInit(options) {
  const settings = await loadSettings(options);
  await mkdir(settings.profileDir, { recursive: true, mode: 0o700 });
  await chmod(settings.profileDir, 0o700);
  await atomicJson(path.join(settings.profileDir, PROFILE_MARKER), {
    protocol: "guanlan-douyin-profile-v1",
    profile_version: "1.0.0",
    created_at: settings.marker?.created_at || nowIso(),
    cdp_port: settings.port,
    purpose: "douyin_capture_only",
    ...(settings.marker?.browser_endpoint_id
      ? {
          browser_endpoint_id: settings.marker.browser_endpoint_id,
          browser_bound_at: settings.marker.browser_bound_at,
        }
      : {}),
  });
  await ensureBrowser(settings, DOUYIN_HOME);
  console.log(
    JSON.stringify({
      status: "auth_initialization_started",
      action: "complete_official_douyin_login_then_run_auth-check",
      authenticated_session_used: false,
      profile_scope: options["profile-dir"] ? "explicit_private_profile" : "guanlan_application_support",
    }),
  );
}

async function inspectAuthentication(settings) {
  const previouslyAuthenticated = await exists(path.join(settings.profileDir, AUTH_MARKER));
  if (!settings.marker) {
    return { status: "auth_required", authenticated_session_ready: false, previouslyAuthenticated };
  }
  await ensureBrowser(settings, DOUYIN_HOME);
  const client = await createPage(settings.port);
  try {
    const probe = await navigate(client, DOUYIN_HOME, 20000);
    const failure = failureFromPageProbe(probe, previouslyAuthenticated);
    if (failure) return { status: failure, authenticated_session_ready: false, previouslyAuthenticated };
    await writeAuthMarker(settings.profileDir, settings.port);
    return { status: "authenticated_session_ready", authenticated_session_ready: true, previouslyAuthenticated };
  } finally {
    try {
      await client.call("Page.close", {}, 3000);
    } catch {
      // Closing an inspection tab is best effort.
    }
    client.close();
  }
}

async function authCheck(options) {
  const settings = await loadSettings(options);
  const result = await inspectAuthentication(settings);
  console.log(JSON.stringify({ ...result, authenticated_session_used: result.authenticated_session_ready }));
  if (!result.authenticated_session_ready) process.exitCode = 2;
}

async function capture(options) {
  const capturedAt = nowIso();
  const runId = options["run-id"] || createRunId();
  validateRunId(runId);
  const settings = await loadSettings(options);
  const runDir = path.join(settings.runtimeRoot, runId);
  ensureWithin(settings.runtimeRoot, runDir);
  if (await exists(runDir)) {
    throw new CaptureError("unsafe_output_path", "run directory already exists");
  }
  await mkdir(runDir, { recursive: true, mode: 0o700 });
  const resultPath = options.output ? path.resolve(options.output) : path.join(runDir, "capture-result.json");
  ensureWithin(settings.runtimeRoot, resultPath);

  let extracted = null;
  let result = resultSkeleton(extracted, runId, capturedAt);
  let client = null;
  try {
    extracted = extractDouyinInput(options.input || "");
    result = resultSkeleton(extracted, runId, capturedAt);
    if (!settings.marker) throw new CaptureError("auth_required", "run auth-init before capture");
    const previouslyAuthenticated = await exists(path.join(settings.profileDir, AUTH_MARKER));
    const browserStartedAt = Date.now();
    const browserStarted = await ensureBrowser(settings, "about:blank");
    const browserReadyAt = Date.now();
    client = await createPage(settings.port);
    const pageStartedAt = Date.now();
    const { probe: identityProbe, resolvedId } = await establishWorkPage(
      client,
      extracted,
      Number(options["page-timeout-ms"] || 30000),
      previouslyAuthenticated,
    );
    await writeAuthMarker(settings.profileDir, settings.port);
    const playbackProbe = await waitForPlayback(client, Number(options["media-timeout-ms"] || 25000));
    const mediaUrls = selectMediaUrls(playbackProbe.mediaUrls);
    const resolvedUrl = `https://www.douyin.com/video/${resolvedId}`;
    const videoPath = path.join(runDir, "video-track.mp4");
    const audioPath = path.join(runDir, "audio-track.m4a");
    const mediaPath = path.join(runDir, "media.mp4");
    const captureStartedAt = Date.now();
    const videoDownload = await downloadMedia(mediaUrls.video, videoPath, resolvedUrl, "video");
    const audioDownload = await downloadMedia(mediaUrls.audio, audioPath, resolvedUrl, "audio");
    const verified = await muxAndVerify({
      videoPath,
      audioPath,
      outputPath: mediaPath,
      ffmpegPath: settings.ffmpegPath,
      ffprobePath: settings.ffprobePath,
      browserDuration: Number(playbackProbe.video?.duration || 0),
    });
    await rm(videoPath, { force: true });
    await rm(audioPath, { force: true });
    const completedAt = nowIso();
    result.source = {
      ...result.source,
      source_url: resolvedUrl,
      title: cleanPublicText(identityProbe.title || playbackProbe.title),
      author: cleanPublicText(identityProbe.author || playbackProbe.author),
      content_id: resolvedId,
    };
    result.capture = {
      provider: "douyin",
      status: "success",
      capture_status: "complete",
      capture_method: "browser_network_response",
      authentication_mode: "browser_session",
      authenticated_session_used: true,
      run_id: runId,
      capture_time: completedAt,
      original_url: extracted.extractedUrl,
      resolved_url: resolvedUrl,
      content_id: resolvedId,
      content_type: "video",
      local_media_path: mediaPath,
      media_sha256: `sha256:${verified.sha256}`,
      media_size: verified.size,
      duration: verified.duration,
      warnings: [],
      provider_metadata: {
        adapter_version: "douyin-browser-capture-v1",
        browser_mode: "headful",
        browser_started_for_run: browserStarted,
        playback: {
          current_time: playbackProbe.video.currentTime,
          ready_state: playbackProbe.video.readyState,
          buffered_end: playbackProbe.video.bufferedEnd,
        },
        media_responses: [videoDownload, audioDownload],
        timings_ms: {
          browser_ready: browserReadyAt - browserStartedAt,
          page_and_playback: captureStartedAt - pageStartedAt,
          media_capture_and_validation: Date.now() - captureStartedAt,
        },
      },
    };
    result.media.files = [
      {
        type: "video",
        path: mediaPath,
        format: "MP4",
        mime_type: "video/mp4",
        size: String(verified.size),
        size_bytes: verified.size,
        sha256: `sha256:${verified.sha256}`,
        duration: verified.duration,
        streams: verified.streams.map((stream) => ({
          index: stream.index,
          codec_type: stream.codec_type,
          codec_name: stream.codec_name,
          width: stream.width,
          height: stream.height,
        })),
      },
    ];
    result.audio = { status: "available", reference: mediaPath };
    await atomicJson(path.join(runDir, "media-verification.json"), {
      protocol: "guanlan-media-verification-v1",
      run_id: runId,
      content_id: resolvedId,
      media_sha256: `sha256:${verified.sha256}`,
      media_size: verified.size,
      duration: verified.duration,
      streams: result.media.files[0].streams,
      status: "valid",
      verified_at: completedAt,
    });
    await atomicJson(resultPath, result);
    console.log(JSON.stringify({ status: "success", run_id: runId, capture_result: resultPath }));
  } catch (error) {
    const code = error instanceof CaptureError ? error.code : "media_capture_failed";
    result.capture = {
      ...result.capture,
      status: code,
      capture_status: "failed",
      authenticated_session_used:
        !["auth_required", "auth_expired"].includes(code) &&
        Boolean(await exists(path.join(settings.profileDir, AUTH_MARKER))),
      blocked_reason: code,
      warnings: [safeFailureMessage(error)],
    };
    await atomicJson(resultPath, result);
    console.log(JSON.stringify({ status: code, run_id: runId, capture_result: resultPath }));
    process.exitCode = 2;
  } finally {
    if (client) {
      try {
        await client.call("Page.close", {}, 3000);
      } catch {
        // Browser interruption is already represented by the CaptureResult.
      }
      client.close();
    }
  }
}

async function main() {
  const options = parseOptions(process.argv.slice(2));
  const command = options._[0];
  try {
    if (command === "inspect-input") {
      const result = extractDouyinInput(options.input || "");
      console.log(JSON.stringify({ status: "valid", extracted_url: result.extractedUrl, content_id: result.contentId }));
    } else if (command === "auth-init") {
      await authInit(options);
    } else if (command === "auth-check") {
      await authCheck(options);
    } else if (command === "capture") {
      await capture(options);
    } else {
      console.error(
        "usage: douyin_browser_capture.mjs <inspect-input|auth-init|auth-check|capture> [options]",
      );
      process.exitCode = 2;
    }
  } catch (error) {
    const code = error instanceof CaptureError ? error.code : "media_capture_failed";
    console.error(JSON.stringify({ status: code, message: safeFailureMessage(error) }));
    process.exitCode = 2;
  }
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}

export { CaptureError };
