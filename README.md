# Apple Podcasts → Notion

将 Apple Podcasts 关注节目、收藏和最近播放记录同步到已有 Podcast2Notion 模板，使用硅基流动 SenseVoiceSmall 转写、DeepSeek 生成大纲，直接在 Notion Mermaid 代码块中展示树状脑图。

## 配置与首次运行

在仓库 Settings → Secrets and variables → Actions 添加 Secrets：

| Secret | 内容 |
|---|---|
| `APPLE_BEARER_TOKEN` | Apple 网页请求的 authorization，可带 Bearer 前缀 |
| `APPLE_MEDIA_USER_TOKEN` | 同一请求的 media-user-token |
| `NOTION_TOKEN` | 有目标模板访问权限的集成令牌 |
| `NOTION_PAGE` | 你的模板页面链接或 ID |
| `SILICONFLOW_API_KEY` | 可选，硅基流动 API Key |
| `DEEPSEEK_API_KEY` | 可选，DeepSeek 官方 API Key，按量计费 |

1. Actions → Apple Podcasts sync → Run workflow，首次保留 `check_only` 勾选。这一步不写入。
2. 检查通过后取消勾选 `check_only`；可勾选 `skip_ai` 先只同步基础内容。
3. 设置 Actions **变量** `SYNC_ENABLED=true` 启用定时任务：每天北京时间 **01:00**（UTC 17:00，GitHub 调度可能延迟）。未配置前定时任务跳过，避免空凭证报错。
4. 默认每次最多处理 3 集 AI，变量 `AI_MAX_EPISODES` 可调整；0 表示暂停 AI。设置 `DEEPSEEK_MODEL` 可更换当前账户可用的 DeepSeek 模型，默认 `deepseek-flash`。API 无可用余额或模型无权限会明确报错，保留基础同步结果。

凭证失效时在 Apple 网页重新登录，再替换两项 Secrets。不要将完整标头、令牌、音频或逐字稿提交至仓库。

## 模板兼容与已有数据

沿用小宇宙开源项目的 `Podcast`、`Episode`、`Author`、`全部` 四个数据库及字段映射；支持位于分栏中的数据库和分页。第一次正式同步会在 Episode 新增“来源、播放位置、进度更新时间、收藏、AI状态、转写指纹、脑图指纹”。已有同名不同类型字段会在写入前报错。

Podcast 不新增字段，通过已有 Pid 的 `apple:` 前缀识别来源；如果已经存在 rich_text 类型的“来源”，则同时填写。这样可兼容含大量“演员”等多选选项、无法再修改结构的旧模板，无需删除选项或字段。此兼容处理仅避免修改 Podcast 结构，不解除 Notion 本身的结构大小限制；若 Episode 也有同类限制，需要另行检查。

- `Pid/Eid` 使用 `apple:` 前缀，索引只查询和处理该前缀的记录。旧小宇宙页面不会被覆盖或删除，其重复 Pid/Eid 不影响 Apple 同步；若 Apple 自身的 ID 重复，仍会停止并报告，避免错误更新。同一节目跨平台会保留独立来源记录，不自动合并。
- 发布时间和原“时间戳”继续指节目发布日期。原“收听时间”是 Notion 创建时间；真实进度更新时间另存。
- 时长和播放位置均转换为秒；状态使用模板既有“未听 / 在听 / 听过”。Apple 收藏与小宇宙“喜欢”分别保存。
- 不将播放位置当成累计收听时长，原 Podcast 收听时长和“全部”汇总不填造假数据，可能保持空值。作者只能使用 Apple 返回的发布者名称，不保证对应每位主播。
- 不执行旧脚本删除未听记录的逻辑。不更改用户笔记、评分及已有正文。未出现在本次 Apple 返回结果中的旧记录保留，包括收藏状态；仅本次获取到的单集更新收藏状态。
- 节目简介属性保存前1800字符；有单集说明时完整文字另存托管折叠块。纯文本说明不保证恢复原始超链接。

## 转写与脑图

下载音源后通过 FFmpeg 切成20分钟、16kHz单声道 WAV，每段约38.4MB，符合硅基流动1小时/50MB限制。默认音源下载上限512MiB，单个托管正文上限15万字符，超过会明确报错而不静默截断。SenseVoiceSmall 返回文字，不提供逐字时间轴或说话人标签保证。专有名词仍可能识别错误。

