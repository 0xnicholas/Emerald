import type { Memory, Profile, SearchMemory, Space } from "./types";

export const MOCK_PROFILE: Profile = {
  entity_id: "demo_user",
  static: [
    { content: "全栈工程师，5 年后端 + 3 年前端经验", importance: 0.95 },
    { content: "偏好 TypeScript 和 Rust", importance: 0.9 },
    { content: "使用 Neovim 作为主要编辑器", importance: 0.85 },
    { content: "开源项目活跃贡献者", importance: 0.8 },
    { content: "喜欢函数式编程范式", importance: 0.75 },
  ],
  dynamic: [
    { content: "正在重构支付模块的微服务架构", relevance: 0.9, source: "conversation" },
    { content: "调试生产环境 Redis 限流问题", relevance: 0.85, source: "conversation" },
    { content: "调研 ClickHouse 作为分析数据库", relevance: 0.7, source: "conversation" },
  ],
  memory_count: 42,
  computed_at: new Date().toISOString(),
  version: 3,
};

export const MOCK_SPACES: Space[] = [
  { containerTag: "default", name: "My Space", emoji: "📁", entityId: "demo_user", memoryCount: 8, createdAt: "2026-01-01T00:00:00Z", updatedAt: "2026-07-10T00:00:00Z" },
  { containerTag: "work", name: "Work", emoji: "💼", entityId: "demo_user", memoryCount: 5, createdAt: "2026-02-15T00:00:00Z", updatedAt: "2026-07-09T00:00:00Z" },
  { containerTag: "ideas", name: "Ideas", emoji: "💡", entityId: "demo_user", memoryCount: 3, createdAt: "2026-03-10T00:00:00Z", updatedAt: "2026-07-08T00:00:00Z" },
  { containerTag: "research", name: "Research", emoji: "📚", entityId: "demo_user", memoryCount: 2, createdAt: "2026-04-01T00:00:00Z", updatedAt: "2026-07-07T00:00:00Z" },
];

