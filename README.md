# Apple Podcasts → Notion

将 Apple Podcasts 关注节目、收藏和最近播放记录同步到已有 Podcast2Notion 模板，使用硅基流动 SenseVoiceSmall 转写、DeepSeek 生成大纲，以原生 Notion 标签页和自包含 Markmap 交互脑图展示内容。

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
- 已审定的同一节目可通过 `config/podcast_aliases.json` 映射 Apple ID 到原小宇宙 Pid。此时保留原小宇宙页面、Pid、链接、简介、收听时长与作者，Apple单集关联到该页面，不再创建第二份节目。映射只包含公开平台ID，无Notion页面ID或凭证。未审定同名节目不自动合并。

跨平台合并工具 `scripts/merge_podcasts.py --backup-dir <本机备份目录>` 默认只生成计划和备份；加 `--apply` 才执行。它逐一检查节目名称、页面正文和单集引用，迁移关联、保留来源链接后，将重复节目软归档。不会合并或删除单集，不处理旧小宇宙重复Eid。
- 发布时间和原“时间戳”继续指节目发布日期。原创建时间字段保留并重命名为“同步创建时间”；新的“最近收听时间”为可写日期，保存 Apple 最近一次进度记录时间，与“进度更新时间”一致，不代表首次收听日期。旧小宇宙记录的原创建时间仍保留，新日期字段未自动猜测填充。旧的可写“收听时间”若存在而新字段不存在，会按属性ID重命名，保留原值和引用。
- Episode新增公式“收听进度”：听过显示100%；Apple有进度更新时间且时长大于0时显示播放位置百分比，限制在0%–100%；没有位置的历史在听记录留空。该百分比不是累计真实收听比例。
- 时长和播放位置均转换为秒；状态使用模板既有“未听 / 在听 / 听过”。Apple 收藏与小宇宙“喜欢”分别保存。
- 不将播放位置当成累计收听时长，原 Podcast 收听时长和“全部”汇总不填造假数据，可能保持空值。作者使用 Apple 返回的发布者名称；保留已有头像或自定义图标；缺图时优先使用作者头像属性，再回退至关联节目封面，最后才使用🎙️。节目封面仅作为作品标识，不宣称是作者本人照片。
- 不执行旧脚本删除未听记录的逻辑。不更改用户笔记、评分。仅迁移本项目标记的自动生成正文。未出现在本次 Apple 返回结果中的旧记录保留，包括收藏状态；仅本次获取到的单集更新收藏状态。
- 节目简介属性保存前1800字符；有单集说明时完整文字另存 ShowNotes 标签页。纯文本说明不保证恢复原始超链接。

## 转写与脑图

下载音源后通过 FFmpeg 切成20分钟、16kHz单声道 WAV，每段约38.4MB，符合硅基流动1小时/50MB限制。默认音源下载上限512MiB，单个托管正文上限15万字符，超过会明确报错而不静默截断。SenseVoiceSmall 返回文字，不提供逐字时间轴或说话人标签保证。专有名词仍可能识别错误。

DeepSeek 对长文本分段提炼，再生成 Markdown 大纲；Markmap 将其渲染为彩色可折叠、缩放和拖动的脑图，默认完全展开并适应窗口，窗口缩小或Notion选项卡从隐藏变为可见后重新适配，支持深浅色切换。脑图文件自包含渲染代码，不依赖外部CDN，上传至Notion HTML区块，在页面权限范围内展示，不通过GitHub Pages公开。Node构建包使用锁定版本，运行前执行 `npm ci && npm run build`。调色板通过Markmap官方`deriveOptions`转换为渲染函数，并用真实浏览器回归测试。

单集正文使用原生 Notion `tab` 区块，顺序固定为 **ShowNotes / 脑图 / 语音转文字 / 音频**。不再显示独立内容大纲或Mermaid。已有自动生成折叠块在内容成功保存后迁移归档；已保存的逐字稿和Markdown大纲会复用，不重新转写或调用DeepSeek。脑图迁移失败时保留原大纲，便于重试。上传 HTML 需要集成具备文件上传能力。

