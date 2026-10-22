// 全局键盘快捷键：在输入框、下拉框里打字时不触发（Esc 与 Ctrl/⌘+K 除外），输入法组字时一律不触发
export type KeyHandler = (e: KeyboardEvent) => boolean | void;

const typing = (el: EventTarget | null) =>
  el instanceof HTMLElement && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));

/** keys：按 e.key 匹配（如 "/"、"j"、"Escape"、"mod+k"）；处理函数返回 false 表示不拦截，交还浏览器 */
export function onShortcuts(keys: Record<string, KeyHandler>) {
  const listener = (e: KeyboardEvent) => {
    if (e.isComposing || e.altKey) return;
    const mod = e.ctrlKey || e.metaKey;
    const name = mod ? `mod+${e.key.toLowerCase()}` : e.key.length === 1 ? e.key.toLowerCase() : e.key;
    const handler = keys[name];
    if (!handler || (typing(e.target) && !mod && !/^(Escape|ArrowDown|ArrowUp)$/.test(e.key))) return;
    if (handler(e) !== false) e.preventDefault();
  };
  addEventListener("keydown", listener);
  return () => removeEventListener("keydown", listener);
}
