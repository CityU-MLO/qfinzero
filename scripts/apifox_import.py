#!/usr/bin/env python3
import json
import requests
from pathlib import Path

APIFOX_BASE_URL = "https://www.apifox.cn/api/v1"
APIFOX_API_VERSION = "2024-03-28"
TOKEN = "afxp_116c0aEW0AQIGCCHeIZ0ZV5UG29N0mFPzH5v"
TEAM_ID = "3671673"

PROJECT_ROOT = Path(__file__).parent.parent
OPENAPI_FILES = {
    "UPQ": PROJECT_ROOT / "docs" / "upq" / "openapi.yaml",
    "NPP": PROJECT_ROOT / "docs" / "npp" / "openapi.yaml", 
    "PMB": PROJECT_ROOT / "docs" / "pmb" / "openapi.yaml",
}

headers = {
    "X-Apifox-Api-Version": APIFOX_API_VERSION,
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

def create_project(name: str, desc: str = "") -> dict:
    url = f"{APIFOX_BASE_URL}/teams/{TEAM_ID}/projects"
    resp = requests.post(url, headers=headers, json={"name": name, "description": desc})
    resp.raise_for_status()
    return resp.json().get("data", {})

def import_openapi(project_id: str, file_path: Path) -> dict:
    url = f"{APIFOX_BASE_URL}/projects/{project_id}/import-openapi"
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    data = {
        "input": content,
        "options": {
            "endpointOverwriteBehavior": "CREATE_NEW",
            "endpointCaseOverwriteBehavior": "CREATE_NEW",
            "updateFolderOfChangedEndpoint": False
        }
    }
    resp = requests.post(url, headers=headers, json=data)
    resp.raise_for_status()
    return resp.json()

def main():
    print("导入 QFinZero API 到 Apifox...")
    
    # 创建项目
    print("\n创建项目...")
    project = create_project("QFinZero", "QFinZero Trading Environment APIs")
    project_id = project.get("id")
    print(f"✅ 项目创建: {project_id}")
    
    # 导入各个服务
    for service, file_path in OPENAPI_FILES.items():
        if not file_path.exists():
            print(f"❌ {service}: 文件不存在")
            continue
        
        print(f"\n导入 {service}...")
        try:
            result = import_openapi(project_id, file_path)
            counters = result.get("data", {}).get("counters", {})
            print(f"✅ {service} 成功")
            print(f"   接口 +{counters.get('endpointCreated', 0)}")
            print(f"   模型 +{counters.get('schemaCreated', 0)}")
        except Exception as e:
            print(f"❌ {service} 失败: {e}")
    
    # 保存项目信息
    with open(PROJECT_ROOT / "scripts" / ".apifox_project", "w") as f:
        json.dump({"team_id": TEAM_ID, "project_id": project_id}, f)
    
    print(f"\n✅ 完成! 项目: {project_id}")
    print("Mock 已自动生成")

if __name__ == "__main__":
    main()
