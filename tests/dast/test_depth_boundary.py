import asyncio

import pytest

from conftest import FakeMessage, FakeNavigator, inline_markup, make_crawler


@pytest.mark.parametrize("mode", ["graph", "legacy"])
def test_crawl_stops_at_configured_depth(cfg, state, tmp_path, mode):
    cfg.max_depth = 1
    cfg.navigation_mode = mode
    messages = [FakeMessage(1, f"Screen {i}", reply_markup=(
        inline_markup([[(f"Open step {i + 1}", f"step_{i + 1}".encode())]])
        if i < 4 else None
    )) for i in range(5)]
    nav = FakeNavigator(messages[0], {
        f"step_{i + 1}".encode(): {"kind": "edit", "msg": messages[i + 1]}
        for i in range(4)
    })
    crawler, writer = make_crawler(cfg, state, nav, tmp_path=tmp_path)
    try:
        assert asyncio.run(crawler.run()) == "done"
        assert nav.presses == [b"step_1"]
        assert max(s["depth_min"] for s in state.screens_all("@fake_bot")) == 1
    finally:
        writer.close()
