import { readFileSync, existsSync } from 'node:fs'
import { join } from 'node:path'

export const SKILL_MANIFEST = [
  {
    name: 'browse-target-library',
    description: 'Turn a vague natural-language interest ("skin metabolism", "油脂分泌", "which microbes matter for body odour") into a pickable list of physiological processes, taxa, and enzyme targets, then materialize the chosen target as a Target Function Card.',
    whenToUse: '用户还没有给出具体的酶/EC/序列，只说关注某个生理过程、表型或身体部位时，先让用户在目标库里选。',
    file: 'browse-target-library.md'
  },
  {
    name: 'intake-environment',
    description: 'Ask the user for their execution environment — host, tool paths, required environment variables, databases, data locations and permission to execute — then verify what is actually reachable before running any workflow.',
    whenToUse: '每个新任务、跑任何外部工具之前：先问用户有没有服务器地址、软件路径、数据库和数据集，并确认是否允许本机执行。',
    file: 'intake-environment.md'
  },
  {
    name: 'functional-dark-matter-discover',
    description: 'Given a target enzyme sequence, EC number, or substrate-product reaction, discover candidate human microbiome protein functions by combining sequence screening, structure search, FedKEA validation, source annotations, and experimental design.',
    whenToUse: '用户给出目标酶/EC/底物产物，想从人体微生物组中找候选功能蛋白。',
    file: 'functional-dark-matter-discover.md'
  },
  {
    name: 'build-target-function-card',
    description: 'Normalize the user target enzyme input into a machine-readable Target Function Card for downstream screening.',
    whenToUse: '开始筛选前需要把目标酶/EC/反应标准化。',
    file: 'build-target-function-card.md'
  },
  {
    name: 'screen-sequence-candidates',
    description: 'Run or consume DIAMOND sequence screening for candidate microbial proteins, including CD-HIT deduplication before search.',
    whenToUse: '需要先按序列相似性筛选候选蛋白时。',
    file: 'screen-sequence-candidates.md'
  },
  {
    name: 'structure-prediction',
    description: 'Retrieve or predict missing candidate structures with priority experimental PDB > AlphaFold DB model passing mean pLDDT >= 60 > homology model > de novo prediction, producing structure/<protein_sequence_id>.pdb for US-align.',
    whenToUse: '候选蛋白还没有 PDB/mmCIF 结构文件，需要在 US-align 前准备结构时。',
    file: 'structure-prediction.md'
  },
  {
    name: 'screen-structure-candidates',
    description: 'Screen candidate protein structures against a reference target structure. Use US-align directly on all candidate structures first, then try DEER only when US-align does not yield enough suitable candidates for a genome.',
    whenToUse: '序列候选已有，需要结构证据评分和排序时。',
    file: 'screen-structure-candidates.md'
  },
  {
    name: 'prepare-cro-work-order',
    description: 'Turn a validated target and candidate list into a vendor-facing contract research work order: quotable modules from gene synthesis through enzyme assays, verbatim sequences, pre-registered decision rules, a glossary for non-specialists, and a "confirm before sending" checklist.',
    whenToUse: '用户要外包实验（基因合成/表达纯化/酶活检测），或者不懂分子生物学、需要一份能直接发给公司询价和执行的方案时。',
    file: 'prepare-cro-work-order.md'
  },
  {
    name: 'literature-evidence',
    description: 'Search and audit published literature for existing functional evidence on the target enzyme and each candidate protein or candidate organism. Uses the nature-academic-search workflow router when MCP literature tools are available, and falls back to OpenAlex-only discovery or user-provided citations otherwise.',
    whenToUse: '已经获得候选蛋白/候选菌后，需要补文献证据链，并据此判断是否已有直接功能证据或优化实验设计时。',
    file: 'literature-evidence.md'
  },
  {
    name: 'genome-search',
    description: 'Search NCBI GCF/GCA assemblies for taxa from a specified source, or audit an existing GCF/GCA list against a specified source, using Assembly and BioSample metadata.',
    whenToUse: '用户有物种或来源信息，需要先选择/审计候选基因组装配时。',
    file: 'genome-search.md'
  },
  {
    name: 'genome-download',
    description: 'Batch-download NCBI RefSeq/GCF or GenBank/GCA genomes from a species list or accession list.',
    whenToUse: '候选基因组列表已确定，需要下载标准基因组文件集时。',
    file: 'genome-download.md'
  },
  {
    name: 'genome-annotation',
    description: 'Annotate bacterial genomes with Bakta using a full or light local database; default to the full database when not specified.',
    whenToUse: '下载的新基因组缺少 .gbff/.faa 注释，需要运行 Bakta 注释时。',
    file: 'genome-annotation.md'
  }
]

function readOrFallback(path, name) {
  try {
    return readFileSync(path, 'utf8')
  } catch {
    return `Skill body for "${name}" is missing from the plugin package.`
  }
}

export function registerSkills(ctx, skillsDir, _agentDir, _refDir, _cfg) {
  const disposers = []

  for (const skill of SKILL_MANIFEST) {
    const content = readOrFallback(join(skillsDir, skill.file), skill.name)
    disposers.push(ctx.skills.register({
      name: skill.name,
      description: skill.description,
      whenToUse: skill.whenToUse,
      source: 'custom',
      provider: 'human-microbiome-function-mining',
      content
    }))
  }

  return disposers
}