DeepSeek 对长文本分段提炼，再生成 Markdown 大纲；程序转换为 `flowchart LR` 树状 Mermaid（兼容性优先），转义特殊字符、限制节点数。脑图直接写入 Notion `code.language=mermaid`，需要时在 Notion 切换预览模式。没有额外图床或脑图网页。

大纲请求显式关闭 DeepSeek 思考模式，输出预算8192 tokens，仅在明确返回 `finish_reason=length` 时用16384 tokens重试一次；其他结束原因明确记录，不无限重试。日志只记录结束原因和用量，不输出思考内容或逐字稿。下载、硅基流动转写、DeepSeek、Notion保存分阶段报告错误，HTTP错误含服务域名、错误码和可用的请求追踪ID，过滤凭证和URL。

`Targeted AI diagnosis and recovery` 工作流可手动诊断并恢复最初三集失败任务，复用已保存逐字稿，会调用AI并写入恢复结果。仅在修改诊断文件且提交信息含 `[verify-ai]` 时自动运行，正常推送不会调用AI。本机 `python scripts/diagnose_ai.py` 只探测音源；加 `--recover` 才执行恢复。

逐字稿、大纲和脑图写入带 `Apple Podcasts ·` 标记的独立折叠块。转写完成后立即保存指纹，脑图失败可重用已保存逐字稿。普通重复运行不重复转写；音源 URL 或模型变化会触发相应阶段重做。AI失败不会回滚已同步资料，但任务显示失败便于排查，之后运行继续处理。AI POST 请求不盲目重试，网络断开时可能已产生服务端费用。

无 AI Key 时基础同步仍正常。已有逐字稿且只配置 DeepSeek Key 时可继续生成脑图。新增单集需要硅基流动 Key 才能转写。当前官方列 SenseVoiceSmall 免费，免费策略和限流可能变化。

## 热力图 / GitHub Pages

界面复用你 Read-notion 风格的控制栏、深浅色切换、年份切换和全部年份汇总，通过已验证的 duolingo-notion 页面适配；SVG只包含日期与计数，不包含令牌、标题、音源和逐字稿。

**指标是按每集最新播放进度记录日期统计的单集数，不是每日收听分钟数，也不是完整历史。** 每集仅有一个最新记录时间，因此后续同步可能改变历史日期的计数。无法用位置快照可靠还原每日实际收听时长。

仓库 Settings → Pages → Source 选择 **GitHub Actions**，设置变量 `PAGES_ENABLED=true`，再手动运行 Publish podcast heatmap。地址通常为 `https://canbaodexieshen.github.io/Apple-Podcast-Notion/`，部署成功后可在 Notion 中用 `/embed` 嵌入该链接。同步成功后自动重新构建。设置变量前不会尝试部署。

## 本机运行与测试

Python 3.12，`pip install -r requirements.txt`。转写另需 FFmpeg 在 PATH 中。`.env.example` 仅列变量名，程序不自动加载 `.env`，请通过当前终端环境变量配置。

```sh
python scripts/sync.py --check
python scripts/sync.py --no-ai
python scripts/sync.py
python scripts/heatmap.py
python -m unittest discover -s tests -v
node --test tests/test_heatmap_ui.cjs
```

Apple 网页接口为未公开稳定承诺的接口，凭证寿命未确定，需人工更新。基础数据读取已由实际账号验证（5个关注节目、1集收藏、26集分页进度）；自动写入、AI调用与Notion中的图形预览仍需要配置个人凭证后验收。程序带只读预检、限流、读请求退避、去重及托管正文更新，但无法保证第三方接口永不报错。

## 参考与复用

- [Podcast2Notion](https://github.com/canbaodexieshen/Podcast2Notion)：数据库命名、字段语义、关系和按来源标识更新的适配思路。旧获取接口、删除逻辑和外部上传服务不沿用。
- [Read-notion](https://github.com/canbaodexieshen/Read-notion)、[duolingo-notion](https://github.com/canbaodexieshen/duolingo-notion)：热力图前端与主题、年份控制。
- [硅基流动转写接口](https://api-docs.siliconflow.cn/docs/api/audio-transcriptions-post)
- [Notion code block API](https://developers.notion.com/reference/block#code)
