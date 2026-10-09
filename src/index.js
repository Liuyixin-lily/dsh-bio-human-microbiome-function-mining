import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { registerSkills } from './skills.js'

export const name = 'human-microbiome-function-mining'

export const inject = ['skills', 'systemPrompt']

const DEFAULT_CONFIG = {
  outputStrict: true
}

export function apply(ctx, config) {
  const cfg = { ...DEFAULT_CONFIG, ...(config ?? {}) }
  const skillsDir = join(dirname(fileURLToPath(import.meta.url)), '..', 'skills')
  const agentDir = join(dirname(fileURLToPath(import.meta.url)), '..', 'agents')
  const refDir = join(dirname(fileURLToPath(import.meta.url)), '..', 'references')

  registerSkills(ctx, skillsDir, agentDir, refDir, cfg)

  ctx.systemPrompt?.section?.({
    name: 'human-microbiome-function-mining',
    order: 200,
    text: `You are using the DeepSeek Harness plugin "human-microbiome-function-mining".
It turns a target enzyme, EC number, or substrate/product pair into candidate human microbiome proteins and an experimental validation plan.
Follow its skills: functional-dark-matter-discover, build-target-function-card, screen-sequence-candidates, structure-prediction, screen-structure-candidates, literature-evidence, genome-search, genome-download, and genome-annotation.
External heavy tools (DIAMOND, CD-HIT, US-align, DEER, FedKEA, Bakta) are not bundled. Run them only when the user gives executable and data paths accessible from the current terminal and allows direct execution. Otherwise give exact commands and consume returned output files.
Literature search is not bundled either; run it through the nature-academic-search skill when MCP literature tools are available and the user allows, otherwise provide verified search terms or accept user-provided citation files. Never fabricate PMID or DOI identifiers.
Never call the FedKEA web server programmatically.`
  })
}