Podcast封面与图标使用节目封面；Episode使用单集封面，缺失时回退至所属节目封面。所有Podcast页面补齐“全部”关联，保留已有其他关联；作者图标按头像、作品封面、🎙️依次补齐，已有图片保留。收听时长暂不写入。

大纲请求显式关闭 DeepSeek 思考模式，输出预算8192 tokens，仅在明确返回 `finish_reason=length` 时用16384 tokens重试一次；其他结束原因明确记录，不无限重试。日志只记录结束原因和用量，不输出思考内容或逐字稿。下载、硅基流动转写、DeepSeek、Notion保存分阶段报告错误，HTTP错误含服务域名、错误码和可用的请求追踪ID，过滤凭证和URL。

发布者音源下载返回403/404/410时，记录“音源受限，未转写”并发出工作流警告，保留待处理状态，继续其他单集；受限音源不占AI处理额度，避免队列被阻塞。任务成功不代表所有音频均已转写，应查看AI状态与警告。硅基流动或DeepSeek的403仍作为真正的API错误报告。后续同步会重新尝试音源，不绕过发布者访问限制。

下载阶段的连接/读取超时、连接中断和源站429/5xx最多重试一次；仍不可用时标记“音源暂不可用”，不占AI额度，继续其他单集。该处理只包围音源GET下载，不会把转写/DeepSeek错误误当作音源问题，也不会自动重试可能已计费的AI POST。已经验证的页面升级及旧文字属性删除在新AI任务之前完成，AI服务失败不会阻止这部分迁移。

`Targeted AI diagnosis and recovery` 工作流可手动诊断并恢复最初三集失败任务，复用已保存逐字稿，会调用AI并写入恢复结果。仅在修改诊断文件且提交信息含 `[verify-ai]` 时自动运行，正常推送不会调用AI。本机 `python scripts/diagnose_ai.py` 只探测音源；加 `--recover` 才执行恢复。

逐字稿和脑图写入对应原生标签页。转写完成后立即保存指纹，脑图失败可重用已保存逐字稿。普通重复运行不重复转写；音源 URL 或模型变化会触发相应阶段重做。AI失败不会回滚已同步资料，但任务显示失败便于排查，之后运行继续处理。AI POST 请求不盲目重试，网络断开时可能已产生服务端费用。

无 AI Key 时基础同步仍正常。已有逐字稿且只配置 DeepSeek Key 时可继续生成脑图。新增单集需要硅基流动 Key 才能转写。当前官方列 SenseVoiceSmall 免费，免费策略和限流可能变化。

## 思维导图资料库

正式同步会在模板下创建内联数据库“思维导图”，每个已有AI脑图的单集对应一条记录，通过“播客单集”双向关联Episode。“思维导图封面”文件属性和页面封面使用同一份私有PNG；每次同步已有脑图时重新完整展开、截图并更新，不会重复调用AI。

正文第一个区块为可折叠二级标题“脑图”，内嵌自包含HTML；第二个区块为可折叠一级标题，使用DeepSeek大纲的总标题，下面按原Markdown级别生成原生可折叠二级、三级、四级标题，保留真实标题语义；不会使用普通toggle代替标题。中断后的层级写入可接续。单集“脑图”标签页的HTML下方添加对应资料库页面的原生page mention，重复同步会复用，不展示裸URL；原有个人笔记保留。

“脑图Markdown”文字属性已取消，原大纲保存在自包含HTML的JSON数据中，使用UTF-8严格读取。迁移会逐条验证HTML能够完整恢复原大纲后才删除旧属性；后续同步不重建该属性。内容指纹继续用于恢复与去重。

截图使用Playwright Chromium，导出前等待字体和布局完成，检查全部节点展开、文本换行及边界无裁切。HTML、PNG均上传Notion，不公开到GitHub Pages。超出安全尺寸或上传上限时明确报错，保留原内容。工作流安装Chromium及中文字体；本机另运行`python -m playwright install chromium`，Windows也可设置环境变量`MINDMAP_BROWSER_CHANNEL=msedge`使用隔离的无头Edge。

