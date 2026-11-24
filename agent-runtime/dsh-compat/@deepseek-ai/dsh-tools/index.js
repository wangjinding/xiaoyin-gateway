// 小银智能体的兼容垫片：DSH 插件只用 defineTool 做规范化，这里原样返回
export function defineTool(def) {
  if (!def || !def.name) throw new Error('defineTool: 缺少 name');
  return def;
}
export default { defineTool };
