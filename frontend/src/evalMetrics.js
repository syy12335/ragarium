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
];

export const FALLBACK_DEFAULT_METRICS = [
  'faithfulness',
  'answer_relevancy',
];

export function resolveMetricSpecs(remote) {
  return remote?.evalMetrics?.metrics?.length ? remote.evalMetrics.metrics : FALLBACK_EVAL_METRICS;
}

export function resolveDefaultMetricNames(remote) {
  return remote?.evalMetrics?.default_metric_names?.length
    ? remote.evalMetrics.default_metric_names
    : FALLBACK_DEFAULT_METRICS;
}
