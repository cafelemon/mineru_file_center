import React, { useEffect, useRef, useState } from "react";

const NAV_ITEMS = [
  { id: "overview", label: "成果总览" },
  { id: "tracks", label: "核心主线" },
  { id: "timeline", label: "阶段成果" },
  { id: "gallery", label: "截图展示" },
  { id: "roadmap", label: "后续规划" },
];

const METRICS = [
  {
    value: "6 周",
    label: "阶段推进",
    note: "完成从业务理解、方案规划到系统验证的首轮闭环",
  },
  {
    value: "57.7 → 74.6",
    label: "知识库准确率",
    note: "通过工作流优化、检索策略迭代与模型配置验证实现提升",
  },
  {
    value: "30% → 70%+",
    label: "文档入库合格率",
    note: "借助 MinerU 与视觉转码链路，显著改善扫描版文档可用性",
  },
  {
    value: "多项搭建完成",
    label: "系统与平台能力",
    note: "涵盖桥接系统、Agent 流程、插件探索、文件管理方案验证",
  },
];

const CORE_TRACKS = [
  {
    title: "产品与业务规划",
    description:
      "围绕医患 AI 协同平台、AI 客服、企业知识问答与 AI 中心工作方向，完成需求梳理、竞品分析、MVP 路线与落地边界设计。",
    tags: ["PRD 初稿", "竞品调研", "MVP 路线", "业务理解"],
  },
  {
    title: "知识库系统建设",
    description:
      "从基础问答链路打通，到多层级权限、七库七 Agent、文件清单与维护手册建设，逐步搭建面向企业内部使用的知识库治理框架。",
    tags: ["FastGPT", "多层级权限", "七库七 Agent", "维护机制"],
  },
  {
    title: "AI 工具链与 Agent 能力",
    description:
      "完成 OpenClaw 部署与文档沉淀，调研安全插件与 skills 体系，探索面向不同岗位的工具接入方式与可复用能力模块。",
    tags: ["OpenClaw", "插件调研", "skills 指南", "工具链落地"],
  },
  {
    title: "质量优化与平台演进",
    description:
      "聚焦准确率、入库质量、原文件追溯与桥接系统稳定性验证，不仅推进功能，还同步搭建后续可持续优化的机制与接口基础。",
    tags: ["准确率优化", "MinerU 转码", "原文件追溯", "桥站验证"],
  },
];

const TIMELINE = [
  {
    week: "第 1 周",
    period: "2.24 - 2.28",
    focus: "完成入职熟悉与业务理解，快速建立产品认知与行业语境。",
    actions: [
      "熟悉入职流程与协作方式，明确 AI 方向岗位的工作边界与推进节奏。",
      "系统学习智能网联胶囊系统，理解工作原理、业务愿景与后续承接空间。",
      "开展竞品分析，围绕医患 AI 协同平台拆分九大板块并输出差异化对照。",
    ],
    output:
      "形成医患 AI 协同平台 PRD 初稿，完成需求背景、用户画像、场景与核心定位的第一轮梳理。",
  },
  {
    week: "第 2 周",
    period: "3.02 - 3.06",
    focus: "从调研进入方案与链路验证阶段，开始搭建可落地的基础能力。",
    actions: [
      "完成云端 AI 赋能方向调研，并输出专题报告，支撑后续方案比较与选型。",
      "基于既有框架打通知识问答基础链路，验证本地知识库问答的可行性。",
      "部署 OpenClaw，沉淀使用指南，并同步规划 AI 客服与内部知识库升级方向。",
    ],
    output:
      "完成云端调研报告、本地问答链路初版验证，以及 AI 客服和知识库升级的产品规划材料。",
  },
  {
    week: "第 3 周",
    period: "3.09 - 3.13",
    focus: "把单点工具验证推进到企业接入方案与效果优化，开始形成技术主线。",
    actions: [
      "输出企微嵌入智能网联胶囊系统的落地路线，明确 MVP 与后续优化路径。",
      "完成飞书与知识库系统中转桥站搭建，验证信息安全前提下的接入方式。",
      "对问答链路进行流程和检索优化，搭建 Agent 工作流，提升准确率表现。",
    ],
    output:
      "完成飞书桥接系统验证，知识库准确率由 57.7 提升到 74.6，并启动 OpenClaw 插件与 skills 调研。",
  },
  {
    week: "第 4 周",
    period: "3.16 - 3.20",
    focus: "从功能可用向企业级治理演进，建立权限、库层与维护能力。",
    actions: [
      "完成知识库全面升级，基于角色和部门设计多层级分级管理架构。",
      "按业务划分七个知识库并挂载七个 Agent，配置差异化提示词和流程策略。",
      "搭建桥站核心能力、飞书机器人与日志、压测、连通等企业级验证链路。",
    ],
    output:
      "形成知识库文件盘点与维护手册，完成多层级知识库架构、飞书机器人及后续企微迁移接口预留。",
  },
  {
    week: "第 5 周",
    period: "3.23 - 3.27",
    focus: "围绕规模化应用提前补齐基础设施与方法论，提升后续扩展效率。",
    actions: [
      "梳理 AI 中心后续工作计划，准备面向各部门个性化 AI 办公需求的访谈提纲。",
      "部署 MinerU 平台，针对扫描版、截图版文档建立视觉转码方案，提高入库可用率。",
      "持续完善 OpenClaw 双版本部署说明，并按部门输出初版 skills 安装测评指南。",
    ],
    output:
      "文档入库合格率由约 30% 提升至 70% 左右，同时完成胶囊系统流程梳理与 skills 评测的首版方法框架。",
  },
  {
    week: "第 6 周",
    period: "3.30 - 4.03",
    focus: "开始向体系化平台延伸，验证文件管理、原文件追溯和数据建设方向。",
    actions: [
      "提出文件管理系统方案，承担 OCR、视觉转码、标记赋码与入库文件管理中枢角色。",
      "设计桥接系统中的原文件请求模块，为飞书侧原文件查看与下载能力做验证准备。",
      "结合医疗器械法规论坛学习，整理纪要并提出高质量数据集初版方案与 AI 沙龙主题。",
    ],
    output:
      "完成文件管理系统与原文件链接方案的初步验证，明确下一阶段数据治理、场景承接与对外服务衔接方向。",
  },
];

