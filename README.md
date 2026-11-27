# Apple Podcasts → Notion

同步Apple Podcasts关注节目、收藏和最近播放进度到原Podcast2Notion模板；通过SenseVoiceSmall转写、DeepSeek生成Markmap脑图。

## 三个正式工作流

| 工作流 | 手动运行 | 自动运行 |
|---|---|---|
| Sync podcast data and progress | 仅同步资料、收藏、进度、图片和关联 | SYNC_ENABLED=true时每天北京时间01:00运行 |
| Transcribe podcasts and generate mindmaps | 仅处理已同步到Notion的单集，不需要Apple登录凭证 | 定时资料同步成功后自动运行；手动运行资料同步不会触发它 |
| Publish podcast heatmap | 单独构建和部署热力图 | 资料同步成功后构建，需PAGES_ENABLED=true |

已移除临时测试/诊断/迁移工作流及只读检查入口。手动入口不再有check_only或skip_ai复选框。自动触发时间使用UTC17:00（次日北京时间01:00），GitHub调度可能延迟。两个写入工作流使用同一个并发组，避免同时修改Notion。

## 配置

在Settings → Secrets and variables → Actions配置Secrets：

| Secret | 用途 |
|---|---|
| APPLE_BEARER_TOKEN | Apple网页请求的authorization，可带Bearer前缀，仅资料同步使用 |
| APPLE_MEDIA_USER_TOKEN | 同一请求的media-user-token，仅资料同步使用 |
| NOTION_TOKEN | 有目标模板访问权限的集成令牌 |
| NOTION_PAGE | 模板页面链接或ID |
| SILICONFLOW_API_KEY | 硅基流动转写，仅AI工作流使用 |
| DEEPSEEK_API_KEY | DeepSeek官方密钥，仅AI工作流使用 |

变量：SYNC_ENABLED=true启用定时同步；AI_MAX_EPISODES默认3，限制每次AI处理数量，0暂停AI；DEEPSEEK_MODEL默认deepseek-flash。凭证失效时在Apple网页重新登录，手动更新两项Apple Secrets。令牌不进入代码或HTML。

## AI状态与处理队列

Episode的“AI状态”为原生Notion状态属性：

- 待处理：尚未转写或转写请求失败后等待重试。
- 下载失败：音源拒绝访问或下载暂不可用。
- 已转写：逐字稿已保存；脑图待生成或生成失败。
- 已完成：逐字稿、脑图及对应资料库页面均已保存。

详细错误单独写入“AI错误”，成功推进阶段时清除旧错误。原文字状态先保留为迁移字段，再根据指纹初始化状态、核验错误未丢失后删除旧字段；非Apple旧记录若含诊断文字则保留该备份字段。转写指纹与脑图指纹继续控制续跑和去重，状态标签本身不作为是否完成的唯一依据。

每次默认处理3集，待处理单集可能需要多次运行。音频播放器代表外链已写入，不代表下载或转写完成。AI工作流从Notion读取音频地址、标题和已有检查点，按最近收听时间优先处理；可在资料同步之外单独运行。

403处理保持原方案：下载返回403/404/410时记录下载失败并跳过，不占AI处理额度，不绕过源站限制。下载阶段的超时、连接中断和429/5xx最多重试一次；仍不可用则记录并继续。转写和DeepSeek服务错误仍会使AI任务报错，保留已同步内容和逐字稿，不盲目重试可能已经计费的POST。

## 转写与新脑图

FFmpeg将音频切为20分钟、16kHz单声道WAV，再提交FunAudioLLM/SenseVoiceSmall；音频下载上限512MiB。逐字稿没有逐字时间轴或说话人标签保证。DeepSeek长文本先分段提炼，再生成Markdown大纲。

