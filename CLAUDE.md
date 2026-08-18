# CLAUDE.md - AI编程最佳实践指南（精简版）

> **版本**: v3.0 Compact | **更新**: 2026-03-11 | **原则**: 精简、实用、可执行

---

## 🎯 核心原则（Core Principles）

### 0. 第一性原理思考（最重要）

**执行前必须自检**：
- [ ] 我理解用户的**真正需求**是什么吗？（不仅是"做什么"，更是"为什么"）
- [ ] 这个任务是**必须做**的吗？还是在做表面功夫？
- [ ] 有没有**更简单、更直接**的方法？
- [ ] 我是在**解决根本问题**，还是在解决表面问题？

**关键**：不假设用户清楚自己想要什么 → 从原始需求出发 → 保持审慎 → 宁可多问，不可乱做

### 1. 简洁优先（Simplicity First）
- 每次变更尽可能简单，最小可行方案
- 减少冗余逻辑、嵌套层级、临时变量
- 测试应该简洁明了，一个测试只验证一个行为

### 2. 拒绝懒惰（No Laziness）
- 深挖根本原因，拒绝临时修复（Quick Fix）
- 以"资深工程师"标准要求自己
- 关键逻辑必须编写测试

### 3. 最小影响（Minimal Impact）
- 变更仅触及必要的模块
- 执行前分析影响范围，制定回滚方案
- 执行后验证未产生负面影响

### 4. 测试优先（Test First）
- TDD是默认工作方式，不是可选项
- 新功能：先写测试 → 再写实现
- Bug修复：先写失败测试 → 再修复
- 没有测试的代码视为未完成

---

## 🔄 工作流编排（Workflow Orchestration）

### 配置层次（The 5-Layer System）

```
settings.json（腰带） → CLAUDE.md（大脑） → MEMORY.md（笔记本） → Hooks（肌肉） → Skills/Agents（手）
    强制                      建议                    学习                 执行              扩展
```

**关键原则**：
- **Tell in CLAUDE.md, enforce in settings and hooks**
- CLAUDE.md中的"NEVER do X"应该移到hooks
- CLAUDE.md是建议，不是保证

### 1. 计划模式优先（Plan Mode Default）

**触发条件**（满足任一即启用）：
- 执行步骤≥3个
- 涉及架构决策
- 跨模块联动
- **涉及测试编写**

**执行要求**：
- 输出结构化计划（目标、步骤、方案、风险、验证标准）
- 异常时**立即停止**，重新规划
- TDD项目必须包含测试计划

### 2. 子代理策略（Subagent Strategy）

**启用场景**：
- 并行执行模块
- 深度研究工作
- 主上下文即将达上限
- **测试套件较大时**（拆分单元/集成/E2E到不同子代理）

**原则**：一代理一任务，高内聚低耦合

### 3. 自我改进循环（Self-Improvement Loop）

**四步闭环**：
1. **修正接收** → 标记为"待沉淀"
2. **记录沉淀** → 更新 `tasks/lessons.md`
3. **规则制定** → 制定可执行的规避规则
4. **迭代优化** → 错误率降至0后标记"已验证"

### 4. 完成前验证（Verification Before Done）

> **核心标准**：未验证，不完成

**验证清单**：
- [ ] 功能验证：运行测试，对比分支差异
- [ ] 正确性验证：检查语法、逻辑、日志
- [ ] 标准自检："资深工程师会批准吗？"
- [ ] 测试覆盖：单元测试≥80%（TDD项目）

### 5. 追求优雅（Demand Elegance）

**执行前暂停思考**：
- 是否存在更优雅的实现方式？
- 当前方案是否有"hacky"特征？
- 简单修复无需过度设计

### 6. 自主修复Bug（Autonomous Bug Fixing）

**流程**：问题定位 → 原因分析 → 方案设计 → 验证收尾

**关键**：
- 零上下文切换（独立完成）
- 重新运行所有相关测试
- 记录修复过程到 `tasks/lessons.md`

---

## 🧪 TDD精华（Test-Driven Development Essentials）

### 红绿重构循环

