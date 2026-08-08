/**
 * fangcun plugin for OpenCode.ai
 *
 * Auto-registers fangcun skills directory via config hook.
 * Provides tool mapping for OpenCode compatibility.
 */

import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const fangcunSkillsDir = path.resolve(__dirname, '../../skills');

export const FangcunPlugin = async ({ client, directory }) => {
  return {
    // Inject skills path into config so OpenCode discovers fangcun skills
    config: async (config) => {
      config.skills = config.skills || {};
      config.skills.paths = config.skills.paths || [];
      if (!config.skills.paths.includes(fangcunSkillsDir)) {
        config.skills.paths.push(fangcunSkillsDir);
      }
    },

    // Inject bootstrap into the first user message
    'experimental.chat.messages.transform': async (_input, output) => {
      if (!output.messages.length) return;

      const bootstrap = `<EXTREMELY_IMPORTANT>
fangcun 创作引擎套件已加载。

**Tool Mapping for OpenCode:**
- \`Bash(python *)\` → OpenCode native shell (python ...)
- \`Read\`/\`Write\`/\`Edit\` → OpenCode native file tools
- \`Skill\` → OpenCode native \`skill\` tool

Use OpenCode's native \`skill\` tool to list and load fangcun skills:
- fangcun/analyze — 源书级分析
- fangcun/drama — 短剧剧本
- fangcun/novel — 小说仿写
- fangcun/write — 通用写作
</EXTREMELY_IMPORTANT>`;

      const firstUser = output.messages.find(m => m.info?.role === 'user');
      if (!firstUser || !firstUser.parts?.length) return;
      if (firstUser.parts.some(p => p.type === 'text' && p.text.includes('fangcun 创作引擎套件'))) return;

      const ref = firstUser.parts[0];
      firstUser.parts.unshift({ ...ref, type: 'text', text: bootstrap });
    }
  };
};
