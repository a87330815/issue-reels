# -*- coding: utf-8 -*-
"""
insights_report.py — 인사이트 주간 분석 리포트

data/insights.csv를 읽어 최근 7일 성과를 분석하고,
카테고리별·시간대별·포맷별 성과를 요약한다.
scriptgen.py가 참고할 수 있는 JSON 힌트 파일도 생성한다.

사용:
  python insights_report.py              # 최근 7일 분석
  python insights_report.py --days 14    # 최근 14일
  python insights_report.py --json       # JSON 힌트만 출력

출력:
  data/weekly_report.md   — 사람이 읽는 리포트
  data/perf_hints.json    — scriptgen이 참조하는 성과 힌트
"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(ROOT, "data", "insights.csv")
ACCOUNT_CSV_PATH = os.path.join(ROOT, "data", "account_insights.csv")
PUBLISHED_PATH = os.path.join(ROOT, "out", "published.json")
REPORT_PATH = os.path.join(ROOT, "data", "weekly_report.md")
HINTS_PATH = os.path.join(ROOT, "data", "perf_hints.json")


def load_published_metadata():
    """발행 기록의 카테고리·포맷을 media_id 기준으로 읽는다."""
    if not os.path.exists(PUBLISHED_PATH):
        return {}
    try:
        with open(PUBLISHED_PATH, encoding="utf-8") as f:
            items = json.load(f).get("items", [])
    except (OSError, json.JSONDecodeError):
        return {}
    meta = {}
    for item in items:
        media_id = str(item.get("media_id") or "")
        if not media_id:
            continue
        name = item.get("name") or ""
        parts = name.split("_")
        fmt = parts[-1] if len(parts) >= 3 else "미분류"
        meta[media_id] = {
            "category": item.get("category") or "미분류",
            "format": fmt,
            "content_name": name,
        }
    return meta


def load_rows(days=7):
    """최근 N일 인사이트 로우를 로드. 같은 미디어는 최신 행만."""
    if not os.path.exists(CSV_PATH):
        print(f"[오류] {CSV_PATH} 없음")
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows_by_id = {}

    with open(CSV_PATH, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("collected_at", "") < cutoff:
                continue
            mid = row.get("media_id", "")
            # 같은 미디어는 최신 수집분만 유지
            existing = rows_by_id.get(mid)
            if not existing or row["collected_at"] > existing["collected_at"]:
                rows_by_id[mid] = row

    rows = list(rows_by_id.values())
    published = load_published_metadata()
    for row in rows:
        meta = published.get(str(row.get("media_id") or ""), {})
        row["_category"] = meta.get("category", "미분류")
        row["_format"] = meta.get("format", "미분류")
        row["_content_name"] = meta.get("content_name", "")
    return rows


def _int(v):
    try:
        return int(v)
    except (ValueError, TypeError):
        return 0


def load_account_growth(days=7):
    """최근 N일 계정 스냅샷으로 팔로워 순증가를 계산한다."""
    if not os.path.exists(ACCOUNT_CSV_PATH):
        return {"available": False}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    snapshots = []
    with open(ACCOUNT_CSV_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                collected = datetime.fromisoformat(
                    (row.get("collected_at") or "").replace("Z", "+00:00")
                )
            except ValueError:
                continue
            if collected >= cutoff:
                snapshots.append((collected, row))

    if not snapshots:
        return {"available": False}
    snapshots.sort(key=lambda x: x[0])
    first = snapshots[0][1]
    last = snapshots[-1][1]
    start = _int(first.get("followers_count"))
    end = _int(last.get("followers_count"))
    net = end - start
    rate = round(net / start * 100, 2) if start else 0
    return {
        "available": True,
        "username": last.get("username", ""),
        "start_followers": start,
        "end_followers": end,
        "net_followers": net,
        "growth_rate": rate,
        "snapshot_count": len(snapshots),
    }


def _group_performance(rows, field):
    groups = defaultdict(list)
    for row in rows:
        groups[row.get(field) or "미분류"].append(row)
    result = []
    for name, items in groups.items():
        views = sum(_int(x.get("views")) for x in items)
        reach = sum(_int(x.get("reach")) for x in items)
        saves = sum(_int(x.get("saved")) for x in items)
        shares = sum(_int(x.get("shares")) for x in items)
        result.append({
            "name": name,
            "count": len(items),
            "avg_views": round(views / len(items)) if items else 0,
            "save_rate": round(saves / reach * 100, 2) if reach else 0,
            "share_rate": round(shares / reach * 100, 2) if reach else 0,
        })
    return sorted(result, key=lambda x: (x["avg_views"], x["share_rate"]), reverse=True)


def analyze(rows):
    """성과 분석 결과 dict 반환."""
    if not rows:
        return {"error": "데이터 없음", "count": 0}

    # 기본 지표 집계
    total_views = sum(_int(r.get("views")) for r in rows)
    total_reach = sum(_int(r.get("reach")) for r in rows)
    total_likes = sum(_int(r.get("like_count")) for r in rows)
    total_saves = sum(_int(r.get("saved")) for r in rows)
    total_shares = sum(_int(r.get("shares")) for r in rows)
    total_comments = sum(_int(r.get("comments_count")) for r in rows)
    n = len(rows)

    # 시간대별 평균 조회수
    hour_views = defaultdict(list)
    for r in rows:
        ts = r.get("timestamp", "")
        if "T" in ts:
            try:
                # Instagram timestamp는 UTC
                h = int(ts.split("T")[1][:2])
                kst_h = (h + 9) % 24
                hour_views[kst_h].append(_int(r.get("views")))
            except (ValueError, IndexError):
                pass

    hour_avg = {}
    for h, vs in sorted(hour_views.items()):
        hour_avg[h] = round(sum(vs) / len(vs)) if vs else 0

    # 캡션에서 카테고리 추출 시도 (커버 텍스트 기반)
    # insights.csv에 카테고리가 없으므로 caption_preview로 최선의 추정
    # → 향후 publish.py에서 카테고리를 CSV에 추가하면 정확해짐

    # 상위/하위 콘텐츠
    ranked = sorted(rows, key=lambda r: _int(r.get("views")), reverse=True)
    top3 = [{
        "caption": r.get("caption_preview", "")[:40],
        "views": _int(r.get("views")),
        "likes": _int(r.get("like_count")),
        "saves": _int(r.get("saved")),
        "shares": _int(r.get("shares")),
        "permalink": r.get("permalink", ""),
    } for r in ranked[:3]]

    bottom3 = [{
        "caption": r.get("caption_preview", "")[:40],
        "views": _int(r.get("views")),
        "likes": _int(r.get("like_count")),
        "permalink": r.get("permalink", ""),
    } for r in ranked[-3:]] if n >= 6 else []

    # 인게이지먼트율 (좋아요+댓글+저장+공유 / 도달)
    eng_rate = 0
    if total_reach > 0:
        eng_rate = round(
            (total_likes + total_comments + total_saves + total_shares)
            / total_reach * 100, 2
        )

    # 최적 게시 시간 추천
    best_hours = sorted(hour_avg.items(), key=lambda x: x[1], reverse=True)[:3]

    return {
        "period_days": len(set(r.get("collected_at", "")[:10] for r in rows)),
        "count": n,
        "total_views": total_views,
        "total_reach": total_reach,
        "avg_views": round(total_views / n) if n else 0,
        "avg_reach": round(total_reach / n) if n else 0,
        "avg_likes": round(total_likes / n, 1) if n else 0,
        "avg_saves": round(total_saves / n, 1) if n else 0,
        "avg_shares": round(total_shares / n, 1) if n else 0,
        "engagement_rate": eng_rate,
        "hour_avg": hour_avg,
        "best_hours_kst": [h for h, _ in best_hours],
        "top3": top3,
        "bottom3": bottom3,
        "category_performance": _group_performance(rows, "_category"),
        "format_performance": _group_performance(rows, "_format"),
    }


def build_report(analysis, days):
    """마크다운 리포트 생성."""
    if "error" in analysis:
        return f"# 주간 인사이트 리포트\n\n데이터 없음 (최근 {days}일)\n"

    lines = [
        f"# 📊 인사이트 리포트 (최근 {days}일)",
        f"",
        f"분석 대상: **{analysis['count']}개** 릴스",
        f"",
        f"## 계정 성장",
        (
            f"- 팔로워: **{analysis['account_growth']['start_followers']:,} → "
            f"{analysis['account_growth']['end_followers']:,}** "
            f"({analysis['account_growth']['net_followers']:+,}, "
            f"{analysis['account_growth']['growth_rate']:+.2f}%)"
            if analysis.get("account_growth", {}).get("available")
            else "- 팔로워 성장: 스냅샷 누적 후 표시"
        ),
        f"",
        f"## 핵심 지표",
        f"| 지표 | 합계 | 평균 |",
        f"|------|------|------|",
        f"| 조회수 | {analysis['total_views']:,} | {analysis['avg_views']:,} |",
        f"| 도달 | {analysis['total_reach']:,} | {analysis['avg_reach']:,} |",
        f"| 좋아요 | — | {analysis['avg_likes']} |",
        f"| 저장 | — | {analysis['avg_saves']} |",
        f"| 공유 | — | {analysis['avg_shares']} |",
        f"| 인게이지먼트율 | — | {analysis['engagement_rate']}% |",
        f"",
    ]

    if analysis.get("category_performance"):
        lines += ["## 주제별 성과", "| 주제 | 게시물 | 평균 조회 | 저장률 | 공유율 |",
                  "|------|------:|----------:|-------:|-------:|"]
        for item in analysis["category_performance"]:
            lines.append(
                f"| {item['name']} | {item['count']} | {item['avg_views']:,} | "
                f"{item['save_rate']}% | {item['share_rate']}% |"
            )
        lines.append("")

    if analysis.get("format_performance"):
        lines += ["## 제작 형식별 성과", "| 형식 | 게시물 | 평균 조회 | 저장률 | 공유율 |",
                  "|------|------:|----------:|-------:|-------:|"]
        for item in analysis["format_performance"]:
            lines.append(
                f"| {item['name']} | {item['count']} | {item['avg_views']:,} | "
                f"{item['save_rate']}% | {item['share_rate']}% |"
            )
        lines.append("")

    if analysis.get("best_hours_kst"):
        hours_str = ", ".join(f"{h}시" for h in analysis["best_hours_kst"])
        lines += [
            f"## 최적 게시 시간 (KST)",
            f"상위 시간대: **{hours_str}**",
            f"",
        ]

    if analysis.get("top3"):
        lines += [f"## 🏆 TOP 3"]
        for i, t in enumerate(analysis["top3"], 1):
            lines.append(
                f"{i}. **{t['caption']}** — 조회 {t['views']:,} / "
                f"좋아요 {t['likes']} / 저장 {t['saves']} / 공유 {t['shares']}"
            )
        lines.append("")

    if analysis.get("bottom3"):
        lines += [f"## 개선 필요"]
        for t in analysis["bottom3"]:
            lines.append(f"- {t['caption']} — 조회 {t['views']:,}")
        lines.append("")

    lines += [
        f"---",
        f"생성: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    return "\n".join(lines)


def build_hints(analysis):
    """scriptgen이 참조할 수 있는 성과 힌트 JSON."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "avg_views": analysis.get("avg_views", 0),
        "avg_engagement_rate": analysis.get("engagement_rate", 0),
        "best_hours_kst": analysis.get("best_hours_kst", []),
        "top_captions": [t["caption"] for t in analysis.get("top3", [])],
        "follower_growth": analysis.get("account_growth", {}),
        "best_categories": analysis.get("category_performance", [])[:3],
        "best_formats": analysis.get("format_performance", [])[:3],
    }


def main():
    ap = argparse.ArgumentParser(description="인사이트 주간 분석")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", action="store_true", help="JSON 힌트만 stdout")
    args = ap.parse_args()

    rows = load_rows(args.days)
    result = analyze(rows)
    result["account_growth"] = load_account_growth(args.days)

    if args.json:
        print(json.dumps(build_hints(result), ensure_ascii=False, indent=2))
        return

    # 마크다운 리포트 저장
    report = build_report(result, args.days)
    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"리포트 저장 → {REPORT_PATH}")

    # 성과 힌트 JSON 저장
    hints = build_hints(result)
    with open(HINTS_PATH, "w", encoding="utf-8") as f:
        json.dump(hints, f, ensure_ascii=False, indent=2)
    print(f"힌트 저장 → {HINTS_PATH}")

    # 콘솔에도 출력
    print()
    print(report)


if __name__ == "__main__":
    main()
