export const nodeCatalog = [
  {
    type: 'start',
    label: 'Start',
    caption: '定义输入参数',
    defaults: { label: 'Start', fields: [] },
  },
  {
    type: 'source',
    label: 'Source DB',
    caption: '选择 name-db',
    defaults: { label: 'Source DB', knowledgeBaseId: '' },
  },
  {
    type: 'parse',
    label: 'Parse',
    caption: '读取已保存来源',
    defaults: { label: 'Parse', parser: 'auto' },
  },
  {
    type: 'chunk',
    label: 'Chunk',
    caption: '文本切片',
    defaults: { label: 'Chunk', chunkSize: 900, chunkOverlap: 120 },
  },
  {
    type: 'embed_index',
    label: 'Embed / Index',
    caption: '构建 vector DB',
    defaults: { label: 'Embed / Index', overwrite: true },
  },
  {
    type: 'query_generate',
    label: 'Query Generate',
    caption: '生成 Query Set',
    defaults: {
      label: 'Query Generate',
      knowledgeBaseId: '',
      name: 'Workflow 生成的 Query 集',
      examples: ['如何配置这个产品？', '上传文档后怎么检索？', '评测结果怎么看？'],
      targetCount: 10,
    },
  },
  {
    type: 'retrieve',
    label: 'Retrieve',
    caption: '检索 chunks',
    defaults: { label: 'Retrieve', topK: 3, searchType: 'similarity', knowledgeBaseId: '' },
  },
  {
    type: 'prompt_llm',
    label: 'Prompt / LLM',
    caption: '生成回答',
    defaults: {
      label: 'Prompt / LLM',
      model: '',
      temperature: 0.2,
      prompt: '问题：{question}\n\n上下文：\n{contexts}\n\n请只基于上下文回答。',
    },
  },
  {
    type: 'answer',
    label: 'Answer',
    caption: '批量生成答案',
    defaults: { label: 'Answer', outputKey: 'answer', includeContexts: true },
  },
  {
    type: 'ragas_eval',
    label: 'RAGAS Eval',
    caption: '消费 Answer 结果评分',
    defaults: { label: 'RAGAS Eval', metricPreset: 'reference_free', limit: '' },
  },
  {
    type: 'end',
    label: 'End',
    caption: '返回输出',
    defaults: { label: 'End', outputs: [] },
  },
];

export const nodeMeta = Object.fromEntries(nodeCatalog.map((item) => [item.type, item]));

export function buildNode(type, index = 0, position = null) {
  const meta = nodeMeta[type];
  return {
    id: `${type}_${Date.now()}_${Math.round(Math.random() * 10000)}`,
    type,
    position: position || { x: 80 + index * 150, y: 120 },
    data: {
      ...meta.defaults,
      fields: meta.defaults.fields ? [...meta.defaults.fields] : undefined,
      outputs: meta.defaults.outputs ? [...meta.defaults.outputs] : undefined,
      examples: meta.defaults.examples ? [...meta.defaults.examples] : undefined,
    },
  };
}
