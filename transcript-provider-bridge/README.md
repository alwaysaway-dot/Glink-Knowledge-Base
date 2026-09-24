# FunASR Provider Bridge

该桥接层读取 `transcript-provider-config-v1`，通过配置中的外部 Python 解释器运行 FunASR，并将结果映射为统一 `TranscriptResult`。

仓库只包含配置、Swift 启动器和 Python 适配代码，不包含 Python 虚拟环境、模型或缓存。运行时强制离线，不执行安装和下载。

Whisper Provider 保留为独立备用能力。

## 长音频

`funasr_chunked_provider.py` 复用同一外部 FunASR 环境，把音频标准化为单声道 16 kHz PCM 并切成有界工作单元。每段在独立、可超时的 Provider 进程中执行，支持有限重试、成功段缓存和失败区间记录，再恢复到全局时间轴。它不新增 ASR 模型，也不改变 `transcript-provider-v1`。

`media_transcript_pipeline.py` 是正式组合边界：分段 ASR → Raw Evidence → 最小转录卫生处理 → 结构与内容质量闸门 → 新 Source revision → 00 投影。只有绑定当前 Raw / Readable 哈希的质量报告通过，音视频采集才可标记为可进入“整理”。
