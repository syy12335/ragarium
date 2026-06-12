export const FALLBACK_EVAL_METRICS = [
  {
    name: 'faithfulness',
    label: 'Faithfulness',
    description: '回答是否被检索到的 contexts 支持，越低越可能幻觉。',
    requires_reference: false,
    default_enabled: true,
  },
  {
    name: 'answer_relevancy',
    label: 'Answer relevancy',
    description: '回答是否贴合 Query，冗余、跑题、不完整会扣分。',
    requires_reference: false,
    default_enabled: true,
  },
  {
    name: 'context_precision',
    label: 'Context precision',
    description: '相关 context 是否排在更前，需要 reference。',
    requires_reference: true,
  },
  {
    name: 'context_recall',
    label: 'Context recall',
    description: 'contexts 是否覆盖 reference 所需信息，需要 reference。',
    requires_reference: true,
  },
  {
    name: 'context_entity_recall',
    label: 'Context entity recall',
    description: 'contexts 是否覆盖 reference 中的实体，需要 reference。',
    requires_reference: true,
  },
  {
    name: 'context_utilization',
    label: 'Context utilization',
    description: '回答是否充分利用了检索到的 contexts，无需 reference；适合看召回内容有没有被答案真正用上。',
    requires_reference: false,
    default_enabled: true,
  },
  {
    name: 'answer_similarity',
    label: 'Answer similarity',
    description: '答案与 reference 的语义相似度，需要 reference。',
    requires_reference: true,
  },
  {
    name: 'answer_correctness',
    label: 'Answer correctness',
    description: '答案相对 reference 的事实正确性，需要 reference。',
    requires_reference: true,
  },
  {
    name: 'summary_score',
    label: 'Summary score',
    description: '把回答当作 contexts 摘要来评估覆盖与简洁性，无需 reference；更适合摘要型回答，普通 RAG 仅作辅助参考。',
    requires_reference: false,
    default_enabled: true,
  },
];

export const FALLBACK_DEFAULT_METRICS = [
  'faithfulness',
  'answer_relevancy',
  'context_utilization',
  'summary_score',
];

export function resolveMetricSpecs(remote) {
  return remote?.evalMetrics?.metrics?.length ? remote.evalMetrics.metrics : FALLBACK_EVAL_METRICS;
}

export function resolveDefaultMetricNames(remote) {
  return remote?.evalMetrics?.default_metric_names?.length
    ? remote.evalMetrics.default_metric_names
    : FALLBACK_DEFAULT_METRICS;
}
