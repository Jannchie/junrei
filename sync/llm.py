"""Claude API 批量调用：去重 + 结果缓存 + Message Batches。

条目按文本去重后打包（一个请求带 chunk_size 条），结构化输出（JSON schema）逐条对回。
每条结果以 (task, prompt_version, model, sha256(文本)) 为键缓存在 cache.llm_cache，重跑只请求没缓存过的条目；
prompt_version 里带系统提示词的哈希，改提示词会自动失效旧缓存。

默认走 Message Batches（半价、异步）：提交后批次 id 记在 cache.llm_batch，下次运行会先去收取结果，
加 --wait 则就地轮询直到结束。--mode sync 逐个请求同步调用，适合小规模试跑。

需要 `pip install anthropic`，凭据按 SDK 默认顺序解析（ANTHROPIC_API_KEY 等）。--dry-run 不需要 SDK 和凭据。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass, field

from sync.enrich_common import now_iso

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"  # 只用于同步模式；Batches API 不接受 fallbacks


def clean_text(s: str) -> str:
    """去掉零宽字符、合并空白，作为发给模型和缓存键的文本。"""
    s = re.sub(r"[\u200b-\u200d\ufeff]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


@dataclass
class Task:
    name: str
    version: str          # 人为维护的版本号；最终 prompt_version 还会拼上系统提示词哈希
    system: str
    item_properties: dict  # 每条结果除 i 以外的字段（JSON schema properties）
    chunk_size: int = 40
    max_tokens: int = 16000
    effort: str = "low"
    prompt_version: str = field(init=False)

    def __post_init__(self):
        self.prompt_version = f"{self.version}-{sha(self.system + json.dumps(self.item_properties, sort_keys=True))[:8]}"

    def schema(self) -> dict:
        item = {"type": "object", "properties": {"i": {"type": "integer"}, **self.item_properties},
                "required": ["i", *self.item_properties], "additionalProperties": False}
        return {"type": "object", "properties": {"items": {"type": "array", "items": item}},
                "required": ["items"], "additionalProperties": False}

    def params(self, model: str, texts: list[str]) -> dict:
        payload = json.dumps([{"i": i, "text": t} for i, t in enumerate(texts)], ensure_ascii=False)
        return {
            "model": model,
            "max_tokens": self.max_tokens,
            "system": self.system,
            "output_config": {"effort": self.effort, "format": {"type": "json_schema", "schema": self.schema()}},
            "messages": [{"role": "user", "content": f"共 {len(texts)} 条，逐条处理并按 i 返回：\n{payload}"}],
        }


def client():
    try:
        import anthropic
    except ImportError:
        sys.exit("需要 Anthropic SDK：pip install anthropic（--dry-run 不需要）")
    return anthropic, anthropic.Anthropic()


def cached(db, task: Task, model: str) -> dict[str, tuple[dict, str]]:
    return {s: (json.loads(o), m) for s, o, m in db.execute(
        "SELECT input_sha, output, served_model FROM cache.llm_cache WHERE task=? AND prompt_version=? AND model=?",
        (task.name, task.prompt_version, model))}


def store(db, task: Task, model: str, served: str, texts: dict[str, str], message_text: str, shas: list[str]) -> int:
    """把一个请求的结构化输出按 i 对回条目并写缓存，返回写入条数。缺失 / 越界的条目留待下次重试。"""
    try:
        items = json.loads(message_text)["items"]
    except (json.JSONDecodeError, KeyError, TypeError):
        print("  ! 输出不是合法 JSON，整块跳过", file=sys.stderr)
        return 0
    n = 0
    ts = now_iso()
    for it in items:
        i = it.pop("i", None)
        if not isinstance(i, int) or not 0 <= i < len(shas):
            continue
        s = shas[i]
        db.execute("INSERT OR REPLACE INTO cache.llm_cache VALUES (?,?,?,?,?,?,?,?)", (
            task.name, task.prompt_version, model, s, texts[s], json.dumps(it, ensure_ascii=False), served, ts))
        n += 1
    db.commit()
    return n


def message_text(msg) -> str | None:
    if msg.stop_reason in ("refusal", "max_tokens"):
        print(f"  ! stop_reason={msg.stop_reason}，该块留待重试", file=sys.stderr)
        return None
    return next((b.text for b in msg.content if b.type == "text"), None)


def collect_batches(db, task: Task, model: str, texts: dict[str, str], wait: bool, poll: float) -> list[str]:
    """收取之前提交、尚未收取的批次。返回仍在处理中的条目 sha（不要重复提交）。"""
    rows = db.execute("SELECT id, chunks FROM cache.llm_batch WHERE task=? AND prompt_version=? AND model=? "
                      "AND collected_at IS NULL", (task.name, task.prompt_version, model)).fetchall()
    if not rows:
        return []
    _, c = client()
    in_flight = []
    for bid, chunks_json in rows:
        chunks = json.loads(chunks_json)
        batch = c.messages.batches.retrieve(bid)
        while wait and batch.processing_status != "ended":
            print(f"  批次 {bid}：{batch.processing_status}，处理中 {batch.request_counts.processing}")
            time.sleep(poll)
            batch = c.messages.batches.retrieve(bid)
        if batch.processing_status != "ended":
            print(f"  批次 {bid} 仍在处理（{batch.request_counts.processing} 个请求），稍后再跑或加 --wait")
            in_flight += [s for shas in chunks.values() for s in shas]
            continue
        n = 0
        for r in c.messages.batches.results(bid):
            shas = chunks.get(r.custom_id)
            if shas is None:
                continue
            if r.result.type == "succeeded":
                text = message_text(r.result.message)
                if text:
                    n += store(db, task, model, r.result.message.model, texts, text, shas)
            else:
                print(f"  ! {r.custom_id}：{r.result.type}，留待重试", file=sys.stderr)
        db.execute("UPDATE cache.llm_batch SET status='ended', collected_at=? WHERE id=?", (now_iso(), bid))
        db.commit()
        print(f"  收取批次 {bid}：{n} 条")
    return in_flight


def run(db, task: Task, inputs: list[str], *, model: str = DEFAULT_MODEL, mode: str = "batch",
        dry_run: bool = False, limit: int | None = None, wait: bool = False, poll: float = 60) -> dict[str, tuple[dict, str]]:
    """对 inputs（已 clean_text）求结果，返回 {sha: (结果, 实际模型)}，只含已完成的条目。"""
    texts = {sha(t): t for t in inputs if t}
    in_flight = set() if dry_run else set(collect_batches(db, task, model, texts, wait, poll))
    done = cached(db, task, model)
    pending = [s for s in texts if s not in done and s not in in_flight]
    if limit is not None:
        pending = pending[:limit]
    chunks = [pending[i : i + task.chunk_size] for i in range(0, len(pending), task.chunk_size)]
    print(f"{task.name}（{task.prompt_version}，{model}）：共 {len(texts)} 条不同文本，已缓存 {len(done)}，"
          f"处理中 {len(in_flight)}，待请求 {len(pending)} 条 / {len(chunks)} 个请求")
    if not chunks:
        return {s: v for s, v in done.items() if s in texts}
    if dry_run:
        chars = sum(len(texts[s]) for s in pending)
        print(f"  dry-run：待请求文本共 {chars} 字，系统提示词 {len(task.system)} 字 × {len(chunks)} 次。第一个请求：")
        print(json.dumps(task.params(model, [texts[s] for s in chunks[0][:3]]), ensure_ascii=False, indent=2)[:3000])
        return {s: v for s, v in done.items() if s in texts}

    anthropic, c = client()
    if mode == "sync":
        for k, shas in enumerate(chunks):
            try:
                msg = c.beta.messages.create(**task.params(model, [texts[s] for s in shas]),
                                             betas=[FALLBACK_BETA], fallbacks="default")
            except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
                sys.exit(f"Claude API 凭据不可用：{e.message}")
            except anthropic.BadRequestError as e:
                print(f"  ! 请求 {k} 参数错误：{e.message}", file=sys.stderr)
                continue
            except (anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError) as e:
                print(f"  ! 请求 {k} 失败（{type(e).__name__}），已重试仍失败，留待下次", file=sys.stderr)
                continue
            text = message_text(msg)
            n = store(db, task, model, msg.model, texts, text, shas) if text else 0
            print(f"  [{k + 1}/{len(chunks)}] {n}/{len(shas)} 条")
    else:
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request

        ids = {f"{task.name}-{k}": shas for k, shas in enumerate(chunks)}
        try:
            batch = c.messages.batches.create(requests=[
                Request(custom_id=cid, params=MessageCreateParamsNonStreaming(**task.params(model, [texts[s] for s in shas])))
                for cid, shas in ids.items()])
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
            sys.exit(f"Claude API 凭据不可用：{e.message}")
        db.execute("INSERT INTO cache.llm_batch VALUES (?,?,?,?,?,?,?,?)", (
            batch.id, task.name, task.prompt_version, model, json.dumps(ids), batch.processing_status, now_iso(), None))
        db.commit()
        print(f"  已提交批次 {batch.id}（{len(ids)} 个请求）")
        collect_batches(db, task, model, texts, wait, poll)
    done = cached(db, task, model)
    return {s: v for s, v in done.items() if s in texts}