const HIGHLIGHTS = [
  {
    title: "知识库准确率显著提升",
    value: "74.6",
    delta: "+16.9pt",
    description:
      "通过 Agent 工作流、检索策略和模型配置优化，LLM Test 结果由 57.7 提升至 74.6。",
  },
  {
    title: "文档入库质量改善",
    value: "70%+",
    delta: "约 2.3 倍",
    description:
      "针对扫描版、截图版资料建立 MinerU + 视觉转码方案，显著提升知识库可入库资料占比。",
  },
  {
    title: "分级治理架构成型",
    value: "7 库 7 Agent",
    delta: "已落地",
    description:
      "完成多层级权限与分级管理架构设计，具备面向管理层、部门与通用库的差异化承接能力。",
  },
  {
    title: "企业级接入链路验证",
    value: "桥站 + 飞书",
    delta: "已打通",
    description:
      "完成飞书桥接系统与企业应用接入链路验证，并补齐日志、压测、连通与权限隔离等关键环节。",
  },
  {
    title: "原文件追溯方案形成",
    value: "方案可验证",
    delta: "持续推进",
    description:
      "围绕企微承接与原文件访问需求，提出文件管理系统与桥接请求模块，为后续服务闭环预留接口。",
  },
];

// 图片路径使用 new URL 写死在组件中，便于直接运行；
// 后续如放入 public 目录，可将 src 替换为 '/your-image-path.png'。
const SCREENSHOTS = [
  {
    title: "知识库问答界面",
    description: "问答结果已开始具备结论、依据与说明的结构化输出能力。",
    category: "问答效果",
    span: "lg:col-span-5",
    src: new URL("./截图/image 2.png", import.meta.url).href,
  },
  {
    title: "本地知识问答链路验证",
    description: "完成本地版知识库问答链路打通，并结合模型参数进行效果调优。",
    category: "链路验证",
    span: "lg:col-span-7",
    src: new URL("./截图/img_v3_02vd_0a695680-fe10-4b50-bdbb-dc6107195f3g.jpg", import.meta.url).href,
  },
  {
    title: "OpenClaw 部署界面",
    description: "完成平台部署、运行验证与使用文档沉淀，形成可复用的工具接入基础。",
    category: "工具平台",
    span: "lg:col-span-6",
    src: new URL("./截图/image.png", import.meta.url).href,
  },
  {
    title: "飞书桥接与代码运行界面",
    description: "桥接服务采用本地运行模式，支撑飞书企业应用与知识库的安全对接。",
    category: "桥接系统",
    span: "lg:col-span-6",
    src: new URL("./截图/image 1.png", import.meta.url).href,
  },
  {
    title: "Agent 工作流编排",
    description: "围绕意图分类、问题分发与知识检索构建工作流，提高问答稳定性与准确率。",
    category: "Agent 流程",
    span: "lg:col-span-8",
    src: new URL("./截图/image 3.png", import.meta.url).href,
  },
  {
    title: "插件与 skills 探索界面",
    description: "围绕安全可控的插件与技能体系做前置调研，为部门级能力复用准备基础。",
    category: "能力模块",
    span: "lg:col-span-4",
    src: new URL("./截图/image 4.png", import.meta.url).href,
  },
  {
    title: "MinerU 文档转码结果",
    description: "验证扫描版 PDF 转为可搜索文本与结构化分块的可行性，支撑入库质量提升。",
    category: "数据治理",
    span: "lg:col-span-4",
    src: new URL("./截图/img_v3_02105_692fe7b8-c6a3-4993-afb8-0e26b9a882ag.jpg", import.meta.url).href,
  },
  {
    title: "原文件追溯与引用证明",
    description: "问答链路已开始保留来源依据，为后续原文件追溯与下载能力铺路。",
    category: "可追溯性",
    span: "lg:col-span-4",
    src: new URL("./截图/img_v3_02105_bacee054-0574-4a71-9a91-2922773efc3g.jpg", import.meta.url).href,
  },
  {
    title: "文件管理系统方案验证",
    description: "提出统一文件管理与解析中枢，用于承接 OCR、赋码、追溯与入库管理。",
    category: "平台演进",
    span: "lg:col-span-4",
    src: new URL("./截图/d1759bd7-7ec2-4649-96f3-4913c498ea48.png", import.meta.url).href,
  },
];

