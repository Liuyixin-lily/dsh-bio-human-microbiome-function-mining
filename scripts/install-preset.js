#!/usr/bin/env node
/**
 * human-microbiome-function-mining — postinstall 钩子
 *
 * 作用：把 `preset/human-microbiome-function-mining/` 复制到
 * `$DSH_HOME/.agent-presets/human-microbiome-function-mining/`，让用户在
 * DeepSeek Harness 的预设选择器里看到「人体微生物功能挖掘专家」人设。
 *
 * 设计原则：
 *   - 幂等：已存在不覆盖（保护用户就地编辑的文件）
 *   - 非致命：失败仅 warn，不 throw——不挡其他 npm 脚本/postinstall
 *   - Windows 友好：路径用 path.join；DSH_HOME 优先取环境变量，否则取用户 HOME
 *   - 支持 --force：CI / 重复安装时强制覆盖
 *   - 支持 --dry-run：只看会做什么，不实际操作
 */
import { existsSync, statSync, mkdirSync, readdirSync, copyFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { homedir } from 'node:os'

const __dirname = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = join(__dirname, '..')
const PRESET_SRC = join(REPO_ROOT, 'preset', 'human-microbiome-function-mining')
const PRESET_ID = 'human-microbiome-function-mining'

function resolveDshHome() {
  if (process.env.DSH_HOME && process.env.DSH_HOME.length > 0) return process.env.DSH_HOME
  const userHome = process.env.USERPROFILE || process.env.HOME || homedir()
  return join(userHome, '.dsh')
}

function parseArgs(argv) {
  return {
    force: argv.includes('--force'),
    dryRun: argv.includes('--dry-run'),
    verbose: argv.includes('--verbose') || argv.includes('-v'),
  }
}

function copyDirSync(src, dst, { force, skipExisting, verbose }) {
  mkdirSync(dst, { recursive: true })
  for (const entry of readdirSync(src, { withFileTypes: true })) {
    const s = join(src, entry.name)
    const d = join(dst, entry.name)
    if (entry.isDirectory()) {
      copyDirSync(s, d, { force, skipExisting, verbose })
      continue
    }
    if (entry.isFile()) {
      if (existsSync(d) && skipExisting) {
        if (verbose) console.log(`[install-preset]   skip: ${d}`)
        continue
      }
      if (existsSync(d) && !force) {
        if (verbose) console.log(`[install-preset]   keep existing: ${d}`)
        continue
      }
      copyFileSync(s, d)
      if (verbose) console.log(`[install-preset]   write: ${d}`)
    }
  }
}

function main() {
  const args = parseArgs(process.argv.slice(2))

  if (!existsSync(PRESET_SRC)) {
    console.warn(`[install-preset] source preset not found at ${PRESET_SRC} (missing preset dir, skip)`)
    return 0
  }
  if (!existsSync(join(PRESET_SRC, 'agent.cordis.yml')) || !existsSync(join(PRESET_SRC, 'preset.yml'))) {
    console.warn(`[install-preset] preset at ${PRESET_SRC} incomplete (missing preset.yml or agent.cordis.yml), skipping`)
    return 0
  }

  const dshHome = resolveDshHome()
  const targetRoot = join(dshHome, '.agent-presets')
  const targetDir = join(targetRoot, PRESET_ID)

  if (args.dryRun) {
    const srcStat = statSync(PRESET_SRC)
    console.log(`[install-preset] dry-run: would copy ${PRESET_SRC} (${srcStat.size} bytes) -> ${targetDir}`)
    console.log(`[install-preset]   DSH_HOME = ${dshHome}`)
    console.log(`[install-preset]   options: ${JSON.stringify(args)}`)
    return 0
  }

  try {
    mkdirSync(targetRoot, { recursive: true })
  } catch (e) {
    console.warn(`[install-preset] cannot create ${targetRoot}: ${e?.message ?? e}`)
    console.warn('[install-preset] skipping preset install; user can copy preset/human-microbiome-function-mining manually')
    return 0
  }

  const existed = existsSync(targetDir)
  if (existed && !args.force) {
    console.log(`[install-preset] preset already installed at ${targetDir} (use --force to overwrite)`)
    return 0
  }

  try {
    copyDirSync(PRESET_SRC, targetDir, { force: args.force, skipExisting: !args.force, verbose: args.verbose })
  } catch (e) {
    console.warn(`[install-preset] copy failed: ${e?.message ?? e}`)
    console.warn('[install-preset] preset not installed; dsh still usable without preset')
    return 0
  }

  const action = existed ? 'updated' : 'installed'
  const files = readdirSync(targetDir)
  console.log(`[install-preset] preset ${action} -> ${targetDir}`)
  console.log(`[install-preset]   files: ${files.join(', ')}`)
  if (existsSync(join(targetDir, 'skills'))) {
    const skills = readdirSync(join(targetDir, 'skills'))
    console.log(`[install-preset]   bundled skills: ${skills.join(', ')}`)
  }
  return 0
}

try {
  process.exit(main())
} catch (e) {
  console.warn(`[install-preset] unexpected error: ${e?.message ?? e}`)
  console.warn('[install-preset] preset installation skipped; plugin still works without the preset')
  process.exit(0)
}
