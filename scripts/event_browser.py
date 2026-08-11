#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""集纲事件浏览器生成器（skill 内置功能）。

读项目的事件资产(source_events) + 集纲(episode_outline 活动版本) + 章节原文，
生成一个可交互 HTML：左侧全事件表（✔选用/✘被裁、可按集筛选、可搜索），
右侧原文全文，点事件即可跳转并高亮原文对应 span，供编剧对照集纲判断故事选取。

用法: fangcun event-browser --dir <项目> [--out out.html]
纯本地、零模型调用，约 1-2 秒/本。
"""
import argparse, html, json
from pathlib import Path

def _load_events(proj: Path) -> list:
    """解析事件资产：优先活动 artifact，兼容项目根 source_events.json 布局。"""
    try:
        from .state_store import active_artifact_path
        path = active_artifact_path(proj, "source_events")
        if path and path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("events", data) if isinstance(data, dict) else data
    except Exception:
        pass
    root_file = proj / "source_events.json"
    if root_file.exists():
        data = json.loads(root_file.read_text(encoding="utf-8"))
        return data.get("events", data) if isinstance(data, dict) else data
    raise FileNotFoundError(f"未找到事件资产（active artifact 或 {root_file}）")


def build(proj: Path, out: Path, title: str = ""):
    proj = proj.resolve()
    evs = _load_events(proj)
    by_id = {e["event_id"]: e for e in evs}
    m = json.loads((proj/"state/manifest.json").read_text(encoding="utf-8"))
    a = m["artifacts"]["episode_outline"]
    v = a["active_version"]
    path = next(x["path"] for x in a["versions"] if x["version"]==v)
    d = json.loads((proj/path).read_text(encoding="utf-8"))
    eps = d.get("episodes", d)

    def selected_of(ep):
        s = set(ep.get("source_event_ids") or [])
        for b in (ep.get("required_story_beats") or []): s.update(b.get("event_ids") or [])
        for b in (ep.get("beat_plan") or []): s.update(b.get("event_ids") or [])
        for mk in (ep.get("must_keep") or []):
            if isinstance(mk, dict) and mk.get("event_id"): s.add(mk["event_id"])
        return s

    ep_selected = {ep["episode"]: selected_of(ep) for ep in eps}
    selected = set().union(*ep_selected.values()) if ep_selected else set()
    ep_by_event = {}
    for ep, s in ep_selected.items():
        for eid in s: ep_by_event.setdefault(eid, []).append(ep)

    idx = json.loads((proj/"source/index.json").read_text(encoding="utf-8"))
    chapters = {}
    for c in idx["chapters"]:
        f = proj / c["file"]
        if f.exists(): chapters[c["chapter_index"]] = f.read_text(encoding="utf-8")

    def esc(t): return html.escape(t or "")

    rows = []
    for ch in sorted(chapters):
        rows.append(f'<div class="chap" id="chap-{ch}"><h3>第{ch}章</h3>')
        for e in sorted([x for x in evs if x.get("chapter_id")==ch], key=lambda x: x["event_id"]):
            eid = e["event_id"]; used = eid in selected
            refs = ep_by_event.get(eid, [])
            badge = f'<span class="b-used">✔ 第{"/".join(map(str,refs))}集</span>' if used else '<span class="b-cut">✘ 被裁</span>'
            rows.append(f'''<div class="ev {'used' if used else 'cut'}" data-eid="{esc(eid)}" onclick="pick('{esc(eid)}')">
              <div class="ev-id">{esc(eid)} {badge}</div><div class="ev-sum">{esc(e.get('event',''))}</div></div>''')
        rows.append('</div>')
    sidebar = "\n".join(rows)

    def render_chapter(ch):
        text = chapters[ch]
        markers = []
        for e in evs:
            if e.get("chapter_id") != ch: continue
            sp = e.get("source_span") or {}
            if isinstance(sp.get("start"), int) and isinstance(sp.get("end"), int):
                markers.append((sp["start"], sp["end"], e["event_id"]))
        if not markers:
            return f'<section class="chsec" id="ch-{ch}"><h2>第{ch}章</h2><p>{esc(text)}</p></section>'
        markers.sort()
        out = [f'<section class="chsec" id="ch-{ch}"><h2>第{ch}章</h2>']
        pos = 0
        for s, e_, eid in markers:
            if s > pos: out.append(esc(text[pos:s]))
            out.append(f'<mark class="evmark" id="m-{esc(eid)}" data-eid="{esc(eid)}" onclick="pick(\'{esc(eid)}\')">{esc(text[s:e_])}</mark>')
            pos = max(pos, e_)
        out.append(esc(text[pos:])); out.append('</section>')
        return "\n".join(out)

    body = "\n".join(render_chapter(ch) for ch in sorted(chapters))
    details = {}
    for e in evs:
        eid = e["event_id"]
        kq = "".join(f"<li>{esc(q.get('speaker',''))}：{esc(q.get('text',''))}</li>" for q in (e.get("key_quotes") or []) if isinstance(q, dict))
        refs = ep_by_event.get(eid, [])
        st = f"第{'/'.join(map(str,refs))}集" if refs else "被裁（未进入集纲）"
        details[eid] = (f'<div class="detail"><h3>{esc(eid)} <span class="st">{esc(st)}</span></h3>'
            f'<p><b>事件：</b>{esc(e.get("event",""))}</p>'
            f'<p><b>触发：</b>{esc(e.get("trigger",""))}</p>'
            f'<p><b>动作：</b>{esc("；".join(e.get("actions") or []))}</p>'
            f'<p><b>结果：</b>{esc(e.get("result",""))}</p>'
            f'<p><b>重要度：</b>{esc(e.get("importance",""))} ｜ <b>建议时长：</b>{e.get("minimum_screen_seconds","-")}–{e.get("preferred_screen_seconds","-")}s</p>'
            + (f'<p><b>关键原句：</b></p><ul>{kq}</ul>' if kq else "")
            + f'<p><b>原文引用：</b>{esc((e.get("source_quote") or "")[:120])}</p></div>')
    detail_js = json.dumps(details, ensure_ascii=False)
    t = title or f"{proj.name} 事件表"
    doc = f'''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>{esc(t)}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#f5f6f8;color:#222}}
header{{background:#1f2a44;color:#fff;padding:14px 20px;position:sticky;top:0;z-index:9}}
header h1{{font-size:18px}} header p{{font-size:12px;opacity:.8;margin-top:4px}}
header input{{margin-top:8px;padding:6px 10px;width:320px;border-radius:6px;border:none;font-size:13px}}
.wrap{{display:flex;height:calc(100vh - 96px)}}
#side{{width:400px;min-width:400px;overflow:auto;background:#fff;border-right:1px solid #ddd;padding:10px}}
#main{{flex:1;overflow:auto;padding:20px 28px}}
.ev{{border:1px solid #e5e7eb;border-radius:8px;padding:8px 10px;margin:6px 0;cursor:pointer;font-size:13px;background:#fafafa}}
.ev:hover{{border-color:#4f6ef7;background:#eef2ff}}.ev.used{{border-left:3px solid #22a06b}}.ev.cut{{border-left:3px solid #d64545}}
.ev-id{{font-weight:600}}.b-used{{color:#22a06b;font-size:11px;margin-left:6px}}.b-cut{{color:#d64545;font-size:11px;margin-left:6px}}
.ev-sum{{color:#555;margin-top:2px;font-size:12px}}
.chap h3{{margin:12px 0 4px;color:#1f2a44;border-bottom:1px solid #eee;padding-bottom:4px}}
.chsec{{margin-bottom:28px}}.chsec h2{{color:#1f2a44;font-size:20px;margin-bottom:10px}}
.evmark{{background:#fff3a0;cursor:pointer;border-radius:3px;padding:0 1px}}.evmark:hover{{background:#ffd966}}
mark#hi{{background:#ffd54f;outline:2px solid #f59f00}}
.detail{{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;margin-bottom:16px;font-size:14px;line-height:1.7}}
.detail h3{{color:#1f2a44}}.detail .st{{font-size:12px;color:#4f6ef7;margin-left:8px}}.detail p{{margin:4px 0}}.detail ul{{margin-left:20px}}
#filters button{{padding:4px 10px;margin-right:6px;border-radius:6px;border:1px solid #ccc;background:#fff;cursor:pointer;font-size:12px}}
#filters button.on{{background:#4f6ef7;color:#fff;border-color:#4f6ef7}}
</style></head><body>
<header><h1>{esc(t)}</h1>
<p>事件总数 {len(evs)} ｜ 集纲选用 {len(selected)} ｜ 未选用 {len(evs)-len(selected)} ｜ 点左侧事件或正文高亮处查看详情</p>
<input id="q" placeholder="搜索事件（如 狗屎 / 咬 / 主人）" oninput="filterList()">
<div id="filters" style="margin-top:6px"><button class="on" data-f="all" onclick="setF('all')">全部</button>
<button data-f="used" onclick="setF('used')">✔ 选用</button><button data-f="cut" onclick="setF('cut')">✘ 被裁</button></div>
</header><div class="wrap"><div id="side">{sidebar}</div><div id="main"><div id="detail"></div>{body}</div></div>
<script>const DETAILS={detail_js};
let curF='all';
function pick(eid){{document.getElementById('detail').innerHTML=DETAILS[eid]||'<p>无详情</p>';
const m=document.getElementById('m-'+eid);if(m){{m.scrollIntoView({{behavior:'smooth',block:'center'}});const o=m.id;m.id='hi';setTimeout(()=>m.id=o,2500);}}
document.querySelectorAll('.ev').forEach(x=>x.style.background='');const el=document.querySelector('.ev[data-eid="'+eid+'"]');if(el)el.style.background='#e8eeff';}}
function setF(f){{curF=f;document.querySelectorAll('#filters button').forEach(b=>b.classList.toggle('on',b.dataset.f===f));filterList();}}
function filterList(){{const q=document.getElementById('q').value.trim().toLowerCase();
document.querySelectorAll('.ev').forEach(el=>{{const u=el.classList.contains('used');const okF=curF==='all'||(curF==='used'&&u)||(curF==='cut'&&!u);const okQ=!q||el.textContent.toLowerCase().indexOf(q)>=0;el.style.display=(okF&&okQ)?'':'none';}});
document.querySelectorAll('.chap').forEach(ch=>{{const any=[...ch.querySelectorAll('.ev')].some(e=>e.style.display!=='none');ch.style.display=any?'':'none';}});}}
</script></body></html>'''
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return out

# CLI 与自动重建钩子统一使用 build_event_browser 名称
build_event_browser = build


def default_out(project_dir: Path) -> Path:
    """默认输出：<项目>/event_browser/index.html（稳定路径，供编剧对照集纲）。"""
    return Path(project_dir).expanduser().resolve() / "event_browser" / "index.html"


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="fangcun event-browser",
                                 description="生成集纲事件浏览器 HTML（编剧对照集纲与原文，查看选用/被裁）。纯本地、零模型调用。")
    ap.add_argument("--dir", required=True, help="项目目录")
    ap.add_argument("--out", help="输出 HTML 路径（默认 <项目>/event_browser/index.html）")
    ap.add_argument("--title", help="页面标题（默认项目名）")
    a = ap.parse_args(argv)
    proj = Path(a.dir).expanduser().resolve()
    out = Path(a.out).expanduser().resolve() if a.out else default_out(proj)
    r = build(proj, out, a.title or f"{proj.name} 集纲事件浏览器")
    print(f"事件浏览器已生成：{r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
