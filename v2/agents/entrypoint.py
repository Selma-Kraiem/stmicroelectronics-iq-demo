"""Role-selecting entry point for the shared V2 Hosted Agent image."""

from __future__ import annotations

import logging
import os


def main() -> None:
    from agent_framework_foundry_hosting import ResponsesHostServer
    from dotenv import load_dotenv

    load_dotenv(override=False)
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    role = os.getenv("STIQ_V2_AGENT_ROLE", "").strip().lower()
    if role == "market":
        from v2.agents.market import build_market_agent

        agent = build_market_agent()
    elif role == "quality":
        from v2.agents.quality import build_quality_agent

        agent = build_quality_agent()
    elif role == "commander":
        from v2.agents.commander import build_commander_agent

        agent = build_commander_agent()
    else:
        raise RuntimeError(
            "STIQ_V2_AGENT_ROLE must be one of: market, quality, commander."
        )

    logging.getLogger("st_iq_v2").info(
        "Starting role=%s protocol=responses/2.0.0",
        role,
    )
    ResponsesHostServer(agent).run()


if __name__ == "__main__":
    main()
