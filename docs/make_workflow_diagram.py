#!/usr/bin/env python3
"""Render the workflow diagram shipped with the plugin.

The README carries the flow as text; a diagram is what a reader looks at first, and a generator in the
repo keeps the picture from drifting away from the code.

Layout is computed rather than hand-placed: every box is laid out on a cursor, text is measured with
the real font, and the renderer asserts that nothing leaves the canvas and that no two boxes overlap.
Run it after changing the flow:

    python3 docs/make_workflow_diagram.py           # docs/workflow.zh.png + docs/workflow.en.png
"""

from __future__ import annotations

import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont

SCALE = 2                     # supersampled, then downscaled for crisp text
W, H = 1920, 1600
MARGIN = 64

INK = (17, 18, 20)
SOFT = (65, 72, 85)
MUTED = (107, 114, 128)
FAINT = (214, 219, 227)
CARD = (255, 255, 255)
CARD_LINE = (227, 231, 238)
HOT = (232, 70, 45)
BLUE = (47, 111, 235)
GREEN = (47, 168, 79)
AMBER = (183, 121, 31)
WASH_HOT = (253, 244, 242)
WASH_BLUE = (243, 247, 254)
WASH_GREEN = (241, 249, 243)
WASH_AMBER = (253, 248, 239)

CJK = "/System/Library/Fonts/Hiragino Sans GB.ttc"
MONO = "/System/Library/Fonts/Menlo.ttc"

FONTS: dict[tuple[str, int, str], ImageFont.FreeTypeFont] = {}


