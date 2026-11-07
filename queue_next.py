# -*- coding: utf-8 -*-
import argparse, glob, json, os, sys
from collections import Counter
ROOT=os.path.dirname(os.path.abspath(__file__))
SCRIPTS=os.path.join(ROOT,'out','scripts')
PUBLISHED=os.path.join(ROOT,'out','published.json')
ALLOWED_CATEGORIES={'연예','국내 정치','해외 정치','경제','해외연예'}
CATEGORY_ALIAS={'정치':'국내 정치','정치·시사':'국내 정치','시사':'국내 정치','세계경제':'해외 정치','글로벌경제':'해외 정치','국제경제':'해외 정치','해외경제':'해외 정치','물가':'경제','경제·돈':'경제','연예·화제':'연예','엔터테인먼트':'연예'}
BLOCKED_KEYWORDS={'생활꿀팁','꿀팁','일반 정보','아파트','부동산','실거래','분양','청약','주거'}
TARGET_RATIO={c:20 for c in ALLOWED_CATEGORIES}

def normalize_category(cat): return CATEGORY_ALIAS.get((cat or '').strip(),(cat or '').strip())
def load_script(stem):
    try:
        with open(os.path.join(SCRIPTS,stem+'.json'),encoding='utf-8') as f: return json.load(f)
    except Exception: return {}
def meta(stem): return normalize_category(load_script(stem).get('meta',{}).get('category'))
def blocked(stem):
    d=load_script(stem)
    text=json.dumps(d,ensure_ascii=False)
    return any(k in text for k in BLOCKED_KEYWORDS)
def records():
    try:
        with open(PUBLISHED,encoding='utf-8') as f: return json.load(f).get('items',[]) or []
    except Exception: return []
def done():
    out=set()
    for x in records():
        n=x.get('name') or x.get('script') or ''
        out.add(os.path.splitext(os.path.basename(str(n)))[0])
    return out
def queue():
    d=done(); out=[]
    for p in sorted(glob.glob(os.path.join(SCRIPTS,'*.json')),reverse=True):
        s=os.path.splitext(os.path.basename(p))[0]
        if s in d or s.startswith(('test_','sample_')): continue
        if meta(s) in ALLOWED_CATEGORIES and not blocked(s): out.append(s)
    return out
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--list',action='store_true'); a=ap.parse_args(); q=queue()
    if a.list:
        print(f'대기 {len(q)}건:')
        for s in q: print(f'  {s} [{meta(s)}]')
        return
    if not q: sys.stderr.write('대기열이 비었습니다 — 허용 주제 대본이 없습니다\n'); raise SystemExit(1)
    print(q[0])
if __name__=='__main__': main()
