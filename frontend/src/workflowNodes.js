export const nodeCatalog = [
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
    caption: '返回结果',
    defaults: { label: 'Answer', outputKey: 'answer', includeContexts: true },
  },
];

export const nodeMeta = Object.fromEntries(nodeCatalog.map((item) => [item.type, item]));

export function buildNode(type, index = 0) {
  const meta = nodeMeta[type];
  return {
    id: `${type}_${Date.now()}`,
    type,
    position: { x: 80 + index * 150, y: 120 },
    data: { ...meta.defaults },
  };
}