`Verify complete podcast sync`工作流用于完整验证：同步全部基础资料，最多处理1集待完成AI任务，读回检查标题层级、原生提及、封面、日期和关联；然后不调用AI再升级一次并复核，验证恢复能力和去重。它需要已配置转写及DeepSeek密钥，正常每日同步仍使用原AI_MAX_EPISODES配置。

`python scripts/upgrade_library.py`只升级现有Notion内容，不需要Apple凭证，也不调用AI。历史单集合并工具`merge_episodes.py`要求明确指定Eid、保留页面ID及备份路径；只接受属性一致、正文为空的已审定重复，迁移可见数据库的引用后软归档，不自动合并冲突笔记。

## 热力图 / GitHub Pages

界面复用你 Read-notion 风格的控制栏、深浅色切换、年份切换和全部年份汇总，通过已验证的 duolingo-notion 页面适配；SVG只包含日期与计数，不包含令牌、标题、音源和逐字稿。

**指标是按每集最新播放进度记录日期统计的单集数，不是每日收听分钟数，也不是完整历史。** 每集仅有一个最新记录时间，因此后续同步可能改变历史日期的计数。无法用位置快照可靠还原每日实际收听时长。

仓库 Settings → Pages → Source 选择 **GitHub Actions**，设置变量 `PAGES_ENABLED=true`，再手动运行 Publish podcast heatmap。地址通常为 `https://canbaodexieshen.github.io/Apple-Podcast-Notion/`，部署成功后可在 Notion 中用 `/embed` 嵌入该链接。同步成功后自动重新构建。设置变量前不会尝试部署。

## 本机运行与测试

Python 3.12、Node 22，`pip install -r requirements.txt`。转写另需 FFmpeg 在 PATH 中。`.env.example` 仅列变量名，程序不自动加载 `.env`，请通过当前终端环境变量配置。

```sh
npm ci
npm run build
python -m playwright install chromium
python scripts/sync.py --check
python scripts/sync.py --no-ai
python scripts/sync.py
python scripts/heatmap.py
python -m unittest discover -s tests -v
node --test tests/test_heatmap_ui.cjs tests/test_markmap_ui.cjs
```

Apple 网页接口为未公开稳定承诺的接口，凭证寿命未确定，需人工更新。基础数据读取已由实际账号验证（5个关注节目、1集收藏、26集分页进度）；实际账号的基础同步、转写和DeepSeek大纲已经验证；客户端视觉与第三方接口仍可能变化。程序带只读预检、限流、读请求退避、去重及托管正文更新，但无法保证第三方接口永不报错。

## 参考与复用

- [Podcast2Notion](https://github.com/canbaodexieshen/Podcast2Notion)：数据库命名、字段语义、关系和按来源标识更新的适配思路。旧获取接口、删除逻辑和外部上传服务不沿用。
- [Read-notion](https://github.com/canbaodexieshen/Read-notion)、[duolingo-notion](https://github.com/canbaodexieshen/duolingo-notion)：热力图前端与主题、年份控制。
- [硅基流动转写接口](https://api-docs.siliconflow.cn/docs/api/audio-transcriptions-post)
- [Notion native tabs and HTML API](https://developers.notion.com/reference/block#tab)
- [Markmap](https://github.com/markmap/markmap)（MIT）

## 已有数据升级

在 Actions 手动运行 `Migrate native tabs and metadata`，仅升级已有Notion资料与已保存脑图，不拉取Apple数据，不调用转写或DeepSeek。末尾会读回校验四个标签页、图标封面、关联和日期。常规同步同样执行升级逻辑，重复运行不会新增重复标签组。读取HTML附件时始终从原始字节按UTF-8严格解码，不使用HTTP默认的Latin-1；已有由旧读取逻辑产生的中文乱码可无损恢复。