def font(kind: str, size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    key = (kind, size, weight)
    if key not in FONTS:
        path = CJK if kind == "cjk" else MONO
        if kind == "cjk":
            index = 2 if weight == "bold" else 0        # Hiragino W6 / W3
        else:
            index = 1 if weight == "bold" else 0        # Menlo Bold / Regular
        FONTS[key] = ImageFont.truetype(path, size * SCALE, index=index)
    return FONTS[key]


TEXT = {
    "zh": {
        "slug": "human-microbiome-function-mining",
        "title": "人体微生物组功能挖掘插件 · 工作流程",
        "subtitle": "两条入口，一条可审计的挖掘链：每一步都留下参照物、阈值与证据来源",
        "entryA_tag": "ENTRY A",
        "entryA_title": "能说出目标",
        "entryA_body": ["给 EC 号、底物-产物反应式或参考序列",
                        "build_target_function_card → target_function_card.json"],
        "entryB_tag": "ENTRY B",
        "entryB_title": "只说得出关注点",
        "entryB_body": ["browse_target_library 摊开菜单 + 每个候选补文献（不是只查库）",
                        "候选酶 / 候选菌排序表 → 你挑一条，收敛到一个 EC"],
        "handoff": "B → A：选定候选后交棒（run_entry_b.py --select <id> --ec <EC>），不重新推导",
        "s0": "0 · 两条入口",
        "s1": "1 · 目标与模板",
        "card": ("target_function_card.json", "目标身份 + 反应 + 辅因子"),
        "templates": ("fetch_reference_enzymes.py", "宿主 + 微生物模板，只收 reviewed；结构取自 PDB 交叉引用"),
        "cdhit": ("CD-HIT", "单基因组 100%，pan-proteome 95%"),
        "diamond": ("DIAMOND", "identity ≥ 20% · coverage ≥ 0.7 · E ≤ 1e-5"),
        "parse": ("parse_sequence_hits → merge_source_annotations", "候选自己的注释作为独立证据并入"),
        "s2": "2 · 判定：序列能不能定案",
        "decision": ("候选自带注释与目标同向？", "同向 = 同一 EC 或同类酶名"),
        "yes": ("SEQUENCE_ANNOTATION_CONFIRMED", "跳过结构，直接出结果"),
        "no": ("进入结构通道", "structure-prediction：PDB > AFDB pLDDT ≥ 60 > 同源建模 > de novo"),
        "usalign": ("US-align 全量", "TM ≥ 0.5（双向）"),
        "deer": ("DEER 兜底", "仅当合格候选不足、且用户同意"),
        "fedkea": ("FedKEA", "酶 / EC 补充证据（预测，不是生化证明）"),
        "s3": "3 · 证据与排序",
        "lit": ("literature-evidence", "每个候选都检索（含结构查询）；只收核验过的 PMID / DOI，检索不到留空"),
        "merge": ("merge_candidates → score_candidates", "TM 优先；USALIGN_OTHER_EC 保留为候选，不是排除"),
        "shortlist": ("score_target_priorities --auto-score", "候选酶 / 候选菌推荐表：证据分层，档内按分数"),
        "gates": ("decisions.py 判断题闸门", "数据路径 · 结构文件 · DEER · 交付规则：没回答就停下问"),
        "s4": "4 · 交付与自查",
        "summary": ("summarize_candidates.py", "最终候选 + 摘要 + 可证伪假设"),
        "delivery": ("outputs/task/ 交付集", "final_target_candidates.tsv · 空表说明 · 高置信摘要 · experimental_hypotheses.tsv"),
        "check": ("check_deliverables.py", "逐项 ok / EMPTY / MISS，缺哪项给哪条命令"),
        "rules": "三条不变式：每条结论都带参照物与阈值 · 空表必须解释 · 没有证据不记低分",
    },
    "en": {
        "slug": "human-microbiome-function-mining",
        "title": "Human Microbiome Function Mining · workflow",
        "subtitle": "Two entries, one auditable chain: every step keeps its reference, threshold and evidence source",
        "entryA_tag": "ENTRY A",
        "entryA_title": "the user can name the target",
        "entryA_body": ["EC number, substrate-product reaction, or reference sequence",
                        "build_target_function_card → target_function_card.json"],
        "entryB_tag": "ENTRY B",
        "entryB_title": "the user only knows a focus point",
        "entryB_body": ["browse_target_library lays out the menu + literature per candidate (not library-only)",
                        "ranked candidate enzymes / taxa → pick one, converge to an EC"],
        "handoff": "B → A: hand off after choosing (run_entry_b.py --select <id> --ec <EC>), nothing re-derived",
        "s0": "0 · two entries",
        "s1": "1 · target and templates",
        "card": ("target_function_card.json", "identity + reaction + cofactor"),
        "templates": ("fetch_reference_enzymes.py", "host + microbial templates, reviewed only; structures from PDB cross-refs"),
        "cdhit": ("CD-HIT", "single genome 100%, pan-proteome 95%"),
        "diamond": ("DIAMOND", "identity >= 20% · coverage >= 0.7 · E <= 1e-5"),
        "parse": ("parse_sequence_hits → merge_source_annotations", "the candidate's own annotation joins as separate evidence"),
        "s2": "2 · decision: does sequence settle it?",
        "decision": ("candidate annotation agrees with the target?", "agrees = same EC or the same enzyme name"),
        "yes": ("SEQUENCE_ANNOTATION_CONFIRMED", "structure skipped, straight to results"),
        "no": ("enter the structure channel", "structure-prediction: PDB > AFDB pLDDT >= 60 > homology > de novo"),
        "usalign": ("full US-align", "TM >= 0.5 both directions"),
        "deer": ("DEER fallback", "only when too few candidates and the user agrees"),
        "fedkea": ("FedKEA", "enzyme / EC supporting evidence (a prediction, not a biochemical proof)"),
        "s3": "3 · evidence and ranking",
        "lit": ("literature-evidence", "retrieved per candidate, structure query included; verified PMID / DOI only, empty when nothing is found"),
        "merge": ("merge_candidates → score_candidates", "TM first; USALIGN_OTHER_EC is kept as a candidate, not excluded"),
        "shortlist": ("score_target_priorities --auto-score", "candidate enzymes / taxa: evidence tier first, score within it"),
        "gates": ("decisions.py judgement gates", "data paths · structures · DEER · delivery rules: stop and ask"),
        "s4": "4 · delivery and self-check",
        "summary": ("summarize_candidates.py", "final candidates + summary + falsifiable hypotheses"),
        "delivery": ("outputs/task/ delivery set", "final_target_candidates.tsv · empty-table note · high-confidence summary · experimental_hypotheses.tsv"),
        "check": ("check_deliverables.py", "ok / EMPTY / MISS per item, with the command that fills each gap"),
        "rules": "three invariants: every conclusion keeps its reference and thresholds · an empty table must explain itself · no evidence is not a low score",
    },
}


class Canvas:
    """Draw in unscaled coordinates; assert nothing leaves the canvas or overlaps."""

    def __init__(self) -> None:
        self.img = Image.new("RGB", (W * SCALE, H * SCALE), (255, 255, 255))
        self.d = ImageDraw.Draw(self.img)
        self.boxes: list[tuple[float, float, float, float]] = []

    # -- primitives ------------------------------------------------------
    def text(self, x, y, s, size=17, colour=INK, kind="cjk", weight="regular", anchor="la"):
        self.d.text((x * SCALE, y * SCALE), s, font=font(kind, size, weight), fill=colour, anchor=anchor)
        self._assert_inside(x, y, s, size, kind, weight)

    def width(self, s, size=17, kind="cjk", weight="regular") -> float:
        return self.d.textlength(s, font=font(kind, size, weight)) / SCALE

    def wrap(self, s, maxw, size=15, kind="cjk", weight="regular") -> list[str]:
        """Break on spaces for Latin text, per character for CJK.

        Splitting Latin words mid-word produced things like "pan-proteo / ome 95%" in the first
        render, which reads as a typo.
        """
        tokens: list[str] = []
        word = ""
        for ch in s:
            if ch == " ":
                if word:
                    tokens.append(word)
                    word = ""
                tokens.append(" ")
            elif ord(ch) < 128 and ch not in "，。、；：（）":
                word += ch
            else:
                if word:
                    tokens.append(word)
                    word = ""
                tokens.append(ch)
        if word:
            tokens.append(word)
        lines, current = [], ""
        for token in tokens:
            trial = current + token
            if self.width(trial, size, kind, weight) > maxw and current.strip():
                lines.append(current.rstrip())
                current = token.lstrip()
            else:
                current = trial
        if current.strip():
            lines.append(current.rstrip())
        return lines

    def para(self, x, y, s, maxw, size=13, colour=MUTED, kind="cjk", weight="regular", max_lines=3):
        for i, line in enumerate(self.wrap(s, maxw, size, kind, weight)[:max_lines]):
            self.text(x, y + i * (size * 1.5), line, size, colour, kind, weight)
        return y + min(max_lines, len(self.wrap(s, maxw, size, kind, weight))) * (size * 1.5)

    def box(self, x, y, w, h, fill=CARD, line=CARD_LINE, radius=14, width=1.6):
        self.d.rounded_rectangle((x * SCALE, y * SCALE, (x + w) * SCALE, (y + h) * SCALE),
                                 radius=radius * SCALE, fill=fill, outline=line, width=int(width * SCALE))
        for bx, by, bw, bh in self.boxes:
            if x < bx + bw and bx < x + w and y < by + bh and by < y + h:
                raise SystemExit(f"overlapping boxes: ({x},{y},{w},{h}) vs ({bx},{by},{bw},{bh})")
        self.boxes.append((x, y, w, h))
        if x < 0 or y < 0 or x + w > W or y + h > H:
            raise SystemExit(f"box outside canvas: ({x},{y},{w},{h})")

    def arrow(self, x1, y1, x2, y2, colour=MUTED, width=2.2, dash=False):
        d = self.d
        (ax, ay), (bx, by) = (x1 * SCALE, y1 * SCALE), (x2 * SCALE, y2 * SCALE)
        if dash:
            step = 9 * SCALE
            total = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
            ux, uy = (bx - ax) / total, (by - ay) / total
            pos = 0.0
            while pos < total - 8 * SCALE:
                d.line([(ax + ux * pos, ay + uy * pos),
                        (ax + ux * min(pos + step, total - 8 * SCALE), ay + uy * min(pos + step, total - 8 * SCALE))],
                       fill=colour, width=int(width * SCALE))
                pos += step * 2
        else:
            d.line([(ax, ay), (bx, by)], fill=colour, width=int(width * SCALE))
        if abs(bx - ax) >= abs(by - ay):
            sign = 1 if bx > ax else -1
            d.polygon([(bx, by), (bx - sign * 11 * SCALE, by - 6 * SCALE), (bx - sign * 11 * SCALE, by + 6 * SCALE)],
                      fill=colour)
        else:
            sign = 1 if by > ay else -1
            d.polygon([(bx, by), (bx - 6 * SCALE, by - sign * 11 * SCALE), (bx + 6 * SCALE, by - sign * 11 * SCALE)],
                      fill=colour)

    def _assert_inside(self, x, y, s, size, kind, weight):
        if not s:
            return
        w = self.width(s, size, kind, weight)
        if x < 0 or x + w > W + 1 or y < 0 or y + size * 1.4 > H + 1:
            raise SystemExit(f"text outside canvas at ({x},{y}): {s[:40]!r} width={w:.0f}")

    # -- composite -------------------------------------------------------
    def card(self, x, y, w, h, title, detail, fill=CARD, line=CARD_LINE, title_size=15,
             mono=False, accent=INK, detail_colour=MUTED, pad=20):
        self.box(x, y, w, h, fill, line)
        kind = "mono" if mono else "cjk"
        lines = self.wrap(title, w - 2 * pad, title_size, kind, "bold")
        ty = y + pad + title_size
        for line in lines:
            self.text(x + pad, ty, line, title_size, accent, kind, "bold")
            ty += title_size * 1.35
        if detail:
            ty += 4
            for line in self.wrap(detail, w - 2 * pad, 13, "cjk")[:3]:
                self.text(x + pad, ty, line, 13, detail_colour)
                ty += 20

    def band(self, y, label):
        self.d.line([(MARGIN * SCALE, y * SCALE), ((W - MARGIN) * SCALE, y * SCALE)], fill=FAINT, width=SCALE)
        self.text(MARGIN, y - 26, label, 14, MUTED, "cjk", "bold")
        return y + 14

    def save(self, path: pathlib.Path):
        self.img = self.img.resize((W, H), Image.LANCZOS)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.img.save(path, "PNG", optimize=True)
        print(f"wrote {path} ({path.stat().st_size // 1024} KB)")


def build(lang: str) -> Canvas:
    t = TEXT[lang]
    c = Canvas()
    # title
    c.text(MARGIN, 46, t["slug"], 14, HOT, "mono", "bold")
    c.text(MARGIN, 88, t["title"], 34, INK, "cjk", "bold")
    c.text(MARGIN, 130, t["subtitle"], 17, SOFT)

    # band 1: entries
    y = c.band(190, t["s0"])
    entry_h = 150
    a_w = 860
    c.box(MARGIN, y, a_w, entry_h, WASH_HOT, (243, 217, 210))
    c.text(MARGIN + 26, y + 30, t["entryA_tag"], 13, HOT, "mono", "bold")
    c.text(MARGIN + 26, y + 58, t["entryA_title"], 21, INK, "cjk", "bold")
    c.text(MARGIN + 26, y + 92, t["entryA_body"][0], 15, SOFT)
    c.text(MARGIN + 26, y + 118, t["entryA_body"][1], 14, BLUE, "mono")

    b_x = MARGIN + a_w + 60
    b_w = W - MARGIN - b_x
    c.box(b_x, y, b_w, entry_h, WASH_BLUE, (215, 227, 248))
    c.text(b_x + 26, y + 30, t["entryB_tag"], 13, BLUE, "mono", "bold")
    c.text(b_x + 26, y + 58, t["entryB_title"], 21, INK, "cjk", "bold")
    c.text(b_x + 26, y + 92, t["entryB_body"][0], 15, SOFT)
    c.text(b_x + 26, y + 118, t["entryB_body"][1], 15, SOFT)
    # handoff arrow, drawn in the gutter between the cards
    mid_y = y + entry_h / 2
    c.arrow(b_x - 6, mid_y, MARGIN + a_w + 6, mid_y, HOT, 2.4)
    c.text(b_x - 34, mid_y - 34, "B → A", 15, HOT, "cjk", "bold", anchor="ra")
    c.text(MARGIN, y + entry_h + 30, t["handoff"], 15, SOFT)

    # band 2: templates and screening
    y = c.band(y + entry_h + 96, t["s1"])
    cards = [
        (t["card"], 280, True), (t["templates"], 330, True), (t["cdhit"], 210, True),
        (t["diamond"], 300, True), (t["parse"], 560, True),
    ]
    total = sum(w for _, w, _ in cards) + 26 * (len(cards) - 1)
    if MARGIN + total > W - MARGIN:
        raise SystemExit(f"screening row too wide: {total}")
    x = MARGIN
    row_h = 104
    for i, ((title, detail), w, mono) in enumerate(cards):
        c.card(x, y, w, row_h, title, detail, mono=mono, title_size=14)
        if i < len(cards) - 1:
            c.arrow(x + w + 3, y + row_h / 2, x + w + 23, y + row_h / 2)
        x += w + 26

    # band 3: decision
    y = c.band(y + row_h + 64, t["s2"])
    dec_w, dec_h = 520, 104
    c.box(MARGIN, y, dec_w, dec_h, WASH_AMBER, (240, 224, 194))
    c.text(MARGIN + 24, y + 38, t["decision"][0], 18, INK, "cjk", "bold")
    c.para(MARGIN + 24, y + 62, t["decision"][1], dec_w - 48, 13)

    yes_x = MARGIN + dec_w + 50
    yes_w = 560
    c.box(yes_x, y, yes_w, dec_h, WASH_GREEN, (205, 235, 214))
    c.text(yes_x + 24, y + 38, t["yes"][0], 14, GREEN, "mono", "bold")
    c.para(yes_x + 24, y + 62, t["yes"][1], yes_w - 48, 13, SOFT)
    c.arrow(MARGIN + dec_w + 6, y + dec_h / 2, yes_x - 6, y + dec_h / 2, GREEN, 2.2)
    c.text(yes_x + yes_w - 146, y + dec_h + 26, "yes" if lang == "en" else "是", 12, GREEN, "cjk", "bold", anchor="ra")

    # no branch, one row below
    ny = y + dec_h + 38
    no_w = 520
    c.box(MARGIN, ny, no_w, 92, CARD, CARD_LINE)
    c.text(MARGIN + 24, ny + 30, t["no"][0], 16, INK, "cjk", "bold")
    c.para(MARGIN + 24, ny + 54, t["no"][1], no_w - 48, 12)
    c.arrow(MARGIN + no_w / 2, y + dec_h + 4, MARGIN + no_w / 2, ny - 4)
    c.text(MARGIN + no_w / 2 + 12, y + dec_h + 30, "no" if lang == "en" else "否", 12, MUTED, "cjk", "bold")

    us_x = MARGIN + no_w + 50
    us_w = 400
    c.box(us_x, ny, us_w, 92, CARD, CARD_LINE)
    c.text(us_x + 24, ny + 30, t["usalign"][0], 16, INK, "cjk", "bold")
    c.para(us_x + 24, ny + 54, t["usalign"][1], us_w - 48, 13)
    c.arrow(MARGIN + no_w + 6, ny + 46, us_x - 6, ny + 46)

    deer_x = us_x + us_w + 50
    deer_w = W - MARGIN - deer_x
    if deer_w < 300:
        raise SystemExit(f"DEER card too narrow: {deer_w}")
    c.box(deer_x, ny, deer_w, 92, CARD, CARD_LINE)
    c.text(deer_x + 24, ny + 30, t["deer"][0], 16, INK, "cjk", "bold")
    c.para(deer_x + 24, ny + 54, t["deer"][1], deer_w - 48, 12)
    c.arrow(us_x + us_w + 6, ny + 46, deer_x - 6, ny + 46)

    # converge on FedKEA
    fy = ny + 92 + 38
    c.box(MARGIN, fy, W - 2 * MARGIN, 84, CARD, CARD_LINE)
    c.text(MARGIN + 24, fy + 30, t["fedkea"][0], 17, INK, "cjk", "bold")
    c.para(MARGIN + 24, fy + 54, t["fedkea"][1], W - 2 * MARGIN - 48, 13)
    # yes -> FedKEA (down the left gutter of the yes card), no-row -> FedKEA
    c.arrow(yes_x + yes_w - 130, y + dec_h + 4, yes_x + yes_w - 130, fy - 4, GREEN, 2.2, dash=True)
    c.arrow(deer_x + deer_w / 2, ny + 92 + 4, deer_x + deer_w / 2, fy - 4, MUTED, 2.2, dash=True)

    # band 4: evidence and ranking
    y = c.band(fy + 84 + 64, t["s3"])
    lit_w = 470
    c.card(MARGIN, y, lit_w, 92, t["lit"][0], t["lit"][1], mono=True, title_size=14)
    merge_x = MARGIN + lit_w + 50
    merge_w = W - MARGIN - merge_x
    c.card(merge_x, y, merge_w, 92, t["merge"][0], t["merge"][1], mono=True, title_size=14)
    c.arrow(MARGIN + lit_w + 6, y + 46, merge_x - 6, y + 46)

    ry = y + 92 + 34
    short_w = 800
    c.card(MARGIN, ry, short_w, 92, t["shortlist"][0], t["shortlist"][1], mono=True, title_size=14)
    gate_x = MARGIN + short_w + 50
    gate_w = W - MARGIN - gate_x
    c.box(gate_x, ry, gate_w, 92, WASH_AMBER, (240, 224, 194))
    c.text(gate_x + 22, ry + 30, t["gates"][0], 15, INK, "cjk", "bold")
    c.para(gate_x + 22, ry + 54, t["gates"][1], gate_w - 44, 12)

    # band 5: delivery
    y = c.band(ry + 92 + 64, t["s4"])
    sum_w = 470
    c.card(MARGIN, y, sum_w, 96, t["summary"][0], t["summary"][1], mono=True, title_size=14)
    del_x = MARGIN + sum_w + 50
    del_w = 900
    c.card(del_x, y, del_w, 96, t["delivery"][0], t["delivery"][1], title_size=15)
    c.arrow(MARGIN + sum_w + 6, y + 48, del_x - 6, y + 48)
    chk_x = del_x + del_w + 50
    chk_w = W - MARGIN - chk_x
    if chk_w < 260:
        raise SystemExit(f"check card too narrow: {chk_w}")
    c.box(chk_x, y, chk_w, 96, WASH_GREEN, (205, 235, 214))
    c.text(chk_x + 22, y + 30, t["check"][0], 14, GREEN, "mono", "bold")
    c.para(chk_x + 22, y + 54, t["check"][1], chk_w - 44, 11)
    c.arrow(del_x + del_w + 6, y + 48, chk_x - 6, y + 48)

    # invariants
    strip_y = y + 96 + 34
    c.box(MARGIN, strip_y, W - 2 * MARGIN, 56, WASH_BLUE, (215, 227, 248))
    c.para(MARGIN + 22, strip_y + 32, t["rules"], W - 2 * MARGIN - 44, 14, SOFT, max_lines=1)
    if strip_y + 56 > H:
        raise SystemExit(f"strip overflows canvas: {strip_y + 56} > {H}")
    return c


def main() -> int:
    out_dir = pathlib.Path(__file__).resolve().parent
    for lang in ("zh", "en"):
        build(lang).save(out_dir / f"workflow.{lang}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