const baseMemories: SearchMemory[] = [
  {
    id: "mem_001",
    content: "Alex 刚加入 Stripe 担任产品经理，负责支付基础设施团队，管理 5 人团队",
    summary: "Stripe PM 新职位，支付基础设施方向",
    score: 0.95,
    source: "memory",
    memory_type: "fact",
    container_tag: "work",
    is_latest: true,
    document_title: "入职对话",
  },
  {
    id: "mem_002",
    content: "用户表示更喜欢在上午进行代码审查，下午专注编码",
    summary: "工作节奏偏好",
    score: 0.88,
    source: "memory",
    memory_type: "preference",
    container_tag: "work",
    is_latest: true,
    document_title: "工作习惯记录",
  },
  {
    id: "mem_003",
    content: "周一和团队进行了支付系统架构评审，决定采用 CQRS 模式",
    summary: "架构决策：支付系统采用 CQRS",
    score: 0.82,
    source: "memory",
    memory_type: "episodic",
    container_tag: "work",
    is_latest: true,
    document_title: "架构评审会议",
  },
  {
    id: "mem_004",
    content: "用户从 Google 离职，结束了 3 年的云计算平台工程师生涯",
    summary: "离开 Google，结束云计算平台工程师角色",
    score: 0.79,
    source: "memory",
    memory_type: "fact",
    is_latest: false,
  },
  {
    id: "mem_005",
    content: "用户提到对 AI Agent 和记忆系统非常感兴趣，想深入这个领域",
    summary: "对 AI Agent 领域感兴趣",
    score: 0.91,
    source: "memory",
    memory_type: "preference",
    is_latest: true,
  },
  {
    id: "mem_006",
    content: "周三和 Dhravya 讨论了 Emerald 项目的架构设计，确定了图谱优先的策略",
    summary: "与 Dhravya 讨论 Emerald 架构",
    score: 0.85,
    source: "memory",
    memory_type: "episodic",
    container_tag: "ideas",
    is_latest: true,
  },
  {
    id: "mem_007",
    content: "用户搬到西雅图 Capitol 山区域，离新办公室步行 15 分钟",
    summary: "搬至西雅图 Capitol Hill",
    score: 0.73,
    source: "memory",
    memory_type: "fact",
    is_latest: true,
    document_title: "搬家记录",
  },
  {
    id: "mem_008",
    content: "偏好暗色模式，所有编辑器、IDE 和终端都使用暗色主题",
    summary: "暗色模式偏好",
    score: 0.87,
    source: "memory",
    memory_type: "preference",
    is_latest: true,
  },
  {
    id: "mem_009",
    content: "正在调研知识图谱数据库方案，对比 Neo4j 和 SurrealDB 的优劣",
    summary: "调研知识图谱数据库",
    score: 0.84,
    source: "memory",
    memory_type: "episodic",
    container_tag: "research",
    is_latest: true,
    document_title: "技术调研文档",
  },
  {
    id: "mem_010",
    content: "用户表示希望在 Emerald v1 中支持所有主要内容类型：文本、Markdown、代码、PDF、图片、音视频",
    summary: "Emerald v1 内容类型需求",
    score: 0.92,
    source: "memory",
    memory_type: "fact",
    is_latest: true,
    document_title: "产品规划",
  },
  {
    id: "mem_011",
    content: "不喜欢在会议中被打断思路，倾向于异步沟通",
    summary: "异步沟通偏好",
    score: 0.76,
    source: "memory",
    memory_type: "preference",
    is_latest: true,
  },
  {
    id: "mem_012",
    content: "上周五部署了 Emerald 的 alpha 版本到测试环境，发现了几个 Neo4j 连接池的问题",
    summary: "Alpha 部署发现问题",
    score: 0.88,
    source: "memory",
    memory_type: "episodic",
    is_latest: true,
  },
  {
    id: "mem_013",
    content: "用户之前在一家金融科技初创公司担任技术负责人，搭建了支付处理系统",
    summary: "前职：金融科技技术负责人",
    score: 0.81,
    source: "memory",
    memory_type: "fact",
    is_latest: false,
  },
  {
    id: "mem_014",
    content: "阅读了 Supermemory 的论文，对 LongMemEval 基准测试指标有深入研究",
    summary: "研究 Supermemory 论文和基准测试",
    score: 0.83,
    source: "memory",
    memory_type: "episodic",
    container_tag: "research",
    is_latest: true,
  },
  {
    id: "mem_015",
    content: "认为记忆系统不应该只是一个加了个用户 ID 的向量数据库，图谱结构才是核心",
    summary: "对记忆系统架构的核心观点",
    score: 0.94,
    source: "memory",
    memory_type: "fact",
    container_tag: "ideas",
    is_latest: true,
    document_title: "架构笔记",
  },
  {
    id: "rag_001",
    content: "Emerald API 文档：POST /v1/memories 用于添加记忆内容，支持 content_type 参数自动检测类型",
    summary: "API 文档 - 添加记忆",
    score: 0.72,
    source: "rag",
    memory_type: "fact",
    is_latest: true,
    document_id: "doc_api",
    document_title: "API 参考文档",
  },
  {
    id: "rag_002",
    content: "混合搜索（Hybrid Search）同时返回 RAG 结果和记忆结果，默认搜索模式为 hybrid",
    summary: "混合搜索模式说明",
    score: 0.68,
    source: "rag",
    memory_type: "fact",
    is_latest: true,
    document_id: "doc_api",
    document_title: "API 参考文档",
  },
  {
    id: "rag_003",
    content: "用户画像是实体的双层摘要：静态事实（始终相关）和动态事实（近期的、情节性的）",
    summary: "用户画像概念",
    score: 0.65,
    source: "rag",
    memory_type: "fact",
    is_latest: true,
    document_id: "doc_concepts",
    document_title: "核心概念",
  },
];

export const MOCK_MEMORIES = baseMemories;

export const MOCK_SEARCH_RESULTS = {
  results: baseMemories,
  search_mode: "memory",
};

export function getMockSearchResults(
  query: string,
  typeFilter?: string,
  containerTag?: string
): { results: SearchMemory[]; search_mode: string } {
  let filtered = [...baseMemories];
  if (containerTag && containerTag !== "default") {
    filtered = filtered.filter((m) => m.container_tag === containerTag);
  }
  if (query) {
    const q = query.toLowerCase();
    filtered = filtered.filter(
      (m) =>
        m.content.toLowerCase().includes(q) ||
        m.summary.toLowerCase().includes(q) ||
        (m.document_title || "").toLowerCase().includes(q)
    );
  }
  if (typeFilter && typeFilter !== "all") {
    filtered = filtered.filter((m) => m.memory_type === typeFilter);
  }
  return { results: filtered, search_mode: "memory" };
}
