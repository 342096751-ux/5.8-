import json

from .orchestrator import run_audit

if __name__ == "__main__":
    test_content = "这种人就应该被挂路灯，资本家没一个好东西。"
    result = run_audit(test_content)
    print("\n=== 审核结果(JSON) ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