新生成脑图必须有三到四层：唯一的#总标题，##主要分支，每个分支至少细化到###，可用####继续展开，禁止跳级或第五层，不限制标题节点数量。模型常见的外层Markdown代码围栏、标题下的列表和正文会先转换为标题结构，保留文本与嵌套关系；超过四层仍会拒绝，不静默截断或压平。模型输出后进行结构校验，不合格时将实际输出及错误附回，只进行一次格式纠正；仍不合格则保留已转写状态及错误，不发布错误脑图。已有完成的脑图保持原结果，不因新层级规则改变指纹或重新调用AI。

Markmap HTML自包含渲染代码，不使用外部CDN，默认全部展开并适应窗口，支持深浅色、拖动、缩放、节点折叠；选项卡从隐藏变为可见时重新适配。

## Notion模板与展示

沿用Podcast、Episode、Author、全部数据库，支持分栏和分页。Pid/Eid使用apple:命名空间；config/podcast_aliases.json记录已审定的跨平台节目映射，Apple单集复用原小宇宙节目页面，保留原Pid、链接、收听时长和作者。未审定同名节目不自动合并；不执行旧项目删除未听记录的逻辑。旧小宇宙任务应避免在同一数据库中无来源限制地删除单集。

Podcast含巨大多选字段时不修改其结构。作者保留已有图标，缺图时依次使用作者头像属性、作品封面、麦克风占位。Podcast与Episode封面使用对应节目/单集图片，Podcast补齐全部关联。

日期使用“最近收听时间”，与Apple进度更新时间一致；不把同步创建日期当作真实收听日期。播放位置和时长以秒保存。“收听进度”为公式：听过显示100%，有Apple进度时显示位置百分比，未知历史进度留空。播放位置不等于真实累计收听时长，Podcast原累计时长保持不变。

单集正文为四个原生标签页：ShowNotes / 脑图 / 语音转文字 / 音频。脑图HTML下使用原生页面提及链接到对应的思维导图页面，保留已有个人笔记。

思维导图数据库每个单集一条记录，通过播客单集关联；生成脑图时完整展开截图，将同一PNG设为页面封面及思维导图封面文件。正文首个可折叠二级标题“脑图”内嵌HTML，后续为普通一至四级标题，按Markdown顺序展开，不使用折叠标题。大纲保存在HTML的JSON中，以UTF-8严格读取，不再使用脑图Markdown文字属性。HTML、PNG保存在Notion，不在GitHub Pages公开。

## 热力图

沿用Read-notion风格，支持主题、年份切换和全部年份汇总。指标为按最新进度记录日期统计的单集数，不是每日收听分钟数或完整收听历史。输出仅含日期与计数。Pages设置Source为GitHub Actions，并启用PAGES_ENABLED=true；成功后可将站点嵌入Notion。

## 本机运行与维护

Python3.12、Node22，安装pip依赖并执行npm ci与npm run build。AI处理另需FFmpeg、Playwright Chromium及中文字体；Windows可设置MINDMAP_BROWSER_CHANNEL=msedge使用隔离的无头Edge。

```sh
pip install -r requirements.txt
npm ci
npm run build
python -m playwright install chromium
python scripts/sync.py
python scripts/process_ai.py
python scripts/heatmap.py
python -m unittest discover -s tests -v
node --test tests/test_heatmap_ui.cjs tests/test_markmap_ui.cjs
```

.env.example仅列变量，程序不自动加载.env。所有配置从环境读取。保留本地回归测试与可复用的维护工具，不再提供测试工作流：upgrade_library.py用于主动迁移已有展示，不调用AI；merge_podcasts.py和merge_episodes.py须先核对内容并保存备份，仅对已审定重复执行软归档。

## 参考

- [Podcast2Notion](https://github.com/canbaodexieshen/Podcast2Notion)
- [Read-notion](https://github.com/canbaodexieshen/Read-notion)
- [硅基流动转写](https://api-docs.siliconflow.cn/docs/api/audio-transcriptions-post)
- [Notion原生状态属性](https://developers.notion.com/reference/property-object#status)
- [Markmap](https://github.com/markmap/markmap)（MIT）