```
🔴 RED → 编写失败测试
🟢 GREEN → 最小实现使测试通过
🔵 REFACTOR → 在测试保护下优化
   ↑__________________|
```

### Kent Beck三大法则
1. 不编写生产代码，除非让失败测试通过
2. 不编写超过足以导致失败的测试
3. 不编写超过足以让测试通过的生产代码

### 测试金字塔

```
    /\      E2E (10%) - 关键流程
   /  \     
  /────\    集成 (20%) - 模块交互
 /      \   
/________\  单元 (70%) - TDD主战场
```

### FIRST原则（好测试特征）
- **F**ast（快速）：毫秒级
- **I**ndependent（独立）：无依赖
- **R**epeatable（可重复）：任何环境
- **S**elf-Validating（自验证）：自动判断
- **T**imely（及时）：先于代码编写

### AAA模式（测试结构）
```javascript
test('should calculate total correctly', () => {
  // Arrange（准备）
  const cart = [{ price: 10, quantity: 2 }];
  
  // Act（执行）
  const total = calculateTotal(cart);
  
  // Assert（断言）
  expect(total).toBe(20);
});
```

### 反模式警示
- ❌ 过度Mock
- ❌ 测试私有方法
- ❌ 测试实现细节
- ❌ 共享测试状态
- ❌ 过大的测试

---

## 🎭 E2E测试精华（End-to-End Testing）

### 选择标准
- ✅ **应该测**：关键业务流程、核心转化路径、跨系统集成、高风险功能
- ❌ **不需测**：每个UI细节、简单CRUD、单元测试已覆盖的逻辑

### 优先级矩阵
```
P0（必须有）→ 用户登录、核心业务流程、支付
P1（重要）  → 注册、数据导出、搜索
P2（可选）  → UI交互细节、辅助功能
```

### 最佳实践
1. **独立性**：每个测试自己准备数据
2. **稳定性**：等待特定条件，不用固定延时
3. **用户视角**：模拟真实用户操作

### 页面对象模式（POM）
```javascript
class LoginPage {
  constructor(page) {
    this.emailInput = '#email';
    this.submitButton = 'button[type="submit"]';
  }
  
  async login(email, password) {
    await this.page.fill(this.emailInput, email);
    await this.page.click(this.submitButton);
  }
}
```

---

## 📋 任务管理（Task Management）

### 六步法（按顺序执行）

```
Plan First → Verify Plan → Track Progress → Explain Changes → Document Results → Capture Lessons
```

### 核心文件
```
tasks/
├── todo.md       # 计划、进度、结果
└── lessons.md    # 经验教训
```

### 快速模板

**todo.md**:
```markdown
# 任务计划 - [名称]
## 执行计划
- [ ] 步骤1：[内容]，完成标准：[条件]
- [ ] 步骤2：[内容]
- [ ] 验证：[内容]

## 评审与结果
- 核心成果：[产出]
- 测试覆盖率：XX%
```

**lessons.md**:
```markdown
# 经验教训 - [任务]
## 问题描述
## 错误原因
## 修正方案
## 规避规则
## 验证状态：[ ] 未验证 | [x] 已验证
```

---

## 🏗️ 项目集成（Project Integration）

### 目录结构
```
project/
├── CLAUDE.md          # 本文件
├── tasks/             # 任务管理
│   ├── todo.md
│   └── lessons.md
├── tests/             # 测试目录
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── .claude/           # Claude配置
    ├── settings.json  # 强制规则
    ├── CLAUDE.md      # 个人覆盖（gitignored）
    ├── hooks/         # 生命周期钩子
    └── skills/        # 复用工作流
```

### CLAUDE.md结构（按优先级）

**最重要的内容**：
1. **Common Pitfalls** - Claude常犯的错误（最高ROI）
2. **Tech Stack & Patterns** - 技术栈和关键模式
3. **Development Commands** - 具体命令
4. **Documentation Pointers** - 文档引用

**不应该包含**：
- ❌ Linter配置（已在pyproject.toml/eslint.config.js中）
- ❌ Claude已知的通用原则
- ❌ 冗长的哲学说明

**长度控制**：< 500行（推荐100-300行）

