# 2026 投稿日程：来源与模拟边界

核查日期：2026-11-15。机器使用的唯一日程是 [conferences-2026.yaml](../../experiments/resources/conferences-2026.yaml)，本页解释其来源和简化。用户两张表中的多数通知日期已有官方来源，包括 2027 年的通知；不能因为日期在未来就认定尚未公布。尚无可靠来源的回复窗口、精确时刻和终稿截止均在配置的 `simulated_fields` 中标出。

这是在模拟开局预置的会务手册，使用核查日已知的信息，不表示这些信息在模拟中的 2026 年 3 月已经公开，也不用于开放未来研究文献。默认列出的日期属于 2026 年；跨年日期写出年份。AoE 是 UTC−12，不是北京时间；ACCV 使用 GMT，MLSys 使用明确 UTC 时刻，ICRA/3DV 的官方 PST/PDT 字样按其固定偏移保留。下表只保留日历日期，运行以 YAML 的带时区时间为准。没有公布开放日期的会议允许提前登记是模拟规则，不代表真实系统已经开放。

## 用户第一张表

“回复”表示作者可操作窗口，不能与内部审稿、评审讨论混同。“模拟”表示项目选择而非官方承诺；即使日期官方已公布，未给出的释放小时也会标为模拟。

| 会议 | 摘要 → 全文 | 初审释放／作者回复 | 通知 → 终稿 | 官方依据与差异 |
|---|---|---|---|---|
| ACM MM 2026 | 3/25 → 4/1 | 主轨仅写 6/4；模拟 5/28–6/4 | 7/9 → 8/6 | [Dates](https://2026.acmmm.org/site/important-dates.html)。不能直接把 BNI 的完整窗口认作主轨官方窗口。 |
| RecSys 2026 | 4/14 → 4/21 | 6/4–6/9 | 7/9 → 7/27 | [Call](https://recsys.acm.org/recsys26/call/)。3/2 开放；采用主研究轨，不含复现轨。 |
| ISMIR 2026 | 4/20 → 4/27 | 模拟 6/19–6/26 | 7/10 → 7/31 | [CFP](https://ismir2026.ismir.net/authors/call-for-papers)。回复日期未获该来源确认。 |
| NeurIPS 2026 | 5/4 → 5/6 | 7/22 释评；7/27–8/3 作者讨论 | 9/24 → 11/6 | [Dates](https://neurips.cc/Conferences/2026/Dates)。模拟合并释评后的回应与讨论。 |
| CIKM 2026 | 5/16 → 5/23 | 模拟 7/17–7/24 | 8/7 → 8/23 | [Full research CFP](https://cikm2026.diag.uniroma1.it/full-research-papers/)。官网 reviewer discussion 不是作者 rebuttal。 |
| AACL 2026 | ARR 全文 5/25 | 7/7–7/13；meta 7/30 | 9/7 → 10/2 | [CFP](https://2026.aaclnet.org/calls/main_conference_papers/)。commit 第一轮 8/7、第二轮 8/25；配置采用最后机会 8/25。 |
| EMNLP 2026 | ARR 全文 5/25 | 7/7–7/13；meta 7/30 | 8/20 → 8/30 | [CFP](https://2026.emnlp.org/calls/main_conference_papers/)。另须 8/2 前 commit，5/25 不是直接向 EMNLP 投稿。 |
| CoRL 2026 | 全文 5/28 | 8/4–8/11，标模拟来源限制 | 9/4 → 10/12 | [当前作者说明](https://www.corl.org/contributions/instruction-for-authors)、[归档评审说明](https://www.corl.org/contributions/old_instruction-for-reviewers)、[当前 demo CFP](https://www.corl.org/contributions/call-for-demos)。回复窗口只在归档页核实。 |
| BMVC 2026 | 5/22 → 5/29 | 7/3–7/10 | 8/7 → 8/28 | [CFP](https://bmvc2026.bmva.org/calls/call-for-papers/)。 |
| ACCV 2026 | 7/3 → 7/5 | 8/26–9/2 | 9/20 → 10/4 | [官方首页](https://accv2026.org/)。时区为 GMT。 |
| KDD 2027 第一轮 | 7/19 → 7/26 | 9/29–10/13 | 11/14 → 模拟 11/28 | [Research CFP](https://kdd2027.kdd.org/research-track-call-for-papers/)。真实流程包含 resubmit，本实现只给模拟 accept/reject。 |
| EACL 2027 | ARR 全文 8/3 | 回应 9/14–19；讨论 9/20–24 | 11/12 → 11/26 | [CFP](https://2027.eacl.org/calls/papers/)。meta 10/8、commit 10/11；模拟合并两段回应窗口。 |
| WSDM 2027 | 8/17 → 8/24 | 模拟 10/12–10/19 | 11/2 → 模拟 11/16 | [CFP](https://www.wsdm-conference.org/2027/cffp.html)。未公布回复/终稿日期；Main/Findings 合并为模拟二元结果。 |
| WACV 2027 第二轮 | 8/21 → 8/28 | 模拟 9/23–9/30 | 10/14 → 11/2 | [Dates](https://wacv.thecvf.com/Conferences/2027/Dates) 与 [Author Guides](https://wacv.thecvf.com/Conferences/2027/AuthorGuides) 存在 10/14、10/9 冲突；采用 Dates 页并保留冲突说明。没有复刻第一轮修订轨。 |

SIGIR 2026 不在用户表中；其 [官方 OpenReview 页面](https://openreview.net/group?id=ACM.org%2FSIGIR%2F2026%2FConference) 的摘要、全文截止位于 1 月，早于本轮 3 月开局，因此没有额外加入可投日历。

## 用户第二张表

这些会议的通知日期均有下列官方页支持；本轮若止于 2026-12-31，2027 年通知保持 pending。表中“模拟回复”不是对真实作者回复政策的断言。

| 会议 | 摘要 → 全文 | 初审释放／回复截止 | 通知 → 终稿 | 官方依据与差异 |
|---|---|---|---|---|
| AAAI 2027 | 7/21 → 7/28 | 10/24–10/31 | 11/30 → 12/14 | [首页日程](https://aaai.org/conference/aaai/aaai-27/)。新版窗口取代旧评审页的 10/19–25；不单独模拟 9/24 第一轮淘汰。 |
| 3DV 2027 | 8/28 → 8/28 | 10/27 释评；模拟 11/10 截止 | 12/2 → 模拟 12/16 | [Dates](https://3dvconf.github.io/2027/dates/)。真实仅部分稿件获邀回复；通知写 11:00 PDT，12 月也照其文字记为 UTC−07。 |
| ICLR 2027 | 9/18 → 9/25 | 11/5–11/18 | 12/16 → 模拟 2027/2/28 | [CFP](https://iclr.cc/Conferences/2027/CallForPapers)、[作者指南](https://iclr.cc/Conferences/2027/AuthorGuidelines)。正式 camera-ready 指引预计 2027 年 2 月，截止未公布。 |
| CHI 2027 | 无独立摘要；9/10 全文 | 11/5 释评；12/3 修订 | 12/17 → 2027/2/18 | [Papers](https://chi2027.acm.org/Authors/Papers/)。真实 revision/resubmission 简化为原稿、最新修订和回应；终稿采用 publication-ready 日期，非 TAPS 上传起点。 |
| AAMAS 2027 | 10/1 → 10/8 | 11/20–11/24 | 12/21 → 2027/1/25 | [Main-track CFP](https://warwick.ac.uk/fac/sci/dcs/aamas2027/calls/call-for-main-track/)。Proceedings/Findings 合并。 |
| WWW 2027 长文 | 10/18 → 10/25 | 12/15–12/20 | 2027/1/4 → 1/31 | [Research CFP](https://www2027.thewebconf.org/research-track-papers/)。采用当前 CFP，不沿用聚合网站的旧回复日期。 |
| AISTATS 2027 | 9/29 → 10/6 | 11/16 释评；讨论至 12/3 | 2027/1/20 → 模拟 2/3 | [CFP](https://virtual.aistats.org/Conferences/2027/CallForPapers)、[AC guide](https://virtual.aistats.org/Conferences/2027/ACGuidelines)。终稿 TBD。真实 AI 检查不打分，最终仍为人类委员会决定。 |
| ICRA 2027 | 无独立摘要；9/16 全文 | 模拟 2027/1/10–1/17 | 2027/1/31 → 模拟 2/28 | [CFP](https://2027.ieee-icra.org/contribute/call-for-icra-2027-papers-now-accepting-submissions/)。截止文字为 23:59 PST，保留 UTC−08；2/6 是最终文件开放，不是截止。 |
| NAACL 2027 | ARR 全文 10/12 | 模拟 11/24–11/30；meta 12/18 | 2027/2/10 → 3/3 | [CFP](https://2027.naacl.org/calls/main_conference_papers/)。commit 12/23；该 CFP 未给作者回应窗口。 |
| COLING 2027 | ARR 全文 10/12 | 模拟 11/24–11/30 | 2027/2/10 → 模拟 2/24 | [CFP](https://2027.coling-iccl.org/calls/main_conference_papers/)。与 NAACL 共用 ARR 周期，但不允许双重 commitment。 |
| CVPR 2027 | 11/10 → 11/16 | 2027/1/25 释评；模拟 2/1 截止 | 2027/2/25 → 模拟 3/11 | [Dates](https://cvpr.thecvf.com/Conferences/2027/Dates)、[作者指南](https://cvpr.thecvf.com/Conferences/2027/AuthorGuidelines)。回复终点未从引用页核实。 |
| PAKDD 2027 | 无独立摘要；11/20 全文 | 模拟 2027/2/5–2/12 | 2027/2/26 → 3/19 | [Research CFP](https://www.pakdd2027.org/pages/calls/research)。 |
| MLSys 2027 | 10/30 21:00 UTC 全文 | 2027/1/18 20:00 UTC → 1/21 20:00 UTC | 2027/2/28 21:00 UTC → 模拟 3/14 | [CFP](https://mlsys.org/Conferences/2027/CallForResearchPapers)、[首页时间表](https://mlsys.org/)。10/19 20:00 UTC 开放，不能改成 AoE。 |
| FAccT 2027 | 10/27 → 11/3 | 12/22 初步结果；2027/1/28 修订 | 2027/3/23 → 模拟 4/6 | [CFP](https://facctconference.org/2027/cfp.html)。真实 accept/revise/reject 多阶段简化为一次最终模拟决定。 |
| HRI 2027 | 9/11 → 9/18 | 10/28–11/3 | 11/30 → 12/18 | [Full papers](https://humanrobotinteraction.org/2027/full-papers/)。 |

## 稿件与回复规则

核心页数、匿名要求、参考文献/附录处理直接写入每个会议的 `format`，避免居民依赖无法打开的会议官网。已确认的模板链接指向真实资源，例如 [ACL 样式库](https://github.com/acl-org/acl-style-files)、[ACM acmart](https://github.com/borisveytsman/acmart)、[CVPR author kit](https://github.com/cvpr-org/author-kit)、[ISMIR 2026 tag](https://github.com/ismir/paper_templates/tree/2026v1)。NeurIPS、ICLR 等只提供官方 ZIP 的，保留真实下载 URL；不能把日期页冒充模板。模板是否能被居民取得还受 point-in-time 浏览器的域名及历史版本限制；这里不声称外网 ZIP 已通过该浏览器开放。

- RecSys：实现 500 字符上限，禁止回复附件、修订稿；科学内容只用于纠正误解。NeurIPS：实现单次合并回复 10,000 字符、禁止附件和修订稿，比官方每评审分别 10,000 字符更保守。[RecSys](https://recsys.acm.org/recsys26/call/)、[NeurIPS handbook](https://neurips.cc/Conferences/2026/MainTrackHandbook)。
- ICLR、CHI、FAccT：显式传入 `paper` / `pdf` 时冻结修订稿，评审同时保留原稿及修订稿；只采用最后一次回复，未实现交互式多轮问答。ICLR 初稿 9 页、回复与终稿 10 页，参考文献、附录及规定的声明不计入正文。[ICLR author guide](https://iclr.cc/Conferences/2027/AuthorGuidelines)。
- CVPR：真实回复为一页 PDF，禁止链接和未经请求的新实验；模拟改为 4,000 字符文本且禁止附件/修订稿。无法从文字机械判断“未经请求”，交由评审辨别。[CVPR author guide](https://cvpr.thecvf.com/Conferences/2027/AuthorGuidelines)。
- 其他未核实字符上限的会议默认 24,000 字符回复，允许总计 40,000 字符的文本证据附件，默认不允许修订主稿。这些是模拟容量规则，不能引用为官方政策。
- [ACM MM 作者说明](https://2026.acmmm.org/site/author-instructions.html)、[ISMIR 作者说明](https://ismir2026.ismir.net/authors/author-guidelines)、[PAKDD author kit](https://www.pakdd2027.org/pages/calls/authors-kit) 用于补足各自格式。PAKDD 的真实 AI 使用限制不允许把本实验产物视作符合真实投稿资格；所有会务操作均只在模拟中发生。

## 执行协议与可复现范围

居民手动 `register` 标题/摘要后 `submit` LaTeX 与 PDF；全组只能有一个 active submission，其他草稿可自由编辑。提交时冻结 Git revision、供审文本和 PDF 哈希/页数。检查确认 LaTeX 有非空 document body、PDF 可读取且有页；这不证明编译成功、PDF 与源码一致或满足视觉排版，评审也不能声称已渲染/独立复现。

到释评时间由同一外部模型按方法、证据、贡献三个不同角色分别评审。三份结果全部成功后才进入居民可读 records；原始输入、尝试及缓存保留在 host-private 目录。回应可覆盖，ARR 还须显式 `commit`；未 commitment 无会议决定或奖励。到通知时间，三角色结合原稿、原评审和最新回应更新评价，再由 meta-review 给出模拟 accept/reject 与理由。角色差异不是三个独立人类专家或独立模型的保证；新颖性判断限定为提交时所供文献，不能证明模型完全遗忘未来知识。

只在最终决定发放阶段资金：每人 `floor(max_reward_per_resident × (overall−1) / 9)`，默认上限 1260，拒稿仍可因有证据的科学贡献获得对应金额。Git 会务状态随 checkpoint 回滚，私有缓存复用同一输入，防止恢复重评和重复支付。API、schema、引用或输入容量失败会明确中止，不伪造成功；源稿不因回复变长而截断。完整评审输入上限 240,000 字符，超限要求缩减可选证据后重试。接受后仍须提交 camera-ready；错过截止明确记为 missing，不假装出版。

这套流程不模拟真实系统账号/费用、互惠审稿、伦理委员会、出版注册、公开讨论、早拒、分会轨道转移或旧 ARR 审稿跨会复用；不向真实会议发送任何内容。会议的范围、证据标准及已实现的提交规则用于模拟科学评审，结果不能表述为真实会议录用。
