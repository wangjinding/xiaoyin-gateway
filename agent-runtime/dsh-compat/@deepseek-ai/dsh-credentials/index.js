// 兼容垫片：DSH 的 credentialRef 只是个带名字的引用
export function credentialRef(name) {
  return { name: String(name) };
}
export default { credentialRef };