### 示例：Common Pitfalls
```markdown
## Common Pitfalls
- Never use `db.session` directly in routers - use async sessions
- Always include `tenant_id` in queries - missing tenant isolation is a security bug
- Don't use `sync_to_async` in API routes - use native async sessions
- Read the testing standards guide before writing ANY test
```

---

## 🔧 Hooks示例（强制规则）

### 包管理器强制
```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Bash",
      "hooks": [{ "type": "command", "command": ".claude/hooks/enforce-pnpm.sh" }]
    }]
  }
}
```

```bash
#!/bin/bash
INPUT=$(cat)
CMD=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
if echo "$CMD" | grep -qE '^\s*npm\s+(install|i|ci|add)\b'; then
  echo '{"hookSpecificOutput": {"permissionDecision": "deny", "permissionDecisionReason": "use pnpm, not npm"}}'
fi
```

### 硬拒绝规则
```json
{
  "deny": [
    "Bash(python3:*)",
    "Read(~/.ssh/**)",
    "Bash(rm -rf:*)",
    "Bash(git push --force:*)"
  ]
}
```

---

## 📚 推荐资源（精选）

### 官方资源
- [Claude Code最佳实践](https://codewithclaude.net/advanced-topics/best-practices) - Anthropic工程师实战
- [CLAUDE.md权威指南](https://potapov.dev/blog/claude-md-guide) - 5层配置系统
- [E2E测试指南](https://shipyard.build/blog/e2e-testing-claude-code/)

### 高质量Skills
1. **AI Workflow Skills（70+）** - [GitHub](https://github.com/ARazaAnjum/ClaudeCodeSkilledAgents)
   ```bash
   claude plugin marketplace add ARazaAnjum/ClaudeCodeSkilledAgents
   claude plugin install ai-workflow-skills@claude-skilled-agents
   ```

2. **TDD Workflow Skill** - 80%+覆盖率，Red-Green-Refactor自动化
   ```bash
   npx playbooks add skill arazaanjum-claudecodeskilledagents-tdd-workflow
   ```

3. **Claude Workflow Plugin** - Spec驱动开发
   ```bash
   claude plugin marketplace add https://github.com/sighup/claude-workflow.git
   ```

### 快速安装脚本
```bash
#!/bin/bash
# Claude Code完整Skills安装

# 核心Skills
claude plugin marketplace add ARazaAnjum/ClaudeCodeSkilledAgents
claude plugin install ai-workflow-skills@claude-skilled-agents

# TDD工作流
npx playbooks add skill arazaanjum-claudecodeskilledagents-tdd-workflow

# Spec驱动开发
claude plugin marketplace add https://github.com/sighup/claude-workflow.git
claude plugin install claude-workflow@claude-workflow --scope project

echo "✅ 安装完成！可用命令："
echo "  /ai-workflow-skills:create-prd [feature]"
echo "  /cw-research → /cw-spec → /cw-plan → /cw-dispatch → /cw-validate"
```

---

## 💡 常用提示词

```bash
# TDD功能开发
"Write a FAILING test for [feature]. Do NOT write implementation yet."

# TDD Bug修复
"Write a regression test that reproduces this bug. Expect it to fail."

# 紧密反馈循环
"implement the validation function and run tests until they pass"

# E2E测试
"Write an E2E test for the [user flow] using Playwright"

# 并行执行
"Implement all pending tests in parallel, then run the full suite"
```

---

## 📊 验证清单

- [ ] 单元测试通过
- [ ] 测试覆盖率≥80%
- [ ] 集成测试通过
- [ ] E2E关键流程通过
- [ ] 无控制台错误
- [ ] 代码审查完成

---

## 🎯 关键原则总结

1. **第一性原理**：从根本问题出发，不假设，不盲从
2. **简洁优先**：每次变更最小化影响
3. **测试优先**：TDD是默认方式
4. **配置分层**：Tell in CLAUDE.md, enforce in hooks
5. **持续改进**：错误 → 记录 → 规则 → 验证
6. **验证完成**：未验证不标记完成

---

*每行都要有价值。如果删除某行不会让Claude的输出变差，就删掉它。*