const NEXT_STEPS = [
  {
    title: "内部知识库持续优化与文件管理系统建设",
    description:
      "继续推进文档治理、OCR 转码、原文件赋码与检索可追溯能力，形成稳定、可维护的知识资产管理底座。",
  },
  {
    title: "智能网联胶囊系统与企微服务体系承接",
    description:
      "围绕企微入口、桥接系统和业务服务流程设计承接机制，逐步打通 AI 能力到具体业务触点的应用闭环。",
  },
  {
    title: "面向各部门的 AI 办公能力与 skills 体系建设",
    description:
      "结合部门访谈与场景梳理，沉淀可复制的 AI 办公方法、技能包与评测规范，推动多部门逐步落地。",
  },
];

function cn(...classes) {
  return classes.filter(Boolean).join(" ");
}

function Reveal({ children, className = "", delay = 0 }) {
  const ref = useRef(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return undefined;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { threshold: 0.16 }
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      className={cn(
        "transition-all duration-700 ease-out will-change-transform",
        visible ? "translate-y-0 opacity-100" : "translate-y-8 opacity-0",
        className
      )}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {children}
    </div>
  );
}

function SectionHeader({ index, eyebrow, title, description, align = "left" }) {
  return (
    <Reveal
      className={cn(
        "mb-10 flex flex-col gap-4",
        align === "center" && "items-center text-center"
      )}
    >
      <div className="inline-flex items-center gap-3">
        <span className="text-5xl font-semibold leading-none text-white/10">
          {index}
        </span>
        <span className="rounded-full border border-emerald-300/20 bg-emerald-300/10 px-3 py-1 text-xs font-medium tracking-[0.24em] text-emerald-200 uppercase">
          {eyebrow}
        </span>
      </div>
      <div className="max-w-3xl">
        <h2 className="text-3xl font-semibold tracking-tight text-white sm:text-4xl">
          {title}
        </h2>
        <p className="mt-4 text-sm leading-7 text-slate-300 sm:text-base">
          {description}
        </p>
      </div>
    </Reveal>
  );
}

function ArrowUpRight() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      className="h-4 w-4"
      aria-hidden="true"
    >
      <path d="M7 17 17 7" />
      <path d="M8 7h9v9" />
    </svg>
  );
}

