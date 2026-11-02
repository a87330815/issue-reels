"""Graph API Explorer에서 만든 이미지 컨테이너로 media_publish 테스트."""
import os, requests, time, sys

TOKEN = os.environ["IG_ACCESS_TOKEN"]
IG_ID = os.environ.get("IG_USER_ID", "17841459210979722")
HOST = os.environ.get("IG_API_HOST", "graph.facebook.com")
VERSION = os.environ.get("IG_API_VERSION", "v21.0")
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

def api(method, path, **params):
    url = f"https://{HOST}/{VERSION}/{path}"
    r = getattr(requests, method.lower())(url, headers=HEADERS, params=params if method == "GET" else None,
                                           data=params if method == "POST" else None, timeout=60)
    data = r.json()
    if "error" in data:
        print(f"  에러: {data['error']}")
    return data

# 1) 새 이미지 컨테이너 생성
print("=== 1) 이미지 컨테이너 생성 ===")
create = api("POST", f"{IG_ID}/media",
             image_url="https://picsum.photos/1080/1080",
             caption="자동화 테스트 #test")
print(f"  응답: {create}")

if "id" not in create:
    print("컨테이너 생성 실패")
    sys.exit(1)

cid = create["id"]
print(f"  컨테이너 ID: {cid}")

# 2) 상태 폴링
print("\n=== 2) 컨테이너 상태 확인 ===")
for i in range(12):
    status = api("GET", cid, fields="status_code,status")
    print(f"  [{i}] {status}")
    sc = status.get("status_code")
    if sc == "FINISHED":
        break
    if sc == "ERROR":
        print("컨테이너 에러")
        sys.exit(1)
    time.sleep(5)

# 3) Publish
print("\n=== 3) media_publish 호출 ===")
pub = api("POST", f"{IG_ID}/media_publish", creation_id=cid)
print(f"  응답: {pub}")

if "id" in pub:
    print(f"\n성공! media_id = {pub['id']}")
else:
    print(f"\n실패: {pub}")
    sys.exit(1)
