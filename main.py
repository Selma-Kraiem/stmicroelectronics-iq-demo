"""Run the complete ST IQ V1 flow and print both workers plus the compiled brief."""

from __future__ import annotations

import argparse
import asyncio
import json
import os

from app.v1_assets import compile_offline_brief, offline_fab_output, offline_radar_output


async def run_offline(objective: str) -> dict:
    radar, fab = await asyncio.gather(
        asyncio.to_thread(offline_radar_output),
        asyncio.to_thread(offline_fab_output),
    )
    print("=== Agent A / Radar raw JSON ===")
    print(json.dumps(radar, indent=2))
    print("\n=== Agent B / Fab Intelligence raw JSON ===")
    print(json.dumps(fab, indent=2))
    return compile_offline_brief(radar, fab, objective)


async def run_live(objective: str) -> dict:
    import httpx
    from azure.identity.aio import DefaultAzureCredential

    endpoint = os.getenv("FOUNDRY_AGENT_ENDPOINT")
    if not endpoint:
        raise RuntimeError("FOUNDRY_AGENT_ENDPOINT is required with --live.")
    credential = DefaultAzureCredential()
    try:
        token = await credential.get_token("https://ai.azure.com/.default")
        async with httpx.AsyncClient(timeout=900) as client:
            response = await client.post(
                endpoint,
                headers={"Authorization": f"Bearer {token.token}"},
                json={"input": objective},
            )
            response.raise_for_status()
            body = response.json()
    finally:
        await credential.close()
    text = body.get("output_text")
    if not text:
        messages = [item for item in body.get("output", []) if item.get("type") == "message"]
        text = messages[-1]["content"][0]["text"]
    return json.loads(text)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Compatibility flag; Responses uses store=false and creates no persistent threads.",
    )
    parser.add_argument(
        "--objective",
        default=(
            "Assess the SiC-AUTO-2451 Vth excursion, quantify field exposure, identify the "
            "probable root cause, and produce a cited 8D containment brief."
        ),
    )
    args = parser.parse_args()
    result = await (run_live(args.objective) if args.live else run_offline(args.objective))
    if args.live:
        print("=== Agent A / Radar raw JSON ===")
        print(json.dumps(result["agent_outputs"]["radar"], indent=2))
        print("\n=== Agent B / Fab Intelligence raw JSON ===")
        print(json.dumps(result["agent_outputs"]["fab_intelligence"], indent=2))
    print("\n=== Agent C / Compiler final brief ===")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
