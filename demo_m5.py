"""M5 Demo: Real end-to-end pipeline run.
Generates a simple Python calculator with tests using real LLM calls."""

import asyncio
import sys
import os

# Load .env manually
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                os.environ[key.strip()] = val.strip()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.orchestrator.orchestrator import Orchestrator
from src.common.llm_client import LLMClient


async def main():
    # Create orchestrator with real model config
    orchestrator = Orchestrator(config={
        "planner": {
            "model": "deepseek-chat",  # Use DeepSeek for planning
        },
        "planner_model": "deepseek-chat",
        "code_agent": {
            "model": "minimax/MiniMax-M2.7",  # MiniMax for code generation
        },
    })

    requirement = (
        "Create a Python calculator module with:\n"
        "- A Calculator class with add, subtract, multiply, divide methods\n"
        "- Proper error handling (division by zero, invalid inputs)\n"
        "- Type hints and docstrings\n"
        "- A corresponding test file with pytest tests covering all methods and edge cases\n"
        "- Output files: calculator.py and tests/test_calculator.py"
    )

    print("=" * 60)
    print("🚀 M5 Pipeline Demo")
    print(f"Planner: DeepSeek V4 Flash  |  Generator: MiniMax M2.7")
    print("=" * 60)
    print(f"\n📋 Requirement:\n{requirement}\n")

    result = await orchestrator.run(requirement)

    print("\n" + "=" * 60)
    print("📊 Pipeline Result")
    print("=" * 60)
    print(f"  Success:         {'✅' if result.success else '❌'}")
    print(f"  Summary:         {result.summary}")
    print(f"  Files:           {len(result.files)}")
    print(f"  Total attempts:  {result.total_attempts}")
    print(f"  Duration:        {result.total_duration:.1f}s")
    print(f"  KB stored:       {'✅' if result.kb_stored else '⏭️'}")
    print()

    for f in result.files:
        status = "✅" if f.success else "❌"
        tested = f" | sandbox={'✅' if f.sandbox_passed else '⏭️' if not f.sandbox_tested else '❌'}" if f.sandbox_tested else ""
        print(f"  {status} {f.path} ({f.language}, {f.lines} lines, {f.attempts} attempt{'s' if f.attempts > 1 else ''}){tested}")
        if f.error:
            print(f"     Error: {f.error}")

    if result.pipeline_test_result is not None:
        tr = result.pipeline_test_result
        print(f"\n  🔬 Pipeline test: {'✅ PASS' if tr.success else '❌ FAIL'}")
        if tr.stdout:
            print(f"     Output:\n{tr.stdout[:500]}")
        if tr.stderr:
            print(f"     Stderr:\n{tr.stderr[:500]}")

    # Show generated files
    print("\n" + "=" * 60)
    print("📄 Generated Files")
    print("=" * 60)
    for f in result.files:
        if f.file_path and os.path.exists(f.file_path):
            with open(f.file_path) as fh:
                content = fh.read()
            print(f"\n--- {f.path} ({len(content.splitlines())} lines) ---")
            # Show first and last 10 lines
            lines = content.splitlines()
            for line in lines[:10]:
                print(f"  {line}")
            if len(lines) > 20:
                print(f"  ... ({len(lines) - 20} more lines) ...")
                for line in lines[-10:]:
                    print(f"  {line}")
            elif len(lines) > 10:
                for line in lines[10:]:
                    print(f"  {line}")

    print("\n" + "=" * 60)
    print("✅ Demo Complete")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
