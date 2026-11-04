# -*- coding: utf-8 -*-
"""
publish.py — 인스타그램 릴스 발행


흐름 (Instagram Content Publishing API):
  1. 컨테이너 생성  POST /{ig_id}/media  media_type=REELS + video_url
  2. 처리 대기      GET /{container_id}?fields=status_code  → FINISHED 까지
  3. 발행           POST /{ig_id}/media_publish  creation_id=...
  4. 지표 수집      GET /{media_id}/insights


중요한 전제 (프로젝트 기준):
  - 프로페셔널(비즈니스·크리에이터) 계정 필수. 개인 계정은 API 발행 불가
  - 영상은 **공개 URL**에 먼저 올라가 있어야 한다. 인스타가 그 주소에서 가져간다
  - 24시간 이동 기준 발행 제한이 있다. 실제 한도는 content_publishing_limit로 조회한다
  - 예약 시각은 UTC. 한국시간 11시 = 02:00 UTC. 이전 시 최다 발생 사고


환경변수:
  IG_USER_ID        인스타그램 비즈니스 계정 ID
  IG_ACCESS_TOKEN   장기 액세스 토큰
  IG_API_HOST       graph.instagram.com (기본) 또는 graph.facebook.com
  IG_API_VERSION    v26.0 (기본)


사용:
  python publish.py --check                    # 계정·토큰·한도 점검
  python publish.py --manifest out/uploaded.json
  python publish.py --video URL --caption "..."
  python publish.py --dry-run --manifest ...   # 발행 직전까지만
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone


ROOT = os.path.dirname(os.path.abspath(__file__))
