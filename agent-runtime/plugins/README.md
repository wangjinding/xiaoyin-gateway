# plugins —— 二次开发入口

在这里放网关专属的 DSH 插件（工具、技能、装饰器）。

一个最小插件：

```
plugins/gateway-tools/
├── package.json        name: dsh-gateway-tools
├── cordis.patch.yml    - insert: [{id: gateway-tools, name: dsh-gateway-tools}]
└── lib/index.js        export const name/inject; export function apply(ctx, config)
```

然后在 `home/profiles/agent/cordis.patch.yml` 里挂载（或由适配器自动扫描 `plugins/` 注入）。

写法参考网关已有的两个插件示例：
`@wangjinding/dsh-agnes-media`、`@wangjinding/dsh-comfyui`
（`ctx.tools.register(defineTool({...}))` + `ctx.effect` 托管）。