export default function TrialReviewShowcase() {
  const [activeSection, setActiveSection] = useState("overview");
  const [isScrolled, setIsScrolled] = useState(false);
  const [selectedShot, setSelectedShot] = useState(null);

  useEffect(() => {
    const onScroll = () => setIsScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const sections = NAV_ITEMS.map((item) => document.getElementById(item.id)).filter(
      Boolean
    );

    if (!sections.length) return undefined;

    const observer = new IntersectionObserver(
      (entries) => {
        const visibleEntries = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);

        if (visibleEntries[0]?.target?.id) {
          setActiveSection(visibleEntries[0].target.id);
        }
      },
      {
        rootMargin: "-28% 0px -45% 0px",
        threshold: [0.15, 0.35, 0.6],
      }
    );

    sections.forEach((section) => observer.observe(section));
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!selectedShot) return undefined;

    const onKeyDown = (event) => {
      if (event.key === "Escape") {
        setSelectedShot(null);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedShot]);

  const scrollToSection = (sectionId) => {
    const section = document.getElementById(sectionId);
    if (!section) return;

    const top = section.getBoundingClientRect().top + window.scrollY - 92;
    window.scrollTo({ top, behavior: "smooth" });
  };

  return (
    <div
      className="min-h-screen bg-[#06101d] text-white antialiased"
      style={{
        fontFamily:
          "'Barlow','Source Han Sans SC','PingFang SC','Microsoft YaHei',sans-serif",
      }}
    >
      <div className="pointer-events-none fixed inset-0 overflow-hidden">
        <div className="absolute inset-x-0 top-0 h-[42rem] bg-[radial-gradient(circle_at_top,_rgba(59,130,246,0.24),_transparent_34%),radial-gradient(circle_at_20%_20%,_rgba(16,185,129,0.24),_transparent_28%),linear-gradient(180deg,_#0b1930_0%,_#06101d_70%)]" />
        <div className="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,0.03)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.03)_1px,transparent_1px)] bg-[size:72px_72px] [mask-image:linear-gradient(180deg,rgba(255,255,255,0.38),transparent_80%)]" />
        <div className="absolute left-[8%] top-[7rem] h-44 w-44 rounded-full bg-cyan-400/10 blur-3xl" />
        <div className="absolute right-[10%] top-[16rem] h-64 w-64 rounded-full bg-emerald-400/10 blur-3xl" />
        <div className="absolute bottom-[12rem] left-[20%] h-52 w-52 rounded-full bg-indigo-400/10 blur-3xl" />
      </div>

      <header
        className={cn(
          "fixed inset-x-0 top-0 z-40 transition-all duration-500",
          isScrolled
            ? "border-b border-white/10 bg-slate-950/[0.72] shadow-[0_16px_50px_rgba(0,0,0,0.28)] backdrop-blur-xl"
            : "bg-slate-950/[0.24] backdrop-blur-md"
        )}
      >
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
          <button
            type="button"
            onClick={() => scrollToSection("overview")}
            className="group flex items-center gap-3 text-left"
          >
            <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-emerald-300/25 bg-white/[0.08] text-sm font-semibold tracking-[0.2em] text-emerald-100 shadow-[0_10px_30px_rgba(16,185,129,0.15)]">
              ZST
            </div>
            <div>
              <p className="text-[11px] uppercase tracking-[0.32em] text-slate-400">
                Trial Review
              </p>
              <p className="text-sm font-medium text-white transition-colors group-hover:text-emerald-200">
                试用期首次考核成果展示
              </p>
            </div>
          </button>

          <nav className="hidden items-center gap-1 rounded-full border border-white/10 bg-white/[0.06] p-1.5 md:flex">
            {NAV_ITEMS.map((item) => {
              const active = activeSection === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => scrollToSection(item.id)}
                  className={cn(
                    "rounded-full px-4 py-2 text-sm transition-all duration-300",
                    active
                      ? "bg-emerald-300 text-slate-950 shadow-[0_10px_24px_rgba(134,239,172,0.24)]"
                      : "text-slate-300 hover:bg-white/[0.08] hover:text-white"
                  )}
                >
                  {item.label}
                </button>
              );
            })}
          </nav>
        </div>

        <div className="mx-auto flex max-w-7xl gap-2 overflow-x-auto px-4 pb-3 md:hidden sm:px-6">
          {NAV_ITEMS.map((item) => {
            const active = activeSection === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => scrollToSection(item.id)}
                className={cn(
                  "whitespace-nowrap rounded-full border px-3 py-1.5 text-xs transition-all",
                  active
                    ? "border-emerald-200/30 bg-emerald-300 text-slate-950"
                    : "border-white/10 bg-white/5 text-slate-300"
                )}
              >
                {item.label}
              </button>
            );
          })}
        </div>
      </header>

      <main className="relative z-10">
        <section id="overview" className="px-4 pb-20 pt-28 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-7xl">
            <Reveal className="relative overflow-hidden rounded-[2rem] border border-white/10 bg-white/[0.04] px-6 py-10 shadow-[0_40px_120px_rgba(2,6,23,0.42)] backdrop-blur-xl sm:px-10 sm:py-14 lg:px-14 lg:py-16">
              <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-emerald-300/80 to-transparent" />
              <div className="absolute right-0 top-0 h-40 w-40 translate-x-1/4 -translate-y-1/4 rounded-full bg-emerald-300/[0.12] blur-3xl" />
              <div className="absolute bottom-0 left-0 h-48 w-48 -translate-x-1/3 translate-y-1/3 rounded-full bg-cyan-400/[0.12] blur-3xl" />

              <div className="relative grid gap-10 lg:grid-cols-[1.2fr_0.8fr] lg:items-end">
                <div>
                  <span className="inline-flex items-center gap-2 rounded-full border border-emerald-300/20 bg-emerald-300/10 px-4 py-2 text-xs font-medium tracking-[0.28em] text-emerald-100 uppercase">
                    AI Product Planning • Knowledge Base • Agent Practice
                  </span>
                  <h1 className="mt-6 max-w-4xl text-4xl font-semibold leading-tight tracking-tight text-white sm:text-5xl lg:text-6xl">
                    浙江势通机器人有限公司｜
                    <span className="block bg-gradient-to-r from-white via-cyan-100 to-emerald-100 bg-clip-text text-transparent">
                      试用期首次考核成果展示
                    </span>
                  </h1>
                  <p className="mt-6 max-w-3xl text-lg leading-8 text-slate-300">
                    AI 产品规划 × 知识库建设 × Agent 落地 × 企业级 AI 体系探索
                  </p>
                  <p className="mt-6 max-w-3xl text-sm leading-8 text-slate-300 sm:text-base">
                    首月阶段已围绕业务理解、方案规划、系统搭建、效果验证与质量优化，初步形成从“需求分析”到“能力原型”和“平台演进设想”的推进闭环。重点不止于完成单项任务，而是在逐步搭建企业内部可复用、可维护、可演进的 AI 能力机制。
                  </p>

                  <div className="mt-8 flex flex-wrap gap-3">
                    {["首月阶段成果", "知识资产治理", "企业级 AI 验证", "平台化演进"].map(
                      (item) => (
                        <span
                          key={item}
                          className="rounded-full border border-white/10 bg-white/[0.06] px-3 py-2 text-xs text-slate-200"
                        >
                          {item}
                        </span>
                      )
                    )}
                  </div>
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  {METRICS.map((metric, index) => (
                    <Reveal
                      key={metric.label}
                      delay={index * 90}
                      className="rounded-[1.5rem] border border-white/10 bg-slate-950/[0.45] p-5 shadow-[0_16px_50px_rgba(15,23,42,0.35)]"
                    >
                      <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                        {metric.label}
                      </p>
                      <p className="mt-3 text-2xl font-semibold text-white sm:text-[1.75rem]">
                        {metric.value}
                      </p>
                      <p className="mt-3 text-sm leading-6 text-slate-300">
                        {metric.note}
                      </p>
                    </Reveal>
                  ))}
                </div>
              </div>
            </Reveal>
          </div>
        </section>

        <section className="px-4 py-20 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-7xl">
            <SectionHeader
              index="01"
              eyebrow="Core Tracks"
              title="核心主线"
              description="围绕产品规划、知识库系统、工具链与质量演进四条主线同步推进，既覆盖当下可交付成果，也为后续企业级 AI 体系建设打底。"
            />

            <div id="tracks" className="grid gap-6 lg:grid-cols-2">
              {CORE_TRACKS.map((track, index) => (
                <Reveal
                  key={track.title}
                  delay={index * 80}
                  className="group rounded-[1.75rem] border border-white/10 bg-white/[0.05] p-6 shadow-[0_18px_60px_rgba(2,6,23,0.24)] transition-all duration-300 hover:-translate-y-1 hover:border-emerald-200/20 hover:bg-white/[0.07]"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h3 className="text-2xl font-semibold text-white">
                        {track.title}
                      </h3>
                      <p className="mt-4 text-sm leading-7 text-slate-300">
                        {track.description}
                      </p>
                    </div>
                    <div className="mt-1 rounded-2xl border border-emerald-200/20 bg-emerald-300/10 p-3 text-emerald-100">
                      <ArrowUpRight />
                    </div>
                  </div>
                  <div className="mt-6 flex flex-wrap gap-2">
                    {track.tags.map((tag) => (
                      <span
                        key={tag}
                        className="rounded-full border border-white/10 bg-slate-950/50 px-3 py-1.5 text-xs text-slate-200"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        <section className="px-4 py-20 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-7xl">
            <SectionHeader
              index="02"
              eyebrow="Weekly Progress"
              title="阶段成果时间轴"
              description="以六周为单位梳理“本周重点、关键动作、阶段产出”，突出推进主线与能力沉淀，而非简单流水账式罗列。"
            />

            <div id="timeline" className="relative">
              <div className="absolute left-[1.15rem] top-0 hidden h-full w-px bg-gradient-to-b from-emerald-300/70 via-cyan-300/[0.35] to-transparent lg:block" />
              <div className="space-y-6">
                {TIMELINE.map((item, index) => (
                  <Reveal
                    key={item.week}
                    delay={index * 60}
                    className="relative rounded-[1.75rem] border border-white/10 bg-white/[0.04] p-6 shadow-[0_16px_48px_rgba(2,6,23,0.22)] lg:ml-10 lg:grid lg:grid-cols-[180px_1fr] lg:gap-8"
                  >
                    <div className="relative">
                      <div className="absolute -left-[2.75rem] top-1 hidden h-5 w-5 rounded-full border border-emerald-200/40 bg-emerald-300 shadow-[0_0_0_6px_rgba(16,185,129,0.12)] lg:block" />
                      <p className="text-sm uppercase tracking-[0.22em] text-emerald-100">
                        {item.week}
                      </p>
                      <p className="mt-2 text-sm text-slate-400">{item.period}</p>
                    </div>

                    <div className="mt-6 lg:mt-0">
                      <div className="grid gap-5 lg:grid-cols-[1fr_1.2fr_1fr]">
                        <div className="rounded-2xl border border-white/[0.08] bg-slate-950/40 p-5">
                          <p className="text-xs uppercase tracking-[0.18em] text-slate-400">
                            本周重点
                          </p>
                          <p className="mt-3 text-sm leading-7 text-slate-200">
                            {item.focus}
                          </p>
                        </div>
                        <div className="rounded-2xl border border-white/[0.08] bg-slate-950/40 p-5">
                          <p className="text-xs uppercase tracking-[0.18em] text-slate-400">
                            关键动作
                          </p>
                          <div className="mt-3 space-y-3 text-sm leading-7 text-slate-200">
                            {item.actions.map((action) => (
                              <div key={action} className="flex gap-3">
                                <span className="mt-2 h-1.5 w-1.5 flex-none rounded-full bg-emerald-300" />
                                <p>{action}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                        <div className="rounded-2xl border border-emerald-300/10 bg-[linear-gradient(180deg,rgba(16,185,129,0.12),rgba(15,23,42,0.5))] p-5">
                          <p className="text-xs uppercase tracking-[0.18em] text-emerald-100">
                            阶段产出
                          </p>
                          <p className="mt-3 text-sm leading-7 text-slate-100">
                            {item.output}
                          </p>
                        </div>
                      </div>
                    </div>
                  </Reveal>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="px-4 py-20 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-7xl">
            <SectionHeader
              index="03"
              eyebrow="Key Results"
              title="核心成果亮点"
              description="这一阶段的价值不止体现在指标提升，更体现在企业知识治理、服务接入与平台演进机制的初步形成。"
            />

            <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
              <Reveal className="overflow-hidden rounded-[2rem] border border-white/10 bg-[linear-gradient(145deg,rgba(10,20,40,0.95),rgba(6,16,29,0.78))] p-7 shadow-[0_24px_80px_rgba(2,6,23,0.32)]">
                <div className="flex flex-col gap-6">
                  <div className="flex items-center justify-between gap-4">
                    <div>
                      <p className="text-xs uppercase tracking-[0.24em] text-slate-400">
                        Capability Build-up
                      </p>
                      <h3 className="mt-3 text-3xl font-semibold text-white">
                        从任务执行到能力与机制搭建
                      </h3>
                    </div>
                    <div className="rounded-full border border-emerald-200/20 bg-emerald-300/10 px-4 py-2 text-sm text-emerald-100">
                      首阶段闭环已形成
                    </div>
                  </div>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="rounded-[1.5rem] border border-white/10 bg-white/[0.05] p-5">
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-400">
                        准确率提升
                      </p>
                      <p className="mt-3 text-4xl font-semibold text-white">+16.9pt</p>
                      <p className="mt-3 text-sm leading-7 text-slate-300">
                        问答质量提升已经不只是模型替换，而是工作流、检索、Rerank 与知识治理的综合结果。
                      </p>
                    </div>
                    <div className="rounded-[1.5rem] border border-white/10 bg-white/[0.05] p-5">
                      <p className="text-xs uppercase tracking-[0.18em] text-slate-400">
                        入库质量提升
                      </p>
                      <p className="mt-3 text-4xl font-semibold text-white">70%+</p>
                      <p className="mt-3 text-sm leading-7 text-slate-300">
                        文档转码链路让历史资料逐步具备可治理、可检索、可持续维护的基础条件。
                      </p>
                    </div>
                  </div>

                  <div className="rounded-[1.75rem] border border-emerald-300/10 bg-emerald-300/10 p-6">
                    <p className="text-sm leading-8 text-slate-100">
                      本阶段的推进逻辑已经逐步清晰：以知识库为核心底座，以桥接系统为接入中枢，以 OpenClaw / skills 为工具能力探索，以文件管理和原文件追溯为后续体系化建设预埋接口。
                    </p>
                  </div>
                </div>
              </Reveal>

              <div className="grid gap-4">
                {HIGHLIGHTS.map((item, index) => (
                  <Reveal
                    key={item.title}
                    delay={index * 70}
                    className="rounded-[1.5rem] border border-white/10 bg-white/[0.05] p-5"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <h3 className="text-lg font-semibold text-white">
                          {item.title}
                        </h3>
                        <p className="mt-3 text-sm leading-7 text-slate-300">
                          {item.description}
                        </p>
                      </div>
                      <span className="rounded-full border border-emerald-200/20 bg-emerald-300/10 px-3 py-1 text-xs text-emerald-100">
                        {item.delta}
                      </span>
                    </div>
                    <p className="mt-5 text-2xl font-semibold text-white">{item.value}</p>
                  </Reveal>
                ))}
              </div>
            </div>
          </div>
        </section>

        <section className="px-4 py-20 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-7xl">
            <SectionHeader
              index="04"
              eyebrow="Evidence Gallery"
              title="截图展示墙"
              description="以成果界面为证明材料，展示知识问答、桥接系统、Agent 工作流、插件与 skills 探索，以及平台演进方向的关键画面。"
            />

            <div id="gallery" className="grid gap-5 lg:grid-cols-12">
              {SCREENSHOTS.map((item, index) => (
                <Reveal
                  key={item.title}
                  delay={index * 45}
                  className={cn(
                    "group overflow-hidden rounded-[1.75rem] border border-white/10 bg-white/[0.05] shadow-[0_18px_48px_rgba(2,6,23,0.24)]",
                    item.span
                  )}
                >
                  <button
                    type="button"
                    onClick={() => setSelectedShot(item)}
                    className="block h-full w-full text-left"
                  >
                    <div className="relative overflow-hidden">
                      <img
                        src={item.src}
                        alt={item.title}
                        className="h-56 w-full object-cover transition-transform duration-500 group-hover:scale-[1.03] sm:h-64"
                      />
                      <div className="absolute inset-0 bg-gradient-to-t from-slate-950/70 via-slate-950/10 to-transparent" />
                      <div className="absolute left-4 top-4 rounded-full border border-white/10 bg-slate-950/[0.65] px-3 py-1 text-xs text-slate-100 backdrop-blur">
                        {item.category}
                      </div>
                    </div>
                    <div className="p-5">
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <h3 className="text-lg font-semibold text-white">
                            {item.title}
                          </h3>
                          <p className="mt-3 text-sm leading-7 text-slate-300">
                            {item.description}
                          </p>
                        </div>
                        <div className="rounded-full border border-white/10 bg-white/5 p-2 text-slate-200 transition-colors group-hover:border-emerald-200/20 group-hover:bg-emerald-300/10 group-hover:text-emerald-100">
                          <ArrowUpRight />
                        </div>
                      </div>
                    </div>
                  </button>
                </Reveal>
              ))}
            </div>
          </div>
        </section>

        <section id="roadmap" className="px-4 py-20 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-7xl">
            <SectionHeader
              index="05"
              eyebrow="Next Phase"
              title="后续规划"
              description="下一阶段将从“能做出来”进一步走向“能持续治理、能服务承接、能规模复制”，把已有验证能力逐步转化为组织可用的体系。"
            />

            <div className="grid gap-6 lg:grid-cols-3">
              {NEXT_STEPS.map((item, index) => (
                <Reveal
                  key={item.title}
                  delay={index * 80}
                  className="rounded-[1.75rem] border border-white/10 bg-[linear-gradient(180deg,rgba(255,255,255,0.06),rgba(255,255,255,0.03))] p-6"
                >
                  <div className="inline-flex rounded-full border border-emerald-300/20 bg-emerald-300/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-emerald-100">
                    方向 0{index + 1}
                  </div>
                  <h3 className="mt-5 text-2xl font-semibold text-white">
                    {item.title}
                  </h3>
                  <p className="mt-4 text-sm leading-7 text-slate-300">
                    {item.description}
                  </p>
                </Reveal>
              ))}
            </div>

            <Reveal className="mt-10 overflow-hidden rounded-[2rem] border border-emerald-300/10 bg-[linear-gradient(135deg,rgba(16,185,129,0.18),rgba(12,22,38,0.95))] px-6 py-8 shadow-[0_20px_60px_rgba(2,6,23,0.28)] sm:px-8">
              <p className="text-lg leading-9 text-white sm:text-[1.3rem]">
                试用期首阶段已完成从规划到验证的初步闭环，下一阶段将继续推动知识库体系化、服务体系承接与 AI 场景落地。
              </p>
            </Reveal>
          </div>
        </section>
      </main>

      <footer className="relative z-10 px-4 pb-10 pt-4 text-center text-sm text-slate-500 sm:px-6 lg:px-8">
        浙江势通机器人科技有限公司
      </footer>

      {selectedShot && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/[0.82] px-4 py-8 backdrop-blur-md"
          onClick={() => setSelectedShot(null)}
          role="presentation"
        >
          <div
            className="max-h-full w-full max-w-6xl overflow-hidden rounded-[1.75rem] border border-white/10 bg-[#07111f] shadow-[0_30px_120px_rgba(0,0,0,0.5)]"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label={selectedShot.title}
          >
            <div className="flex items-center justify-between gap-4 border-b border-white/10 px-5 py-4">
              <div>
                <p className="text-xs uppercase tracking-[0.2em] text-emerald-100">
                  {selectedShot.category}
                </p>
                <h3 className="mt-2 text-xl font-semibold text-white">
                  {selectedShot.title}
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setSelectedShot(null)}
                className="rounded-full border border-white/10 bg-white/5 px-3 py-2 text-sm text-slate-200 transition hover:bg-white/10"
              >
                关闭
              </button>
            </div>
            <div className="grid gap-0 lg:grid-cols-[1.25fr_0.75fr]">
              <div className="bg-slate-950/50 p-4">
                <img
                  src={selectedShot.src}
                  alt={selectedShot.title}
                  className="max-h-[72vh] w-full rounded-[1.25rem] object-contain"
                />
              </div>
              <div className="flex flex-col justify-between border-t border-white/10 p-6 lg:border-l lg:border-t-0">
                <div>
                  <p className="text-sm leading-8 text-slate-300">
                    {selectedShot.description}
                  </p>
                  <div className="mt-6 rounded-2xl border border-emerald-300/10 bg-emerald-300/10 p-4 text-sm leading-7 text-slate-100">
                    该区域已预留为静态图片数据结构。后续如需替换真实成果图，只需修改组件顶部
                    <span className="mx-1 rounded bg-black/20 px-1.5 py-0.5 text-xs text-emerald-100">
                      SCREENSHOTS
                    </span>
                    数组中的标题、说明与图片路径即可。
                  </div>
                </div>
                <div className="mt-8 text-xs uppercase tracking-[0.18em] text-slate-500">
                  Click outside or press ESC to close
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
